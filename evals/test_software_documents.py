"""软件候选逻辑页的内存DOCX装配；不冒充渲染后的物理页验收。"""
import base64
import copy
import io
import struct
import sys
import unittest
import warnings
import zipfile
import zlib
from unittest.mock import patch
from xml.etree import ElementTree as ET

from tools import documents
from tools.core import ContractError, sha256_bytes


W = "{" + documents.W + "}"
NS = {"w": documents.W, "r": documents.R, "wp": documents.WP,
      "a": documents.A, "rel": documents.REL}


def legacy_docx_hash(*, windows, unix):
    """同一 3.11 基准包保留成员和元数据，仅替换压缩器及 ZIP 宿主标记。"""
    classic, ng = windows if sys.platform == "win32" else unix
    if hasattr(zlib, "ZLIBNG_VERSION") or "zlib-ng" in zlib.ZLIB_RUNTIME_VERSION:
        return ng
    return classic


def png(width=120, height=80):
    """纯合成RGB测试图，既不抓屏也不声明是真实操作证据。"""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = (b"\x00" + b"\xff\xff\xff" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def parts(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        return {name: package.read(name) for name in package.namelist()}


def repack(items):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as package:
        for name, value in items:
            package.writestr(name, value)
    return stream.getvalue()


def text(node):
    return "".join(element.text or "" if element.tag == W + "t"
                   else "\t" if element.tag == W + "tab"
                   else "\n" if element.tag == W + "br" else ""
                   for element in node.iter())


class SoftwareDocumentTests(unittest.TestCase):
    def setUp(self):
        self.options = {"title": "合成软件 & <测试>", "version": "V1.0", "kind": "source"}
        self.pages = [
            [{"id": "Copyright", "kind": "code", "text": "# Copyright © 2026 原作者"},
             {"id": "Empty", "kind": "code", "text": ""},
             {"id": "Literal", "kind": "code",
              "text": '\treturn "<a href=\"https://example.invalid/?a=1&b=2\">链接</a>"  '}],
            [{"id": "Next", "kind": "code", "text": "    pass"}],
        ]

    def make(self, pages=None, **options):
        self.assertTrue(callable(getattr(documents, "make_software_docx", None)),
                        "missing make_software_docx API")
        return documents.make_software_docx(
            self.pages if pages is None else pages, **{**self.options, **options})

    def inspect(self, raw, pages=None, **options):
        self.assertTrue(callable(getattr(documents, "inspect_software_docx", None)),
                        "missing inspect_software_docx API")
        return documents.inspect_software_docx(
            raw, self.pages if pages is None else pages, **{**self.options, **options})

    def test_source_lines_preserve_empty_tabs_markup_url_and_copyright(self):
        raw = self.make()
        document = ET.fromstring(parts(raw)["word/document.xml"])
        paragraphs = document.findall("./w:body/w:p", NS)
        self.assertEqual([text(p) for p in paragraphs],
                         [block["text"] for page in self.pages for block in page])
        self.assertEqual(len(document.findall(".//w:hyperlink", NS)), 0)
        self.assertEqual([e.get(W + "name") for e in document.findall(".//w:bookmarkStart", NS)],
                         ["Copyright", "Empty", "Literal", "Next"])
        result = self.inspect(raw)
        self.assertTrue(result["source_text_equal"])
        self.assertTrue(result["generated_package_parts_equal"])
        self.assertTrue(result["media_equal"])
        self.assertTrue(result["no_external_relationships"])
        self.assertEqual(result["paragraphs"], 4)

    def test_explicit_pages_are_break_before_not_physical_page_claims(self):
        raw = self.make()
        document = ET.fromstring(parts(raw)["word/document.xml"])
        paragraphs = document.findall("./w:body/w:p", NS)
        self.assertEqual([i for i, p in enumerate(paragraphs)
                          if p.find("w:pPr/w:pageBreakBefore", NS) is not None], [0, 3])
        result = self.inspect(raw)
        self.assertEqual(result["logical_pages"], 2)
        self.assertEqual(result["pagination_basis"], "candidate_logical_pages")
        self.assertFalse(result["physical_pagination_verified"])
        self.assertEqual(result["visual_review"], "not_performed")

    def test_a4_margins_headers_and_page_number_field(self):
        package = parts(self.make())
        document = ET.fromstring(package["word/document.xml"])
        section = document.find("./w:body/w:sectPr", NS)
        self.assertEqual(len(document.findall(".//w:sectPr", NS)), 1)
        self.assertEqual(section.find("w:pgSz", NS).attrib,
                         {W + "w": "11906", W + "h": "16838"})
        margins = section.find("w:pgMar", NS)
        for side in ("top", "bottom", "left", "right"):
            self.assertEqual(margins.get(W + side), "1134")
        for side in ("header", "footer"):
            self.assertEqual(margins.get(W + side), "567")
        self.assertEqual(text(ET.fromstring(package["word/header1.xml"])),
                         self.options["title"] + " " + self.options["version"])
        footer = ET.fromstring(package["word/footer1.xml"])
        field = footer.find(".//w:fldSimple", NS)
        self.assertEqual(field.get(W + "instr").strip(), "PAGE")
        self.assertEqual(text(footer), "1")
        rels = ET.fromstring(package["word/_rels/document.xml.rels"])
        for kind in ("header", "footer"):
            ref = section.find("w:" + kind + "Reference", NS)
            relation = next(r for r in rels if r.get("Id") == ref.get("{" + documents.R + "}id"))
            self.assertEqual(relation.get("Target"), kind + "1.xml")
            self.assertEqual(relation.get("Type"), documents.R + "/" + kind)
            self.assertIn(("/word/" + kind + "1.xml").encode(), package["[Content_Types].xml"])

    def test_source_font_spacing_and_long_line_are_not_truncated(self):
        long_line = "\t" + "代码abc" * 4000 + "  "
        pages = [[{"id": "Long", "kind": "code", "text": long_line}]]
        package = parts(self.make(pages))
        document = ET.fromstring(package["word/document.xml"])
        self.assertEqual(text(document.find("./w:body/w:p", NS)), long_line)
        styles = ET.fromstring(package["word/styles.xml"])
        code = styles.find("w:style[@w:styleId='Code']", NS)
        self.assertEqual(code.find("w:rPr/w:sz", NS).get(W + "val"), "18")
        fonts = code.find("w:rPr/w:rFonts", NS)
        self.assertEqual(fonts.get(W + "ascii"), "Consolas")
        self.assertEqual(fonts.get(W + "hAnsi"), "Consolas")
        self.assertEqual(fonts.get(W + "eastAsia"), "Microsoft YaHei")
        spacing = code.find("w:pPr/w:spacing", NS)
        self.assertEqual(spacing.get(W + "line"), "240")
        self.assertEqual(spacing.get(W + "lineRule"), "exact")
        self.assertEqual(spacing.get(W + "before"), "0")
        self.assertEqual(spacing.get(W + "after"), "0")
        self.assertTrue(self.inspect(self.make(pages), pages)["source_text_equal"])

    def test_code_four_character_tab_stops_fit_body_without_changing_text(self):
        original = "\t" * 19 + "x\t" + "保留原始制表符"
        pages = [[{"id": "Tabs", "kind": "code", "text": original}]]
        raw = self.make(pages)
        package = parts(raw)
        document = ET.fromstring(package["word/document.xml"])
        self.assertEqual(text(document.find("./w:body/w:p", NS)), original)
        styles = ET.fromstring(package["word/styles.xml"])
        code = styles.find("w:style[@w:styleId='Code']", NS)
        stops = code.findall("w:pPr/w:tabs/w:tab", NS)
        self.assertEqual([int(stop.get(W + "pos")) for stop in stops],
                         list(range(396, 9638 + 1, 396)))
        self.assertTrue(all(stop.get(W + "val") == "left" for stop in stops))
        section = document.find("./w:body/w:sectPr", NS)
        size = section.find("w:pgSz", NS)
        margins = section.find("w:pgMar", NS)
        body_width = int(size.get(W + "w")) - int(margins.get(W + "left")) - int(margins.get(W + "right"))
        self.assertLessEqual(max(int(stop.get(W + "pos")) for stop in stops), body_width)
        self.assertTrue(self.inspect(raw, pages)["source_text_equal"])

    def test_multiline_code_is_one_paragraph_per_line_with_one_bookmark(self):
        pages = [[{"id": "Block", "kind": "code", "text": "\n\tfirst\n\nlast\n"}]]
        raw = self.make(pages)
        document = ET.fromstring(parts(raw)["word/document.xml"])
        self.assertEqual([text(p) for p in document.findall("./w:body/w:p", NS)],
                         ["", "\tfirst", "", "last", ""])
        self.assertEqual(len(document.findall(".//w:bookmarkStart", NS)), 1)
        self.assertEqual(len(document.findall(".//w:bookmarkEnd", NS)), 1)
        self.assertEqual(self.inspect(raw, pages)["paragraphs"], 5)

    def test_inline_png_position_caption_and_aspect_ratio_without_svg(self):
        image = {"id": "Screenshot", "kind": "image", "png": png(1200, 200),
                 "width": 1200, "height": 200, "text": "合成测试图，非真实截图证据"}
        pages = [[{"id": "Start", "kind": "heading1", "text": "操作示例"},
                  image, {"id": "After", "kind": "paragraph", "text": "图后步骤"}]]
        raw = self.make(pages, kind="manual")
        package = parts(raw)
        document = ET.fromstring(package["word/document.xml"])
        paragraphs = document.findall("./w:body/w:p", NS)
        self.assertIsNotNone(paragraphs[1].find(".//w:drawing", NS))
        self.assertEqual([text(p) for p in paragraphs],
                         ["操作示例", "", image["text"], "图后步骤"])
        self.assertIsNone(paragraphs[1].find("w:pPr/w:pageBreakBefore", NS))
        extent = document.find(".//wp:extent", NS)
        self.assertEqual(int(extent.get("cx")), 5940000)
        self.assertEqual(int(extent.get("cy")), 990000)
        self.assertEqual(package["word/media/image1.png"], image["png"])
        self.assertFalse(any(name.endswith(".svg") for name in package))
        self.assertEqual(self.inspect(raw, pages, kind="manual")["figures"], 1)
        styles = ET.fromstring(package["word/styles.xml"])
        normal = styles.find("w:style[@w:styleId='Normal']", NS)
        self.assertEqual(normal.find("w:pPr/w:spacing", NS).get(W + "line"), "280")
        self.assertEqual(normal.find("w:pPr/w:spacing", NS).get(W + "lineRule"), "atLeast")

    def test_tall_image_cap_and_image_first_page_break(self):
        pages = [[{"id": "Tall", "kind": "image", "png": png(20, 200),
                   "width": 20, "height": 200}]]
        raw = self.make(pages, kind="manual")
        document = ET.fromstring(parts(raw)["word/document.xml"])
        p = document.find("./w:body/w:p", NS)
        self.assertIsNotNone(p.find("w:pPr/w:pageBreakBefore", NS))
        extent = p.find(".//wp:extent", NS)
        self.assertEqual((int(extent.get("cx")), int(extent.get("cy"))), (360000, 3600000))
        self.assertEqual(document.find(".//w:bookmarkStart", NS).get(W + "name"), "Tall")
        self.assertEqual(self.inspect(raw, pages, kind="manual")["paragraphs"], 1)

    def test_worksheet_normal_heading_styles_and_all_kinds_are_deterministic(self):
        pages = [[{"id": "Title", "kind": "heading1", "text": "字段核对"},
                  {"id": "Field", "kind": "heading2", "text": "名称"},
                  {"id": "Value", "kind": "paragraph", "text": "原值\t不改写\n第二行"}]]
        before = copy.deepcopy(pages)
        for kind in ("source", "manual", "worksheet"):
            with self.subTest(kind=kind):
                first = self.make(pages, kind=kind)
                self.assertEqual(first, self.make(pages, kind=kind))
                self.assertTrue(self.inspect(first, pages, kind=kind)["source_text_equal"])
        self.assertEqual(pages, before)

    def test_invalid_metadata_kind_page_and_block_shapes(self):
        for options in ({"title": ""}, {"title": 5}, {"version": " "},
                        {"version": "v1\nv2"}, {"title": "x\tY"},
                        {"kind": "patent"}, {"kind": []}):
            with self.subTest(options=options), self.assertRaises(ContractError):
                self.make(**options)
        for pages in (None, "text", [], [[]], ["line"], [[None]],
                      [[{}]], [[{"id": "A", "kind": "paragraph"}]],
                      [[{"id": "A", "kind": "unknown", "text": "x"}]],
                      [[{"id": "A", "kind": "paragraph", "text": 1}]]):
            with self.subTest(pages=pages), self.assertRaises(ContractError):
                self.assertTrue(callable(getattr(documents, "make_software_docx", None)),
                                "missing make_software_docx API")
                documents.make_software_docx(pages, **self.options)

    def test_duplicate_or_unsafe_bookmarks_and_xml_controls_rejected(self):
        for identity in ("中文", "has space", "1start", "A" * 40, "a-b", None):
            with self.subTest(identity=identity), self.assertRaises(ContractError):
                self.make([[{"id": identity, "kind": "code", "text": "x"}]])
        with self.assertRaises(ContractError):
            self.make([[{"id": "A", "kind": "code", "text": "x"}],
                       [{"id": "A", "kind": "code", "text": "y"}]])
        for invalid in ("\x00", "\x0b", "\ud800", "\ufffe", "\uffff", "\r"):
            with self.subTest(character=repr(invalid)), self.assertRaises(ContractError):
                self.make([[{"id": "A", "kind": "code", "text": "before" + invalid}]])
        with self.assertRaises(ContractError):
            self.make(title="Title\x00")

    def test_png_format_dimensions_crc_and_truncation_are_checked(self):
        image = {"id": "Image", "kind": "image", "png": png(120, 80),
                 "width": 120, "height": 80}
        for change in ({"width": 0}, {"height": True}, {"width": 121},
                       {"height": 20001}, {"png": b"not a PNG"},
                       {"png": image["png"][:24]}, {"png": image["png"][:-1]},
                       {"png": image["png"] + b"trailing"},
                       {"png": image["png"][:-8] + b"IENDbad!"},
                       {"text": "bad\x00caption"}):
            with self.subTest(fields=list(change)), self.assertRaises(ContractError):
                self.make([[{**image, **change}]], kind="manual")

    def test_exact_package_check_rejects_text_media_style_and_external_tampering(self):
        pages = [[self.pages[0][0], {"id": "Image", "kind": "image",
                  "png": png(), "width": 120, "height": 80}]]
        original = parts(self.make(pages, kind="manual"))
        faults = {
            "body": ("word/document.xml", lambda b: b.replace(b"2026", b"2027")),
            "style": ("word/styles.xml", lambda b: b.replace(b'val="18"', b'val="19"', 1)),
            "header": ("word/header1.xml", lambda b: b.replace(b"V1.0", b"V9.0")),
            "footer": ("word/footer1.xml", lambda b: b.replace(b"PAGE", b"DATE")),
            "media": ("word/media/image1.png", lambda b: b[:-1] + bytes([b[-1] ^ 1])),
            "external": ("word/_rels/document.xml.rels", lambda b: b.replace(
                b'Target="styles.xml"', b'Target="https://example.invalid" TargetMode="External"')),
            "hidden": ("word/document.xml", lambda b: b.replace(
                b"<w:r>", b"<w:r><w:rPr><w:vanish /></w:rPr>", 1)),
        }
        for name, (part, change) in faults.items():
            with self.subTest(fault=name):
                changed = {**original, part: change(original[part])}
                self.assertNotEqual(changed[part], original[part])
                with self.assertRaises(ContractError):
                    self.inspect(repack(changed.items()), pages, kind="manual")
        with self.assertRaises(ContractError):
            self.inspect(repack({**original, "word/comments.xml": b"private note"}.items()),
                         pages, kind="manual")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicate = repack([*original.items(), ("word/document.xml", original["word/document.xml"])])
        with self.assertRaises(ContractError):
            self.inspect(duplicate, pages, kind="manual")
        with self.assertRaises(ContractError):
            self.inspect(b"not a zip", pages, kind="manual")

    def test_wrong_title_version_or_logical_page_binding_rejected(self):
        raw = self.make()
        for changed in ({"title": "Another"}, {"version": "V2.0"}, {"kind": "manual"}):
            with self.subTest(changed=changed), self.assertRaises(ContractError):
                self.inspect(raw, **changed)
        with self.assertRaises(ContractError):
            self.inspect(raw, [self.pages[0] + self.pages[1]])

    def test_pure_memory_api_does_not_use_files_or_svg_gate(self):
        with patch.object(documents, "_read", side_effect=AssertionError("filesystem read")), \
             patch.object(documents, "_svg", side_effect=AssertionError("SVG required")), \
             patch.object(documents.subprocess, "run", side_effect=AssertionError("external program")):
            raw = self.make()
            self.assertTrue(self.inspect(raw)["source_text_equal"])

    def test_legacy_fixture_bytes_are_unchanged_by_new_shared_helpers(self):
        block = [{"id": "Legacy", "kind": "paragraph", "text": "旧合成入口，不改门禁。"}]
        raw = documents.make_docx(block, [])
        self.assertEqual(sha256_bytes(raw), legacy_docx_hash(
            windows=("b36db6eccf78fbf82b861d11c2b82d5e2758d2aa1431cd67c4e051dfd3c7b4e8",
                     "62c6ad5b4dc6004cbfc9c91b5765d62c6ebda90901b0dd1a1615edd4ab61a22a"),
            unix=("46a5299651ab14b6353619721197d5497127ac863d13cf28e8869e158a1ea4cf",
                  "faeaa88546ca1d9977acffbff39d48e766e956b132d9ed697ab3e24ae3a9b5d8")))
        # 原 3.11 png(120, 80) 的完整字节；IDAT 不能随外层 ZIP 压缩器变化。
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAHgAAABQCAIAAABd+SbeAAAAxUlEQVR4nO3QQREAMAjA"
            "MPybHi6yB42CXueFmN8BVzQaaTTSaKTRSKORRiONRhqNNBppNNJopNFIo5FGI41GGo00"
            "Gmk00mik0UijkUYjjUYajTQaaTTSaKTRSKORRiONRhqNNBppNNJopNFIo5FGI41GGo00"
            "Gmk00mik0UijkUYjjUYajTQaaTTSaKTRSKORRiONRhqNNBppNNJopNFIo5FGI41GGo00"
            "Gmk00mik0UijkUYjjUYajTQaaTTSaKTRSKORRiMLMEMWEfUbSmoAAAAASUVORK5CYII=",
            validate=True)
        images = [{"id": "Figure", "png": image, "width": 120, "height": 80}]
        with_image = documents.make_docx(block, images)
        self.assertEqual(sha256_bytes(with_image), legacy_docx_hash(
            windows=("4dde00772315c433c80ddb8e0e6191a6eb38bcf8b2e1d2e75ca05ee34aae8cef",
                     "685c6d79ca3d84c0e5792653cbff02292a602818a73b43ad3e4ab6eb8f098453"),
            unix=("3c63c5e24a1ccd84d353d1a78de568d780999f4856f960fee50cc5e31435e027",
                  "2e8a106b8f20852177288c71b50b4f98c50b301599fc4518c8c9436f9f977cd8")))
        self.assertTrue(documents.inspect_generated_docx(raw, block, [])["source_text_equal"])
        self.assertTrue(documents.inspect_generated_docx(with_image, block, images)["source_text_equal"])


if __name__ == "__main__":
    unittest.main()
