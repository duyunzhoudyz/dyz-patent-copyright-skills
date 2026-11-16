"""R04/R06：临时原创合成稿的真实文件、编辑回查和普通确认回归。"""
import copy
import importlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile
import zlib

from tools import document_review
from tools.core import ContractError, VersionLedger, canonical_bytes, capture_evidence, digest, sha256_bytes
from evals.test_fidelity import citation, document, example


NOTICE = "合成示例；内部工作稿，待专业审阅，不得据此提交或外发。"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def edit_docx(raw, change):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    tree = ET.fromstring(entries["word/document.xml"])
    change(tree)
    entries["word/document.xml"] = ET.tostring(tree, encoding="utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return buffer.getvalue()


class PatentDeliveryTests(unittest.TestCase):
    def setUp(self):
        # 缺少实际消费者时给出明确失败，而非以跳过或导入异常伪装红灯。
        self.assertIsNotNone(importlib.util.find_spec("tools.patent_delivery"),
                             "R04/R06 patent delivery consumer is not implemented")
        self.delivery = importlib.import_module("tools.patent_delivery")
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-patent-delivery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lines = [NOTICE, "一种合成发布系统，其发布时须已取得许可。",
                      "合成实施方式：系统发布时须已取得许可，未获许可的状态不在本例中补充动作。",
                      "合成摘要：本例说明发布须具有许可的必要条件。",
                      "内部意见：待确认的专业问题只保留在内部材料。"]
        self.spec = {"sensitivity": "synthetic", "business": "patent",
                     "document_id": "SyntheticPatent", "version": "1", "delivery_stage": "draft",
                     "sources": [{"id": "SRC", "path": "manuscript.txt", "sha256": ""}],
                     "blocks": [{"id": key, "source_id": "SRC", "start_line": i,
                                 "end_line": i, "kind": "paragraph",
                                 "audience": "internal" if key == "Notes" else "body"}
                                for i, key in enumerate(("Notice", "Claim", "Spec", "Abstract", "Notes"), 1)],
                     "patent_delivery": {"project_id": "SYNTHETIC-PATENT", "scope": "合成CN内部起草",
                         "purpose": "本地开发回归", "rules": [{"id": "synthetic-rule", "version": "1"}],
                         "notice_block": "Notice", "expected_roles": {"claims": ["Claim"],
                             "specification": ["Spec"], "abstract": ["Abstract"]},
                         "drawings": {"applicable": False, "figure_ids": [],
                                      "not_applicable_reason": "本合成文字示例不使用结构或流程附图。"}}}
        self.write_source()

    def write_source(self):
        raw = ("\n".join(self.lines) + "\n").encode("utf-8")
        (self.root / "manuscript.txt").write_bytes(raw)
        self.spec["sources"][0]["sha256"] = sha256_bytes(raw)

    def build(self, output="pack"):
        return self.delivery.prepare(self.root, self.spec, output, synthetic=True)

    def verify(self, output="pack"):
        return self.delivery.verify(self.root, self.spec, output, synthetic=True)

    def bind(self, ledger, output="pack"):
        return self.delivery.register_package(ledger, self.root, self.spec, output, synthetic=True)

    def confirm(self, ledger, binding, decision="accepted", conditions=None, identity="C1"):
        event = {"id": identity, "actor_id": "synthetic-caller", "actor_type": "human",
                 "stage": "internal_review", "decision": decision,
                 "conditions": [] if conditions is None else conditions,
                 "confirmed_at": "2026-11-01T00:00:00Z",
                 "manifest_sha256": binding["manifest_sha256"]}
        return self.delivery.record_confirmation(ledger, binding, event,
            self.root, self.spec, "pack", synthetic=True)

    def add_final_gate_sources(self):
        self.lines[1:4] = ["只有许可成立，才允许发布。"] * 3
        self.write_source()
        self.add_fidelity()
        self.spec["final_text_sources"] = [document("GateOriginal", "original", self.lines[1])]

    def add_fidelity(self):
        payload = example()
        payload["documents"] = payload["documents"][:1]
        payload["assertions"] = []
        payload["regions"] = []
        bindings = {}
        for index, block in enumerate(self.spec["blocks"]):
            if block["audience"] != "body":
                continue
            candidate = document("D" + str(index), "candidate", self.lines[index])
            payload["documents"].append(candidate)
            bindings[block["id"]] = citation(candidate)
            if block["id"] != "Notice":
                assertion_id = "A" + str(index)
                payload["assertions"].append({"id": assertion_id, "citation": citation(candidate),
                    "formula": {"implies": ["release", "permission"]}, "basis_fact_ids": ["F1"],
                    "proof_scope": "original_support", "mode": "asserted"})
                payload["regions"].append({"id": "R" + str(index), "citation": citation(candidate),
                    "kind": "technical", "assertion_ids": [assertion_id]})
            else:
                payload["regions"].append({"id": "NoticeRegion", "citation": citation(candidate),
                    "kind": "context", "reason": "合成与工作稿状态声明"})
        self.spec["fidelity"] = {"payload": payload, "blocks": bindings}

    def add_figure(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        png += chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b"")
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><text x="1" y="12">A</text></svg>'
        (self.root / "figure.png").write_bytes(png)
        (self.root / "figure.svg").write_bytes(svg)
        self.spec["figures"] = [{"id": "Fig1", "png": {"path": "figure.png", "sha256": sha256_bytes(png)},
            "svg": {"path": "figure.svg", "sha256": sha256_bytes(svg)},
            "render_binding": digest({"svg": sha256_bytes(svg), "png": sha256_bytes(png)})}]
        self.spec["patent_delivery"]["drawings"] = {"applicable": True, "figure_ids": ["Fig1"]}

    def add_source_derivation(self):
        raw = b"SYNTHETIC ORIGINAL CARRIER\x00" + "\n".join(self.lines).encode("utf-8")
        (self.root / "original.bin").write_bytes(raw)
        evidence, snapshot = capture_evidence(self.root, "original.bin",
            source={"id": "ORIGINAL", "version": "1", "origin": "synthetic", "level": "synthetic-carrier"},
            permissions=[{"action": "local_read", "purpose": "synthetic_test", "recipient": "local_tool",
                "decision": "allow", "authority_evidence": "synthetic-consent",
                "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z"}],
            environment={}, sensitivity="synthetic", purpose="synthetic_test",
            acquired_at="2026-11-01T00:00:00Z", locator="synthetic-carrier#section-1",
            extraction_status="complete")
        self.assertEqual(snapshot, raw)
        self.spec["dependencies"] = [{"path": evidence["path"], "sha256": evidence["sha256"]}]
        link = {"source_id": "SRC", "source_sha256": self.spec["sources"][0]["sha256"],
                "original_evidence": evidence, "method": "caller_supplied_transcription",
                "scope": "本地合成记录所声明的文字范围", "block_ids": ["Claim", "Spec", "Abstract"],
                "location_status": "located"}
        self.spec["patent_delivery"]["source_derivations"] = [link]
        return link

    def test_original_derivation_missing_is_explicitly_not_performed(self):
        self.add_final_gate_sources()
        self.spec["delivery_stage"] = "final"
        result = self.build()["source_derivations"]
        self.assertEqual(result["status"], "not_performed")
        self.assertEqual(result["original_verification"], "not_performed")
        self.assertEqual(result["records"], [])

    def test_original_derivation_uses_capture_and_actual_source_map_without_authenticating(self):
        link = self.add_source_derivation()
        result = self.build()["source_derivations"]
        self.assertEqual(result["status"], "bindings_checked")
        self.assertEqual(result["coverage"], "declared_scope_only")
        self.assertEqual(result["original_verification"], "not_performed")
        self.assertEqual(result["extraction_authenticity"], "not_verified")
        record = result["records"][0]
        self.assertEqual(record["original_sha256"], link["original_evidence"]["sha256"])
        self.assertEqual(record["source_sha256"], self.spec["sources"][0]["sha256"])
        self.assertNotEqual(record["original_sha256"], record["source_sha256"])
        self.assertEqual(record["evidence_id"], link["original_evidence"]["evidence_id"])
        self.assertEqual(record["original_locator"], "synthetic-carrier#section-1")
        self.assertEqual(record["blocks"][0]["start_line"], 2)
        self.assertEqual(record["blocks"][0]["end_line"], 2)
        self.assertTrue(self.verify()["file_hashes_equal"])
        body = (self.root / "pack/document/body/source.txt").read_bytes()
        self.assertNotIn(b"SYNTHETIC ORIGINAL CARRIER", body)

    def test_original_derivation_mismatches_are_rejected_before_output(self):
        link = self.add_source_derivation()
        original = copy.deepcopy(self.spec)
        changes = [lambda row: row.update(source_id="MissingSource"),
                   lambda row: row.update(source_sha256=row["original_evidence"]["sha256"]),
                   lambda row: row["original_evidence"].update(sha256=row["source_sha256"]),
                   lambda row: row["original_evidence"].update(path="unlisted.bin"),
                   lambda row: row["original_evidence"].update(evidence_id="ev-forged"),
                   lambda row: row.update(block_ids=["MissingBlock"]),
                   lambda row: row["original_evidence"].update(sensitivity="restricted")]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.spec = copy.deepcopy(original)
                change(self.spec["patent_delivery"]["source_derivations"][0])
                with self.assertRaises(ContractError):
                    self.build("mismatch-" + str(index))
                self.assertFalse((self.root / ("mismatch-" + str(index))).exists())
        self.assertNotEqual(link["source_sha256"], link["original_evidence"]["sha256"])

    def test_original_and_derived_file_tampering_is_rejected_by_actual_consumer(self):
        self.add_source_derivation()
        self.build()
        for name in ("original.bin", "manuscript.txt"):
            with self.subTest(file=name):
                path = self.root / name
                raw = path.read_bytes()
                path.write_bytes(raw + b"changed")
                try:
                    with self.assertRaises(ContractError):
                        self.verify()
                finally:
                    path.write_bytes(raw)

    def test_updating_dependency_or_source_hash_cannot_reuse_old_extraction_link(self):
        self.add_source_derivation()
        original = copy.deepcopy(self.spec)
        for name, field in (("original.bin", "dependencies"), ("manuscript.txt", "sources")):
            with self.subTest(file=name):
                self.spec = copy.deepcopy(original)
                path = self.root / name
                raw = path.read_bytes()
                changed = raw + b" changed"
                path.write_bytes(changed)
                self.spec[field][0]["sha256"] = sha256_bytes(changed)
                try:
                    with self.assertRaises(ContractError):
                        self.build("new-" + field)
                    self.assertFalse((self.root / ("new-" + field)).exists())
                finally:
                    path.write_bytes(raw)

    def test_partial_unlocated_or_unmapped_derivation_never_upgrades_original_verification(self):
        self.add_fidelity()
        self.add_source_derivation()
        original = copy.deepcopy(self.spec)
        cases = [lambda row: row["original_evidence"].update(extraction_status="partial"),
                 lambda row: row["original_evidence"].update(extraction_status="ocr_uncertain"),
                 lambda row: row.update(location_status="unlocated"),
                 lambda row: row.update(block_ids=["Claim"])]
        for index, change in enumerate(cases):
            with self.subTest(index=index):
                self.spec = copy.deepcopy(original)
                change(self.spec["patent_delivery"]["source_derivations"][0])
                result = self.build("partial-" + str(index))
                self.assertEqual(result["source_derivations"]["coverage"], "partial")
                self.assertEqual(result["source_derivations"]["original_verification"], "not_performed")
                self.assertFalse(result["checks_ready"])
                self.spec["delivery_stage"] = "final"
                with self.assertRaisesRegex(ContractError, "patent_final_requirements_missing"):
                    self.build("final-" + str(index))
                self.assertFalse((self.root / ("final-" + str(index))).exists())

    def test_derivation_scope_change_invalidates_serialized_confirmation(self):
        self.add_fidelity()
        link = self.add_source_derivation()
        self.build()
        ledger = VersionLedger()
        identity = self.confirm(ledger, self.bind(ledger))
        state = ledger.export()
        restored = VersionLedger(state["records"], state["reviews"])
        link["scope"] = "新的合成提取范围"
        self.build("next")
        self.bind(restored, "next")
        self.assertFalse(restored.is_current(identity))

    def test_derivation_report_cannot_be_promoted_by_rewriting_hashes(self):
        self.add_source_derivation()
        self.build()
        path = self.root / "pack/internal/delivery-review.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["source_derivations"]["original_verification"] = "complete"
        raw = canonical_bytes(report) + b"\n"
        path.write_bytes(raw)
        manifest_path = self.root / "pack/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        row = next(item for item in manifest["files"] if item["path"] == "internal/delivery-review.json")
        row.update(sha256=sha256_bytes(raw), bytes=len(raw))
        manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
        with self.assertRaisesRegex(ContractError, "patent_internal_report_changed"):
            self.verify()

    def test_actual_manuscript_internal_isolation_and_inventory(self):
        manifest = self.build()
        self.assertEqual(manifest["completeness"], "complete_declared_roles")
        self.assertEqual(manifest["delivery_state"], "internal_draft")
        self.assertEqual(manifest["fidelity"], "not_performed")
        path = self.root / "pack/document/body/document.docx"
        report = document_review.review_docx(path.read_bytes())
        text = "\n".join(row["text"] for row in report["current"]["blocks"])
        for line in self.lines[:4]:
            self.assertIn(line, text)
        self.assertNotIn(self.lines[4], text)
        self.assertIn(self.lines[4], (self.root / "pack/document/internal/notes.txt").read_text(encoding="utf-8"))
        purposes = {row["path"]: row["purpose"] for row in manifest["files"]}
        self.assertEqual(purposes["document/body/document.docx"], "manuscript_candidate")
        self.assertEqual(purposes["document/internal/notes.txt"], "internal_only")
        self.assertNotIn("manifest.json", purposes)
        self.assertEqual(manifest["professional_review"], "not_performed")
        self.assertTrue(self.verify()["file_hashes_equal"])

    def test_missing_role_is_incomplete_draft_and_final_is_blocked(self):
        self.spec["patent_delivery"]["expected_roles"]["abstract"] = ["MissingAbstract"]
        manifest = self.build()
        self.assertEqual(manifest["completeness"], "incomplete")
        self.assertIn("patent_role_block_missing", {row["code"] for row in manifest["issues"]})
        self.spec["delivery_stage"] = "final"
        with self.assertRaisesRegex(ContractError, "patent_final_requirements_missing"):
            self.build("final")
        self.assertFalse((self.root / "final").exists())

    def test_internal_block_cannot_satisfy_claims(self):
        self.spec["patent_delivery"]["expected_roles"]["claims"] = ["Notes"]
        self.assertEqual(self.build()["completeness"], "incomplete")

    def test_role_reuse_cannot_disguise_missing_parts(self):
        self.spec["patent_delivery"]["expected_roles"]["abstract"] = ["Claim"]
        self.assertEqual(self.build()["completeness"], "incomplete")

    def test_drawings_need_explicit_applicability_and_actual_members(self):
        self.spec["patent_delivery"]["drawings"].pop("not_applicable_reason")
        with self.assertRaisesRegex(ContractError, "patent_drawings_reason_required"):
            self.build()
        self.spec["patent_delivery"]["drawings"] = {"applicable": True, "figure_ids": ["MissingFigure"]}
        self.assertEqual(self.build()["completeness"], "incomplete")

    def test_no_fidelity_does_not_upgrade_final(self):
        self.spec["delivery_stage"] = "final"
        with self.assertRaisesRegex(ContractError, "patent_final_requirements_missing"):
            self.build()
        self.assertFalse((self.root / "pack").exists())

    def test_bound_final_is_only_a_review_candidate(self):
        self.add_final_gate_sources()
        self.spec["delivery_stage"] = "final"
        manifest = self.build()
        self.assertEqual(manifest["delivery_state"], "candidate_needs_professional_review")
        self.assertEqual(manifest["fidelity"], "checked")
        self.assertEqual(manifest["professional_review"], "not_performed")
        self.assertEqual(manifest["visual_review"], "not_performed")
        self.assertEqual(manifest["external_action"], "not_performed")
        self.assertTrue(self.verify()["file_hashes_equal"])

    def test_final_recognized_heading_is_context_but_unknown_heading_is_checked(self):
        self.add_final_gate_sources()
        self.spec["delivery_stage"] = "final"
        self.lines.append("权利要求书")
        self.write_source()
        self.spec["blocks"].append({"id": "Heading", "source_id": "SRC", "start_line": 6,
                                    "end_line": 6, "kind": "heading1", "audience": "body"})
        self.spec["patent_delivery"]["expected_roles"]["claims"].append("Heading")
        self.add_fidelity()
        self.assertEqual("checked", self.build()["final_text_gate"]["status"])
        self.lines[5] = "一旦许可成立，就允许发布。"
        self.write_source()
        self.add_fidelity()
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            self.build("bad-heading")
        self.assertFalse((self.root / "bad-heading").exists())

    def test_final_body_direction_is_checked_before_any_output(self):
        self.add_final_gate_sources()
        self.lines[1] = "一旦许可成立，就允许发布。"
        self.write_source()
        self.add_fidelity()  # 旧形式化记录可通过；正文门禁必须独立拒绝。
        self.spec["delivery_stage"] = "final"
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            self.build()
        self.assertFalse((self.root / "pack").exists())

    def test_generic_documents_final_cannot_bypass_the_same_gate(self):
        self.add_final_gate_sources()
        self.lines[1] = "一旦许可成立，就允许发布。"
        self.write_source()
        self.add_fidelity()
        self.spec["delivery_stage"] = "final"
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            self.delivery.documents.build(self.root, self.spec, "direct", synthetic=True)
        self.assertFalse((self.root / "direct").exists())

    def test_missing_final_gate_prevents_ordinary_accepted_continuation(self):
        self.add_fidelity()
        self.build()
        ledger = VersionLedger()
        identity = self.confirm(ledger, self.bind(ledger))
        status = self.delivery.confirmation_status(ledger, identity, self.root, self.spec, "pack", synthetic=True)
        self.assertFalse(status["may_continue"])
        self.assertTrue(status["binding_current"])

    def test_final_gate_report_is_rechecked_not_trusted_from_manifest(self):
        self.add_final_gate_sources()
        self.spec["delivery_stage"] = "final"
        manifest = self.build()
        self.assertEqual("checked", manifest["final_text_gate"]["status"])
        path = self.root / "pack/document/internal/final-text-gate.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["natural_language_verified"] = True
        changed = canonical_bytes(report) + b"\n"
        path.write_bytes(changed)
        child = self.root / "pack/document/manifest.json"
        child_manifest = json.loads(child.read_text(encoding="utf-8"))
        row = next(row for row in child_manifest["files"] if row["path"] == "internal/final-text-gate.json")
        row.update(sha256=sha256_bytes(changed), bytes=len(changed))
        child.write_bytes(canonical_bytes(child_manifest) + b"\n")
        with self.assertRaisesRegex(ContractError, "document_final_gate_report_changed"):
            self.verify()

    def test_notice_is_required_inside_the_actual_body(self):
        self.lines[0] = "正式可提交申请文件"
        self.write_source()
        with self.assertRaisesRegex(ContractError, "patent_working_notice_required"):
            self.build()
        self.assertFalse((self.root / "pack").exists())

    def test_research_and_real_material_cannot_borrow_synthetic_entry(self):
        with self.assertRaisesRegex(ContractError, "patent_synthetic_only"):
            self.delivery.prepare(self.root, self.spec, "pack")
        self.spec["sensitivity"] = "public"
        self.spec["research_materials"] = []
        with self.assertRaisesRegex(ContractError, "patent_synthetic_only"):
            self.build()
        self.assertFalse((self.root / "pack").exists())

    def test_build_failure_cannot_leave_success_manifest(self):
        with patch.object(self.delivery.documents, "build", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                self.build()
        self.assertFalse((self.root / "pack/manifest.json").exists())

    def test_no_overwrite_and_new_members_are_rejected(self):
        self.build()
        with self.assertRaisesRegex(ContractError, "output_exists"):
            self.build()
        (self.root / "pack/private.txt").write_text("synthetic", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "patent_package_members_changed"):
            self.verify()

    def test_actual_modified_docx_and_old_hash_cannot_confirm(self):
        self.build()
        ledger = VersionLedger()
        binding = self.bind(ledger)
        path = self.root / "pack/document/body/document.docx"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(ContractError):
            self.confirm(ledger, binding)
        self.assertFalse(any("/confirmation/" in key for key in ledger.records))

    def test_changed_source_cannot_reuse_old_manifest(self):
        self.build()
        ledger = VersionLedger()
        binding = self.bind(ledger)
        self.lines[1] = "许可成立即自动发布。"
        self.write_source()
        with self.assertRaises(ContractError):
            self.confirm(ledger, binding)

    def test_confirmation_reject_conditional_and_serialization_are_separate(self):
        self.add_final_gate_sources()
        self.build()
        ledger = VersionLedger()
        binding = self.bind(ledger)
        for decision, conditions in (("accepted", []), ("conditional", ["等待专业复核"]),
                                     ("rejected", []), ("accepted", ["等待专业复核"])):
            with self.subTest(decision=decision, conditions=conditions):
                identity = self.confirm(ledger, binding, decision, conditions, identity=str((decision, conditions)))
                state = json.loads(json.dumps(ledger.export()))
                restored = VersionLedger(state["records"], state["reviews"])
                current = self.delivery.confirmation_status(restored, identity, self.root, self.spec, "pack", synthetic=True)
                self.assertTrue(current["binding_current"])
                self.assertEqual(current["may_continue"], decision == "accepted" and not conditions)
                self.assertEqual(current["professional_review"], "not_performed")
                self.assertEqual(current["identity_verification"], "caller_responsibility")
                self.assertEqual(restored.reviews, [])

    def test_confirmation_status_does_not_mutate_recorded_conditions(self):
        self.add_fidelity()
        self.build()
        ledger = VersionLedger()
        identity = self.confirm(ledger, self.bind(ledger), "accepted", ["等待专业复核"])
        status = self.delivery.confirmation_status(ledger, identity, self.root, self.spec, "pack", synthetic=True)
        status["conditions"].clear()
        again = self.delivery.confirmation_status(ledger, identity, self.root, self.spec, "pack", synthetic=True)
        self.assertFalse(again["may_continue"])
        self.assertEqual(again["conditions"], ["等待专业复核"])

    def test_confirmation_status_rechecks_bytes_and_same_bytes_copy_has_no_confirmation(self):
        self.build()
        self.build("copy")
        ledger = VersionLedger()
        identity = self.confirm(ledger, self.bind(ledger))
        state = self.delivery.confirmation_status(ledger, identity, self.root, self.spec, "copy", synthetic=True)
        self.assertFalse(state["binding_current"])
        path = self.root / "pack/document/body/document.docx"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(ContractError):
            self.delivery.confirmation_status(ledger, identity, self.root, self.spec, "pack", synthetic=True)

    def test_source_map_keeps_source_file_and_resolved_text_hashes_distinct(self):
        self.build()
        mapping = json.loads((self.root / "pack/document/internal/source-map.json").read_text(encoding="utf-8"))
        self.assertEqual(mapping["sources"][0]["sha256"], self.spec["sources"][0]["sha256"])
        claim = next(row for row in mapping["blocks"] if row["id"] == "Claim")
        self.assertEqual(claim["text_sha256"], sha256_bytes(self.lines[1].encode("utf-8")))
        self.assertNotEqual(claim["text_sha256"], mapping["sources"][0]["sha256"])
        self.assertEqual((claim["source_id"], claim["start_line"], claim["end_line"]), ("SRC", 2, 2))

    def test_rewritten_manifest_cannot_hide_changed_actual_body(self):
        self.build()
        ledger = VersionLedger()
        binding = self.bind(ledger)
        path = self.root / "pack/document/body/document.docx"
        def change(tree):
            for node in tree.iter(W + "t"):
                if node.text == self.lines[1]:
                    node.text = "取得许可即自动发布。"
        raw = edit_docx(path.read_bytes(), change)
        path.write_bytes(raw)
        manifest_path = self.root / "pack/document/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        row = next(item for item in manifest["files"] if item["path"] == "body/document.docx")
        row.update(sha256=sha256_bytes(raw), bytes=len(raw))
        manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
        with self.assertRaises(ContractError):
            self.confirm(ledger, binding)

    def test_incomplete_or_unchecked_confirmation_never_allows_continuation(self):
        self.build()
        ledger = VersionLedger()
        identity = self.confirm(ledger, self.bind(ledger))
        state = self.delivery.confirmation_status(ledger, identity, self.root, self.spec, "pack", synthetic=True)
        self.assertTrue(state["binding_current"])
        self.assertFalse(state["may_continue"])

    def test_confirmations_require_explicit_actor_time_decision_and_conditions(self):
        self.build()
        ledger = VersionLedger()
        binding = self.bind(ledger)
        event = {"id": "invalid", "actor_id": "synthetic", "actor_type": "human", "stage": "internal_review",
                 "decision": "accepted", "conditions": [], "confirmed_at": "2026-11-01T00:00:00Z",
                 "manifest_sha256": binding["manifest_sha256"]}
        for key in ("actor_id", "confirmed_at", "decision", "conditions"):
            changed = copy.deepcopy(event)
            changed.pop(key)
            with self.subTest(key=key), self.assertRaises(ContractError):
                self.delivery.record_confirmation(ledger, binding, changed, self.root, self.spec, "pack", synthetic=True)
        event["confirmed_at"] = "2999-01-01T00:00:00Z"
        with self.assertRaises(ContractError):
            self.delivery.record_confirmation(ledger, binding, event, self.root, self.spec, "pack", synthetic=True)

    def test_restored_confirmation_invalidates_on_scope_purpose_rules_and_source(self):
        self.build()
        ledger = VersionLedger()
        identity = self.confirm(ledger, self.bind(ledger))
        self.spec["patent_delivery"]["project_id"] = "UNRELATED"
        self.build("unrelated")
        other_binding = self.bind(ledger, "unrelated")
        other_id = other_binding["package_id"]
        self.spec["patent_delivery"]["project_id"] = "SYNTHETIC-PATENT"
        state = ledger.export()
        for field in ("scope", "purpose", "rules", "source"):
            with self.subTest(field=field):
                restored = VersionLedger(state["records"], state["reviews"])
                before = copy.deepcopy(self.spec)
                if field == "source":
                    self.lines[1] += " 此句为新的合成版本。"
                    self.write_source()
                elif field == "rules":
                    self.spec["patent_delivery"][field][0]["version"] = "2"
                else:
                    self.spec["patent_delivery"][field] += " changed"
                self.build("changed-" + field)
                self.bind(restored, "changed-" + field)
                self.assertFalse(restored.is_current(identity))
                self.assertTrue(restored.is_current(other_id))
                exported = restored.export()
                again = VersionLedger(exported["records"], exported["reviews"])
                self.assertFalse(again.is_current(identity))
                self.spec = before

    def test_figure_change_invalidates_after_restore_and_real_readback(self):
        self.add_figure()
        self.build()
        ledger = VersionLedger()
        identity = self.confirm(ledger, self.bind(ledger))
        state = ledger.export()
        restored = VersionLedger(state["records"], state["reviews"])
        path = self.root / "figure.svg"
        raw = path.read_bytes().replace(b">A<", b">B<")
        path.write_bytes(raw)
        figure = self.spec["figures"][0]
        figure["svg"]["sha256"] = sha256_bytes(raw)
        figure["render_binding"] = digest({"svg": figure["svg"]["sha256"], "png": figure["png"]["sha256"]})
        self.build("changed")
        self.bind(restored, "changed")
        self.assertFalse(restored.is_current(identity))

    def test_edit_readback_detects_condition_bookmark_hidden_revision_and_figure_label(self):
        self.add_figure()
        self.build()
        baseline = (self.root / "pack/document/body/document.docx").read_bytes()

        def claim_change(tree):
            for node in tree.iter(W + "t"):
                if node.text == self.lines[1]:
                    node.text = "一种合成发布系统，只要许可即自动发布。"

        def bookmark_change(tree):
            for parent in tree.iter():
                for node in list(parent):
                    if node.tag == W + "bookmarkStart" and node.get(W + "name") == "Claim":
                        parent.remove(node)

        def hidden_change(tree):
            paragraph = tree.find("./" + W + "body/" + W + "p")
            insertion = ET.SubElement(paragraph, W + "ins", {W + "id": "99"})
            run = ET.SubElement(insertion, W + "r")
            ET.SubElement(ET.SubElement(run, W + "rPr"), W + "vanish")
            ET.SubElement(run, W + "t").text = "隐藏合成修订"

        def figure_change(tree):
            for node in tree.iter():
                if node.tag.endswith("}docPr"):
                    node.set("name", "ChangedFigureLabel")

        condition = document_review.review_docx(edit_docx(baseline, claim_change), baseline)
        claim = next(row for row in condition["comparison"]["paired_bookmarks"] if row["name"] == "Claim")
        self.assertFalse(claim["text_equal"])
        bookmarks = document_review.review_docx(edit_docx(baseline, bookmark_change), baseline)
        self.assertEqual(bookmarks["comparison"]["state"], "partial")
        hidden = document_review.review_docx(edit_docx(baseline, hidden_change), baseline)
        self.assertEqual(hidden["current"]["readback_state"], "partial")
        self.assertEqual(hidden["professional_review"], "not_performed")
        figure = document_review.review_docx(edit_docx(baseline, figure_change), baseline)
        self.assertTrue(figure["comparison"]["unresolved_drawings"])


if __name__ == "__main__":
    unittest.main()
