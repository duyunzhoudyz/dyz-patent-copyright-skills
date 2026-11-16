"""修订导入纯内存测试：正文保留、稳定ID、来源降级及显式拒绝。"""

import copy
import io
import struct
import unittest
import warnings
import zipfile
import zlib
from unittest.mock import patch
from xml.etree import ElementTree as ET

from tools import documents, software_revision as revision
from tools.core import ContractError

W = "{" + revision.W + "}"


def png():
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0\xff\xff\xff\0\0\0"))
            + chunk(b"IEND", b""))


def package(parts):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items() if isinstance(parts, dict) else parts:
            archive.writestr(name, value)
    return stream.getvalue()


def unpack(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def xml(node):
    return ET.tostring(node, encoding="utf-8", xml_declaration=True)


def sample_docx():
    return documents.make_software_docx(
        [[{"id": "Title", "kind": "heading1", "text": "合成工具"},
          {"id": "Section", "kind": "heading2", "text": "执行流程"},
          {"id": "Prose", "kind": "paragraph", "text": "先检查。\n再运行。\t保留制表符"},
          {"id": "Code", "kind": "code", "text": "print('<body>')"},
          {"id": "Figure", "kind": "image", "text": "合成演示图",
           "png": png(), "width": 2, "height": 1}]],
        title="合成工具", version="V1.0", kind="manual")


class MarkdownRevisionTests(unittest.TestCase):
    def test_preserves_supported_text_and_anchor(self):
        text = (
            "# 合成工具\n\n## 功能\n\n"
            "<!-- block:Flow evidence:EV1,EV2 status:confirmed operation:OP1 -->\n"
            "第一段**强调**。\n保留整段第二行。\n\n"
            "- 项目一\n- 项目二\n  续行\n\n"
            "```python\n\tprint('<div>')  \n\n```\n\n"
            "| 字段 | 内容 |\n| --- | :---: |\n| 名称 | 完整\\|文本 |\n")
        parsed = revision.parse_markdown(text)
        self.assertEqual([b["kind"] for b in parsed["blocks"]],
                         ["heading1", "heading2", "paragraph", "list", "code", "table"])
        paragraph = parsed["blocks"][2]
        self.assertEqual(paragraph["text"], "第一段**强调**。\n保留整段第二行。")
        self.assertEqual(paragraph["id"], "Flow")
        self.assertEqual(paragraph["status"], "confirmed")
        self.assertEqual(paragraph["evidence_ids"], ["EV1", "EV2"])
        self.assertEqual(paragraph["operation_id"], "OP1")
        self.assertEqual(parsed["blocks"][4]["text"], "\tprint('<div>')  \n")
        self.assertEqual(parsed["blocks"][5]["cells"],
                         [["字段", "内容"], ["名称", "完整|文本"]])
        self.assertEqual(parsed["metadata"]["title"], "合成工具")
        self.assertEqual(parsed["metadata"]["identity_verification"], "not_performed")
        self.assertEqual(text.splitlines()[0], "# 合成工具")

    def test_same_draft_stable_ids_and_reorder_content_ids(self):
        text = "# 名称\n\n第一段。\n\n第二段。\n\n第一段。"
        first = revision.parse_markdown(text)
        self.assertEqual(first, revision.parse_markdown(text))
        identities = [b["id"] for b in first["blocks"]]
        self.assertEqual(len(identities), len(set(identities)))
        moved = revision.parse_markdown("第二段。\n\n# 名称\n\n第一段。\n\n第一段。")
        self.assertEqual(set(identities), {b["id"] for b in moved["blocks"]})

    def test_confirmed_without_source_is_downgraded(self):
        block = revision.parse_markdown(
            "<!-- block:Facts status:confirmed -->\n仅为输入声明。")['blocks'][0]
        self.assertEqual(block["status"], "needs_review")
        self.assertEqual(block["evidence_ids"], [])

    def test_relative_inline_png_is_reference_only_and_ordered(self):
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("read forbidden")):
            result = revision.parse_markdown(
                "<!-- block:Picture evidence:EV1 status:confirmed -->\n"
                "前文![操作图](images/view.png)后文")
        blocks = result["blocks"]
        self.assertEqual([b["kind"] for b in blocks], ["paragraph", "image", "paragraph"])
        self.assertEqual([b["text"] for b in blocks], ["前文", "操作图", "后文"])
        self.assertEqual(blocks[0]["id"], "Picture")
        self.assertEqual(blocks[1]["image_id"], result["images"][0]["image_id"])
        self.assertEqual(result["images"][0]["png"], None)
        self.assertEqual(result["images"][0]["path"], "images/view.png")
        self.assertEqual([b["status"] for b in blocks], ["confirmed"] * 3)
        self.assertEqual(len(revision.parse_markdown(
            "![一](a.png) ![二](a.png)")["images"]), 1)

    def test_rejects_unsafe_or_ambiguous_image_references(self):
        for target in ("https://example.invalid/a.png", "http://x/a.png",
                       "file:///C:/a.png", "C:/a.png", "/a.png", "../a.png",
                       "dir/../a.png", "dir\\a.png", "%2e%2e/a.png", "a.svg",
                       "a.png?q=1", "a.png#frag", "a.png \"title\"", "//server/a.png",
                       "data:image/png;base64,AAAA", "a(1).png"):
            with self.subTest(target=target), self.assertRaises(ContractError):
                revision.parse_markdown(f"![图]({target})")

    def test_rejects_html_and_unsupported_comments(self):
        for text in ("<script>alert(1)</script>", "<img src='a.png'>",
                     "正文<div>后文", "<!-- arbitrary -->\n正文", "<!DOCTYPE html>"):
            with self.subTest(text=text), self.assertRaises(ContractError):
                revision.parse_markdown(text)
        # 代码块里的字面HTML不解释成可执行对象。
        self.assertEqual(revision.parse_markdown("```html\n<div>文字</div>\n```")
                         ["blocks"][0]["text"], "<div>文字</div>")

    def test_rejects_bad_anchor_or_unsupported_structure(self):
        for text in ("<!-- block:A -->", "<!-- block:A -->\n<!-- block:B -->\n文字",
                     "<!-- block:A status:accepted -->\n文字",
                     "<!-- block:A evidence:X,X -->\n文字",
                     "<!-- block:A evidence: -->\n文字",
                     "<!-- block:A actor:person -->\n文字",
                     "<!-- block:A -->\n一\n\n<!-- block:A -->\n二",
                     "```\n未结束", "### 不支持的层级", "| A | B |\n| --- | --- |\n| X |",
                     "- ![图](a.png)", "# ![图](a.png)", "![图][ref]"):
            with self.subTest(text=text), self.assertRaises(ContractError):
                revision.parse_markdown(text)

    def test_type_empty_size_and_unicode_boundaries(self):
        for value in (None, b"text", "", " \n\n", "bad\x00text", "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(ContractError):
                revision.parse_markdown(value)
        with patch.object(revision, "MAX_INPUT_BYTES", 3), self.assertRaises(ContractError):
            revision.parse_markdown("四个字节以上")


class DocxRevisionTests(unittest.TestCase):
    def setUp(self):
        self.raw = sample_docx()
        self.parts = unpack(self.raw)

    def modify_document(self, modify):
        document = ET.fromstring(self.parts["word/document.xml"])
        modify(document)
        return package({**self.parts, "word/document.xml": xml(document)})

    def test_project_generated_docx_imports_text_inline_png_and_headers(self):
        original = self.raw[:]
        parsed = revision.parse_docx(self.raw)
        self.assertEqual(self.raw, original)
        self.assertEqual(parsed, revision.parse_docx(self.raw))
        self.assertEqual([b["kind"] for b in parsed["blocks"]],
                         ["heading1", "heading2", "paragraph", "code", "image", "paragraph"])
        self.assertEqual(parsed["blocks"][2]["text"], "先检查。\n再运行。\t保留制表符")
        self.assertEqual(parsed["blocks"][0]["id"], "Title")
        self.assertEqual(parsed["blocks"][3]["text"], "print('<body>')")
        self.assertEqual(parsed["images"][0]["png"], png())
        self.assertEqual(parsed["images"][0]["width"], 2)
        self.assertEqual(parsed["images"][0]["height"], 1)
        self.assertEqual(parsed["images"][0]["sha256"],
                         __import__("hashlib").sha256(png()).hexdigest())
        self.assertEqual(parsed["blocks"][4]["image_id"], parsed["images"][0]["image_id"])
        self.assertTrue(all(b["status"] == "needs_review" and not b["evidence_ids"]
                            for b in parsed["blocks"]))
        self.assertEqual(parsed["metadata"]["auxiliary_text"],
                         {"word/header1.xml": "合成工具 V1.0", "word/footer1.xml": ""})

    def test_skips_layout_blank_paragraphs_preserving_code_whitespace(self):
        blocks = [
            {"id": "Intro", "kind": "paragraph", "text": "首段"},
            {"id": "Empty", "kind": "paragraph", "text": ""},
            {"id": "Spaces", "kind": "paragraph", "text": " \t\n "},
            {"id": "Code", "kind": "code", "text": "first()"},
            {"id": "Last", "kind": "paragraph", "text": "末段"},
        ]
        raw = documents.make_software_docx([blocks], title="合成工具", version="1.0", kind="manual")
        parts = unpack(raw)
        document = ET.fromstring(parts["word/document.xml"])
        paragraph = next(p for p in document.findall("w:body/w:p", revision.NS)
                         if p.find("w:pPr/w:pStyle", revision.NS).get(W + "val") == "Code")
        run = paragraph.find("w:r", revision.NS)
        ET.SubElement(run, W + "br")
        ET.SubElement(run, W + "br")
        ET.SubElement(run, W + "t").text = "  second()"
        ET.SubElement(run, W + "br")
        blocks[3]["text"] = "first()\n\n  second()\n"
        parsed = revision.parse_docx(package({**parts, "word/document.xml": xml(document)}))
        self.assertEqual([(block["id"], block["text"]) for block in parsed["blocks"]],
                         [(block["id"], block["text"]) for block in blocks
                          if block["id"] not in {"Empty", "Spaces"}])

    def test_cli_imports_docx_with_layout_blank_paragraphs(self):
        from evals.test_software_prepare import SoftwarePrepareCliTests
        from tools import core

        case = SoftwarePrepareCliTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        code_text = "first()\n\n  second()\n"
        raw = documents.make_software_docx([[
            {"id": "Intro", "kind": "paragraph", "text": "首段"},
            {"id": "Empty", "kind": "paragraph", "text": ""},
            {"id": "Spaces", "kind": "paragraph", "text": " \t "},
            {"id": "Code", "kind": "code", "text": "first()"},
            {"id": "Last", "kind": "paragraph", "text": "末段"},
        ]], title="合成计数器", version="1.0", kind="manual")
        parts = unpack(raw)
        document = ET.fromstring(parts["word/document.xml"])
        paragraph = next(p for p in document.findall("w:body/w:p", revision.NS)
                         if p.find("w:pPr/w:pStyle", revision.NS).get(W + "val") == "Code")
        run = paragraph.find("w:r", revision.NS)
        ET.SubElement(run, W + "br")
        ET.SubElement(run, W + "br")
        ET.SubElement(run, W + "t").text = "  second()"
        ET.SubElement(run, W + "br")
        raw = package({**parts, "word/document.xml": xml(document)})
        (case.root / "revision.docx").write_bytes(raw)
        sha256 = core.sha256_bytes(raw)
        case.request["manual_revision"] = {"path": "revision.docx", "sha256": sha256,
                                           "format": "docx"}
        case.authorization["files"].append({"path": "revision.docx", "sha256": sha256})
        case.save_request()
        args = case.args()
        args[0] = "import-software-manual"
        self.assertEqual(case.invoke(args), (0, "result_written\n", ""))
        blocks = case.result()["artifacts"]["manual"]["blocks"]
        self.assertEqual([block["text"] for block in blocks], ["首段", code_text, "末段"])
        self.assertTrue(all(block["status"] == "needs_review" for block in blocks))

    def test_list_and_table_preserve_all_rows_and_cell_paragraphs(self):
        def insert(document):
            body = document.find("w:body", revision.NS)
            paragraph = ET.Element(W + "p")
            props = ET.SubElement(paragraph, W + "pPr")
            numbers = ET.SubElement(props, W + "numPr")
            ET.SubElement(numbers, W + "ilvl", {W + "val": "0"})
            ET.SubElement(numbers, W + "numId", {W + "val": "1"})
            ET.SubElement(ET.SubElement(paragraph, W + "r"), W + "t").text = "列表内容"
            body.insert(2, paragraph)
            table = ET.Element(W + "tbl")
            for values in (("字段", "说明"), ("名称", "第一行\n第二行")):
                row = ET.SubElement(table, W + "tr")
                for value in values:
                    cell = ET.SubElement(row, W + "tc")
                    for line in value.split("\n"):
                        ET.SubElement(ET.SubElement(ET.SubElement(cell, W + "p"),
                                                   W + "r"), W + "t").text = line
            body.insert(3, table)
        parsed = revision.parse_docx(self.modify_document(insert))
        self.assertEqual(parsed["blocks"][2]["kind"], "list")
        self.assertEqual(parsed["blocks"][2]["numbering_id"], "1")
        table = parsed["blocks"][3]
        self.assertEqual(table["kind"], "table")
        self.assertEqual(table["cells"], [["字段", "说明"], ["名称", "第一行\n第二行"]])
        self.assertEqual(table["text"], "字段\t说明\n名称\t第一行\n第二行")

    def test_custom_heading_based_on_and_outline_styles(self):
        styles = ET.fromstring(self.parts["word/styles.xml"])
        custom = ET.SubElement(styles, W + "style", {W + "styleId": "CustomTitle"})
        ET.SubElement(custom, W + "basedOn", {W + "val": "Heading1"})
        self.parts["word/styles.xml"] = xml(styles)
        def alter(document):
            document.find(".//w:pStyle", revision.NS).set(W + "val", "CustomTitle")
        self.assertEqual(revision.parse_docx(self.modify_document(alter))
                         ["blocks"][0]["kind"], "heading1")

    def test_text_before_and_after_inline_image_preserves_order(self):
        def surround(document):
            paragraph = next(p for p in document.findall(".//w:body/w:p", revision.NS)
                             if p.find(".//w:drawing", revision.NS) is not None)
            leading = ET.Element(W + "r")
            ET.SubElement(leading, W + "t").text = "图前"
            paragraph.insert(1, leading)
            ET.SubElement(ET.SubElement(paragraph, W + "r"), W + "t").text = "图后"
        parsed = revision.parse_docx(self.modify_document(surround))
        index = next(i for i, b in enumerate(parsed["blocks"]) if b["kind"] == "image")
        self.assertEqual([b["text"] for b in parsed["blocks"][index - 1:index + 2]],
                         ["图前", "", "图后"])

    def test_rejects_external_relationships_anywhere(self):
        for name in ("_rels/.rels", "word/_rels/document.xml.rels"):
            with self.subTest(name=name):
                rels = ET.fromstring(self.parts[name])
                ET.SubElement(rels, "{" + revision.REL + "}Relationship", {
                    "Id": "External", "Type": revision.R + "/image",
                    "Target": "https://example.invalid/p.png", "TargetMode": "External"})
                with self.assertRaisesRegex(ContractError, "external_relationship"):
                    revision.parse_docx(package({**self.parts, name: xml(rels)}))

    def test_rejects_unsafe_zip_paths_duplicate_members_and_expansion(self):
        for name in ("../outside.xml", "/outside.xml", "word/../outside.xml",
                     "word\\outside.xml", "C:/outside.xml", "%2e%2e/outside.xml"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                revision.parse_docx(package({**self.parts, name: b"data"}))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicate = package(list(self.parts.items()) + [("word/document.xml", b"x")])
        with self.assertRaisesRegex(ContractError, "members"):
            revision.parse_docx(duplicate)
        for setting, limit in (("MAX_INPUT_BYTES", 1), ("MAX_MEMBER_BYTES", 1),
                               ("MAX_EXPANDED_BYTES", 1), ("MAX_MEMBERS", 1)):
            with self.subTest(setting=setting), patch.object(revision, setting, limit):
                with self.assertRaises(ContractError):
                    revision.parse_docx(self.raw)

    def test_rejects_macros_activex_ole_and_unsupported_parts(self):
        for name in ("word/vbaProject.bin", "word/activeX/activeX1.xml",
                     "word/embeddings/oleObject1.bin", "word/comments.xml",
                     "word/footnotes.xml", "word/media/image2.jpg"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                revision.parse_docx(package({**self.parts, name: b"data"}))
        types = self.parts["[Content_Types].xml"].replace(
            b"wordprocessingml.document.main+xml", b"ms-word.document.macroEnabled.main+xml")
        with self.assertRaisesRegex(ContractError, "active_content"):
            revision.parse_docx(package({**self.parts, "[Content_Types].xml": types}))

    def test_rejects_textboxes_floating_images_revisions_and_unknown_objects(self):
        for tag in ("txbxContent", "pict", "object", "ins", "del", "moveFrom",
                    "sdt", "hyperlink", "altChunk", "unknownObject"):
            def insert(document, tag=tag):
                ET.SubElement(document.find("w:body/w:p", revision.NS), W + tag)
            with self.subTest(tag=tag), self.assertRaises(ContractError):
                revision.parse_docx(self.modify_document(insert))
        def floating(document):
            document.find(".//wp:inline", revision.NS).tag = "{" + revision.WP + "}anchor"
        with self.assertRaises(ContractError):
            revision.parse_docx(self.modify_document(floating))

    def test_rejects_unknown_objects_inside_format_properties(self):
        for location in ("w:body/w:p/w:pPr", "w:body/w:sectPr"):
            def hidden(document, location=location):
                ET.SubElement(document.find(location, revision.NS), W + "unknownObject")
            with self.subTest(location=location), self.assertRaises(ContractError):
                revision.parse_docx(self.modify_document(hidden))
        def concealed_text(document):
            properties = document.find("w:body/w:p/w:pPr/w:pStyle", revision.NS)
            ET.SubElement(properties, W + "t").text = "不得丢失的隐藏正文"
        with self.assertRaises(ContractError):
            revision.parse_docx(self.modify_document(concealed_text))

    def test_rejects_objects_inside_ignored_page_field(self):
        footer = ET.fromstring(self.parts["word/footer1.xml"])
        field = footer.find(".//w:fldSimple", revision.NS)
        ET.SubElement(ET.SubElement(field, W + "r"), W + "drawing")
        with self.assertRaisesRegex(ContractError, "field_unsupported"):
            revision.parse_docx(package({**self.parts, "word/footer1.xml": xml(footer)}))

    def test_rejects_body_fields_and_non_page_auxiliary_fields(self):
        for tag in ("fldSimple", "instrText", "fldChar"):
            def field(document, tag=tag):
                parent = document.find("w:body/w:p", revision.NS)
                if tag != "fldSimple":
                    parent = ET.SubElement(parent, W + "r")
                ET.SubElement(parent, W + tag)
            with self.subTest(tag=tag), self.assertRaises(ContractError):
                revision.parse_docx(self.modify_document(field))
        footer = ET.fromstring(self.parts["word/footer1.xml"])
        footer.find(".//w:fldSimple", revision.NS).set(W + "instr", " INCLUDETEXT secret ")
        with self.assertRaisesRegex(ContractError, "field_unsupported"):
            revision.parse_docx(package({**self.parts, "word/footer1.xml": xml(footer)}))

    def test_accepts_only_page_complex_field_in_auxiliary(self):
        footer = ET.Element(W + "ftr")
        p = ET.SubElement(footer, W + "p")
        for field_type in ("begin", "separate", "end"):
            r = ET.SubElement(p, W + "r")
            ET.SubElement(r, W + "fldChar", {W + "fldCharType": field_type})
            if field_type == "begin":
                ET.SubElement(ET.SubElement(p, W + "r"), W + "instrText").text = " PAGE "
            if field_type == "separate":
                ET.SubElement(ET.SubElement(p, W + "r"), W + "t").text = "123"
        parsed = revision.parse_docx(package({**self.parts, "word/footer1.xml": xml(footer)}))
        self.assertEqual(parsed["metadata"]["auxiliary_text"]["word/footer1.xml"], "")

    def test_rejects_xml_entities_corrupt_png_and_non_zip_input(self):
        for raw in (None, "text", b"not zip", self.raw[:20]):
            with self.subTest(value=repr(raw)), self.assertRaises(ContractError):
                revision.parse_docx(raw)
        malicious = (b'<!DOCTYPE document [<!ENTITY x "secret">]>'
                     b'<document>&x;</document>')
        with self.assertRaisesRegex(ContractError, "xml_dtd"):
            revision.parse_docx(package({**self.parts, "word/document.xml": malicious}))
        image_part = next(name for name in self.parts if name.endswith(".png"))
        damaged = png()[:-1] + b"!"
        with self.assertRaisesRegex(ContractError, "png_invalid"):
            revision.parse_docx(package({**self.parts, image_part: damaged}))


class RevisionDiffTests(unittest.TestCase):
    def test_identical_is_empty_and_does_not_mutate(self):
        blocks = revision.parse_markdown("# 名称\n\n段落")["blocks"]
        snapshot = copy.deepcopy(blocks)
        difference = revision.diff_blocks(blocks, blocks)
        self.assertFalse(difference["changed"])
        self.assertEqual(blocks, snapshot)
        self.assertEqual(difference["added"], [])
        self.assertEqual(difference["removed"], [])

    def test_tracks_explicit_add_remove_rewrite_reorder_sources_and_images(self):
        before = revision.parse_markdown(
            "<!-- block:A evidence:E1 status:confirmed operation:OP1 -->\n甲\n\n"
            "<!-- block:B -->\n乙\n\n<!-- block:C -->\n待删除\n\n"
            "<!-- block:Pic -->\n![图](a.png)")["blocks"]
        after = revision.parse_markdown(
            "<!-- block:B -->\n乙\n\n"
            "<!-- block:A evidence:E2 status:needs_review operation:OP2 -->\n甲改写\n\n"
            "<!-- block:D -->\n新增\n\n<!-- block:Pic -->\n![图](b.png)")["blocks"]
        saved = copy.deepcopy((before, after))
        result = revision.diff_blocks(before, after)
        self.assertEqual([b["id"] for b in result["added"]], ["D"])
        self.assertEqual([b["id"] for b in result["removed"]], ["C"])
        self.assertEqual([b["before_id"] for b in result["rewritten"]], ["A"])
        self.assertEqual({b["before_id"] for b in result["reordered"]}, {"A", "B"})
        self.assertEqual([b["before_id"] for b in result["images_changed"]], ["Pic"])
        for key in ("evidence_changed", "status_changed", "operation_changed"):
            self.assertEqual([b["before_id"] for b in result[key]], ["A"])
        self.assertTrue(result["source_changed"])
        self.assertEqual((before, after), saved)

    def test_unanchored_rewrite_is_explicitly_heuristic(self):
        before = revision.parse_markdown("# 工具\n\n这是第一版。\n\n固定末段。")["blocks"]
        after = revision.parse_markdown("# 工具\n\n这是第二版。\n\n固定末段。")["blocks"]
        difference = revision.diff_blocks(before, after)
        self.assertEqual(len(difference["rewritten"]), 1)
        self.assertEqual(difference["rewritten"][0]["matching"], "kind_order_heuristic")
        self.assertFalse(difference["added"] or difference["removed"])
        self.assertEqual(difference["metadata_comparison"], "caller_responsibility")

    def test_inserting_block_does_not_report_reorder(self):
        before = revision.parse_markdown("<!-- block:A -->\n甲\n\n<!-- block:B -->\n乙")["blocks"]
        after = revision.parse_markdown("<!-- block:Z -->\n前言\n\n"
                                        "<!-- block:A -->\n甲\n\n<!-- block:B -->\n乙")["blocks"]
        self.assertEqual(revision.diff_blocks(before, after)["reordered"], [])

    def test_rejects_invalid_blocks_and_duplicate_id(self):
        valid = revision.parse_markdown("正文")["blocks"]
        for malformed in (None, [1], [{}], [valid[0], valid[0]],
                          [{**valid[0], "kind": "other"}],
                          [{**valid[0], "status": "accepted"}],
                          [{**valid[0], "evidence_ids": "E1"}],
                          [{**valid[0], "kind": "image"}]):
            with self.subTest(value=malformed), self.assertRaises(ContractError):
                revision.diff_blocks(malformed, valid)


if __name__ == "__main__":
    unittest.main()
