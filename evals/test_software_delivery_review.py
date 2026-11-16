"""成品链审查反例：只验证状态传播与检查调用，不是实际 PDF 版式证据。

DOCX 生成/检查、PDF 转换和物理检查全部用确定性合成边界替代；真实准备、
授权入口、成品映射、目录成员及文件指纹检查照常运行。文件仅写入临时目录。
"""

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import core, software


def _synthetic_docx(pages, **metadata):
    """并非 DOCX；避免将其他并行模块的错误误归因为成品链问题。"""
    return core.canonical_bytes({"pages": pages, **metadata})


def _inspect_synthetic_docx(raw, pages, **metadata):
    core.require(raw == _synthetic_docx(pages, **metadata), "synthetic_docx_changed")
    return {"status": "checked", "mock_boundary_not_pdf_evidence": True}


def _synthetic_convert(_executable, docx, destination):
    path = destination / (docx.stem + ".pdf")
    path.write_bytes(b"%PDF-1.7\nSynthetic conversion boundary, not a real PDF.\n")
    return path


class SoftwareDeliveryReviewTests(unittest.TestCase):
    def setUp(self):
        from evals.test_software_prepare import SoftwarePrepareCliTests

        self.case = SoftwarePrepareCliTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.authorization["output"] = "materials"
        self.case.request["delivery"] = {
            "selection": "all", "screenshots": [], "sensitive_literals": []}
        self.case.request["manual_input"]["runtime_evidence"] = [{
            "id": "run1", "version": "1.0", "kind": "transcript",
            "evidence_id": "synthetic-transcript-not-executed",
        }]
        self.case.save_request()
        self.pack = self.case.root / "materials"
        self.converter = self.case.root / "soffice.exe"
        self.extractor = self.case.root / "pdftotext.exe"
        self.converter.write_bytes(b"synthetic converter, never executed")
        self.extractor.write_bytes(b"synthetic extractor, never executed")
        self.inspected_pdfs = []
        for target, replacement in (
            ("tools.documents.make_software_docx", _synthetic_docx),
            ("tools.documents.inspect_software_docx", _inspect_synthetic_docx),
            ("tools.software_delivery._convert", _synthetic_convert),
            ("tools.software_layout.inspect_pdf", self._inspect_synthetic_pdf),
        ):
            patcher = patch(target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _inspect_synthetic_pdf(self, pdf, _pages, **_metadata):
        self.inspected_pdfs.append(Path(pdf).name)
        valid = Path(pdf).read_bytes().startswith(b"%PDF-")
        return {
            "status": "checked" if valid else "blocked",
            "issues": [] if valid else [{"code": "synthetic_invalid_pdf"}],
            "mock_boundary_not_pdf_evidence": True,
        }

    def _args(self):
        self.case.save_request()
        args = self.case.args()
        args[0] = "build-software"
        return args

    def _build_with_synthetic_pdf(self):
        result = self.case.invoke(self._args() + [
            "--pdf-tool", str(self.converter),
            "--pdf-text-tool", str(self.extractor),
        ])
        self.assertIn(result[0], (0, 4), result)
        self.assertEqual(result[2], "", result)
        return result

    def _manifest(self):
        return json.loads((self.pack / "manifest.json").read_text(encoding="utf-8"))

    def test_verify_cannot_upgrade_missing_pdf_by_changing_manifest_status(self):
        self.case.request["manual_input"]["runtime_evidence"] = []
        args = self._args()
        self.assertEqual(self.case.invoke(args), (4, "software_documents_partial\n", ""))
        manifest = self._manifest()
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(manifest["pdf"], "not_generated")
        self.assertIn("pdf_not_generated", manifest["issues"])
        self.assertIn("physical_layout_not_checked", manifest["issues"])
        # 只改清单状态，不改问题列表、文件成员、正文或指纹。
        manifest["status"] = "needs_review"
        (self.pack / "manifest.json").write_bytes(core.canonical_bytes(manifest))

        code, stdout, stderr = self.case.invoke(args + ["--verify"])

        self.assertIn(code, (2, 4), (code, stdout, stderr))
        self.assertNotIn("software_documents_verified_needs_review", stdout)
        self.assertEqual(self.inspected_pdfs, [])

    def test_build_preserves_preparation_form_version_conflict(self):
        form = copy.deepcopy(self.case.request["scope_input"]["metadata"])
        form.update(version="9.9", total_source_lines=3, selected_source_lines=3)
        self.case.request["form"] = form
        context = {**self.case.authorization["context"],
                   "now": datetime.now(timezone.utc).isoformat()}
        payload = {key: value for key, value in self.case.request.items()
                   if key != "delivery"}
        payload["pagination"] = {**payload["pagination"], "selection": "all"}
        prepared = software.prepare({**payload, "authorized_root": str(self.case.root),
                                     "context": context}, use_system_time=True)
        self.assertEqual(prepared["status"], "partial")
        self.assertIn("field_mismatch:version",
                      {row["code"] for row in prepared["issues"]})

        code, stdout, stderr = self._build_with_synthetic_pdf()
        manifest = self._manifest()

        self.assertEqual(manifest["status"], "partial")
        self.assertIn("field_mismatch:version", manifest["issues"])
        self.assertEqual((code, stdout, stderr),
                         (4, "software_documents_partial\n", ""))

    def test_pdf_recheck_covers_head_tail_mother_not_only_selected_body(self):
        source = "".join(f"line_{number}\n" for number in range(1, 3051))
        raw = source.encode("utf-8")
        (self.case.root / "counter.py").write_bytes(raw)
        self.case.authorization["files"][0]["sha256"] = core.sha256_bytes(raw)
        self.case.request["delivery"]["selection"] = "head_tail"
        self._build_with_synthetic_pdf()
        manifest = self._manifest()
        self.assertEqual(manifest["selection_applied"],
                         "head_tail_from_verified_physical_mother")
        self.assertEqual(len(manifest["selected_mother_pages"]), 60)
        self.assertNotIn(31, manifest["selected_mother_pages"])
        self.assertIn("mother.pdf", self.inspected_pdfs)
        mother = self.pack / "internal/mother.pdf"
        mother.write_bytes(b"NOT A PDF: full mother validation is no longer true.")
        # 模拟自洽的被修改交付包；重新计算自报指纹不能替代母本实页重查。
        for row in manifest["files"]:
            if row["path"] == "internal/mother.pdf":
                row.update(sha256=core.sha256_bytes(mother.read_bytes()),
                           bytes=mother.stat().st_size)
        (self.pack / "manifest.json").write_bytes(core.canonical_bytes(manifest))
        self.inspected_pdfs.clear()

        code, stdout, stderr = self.case.invoke(self._args() + [
            "--verify", "--pdf-text-tool", str(self.extractor),
        ])

        self.assertIn("mother.pdf", self.inspected_pdfs,
                      "显式重查不能跳过首尾选择所依赖的完整母本")
        self.assertIn(code, (2, 4), (code, stdout, stderr))
        self.assertNotIn("software_documents_verified_needs_review", stdout)

    def test_internal_markers_are_recorded_without_copying_private_question(self):
        self.case.request["manual_input"]["facts"][0]["text"] = (
            "x" * 70 + "[待确认：SYNTHETIC_PRIVATE_QUESTION] STOP_FOR_USER NEXT_ACTION")
        self._build_with_synthetic_pdf()
        manifest = self._manifest()
        report = manifest.get("text_review", {})
        self.assertEqual(report.get("status"), "needs_review")
        self.assertEqual(manifest["status"], "partial")
        codes = {row["code"] for row in report["issues"]}
        self.assertIn("unresolved_placeholder_in_internal", codes)
        self.assertIn("internal_workflow_marker", codes)
        self.assertIn("unresolved_placeholder_in_internal", manifest["issues"])
        self.assertIn("internal_workflow_marker", manifest["issues"])
        self.assertNotIn("SYNTHETIC_PRIVATE_QUESTION", json.dumps(manifest))
        self.assertEqual(report["coverage"]["image_pixels"], "not_checked")
        self.assertTrue((self.pack / "body/manual.docx").is_file())

    def test_verify_rebuilds_marker_report_instead_of_accepting_forged_clearance(self):
        self.case.request["manual_input"]["facts"][0]["text"] = "[TO CONFIRM: synthetic]"
        self._build_with_synthetic_pdf()
        manifest = self._manifest()
        report = manifest.get("text_review", {})
        self.assertTrue(report.get("issues"), "构建须有实际扫描结果")
        report.update(status="checked", issues=[])
        manifest.update(status="needs_review", issues=[], text_review=report)
        (self.pack / "manifest.json").write_bytes(core.canonical_bytes(manifest))

        code, stdout, stderr = self.case.invoke(self._args() + [
            "--verify", "--pdf-text-tool", str(self.extractor)])

        self.assertEqual((code, stdout, stderr), (2, "", "contract_rejected\n"))

    def _long_manual(self, page_count):
        # 固定短行使说明母本正好为 page_count 个30行候选页；实页由mock代替。
        self.case.request["manual_input"]["facts"] = [
            {"id": f"fact-{number}", "text": f"Synthetic manual line {number}.",
             "evidence_id": "synthetic-fact"}
            for number in range(page_count * 30 - 5)
        ]
        self.case.request["delivery"]["selection"] = "head_tail"

    def test_manual_head_tail_is_independent_from_short_source(self):
        self._long_manual(61)
        self._build_with_synthetic_pdf()
        manifest = self._manifest()
        mapping = json.loads((self.pack / "internal/source-map.json").read_text(
            encoding="utf-8"))
        self.assertEqual(len(mapping["document_pages"]["manual"]), 60)
        self.assertEqual(manifest["selected_mother_pages"], [1])
        expected = list(range(1, 31)) + list(range(32, 62))
        self.assertEqual(manifest["manual_selected_mother_pages"], expected)
        self.assertEqual(mapping["manual"]["selected_mother_pages"], expected)
        self.assertEqual(manifest["manual_selection_applied"],
                         "head_tail_from_verified_physical_mother")
        self.assertIn("manual-mother.pdf", self.inspected_pdfs)
        self.assertTrue((self.pack / "internal/manual-mother.docx").is_file())

    def test_manual_up_to_sixty_pages_keeps_every_mother_page(self):
        for count in (59, 60):
            with self.subTest(count=count):
                self.case.authorization["output"] = f"materials-{count}"
                self.pack = self.case.root / f"materials-{count}"
                self._long_manual(count)
                self._build_with_synthetic_pdf()
                manifest = self._manifest()
                self.assertEqual(manifest["manual_selected_mother_pages"],
                                 list(range(1, count + 1)))
                self.assertEqual(manifest["manual_selection_applied"],
                                 "head_tail_from_verified_physical_mother")
                mapping = json.loads((self.pack / "internal/source-map.json").read_text(
                    encoding="utf-8"))
                self.assertEqual(len(mapping["document_pages"]["manual"]), count)
                self.assertEqual(mapping["manual"]["mother_page_count"], count)

    def test_missing_manual_has_no_mother_and_not_applicable_selection(self):
        del self.case.request["manual_input"]
        self.case.request["delivery"]["selection"] = "head_tail"
        self._build_with_synthetic_pdf()
        manifest = self._manifest()
        self.assertEqual(manifest["manual_selected_mother_pages"], [])
        self.assertEqual(manifest["manual_selection_applied"], "not_applicable")
        self.assertNotIn("manual_mother", manifest["physical_review"])
        self.assertFalse((self.pack / "internal/manual-mother.docx").exists())
        code, _, stderr = self.case.invoke(self._args() + [
            "--verify", "--pdf-text-tool", str(self.extractor)])
        self.assertEqual((code, stderr), (4, ""))

    def test_verify_rebuilds_manual_mother_docx_even_after_manifest_rehash(self):
        self._long_manual(61)
        self._build_with_synthetic_pdf()
        manifest = self._manifest()
        mother = self.pack / "internal/manual-mother.docx"
        mother.write_bytes(b"changed synthetic manual mother document")
        for row in manifest["files"]:
            if row["path"] == "internal/manual-mother.docx":
                row.update(sha256=core.sha256_bytes(mother.read_bytes()),
                           bytes=mother.stat().st_size)
        (self.pack / "manifest.json").write_bytes(core.canonical_bytes(manifest))

        result = self.case.invoke(self._args() + ["--verify"])

        self.assertEqual(result, (2, "", "contract_rejected\n"))

    def test_manual_mother_failure_keeps_full_draft_with_its_own_state(self):
        self._long_manual(61)
        original = self._inspect_synthetic_pdf

        def fail_manual_mother(pdf, pages, **metadata):
            report = original(pdf, pages, **metadata)
            if Path(pdf).name == "manual-mother.pdf":
                report.update(status="blocked", issues=[{"code": "synthetic_layout"}])
            return report

        with patch("tools.software_layout.inspect_pdf", side_effect=fail_manual_mother):
            self._build_with_synthetic_pdf()
        manifest = self._manifest()
        self.assertEqual(manifest["status"], "partial")
        self.assertIn("physical_manual_mother_failed", manifest["issues"])
        self.assertIn("physical_manual_selection_not_verified", manifest["issues"])
        self.assertEqual(manifest["manual_selection_applied"],
                         "all_pending_physical_validation")
        self.assertEqual(manifest["manual_selected_mother_pages"], list(range(1, 62)))
        self.assertEqual(manifest["selection_applied"],
                         "head_tail_from_verified_physical_mother")

    def test_verify_rechecks_manual_mother_and_does_not_inherit_status(self):
        self._long_manual(61)
        self._build_with_synthetic_pdf()
        manifest = self._manifest()
        mother = self.pack / "internal/manual-mother.pdf"
        self.assertTrue(mother.is_file(), "说明选段必须保留可回查的完整母本")
        mother.write_bytes(b"NOT A PDF: changed synthetic manual mother")
        for row in manifest["files"]:
            if row["path"] == "internal/manual-mother.pdf":
                row.update(sha256=core.sha256_bytes(mother.read_bytes()),
                           bytes=mother.stat().st_size)
        manifest["status"] = "needs_review"
        (self.pack / "manifest.json").write_bytes(core.canonical_bytes(manifest))
        self.inspected_pdfs.clear()

        result = self.case.invoke(self._args() + [
            "--verify", "--pdf-text-tool", str(self.extractor)])

        self.assertIn("manual-mother.pdf", self.inspected_pdfs)
        self.assertIn(result[0], (2, 4), result)
        self.assertNotIn("software_documents_verified_needs_review", result[1])


if __name__ == "__main__":
    unittest.main()
