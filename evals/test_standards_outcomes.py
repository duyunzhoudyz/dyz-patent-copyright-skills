"""AF-04：意见处理结果受控词表。只校验调用者交来的处置结构，不判断处置是否专业正确。"""
import copy
import unittest

from evals.test_standards import payload
from tools.core import ContractError
from tools.standards import run


def gov(**updates):
    data = payload("STD-09")
    # 现有 fixture 用自由 decision 文本；这里改走 comment_outcomes 受控路径。
    data.pop("decisions", None)
    data["comment_outcomes"] = [
        {"comment_id": "COM-1", "outcome": "accepted", "proposed_text": "改为“应”",
         "reason": "安全需要", "classification": "technical", "major_change": "yes"},
        {"comment_id": "COM-2", "outcome": "accepted", "proposed_text": "改为“应”",
         "reason": "安全需要", "classification": "technical", "major_change": "yes"},
    ]
    data.update(updates)
    return data


class CommentOutcomeTests(unittest.TestCase):
    def codes(self, output):
        return {row["code"] for row in output["issues"]}

    def test_four_controlled_outcomes_are_counted(self):
        data = gov()
        data["comment_outcomes"] = [
            {"comment_id": "COM-1", "outcome": "accepted", "proposed_text": "改为“应”",
             "reason": "安全需要", "classification": "technical", "major_change": "yes"},
            {"comment_id": "COM-2", "outcome": "rejected", "reason": "无实施路径",
             "reason_source": "synthetic-feasibility", "classification": "insufficient_evidence"},
        ]
        out = run("STD-09", data)
        tally = out["artifacts"]["outcome_tally"]
        self.assertEqual(1, tally["accepted"])
        self.assertEqual(1, tally["rejected"])
        self.assertEqual(0, tally["pending"])
        self.assertEqual(2, tally["total_ranked"])
        self.assertTrue(tally["tally_balanced"])

    def test_unknown_outcome_is_rejected(self):
        data = gov()
        data["comment_outcomes"][0]["outcome"] = "retain_for_review"
        with self.assertRaisesRegex(ContractError, "comment_outcome_unknown"):
            run("STD-09", data)

    def test_accepted_without_landing_point_is_blocked(self):
        data = gov()
        data["comment_outcomes"][0] = {"comment_id": "COM-1", "outcome": "accepted",
                                       "reason": "同意"}
        with self.assertRaisesRegex(ContractError, "accepted_text_unresolved"):
            run("STD-09", data)

    def test_accepted_with_both_text_and_clause_is_ambiguous(self):
        data = gov()
        data["comment_outcomes"][0] = {"comment_id": "COM-1", "outcome": "accepted",
                                       "proposed_text": "改", "clause_id": "C-1",
                                       "reason": "同意"}
        with self.assertRaisesRegex(ContractError, "accepted_text_unresolved"):
            run("STD-09", data)

    def test_rejection_without_source_is_blocked(self):
        data = gov()
        data["comment_outcomes"][0] = {"comment_id": "COM-1", "outcome": "rejected",
                                       "reason": "不予采纳"}
        with self.assertRaisesRegex(ContractError, "rejection_reason_unsourced"):
            run("STD-09", data)

    def test_pending_without_owner_is_blocked(self):
        data = gov()
        data["comment_outcomes"][0] = {"comment_id": "COM-1", "outcome": "pending",
                                       "unresolved_item": "待验证维护模式"}
        with self.assertRaisesRegex(ContractError, "pending_item_unowned"):
            run("STD-09", data)

    def test_undisposed_comment_is_reported_not_silently_passed(self):
        data = gov()
        data["comment_outcomes"] = [data["comment_outcomes"][0]]
        out = run("STD-09", data)
        self.assertIn("comment_outcome_missing", self.codes(out))

    def test_legacy_decision_does_not_bypass_controlled_outcome(self):
        # 旧自由 decision 只能作补充信息，不能充当处置结果。
        data = payload("STD-09")
        data.pop("comment_outcomes", None)
        out = run("STD-09", data)
        self.assertIn("comment_outcome_missing", self.codes(out))

    def test_default_fixture_exercises_controlled_outcomes(self):
        # 防退：默认 fixture 必须走受控路径，否则新校验平时不被触发。
        out = run("STD-09", payload("STD-09"))
        tally = out["artifacts"]["outcome_tally"]
        self.assertGreater(tally["total_ranked"], 0)
        self.assertTrue(tally["tally_balanced"])
        self.assertEqual(2, len(out["artifacts"]["comment_outcomes"]))

    def test_classification_must_be_controlled(self):
        data = gov()
        data["comment_outcomes"][0]["classification"] = "typo"
        with self.assertRaisesRegex(ContractError, "comment_classification_unknown"):
            run("STD-09", data)

    def test_major_change_is_three_valued(self):
        data = gov()
        data["comment_outcomes"][0]["major_change"] = "maybe"
        with self.assertRaisesRegex(ContractError, "comment_major_change_unknown"):
            run("STD-09", data)

    def test_duplicate_outcome_row_is_rejected(self):
        data = gov()
        data["comment_outcomes"].append(copy.deepcopy(data["comment_outcomes"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate_comment_outcome"):
            run("STD-09", data)

    def test_outcome_for_unknown_comment_is_rejected(self):
        data = gov()
        data["comment_outcomes"][0]["comment_id"] = "COM-404"
        with self.assertRaisesRegex(ContractError, "comment_outcome_comment_missing"):
            run("STD-09", data)

    def test_outcome_does_not_assert_consensus(self):
        out = run("STD-09", gov())
        self.assertEqual("not_inferred", out["artifacts"]["consensus"])
        self.assertEqual("not_asserted", out["artifacts"]["organization_approval"])


if __name__ == "__main__":
    unittest.main()
