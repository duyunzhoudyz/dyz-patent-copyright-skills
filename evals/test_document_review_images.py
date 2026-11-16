"""CORE-07：图像替换、引用与正文定位；开发合成检查，不是视觉或专业验收。"""
import io
import struct
import unittest
from unittest.mock import patch
import zipfile
import zlib
from xml.etree import ElementTree as ET

from tools import document_review as review
from tools.core import ContractError, sha256_bytes
from tools.documents import make_docx


W, R, REL, CT = review.W, review.R, review.REL, review.CT
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"


def png(pixel):
    def chunk(kind, raw):
        return struct.pack(">I", len(raw)) + kind + raw + struct.pack(">I", zlib.crc32(kind + raw))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"\x00" + pixel)) + chunk(b"IEND", b""))


RED, BLUE = png(b"\xff\x00\x00\xff"), png(b"\x00\x00\xff\xff")


def fixture(names=("FLOW",)):
    return make_docx([{"id": "BODY", "kind": "paragraph", "text": "合成图证字节与位置检查。"}],
                     [{"id": name, "png": RED, "width": 1, "height": 1} for name in names])


def parts(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def pack(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return out.getvalue()


def change_xml(entries, path, change):
    tree = ET.fromstring(entries[path])
    change(tree)
    entries[path] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)


class DocumentImageReviewTests(unittest.TestCase):
    def setUp(self):
        self.raw = fixture()

    def test_inline_image_has_actual_source_hash_location_and_review_limits(self):
        report = review.review_docx(self.raw, self.raw)
        drawing = report["current"]["drawings"][0]
        self.assertEqual(2, drawing["block_index"])
        self.assertTrue(drawing["locator"].endswith("/drawing[1]"))
        self.assertEqual("FLOW", drawing["doc_properties"][0]["name"])
        self.assertEqual("inline", drawing["containers"][0]["kind"])
        image = drawing["references"][0]
        self.assertEqual("embed", image["mode"])
        self.assertEqual("embedded_part_bound", image["state"])
        self.assertEqual("word/media/image1.png", image["part"])
        self.assertEqual(sha256_bytes(RED), image["sha256"])
        self.assertEqual(len(RED), image["bytes"])
        self.assertTrue(report["comparison"]["paired_drawings"][0]["embedded_bytes_equal"])
        self.assertEqual("partial", report["current"]["readback_state"])
        self.assertEqual("not_assessed", report["comparison"]["format_equivalence"])
        self.assertEqual("not_performed", report["visual_review"])
        self.assertEqual("not_performed", report["professional_review"])
        self.assertIn("word/media/image1.png", {p["path"] for p in report["current"]["unread_parts"]})

    def test_replaced_media_is_localized_even_when_drawing_and_text_did_not_change(self):
        entries = parts(self.raw)
        entries["word/media/image1.png"] = BLUE
        report = review.review_docx(pack(entries), self.raw)
        pair = report["comparison"]["paired_drawings"][0]
        self.assertEqual("FLOW", pair["name"])
        self.assertFalse(pair["embedded_bytes_equal"])
        self.assertTrue(pair["serialized_drawing_markup_equal"])
        self.assertTrue(report["comparison"]["main_literal_stream_equal"])
        self.assertEqual(sha256_bytes(RED), report["baseline"]["drawings"][0]["references"][0]["sha256"])
        self.assertEqual(sha256_bytes(BLUE), report["current"]["drawings"][0]["references"][0]["sha256"])
        self.assertTrue(pair["current_locator"].startswith("body/p[2]/"))

    def test_relationship_id_media_path_and_numeric_id_changes_are_not_image_changes(self):
        entries = parts(self.raw)
        entries["word/media/renamed.png"] = entries.pop("word/media/image1.png")
        def rels(tree):
            row = next(r for r in tree if r.get("Type") == R + "/image")
            row.set("Id", "renumbered")
            row.set("Target", "media/renamed.png")
        def body(tree):
            tree.find(".//{" + A + "}blip").set("{" + R + "}embed", "renumbered")
            tree.find(".//{" + WP + "}docPr").set("id", "99")
        change_xml(entries, "word/_rels/document.xml.rels", rels)
        change_xml(entries, "word/document.xml", body)
        pair = review.review_docx(pack(entries), self.raw)["comparison"]["paired_drawings"][0]
        self.assertTrue(pair["embedded_bytes_equal"])
        self.assertFalse(pair["serialized_drawing_markup_equal"])

    def test_crop_change_is_reported_separately_from_unchanged_image_bytes(self):
        entries = parts(self.raw)
        def crop(tree):
            fill = tree.find(".//{" + PIC + "}blipFill")
            ET.SubElement(fill, "{" + A + "}srcRect", {"l": "50000"})
        change_xml(entries, "word/document.xml", crop)
        report = review.review_docx(pack(entries), self.raw)
        pair = report["comparison"]["paired_drawings"][0]
        self.assertTrue(pair["embedded_bytes_equal"])
        self.assertFalse(pair["serialized_drawing_markup_equal"])
        self.assertEqual("not_assessed", report["comparison"]["format_equivalence"])

    def test_cached_embed_does_not_hide_linked_image_and_no_network_is_used(self):
        entries = parts(self.raw)
        change_xml(entries, "word/document.xml", lambda t: t.find(".//{" + A + "}blip").set("{" + R + "}link", "remote"))
        change_xml(entries, "word/_rels/document.xml.rels", lambda t: ET.SubElement(t, "{" + REL + "}Relationship", {
            "Id": "remote", "Type": R + "/image", "Target": "https://example.invalid/image.png", "TargetMode": "External"}))
        with patch("socket.socket", side_effect=AssertionError("network must not be used")):
            report = review.review_docx(pack(entries), self.raw)
        refs = report["current"]["drawings"][0]["references"]
        self.assertEqual(["embed", "link"], [r["mode"] for r in refs])
        self.assertEqual("embedded_part_bound", refs[0]["state"])
        self.assertEqual("linked_reference_not_followed", refs[1]["state"])
        self.assertNotIn("sha256", refs[1])
        self.assertIsNone(report["comparison"]["paired_drawings"][0]["embedded_bytes_equal"])

    def test_missing_relationship_wrong_kind_external_embed_and_missing_part_remain_unbound(self):
        variants = ["missing_relationship", "wrong_kind", "external_embed", "missing_part"]
        expected = ["relationship_missing", "relationship_type_mismatch", "external_reference_not_followed", "image_part_missing"]
        for variant, state in zip(variants, expected):
            with self.subTest(variant=variant):
                entries = parts(self.raw)
                rels = ET.fromstring(entries["word/_rels/document.xml.rels"])
                row = next(r for r in rels if r.get("Type") == R + "/image")
                if variant == "missing_relationship":
                    rels.remove(row)
                elif variant == "wrong_kind":
                    row.set("Type", R + "/hyperlink")
                elif variant == "external_embed":
                    row.set("TargetMode", "External")
                    row.set("Target", "https://example.invalid/image.png")
                else:
                    entries.pop("word/media/image1.png")
                entries["word/_rels/document.xml.rels"] = ET.tostring(rels)
                report = review.review_docx(pack(entries), self.raw)
                ref = report["current"]["drawings"][0]["references"][0]
                self.assertEqual(state, ref["state"])
                self.assertNotIn("sha256", ref)
                self.assertIsNone(report["comparison"]["paired_drawings"][0]["embedded_bytes_equal"])

    def test_duplicate_or_missing_names_are_not_paired_by_position_id_or_same_bytes(self):
        report = review.review_docx(fixture(("FLOW", "FLOW")), self.raw)
        self.assertEqual([], report["comparison"]["paired_drawings"])
        self.assertEqual(2, report["comparison"]["unresolved_drawings"][0]["current_occurrences"])
        entries = parts(self.raw)
        change_xml(entries, "word/document.xml", lambda t: t.find(".//{" + WP + "}docPr").attrib.pop("name"))
        report = review.review_docx(pack(entries), self.raw)
        self.assertEqual([], report["comparison"]["paired_drawings"])
        self.assertTrue(report["comparison"]["unresolved_drawings"])

    def test_container_is_recognized_as_anchor_without_claiming_layout(self):
        entries = parts(self.raw)
        change_xml(entries, "word/document.xml", lambda t: setattr(t.find(".//{" + WP + "}inline"), "tag", "{" + WP + "}anchor"))
        report = review.review_docx(pack(entries), self.raw)
        self.assertEqual("anchor", report["current"]["drawings"][0]["containers"][0]["kind"])
        self.assertEqual("not_assessed", report["comparison"]["format_equivalence"])
        self.assertEqual("partial", report["comparison"]["state"])

    def test_image_relationship_is_resolved_from_actual_opc_main_part(self):
        entries = parts(self.raw)
        entries["custom/body.xml"] = entries.pop("word/document.xml")
        rels = ET.fromstring(entries.pop("word/_rels/document.xml.rels"))
        for row in rels:
            row.set("Target", "../word/" + row.get("Target"))
        entries["custom/_rels/body.xml.rels"] = ET.tostring(rels)
        change_xml(entries, "_rels/.rels", lambda t: t[0].set("Target", "custom/body.xml"))
        def types(tree):
            next(n for n in tree if n.get("PartName") == "/word/document.xml").set("PartName", "/custom/body.xml")
        change_xml(entries, "[Content_Types].xml", types)
        report = review.review_docx(pack(entries))
        self.assertEqual("custom/body.xml", report["current"]["main_part"])
        self.assertEqual(sha256_bytes(RED), report["current"]["drawings"][0]["references"][0]["sha256"])

    def test_images_in_skipped_revision_are_not_promoted_to_current_body(self):
        entries = parts(self.raw)
        def revision(tree):
            body = tree.find("{" + W + "}body")
            paragraph = body.findall("{" + W + "}p")[1]
            run = paragraph.find("{" + W + "}r")
            paragraph.remove(run)
            ET.SubElement(paragraph, "{" + W + "}del").append(run)
        change_xml(entries, "word/document.xml", revision)
        report = review.review_docx(pack(entries))
        self.assertEqual([], report["current"]["drawings"])
        self.assertIn("revision_not_resolved", {n["code"] for n in report["current"]["notices"]})

    def test_drawing_and_reference_counts_are_bounded(self):
        with patch.object(review, "MAX_DRAWINGS", 1):
            with self.assertRaisesRegex(ContractError, "docx_drawing_count_limit"):
                review.review_docx(fixture(("A", "B")))
        with patch.object(review, "MAX_IMAGE_REFERENCES", 0):
            with self.assertRaisesRegex(ContractError, "docx_image_reference_count_limit"):
                review.review_docx(self.raw)


if __name__ == "__main__":
    unittest.main()
