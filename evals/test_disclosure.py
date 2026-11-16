"""DG-01—20：合成材料 + 真实临时SQLite；外部动作恒为零。

专业意见是预先指定的合成记录，测试验证门禁分支而非法律/语义正确性。
"""
from __future__ import annotations

import base64
import copy
import json
import multiprocessing
import sqlite3
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tools import core
from tools.disclosure import (DisclosureJournal, freeze_candidate, inspect_bytes,
                              required_roles, review_candidate)

NOW = "2026-10-31T12:00:00+00:00"
START = "2026-01-01T00:00:00+00:00"
END = "2027-01-01T00:00:00+00:00"


def make_case(root: Path) -> dict:
    permission = {"action": "local_read", "purpose": "synthetic-review", "recipient": "local_tool",
                  "decision": "allow", "authority_evidence": "synthetic-authority",
                  "valid_from": START, "valid_until": END}
    context = {"sensitivity": "synthetic", "environment": {}, "permissions": [permission],
               "purpose": "synthetic-review", "now": NOW}
    files = []
    for number, text in ((1, "Synthetic feature alpha.\n"), (2, "Synthetic feature beta.\n")):
        path = root / f"file{number}.txt"
        path.write_text(text, encoding="utf-8")
        files.append({"file_id": f"f{number}", "path": path.name, "version": "1",
                      "expected_sha256": core.sha256_bytes(path.read_bytes()),
                      "kind": "external", "content_ids": [f"c{number}"]})
    files.append({"file_id": "internal", "path": "not-read-internal.txt", "version": "1",
                  "expected_sha256": "0" * 64, "kind": "internal_report"})
    candidate = freeze_candidate(root, files, context)
    request = {"release_id": "release-1", "project_id": "project-1", "businesses": ["standard"],
               "purpose": "synthetic-review", "action": "public_disclosure", "recipient": "synthetic-group",
               "channel": "synthetic", "access": {"audience": "public", "download": True,
               "forward": True, "archive": True, "retention": "synthetic-only"},
               "targets": ["CN", "US"], "valid_from": START, "valid_until": END,
               "max_uses": 1, "conditions": []}
    assessment = {"strategy": "protect", "rules": {"version": "rules-1", "status": "available",
                  "evidence": "synthetic-rule-evidence"}, "application": {"version": "application-1",
                  "status": "verified", "application_id": "SYNTHETIC-NOT-REAL",
                  "receipt_evidence": "synthetic-receipt", "files": ["a" * 64],
                  "date_evidence": "synthetic-date"}, "combinations": ["combo-1"],
                  "joint_review": {"status": "confirmed", "evidence": "synthetic-joint-review",
                  "manifest_hash": candidate["manifest_hash"], "file_ids": ["f1", "f2"],
                  "content_ids": ["c1", "c2"], "combination_ids": ["combo-1"], "inventory_complete": True},
                  "hidden_review": {"status": "confirmed", "evidence": "synthetic-full-review",
                                    "manifest_hash": candidate["manifest_hash"]},
                  "policy": {"status": "reviewed", "evidence": "synthetic-policy", "conflicts": [],
                             "license_status": "confirmed", "fto_status": "reviewed"},
                  "rights": {}, "roles_not_applicable": {"software": "no software material"},
                  "unresolved": [], "support": []}
    for file_id in ("f1", "f2"):
        assessment["rights"][file_id] = {"source_evidence": "synthetic-source",
            "contribution_evidence": "synthetic-contribution", "restrictions": [],
            "permissions": [{**permission, "action": request["action"], "recipient": request["recipient"]}]}
    for content_id in ("c1", "c2", "combo-1"):
        for target in request["targets"]:
            assessment["support"].append({"content_id": content_id, "target": target,
                "status": "confirmed", "original_locator": "synthetic-p1",
                "evidence": "synthetic-support", "date_evidence": "synthetic-date",
                "application_version": "application-1", "document_sha256": "a" * 64})
    roles = required_roles(request, assessment)
    registry = {"mode": "synthetic", "version": "actors-1", "actors": [
        {"actor_id": role, "kind": "synthetic_human", "roles": [role], "active": True,
         "authority_evidence": "synthetic-role-evidence", "valid_from": START, "valid_until": END,
         "scope": {"project_id": request["project_id"], "actions": [request["action"]],
                   "recipients": [request["recipient"]], "purposes": [request["purpose"]]}}
        for role in sorted(roles)]}
    return {"candidate": candidate, "request": request, "assessment": assessment,
            "registry": registry, "context": context, "files": files}


def concurrent_execute(path: str, current: dict) -> str:
    journal = DisclosureJournal(path, synthetic=True)
    try:
        return journal.execute("release-1", current=current, now=NOW)["state"]
    except core.ContractError as exc:
        return str(exc)


class DisclosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-dg-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = make_case(self.root)
        self.path = self.root / "journal.sqlite"
        self.journal = DisclosureJournal(self.path, synthetic=True)

    def current(self):
        return {**{k: copy.deepcopy(self.case[k]) for k in ("request", "assessment", "registry")},
                "manifest_hash": self.case["candidate"]["manifest_hash"]}

    def prepare(self, omit=()):
        release = self.journal.create_release(**{k: self.case[k] for k in
            ("candidate", "request", "assessment", "registry")})
        for role in sorted(required_roles(self.case["request"], self.case["assessment"])):
            if role not in omit:
                self.journal.sign("release-1", role=role, actor_id=role,
                    evidence="synthetic-signature", binding=release["binding"], now=NOW)
        return release

    def counts(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in ("executions", "outbox"))

    def blocked(self, code, *, now=NOW, current=None):
        review = self.journal.review("release-1", now=now)
        self.assertIn(code, [issue["code"] for issue in review["issues"]])
        with self.assertRaises(core.ContractError):
            self.journal.execute("release-1", current=current or self.current(), now=now)
        self.assertEqual((0, 0), self.counts())
        self.assertEqual("not_performed", self.journal.status("release-1")["external_action"])

    def test_dg01_unfiled_protection_blocks_publication(self):
        self.case["assessment"]["application"]["status"] = "not_filed"
        self.prepare()
        self.blocked("actual_application_unverified")

    def test_dg02_application_number_does_not_cover_new_combination(self):
        self.case["assessment"]["support"][-1]["status"] = "new_content"
        self.prepare()
        self.blocked("content_or_region_support_unknown")

    def test_dg03_changed_attachment_invalidates_approval(self):
        self.prepare()
        current = self.current()
        current["manifest_hash"] = "changed-attachment-translation-or-figure"
        changed = self.journal.invalidate("release-1", current=current, now=NOW)
        self.assertIn("manifest_hash", changed["changed"])
        self.blocked("release_invalidated", current=current)

    def test_dg04_recipient_and_action_change_requires_new_approval(self):
        self.prepare()
        current = self.current()
        current["request"].update(recipient="other-group", action="controlled_share")
        self.journal.invalidate("release-1", current=current, now=NOW)
        self.blocked("release_invalidated", current=current)

    def test_dg05_access_expansion_and_observed_expansion_incident(self):
        self.prepare()
        current = self.current()
        current["request"]["access"]["audience"] = "other-public-audience"
        self.journal.invalidate("release-1", current=current, now=NOW)
        self.blocked("release_invalidated", current=current)
        incident = self.journal.report_incident("release-1", facts={
            "observed_at": NOW, "known_access": "synthetic public archive", "evidence": ["fixture"],
            "containment_authority": "stop-local-only"}, now=NOW)
        self.assertEqual("reported_stopped", incident["state"])

    def test_dg06_hidden_information_and_unsupported_container_block(self):
        for suffix, text in ((".txt", "visible\u200bSYNTHETIC_HIDDEN"),
                             (".md", "visible <!--SYNTHETIC_HIDDEN-->"),
                             (".docx", "unsupported hidden table")):
            with self.subTest(suffix=suffix):
                self.assertNotEqual("source_checked", inspect_bytes("a" + suffix, text.encode())["status"])
        self.case["assessment"]["hidden_review"]["status"] = "hidden_content_found"
        self.prepare()
        self.blocked("full_content_review_required")
        self.assertNotIn("SYNTHETIC_HIDDEN", json.dumps(self.journal.review("release-1", now=NOW)))

    def test_dg07_joint_semantic_review_not_individual_keyword_passes(self):
        self.case["assessment"]["joint_review"]["status"] = "combination_discloses_new_scheme"
        self.prepare()
        self.blocked("joint_semantic_review_required")

    def test_dg08_model_permission_not_redistribution_internal_report_excluded(self):
        for rights in self.case["assessment"]["rights"].values():
            rights["permissions"][0]["action"] = "service_processing"
        self.prepare()
        self.blocked("material_action_not_authorized")
        self.assertEqual(["internal"], self.case["candidate"]["manifest"]["excluded_internal_reports"])
        self.assertNotIn("internal", self.case["candidate"]["snapshots"])

    def test_dg09_expiry_revocation_rules_unavailable_and_missing_signatures(self):
        self.prepare(omit={"patent"})
        self.blocked("required_signature_missing")
        self.blocked("approval_expired_or_not_started", now=END)
        self.assertEqual("expired", DisclosureJournal(self.path, synthetic=True).status("release-1")["approval_state"])
        self.journal.revoke("release-1", evidence="synthetic-revocation", now=NOW)
        self.blocked("release_revoked")
        body = {k: self.case[k] for k in ("candidate", "request", "assessment", "registry")}
        body = copy.deepcopy(body)
        body["assessment"]["rules"]["status"] = "unavailable"
        review = review_candidate(**body, signatures=[], now=NOW)
        self.assertIn("rules_unavailable", [i["code"] for i in review["issues"]])
        self.assertEqual((0, 0), self.counts())

    def test_dg10_timeout_persists_unknown_and_blocks_retry(self):
        self.prepare()
        output = self.journal.execute("release-1", current=self.current(), now=NOW, outcome="timeout")
        self.assertEqual("unknown", output["state"])
        restarted = DisclosureJournal(self.path, synthetic=True)
        self.assertEqual("unknown", restarted.status("release-1")["execution"]["state"])
        with self.assertRaisesRegex(core.ContractError, "already_attempted"):
            restarted.execute("release-1", current=self.current(), now=NOW)
        receipt = restarted.simulated_receipt(output["execution_id"])
        verified = restarted.verify_receipt("release-1", receipt=receipt, evidence="synthetic-query", now=NOW)
        self.assertEqual("synthetic_confirmed", verified["state"])
        self.assertEqual((1, 1), self.counts())

    def test_dg11_deleted_link_does_not_restore_novelty_evidence_preserved(self):
        self.prepare()
        incident = self.journal.report_incident("release-1", facts={"observed_at": NOW,
            "known_access": "synthetic public", "evidence": ["synthetic-access-record"],
            "containment_authority": "synthetic-stop", "link_deleted": True}, now=NOW)
        self.assertTrue(incident["evidence_preserved"])
        self.assertFalse(incident["novelty_restored"])
        self.blocked("project_incident_stop")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM incidents").fetchone()[0])
            self.assertGreater(db.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 0)

    def test_dg12_translation_new_parameter_requires_technical_patent_review(self):
        self.prepare()
        current = self.current()
        current["assessment"]["support"][0]["status"] = "translation_added_parameter"
        self.journal.invalidate("release-1", current=current, now=NOW)
        self.blocked("release_invalidated", current=current)

    def test_dg13_third_party_contribution_restrictions_block(self):
        self.case["assessment"]["rights"]["f1"]["restrictions"] = ["restricted-standard-content"]
        self.case["assessment"]["rights"]["f1"]["contribution_evidence"] = ""
        self.prepare()
        self.blocked("material_rights_unresolved")

    def test_dg14_family_support_does_not_inherit_unknown_region(self):
        self.case["assessment"]["support"][1]["status"] = "unknown"
        self.prepare()
        review = self.journal.review("release-1", now=NOW)
        gaps = [i for i in review["issues"] if i["code"] == "content_or_region_support_unknown"]
        self.assertEqual([{"code": "content_or_region_support_unknown", "content_id": "c1", "target": "US"}], gaps)
        self.blocked("content_or_region_support_unknown")

    def test_dg15_defensive_publication_does_not_override_third_party_rights(self):
        assessment = self.case["assessment"]
        assessment.update(strategy="defensive", opportunities_lost=["synthetic patent opportunity"],
                          strategy_authority="synthetic-owner", patent_not_applicable={
                          "reason": "deliberate strategy", "evidence": "synthetic-decision"})
        assessment["roles_not_applicable"]["patent"] = "strategy selected separately"
        assessment["rights"]["f1"]["restrictions"] = ["third-party-not-cleared"]
        self.prepare()
        self.blocked("material_rights_unresolved")

    def test_dg16_positive_exact_package_once_and_independent_official_status(self):
        self.prepare()
        self.assertEqual("synthetic_ready", self.journal.review("release-1", now=NOW)["status"])
        output = self.journal.execute("release-1", current=self.current(), now=NOW)
        self.assertEqual("synthetic_confirmed", output["state"])
        self.assertEqual(self.case["candidate"]["manifest_hash"], output["receipt"]["manifest_hash"])
        self.assertEqual("not_asserted", output["official_status"])
        self.assertEqual("not_performed", output["external_action"])
        with self.assertRaises(core.ContractError):
            self.journal.execute("release-1", current=self.current(), now=NOW)
        self.assertEqual((1, 1), self.counts())

    def test_dg17_software_deposit_permission_does_not_authorize_public_source(self):
        for right in self.case["assessment"]["rights"].values():
            right["permissions"][0].update(action="formal_submission", purpose="software-deposit")
        self.prepare()
        self.blocked("material_action_not_authorized")
        self.assertEqual(["standard"], self.case["request"]["businesses"])

    def test_dg18_public_material_patent_na_with_reason_and_rights(self):
        assessment = self.case["assessment"]
        assessment.update(strategy="already_public", application={}, support=[], patent_not_applicable={
            "reason": "synthetic public source no protection goal", "evidence": "synthetic-public-time"})
        assessment["roles_not_applicable"]["patent"] = "no protection objective"
        self.prepare()
        output = self.journal.execute("release-1", current=self.current(), now=NOW)
        self.assertEqual("synthetic_confirmed", output["state"])
        self.assertEqual((1, 1), self.counts())

    def test_dg19_fixed_snapshot_and_sensitive_pre_read_refusal(self):
        self.prepare()
        expected = self.case["candidate"]["snapshots"]["f1"]
        self.journal.review("release-1", now=NOW)
        (self.root / "file1.txt").write_text("replacement-never-sent", encoding="utf-8")
        output = self.journal.execute("release-1", current=self.current(), now=NOW)
        with closing(sqlite3.connect(self.path)) as db:
            sent = json.loads(db.execute("SELECT snapshots FROM outbox").fetchone()[0])
        self.assertEqual(expected, sent["f1"])
        self.assertNotIn(b"replacement", base64.b64decode(sent["f1"]))
        self.assertEqual("not_performed", output["external_action"])
        context = {**self.case["context"], "sensitivity": "confidential"}
        with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(core.ContractError, "synthetic_only"):
                freeze_candidate(self.root, self.case["files"], context)

    def test_dg20_sep_and_policy_conflict_cannot_substitute_license_fto(self):
        self.case["assessment"]["policy"].update(license_status="sep_declaration_only",
            fto_status="unknown", conflicts=["mandatory_disclosure_vs_confidentiality"])
        self.prepare()
        self.blocked("sep_not_license_or_fto")
        self.blocked("policy_conflict_or_unknown")

    def test_restart_and_two_processes_execute_at_most_once(self):
        self.prepare()
        with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
            results = list(pool.map(concurrent_execute, [str(self.path)] * 2, [self.current()] * 2))
        self.assertEqual(1, results.count("synthetic_confirmed"))
        self.assertEqual(1, results.count("release_already_attempted"))
        self.assertEqual((1, 1), self.counts())

    def test_crash_before_transport_preserves_unknown_without_retry(self):
        self.prepare()
        self.journal.execute("release-1", current=self.current(), now=NOW, outcome="crash_before_transport")
        restarted = DisclosureJournal(self.path, synthetic=True)
        self.assertEqual("unknown", restarted.status("release-1")["execution"]["state"])
        with self.assertRaises(core.ContractError):
            restarted.execute("release-1", current=self.current(), now=NOW)
        self.assertEqual((1, 0), self.counts())

    def test_confirmed_not_sent_is_distinct_and_no_automatic_retry(self):
        self.prepare()
        output = self.journal.execute("release-1", current=self.current(), now=NOW, outcome="not_sent")
        self.assertEqual("confirmed_not_sent", output["state"])
        with self.assertRaises(core.ContractError):
            self.journal.execute("release-1", current=self.current(), now=NOW)
        self.assertEqual((1, 0), self.counts())

    def test_wrong_hash_recipient_execution_receipt_refused(self):
        self.prepare()
        output = self.journal.execute("release-1", current=self.current(), now=NOW, outcome="timeout")
        receipt = self.journal.simulated_receipt(output["execution_id"])
        for key in ("manifest_hash", "recipient", "execution_id", "binding"):
            with self.subTest(key=key), self.assertRaisesRegex(core.ContractError, "receipt_binding_mismatch"):
                self.journal.verify_receipt("release-1", receipt={**receipt, key: "wrong"}, evidence="fixture", now=NOW)
        self.assertEqual("unknown", self.journal.status("release-1")["execution"]["state"])
        self.assertEqual((1, 1), self.counts())

    def test_duplicate_release_does_not_overwrite_history(self):
        self.prepare()
        with self.assertRaisesRegex(core.ContractError, "duplicate_release"):
            self.journal.create_release(**{k: self.case[k] for k in ("candidate", "request", "assessment", "registry")})
        self.assertEqual((0, 0), self.counts())

    def test_rule_application_registry_permission_changes_invalidate(self):
        self.prepare()
        for target, key in (("assessment", "rules"), ("assessment", "application"),
                            ("assessment", "rights"), ("registry", "version")):
            with self.subTest(key=key):
                current = self.current()
                current[target][key] = "changed"
                changed = self.journal.invalidate("release-1", current=current, now=NOW)
                self.assertEqual("invalidated", changed["state"])
                with self.assertRaises(core.ContractError):
                    self.journal.execute("release-1", current=current, now=NOW)
                self.assertEqual((0, 0), self.counts())

    def test_conditions_must_be_proven(self):
        self.case["request"]["conditions"] = ["contract-effective"]
        self.prepare()
        self.blocked("condition_not_satisfied")

    def test_machine_cannot_sign_and_independent_cannot_be_same_actor(self):
        release = self.prepare(omit={"independent"})
        with self.assertRaisesRegex(core.ContractError, "role_not_authorized"):
            self.journal.sign("release-1", role="independent", actor_id="technical",
                evidence="fixture", binding=release["binding"], now=NOW)
        self.blocked("required_signature_missing")
        from tools.disclosure import _actor
        registry = copy.deepcopy(self.case["registry"])
        registry["actors"][0]["kind"] = "machine"
        with self.assertRaisesRegex(core.ContractError, "human_role_required"):
            _actor(registry, registry["actors"][0]["actor_id"], registry["actors"][0]["roles"][0],
                   self.case["request"], NOW)

    def test_same_actor_cannot_independently_approve_even_if_both_roles_allowed(self):
        actor = next(a for a in self.case["registry"]["actors"] if a["actor_id"] == "technical")
        actor["roles"].append("independent")
        release = self.prepare(omit={"independent"})
        self.journal.sign("release-1", role="independent", actor_id="technical",
                          evidence="synthetic", binding=release["binding"], now=NOW)
        self.blocked("independent_review_required")

    def test_rules_unavailable_alone_blocks_transport(self):
        self.case["assessment"]["rules"]["status"] = "unavailable"
        self.prepare()
        self.blocked("rules_unavailable")

    def test_proven_condition_allows_single_synthetic_execution(self):
        self.case["request"]["conditions"] = ["contract-effective"]
        self.case["assessment"]["condition_evidence"] = {
            "contract-effective": {"status": "satisfied", "evidence": "synthetic-contract"}}
        self.prepare()
        output = self.journal.execute("release-1", current=self.current(), now=NOW)
        self.assertEqual("synthetic_confirmed", output["state"])
        self.assertEqual((1, 1), self.counts())

    def test_public_not_applicable_requires_evidence(self):
        self.case["assessment"]["strategy"] = "already_public"
        self.case["assessment"]["roles_not_applicable"]["patent"] = "no patent goal"
        self.prepare()
        self.blocked("patent_na_evidence_required")

    def test_file_dependencies_rechecked_before_transport(self):
        ledger = core.VersionLedger()
        ledger.put("scope", {"version": 1})
        self.case["files"][0]["dependency_ids"] = ["scope"]
        candidate = freeze_candidate(self.root, self.case["files"], self.case["context"], ledger=ledger.export())
        self.case["candidate"] = candidate
        for key in ("joint_review", "hidden_review"):
            self.case["assessment"][key]["manifest_hash"] = candidate["manifest_hash"]
        self.prepare()
        current = self.current()
        current["dependency_hashes"] = {"scope": ledger.records["scope"][-1]["hash"]}
        self.assertEqual([], self.journal.invalidate("release-1", current=current, now=NOW)["changed"])
        ledger.put("scope", {"version": 2})
        current["dependency_hashes"]["scope"] = ledger.records["scope"][-1]["hash"]
        self.journal.invalidate("release-1", current=current, now=NOW)
        self.blocked("release_invalidated", current=current)

    def test_unauthorized_read_blocked_before_reading_bytes(self):
        context = {**self.case["context"], "permissions": []}
        with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(core.ContractError, "permission_not_proven"):
                freeze_candidate(self.root, self.case["files"], context)

    def test_path_traversal_and_stale_source_are_detected(self):
        files = copy.deepcopy(self.case["files"])
        files[0]["path"] = "../escape.txt"
        with self.assertRaisesRegex(core.ContractError, "unsafe_path"):
            freeze_candidate(self.root, files, self.case["context"])
        files[0] = {**self.case["files"][0], "expected_sha256": "0" * 64}
        candidate = freeze_candidate(self.root, files, self.case["context"])
        self.assertIn("stale_source_version", candidate["manifest"]["files"][0]["inspection"]["issues"])

    def test_json_duplicates_and_md_svg_render_gaps(self):
        self.assertIn("invalid_json", inspect_bytes("a.json", b'{"x":1,"x":2}')["issues"])
        self.assertEqual("source_checked", inspect_bytes("a.json", b'{"x":1}')["status"])
        for name, content in (("a.md", b"# Heading"), ("a.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')):
            with self.subTest(name=name):
                self.assertIn("rendering_not_checked", inspect_bytes(name, content)["issues"])
                self.assertEqual("not_checked", inspect_bytes(name, content)["rendering"])

    def test_dg06_rendering_sidecar_cannot_rewrite_fixed_inspection(self):
        content = b"# Synthetic heading"
        (self.root / "document.md").write_bytes(content)
        files = [{"file_id": "f1", "path": "document.md", "version": "1", "kind": "external",
                  "expected_sha256": core.sha256_bytes(content), "content_ids": ["c1"]}]
        candidate = freeze_candidate(self.root, files, self.case["context"])
        candidate["rendering_evidence"] = {"f1": {"status": "consistent", "issues": []}}
        self.case["candidate"] = candidate
        self.prepare()
        self.blocked("rendering_not_checked")

    def test_dg09_old_signatures_cannot_reuse_loaded_rendering_summary(self):
        self.case["candidate"]["rendering_evidence"] = {
            "f1": {"status": "blocked", "issues": ["visual_review_incomplete"]}}
        self.prepare()
        self.blocked("rendering_evidence_recheck_required")

    def test_dg03_sidecar_claims_do_not_make_tampered_snapshot_valid(self):
        candidate = copy.deepcopy(self.case["candidate"])
        candidate["rendering_evidence"] = {"f1": {"status": "consistent", "issues": []}}
        candidate["snapshots"]["f1"] = base64.b64encode(b"changed source").decode()
        with self.assertRaisesRegex(core.ContractError, "snapshot_hash_mismatch"):
            review_candidate(candidate, self.case["request"], self.case["assessment"],
                             self.case["registry"], signatures=[], now=NOW)

    def test_mutated_snapshot_or_scan_cannot_be_trusted(self):
        candidate = copy.deepcopy(self.case["candidate"])
        candidate["snapshots"]["f1"] = base64.b64encode(b"different").decode()
        with self.assertRaisesRegex(core.ContractError, "snapshot_hash_mismatch"):
            self.journal.create_release(candidate, self.case["request"], self.case["assessment"], self.case["registry"])
        self.assertEqual((0, 0), self.counts())

    def test_incident_stops_new_release_same_project(self):
        self.prepare()
        self.journal.report_incident("release-1", facts={"observed_at": NOW,
            "known_access": "synthetic", "evidence": ["fixture"], "containment_authority": "local-stop"}, now=NOW)
        request = {**self.case["request"], "release_id": "release-2"}
        with self.assertRaisesRegex(core.ContractError, "project_incident_stop"):
            self.journal.create_release(self.case["candidate"], request, self.case["assessment"], self.case["registry"])
        self.assertEqual((0, 0), self.counts())


if __name__ == "__main__":
    unittest.main()
