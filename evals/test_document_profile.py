"""SE-04：原创内部版式、默认字节兼容与完整区间书签。"""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from tools import documents
from tools.core import ContractError
from evals.test_document_quality import source_case


class DocumentProfileTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            {"id": "CLAUSE", "kind": "paragraph", "text": "仅当A与B成立才启动。\n维护模式除外；不得删除例外。"},
            {"id": "TABLE", "kind": "table", "text": "unused", "cells": [["项目", "条件"], ["测量", "≤ 5 μs"]]},
        ]

    def test_default_profile_keeps_identical_bytes(self):
        raw = documents.make_docx(self.blocks, [])
        self.assertEqual(raw, documents.make_docx(self.blocks, [], profile=None))
        self.assertEqual(documents.inspect_generated_docx(raw, self.blocks, []),
                         documents.inspect_generated_docx(raw, self.blocks, [], profile=None))

    def test_original_standard_profile_changes_styles_not_text(self):
        raw = documents.make_docx(self.blocks, [], profile="dyz-standard-internal-v1")
        baseline = documents.make_docx(self.blocks, [])
        self.assertNotEqual(baseline, raw)
        checks = documents.inspect_generated_docx(raw, self.blocks, [], profile="dyz-standard-internal-v1")
        self.assertTrue(checks["source_text_equal"])
        profile = documents.document_profile("dyz-standard-internal-v1")
        self.assertEqual("not_asserted", profile["official_format"])
        self.assertEqual("original_internal_implementation", profile["template_origin"])
        self.assertEqual("2", profile["version"])
        self.assertEqual("generated_not_refreshed", profile["dynamic_fields"])
        self.assertFalse(profile["fields_refreshed"])
        self.assertIn("field_refresh", profile["unsupported_objects"])
        self.assertTrue({"TOC", "SEQ", "REF", "PAGEREF"} <= set(profile["supported_objects"]))
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = ET.fromstring(package.read("word/styles.xml"))
        ns = {"w": documents.W}
        size = xml.find("w:style[@w:styleId='Normal']/w:rPr/w:sz", ns)
        self.assertEqual("24", size.get("{" + documents.W + "}val"))
        with self.assertRaises(ContractError):
            documents.inspect_generated_docx(raw, self.blocks, [])

    def test_bookmarks_cover_full_paragraph_and_table_not_only_heading(self):
        raw = documents.make_docx(self.blocks, [], profile="dyz-standard-internal-v1")
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = ET.fromstring(package.read("word/document.xml"))
        active, captured = {}, {}
        w = "{" + documents.W + "}"
        for node in xml.iter():
            if node.tag == w + "bookmarkStart":
                identity = node.get(w + "id")
                active[identity] = node.get(w + "name")
                captured[active[identity]] = ""
            elif node.tag == w + "bookmarkEnd":
                active.pop(node.get(w + "id"))
            elif node.tag in {w + "t", w + "br"}:
                for name in active.values():
                    captured[name] += node.text or "" if node.tag == w + "t" else "\n"
        self.assertEqual(self.blocks[0]["text"], captured["CLAUSE"])
        self.assertEqual("项目条件测量≤ 5 μs", captured["TABLE"])
        self.assertEqual({}, active)

    def test_unknown_or_falsely_official_profile_rejected(self):
        for profile in (True, "GB/T 1.1", {"profile_id": "dyz-standard-internal-v1", "official_format": "passed"}):
            with self.subTest(profile=profile), self.assertRaisesRegex(ContractError, "document_profile_unsupported"):
                documents.make_docx(self.blocks, [], profile=profile)

    def test_build_and_verify_bind_profile_to_quality_manifest_version(self):
        with tempfile.TemporaryDirectory(prefix="dyz-profile-") as folder:
            root = Path(folder)
            spec = source_case(root, "原创内部条款。")
            spec["profile"] = "dyz-standard-internal-v1"
            built = documents.build(root, spec, "pack", synthetic=True)
            self.assertEqual("1.5", built["generator_version"])
            self.assertEqual("dyz-standard-internal-v1", built["profile"]["profile_id"])
            checked = documents.verify(root, spec, "pack", synthetic=True)
            self.assertEqual(built["profile"], checked["profile"])

    def test_resolution_rejects_non_string_profile_before_dispatch(self):
        with tempfile.TemporaryDirectory(prefix="dyz-profile-") as folder:
            root = Path(folder)
            spec = source_case(root, "Original technical text.")
            for profile in ({"unexpected": "value"}, [], True):
                with self.subTest(profile=profile), self.assertRaisesRegex(ContractError, "document_profile_unsupported"):
                    documents.resolve_document(root, {**spec, "profile": profile})

    def test_unsupported_standard_profiles_reject_formula(self):
        with tempfile.TemporaryDirectory(prefix="dyz-profile-") as folder:
            root = Path(folder)
            spec = source_case(root, "x = y^2")
            spec["blocks"][0]["kind"] = "formula"
            for profile in (None, "dyz-standard-internal-v1", "dyz-standard-internal-v2"):
                with self.subTest(profile=profile), self.assertRaisesRegex(ContractError, "document_formula_profile_unsupported"):
                    documents.resolve_document(root, {**spec, "profile": profile})
            for profile in ("dyz-standard-internal-v1", "dyz-standard-internal-v2"):
                with self.subTest(direct_profile=profile), self.assertRaisesRegex(ContractError, "document_formula_profile_unsupported"):
                    documents.make_docx([{"id": "F", "kind": "formula", "text": "x = y^2"}], [], profile=profile)

    def test_v3_formula_keep_with_next_is_written_and_verified(self):
        profile = "dyz-standard-internal-v3"
        blocks = [{"id": "F1", "kind": "formula", "text": "x = y^2", "keep_with_next": True},
                  {"id": "F2", "kind": "formula", "text": "x = y^2", "keep_with_next": False}]
        raw = documents.make_docx(blocks, [], profile=profile)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = ET.fromstring(package.read("word/document.xml"))
        w = "{" + documents.W + "}"
        self.assertEqual(["1", "0"], [node.get(w + "val") for node in xml.iter(w + "keepNext")])
        self.assertTrue(documents.inspect_generated_docx(raw, blocks, [], profile=profile)["source_text_equal"])


if __name__ == "__main__":
    unittest.main()
