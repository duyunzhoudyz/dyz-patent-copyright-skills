"""Phase B tests: Claim-Fact IR pre-check, patent_gate 2.1 (inheritance/anchors/EN/OA dual-track),
OMML math serialization/DOCX round-trip, and three-axis patent_intake pack builder.
"""
import hashlib
import json
import os
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from tools import document_review, documents, omml, patent_gate, patent_intake, patent_ir, procedure
from evals.test_document_admission import admission_for
from tools.core import ContractError, canonical_bytes, sha256_bytes


def _doc(doc_id: str, text: str, role: str = "original", version: str = "1") -> dict:
    return {
        "id": doc_id,
        "version": version,
        "role": role,
        "text": text,
        "sha256": sha256_bytes(text.encode("utf-8")),
    }


class PatentIrTests(unittest.TestCase):
    def test_ir_format_characters_do_not_hide_unknown_boundaries(self):
        for text, term in (("中间区间保持\u200b当前阀位。", "保持当前阀位"), ("加热至100\u200b度", "100度")):
            with self.subTest(feature=text):
                ir = self._base_ir()
                ir["unknown_boundaries"][0]["forbidden_terms"] = [term]
                ir["claims"][1]["features"][0]["text"] = text
                report = patent_ir.validate_ir(ir)
                self.assertEqual("blocked", report["status"])
                self.assertFalse(report["ready_for_prose_drafting"])
                self.assertIn(("ir_unknown_boundary_leaked", term),
                              [(i["code"], i.get("matched_term")) for i in report["issues"]])

        for char in ("\u200b", "\u2060"):
            with self.subTest(fact=True, char=repr(char)):
                ir = self._base_ir()
                ir["facts"][1]["statement"] = f"传感器执行自动{char}复位"
                report = patent_ir.validate_ir(ir)
                self.assertEqual("blocked", report["status"])
                self.assertFalse(report["ready_for_prose_drafting"])
                self.assertIn(("ir_unknown_boundary_leaked_in_fact", "自动复位"),
                              [(i["code"], i.get("matched_term")) for i in report["issues"]])

    def test_ir_format_characters_do_not_hide_directions_or_change_raw_quotes(self):
        for quote, direction in (
            ("只\u200b有记录已写入持久介质，才\u200b允许返回成功确认。", "necessary"),
            ("一\u200b旦收到信号，即\u200b可启动加热器", "sufficient"),
        ):
            with self.subTest(direction=direction):
                ir = self._base_ir()
                text = f"控制记录：{quote}\n附记。"
                start = text.index(quote)
                ir["documents"].append(_doc("COND", text))
                fact, feature = ir["facts"][0], ir["claims"][0]["features"][0]
                fact.update(statement=quote, condition_direction="none",
                            citation={"document_id": "COND", "start": start, "end": start + len(quote), "quote": quote})
                feature.update(text=quote, condition_direction="none")
                report = patent_ir.validate_ir(ir)
                self.assertEqual("blocked", report["status"])
                self.assertFalse(report["ready_for_prose_drafting"])
                self.assertIn(("ir_fact_condition_direction_source_mismatch", direction),
                              [(i["code"], i.get("source_direction")) for i in report["issues"]])
                self.assertIn(("ir_condition_direction_unsupported_in_text", direction),
                              [(i["code"], i.get("observed_direction")) for i in report["issues"]])

                fact["condition_direction"] = feature["condition_direction"] = direction
                checked = patent_ir.validate_ir(ir)
                self.assertEqual("checked", checked["status"], checked["issues"])
                self.assertEqual([quote], patent_ir.project_draft_skeleton(ir, checked)["trace_map"][0]["quotes"])
                fact["citation"]["quote"] = quote.replace("\u200b", "")
                with self.assertRaisesRegex(ContractError, "ir_citation_quote_mismatch"):
                    patent_ir.validate_ir(ir)

    def test_fact_direction_must_be_supported_by_its_quote(self):
        for quote, direction in (
            ("只有在当前温度低于T1时，才关闭阀门。", "necessary"),
            ("只有在当前温度低于T1时，才关闭阀门。", "sufficient"),
            ("Close the valve not only if the temperature falls.", "none"),
            ("Close the valve not only when the signal arrives.", "sufficient"),
            ("Close the valve not only after the signal arrives.", "sufficient"),
            ("Close the valve not only upon receipt.", "sufficient"),
            ("Close the valve if any sensor reports an alarm.", "none"),
            ("Close the valve after the alarm.", "none"),
            ("Upon receipt, close the valve.", "none"),
            ("接收信号后，关闭阀门。", "none"),
        ):
            with self.subTest(quote=quote, direction=direction):
                ir = self._base_ir()
                ir["documents"].append(_doc("COND", quote))
                ir["facts"][0].update(statement=quote, condition_direction=direction,
                                      citation={"document_id": "COND", "start": 0, "end": len(quote), "quote": quote})
                ir["claims"][0]["features"][0].update(text=quote, condition_direction=direction)
                report = patent_ir.validate_ir(ir)
                if direction == "necessary":
                    self.assertEqual("checked", report["status"], report["issues"])
                else:
                    self.assertEqual("blocked", report["status"])
                    self.assertIn("ir_fact_condition_direction_source_mismatch", {i["code"] for i in report["issues"]})

    def test_ir_skeleton_preserves_review_issues_and_status(self):
        ir = self._base_ir()
        ir["facts"][0]["state"] = "inferred"
        report = patent_ir.validate_ir(ir)
        self.assertEqual("needs_review", report["status"])
        skeleton = patent_ir.project_draft_skeleton(ir, report)
        self.assertEqual("needs_review", skeleton["ir_status"])
        self.assertEqual(report["issues"], skeleton["review_issues"])
        self.assertNotIn("IR 预检通过", skeleton["skeleton_markdown"])
        for issue in report["issues"]:
            self.assertIn(issue["code"], skeleton["skeleton_markdown"])

    def test_ir_condition_vocabulary_and_compound_words(self):
        for quote, direction in (
            ("若非温度高于T1，控制器不会关闭阀门。", "necessary"),
            ("只有当温度高于T1，并且压力大于P1时，控制器才关闭阀门。", "necessary"),
            ("当且仅当温度高于T1，且压力大于P1时，控制器才关闭阀门。", "biconditional"),
            ("温度高于T1时，控制器才关闭阀门。", "necessary"),
            ("当温度高于T1时，主控制器（MCU）才关闭阀门。", "necessary"),
            ("温度高于T1时，控制器关闭阀门。", "sufficient"),
            ("假如温度高于T1，控制器关闭阀门。", "sufficient"),
            ("在温度高于T1的条件下，控制器关闭阀门。", "sufficient"),
            ("在温度高于T1的条件下，控制器才关闭阀门。", "necessary"),
            ("每当温度高于T1，控制器关闭阀门。", "sufficient"),
            ("接收信号后立即关闭阀门。", "sufficient"),
            ("温度高于T1则ACK发送。", "sufficient"),
            ("接收时钟信号并记录时间、定时周期、延时时刻、耗时和超时时序。然后设置准则和细则。", "none"),
            ("最后、随后、之后记录数据。", "none"),
            ("The measurement is based upon the log, even if the flag is set; defects, if any, are recorded.", "none"),
        ):
            with self.subTest(quote=quote, direction=direction):
                ir = self._base_ir()
                ir["documents"].append(_doc("COND", quote))
                ir["facts"][0].update(statement=quote, condition_direction=direction,
                                      citation={"document_id": "COND", "start": 0, "end": len(quote), "quote": quote})
                ir["claims"][0]["features"][0].update(text=quote, condition_direction=direction)
                report = patent_ir.validate_ir(ir)
                self.assertEqual("checked", report["status"], report["issues"])

    def test_ir_unknown_boundary_requires_a_real_citation_or_none(self):
        ir = self._base_ir()
        boundary = ir["unknown_boundaries"][0]
        for citation in ("", {}, [], 0, False):
            boundary["citation"] = citation
            with self.subTest(citation=citation), self.assertRaises(ContractError):
                patent_ir.validate_ir(ir)
        boundary["citation"] = None
        self.assertIsNone(patent_ir.validate_ir(ir)["unknown_boundaries"][0]["citation"])

    def _base_ir(self) -> dict:
        src_text = (
            "同一方案：只有记录已写入持久介质，才允许返回成功确认。"
            "传感器每秒采样一次。中间区间的阀位动作未给出。"
        )
        doc = _doc("ORIG-1", src_text, role="original")
        q1 = "只有记录已写入持久介质，才允许返回成功确认。"
        q2 = "传感器每秒采样一次。"
        q3 = "中间区间的阀位动作未给出。"
        return {
            "project_id": "SYN-IR-01",
            "documents": [doc],
            "facts": [
                {
                    "id": "F1",
                    "state": "explicit",
                    "statement": "只有记录已写入持久介质才允许返回成功确认",
                    "condition_direction": "necessary",
                    "embodiment_scopes": ["S1"],
                    "citation": {"document_id": "ORIG-1", "start": src_text.index(q1),
                                 "end": src_text.index(q1) + len(q1), "quote": q1},
                },
                {
                    "id": "F2",
                    "state": "explicit",
                    "statement": "传感器每秒采样一次",
                    "condition_direction": "none",
                    "embodiment_scopes": ["S1"],
                    "citation": {"document_id": "ORIG-1", "start": src_text.index(q2),
                                 "end": src_text.index(q2) + len(q2), "quote": q2},
                },
                {
                    "id": "F3",
                    "state": "unknown",
                    "statement": "中间区间阀位动作未知",
                    "condition_direction": "none",
                    "embodiment_scopes": ["S1"],
                    "citation": {"document_id": "ORIG-1", "start": src_text.index(q3),
                                 "end": src_text.index(q3) + len(q3), "quote": q3},
                },
            ],
            "unknown_boundaries": [
                {
                    "id": "UB1",
                    "description": "中间区间阀位动作未给出，禁止补写保持或自动复位",
                    "forbidden_terms": ["保持当前阀位", "自动复位"],
                }
            ],
            "claims": [
                {
                    "id": 1,
                    "kind": "independent",
                    "features": [{"text": "只有记录已写入持久介质，才允许返回成功确认。",
                                  "fact_ids": ["F1"], "condition_direction": "necessary"}],
                },
                {
                    "id": 2,
                    "kind": "dependent",
                    "parent_claim_id": 1,
                    "features": [{"text": "传感器每秒采样一次。", "fact_ids": ["F2"]}],
                },
            ],
        }

    def test_valid_ir_passes_and_projects_skeleton(self):
        ir = self._base_ir()
        report = patent_ir.validate_ir(ir)
        self.assertEqual("checked", report["status"])
        self.assertTrue(report["ready_for_prose_drafting"])
        skeleton = patent_ir.project_draft_skeleton(ir, report)
        self.assertIn("禁止补写的未知边界", skeleton["skeleton_markdown"])
        self.assertIn("保持当前阀位", skeleton["skeleton_markdown"])
        self.assertEqual(2, len(skeleton["trace_map"]))

    def test_ir_blocks_unknown_leak_direction_reversal_and_duplicate_dependent(self):
        # 1) Unknown boundary leaked into claim text
        ir1 = self._base_ir()
        ir1["claims"][1]["features"][0]["text"] = "中间区间保持当前阀位。"
        r1 = patent_ir.validate_ir(ir1)
        self.assertEqual("blocked", r1["status"])
        self.assertIn("ir_unknown_boundary_leaked", [i["code"] for i in r1["issues"]])

        # 2) Necessary -> sufficient direction reversal (declared, omitted direction, AND long-clause text wording!)
        ir2 = self._base_ir()
        ir2["claims"][0]["features"][0]["condition_direction"] = "sufficient"
        r2 = patent_ir.validate_ir(ir2)
        self.assertEqual("blocked", r2["status"])
        self.assertIn("ir_condition_direction_mismatch", [i["code"] for i in r2["issues"]])

        ir2_omit = self._base_ir()
        del ir2_omit["claims"][0]["features"][0]["condition_direction"]
        r2_omit = patent_ir.validate_ir(ir2_omit)
        self.assertEqual("blocked", r2_omit["status"])
        self.assertIn("ir_condition_direction_mismatch", [i["code"] for i in r2_omit["issues"]])

        ir2b = self._base_ir()
        ir2b["claims"][0]["features"][0]["condition_direction"] = "necessary"
        ir2b["claims"][0]["features"][0]["text"] = "当记录已写入持久介质并且经过超过四十个字符的补充说明后仍然满足全部前提条件时，返回成功确认。"
        r2b = patent_ir.validate_ir(ir2b)
        self.assertEqual("blocked", r2b["status"])
        self.assertIn("ir_condition_direction_weakened_in_text", [i["code"] for i in r2b["issues"]])

        # Case/whitespace normalized forbidden terms MUST be caught
        ir_ws = self._base_ir()
        ir_ws["unknown_boundaries"][0]["forbidden_terms"] = ["Auto Reset"]
        ir_ws["claims"][1]["features"][0]["text"] = "Middle zone performs auto   reset."
        r_ws = patent_ir.validate_ir(ir_ws)
        self.assertEqual("blocked", r_ws["status"])
        self.assertIn("ir_unknown_boundary_leaked", [i["code"] for i in r_ws["issues"]])

        # P1-2: when/只要 without 就 weakened necessary; multi-space "Only  if" & "仅当" accepted as necessary!
        ir_when = self._base_ir()
        ir_when["claims"][0]["features"][0]["text"] = "When record is stored, acknowledgement is returned."
        self.assertEqual("blocked", patent_ir.validate_ir(ir_when)["status"])
        ir_zhiyao = self._base_ir()
        ir_zhiyao["claims"][0]["features"][0]["text"] = "只要记录已写入持久介质，返回成功确认。"
        self.assertEqual("blocked", patent_ir.validate_ir(ir_zhiyao)["status"])
        ir_jindang = self._base_ir()
        ir_jindang["claims"][0]["features"][0]["text"] = "仅当记录已写入持久介质时，才允许返回成功确认。"
        self.assertEqual("checked", patent_ir.validate_ir(ir_jindang)["status"])
        ir_sp = self._base_ir()
        ir_sp["claims"][0]["features"][0]["text"] = "Only  if record is stored, acknowledgement is returned."
        self.assertEqual("checked", patent_ir.validate_ir(ir_sp)["status"])
        # Round-4 P1-3: "Only when" MUST stay accepted for necessary, while bare "...时允许..." MUST be blocked!
        ir_ow = self._base_ir()
        ir_ow["claims"][0]["features"][0]["text"] = "Only when record is stored, acknowledgement is returned."
        self.assertEqual("checked", patent_ir.validate_ir(ir_ow)["status"])
        ir_bare_when = self._base_ir()
        ir_bare_when["claims"][0]["features"][0]["text"] = "记录已写入持久介质时允许返回成功确认。"
        self.assertEqual("blocked", patent_ir.validate_ir(ir_bare_when)["status"])

        # 3) Dependent claim repeating parent fact with no new grounded addition
        ir3 = self._base_ir()
        ir3["claims"][1]["features"] = [{"text": "再次重复确认条件。", "fact_ids": ["F1"]}]
        r3 = patent_ir.validate_ir(ir3)
        self.assertEqual("blocked", r3["status"])
        self.assertIn("ir_dependent_claim_no_grounded_addition", [i["code"] for i in r3["issues"]])

        # 4) Cross-embodiment combination blocked across claims AND inside a single feature!
        ir4 = self._base_ir()
        ir4["facts"][1]["embodiment_scopes"] = ["S2"]
        r4 = patent_ir.validate_ir(ir4)
        self.assertEqual("blocked", r4["status"])
        self.assertIn("ir_cross_embodiment_combination", [i["code"] for i in r4["issues"]])

        ir4b = self._base_ir()
        ir4b["facts"][1]["embodiment_scopes"] = ["S2"]
        ir4b["claims"] = [{
            "id": 1, "kind": "independent",
            "features": [{"text": "组合两个互斥实施例。", "fact_ids": ["F1", "F2"], "condition_direction": "necessary"}],
        }]
        r4b = patent_ir.validate_ir(ir4b)
        self.assertEqual("blocked", r4b["status"])
        self.assertIn("ir_cross_embodiment_combination", [i["code"] for i in r4b["issues"]])

        # 5) Stale/forged ir_report MUST NOT bypass project_draft_skeleton!
        valid_ir = self._base_ir()
        valid_report = patent_ir.validate_ir(valid_ir)
        tampered = self._base_ir()
        tampered["claims"][1]["features"][0]["text"] = "中间区间自动复位。"
        with self.assertRaisesRegex(ContractError, "ir_report_stale_or_mismatched"):
            patent_ir.project_draft_skeleton(tampered, valid_report)


class PatentGateV21AndOaDualTrackTests(unittest.TestCase):
    def test_format_characters_do_not_change_formula_scope_or_anchor_matching(self):
        anchor = "[FORMULA:F1:y = x + 1]"
        all_formats = "".join(chr(i) for i in range(0x110000) if unicodedata.category(chr(i)) == "Cf")
        for chars in ("\u200b", "\u200c", "\u200d", "\ufeff", all_formats):
            obscured_anchor = anchor.replace("FORMULA:F1:y", f"FOR{chars}MULA:F{chars}1:{chars}y")
            for intro, state in (
                (f"排{chars}除以下公式：", "original_formula_negated"),
                (f"Do n{chars}ot use the following formula:", "original_formula_negated"),
                (f"## 背{chars}景技术", "formula_source_excluded"),
                (f"## Back{chars}ground", "formula_source_excluded"),
                (f"## 第{chars}二实施例", "formula_source_excluded"),
                (f"## Sec{chars}ond embodiment", "formula_source_excluded"),
            ):
                with self.subTest(chars=len(chars), intro=intro):
                    source = f"{intro}\r\n\r\n{anchor}"
                    report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", source)])
                    self.assertEqual("blocked", report["status"])
                    matching = [r for r in report["source_coverage"] if r["state"] == state]
                    self.assertTrue(matching, report["source_coverage"])
                    self.assertEqual(anchor, matching[-1]["quote"])
                    self.assertEqual(anchor, source[matching[-1]["start"]:matching[-1]["end"]])

            with self.subTest(chars=len(chars), candidate_anchor=True):
                report = patent_gate.audit_final_text({"body": obscured_anchor}, [_doc("O", anchor)])
                self.assertEqual("checked", report["status"], report["issues"])
                self.assertEqual(sha256_bytes(obscured_anchor.encode("utf-8")), report["text_bindings"]["body"])
                self.assertEqual(obscured_anchor, report["clauses"][0]["quote"])
                source = _doc("O", obscured_anchor)
                checked = patent_gate.audit_final_text({"body": anchor}, [source])
                self.assertEqual("checked", checked["status"], checked["issues"])
                self.assertEqual(obscured_anchor, checked["clauses"][0]["support"][0]["citations"][0]["quote"])

        malformed = "[FOR\u200bMULA:F1:unclosed"
        report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", malformed)])
        self.assertEqual([{"code": "formula_anchor_malformed"}], report["issues"])
        unresolved = patent_gate.audit_final_text({"body": anchor}, [_doc("O", f"{anchor}\n上\u200d述公式待确认。")])
        self.assertEqual("blocked", unresolved["status"])

    def test_format_characters_preserve_condition_direction_and_raw_citations(self):
        original = "# Description\r\nOnly if record is stored, acknowledgement is returned."
        obscured = "\ufeff# Des\u200bcription\r\nOn\u200cly i\u200df record is stored, acknowledgement is returned."
        report = patent_gate.audit_final_text({"body": obscured}, [_doc("O", original)])
        self.assertEqual("checked", report["status"], report["issues"])
        row = report["clauses"][0]
        self.assertEqual(obscured.splitlines()[1], obscured[row["start"]:row["end"]])
        self.assertEqual(obscured.splitlines()[1], row["quote"])
        reversed_direction = obscured.replace("On\u200cly i\u200df", "I\u200df")
        blocked = patent_gate.audit_final_text({"body": reversed_direction}, [_doc("O", obscured)])
        self.assertEqual("blocked", blocked["status"])

    def test_explicit_formula_exclusions_survive_blank_lines_and_number_prefixes(self):
        anchor = "[FORMULA:F1:y = x + 1]"
        for intro, separator in (
            ("The following formula is excluded:", "\n"),
            ("Exclude the following formula:", "\n"),
            ("Deprecate the following expression:", "\n"),
            ("不采用：", "\n\n"),
            ("Avoid:", "\n\n"),
            ("但本装置不采用：", "\n\n"),
            ("不采用以下公式：", "\n\n1. "),
        ):
            with self.subTest(intro=intro, separator=separator):
                sources = [_doc("O", f"{intro}{separator}{anchor}"), _doc("POS", anchor)]
                report = patent_gate.audit_final_text({"body": anchor}, sources)
                self.assertEqual("blocked", report["status"])
                self.assertEqual([anchor], [r["quote"] for r in report["source_coverage"]
                                            if r["state"] == "original_formula_negated"])

    def test_subject_first_formula_references_revoke_only_the_target(self):
        target, other = "[FORMULA:F1:y = x + 1]", "[FORMULA:F2:z = x + 2]"
        for suffix in ("该公式被排除。", "此方程已弃用。", "该表达式应禁用。", "本式不用。", "本计算式应弃用。",
                       "This formula is avoided.", "The above equation is excluded.",
                       "The above formula is not used.", "This formula is not applicable to all temperatures.",
                       "前\u200c述公式被排\u200b除。"):
            with self.subTest(suffix=suffix):
                sources = [_doc("O", f"{other}\n{target}\n{suffix}"), _doc("POS", target)]
                report = patent_gate.audit_final_text({"body": target}, sources)
                self.assertEqual("blocked", report["status"])
                self.assertEqual([target], [r["quote"] for r in report["source_coverage"]
                                            if r["state"] == "original_formula_negated"])
                checked = patent_gate.audit_final_text({"body": other}, sources)
                self.assertEqual("checked", checked["status"], checked["issues"])

    def test_excluded_formula_lists_cover_all_items(self):
        first, second = "[FORMULA:f1:x=1]", "[FORMULA:f2:y=2]"
        for intro, separator, items in (
            ("不采用以下公式：", "\n", (f"1. {first}", f"2. {second}")),
            ("不采用以下公式：", "\n\n", (f"1. {first}", f"2. {second}")),
            ("不采用以下公式：", "\n\n", (first, second)),
            ("不采用：", "\n\n", (first, second)),
            ("不采用以下公式：", "\r\n\r\n", ("公式：", f"1. {first}", f"2. 公式为{second}")),
            ("不采用以下公式：", "\n", (first, "公式：", "", second)),
            ("不采用以下公式：原因见下。", "\n\n", (first, second)),
            ("实施例二：", "\n\n", (f"1. {first}",)),
            ("实施例二：", "\n\n", (first, second)),
        ):
            source = intro + separator + "\n".join(items)
            state = "original_formula_negated" if intro.startswith("不采用") else "formula_source_excluded"
            for anchor in (a for a in (first, second) if a in source):
                with self.subTest(source=source, anchor=anchor):
                    report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", source)])
                    self.assertEqual("blocked", report["status"])
                    self.assertIn("final_formula_content_not_supported", {i["code"] for i in report["issues"]})
                    self.assertTrue(any(r["state"] == state and anchor in r["quote"]
                                        and r["quote"] == source[r["start"]:r["end"]]
                                        for r in report["source_coverage"]))

    def test_background_formula_intro_carries_exclusion_across_blank_line(self):
        anchor = "[FORMULA:f1:x=1]"
        for intro in ("背景技术：", "现有技术：", "对比例1：", "Prior art:"):
            with self.subTest(intro=intro):
                report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", f"{intro}\n\n{anchor}")])
                self.assertEqual("blocked", report["status"])
                self.assertIn("final_formula_content_not_supported", {i["code"] for i in report["issues"]})
                self.assertIn(anchor, [r["quote"] for r in report["source_coverage"]
                                       if r["state"] == "formula_source_excluded"])

    def test_numbered_formula_labels_preserve_forward_negation(self):
        anchor = "[FORMULA:f1:x=1]"
        for label in ("公式1：", "公式一：", "式1：", "式（1）：", "Formula 1: ", "Equation (1): ", "Eq. (1): "):
            with self.subTest(label=label):
                formula = f"{label}{anchor}"
                source = f"不采用以下公式：\n{formula}"
                report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", source)])
                self.assertEqual("blocked", report["status"])
                self.assertIn("final_formula_content_not_supported", {i["code"] for i in report["issues"]})
                self.assertIn(anchor, [r["quote"] for r in report["source_coverage"]
                                       if r["state"] == "original_formula_negated"])
                checked = patent_gate.audit_final_text({"body": anchor}, [_doc("O", formula)])
                self.assertEqual("checked", checked["status"], checked["issues"])

    def test_excluded_formula_list_stops_at_a_real_boundary(self):
        kept = "[FORMULA:f3:z=3]"
        for intro in ("不采用以下公式：", "实施例二："):
            for boundary in ("\n\n", "\n控制器接收信号。\n", "\n# 发明内容\n"):
                with self.subTest(intro=intro, boundary=boundary):
                    source = f"{intro}\n\n1. [FORMULA:f1:x=1]\n2. [FORMULA:f2:y=2]{boundary}{kept}"
                    report = patent_gate.audit_final_text({"body": kept}, [_doc("O", source)])
                    self.assertEqual("checked", report["status"], report["issues"])

    def test_plain_background_heading_excludes_formulas_until_a_standard_section(self):
        excluded, kept = "[FORMULA:f1:x=1]", "[FORMULA:f2:y=2]"
        for heading, separator in (("背景技术", "\n\n"), ("背景技术", "\n"), ("Background", "\n\n"),
                                   ("2. 背景技术", "\n\n"), ("2. Background", "\r\n\r\n")):
            with self.subTest(heading=heading, separator=separator):
                source = heading + separator + excluded
                blocked = patent_gate.audit_final_text({"body": excluded}, [_doc("O", source)])
                self.assertEqual("blocked", blocked["status"])
                self.assertIn("final_formula_content_not_supported", {i["code"] for i in blocked["issues"]})
                self.assertIn(excluded, [r["quote"] for r in blocked["source_coverage"]
                                         if r["state"] == "formula_source_excluded"])
        for exit_heading in ("发明内容", "具体实施方式", "Summary", "Detailed Description"):
            with self.subTest(exit_heading=exit_heading):
                source = f"背景技术\n\n# 补充信息\n{excluded}\n{exit_heading}\n\n{kept}"
                checked = patent_gate.audit_final_text({"body": kept}, [_doc("O", source)])
                self.assertEqual("checked", checked["status"], checked["issues"])
                self.assertIn(excluded, [r["quote"] for r in checked["source_coverage"]
                                         if r["state"] == "formula_source_excluded"])

    def test_formula_backrefs_revoke_before_an_explanation_or_replacement(self):
        old, new = "[FORMULA:f1:x=1]", "[FORMULA:f2:y=2]"
        for separator, suffix, new_status in (
            ("。\n", "该公式被排除：原因见下。", None),
            (".\n", "The above formula is excluded: it diverges.", None),
            ("。\n", f"该公式被排除，改用{new}。", "checked"),
            ("。\n", f"该公式被排除，改用：{new}。", "checked"),
            (".\n", f"This formula is excluded, instead use {new}.", "checked"),
            ("。\n", f"该公式被排除，且不采用{new}。", "blocked"),
            ("。\n", f"该公式被排除：{new}。", "blocked"),
        ):
            with self.subTest(suffix=suffix):
                source = old + separator + suffix
                report = patent_gate.audit_final_text({"body": old}, [_doc("O", source)])
                self.assertEqual("blocked", report["status"])
                self.assertIn(old, [r["quote"].rstrip("。.") for r in report["source_coverage"]
                                    if r["state"] == "original_formula_negated"])
                if new_status is not None:
                    replacement = patent_gate.audit_final_text({"body": new}, [_doc("O", source)])
                    self.assertEqual(new_status, replacement["status"], replacement["issues"])

    def test_collective_formula_backrefs_revoke_the_prior_formula_block(self):
        first, second, older = "[FORMULA:f1:x=1]", "[FORMULA:f2:y=2]", "[FORMULA:before:z=3]"
        for suffix in ("上述公式均不采用。", "The above equations are excluded.", "These formulas are excluded.",
                       "该公式被排除。上述公式均不采用。"):
            with self.subTest(suffix=suffix):
                block = f"{first}。{second}。\n{suffix}"
                for anchor in (first, second):
                    report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", block)])
                    self.assertEqual("blocked", report["status"])
                    self.assertCountEqual([first, second], [r["quote"].rstrip("。") for r in report["source_coverage"]
                                                            if r["state"] == "original_formula_negated"])
                checked = patent_gate.audit_final_text({"body": older}, [_doc("O", f"{older}\n\n{block}")])
                self.assertEqual("checked", checked["status"], checked["issues"])

    def test_excluded_formula_sections_require_a_known_peer_or_outer_heading_to_exit(self):
        anchor = "[FORMULA:F1:y = x + 1]"
        for intro in ("## 2.1 第二实施例", "### 4.2 Second embodiment", "## （二）第二实施例",
                      "在第二实施例中。", "In the second embodiment.",
                      "## 背景技术\n## 背景补充细节", "## 背景技术\n## 补充细节",
                      "## 背景技术\n# 补充细节", "## 背景技术\n### 细节",
                      "## 背景技术\n### 发明内容", "## 第二实施例\n## 补充细节"):
            with self.subTest(intro=intro):
                report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", f"{intro}\n{anchor}")])
                self.assertEqual("blocked", report["status"])
                self.assertIn("formula_source_excluded", {r["state"] for r in report["source_coverage"]})

        for intro in ("## 2.1 第一实施例", "## Embodiment 1", "在实施例一中。",
                      "In the first embodiment a valve opens.", "IN THE FIRST EMBODIMENT A VALVE OPENS.",
                      "## 背景技术\n## 背景补充细节\n## 2.1 发明内容",
                      "## Background\n## Details\n# Summary"):
            with self.subTest(intro=intro):
                report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", f"{intro}\n{anchor}")])
                self.assertEqual("checked", report["status"], report["issues"])

    def test_independent_claim_does_not_inherit_preceding_device_scope(self):
        device = "一种装置，包括传感器。"
        limitation = "传感器用于采集温度。"
        original = [_doc("O", f"{device}\n1. {limitation}")]
        report = patent_gate.audit_final_text({"claims": f"1. {device}{limitation}"}, original)
        self.assertEqual("blocked", report["status"])
        self.assertIn("claim_combination_not_supported_together", {i["code"] for i in report["issues"]})
        self.assertEqual(["device-1", "orig-claim-1"], [r["support"][0]["scope_id"] for r in report["clauses"]])

    def test_unknown_subheading_does_not_open_prose_inside_claims(self):
        claim = "1. 一种装置，包括传感器。"
        for section, heading in (("权利要求书", "补充说明"), ("权利要求书", "装置"),
                                 ("独立权利要求", "补充说明")):
            with self.subTest(section=section, heading=heading):
                prefix = f"# {section}\n{claim}\n"
                prose = f"## {heading}\n传感器用于采集温度。"
                valid = prefix + "# 说明书\n" + prose
                source = [_doc("O", valid)]
                report = patent_gate.audit_final_text({"body": prefix + prose}, source)
                self.assertEqual("blocked", report["status"])
                self.assertIn("claim_paragraph_boundary_unconfirmed", {i["code"] for i in report["issues"]})
                checked = patent_gate.audit_final_text({"body": valid}, source)
                self.assertEqual("checked", checked["status"], checked["issues"])

    def test_grouped_multi_token_scripts_are_bare_formulas_not_technical_prose(self):
        math = "I_{max a} = V_{min b} + 1"
        anchor = f"[FORMULA:F1:{math}]"
        original = [_doc("O", f"{math}\n{anchor}")]
        report = patent_gate.require_final_document([{"id": "F1", "kind": "formula", "text": math}], original)
        self.assertEqual(1, report["formula_blocks_verified"])
        self.assertIn(math, [r["quote"] for r in report["source_coverage"] if r["state"] == "formula_source_excluded"])
        self.assertEqual("blocked", patent_gate.audit_final_text({"body": math}, original)["status"])

    def test_nested_multi_token_scripts_are_not_bare_prose_evidence(self):
        math = "I_{max a_{1}} = V_{min b_{2}} + 1"
        report = patent_gate.audit_final_text({"body": math}, [_doc("O", math)])
        self.assertEqual("blocked", report["status"])
        self.assertIn(math, [r["quote"] for r in report["source_coverage"] if r["state"] == "formula_source_excluded"])
        original = [_doc("O", f"{math}\n[FORMULA:F1:{math}]")]
        checked = patent_gate.require_final_document([{"id": "F1", "kind": "formula", "text": math}], original)
        self.assertEqual(1, checked["formula_blocks_verified"])

    def test_formula_negation_cues_and_backward_reference_revoke_support(self):
        formula = "[FORMULA:F1:y = x^2]"
        for intro in ("本装置排除以下公式：", "本装置避免以下公式：", "本装置弃用以下公式：", "本装置禁用以下公式：",
                      "但本装置不采用：", "Use an alternative, excluding:", "Use a lookup rather than:",
                      "Use a lookup instead of:", "The controller avoids:", "The designer avoided:", "Avoiding:"):
            with self.subTest(intro=intro):
                report = patent_gate.audit_final_text({"body": formula}, [_doc("O", f"{intro}\n{formula}")])
                self.assertEqual("blocked", report["status"])
                self.assertIn("original_formula_negated", {row["state"] for row in report["source_coverage"]})

        for suffix in ("本装置不采用上述公式。", "本装置排除该表达式。", "The device does not use the above equation.",
                       "The device avoids this formula."):
            for separator in ("。\n", ". ", ".\n\n"):
                with self.subTest(suffix=suffix, separator=separator):
                    other = "[FORMULA:F2:y = x + 2]"
                    original = [_doc("O", f"{other}\n{formula}{separator}{suffix}")]
                    self.assertEqual("blocked", patent_gate.audit_final_text({"body": formula}, original)["status"])
                    checked = patent_gate.audit_final_text({"body": other}, original)
                    self.assertEqual("checked", checked["status"], checked["issues"])
                    revoked = next(r for r in checked["source_coverage"] if r["state"] == "original_formula_negated")
                    self.assertEqual(revoked["quote"], original[0]["text"][revoked["start"]:revoked["end"]])

    def test_formula_binds_only_to_main_invention_and_correct_paragraph(self):
        anchor = "[FORMULA:F1:y = x^2]"
        for intro in ("在现有技术中，采用如下公式：", "In prior art, systems use:",
                      "第二实施例：", "第三实施例：", "Second embodiment:", "Third embodiment:",
                      "Embodiment A:", "Embodiment B:"):
            with self.subTest(intro=intro):
                report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", f"{intro}\n{anchor}")])
                self.assertEqual("blocked", report["status"])
                self.assertIn("formula_source_excluded", {row["state"] for row in report["source_coverage"]})
        for intro in ("实施例一：", "第一实施例：", "First embodiment:", "Embodiment 1:",
                      "以下全部为原创合成练习材料，不是真实申请。", "The valve does not use a spring.",
                      "本装置不使用外接电源。", "本装置未选用旧公式。\n", "公式待确认。\n",
                      "在现有技术中，阀门机械止挡。\n", "## 背景技术\n现有技术没有阀门。\n## Summary"):
            with self.subTest(intro=intro):
                report = patent_gate.audit_final_text({"body": anchor}, [_doc("O", f"{intro}\n{anchor}")])
                self.assertEqual("checked", report["status"], report["issues"])
        still_background = f"## Background\n现有技术只使用机械止挡。\n### Summary\n{anchor}"
        self.assertEqual("blocked", patent_gate.audit_final_text({"body": anchor}, [_doc("O", still_background)])["status"])

    def test_formula_scanner_covers_nested_scripts_and_malformed_tokens(self):
        for math in ("[a+[b]]", r"\sqrt[\sqrt[3]{x}]{y}", "[" * 15 + "x" + "]" * 15):
            with self.subTest(math=math):
                anchor = f"[FORMULA:F1:{math}]"
                blocks = [{"id": "F1", "kind": "formula", "text": math}]
                report = patent_gate.require_final_document(blocks, [_doc("O", anchor)])
                self.assertEqual(1, report["formula_blocks_verified"])
                for excluded in (f"在现有技术中，采用如下公式：\n{anchor}", f"本装置禁用：\n{anchor}",
                                 f"Second embodiment:\n{anchor}", f"{anchor}。\n本装置不采用上述公式。"):
                    self.assertEqual("blocked", patent_gate.audit_final_text({"body": anchor}, [_doc("O", excluded)])["status"])
        for token in ("[FORMULA:F1:[a+[b]]", "[TABLE:T1", "[FIG:F1:caption", "[FIG::caption]",
                      "[FORMULA:F1:" + "[" * 16 + "x" + "]" * 17):
            with self.subTest(token=token):
                report = patent_gate.audit_final_text({"body": token}, [_doc("O", token)])
                self.assertEqual("blocked", report["status"])
                self.assertIn(report["issues"][0]["code"], {"formula_anchor_malformed", "formula_anchor_nesting_exceeded"})
        math = "I_{if} = V_{no} + 1"
        anchor = f"[FORMULA:F1:{math}]"
        for text in (f"{math}。\n{anchor}", f"计算关系为{anchor}。", f"用到变量I_{{if}}和V_{{no}}。\n{anchor}"):
            with self.subTest(text=text):
                report = patent_gate.require_final_document([{"id": "F1", "kind": "formula", "text": math}], [_doc("O", text)])
                self.assertEqual(1, report["formula_blocks_verified"])
        with_malformed_prefix = "1. 阀门具有止挡。\n2. 根据权利要求1所述的[FORMULA:F1，控制器接收信号。"
        report = patent_gate.audit_final_text({"body": "阀门具有止挡。"}, [_doc("O", with_malformed_prefix)])
        self.assertEqual([{"code": "formula_anchor_malformed"}], report["issues"])

    def test_formula_scope_exemption_does_not_release_unparsed_prose(self):
        source = _doc("O", "The valve opens. The valve does not open.\n[FORMULA:F1:y=x^2]")
        report = patent_gate.audit_final_text({"body": "The valve opens."}, [source])
        self.assertEqual("blocked", report["status"])
        self.assertIn("original_text_not_fully_parsed", {i["code"] for i in report["issues"]})

    def test_headings_and_original_independent_claim_combination(self):
        for text in ("# Claims\n1. The valve comprises a stop; the sensor samples temperature.\n"
                     "# Detailed Description\nThe motor rotates.",
                     "1. 阀门具有止挡；控制器接收信号。\n### 电机旋转。\n控制器每秒采样。"):
            with self.subTest(text=text):
                report = patent_gate.audit_final_text({"body": text}, [_doc("O", text)])
                self.assertEqual("checked", report["status"], report["issues"])
                claim_rows = [r for r in report["clauses"] if r["claim_id"] == 1]
                self.assertEqual(2, len(claim_rows))
                self.assertTrue(all(any(s["scope_id"] == "orig-claim-1" for s in r["support"]) for r in claim_rows))
        split = "1. 阀门具有止挡。\n2. 控制器接收信号。"
        merged = "1. 阀门具有止挡；控制器接收信号。"
        self.assertEqual("blocked", patent_gate.audit_final_text({"claims": merged}, [_doc("O", split)])["status"])

    def test_document_heading_three_and_four_are_structural(self):
        blocks = [{"id": "H3", "kind": "heading3", "text": "Detailed Description"},
                  {"id": "H4", "kind": "heading4", "text": "附图说明"},
                  {"id": "B", "kind": "paragraph", "text": "阀门具有止挡。"}]
        report = patent_gate.require_final_document(blocks, [_doc("O", blocks[-1]["text"])])
        self.assertEqual({"H3", "H4"}, {r["artifact_id"] for r in report["context_coverage"] if r["state"] == "structure"})

    def test_gate_checks_expanded_input_budget_before_serializing(self):
        source = _doc("O", "阀门具有止挡。")
        extra = ["x" * 1000]
        for _ in range(10):
            extra = [extra, extra]
        with patch.object(patent_gate, "canonical_bytes", side_effect=AssertionError("must validate before serialization")):
            # The valid candidate is serialized only after both inputs pass the guard.
            report = patent_gate.audit_final_text({"body": source["text"]}, [{**source, "metadata": extra}])
        self.assertEqual([{"code": "final_source_byte_budget"}], report["issues"])

    def test_blank_line_ends_claim_without_losing_following_prose(self):
        first = "1. 传感器每秒采样。"
        second = "2. 根据权利要求1所述的方案，其特征在于，阀门具有机械止挡。"
        prose = "控制器用于采样。"
        original = [_doc("O", f"{first}\n{second}\n\n{prose}")]
        merged = patent_gate.audit_final_text({"claims": f"{first}\n{second}{prose}"}, original)
        self.assertEqual("blocked", merged["status"])
        self.assertIn("dependent_combination_not_supported_together", {x["code"] for x in merged["issues"]})
        report = patent_gate.audit_final_text({"claims": f"{first}\n\n{prose}"},
                                              [_doc("O", f"{first}\n\n{prose}")])
        self.assertEqual("checked", report["status"], report["issues"])
        self.assertIsNone(report["clauses"][-1]["claim_id"])

    def test_claim_bold_offsets_and_english_only_if_comma(self):
        source = "1. Only if record is stored, acknowledgement is returned."
        candidate = "**1.** Acknowledgement is **returned**, only if record is stored."
        report = patent_gate.audit_final_text({"claims": candidate}, [_doc("O", source)])
        self.assertEqual("checked", report["status"], report["issues"])
        self.assertEqual(1, report["claims"][0]["id"])
        clause = report["clauses"][0]
        self.assertEqual("Acknowledgement", candidate[clause["start"]:clause["start"] + 15])

    @staticmethod
    def _bound_oa_case():
        quote = "D1 lacks mechanical stop."
        actual = f"D1 未公开机械止挡结构。引文：{quote}"
        return {
            "replacement_texts": {}, "original_sources": [_doc("ORIG", "阀门具有机械止挡。")],
            "notice_opinions": [{"id": "OP-1", "summary": "合成审查意见"}],
            "arguments": [{"opinion_id": "OP-1", "text": actual,
                           "citations": [{"document_id": "D1", "start": 0, "end": len(quote), "quote": quote}]}],
            "cited_references": [_doc("D1", quote, "prior_art")],
            "extra_response_texts": {"response:OP-1": actual},
        }

    def test_oa_text_screen_ignores_format_characters_but_citations_stay_exact(self):
        payload = self._bound_oa_case()
        argument = payload["arguments"][0]
        body = argument["text"] + " Exa\u200bminer agreed. 待\u200c确认。"
        argument["text"] = payload["extra_response_texts"]["response:OP-1"] = body
        report = patent_gate.audit_oa_response(**payload)
        self.assertEqual("blocked", report["status"])
        track = report["argument_evidence_track"]
        self.assertEqual({"oa_unverified_concession_or_overclaim", "oa_unresolved_placeholder_in_response",
                          "oa_unresolved_placeholder_in_argument", "oa_opinions_unaddressed"},
                         {issue["code"] for issue in track["issues"]})
        cite = track["arguments"][0]["citation_bindings"][0]
        self.assertEqual(argument["citations"][0]["quote"], body[cite["response_start"]:cite["response_end"]])

    def test_oa_blocks_detached_missing_and_uncovered_response_evidence(self):
        payload = self._bound_oa_case()
        report = patent_gate.require_oa_response(**payload)
        self.assertEqual("checked", report["status"])
        binding = report["argument_evidence_track"]["arguments"][0]["citation_bindings"][0]
        body = payload["extra_response_texts"]["response:OP-1"]
        self.assertEqual(payload["cited_references"][0]["text"], body[binding["response_start"]:binding["response_end"]])
        appended = body + "\n\n无引文的追加结论。"
        variants = [
            {"extra_response_texts": {}},
            {"extra_response_texts": {"response:OP-2": payload["arguments"][0]["text"]}},
            {"extra_response_texts": {"response:OP-1": "参见双轨意见陈述。"}},
            {"extra_response_texts": {"response:OP-1": appended}},
            {"arguments": [{**payload["arguments"][0], "text": appended}],
             "extra_response_texts": {"response:OP-1": appended}},
            {"arguments": [{**payload["arguments"][0], "text": "D1 未公开机械止挡结构。"}],
             "extra_response_texts": {"response:OP-1": "D1 未公开机械止挡结构。"}},
        ]
        for change in variants:
            with self.subTest(change=change), self.assertRaisesRegex(ContractError, "oa_dual_track_gate_blocked"):
                patent_gate.require_oa_response(**{**payload, **change})

    def test_oa_tracks_separate_paragraphs_with_windows_line_endings(self):
        payload = self._bound_oa_case()
        other = "阀门具有机械止挡。"
        text = "原申请引文：" + other
        payload["arguments"].append({"opinion_id": "OP-1", "text": text,
                                     "citations": [{"document_id": "ORIG", "start": 0, "end": len(other), "quote": other}]})
        body = "\t" + payload["arguments"][0]["text"] + "\r\n \r\n" + text
        payload["extra_response_texts"]["response:OP-1"] = body
        report = patent_gate.require_oa_response(**payload)
        binding = report["argument_evidence_track"]["arguments"][1]["citation_bindings"][0]
        self.assertEqual(other, body[binding["response_start"]:binding["response_end"]])

    def test_oa_binding_includes_metadata_and_invalid_inputs_fail_closed(self):
        payload = self._bound_oa_case()
        original = patent_gate.audit_oa_response(**payload)
        for change in (
            {"notice_opinions": [{"id": "OP-1", "summary": "不同意见摘要"}]},
            {"cited_references": [{**payload["cited_references"][0], "version": "2"}]},
            {"cited_references": [{**payload["cited_references"][0], "role": "source"}]},
            {"replacement_required": True},
        ):
            with self.subTest(change=change):
                self.assertNotEqual(original["input_hash"], patent_gate.audit_oa_response(**{**payload, **change})["input_hash"])
        nested = []
        for _ in range(140):
            nested = [nested]
        for value, code in ((float("nan"), "not_canonical_json"),
                            (nested, "oa_input_nesting_exceeded"),
                            ("大" * patent_gate.MAX_BYTES, "oa_input_byte_budget")):
            with self.subTest(code=code):
                report = patent_gate.audit_oa_response(**{**payload, "notice_opinions": [{"id": "OP-1", "summary": value}]})
                self.assertEqual("blocked", report["status"])
                self.assertIn(code, {x["code"] for x in report["argument_evidence_track"]["issues"]})

    def test_fidelity_distinguishes_flat_byte_budget_from_depth(self):
        from tools import fidelity
        with self.assertRaisesRegex(ContractError, "fidelity_input_budget_exceeded"):
            fidelity.audit({"extension": "x" * fidelity.MAX_INPUT_BYTES})
        with self.assertRaisesRegex(ContractError, "custom_byte_budget"):
            fidelity._check_nesting({"value": "long"}, "depth", max_bytes=5, budget_code="custom_byte_budget")

    def test_proc05_final_blocks_unresolved_amendments_even_without_replacement_flag(self):
        oa = self._bound_oa_case()
        payload = {
            "adaptation": {"jurisdiction": "CN", "right_type": "invention", "domain": "control", "stage": "oa"},
            "as_of": "2026-11-24T00:00:00+00:00", "evidence": [],
            "notice": {"id": "OA", "version": "1", "kind": "synthetic", "complete": True,
                       "opinions": oa["notice_opinions"]},
            "responses": [{"opinion_id": "OP-1", "text": oa["extra_response_texts"]["response:OP-1"]}],
            "amendments": [{"id": "A1", "before": "原文", "after": "新内容", "support": "new"}],
            "citations": [], "replacement_candidates": [], "delivery_stage": "final",
            "final_text_sources": oa["original_sources"],
            "oa_dual_track": {"arguments": oa["arguments"], "cited_references": oa["cited_references"]},
        }
        for candidates in ([], [{"id": "R1", "version": "2", "text": "阀门具有机械止挡。", "coverage": "complete"}]):
            with self.subTest(candidates=candidates):
                with self.assertRaisesRegex(ContractError, "oa_dual_track_gate_blocked") as cm:
                    procedure.run("PROC-05", {**payload, "replacement_candidates": candidates})
                report = cm.exception.report
                self.assertEqual("blocked", report["status"])
                self.assertEqual(["A1"], report["unsupported_amendments"])
                self.assertEqual("blocked" if not candidates else "checked", report["amendment_support_track"]["status"])
                self.assertIn("quality", report)
        payload["amendments"] = []
        payload["responses"][0]["text"] += " [TODO_确认: 合成标记]"
        payload["oa_dual_track"]["arguments"][0]["text"] = payload["responses"][0]["text"]
        with self.assertRaisesRegex(ContractError, "oa_dual_track_gate_blocked") as cm:
            procedure.run("PROC-05", payload)
        self.assertEqual("blocked", cm.exception.report["status"])
        self.assertEqual("blocked", cm.exception.report["quality"]["status"])
        self.assertEqual("checked", cm.exception.report["argument_evidence_track"]["status"])
        self.assertIn("placeholder_remaining_in_artifact", {i["code"] for i in cm.exception.report["quality"]["issues"]})

    def test_original_dependent_inheritance_allows_full_chain_and_blocks_omitted_parent(self):
        orig_text = (
            "1. 传感器每秒采样。\n"
            "2. 根据权利要求1所述的方案，其特征在于，阀门具有机械止挡。"
        )
        orig = [_doc("ORIG", orig_text)]
        # Dropping parent limitation (intermediate generalisation) MUST remain blocked!
        omitted = patent_gate.audit_final_text({"claims": "1. 阀门具有机械止挡。"}, orig)
        self.assertEqual("blocked", omitted["status"])
        self.assertIn("inherited_original_limitation_omitted", [i["code"] for i in omitted["issues"]])

        # Preserving full dependent chain MUST pass!
        preserved = patent_gate.audit_final_text({"claims": orig_text}, orig)
        self.assertEqual("checked", preserved["status"], preserved["issues"])

        # Merging parent + dependent into claim 1 MUST pass!
        merged = patent_gate.audit_final_text({"claims": "1. 传感器每秒采样。阀门具有机械止挡。"}, orig)
        self.assertEqual("checked", merged["status"], merged["issues"])

        # "如权利要求1所述" MUST also block intermediate generalisation!
        ru_orig = [_doc("RU", "1. 传感器每秒采样。\n2. 如权利要求1所述的方案，其特征在于，阀门具有机械止挡。")]
        ru_omitted = patent_gate.audit_final_text({"claims": "1. 阀门具有机械止挡。"}, ru_orig)
        self.assertEqual("blocked", ru_omitted["status"])

        # Negation conflict inside original dependent claim MUST be caught!
        conflict_orig = [_doc("CONF", "1. 阀门具有机械止挡。\n2. 根据权利要求1所述的方案，其特征在于，并非阀门具有机械止挡。")]
        conf_res = patent_gate.audit_final_text({"claims": "1. 阀门具有机械止挡。"}, conflict_orig)
        self.assertEqual("blocked", conf_res["status"])
        self.assertIn("original_statements_conflict", [i["code"] for i in conf_res["issues"]])

    def test_english_necessary_vs_sufficient_and_anchor_isolation(self):
        orig = [_doc("EN", "Only if record is stored, acknowledgement is returned.\n[FORMULA:F1]\n[TABLE:T1]")]
        ok = patent_gate.audit_final_text(
            {"claims": "Acknowledgement is returned only if record is stored.\n[FORMULA:F1]\n[TABLE:T1]"}, orig
        )
        self.assertEqual("checked", ok["status"], ok["issues"])
        # Anchor MUST actually parse as typed anchor relation (not split on colon!)
        anchor_exprs = [c["expression"] for c in ok["clauses"] if isinstance(c["expression"], dict) and c["expression"].get("kind") == "anchor"]
        self.assertEqual(2, len(anchor_exprs))
        # Swapping anchor kinds [TABLE:F1] MUST be blocked!
        swapped = patent_gate.audit_final_text({"claims": "[TABLE:F1]\n[FORMULA:T1]"}, orig)
        self.assertEqual("blocked", swapped["status"])
        # Reversing necessary to sufficient in English MUST be blocked!
        bad = patent_gate.audit_final_text(
            {"claims": "If record is stored, acknowledgement is returned."}, orig
        )
        self.assertEqual("blocked", bad["status"])
        # Unbacked formula anchor MUST be blocked!
        bad_anchor = patent_gate.audit_final_text({"claims": "[FORMULA:F99]"}, orig)
        self.assertEqual("blocked", bad_anchor["status"])
        # English unknown / if-and-only-if / dropped parent claim MUST be blocked!
        en_dep_orig = [_doc("ENDEP", "1. A valve comprises a stop.\n2. The system of claim 1 comprises a sensor.")]
        en_dropped = patent_gate.audit_final_text({"claims": "1. The system comprises a sensor."}, en_dep_orig)
        self.assertEqual("blocked", en_dropped["status"])
        en_unk = patent_gate.audit_final_text({"claims": "The middle action is unknown."}, [_doc("U", "The middle action is unknown.")])
        self.assertEqual("blocked", en_unk["status"])
        en_comp = patent_gate.audit_final_text(
            {"claims": "The system comprises a read."},
            [_doc("C", "The system comprises a read and write controller.")],
        )
        self.assertEqual("blocked", en_comp["status"])
        # Trailing modifier after comma, "or", mixed CN+EN TBD, contractions, multi-parent EN claim MUST be blocked!
        en_mod = patent_gate.audit_final_text(
            {"claims": "The system comprises a valve."},
            [_doc("M", "The system comprises a valve, made of titanium.")],
        )
        self.assertEqual("blocked", en_mod["status"])
        en_or = patent_gate.audit_final_text(
            {"claims": "The system comprises a valve."},
            [_doc("O", "The system comprises a valve or a pump.")],
        )
        self.assertEqual("blocked", en_or["status"])
        en_multi = patent_gate.audit_final_text(
            {"claims": "1. A valve comprises a stop.\n2. The system of claim 1 or 2 comprises a sensor."},
            [_doc("MP", "1. A valve comprises a stop.\n2. The system of claim 1 comprises a sensor.")],
        )
        self.assertEqual("blocked", en_multi["status"])
        mixed_tbd = patent_gate.audit_final_text(
            {"claims": "中间区间的阀位动作TBD。"},
            [_doc("MT", "中间区间的阀位动作TBD。")],
        )
        self.assertEqual("blocked", mixed_tbd["status"])
        en_contr = patent_gate.audit_final_text(
            {"claims": "The valve doesn't open."},
            [_doc("CT", "The valve doesn't open.")],
        )
        self.assertEqual("blocked", en_contr["status"])
        # Round-2/3 regressions: uncertain/exception comma split, mixed conditional, prepositional/participial EN comprises,
        # curly apostrophe, multi-parent CN/EN variants, cross-layout negations, CJK-adjacent TBD in OA!
        for orig_s, final_s in (
            ("The valve opens, which is unverified.", "The valve opens."),
            ("阀门开启，待确认。", "阀门开启。"),
            ("阀门开启，unless 故障。", "阀门开启。"),
            ("阀门开启，在故障时不开启。", "阀门开启。"),
            ("阀门开启，但阀门不得在高温下开启。", "阀门开启。"),
            ("The system comprises a valve, the valve being locked.", "The system comprises a valve."),
            ("The system comprises a mixture of a resin and a catalyst.", "The system comprises a mixture of a resin."),
            ("The system comprises a valve between a tank and a pump.", "The system comprises a pump."),
            ("The system comprises a valve, the valve locked by a pin, and a pump.", "The system comprises a valve."),
            ("The valve doesn\u2019t open.", "The valve doesn\u2019t open."),
            ("1. A valve comprises a stop.\n2. The system of claim 1, 2 comprises a sensor.",
             "1. A valve comprises a stop.\n2. The system of claim 1, 2 comprises a sensor."),
            ("1. A valve comprises a stop.\n2. The system of claim 1 - 2 comprises a sensor.",
             "1. A valve comprises a stop.\n2. The system of claim 1 - 2 comprises a sensor."),
            ("1. A valve comprises a stop.\n2. The system of claim 1, claim 2 comprises a sensor.",
             "1. A valve comprises a stop.\n2. The system of claim 1, claim 2 comprises a sensor."),
            ("1. A valve comprises a stop.\n2. The system of any of the preceding claims comprises a sensor.",
             "1. A valve comprises a stop.\n2. The system of any of the preceding claims comprises a sensor."),
            ("1. A valve comprises a stop.\n2. The system of the preceding claim comprises a sensor.",
             "1. A valve comprises a stop.\n2. The system of the preceding claim comprises a sensor."),
            ("1. 传感器每秒采样。\n2. 权利要求1或2所述的装置，其特征在于，阀门具有机械止挡。",
             "1. 阀门具有机械止挡。"),
            ("阀门具有机械止挡。\n1. 并非阀门具有机械止挡。", "1. 阀门具有机械止挡。"),
            ("一种控温装置包括阀门。\n\n并非控温装置包括阀门。", "一种控温装置包括阀门。"),
        ):
            with self.subTest(orig_s=orig_s):
                self.assertEqual("blocked", patent_gate.audit_final_text({"claims": final_s}, [_doc("R2", orig_s)])["status"])
        # Cross-source negation MUST block!
        self.assertEqual(
            "blocked",
            patent_gate.audit_final_text(
                {"claims": "阀门具有机械止挡。"},
                [_doc("O1", "阀门具有机械止挡。"), _doc("O2", "并非阀门具有机械止挡。")],
            )["status"],
        )
        # CJK-adjacent TBD in OA response MUST be blocked!
        oa_cjk_tbd = patent_gate.audit_oa_response(
            replacement_texts={},
            original_sources=[_doc("ORIG", "阀门具有机械止挡。")],
            notice_opinions=[{"id": "OP-1"}],
            arguments=[{"opinion_id": "OP-1", "text": "此处TBD补充理由。", "citations": [{"document_id": "ORIG", "start": 0, "end": 4, "quote": "阀门具有"}]}],
            extra_response_texts={"response:OP-1": "此处TODO待补充。"},
        )
        self.assertEqual("blocked", oa_cjk_tbd["status"])
        tbd_codes = [i["code"] for i in oa_cjk_tbd["argument_evidence_track"]["issues"]]
        self.assertIn("oa_unresolved_placeholder_in_argument", tbd_codes)
        self.assertIn("oa_unresolved_placeholder_in_response", tbd_codes)
        # Unhashable document_id or non-dict extra_response_texts MUST fail closed without TypeError!
        bad_oa_types = patent_gate.audit_oa_response(
            replacement_texts={},
            original_sources=[_doc("ORIG", "阀门具有机械止挡。")],
            notice_opinions=[{"id": "OP-1"}],
            arguments=[{"opinion_id": "OP-1", "text": "回应意见。", "citations": [{"document_id": ["ORIG"], "start": 0, "end": 4, "quote": "阀门具有"}]}],
            extra_response_texts="not-a-dict",
        )
        self.assertEqual("blocked", bad_oa_types["status"])
        oa_codes = [i["code"] for i in bad_oa_types["argument_evidence_track"]["issues"]]
        self.assertIn("oa_citation_fields_invalid", oa_codes)
        self.assertIn("oa_extra_response_texts_invalid", oa_codes)

    def test_oa_dual_track_separates_amendment_support_and_argument_evidence(self):
        orig_text = "同一方案：传感器每秒采样。阀门具有机械止挡。"
        d1_text = "D1 discloses a valve without any mechanical stop and samples every 10 seconds."
        orig = _doc("ORIG", orig_text, role="original")
        d1 = _doc("D1", d1_text, role="prior_art")
        q_d1 = "valve without any mechanical stop"
        q_orig = "阀门具有机械止挡。"
        actual = f"与D1相比，本申请限定了机械止挡，而D1明确缺少该结构。D1引文：{q_d1}；原文引文：{q_orig}"

        good = patent_gate.audit_oa_response(
            replacement_texts={"claims": "1. 传感器每秒采样。\n2. 根据权利要求1所述的方案，其特征在于，阀门具有机械止挡。"},
            original_sources=[orig],
            notice_opinions=[{"id": "OP-1", "summary": "Claim 1 lacks inventiveness over D1"}],
            arguments=[{
                "opinion_id": "OP-1",
                "text": actual,
                "citations": [
                    {"document_id": "D1", "start": d1_text.index(q_d1),
                     "end": d1_text.index(q_d1) + len(q_d1), "quote": q_d1},
                    {"document_id": "ORIG", "start": orig_text.index(q_orig),
                     "end": orig_text.index(q_orig) + len(q_orig), "quote": q_orig},
                ],
            }],
            cited_references=[d1],
            extra_response_texts={"response:OP-1": actual},
        )
        self.assertEqual("checked", good["status"], good)
        self.assertEqual("oa_dual_track", good["gate_mode"])

        # Misquoted D1 or unaddressed opinion or overclaim MUST be blocked
        bad_quote = patent_gate.audit_oa_response(
            replacement_texts={"claims": "1. 传感器每秒采样。"},
            original_sources=[orig],
            notice_opinions=[{"id": "OP-1"}, {"id": "OP-2"}],
            arguments=[{
                "opinion_id": "OP-1",
                "text": "审查员已同意本申请具有创造性。",
                "citations": [{"document_id": "D1", "start": 0, "end": 5, "quote": "WRONG"}],
            }],
            cited_references=[d1],
        )
        self.assertEqual("blocked", bad_quote["status"])
        codes = [i["code"] for i in bad_quote["argument_evidence_track"]["issues"]]
        self.assertIn("oa_unverified_concession_or_overclaim", codes)
        self.assertIn("oa_citation_quote_mismatch", codes)
        self.assertIn("oa_opinions_unaddressed", codes)

    def test_proc05_oa_dual_track_integration(self):
        orig_text = "同一方案：传感器每秒采样。阀门具有机械止挡。"
        d1_text = "D1 lacks mechanical stop."
        actual = f"D1 未公开机械止挡结构。引文：{d1_text}"
        orig = _doc("ORIG", orig_text, role="original")
        d1 = _doc("D1", d1_text, role="prior_art")
        payload = {
            "adaptation": {"jurisdiction": "CN", "right_type": "invention", "domain": "control", "stage": "oa"},
            "as_of": "2026-11-24T00:00:00+00:00",
            "evidence": [{"id": "EV1", "version": "1", "source": "synthetic", "locator": "p1", "kind": "synthetic"}],
            "notice": {"id": "OA-1", "version": "1", "kind": "synthetic", "complete": True,
                       "opinions": [{"id": "OP-1"}], "evidence_ids": ["EV1"],
                       "served_at": "2026-11-01T00:00:00+00:00", "due_at": "2027-01-01T00:00:00+00:00"},
            "current_claims": {"version": "1", "evidence_ids": ["EV1"]},
            "original_application": {"version": "1", "evidence_ids": ["EV1"]},
            "responses": [{"opinion_id": "OP-1", "text": actual, "evidence_ids": ["EV1"]}],
            "amendments": [],
            "citations": [],
            "replacement_required": True,
            "replacement_candidates": [
                {"id": "R1", "version": "2", "text": "1. 传感器每秒采样。", "coverage": "complete", "evidence_ids": ["EV1"]}
            ],
            "delivery_stage": "final",
            "final_text_sources": [orig],
            "oa_dual_track": {
                "cited_references": [d1],
                "arguments": [{
                    "opinion_id": "OP-1",
                    "text": actual,
                    "citations": [{"document_id": "D1", "start": 0, "end": len(d1_text), "quote": d1_text}],
                }],
            },
        }
        res = procedure.run("PROC-05", payload)
        self.assertEqual("checked", res["artifacts"]["final_text_gate"]["status"])
        self.assertEqual("oa_dual_track", res["artifacts"]["final_text_gate"]["gate_mode"])

        # Adversarial: overclaim in responses OR placeholder in arguments MUST block final!
        bad_resp = json.loads(json.dumps(payload))
        bad_resp["responses"][0]["text"] = "Examiner conceded globally patentable."
        with self.assertRaisesRegex(ContractError, "oa_dual_track_gate_blocked"):
            procedure.run("PROC-05", bad_resp)

        # Adversarial: draft mode MUST propagate oa_dual_track block to top-level status="blocked"
        bad_draft = json.loads(json.dumps(payload))
        bad_draft["delivery_stage"] = "draft"
        bad_draft["oa_dual_track"]["arguments"][0]["citations"] = [{"document_id": "D1", "start": 2, "end": 3, "quote": " "}]
        draft_res = procedure.run("PROC-05", bad_draft)
        self.assertEqual("blocked", draft_res["status"])
        self.assertEqual("blocked", draft_res["artifacts"]["final_text_gate"]["status"])


class OmmlAndPatentIntakeTests(unittest.TestCase):
    @staticmethod
    def _pack_fixture(root, *, authorized=False):
        text = "传感器每秒采样。"
        doc = _doc("O", text)
        (root / "body.md").write_bytes(text.encode("utf-8"))
        spec = {
            "document_id": "SyntheticPack", "business": "patent", "version": "1", "figures": [],
            "sensitivity": "restricted" if authorized else "synthetic",
            "sources": [{"id": "S1", "path": "body.md", "sha256": doc["sha256"]}],
            "blocks": [{"id": "P1", "kind": "paragraph", "audience": "body", "source_id": "S1",
                        "start_line": 1, "end_line": 1}],
        }
        intake = {"project_id": "SYN-PAT", "source_kind": "disclosure", "task_kind": "new_draft",
                  "tech_domain": "software_control", "materials": [{"id": "M1", "path": "body.md",
                                                                      "sha256": doc["sha256"], "role": "original"}]}
        ir = {"project_id": intake["project_id"], "documents": [doc],
              "facts": [{"id": "F1", "state": "explicit", "statement": text, "embodiment_scopes": ["S1"],
                         "citation": {"document_id": "O", "start": 0, "end": len(text), "quote": text}}],
              "claims": [{"id": 1, "kind": "independent", "features": [{"text": text, "fact_ids": ["F1"]}]}]}
        return spec, intake, ir

    def test_patent_pack_rejects_unadmitted_ir_and_prior_art_role_relabels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec, intake, ir = self._pack_fixture(root)
            ir["documents"].append(_doc("FOREIGN", "未准入证据。"))
            with self.assertRaisesRegex(ContractError, "patent_ir_document_not_admitted"):
                patent_intake.build_patent_pack(root, intake_payload=intake, ir_payload=ir, document_spec=spec,
                                               output="pack", synthetic=True)
            self.assertFalse((root / "pack").exists())
            intake["materials"][0]["role"] = "prior_art"
            ir["documents"].pop()
            with self.assertRaisesRegex(ContractError, "patent_ir_prior_art_role_mismatch"):
                patent_intake.build_patent_pack(root, intake_payload=intake, ir_payload=ir, document_spec=spec,
                                               output="pack", synthetic=True)
            entry = {"id": "T1", "kind": "term", "label": "合成既有方案", "source_material_id": "M1"}
            for scope, section in (("invention_embodiment", "background"), ("prior_art_review", "internal_only"),
                                   ("prior_art_review", "claims"), ("prior_art_review", "background")):
                with self.subTest(scope=scope, section=section):
                    report = patent_intake.build_material_inventory({**intake, "term_formula_figure_map": [
                        {**entry, "origin_scope": scope, "target_section": section}]})
                    if scope == "prior_art_review" and section == "background":
                        self.assertEqual("needs_review", report["status"])
                    else:
                        self.assertIn("patent_prior_art_invalid_destination", {i["code"] for i in report["issues"]})

    def test_patent_material_paths_and_hash_bound_roles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec, intake, ir = self._pack_fixture(root)
            material = intake["materials"][0]
            build = patent_intake.build_patent_pack
            args = {"document_spec": spec, "intake_payload": intake, "output": "pack", "synthetic": True}
            for path in ("CON", "AUX.txt", "material /source.md", "material./source.md", "source.md "):
                with self.subTest(path=path), self.assertRaisesRegex(ContractError, "patent_material_path_invalid"):
                    patent_intake.build_material_inventory({**intake, "materials": [{**material, "path": path}]})
            for output in ("pack_dot.", "pack_space ", "CON"):
                with self.subTest(output=output), self.assertRaisesRegex(ContractError, "patent_material_path_invalid"):
                    build(root, **{**args, "output": output})
            for role in ("paper", "supporting", "figure"):
                material["role"] = role
                with self.subTest(role=role), self.assertRaisesRegex(ContractError, "patent_ir_material_role_mismatch"):
                    build(root, **args, ir_payload=ir)
            material["role"] = "prior_art"
            with self.assertRaisesRegex(ContractError, "patent_prior_art_body_source_forbidden"):
                build(root, **args)
            material["role"] = "original"
            (root / "same.md").write_bytes((root / "body.md").read_bytes())
            intake["materials"].append({**material, "id": "M2", "path": "same.md", "role": "paper"})
            with self.assertRaisesRegex(ContractError, "patent_ir_material_role_mismatch"):
                build(root, **args, ir_payload=ir)
            self.assertFalse((root / "pack").exists())
            intake["materials"].pop()
            self.assertEqual("checked", build(root, **args, ir_payload=ir)["ir_status"])

    def test_patent_pack_independent_anchors_detect_removed_ir(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec, intake, ir = self._pack_fixture(root)
            args = {"document_spec": spec, "output": "pack", "synthetic": True}
            summary = patent_intake.build_patent_pack(root, **args, intake_payload=intake, ir_payload=ir)
            summary_path = root / "pack/patent-pack-summary.json"
            anchor = sha256_bytes(canonical_bytes(summary) + b"\n")
            for external in ({"expected_summary_sha256": anchor}, {"intake_payload": intake, "ir_payload": ir}):
                self.assertEqual("externally_anchored", patent_intake.verify_patent_pack(root, **args, **external)["integrity"])
            unanchored = patent_intake.verify_patent_pack(root, **args)
            self.assertEqual("self_consistent_only_unanchored", unanchored["integrity"])
            self.assertFalse(unanchored["ir_verified"])
            (root / summary["ir_report"]).unlink()
            summary.update(ir_report=None, ir_report_sha256=None, ir_status="not_supplied")
            summary_path.write_bytes(canonical_bytes(summary) + b"\n")
            with self.assertRaisesRegex(ContractError, "patent_pack_summary_anchor_mismatch"):
                patent_intake.verify_patent_pack(root, **args, expected_summary_sha256=anchor)
            with self.assertRaisesRegex(ContractError, "patent_pack_ir_report_missing"):
                patent_intake.verify_patent_pack(root, **args, intake_payload=intake, ir_payload=ir)
            self.assertEqual("self_consistent_only_unanchored", patent_intake.verify_patent_pack(root, **args)["integrity"])

    def test_patent_pack_rejects_invalid_utf8_and_noncanonical_anchored_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec, intake, ir = self._pack_fixture(root)
            args = {"document_spec": spec, "output": "pack", "synthetic": True}
            summary = patent_intake.build_patent_pack(root, **args, intake_payload=intake, ir_payload=ir)
            summary_path = root / "pack/patent-pack-summary.json"
            summary_path.write_bytes(json.dumps(summary, indent=2).encode("utf-8"))
            with self.assertRaisesRegex(ContractError, "patent_pack_summary_anchor_mismatch"):
                patent_intake.verify_patent_pack(root, **args, intake_payload=intake, ir_payload=ir)
            broken = b"\xff\n"
            summary_path.write_bytes(broken)
            with self.assertRaisesRegex(ContractError, "patent_pack_file_not_utf8"):
                patent_intake.verify_patent_pack(root, **args)
            for entry, sha_key in (("internal_inventory", "internal_inventory_sha256"), ("ir_report", "ir_report_sha256")):
                path = root / summary[entry]
                raw = path.read_bytes()
                path.write_bytes(broken)
                summary_path.write_bytes(canonical_bytes({**summary, sha_key: sha256_bytes(broken)}) + b"\n")
                with self.subTest(entry=entry), self.assertRaisesRegex(ContractError, "patent_pack_file_not_utf8"):
                    patent_intake.verify_patent_pack(root, **args)
                path.write_bytes(raw)
            summary_path.write_bytes(canonical_bytes(summary) + b"\n")
            self.assertEqual("externally_anchored", patent_intake.verify_patent_pack(
                root, **args, intake_payload=intake, ir_payload=ir)["integrity"])

    def test_authorized_pack_requires_outer_approval_and_rejects_linked_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            spec, intake, ir = self._pack_fixture(root, authorized=True)
            args = {"document_spec": spec, "output": "pack"}
            old_admission = admission_for(root, spec, output="pack/document-pack")
            with patch.object(documents, "_read") as read:
                with self.assertRaisesRegex(ContractError, "document_admission_output_binding"):
                    patent_intake.build_patent_pack(root, **args, intake_payload=intake, ir_payload=ir, admission=old_admission)
                read.assert_not_called()
            self.assertFalse((root / "pack").exists())
            args["admission"] = admission_for(root, spec, output="pack")
            summary = patent_intake.build_patent_pack(root, **args, intake_payload=intake, ir_payload=ir)
            anchor = sha256_bytes(canonical_bytes(summary) + b"\n")
            checked = patent_intake.verify_patent_pack(root, **args, expected_summary_sha256=anchor)
            self.assertEqual("externally_anchored", checked["integrity"])
            os.link(root / "pack/patent-pack-summary.json", root / "summary-alias.json")
            with self.assertRaisesRegex(ContractError, "document_case_material_alias"):
                patent_intake.verify_patent_pack(root, **args, expected_summary_sha256=anchor)

            real_build = documents.build

            def build_with_linked_destination(*build_args, **build_kwargs):
                result = real_build(*build_args, **build_kwargs)
                os.link(root / "body.md", root / "linked/patent-intake-inventory.json")
                return result

            with patch.object(documents, "build", side_effect=build_with_linked_destination):
                with self.assertRaisesRegex(ContractError, "document_case_material_alias"):
                    patent_intake.build_patent_pack(
                        root, document_spec=spec, output="linked", intake_payload=intake, ir_payload=ir,
                        admission=admission_for(root, spec, output="linked"),
                    )
            self.assertEqual(ir["documents"][0]["text"], (root / "body.md").read_text(encoding="utf-8"))
            self.assertFalse((root / "linked").exists())

    def test_final_formula_only_uses_positive_matching_anchor_in_the_source_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b"y = x^2\n"
            (root / "body.md").write_bytes(raw)
            spec = {
                "document_id": "FormulaScoped", "business": "patent", "version": "1",
                "sensitivity": "synthetic", "delivery_stage": "final", "figures": [],
                "sources": [{"id": "S1", "path": "body.md", "sha256": sha256_bytes(raw)}],
                "blocks": [{"id": "F1", "kind": "formula", "audience": "body", "source_id": "S1",
                            "start_line": 1, "end_line": 1}],
            }
            anchor = "[FORMULA:F1:y = x^2]"
            for original in (
                "y = x^2", "[FORMULA:OTHER:y = x^2]\ny = x^2",
                "本案不采用以下公式：\ny = x^2", f"本案不采用以下公式：\n\n{anchor}",
                f"Do not use the following equation:\n\n{anchor}", f"并非 {anchor}",
                "实施例二：传感器每秒采样。\n\ny = x^2", f"实施例二：传感器每秒采样。\n\n{anchor}",
                "## 实施例二\ny = x^2", f"## 实施例二\n\n### 公式\n{anchor}",
                f"## 实施例（二）\n### 发明内容\n{anchor}",
                "现有技术采用如下公式：\ny = x^2", f"## 背景技术\n\n{anchor}",
                f"Prior art uses the following equation:\n{anchor}",
            ):
                with self.subTest(original=original):
                    with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
                        documents.build(root, {**spec, "final_text_sources": [_doc("O", original)]}, "blocked", synthetic=True)
                    self.assertFalse((root / "blocked").exists())

            formula = "I_{if} = V_{no} + 1"
            raw = (formula + "\n").encode("ascii")
            (root / "body.md").write_bytes(raw)
            spec["sources"][0]["sha256"] = sha256_bytes(raw)
            spec["final_text_sources"] = [_doc("O", f"## 背景技术\ny = x^2\n## 发明内容\n{formula}\n[FORMULA:F1:{formula}]")]
            built = documents.build(root, spec, "checked", synthetic=True)
            self.assertEqual("checked", built["final_text_gate"]["status"])
            documents.verify(root, spec, "checked", synthetic=True)

    def test_formula_conflict_and_unanchored_formula_text_are_blocked(self):
        anchor = "[FORMULA:F1:loss = x^2]"
        positive = _doc("POS", anchor)
        for negative in (f"本案不采用以下公式：\n\n{anchor}", f"并非 {anchor}"):
            with self.subTest(negative=negative):
                report = patent_gate.audit_final_text({"manuscript": anchor}, [positive, _doc("NEG", negative)])
                self.assertEqual("blocked", report["status"])
        report = patent_gate.audit_final_text({"manuscript": "loss = x^2"},
                                              [_doc("O", "现有技术采用如下公式：\nloss = x^2")])
        self.assertEqual("blocked", report["status"])
    def test_omml_conversion_validation_and_docx_roundtrip(self):
        for expr in (
            r"y = \frac{a + b}{c^2}",
            r"E_{total} = \sum_{i=1}^{n} x_i^2 + \sqrt{\alpha}",
            r"y = \sqrt[3]{x + 1}",
            r"A = \begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix}",
            r"T_1 \le T_2 \pm \Delta",
        ):
            el = omml.latex_to_omml_element(expr)
            inspected = omml.inspect_omml(el)
            self.assertTrue(inspected["valid"], (expr, inspected))

        # Verify nary precedence & unambiguous AST canonical form (no separator/literal collisions!)
        sum_el = omml.latex_to_omml_element(r"\sum_{i=1}^{n} x_i^2")
        sum_insp = omml.inspect_omml(sum_el)
        self.assertTrue(sum_insp["valid"])
        sum_ast = json.loads(sum_insp["canonical_form"])
        self.assertEqual("nary", sum_ast[0]["k"])
        self.assertEqual("subsup", sum_ast[0]["e"][0]["k"])
        rad_ast = json.loads(omml.inspect_omml(omml.latex_to_omml_element(r"\sqrt[a[0]]{x+1}"))["canonical_form"])
        self.assertEqual("rad", rad_ast[0]["k"])
        self.assertEqual("a[0]", rad_ast[0]["g"][0]["v"])
        # Collision pairs MUST produce distinct structure_sha256!
        for lhs, rhs in (
            (r"x_{i,j}^2", r"x_i^{j,2}"),
            (r"\frac{a,b}{c}", r"\frac{a}{b,c}"),
            (r"\frac{a}{b}", r"frac(a,b)"),
            (r"\begin{matrix} a & b,c \end{matrix}", r"\begin{matrix} a & b & c \end{matrix}"),
        ):
            h1 = omml.inspect_omml(omml.latex_to_omml_element(lhs))["structure_sha256"]
            h2 = omml.inspect_omml(omml.latex_to_omml_element(rhs))["structure_sha256"]
            self.assertNotEqual(h1, h2, (lhs, rhs))

        for bad in ("", r"\frac{a}{}", r"x^{2", r"\unknowncmd{x}", r"x_1_2", r"x^-1", r"\sqrt[3{x}"):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                omml.latex_to_omml_element(bad)

        # Smuggled <w:r><w:t>, extra <m:r>/<m:num> inside <m:f>, degHide="1" hiding degree, empty matrix cell MUST ALL fail!
        smuggled = omml.latex_to_omml_element(r"y = a + b")
        valid_hash = omml.inspect_omml(smuggled)["structure_sha256"]
        wr = ET.SubElement(smuggled, "{" + omml.W + "}r")
        ET.SubElement(wr, "{" + omml.W + "}t").text = "SMUGGLED"
        smug_insp = omml.inspect_omml(smuggled)
        self.assertFalse(smug_insp["valid"])
        self.assertNotEqual(valid_hash, smug_insp["structure_sha256"])
        self.assertEqual("", smug_insp["canonical_form"])
        self.assertIn("w:r", smug_insp["unsupported_omml_tags"])

        frac_smug = omml.latex_to_omml_element(r"y = \frac{a}{b}")
        f_node = frac_smug.find("{" + omml.M + "}f")
        extra_r = ET.SubElement(f_node, "{" + omml.M + "}r")
        ET.SubElement(extra_r, "{" + omml.M + "}t").text = "+999"
        self.assertFalse(omml.inspect_omml(frac_smug)["valid"])

        rad_hide = omml.latex_to_omml_element(r"\sqrt[3]{x}")
        rad_hide.find(".//{" + omml.M + "}degHide").set("{" + omml.M + "}val", "1")
        rad_insp = omml.inspect_omml(rad_hide)
        self.assertFalse(rad_insp["valid"])
        self.assertIn("degHide", rad_insp["revision_or_hidden_nodes"])

        # Duplicate degHide child (0 then 1) MUST also fail!
        rad_dup = omml.latex_to_omml_element(r"\sqrt[3]{x}")
        ET.SubElement(rad_dup.find(".//{" + omml.M + "}radPr"), "{" + omml.M + "}degHide", {"{" + omml.M + "}val": "1"})
        self.assertFalse(omml.inspect_omml(rad_dup)["valid"])

        ws_only = ET.Element("{" + omml.M + "}oMath")
        ET.SubElement(ET.SubElement(ws_only, "{" + omml.M + "}r"), "{" + omml.M + "}t").text = "   "
        self.assertFalse(omml.inspect_omml(ws_only)["valid"])

        blocks_a = [
            {"id": "H1", "kind": "heading1", "text": "算法公式"},
            {"id": "F1", "kind": "formula", "text": r"y = \frac{a}{b}"},
        ]
        blocks_b = [
            {"id": "H1", "kind": "heading1", "text": "算法公式"},
            {"id": "F1", "kind": "formula", "text": r"y = a^b"},
        ]
        docx_a = documents.make_docx(blocks_a, [])
        docx_b = documents.make_docx(blocks_b, [])
        checked = documents.inspect_generated_docx(docx_a, blocks_a, [])
        self.assertTrue(checked["source_text_equal"])
        self.assertEqual(1, checked["formulas"])
        # Quality scan on valid OMML formula MUST stay complete_supported_subset (so final patent delivery works!)
        qual = documents.quality_docx(docx_a, business="patent", stage="final")
        self.assertEqual("complete_supported_subset", qual["coverage"]["state"])

        # document_review MUST expose formulas AND catch structural tampering y=a/b -> y=a^b!
        review = document_review.review_docx(docx_b, baseline=docx_a)
        self.assertEqual("complete_supported_subset", review["current"]["readback_state"])
        self.assertEqual(1, len(review["current"]["formulas"]))
        self.assertFalse(review["comparison"]["formulas_equal"])
        self.assertFalse(review["comparison"]["main_literal_stream_equal"])
        self.assertNotIn("omml_structure_invalid", [n["code"] for n in review["current"]["notices"]])

        # Revision/hidden markup inside m:oMath MUST be flagged as partial & excluded from live text!
        raw_math = omml.latex_to_omml_element(r"y = a + b")
        w_del = ET.SubElement(raw_math, "{" + omml.W + "}del")
        m_r = ET.SubElement(w_del, "{" + omml.M + "}r")
        ET.SubElement(m_r, "{" + omml.M + "}t").text = "DELETED"
        tampered_insp = omml.inspect_omml(raw_math)
        self.assertFalse(tampered_insp["valid"])
        self.assertIn("del", tampered_insp["revision_or_hidden_nodes"])
        self.assertNotIn("DELETED", tampered_insp["canonical_form"])

    def test_patent_intake_three_axis_blocks_paper_only_leak_and_builds_pack(self):
        with tempfile.TemporaryDirectory(prefix="dyz-patent-intake-") as folder:
            root = Path(folder)
            src_text = "算法核心公式\ny = \\frac{x^2}{2}\n同一方案：传感器每秒采样。\n内部说明\n"
            raw = src_text.encode("utf-8")
            (root / "source.md").write_bytes(raw)
            h = sha256_bytes(raw)

            bad_intake = {
                "project_id": "P-PAPER-1",
                "source_kind": "paper",
                "task_kind": "new_draft",
                "tech_domain": "software_control",
                "materials": [{"id": "M1", "path": "source.md", "sha256": h, "role": "paper"}],
                "term_formula_figure_map": [
                    {"id": "T1", "kind": "formula", "label": "baseline_loss", "latex": r"y = \frac{x^2}{2}",
                     "origin_scope": "prior_art_review", "source_material_id": "M1", "target_section": "Claims"}
                ],
            }
            inv = patent_intake.build_material_inventory(bad_intake)
            self.assertEqual("blocked", inv["status"])
            self.assertIn("patent_non_invention_material_targeted_to_claims_or_embodiment",
                          [i["code"] for i in inv["issues"]])

            # Invalid LaTeX in inventory MUST record issue cleanly rather than crashing!
            bad_latex = json.loads(json.dumps(bad_intake))
            bad_latex["term_formula_figure_map"][0].update(
                origin_scope="invention_embodiment", target_section="embodiment", latex=r"\frac{a}{}"
            )
            inv_bad_l = patent_intake.build_material_inventory(bad_latex)
            self.assertEqual("blocked", inv_bad_l["status"])
            self.assertIn("patent_formula_omml_invalid", [i["code"] for i in inv_bad_l["issues"]])

            good_intake = dict(bad_intake)
            good_intake["term_formula_figure_map"] = [
                {"id": "T1", "kind": "formula", "label": "core_eq", "latex": r"y = \frac{x^2}{2}",
                 "origin_scope": "invention_embodiment", "source_material_id": "M1", "target_section": "embodiment"}
            ]
            doc_spec = {
                "document_id": "PatentPackDemo",
                "business": "patent",
                "version": "1",
                "sensitivity": "synthetic",
                "sources": [{"id": "S1", "path": "source.md", "sha256": h}],
                "blocks": [
                    {"id": "H1", "kind": "heading1", "audience": "body", "source_id": "S1", "start_line": 1, "end_line": 1},
                    {"id": "EQ1", "kind": "formula", "audience": "body", "source_id": "S1", "start_line": 2, "end_line": 2},
                    {"id": "P1", "kind": "paragraph", "audience": "body", "source_id": "S1", "start_line": 3, "end_line": 3},
                    {"id": "N1", "kind": "paragraph", "audience": "internal", "source_id": "S1", "start_line": 4, "end_line": 4},
                ],
                "figures": [],
            }
            summary = patent_intake.build_patent_pack(
                root, intake_payload=good_intake, document_spec=doc_spec, output="pack", synthetic=True
            )
            self.assertEqual("synthetic", summary["mode"])
            self.assertTrue((root / summary["body_docx"]).is_file())
            self.assertTrue((root / summary["internal_inventory"]).is_file())
            # MUST pass BOTH documents.verify() AND verify_patent_pack()!
            verified = patent_intake.verify_patent_pack(
                root, document_spec=doc_spec, output="pack", synthetic=True
            )
            self.assertEqual("verified_needs_review", verified["status"])

            # Unreviewed extra source in document_spec MUST be rejected by build_patent_pack!
            (root / "unreviewed.md").write_text("未审查文本\n", encoding="utf-8")
            unrev_spec = json.loads(json.dumps(doc_spec))
            unrev_spec["sources"].append({
                "id": "S2", "path": "unreviewed.md",
                "sha256": sha256_bytes((root / "unreviewed.md").read_bytes()),
            })
            with self.assertRaisesRegex(ContractError, "patent_source_not_in_intake_materials"):
                patent_intake.build_patent_pack(
                    root, intake_payload=good_intake, document_spec=unrev_spec, output="pack-bad", synthetic=True
                )

            # Extra unlisted file in outer pack dir MUST be rejected by verify_patent_pack!
            (root / "pack" / "sneaky.txt").write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "patent_pack_unexpected_members"):
                patent_intake.verify_patent_pack(root, document_spec=doc_spec, output="pack", synthetic=True)
            (root / "pack" / "sneaky.txt").unlink()

            # Patent final gate MUST block fabricated formula blocks while accepting verbatim original formula!
            (root / "final-body.md").write_text("传感器每秒采样。\ny = \\frac{x^2}{2}\n", encoding="utf-8")
            fb_sha = sha256_bytes((root / "final-body.md").read_bytes())
            orig_doc = _doc("ORIGF", "同一方案：传感器每秒采样。\n[FORMULA:EQ1:y = \\frac{x^2}{2}]\n")
            spec_ok_formula = {
                "document_id": "FormulaFinalOk",
                "business": "patent",
                "version": "1",
                "sensitivity": "synthetic",
                "delivery_stage": "final",
                "final_text_sources": [orig_doc],
                "sources": [{"id": "S1", "path": "final-body.md", "sha256": fb_sha}],
                "blocks": [
                    {"id": "P1", "kind": "paragraph", "audience": "body", "source_id": "S1", "start_line": 1, "end_line": 1},
                    {"id": "EQ1", "kind": "formula", "audience": "body", "source_id": "S1", "start_line": 2, "end_line": 2},
                ],
                "figures": [],
            }
            built_f = documents.build(root, spec_ok_formula, "formula-ok-out", synthetic=True)
            self.assertEqual("checked", built_f["final_text_gate"]["status"])

            spec_bad_formula = json.loads(json.dumps(spec_ok_formula))
            spec_bad_formula["final_text_sources"] = [_doc("ORIGF2", "同一方案：传感器每秒采样。\n[FORMULA:EQ1:y = \\frac{x^3}{2}]\n")]
            with self.assertRaisesRegex(ContractError, "final_text_gate_blocked") as ctx_f:
                documents.build(root, spec_bad_formula, "formula-bad-out", synthetic=True)
            self.assertIn("final_formula_content_not_supported", [i["code"] for i in ctx_f.exception.report["issues"]])

            # Substring formula fabrication (x=1 from x=100) MUST be blocked, AND formula-only final build+verify MUST work!
            (root / "sub-formula.md").write_text("x = 1\n", encoding="utf-8")
            sf_sha = sha256_bytes((root / "sub-formula.md").read_bytes())
            spec_sub = {
                "document_id": "FormulaSub",
                "business": "patent",
                "version": "1",
                "sensitivity": "synthetic",
                "delivery_stage": "final",
                "final_text_sources": [_doc("O100", "x = 100\n")],
                "sources": [{"id": "S1", "path": "sub-formula.md", "sha256": sf_sha}],
                "blocks": [{"id": "EQ1", "kind": "formula", "audience": "body", "source_id": "S1", "start_line": 1, "end_line": 1}],
                "figures": [],
            }
            with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
                documents.build(root, spec_sub, "formula-sub-out", synthetic=True)

            spec_only_ok = json.loads(json.dumps(spec_sub))
            spec_only_ok["final_text_sources"] = [_doc("O1", "[FORMULA:EQ1:x = 1]\n")]
            built_only = documents.build(root, spec_only_ok, "formula-only-out", synthetic=True)
            self.assertEqual("checked", built_only["final_text_gate"]["status"])
            self.assertIn("input_hash", built_only["final_text_gate"])
            documents.verify(root, spec_only_ok, "formula-only-out", synthetic=True)


if __name__ == "__main__":
    unittest.main()
