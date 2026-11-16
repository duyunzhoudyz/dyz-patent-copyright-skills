"""字段集中确认的合成反例；不认证确认人身份、证据真实性或专业签核。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import software
from tools.core import ContractError, digest, sha256_bytes


class SoftwareFactsTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "software" / "synthetic.json"
        self.fixture = json.loads(fixture.read_text(encoding="utf-8"))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source_path = self.root / "counter.py"
        self.source_path.write_text(self.fixture["source"], encoding="utf-8")
        self.args = {
            "context": copy.deepcopy(self.fixture["context"]),
            "authorized_root": str(self.root),
            "scope_input": copy.deepcopy(self.fixture["scope_input"]),
            "rights": copy.deepcopy(self.fixture["rights"]),
            "files": [{"id": "f1", "path": "counter.py", "component_id": "cli",
                       "kind": "source", "include": True}],
            "inventory_complete": True, "pagination": self.fixture["pagination"],
            "manual_input": copy.deepcopy(self.fixture["manual_input"]),
            "form_rule_evidence": "synthetic-form-rule",
        }

    def prepare(self, **changes):
        return software.prepare(self.args | changes)

    def candidate(self, field="name", value="集中确认名称", status="candidate", **changes):
        return {"field": field, "value": value, "status": status,
                "sources": [{"evidence_id": "synthetic-source", "locator": "fact-1"}],
                **changes}

    def confirmation(self, worksheet, candidate):
        return {"candidate_digest": digest(candidate), "input_binding": worksheet["input_binding"],
                "status": "confirmed", "actor": "synthetic-user", "role": "fact_provider",
                "evidence_id": "synthetic-explicit-confirmation"}

    def reviewed(self, candidate=None):
        candidate = self.candidate() if candidate is None else candidate
        first = self.prepare(field_candidates=[candidate])["artifacts"]
        self.assertIn("worksheet", first, "prepare must return a reviewable worksheet")
        return candidate, first, self.confirmation(first["worksheet"], candidate)

    def candidate_row(self, worksheet, candidate):
        return next(row for row in worksheet["rows"]
                    if row.get("candidate_digest") == digest(candidate))

    def test_legacy_form_gets_declared_rows_not_automatic_confirmation(self):
        output = self.prepare()
        self.assertIn("worksheet", output["artifacts"],
                      "legacy inputs must still produce pending field questions")
        sheet = output["artifacts"]["worksheet"]
        self.assertEqual(sheet["kind"], "software_field_worksheet")
        self.assertEqual({row["field"] for row in sheet["rows"]},
                         {"software_id", "name", "version", "completed_date",
                          "published_date", "runtime_environment"})
        self.assertTrue(all(row["status"] == "declared" for row in sheet["rows"]))
        self.assertTrue(all(not row["applied"] for row in sheet["rows"]))
        self.assertEqual(len(sheet["questions"]), 6)
        self.assertEqual(sheet["binding"], digest({k: v for k, v in sheet.items() if k != "binding"}))
        self.assertEqual(output["status"], "needs_review")
        self.assertEqual(output["professional_review"], "not_performed")

    def test_no_candidate_preserves_unknown_dates(self):
        self.args["scope_input"]["metadata"]["completed_date"] = None
        result = self.prepare()["artifacts"]
        self.assertIn("worksheet", result)
        row = next(row for row in result["worksheet"]["rows"] if row["field"] == "completed_date")
        self.assertIsNone(row["value"])
        self.assertEqual(row["status"], "unknown")
        self.assertIsNone(result["form"]["completed_date"])

    def test_unconfirmed_inference_never_overwrites_form_or_scope(self):
        baseline = self.prepare()["artifacts"]
        candidate = self.candidate(status="inferred")
        result = self.prepare(field_candidates=[candidate])["artifacts"]
        for name in ("form", "scope", "rights", "source", "manual"):
            self.assertEqual(result[name], baseline[name])
        row = self.candidate_row(result["worksheet"], candidate)
        self.assertEqual(row["status"], "inferred")
        self.assertFalse(row["applied"])
        self.assertEqual(row["reason"], "field_confirmation_required")

    def test_confirmed_field_only_updates_form_and_retains_scope_mismatch(self):
        candidate, before, confirmation = self.reviewed()
        frozen = copy.deepcopy((self.args, candidate, confirmation, before))
        output = self.prepare(field_candidates=[candidate], confirmations=[confirmation],
                              previous_preparation=before)
        result = output["artifacts"]
        self.assertEqual(result["form"]["name"], candidate["value"])
        for name in ("scope", "rights", "source", "manual"):
            self.assertEqual(result[name], before[name])
        row = self.candidate_row(result["worksheet"], candidate)
        self.assertEqual(row["status"], "confirmed")
        self.assertTrue(row["applied"])
        self.assertEqual(row["confirmation"], confirmation)
        self.assertIn("field_mismatch:name", {item["code"] for item in output["issues"]})
        self.assertEqual({item["artifact"] for item in result["changes"]},
                         {"form", "consistency", "worksheet"})
        self.assertEqual((self.args, candidate, confirmation, before), frozen)
        self.assertEqual(output["professional_review"], "not_performed")
        self.assertEqual(output["official_status"], "not_asserted")

    def test_unknown_and_conflict_cannot_be_confirmed_into_values(self):
        for candidate in (self.candidate(status="conflict"),
                          self.candidate(status="unknown", value=None, sources=[])):
            with self.subTest(status=candidate["status"]):
                candidate, before, confirmation = self.reviewed(candidate)
                output = self.prepare(field_candidates=[candidate], confirmations=[confirmation])
                result = output["artifacts"]
                self.assertEqual(result["form"], before["form"])
                row = self.candidate_row(result["worksheet"], candidate)
                self.assertEqual(row["status"], candidate["status"])
                self.assertFalse(row["applied"])
                self.assertEqual(output["status"], "partial")

    def test_multiple_distinct_values_are_conflicts_even_if_one_is_confirmed(self):
        first, second = self.candidate(), self.candidate(value="另一名称")
        before = self.prepare(field_candidates=[first, second])["artifacts"]
        confirmation = self.confirmation(before["worksheet"], first)
        result = self.prepare(field_candidates=[first, second], confirmations=[confirmation])["artifacts"]
        self.assertEqual(result["form"], before["form"])
        for candidate in (first, second):
            self.assertEqual(self.candidate_row(result["worksheet"], candidate)["status"], "conflict")

    def test_changed_source_invalidates_confirmation_without_reusing_it(self):
        candidate, before, confirmation = self.reviewed()
        self.source_path.write_text("print('same-version new bytes')\n", encoding="utf-8")
        output = self.prepare(field_candidates=[candidate], confirmations=[confirmation],
                              previous_preparation=before)
        result = output["artifacts"]
        self.assertNotEqual(result["worksheet"]["input_binding"], before["worksheet"]["input_binding"])
        self.assertEqual(result["form"]["name"], before["form"]["name"])
        self.assertEqual(self.candidate_row(result["worksheet"], candidate)["reason"],
                         "field_confirmation_stale")
        affected = {row["artifact"] for row in result["changes"]}
        self.assertTrue({"source", "manual", "form", "worksheet"} <= affected)
        self.assertNotIn("rights", affected)
        self.assertNotIn("screenshots", affected)
        self.assertEqual(result["manual"]["source_binding"], result["source"]["binding"])

    def test_changed_facts_version_or_form_invalidates_confirmation(self):
        candidate, before, confirmation = self.reviewed()
        for section in ("facts", "version", "form", "rule", "limits"):
            with self.subTest(section=section):
                args = copy.deepcopy(self.args)
                if section == "facts":
                    args["manual_input"]["facts"][0]["text"] = "另一个有待核验的事实"
                elif section == "version":
                    args["scope_input"]["metadata"]["version"] = "2.0"
                elif section == "form":
                    args["form"] = {**before["form"], "name": "调用者直接改名"}
                elif section == "rule":
                    args["form_rule_evidence"] = "changed-rule"
                else:
                    args["field_limits"] = {"name": 200}
                result = software.prepare(args | {"field_candidates": [candidate],
                                                 "confirmations": [confirmation]})["artifacts"]
                row = self.candidate_row(result["worksheet"], candidate)
                self.assertFalse(row["applied"])
                self.assertEqual(row["reason"], "field_confirmation_stale")

    def test_changed_candidate_or_sources_cannot_reuse_confirmation(self):
        candidate, before, confirmation = self.reviewed()
        for changed in (candidate | {"value": "换值"},
                        candidate | {"sources": [{"evidence_id": "synthetic-source", "locator": "different"}]}):
            with self.subTest(changed=changed):
                output = self.prepare(field_candidates=[changed], confirmations=[confirmation])
                result = output["artifacts"]
                self.assertEqual(result["form"], before["form"])
                self.assertFalse(self.candidate_row(result["worksheet"], changed)["applied"])
                self.assertIn("field_confirmation_candidate_missing", {row["code"] for row in output["issues"]})
                self.assertEqual(result["worksheet"]["unmatched_confirmations"], [confirmation])

    def test_valid_source_hash_is_checked_against_actual_manifest(self):
        candidate = self.candidate(sources=[{"path": "counter.py",
                                           "sha256": sha256_bytes(self.source_path.read_bytes()),
                                           "locator": "L1-L3"}])
        candidate, before, confirmation = self.reviewed(candidate)
        result = self.prepare(field_candidates=[candidate], confirmations=[confirmation])["artifacts"]
        self.assertTrue(self.candidate_row(result["worksheet"], candidate)["applied"])
        self.source_path.write_text("changed\n", encoding="utf-8")
        current = self.prepare(field_candidates=[candidate])["artifacts"]
        refreshed = self.confirmation(current["worksheet"], candidate)
        result = self.prepare(field_candidates=[candidate], confirmations=[refreshed])["artifacts"]
        self.assertFalse(self.candidate_row(result["worksheet"], candidate)["applied"])
        self.assertEqual(self.candidate_row(result["worksheet"], candidate)["reason"], "field_source_stale")
        self.assertEqual(result["form"]["name"], before["form"]["name"])

    def test_unknown_evidence_and_unlisted_file_cannot_fill_or_trigger_extra_reads(self):
        for source in ({"evidence_id": "nonexistent-evidence", "locator": "p1"},
                       {"path": "not-authorized.py", "sha256": "0" * 64, "locator": "L1"}):
            candidate = self.candidate(sources=[source])
            candidate, before, confirmation = self.reviewed(candidate)
            real_open, opened = Path.open, []

            def tracked_open(path, *args, **kwargs):
                opened.append(path.name)
                return real_open(path, *args, **kwargs)

            with patch.object(Path, "open", tracked_open):
                result = self.prepare(field_candidates=[candidate], confirmations=[confirmation])["artifacts"]
            self.assertEqual(opened, ["counter.py"])
            self.assertEqual(result["form"], before["form"])
            self.assertEqual(self.candidate_row(result["worksheet"], candidate)["reason"], "field_source_unavailable")

    def test_invalid_candidate_shapes_fail_before_source_read(self):
        candidates = [self.candidate(field=field) for field in (
            "total_source_lines", "selected_source_lines", "original_source_lines", "rights",
            "permissions", "scope", "components", "facts", "name.value", "__dict__")]
        candidates += [self.candidate(status="confirmed"), self.candidate(sources=[]),
                       self.candidate(value={"unexpected": "object"}),
                       self.candidate(status="unknown", value="not unknown"),
                       self.candidate(actor="inline confirmation"),
                       self.candidate(field="completed_date", value={"value": "2026-02-31", "evidence_id": "e"}),
                       self.candidate(field="runtime_environment", value={"description": "env", "evidence_id": ""})]
        for source in ({"path": "../secret", "sha256": "0" * 64, "locator": "L1"},
                       {"path": "C:/secret", "sha256": "0" * 64, "locator": "L1"},
                       {"path": "counter.py", "sha256": "bad", "locator": "L1"},
                       {"path": "counter.py", "sha256": "0" * 64},
                       {"evidence_id": "synthetic-source", "locator": "", "extra": "secret"}):
            candidates.append(self.candidate(sources=[source]))
        for candidate in candidates:
            with self.subTest(candidate=candidate), patch.object(Path, "open") as opened:
                with self.assertRaises(ContractError):
                    self.prepare(field_candidates=[candidate])
                opened.assert_not_called()

    def test_invalid_confirmation_shapes_fail_before_source_read(self):
        candidate, _, confirmation = self.reviewed()
        cases = [confirmation | {"status": "approved"}, confirmation | {"candidate_digest": "bad"},
                 confirmation | {"input_binding": "bad"}, confirmation | {"actor": ""},
                 confirmation | {"role": ""}, confirmation | {"evidence_id": ""},
                 confirmation | {"value": "override"}]
        cases += [{k: v for k, v in confirmation.items() if k != field}
                  for field in ("actor", "role", "evidence_id", "candidate_digest", "input_binding")]
        for item in cases:
            with self.subTest(item=item), patch.object(Path, "open") as opened:
                with self.assertRaises(ContractError):
                    self.prepare(field_candidates=[candidate], confirmations=[item])
                opened.assert_not_called()

    def test_candidate_and_confirmation_lists_are_strict(self):
        candidate, _, confirmation = self.reviewed()
        for changes in ({"field_candidates": {}}, {"confirmations": {}},
                        {"field_candidates": [None]}, {"confirmations": [None]},
                        {"field_candidates": [candidate, candidate]},
                        {"field_candidates": [candidate], "confirmations": [confirmation, confirmation]}):
            with self.subTest(changes=changes), patch.object(Path, "open") as opened:
                with self.assertRaises(ContractError):
                    self.prepare(**changes)
                opened.assert_not_called()

    def test_same_preparation_is_stable_and_old_format_upgrades_without_screenshot_invalidation(self):
        first = self.prepare()["artifacts"]
        self.assertIn("worksheet", first)
        self.assertEqual(self.prepare(previous_preparation=first)["artifacts"], first)
        old = {k: v for k, v in first.items()
               if k not in {"binding", "worksheet", "dependencies", "changes"}}
        old["manual"] = {k: v for k, v in old["manual"].items() if k not in {"binding", "source_binding"}}
        old["manual"]["binding"] = digest(old["manual"])
        old["binding"] = digest(old)
        frozen = copy.deepcopy(old)
        upgraded = self.prepare(previous_preparation=old)["artifacts"]
        self.assertEqual(upgraded["supersedes"], old["binding"])
        self.assertIn("worksheet", {row["artifact"] for row in upgraded["changes"]})
        self.assertNotIn("screenshots", {row["artifact"] for row in upgraded["changes"]})
        self.assertEqual(old, frozen)
        self.assertEqual(self.prepare(previous_preparation=upgraded)["artifacts"], upgraded)

    def test_form_change_does_not_invalidate_unchanged_screenshots(self):
        self.args["manual_input"]["mode"] = "GUI"
        self.args["manual_input"]["runtime_evidence"] = [
            {"id": "shot-1", "version": "1.0", "evidence_id": "synthetic-shot", "kind": "screenshot"}]
        candidate, before, confirmation = self.reviewed()
        result = self.prepare(field_candidates=[candidate], confirmations=[confirmation],
                              previous_preparation=before)["artifacts"]
        self.assertEqual(result["manual"]["screenshots"], before["manual"]["screenshots"])
        self.assertEqual(result["dependencies"]["screenshots"], before["dependencies"]["screenshots"])
        self.assertNotIn("screenshots", {row["artifact"] for row in result["changes"]})

    def test_current_issues_are_bound_into_preparation_for_artifact_only_handoff(self):
        candidate = self.candidate(status="conflict")
        baseline = self.prepare()["artifacts"]
        form = {**baseline["form"], "version": "different-version"}
        output = self.prepare(form=form, field_candidates=[candidate])
        artifact = output["artifacts"]
        self.assertIn("issues", artifact, "artifact-only delivery must retain current blockers")
        codes = {issue["code"] for issue in artifact["issues"]}
        self.assertIn("field_mismatch:version", codes)
        self.assertIn("field_conflict_unresolved", codes)
        self.assertEqual(artifact["issues"], output["issues"])
        self.assertEqual(artifact["binding"], digest({key: value for key, value in artifact.items()
                                                   if key != "binding"}))
        self.assertEqual(json.loads(json.dumps(artifact))["issues"], output["issues"])

    def test_bound_issues_exclude_history_and_old_snapshot_upgrades_stably(self):
        first = self.prepare()["artifacts"]
        self.assertIn("issues", first)
        legacy = {key: value for key, value in first.items() if key not in {"issues", "binding"}}
        legacy["binding"] = digest(legacy)
        frozen = copy.deepcopy(legacy)
        output = self.prepare(previous_preparation=legacy)
        current = output["artifacts"]
        self.assertIn("previous_preparation_invalidated", {issue["code"] for issue in output["issues"]})
        self.assertNotIn("previous_preparation_invalidated", {issue["code"] for issue in current["issues"]})
        self.assertEqual(current["issues"], first["issues"])
        self.assertEqual(current["supersedes"], legacy["binding"])
        repeated = self.prepare(previous_preparation=current)
        self.assertEqual(repeated["artifacts"], current)
        self.assertEqual(repeated["issues"], current["issues"])
        self.assertEqual(legacy, frozen)

    def test_changed_rights_have_localized_dependencies(self):
        before = self.prepare()["artifacts"]
        self.args["rights"][0]["evidence_ids"].append("synthetic-additional-basis")
        result = self.prepare(previous_preparation=before)["artifacts"]
        self.assertIn("changes", result)
        affected = {row["artifact"] for row in result["changes"]}
        self.assertTrue({"rights", "source", "manual", "form", "worksheet"} <= affected)
        self.assertNotIn("screenshots", affected)


if __name__ == "__main__":
    unittest.main()
