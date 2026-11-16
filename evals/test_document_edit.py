"""SE-06：原创DOCX的受限新副本修改，不是任意Word保真保证。"""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile
from contextlib import redirect_stdout
from unittest.mock import patch
from xml.etree import ElementTree as ET

from tools import document_edit as edit
from tools import document_review as review
from tools.core import ContractError, canonical_bytes, sha256_bytes
from tools.documents import make_docx
from evals.test_standard_sources import admission


W = "{" + review.W + "}"


def unpack(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def mutate(raw, change):
    parts = unpack(raw)
    tree = ET.fromstring(parts["word/document.xml"])
    change(tree)
    parts["word/document.xml"] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return output.getvalue()


class DocumentEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = make_docx([
            {"id": "C1", "kind": "paragraph", "text": "周期应为10 ms。"},
            {"id": "C2", "kind": "paragraph", "text": "维护模式除外。"}], [])
        (self.root / "original.docx").write_bytes(self.raw)
        self.request = {"expected_sha256": sha256_bytes(self.raw), "operations": [
            {"locator": {"bookmark": "C1"}, "old_text": "周期应为10 ms。",
             "new_text": "周期应为12 ms。", "source_refs": ["synthetic-comment-1"]}]}

    def invoke(self, request=None, **kwargs):
        return edit.edit_copy(self.root, "original.docx", "revised.docx", request or self.request, **kwargs)

    def test_new_copy_keeps_original_and_unchanged_part_bytes(self):
        report = self.invoke(synthetic=True)
        result = (self.root / "revised.docx").read_bytes()
        self.assertEqual(self.raw, (self.root / "original.docx").read_bytes())
        old, new = unpack(self.raw), unpack(result)
        self.assertEqual(set(old), set(new))
        for name in old:
            if name != "word/document.xml":
                self.assertEqual(old[name], new[name])
        self.assertEqual(old["word/document.xml"].replace("10 ms".encode(), "12 ms".encode()), new["word/document.xml"])
        self.assertEqual("not_performed", report["professional_review"])
        self.assertEqual("required", report["standard_semantic_review"])
        self.assertEqual(sha256_bytes(result), report["output_sha256"])
        self.assertEqual(1, len(report["changes"]))

    def test_all_operations_prevalidated_no_partial_file(self):
        request = copy.deepcopy(self.request)
        request["operations"].append({"locator": {"bookmark": "C2"}, "old_text": "wrong",
            "new_text": "不应写入", "source_refs": ["synthetic-comment-2"]})
        with self.assertRaisesRegex(ContractError, "old_text_mismatch"):
            self.invoke(request, synthetic=True)
        self.assertFalse((self.root / "revised.docx").exists())
        self.assertEqual(self.raw, (self.root / "original.docx").read_bytes())

    def test_mixed_runs_fields_formulas_textboxes_tables_revisions_rejected(self):
        changes = [
            lambda p: p.append(copy.deepcopy(p.find(W + "r"))),
            lambda p: ET.SubElement(p.find(W + "r"), W + "fldChar"),
            lambda p: ET.SubElement(p, "{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath"),
            lambda p: ET.SubElement(p, W + "txbxContent"),
            lambda p: ET.SubElement(p, W + "tbl"),
            lambda p: ET.SubElement(p, W + "ins"),
        ]
        for change in changes:
            with self.subTest(change=change):
                raw = mutate(self.raw, lambda t: change(t.find("./" + W + "body/" + W + "p")))
                (self.root / "original.docx").write_bytes(raw)
                with self.assertRaises(ContractError):
                    self.invoke({**self.request, "expected_sha256": sha256_bytes(raw)}, synthetic=True)
                self.assertFalse((self.root / "revised.docx").exists())

    def test_duplicate_bookmark_or_duplicate_operation_rejected(self):
        raw = mutate(self.raw, lambda t: t.findall(".//" + W + "bookmarkStart")[1].set(W + "name", "C1"))
        (self.root / "original.docx").write_bytes(raw)
        with self.assertRaisesRegex(ContractError, "bookmark_ambiguous"):
            self.invoke({**self.request, "expected_sha256": sha256_bytes(raw)}, synthetic=True)
        (self.root / "original.docx").write_bytes(self.raw)
        request = copy.deepcopy(self.request)
        request["operations"] *= 2
        with self.assertRaisesRegex(ContractError, "duplicate_edit_target"):
            self.invoke(request, synthetic=True)

    def test_unique_paragraph_locator_and_escaped_text(self):
        request = copy.deepcopy(self.request)
        request["operations"][0].update(locator={"paragraph": 1}, new_text="  A < B & C > D  ")
        self.invoke(request, synthetic=True)
        tree = ET.fromstring(unpack((self.root / "revised.docx").read_bytes())["word/document.xml"])
        node = tree.find(".//" + W + "t")
        self.assertEqual("  A < B & C > D  ", node.text)
        self.assertEqual("preserve", node.get("{http://www.w3.org/XML/1998/namespace}space"))

    def test_original_hash_path_overwrite_and_absent_mode_refused(self):
        with self.assertRaisesRegex(ContractError, "authorization_required"):
            self.invoke()
        with self.assertRaises(ContractError):
            edit.edit_copy(self.root, "original.docx", "original.docx", self.request, synthetic=True)
        with self.assertRaises(ContractError):
            edit.edit_copy(self.root, "original.docx", "../revised.docx", self.request, synthetic=True)
        (self.root / "revised.docx").write_bytes(b"already here")
        with self.assertRaises(ContractError):
            self.invoke(synthetic=True)
        self.assertEqual(b"already here", (self.root / "revised.docx").read_bytes())

    def test_source_drift_before_publication_keeps_output_absent(self):
        from tools import standard_sources
        real_read = standard_sources.read_bound
        count = 0
        def change_before_second_read(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                (self.root / "original.docx").write_bytes(b"changed concurrently")
            return real_read(*args, **kwargs)
        with patch.object(edit, "read_bound", side_effect=change_before_second_read):
            with self.assertRaisesRegex(ContractError, "input_hash_changed"):
                self.invoke(synthetic=True)
        self.assertFalse((self.root / "revised.docx").exists())

    def test_duplicate_zip_member_and_bomb_limits_refused(self):
        stream = io.BytesIO(self.raw)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(stream, "a") as archive:
                archive.writestr("word/document.xml", unpack(self.raw)["word/document.xml"])
        raw = stream.getvalue()
        (self.root / "original.docx").write_bytes(raw)
        with self.assertRaisesRegex(ContractError, "docx_duplicate_member"):
            self.invoke({**self.request, "expected_sha256": sha256_bytes(raw)}, synthetic=True)
        (self.root / "original.docx").write_bytes(self.raw)
        with patch.object(review, "MAX_TOTAL_BYTES", 1):
            with self.assertRaisesRegex(ContractError, "docx_total_size_limit"):
                self.invoke(synthetic=True)

    def test_authorized_local_edit_checks_scope_copy_permission_and_preflight(self):
        proof = admission(self.root, {"original.docx": self.request["expected_sha256"]}, ["revised.docx"], self.request)
        proof["permissions"] = [p for p in proof["permissions"] if p["action"] != "copy"]
        with patch.object(Path, "open", side_effect=AssertionError("read before authorization")):
            with self.assertRaisesRegex(ContractError, "permission_not_proven"):
                self.invoke(admission=proof)
        proof = admission(self.root, {"original.docx": self.request["expected_sha256"]}, ["revised.docx"], self.request)
        result = self.invoke(admission=proof)
        self.assertEqual("authorized_case", result["mode"])
        self.assertEqual("caller_responsibility_not_authenticated", result["authorization_authenticity"])
        self.assertEqual("change_detection_not_signature_or_trusted_anchor", result["authorization_binding_scope"])

    def test_cli_mode_and_evidence_report(self):
        (self.root / "request.json").write_bytes(canonical_bytes(self.request))
        args = ["--root", str(self.root), "--input", "original.docx", "--request", "request.json", "--output", "revised.docx", "--report", "changes.json"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(2, edit.main(args))
            self.assertEqual(0, edit.main(args + ["--synthetic"]))
        report = json.loads((self.root / "changes.json").read_text(encoding="utf-8"))
        self.assertEqual(sha256_bytes(self.raw), report["original_sha256"])


class ConservativeEditV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def invoke(self, raw, operations):
        (self.root / "original.docx").write_bytes(raw)
        return edit.edit_copy(self.root, "original.docx", "revised.docx",
                              {"expected_sha256": sha256_bytes(raw), "operations": operations}, synthetic=True)

    def paragraph_fixture(self, *, styles=None, extra=None):
        raw = make_docx([{"id": "P", "kind": "paragraph", "text": "周期应为10 ms。"}], [])
        def split(tree):
            paragraph = tree.find("./" + W + "body/" + W + "p")
            first = paragraph.find(W + "r")
            position = list(paragraph).index(first)
            paragraph.remove(first)
            for index, text in enumerate(("周期应为", "10", " ms。")):
                run = copy.deepcopy(first)
                run.find(W + "t").text = text
                if styles:
                    prop = ET.Element(W + "rPr")
                    ET.SubElement(prop, W + "b", {W + "val": styles[index]})
                    run.insert(0, prop)
                paragraph.insert(position + index, run)
            if extra:
                extra(paragraph)
        return mutate(raw, split)

    def operation(self, old="周期应为10 ms。", new="周期应为123 ms。", **extra):
        return {"type": "replace_paragraph", "part": "word/document.xml",
                "locator": {"bookmark": "P"}, "old_text": old,
                "old_text_sha256": sha256_bytes(old.encode()), "new_text": new,
                "source_refs": ["original-synthetic-review"], **extra}

    def table_fixture(self, columns=6, merge=False):
        headers = (["序号", "条款", "原意见", "决定", "理由", "落实／状态"] if columns == 6
                   else ["位置／原意见", "建议", "理由"])
        raw = make_docx([{"id": "Table", "kind": "table", "cells": [headers,
                         [f"原文{index}" for index in range(1, columns + 1)],
                         [f"续行{index}" for index in range(1, columns + 1)]]}], [])
        if merge:
            def merged(tree):
                rows = tree.findall("./" + W + "body/" + W + "tbl/" + W + "tr")
                for row_index in (1, 2):
                    cells = rows[row_index].findall(W + "tc")
                    cp = cells[2].find(W + "tcPr")
                    ET.SubElement(cp, W + "gridSpan", {W + "val": "2"})
                    ET.SubElement(cp, W + "vMerge", {W + "val": "restart"} if row_index == 1 else {})
                    rows[row_index].remove(cells[3])
                    if row_index == 2:
                        paragraph = cells[2].find(W + "p")
                        for run in list(paragraph.findall(W + "r")):
                            paragraph.remove(run)
            raw = mutate(raw, merged)
        return raw

    def cell_operation(self, *, columns=6, row=2, column=3, old="原文3", new="合成新意见。"):
        return {"type": "replace_table_cell", "part": "word/document.xml",
                "table_profile": f"dyz-comment-{'six' if columns == 6 else 'three'}-column-v1",
                "locator": {"table": 1, "row": row, "column": column},
                "old_text": old, "old_text_sha256": sha256_bytes(old.encode()),
                "new_text": new, "source_refs": ["original-synthetic-comment"]}

    def test_adjacent_equal_style_runs_keep_exact_style_text_correspondence(self):
        raw = self.paragraph_fixture(styles=["1", "1", "1"])
        report = self.invoke(raw, [self.operation()])
        updated = (self.root / "revised.docx").read_bytes()
        old, new = unpack(raw), unpack(updated)
        expected = old["word/document.xml"].replace(b">10</", b">123</")
        self.assertEqual(expected, new["word/document.xml"])
        runs = ET.fromstring(new["word/document.xml"]).findall(".//" + W + "r")
        self.assertEqual(["周期应为", "123", " ms。"], [r.find(W + "t").text for r in runs])
        evidence = report["changes"][0]["run_evidence"]
        self.assertEqual(["周期应为", "10", " ms。"], [row["old_text"] for row in evidence])
        self.assertEqual(["周期应为", "123", " ms。"], [row["new_text"] for row in evidence])
        self.assertTrue(all(row["properties_unchanged"] for row in evidence))
        self.assertEqual(raw, (self.root / "original.docx").read_bytes())
        self.assertTrue(all(old[name] == new[name] for name in old if name != "word/document.xml"))

    def test_full_replacement_distributes_across_runs_and_long_text_is_not_truncated(self):
        raw = self.paragraph_fixture()
        new = "全新合成替代内容。" * 300
        report = self.invoke(raw, [self.operation(new=new)])
        evidence = report["changes"][0]["run_evidence"]
        self.assertEqual(new, "".join(row["new_text"] for row in evidence))
        self.assertTrue(all(row["new_text"] for row in evidence))
        self.assertEqual(new, report["changes"][0]["new_text"])

    def test_two_original_table_profiles_and_explicit_part_hash(self):
        for columns in (3, 6):
            with self.subTest(columns=columns):
                target = self.root / "revised.docx"
                target.unlink(missing_ok=True)
                raw = self.table_fixture(columns)
                operation = self.cell_operation(columns=columns, new="长意见。" * 800)
                report = self.invoke(raw, [operation])
                actual = unpack(target.read_bytes())
                self.assertIn(operation["new_text"].encode(), actual["word/document.xml"])
                self.assertEqual({"table": 1, "row": 2, "column": 3}, report["changes"][0]["canonical_cell"])
                self.assertEqual(raw, (self.root / "original.docx").read_bytes())

    def test_horizontal_and_vertical_merge_aliases_resolve_to_one_owner(self):
        raw = self.table_fixture(merge=True)
        operation = self.cell_operation(row=3, column=4)
        report = self.invoke(raw, [operation])
        change = report["changes"][0]
        self.assertEqual({"table": 1, "row": 2, "column": 3}, change["canonical_cell"])
        self.assertEqual(2, change["column_span"])
        self.assertEqual(2, change["row_span"])
        self.assertEqual(unpack(raw)["word/document.xml"].replace("原文3".encode(), "合成新意见。".encode()),
                         unpack((self.root / "revised.docx").read_bytes())["word/document.xml"])

    def test_merge_alias_duplicate_and_half_plan_rejected_before_output(self):
        raw = self.table_fixture(merge=True)
        plans = [[self.cell_operation(), self.cell_operation(row=3, column=4)],
                 [self.cell_operation(), self.cell_operation(column=5, old="不匹配")]]
        for operations in plans:
            with self.subTest(operations=operations), self.assertRaises(ContractError):
                self.invoke(raw, operations)
            self.assertFalse((self.root / "revised.docx").exists())
            self.assertEqual(raw, (self.root / "original.docx").read_bytes())

    def test_mixed_styles_interleaved_bookmarks_and_control_objects_refused(self):
        cases = [self.paragraph_fixture(styles=["1", "0", "1"])]
        for tag in ("tab", "br", "fldChar"):
            cases.append(self.paragraph_fixture(extra=lambda p, tag=tag: ET.SubElement(p.find(W + "r"), W + tag)))
        for raw in cases:
            with self.subTest(hash=sha256_bytes(raw)), self.assertRaises(ContractError):
                self.invoke(raw, [self.operation()])
            self.assertFalse((self.root / "revised.docx").exists())

    def test_invalid_part_old_hash_profile_header_and_locator_refused(self):
        raw = self.table_fixture()
        for changes in ({"part": "word/footer1.xml"}, {"old_text_sha256": "0" * 64},
                        {"table_profile": "official-unknown"}, {"locator": {"table": 1, "row": 9, "column": 1}},
                        {"locator": {"table": 1, "row": 2, "column": 3, "cell": 3}}):
            op = self.cell_operation()
            op.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.invoke(raw, [op])
            self.assertFalse((self.root / "revised.docx").exists())
        broken = mutate(raw, lambda t: setattr(t.find(".//" + W + "t"), "text", "未映射表头"))
        with self.assertRaisesRegex(ContractError, "edit_table_profile_header_mismatch"):
            self.invoke(broken, [self.cell_operation()])

    def test_insert_delete_and_cross_boundary_changes_keep_unchanged_run_text(self):
        for new, expected in [
            ("周期应为10.5 ms。", ["周期应为", "10.5", " ms。"]),
            ("周期为10 ms。", ["周期为", "10", " ms。"]),
            ("周期应为1 ms。", ["周期应为", "1", " ms。"]),
            ("周期应为10ms。", ["周期应为", "10", "ms。"]),
        ]:
            with self.subTest(new=new):
                (self.root / "revised.docx").unlink(missing_ok=True)
                report = self.invoke(self.paragraph_fixture(), [self.operation(new=new)])
                self.assertEqual(expected, [row["new_text"] for row in report["changes"][0]["run_evidence"]])

    def test_ambiguous_merge_geometry_and_nonempty_continuation_refuse_before_output(self):
        for transform in [
            lambda t: t.find(".//" + W + "vMerge").set(W + "val", "continue"),
            lambda t: t.findall(".//" + W + "gridSpan")[-1].set(W + "val", "1"),
            lambda t: ET.SubElement(t.findall(".//" + W + "tc")[13].find(W + "p"), W + "r"),
        ]:
            raw = mutate(self.table_fixture(merge=True), transform)
            with self.subTest(hash=sha256_bytes(raw)), self.assertRaises(ContractError):
                self.invoke(raw, [self.cell_operation(row=3, column=4)])
            self.assertFalse((self.root / "revised.docx").exists())
        raw = self.table_fixture(merge=True)
        def fill_continuation(tree):
            rows = tree.findall(".//" + W + "tr")
            p = rows[2].findall(W + "tc")[2].find(W + "p")
            ET.SubElement(ET.SubElement(p, W + "r"), W + "t").text = "续格有独立文字"
        changed = mutate(raw, fill_continuation)
        with self.assertRaisesRegex(ContractError, "edit_nonempty_merge_continuation_unsupported"):
            self.invoke(changed, [self.cell_operation()])
        self.assertFalse((self.root / "revised.docx").exists())

    def test_explicit_operations_require_part_and_old_hash(self):
        for omitted in ("part", "old_text_sha256"):
            operation = self.operation()
            operation.pop(omitted)
            with self.subTest(omitted=omitted), self.assertRaises(ContractError):
                self.invoke(self.paragraph_fixture(), [operation])
            self.assertFalse((self.root / "revised.docx").exists())

    def test_empty_text_node_fill_keeps_run_and_non_target_xml(self):
        raw = self.table_fixture(columns=3)
        def empty(tree):
            tree.findall(".//" + W + "tr")[1].findall(W + "tc")[2].find(".//" + W + "t").text = None
        raw = mutate(raw, empty)
        report = self.invoke(raw, [self.cell_operation(columns=3, old="", new="填入合成理由。")])
        xml = ET.fromstring(unpack((self.root / "revised.docx").read_bytes())["word/document.xml"])
        cell = xml.findall(".//" + W + "tr")[1].findall(W + "tc")[2]
        self.assertEqual("填入合成理由。", cell.find(".//" + W + "t").text)
        self.assertEqual(1, len(cell.findall(".//" + W + "r")))
        self.assertEqual("byte_identical", report["outside_replacement_ranges"])

    def test_table_complex_objects_and_interleaved_run_bookmarks_are_rejected(self):
        for tag in ("fldSimple", "ins", "txbxContent", "tbl"):
            raw = mutate(self.table_fixture(), lambda t, tag=tag: ET.SubElement(
                t.findall(".//" + W + "tr")[1].findall(W + "tc")[2].find(W + "p"), W + tag))
            with self.subTest(tag=tag), self.assertRaises(ContractError):
                self.invoke(raw, [self.cell_operation()])
            self.assertFalse((self.root / "revised.docx").exists())
        def interleaved(p):
            start = p.find(W + "bookmarkStart")
            p.remove(start)
            p.insert(list(p).index(p.findall(W + "r")[1]), start)
        raw = self.paragraph_fixture(extra=interleaved)
        with self.assertRaisesRegex(ContractError, "edit_runs_not_adjacent"):
            self.invoke(raw, [self.operation()])
        self.assertFalse((self.root / "revised.docx").exists())

    def test_unknown_fields_beside_target_still_rejected_with_original_unchanged(self):
        raw = self.paragraph_fixture(extra=lambda p: ET.SubElement(
            p.find(W + "r"), W + "instrText", {W + "instr": " PAGE "}))
        with self.assertRaises(ContractError):
            self.invoke(raw, [self.operation()])
        self.assertFalse((self.root / "revised.docx").exists())
        self.assertEqual(raw, (self.root / "original.docx").read_bytes())

    def test_v2_page_footer_is_preserved_while_editing_plain_body(self):
        from tools.documents import make_docx as render
        raw = render([{"id": "P", "kind": "paragraph", "text": "周期应为10 ms。"}], [],
                     profile="dyz-standard-internal-v2")
        self.invoke(raw, [self.operation()])
        old, new = unpack(raw), unpack((self.root / "revised.docx").read_bytes())
        self.assertEqual(old["word/footer1.xml"], new["word/footer1.xml"])
        self.assertEqual(old["word/header1.xml"], new["word/header1.xml"])


if __name__ == "__main__":
    unittest.main()
