"""CORE-07：真实ZIP/XML编辑变体；仅合成工程验证，不是Word宿主或专业验收。"""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from xml.etree import ElementTree as ET

from tools import document_review as review
from tools.core import ContractError, sha256_bytes
from tools.documents import make_docx


ROOT = Path(__file__).resolve().parents[1]
W, R, REL, CT = review.W, review.R, review.REL, review.CT


def tag(name):
    return "{" + W + "}" + name


def fixture():
    return make_docx([
        {"id": "CLAUSE8", "kind": "paragraph", "text": "8 仅当A与B同时成立才关闭阀门；维护模式除外。"},
        {"id": "CLAUSE9", "kind": "paragraph", "text": "9 周期为10 ms ±1 ms。"},
        {"id": "PARAMS", "kind": "table", "cells": [["参数", "值"], ["周期", "10 ms ±1 ms"]]},
    ], [])


def parts(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def pack(entries):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return target.getvalue()


def edited(raw, change):
    entries = parts(raw)
    tree = ET.fromstring(entries["word/document.xml"])
    change(tree)
    entries["word/document.xml"] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    return pack(entries)


def by_name(report, name, section="paired_bookmarks"):
    return next(item for item in report["comparison"][section] if item["name"] == name)


class DocumentReviewTests(unittest.TestCase):
    def setUp(self):
        self.raw = fixture()

    def test_summary_locates_condition_change_without_repeating_unchanged_text(self):
        raw = edited(self.raw, lambda tree: setattr(tree.find(".//" + tag("t")), "text",
            "8 仅当A或B成立才关闭阀门；维护模式除外。"))
        report = review.review_docx(raw, self.raw)
        before = json.dumps(report, ensure_ascii=False)
        summary = review._review_summary(report)
        changed = [item for item in summary["items"] if "literal_change" in item]
        self.assertEqual(1, len(changed))
        self.assertEqual("CLAUSE8", changed[0]["name"])
        self.assertIn("或B", changed[0]["literal_change"]["after"]["text"])
        self.assertNotIn("10 ms", json.dumps(summary, ensure_ascii=False))
        self.assertEqual(before, json.dumps(report, ensure_ascii=False))
        for item in summary["items"]:
            value = report
            for part in item["report_pointer"].split("/")[1:]:
                value = value[int(part)] if isinstance(value, list) else value[part]
            self.assertIsInstance(value, dict)
        self.assertEqual("not_performed", summary["professional_review"])

    def test_summary_excerpts_bound_unicode_without_changing_full_span(self):
        raw = edited(self.raw, lambda tree: setattr(tree.find(".//" + tag("t")), "text", "新🙂" * 1400))
        report = review.review_docx(raw, self.raw)
        summary = review._review_summary(report)
        item = next(row for row in summary["items"] if "literal_change" in row)
        span = item["literal_change"]["after"]
        full = by_name(report, "CLAUSE8")["literal_change"]["after"]
        self.assertEqual(240, len(span["text"]))
        self.assertEqual(full["text"][:240], span["text"])
        self.assertTrue(span["truncated"])
        self.assertEqual(full["sha256"], span["sha256"])
        self.assertEqual(full["end"], span["end"])
        self.assertEqual(2048, len(full["text"]))

    def test_summary_bounds_keep_counts_partial_and_full_evidence(self):
        entries = parts(self.raw)
        entries["word/comments.xml"] = ('<w:comments xmlns:w="' + W + '">' +
            ''.join('<w:comment w:id="%d"><w:p><w:r><w:t>PRIVATE COMMENT</w:t></w:r></w:p></w:comment>' % i
                    for i in range(60)) + '</w:comments>').encode()
        report = review.review_docx(pack(entries))
        summary = review._review_summary(report)
        self.assertEqual("partial", summary["readback_state"])
        self.assertEqual("not_requested", summary["comparison_state"])
        self.assertIsNone(summary["baseline_sha256"])
        self.assertEqual("not_assessed", summary["hidden_content_clearance"])
        self.assertGreater(summary["omitted_items"], 0)
        self.assertLessEqual(len(summary["items"]), 32)
        self.assertLessEqual(sum(len(json.dumps(item, ensure_ascii=False).encode()) for item in summary["items"]), 24000)
        group = next(g for g in summary["groups"] if g["report_pointer"].endswith("/findings"))
        self.assertEqual(60, group["total"])
        self.assertEqual(group["total"], group["shown"] + group["omitted"])
        self.assertEqual(60, len(report["current"]["content_inventory"]["findings"]))
        self.assertNotIn("PRIVATE COMMENT", json.dumps(summary))

    def test_summary_keeps_unanchored_changes_and_unresolved_identity(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            for node in list(paragraph):
                if node.tag in {tag("bookmarkStart"), tag("bookmarkEnd")}:
                    paragraph.remove(node)
            paragraph.find(".//" + tag("t")).text = "无书签的新条件"
        report = review.review_docx(edited(self.raw, change), self.raw)
        summary = review._review_summary(report)
        self.assertEqual("partial", summary["comparison_state"])
        self.assertTrue(any("unresolved_bookmarks" in item["report_pointer"] for item in summary["items"]))
        self.assertTrue(any(item.get("text") == "无书签的新条件" for item in summary["items"]))

    def test_paragraph_table_and_stable_bookmark_readback(self):
        report = review.review_docx(self.raw, self.raw)
        self.assertEqual("needs_review", report["status"])
        self.assertEqual("complete_supported_subset", report["current"]["readback_state"])
        self.assertEqual("complete_supported_subset", report["comparison"]["state"])
        self.assertEqual("参数\t值\n周期\t10 ms ±1 ms", report["current"]["blocks"][2]["text"])
        self.assertEqual("10 ms ±1 ms", report["current"]["blocks"][2]["cells"][3]["text"])
        self.assertTrue(all(item["text_equal"] for item in report["comparison"]["paired_bookmarks"]))
        self.assertEqual(sha256_bytes(self.raw), report["current"]["sha256"])
        for name in ("professional_review", "visual_review", "external_action"):
            self.assertEqual("not_performed", report[name])
        self.assertEqual("not_assessed", report["comparison"]["semantic_equivalence"])

    def test_readback_without_baseline_does_not_invent_comparison(self):
        report = review.review_docx(self.raw)
        self.assertIsNone(report["baseline"])
        self.assertEqual({"state": "not_requested"}, report["comparison"])

    def test_literal_condition_change_is_localized(self):
        raw = edited(self.raw, lambda tree: setattr(tree.find(".//" + tag("t")), "text",
            "8 仅当A或B成立才关闭阀门；维护模式除外。"))
        report = review.review_docx(raw, self.raw)
        difference = by_name(report, "CLAUSE8")
        self.assertFalse(difference["text_equal"])
        self.assertIn("与B同时", difference["literal_change"]["before"]["text"])
        self.assertIn("或B", difference["literal_change"]["after"]["text"])
        self.assertTrue(by_name(report, "CLAUSE9")["text_equal"])
        self.assertEqual("requires_separate_current_version_review", report["comparison"]["prior_review_reuse"])

    def test_split_runs_and_format_edit_keep_literal_text(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            run = paragraph.find(tag("r"))
            text = run.find(tag("t")).text
            run.find(tag("t")).text = text[:6]
            new = ET.Element(tag("r"))
            ET.SubElement(ET.SubElement(new, tag("rPr")), tag("b"))
            ET.SubElement(new, tag("t")).text = text[6:]
            paragraph.insert(list(paragraph).index(run) + 1, new)
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertTrue(by_name(report, "CLAUSE8")["text_equal"])
        self.assertTrue(report["comparison"]["main_literal_stream_equal"])
        self.assertFalse(report["comparison"]["package_bytes_equal"])
        self.assertIn("word/document.xml", [item["path"] for item in report["comparison"]["changed_parts"]])
        self.assertEqual("not_assessed", report["comparison"]["format_equivalence"])

    def test_visible_number_and_numeric_bookmark_id_do_not_replace_name(self):
        def change(tree):
            tree.find(".//" + tag("t")).text = "11 仅当A与B同时成立才关闭阀门；维护模式除外。"
            for node in tree.iter():
                if node.tag in {tag("bookmarkStart"), tag("bookmarkEnd")}:
                    node.set(tag("id"), str(int(node.get(tag("id"))) + 100))
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertFalse(by_name(report, "CLAUSE8")["text_equal"])
        self.assertEqual([], report["comparison"]["unresolved_bookmarks"])

    def test_position_change_is_reported_without_renaming_clause(self):
        def change(tree):
            body = tree.find(tag("body"))
            paragraphs = body.findall(tag("p"))
            body.remove(paragraphs[1])
            body.insert(0, paragraphs[1])
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertTrue(by_name(report, "CLAUSE8")["text_equal"])
        self.assertTrue(by_name(report, "CLAUSE8")["block_positions_changed"])

    def test_bookmark_can_span_paragraphs_and_overlap_another(self):
        def change(tree):
            first, second = tree.find(tag("body")).findall(tag("p"))
            end = first.find(tag("bookmarkEnd"))
            first.remove(end)
            second.append(end)
        report = review.review_docx(edited(self.raw, change))
        span = report["current"]["bookmarks"][0]
        self.assertEqual([1, 2], span["blocks"])
        self.assertEqual("8 仅当A与B同时成立才关闭阀门；维护模式除外。\n9 周期为10 ms ±1 ms。", span["text"])
        self.assertEqual("paired_unique_name", span["identity_state"])

    def test_removed_bookmark_does_not_guess_identity_from_position(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            paragraph.remove(paragraph.find(tag("bookmarkStart")))
            paragraph.remove(paragraph.find(tag("bookmarkEnd")))
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertEqual("identity_not_verified", by_name(report, "CLAUSE8", "unresolved_bookmarks")["state"])
        self.assertEqual([1], report["comparison"]["current_blocks_without_verified_identity"])
        self.assertEqual("partial", report["comparison"]["state"])

    def test_bookmark_touching_only_part_of_paragraph_does_not_cover_other_text(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            run = paragraph.find(tag("r"))
            original = run.find(tag("t")).text
            run.find(tag("t")).text = original[:2]
            unanchored = ET.SubElement(paragraph, tag("r"))
            ET.SubElement(unanchored, tag("t")).text = original[2:]
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertIn(1, report["comparison"]["current_blocks_without_verified_identity"])
        gaps = report["comparison"]["current_unanchored_text_ranges"]
        self.assertEqual("仅当A与B同时成立才关闭阀门；维护模式除外。", gaps[0]["text"])
        self.assertEqual("partial", report["comparison"]["state"])

    def test_unanchored_edit_is_not_hidden_by_unchanged_empty_bookmark(self):
        def move_end(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            end = paragraph.find(tag("bookmarkEnd"))
            paragraph.remove(end)
            paragraph.insert(list(paragraph).index(paragraph.find(tag("r"))), end)
        baseline = edited(self.raw, move_end)
        current = edited(baseline, lambda tree: setattr(tree.find(".//" + tag("t")), "text", "8 新增无来源条件。"))
        report = review.review_docx(current, baseline)
        self.assertTrue(by_name(report, "CLAUSE8")["text_equal"])
        self.assertFalse(report["comparison"]["main_literal_stream_equal"])
        self.assertEqual([1], report["comparison"]["current_blocks_without_verified_identity"])
        self.assertEqual([1], report["comparison"]["baseline_blocks_without_verified_identity"])
        self.assertEqual("partial", report["comparison"]["state"])

    def test_duplicate_name_or_numeric_id_never_proves_identity(self):
        for attribute, value in (("name", "CLAUSE8"), ("id", "1")):
            def change(tree):
                tree.findall(".//" + tag("bookmarkStart"))[1].set(tag(attribute), value)
            with self.subTest(attribute=attribute):
                report = review.review_docx(edited(self.raw, change), self.raw)
                self.assertEqual("partial", report["comparison"]["state"])
                self.assertFalse(any(item["name"] == "CLAUSE8" for item in report["comparison"]["paired_bookmarks"]))

    def test_numeric_id_lexical_padding_is_not_a_distinct_identifier(self):
        def change(tree):
            tree.findall(".//" + tag("bookmarkStart"))[1].set(tag("id"), "01")
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertIn("bookmark_id_duplicated", {item["code"] for item in report["current"]["notices"]})
        self.assertFalse(any(item["name"] == "CLAUSE8" for item in report["comparison"]["paired_bookmarks"]))

    def test_unclosed_and_unmatched_bookmarks_remain_unresolved(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            paragraph.find(tag("bookmarkEnd")).set(tag("id"), "99")
        report = review.review_docx(edited(self.raw, change), self.raw)
        codes = {item["code"] for item in report["current"]["notices"]}
        self.assertTrue({"bookmark_unclosed", "bookmark_end_unmatched"} <= codes)
        self.assertEqual("identity_not_verified", by_name(report, "CLAUSE8", "unresolved_bookmarks")["state"])

    def test_table_column_scoped_bookmark_is_not_a_contiguous_text_claim(self):
        def change(tree):
            bookmark = tree.findall(".//" + tag("bookmarkStart"))[2]
            bookmark.set(tag("colFirst"), "1")
            bookmark.set(tag("colLast"), "1")
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertIn("bookmark_column_scope_not_interpreted",
                      by_name(report, "PARAMS", "unresolved_bookmarks")["current_issues"][0])
        self.assertIsNone(report["current"]["bookmarks"][2]["text"])

    def test_table_cell_edit_has_xml_row_cell_locator(self):
        def change(tree):
            tree.findall(".//" + tag("tc"))[-1].find(".//" + tag("t")).text = "20 ms ±1 ms"
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertFalse(by_name(report, "PARAMS")["text_equal"])
        cell = report["current"]["blocks"][2]["cells"][3]
        self.assertEqual((2, 2, "20 ms ±1 ms"), (cell["row"], cell["cell"], cell["text"]))
        self.assertEqual("body/tbl[1]/tr[2]/tc[2]", cell["locator"])

    def test_collapsed_table_bookmark_does_not_inherit_whole_table_identity(self):
        def change(tree):
            paragraphs = tree.find("./" + tag("body") + "/" + tag("tbl")).findall(".//" + tag("p"))
            start = paragraphs[0].find(tag("bookmarkStart"))
            end = paragraphs[-1].find(tag("bookmarkEnd"))
            paragraphs[0].remove(start)
            paragraphs[-1].remove(end)
            paragraphs[-1].append(start)
            paragraphs[-1].append(end)
        report = review.review_docx(edited(self.raw, change), self.raw)
        self.assertTrue(report["comparison"]["main_literal_stream_equal"])
        self.assertFalse(by_name(report, "PARAMS")["text_equal"])
        self.assertEqual([3], report["comparison"]["current_blocks_without_verified_identity"])
        self.assertEqual("参数\t值\n周期\t10 ms ±1 ms", report["comparison"]["current_unanchored_text_ranges"][0]["text"])
        self.assertEqual("partial", report["comparison"]["state"])

    def test_merged_and_nested_table_are_explicitly_partial(self):
        def change(tree):
            cell = tree.findall(".//" + tag("tc"))[-1]
            ET.SubElement(cell.find(tag("tcPr")), tag("gridSpan"), {tag("val"): "2"})
            nested = ET.SubElement(cell, tag("tbl"))
            ET.SubElement(ET.SubElement(ET.SubElement(nested, tag("tr")), tag("tc")), tag("p"))
        report = review.review_docx(edited(self.raw, change), self.raw)
        codes = {item["code"] for item in report["current"]["notices"]}
        self.assertTrue({"table_merge_not_interpreted", "table_cell_child_not_interpreted"} <= codes)
        self.assertEqual("partial", report["current"]["readback_state"])

    def test_insertions_and_deletions_are_kept_separate_and_not_accepted(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            for kind, text in (("del", "仅当A与B同时成立"), ("ins", "满足任一条件")):
                revision = ET.Element(tag(kind), {tag("id"): "8"})
                run = ET.SubElement(revision, tag("r"))
                ET.SubElement(run, tag("delText") if kind == "del" else tag("t")).text = text
                paragraph.insert(len(paragraph) - 1, revision)
        report = review.review_docx(edited(self.raw, change), self.raw)
        fragments = report["current"]["unresolved_fragments"]
        self.assertEqual(["del", "ins"], [item["kind"] for item in fragments])
        self.assertNotIn("满足任一条件", report["current"]["blocks"][0]["text"])
        self.assertEqual("identity_not_verified", by_name(report, "CLAUSE8", "unresolved_bookmarks")["state"])

    def test_direct_hidden_false_differs_from_hidden_true(self):
        for value, partial in (("false", False), ("0", False), ("true", True), ("1", True)):
            def change(tree):
                run = tree.find(".//" + tag("r"))
                properties = ET.Element(tag("rPr"))
                ET.SubElement(properties, tag("vanish"), {tag("val"): value})
                run.insert(0, properties)
            with self.subTest(value=value):
                report = review.review_docx(edited(self.raw, change))
                self.assertEqual(partial, report["current"]["readback_state"] == "partial")
                self.assertIn("仅当A与B", report["current"]["blocks"][0]["text"])

    def test_style_hidden_toggle_is_not_guessed_from_false_value(self):
        entries = parts(self.raw)
        tree = ET.fromstring(entries["word/styles.xml"])
        ET.SubElement(tree.find(".//" + tag("rPr")), tag("vanish"), {tag("val"): "false"})
        entries["word/styles.xml"] = ET.tostring(tree)
        report = review.review_docx(pack(entries))
        self.assertIn("style_hidden_toggle_not_resolved", {i["code"] for i in report["current"]["notices"]})

    def test_simple_and_complex_fields_are_not_refreshed_or_trusted(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            field = ET.Element(tag("fldSimple"), {tag("instr"): "REF CLAUSE9"})
            ET.SubElement(ET.SubElement(field, tag("r")), tag("t")).text = "过期编号99"
            paragraph.insert(len(paragraph) - 1, field)
            for kind, value in (("fldChar", "begin"), ("instrText", "REF CLAUSE9"),
                                ("fldChar", "separate"), ("t", "缓存编号88"), ("fldChar", "end")):
                run = ET.Element(tag("r"))
                node = ET.SubElement(run, tag(kind))
                if kind == "fldChar":
                    node.set(tag("fldCharType"), value)
                else:
                    node.text = value
                paragraph.insert(len(paragraph) - 1, run)
        report = review.review_docx(edited(self.raw, change))
        text = report["current"]["blocks"][0]["text"]
        self.assertNotIn("过期编号", text)
        self.assertNotIn("缓存编号", text)
        self.assertIn("缓存编号88", [item["text"] for item in report["current"]["unresolved_fragments"]])
        self.assertEqual("partial", report["current"]["readback_state"])

    def test_comments_headers_images_and_binary_objects_are_listed_unread(self):
        entries = parts(self.raw)
        for name in ("word/comments.xml", "word/header1.xml", "word/footnotes.xml"):
            entries[name] = ('<w:p xmlns:w="' + W + '"><w:r><w:t>另部件文字</w:t></w:r></w:p>').encode()
        entries["word/embeddings/oleObject1.bin"] = b"synthetic-not-an-executable"
        entries["word/media/image1.png"] = b"synthetic-image-byte-binding-only"
        report = review.review_docx(pack(entries))
        unread = {item["path"] for item in report["current"]["unread_parts"]}
        self.assertTrue({"word/comments.xml", "word/header1.xml", "word/footnotes.xml",
                         "word/embeddings/oleObject1.bin", "word/media/image1.png"} <= unread)
        self.assertEqual("partial", report["current"]["readback_state"])
        self.assertEqual("not_performed", report["external_action"])

    def test_inventory_locates_markers_in_unread_and_skipped_content(self):
        entries = parts(self.raw)
        entries["word/comments.xml"] = (
            '<w:comments xmlns:w="' + W + '"><w:comment w:id="7" w:author="PRIVATE-AUTHOR">'
            '<w:p><w:del><w:r><w:rPr><w:vanish/></w:rPr>'
            '<w:delText>PRIVATE-COMMENT</w:delText></w:r></w:del></w:p>'
            '</w:comment></w:comments>').encode()
        entries["word/header1.xml"] = (
            '<w:hdr xmlns:w="' + W + '"><w:p><w:ins><w:r><w:rPr>'
            '<w:webHidden w:val="false"/></w:rPr><w:t>PRIVATE-HEADER</w:t>'
            '</w:r></w:ins></w:p></w:hdr>').encode()
        report = review.review_docx(pack(entries))
        inventory = report["current"]["content_inventory"]
        self.assertEqual("enumerated_markers_only", inventory["state"])
        findings = inventory["findings"]
        comment = next(f for f in findings if f["element"] == "comment")
        self.assertEqual("word/comments.xml", comment["part"])
        self.assertEqual(sha256_bytes(entries[comment["part"]]), comment["part_sha256"])
        self.assertEqual("comments[1]/comment[1]", comment["locator"])
        self.assertEqual({"comment", "del", "vanish", "ins", "webHidden"},
                         {f["element"] for f in findings})
        hidden = next(f for f in findings if f["element"] == "webHidden")
        self.assertEqual("false", hidden["declared_value"])
        self.assertEqual("not_evaluated", hidden["effective_visibility"])
        serialized = json.dumps(inventory)
        self.assertNotIn("PRIVATE-", serialized)
        self.assertEqual("partial", report["current"]["readback_state"])
        self.assertIn("word/comments.xml", {p["path"] for p in report["current"]["unread_parts"]})
        self.assertEqual("not_performed", report["visual_review"])

    def test_inventory_ignores_foreign_names_and_does_not_certify_clean_file(self):
        entries = parts(self.raw)
        entries["custom/data.xml"] = b'<x:root xmlns:x="urn:unrelated"><x:ins/><x:vanish/><x:comment/></x:root>'
        report = review.review_docx(pack(entries))
        inventory = report["current"]["content_inventory"]
        self.assertEqual([], inventory["findings"])
        self.assertEqual("not_assessed", inventory["hidden_content_clearance"])
        self.assertIn("custom/data.xml", inventory["scanned_parts"])
        self.assertEqual("needs_review", report["status"])

    def test_inventory_is_bound_separately_to_current_and_baseline(self):
        def change(tree):
            run = tree.find(".//" + tag("r"))
            props = ET.Element(tag("rPr"))
            ET.SubElement(props, tag("vanish"), {tag("val"): "0"})
            run.insert(0, props)
        current = edited(self.raw, change)
        report = review.review_docx(current, self.raw)
        self.assertEqual([], report["baseline"]["content_inventory"]["findings"])
        findings = report["current"]["content_inventory"]["findings"]
        self.assertEqual(1, len(findings))
        self.assertEqual("0", findings[0]["declared_value"])
        self.assertEqual(sha256_bytes(parts(current)["word/document.xml"]), findings[0]["part_sha256"])
        self.assertTrue(report["comparison"]["main_literal_stream_equal"])
        self.assertEqual("complete_supported_subset", report["current"]["readback_state"])
        self.assertEqual("not_assessed", report["current"]["content_inventory"]["hidden_content_clearance"])

    def test_inventory_bounds_reject_instead_of_returning_partial_success(self):
        from unittest.mock import patch
        def change(tree):
            paragraph = tree.find(".//" + tag("p"))
            ET.SubElement(paragraph, tag("commentRangeStart"), {tag("id"): "1"})
            ET.SubElement(paragraph, tag("commentRangeEnd"), {tag("id"): "1"})
        raw = edited(self.raw, change)
        with patch.object(review, "MAX_INVENTORY_ITEMS", 1):
            with self.assertRaisesRegex(ContractError, "docx_inventory_count_limit"):
                review.review_docx(raw)
        with patch.object(review, "MAX_INVENTORY_NODES", 1):
            with self.assertRaisesRegex(ContractError, "docx_inventory_scan_limit"):
                review.review_docx(self.raw)

    def test_external_relationship_is_reported_without_fetch(self):
        entries = parts(self.raw)
        tree = ET.fromstring(entries["word/_rels/document.xml.rels"])
        ET.SubElement(tree, "{" + REL + "}Relationship", {"Id": "external", "Type": R + "/hyperlink",
                      "Target": "https://example.invalid/never-fetch", "TargetMode": "External"})
        entries["word/_rels/document.xml.rels"] = ET.tostring(tree)
        report = review.review_docx(pack(entries))
        self.assertIn("external_relationship_not_followed", {i["code"] for i in report["current"]["notices"]})
        self.assertEqual("not_performed", report["external_action"])

    def test_internal_anchor_and_missing_hyperlink_relationship_are_explicit(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            ET.SubElement(paragraph, tag("hyperlink"), {tag("anchor"): "CLAUSE9"})
            ET.SubElement(paragraph, tag("hyperlink"), {tag("anchor"): "MISSING_CLAUSE"})
            ET.SubElement(paragraph, tag("hyperlink"), {"{" + R + "}id": "missing_relationship"})
        report = review.review_docx(edited(self.raw, change))
        self.assertEqual("located_in_main_body", report["current"]["hyperlinks"][0]["anchor_state"])
        self.assertEqual("not_verified_in_main_body", report["current"]["hyperlinks"][1]["anchor_state"])
        codes = {item["code"] for item in report["current"]["notices"]}
        self.assertTrue({"hyperlink_anchor_not_verified", "hyperlink_relationship_not_verified"} <= codes)
        self.assertEqual("partial", report["current"]["readback_state"])

    def test_drawing_content_controls_and_altchunk_are_not_flattened(self):
        def change(tree):
            paragraph = tree.find("./" + tag("body") + "/" + tag("p"))
            for kind in ("drawing", "sdt", "altChunk"):
                node = ET.SubElement(paragraph, tag(kind))
                ET.SubElement(ET.SubElement(node, tag("r")), tag("t")).text = "不应当普通正文抽取"
        report = review.review_docx(edited(self.raw, change))
        self.assertNotIn("不应当普通正文抽取", report["current"]["blocks"][0]["text"])
        self.assertEqual(3, len(report["current"]["unresolved_fragments"]))

    def test_main_part_follows_opc_relationship_not_decoy_default_path(self):
        entries = parts(self.raw)
        entries["custom/review.xml"] = entries["word/document.xml"].replace("10 ms".encode(), "20 ms".encode())
        tree = ET.fromstring(entries["_rels/.rels"])
        tree[0].set("Target", "custom/review.xml")
        entries["_rels/.rels"] = ET.tostring(tree)
        tree = ET.fromstring(entries["[Content_Types].xml"])
        for node in tree:
            if node.get("PartName") == "/word/document.xml":
                node.set("PartName", "/custom/review.xml")
        entries["[Content_Types].xml"] = ET.tostring(tree)
        report = review.review_docx(pack(entries))
        self.assertEqual("custom/review.xml", report["current"]["main_part"])
        self.assertIn("20 ms", report["current"]["blocks"][1]["text"])
        self.assertIn("word/document.xml", [item["path"] for item in report["current"]["unread_parts"]])

    def test_ambiguous_or_external_main_relationship_is_rejected(self):
        for variant in ("ambiguous", "external", "escape"):
            entries = parts(self.raw)
            tree = ET.fromstring(entries["_rels/.rels"])
            if variant == "ambiguous":
                ET.SubElement(tree, "{" + REL + "}Relationship", {"Id": "second", "Type": R + "/officeDocument",
                              "Target": "word/document.xml"})
            elif variant == "external":
                tree[0].set("TargetMode", "External")
                tree[0].set("Target", "https://example.invalid/main.xml")
            else:
                tree[0].set("Target", "../outside.xml")
            entries["_rels/.rels"] = ET.tostring(tree)
            with self.subTest(variant=variant), self.assertRaises(ContractError):
                review.review_docx(pack(entries))

    def test_malformed_targets_case_aliases_and_unknown_encoding_fail_with_contract_errors(self):
        for value in ("//[", "word/%0adocument.xml", "word/document.xml?query=1"):
            entries = parts(self.raw)
            tree = ET.fromstring(entries["_rels/.rels"])
            tree[0].set("Target", value)
            entries["_rels/.rels"] = ET.tostring(tree)
            with self.subTest(target=value), self.assertRaises(ContractError):
                review.review_docx(pack(entries))
        entries = parts(self.raw)
        entries["word/Document.xml"] = entries["word/document.xml"]
        with self.assertRaisesRegex(ContractError, "docx_member_case_ambiguous"):
            review.review_docx(pack(entries))
        entries = parts(self.raw)
        entries["word/document.xml"] = b'<?xml version="1.0" encoding="unknown-test-encoding"?><x/>'
        with self.assertRaisesRegex(ContractError, "docx_xml_invalid"):
            review.review_docx(pack(entries))

    def test_duplicate_zip_members_and_unsafe_paths_are_rejected(self):
        target = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(target, "w") as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, content in parts(self.raw).items():
                archive.writestr(name, content)
            archive.writestr("word/document.xml", b"decoy")
        with self.assertRaisesRegex(ContractError, "docx_duplicate_member"):
            review.review_docx(target.getvalue())
        entries = parts(self.raw)
        entries["../outside.xml"] = b"<x/>"
        with self.assertRaisesRegex(ContractError, "docx_member_path_unsafe"):
            review.review_docx(pack(entries))

    def test_dtd_utf8_utf16_utf32_and_invalid_xml_are_rejected(self):
        xml = '<!DOCTYPE w:document [<!ENTITY hidden "never-expand">]><w:document xmlns:w="' + W + '"><w:body/></w:document>'
        for encoding in ("utf-8", "utf-16", "utf-32"):
            entries = parts(self.raw)
            entries["word/document.xml"] = xml.encode(encoding)
            with self.subTest(encoding=encoding), self.assertRaisesRegex(ContractError, "docx_dtd_or_entity_forbidden"):
                review.review_docx(pack(entries))
        entries["word/document.xml"] = b"<broken"
        with self.assertRaisesRegex(ContractError, "docx_xml_invalid"):
            review.review_docx(pack(entries))

    def test_unknown_word_namespace_and_macro_main_are_not_empty_success(self):
        entries = parts(self.raw)
        entries["word/document.xml"] = entries["word/document.xml"].replace(W.encode(), b"urn:unsupported-word")
        with self.assertRaisesRegex(ContractError, "docx_document_namespace_unsupported"):
            review.review_docx(pack(entries))
        entries = parts(self.raw)
        entries["[Content_Types].xml"] = entries["[Content_Types].xml"].replace(
            b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
            b"application/vnd.ms-word.document.macroEnabled.main+xml")
        with self.assertRaisesRegex(ContractError, "docx_main_content_type_unsupported"):
            review.review_docx(pack(entries))

    def test_size_member_count_and_depth_bounds_are_enforced(self):
        with self.assertRaisesRegex(ContractError, "docx_package_size_limit"):
            review.review_docx(b"x" * (review.MAX_PACKAGE_BYTES + 1))
        with self.assertRaisesRegex(ContractError, "docx_member_count_limit"):
            review.review_docx(pack({f"part{i}": b"" for i in range(review.MAX_MEMBERS + 1)}))
        entries = parts(self.raw)
        entries["word/document.xml"] = (b"<n>" * (review.MAX_XML_DEPTH + 1) +
                                         b"</n>" * (review.MAX_XML_DEPTH + 1))
        with self.assertRaisesRegex(ContractError, "docx_xml_structure_limit"):
            review.review_docx(pack(entries))
        with self.assertRaisesRegex(ContractError, "docx_package_invalid"):
            review.review_docx(b"not-a-zip")

    def test_cli_research_example_mode_is_not_reported_as_synthetic(self):
        with tempfile.TemporaryDirectory(prefix="dyz-docx-research-") as folder:
            root = Path(folder)
            (root / "research.docx").write_bytes(self.raw)
            args = [sys.executable, "-X", "utf8", "-m", "tools.document_review", "--research-example",
                    "--root", folder, "--input", "research.docx", "--expected-sha256", sha256_bytes(self.raw),
                    "--output", "readback.json"]
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            report = json.loads((root / "readback.json").read_text(encoding="utf-8"))
            self.assertEqual("research_example", report["mode"])
            self.assertEqual("caller_declaration_not_verified", report["material_classification"])
            self.assertEqual("not_performed", report["professional_review"])
            self.assertEqual(self.raw, (root / "research.docx").read_bytes())

    def test_cli_synthetic_precheck_hash_binding_new_output_and_no_source_mutation(self):
        with tempfile.TemporaryDirectory(prefix="dyz-docx-readback-") as folder:
            root = Path(folder)
            (root / "baseline.docx").write_bytes(self.raw)
            (root / "edited.docx").write_bytes(self.raw)
            base = [sys.executable, "-X", "utf8", "-m", "tools.document_review", "--root", folder,
                    "--input", "edited.docx", "--baseline", "baseline.docx", "--output", "review.json"]
            def run(args):
                return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15)
            denied = run(base)
            self.assertEqual(2, denied.returncode)
            self.assertEqual("synthetic_only", json.loads(denied.stdout)["error"])
            self.assertFalse((root / "review.json").exists())
            mismatch = run(base + ["--synthetic", "--expected-sha256", "0" * 64])
            self.assertEqual("docx_input_hash_changed", json.loads(mismatch.stdout)["error"])
            success = run(base + ["--synthetic", "--expected-sha256", sha256_bytes(self.raw),
                                  "--baseline-sha256", sha256_bytes(self.raw)])
            self.assertEqual(0, success.returncode, success.stderr + success.stdout)
            self.assertNotIn("阀门", success.stdout)
            self.assertEqual("needs_review", json.loads(success.stdout)["status"])
            first_report = (root / "review.json").read_bytes()
            self.assertEqual(2, run(base + ["--synthetic"]).returncode)
            self.assertEqual(first_report, (root / "review.json").read_bytes())
            self.assertEqual(self.raw, (root / "edited.docx").read_bytes())
            self.assertEqual(self.raw, (root / "baseline.docx").read_bytes())
            escape = run(base + ["--synthetic", "--output", "../escape.json"])
            self.assertEqual("unsafe_path", json.loads(escape.stdout)["error"])
            overwrite = run(base + ["--synthetic", "--output", "edited.docx"])
            self.assertEqual("docx_report_json_required", json.loads(overwrite.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
