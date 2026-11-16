"""实际导出缺陷、源版本变化和内部材料隔离的回归；无外部程序。"""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from types import SimpleNamespace

from tools import documents
from tools.core import ContractError, sha256_bytes


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-documents-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = '# 合成说明\n连续三个周期均满足且不回绕；≤ 5 μs。\n    return "保存失败"\n私审：合同尚未核实。\n'.encode()
        (self.root / "source.txt").write_bytes(raw)
        self.spec = {"sensitivity": "synthetic", "document_id": "Example", "version": "v1", "business": "patent",
            "sources": [{"id": "S", "path": "source.txt", "sha256": sha256_bytes(raw)}],
            "blocks": [dict(id="Title", kind="heading1", audience="body", source_id="S", start_line=1, end_line=1),
                       dict(id="Claim1", kind="paragraph", audience="body", source_id="S", start_line=2, end_line=2),
                       dict(id="Code1", kind="code", audience="body", source_id="S", start_line=3, end_line=3),
                       dict(id="Note1", kind="paragraph", audience="internal", source_id="S", start_line=4, end_line=4)]}

    def build(self, output="pack"):
        return documents.build(self.root, self.spec, output, synthetic=True)

    def test_source_text_units_conditions_and_internal_separation(self):
        result = self.build()
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["visual_review"], "not_performed")
        self.assertEqual(result["checks"]["paragraphs"], 3)
        text = (self.root / "pack/body/source.txt").read_text(encoding="utf-8")
        self.assertIn("连续三个周期均满足且不回绕；≤ 5 μs。", text)
        self.assertIn('    return "保存失败"', text)
        self.assertNotIn("私审", text)
        with zipfile.ZipFile(self.root / "pack/body/document.docx") as package:
            for name in package.namelist():
                self.assertNotIn("合同尚未核实".encode(), package.read(name))
        mapping = json.loads((self.root / "pack/internal/source-map.json").read_text(encoding="utf-8"))
        self.assertEqual(mapping["blocks"][1]["start_line"], 2)
        self.assertIn("合同尚未核实", (self.root / "pack/internal/notes.txt").read_text(encoding="utf-8"))

    def test_repeat_build_deterministic_bytes_and_no_overwrite(self):
        self.build("first")
        self.build("second")
        for path in (self.root / "first").rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (self.root / "second" / path.relative_to(self.root / "first")).read_bytes())
        before = (self.root / "first/manifest.json").read_bytes()
        with self.assertRaisesRegex(ContractError, "output_exists"):
            self.build("first")
        self.assertEqual(before, (self.root / "first/manifest.json").read_bytes())

    def test_changed_source_rejected_before_writing(self):
        (self.root / "source.txt").write_text("修改了连续条件", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "source_changed"):
            self.build()
        self.assertFalse((self.root / "pack").exists())

    def test_changed_version_changes_binding_preserves_old_package(self):
        first = self.build("v1")
        self.spec["version"] = "v2"
        second = self.build("v2")
        self.assertNotEqual(first["input_sha256"], second["input_sha256"])
        self.assertEqual(json.loads((self.root / "v1/manifest.json").read_text(encoding="utf-8"))["version"], "v1")
        self.assertEqual(second["visual_review"], "not_performed")

    def test_source_or_output_escape_rejected(self):
        with self.assertRaises(ContractError):
            self.build("../escape")
        self.spec["sources"][0]["path"] = "../private.txt"
        with self.assertRaises(ContractError):
            self.build()

    def test_missing_audience_duplicate_ids_and_bad_ranges(self):
        original = copy.deepcopy(self.spec)
        for change in (lambda s: s["blocks"][0].update(audience="unknown"),
                       lambda s: s["blocks"][1].update(id="Title"),
                       lambda s: s["blocks"][1].update(start_line=0),
                       lambda s: s["blocks"][1].update(end_line=50),
                       lambda s: s.update(sensitivity="private")):
            self.spec = copy.deepcopy(original)
            change(self.spec)
            with self.assertRaises(ContractError):
                self.build()
            self.assertFalse((self.root / "pack").exists())

    def test_generated_package_faults_detected(self):
        blocks, figures = documents.resolve_document(self.root, self.spec)
        blocks = [b for b in blocks if b["audience"] == "body"]
        raw = documents.make_docx(blocks, figures)
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            original = {n: source.read(n) for n in source.namelist()}
        faults = {
            "condition_changed": lambda p: p.update({"word/document.xml": p["word/document.xml"].replace("不回绕".encode(), "可回绕".encode())}),
            "hidden_text": lambda p: p.update({"word/document.xml": p["word/document.xml"].replace(b"<w:r>", b"<w:r><w:rPr><w:vanish/></w:rPr>", 1)}),
            "external_relationship": lambda p: p.update({"word/_rels/document.xml.rels": p["word/_rels/document.xml.rels"].replace(b'Target="styles.xml"', b'Target="https://example.invalid" TargetMode="External"')}),
            "comment_added": lambda p: p.update({"word/comments.xml": b"<comments>internal review</comments>"}),
            "private_attachment": lambda p: p.update({"private/contract.txt": "私审：合同尚未核实。".encode()}),
            "text_omitted": lambda p: p.update({"word/document.xml": p["word/document.xml"].replace("连续三个周期".encode(), b"")}),
        }
        for name, change in faults.items():
            with self.subTest(name=name):
                parts = dict(original)
                change(parts)
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w") as package:
                    for part, data in parts.items():
                        package.writestr(part, data)
                with self.assertRaises(ContractError):
                    documents.inspect_generated_docx(output.getvalue(), blocks, figures)

    def test_multiline_tab_and_xml_characters_roundtrip(self):
        raw = '# 标题\na\tb\nc & d < 5\nprivate\n'.encode()
        (self.root / "source.txt").write_bytes(raw)
        self.spec["sources"][0]["sha256"] = sha256_bytes(raw)
        self.spec["blocks"][1].update(start_line=2, end_line=3)
        result = self.build()
        self.assertTrue(result["checks"]["source_text_equal"])
        self.assertIn('a\tb\nc & d < 5', (self.root / "pack/body/source.txt").read_text(encoding="utf-8"))

    def test_explicit_synthetic_declaration_before_read(self):
        with self.assertRaisesRegex(ContractError, "synthetic_declaration_required"):
            documents.build(self.root, {}, "pack")
        self.assertFalse((self.root / "pack").exists())

    def research_spec(self):
        spec = copy.deepcopy(self.spec)
        spec["sensitivity"] = "research_example"
        spec["research_materials"] = [dict(
            path="source.txt", sha256=spec["sources"][0]["sha256"],
            content_kind="original_mixed_research", third_party_text="not_included",
            processing_basis="Original synthetic test text; caller declaration for a test fixture.",
            export_basis="Original test text under repository LICENSE; no third-party text.")]
        return spec

    def test_research_mode_retains_declared_scope_and_body_internal_separation(self):
        spec = self.research_spec()
        result = documents.build(self.root, spec, "research", research_example=True)
        self.assertEqual("research_example", result["mode"])
        self.assertEqual("caller_declarations_not_independently_verified",
                         result["research_scope"]["basis_verification"])
        self.assertEqual("not_performed", result["professional_review"])
        mapping = json.loads((self.root / "research/internal/source-map.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["research_materials"], mapping["research_materials"])
        self.assertNotIn("合同尚未核实", (self.root / "research/body/source.txt").read_text(encoding="utf-8"))
        documents.verify(self.root, spec, "research", research_example=True)

    def test_research_declaration_cannot_be_passed_under_synthetic_flag(self):
        spec = self.research_spec()
        with patch.object(documents, "_read") as read:
            with self.assertRaisesRegex(ContractError, "synthetic_only"):
                documents.build(self.root, spec, "out", synthetic=True)
            spec["sensitivity"] = "synthetic"
            with self.assertRaisesRegex(ContractError, "synthetic_only"):
                documents.build(self.root, spec, "out", synthetic=True)
            with self.assertRaisesRegex(ContractError, "declarations_conflict"):
                documents.build(self.root, spec, "out", synthetic=True, research_example=True)
            read.assert_not_called()

    def test_research_complete_read_set_including_dependency_checked_before_content(self):
        spec = self.research_spec()
        spec["dependencies"] = [{"path": "missing.bin", "sha256": "0" * 64}]
        with patch.object(documents, "_read") as read:
            with self.assertRaisesRegex(ContractError, "coverage_required"):
                documents.build(self.root, spec, "out", research_example=True)
            spec["research_materials"].append({**spec["research_materials"][0],
                "path": "missing.bin", "sha256": "0" * 64, "content_kind": "private"})
            with self.assertRaisesRegex(ContractError, "kind_unsupported"):
                documents.build(self.root, spec, "out", research_example=True)
            read.assert_not_called()
        self.assertFalse((self.root / "out").exists())

    def test_research_unknown_basis_raw_standard_and_unbound_hash_rejected(self):
        for field, value, error in [
            ("processing_basis", "unknown", "use_basis_required"),
            ("export_basis", "", "use_basis_required"),
            ("export_basis", "待核", "use_basis_required"),
            ("content_kind", "third_party_standard_full_text", "kind_unsupported"),
            ("third_party_text", "included", "kind_unsupported"),
            ("sha256", "0" * 64, "binding_changed"),
            ("path", "unbound.txt", "binding_changed")]:
            with self.subTest(field=field, value=value):
                spec = self.research_spec()
                spec["research_materials"][0][field] = value
                with patch.object(documents, "_read") as read:
                    with self.assertRaisesRegex(ContractError, error):
                        documents.build(self.root, spec, "out", research_example=True)
                    read.assert_not_called()

    def test_research_does_not_call_synthetic_fidelity_consumer(self):
        spec = self.research_spec()
        spec["fidelity"] = {}
        with patch.object(documents, "_read") as read:
            with self.assertRaisesRegex(ContractError, "fidelity_not_supported"):
                documents.build(self.root, spec, "out", research_example=True)
            read.assert_not_called()

    def test_research_duplicate_extra_alias_or_unsafe_declarations_never_read(self):
        cases = []
        extra = self.research_spec()
        extra["research_materials"].append(copy.deepcopy(extra["research_materials"][0]))
        cases.append((extra, "coverage_required"))
        alias = self.research_spec()
        alias["dependencies"] = [{"path": "source.txt", "sha256": alias["sources"][0]["sha256"]}]
        cases.append((alias, "read_alias"))
        unsafe = self.research_spec()
        unsafe["research_materials"][0]["path"] = "../outside.txt"
        cases.append((unsafe, "unsafe_path"))
        for spec, error in cases:
            with self.subTest(error=error), patch.object(documents, "_read") as read:
                with self.assertRaisesRegex(ContractError, error):
                    documents.build(self.root, spec, "out", research_example=True)
                read.assert_not_called()

    def test_research_actual_execution_dependency_is_bound_without_synthetic_relabel(self):
        spec = self.research_spec()
        raw = b'Original fixture execution record, not a real user case.\n'
        (self.root / "run.txt").write_bytes(raw)
        spec["dependencies"] = [{"path": "run.txt", "sha256": sha256_bytes(raw)}]
        spec["research_materials"].append({**spec["research_materials"][0],
            "path": "run.txt", "sha256": sha256_bytes(raw), "content_kind": "original_execution_evidence"})
        documents.build(self.root, spec, "out", research_example=True)
        documents.verify(self.root, spec, "out", research_example=True)
        (self.root / "run.txt").write_bytes(raw + b'changed\n')
        with self.assertRaisesRegex(ContractError, "source_changed"):
            documents.verify(self.root, spec, "out", research_example=True)

    def test_research_manifest_scope_tampering_and_old_input_reuse_rejected(self):
        spec = self.research_spec()
        documents.build(self.root, spec, "out", research_example=True)
        path = self.root / "out/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["research_scope"]["materials"][0]["content_kind"] = "original_synthetic"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "research_scope_changed"):
            documents.verify(self.root, spec, "out", research_example=True)
        spec["version"] = "v2"
        with self.assertRaisesRegex(ContractError, "input_binding_changed"):
            documents.verify(self.root, spec, "out", research_example=True)

    def test_research_cli_build_and_verify_preserve_declared_mode(self):
        spec = self.research_spec()
        (self.root / "input.json").write_text(json.dumps(spec), encoding="utf-8")
        args = ["--research-example", "--root", str(self.root), "--input", "input.json", "--output", "out"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, documents.main(args))
            self.assertEqual(0, documents.main(args + ["--verify"]))
        manifest = json.loads((self.root / "out/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("research_example", manifest["mode"])

    def test_pdf_tool_requires_explicit_existing_absolute_path(self):
        with self.assertRaisesRegex(ContractError, "pdf_tool_absolute_file_required"):
            documents.build(self.root, self.spec, "pack", synthetic=True, pdf_tool="soffice")
        self.assertFalse((self.root / "pack").exists())

    def test_pdf_failure_retains_docx_but_does_not_write_success_manifest(self):
        executable = self.root / "soffice.exe"
        executable.write_bytes(b"synthetic test only")
        with patch.object(documents.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaisesRegex(ContractError, "pdf_conversion_failed"):
                documents.build(self.root, self.spec, "pack", synthetic=True, pdf_tool=str(executable))
        self.assertTrue((self.root / "pack/body/document.docx").is_file())
        self.assertFalse((self.root / "pack/manifest.json").exists())
        self.assertIsInstance(run.call_args.args[0], list)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_cli_requires_declaration_and_rejects_duplicate_input_keys(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = documents.main(["--root", str(self.root), "--input", "missing.json", "--output", "pack"])
        self.assertEqual(code, 2)
        (self.root / "input.json").write_text('{"sensitivity":"synthetic","sensitivity":"private"}', encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code = documents.main(["--synthetic", "--root", str(self.root), "--input", "input.json", "--output", "pack"])
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "pack").exists())

    def test_existing_pack_verified_but_extra_attachment_rejected(self):
        self.build()
        result = documents.verify(self.root, self.spec, "pack", synthetic=True)
        self.assertEqual(result["status"], "needs_review")
        (self.root / "pack/body/internal-review.txt").write_text("not for recipient")
        with self.assertRaisesRegex(ContractError, "directory_members_changed"):
            documents.verify(self.root, self.spec, "pack", synthetic=True)

    def test_changed_body_rejected_even_when_manifest_rehashed(self):
        self.build()
        body = self.root / "pack/body/source.txt"
        body.write_bytes(body.read_bytes().replace("不回绕".encode(), "可回绕".encode()))
        path = self.root / "pack/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        row = next(r for r in manifest["files"] if r["path"] == "body/source.txt")
        row.update(sha256=sha256_bytes(body.read_bytes()), bytes=body.stat().st_size)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "text_file_changed"):
            documents.verify(self.root, self.spec, "pack", synthetic=True)

    def test_version_changed_existing_pack_is_stale(self):
        self.build()
        self.spec["version"] = "v2"
        with self.assertRaisesRegex(ContractError, "input_binding_changed"):
            documents.verify(self.root, self.spec, "pack", synthetic=True)

    def test_binary_dependency_is_bound_without_entering_document_body(self):
        evidence = self.root / 'evidence.png'
        evidence.write_bytes(b'\x89PNG\x00\xff synthetic evidence')
        self.spec['dependencies'] = [{'path': 'evidence.png', 'sha256': sha256_bytes(evidence.read_bytes())}]
        self.build()
        documents.verify(self.root, self.spec, 'pack', synthetic=True)
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_text(encoding='utf-8'))
        self.assertEqual(self.spec['dependencies'], mapping['dependencies'])
        with zipfile.ZipFile(self.root / 'pack/body/document.docx') as package:
            self.assertNotIn('word/media/evidence.png', package.namelist())
        evidence.write_bytes(b'changed evidence')
        with self.assertRaisesRegex(ContractError, 'document_source_changed'):
            documents.verify(self.root, self.spec, 'pack', synthetic=True)

    def test_dependency_may_not_escape_authorized_root(self):
        self.spec['dependencies'] = [{'path': '../outside.png', 'sha256': '0' * 64}]
        with self.assertRaises(ContractError):
            self.build()
        self.assertFalse((self.root / 'pack').exists())

    def test_manifest_identity_cannot_disagree_with_frozen_input(self):
        self.build()
        path = self.root / 'pack/manifest.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for field, value in [('document_id', 'AnotherCase'), ('version', 'v2'),
                             ('business', 'software'), ('mode', 'private'),
                             ('generator', 'another-generator'), ('generator_version', '0.0')]:
            with self.subTest(field=field):
                manifest = {**original, field: value}
                path.write_text(json.dumps(manifest), encoding='utf-8')
                with self.assertRaisesRegex(ContractError, 'manifest_identity_changed'):
                    documents.verify(self.root, self.spec, 'pack', synthetic=True)


class StandardRenderingV2Tests(unittest.TestCase):
    PROFILE = "dyz-standard-internal-v2"
    W = "{" + documents.W + "}"

    def fixture(self):
        return [
            {"id": "Title", "kind": "title", "text": "原创内部标准工作稿"},
            {"id": "Contents", "kind": "field", "field_type": "TOC"},
            *[{"id": f"H{level}", "kind": f"heading{level}",
               "text": ".".join(["1"] * level) + " 合成层级"}
              for level in range(1, 5)],
            {"id": "Annex", "kind": "heading1", "annex": True,
             "text": "附录A 合成附录"},
            {"id": "AnnexSub", "kind": "heading2", "annex": True,
             "text": "A.1 合成附录节"},
            {"id": "Table", "kind": "table", "table_profile": "dyz-comment-six-column-v1",
             "cells": [["序号", "条款", "原意见", "决定", "理由", "落实／状态"],
                       ["1", "1.1", "原创长意见。" * 300, "拟议采纳", "理由。" * 300, "待审"]]},
            {"id": "PageRef", "kind": "field", "field_type": "PAGEREF", "target": "H4"},
        ]

    def test_v2_header_footer_page_relationships_content_types_and_continuity(self):
        blocks = self.fixture()
        raw = documents.make_docx(blocks, [], profile=self.PROFILE)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            self.assertTrue({"word/header1.xml", "word/footer1.xml"} <= set(package.namelist()))
            xml = documents.ET.fromstring(package.read("word/document.xml"))
            rels = documents.ET.fromstring(package.read("word/_rels/document.xml.rels"))
            content_types = package.read("[Content_Types].xml")
            types = documents.ET.fromstring(content_types)
            footer = documents.ET.fromstring(package.read("word/footer1.xml"))
        self.assertIn(b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">', content_types)
        self.assertNotIn(b'ns0:', content_types)
        w = self.W
        refs = xml.find(w + "body/" + w + "sectPr")
        for name in ("header", "footer"):
            rid = refs.find(w + name + "Reference").get("{" + documents.R + "}id")
            rel = next(row for row in rels if row.get("Id") == rid)
            self.assertEqual(documents.R + "/" + name, rel.get("Type"))
            self.assertEqual(name + "1.xml", rel.get("Target"))
            ct = next(row for row in types if row.get("PartName") == "/word/" + name + "1.xml")
            self.assertIn("." + name + "+xml", ct.get("ContentType"))
        self.assertEqual("1", refs.find(w + "pgNumType").get(w + "start"))
        self.assertEqual(["PAGE"], [(node.text or "").strip() for node in footer.iter(w + "instrText")])
        self.assertEqual(["begin", "separate", "end"],
                         [node.get(w + "fldCharType") for node in footer.iter(w + "fldChar")])
        report = documents.inspect_generated_docx(raw, blocks, [], profile=self.PROFILE)
        self.assertEqual("word/footer1.xml", report["page_numbering"]["part"])
        self.assertEqual("continuous_from_1_including_contents_body_annex_and_figures",
                         report["page_numbering"]["policy"])
        self.assertFalse(report["page_numbering"]["fields_refreshed"])
        self.assertEqual("not_verified", report["page_numbering"]["physical_page_numbers"])
        self.assertTrue(report["header_footer"]["relationships_and_content_types_equal"])

    def test_v2_preserves_literal_spacing_and_keeps_punctuation_inside_text_area(self):
        raw = documents.make_docx(self.fixture(), [], profile=self.PROFILE)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            styles = documents.ET.fromstring(package.read("word/styles.xml"))
        for style in styles:
            for setting in ("overflowPunct", "autoSpaceDE", "autoSpaceDN"):
                node = style.find(self.W + "pPr/" + self.W + setting)
                self.assertIsNotNone(node)
                self.assertEqual("0", node.get(self.W + "val"))

    def test_v2_four_levels_annex_and_toc_use_actual_styles(self):
        blocks = self.fixture()
        raw = documents.make_docx(blocks, [], profile=self.PROFILE)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = documents.ET.fromstring(package.read("word/document.xml"))
            styles = documents.ET.fromstring(package.read("word/styles.xml"))
        w = self.W
        for level in range(1, 5):
            for prefix in ("Heading", "AnnexHeading"):
                style = next(node for node in styles if node.get(w + "styleId") == prefix + str(level))
                self.assertEqual(str(level - 1), style.find(w + "pPr/" + w + "outlineLvl").get(w + "val"))
                self.assertIsNotNone(style.find(w + "pPr/" + w + "keepNext"))
        paragraphs = xml.findall(w + "body/" + w + "p")
        annex = next(p for p in paragraphs if any(n.get(w + "name") == "Annex" for n in p.iter(w + "bookmarkStart")))
        self.assertEqual("AnnexHeading1", annex.find(w + "pPr/" + w + "pStyle").get(w + "val"))
        instructions = [(node.text or "").strip() for node in xml.iter(w + "instrText")]
        self.assertIn('TOC \\o "1-4" \\h \\z \\u', instructions)
        self.assertEqual(4, documents.document_profile(self.PROFILE)["max_heading_depth"])
        with self.assertRaisesRegex(ContractError, "document_heading_depth_unsupported"):
            documents.make_docx([{"id": "Deep", "kind": "heading5", "text": "过深"}], [], profile=self.PROFILE)

    def test_v2_original_table_maps_header_and_allows_long_rows_to_split(self):
        raw = documents.make_docx(self.fixture(), [], profile=self.PROFILE)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = documents.ET.fromstring(package.read("word/document.xml"))
        w = self.W
        rows = xml.findall(w + "body/" + w + "tbl/" + w + "tr")
        self.assertIsNotNone(rows[0].find(w + "trPr/" + w + "tblHeader"))
        self.assertTrue(all(p.find(w + "pPr/" + w + "keepNext") is not None for p in rows[0].iter(w + "p")))
        self.assertIsNone(rows[1].find(w + "trPr/" + w + "cantSplit"))
        self.assertFalse(list(rows[1].iter(w + "keepNext")))
        self.assertFalse(list(rows[1].iter(w + "keepLines")))
        profile = documents.table_template_profile("dyz-comment-six-column-v1")
        self.assertEqual(6, len(profile["columns"]))
        self.assertEqual("original_internal_fixture", profile["template_origin"])
        broken = self.fixture()
        broken[-2]["cells"][0][2] = "相似但未映射的意见栏"
        with self.assertRaisesRegex(ContractError, "document_table_profile_header_mismatch"):
            documents.make_docx(broken, [], profile=self.PROFILE)

    def test_v2_optional_a3_figures_continue_page_sequence_in_same_footer(self):
        blocks = self.fixture()
        def chunk(kind, value):
            data = kind + value
            return documents.struct.pack(">I", len(value)) + data + documents.struct.pack(">I", documents.zlib.crc32(data))
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", documents.struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", documents.zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b""))
        images = [{"id": "Figure", "png": png, "width": 1, "height": 1}]
        raw = documents.make_docx(blocks, images, profile=self.PROFILE)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = documents.ET.fromstring(package.read("word/document.xml"))
        w = self.W
        sections = list(xml.iter(w + "sectPr"))
        self.assertEqual(2, len(sections))
        self.assertEqual("1", sections[0].find(w + "pgNumType").get(w + "start"))
        self.assertIsNone(sections[1].find(w + "pgNumType").get(w + "start"))
        self.assertEqual(["11906", "16838"], [s.find(w + "pgSz").get(w + "w") for s in sections])
        self.assertTrue(all(s.find(w + "footerReference").get("{" + documents.R + "}id") == "footer" for s in sections))
        documents.inspect_generated_docx(raw, blocks, images, profile=self.PROFILE)

    def test_v2_source_resolution_supports_four_levels_without_default_expansion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = "### 1.1.1 合成三级\n#### 1.1.1.1 合成四级\n".encode()
            (root / "source.txt").write_bytes(raw)
            spec = {"document_id": "Levels", "business": "standard", "version": "1",
                    "sensitivity": "synthetic", "profile": self.PROFILE,
                    "sources": [{"id": "S", "path": "source.txt", "sha256": sha256_bytes(raw)}],
                    "blocks": [{"id": "H3", "kind": "heading3", "source_id": "S", "audience": "body", "start_line": 1, "end_line": 1},
                               {"id": "H4", "kind": "heading4", "source_id": "S", "audience": "body", "start_line": 2, "end_line": 2}]}
            result = documents.build(root, spec, "pack", synthetic=True)
            self.assertEqual(4, result["profile"]["max_heading_depth"])
            documents.verify(root, spec, "pack", synthetic=True)
            spec.pop("profile")
            with self.assertRaisesRegex(ContractError, "document_block_kind"):
                documents.resolve_document(root, spec)

    def test_v2_header_footer_tampering_is_in_package_check(self):
        blocks = self.fixture()
        raw = documents.make_docx(blocks, [], profile=self.PROFILE)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            parts = {name: package.read(name) for name in package.namelist()}
        parts["word/footer1.xml"] = parts["word/footer1.xml"].replace(b" PAGE ", b" PAGEREF Missing ")
        with self.assertRaisesRegex(ContractError, "document_package_"):
            documents.inspect_generated_docx(documents._zip_docx(parts), blocks, [], profile=self.PROFILE)

    def test_legacy_and_v1_preserve_preimplementation_bytes(self):
        plain = [{"id": "Heading", "kind": "heading1", "text": "合成基线"},
                 {"id": "Para", "kind": "paragraph", "text": "仅当A成立才启动；10 ms。"},
                 {"id": "Table", "kind": "table", "text": "表", "cells": [["甲", "乙"], ["A B", "10 ms"]]}]
        fields = [{"id": "Title", "kind": "title", "text": "内部基线"},
                  {"id": "TOC", "kind": "field", "field_type": "TOC"}, *plain,
                  {"id": "Caption", "kind": "field", "field_type": "SEQ", "sequence": "Table", "prefix": "表 "},
                  {"id": "Ref", "kind": "field", "field_type": "REF", "target": "Heading"},
                  {"id": "PageRef", "kind": "field", "field_type": "PAGEREF", "target": "Heading"}]
        self.assertEqual("9b3fbce91e9b23cc68a4798d85e2c88ed06a13cd89cd45d5bfa2d5790c239bcf",
                         sha256_bytes(documents.make_docx(plain, [])))
        self.assertEqual("fa247b95cf0d5ebdd712378383fec70cb41241efd3f90f55444ce3923b3b4dae",
                         sha256_bytes(documents.make_docx(fields, [], profile="dyz-standard-internal-v1")))


if __name__ == "__main__":
    unittest.main()
