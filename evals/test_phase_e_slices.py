"""Phase E tests: US/EP jurisdiction analyzers, Procedure no-go/FTO/SEP strategy tools,
and multimodal visual coverage ledger.
"""
import unittest

from tools import jurisdiction_analyzers, procedure_strategy, visual_ledger
from tools.core import ContractError


class JurisdictionAnalyzersTests(unittest.TestCase):
    def test_us_claims_antecedent_112e_112f_and_101_checks(self):
        claims = [
            {"id": 1, "text": "A controller comprising a sensor configured to sample temperature and substantially adjust the valve."},
            {"id": 2, "parent_ids": [1], "text": "The controller of claim 1, further comprising means for scoring events using the sensor."},
            {"id": 3, "parent_ids": [1, 2], "text": "The controller of claim 1 or 2, wherein the sensor updates the timer."},
            {"id": 4, "parent_ids": [2, 3], "text": "The controller of claim 2 or 3, further comprising a display."},
        ]
        res = jurisdiction_analyzers.analyze_us_claims(claims)
        self.assertEqual("blocked", res["status"])
        issue_codes = [i["code"] for i in res["issues"]]
        warn_codes = [w["code"] for w in res["warnings"]]
        # Claim 1 uses "the valve" without introducing "a valve"
        self.assertIn("us_112b_missing_antecedent_basis", issue_codes)
        # Claim 4 depends on multiple dependent claim 3 -> 35 U.S.C. 112(e)
        self.assertIn("us_112e_multiple_dependent_on_multiple_dependent", issue_codes)
        self.assertIn("us_112b_relative_term_needs_spec_anchor", warn_codes)
        self.assertIn("us_112f_functional_claiming_verify_structure", warn_codes)
        self.assertIn("us_101_alice_mayo_eligibility_review_required", warn_codes)
        self.assertEqual("not_determined", res["legal_conclusion"])
        self.assertTrue(len(res["checks_skipped"]) >= 2)

    def test_ep_claims_two_part_exception_and_art123_2_intermediate_generalisation(self):
        embodiments = [{
            "id": "EMB-1",
            "features": ["F_sensor", "F_filter", "F_valve", "F_stop"],
            "functionally_linked_groups": [["F_filter", "F_valve"]],
        }]
        # 1) Taking F_filter without coupled F_valve -> Art. 123(2) intermediate generalisation!
        bad = jurisdiction_analyzers.analyze_ep_claims(
            [{"id": 1, "text": "A device comprising a sensor and a filter.",
              "two_part_not_appropriate_reason": "Single integrated architecture where separation would distort clarity.",
              "feature_ids": ["F_sensor", "F_filter"]}],
            original_embodiments=embodiments,
        )
        self.assertEqual("blocked", bad["status"])
        self.assertIn("ep_art123_2_intermediate_generalisation", [i["code"] for i in bad["issues"]])
        # Two-part exception was properly recorded, so NO Rule 43(1) warning!
        self.assertEqual([], bad["warnings"])

        # 2) Taking full coupled group [F_filter, F_valve] passes finite check (still needs_review overall)
        ok = jurisdiction_analyzers.analyze_ep_claims(
            [{"id": 1, "text": "A device comprising a sensor, characterized in that a filter drives a valve.",
              "feature_ids": ["F_sensor", "F_filter", "F_valve"]}],
            original_embodiments=embodiments,
        )
        self.assertEqual("needs_review", ok["status"])
        self.assertEqual("checked_finite_feature_set", ok["claims"][0]["art123_2_check"])

    def test_us_indirect_multiple_dependency(self):
        result = jurisdiction_analyzers.analyze_us_claims([
            {"id": 5, "parent_ids": [4, 1], "text": "A device."},
            {"id": 4, "parent_ids": [3], "text": "A device."},
            {"id": 3, "parent_ids": [1, 2], "text": "A device."},
            {"id": 2, "text": "A device."},
            {"id": 1, "text": "A device."},
        ])
        self.assertEqual([1, 2, 3, 4, 5], [row["claim_id"] for row in result["claims"]])
        self.assertEqual([3], result["claims"][3]["parent_ids"])
        self.assertEqual([("us_112e_multiple_dependent_on_multiple_dependent", 5, 4)], [
            (issue["code"], issue["claim_id"], issue["parent_id"]) for issue in result["issues"]
        ])

    def test_us_antecedents_stop_at_predicates_without_hiding_missing_ordinal(self):
        result = jurisdiction_analyzers.analyze_us_claims([
            {"id": 1, "text": "A controller comprising a valve and a pump configured to run."},
            {"id": 2, "parent_ids": [1], "text": "The controller of claim 1, wherein the valve configured to open is biased by the pump."},
            {"id": 3, "parent_ids": [2], "text": "The controller of claim 2, wherein the second valve is closed."},
        ])
        self.assertEqual([], result["claims"][1]["missing_antecedents"])
        self.assertEqual(["second valve"], result["claims"][2]["missing_antecedents"])

    def test_us_antecedents_require_each_branch_and_prior_introduction(self):
        result = jurisdiction_analyzers.analyze_us_claims([
            {"id": 1, "text": "A device comprising a first\nsensor, a valve and a pressure sensor."},
            {"id": 2, "text": "A device comprising a first sensor and a pump."},
            {"id": 3, "parent_ids": [1, 2], "text": "The first sensor signals. The valve closes."},
            {"id": 4, "parent_ids": [1], "text": "The valve closes. The temperature sensor is sampled."},
            {"id": 5, "text": "The timer is reset; a timer is installed; the timer counts."},
            {"id": 6, "parent_ids": [3], "text": "The valve closes. The first sensor signals."},
            {"id": 7, "text": "A controller comprising a pressure sensor; the pressure sensor calibrates."},
        ])
        self.assertEqual([[], [], ["valve"], ["temperature sensor"], ["timer"], ["valve"], []],
                         [row["missing_antecedents"] for row in result["claims"]])

    def test_us_101_cues_match_words_not_substrings(self):
        result = jurisdiction_analyzers.analyze_us_claims([
            {"id": 1, "text": "A device for underscoring tokens."},
            {"id": 2, "text": "A device for scoring events."},
        ])
        self.assertEqual([[], ["scoring"]], [row["flags_101"] for row in result["claims"]])

    def test_ep_claim_uses_transitive_inherited_feature_combination(self):
        result = jurisdiction_analyzers.analyze_ep_claims([
            {"id": 3, "text": "A device.", "parent_ids": [2], "feature_ids": ["F3"]},
            {"id": 2, "text": "A device.", "parent_ids": [1], "feature_ids": ["F2"]},
            {"id": 1, "text": "A device.", "feature_ids": ["F1"]},
        ], original_embodiments=[
            {"id": "E1", "features": ["F1", "F2"]},
            {"id": "E2", "features": ["F2", "F3"]},
        ])
        self.assertEqual([1, 2, 3], [row["claim_id"] for row in result["claims"]])
        self.assertEqual([2], result["claims"][2]["parent_ids"])
        self.assertEqual("checked_finite_feature_set", result["claims"][1]["art123_2_check"])
        self.assertEqual("blocked", result["claims"][2]["art123_2_check"])
        self.assertIn({
            "code": "ep_art123_2_ungrounded_or_mixed_embodiment_features", "claim_id": 3,
            "feature_ids": ["F1", "F2", "F3"],
        }, result["issues"])

    def test_ep_checks_each_alternative_parent_and_transitive_branch(self):
        claims = [{"id": cid, "text": "A device.", "feature_ids": [feature], "parent_ids": parents}
                  for cid, feature, parents in ((1, "A", []), (2, "B", []), (3, "C", [1, 2]), (4, "D", [3]))]
        embodiments = [{"id": "ONE", "features": ["A", "C", "D"]},
                       {"id": "TWO", "features": ["B", "C", "D"]}]
        passed = jurisdiction_analyzers.analyze_ep_claims(claims, original_embodiments=embodiments)
        self.assertEqual("needs_review", passed["status"], passed["issues"])
        self.assertTrue(all(r["art123_2_check"] == "checked_finite_feature_set" for r in passed["claims"]))
        embodiments[1]["features"].remove("D")
        blocked = jurisdiction_analyzers.analyze_ep_claims(claims, original_embodiments=embodiments)
        self.assertEqual("blocked", blocked["status"])
        self.assertEqual([{"code": "ep_art123_2_ungrounded_or_mixed_embodiment_features", "claim_id": 4,
                           "feature_ids": ["B", "C", "D"]}], blocked["issues"])

    def test_ep_branch_budget_and_numbering_gap_block_incomplete_checks(self):
        def claim(cid, parents=()):
            return {"id": cid, "text": "A device.", "feature_ids": [f"F{cid}"], "parent_ids": list(parents)}

        analyzer = jurisdiction_analyzers.analyze_ep_claims
        gap = analyzer([claim(1), claim(3, [1])])
        self.assertIn({"code": "ep_claim_numbering_gap"}, gap["issues"])
        claims = [claim(cid) for cid in range(1, 66)] + [claim(66, range(1, 66)), claim(67, [66])]
        report = analyzer(claims)
        self.assertEqual("blocked", report["status"])
        self.assertIn({"code": "ep_claim_branch_budget_exceeded", "claim_id": 66}, report["issues"])
        self.assertEqual(["not_checked_branch_budget_exceeded", "not_checked_invalid_parent_chain"],
                         [r["art123_2_check"] for r in report["claims"][-2:]])

    def test_ep_distinguishes_missing_features_and_missing_embodiments(self):
        claims = [{"id": 1, "text": "A device.", "feature_ids": ["F1"]}]
        no_embodiments = jurisdiction_analyzers.analyze_ep_claims(claims)
        no_features = jurisdiction_analyzers.analyze_ep_claims(
            claims + [{"id": 2, "text": "A device.", "parent_ids": [1]}],
            original_embodiments=[{"id": "E1", "features": ["F1"]}],
        )
        self.assertEqual("not_checked_no_embodiments", no_embodiments["claims"][0]["art123_2_check"])
        self.assertEqual("not_checked_no_feature_ids", no_features["claims"][1]["art123_2_check"])

    def test_ep_does_not_pass_a_chain_with_a_forward_parent(self):
        result = jurisdiction_analyzers.analyze_ep_claims([
            {"id": 1, "text": "A device.", "parent_ids": [2], "feature_ids": ["F1"]},
            {"id": 2, "text": "A device.", "parent_ids": [1], "feature_ids": ["F2"]},
        ], original_embodiments=[{"id": "E1", "features": ["F1", "F2"]}])
        self.assertEqual("blocked", result["status"])
        self.assertIn({"code": "ep_claim_parent_missing_or_forward", "claim_id": 1, "parent_id": 2}, result["issues"])
        self.assertEqual(["not_checked_invalid_parent_chain"] * 2,
                         [row["art123_2_check"] for row in result["claims"]])

    def test_jurisdictions_reject_invalid_structured_input_with_contract_error(self):
        for analyzer in (jurisdiction_analyzers.analyze_us_claims, jurisdiction_analyzers.analyze_ep_claims):
            for invalid in ({"text": 42}, {"id": True}, {"parent_ids": "12"}, {"parent_ids": [False]}):
                with self.subTest(analyzer=analyzer.__name__, invalid=invalid), self.assertRaises(ContractError):
                    analyzer([{"id": 1, "text": "A device.", **invalid}])
            with self.subTest(analyzer=analyzer.__name__), self.assertRaisesRegex(ContractError, "parent_id_duplicate"):
                analyzer([{"id": 1, "text": "A device."}, {"id": 2, "text": "A device.", "parent_ids": [1, 1]}])
        analyze_ep = jurisdiction_analyzers.analyze_ep_claims
        for invalid in ({"feature_ids": [[]]}, {"feature_ids": "F1"}, {"two_part_not_appropriate_reason": 42}):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                analyze_ep([{"id": 1, "text": "A device.", **invalid}])
        for embodiments in ({}, [{"id": "E1", "features": [[]]}], [
            {"id": "E1", "features": ["F1"], "functionally_linked_groups": ["F1"]},
        ]):
            with self.subTest(embodiments=embodiments), self.assertRaises(ContractError):
                analyze_ep([{"id": 1, "text": "A device."}], original_embodiments=embodiments)


class ProcedureStrategyAndVisualLedgerTests(unittest.TestCase):
    def test_no_go_and_narrowing_reassessment(self):
        res = procedure_strategy.evaluate_no_go_and_narrowing({
            "project_id": "P-NOGO-1",
            "narrowed_claim_summary": "Internal cache eviction parameter narrowed to exact 7ms",
            "detectability": "internal_unobservable",
            "design_around_paths": [{"id": "DA1", "effort": "low", "description": "Use 8ms"}],
        })
        self.assertEqual("no_go_recommend_internal_archive_or_trade_secret", res["working_recommendation"])
        self.assertEqual("intentionally_omitted", res["single_composite_score"])

    def test_no_go_rejects_untyped_flags_ids_and_invalid_enums(self):
        base = {"project_id": "P", "narrowed_claim_summary": "Candidate", "detectability": "observable_external",
                "design_around_paths": [{"id": "DA", "effort": "medium"}], "commercial_alignment": "moderate",
                "prior_art_blocking_unresolved": False}
        evaluate = procedure_strategy.evaluate_no_go_and_narrowing
        self.assertEqual(1, evaluate(base)["design_around_count"])
        for field, value, code in (
            ("prior_art_blocking_unresolved", "true", "strategy_prior_art_flag_invalid"),
            ("prior_art_blocking_unresolved", 1, "strategy_prior_art_flag_invalid"),
            ("prior_art_blocking_unresolved", None, "strategy_prior_art_flag_invalid"),
            ("design_around_paths", ["low"], "strategy_design_around_object_required"),
            ("design_around_paths", [{}], "strategy_design_around_effort_invalid"),
            ("design_around_paths", [{"effort": "trivial"}], "strategy_design_around_effort_invalid"),
            ("design_around_paths", [{"id": 1, "effort": "high"}], "strategy_design_around_id_invalid"),
            ("commercial_alignment", "other", "strategy_commercial_alignment_invalid"),
            ("commercial_alignment", [], "strategy_commercial_alignment_invalid"),
            ("project_id", 1, "strategy_identifier_invalid"),
            ("narrowed_claim_summary", [], "strategy_identifier_invalid"),
        ):
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ContractError, code):
                evaluate({**base, field: value})

    def test_fto_and_sep_reject_non_string_identifiers(self):
        fto, sep = procedure_strategy.build_fto_four_track_matrix, procedure_strategy.build_sep_handoff_pack
        element = {"element_id": "E1", "state": "not_observed_unknown"}
        patent = {"patent_id": "P1", "legal_status": "unknown", "elements": [element]}
        matrix = {"product_id": "PR1", "jurisdiction": "US", "as_of": "2026-11-24T00:00:00Z", "patents": [patent]}
        clause = {"clause_id": "C1", "normative": True, "related_patent_ids": [],
                  "filing_support_verified": False, "technical_alternatives": []}
        handoff = {"standard_id": "STD-01", "standard_version": "1", "organization_policy": "Synthetic", "clause_links": [clause]}
        self.assertEqual("PR1", fto(matrix)["product_id"])
        self.assertEqual("STD-01", sep(handoff)["standard_id"])
        for analyzer, payload, row, key, code in (
            (fto, matrix, matrix, "product_id", "fto_identifier_invalid"),
            (fto, matrix, patent, "patent_id", "fto_patent_id_invalid"),
            (fto, matrix, element, "element_id", "fto_element_id_invalid"),
            (sep, handoff, handoff, "standard_id", "sep_identifier_invalid"),
            (sep, handoff, clause, "clause_id", "sep_clause_id_invalid"),
        ):
            old = row[key]
            row[key] = 17
            with self.subTest(key=key), self.assertRaisesRegex(ContractError, code):
                analyzer(payload)
            row[key] = old

    def test_fto_four_track_never_turns_unobserved_into_clearance(self):
        res = procedure_strategy.build_fto_four_track_matrix({
            "product_id": "PROD-X",
            "jurisdiction": "US",
            "as_of": "2026-11-24T00:00:00+00:00",
            "patents": [{
                "patent_id": "US11000001B2",
                "legal_status": "in_force",
                "elements": [
                    {"element_id": "E1", "state": "observed_present", "evidence_id": "EV1"},
                    {"element_id": "E2", "state": "not_observed_unknown"},
                ],
            }],
        })
        self.assertFalse(res["fto_clearance_granted"])
        self.assertIn("US11000001B2:unobserved_elements_1", res["unresolved_unknowns"])
        self.assertEqual("incomplete_or_pending_legal_and_technical_verification", res["patents"][0]["working_state"])

    def test_sep_dual_handoff_keeps_pre_disclosure_and_essentiality_separate(self):
        res = procedure_strategy.build_sep_handoff_pack({
            "standard_id": "T/SYN-001",
            "standard_version": "0.9",
            "organization_policy": "ITU-T/ISO/IEC Common Patent Policy (reference)",
            "clause_links": [{
                "clause_id": "C-05",
                "normative": True,
                "related_patent_ids": ["PAT-1"],
                "filing_support_verified": False,
                "technical_alternatives": ["Alternative checksum layout B"],
            }],
        })
        self.assertIn("pre_disclosure_patent_support_unverified:C-05", res["issues"])
        self.assertFalse(res["essentiality_and_policy_track"][0]["standard_adoption_proves_patentability"])
        self.assertFalse(res["essentiality_and_policy_track"][0]["essentiality_certified"])

    def test_visual_coverage_ledger_keeps_partial_and_separates_ai_from_human(self):
        sha_a = "a" * 64
        partial = visual_ledger.build_visual_coverage_ledger({
            "artifact_id": "DOC-PDF-1",
            "artifact_sha256": sha_a,
            "total_pages": 10,
            "pages": [
                {"page": 1, "status": "inspected", "observer_kind": "ai_page_observation", "image_sha256": "b" * 64},
                {"page": 2, "status": "skipped", "skip_reason": "sampling_budget_limit"},
            ],
        })
        self.assertEqual("partial", partial["coverage_status"])
        self.assertEqual("not_performed", partial["human_visual_review"])
        self.assertEqual(8, len(partial["unaccounted_pages"]))

        ai_all = visual_ledger.build_visual_coverage_ledger({
            "artifact_id": "DOC-PDF-2",
            "artifact_sha256": sha_a,
            "total_pages": 2,
            "pages": [
                {"page": 1, "status": "inspected", "observer_kind": "ai_page_observation", "image_sha256": "c" * 64},
                {"page": 2, "status": "inspected", "observer_kind": "ai_page_observation", "image_sha256": "d" * 64},
            ],
        })
        self.assertEqual("complete", ai_all["coverage_status"])
        self.assertEqual("not_performed", ai_all["human_visual_review"])
        self.assertEqual("machine_or_ai_complete_human_visual_not_performed", ai_all["overall_status"])

    def test_blocking_prior_art_does_not_recommend_trade_secret_for_observable_feature(self):
        res = procedure_strategy.evaluate_no_go_and_narrowing({
            "project_id": "P-NOGO-2", "narrowed_claim_summary": "Externally measurable timing",
            "detectability": "observable_external", "design_around_paths": [],
            "prior_art_blocking_unresolved": True,
        })
        self.assertIn("prior_art_blocking_unresolved", res["risk_factors"])
        self.assertEqual("no_go_pending_prior_art_resolution", res["working_recommendation"])

    def test_fto_validates_as_of_and_evidence_even_for_inactive_patent(self):
        def run_matrix(*, as_of="2026-11-24T00:00:00Z", legal_status="expired", evidence_id="EV1",
                       state="observed_present"):
            return procedure_strategy.build_fto_four_track_matrix({
                "product_id": "PROD-X", "jurisdiction": "US", "as_of": as_of,
                "patents": [{"patent_id": "PAT-1", "legal_status": legal_status, "elements": [
                    {"element_id": "E1", "state": state, "evidence_id": evidence_id},
                ]}],
            })

        for timestamp, code in (("not-a-date", "invalid_timestamp"), ("2026-11-24", "timezone_required")):
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(ContractError, code):
                run_matrix(as_of=timestamp)
        for state in ("observed_present", "observed_absent_with_evidence"):
            for evidence_id in ("  ", 42, ["EV1"]):
                with self.subTest(state=state, evidence_id=evidence_id), self.assertRaisesRegex(
                    ContractError, "fto_observed_state_requires_evidence",
                ):
                    run_matrix(state=state, evidence_id=evidence_id)
        for legal_status in ("expired", "revoked"):
            with self.subTest(legal_status=legal_status):
                res = run_matrix(legal_status=legal_status)
                self.assertEqual("inactive_status_reported_pending_verification", res["patents"][0]["working_state"])
                self.assertFalse(res["fto_clearance_granted"])

    def test_sep_public_release_review_and_string_list_validation(self):
        def build_pack(**changes):
            return procedure_strategy.build_sep_handoff_pack({
                "standard_id": "T/SYN-002", "standard_version": "0.9", "organization_policy": "Synthetic",
                "clause_links": [{"clause_id": "C-01", "normative": True, "filing_support_verified": False,
                                  "related_patent_ids": ["PAT-1"], "technical_alternatives": [], **changes}],
            })

        for field in ("related_patent_ids", "technical_alternatives"):
            for value in ("text", ["  "], [42]):
                with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                    build_pack(**{field: value})
        pack = build_pack()
        self.assertIn("REVIEW-02", pack["pre_disclosure_protection_track"][0]["handoff_target"])
        self.assertEqual("candidate_requires_independent_essentiality_review",
                         pack["essentiality_and_policy_track"][0]["essentiality_status"])

    def test_visual_rejects_invalid_types_and_empty_finding_codes(self):
        base = {"page": 1, "status": "inspected", "observer_kind": "ai_page_observation", "image_sha256": "b" * 64}
        for changes in ({"artifact_sha256": 123}, {"artifact_id": []}, {"pages": [{**base, "status": []}]},
                        {"pages": [{**base, "observer_kind": {}}]}, {"pages": [{**base, "findings": None}]},
                        {"pages": [{**base, "findings": [{"code": " "}]}]}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                visual_ledger.build_visual_coverage_ledger({
                    "artifact_id": "DOC-PDF-3", "artifact_sha256": "a" * 64, "total_pages": 1,
                    "pages": [base], **changes,
                })

    def test_visual_mixed_coverage_unrendered_pages_and_finding_scope(self):
        human = {"page": 1, "status": "inspected", "observer_kind": "human_visual_review", "image_sha256": "b" * 64}
        ai = {"page": 2, "status": "inspected", "observer_kind": "ai_page_observation", "image_sha256": "c" * 64}
        base = {"artifact_id": "DOC-PDF-4", "artifact_sha256": "a" * 64, "total_pages": 2, "pages": [human, ai]}
        mixed = visual_ledger.build_visual_coverage_ledger(base)
        self.assertEqual("complete", mixed["coverage_status"])
        self.assertEqual("partial_recorded", mixed["human_visual_review"])
        self.assertEqual("mixed_observers_complete_human_visual_partial_recorded", mixed["overall_status"])
        self.assertFalse(mixed["image_bytes_verified"])
        self.assertFalse(mixed["reviewer_identity_verified"])

        incomplete = visual_ledger.build_visual_coverage_ledger({
            **base, "pages": [{**human, "findings": [{"page": 2, "code": "clipped"}]},
                             {"page": 2, "status": "unrendered"}],
        })
        self.assertEqual("partial", incomplete["coverage_status"])
        self.assertEqual([2], incomplete["unrendered_pages"])
        self.assertEqual([{"page": 1, "code": "clipped"}], incomplete["findings"])
        self.assertEqual("findings_present_needs_remediation", incomplete["overall_status"])


if __name__ == "__main__":
    unittest.main()
