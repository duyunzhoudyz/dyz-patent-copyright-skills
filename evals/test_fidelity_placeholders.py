"""AF-01/05：待确认标记扫描与禁用措辞。只检查调用者交来的文字，不判断内容是否完整。"""
import copy
import unittest

from tools import fidelity
from evals.test_fidelity import citation, document, example


def bound_case(candidate_text, role="candidate", resolved=None):
    value = example()
    if role != "candidate":
        value["documents"][1]["role"] = role
    value["documents"][1]["text"] = candidate_text
    value["documents"][1]["sha256"] = __import__("hashlib").sha256(
        candidate_text.encode("utf-8")).hexdigest()
    value["assertions"][0]["citation"] = citation(value["documents"][1])
    value["regions"][0]["citation"] = citation(value["documents"][1])
    if resolved is not None:
        value["placeholder_resolutions"] = resolved
    return value, {"D": candidate_text}, {"D": citation(value["documents"][1])}


class PlaceholderScanTests(unittest.TestCase):
    def test_marker_in_formal_deliverable_blocks(self):
        text = "系统发布时须已取得许可。[TO CONFIRM: 许可是否已取得]"
        payload, texts, bindings = bound_case(text)
        out = fidelity.audit_bound_text(payload, texts, bindings)
        self.assertEqual("blocked", out["status"])
        self.assertEqual("unresolved_placeholder_in_candidate",
                         out["placeholders"]["issues"][0]["code"])
        self.assertIn("许可是否已取得", out["placeholders"]["issues"][0]["question"])

    def test_chinese_and_fullwidth_markers_are_matched(self):
        for text in ("系统发布时须已取得许可。【待确认：许可来源】",
                     "系统发布时须已取得许可.（待确认: 许可来源）",
                     "系统发布时须已取得许可。[待核实：许可来源]"):
            payload, texts, bindings = bound_case(text)
            out = fidelity.audit_bound_text(payload, texts, bindings)
            self.assertEqual("blocked", out["status"], text)

    def test_resolution_with_source_and_reviewer_clears(self):
        text = "系统发布时须已取得许可。[TO CONFIRM: 许可是否已取得]"
        offset = text.index("[")
        payload, texts, bindings = bound_case(text, resolved=[{
            "id": "D#" + str(offset), "resolution_source": "1", "reviewer": "许可负责人"}])
        out = fidelity.audit_bound_text(payload, texts, bindings)
        self.assertEqual("checked", out["status"])
        self.assertEqual([], out["placeholders"]["issues"])
        self.assertEqual(1, len(out["placeholders"]["resolved"]))
        self.assertEqual("not_performed", out["placeholders"]["resolutions_authenticated"])

    def test_resolution_for_other_version_does_not_clear(self):
        text = "系统发布时须已取得许可。[TO CONFIRM: 许可是否已取得]"
        offset = text.index("[")
        payload, texts, bindings = bound_case(text, resolved=[{
            "id": "D#" + str(offset), "resolution_source": "0", "reviewer": "许可负责人"}])
        out = fidelity.audit_bound_text(payload, texts, bindings)
        self.assertEqual("blocked", out["status"])
        self.assertEqual("placeholder_resolution_unproven",
                         out["placeholders"]["issues"][0]["code"])

    def test_internal_document_is_review_not_blocking(self):
        # audit_bound_text 本身只接受 candidate 绑定，内部稿降级由扫描器直接兜住。
        text = "系统发布时须已取得许可。[TO CONFIRM: 许可是否已取得]"
        doc = document("D", "internal", text)
        out = fidelity.scan_placeholders(
            {"D": text}, {"D": doc},
            {"D": citation(doc)}, [])
        self.assertEqual("needs_review", out["status"])
        self.assertEqual("unresolved_placeholder_in_internal", out["issues"][0]["code"])

    def test_clean_text_is_checked(self):
        payload, texts, bindings = bound_case("系统发布时须已取得许可。")
        out = fidelity.audit_bound_text(payload, texts, bindings)
        self.assertEqual("checked", out["status"])
        self.assertEqual("checked", out["placeholders"]["status"])


class PhrasingTests(unittest.TestCase):
    def test_qualified_statement_passes(self):
        out = fidelity.check_phrasing({"B": "在本次文本审稿范围内未发现问题。"}, "standard_review")
        self.assertEqual("checked", out["status"])
        self.assertEqual([], out["issues"])

    def test_absolute_claim_is_flagged_with_advice(self):
        out = fidelity.check_phrasing({"B": "本稿全文符合 GB/T 1.1-2020。"}, "standard_review")
        self.assertEqual("needs_review", out["status"])
        row = out["issues"][0]
        self.assertEqual("phrasing_overclaim", row["code"])
        self.assertEqual("全文符合", row["phrase"])
        self.assertTrue(row["advice"])

    def test_all_occurrences_are_reported(self):
        out = fidelity.check_phrasing({"B": "全文符合。另附：全文符合。"}, "standard_review")
        self.assertEqual(2, len(out["issues"]))

    def test_verification_layer_must_be_named(self):
        out = fidelity.check_phrasing({"B": "本方法验证通过。"}, "verification")
        self.assertEqual("needs_review", out["status"])
        self.assertIn("计划", out["issues"][0]["advice"])

    def test_unknown_scope_is_rejected(self):
        with self.assertRaises(Exception):
            fidelity.check_phrasing({"B": "全文符合。"}, "not_a_scope")


if __name__ == "__main__":
    unittest.main()
