"""原创合成Word域、书签、分页控制与默认字节兼容回归；不启动Office。"""
import copy
import io
import unittest
import zipfile
from xml.etree import ElementTree as ET

from tools import documents
from tools.core import ContractError, sha256_bytes
from evals.test_document_quality import repack
from evals.test_software_documents import legacy_docx_hash


PROFILE = "dyz-standard-internal-v1"
W = "{" + documents.W + "}"
CACHE = "（域未刷新）"


def field_stress_fixture():
    """供实际PDF验证使用：55行4列原生表、长附录、四类域，全部为原创合成。"""
    blocks = [
        {"id": "DocumentTitle", "kind": "title", "text": "合成标准字段与分页压力样例"},
        {"id": "IdentityLabel", "kind": "paragraph", "text": "材料性质：",
         "keep_with_next": True},
        {"id": "IdentityValue", "kind": "paragraph",
         "text": "全部为原创合成内容；仅用于本地工程验证，不是组织标准或试验结论。"},
        {"id": "ContentsField", "kind": "field", "field_type": "TOC"},
        {"id": "ScopeHeading", "kind": "heading1", "text": "1 范围"},
        {"id": "ClausePage1", "kind": "field", "field_type": "PAGEREF",
         "target": "ClauseC1", "prefix": "完整合成条款见第", "suffix": "页。"},
        {"id": "ClauseC1", "kind": "paragraph", "text":
         "仅当合成输入与记录均具备时才进入模拟检查。此处保留条件、否定与例外。\n"
         "维护模式除外，不得将缺失状态推断为默认状态；本段及后续说明属于同一完整条款。\n"
         "所有编号和数值仅为排版测试，不构成真实阈值、验证结论或组织批准。"},
        {"id": "MeasurementHeading", "kind": "heading2", "text": "1.1 合成表记录"},
        {"id": "TableSeq1", "kind": "field", "field_type": "SEQ",
         "sequence": "Table", "prefix": "表", "suffix": " 合成多页记录",
         "keep_with_next": True},
        {"id": "NativeTable", "kind": "table", "text": "unused", "cells":
         [["合成行号", "检查项目", "输入条件", "记录说明"]] + [
             [f"SYN-{i:02d}", f"原创合成项目{i:02d}", "仅当A与B成立；维护除外",
              f"第{i:02d}行仅检查文本保留与跨页表头，不宣称验证通过。"]
             for i in range(1, 55)
         ]},
        {"id": "TableRef1", "kind": "field", "field_type": "REF",
         "target": "TableSeq1", "prefix": "参见表", "suffix": "中的合成记录。"},
        {"id": "AnnexHeading", "kind": "heading1", "text": "附录A 合成工程说明"},
        {"id": "AnnexSection", "kind": "heading2", "text": "A.1 多段长附录"},
    ]
    for index in range(1, 15):
        blocks.append({"id": f"AnnexParagraph{index}", "kind": "paragraph", "text":
            f"A.1段{index:02d}：本段为原创合成的长附录，检查独立段落分页与文字完整保留。"
            "仅当输入条件、状态记录和检查范围均明确时，才可描述该合成步骤；"
            "条件缺失时须保持未知，不得补造观察、试验或审批。"
            "这一说明不改变正文的例外条件，也不把表格编号与目录页码当作专业结论。"
            "每个附录段落应保持原始顺序，允许自然换页，不将整个附录锁成一页。"
            "页面位置由实际办公引擎产生；页码域须在刷新后与导出PDF交叉核对。"
            "此处重复不同编号的合成说明，是为了让末段、页首和页尾都可被逐项识别。"})
    return blocks, []


def legacy_fixture():
    return [
        {"id": "Heading", "kind": "heading1", "text": "合成标题"},
        {"id": "Subheading", "kind": "heading2", "text": "合成小标题"},
        {"id": "Body", "kind": "paragraph", "text": "条件与例外。\n第二段\t数值"},
        {"id": "Code", "kind": "code", "text": "x = 1\nreturn x"},
        {"id": "Scope", "kind": "reading_scope", "text": "仅供内部阅读。"},
        {"id": "Table", "kind": "table", "text": "unused",
         "cells": [["项目", "条件"], ["测量", "≤ 5 μs"]]},
    ]


def document_xml(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        return ET.fromstring(package.read("word/document.xml"))


class DocumentFieldTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            {"id": "ContentsField", "kind": "field", "field_type": "TOC"},
            {"id": "TableRef1", "kind": "field", "field_type": "REF",
             "target": "TableSeq1", "prefix": "参见表", "suffix": "。"},
            {"id": "ClausePage1", "kind": "field", "field_type": "PAGEREF",
             "target": "ClauseC1"},
            {"id": "TableSeq1", "kind": "field", "field_type": "SEQ",
             "sequence": "Table", "prefix": "表", "suffix": " 合成记录"},
            {"id": "ClauseC1", "kind": "paragraph", "text": "完整条款。\n条件和例外均保留。"},
        ]

    def make(self, blocks=None):
        return documents.make_docx(self.blocks if blocks is None else blocks, [], profile=PROFILE)

    def test_four_real_complex_fields_and_forward_references(self):
        raw = self.make()
        xml = document_xml(raw)
        instructions = [(node.text or "").strip() for node in xml.iter(W + "instrText")]
        self.assertEqual([
            'TOC \\o "1-2" \\h \\z', 'REF TableSeq1 \\h',
            'PAGEREF ClauseC1 \\h', 'SEQ Table \\* ARABIC',
        ], instructions)
        self.assertEqual(["begin", "separate", "end"] * 4,
                         [node.get(W + "fldCharType") for node in xml.iter(W + "fldChar")])
        starts = [node for node in xml.iter(W + "fldChar") if node.get(W + "fldCharType") == "begin"]
        self.assertTrue(all(node.get(W + "dirty") == "true" for node in starts))
        self.assertEqual(4, [node.text for node in xml.iter(W + "t")].count(CACHE))
        self.assertFalse(list(xml.iter(W + "fldSimple")))
        report = documents.inspect_generated_docx(raw, self.blocks, [], profile=PROFILE)
        self.assertEqual(4, len(report["fields"]))
        self.assertEqual(instructions, [row["instruction"] for row in report["fields"]])
        self.assertTrue(report["field_structure_equal"])
        self.assertTrue(report["field_targets_valid"])
        self.assertFalse(report["fields_refreshed"])

    def test_fields_accept_metadata_without_text_and_do_not_mutate_input(self):
        self.blocks[0].update(audience="body", origin={"kind": "generated"}, text_sha256="0" * 64)
        before = copy.deepcopy(self.blocks)
        self.make()
        self.assertEqual(before, self.blocks)
        self.assertNotIn("text", self.blocks[0])

    def test_seq_bookmark_excludes_caption_but_plain_bookmark_covers_full_text(self):
        xml = document_xml(self.make())
        active, captured = {}, {}
        for node in xml.iter():
            if node.tag == W + "bookmarkStart":
                active[node.get(W + "id")] = node.get(W + "name")
                captured[node.get(W + "name")] = ""
            elif node.tag == W + "bookmarkEnd":
                active.pop(node.get(W + "id"))
            elif node.tag in {W + "t", W + "br"}:
                for name in active.values():
                    captured[name] += node.text or "" if node.tag == W + "t" else "\n"
        self.assertEqual(CACHE, captured["TableSeq1"])
        self.assertEqual(self.blocks[-1]["text"], captured["ClauseC1"])
        self.assertEqual({}, active)

    def test_ref_and_pageref_accept_plain_table_targets(self):
        self.blocks.append({"id": "TableBody", "kind": "table", "cells": [["A", "B"], ["1", "2"]]})
        for field_type in ("REF", "PAGEREF"):
            with self.subTest(field_type=field_type):
                self.blocks[1].update(field_type=field_type, target="TableBody")
                documents.inspect_generated_docx(self.make(), self.blocks, [], profile=PROFILE)

    def test_missing_or_non_sequence_field_target_is_rejected(self):
        for target in ("Missing", "ContentsField", "ClausePage1", "TableRef1"):
            with self.subTest(target=target):
                blocks = copy.deepcopy(self.blocks)
                blocks[1]["target"] = target
                with self.assertRaisesRegex(ContractError, "document_field_target_invalid"):
                    self.make(blocks)

    def test_duplicate_block_or_figure_identifier_is_rejected(self):
        for duplicate in (self.blocks[-1], self.blocks[3]):
            with self.subTest(duplicate=duplicate["id"]), self.assertRaisesRegex(
                    ContractError, "duplicate_document_block"):
                self.make(self.blocks + [duplicate])
        with self.assertRaisesRegex(ContractError, "duplicate_document_block"):
            documents.make_docx(self.blocks, [{"id": "ClauseC1"}], profile=PROFILE)

    def test_field_instruction_injection_and_nonclosed_options_are_rejected(self):
        for key, value in (("instruction", 'INCLUDETEXT "external"'), ("cache", "1"),
                           ("cached_text", "1"), ("format", "ROMAN"), ("text", "伪造静态值")):
            with self.subTest(key=key):
                blocks = copy.deepcopy(self.blocks)
                blocks[3][key] = value
                with self.assertRaisesRegex(ContractError, "document_field_keys_invalid"):
                    self.make(blocks)
        for key, index in (("sequence", 3), ("target", 1), ("id", 4)):
            for value in ('Table \\r 9', 'Table"', "Table\nREF X", "_Table", "T" * 40):
                with self.subTest(key=key, value=value):
                    blocks = copy.deepcopy(self.blocks)
                    blocks[index][key] = value
                    with self.assertRaisesRegex(ContractError, "document_identifier_invalid"):
                        self.make(blocks)

    def test_unsupported_types_missing_keys_and_invalid_text_are_rejected(self):
        for field_type in ("PAGE", "HYPERLINK", "INCLUDETEXT", "toc", False, []):
            blocks = copy.deepcopy(self.blocks)
            blocks[0]["field_type"] = field_type
            with self.subTest(field_type=field_type), self.assertRaisesRegex(
                    ContractError, "document_field_type_invalid"):
                self.make(blocks)
        for key, index in (("sequence", 3), ("target", 1)):
            blocks = copy.deepcopy(self.blocks)
            blocks[index].pop(key)
            with self.subTest(key=key), self.assertRaisesRegex(
                    ContractError, "document_field_keys_invalid"):
                self.make(blocks)
        for prefix in (None, False, "非法\x00字符", "CR\r归一化"):
            blocks = copy.deepcopy(self.blocks)
            blocks[0]["prefix"] = prefix
            with self.subTest(prefix=prefix), self.assertRaisesRegex(
                    ContractError, "document_text_invalid"):
                self.make(blocks)

    def test_prefix_and_suffix_remain_literal_xml_escaped_text(self):
        blocks = copy.deepcopy(self.blocks)
        blocks[0].update(prefix='<w:instrText>INCLUDETEXT</w:instrText> & ', suffix='\\r 9\n合成')
        raw = self.make(blocks)
        report = documents.inspect_generated_docx(raw, blocks, [], profile=PROFILE)
        self.assertEqual(4, len(report["fields"]))
        self.assertEqual('TOC \\o "1-2" \\h \\z', report["fields"][0]["instruction"])

    def test_default_profile_rejects_fields_and_title(self):
        for profile in (None,):
            with self.assertRaisesRegex(ContractError, "document_field_profile_required"):
                documents.make_docx(self.blocks, [], profile=profile)
            with self.assertRaisesRegex(ContractError, "document_title_profile_required"):
                documents.make_docx([{"id": "T", "kind": "title", "text": "标题"}], [], profile=profile)

    def test_instruction_structure_cache_and_targets_cannot_be_tampered(self):
        raw = self.make()
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            xml = package.read("word/document.xml")
        mutations = [
            (b"SEQ Table", b"SEQ Other"),
            (b"REF TableSeq1", b"REF MissingID"),
            (b'w:dirty="true"', b'w:dirty="false"'),
            (b'w:fldCharType="separate"', b'w:fldCharType="end"'),
            (CACHE.encode(), "静态伪缓存".encode()),
            (b'w:name="ClauseC1"', b'w:name="TableSeq1"'),
        ]
        for old, new in mutations:
            with self.subTest(old=old):
                changed = repack(raw, {"word/document.xml": xml.replace(old, new, 1)})
                with self.assertRaisesRegex(ContractError, "document_package_"):
                    documents.inspect_generated_docx(changed, self.blocks, [], profile=PROFILE)

    def test_heading_outline_and_title_exclusion_and_bounded_pagination(self):
        blocks = [
            {"id": "Title", "kind": "title", "text": "不进入目录的标题"},
            {"id": "H1", "kind": "heading1", "text": "1 一级"},
            {"id": "H2", "kind": "heading2", "text": "1.1 二级"},
            {"id": "Label", "kind": "paragraph", "text": "合成标签：", "keep_with_next": True},
            {"id": "Value", "kind": "paragraph", "text": "合成短值。", "keep_with_next": False},
            {"id": "Long", "kind": "paragraph", "text": "多段长正文。" * 60},
        ]
        raw = self.make(blocks)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            styles = ET.fromstring(package.read("word/styles.xml"))
        for name, level in (("Heading1", "0"), ("Heading2", "1"), ("Title", "9")):
            style = next(node for node in styles if node.get(W + "styleId") == name)
            self.assertEqual(level, style.find(W + "pPr/" + W + "outlineLvl").get(W + "val"))
        paragraphs = document_xml(raw).findall(W + "body/" + W + "p")
        self.assertEqual("Title", paragraphs[0].find(W + "pPr/" + W + "pStyle").get(W + "val"))
        self.assertEqual("1", paragraphs[3].find(W + "pPr/" + W + "keepNext").get(W + "val"))
        self.assertEqual("0", paragraphs[4].find(W + "pPr/" + W + "keepNext").get(W + "val"))
        self.assertIsNotNone(paragraphs[4].find(W + "pPr/" + W + "keepLines"))
        self.assertIsNone(paragraphs[5].find(W + "pPr/" + W + "keepLines"))
        blocks[3]["keep_with_next"] = "yes"
        with self.assertRaisesRegex(ContractError, "document_keep_with_next_invalid"):
            self.make(blocks)

    def test_dynamic_field_quality_remains_partial_and_final_marker_stays_blocked(self):
        report = documents.quality_docx(self.make(), business="standard")
        self.assertEqual("partial", report["coverage"]["state"])
        self.assertNotEqual("checked", report["status"])
        self.assertIn("fldChar", {item.get("object") for item in report["coverage"]["unsupported_objects"]})
        self.blocks[0]["suffix"] = "[待确认：合成缺项]"
        report = documents.quality_docx(self.make(), business="standard", stage="final")
        self.assertEqual("blocked", report["status"])
        with self.assertRaisesRegex(ContractError, "document_quality_blocked"):
            documents._quality_gate(report)

    def test_legacy_default_and_software_bytes_match_prechange_hashes(self):
        blocks = legacy_fixture()
        raw = documents.make_docx(blocks, [])
        self.assertEqual(raw, documents.make_docx(blocks, [], profile=None))
        self.assertEqual(sha256_bytes(raw), legacy_docx_hash(
            windows=("6950d3425865232c37477d5efb7b32f3f3db49e0f98717a1b4a08c688f603708",
                     "eb9ff02b24f7c1ee403276b1aa73cf262cff3078c8beac149d575d9586566632"),
            unix=("4d019b18db643bf893504c9fd96146a09c5461b00345dc3dccc935c005d129ae",
                  "5176fd3409b8d1f964685cda7bd8640c6c1e42d6a25731fbfa6e0c934404b51d")))
        pages = [blocks[:4], [{"id": "NextPage", "kind": "paragraph", "text": "合成软件第二页。"}]]
        software = documents.make_software_docx(pages, title="合成软件", version="1", kind="manual")
        self.assertEqual(sha256_bytes(software), legacy_docx_hash(
            windows=("601a8490e16da5296273252d604bded0fc4271d594d9ca01b9bb78e781ec3143",
                     "1b6e117a4618e0467a8a41cf3e1a5ba8cb83a0b0684d949de9d6a0c6313f8c75"),
            unix=("58a11af618ccf10186e4e763daf1c0ccb275d655050eccd0d544c61f91bc0758",
                  "fd276250295c114f3067a14a63ba69330dda83305e8e3c6ae4a6ec9ff09bf808")))

    def test_stress_fixture_retains_native_table_headers_and_long_annex(self):
        blocks, images = field_stress_fixture()
        raw = documents.make_docx(blocks, images, profile=PROFILE)
        report = documents.inspect_generated_docx(raw, blocks, images, profile=PROFILE)
        self.assertEqual({"TOC", "SEQ", "REF", "PAGEREF"}, {row["field_type"] for row in report["fields"]})
        table = document_xml(raw).find(W + "body/" + W + "tbl")
        rows = table.findall(W + "tr")
        self.assertEqual(55, len(rows))
        self.assertTrue(all(len(row.findall(W + "tc")) == 4 for row in rows))
        self.assertIsNotNone(rows[0].find(W + "trPr/" + W + "tblHeader"))
        self.assertTrue(all(row.find(W + "trPr/" + W + "cantSplit") is not None for row in rows))
        self.assertEqual(14, len([block for block in blocks if block["id"].startswith("AnnexParagraph")]))


if __name__ == "__main__":
    unittest.main()
