"""AC-STD-01..12 的合成确定性测试，不是组织规则或专业签核验证。"""

import copy
import json
from pathlib import Path
import unittest

from tools.core import ContractError, digest
from tools.standards import CAPABILITIES, closed_loop, run
from evals.test_standards_closed_loop import final_ready_payload

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "standards" / "cases.json").read_text(encoding="utf-8"))


def payload(capability):
    data = copy.deepcopy(FIXTURE["common"])
    data.update(copy.deepcopy(FIXTURE["cases"][capability]))
    clause = copy.deepcopy(FIXTURE["clause"])
    if capability in {"STD-04", "STD-05", "STD-06", "STD-11", "STD-12"}:
        data["clauses"] = [clause]
    if capability == "STD-10":
        data["source_clauses"] = [clause]
        data["target_clauses"] = [copy.deepcopy(clause)]
        data["target_clauses"][0]["conditions"] = ["工作温度25摄氏度"]
    if capability == "STD-12":
        data["previous_clauses"] = [copy.deepcopy(clause)]
        data["clauses"][0]["conditions"] = ["工作温度25摄氏度"]
    return data


def measurement_payload(value=9, uncertainty=0.5):
    data = payload("STD-06")
    aspects = ("sampling", "environment", "equipment", "calibration", "uncertainty",
               "repeatability", "reproducibility", "boundary_rule")
    data["methods"][0].update({
        "kind": "measurement",
        "methodology": {name: {"status": "provided", "evidence": "synthetic-method-" + name} for name in aspects},
        "decision_rule": {"source": "synthetic-threshold", "operator": "le", "limit": 10,
                          "unit": "ms", "uncertainty_policy": "interval"},
    })
    data["results"] = [{"id": "RESULT-1", "method_id": "M-1", "value": value, "unit": "ms",
                        "uncertainty": uncertainty, "evidence_id": "synthetic-observation",
                        "execution_evidence": "synthetic-execution"}]
    return data


class StandardsContractTests(unittest.TestCase):
    def test_all_capabilities_have_substantive_artifacts_and_no_side_effect(self):
        expected = ("nodes", "scope_difference", "statements", "sections", "draft_markdown",
                    "matrix", "impacts", "protection_handoff", "dispositions", "comparisons",
                    "candidate_documents", "changes")
        for capability, key in zip(CAPABILITIES, expected):
            with self.subTest(ac=capability):
                data = payload(capability)
                original = copy.deepcopy(data)
                outcome = run(capability, data)
                self.assertTrue(outcome["artifacts"][key])
                self.assertEqual(data, original)
                self.assertEqual(outcome["capability"], capability)
                self.assertEqual(outcome["external_action"], "not_performed")
                self.assertEqual(outcome["professional_review"], "not_performed")
                self.assertEqual(outcome["official_status"], "not_asserted")
                self.assertIn(outcome["status"], {"needs_review", "needs_evidence"})
                json.dumps(outcome, allow_nan=False)

    def test_all_capabilities_reject_missing_adaptation(self):
        for capability in CAPABILITIES:
            with self.subTest(ac=capability):
                data = payload(capability)
                del data["adaptation"]["organization"]
                with self.assertRaisesRegex(ContractError, "missing:organization"):
                    run(capability, data)

    def test_all_capabilities_allow_explained_not_applicable(self):
        for capability in CAPABILITIES:
            with self.subTest(ac=capability):
                data = payload(capability)
                data.update(applicable=False, not_applicable_reason="合成案例不适用该任务")
                self.assertEqual(run(capability, data)["status"], "not_applicable")
                del data["not_applicable_reason"]
                with self.assertRaisesRegex(ContractError, "not_applicable_reason_required"):
                    run(capability, data)

    def test_all_capabilities_bind_changed_version_without_inheriting_review(self):
        for capability in CAPABILITIES:
            with self.subTest(ac=capability):
                data = payload(capability)
                first = run(capability, data)["artifacts"]["bindings"]
                data["previous_input_hash"] = first["input_hash"]
                self.assertEqual(run(capability, data)["artifacts"]["bindings"]["prior_review"], "not_inherited")
                data["version"] = "2"
                changed = run(capability, data)["artifacts"]["bindings"]
                self.assertNotEqual(first["input_hash"], changed["input_hash"])
                self.assertEqual(changed["prior_review"], "invalidated")

    def test_all_unknown_business_inputs_preserve_unreviewed_state(self):
        for capability in CAPABILITIES:
            with self.subTest(ac=capability):
                outcome = run(capability, copy.deepcopy(FIXTURE["common"]))
                self.assertNotEqual(outcome["status"], "checked")
                self.assertEqual(outcome["professional_review"], "not_performed")

    def test_unknown_capability_and_non_json_fail_closed(self):
        with self.assertRaisesRegex(ContractError, "unsupported_standard_capability"):
            run("STD-13", payload("STD-01"))
        data = payload("STD-01")
        data["value"] = float("nan")
        with self.assertRaisesRegex(ContractError, "not_canonical_json"):
            run("STD-01", data)


class StandardsAcceptanceTests(unittest.TestCase):
    def test_ac_std01_versions_replacements_and_permission_independent(self):
        outcome = run("STD-01", payload("STD-01"))["artifacts"]
        self.assertEqual(len(outcome["nodes"]), 2)
        self.assertEqual(outcome["nodes"][0]["fulltext"], "restricted")
        self.assertEqual(outcome["nodes"][1]["redistribution"], "unknown")
        self.assertEqual(outcome["edges"], [{"from": "S-2026", "to": "S-2020", "relation": "replaces"}])
        self.assertNotIn("fulltext_content", outcome)

    def test_ac_std01_zero_hits_not_network_failure(self):
        data = payload("STD-01")
        data["catalog"] = []
        data["search_log"][0]["status"] = "zero_hits"
        zero = run("STD-01", data)
        data["search_log"][0]["status"] = "network_error"
        failed = run("STD-01", data)
        self.assertEqual(zero["issues"], [])
        self.assertIn("search_incomplete", {i["code"] for i in failed["issues"]})

    def test_ac_std01_authorized_fulltext_requires_evidence(self):
        data = payload("STD-01")
        del data["catalog"][1]["access"]["authority_evidence"]
        with self.assertRaisesRegex(ContractError, "fulltext_authority_required"):
            run("STD-01", data)

    def test_ac_std02_difference_is_not_project_approval(self):
        outcome = run("STD-02", payload("STD-02"))["artifacts"]
        self.assertEqual(outcome["scope_difference"][0]["new_features"], ["clock-validation"])
        self.assertEqual(outcome["scope_difference"][0]["covered_features"], ["timestamp"])
        self.assertIn("记录时间并校验时钟", outcome["proposal_markdown"])
        self.assertEqual(outcome["project_approval"], "not_asserted")

    def test_ac_std03_duplicates_preserve_provenance_conflicts_and_categories(self):
        outcome = run("STD-03", payload("STD-03"))["artifacts"]
        self.assertEqual(len(outcome["statements"]), 4)
        self.assertEqual(outcome["duplicate_groups"][0]["statement_ids"], ["O-1", "O-2"])
        self.assertEqual(outcome["conflicts"], ["P-1"])
        self.assertEqual({s["category"] for s in outcome["statements"]}, {"fact", "opinion", "hypothesis"})
        self.assertEqual(outcome["consensus"], "not_inferred")

    def test_ac_std03_missing_authority_and_group_reported(self):
        data = payload("STD-03")
        data["participants"] = []
        outcome = run("STD-03", data)
        self.assertIn("representative_authority_unproven", {i["code"] for i in outcome["issues"]})
        self.assertEqual(outcome["artifacts"]["missing_groups"], ["producer", "user"])

    def test_ac_std04_three_effect_layers(self):
        outcome = run("STD-04", payload("STD-04"))["artifacts"]
        self.assertEqual(outcome["effects"]["clause_strengths"][0]["strength"], "requirement")
        self.assertEqual(outcome["effects"]["standard_nature"]["value"], "voluntary")
        self.assertEqual(outcome["effects"]["external_obligations"][0]["scope"], "synthetic-procurement-only")
        self.assertEqual(outcome["effects"]["universal_legal_obligation"], "not_inferred")
        self.assertEqual(outcome["sections"][1]["kind"], "informative")

    def test_ac_std04_informative_requirements_and_term_conflicts_flagged(self):
        data = payload("STD-04")
        data["clauses"][0]["kind"] = "informative"
        data["terms"].append({**data["terms"][0], "id": "TERM-2", "definition": "另一不同定义"})
        codes = {i["code"] for i in run("STD-04", data)["issues"]}
        self.assertEqual(codes, {"informative_requirement", "conflicting_term_definitions"})

    def test_ac_std05_editable_draft_preserves_conditions_exception_quantity(self):
        outcome = run("STD-05", payload("STD-05"))["artifacts"]
        for text in ("C-1", "维护模式除外", "工作温度20摄氏度", "10 ms", "容差：1"):
            self.assertIn(text, outcome["draft_markdown"])
        self.assertEqual(outcome["clauses"][0]["strength"], "requirement")

    def test_ac_std05_semantic_edits_invalidate_reviews_but_renumber_keeps_id(self):
        data = payload("STD-05")
        data["previous_clauses"] = copy.deepcopy(data["clauses"])
        data["clauses"][0]["number"] = "9"
        self.assertEqual(run("STD-05", data)["artifacts"]["semantic_changes"], [])
        data["clauses"][0]["strength"] = "permission"
        changed = run("STD-05", data)["artifacts"]
        self.assertEqual(changed["semantic_changes"][0]["fields"], ["strength"])
        self.assertEqual(changed["invalidated_reviews"][0]["clause_id"], "C-1")
        self.assertFalse(changed["automatic_semantic_edit"])

    def test_ac_std05_unbased_quantity_and_duplicate_id_rejected(self):
        data = payload("STD-05")
        del data["clauses"][0]["quantities"][0]["source"]
        with self.assertRaisesRegex(ContractError, "missing:source"):
            run("STD-05", data)
        data = payload("STD-05")
        data["clauses"].append(copy.deepcopy(data["clauses"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate_record_id"):
            run("STD-05", data)

    def test_ac_std06_plan_is_not_execution_or_certification(self):
        row = run("STD-06", payload("STD-06"))["artifacts"]["matrix"][0]
        self.assertEqual(row["kind"], "document_review")
        self.assertEqual(row["execution"], "not_provided")
        self.assertEqual(row["results"], [])
        self.assertEqual(row["conformity"], "not_determined")
        self.assertEqual(row["certification"], "not_performed")

    def test_ac_std06_interval_boundary_is_rule_driven(self):
        for value, uncertainty, expected in ((9, 0.5, "within_rule"), (10, 0.5, "indeterminate"),
                                             (11, 0.5, "outside_rule"), (10, 0, "within_rule")):
            with self.subTest(value=value, uncertainty=uncertainty):
                row = run("STD-06", measurement_payload(value, uncertainty))["artifacts"]["matrix"][0]
                self.assertEqual(row["comparisons"][0]["machine_comparison"], expected)
                self.assertEqual(row["conformity"], "not_determined")

    def test_ac_std06_missing_rule_or_uncertainty_never_passes(self):
        for missing in ("decision_rule", "uncertainty", "calibration"):
            with self.subTest(missing=missing):
                data = measurement_payload()
                if missing == "decision_rule":
                    data["methods"][0].pop("decision_rule")
                elif missing == "uncertainty":
                    data["results"][0].pop("uncertainty")
                else:
                    data["methods"][0]["methodology"].pop("calibration")
                outcome = run("STD-06", data)
                self.assertTrue(outcome["issues"])
                self.assertEqual(outcome["artifacts"]["matrix"][0]["comparisons"][0]["machine_comparison"], "not_evaluated")

    def test_ac_std06_na_aspect_needs_reason_and_unit_mismatch_blocks(self):
        data = measurement_payload()
        data["methods"][0]["methodology"]["reproducibility"] = {"status": "not_applicable", "reason": "合成单次文稿算法案例"}
        self.assertEqual(run("STD-06", data)["issues"], [])
        data["results"][0]["unit"] = "s"
        self.assertIn("unit_mismatch", run("STD-06", data)["artifacts"]["matrix"][0]["blockers"])

    def test_ac_std07_dated_reference_kept_and_impact_traced(self):
        outcome = run("STD-07", payload("STD-07"))["artifacts"]
        impact = outcome["impacts"][0]
        self.assertEqual(outcome["references"][0]["edition"], "2020")
        self.assertEqual(impact["candidate_edition"], "2026")
        self.assertFalse(impact["automatic_upgrade"])
        self.assertEqual(impact["products"], ["product-1"])
        self.assertEqual(impact["conclusions"], ["conclusion-1"])

    def test_ac_std08_application_number_and_sep_never_authorize(self):
        outcome = run("STD-08", payload("STD-08"))["artifacts"]
        protection, rights = outcome["protection_handoff"], outcome["rights_handoff"]
        self.assertEqual(protection["public_route"], "blocked")
        self.assertEqual(len(protection["support"]), 2)
        self.assertEqual(rights["license_granted"], "not_inferred")
        self.assertEqual(rights["fto"], "not_determined")
        self.assertNotEqual(protection["targets"], rights["targets"])

    def test_ac_std08_complete_support_still_requires_shared_gate(self):
        data = payload("STD-08")
        data["support_mappings"] = [dict(id="MAP-" + region, content_id="CONTENT-1", jurisdiction=region,
                                        status="supported", application_document_hash="synthetic-hash",
                                        locator="synthetic-file#paragraph-1", date_evidence="synthetic-date",
                                        review_evidence="synthetic-review", reviewer_authority="synthetic-authority")
                                    for region in ("CN", "US")]
        outcome = run("STD-08", data)["artifacts"]
        self.assertEqual(outcome["protection_handoff"]["public_route"], "requires_core_disclosure_approval")
        self.assertEqual(outcome["external_action"], "not_performed")

    def test_ac_std08_public_no_protection_goal_is_explicit_na(self):
        data = payload("STD-08")
        data["contents"][0].update(protection_required=False, not_applicable_reason="合成已公开材料", public_evidence="synthetic-public-source")
        self.assertEqual(run("STD-08", data)["artifacts"]["protection_handoff"]["support"][0]["status"], "not_applicable")

    def test_ac_std09_minorities_quorum_major_change_and_appeal_retained(self):
        outcome = run("STD-09", payload("STD-09"))["artifacts"]
        self.assertEqual(len(outcome["dispositions"]), 2)
        self.assertTrue(outcome["dispositions"][0]["minority_retained"])
        self.assertEqual(outcome["duplicate_groups"], [["COM-1", "COM-2"]])
        self.assertEqual(outcome["ballot_assessment"], "numeric_conditions_not_met")
        self.assertEqual(outcome["major_change_review"][0]["action"], "reconsultation_required")
        self.assertEqual(outcome["appeals"][0]["status"], "pending")
        self.assertEqual(outcome["consensus"], "not_inferred")

    def test_ac_std09_numeric_quorum_not_approval_and_duplicate_votes_rejected(self):
        data = payload("STD-09")
        data["votes"].append({"id": "V-2", "participant_id": "P-2", "choice": "yes", "evidence_id": "synthetic-vote-2"})
        outcome = run("STD-09", data)["artifacts"]
        self.assertEqual(outcome["ballot_assessment"], "numeric_conditions_met")
        self.assertEqual(outcome["organization_approval"], "not_asserted")
        data["votes"].append({**data["votes"][0], "id": "V-3"})
        with self.assertRaisesRegex(ContractError, "duplicate_participant_vote"):
            run("STD-09", data)

    def test_ac_std09_missing_rule_does_not_assume_threshold(self):
        data = payload("STD-09")
        del data["ballot_rule"]
        self.assertEqual(run("STD-09", data)["artifacts"]["ballot_assessment"], "unknown")

    def test_ac_std10_same_words_changed_conditions_not_idt(self):
        outcome = run("STD-10", payload("STD-10"))["artifacts"]
        self.assertEqual(outcome["comparisons"][0]["technical_differences"], ["conditions"])
        self.assertEqual(outcome["adoption_relationship"], "not_determined")
        self.assertFalse(outcome["translation_is_idt"])

    def test_ac_std10_translation_permission_and_unmapped_clauses_reported(self):
        data = payload("STD-10")
        data["translation_permission"] = {}
        data["mappings"] = []
        codes = {i["code"] for i in run("STD-10", data)["issues"]}
        self.assertEqual(codes, {"translation_permission_unproven", "unmapped_adoption_clauses"})

    def test_ac_std11_candidate_separates_risks_and_cannot_claim_approval(self):
        outcome = run("STD-11", payload("STD-11"))["artifacts"]
        self.assertEqual([d["id"] for d in outcome["candidate_documents"]], ["DOC-1"])
        self.assertEqual([d["id"] for d in outcome["internal_documents"]], ["DOC-2"])
        self.assertEqual(outcome["candidate_status"], "needs_evidence")
        self.assertEqual(outcome["organization_approval"], "not_asserted")
        self.assertEqual(outcome["submission"], "not_performed")

    def test_ac_std11_machine_or_stale_review_cannot_satisfy_independent_review(self):
        data = payload("STD-11")
        for actor, content_hash in (("machine", digest(data["clauses"])), ("human", "stale")):
            with self.subTest(actor=actor):
                data["reviews"] = [{"id": "REV-1", "reviewer": "synthetic-reviewer", "source": "synthetic-review",
                                    "actor_type": actor, "authority_evidence": "synthetic-authority", "content_hash": content_hash}]
                codes = {i["code"] for i in run("STD-11", data)["issues"]}
                self.assertIn("independent_review_unproven_or_stale", codes)

    def test_ac_std12_changed_condition_traces_reference_product_conclusion(self):
        outcome = run("STD-12", payload("STD-12"))["artifacts"]
        self.assertEqual(outcome["changes"][0]["fields"], ["conditions"])
        self.assertEqual({i["kind"] for i in outcome["impacts"]}, {"reference", "product", "conformity_conclusion"})
        self.assertEqual(outcome["disclosure_reassessment"], ["C-1"])
        self.assertEqual(outcome["effective_status"], "not_asserted")
        self.assertEqual(outcome["history_preserved"][0]["conditions"], ["工作温度20摄氏度"])

    def test_ac_std12_unchanged_clauses_keep_old_conclusions(self):
        data = payload("STD-12")
        data["clauses"] = copy.deepcopy(data["previous_clauses"])
        outcome = run("STD-12", data)["artifacts"]
        self.assertEqual(outcome["impacts"], [])
        self.assertEqual(outcome["review_invalidation"], [])
        self.assertEqual(outcome["disclosure_reassessment"], [])


class StandardsBallotGovernanceTests(unittest.TestCase):
    def ballot_payload(self):
        data = payload("STD-09")
        for field in ("comments", "decisions", "comment_outcomes", "modifications", "appeals"):
            data[field] = []
        data["votes"].append({"id": "V-2", "participant_id": "P-2", "choice": "yes",
                              "evidence_id": "synthetic-vote-2"})
        for vote in data["votes"]:
            vote["version"] = data["version"]
        return data

    def add_unproven_vote(self, data):
        data["participants"].append({"id": "P-3"})
        data["votes"].append({"id": "V-3", "participant_id": "P-3", "choice": "yes",
                              "evidence_id": "synthetic-vote-3"})

    def test_legacy_numeric_result_does_not_bind_missing_vote_versions(self):
        data = self.ballot_payload()
        for vote in data["votes"]:
            del vote["version"]
        original = copy.deepcopy(data)
        outcome = run("STD-09", data)
        artifacts = outcome["artifacts"]
        self.assertEqual(artifacts["ballot_assessment"], "numeric_conditions_met")
        self.assertEqual(artifacts["valid_vote_counts"], {"yes": 2, "no": 0, "abstain": 0})
        review = artifacts.get("ballot_governance", {})
        self.assertEqual(review.get("status"), "unknown")
        self.assertEqual(review["same_version_status"], "unknown")
        self.assertEqual(review["qualified_same_version_vote_counts"], {"yes": 0, "no": 0, "abstain": 0})
        self.assertIn("vote_version_unproven", {issue["code"] for issue in outcome["issues"]})
        self.assertEqual(data, original)

    def test_numeric_met_with_both_qualification_and_version_unknown(self):
        data = self.ballot_payload()
        self.add_unproven_vote(data)
        artifacts = run("STD-09", data)["artifacts"]
        self.assertEqual(artifacts["ballot_assessment"], "numeric_conditions_met")
        review = artifacts.get("ballot_governance", {})
        self.assertEqual(review.get("status"), "unknown")
        self.assertEqual(review["eligibility_status"], "unknown")
        self.assertEqual(review["same_version_status"], "unknown")
        self.assertEqual(review["qualified_same_version_vote_counts"]["yes"], 2)
        self.assertEqual(review["vote_checks"][-1]["status"], "unknown")
        self.assertEqual(artifacts["organization_approval"], "not_asserted")

    def test_qualification_only_missing_does_not_invalidate_known_version(self):
        data = self.ballot_payload()
        self.add_unproven_vote(data)
        data["votes"][-1]["version"] = data["version"]
        artifacts = run("STD-09", data)["artifacts"]
        self.assertEqual(artifacts["ballot_assessment"], "numeric_conditions_met")
        review = artifacts.get("ballot_governance", {})
        self.assertEqual(review.get("status"), "unknown")
        self.assertEqual(review["eligibility_status"], "unknown")
        self.assertEqual(review["same_version_status"], "valid")

    def test_version_only_missing_keeps_provided_qualification(self):
        for value in (None, "", "   "):
            with self.subTest(version=value):
                data = self.ballot_payload()
                data["votes"][0]["version"] = value
                artifacts = run("STD-09", data)["artifacts"]
                self.assertEqual(artifacts["ballot_assessment"], "numeric_conditions_met")
                review = artifacts.get("ballot_governance", {})
                self.assertEqual(review.get("status"), "unknown")
                self.assertEqual(review["eligibility_status"], "valid")
                self.assertEqual(review["same_version_status"], "unknown")
                self.assertEqual(review["qualified_same_version_vote_counts"]["yes"], 1)

    def test_explicitly_ineligible_vote_is_invalid_even_when_numeric_met(self):
        data = self.ballot_payload()
        self.add_unproven_vote(data)
        data["participants"][-1]["eligible"] = False
        data["votes"][-1]["version"] = data["version"]
        outcome = run("STD-09", data)
        artifacts = outcome["artifacts"]
        self.assertEqual(artifacts["ballot_assessment"], "numeric_conditions_met")
        review = artifacts.get("ballot_governance", {})
        self.assertEqual(review.get("status"), "invalid")
        self.assertEqual(review["eligibility_status"], "invalid")
        self.assertEqual(review["same_version_status"], "valid")
        self.assertEqual(review["vote_checks"][-1]["status"], "invalid")
        self.assertEqual(len(artifacts["votes"]), 3)
        self.assertIn("vote_ineligible", {issue["code"] for issue in outcome["issues"]})

    def test_explicit_version_mismatch_overrides_other_unknown_without_erasing_it(self):
        data = self.ballot_payload()
        data["votes"][0]["version"] = "old-version"
        self.add_unproven_vote(data)
        outcome = run("STD-09", data)
        artifacts = outcome["artifacts"]
        self.assertEqual(artifacts["ballot_assessment"], "numeric_conditions_met")
        review = artifacts.get("ballot_governance", {})
        self.assertEqual(review.get("status"), "invalid")
        self.assertEqual(review["eligibility_status"], "unknown")
        self.assertEqual(review["same_version_status"], "invalid")
        self.assertEqual(review["qualified_same_version_vote_counts"]["yes"], 1)
        self.assertEqual(review["vote_checks"][0]["version"], "old-version")
        self.assertEqual(review["vote_checks"][-1]["same_version_status"], "unknown")
        self.assertIn("vote_version_mismatch", {issue["code"] for issue in outcome["issues"]})

    def test_complete_records_are_internal_checks_only(self):
        data = self.ballot_payload()
        outcome = run("STD-09", data)
        artifacts = outcome["artifacts"]
        review = artifacts.get("ballot_governance", {})
        self.assertEqual(review.get("status"), "internal_checks_met")
        self.assertEqual(review["scope"], "internal_records_only")
        self.assertEqual(review["version"], data["version"])
        self.assertEqual(review["eligibility_status"], "valid")
        self.assertEqual(review["same_version_status"], "valid")
        self.assertEqual(review["qualified_same_version_vote_counts"], artifacts["valid_vote_counts"])
        self.assertEqual(outcome["issues"], [])
        self.assertEqual(outcome["status"], "needs_review")
        self.assertEqual(artifacts["organization_approval"], "not_asserted")
        self.assertEqual(artifacts["consensus"], "not_inferred")
        self.assertEqual(outcome["professional_review"], "not_performed")
        data["version"] = "2"
        self.assertEqual(run("STD-09", data)["artifacts"]["ballot_governance"]["status"], "invalid")

    def test_complete_records_preserve_numeric_failure_and_missing_rule(self):
        for field, value, numeric, governance in (
                ("min_votes", 3, "numeric_conditions_not_met", "internal_checks_not_met"),
                ("source", "", "unknown", "unknown")):
            with self.subTest(field=field):
                data = self.ballot_payload()
                data["ballot_rule"][field] = value
                artifacts = run("STD-09", data)["artifacts"]
                self.assertEqual(artifacts["ballot_assessment"], numeric)
                self.assertEqual(artifacts.get("ballot_governance", {}).get("status"), governance)

    def test_truthy_authority_is_not_evidence_but_legacy_counts_stay_unchanged(self):
        for authority in (True, "   ", {"provided": True}):
            with self.subTest(authority=authority):
                data = self.ballot_payload()
                data["participants"][0]["authority_evidence"] = authority
                artifacts = run("STD-09", data)["artifacts"]
                self.assertEqual(artifacts["ballot_assessment"], "numeric_conditions_met")
                review = artifacts.get("ballot_governance", {})
                self.assertEqual(review.get("status"), "unknown")
                self.assertEqual(review["qualified_same_version_vote_counts"]["yes"], 1)

    def test_eligible_denominator_requires_nonvoter_qualification_records(self):
        data = self.ballot_payload()
        data["participants"].append({"id": "P-3"})
        artifacts = run("STD-09", data)["artifacts"]
        self.assertEqual(artifacts["ballot_assessment"], "numeric_conditions_met")
        review = artifacts.get("ballot_governance", {})
        self.assertEqual(review.get("status"), "unknown")
        self.assertEqual(review["denominator_eligibility_status"], "unknown")
        data["participants"][-1]["eligible"] = False
        self.assertEqual(run("STD-09", data)["artifacts"]["ballot_governance"]["status"], "internal_checks_met")
        del data["participants"][-1]["eligible"]
        data["ballot_rule"]["denominator"] = "cast"
        self.assertEqual(run("STD-09", data)["artifacts"]["ballot_governance"]["status"], "internal_checks_met")

    def test_no_votes_does_not_vacuously_prove_qualification_or_same_version(self):
        data = self.ballot_payload()
        data["votes"] = []
        review = run("STD-09", data)["artifacts"].get("ballot_governance", {})
        self.assertEqual(review.get("status"), "unknown")
        self.assertEqual(review["eligibility_status"], "unknown")
        self.assertEqual(review["same_version_status"], "unknown")


class StandardsClosedLoopBallotTests(StandardsBallotGovernanceTests):
    """同一组资格/同版反例必须经v2入口成立，不能回退到旧意见结构。"""

    def ballot_payload(self):
        data = final_ready_payload()
        legacy = super().ballot_payload()
        data.update({key: legacy[key] for key in ("participants", "votes", "ballot_rule")})
        for vote in data["votes"]:
            vote["version"] = data["version"]
        return data

    def test_no_ballot_inputs_does_not_invent_missing_ballot(self):
        data = final_ready_payload()
        baseline = closed_loop(data)
        data["participants"] = [{"id": "P-1"}]
        outcome = closed_loop(data)
        self.assertEqual(outcome["issues"], baseline["issues"])
        for key in ("votes", "valid_vote_counts", "ballot_rule", "ballot_assessment", "ballot_governance"):
            self.assertNotIn(key, outcome)
        self.assertNotIn("organization_ballot_rule_missing", {i["code"] for i in outcome["issues"]})

    def test_explicit_empty_ballot_inputs_request_an_unknown_review(self):
        for key, value in (("votes", []), ("ballot_rule", {})):
            with self.subTest(field=key):
                data = final_ready_payload()
                data[key] = value
                outcome = closed_loop(data)
                self.assertEqual(outcome.get("ballot_governance", {}).get("status"), "unknown")
                self.assertEqual(outcome["ballot_assessment"], "unknown")
                self.assertIn("organization_ballot_rule_missing", {i["code"] for i in outcome["issues"]})
                self.assertFalse(outcome["outcome_tally"]["closed"])

    def test_direct_closed_loop_has_same_governance_and_preserves_input(self):
        data = self.ballot_payload()
        before = copy.deepcopy(data)
        direct = closed_loop(data)
        wrapped = run("STD-09", data)["artifacts"]
        for key in ("participants", "votes", "valid_vote_counts", "ballot_rule",
                    "ballot_assessment", "ballot_governance"):
            self.assertIn(key, direct)
            self.assertEqual(direct[key], wrapped[key])
        direct["votes"][0]["version"] = "changed-output"
        direct["participants"][0]["eligible"] = False
        direct["ballot_rule"]["source"] = "changed-output"
        self.assertEqual(data, before)

    def test_document_scope_comment_does_not_enter_legacy_governance(self):
        data = self.ballot_payload()
        del data["comments"][0]["clause_id"]
        data["comments"][0]["scope"] = "document"
        outcome = closed_loop(data)
        self.assertEqual(outcome.get("ballot_governance", {}).get("status"), "internal_checks_met")
        self.assertEqual(outcome["comments"][0]["scope"], "document")
        self.assertNotIn("comment_disposition_missing", {i["code"] for i in outcome["issues"]})
        self.assertNotIn("dispositions", outcome)

    def test_v2_ballot_invalid_shapes_and_duplicate_participants_are_rejected(self):
        for field, value, error in (("participants", {}, "records_list_required"),
                                     ("votes", {}, "records_list_required"),
                                     ("ballot_rule", [], "ballot_rule_object_required")):
            with self.subTest(field=field):
                data = self.ballot_payload()
                data[field] = value
                with self.assertRaisesRegex(ContractError, error):
                    closed_loop(data)
        data = self.ballot_payload()
        data["votes"][0]["version"] = 2
        with self.assertRaisesRegex(ContractError, "vote_version_string_required"):
            closed_loop(data)
        data = self.ballot_payload()
        data["votes"].append({**data["votes"][0], "id": "V-3"})
        with self.assertRaisesRegex(ContractError, "duplicate_participant_vote"):
            closed_loop(data)

    def test_v2_schema_declares_only_consumed_ballot_fields(self):
        path = Path(__file__).resolve().parents[1] / "skills/dyz-standards/resources/lifecycle/comment-disposition.v2.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        for field, definition in (("participants", "ballotParticipant"), ("votes", "vote")):
            with self.subTest(field=field):
                self.assertIn(field, schema["properties"])
                self.assertEqual(schema["properties"][field]["type"], "array")
                self.assertEqual(schema["properties"][field]["items"], {"$ref": "#/$defs/" + definition})
        self.assertEqual(schema["properties"]["ballot_rule"], {"$ref": "#/$defs/ballotRule"})
        vote = schema["$defs"]["vote"]
        self.assertEqual(vote["required"], ["id", "participant_id", "choice", "evidence_id"])
        self.assertEqual(vote["properties"]["version"]["type"], ["string", "null"])
        self.assertNotIn("version", vote["required"])
        self.assertEqual(vote["properties"]["choice"]["enum"], ["yes", "no", "abstain"])


class StandardsBoundaryTests(unittest.TestCase):
    def test_review_rejection_cannot_prepare_candidate(self):
        data = payload("STD-11")
        data["required_document_roles"] = ["draft"]
        clause = data["clauses"][0]
        data["verification_matrix"] = [{"id": "MATRIX-1", "clause_id": "C-1", "source": "synthetic-matrix",
                                        "result_evidence": "synthetic-result", "review_evidence": "synthetic-review",
                                        "clause_hash": digest(clause)}]
        data["reviews"] = [{"id": "REV-1", "reviewer": "synthetic-human", "source": "synthetic-review",
                            "actor_type": "human", "authority_evidence": "synthetic-authority",
                            "content_hash": digest(data["clauses"]), "decision": "rejected"}]
        outcome = run("STD-11", data)
        self.assertEqual(outcome["artifacts"]["candidate_status"], "needs_evidence")
        self.assertIn("independent_review_unproven_or_stale", {i["code"] for i in outcome["issues"]})

    def test_stale_verification_matrix_cannot_cover_changed_clause(self):
        data = payload("STD-11")
        data["verification_matrix"] = [{"id": "MATRIX-1", "clause_id": "C-1", "source": "synthetic-matrix",
                                        "result_evidence": "synthetic-result", "review_evidence": "synthetic-review",
                                        "clause_hash": "old-hash"}]
        self.assertIn("required_verification_missing", {i["code"] for i in run("STD-11", data)["issues"]})

    def test_matrix_does_not_silently_replace_declared_method(self):
        data = payload("STD-06")
        data["clauses"][0]["method_ids"] = ["OTHER-METHOD"]
        codes = {i["code"] for i in run("STD-06", data)["issues"]}
        self.assertIn("declared_verification_method_missing", codes)

    def test_empty_ip_request_cannot_look_complete(self):
        data = copy.deepcopy(FIXTURE["common"])
        outcome = run("STD-08", data)
        self.assertEqual(outcome["artifacts"]["protection_handoff"]["public_route"], "blocked")
        self.assertIn("disclosure_contents_missing", {i["code"] for i in outcome["issues"]})

    def test_major_change_without_rule_source_stays_pending(self):
        data = payload("STD-09")
        del data["major_change_rule"]["source"]
        action = run("STD-09", data)["artifacts"]["major_change_review"][0]["action"]
        self.assertEqual(action, "organization_decision_required")

    def test_dispute_closure_requires_evidence(self):
        data = payload("STD-03")
        data["disputes"] = [{"id": "D-1", "source": "synthetic-dispute", "status": "resolved_with_evidence"}]
        self.assertIn("unresolved_dispute", {i["code"] for i in run("STD-03", data)["issues"]})

    def test_common_input_types_rejected(self):
        for field, value in (("evidence_ids", "not-a-list"), ("applicable", "false")):
            with self.subTest(field=field):
                data = payload("STD-01")
                data[field] = value
                with self.assertRaises(ContractError):
                    run("STD-01", data)

    def test_major_change_rule_object_rejected_as_contract_error(self):
        data = payload("STD-09")
        data["major_change_rule"] = []
        with self.assertRaises(ContractError):
            run("STD-09", data)

    def test_deadlines_have_standard_ownership_and_missing_evidence_state(self):
        data = payload("STD-09")
        data["deadlines"] = [{"business": "standard", "event_id": "EV-1", "owner": "synthetic-secretariat",
                              "rule_id": "synthetic-date-rule"}]
        outcome = run("STD-09", data)["artifacts"]
        self.assertEqual(outcome["deadline_checks"][0]["status"], "needs_evidence")
        self.assertEqual(outcome["deadline_checks"][0]["artifacts"]["rule_owner"], "STD-09/11")


if __name__ == "__main__":
    unittest.main()
