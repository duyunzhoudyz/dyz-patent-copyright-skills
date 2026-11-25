"""SP-04有限语法及SP-05实际证据消费；全为原创合成文本。"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import standard_review as review
from tools import standard_sources as sources
from tools.core import canonical_bytes, digest, sha256_bytes
from evals.test_standard_sources import consumption_package


def payload(text="设备应记录结果。", **semantics):
    clause = {"id": "C-1", "text": text, "strength": "requirement", "kind": "normative",
              "source": "synthetic:S1", "conditions": [], "exceptions": [],
              "quantities": [], "method_ids": ["V1"], **semantics}
    return {"version": "v2", "clauses": [clause], "verification_matrix": [
        {"id": "V1", "clause_id": "C-1", "method": "合成检查", "source": "synthetic:S1"}]}


class FiniteReviewTests(unittest.TestCase):
    def codes(self, result):
        return {row["code"] for row in result["issues"]}

    def check(self, data, actual):
        return review.assess(data, actual_texts={"C-1": actual})

    def test_pure_call_has_no_actual_file_claim_and_does_not_mutate(self):
        data = payload()
        before = copy.deepcopy(data)
        result = review.assess(data)
        self.assertEqual(before, data)
        self.assertEqual("not_performed", result["coverage"]["actual_file_verification"])
        self.assertIn("actual_final_text_not_verified", {r["code"] for r in result["pending_reviews"]})
        self.assertIn("source_evidence_not_verified", {r["code"] for r in result["pending_reviews"]})
        self.assertTrue(result["rules_hash"])
        self.assertEqual("not_performed", result["professional_review"])

    def test_actual_text_not_structure_detects_ten_vs_hundred_and_units(self):
        data = payload("设备周期应为10 ms。", quantities=[
            {"id": "Q-1", "value": 10, "unit": "ms", "source": "synthetic:S1"}])
        result = self.check(data, "设备周期应为100 ms。")
        self.assertIn("review_quantity_conflict", self.codes(result))
        unit = self.check(data, "设备周期应为10 s。")
        self.assertIn("review_unit_conflict", self.codes(unit))
        quantity = next(r for r in result["limitation_checks"] if r["limitation_type"] == "quantity_unit")
        self.assertEqual("conflicts", quantity["judgment"])
        self.assertEqual("C-1", quantity["target_id"])
        self.assertEqual(sha256_bytes("设备周期应为100 ms。".encode()), quantity["actual_sha256"])
        self.assertIn("100 ms", quantity["actual_range"]["quote"])

    def test_necessity_is_not_sufficiency_in_verified_subset(self):
        data = payload("仅在设备就绪时设备应启动。", conditions=["设备就绪"])
        result = self.check(data, "设备就绪时设备应启动。")
        self.assertIn("review_condition_direction_conflict", self.codes(result))
        condition = next(r for r in result["limitation_checks"] if r["limitation_type"] == "condition_direction")
        self.assertEqual("necessary", condition["source_value"]["direction"])
        self.assertEqual("sufficient", condition["actual_value"]["direction"])
        self.assertEqual("conflicts", condition["judgment"])

    def test_exception_omission_and_strength_change_are_located(self):
        data = payload("设备宜保持指示灯常亮；维护模式除外。", strength="recommendation",
                       exceptions=["维护模式"])
        result = self.check(data, "设备应保持指示灯常亮。")
        self.assertIn("review_exception_conflict", self.codes(result))
        self.assertIn("review_strength_conflict", self.codes(result))
        exception = next(r for r in result["limitation_checks"] if r["limitation_type"] == "exception")
        self.assertEqual("维护模式", exception["source_value"])
        self.assertEqual("conflicts", exception["judgment"])

    def test_response_adaptation_reliability_and_capability_are_not_modals(self):
        data = payload("响应、适应、可靠性与能力属于描述。", strength="statement", kind="informative")
        result = self.check(data, data["clauses"][0]["text"])
        self.assertNotIn("review_strength_conflict", self.codes(result))
        strength = next(r for r in result["limitation_checks"] if r["limitation_type"] == "strength")
        self.assertEqual([], strength["actual_value"])

    def test_negation_quote_and_complex_grammar_remain_pending(self):
        for text in ("仅在A且(B或C)成立时，设备应启动。", "说明：原文“设备应启动”不构成本条要求。",
                     "设备并非在所有情况下均应启动。", "如果设备在必要时可用，则其可能保持状态。"):
            with self.subTest(text=text):
                result = self.check(payload(text), text)
                self.assertEqual([], result["issues"])
                self.assertTrue(result["pending_reviews"])
                self.assertTrue(any(r["judgment"] == "unknown" for r in result["limitation_checks"]))
                self.assertNotEqual("reviewed_no_issues", result["status"])

    def test_same_complex_text_is_not_semantic_pass_and_context_is_retained(self):
        text = "当其满足附录A中除X外的任一条件时，应按表2处理，另有规定的除外。"
        result = self.check(payload(text), text)
        self.assertEqual([], result["issues"])
        pending = result["pending_reviews"]
        self.assertTrue(pending)
        self.assertEqual("needs_review", result["status"])
        self.assertTrue(any(item.get("actual_range", {}).get("quote") == text for item in pending))

    def test_declared_exception_field_is_checked_against_actual_sentence(self):
        data = payload("设备应记录结果；维护模式除外。", exceptions=["检修模式"])
        result = self.check(data, data["clauses"][0]["text"])
        self.assertIn("review_exception_conflict", self.codes(result))

    def test_declared_condition_does_not_silently_override_actual_condition(self):
        data = payload("仅在设备就绪时设备应启动。", conditions=["设备停止"])
        result = self.check(data, data["clauses"][0]["text"])
        self.assertTrue(any(r["code"] == "review_condition_declaration_needs_review" for r in result["pending_reviews"]))

    def test_unrecognized_condition_form_is_unknown_not_not_applicable(self):
        text = "若设备就绪，则设备应启动。"
        result = self.check(payload(text), text)
        condition = next(r for r in result["limitation_checks"] if r["limitation_type"] == "condition_direction")
        self.assertEqual("unknown", condition["judgment"])
        self.assertEqual([], result["issues"])

    def test_literal_quantities_with_different_objects_are_not_silently_paired(self):
        data = payload("设备电压应为10 V。", quantities=[
            {"id": "Q-1", "value": 10, "unit": "V", "source": "synthetic:S1"}])
        result = self.check(data, "记录周期应为100 ms。")
        quantity = next(r for r in result["limitation_checks"] if r["limitation_type"] == "quantity_unit")
        self.assertEqual("unknown", quantity["judgment"])
        self.assertNotIn("review_quantity_conflict", self.codes(result))

    def test_prohibition_reversal_does_not_pass_same_requirement_class(self):
        result = self.check(payload("设备不得启动。"), "设备应启动。")
        strength = next(r for r in result["limitation_checks"] if r["limitation_type"] == "strength")
        self.assertNotEqual("supports", strength["judgment"])
        unchanged = self.check(payload("设备不得启动。"), "设备不得启动。")
        self.assertNotIn("review_strength_conflict", self.codes(unchanged))

    def test_wrong_actual_text_key_cannot_fall_back_to_correct_structure(self):
        result = review.assess(payload(), actual_texts={"unrelated": "设备应记录结果。"})
        self.assertIn("actual_final_text_missing", {r["code"] for r in result["pending_reviews"]})
        self.assertEqual(0, result["coverage"]["actual_texts_checked"])

    def test_claimed_review_needs_ranges_identity_evidence_and_current_hashes(self):
        data = payload()
        data["limitation_reviews"] = [{"id": "LR1", "target_type": "clause", "target_id": "C-1",
                                       "limitation_type": "strength", "judgment": "supports",
                                       "dependency_hash": "0" * 64, "rules_hash": "0" * 64}]
        result = self.check(data, data["clauses"][0]["text"])
        review_record = result["limitation_review_records"][0]
        self.assertEqual("needs_review", review_record["status"])
        self.assertIn("limitation_review_incomplete", {r["code"] for r in result["pending_reviews"]})
        self.assertEqual([], result["issues"])

    def test_current_review_record_ranges_are_checked_and_never_a_signature(self):
        data = payload()
        actual = data["clauses"][0]["text"]
        generated = self.check(data, actual)
        row = copy.deepcopy(next(r for r in generated["limitation_checks"] if r["limitation_type"] == "strength"))
        row.update(id="LR1", evidence=["synthetic:review:1"], reviewer_type="author_engineering_review",
                   reviewer_id="synthetic-author")
        data["limitation_reviews"] = [row]
        reviewed = self.check(data, actual)
        self.assertEqual("bound_record_unverified", reviewed["limitation_review_records"][0]["status"])
        self.assertEqual("not_authenticated", reviewed["limitation_review_records"][0]["reviewer_identity"])
        row["actual_range"]["quote"] = "不同正文"
        stale = self.check(data, actual)
        self.assertEqual("stale", stale["limitation_review_records"][0]["status"])
        self.assertIn("limitation_review_range_stale", {r["code"] for r in stale["pending_reviews"]})

    def test_unsupported_review_dimension_and_unknown_target_cannot_disappear(self):
        data = payload()
        data["limitation_reviews"] = [{"id": "LR1", "target_type": "clause", "target_id": "MISSING",
                                       "limitation_type": "arbitrary_proof", "judgment": "supports"}]
        result = self.check(data, data["clauses"][0]["text"])
        self.assertEqual(1, len(result["limitation_review_records"]))
        self.assertTrue(any(r["code"] == "limitation_review_target_unresolved" for r in result["pending_reviews"]))
        self.assertTrue(any(r["code"] == "limitation_review_dimension_unsupported" for r in result["pending_reviews"]))

    def test_pure_call_records_source_descriptors_as_unread_not_verified(self):
        data = payload()
        data["source_reports"] = [{"report_id": "R1", "path": "report.json", "sha256": "0" * 64,
                                   "source": "S1", "verified": True}]
        data["source_bindings"] = [{"binding_id": "B1", "target_type": "clause", "target_id": "C-1",
                                    "report_id": "R1", "citation_ids": ["CITE1"], "proposition": "命题", "version": "v2"}]
        result = review.assess(data)
        self.assertEqual("not_read", result["source_report_checks"][0]["state"])
        self.assertEqual("not_verified", result["source_binding_checks"][0]["state"])
        self.assertTrue(any(r["code"] == "source_report_not_read" for r in result["pending_reviews"]))

    def test_internal_rule_asset_is_loaded_and_contributes_to_hash(self):
        result = self.check(payload(), "设备应记录结果。")
        asset = Path(review.__file__).resolve().parents[1] / "skills/dyz-standards/resources/lifecycle/review-rules.v1.json"
        self.assertEqual(sha256_bytes(asset.read_bytes()), result["rules_hash"])
        self.assertTrue(result["coverage"]["rule_ids"])
        self.assertEqual("internal", result["coverage"]["rule_scope"])
        self.assertEqual("not_asserted", result["organization_compliance"])

    def test_assess_itself_does_not_open_files_or_compare_unknown_subject(self):
        with patch.object(Path, "open", side_effect=AssertionError("assess must be pure")):
            result = self.check(payload("应保存记录。"), "应保存记录。")
        self.assertTrue(result["pending_reviews"])
        object_check = next(r for r in result["limitation_checks"] if r["limitation_type"] == "object_action")
        self.assertEqual("unknown", object_check["judgment"])

    def test_term_definition_conflict_and_declared_alias_are_consumed(self):
        data = payload("设备应保存运行日志。")
        data["terms"] = [{"id": "T1", "term": "设备", "definition": "装置一", "source": "synthetic:1"},
                         {"id": "T2", "term": "设备", "definition": "装置二", "source": "synthetic:2"}]
        result = self.check(data, data["clauses"][0]["text"])
        self.assertIn("review_term_definition_conflict", self.codes(result))
        data["terms"] = [{"id": "T1", "term": "运行日志", "definition": "合成记录", "source": "synthetic:1",
                          "aliases": ["工作记录"]}]
        result = self.check(data, "设备应保存工作记录。")
        self.assertNotIn("review_term_undeclared_substitution", self.codes(result))
        self.assertTrue(any(r.get("limitation_type") == "term_usage" for r in result["limitation_checks"]))

    def test_circular_definitions_casefold_admitted_validation_and_delivery_integration(self):
        from tools import standards_delivery as delivery
        from tools.core import ContractError
        from evals.test_standards_delivery import task as delivery_task
        import zipfile
        from xml.etree import ElementTree as ET

        # Mixed-case circularity (Latency <-> jitter), mixed-case self-cycle, and case-folded duplicates
        findings = review.detect_circular_definitions([
            {"id": "T1", "term": "Latency", "definition": "Delay dependent on jitter."},
            {"id": "T2", "term": "Jitter", "definition": "Variation of latency over time."},
            {"id": "T3", "term": "Packet", "definition": "A packet carrying payload."},
            {"id": "T4", "term": "Frame", "definition": "Unit A."},
            {"id": "T5", "term": "frame", "definition": "Unit B."},
        ])
        by_code = {row["code"]: row for row in findings}
        self.assertIn("review_term_circular_definition", by_code)
        self.assertEqual(["Latency", "Jitter"], by_code["review_term_circular_definition"]["terms"])
        self.assertEqual(["Latency", "Jitter", "Latency"], by_code["review_term_circular_definition"]["cycle"])
        self.assertIn("review_term_self_circular_definition", by_code)
        self.assertEqual("Packet", by_code["review_term_self_circular_definition"]["term"])
        self.assertIn("review_duplicate_term_name", by_code)
        self.assertEqual("Frame", by_code["review_duplicate_term_name"]["term"])
        self.assertEqual(["T4", "T5"], by_code["review_duplicate_term_name"]["record_ids"])

        # Non-list admitted MUST fail closed with ContractError
        for bad_admitted in ("not-a-list", 123, [123], [""]):
            with self.subTest(admitted=bad_admitted):
                with self.assertRaisesRegex(ContractError, "review_term_admitted_required"):
                    review.detect_circular_definitions([
                        {"id": "T1", "term": "Latency", "admitted": bad_admitted, "definition": "Delay."},
                    ])

        # Circular definitions flow into assess(), six-dimension report (without double-counting), and standards_delivery!
        data = payload("设备应满足规范要求。")
        data["terms"] = [
            {"id": "T1", "term": "Latency", "definition": "Delay dependent on jitter.", "source": "S1"},
            {"id": "T2", "term": "Jitter", "definition": "Variation of latency.", "source": "S1"},
        ]
        assessed = review.assess(data, actual_texts={"C-1": data["clauses"][0]["text"]})
        self.assertEqual("blocked", assessed["status"])
        self.assertIn("review_term_circular_definition", self.codes(assessed))
        six = review.project_six_dimension_report(assessed, payload=data)
        self.assertEqual("blocked", six["status"])
        self.assertEqual(1, six["dimension_counts"]["4_terminology_and_circularity"])

        with tempfile.TemporaryDirectory(prefix="dyz-std-circ-") as folder:
            root = Path(folder)
            pkg = delivery_task()
            pkg["terms"] = copy.deepcopy(data["terms"])
            manifest = delivery.prepare(root, pkg, "pack", synthetic=True)
            self.assertEqual("needs_evidence", manifest["status"])
            self.assertEqual("internal_draft_needs_evidence", manifest["delivery_state"])
            self.assertIn("review_term_circular_definition", {row["code"] for row in manifest["issues"]})
            with zipfile.ZipFile(root / "pack/body/review_report.docx") as archive:
                tree = ET.fromstring(archive.read("word/document.xml"))
            report_text = "".join(node.text or "" for node in tree.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
            self.assertIn("review_term_circular_definition", report_text)
            self.assertIn("Latency", report_text)
            self.assertTrue(delivery.verify(root, pkg, "pack", synthetic=True)["file_hashes_equal"])

            # P2-9: OSError from .stat() on macOS system root symlink is caught as ContractError
            child = root / "sub" / "leaf.txt"
            (root / "sub").mkdir()
            child.write_text("x", encoding="utf-8")
            fake_link = type("FakeStat", (), {"st_mode": 0o120777, "st_nlink": 1})()
            real_lstat = Path.lstat
            real_stat = Path.stat

            def mock_lstat(p):
                if p == root / "sub":
                    return fake_link
                return real_lstat(p)

            def mock_stat(p, *args, **kwargs):
                if p == root / "sub":
                    raise OSError("broken system symlink")
                return real_stat(p, *args, **kwargs)

            with patch.object(delivery, "is_macos_system_root_symlink", side_effect=lambda p: p == root / "sub"), \
                 patch.object(Path, "lstat", mock_lstat), \
                 patch.object(Path, "stat", mock_stat):
                with self.assertRaisesRegex(ContractError, "standard_path_link_unsupported"):
                    delivery._plain_path(child)


class VerifiedSourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data, self.report = consumption_package(self.root, ["仅在设备就绪时设备应启动。维护模式除外。"])
        self.data["clauses"][0].update(strength="requirement", kind="normative", conditions=["设备就绪"],
                                        exceptions=["维护模式"], quantities=[], method_ids=["V1"])
        self.data["verification_matrix"] = [{"id": "V1", "clause_id": "C-1", "method": "合成检查"}]
        self.actual = {"C-1": self.data["clauses"][0]["text"]}

    def test_verified_citation_is_compared_with_actual_text_not_proposition_summary(self):
        self.data["clauses"][0]["text"] = "设备就绪时设备应启动。"
        self.data["source_bindings"][0]["proposition"] = "设备就绪时设备应启动。"
        self.data["clauses"][0]["exceptions"] = []
        verified = sources.verify_reports(self.root, self.data, synthetic=True)
        result = review.assess(self.data, actual_texts={"C-1": self.data["clauses"][0]["text"]},
                               source_verification=verified)
        codes = {r["code"] for r in result["issues"]}
        self.assertIn("review_condition_direction_conflict", codes)
        self.assertIn("review_exception_conflict", codes)
        bound = [r for r in result["limitation_checks"] if r.get("binding_id") == "B-1"]
        self.assertTrue(bound)
        self.assertTrue(all(r["source_sha256"] for r in bound))
        self.assertTrue(any(r["source_range"].get("citation_ids") == ["CITE-1"] for r in bound))

    def test_serialized_or_changed_verification_is_not_trusted(self):
        verified = sources.verify_reports(self.root, self.data, synthetic=True)
        for fake in (dict(verified), {"status": "passed", "verified": True, "source_trace": []}):
            result = review.assess(self.data, actual_texts=self.actual, source_verification=fake)
            self.assertIn("source_verification_untrusted_or_stale", {r["code"] for r in result["pending_reviews"]})
        self.data["source_bindings"][0]["proposition"] = "改变命题"
        result = review.assess(self.data, actual_texts=self.actual, source_verification=verified)
        self.assertIn("source_verification_untrusted_or_stale", {r["code"] for r in result["pending_reviews"]})

    def test_local_review_dependency_changes_only_for_related_target(self):
        self.data["clauses"].append({"id": "C-2", "text": "设备应保存记录。", "strength": "requirement",
                                      "kind": "normative", "conditions": [], "exceptions": [],
                                      "quantities": [], "method_ids": ["V2"]})
        self.actual["C-2"] = self.data["clauses"][1]["text"]
        before = review.assess(self.data, actual_texts=self.actual)
        hashes = {r["target_id"]: r["dependency_hash"] for r in before["limitation_checks"]}
        self.data["source_bindings"][0]["proposition"] = "改变相关命题"
        after = review.assess(self.data, actual_texts=self.actual)
        current = {r["target_id"]: r["dependency_hash"] for r in after["limitation_checks"]}
        self.assertNotEqual(hashes["C-1"], current["C-1"])
        self.assertEqual(hashes["C-2"], current["C-2"])

    def test_verified_literal_source_does_not_assert_professional_approval(self):
        verified = sources.verify_reports(self.root, self.data, synthetic=True)
        result = review.assess(self.data, actual_texts=self.actual, source_verification=verified)
        self.assertEqual([], result["issues"])
        self.assertEqual("not_performed", result["professional_review"])
        self.assertEqual("not_asserted", result["organization_compliance"])
        self.assertTrue(any(r["code"] == "source_proposition_applicability_needs_review"
                            for r in result["pending_reviews"]))


class NonclauseSourceReviewTests(unittest.TestCase):
    """实际业务字段只由消费者提供的完整书签和唯一范围定位。"""

    kinds = ("comment", "comment_reason", "verification", "verification_basis",
             "compilation_note", "note_section")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    @staticmethod
    def block(text, *, kind="comment_reason", identity="K-1", prefix="书签正文前缀\n",
              role="comments", bookmark="BusinessField"):
        return {"target_type": kind, "target_id": identity, "document_role": role,
                "bookmark": bookmark, "text": prefix + text + "\n记录角色及定位。",
                "start": len(prefix), "end": len(prefix) + len(text)}

    def case(self, source="设备宜记录结果。", actual=None, *, kind="comment_reason"):
        actual = source if actual is None else actual
        data, _ = consumption_package(self.root, [source])
        data["clauses"] = []
        data["comments"] = [{"id": "K-1", "text": actual}]
        data["comment_outcomes"] = [{"comment_id": "K-1", "reason": actual}]
        data["verification_matrix"] = [{"id": "K-1", "clause_id": "C-1", "method": actual,
                                         "reason": actual}]
        data["compilation_note"] = {"sections": [{"id": "K-1", "body": actual}]}
        data["source_bindings"][0].update(target_type=kind, target_id="K-1")
        return data, {"B-1": [self.block(actual, kind=kind)]}

    def assess(self, data, blocks, *, verified=True):
        evidence = sources.verify_reports(self.root, data, synthetic=True) if verified else None
        return review.assess(data, actual_blocks=blocks, source_verification=evidence)

    @staticmethod
    def bound(result, dimension=None):
        return [row for row in result["limitation_checks"]
                if row.get("binding_id") == "B-1"
                and (dimension is None or row["limitation_type"] == dimension)]

    def test_verified_condition_reversal_uses_actual_field_and_full_bookmark_offsets(self):
        data, blocks = self.case("仅在设备就绪时设备应启动。", "设备就绪时设备应启动。")
        result = self.assess(data, blocks)
        check = self.bound(result, "condition_direction")[0]
        self.assertEqual("conflicts", check["judgment"])
        self.assertEqual("comment_reason", check["target_type"])
        self.assertEqual("K-1", check["target_id"])
        block = blocks["B-1"][0]
        self.assertEqual(block["start"], check["actual_range"]["start"])
        self.assertEqual(block["end"], check["actual_range"]["end"])
        self.assertEqual(block["text"][block["start"]:block["end"]], check["actual_range"]["quote"])
        self.assertEqual(sha256_bytes(block["text"].encode()), check["actual_sha256"])
        self.assertEqual(data["source_reports"][0]["sha256"], check["report_sha256"])
        self.assertTrue(check["original_sha256"])
        self.assertTrue(check["source_sha256"])
        self.assertEqual(["CITE-1"], check["source_range"]["citation_ids"])
        self.assertTrue(check["source_range"]["segments"])
        self.assertEqual("BusinessField", check["actual_location"]["bookmark"])
        pending = next(row for row in result["pending_reviews"]
                       if row["code"] == "source_proposition_applicability_needs_review")
        self.assertEqual("actual_final_bookmark_spans", pending["actual_evidence"])
        self.assertEqual("conflicts", result["nonclause_final_text_checks"][0]["finite_check_status"])

    def test_each_business_field_compares_original_citation_in_finite_subset(self):
        cases = (("仅在设备就绪时设备应启动。", "设备就绪时设备应启动。", "condition_direction"),
                 ("设备周期应为10 ms。", "设备周期应为100 ms。", "quantity_unit"),
                 ("设备宜保持指示灯常亮。", "设备应保持指示灯常亮。", "strength"),
                 ("设备应记录结果；维护模式除外。", "设备应记录结果。", "exception"))
        for kind in self.kinds:
            for source, actual, dimension in cases:
                with self.subTest(kind=kind, dimension=dimension):
                    data, blocks = self.case(source, actual, kind=kind)
                    data["source_bindings"][0]["proposition"] = actual
                    result = self.assess(data, blocks)
                    checks = self.bound(result, dimension)
                    self.assertEqual(1, len(checks))
                    self.assertEqual("conflicts", checks[0]["judgment"])
                    self.assertEqual(kind, checks[0]["target_type"])
                    self.assertEqual("K-1", checks[0]["target_id"])
                    self.assertFalse(self.bound(result, "verification_link"))

    def test_identical_simple_field_checks_only_literals_and_keeps_proposition_pending(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                data, blocks = self.case(kind=kind)
                for row in (data["comments"][0], data["comment_outcomes"][0],
                            data["verification_matrix"][0], data["compilation_note"]["sections"][0]):
                    row.update(strength="requirement", conditions=["不同条件"], exceptions=["不同例外"],
                               quantities=[{"value": 100, "unit": "s"}], method_ids=["missing"])
                before = copy.deepcopy((data, blocks))
                with patch.object(Path, "open", side_effect=AssertionError("assess must stay pure")):
                    result = review.assess(data, actual_blocks=blocks)
                self.assertEqual([], self.bound(result))
                result = self.assess(data, blocks)
                self.assertEqual(before, (data, blocks))
                self.assertEqual([], result["issues"])
                self.assertEqual("supports", self.bound(result, "strength")[0]["judgment"])
                summary = result["nonclause_final_text_checks"][0]
                self.assertEqual("checked_finite_subset", summary["finite_check_status"])
                self.assertEqual("needs_review", summary["status"])
                self.assertEqual("not_verified", summary["proposition_support"])
                self.assertEqual("not_performed", result["professional_review"])
                self.assertNotEqual("checked_finite_subset", result["status"])

    def test_unchanged_finite_conditions_quantities_strength_and_exception_are_literal_matches(self):
        for text, dimension in (("仅在设备就绪时设备应启动。", "condition_direction"),
                                ("设备周期应为10 ms。", "quantity_unit"),
                                ("设备宜保持指示灯常亮。", "strength"),
                                ("设备应记录结果；维护模式除外。", "exception")):
            with self.subTest(dimension=dimension):
                data, blocks = self.case(text)
                result = self.assess(data, blocks)
                self.assertEqual("supports", self.bound(result, dimension)[0]["judgment"])
                self.assertEqual([], result["issues"])
                self.assertEqual("checked_finite_subset", result["nonclause_final_text_checks"][0]["finite_check_status"])

    def test_complex_or_explanatory_business_field_stays_unknown(self):
        for text in ("仅在A且(B或C)成立时，设备应启动。", "说明：原文“设备应启动”不构成本条要求。",
                     "设备并非在所有情况下均应启动。", "设备周期应为10至100 ms。"):
            with self.subTest(text=text):
                data, blocks = self.case(text, kind="compilation_note")
                result = self.assess(data, blocks)
                self.assertEqual([], result["issues"])
                self.assertTrue(any(row["judgment"] == "unknown" for row in self.bound(result)))
                self.assertEqual("unknown", result["nonclause_final_text_checks"][0]["finite_check_status"])

    def test_each_final_field_and_each_projected_block_is_checked_separately(self):
        source = "设备周期应为10 ms。"
        changed = "设备周期应为100 ms。"
        data, blocks = self.case(source, changed)
        data["comment_outcomes"].append({"comment_id": "K-1", "reason": source})
        blocks["B-1"].append(self.block(source, bookmark="SecondOutcome", prefix="第二理由："))
        blocks["B-1"].append(self.block(changed, role="compilation_note", bookmark="ProjectedReason"))
        result = self.assess(data, blocks)
        checks = self.bound(result, "quantity_unit")
        self.assertEqual(["conflicts", "supports", "conflicts"], [row["judgment"] for row in checks])
        self.assertEqual(3, len(result["nonclause_final_text_checks"][0]["actual_locations"]))
        self.assertEqual(["BusinessField", "SecondOutcome", "ProjectedReason"],
                         [row["actual_location"]["bookmark"] for row in checks])
        for row, block in zip(checks, blocks["B-1"]):
            span = row["actual_range"]
            self.assertEqual(span["quote"], block["text"][span["start"]:span["end"]])
            self.assertTrue(block["start"] <= span["start"] < span["end"] <= block["end"])

    def test_equal_fields_in_multiple_records_are_checked_for_each_actual_bookmark(self):
        data, blocks = self.case()
        data["comment_outcomes"].append(copy.deepcopy(data["comment_outcomes"][0]))
        blocks["B-1"].append(self.block(data["comment_outcomes"][0]["reason"], bookmark="SameOtherReason"))
        result = self.assess(data, blocks)
        self.assertEqual(["supports", "supports"],
                         [row["judgment"] for row in self.bound(result, "strength")])
        self.assertEqual(2, len(result["nonclause_final_text_checks"][0]["actual_locations"]))
        blocks["B-1"].pop()
        missing = self.assess(data, blocks)
        self.assertTrue(any(row["code"] == "actual_final_field_missing"
                            for row in missing["pending_reviews"]))
        self.assertEqual("unknown", missing["nonclause_final_text_checks"][0]["finite_check_status"])

    def test_mismatched_valid_range_or_duplicate_location_cannot_add_support(self):
        data, blocks = self.case()
        block = blocks["B-1"][0]
        block["end"] -= 1
        result = self.assess(data, blocks)
        self.assertEqual([], self.bound(result))
        self.assertTrue(any(row["code"] == "actual_final_block_field_unresolved"
                            for row in result["pending_reviews"]))
        data, blocks = self.case()
        blocks["B-1"].append(copy.deepcopy(blocks["B-1"][0]))
        result = self.assess(data, blocks)
        self.assertEqual(1, len(self.bound(result, "strength")))
        self.assertTrue(any(row["code"] == "actual_final_block_duplicated"
                            for row in result["pending_reviews"]))
        self.assertEqual("unknown", result["nonclause_final_text_checks"][0]["finite_check_status"])

    def test_missing_blocks_or_field_never_fall_back_to_input_or_self_reported_flags(self):
        data, blocks = self.case()
        data["source_bindings"][0]["verified"] = True
        for supplied in (None, {}, {"B-1": []}):
            with self.subTest(blocks=supplied):
                result = self.assess(data, supplied)
                self.assertEqual([], self.bound(result))
                self.assertEqual("not_performed", result["nonclause_final_text_checks"][0]["finite_check_status"])
                self.assertTrue(any(row["code"].startswith("actual_final_block_")
                                    for row in result["pending_reviews"]))
        wrong = copy.deepcopy(blocks)
        wrong["B-1"][0] = {**self.block("其他正文。"), "verified": True, "status": "passed"}
        result = self.assess(data, wrong)
        self.assertEqual([], self.bound(result))
        self.assertTrue(any(row["code"] == "actual_final_block_field_unresolved"
                            for row in result["pending_reviews"]))

    def test_ambiguous_business_field_is_pending_even_when_a_range_is_supplied(self):
        data, blocks = self.case()
        block = blocks["B-1"][0]
        block["text"] += block["text"][block["start"]:block["end"]]
        result = self.assess(data, blocks)
        self.assertEqual([], self.bound(result))
        self.assertTrue(any(row["code"] == "actual_final_field_ambiguous"
                            for row in result["pending_reviews"]))
        self.assertEqual("not_performed", result["nonclause_final_text_checks"][0]["finite_check_status"])

    def test_partial_field_coverage_is_not_a_complete_finite_check(self):
        data, blocks = self.case()
        data["comment_outcomes"].append({"comment_id": "K-1", "reason": "设备应保存日志。"})
        result = self.assess(data, blocks)
        self.assertTrue(self.bound(result))
        self.assertTrue(any(row["code"] == "actual_final_field_missing"
                            for row in result["pending_reviews"]))
        self.assertEqual("unknown", result["nonclause_final_text_checks"][0]["finite_check_status"])

    def test_verification_basis_falls_back_only_when_reason_is_absent_and_method_is_text(self):
        data, blocks = self.case(kind="verification_basis")
        del data["verification_matrix"][0]["reason"]
        self.assertTrue(self.bound(self.assess(data, blocks)))
        for bad_reason in (None, "", {"text": "设备宜记录结果。"}):
            with self.subTest(reason=bad_reason):
                data["verification_matrix"][0]["reason"] = bad_reason
                result = self.assess(data, blocks)
                self.assertEqual([], self.bound(result))
                self.assertTrue(any(row["code"] == "review_nonclause_field_unavailable"
                                    for row in result["pending_reviews"]))
        data, blocks = self.case(kind="verification")
        data["verification_matrix"][0]["method"] = {"text": "设备宜记录结果。", "verified": True}
        self.assertEqual([], self.bound(self.assess(data, blocks)))

    def test_complete_current_source_is_required_for_nonclause_comparison(self):
        data, blocks = self.case()
        verified = sources.verify_reports(self.root, data, synthetic=True)
        for fake in (None, dict(verified), {"verified": True, "source_trace": verified["source_trace"]}):
            with self.subTest(fake=type(fake).__name__):
                result = review.assess(data, actual_blocks=blocks, source_verification=fake)
                self.assertEqual([], self.bound(result))
                self.assertTrue(any(row["code"] == "source_evidence_not_verified"
                                    for row in result["pending_reviews"]))
        data["source_bindings"][0]["version"] = "v1"
        result = self.assess(data, blocks)
        self.assertEqual([], self.bound(result))
        self.assertIn("source_target_version_mismatch", {row["code"] for row in result["issues"]})

    def test_actual_partial_citation_is_not_used_as_complete_source(self):
        source = "设备宜记录结果。"
        data, report = consumption_package(self.root, [source])
        data["clauses"] = []
        data["comments"] = [{"id": "K-1", "text": source}]
        data["source_bindings"][0].update(target_type="comment", target_id="K-1")
        report["citations"][0]["segments"] = [
            {"page": 1, "start": 0, "end": 3, "quote": source[:3]},
            {"page": 1, "start": 4, "end": len(source), "quote": source[4:]}]
        raw = canonical_bytes(report) + b"\n"
        (self.root / "report.json").write_bytes(raw)
        data["source_reports"][0]["sha256"] = sha256_bytes(raw)
        blocks = {"B-1": [self.block(source, kind="comment")]}
        verified = sources.verify_reports(self.root, data, synthetic=True)
        self.assertEqual("partial", verified["source_trace"][0]["coverage"])
        result = review.assess(data, actual_blocks=blocks, source_verification=verified)
        self.assertEqual([], self.bound(result))
        self.assertEqual("not_performed", result["nonclause_final_text_checks"][0]["finite_check_status"])
        self.assertIn("source_citation_coverage_partial", {row["code"] for row in result["issues"]})

    def test_missing_target_remains_an_issue_without_finite_support(self):
        data, blocks = self.case()
        data["comments"] = []
        result = self.assess(data, blocks)
        self.assertEqual([], self.bound(result))
        self.assertIn("source_target_missing_or_ambiguous", {row["code"] for row in result["issues"]})

    def test_binding_version_and_report_changes_invalidate_only_local_dependency(self):
        data, blocks = self.case()
        data["comments"].append({"id": "K-2", "text": data["comments"][0]["text"]})
        data["comment_outcomes"].append({"comment_id": "K-2", "reason": data["comment_outcomes"][0]["reason"]})
        (self.root / "second-report.json").write_bytes((self.root / "report.json").read_bytes())
        second_report = {**data["source_reports"][0], "report_id": "R-2", "path": "second-report.json"}
        data["source_reports"].append(second_report)
        data["source_bindings"].append({**data["source_bindings"][0], "binding_id": "B-2",
                                         "target_id": "K-2", "report_id": "R-2"})
        blocks["B-2"] = [self.block(data["comments"][0]["text"], identity="K-2", bookmark="OtherTarget")]

        def hashes():
            return {row["binding_id"]: row["dependency_hash"]
                    for row in self.assess(data, blocks)["nonclause_final_text_checks"]}

        before = hashes()
        data["source_bindings"][0]["version"] = "v1"
        changed = hashes()
        self.assertNotEqual(before["B-1"], changed["B-1"])
        self.assertEqual(before["B-2"], changed["B-2"])
        data["source_bindings"][0]["version"] = "v2"
        raw = (self.root / "report.json").read_bytes() + b" \n"
        (self.root / "report.json").write_bytes(raw)
        data["source_reports"][0]["sha256"] = sha256_bytes(raw)
        changed = hashes()
        self.assertNotEqual(before["B-1"], changed["B-1"])
        self.assertEqual(before["B-2"], changed["B-2"])

    def test_actual_block_shape_binding_and_range_are_validated(self):
        data, valid = self.case()
        malformed = [[], {"B-1": {}}, {"B-1": [None]}, {"unknown": valid["B-1"]}]
        for field, value in (("target_type", "comment"), ("target_id", "wrong"),
                             ("document_role", ""), ("document_role", 1), ("bookmark", ""),
                             ("text", 1), ("start", True), ("start", -1), ("end", 0),
                             ("end", 10_000_000)):
            rows = copy.deepcopy(valid)
            rows["B-1"][0][field] = value
            malformed.append(rows)
        for field in valid["B-1"][0]:
            rows = copy.deepcopy(valid)
            del rows["B-1"][0][field]
            malformed.append(rows)
        for blocks in malformed:
            with self.subTest(blocks=blocks):
                with self.assertRaises(ValueError):
                    review.assess(data, actual_blocks=blocks)

    def test_nonclause_manual_review_remains_explicitly_unsupported(self):
        data, blocks = self.case()
        first = self.assess(data, blocks)
        record = copy.deepcopy(self.bound(first, "strength")[0])
        record.update(id="LR-NONCLAUSE", reviewer_type="human_professional", reviewer_id="synthetic-reviewer",
                      evidence=["synthetic:manual-review"])
        data["limitation_reviews"] = [record]
        result = self.assess(data, blocks)
        row = result["limitation_review_records"][0]
        self.assertEqual("needs_review", row["status"])
        self.assertEqual("not_inferred", row["professional_approval"])
        self.assertIn("limitation_review_target_unresolved", row["problems"])


if __name__ == "__main__":
    unittest.main()
