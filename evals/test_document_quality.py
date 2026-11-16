"""SE-03：无语义映射也必须扫描实际文档，合成临时材料且不运行Office。"""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools import documents, fidelity
from tools.core import ContractError, canonical_bytes, sha256_bytes
from evals.test_fidelity_placeholders import bound_case


def source_case(root, text, *, stage="draft", research=False):
    raw = text.encode("utf-8")
    (root / "source.txt").write_bytes(raw)
    spec = {"document_id": "QualityExample", "version": "1", "business": "standard",
            "sensitivity": "research_example" if research else "synthetic",
            "delivery_stage": stage,
            "sources": [{"id": "S", "path": "source.txt", "sha256": sha256_bytes(raw)}],
            "blocks": [{"id": "Clause", "kind": "paragraph", "audience": "body",
                        "source_id": "S", "start_line": 1, "end_line": len(text.splitlines())}]}
    if research:
        spec["research_materials"] = [{"path": "source.txt", "sha256": sha256_bytes(raw),
            "content_kind": "original_synthetic", "third_party_text": "not_included",
            "processing_basis": "Original synthetic unit fixture.",
            "export_basis": "Original synthetic fixture, local test output only."}]
    return spec


def repack(raw, parts):
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        payload = {name: package.read(name) for name in package.namelist()}
    payload.update(parts)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        for name, value in payload.items():
            package.writestr(name, value)
    return stream.getvalue()


class DocumentQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-quality-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_no_fidelity_final_marker_is_blocked_before_output(self):
        spec = source_case(self.root, "仅当A成立。[待确认：测量条件]", stage="final")
        with self.assertRaisesRegex(ContractError, "document_quality_blocked"):
            documents.build(self.root, spec, "pack", synthetic=True)
        self.assertFalse((self.root / "pack").exists())

    def test_draft_retains_unknown_with_blocked_quality(self):
        spec = source_case(self.root, "[TO CONFIRM: 条件尚缺，不推断默认值]")
        result = documents.build(self.root, spec, "pack", synthetic=True)
        self.assertEqual("blocked", result["quality"]["status"])
        self.assertEqual("internal_draft", result["delivery_state"])
        self.assertEqual("not_performed", result["quality"]["semantic_fidelity"])
        self.assertIn("TO CONFIRM", (self.root / "pack/body/source.txt").read_text(encoding="utf-8"))
        checked = documents.verify(self.root, spec, "pack", synthetic=True)
        self.assertEqual(result["quality"], checked["quality"])

    def test_research_also_scanned_without_optional_fidelity(self):
        spec = source_case(self.root, "全文符合。[待补证：样本记录]", research=True)
        report = documents.build(self.root, spec, "pack", research_example=True)
        self.assertEqual("blocked", report["quality"]["status"])
        self.assertNotIn("fidelity", report)
        self.assertEqual("research_example", report["mode"])
        documents.verify(self.root, spec, "pack", research_example=True)

    def test_quality_report_recomputed_even_if_manifest_rehashed(self):
        spec = source_case(self.root, "不能由结构检查推定全文符合。")
        documents.build(self.root, spec, "pack", synthetic=True)
        report_path = self.root / "pack/internal/quality-review.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report.update(status="checked", issues=[])
        changed = canonical_bytes(report) + b"\n"
        report_path.write_bytes(changed)
        manifest_path = self.root / "pack/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        row = next(r for r in manifest["files"] if r["path"] == "internal/quality-review.json")
        row.update(sha256=sha256_bytes(changed), bytes=len(changed))
        manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
        with self.assertRaisesRegex(ContractError, "document_quality_report_changed"):
            documents.verify(self.root, spec, "pack", synthetic=True)

    def test_quality_scans_actual_docx_not_supplied_blocks(self):
        raw = documents.make_docx([{"id": "P", "kind": "paragraph", "text": "确定内容。"}], [])
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = package.read("word/document.xml")
        changed = repack(raw, {"word/document.xml": xml.replace("确定内容。".encode(), "[待确认：替换后的文字]".encode())})
        report = documents.inspect_docx_quality(changed, business="standard")
        self.assertEqual("blocked", report["status"])
        self.assertEqual(sha256_bytes(changed), report["artifact_sha256"])

    def test_same_version_legacy_resolution_never_clears_actual_quality(self):
        text = "系统发布时须已取得许可。[TO CONFIRM: 许可是否已取得]"
        payload, texts, bindings = bound_case(text, resolved=[{
            "id": "D#" + str(text.index("[")), "resolution_source": "1", "reviewer": "合成负责人"}])
        legacy = fidelity.audit_bound_text(payload, texts, bindings)
        self.assertEqual("checked", legacy["status"])
        spec = source_case(self.root, text, stage="final")
        spec["business"] = "patent"
        spec["fidelity"] = {"payload": payload, "blocks": {"Clause": next(iter(bindings.values()))}}
        spec["fidelity"]["payload"]["placeholder_resolutions"][0]["id"] = "Clause#" + str(text.index("["))
        with self.assertRaisesRegex(ContractError, "document_quality_blocked"):
            documents.build(self.root, spec, "pack", synthetic=True)

    def test_quote_negation_and_qualification_remain_review_not_rewrite(self):
        for text in ["原意见为“全文符合”，此处仅引用原文。", "不能宣称全文符合。", "本次验证通过仅指结构校验。"]:
            with self.subTest(text=text):
                original = {"P": text}
                report = fidelity.audit_text_quality(original, business="standard")
                self.assertEqual("needs_review", report["status"])
                self.assertTrue(all(row["severity"] == "review" for row in report["issues"]))
                self.assertEqual({"P": text}, original)
                self.assertTrue(all("context" in row and "end" in row for row in report["issues"]))

    def test_empty_coverage_not_checked(self):
        report = fidelity.audit_text_quality({}, business="standard")
        self.assertEqual("partial", report["coverage"]["state"])
        self.assertNotEqual("checked", report["status"])

    def test_tables_headers_comments_revisions_and_hidden_runs_are_scanned(self):
        blocks = [{"id": "T", "kind": "table", "text": "unused", "cells": [["条件"], ["[待核实：数值]"]]}]
        raw = documents.make_docx(blocks, [])
        ns = ' xmlns:w="' + documents.W + '"'
        changed = repack(raw, {
            "word/header1.xml": ('<w:hdr' + ns + '><w:p><w:r><w:t>全文符合</w:t></w:r></w:p></w:hdr>').encode(),
            "word/comments.xml": ('<w:comments' + ns + '><w:comment><w:p><w:r><w:t>[待确认：批注]</w:t></w:r></w:p></w:comment></w:comments>').encode(),
            "word/footer1.xml": ('<w:ftr' + ns + '><w:p><w:del><w:r><w:delText>[待补证：删除文字]</w:delText></w:r></w:del><w:r><w:rPr><w:vanish/></w:rPr><w:t>[待确认：隐藏]</w:t></w:r></w:p></w:ftr>').encode()})
        report = documents.inspect_docx_quality(changed)
        self.assertEqual("blocked", report["status"])
        locations = {hit["block_id"].split("#")[0] for hit in report["issues"] if "block_id" in hit}
        self.assertTrue({"word/document.xml", "word/header1.xml", "word/footer1.xml", "word/comments.xml"} <= locations)

    def test_unsupported_objects_have_partial_coverage(self):
        raw = documents.make_docx([{"id": "P", "kind": "paragraph", "text": "合成正文。"}], [])
        changed = repack(raw, {"word/embeddings/oleObject1.bin": b"synthetic-object"})
        report = documents.inspect_docx_quality(changed)
        self.assertEqual("partial", report["coverage"]["state"])
        self.assertTrue(report["coverage"]["unsupported_objects"])
        self.assertNotEqual("checked", report["status"])

    def test_old_manifest_version_cannot_claim_current_quality_protocol(self):
        spec = source_case(self.root, "合成正文。")
        built = documents.build(self.root, spec, "pack", synthetic=True)
        self.assertEqual("1.5", built["generator_version"])
        path = self.root / "pack/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for version in ("1.3", "1.4"):
            with self.subTest(version=version):
                manifest["generator_version"] = version
                path.write_bytes(canonical_bytes(manifest) + b"\n")
                with self.assertRaisesRegex(ContractError, "document_manifest_identity_changed"):
                    documents.verify(self.root, spec, "pack", synthetic=True)

    def test_clean_quality_does_not_assert_semantic_or_professional_review(self):
        spec = source_case(self.root, "仅当A与B同时成立才启动；维护模式除外。", stage="final")
        result = documents.build(self.root, spec, "pack", synthetic=True)
        self.assertEqual("checked", result["quality"]["status"])
        self.assertEqual("not_performed", result["quality"]["semantic_fidelity"])
        self.assertEqual("not_performed", result["professional_review"])
        self.assertEqual("needs_review", result["status"])
        documents.verify(self.root, spec, "pack", synthetic=True)

    def test_low_level_final_scan_reports_issues_without_preventing_internal_candidate(self):
        raw = documents.make_docx([{"id": "P", "kind": "paragraph", "text": "[待确认：未完成]"}], [])
        report = documents.quality_docx(raw, stage="final")
        self.assertEqual("blocked", report["status"])
        self.assertTrue(report["issues"])

    def test_text_outside_supported_paragraph_is_not_silently_omitted(self):
        raw = documents.make_docx([{"id": "P", "kind": "paragraph", "text": "确定正文。"}], [])
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = package.read("word/document.xml")
        xml = xml.replace(b"</w:body>", "<w:t>[待确认：异常位置]</w:t></w:body>".encode())
        report = documents.quality_docx(repack(raw, {"word/document.xml": xml}))
        self.assertEqual("blocked", report["status"])
        self.assertEqual("partial", report["coverage"]["state"])
        self.assertTrue(report["coverage"]["unsupported_objects"])

    def test_v2_page_field_is_scanned_and_remains_unrefreshed_partial(self):
        raw = documents.make_docx([{"id": "P", "kind": "paragraph", "text": "原创合成正文。"}], [],
                                  profile="dyz-standard-internal-v2")
        report = documents.quality_docx(raw, business="standard")
        self.assertEqual("partial", report["coverage"]["state"])
        self.assertIn("word/footer1.xml", report["coverage"]["covered_parts"])
        self.assertIn("word/header1.xml", report["coverage"]["covered_parts"])
        self.assertTrue(any(row["part"] == "word/footer1.xml" and row.get("object") == "instrText"
                            for row in report["coverage"]["unsupported_objects"]))
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            header = package.read("word/header1.xml")
        changed = repack(raw, {"word/header1.xml": header.replace("原创内部工作稿".encode(),
                                                                "[待确认：页眉条件]".encode())})
        actual = documents.quality_docx(changed, business="standard", stage="final")
        self.assertEqual("blocked", actual["status"])
        self.assertTrue(any(row.get("block_id", "").startswith("word/header1.xml#")
                            for row in actual["issues"]))

    def test_stage_is_closed_enum(self):
        for stage in (False, "published", ""):
            spec = source_case(self.root, "合成正文。", stage=stage)
            with self.subTest(stage=stage), self.assertRaisesRegex(ContractError, "document_delivery_stage_invalid"):
                documents.build(self.root, spec, "pack", synthetic=True)


if __name__ == "__main__":
    unittest.main()
