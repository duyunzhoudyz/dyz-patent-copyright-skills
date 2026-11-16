"""程序及争议辅助的合成 AC；不代表任何现行规则或专业签核。"""

import copy
import json
from pathlib import Path
import unittest

from tools.core import ContractError
from tools.procedure import CAPABILITIES, run


NOW = "2026-10-31T12:00:00+00:00"
EARLY = "2025-01-31T09:00:00+00:00"
LATE = "2026-01-31T09:00:00+00:00"


def base():
    return {
        "adaptation": {"jurisdiction": "TEST", "right_type": "invention",
                       "domain": "synthetic", "stage": "review"},
        "as_of": NOW,
        "evidence": [{"id": "e1", "version": "1", "source": "synthetic",
                      "locator": "fixture:1", "kind": "synthetic"}],
    }


def ev(**fields):
    return {"evidence_ids": ["e1"], **fields}


def applications():
    return [ev(id="a1", jurisdiction="TEST", version="1", submitted=True,
               filing_at=LATE, priority_at=EARLY)]


def contents():
    return [{"id": "f1", "kind": "combination", "mappings": [
        ev(application_id="a1", support="confirmed", locator="description:2",
           priority_supported=False)]}]


def claims():
    return [ev(id="c1", version="v1", jurisdiction="TEST", text_kind="claims",
               legal_status="active", status_at=NOW,
               elements=[{"id": "x", "text": "internal mechanism"},
                         {"id": "y", "text": "output"}])]


def observations():
    return [ev(claim_id="c1", claim_version="v1", product_version="1", element_id="x",
               state="present", source_kind="technical", locator="test:1"),
            ev(claim_id="c1", claim_version="v1", product_version="1", element_id="y",
               state="absent", source_kind="technical", locator="test:2")]


def rule():
    return {
        "rule_id": "r1", "version": "synthetic-1", "source": "synthetic",
        "locator": "fixture-rule:1", "scope": {"jurisdiction": "TEST"},
        "effective_from": "2020-01-01T00:00:00Z", "verified_at": NOW,
        "license": "synthetic", "review_status": "professionally_verified",
        "review_evidence": "synthetic-test-attestation",
        "interval": {"unit": "months", "value": 1},
    }


def example(capability):
    p = base()
    if capability == "PROC-01":
        p.update(contents=[{"id": "f1"}], events=[
            ev(id="branch", content_ids=["f1"], kind="public_branch",
               occurred_at=EARLY, access="public", location="TEST")],
            target_regions=["TEST"], conditions=[])
    elif capability in {"PROC-02", "PROC-07"}:
        p.update(applications=applications(), contents=contents(),
                 target_regions=["TEST"])
        if capability == "PROC-07":
            p["applications"].append(ev(id="a2", parent_id="a1", version="1",
                jurisdiction="OTHER", submitted=False, filing_at=None))
            p["route_conditions"] = []
    elif capability == "PROC-03":
        p.update(routes=[ev(id="entry", jurisdiction="TEST", anchor_at=EARLY,
                            rule_id="r1", materials=["translation"],
                            language="xx", representative="unknown",
                            fee_basis="unknown")], rules=[rule()])
    elif capability == "PROC-04":
        p.update(required_files=["claims", "description"], files=[
            {"id": "claims", "sha256": "a" * 64},
            {"id": "description", "sha256": "b" * 64}],
            transmission={"state": "transport_success", "evidence_ids": ["e1"]},
            receipt=None, citations=[], disclosure_targets=[])
    elif capability == "PROC-05":
        p.update(notice=ev(id="oa", version="1", kind="synthetic", complete=True,
                           served_at=LATE, due_at="2026-12-01T00:00:00Z",
                           opinions=[{"id": "o1", "text": "synthetic objection"},
                                     {"id": "o2", "text": "synthetic objection 2"}]),
                 current_claims=ev(version="claims1"),
                 original_application=ev(version="original1"),
                 responses=[ev(opinion_id="o1", text="proposed response")],
                 amendments=[ev(id="m1", before="a", after="a+b",
                                support="new", locator=None, original_version="original1")],
                 citations=[ev(id="d1", origin_jurisdiction="OTHER")],
                 disclosure_targets=[{"jurisdiction": "TEST", "owner": "agent"}])
    elif capability == "PROC-06":
        p.update(agenda=[{"id": "a", "text": "proposed discussion"}],
                 minutes=[ev(id="m", participant_confirmed=False,
                             text="unconfirmed note")],
                 defects=[ev(id="d", kind="missing_document", file_id="claims")])
    elif capability == "PROC-08":
        p.update(events=[ev(id="late", kind="missed_deadline", occurred_at=LATE)],
                 remedies=[ev(id="restore", jurisdiction="TEST", rule_id="unknown",
                              eligibility="unknown", due_at=None)], decisions=[])
    elif capability == "PROC-09":
        p.update(official=ev(version="grant1", sections={"c1": "a+b"}),
                 approved=ev(version="draft1", sections={"c1": "a"}),
                 routes=[{"id": "national", "jurisdiction": "TEST"}])
    elif capability in {"RIGHTS-01", "RIGHTS-02", "RIGHTS-03", "RIGHTS-05"}:
        p.update(product={"id": "p1", "version": "1"}, claims=claims(),
                 observations=observations())
        if capability == "RIGHTS-03":
            p.update(territories=["TEST"], activities=["sale"],
                     search={"status": "complete", "coverage": ["fixture"],
                             "evidence_ids": ["e1"]})
        if capability == "RIGHTS-05":
            p.update(previous_product_version="0", changes=[ev(
                id="design1", element_id="x", description="alternative",
                functional_impact="untested")],
                screened_claim_ids=["c1"], search_product_version="0")
    elif capability in {"SEARCH-07", "RIGHTS-04"}:
        p.update(purpose="invalidity", critical_at=LATE, territories=["TEST"],
                 documents=[ev(id="d1", jurisdiction="TEST", legal_status="expired",
                               public_at=EARLY, acquired_at=NOW, status_at=NOW)],
                 grounds=[ev(id="g1", document_ids=["d1"], claim_id="c1",
                             reason="candidate only", burden="not_assessed")])
    elif capability == "RIGHTS-06":
        p.update(request={"products": ["p1", "p2"], "territories": ["TEST", "OTHER"],
                          "actions": ["sale"]},
                 license=ev(id="l1", state="executed", products=["p1"],
                            territories=["TEST"], actions=["sale"],
                            valid_from=EARLY, valid_until="2027-01-01T00:00:00Z",
                            authority_evidence_ids=[], chain_evidence_ids=[],
                            encumbrances="unknown"))
    elif capability == "RIGHTS-07":
        p.update(declarations=[ev(id="dec1", claim_id="c1")],
                 standard={"id": "s1", "version": "1", "clauses": ["cl1", "cl2"]},
                 claims=claims(), mappings=[], policy_conflicts=["confidentiality"])
    elif capability == "SEARCH-08":
        p.update(counting="document", window={"start": EARLY, "end": NOW},
                 documents=[ev(id="d1", family_id="f", public_at=LATE,
                               category="control", effect="speed"),
                            ev(id="d2", family_id="f", public_at=LATE,
                               category="control", effect="speed")],
                 coverage=[{"source": "synthetic", "status": "complete"}])
    elif capability == "LIFE-02":
        p.update(quotes=[ev(id="q1", family_id="fam", amount="12.50", currency="USD",
                            valid_from=EARLY, valid_until=LATE, decision="maintain"),
                         ev(id="q2", family_id="fam", amount="5.10", currency="EUR",
                            valid_from=EARLY, valid_until="2027-01-01T00:00:00Z",
                            decision="undecided")])
    else:
        raise AssertionError(capability)
    return p


class ProcedureContracts(unittest.TestCase):
    def test_shipped_skill_example_and_resource_links(self):
        root = Path(__file__).resolve().parents[1]
        skill = root / "skills" / "dyz-procedure"
        p = json.loads((skill / "resources" / "example.json").read_text(encoding="utf-8"))
        out = run("PROC-02", p)
        self.assertEqual(len(out["artifacts"]["support_matrix"]), 4)
        self.assertEqual(out["status"], "needs_evidence")
        self.assertTrue((skill / "resources" / "input-contracts.md").is_file())
        for required in ("__init__.py", "core.py", "procedure.py"):
            self.assertTrue((root / "tools" / required).is_file())

    def test_all_19_tasks_return_independent_safe_results(self):
        self.assertEqual(len(CAPABILITIES), 19)
        for capability in CAPABILITIES:
            with self.subTest(capability=capability):
                p = example(capability)
                original = copy.deepcopy(p)
                out = run(capability, p)
                self.assertEqual(out["capability"], capability)
                self.assertEqual(out["external_action"], "not_performed")
                self.assertEqual(out["professional_review"], "not_performed")
                self.assertEqual(out["official_status"], "not_asserted")
                self.assertEqual(p, original)
                self.assertEqual(len(out["artifacts"]["input_digest"]), 64)

    def test_version_change_invalidates_each_capability(self):
        for capability in CAPABILITIES:
            with self.subTest(capability=capability):
                p = example(capability)
                first = run(capability, p)
                p["previous_input_digest"] = first["artifacts"]["input_digest"]
                self.assertNotEqual(run(capability, p)["status"], "invalidated")
                p["evidence"][0]["version"] = "2"
                self.assertEqual(run(capability, p)["status"], "invalidated")

    def test_not_applicable_requires_reason_and_evidence(self):
        for capability in CAPABILITIES:
            p = base()
            p["applicability"] = ev(state="not_applicable", reason="synthetic exclusion")
            self.assertEqual(run(capability, p)["status"], "not_applicable")
        p["applicability"]["reason"] = ""
        with self.assertRaises(ContractError):
            run("PROC-01", p)

    def test_malformed_and_unbound_evidence_rejected(self):
        for capability in CAPABILITIES:
            with self.subTest(capability=capability):
                with self.assertRaises(ContractError):
                    run(capability, {})
                p = example(capability)
                p["evidence"] = []
                with self.assertRaises(ContractError):
                    run(capability, p)
        with self.assertRaises(ContractError):
            run("PROC-99", base())

    def test_missing_timezone_rejected(self):
        p = example("PROC-01")
        p["events"][0]["occurred_at"] = "2025-01-01"
        with self.assertRaises(ContractError):
            run("PROC-01", p)

    def test_duplicate_ids_rejected(self):
        p = example("PROC-01")
        p["events"].append(copy.deepcopy(p["events"][0]))
        with self.assertRaises(ContractError):
            run("PROC-01", p)

    def test_public_branch_and_unknown_demo_preserved(self):
        p = example("PROC-01")
        p["events"].append(ev(id="demo", content_ids=["f1"], kind="demo",
                              occurred_at=None, access="unknown", location="TEST"))
        out = run("PROC-01", p)
        self.assertEqual(out["status"], "needs_evidence")
        self.assertEqual(out["artifacts"]["potential_disclosures"], ["branch", "demo"])
        self.assertEqual(out["artifacts"]["public_release_opinion"], "defer")

    def test_priority_not_inherited_for_new_content_or_other_region(self):
        p = example("PROC-02")
        p["contents"].append({"id": "new", "kind": "range", "mappings": []})
        p["target_regions"].append("OTHER")
        rows = run("PROC-02", p)["artifacts"]["support_matrix"]
        self.assertEqual(rows[0]["date_candidates"][0]["filing_at"], LATE)
        self.assertIsNone(rows[0]["date_candidates"][0]["priority_at"])
        self.assertTrue(any(r["content_id"] == "new" and r["state"] == "unknown"
                            for r in rows))
        self.assertTrue(any(r["jurisdiction"] == "OTHER" and r["state"] == "unknown"
                            for r in rows))

    def test_priority_requires_content_specific_evidence(self):
        p = example("PROC-02")
        mapping = p["contents"][0]["mappings"][0]
        mapping.update(priority_supported=True, priority_evidence_ids=["e1"])
        self.assertEqual(run("PROC-02", p)["artifacts"]["support_matrix"][0]
                         ["date_candidates"][0]["priority_at"], EARLY)

    def test_subsequent_application_graph_and_cycle(self):
        p = example("PROC-07")
        out = run("PROC-07", p)
        self.assertEqual(out["artifacts"]["edges"], [["a1", "a2"]])
        self.assertEqual(out["artifacts"]["route_decision"], "undetermined")
        p["applications"][0]["parent_id"] = "a2"
        with self.assertRaises(ContractError):
            run("PROC-07", p)

    def test_region_specific_rule_arithmetic_and_exceptions(self):
        p = example("PROC-03")
        r2 = copy.deepcopy(rule())
        r2.update(rule_id="r2", scope={"jurisdiction": "OTHER"},
                  interval={"unit": "days", "value": 10})
        p["rules"].append(r2)
        p["routes"].append(ev(id="entry2", jurisdiction="OTHER", anchor_at=EARLY,
                              rule_id="r2", materials=[], language="yy",
                              representative="pending", fee_basis="pending"))
        rows = run("PROC-03", p)["artifacts"]["routes"]
        self.assertTrue(rows[0]["candidate_due_at"].startswith("2025-02-28"))
        self.assertTrue(rows[1]["candidate_due_at"].startswith("2025-02-10"))
        p["routes"][0]["adjustment"] = ev(due_at="2025-03-03T09:00:00Z",
                                             reason="synthetic holiday exception")
        rows = run("PROC-03", p)["artifacts"]["routes"]
        self.assertEqual(rows[0]["candidate_due_at"], "2025-03-03T09:00:00Z")

    def test_unverified_rule_never_computes_deadline(self):
        p = example("PROC-03")
        p["rules"][0]["review_status"] = "not_verified"
        out = run("PROC-03", p)
        self.assertIsNone(out["artifacts"]["routes"][0]["candidate_due_at"])
        self.assertEqual(out["status"], "needs_evidence")

    def test_transmission_success_is_not_filing_date(self):
        out = run("PROC-04", example("PROC-04"))
        self.assertEqual(out["artifacts"]["filing_fact"], "unverified")
        self.assertEqual(out["artifacts"]["missing_files"], [])

    def test_unknown_failure_and_missing_file_are_distinct(self):
        p = example("PROC-04")
        p["files"].pop()
        p["transmission"]["state"] = "unknown"
        out = run("PROC-04", p)
        self.assertFalse(out["artifacts"]["retry_allowed"])
        self.assertEqual(out["artifacts"]["missing_files"], ["description"])
        p["transmission"]["state"] = "failed"
        self.assertEqual(run("PROC-04", p)["status"], "failed")

    def test_receipt_must_bind_actual_manifest(self):
        p = example("PROC-04")
        p["receipt"] = ev(manifest_digest="wrong", application_id="synthetic-id",
                           filing_at=LATE)
        self.assertIn("receipt_manifest_mismatch", run("PROC-04", p)["issues"])

    def test_oa_omissions_new_matter_and_foreign_citation(self):
        out = run("PROC-05", example("PROC-05"))
        a = out["artifacts"]
        self.assertEqual(a["unanswered_opinions"], ["o2"])
        self.assertEqual(a["unsupported_amendments"], ["m1"])
        self.assertEqual(a["citation_tasks"][0]["status"], "applicability_unknown")
        self.assertEqual(a["notice_kind"], "synthetic")

    def test_complete_oa_response_remains_professional_draft(self):
        p = example("PROC-05")
        p["responses"].append(ev(opinion_id="o2", text="response 2"))
        p["amendments"][0].update(support="confirmed", locator="original:1")
        p["citations"] = []
        out = run("PROC-05", p)
        self.assertEqual(out["status"], "needs_review")
        self.assertEqual(out["artifacts"]["unanswered_opinions"], [])

    def test_notice_missing_pages_and_deadline(self):
        p = example("PROC-05")
        p["notice"].update(complete=False, due_at=None)
        out = run("PROC-05", p)
        self.assertIn("notice_incomplete", out["issues"])
        self.assertIn("notice_due_at_unknown", out["issues"])

    def test_agenda_does_not_become_minutes_or_repair(self):
        out = run("PROC-06", example("PROC-06"))
        self.assertEqual(len(out["artifacts"]["agenda"]), 1)
        self.assertEqual(out["artifacts"]["confirmed_minutes"], [])
        self.assertEqual(out["artifacts"]["repair_tasks"][0]["action"],
                         "verify_missing_document_remedy")

    def test_missed_deadline_does_not_decide_restoration(self):
        a = run("PROC-08", example("PROC-08"))["artifacts"]
        self.assertEqual(a["rights_outcome"], "undetermined")
        self.assertEqual(a["remedy_paths"][0]["eligibility"], "unknown")

    def test_granted_text_diff_preserved(self):
        a = run("PROC-09", example("PROC-09"))["artifacts"]
        self.assertEqual(a["differences"][0]["official"], "a+b")
        self.assertEqual(a["differences"][0]["approved"], "a")
        self.assertEqual(a["correction_status"], "needs_review")

    def test_unknown_absent_and_marketing_evidence_are_distinct(self):
        p = example("RIGHTS-02")
        p["observations"][0]["source_kind"] = "marketing"
        a = run("RIGHTS-02", p)["artifacts"]
        self.assertEqual(a["matrix"][0]["state"], "unknown")
        self.assertEqual(a["matrix"][1]["state"], "absent")
        self.assertEqual(a["infringement"], "undetermined")

    def test_claim_version_mismatch_cannot_clear_risk(self):
        p = example("RIGHTS-01")
        p["observations"][0]["claim_version"] = "old"
        self.assertEqual(run("RIGHTS-01", p)["artifacts"]["matrix"][0]["state"],
                         "unknown")
        p["claims"][0]["text_kind"] = "abstract"
        with self.assertRaises(ContractError):
            run("RIGHTS-01", p)

    def test_fto_own_patent_cannot_clear_third_party_scope(self):
        p = example("RIGHTS-03")
        p["own_patents"] = ["own1"]
        p["observations"].pop()
        a = run("RIGHTS-03", p)["artifacts"]
        self.assertEqual(a["fto"], "undetermined")
        self.assertIn("c1:y", a["unknown_elements"])

    def test_expired_document_retained_for_invalidity_only(self):
        p = example("SEARCH-07")
        a = run("SEARCH-07", p)["artifacts"]
        self.assertEqual(a["candidates"][0]["selection"], "candidate")
        p["purpose"] = "fto"
        a = run("SEARCH-07", p)["artifacts"]
        self.assertEqual(a["candidates"][0]["selection"], "not_current_target")
        self.assertFalse(a["global_clearance"])

    def test_invalidity_unknown_publication_date_is_only_lead(self):
        p = example("RIGHTS-04")
        p["documents"][0]["public_at"] = None
        out = run("RIGHTS-04", p)
        self.assertEqual(out["artifacts"]["candidates"][0]["selection"], "lead_only")
        self.assertEqual(out["artifacts"]["invalidity"], "undetermined")

    def test_design_change_rescreens_other_claims(self):
        p = example("RIGHTS-05")
        c2 = copy.deepcopy(p["claims"][0])
        c2["id"] = "c2"
        p["claims"].append(c2)
        a = run("RIGHTS-05", p)["artifacts"]
        self.assertEqual(a["remaining_claims"], ["c2"])
        self.assertTrue(a["search_required"])
        self.assertFalse(a["safe_design"])

    def test_license_product_territory_authority_gaps(self):
        a = run("RIGHTS-06", example("RIGHTS-06"))["artifacts"]
        self.assertEqual(a["scope_gaps"]["products"], ["p2"])
        self.assertEqual(a["scope_gaps"]["territories"], ["OTHER"])
        self.assertIn("signing_authority_unknown", a["due_diligence"])
        self.assertEqual(a["permission"], "undetermined")

    def test_sep_declaration_does_not_prove_essentiality(self):
        a = run("RIGHTS-07", example("RIGHTS-07"))["artifacts"]
        self.assertEqual(a["essentiality"], "undetermined")
        self.assertEqual(a["license"], "not_established")
        self.assertEqual(len(a["missing_mappings"]), 2)
        self.assertEqual(a["handoff"], "STD-08")

    def test_landscape_recounts_with_family_basis(self):
        p = example("SEARCH-08")
        a = run("SEARCH-08", p)["artifacts"]
        self.assertEqual(a["total"], 2)
        p["counting"] = "family"
        p["previous_input_digest"] = a["input_digest"]
        out = run("SEARCH-08", p)
        self.assertEqual(out["artifacts"]["total"], 1)
        self.assertEqual(out["status"], "invalidated")
        self.assertFalse(out["artifacts"]["white_space_is_patentability"])

    def test_unknown_family_not_collapsed_and_missing_source_visible(self):
        p = example("SEARCH-08")
        p["counting"] = "family"
        for d in p["documents"]:
            d["family_id"] = None
        p["coverage"].append({"source": "missing", "status": "unavailable"})
        out = run("SEARCH-08", p)
        self.assertEqual(out["artifacts"]["total"], 2)
        self.assertEqual(out["status"], "partial")

    def test_expired_quotes_not_summed_with_current_or_other_currency(self):
        a = run("LIFE-02", example("LIFE-02"))["artifacts"]
        self.assertEqual(a["expired_quote_ids"], ["q1"])
        self.assertEqual(a["current_totals"], {"EUR": "5.10"})
        self.assertFalse(a["payment_authorized"])
        self.assertFalse(a["abandonment_authorized"])

    def test_changed_product_cannot_reuse_observations(self):
        p = example("RIGHTS-02")
        p["product"]["version"] = "2"
        a = run("RIGHTS-02", p)["artifacts"]
        self.assertEqual(a["unknown_elements"], ["c1:x", "c1:y"])

    def test_new_citation_without_target_stays_actionable_unknown(self):
        p = example("PROC-05")
        p["disclosure_targets"] = []
        a = run("PROC-05", p)["artifacts"]
        self.assertEqual(a["citation_tasks"][0]["status"], "target_scope_unknown")
        self.assertIsNone(a["citation_tasks"][0]["owner"])

    def test_old_expiry_snapshot_does_not_filter_current_fto(self):
        p = example("SEARCH-07")
        p["purpose"] = "fto"
        p["documents"][0]["status_at"] = EARLY
        a = run("SEARCH-07", p)["artifacts"]
        self.assertEqual(a["candidates"][0]["selection"], "needs_status")

    def test_oa_original_version_mismatch_retains_support_gap(self):
        p = example("PROC-05")
        p["amendments"][0].update(support="confirmed", locator="p1",
                                     original_version="older")
        a = run("PROC-05", p)["artifacts"]
        self.assertEqual(a["unsupported_amendments"], ["m1"])

    def test_sep_unknown_clause_rejected(self):
        p = example("RIGHTS-07")
        p["mappings"] = [ev(claim_id="c1", element_id="x", clause_id="missing")]
        with self.assertRaises(ContractError):
            run("RIGHTS-07", p)

    def test_unobserved_is_not_absent(self):
        p = example("RIGHTS-02")
        p["observations"][0]["state"] = "unobserved"
        a = run("RIGHTS-02", p)["artifacts"]
        self.assertEqual(a["matrix"][0]["state"], "unobserved")
        self.assertIn("c1:x", a["unknown_elements"])

    def test_each_task_keeps_unknown_evidence_visible(self):
        def clear_refs(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "evidence_ids" or key.endswith("_evidence_ids"):
                        value[key] = []
                    else:
                        clear_refs(child)
            elif isinstance(value, list):
                for child in value:
                    clear_refs(child)
        for capability in CAPABILITIES:
            with self.subTest(capability=capability):
                p = example(capability)
                clear_refs(p)
                out = run(capability, p)
                self.assertIn(out["status"], {"needs_evidence", "partial"})
                self.assertTrue(out["issues"])

    def test_negative_and_nonfinite_quote_rejected(self):
        for amount in ["-1", "NaN", "Infinity", True]:
            p = example("LIFE-02")
            p["quotes"][0]["amount"] = amount
            with self.assertRaises(ContractError):
                run("LIFE-02", p)


if __name__ == "__main__":
    unittest.main()
