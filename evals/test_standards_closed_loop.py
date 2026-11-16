"""SE-01 synthetic契约反例；保留v1行为，v2只提供确定性检查。"""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

from tools import standards, standards_contract, standards_delivery
from tools.core import ContractError, canonical_bytes, digest


ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / "skills/dyz-standards/resources/lifecycle"


def closed_payload():
    """新闭环的最小内部profile样例，不代表专业审阅或实物证明。"""
    profile = {"id": "internal-eleven", "version": "1", "scope": "internal",
               "required_sections": list(standards.COMPILATION_NOTE_SECTIONS)}
    clauses = [{"id": "C-1", "text": "应记录校验结果。"}]
    return {
        "contract_version": 2, "project_id": "synthetic-loop", "version": "v2",
        "adaptation": {"organization": "synthetic", "standard_type": "internal",
                       "domain": "synthetic", "stage": "draft"},
        "standard_name": "合成标准", "profile": profile,
        "baseline_clauses": [{"id": "C-1", "text": "宜记录校验结果。"}],
        "clauses": clauses, "collection_status": "complete",
        "comments": [{"id": "COM-1", "text": "请使用要求型措辞。", "source": "synthetic:1",
                      "participant_id": "P-1", "version": "v1", "clause_id": "C-1"}],
        "comment_outcomes": [{"comment_id": "COM-1", "outcome": "accepted",
                              "classification": "technical", "reason": "采用一致措辞。",
                              "decision_status": "proposed", "major_change": "no",
                              "impact": {"verification": False, "references": False,
                                         "compilation_note": True, "downstream_products": False},
                              "changes": [{"operation": "replace", "clause_id": "C-1",
                                           "proposed_text": clauses[0]["text"]}]}],
        "compilation_note": {
            "standard_name": "合成标准", "version": "v2", "clause_digest": digest(clauses),
            "profile_id": profile["id"], "profile_hash": digest(profile),
            "sections": [{"id": key, "heading": key, "body": "这是合成工作记录，不是批准。",
                          "state": "explicit", "owner": "synthetic-team",
                          "source": ["synthetic:note:1"]}
                         for key in standards.COMPILATION_NOTE_SECTIONS]},
    }


def final_ready_payload():
    """无确定性缺口的合成审阅候选；不代表专业审阅、批准或真实可送审。"""
    data = closed_payload()
    data.update(sensitivity="synthetic", delivery_stage="review_candidate",
                baseline_version="v1", evidence_ids=["S1"])
    for clause in data["baseline_clauses"] + data["clauses"]:
        clause.update(strength="requirement", kind="normative", source="S1",
                      conditions=[], exceptions=[], method_ids=["V1"], references=[])
    row = data["comment_outcomes"][0]
    row.update(decision_status="confirmed", decision_by="synthetic-reviewer",
               decision_source="synthetic:decision:1", decision_version="decision-v1")
    row["confirmation"] = {
        "actor": "synthetic-reviewer", "authority_evidence": "synthetic:authority",
        "source": "synthetic:decision:1", "version": "decision-v1", "baseline_version": "v1",
    }
    row["impact"] = {key: False for key in row["impact"]}
    data["verification_matrix"] = [
        {"id": "V1", "clause_id": "C-1", "clause_hash": digest(data["clauses"][0]),
         "method": "inspection", "status": "performed", "source": "S1",
         "execution_evidence": "synthetic:execution:1", "result_evidence": "synthetic:result:1"},
    ]
    data["compilation_note"]["clause_digest"] = digest(data["clauses"])
    data["compilation_note"]["sections"][-1]["open_items"] = []
    confirmation = row.pop("confirmation")
    return standards_contract.confirm_comment(data, "COM-1", confirmation)


class ClosedLoopTests(unittest.TestCase):
    def codes(self, value):
        return {row["code"] for row in value["issues"]}

    def test_v2_public_contract_preserves_original_and_no_proof(self):
        data = closed_payload()
        before = copy.deepcopy(data)
        out = standards.closed_loop(data)
        self.assertEqual(2, out["contract_version"])
        self.assertEqual(data, before)
        self.assertEqual(data["comments"], out["comments"])
        self.assertEqual(data["comment_outcomes"], out["comment_outcomes"])
        self.assertNotIn("comment_realizations", out)
        self.assertEqual(digest(data["clauses"]), out["clause_digest"])
        self.assertTrue(out["outcome_tally"]["complete"])
        self.assertEqual("not_performed", out["professional_review"])

    def test_version_dispatch_and_unknown_versions(self):
        for capability in ("STD-09", "STD-11"):
            out = standards.run(capability, closed_payload())
            self.assertEqual(2, out["artifacts"]["contract_version"])
            self.assertNotIn("comment_disposition_missing", self.codes(out))
            self.assertEqual("not_performed", out["professional_review"])
        for version in (True, False, 0, 3, "2", 2.0, None):
            with self.subTest(version=version):
                data = closed_payload()
                data["contract_version"] = version
                with self.assertRaisesRegex(ContractError, "unsupported_standard_contract_version"):
                    standards.run("STD-09", data)
        legacy = {k: v for k, v in closed_payload().items()
                  if k not in {"contract_version", "comments", "comment_outcomes"}}
        for version in (None, 1):
            if version is not None:
                legacy["contract_version"] = version
            self.assertEqual("legacy", standards.run("STD-09", legacy)["artifacts"]["contract_mode"])

    def test_accepted_direct_target_and_text_are_valid(self):
        data = closed_payload()
        row = data["comment_outcomes"][0]
        row.pop("changes")
        row.update(clause_id="C-1", proposed_text=data["clauses"][0]["text"])
        out = standards.closed_loop(data)
        self.assertNotIn("accepted_text_unresolved", self.codes(out))
        self.assertTrue(out["outcome_tally"]["complete"])

    def test_target_without_text_and_false_no_change_rejected(self):
        for patch in ({"clause_id": "C-1"}, {"no_change": False}):
            data = closed_payload()
            data["comment_outcomes"][0].pop("changes")
            data["comment_outcomes"][0].update(patch)
            with self.assertRaisesRegex(ContractError, "accepted_text_unresolved"):
                standards.closed_loop(data)

    def test_realization_is_separate_and_structural_mismatch_is_reported(self):
        data = closed_payload()
        data["clauses"][0]["text"] = "宜记录校验结果。"
        out = standards.closed_loop(data)
        self.assertIn("comment_change_not_applied", self.codes(out))
        data["comment_outcomes"][0]["realization"] = {"state": "verified"}
        with self.assertRaisesRegex(ContractError, "comment_realization_separate_required"):
            standards.closed_loop(data)

    def test_zero_vs_unknown_collection_and_missing_outcome(self):
        for status in ("complete", "unknown", "partial", "not_started"):
            data = closed_payload()
            data.update(comments=[], comment_outcomes=[], collection_status=status,
                        collection_evidence=["synthetic:collection:complete"])
            out = standards.closed_loop(data)
            tally = out["outcome_tally"]
            self.assertEqual(status == "complete", tally["complete"])
            self.assertEqual(0 if status == "complete" else None, tally["total"])
            self.assertEqual(0, tally["registered_count"])
        data = closed_payload()
        data["comment_outcomes"] = []
        out = standards.closed_loop(data)
        self.assertEqual(["COM-1"], out["outcome_tally"]["unprocessed_ids"])
        self.assertFalse(out["outcome_tally"]["complete"])
        self.assertIn("comment_outcome_missing", self.codes(out))

    def test_duplicate_ids_are_reported_not_overwritten(self):
        data = closed_payload()
        data["comments"].append(copy.deepcopy(data["comments"][0]))
        data["comment_outcomes"].append(copy.deepcopy(data["comment_outcomes"][0]))
        out = standards.closed_loop(data)
        self.assertEqual(["COM-1"], out["outcome_tally"]["duplicate_comment_ids"])
        self.assertEqual(["COM-1"], out["outcome_tally"]["duplicate_outcome_ids"])
        self.assertFalse(out["outcome_tally"]["complete"])
        self.assertEqual(2, len(out["comments"]))

    def test_add_delete_multi_target_and_document_scope(self):
        data = closed_payload()
        data["comments"][0].pop("clause_id")
        data["comments"][0]["scope"] = "document"
        data["clauses"] = [{"id": "C-2", "text": "新增记录条款。"}]
        data["comment_outcomes"][0]["changes"] = [
            {"operation": "delete", "clause_id": "C-1", "proposed_text": "",
             "dependency_resolution": {"status": "not_applicable", "reason": "合成基线无依赖。"}},
            {"operation": "add", "clause_id": "C-2", "proposed_text": "新增记录条款。"}]
        out = standards.closed_loop(data)
        self.assertNotIn("comment_change_not_applied", self.codes(out))
        self.assertNotIn("comment_change_target_invalid", self.codes(out))
        self.assertEqual(2, out["outcome_tally"]["clauses_touched"])

    def test_conflicting_proposals_do_not_last_win(self):
        data = closed_payload()
        data["comments"].append({**data["comments"][0], "id": "COM-2"})
        other = copy.deepcopy(data["comment_outcomes"][0])
        other["comment_id"] = "COM-2"
        other["changes"][0]["proposed_text"] = "不得记录。"
        data["comment_outcomes"].append(other)
        out = standards.closed_loop(data)
        self.assertIn("conflicting_comment_changes", self.codes(out))
        self.assertEqual(2, out["outcome_tally"]["registered_count"])
        self.assertEqual(2, len(out["comment_outcomes"]))

    def test_partial_rejection_and_pending_conditions(self):
        data = closed_payload()
        data["comment_outcomes"][0]["outcome"] = "partially_accepted"
        with self.assertRaisesRegex(ContractError, "partial_acceptance_details_required"):
            standards.closed_loop(data)
        data["comment_outcomes"][0].update(accepted_part="措辞", rejected_part="增加试验",
                                         rejected_reason="范围外", reason_source="synthetic:scope")
        self.assertEqual(1, standards.closed_loop(data)["outcome_tally"]["partially_accepted"])
        row = data["comment_outcomes"][0]
        row.pop("changes")
        row["outcome"] = "pending"
        row["unresolved_item"] = {"question": "采用何种方法？", "owner": "组A",
                                  "blocks": "submission", "recovery": "取得方法记录"}
        out = standards.closed_loop(data)
        self.assertEqual(1, len(out["open_items"]))
        self.assertEqual("comment:COM-1", out["open_items"][0]["id"])
        self.assertIn("comment:COM-1", out["open_items"][0]["source_refs"])
        self.assertEqual(1, out["outcome_tally"]["pending"])
        self.assertFalse(out["outcome_tally"]["closed"])
        del row["unresolved_item"]["owner"]
        with self.assertRaisesRegex(ContractError, "pending_item_unowned"):
            standards.closed_loop(data)

    def test_note_bindings_nonempty_body_states_and_sections(self):
        mutations = [
            (lambda p: p["compilation_note"].update(version="v1"), "compilation_note_version_mismatch"),
            (lambda p: p["compilation_note"].update(clause_digest="0" * 64), "compilation_note_stale"),
            (lambda p: p["compilation_note"].update(profile_hash="0" * 64), "compilation_note_profile_mismatch"),
            (lambda p: p["compilation_note"]["sections"][0].update(body="  "), "compilation_note_body_missing"),
            (lambda p: p["compilation_note"]["sections"][0].update(source=[]), "compilation_note_source_missing"),
            (lambda p: p["compilation_note"]["sections"].pop(), "compilation_note_section_missing"),
            (lambda p: p["compilation_note"]["sections"].append(copy.deepcopy(p["compilation_note"]["sections"][0])), "compilation_note_section_duplicate"),
            (lambda p: p["compilation_note"]["sections"][0].update(id="alien"), "compilation_note_section_unknown"),
        ]
        for mutate, code in mutations:
            with self.subTest(code=code):
                data = closed_payload()
                mutate(data)
                self.assertIn(code, self.codes(standards.closed_loop(data)))
        for state, code in (("unknown", "compilation_note_state_unowned"),
                            ("inferred", "compilation_note_inference_unreviewed"),
                            ("not_applicable", "compilation_note_not_applicable_unreasoned")):
            data = closed_payload()
            data["compilation_note"]["sections"][0]["state"] = state
            self.assertIn(code, self.codes(standards.closed_loop(data)))

    def test_note_tally_verification_and_open_set_cannot_hide_conflict(self):
        data = closed_payload()
        note = data["compilation_note"]
        note["sections"][8]["outcome_tally"] = {"accepted": 99}
        note["sections"][9]["verification_summary"] = {"executed": 99}
        note["sections"][10]["open_items"] = [
            {"id": "invented", "question": "问题", "owner": "组A", "blocks": "none",
             "recovery": "确认", "source_refs": ["synthetic"]}]
        out = standards.closed_loop(data)
        self.assertIn("compilation_note_tally_mismatch", self.codes(out))
        self.assertIn("compilation_note_verification_mismatch", self.codes(out))
        self.assertIn("compilation_note_open_items_mismatch", self.codes(out))
        self.assertEqual(99, out["compilation_note"]["sections"][8]["outcome_tally"]["accepted"])

    def test_positive_contract_has_no_issues_without_professional_claim(self):
        data = final_ready_payload()
        out = standards.closed_loop(data)
        self.assertEqual([], out["issues"])
        self.assertEqual("not_performed", out["professional_review"])
        self.assertEqual("not_performed", out["implementation_verification"])
        self.assertEqual("not_asserted", out["organization_approval"])

    def test_internal_draft_empty_impact_and_unproven_decision_are_retained(self):
        for empty in ([], {}):
            data = final_ready_payload()
            row = data["comment_outcomes"][0]
            row["impact"] = empty
            row.pop("confirmation")
            before = copy.deepcopy(data)
            out = standards.closed_loop(data)
            self.assertEqual(before, data)
            self.assertEqual(before["comment_outcomes"], out["comment_outcomes"])
            self.assertIn("comment_impact_assessment_missing", self.codes(out))
            self.assertIn("comment_decision_authority_unproven", self.codes(out))
            self.assertFalse(out["outcome_tally"]["closed"])
            self.assertEqual("not_performed", out["professional_review"])
        data["comment_outcomes"][0].pop("impact")
        self.assertIn("comment_impact_assessment_missing", self.codes(standards.closed_loop(data)))

    def test_nonempty_malformed_impact_is_not_an_unknown_assessment(self):
        for impact in (["verification"], {"verification": False}, "unknown", None):
            data = final_ready_payload()
            data["comment_outcomes"][0]["impact"] = impact
            with self.subTest(impact=impact):
                with self.assertRaisesRegex(ContractError, "comment_impact_fields_required"):
                    standards.closed_loop(data)
        for value in (0, 1, "false", [], {}):
            data = final_ready_payload()
            data["comment_outcomes"][0]["impact"]["verification"] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(ContractError, "comment_impact_value_unknown"):
                    standards.closed_loop(data)

    def test_unknown_impact_and_majority_are_not_promoted_to_no(self):
        for value in (True, "unknown", "undetermined"):
            data = final_ready_payload()
            data["comment_outcomes"][0]["impact"]["verification"] = value
            out = standards.closed_loop(data)
            self.assertIn("comment_impact_review_required", self.codes(out))
            self.assertIs(value, out["comment_outcomes"][0]["impact"]["verification"])
            self.assertFalse(out["outcome_tally"]["closed"])
        for value in ("yes", "undetermined"):
            data = final_ready_payload()
            data["comment_outcomes"][0]["major_change"] = value
            out = standards.closed_loop(data)
            self.assertIn("comment_major_change_review_required", self.codes(out))
            self.assertFalse(out["outcome_tally"]["closed"])

    def test_zero_comments_require_collection_source_even_when_declared_complete(self):
        data = final_ready_payload()
        data.update(comments=[], comment_outcomes=[])
        out = standards.closed_loop(data)
        self.assertIn("zero_comment_collection_evidence_missing", self.codes(out))
        self.assertIsNone(out["outcome_tally"]["total"])
        self.assertFalse(out["outcome_tally"]["complete"])
        data["collection_evidence"] = ["synthetic:empty-collection-record"]
        out = standards.closed_loop(data)
        self.assertEqual([], out["issues"])
        self.assertEqual(0, out["outcome_tally"]["total"])
        self.assertTrue(out["outcome_tally"]["complete"])

    def test_no_change_and_rejection_have_locatable_reasons(self):
        data = final_ready_payload()
        row = data["comment_outcomes"][0]
        row.pop("changes")
        row.update(no_change=True, reason_source="synthetic:retained-text")
        data["clauses"] = copy.deepcopy(data["baseline_clauses"])
        data["compilation_note"]["clause_digest"] = digest(data["clauses"])
        data["verification_matrix"][0]["clause_hash"] = digest(data["clauses"][0])
        data = standards_contract.confirm_comment(data, "COM-1", row["confirmation"])
        row = data["comment_outcomes"][0]
        self.assertEqual([], standards.closed_loop(data)["issues"])
        row.pop("reason_source")
        with self.assertRaisesRegex(ContractError, "no_change_reason_unsourced"):
            standards.closed_loop(data)
        row.update(outcome="rejected", no_change=False)
        with self.assertRaisesRegex(ContractError, "rejection_reason_unsourced"):
            standards.closed_loop(data)
        row["reason_source"] = "synthetic:rejection-basis"
        data = standards_contract.confirm_comment(data, "COM-1", row["confirmation"])
        out = standards.closed_loop(data)
        self.assertEqual([], out["issues"])
        self.assertEqual(1, out["outcome_tally"]["rejected"])

    def test_deleted_clause_dependency_and_retained_reference_are_not_hidden(self):
        data = final_ready_payload()
        data["clauses"] = [{"id": "C-2", "text": "引用原条款。", "references": ["C-1"]}]
        data["comment_outcomes"][0]["changes"] = [{"operation": "delete", "clause_id": "C-1"}]
        out = standards.closed_loop(data)
        self.assertIn("deleted_clause_dependencies_unresolved", self.codes(out))
        self.assertIn("deleted_clause_reference_retained", self.codes(out))

    def test_missing_note_and_late_note_issues_keep_candidate_open(self):
        for mutate, code in (
            (lambda p: p.pop("compilation_note"), "compilation_note_structure_missing"),
            (lambda p: p["compilation_note"].update(version="old"), "compilation_note_version_mismatch"),
            (lambda p: p["compilation_note"]["sections"][8].update(outcome_tally={"accepted": 8}), "compilation_note_tally_mismatch"),
        ):
            data = final_ready_payload()
            mutate(data)
            out = standards.closed_loop(data)
            self.assertIn(code, self.codes(out))
            self.assertFalse(out["outcome_tally"]["closed"])

    def test_open_items_merge_sources_and_conflicts_keep_original(self):
        data = final_ready_payload()
        item = {"id": "O-1", "question": "核实合成记录", "owner": "组A",
                "blocks": "submission", "recovery": "取得记录", "source_refs": ["verification:V1"]}
        data["verification_open_items"] = [item]
        data["reference_open_items"] = [{**item, "source_refs": ["reference:R1"]}]
        merged = {**item, "source_refs": ["reference:R1", "verification:V1"]}
        data["compilation_note"]["sections"][-1]["open_items"] = [merged]
        out = standards.closed_loop(data)
        self.assertEqual([merged], out["open_items"])
        self.assertIn("open_item_stage_blocked", self.codes(out))
        self.assertNotIn("compilation_note_open_items_mismatch", self.codes(out))
        self.assertFalse(out["outcome_tally"]["closed"])
        data["reference_open_items"][0]["owner"] = "组B"
        self.assertIn("open_item_conflict", self.codes(standards.closed_loop(data)))

    def test_organization_profile_mapping_and_version_hash(self):
        data = final_ready_payload()
        ids = [f"org-{i}" for i in range(11)]
        data["profile"].update(id="synthetic-org", scope="organization", source="synthetic:rules",
                               required_sections=ids,
                               section_semantics=dict(zip(ids, standards.COMPILATION_NOTE_SECTIONS)))
        for section, key in zip(data["compilation_note"]["sections"], ids):
            section["id"] = key
        data["compilation_note"].update(profile_id="synthetic-org", profile_hash=digest(data["profile"]))
        self.assertEqual({"organization_profile_needs_review"}, self.codes(standards.closed_loop(data)))
        data["profile"]["version"] = "2"
        self.assertIn("compilation_note_profile_mismatch", self.codes(standards.closed_loop(data)))
        data["profile"]["section_semantics"].pop(ids[0])
        with self.assertRaisesRegex(ContractError, "profile_section_semantics_required"):
            standards.closed_loop(data)

    def test_required_verification_coverage_and_evidence_cannot_be_omitted(self):
        mutations = (
            (lambda p: p.update(verification_matrix=[]), "verification_matrix_missing"),
            (lambda p: p["verification_matrix"].append(copy.deepcopy(p["verification_matrix"][0])), "duplicate_verification_id"),
            (lambda p: p["verification_matrix"][0].pop("execution_evidence"), "verification_execution_missing"),
            (lambda p: p["verification_matrix"][0].pop("result_evidence"), "verification_result_missing"),
            (lambda p: p["verification_matrix"][0].update(status="planned"), "verification_not_performed"),
            (lambda p: p["verification_matrix"][0].update(status="reviewed"), "verification_review_missing"),
            (lambda p: p["verification_matrix"][0].update(status="not_applicable"), "verification_not_applicable_unreasoned"),
            (lambda p: p["verification_matrix"][0].update(clause_hash="stale"), "required_verification_missing"),
            (lambda p: p["verification_matrix"][0].update(id="unrelated"), "declared_verification_method_missing"),
        )
        for mutate, code in mutations:
            with self.subTest(code=code):
                data = final_ready_payload()
                mutate(data)
                out = standards.closed_loop(data)
                self.assertIn(code, self.codes(out))
                self.assertFalse(out["outcome_tally"]["closed"])
                self.assertEqual("not_performed", out["professional_review"])
        data = final_ready_payload()
        second = {**data["clauses"][0], "id": "C-2"}
        data["clauses"].append(second)
        self.assertIn("required_verification_missing", self.codes(standards.closed_loop(data)))

    def test_minimal_clause_cannot_omit_semantics_for_readiness(self):
        data = final_ready_payload()
        data["clauses"][0] = {key: data["clauses"][0][key] for key in ("id", "text")}
        data["compilation_note"]["clause_digest"] = digest(data["clauses"])
        data["verification_matrix"][0]["clause_hash"] = digest(data["clauses"][0])
        out = standards.closed_loop(data)
        self.assertIn("clause_semantics_incomplete_or_invalid", self.codes(out))
        self.assertFalse(out["outcome_tally"]["closed"])

    def test_confirmation_binds_decision_and_baseline_versions(self):
        mutations = (
            (lambda p: p["comment_outcomes"][0].pop("decision_version"), "comment_decision_version_missing"),
            (lambda p: p["comment_outcomes"][0]["confirmation"].update(version="other"), "comment_decision_confirmation_stale"),
            (lambda p: p.pop("baseline_version"), "comment_decision_baseline_unbound_or_stale"),
            (lambda p: p["comments"][0].update(version="old"), "comment_decision_baseline_unbound_or_stale"),
            (lambda p: p["comment_outcomes"][0]["confirmation"].update(baseline_version="old"), "comment_decision_baseline_unbound_or_stale"),
        )
        for mutate, code in mutations:
            data = final_ready_payload()
            mutate(data)
            before = copy.deepcopy(data["comment_outcomes"])
            out = standards.closed_loop(data)
            self.assertIn(code, self.codes(out))
            self.assertEqual(before, out["comment_outcomes"])
            self.assertFalse(out["outcome_tally"]["closed"])

    def test_no_change_derives_targets_but_does_not_skip_actual_comparison(self):
        data = final_ready_payload()
        row = data["comment_outcomes"][0]
        row.pop("changes")
        row.update(no_change=True, reason_source="synthetic:no-change")
        out = standards.closed_loop(data)
        self.assertIn("no_change_target_changed", self.codes(out))
        self.assertEqual(["C-1"], out["no_change_checks"][0]["clause_ids"])
        self.assertEqual("unresolved", out["no_change_checks"][0]["structure_status"])
        data["clauses"] = copy.deepcopy(data["baseline_clauses"])
        out = standards.closed_loop(data)
        self.assertNotIn("no_change_target_changed", self.codes(out))
        self.assertEqual("matched", out["no_change_checks"][0]["structure_status"])
        self.assertEqual("not_performed", out["no_change_checks"][0]["implementation_verification"])
        data["comments"][0].pop("clause_id")
        data["comments"][0]["scope"] = "document"
        data["clauses"].append({**data["clauses"][0], "id": "C-2"})
        out = standards.closed_loop(data)
        self.assertIn("no_change_target_missing", self.codes(out))
        self.assertEqual(["C-1", "C-2"], out["no_change_checks"][0]["clause_ids"])
        data["comments"][0]["scope"] = "introduction"
        self.assertIn("no_change_scope_missing", self.codes(standards.closed_loop(data)))
        row["no_change_targets"] = ["C-1"]
        self.assertNotIn("no_change_scope_missing", self.codes(standards.closed_loop(data)))

    def test_organization_profile_may_have_fewer_sections_but_remains_unreviewed(self):
        data = final_ready_payload()
        data["profile"].update(id="synthetic-org", scope="organization", source="synthetic:rules",
                               required_sections=["org-overview", "org-open"],
                               section_semantics={"org-overview": "note-01-work-overview",
                                                  "org-open": "note-11-open-items"})
        sections = data["compilation_note"]["sections"]
        sections[:] = [sections[0], sections[-1]]
        for section, key in zip(sections, data["profile"]["required_sections"]):
            section["id"] = key
        data["compilation_note"].update(profile_id="synthetic-org", profile_hash=digest(data["profile"]))
        out = standards.closed_loop(data)
        self.assertEqual({"organization_profile_needs_review"}, self.codes(out))
        self.assertFalse(out["outcome_tally"]["closed"])

    def test_candidate_roles_cannot_be_reduced_by_caller(self):
        data = final_ready_payload()
        data.update(required_document_roles=[], require_complete=False)
        out = standards.run("STD-11", data)
        missing = {issue["record_id"] for issue in out["issues"]
                   if issue["code"] == "candidate_document_missing"}
        self.assertEqual({"draft", "explanatory_note", "comment_dispositions",
                          "verification_evidence", "review_report"}, missing)
        self.assertEqual("not_performed", out["professional_review"])

    def test_internal_profile_cannot_reduce_required_sections(self):
        data = closed_payload()
        data["profile"]["required_sections"] = []
        with self.assertRaisesRegex(ContractError, "internal_profile_sections_invalid"):
            standards.closed_loop(data)

    def test_v1_schema_bytes_frozen_and_v2_enum_alignment(self):
        expected = {
            "comment-disposition.schema.json": "0a331670b5de3097f207d3f0b33109d7d794a0bf58cb50e62c87be6d5b9d9bbc",
            "compilation-note.schema.json": "87340210dfae7e29791b98e88b8b7a922bf453c0b33b4820fe2a2705833e9840",
        }
        for filename, expected_hash in expected.items():
            self.assertEqual(expected_hash, hashlib.sha256((RESOURCE / filename).read_bytes()).hexdigest())
        comment = json.loads((RESOURCE / "comment-disposition.v2.schema.json").read_text(encoding="utf-8"))
        note = json.loads((RESOURCE / "compilation-note.v2.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("dyz/standards/comment-disposition/v2", comment["$id"])
        self.assertEqual("dyz/standards/compilation-note/v2", note["$id"])
        props = comment["$defs"]["outcome"]["properties"]
        self.assertEqual(standards.COMMENT_OUTCOMES, set(props["outcome"]["enum"]))
        self.assertEqual(standards.COMMENT_CLASSIFICATIONS, set(props["classification"]["enum"]))
        self.assertEqual(list(standards.COMPILATION_NOTE_SECTIONS), note["$defs"]["internalSectionId"]["enum"])
        for fixture in (closed_payload(), final_ready_payload()):
            for row in fixture["comment_outcomes"]:
                self.assertTrue(set(comment["$defs"]["outcome"]["required"]) <= set(row))
                self.assertTrue(set(row) <= set(props))
            self.assertTrue(set(note["required"]) <= set(fixture["compilation_note"]))
        self.assertEqual({"clause_id": ["proposed_text"], "proposed_text": ["clause_id"]},
                         comment["$defs"]["outcome"]["dependentRequired"])
        impact = comment["$defs"]["impact"]["oneOf"]
        self.assertEqual(0, impact[0]["maxItems"])
        self.assertEqual(0, impact[1]["maxProperties"])
        self.assertEqual(set(final_ready_payload()["comment_outcomes"][0]["impact"]),
                         set(impact[2]["required"]))
        self.assertTrue(all(props[key] is False for key in
                            ("realization", "realization_evidence", "comment_realizations", "applied", "document_hash")))
        self.assertIn("body", note["$defs"]["section"]["required"])
        self.assertEqual("\\S", note["$defs"]["text"]["pattern"])
        self.assertEqual(4, len(note["$defs"]["section"]["allOf"]))


class ContentConsistencyTests(unittest.TestCase):
    """SP-01／02：普通引用与完整确认在同版标签下也必须重新核对。"""

    def codes(self, data):
        return {issue["code"] for issue in standards.closed_loop(data)["issues"]}

    def test_ordinary_unresolved_reference_without_delete_is_not_closed(self):
        data = final_ready_payload()
        data["clauses"][0]["references"] = ["MISSING"]
        out = standards.closed_loop(data)
        self.assertIn("unresolved_clause_reference", {issue["code"] for issue in out["issues"]})
        self.assertEqual("standards-consistency/1", out["assessment_version"])
        check = out["reference_checks"][0]
        self.assertEqual(("C-1", "MISSING", "unresolved"),
                         (check["clause_id"], check["reference"], check["status"]))
        self.assertFalse(out["outcome_tally"]["closed"])

    def test_external_editions_and_legacy_registration_are_distinct(self):
        data = final_ready_payload()
        data["clauses"][0]["references"] = ["GB/T 1234-2020", "GB/T 1234-2024", "OLD"]
        data["external_reference_ids"] = ["OLD"]
        data["external_references"] = [
            {"id": "R-2020", "identifier": "GB/T 1234", "edition": "2020",
             "title": "合成外部标准旧版", "source": "synthetic:external:2020"},
            {"id": "R-2024", "identifier": "GB/T 1234", "edition": "2024",
             "title": "合成外部标准新版", "source": "synthetic:external:2024"}]
        out = standards.closed_loop(data)
        checks = out["reference_checks"]
        self.assertEqual(["resolved", "resolved", "registered_only"],
                         [row["status"] for row in checks])
        self.assertEqual(["2020", "2024"], [row["identity"]["edition"] for row in checks[:2]])
        self.assertIn("external_reference_identity_missing", {issue["code"] for issue in out["issues"]})
        self.assertNotIn("unresolved_clause_reference", {issue["code"] for issue in out["issues"]})
        data["reference_bindings"] = [{"clause_id": "C-1", "reference": "GB/T 1234-2020",
                                       "kind": "external", "target_id": "R-2024"}]
        out = standards.closed_loop(data)
        self.assertEqual("version_mismatch", out["reference_checks"][0]["status"])
        self.assertIn("clause_reference_version_mismatch", {issue["code"] for issue in out["issues"]})

    def test_internal_external_collision_requires_one_actual_explicit_binding(self):
        data = final_ready_payload()
        data["clauses"][0]["references"] = ["C-1"]
        data["external_references"] = [{"id": "C-1", "identifier": "SYN-1", "edition": "unspecified",
                                          "title": "合成标准", "source": "synthetic:external"}]
        out = standards.closed_loop(data)
        self.assertEqual("ambiguous", out["reference_checks"][0]["status"])
        self.assertIn("ambiguous_clause_reference", {issue["code"] for issue in out["issues"]})
        binding = {"clause_id": "C-1", "reference": "C-1", "kind": "internal", "target_id": "C-1"}
        data["reference_bindings"] = [binding]
        self.assertEqual("resolved", standards.closed_loop(data)["reference_checks"][0]["status"])
        data["reference_bindings"].append(copy.deepcopy(binding))
        with self.assertRaisesRegex(ContractError, "duplicate_reference_binding"):
            standards.closed_loop(data)
        data["reference_bindings"] = [{**binding, "reference": "ABSENT"}]
        with self.assertRaisesRegex(ContractError, "reference_binding_reference_missing"):
            standards.closed_loop(data)

    def test_external_wrong_year_is_never_upgraded_and_cycle_is_allowed(self):
        data = final_ready_payload()
        data["clauses"][0]["references"] = ["GB/T 1234-2010"]
        data["external_references"] = [{"id": "R-2024", "identifier": "GB/T 1234", "edition": "2024",
                                          "title": "合成标准", "source": "synthetic:external"}]
        self.assertIn("clause_reference_version_mismatch", self.codes(data))
        data["clauses"][0]["references"] = ["C-2"]
        data["clauses"].append({**data["clauses"][0], "id": "C-2", "references": ["C-1"]})
        out = standards.closed_loop(data)
        self.assertEqual(["resolved", "resolved"], [row["status"] for row in out["reference_checks"]])

    def test_external_identity_mismatch_and_unreferenced_registration_duplicates_reject(self):
        data = final_ready_payload()
        data["external_references"] = [{"id": "R-1", "identifier": "SYN-1", "edition": "2024",
                                          "title": "合成外部标准", "source": "synthetic:external"}]
        data["clauses"][0]["references"] = ["SYN-2"]
        data["reference_bindings"] = [{"clause_id": "C-1", "reference": "SYN-2", "kind": "external", "target_id": "R-1"}]
        out = standards.closed_loop(data)
        self.assertEqual("identity_mismatch", out["reference_checks"][0]["status"])
        self.assertIn("clause_reference_identity_mismatch", {row["code"] for row in out["issues"]})
        data["reference_bindings"] = []
        data["clauses"][0]["references"] = []
        data["external_references"].append({**data["external_references"][0], "id": "R-2", "identifier": "SYN-1-2024"})
        with self.assertRaisesRegex(ContractError, "duplicate_external_reference_identity"):
            standards.closed_loop(data)

    def test_same_labels_modified_proposal_reason_and_original_are_stale(self):
        changes = (
            lambda p: (p["comment_outcomes"][0]["changes"][0].update(proposed_text="应保留完整校验结果。"),
                       p["clauses"][0].update(text="应保留完整校验结果。")),
            lambda p: p["comment_outcomes"][0].update(reason="另一项合成理由"),
            lambda p: p["comment_outcomes"][0].update(extension={"new_decision_fact": True}),
            lambda p: p["comment_outcomes"][0]["impact"].update(references=True),
            lambda p: p["comments"][0].update(source="synthetic:changed-original"),
            lambda p: p["comments"][0].update(text="另一条完整合成意见。"),
            lambda p: p["comments"][0].update(participant_id="synthetic:participant-2"),
            lambda p: p["comments"][0].update(provenance={"page": 3, "scope": "synthetic"}),
            lambda p: p.update(adaptation={**p["adaptation"], "domain": "synthetic:changed-domain"}),
            lambda p: p["baseline_clauses"][0].update(text="新的合成基线原文。"),
            lambda p: p["comment_outcomes"][0].update(no_change_targets=["C-2"]),
        )
        for mutate in changes:
            data = final_ready_payload()
            mutate(data)
            before = copy.deepcopy(data)
            out = standards.closed_loop(data)
            self.assertIn("comment_decision_content_binding_stale", {issue["code"] for issue in out["issues"]})
            self.assertEqual("stale", out["confirmation_checks"][0]["status"])
            self.assertEqual(before, data)

    def test_early_v2_is_unbound_and_confirm_action_archives_without_mutation(self):
        data = final_ready_payload()
        data["comment_outcomes"][0]["confirmation"].pop("content_binding", None)
        before = copy.deepcopy(data)
        out = standards.closed_loop(data)
        self.assertEqual("unbound", out["confirmation_checks"][0]["status"])
        self.assertIn("comment_decision_content_binding_unbound", {issue["code"] for issue in out["issues"]})
        confirmed = standards_contract.confirm_comment(data, "COM-1", {
            "actor": "synthetic-reviewer-2", "authority_evidence": "synthetic:authority-2",
            "source": "synthetic:confirmation-2", "version": "decision-v1", "baseline_version": "v1"})
        self.assertEqual(before, data)
        row = confirmed["comment_outcomes"][0]
        self.assertEqual([before["comment_outcomes"][0]["confirmation"]], row["confirmation_history"])
        self.assertEqual("confirmed", row["decision_status"])
        expected = standards_contract.comment_content_binding(confirmed, row)
        self.assertEqual(expected, row["confirmation"]["content_binding"])
        self.assertEqual("current", standards.closed_loop(confirmed)["confirmation_checks"][0]["status"])
        self.assertNotEqual(expected["decision_hash"], digest({key: value for key, value in row.items()
            if key not in ("confirmation", "confirmation_history", "decision_status")}))

    def test_explicit_confirmation_uses_confirmed_hash_and_preserves_proposal(self):
        data = final_ready_payload()
        row = data["comment_outcomes"][0]
        row["decision_status"] = "proposed"
        row.pop("confirmation")
        before = copy.deepcopy(data)
        out = standards.closed_loop(data)
        self.assertEqual("unconfirmed", out["confirmation_checks"][0]["status"])
        self.assertEqual(before, data)
        data = standards_contract.confirm_comment(data, "COM-1", {
            "actor": "synthetic-reviewer", "authority_evidence": "synthetic:authority",
            "source": "synthetic:confirmation", "version": "decision-v2", "baseline_version": "v1"})
        row = data["comment_outcomes"][0]
        self.assertEqual("confirmed", row["decision_status"])
        self.assertEqual("proposed", before["comment_outcomes"][0]["decision_status"])
        self.assertEqual(digest({key: value for key, value in row.items()
                                if key not in ("confirmation", "confirmation_history")}),
                         row["confirmation"]["content_binding"]["decision_hash"])
        data["clauses"][0]["text"] = "决定尚未落地的正文。"
        self.assertIn("comment_change_not_applied", self.codes(data))

    def test_forged_scope_and_malformed_content_binding_do_not_confirm(self):
        data = final_ready_payload()
        binding = data["comment_outcomes"][0]["confirmation"]["content_binding"]
        binding["baseline_scope"]["clause_ids"] = ["C-OTHER"]
        self.assertEqual("stale", standards.closed_loop(data)["confirmation_checks"][0]["status"])
        binding["decision_hash"] = "not-a-digest"
        with self.assertRaisesRegex(ContractError, "comment_content_binding_hash_invalid:decision_hash"):
            standards.closed_loop(data)
        data = final_ready_payload()
        data["comment_outcomes"][0]["confirmation"]["content_binding"]["binding_version"] = "comment-content/999"
        self.assertEqual("stale", standards.closed_loop(data)["confirmation_checks"][0]["status"])

    def test_confirmation_history_accepts_only_confirmation_records(self):
        for hidden in ({"reason": "隐藏决定"}, {"changes": []}, {"extension": {"outcome": "accepted"}}):
            data = final_ready_payload()
            data["comment_outcomes"][0]["confirmation_history"] = [hidden]
            with self.assertRaisesRegex(ContractError, "confirmation_history_record_invalid"):
                standards.closed_loop(data)
        data = final_ready_payload()
        original = copy.deepcopy(data["comment_outcomes"][0]["confirmation"])
        data["comment_outcomes"][0]["confirmation_history"] = [original]
        self.assertEqual("current", standards.closed_loop(data)["confirmation_checks"][0]["status"])
        data["comment_outcomes"][0]["confirmation"]["actor"] = "synthetic:another-actor"
        self.assertEqual("current", standards.closed_loop(data)["confirmation_checks"][0]["status"])

    def test_local_baseline_scope_includes_actual_dependencies_but_not_unrelated(self):
        data = final_ready_payload()
        dependent = {**copy.deepcopy(data["baseline_clauses"][0]), "id": "C-DEP", "references": []}
        unrelated = {**copy.deepcopy(dependent), "id": "C-UNRELATED"}
        data["baseline_clauses"] += [dependent, unrelated]
        data["clauses"] += [copy.deepcopy(dependent), copy.deepcopy(unrelated)]
        data["baseline_clauses"][0]["references"] = ["C-DEP"]
        data["clauses"][0]["references"] = ["C-DEP"]
        confirmation = {key: value for key, value in data["comment_outcomes"][0]["confirmation"].items()
                        if key != "content_binding"}
        data = standards_contract.confirm_comment(data, "COM-1", confirmation)
        binding = data["comment_outcomes"][0]["confirmation"]["content_binding"]
        self.assertEqual({"kind": "targets", "clause_ids": ["C-1", "C-DEP"]}, binding["baseline_scope"])
        data["baseline_clauses"][2]["text"] = "无关基线变化。"
        self.assertEqual("current", standards.closed_loop(data)["confirmation_checks"][0]["status"])
        data["baseline_clauses"][1]["text"] = "依赖基线变化。"
        self.assertEqual("stale", standards.closed_loop(data)["confirmation_checks"][0]["status"])
        data["comments"][0].pop("clause_id")
        data["comments"][0]["scope"] = "document"
        self.assertEqual("document", standards_contract.comment_content_binding(
            data, data["comment_outcomes"][0])["baseline_scope"]["kind"])


    def test_independent_comment_decisions_keep_their_own_binding(self):
        data = final_ready_payload()
        other_clause = {**copy.deepcopy(data["baseline_clauses"][0]), "id": "C-2"}
        data["baseline_clauses"].append(other_clause)
        data["clauses"].append(copy.deepcopy(other_clause))
        data["comments"].append({**copy.deepcopy(data["comments"][0]), "id": "COM-2", "clause_id": "C-2"})
        other = copy.deepcopy(data["comment_outcomes"][0])
        other.update(comment_id="COM-2", changes=[], no_change=True, reason_source="synthetic:unchanged")
        other.pop("confirmation")
        data["comment_outcomes"].append(other)
        confirmation = {"actor": "synthetic-reviewer", "authority_evidence": "synthetic:authority",
                        "source": "synthetic:decision", "version": "decision-v1", "baseline_version": "v1"}
        data = standards_contract.confirm_comment(data, "COM-1", confirmation)
        data = standards_contract.confirm_comment(data, "COM-2", confirmation)
        data["comment_outcomes"][0]["reason"] = "重审第一项的理由。"
        checks = standards.closed_loop(data)["confirmation_checks"]
        self.assertEqual(["stale", "current"], [row["status"] for row in checks])
        data["baseline_clauses"][0]["text"] = "第一项基线也发生变化。"
        self.assertEqual("current", standards.closed_loop(data)["confirmation_checks"][1]["status"])


class ConfirmationSourceDependencyTests(unittest.TestCase):
    """SP-02／05：来源声明随实际依赖失效；合成hash不证明原件真实。"""

    @staticmethod
    def source_payload(*, kind="comment_reason", identity="COM-1", document=False):
        data = final_ready_payload()
        dependent = {**copy.deepcopy(data["baseline_clauses"][0]), "id": "C-DEP", "method_ids": ["V-DEP"]}
        unrelated = {**copy.deepcopy(dependent), "id": "C-OTHER", "method_ids": ["V-OTHER"]}
        data["baseline_clauses"] += [dependent, unrelated]
        data["clauses"] += [copy.deepcopy(dependent), copy.deepcopy(unrelated)]
        data["baseline_clauses"][0]["references"] = ["C-DEP"]
        data["clauses"][0]["references"] = ["C-DEP"]
        for clause, method in zip(data["clauses"], ("V1", "V-DEP", "V-OTHER")):
            if method == "V1":
                row = data["verification_matrix"][0]
            else:
                row = {**copy.deepcopy(data["verification_matrix"][0]), "id": method}
                data["verification_matrix"].append(row)
            row.update(clause_id=clause["id"], clause_hash=digest(clause))
        data["comments"].append({**copy.deepcopy(data["comments"][0]), "id": "COM-OTHER", "clause_id": "C-OTHER"})
        other = copy.deepcopy(data["comment_outcomes"][0])
        other.update(comment_id="COM-OTHER", changes=[], no_change=True, reason_source="synthetic:unchanged")
        other.pop("confirmation")
        data["comment_outcomes"].append(other)
        if document:
            data["comments"][0].pop("clause_id")
            data["comments"][0]["scope"] = "document"
        data["source_reports"] = [{
            "report_id": "SR-1", "path": "synthetic/not-opened-source-report.json", "sha256": "a" * 64,
            "source": {"number": "SYN-1", "edition": "2026", "publisher": "synthetic", "title": "合成来源"},
            "original_sha256": "b" * 64,
            "citations": [{"id": "CITE-1", "quote": "合成引文", "proposition": "合成支持命题"}],
        }]
        data["source_bindings"] = [{
            "binding_id": "SB-1", "target_type": kind, "target_id": identity, "report_id": "SR-1",
            "citation_ids": ["CITE-1"], "proposition": "合成支持命题", "version": data["version"],
        }]
        data["compilation_note"]["clause_digest"] = digest(data["clauses"])
        confirmation = {"actor": "synthetic-reviewer", "authority_evidence": "synthetic:authority",
                        "source": "synthetic:decision", "version": "decision-v1", "baseline_version": "v1"}
        for comment_id in ("COM-1", "COM-OTHER"):
            data = standards_contract.confirm_comment(data, comment_id, confirmation)
        return data

    def assert_source_stale(self, data, mutate, *, other_current=True):
        original = copy.deepcopy(data)
        before = standards.closed_loop(data)
        self.assertEqual(["current", "current"], [row["status"] for row in before["confirmation_checks"]])
        self.assertTrue(before["outcome_tally"]["closed"])
        mutate(data)
        changed = copy.deepcopy(data)
        after = standards.closed_loop(data)
        self.assertEqual("stale", after["confirmation_checks"][0]["status"])
        if other_current:
            self.assertEqual("current", after["confirmation_checks"][1]["status"])
        self.assertFalse(after["outcome_tally"]["closed"])
        self.assertEqual(original["comment_outcomes"], after["comment_outcomes"])
        self.assertEqual(changed, data)

    def test_current_comment_source_binding_and_report_changes_are_stale(self):
        changes = {
            "report_sha": lambda p: p["source_reports"][0].update(sha256="c" * 64),
            "original_sha": lambda p: p["source_reports"][0].update(original_sha256="c" * 64),
            "report_path": lambda p: p["source_reports"][0].update(path="synthetic/another-report.json"),
            "edition": lambda p: p["source_reports"][0]["source"].update(edition="2027"),
            "report_citation": lambda p: p["source_reports"][0]["citations"][0].update(quote="另一段合成引文"),
            "report_extension": lambda p: p["source_reports"][0].update(extraction={"coverage": "partial"}),
            "proposition": lambda p: p["source_bindings"][0].update(proposition="另一项合成命题"),
            "binding_citation": lambda p: p["source_bindings"][0].update(citation_ids=["CITE-2"]),
            "binding_version": lambda p: p["source_bindings"][0].update(version="v3"),
            "report_removed": lambda p: p["source_reports"].clear(),
            "binding_removed": lambda p: p["source_bindings"].clear(),
        }
        for kind in ("comment", "comment_reason"):
            for label, mutate in changes.items():
                with self.subTest(kind=kind, change=label):
                    self.assert_source_stale(self.source_payload(kind=kind), mutate)

    def test_system_related_clause_and_verification_sources_are_stale(self):
        for kind, identity in (("clause", "C-1"), ("clause", "C-DEP"),
                               ("verification", "V1"), ("verification_basis", "V-DEP")):
            with self.subTest(kind=kind, identity=identity):
                data = self.source_payload(kind=kind, identity=identity)
                # impact是审阅声明；全false也不能取消真实引用和验证依赖。
                self.assertTrue(all(value is False for value in data["comment_outcomes"][0]["impact"].values()))
                self.assert_source_stale(data, lambda p: p["source_bindings"][0].update(proposition="重新解释来源命题"))

    def test_document_note_and_external_reference_sources_are_stale(self):
        for kind in ("compilation_note", "note_section"):
            with self.subTest(kind=kind):
                data = self.source_payload(kind=kind, identity=standards.COMPILATION_NOTE_SECTIONS[0])
                self.assert_source_stale(data, lambda p: p["source_reports"][0].update(sha256="c" * 64),
                                         other_current=False)
        data = self.source_payload(kind="external_reference", identity="EXT-1")
        data["external_references"] = [{"id": "EXT-1", "identifier": "SYN-EXT", "edition": "2026",
                                        "title": "合成外部引用", "source": "synthetic:external"}]
        data["clauses"][1]["references"] = ["SYN-EXT-2026"]
        data["baseline_clauses"][1]["references"] = ["SYN-EXT-2026"]
        data["verification_matrix"][1]["clause_hash"] = digest(data["clauses"][1])
        data["compilation_note"]["clause_digest"] = digest(data["clauses"])
        confirmation = {key: value for key, value in data["comment_outcomes"][0]["confirmation"].items()
                        if key != "content_binding"}
        data = standards_contract.confirm_comment(data, "COM-1", confirmation)
        data = standards_contract.confirm_comment(data, "COM-OTHER", confirmation)
        self.assert_source_stale(data, lambda p: p["source_reports"][0]["source"].update(edition="2027"))

    def test_unrelated_sources_and_unbound_report_remain_current_locally(self):
        data = self.source_payload(kind="comment_reason", identity="COM-OTHER")
        data["source_reports"][0].update(sha256="c" * 64)
        checks = standards.closed_loop(data)["confirmation_checks"]
        self.assertEqual(["current", "stale"], [row["status"] for row in checks])
        for kind, identity in (("clause", "C-OTHER"), ("verification_basis", "V-OTHER")):
            with self.subTest(kind=kind):
                data = self.source_payload(kind=kind, identity=identity)
                data["source_bindings"][0].update(proposition="无关联来源的新命题")
                self.assertEqual(["current", "stale"],
                                 [row["status"] for row in standards.closed_loop(data)["confirmation_checks"]])
        data = self.source_payload()
        data["source_bindings"] = []
        confirmation = {key: value for key, value in data["comment_outcomes"][0]["confirmation"].items()
                        if key != "content_binding"}
        data = standards_contract.confirm_comment(data, "COM-1", confirmation)
        data["source_reports"][0].update(sha256="c" * 64)
        self.assertEqual("current", standards.closed_loop(data)["confirmation_checks"][0]["status"])

    def test_document_scope_includes_all_source_declarations(self):
        for kind, identity in (("comment_reason", "COM-OTHER"), ("clause", "C-OTHER"),
                               ("verification_basis", "V-OTHER")):
            with self.subTest(kind=kind):
                data = self.source_payload(kind=kind, identity=identity, document=True)
                self.assert_source_stale(data, lambda p: p["source_reports"][0].update(sha256="c" * 64),
                                         other_current=False)
        data = self.source_payload(document=True)
        data["source_bindings"] = []
        confirmation = {key: value for key, value in data["comment_outcomes"][0]["confirmation"].items()
                        if key != "content_binding"}
        data = standards_contract.confirm_comment(data, "COM-1", confirmation)
        data["source_reports"][0]["source"]["edition"] = "2027"
        self.assertEqual("stale", standards.closed_loop(data)["confirmation_checks"][0]["status"])

    def test_old_content_binding_is_stale_and_explicit_reconfirmation_keeps_history(self):
        data = self.source_payload()
        data["comment_outcomes"][0]["confirmation"]["content_binding"]["binding_version"] = "comment-content/1"
        original = copy.deepcopy(data)
        out = standards.closed_loop(data)
        self.assertEqual("stale", out["confirmation_checks"][0]["status"])
        self.assertEqual(original, data)
        confirmation = {key: value for key, value in data["comment_outcomes"][0]["confirmation"].items()
                        if key != "content_binding"}
        confirmed = standards_contract.confirm_comment(data, "COM-1", confirmation)
        self.assertEqual("comment-content/2", confirmed["comment_outcomes"][0]["confirmation"]["content_binding"]["binding_version"])
        self.assertEqual(original["comment_outcomes"][0]["confirmation"],
                         confirmed["comment_outcomes"][0]["confirmation_history"][-1])
        self.assertEqual("current", standards.closed_loop(confirmed)["confirmation_checks"][0]["status"])


class V2SchemaParityTests(unittest.TestCase):
    """核具体schema节点及真实消费者，不实现通用JSON Schema解释器。"""

    @classmethod
    def setUpClass(cls):
        cls.comment_schema = json.loads(
            (RESOURCE / "comment-disposition.v2.schema.json").read_text(encoding="utf-8"))
        cls.note_schema = json.loads(
            (RESOURCE / "compilation-note.v2.schema.json").read_text(encoding="utf-8"))

    def assert_contract_error(self, payload, code):
        with self.assertRaises(ContractError) as caught:
            standards.closed_loop(payload)
        self.assertEqual(code, str(caught.exception))

    def rich_payload(self):
        data = final_ready_payload()
        data["collection_evidence"] = ["synthetic:collection"]
        data["comments"][0].update(scope="", provenance={"page": 2, "quote": "合成原文"})
        row = data["comment_outcomes"][0]
        row.update(reason_source="synthetic:reason", no_change=False,
                   no_change_scope=None, no_change_targets=[], accepted_part="",
                   rejected_part="", rejected_reason="", extension={"review_tags": ["synthetic"]})
        row["confirmation_history"] = [copy.deepcopy(row["confirmation"])]
        row["confirmation"]["extension"] = {"record": "synthetic:authority-record"}
        row["changes"][0]["dependency_resolution"] = {
            "status": "not_applicable", "source": "", "reason": "合成替换，无删除依赖。"}
        row["changes"][0]["extension"] = {"order": 1}
        for index, outcome in enumerate(("partially_accepted", "rejected", "pending"), 2):
            cid = f"COM-{index}"
            data["comments"].append({**data["comments"][0], "id": cid})
            other = copy.deepcopy(row)
            other.update(comment_id=cid, outcome=outcome)
            if outcome == "partially_accepted":
                other.update(accepted_part="措辞", rejected_part="试验", rejected_reason="范围外")
            else:
                other["changes"] = []
            if outcome == "pending":
                other["unresolved_item"] = {
                    "id": "O-comment", "question": "补核原记录", "owner": "组A",
                    "blocks": "submission", "recovery": "获得记录",
                    "source_refs": ["synthetic:pending"], "extension": {"priority": 1}}
            data["comment_outcomes"].append(other)
        note = data["compilation_note"]
        note["extension"] = {"template_locator": "synthetic:template:1"}
        sections = note["sections"]
        sections[0].update(inference_basis="", review_required=False, reason="",
                           question="", blocks="none", recovery="",
                           extension={"paragraph": "synthetic:paragraph:1"})
        sections[1].update(state="inferred", inference_basis="合成推断依据", review_required=True)
        sections[2].update(state="unknown", question="适用性待核", blocks="none", recovery="取得依据")
        sections[3].update(state="not_applicable", reason="合成案例无此事项")
        sections[0]["open_items"] = [{
            "id": "O-note", "question": "核对记录", "owner": "组A", "blocks": "none",
            "recovery": "取得原始记录", "source_refs": ["synthetic:note"], "extension": ["original"]}]
        sections[-1].pop("open_items")
        assessment = standards.closed_loop(data)
        sections[8]["outcome_tally"] = copy.deepcopy(assessment["outcome_tally"])
        sections[9]["verification_summary"] = copy.deepcopy(assessment["verification_summary"])
        sections[-1]["open_items"] = copy.deepcopy(assessment["open_items"])
        return data

    def test_identity_mapping_both_directions_preserve_complete_records(self):
        """schema→运行时→schema是原字段映射；序列化只额外核输出边界。"""
        data = self.rich_payload()
        before = copy.deepcopy(data)
        record_fields = ("comments", "comment_outcomes", "compilation_note")
        for capability in ("STD-09", "STD-11"):
            result = standards.run(capability, data)
            artifacts = result["artifacts"]
            self.assertEqual(before, data)
            imported = copy.deepcopy(data)
            for field in record_fields:
                # 真实运行结果而非json.loads(json.dumps(input))充当反向输入。
                self.assertEqual(data[field], artifacts[field])
                self.assertIsNot(data[field], artifacts[field])
                imported[field] = copy.deepcopy(artifacts[field])
            second = standards.closed_loop(imported)
            for field in record_fields:
                self.assertEqual(data[field], second[field])
                self.assertEqual(data[field], json.loads(canonical_bytes(result))["artifacts"][field])
            self.assertEqual(standards.closed_loop(data)["issues"], second["issues"])
            self.assertEqual("not_performed", second["implementation_verification"])
        outcome_props = self.comment_schema["$defs"]["outcome"]["properties"]
        fields_seen = set().union(*(set(row) for row in data["comment_outcomes"]))
        # 直写替换和不改互斥，另以真实分支覆盖，不伪造一个全字段冲突记录。
        self.assertEqual(set(outcome_props) - {
            "clause_id", "proposed_text", "comment_realizations", "realization",
            "realization_evidence", "applied", "document_hash"}, fields_seen - {"extension"})
        self.assertEqual(set(self.note_schema["$defs"]["section"]["properties"]),
                         set().union(*(set(s) for s in data["compilation_note"]["sections"])) - {"extension"})
        self.assertTrue(self.comment_schema["additionalProperties"])
        self.assertTrue(self.note_schema["additionalProperties"])

    def test_identity_mapping_direct_change_and_no_change_forms(self):
        for form in ("direct", "clause-no-change", "document-no-change"):
            with self.subTest(form=form):
                data = final_ready_payload()
                row = data["comment_outcomes"][0]
                row.pop("changes")
                if form == "direct":
                    row.update(clause_id="C-1", proposed_text=data["clauses"][0]["text"])
                else:
                    data["baseline_clauses"] = copy.deepcopy(data["clauses"])
                    row.update(no_change=True, reason_source="synthetic:unchanged")
                    if form == "document-no-change":
                        row.update(no_change_scope="document", no_change_targets=[])
                    else:
                        row.update(no_change_scope=None, no_change_targets=["C-1"])
                data = standards_contract.confirm_comment(data, "COM-1", row["confirmation"])
                row = data["comment_outcomes"][0]
                out = standards.closed_loop(data)
                self.assertEqual([], out["issues"])
                self.assertEqual(row, out["comment_outcomes"][0])
                data["comment_outcomes"] = out["comment_outcomes"]
                self.assertEqual(out, standards.closed_loop(data))

    def test_schema_required_fields_and_runtime_errors_are_explicit(self):
        definitions = self.comment_schema["$defs"]
        self.assertEqual(["contract_version", "project_id", "version", "adaptation"],
                         self.comment_schema["required"])
        for name, expected in (
            ("comment", ["id", "text", "source", "participant_id", "version"]),
            ("outcome", ["comment_id", "outcome", "classification", "reason", "decision_status", "major_change"]),
            ("change", ["operation", "clause_id"]),
            ("pendingItem", ["question", "owner", "blocks", "recovery"]),
        ):
            self.assertEqual(expected, definitions[name]["required"])
        for path, fields in (("comments", definitions["comment"]["required"]),
                             ("comment_outcomes", definitions["outcome"]["required"])):
            for field in fields:
                with self.subTest(record=path, field=field):
                    data = final_ready_payload()
                    del data[path][0][field]
                    self.assert_contract_error(data, f"string_required:{field}")
        for field in ("project_id", "version", "adaptation"):
            data = final_ready_payload()
            del data[field]
            self.assert_contract_error(data, f"missing:{field}")
        data = final_ready_payload()
        del data["contract_version"]
        self.assert_contract_error(data, "closed_loop_requires_contract_v2")
        self.assertEqual(["organization", "standard_type", "domain", "stage"],
                         self.comment_schema["properties"]["adaptation"]["required"])
        for field in self.comment_schema["properties"]["adaptation"]["required"]:
            data = final_ready_payload()
            del data["adaptation"][field]
            self.assert_contract_error(data, f"missing:{field}")

    def test_every_controlled_enum_matches_runtime_rejection(self):
        definitions = self.comment_schema["$defs"]
        props = definitions["outcome"]["properties"]
        cases = (
            (props["outcome"], ["accepted", "partially_accepted", "rejected", "pending"],
             lambda p: p["comment_outcomes"][0], "outcome", "comment_outcome_unknown"),
            (props["classification"], ["technical", "editorial", "procedural", "ip", "insufficient_evidence"],
             lambda p: p["comment_outcomes"][0], "classification", "comment_classification_unknown"),
            (props["decision_status"], ["proposed", "confirmed"],
             lambda p: p["comment_outcomes"][0], "decision_status", "comment_decision_status_unknown"),
            (props["major_change"], ["yes", "no", "undetermined"],
             lambda p: p["comment_outcomes"][0], "major_change", "comment_major_change_unknown"),
            (definitions["change"]["properties"]["operation"], ["replace", "add", "delete"],
             lambda p: p["comment_outcomes"][0]["changes"][0], "operation", "comment_change_operation_unknown"),
            (self.comment_schema["properties"]["collection_status"], ["complete", "partial", "unknown", "not_started"],
             lambda p: p, "collection_status", "collection_status_unknown"),
            (self.note_schema["$defs"]["section"]["properties"]["state"], ["explicit", "inferred", "unknown", "not_applicable"],
             lambda p: p["compilation_note"]["sections"][0], "state", "compilation_note_state_unknown"),
        )
        for schema, values, locate, field, code in cases:
            self.assertEqual(values, schema["enum"])
            for invalid in ("unrecognized", True, 1):
                with self.subTest(field=field, value=invalid):
                    data = final_ready_payload()
                    locate(data)[field] = invalid
                    self.assert_contract_error(data, code if isinstance(invalid, str) or field == "collection_status"
                                               else f"string_required:{field}")
        for value in definitions["outcome"]["properties"]["classification"]["enum"]:
            data = final_ready_payload()
            data["comment_outcomes"][0]["classification"] = value
            data = standards_contract.confirm_comment(data, "COM-1", data["comment_outcomes"][0]["confirmation"])
            self.assertEqual([], standards.closed_loop(data)["issues"])
        expected_blocks = ["submission", "approval", "publication", "none"]
        self.assertEqual(expected_blocks, definitions["pendingItem"]["properties"]["blocks"]["enum"])
        self.assertEqual(expected_blocks, self.note_schema["$defs"]["openItem"]["properties"]["blocks"]["enum"])

    def test_optional_types_rejected_even_outside_active_business_branch(self):
        definitions = self.comment_schema["$defs"]
        outcome_props = definitions["outcome"]["properties"]
        note_props = self.note_schema["$defs"]["section"]["properties"]
        for field in ("reason_source", "decision_version", "accepted_part", "rejected_part", "rejected_reason"):
            self.assertEqual("string", outcome_props[field]["type"])
            data = final_ready_payload()
            data["comment_outcomes"][0][field] = 1
            self.assert_contract_error(data, f"comment_outcome_string_required:{field}")
        for field in ("clause_id", "scope"):
            self.assertEqual("string", definitions["comment"]["properties"][field]["type"])
            data = final_ready_payload()
            data["comments"][0][field] = 42
            self.assert_contract_error(data, f"comment_string_required:{field}")
        for field in ("actor", "authority_evidence", "source", "version", "baseline_version"):
            self.assertEqual("string", outcome_props["confirmation"]["properties"][field]["type"])
            data = final_ready_payload()
            data["comment_outcomes"][0]["decision_status"] = "proposed"
            data["comment_outcomes"][0]["confirmation"][field] = []
            self.assert_contract_error(data, f"comment_confirmation_string_required:{field}")
        for field in ("inference_basis", "reason", "question", "recovery"):
            self.assertEqual("string", note_props[field]["type"])
            data = final_ready_payload()
            data["compilation_note"]["sections"][0][field] = False
            self.assert_contract_error(data, f"compilation_note_string_required:{field}")
        for field in ("status", "source", "reason"):
            schema = definitions["change"]["properties"]["dependency_resolution"]
            self.assertEqual("string", schema["properties"][field]["type"])
            data = final_ready_payload()
            data["comment_outcomes"][0]["changes"][0]["dependency_resolution"] = {field: 1}
            self.assert_contract_error(data, f"dependency_resolution_string_required:{field}")
        cases = (
            (lambda p: p.update(baseline_version=False), "comment_string_required:baseline_version"),
            (lambda p: p["comment_outcomes"][0].update(decision_status="proposed", confirmation=[]), "comment_confirmation_object_required"),
            (lambda p: p["comment_outcomes"][0].update(no_change_targets="C-1"), "no_change_targets_required"),
            (lambda p: p["comment_outcomes"][0].update(no_change_scope="section"), "no_change_scope_unknown"),
            (lambda p: p["comment_outcomes"][0].update(no_change=1), "comment_no_change_boolean_required"),
            (lambda p: p["comment_outcomes"][0].update(unresolved_item=[]), "open_item_object_required"),
            (lambda p: p["comment_outcomes"][0]["changes"][0].update(dependency_resolution=[]), "dependency_resolution_object_required"),
            (lambda p: p["compilation_note"]["sections"][0].update(review_required=1), "compilation_note_review_boolean_required"),
            (lambda p: p["compilation_note"]["sections"][0].update(body=[]), "compilation_note_string_required:body"),
            (lambda p: p["compilation_note"].update(profile_hash=1), "compilation_note_string_required:profile_hash"),
        )
        for mutate, code in cases:
            with self.subTest(code=code):
                data = final_ready_payload()
                mutate(data)
                self.assert_contract_error(data, code)
        self.assertEqual("boolean", outcome_props["no_change"]["type"])
        self.assertEqual("boolean", note_props["review_required"]["type"])
        self.assertEqual([None, "document"], outcome_props["no_change_scope"]["enum"])

    def test_missing_or_blank_evidence_remains_an_internal_draft(self):
        self.assertEqual("string", self.comment_schema["properties"]["baseline_version"]["type"])
        self.assertEqual("string", self.comment_schema["$defs"]["outcome"]["properties"]["decision_version"]["type"])
        for field, issue_code in (("baseline_version", "comment_decision_baseline_unbound_or_stale"),
                                  ("decision_version", "comment_decision_version_missing")):
            for value in (None, "", "  "):
                data = final_ready_payload()
                record = data if field == "baseline_version" else data["comment_outcomes"][0]
                if value is None:
                    record.pop(field)
                else:
                    record[field] = value
                out = standards.closed_loop(data)
                self.assertIn(issue_code, {issue["code"] for issue in out["issues"]})
                self.assertFalse(out["outcome_tally"]["closed"])
                self.assertEqual(data["comment_outcomes"], out["comment_outcomes"])
        self.assertEqual(["standard_name", "version", "clause_digest", "profile_id", "profile_hash", "sections"],
                         self.note_schema["required"])
        self.assertEqual(["id", "heading", "body", "state", "owner"],
                         self.note_schema["$defs"]["section"]["required"])
        for field in self.note_schema["required"]:
            data = final_ready_payload()
            del data["compilation_note"][field]
            out = standards.closed_loop(data)
            expected = "compilation_note_section_missing" if field == "sections" else "compilation_note_field_missing"
            self.assertIn(expected, {issue["code"] for issue in out["issues"]})
            self.assertEqual(data["compilation_note"], out["compilation_note"])
            self.assertFalse(out["outcome_tally"]["closed"])
        for field in ("id", "heading", "state", "owner"):
            data = final_ready_payload()
            del data["compilation_note"]["sections"][0][field]
            self.assert_contract_error(data, f"string_required:{field}")
        data = final_ready_payload()
        del data["compilation_note"]["sections"][0]["body"]
        out = standards.closed_loop(data)
        self.assertIn("compilation_note_body_missing", {issue["code"] for issue in out["issues"]})
        self.assertEqual(data["compilation_note"], out["compilation_note"])

    def test_schema_state_conditions_have_positive_and_draft_counterexamples(self):
        conditions = self.note_schema["$defs"]["section"]["allOf"]
        cases = (
            ("explicit", {"source": ["synthetic:source"]}, "source", "compilation_note_source_missing"),
            ("inferred", {"source": ["synthetic:source"], "inference_basis": "合成推断", "review_required": True},
             "inference_basis", "compilation_note_inference_unreviewed"),
            ("unknown", {"question": "核验资料？", "blocks": "none", "recovery": "取得资料"},
             "recovery", "compilation_note_state_unowned"),
            ("not_applicable", {"reason": "不适用依据"}, "reason", "compilation_note_not_applicable_unreasoned"),
        )
        for index, (state, fields, missing_field, issue_code) in enumerate(cases):
            with self.subTest(state=state):
                self.assertEqual(state, conditions[index]["if"]["properties"]["state"]["const"])
                self.assertEqual(set(fields), set(conditions[index]["then"]["required"]))
                data = final_ready_payload()
                section = data["compilation_note"]["sections"][0]
                section.update(state=state, **fields)
                data["compilation_note"]["sections"][-1].pop("open_items")
                out = standards.closed_loop(data)
                self.assertNotIn(issue_code, {issue["code"] for issue in out["issues"]})
                self.assertEqual(section, out["compilation_note"]["sections"][0])
                del section[missing_field]
                out = standards.closed_loop(data)
                self.assertIn(issue_code, {issue["code"] for issue in out["issues"]})
                self.assertFalse(out["outcome_tally"]["closed"])
        self.assertEqual({"const": True}, conditions[1]["then"]["properties"]["review_required"])
        self.assertEqual({"minItems": 1}, conditions[0]["then"]["properties"]["source"])

    def test_schema_change_conditions_reject_conflicting_forms(self):
        definition = self.comment_schema["$defs"]["outcome"]
        self.assertEqual({"clause_id": ["proposed_text"], "proposed_text": ["clause_id"]},
                         definition["dependentRequired"])
        scope_rule = definition["allOf"][-1]
        self.assertEqual({"required": ["no_change"], "properties": {"no_change": {"const": True}}}, scope_rule["if"])
        self.assertEqual({"not": {"required": ["no_change_targets", "no_change_scope"], "properties": {
            "no_change_targets": {"minItems": 1}, "no_change_scope": {"const": "document"}}}}, scope_rule["then"])
        for patch, code in (
            ({"clause_id": "C-1", "proposed_text": "text"}, "comment_change_forms_conflict"),
            ({"no_change": True}, "comment_change_forms_conflict"),
        ):
            data = final_ready_payload()
            data["comment_outcomes"][0].update(patch)
            self.assert_contract_error(data, code)
        data = final_ready_payload()
        row = data["comment_outcomes"][0]
        row.pop("changes")
        row.update(no_change=True, reason_source="synthetic:reason", no_change_targets=["C-1"],
                   no_change_scope="document")
        self.assert_contract_error(data, "no_change_scope_conflict")
        row["no_change_targets"] = []
        self.assertTrue(standards.closed_loop(data)["no_change_checks"])
        row["no_change_scope"] = None
        row["no_change_targets"] = ["MISSING"]
        out = standards.closed_loop(data)
        self.assertIn({"code": "no_change_target_missing", "record_id": "COM-1", "clause_id": "MISSING"}, out["issues"])
        self.assertFalse(out["outcome_tally"]["closed"])

    def test_schema_partial_pending_and_realization_conditions_match_runtime(self):
        definition = self.comment_schema["$defs"]["outcome"]
        self.assertEqual(["accepted_part", "rejected_part", "rejected_reason", "reason_source"],
                         definition["allOf"][2]["then"]["required"])
        self.assertEqual(["reason_source"], definition["allOf"][3]["then"]["required"])
        self.assertEqual(["unresolved_item"], definition["allOf"][4]["then"]["required"])
        for field in definition["allOf"][2]["then"]["required"]:
            data = self.rich_payload()
            del data["comment_outcomes"][1][field]
            self.assert_contract_error(data, "partial_acceptance_details_required")
        for field in ("question", "owner", "blocks", "recovery"):
            data = self.rich_payload()
            del data["comment_outcomes"][-1]["unresolved_item"][field]
            self.assert_contract_error(data, "pending_item_unowned")
        for field in ("realization", "realization_evidence", "comment_realizations", "applied", "document_hash"):
            self.assertIs(False, definition["properties"][field])
            data = final_ready_payload()
            data["comment_outcomes"][0][field] = None
            self.assert_contract_error(data, "comment_realization_separate_required")
        change_rule = self.comment_schema["$defs"]["change"]["allOf"][0]
        self.assertEqual({"const": ""}, change_rule["then"]["properties"]["proposed_text"])
        self.assertEqual(["proposed_text"], change_rule["else"]["required"])
        data = final_ready_payload()
        data["comment_outcomes"][0]["changes"][0].update(operation="delete", proposed_text="not empty")
        self.assert_contract_error(data, "delete_proposed_text_must_be_empty")


    def test_explicit_ballot_numeric_failure_blocks_v2_closure(self):
        for minimum, choice, present, expected in ((2, 'yes', True, False),
                                                  (1, 'no', True, False),
                                                  (1, 'yes', False, False),
                                                  (1, 'yes', True, True)):
            with self.subTest(minimum=minimum, choice=choice, present=present):
                data = final_ready_payload()
                data['participants'] = [dict(id='P1', eligible=True, authority_evidence='synthetic')]
                data['votes'] = [dict(id='V1', participant_id='P1', choice=choice,
                    evidence_id='synthetic', version=data['version'])] if present else []
                data['ballot_rule'] = dict(source='synthetic', min_votes=minimum,
                    min_yes_fraction=1, denominator='cast')
                result = standards.closed_loop(data)
                self.assertEqual(expected, result['outcome_tally']['closed'])
                self.assertEqual(not expected, any(row['code'] == 'ballot_numeric_conditions_not_met'
                    for row in result['issues']))

    def test_ballot_issues_precede_declared_compilation_tally_comparison(self):
        for declared in (True, False):
            with self.subTest(declared_closed=declared):
                data = final_ready_payload()
                data["participants"] = [dict(id="P1", group="synthetic", eligible=True,
                                              authority_evidence="synthetic:authority")]
                data["votes"] = [dict(id="V1", participant_id="P1", choice="yes",
                                       evidence_id="synthetic:vote")]
                data["ballot_rule"] = dict(source="synthetic:rule", min_votes=1,
                                           min_yes_fraction=1, denominator="cast")
                data["compilation_note"]["sections"][8]["outcome_tally"] = {"closed": declared}
                before = copy.deepcopy(data)
                result = standards.closed_loop(data)
                codes = {row["code"] for row in result["issues"]}
                self.assertFalse(result["outcome_tally"]["closed"])
                self.assertIn("vote_version_unproven", codes)
                self.assertEqual(declared, "compilation_note_tally_mismatch" in codes)
                self.assertEqual(before, data)

    def test_optional_top_level_inventory_is_consumed_and_preserved_in_package(self):
        props = self.comment_schema["properties"]
        optional = {"baseline_version", "standard_name", "profile", "verification_matrix",
                    "compilation_note", "decisions", "collection_status", "collection_evidence",
                    "comments", "comment_outcomes", "baseline_clauses", "clauses", "open_items",
                    "verification_open_items", "reference_open_items", "profile_open_items", "material_open_items",
                    "participants", "votes", "ballot_rule", "external_reference_ids", "external_references",
                    "reference_bindings", "source_reports", "source_bindings", "limitation_reviews", "presentation"}
        self.assertEqual(optional, set(props) - set(self.comment_schema["required"]))
        data = self.rich_payload()
        data["decisions"] = [{"id": "legacy-free-note", "decision": "仅保留原记录，不推断受控结果"}]
        data["participants"] = [{"id": f"P-{i}", "group": "synthetic", "eligible": True,
                                 "authority_evidence": f"synthetic:authority-{i}"} for i in (1, 2)]
        data["votes"] = [{"id": f"V-{i}", "participant_id": f"P-{i}", "choice": "yes",
                          "evidence_id": f"synthetic:vote-{i}", "version": data["version"]} for i in (1, 2)]
        data["ballot_rule"] = {"source": "synthetic:rule", "min_votes": 2,
                               "min_yes_fraction": 0.5, "denominator": "cast"}
        data.update(external_reference_ids=[], external_references=[], reference_bindings=[],
                    source_reports=[], source_bindings=[], limitation_reviews=[], presentation={})
        data["profile"].update(source="synthetic:internal-profile", section_semantics={})
        data["compilation_note"]["profile_hash"] = digest(data["profile"])
        sources = ("open_items", "verification_open_items", "reference_open_items",
                   "profile_open_items", "material_open_items")
        for field in sources:
            self.assertEqual({"type": "array", "items": {"$ref": "#/$defs/openItem"}}, props[field])
            data[field] = [{"id": "O-" + field, "question": "核验原记录", "owner": "组A",
                            "blocks": "none", "recovery": "取得记录", "source_refs": [field + ":S1"],
                            "extension": {"source_field": field}}]
        for row in data["verification_matrix"]:
            row.update(status="reviewed", review_evidence="synthetic:review",
                       reason="", applicability_source="", extension={"method_version": "synthetic:1"})
        sections = data["compilation_note"]["sections"]
        sections[8].pop("outcome_tally")
        sections[9].pop("verification_summary")
        sections[-1].pop("open_items")
        out = standards.closed_loop(data)
        sections[8]["outcome_tally"] = copy.deepcopy(out["outcome_tally"])
        sections[9]["verification_summary"] = copy.deepcopy(out["verification_summary"])
        sections[-1]["open_items"] = copy.deepcopy(out["open_items"])
        self.assertTrue(set(props) <= set(data))
        out = standards.closed_loop(data)
        self.assertEqual(data["decisions"], out["decisions"])
        self.assertEqual(data["profile"], out["profile"])
        self.assertEqual(data["collection_evidence"], out["collection_evidence"])
        self.assertEqual(digest(data["clauses"]), out["clause_digest"])
        for field in sources:
            self.assertIn(data[field][0], out["open_items"])
        self.assertEqual(1, out["verification_summary"]["reviewed"])
        with tempfile.TemporaryDirectory(prefix="dyz-schema-preservation-") as folder:
            root = Path(folder)
            standards_delivery.prepare(root, data, "pack", synthetic=True)
            exported = json.loads((root / "pack/internal/input.json").read_text(encoding="utf-8"))
            # 全量包原记录保留是另一条输出边界，不把JSON读回替代上面的运行契约断言。
            self.assertEqual(data, exported)
            self.assertEqual(out, standards.closed_loop(exported))
            for role, required_text in (
                ("comment_disposition", ("provenance", "authority_evidence", "source_refs", "采纳部分", "未决事项")),
                ("compilation_note", ("推论依据", "需复核", "未决", "source_refs", "意见统计", "验证概要")),
                ("verification_matrix", ("审阅证据", "适用性依据", "method_version")),
            ):
                with zipfile.ZipFile(root / "pack/body" / (role + ".docx")) as package:
                    tree = ET.fromstring(package.read("word/document.xml"))
                text = "".join(node.text or "" for node in tree.iter(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
                for field in required_text:
                    self.assertIn(field, text)
            self.assertTrue(standards_delivery.verify(root, data, "pack", synthetic=True)["file_hashes_equal"])

    def test_optional_top_level_and_section_malformed_containers_are_errors(self):
        props = self.comment_schema["properties"]
        for field in ("comments", "comment_outcomes", "baseline_clauses", "clauses",
                      "open_items", "verification_open_items", "reference_open_items",
                      "profile_open_items", "material_open_items", "verification_matrix"):
            self.assertEqual("array", props[field]["type"])
            data = final_ready_payload()
            data[field] = {}
            self.assert_contract_error(data, "records_list_required")
        data = final_ready_payload()
        data["standard_name"] = False
        self.assert_contract_error(data, "comment_string_required:standard_name")
        data = final_ready_payload()
        data["collection_evidence"] = "not a list"
        self.assert_contract_error(data, "comment_collection_evidence_list_required")
        data = final_ready_payload()
        data["compilation_note"] = []
        self.assert_contract_error(data, "compilation_note_object_required")
        data = final_ready_payload()
        data["profile"] = []
        self.assert_contract_error(data, "object_required")
        section_props = self.note_schema["$defs"]["section"]["properties"]
        for field, invalid, code in (
            ("source", "not a list", "compilation_note_source_list_required"),
            ("outcome_tally", [], "outcome_tally_object_required"),
            ("verification_summary", [], "verification_summary_object_required"),
            ("open_items", {}, "records_list_required"),
            ("blocks", "unknown", "open_item_blocks_unknown"),
        ):
            self.assertIn(field, section_props)
            data = final_ready_payload()
            data["compilation_note"]["sections"][0][field] = invalid
            self.assert_contract_error(data, code)
        self.assertEqual("object", section_props["outcome_tally"]["type"])
        self.assertEqual("object", section_props["verification_summary"]["type"])
        self.assertEqual({"type": "array", "items": {"$ref": "#/$defs/openItem"}}, section_props["open_items"])

    def test_profile_and_verification_optional_fields_have_typed_contracts(self):
        profile = self.comment_schema["$defs"]["profile"]
        self.assertEqual(["id", "version", "scope", "required_sections"], profile["required"])
        self.assertEqual(["internal", "organization"], profile["properties"]["scope"]["enum"])
        self.assertEqual({"source", "section_semantics"}, set(profile["properties"]) - set(profile["required"]))
        rule = profile["allOf"][0]
        self.assertEqual({"properties": {"scope": {"const": "internal"}}}, rule["if"])
        self.assertEqual(list(standards.COMPILATION_NOTE_SECTIONS),
                         rule["then"]["properties"]["required_sections"]["const"])
        self.assertEqual(["source", "section_semantics"], rule["else"]["required"])
        self.assertEqual({"minItems": 1, "uniqueItems": True},
                         rule["else"]["properties"]["required_sections"])
        self.assertEqual({"$ref": "compilation-note.v2.schema.json#/$defs/internalSectionId"},
                         rule["else"]["properties"]["section_semantics"]["additionalProperties"])
        for field, value, code in (
            ("scope", "unknown", "profile_scope_unknown"),
            ("source", 1, "profile_string_required:source"),
            ("section_semantics", [], "profile_section_semantics_required"),
            ("required_sections", "not a list", "profile_sections_required"),
        ):
            data = final_ready_payload()
            data["profile"][field] = value
            self.assert_contract_error(data, code)
        verification = self.comment_schema["$defs"]["verification"]
        self.assertEqual(["id", "clause_id", "source"], verification["required"])
        self.assertEqual(["planned", "performed", "reviewed", "not_applicable"],
                         verification["properties"]["status"]["enum"])
        fields = {"clause_hash", "method", "reason", "applicability_source",
                  "execution_evidence", "result_evidence", "review_evidence"}
        self.assertEqual(fields | {"status"}, set(verification["properties"]) - set(verification["required"]))
        for field in fields:
            self.assertEqual("string", verification["properties"][field]["type"])
            data = final_ready_payload()
            data["verification_matrix"][0][field] = []
            self.assert_contract_error(data, "verification_string_required:" + field)
        for field in verification["required"]:
            data = final_ready_payload()
            del data["verification_matrix"][0][field]
            self.assert_contract_error(data, "string_required:" + field)
        for state in ("planned", "performed", "reviewed", "not_applicable"):
            data = final_ready_payload()
            data["verification_matrix"][0].update(status=state, review_evidence="synthetic:review",
                reason="合成不适用记录", applicability_source="synthetic:applicability")
            out = standards.closed_loop(data)
            self.assertEqual(state != "planned", out["outcome_tally"]["closed"])
        data["verification_matrix"][0]["status"] = "unknown"
        self.assert_contract_error(data, "verification_status_unknown")

    def test_legacy_pending_string_is_not_a_v2_object_or_silent_migration(self):
        legacy_schema = json.loads((RESOURCE / "comment-disposition.schema.json").read_text(encoding="utf-8"))
        # v1表式schema与v1自由业务行原本不是同形结构；冻结它们，不假称identity迁移。
        self.assertEqual("dyz/standards/comment-disposition/v1", legacy_schema["$id"])
        self.assertEqual(["header", "items", "summary"], legacy_schema["required"])
        self.assertEqual("object", legacy_schema["$defs"]["openItem"]["type"])
        data = final_ready_payload()
        row = data["comment_outcomes"][0]
        row.pop("changes")
        row.update(outcome="pending", unresolved_item="补充原始记录", owner="组A")
        data["contract_version"] = 1
        legacy = standards.run("STD-09", data)
        self.assertEqual("legacy", legacy["artifacts"]["contract_mode"])
        self.assertEqual("补充原始记录", legacy["artifacts"]["comment_outcomes"][0]["unresolved_item"])
        data["contract_version"] = 2
        self.assert_contract_error(data, "open_item_object_required")
        row["unresolved_item"] = {"question": "补充原始记录", "owner": "组A",
                                  "blocks": "submission", "recovery": "取得原始记录"}
        out = standards.closed_loop(data)
        self.assertEqual(row, out["comment_outcomes"][0])
        self.assertNotIn("id", row["unresolved_item"])
        self.assertEqual("comment:COM-1", out["open_items"][0]["id"])
        self.assertEqual(["comment:COM-1"], out["open_items"][0]["source_refs"])
        self.assertFalse(out["outcome_tally"]["closed"])
        data["contract_version"] = 1
        with self.assertRaisesRegex(ContractError, "^comment_outcome_unresolved_item_required$"):
            standards.run("STD-09", data)


class ChangeTargetBoundaryTests(unittest.TestCase):
    @staticmethod
    def payload_for(operation, before, after):
        data = final_ready_payload()
        target = {**data["clauses"][0], "id": "C-TARGET"}
        if before:
            data["baseline_clauses"].append(copy.deepcopy(target))
        if after:
            data["clauses"].append(copy.deepcopy(target))
        data["comments"][0].pop("clause_id")
        data["comments"][0]["scope"] = "document"
        change = {"operation": operation, "clause_id": "C-TARGET"}
        if operation == "delete":
            change["dependency_resolution"] = {"status": "not_applicable", "reason": "合成无依赖"}
        else:
            change["proposed_text"] = target["text"]
        data["comment_outcomes"][0]["changes"] = [change]
        # 完整重绑其余记录，确保反例由目标关系本身而非陈旧hash触发。
        for index, clause in enumerate(data["clauses"], 1):
            clause["method_ids"] = [f"V{index}"]
        data["verification_matrix"] = [
            {**data["verification_matrix"][0], "id": f"V{index}", "clause_id": clause["id"],
             "clause_hash": digest(clause)} for index, clause in enumerate(data["clauses"], 1)]
        data["compilation_note"]["clause_digest"] = digest(data["clauses"])
        return standards_contract.confirm_comment(data, "COM-1", data["comment_outcomes"][0]["confirmation"])

    def test_operation_target_existence_truth_table(self):
        for operation in ("replace", "add", "delete"):
            for before, after in ((False, False), (False, True), (True, False), (True, True)):
                with self.subTest(operation=operation, before=before, after=after):
                    data = self.payload_for(operation, before, after)
                    out = standards.closed_loop(data)
                    valid = ((before and after) if operation == "replace" else
                             (not before and after) if operation == "add" else (before and not after))
                    expected = [] if valid else [{
                        "code": "comment_change_target_invalid", "record_id": "COM-1",
                        "clause_id": "C-TARGET", "operation": operation}]
                    self.assertEqual(expected, out["issues"])
                    self.assertEqual(valid, out["outcome_tally"]["closed"])
                    self.assertEqual(data["comment_outcomes"], out["comment_outcomes"])

    def test_one_invalid_target_does_not_hide_among_replace_add_delete(self):
        for invalid_operation in (None, "replace", "add", "delete"):
            with self.subTest(operation=invalid_operation):
                data = self.payload_for("add", False, True)
                deleted = {**data["baseline_clauses"][0], "id": "C-DELETE"}
                data["baseline_clauses"].append(deleted)
                changes = data["comment_outcomes"][0]["changes"]
                changes.extend([
                    {"operation": "replace", "clause_id": "C-1", "proposed_text": data["clauses"][0]["text"]},
                    {"operation": "delete", "clause_id": "C-DELETE", "dependency_resolution": {
                        "status": "resolved", "source": "synthetic:dependency-check"}},
                ])
                if invalid_operation:
                    change = next(row for row in changes if row["operation"] == invalid_operation)
                    change["clause_id"] = "MISSING"
                data = standards_contract.confirm_comment(data, "COM-1", data["comment_outcomes"][0]["confirmation"])
                out = standards.closed_loop(data)
                expected = [] if invalid_operation is None else [{
                    "code": "comment_change_target_invalid", "record_id": "COM-1",
                    "clause_id": "MISSING", "operation": invalid_operation}]
                self.assertEqual(expected, out["issues"])
                self.assertEqual(3, out["outcome_tally"]["clauses_touched"])
                self.assertEqual(invalid_operation is None, out["outcome_tally"]["closed"])
                self.assertEqual(changes, out["comment_outcomes"][0]["changes"])
        data["comment_outcomes"][0]["changes"].append(copy.deepcopy(changes[0]))
        with self.assertRaisesRegex(ContractError, "^duplicate_comment_change_target$"):
            standards.closed_loop(data)

    def test_missing_comment_target_is_not_confused_with_missing_change_target(self):
        data = final_ready_payload()
        data["comments"][0]["clause_id"] = "MISSING"
        data = standards_contract.confirm_comment(data, "COM-1", data["comment_outcomes"][0]["confirmation"])
        out = standards.closed_loop(data)
        self.assertEqual([{"code": "comment_clause_missing", "record_id": "COM-1"}], out["issues"])
        self.assertFalse(out["outcome_tally"]["closed"])
        self.assertEqual(data["comments"], out["comments"])

    def test_missing_targets_generate_five_draft_documents_without_false_realization(self):
        with tempfile.TemporaryDirectory(prefix="dyz-target-contract-") as folder:
            root = Path(folder)
            for operation in ("replace", "add", "delete"):
                with self.subTest(operation=operation):
                    data = self.payload_for(operation, False, False)
                    before = copy.deepcopy(data)
                    manifest = standards_delivery.prepare(root, data, operation, synthetic=True)
                    self.assertEqual("internal_draft_needs_evidence", manifest["delivery_state"])
                    self.assertEqual("needs_evidence", manifest["status"])
                    self.assertEqual(before, data)
                    self.assertIn({"code": "comment_change_target_invalid", "record_id": "COM-1",
                                   "clause_id": "C-TARGET", "operation": operation}, manifest["issues"])
                    self.assertEqual(5, len(list((root / operation / "body").glob("*.docx"))))
                    realizations = json.loads((root / operation / "internal/realizations.json").read_text(encoding="utf-8"))
                    self.assertEqual("needs_review", realizations[0]["status"])
                    self.assertEqual([{"clause_id": "C-TARGET", "operation": operation, "text_matches": False}],
                                     realizations[0]["changes"])
                    self.assertEqual(digest(data["comment_outcomes"][0]), realizations[0]["decision_hash"])
                    with zipfile.ZipFile(root / operation / "body/review_report.docx") as package:
                        tree = ET.fromstring(package.read("word/document.xml"))
                    text = "".join(node.text or "" for node in tree.iter(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
                    self.assertIn("comment_change_target_invalid", text)
                    self.assertIn("C-TARGET", text)
                    checked = standards_delivery.verify(root, data, operation, synthetic=True)
                    self.assertTrue(checked["file_hashes_equal"])
                    self.assertEqual("not_performed", manifest["professional_review"])


if __name__ == "__main__":
    unittest.main()
