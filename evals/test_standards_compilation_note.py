"""AF-03：编制说明 11 节结构校验。只校验结构与状态，不判断说明内容是否专业正确。"""
import copy
import unittest

from evals.test_standards import payload
from tools.core import ContractError, digest
from tools.standards import COMPILATION_NOTE_SECTIONS, run


def sections(overrides=None):
    rows = [{"id": name, "heading": name, "state": "explicit", "owner": "标准组",
             "source": ["synthetic-source"], "body": "已写"} for name in COMPILATION_NOTE_SECTIONS]
    for index, patch in (overrides or {}).items():
        rows[index].update(patch)
    return rows


def cand(note):
    data = payload("STD-11")
    data["compilation_note"] = note
    return data


def complete(overrides=None):
    return {"standard_name": "合成标准", "version": "v1",
            "clause_digest": digest(payload("STD-11")["clauses"]),
            "sections": sections(overrides)}


class CompilationNoteTests(unittest.TestCase):
    def codes(self, output):
        return {row["code"] for row in output["issues"]}

    def test_complete_note_passes_structure(self):
        out = run("STD-11", cand(complete()))
        self.assertNotIn("compilation_note_section_missing", self.codes(out))
        self.assertNotIn("compilation_note_stale", self.codes(out))
        self.assertEqual(11, len(out["artifacts"]["compilation_note_sections"]))

    def test_missing_section_is_reported(self):
        note = complete()
        note["sections"] = [s for s in note["sections"] if s["id"] != "note-11-open-items"]
        out = run("STD-11", cand(note))
        self.assertIn("compilation_note_section_missing", self.codes(out))

    def test_missing_section_is_hard_error_when_completeness_claimed(self):
        note = complete()
        note["require_complete"] = True
        note["sections"] = [s for s in note["sections"] if s["id"] != "note-09-comment-disposition"]
        with self.assertRaisesRegex(ContractError, "compilation_note_section_missing"):
            run("STD-11", cand(note))

    def test_unknown_state_without_question_is_flagged(self):
        out = run("STD-11", cand(complete({3: {"state": "unknown", "body": ""}})))
        self.assertIn("compilation_note_state_unowned", self.codes(out))

    def test_unknown_state_with_question_still_needs_owner(self):
        note = complete({3: {"state": "unknown", "question": "缺少实测依据"}})
        note["sections"][3]["owner"] = ""
        with self.assertRaises(ContractError):
            run("STD-11", cand(note))

    def test_explicit_without_source_is_flagged(self):
        out = run("STD-11", cand(complete({3: {"source": []}})))
        self.assertIn("compilation_note_source_missing", self.codes(out))

    def test_not_applicable_requires_reason(self):
        out = run("STD-11", cand(complete({5: {"state": "not_applicable"}})))
        self.assertIn("compilation_note_not_applicable_unreasoned", self.codes(out))

    def test_stale_digest_is_reported(self):
        note = complete()
        note["clause_digest"] = "0" * 64
        out = run("STD-11", cand(note))
        self.assertIn("compilation_note_stale", self.codes(out))

    def test_open_item_requires_owner_blocks_and_recovery(self):
        note = complete({10: {"open_items": [
            {"question": "待验证维护模式", "owner": "技术组", "blocks": "submission"}]}})
        with self.assertRaisesRegex(ContractError, "pending_item_unowned"):
            run("STD-11", cand(note))

    def test_open_item_blocks_value_is_controlled(self):
        note = complete({10: {"open_items": [
            {"question": "q", "owner": "o", "blocks": "someday", "recovery": "r"}]}})
        with self.assertRaisesRegex(ContractError, "open_item_blocks_unknown"):
            run("STD-11", cand(note))

    def test_duplicate_section_is_rejected(self):
        # _records 自身先挡重复 id，本节只证明重复不会被静默接受。
        note = complete()
        note["sections"].append(copy.deepcopy(note["sections"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate_record_id"):
            run("STD-11", cand(note))

    def test_absent_note_keeps_legacy_behaviour(self):
        # 未交 explanatory_note 文件、也未传结构时不应新增报错，保持历史用例可用。
        data = payload("STD-11")
        out = run("STD-11", data)
        self.assertNotIn("compilation_note_section_missing", self.codes(out))

    def test_role_file_without_structure_is_rejected(self):
        # 清单里有 explanatory_note 文件、却只有文件名没有结构，属空壳，必须报错。
        data = payload("STD-11")
        data["documents"] = data["documents"] + [
            {"id": "DOC-NOTE", "role": "explanatory_note", "hash": "0" * 64,
             "source": "synthetic-note"}]
        with self.assertRaisesRegex(ContractError, "compilation_note_structure_missing"):
            run("STD-11", data)

    def test_empty_structure_dict_is_rejected(self):
        data = payload("STD-11")
        data["documents"] = data["documents"] + [
            {"id": "DOC-NOTE", "role": "explanatory_note", "hash": "0" * 64,
             "source": "synthetic-note"}]
        data["compilation_note"] = {}
        with self.assertRaisesRegex(ContractError, "compilation_note_structure_missing"):
            run("STD-11", data)

    def test_note_does_not_assert_approval(self):
        out = run("STD-11", cand(complete()))
        self.assertEqual("not_asserted", out["artifacts"]["organization_approval"])
        self.assertEqual("not_performed", out["artifacts"]["submission"])


if __name__ == "__main__":
    unittest.main()
