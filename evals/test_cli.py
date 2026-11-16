"""统一CLI真实模块集成、共享AC分支和输入/输出边界。"""
import contextlib
import copy
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import core
from tools.bundle import build_bundle
from tools.cli import CAPABILITIES, catalog, demo, dispatch, main
from evals.test_disclosure import END, NOW, START, make_case

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-cli-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def call_main(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_list_all_83_without_inflating_support(self):
        rows = catalog()
        self.assertEqual(83, len(rows))
        self.assertEqual(83, len({r["capability"] for r in rows}))
        self.assertTrue(all(r["support"] in {"synthetic_helper_only", "not_implemented"} for r in rows))
        self.assertEqual(11, len(CAPABILITIES))

    def test_missing_module_is_unavailable_not_stub(self):
        real_import = importlib.import_module
        def load(name):
            if name == "tools.software":
                raise ModuleNotFoundError(name, name=name)
            return real_import(name)
        with patch("tools.cli.importlib.import_module", side_effect=load):
            row = next(r for r in catalog() if r["capability"] == "SW-01")
            self.assertEqual("unavailable", row["availability"])
            with self.assertRaisesRegex(core.ContractError, "capability_unavailable"):
                dispatch("SW-01", {}, synthetic=True)

    def test_ac_core01_routes_three_independent_states_documented_fixture(self):
        payload = json.loads((ROOT / "evals/fixtures/shared/route.json").read_text(encoding="utf-8"))
        output = dispatch("CORE-01", payload, synthetic=True)
        tasks = output["artifacts"]["tasks"]
        self.assertEqual(["patent", "software", "standard"], [t["business"] for t in tasks])
        self.assertEqual(3, len({t["task_id"] for t in tasks}))
        self.assertTrue(all(t["disclosure_status"] == "not_authorized" for t in tasks))

    def test_ac_core02_conflicting_rights_remain_unresolved(self):
        output = dispatch("CORE-02", {"facts": [
            {"subject": "synthetic-work", "claim": "owner-a", "evidence_id": "a"},
            {"subject": "synthetic-work", "claim": "owner-b", "evidence_id": "b"}]}, synthetic=True)
        self.assertEqual("needs_evidence", output["status"])
        self.assertEqual("undetermined", output["artifacts"]["ownership"])

    def test_ac_core03_raw_versions_and_missing_pages(self):
        case = make_case(self.root)
        payload = {"root": str(self.root), "path": "file1.txt", "context": case["context"],
                   "source": {"id": "source", "version": "1", "origin": "fixture", "level": "synthetic"},
                   "locator": "line:1", "extraction_status": "missing_pages"}
        first = dispatch("CORE-03", payload, synthetic=True)["artifacts"]
        (self.root / "file1.txt").write_bytes(b"synthetic v2")
        payload["source"]["version"] = "2"
        second = dispatch("CORE-03", payload, synthetic=True)["artifacts"]
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual("missing_pages", second["extraction_status"])

    def test_ac_core04_real_journal_creation_and_no_permission_invention(self):
        case = make_case(self.root)
        arguments = {k: case[k] for k in ("candidate", "request", "assessment", "registry")}
        output = dispatch("CORE-04", {"root": str(self.root), "journal": "journal.sqlite",
                          "operation": "create", "arguments": arguments}, synthetic=True)
        self.assertEqual("draft", output["artifacts"]["state"])
        review = dispatch("CORE-04", {"root": str(self.root), "journal": "journal.sqlite",
                          "operation": "review", "arguments": {"release_id": "release-1", "now": NOW}}, synthetic=True)
        self.assertEqual("blocked", review["status"])
        self.assertIn("required_signature_missing", [i["code"] for i in review["artifacts"]["issues"]])

    def test_ac_core05_rule_scope_and_versions(self):
        rule = {"rule_id": "r1", "version": "1", "source": "fixture", "locator": "rule:1",
                "scope": {"jurisdiction": "synthetic"}, "effective_from": START, "effective_until": END,
                "verified_at": NOW, "license": "synthetic", "review_status": "unverified"}
        output = dispatch("CORE-05", {"rules": [rule], "adaptation": {"jurisdiction": "synthetic"},
                          "as_of": NOW}, synthetic=True)
        self.assertEqual("needs_review", output["status"])
        self.assertEqual(["r1"], output["artifacts"]["unresolved"])

    def test_ac_core06_dependency_change_only_invalidates_affected_reviews(self):
        payload = {"changes": [{"record_id": "f1", "payload": "v1"},
                               {"record_id": "other-project", "payload": "unrelated"}],
                   "reviews": [{"review_id": "rv1", "record_ids": ["f1"], "reviewer": {
                       "actor_id": "synthetic-human", "actor_type": "human", "authority_evidence": "fixture"},
                       "kind": "professional", "decision": "accepted"}]}
        first = dispatch("CORE-06", payload, synthetic=True)["artifacts"]
        second = dispatch("CORE-06", {"ledger": first, "changes": [{"record_id": "f1", "payload": "v2"}]},
                          synthetic=True)["artifacts"]
        self.assertEqual("invalidated", second["reviews"][0]["status"])
        self.assertEqual(first["records"]["other-project"], second["records"]["other-project"])

    def test_ac_core07_manifest_internal_report_and_stale_file(self):
        case = make_case(self.root)
        case["files"][0]["expected_sha256"] = "0" * 64
        output = dispatch("CORE-07", {"root": str(self.root), "files": case["files"],
                          "context": case["context"]}, synthetic=True)
        self.assertEqual("blocked", output["status"])
        self.assertIn("stale_source_version", [i["code"] for i in output["issues"]])
        self.assertEqual(["internal"], output["artifacts"]["manifest"]["excluded_internal_reports"])

    def test_ac_review07_clean_checker_does_not_replace_signatures(self):
        case = make_case(self.root)
        output = dispatch("REVIEW-07", {**{k: case[k] for k in
            ("candidate", "request", "assessment", "registry")}, "signatures": [], "now": NOW}, synthetic=True)
        self.assertEqual("blocked", output["status"])
        self.assertEqual("not_performed", output["professional_review"])

    def test_ac_life01_deadline_owner_missing_service_not_guessed(self):
        for business, owner in (("patent", "PROC"), ("software", "SW-06"), ("standard", "STD-09/11")):
            with self.subTest(business=business):
                output = dispatch("LIFE-01", {"event": {"business": business, "event_id": "e1",
                                  "owner": "synthetic-human", "rule_id": "r1"}}, synthetic=True)
                self.assertEqual(owner, output["artifacts"]["rule_owner"])
                self.assertIn("service_at", output["artifacts"]["missing"])
                self.assertFalse(output["artifacts"]["reminder_is_performance"])

    def test_ac_life03_changed_receiver_not_authorized_machine_not_independent(self):
        record = {"version": 1}
        payload = {"handoff": {"record_id": "r1", "version": "1", "recipient": "reviewer",
            "purpose": "synthetic-review", "owner": "author", "pending": ["review"],
            "record": record, "expected_hash": core.digest(record)}, "now": NOW,
            "permissions": [{"action": "handoff", "purpose": "synthetic-review", "recipient": "reviewer",
                "decision": "allow", "authority_evidence": "fixture", "valid_from": START, "valid_until": END}],
            "reviewers": [{"kind": "machine", "actor_id": "model", "binding": core.digest(record),
                           "authority_evidence": "fixture", "evidence": "fixture"}]}
        output = dispatch("LIFE-03", payload, synthetic=True)
        self.assertEqual("blocked", output["status"])
        payload["handoff"]["recipient"] = "other"
        with self.assertRaisesRegex(core.ContractError, "permission_not_proven"):
            dispatch("LIFE-03", payload, synthetic=True)

    def test_ac_life04_rule_changes_localized_and_unrun_tests_not_passed(self):
        rows = [{"capability": "STD-04", "adaptation": {"organization": "synthetic-A"},
                 "dependencies": ["rule-A"], "checks": [{"status": "passed", "evidence": "synthetic-test-log"}]},
                {"capability": "STD-04", "adaptation": {"organization": "synthetic-B"},
                 "dependencies": ["rule-B"], "checks": []}]
        output = dispatch("LIFE-04", {"combinations": rows, "changed_dependencies": ["rule-A"]}, synthetic=True)
        self.assertEqual(["needs_regression", "unverified"], [r["status"] for r in output["artifacts"]["combinations"]])
        self.assertFalse(output["artifacts"]["cross_combination_inheritance"])

    def regression_case(self):
        ledger = dispatch('CORE-06', {'changes': [
            {'record_id': 'rule-A', 'payload': {'revision': 1}},
            {'record_id': 'adapter-A', 'payload': {'adapter': 'synthetic'}, 'dependencies': ['rule-A']},
            {'record_id': 'case-A', 'payload': {'case': 'synthetic'}, 'dependencies': ['adapter-A']},
            {'record_id': 'rule-B', 'payload': {'revision': 1}}]}, synthetic=True)['artifacts']
        rows = [{'capability': 'STD-04', 'adaptation': {'organization': 'synthetic-A'},
                 'dependencies': ['case-A'], 'checks': [{'status': 'passed', 'evidence': 'synthetic-log-A'}]},
                {'capability': 'STD-04', 'adaptation': {'organization': 'synthetic-B'},
                 'dependencies': ['rule-B'], 'checks': [{'status': 'passed', 'evidence': 'synthetic-log-B'}]}]
        payload = {'combinations': rows, 'changed_dependencies': [], 'ledger': ledger}
        unbound = dispatch('LIFE-04', payload, synthetic=True)
        self.assertEqual(['unverified', 'unverified'],
                         [row['status'] for row in unbound['artifacts']['combinations']])
        for row, recorded in zip(rows, unbound['artifacts']['combinations']):
            row['checks'][0]['binding'] = recorded['binding']
        return payload

    def test_life04_transitive_rule_change_is_localized(self):
        payload = self.regression_case()
        before = copy.deepcopy(payload)
        initial = dispatch('LIFE-04', payload, synthetic=True)
        self.assertEqual(initial['status'], 'checked')
        self.assertEqual(payload, before)
        payload['ledger'] = dispatch('CORE-06', {'ledger': payload['ledger'], 'changes': [
            {'record_id': 'rule-A', 'payload': {'revision': 2}}]}, synthetic=True)['artifacts']
        payload['changed_dependencies'] = ['rule-A']
        output = dispatch('LIFE-04', payload, synthetic=True)
        a, b = output['artifacts']['combinations']
        self.assertEqual(a['status'], 'needs_regression')
        self.assertEqual(a['affected_dependencies'], ['rule-A'])
        self.assertEqual(a['dependency_scope'], ['adapter-A', 'case-A', 'rule-A'])
        self.assertEqual(a['stale_dependencies'], ['case-A'])
        self.assertEqual(b['status'], 'recorded_checks_passed')
        self.assertEqual(b['binding'], initial['artifacts']['combinations'][1]['binding'])
        self.assertEqual(output['professional_review'], 'not_performed')
        self.assertTrue(all(row['professional_support'] == 'unverified'
                            for row in output['artifacts']['support_table']))

    def test_life04_stale_graph_cannot_be_cleared_by_omitting_changes(self):
        payload = self.regression_case()
        payload['ledger'] = dispatch('CORE-06', {'ledger': payload['ledger'], 'changes': [
            {'record_id': 'rule-A', 'payload': {'revision': 2}}]}, synthetic=True)['artifacts']
        output = dispatch('LIFE-04', payload, synthetic=True)
        row = output['artifacts']['combinations'][0]
        self.assertEqual(row['status'], 'needs_regression')
        self.assertIn('stale_dependencies', [gap['code'] for gap in row['validation_gaps']])
        payload['combinations'][0]['checks'][0]['binding'] = row['binding']
        self.assertEqual(dispatch('LIFE-04', payload, synthetic=True)['artifacts']['combinations'][0]['status'],
                         'needs_regression')

    def test_life04_recheck_requires_rebuilt_dependencies_and_new_binding(self):
        payload = self.regression_case()
        payload['ledger'] = dispatch('CORE-06', {'ledger': payload['ledger'], 'changes': [
            {'record_id': 'rule-A', 'payload': {'revision': 2}},
            {'record_id': 'adapter-A', 'payload': {'adapter': 'synthetic'}, 'dependencies': ['rule-A']},
            {'record_id': 'case-A', 'payload': {'case': 'synthetic'}, 'dependencies': ['adapter-A']}
        ]}, synthetic=True)['artifacts']
        current = dispatch('LIFE-04', payload, synthetic=True)['artifacts']['combinations'][0]
        self.assertEqual(current['status'], 'unverified')
        self.assertIn('check_binding_mismatch', [gap['code'] for gap in current['validation_gaps']])
        self.assertEqual(current['stale_dependencies'], [])
        payload['combinations'][0]['checks'][0].update(binding=current['binding'], evidence='new-synthetic-log')
        output = dispatch('LIFE-04', payload, synthetic=True)
        self.assertEqual(output['status'], 'checked')
        self.assertEqual(len(payload['ledger']['records']['rule-A']), 2)
        self.assertEqual(output['artifacts']['combinations'][0]['evidence_verification'], 'caller_records_only')
        payload['changed_dependencies'] = ['rule-A']
        self.assertEqual(dispatch('LIFE-04', payload, synthetic=True)['artifacts']['combinations'][0]['status'],
                         'needs_regression')

    def test_life04_reverting_content_does_not_revive_old_check(self):
        payload = self.regression_case()
        before = dispatch('LIFE-04', payload, synthetic=True)['artifacts']['combinations'][0]
        payload['ledger'] = dispatch('CORE-06', {'ledger': payload['ledger'], 'changes': [
            {'record_id': 'rule-A', 'payload': {'revision': 2}},
            {'record_id': 'rule-A', 'payload': {'revision': 1}}
        ]}, synthetic=True)['artifacts']
        row = dispatch('LIFE-04', payload, synthetic=True)['artifacts']['combinations'][0]
        self.assertEqual(row['dependency_bindings'], before['dependency_bindings'])
        self.assertNotEqual(row['binding'], before['binding'])
        self.assertEqual(row['dependency_versions']['rule-A'], 3)
        self.assertEqual(row['status'], 'unverified')
        self.assertIn('check_binding_mismatch', [gap['code'] for gap in row['validation_gaps']])

    def test_life04_binding_cannot_cross_capability_or_adaptation(self):
        for changes in ({'capability': 'STD-05'}, {'adaptation': {'organization': 'synthetic-C'}}):
            with self.subTest(changes=changes):
                payload = self.regression_case()
                payload['combinations'][0].update(changes)
                row = dispatch('LIFE-04', payload, synthetic=True)['artifacts']['combinations'][0]
                self.assertEqual(row['status'], 'unverified')
                self.assertIn('check_binding_mismatch', [gap['code'] for gap in row['validation_gaps']])

    def test_life04_failed_skipped_unrun_and_empty_evidence_never_pass(self):
        for check in ({'status': 'failed', 'evidence': 'log'},
                      {'status': 'skipped', 'evidence': 'log'},
                      {'status': 'not_run', 'evidence': 'log'},
                      {'status': 'not_applicable', 'evidence': 'log'},
                      {'status': 'unknown', 'evidence': 'log'},
                      {'status': 'passed', 'evidence': ' '},
                      {'status': 'passed', 'evidence': True}):
            with self.subTest(check=check):
                payload = self.regression_case()
                payload['combinations'][0]['checks'][0].update(check)
                row = dispatch('LIFE-04', payload, synthetic=True)['artifacts']['combinations'][0]
                self.assertEqual(row['status'], 'unverified')
                self.assertTrue(row['validation_gaps'])

    def test_life04_empty_and_partial_catalog_coverage_are_explicit(self):
        output = dispatch('LIFE-04', {'combinations': [], 'changed_dependencies': []}, synthetic=True)
        self.assertEqual(output['status'], 'needs_review')
        table = output['artifacts']['support_table']
        self.assertEqual([row['capability'] for row in table], [row['capability'] for row in catalog()])
        self.assertTrue(all(row['status'] == 'not_evaluated' for row in table))
        self.assertEqual(len(output['artifacts']['unassessed_capabilities']), 83)
        output = dispatch('LIFE-04', self.regression_case(), synthetic=True)
        self.assertEqual(len(output['artifacts']['unassessed_capabilities']), 82)
        row = next(row for row in output['artifacts']['support_table'] if row['capability'] == 'STD-04')
        self.assertEqual(row['combination_indexes'], [0, 1])
        self.assertEqual(row['status'], 'recorded_combinations_only')
        self.assertEqual(output['artifacts']['assessment_scope'], 'provided_combinations_only')
        self.assertFalse(output['artifacts']['cross_combination_inheritance'])

    def test_life04_legacy_inputs_keep_declared_only_boundary(self):
        payload = {'combinations': [{'capability': 'SW-01', 'adaptation': {'jurisdiction': 'synthetic'},
                   'dependencies': ['rule'], 'checks': [{'status': 'passed', 'evidence': 'log'}]}],
                   'changed_dependencies': []}
        row = dispatch('LIFE-04', payload, synthetic=True)['artifacts']['combinations'][0]
        self.assertEqual(row['status'], 'recorded_checks_passed')
        self.assertEqual(row['dependency_verification'], 'declared_dependencies_only')
        self.assertIsNone(row['binding'])
        self.assertEqual(row['professional_support'], 'unverified')

    def test_life04_malformed_graph_and_input_rejected(self):
        base = {'combinations': [{'capability': 'STD-04', 'adaptation': {'organization': 'synthetic'},
                'dependencies': ['r1'], 'checks': []}], 'changed_dependencies': []}
        cases = [{**base, 'combinations': {}}, {**base, 'changed_dependencies': 'r1'},
                 {**base, 'ledger': []}, {**base, 'changed_dependencies': ['r1', 'r1']}]
        for field, value in (('capability', 'UNKNOWN-01'), ('adaptation', {}),
                             ('dependencies', 'r1'), ('dependencies', ['r1', 'r1']),
                             ('checks', {}), ('checks', [True])):
            cases.append({**base, 'combinations': [{**base['combinations'][0], field: value}]})
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(core.ContractError):
                dispatch('LIFE-04', payload, synthetic=True)
        payload = self.regression_case()
        payload['combinations'][0]['dependencies'] = ['missing']
        with self.assertRaisesRegex(core.ContractError, 'regression_dependency_missing'):
            dispatch('LIFE-04', payload, synthetic=True)
        payload = self.regression_case()
        payload['ledger']['records']['rule-A'][0]['payload'] = {'tampered': True}
        with self.assertRaisesRegex(core.ContractError, 'record_hash_mismatch'):
            dispatch('LIFE-04', payload, synthetic=True)

    def test_life04_real_cli_writes_version_bound_support_table(self):
        payload = self.regression_case()
        (self.root / 'regression.json').write_bytes(core.canonical_bytes(payload))
        process = subprocess.run([sys.executable, '-m', 'tools', 'run', 'LIFE-04', '--synthetic',
            '--root', str(self.root), '--input', 'regression.json', '--output', 'support.json'],
            cwd=ROOT, text=True, encoding='utf-8', capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        output = core.strict_json_loads((self.root / 'support.json').read_text(encoding='utf-8'))
        self.assertEqual(output, dispatch('LIFE-04', payload, synthetic=True))
        self.assertEqual(output['external_action'], 'not_performed')
        self.assertEqual(output['official_status'], 'not_asserted')

    def test_four_real_business_modules_payload_transmitted_unchanged(self):
        from evals.test_patent import search_payload
        from evals.test_procedure import example
        sw = json.loads((ROOT / "evals/fixtures/software/synthetic.json").read_text(encoding="utf-8"))
        std = json.loads((ROOT / "evals/fixtures/standards/cases.json").read_text(encoding="utf-8"))
        inputs = [("SEARCH-01", "tools.patent", search_payload()),
                  ("PROC-01", "tools.procedure", example("PROC-01")),
                  ("SW-01", "tools.software", {"context": sw["context"], **sw["scope_input"]}),
                  ("STD-01", "tools.standards", {**std["common"], **std["cases"]["STD-01"]})]
        for cap, module, payload in inputs:
            with self.subTest(cap=cap):
                before = copy.deepcopy(payload)
                expected = importlib.import_module(module).run(cap, payload)
                output = dispatch(cap, payload, synthetic=True)
                self.assertEqual(expected["artifacts"], output["artifacts"])
                self.assertEqual(before, payload)
                self.assertEqual("synthetic", output["mode"])
                self.assertEqual("not_asserted", output["official_status"])
                self.assertEqual("not_performed", output["external_action"])

    def test_missing_software_permission_not_automatically_added(self):
        with self.assertRaises(core.ContractError):
            dispatch("SW-01", {"context": {"environment": {}, "permissions": [],
                "sensitivity": "synthetic", "purpose": "test", "now": NOW}}, synthetic=True)

    def test_synthetic_required_before_input_read(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("must not read")):
            code, out, err = self.call_main(["run", "CORE-01", "--root", str(self.root),
                                            "--input", "secret.json", "--output", "result.json"])
        self.assertEqual((2, "", "contract_rejected\n"), (code, out, err))
        self.assertFalse((self.root / "result.json").exists())

    def test_secret_text_never_printed_on_parse_failure(self):
        (self.root / "input.json").write_text("SYNTHETIC_PRIVATE_MARKER", encoding="utf-8")
        code, out, err = self.call_main(["run", "CORE-01", "--synthetic", "--root", str(self.root),
                                        "--input", "input.json", "--output", "result.json"])
        self.assertEqual(2, code)
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", out + err)
        self.assertFalse((self.root / "result.json").exists())

    def test_path_safety_and_no_output_overwrite(self):
        (self.root / "result.json").write_text("original", encoding="utf-8")
        for output in ("result.json", "../outside.json", "C:/outside.json"):
            with self.subTest(output=output):
                code, _, _ = self.call_main(["demo", "--synthetic", "--root", str(self.root), "--output", output])
                self.assertEqual(2, code)
        self.assertEqual("original", (self.root / "result.json").read_text(encoding="utf-8"))

    def test_real_entrypoint_demo_and_run_do_not_print_material(self):
        (self.root / "input.json").write_bytes((ROOT / "evals/fixtures/shared/route.json").read_bytes())
        for args in (["demo", "--synthetic", "--root", str(self.root), "--output", "demo.json"],
                     ["run", "CORE-01", "--synthetic", "--root", str(self.root),
                      "--input", "input.json", "--output", "route.json"]):
            process = subprocess.run([sys.executable, "-m", "tools", *args], cwd=ROOT,
                                     text=True, capture_output=True, check=False)
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual("result_written\n", process.stdout)
        output = json.loads((self.root / "demo.json").read_text(encoding="utf-8"))
        self.assertEqual("synthetic_confirmed", output["execution"]["state"])
        self.assertEqual(1, output["attempts"])
        self.assertEqual("not_controlled", output["host_egress"])

    def test_sw03_document_only_handoff_and_old_scope_rejected(self):
        fixture = json.loads((ROOT / "evals/fixtures/software/synthetic.json").read_text(encoding="utf-8"))
        context = fixture["context"]
        def call(capability, **payload):
            return dispatch(capability, {"context": context, **payload}, synthetic=True)["artifacts"]
        scope = call("SW-01", **fixture["scope_input"])
        rights = call("SW-07", scope=scope, rights=fixture["rights"])
        (self.root / "counter.py").write_text(fixture["source"], encoding="utf-8")
        source = call("SW-02", scope=scope, rights_decisions=rights,
                      authorized_root=str(self.root), inventory_complete=True,
                      files=[{"id": "f1", "path": "counter.py", "component_id": "cli",
                              "kind": "source", "include": True}], pagination=fixture["pagination"])
        masked = call("SW-03", material=source, redactions=[], sensitive_literals=["count"],
                      deposit_rule={"evidence_id": "synthetic-rule", "review_evidence": "synthetic-review"})
        ledger = core.VersionLedger()
        ledger.put("scope", scope)
        ledger.put("source", source, dependencies=["scope"])
        ledger.put("masked", masked, dependencies=["source"])
        ledger.add_review("scope-review", ["scope", "masked"], reviewer={"actor_id": "synthetic-human",
                          "actor_type": "human", "authority_evidence": "synthetic-authority"},
                          kind="professional", decision="accepted")
        files = []
        for file_id, artifact in (("document", masked["document"]), ("private", masked["private_audit"]),
                                  ("source", source), ("whole", masked)):
            data = core.canonical_bytes(artifact)
            (self.root / (file_id + ".json")).write_bytes(data)
            files.append({"file_id": file_id, "path": file_id + ".json", "version": "1",
                          "expected_sha256": core.sha256_bytes(data), "kind": "external",
                          "content_ids": [file_id], "dependency_ids": ["scope", "source", "masked"]})
        for entry in files[1:]:
            output = dispatch("CORE-07", {"root": str(self.root), "context": context,
                "files": [entry], "ledger": ledger.export()}, synthetic=True)
            self.assertEqual("blocked", output["status"])
            self.assertIn("internal_artifact_not_exportable", [i["code"] for i in output["issues"]])
        good_files = [files[0], {**files[1], "kind": "internal_report"}]
        output = dispatch("CORE-07", {"root": str(self.root), "context": context,
            "files": good_files, "ledger": ledger.export()}, synthetic=True)
        self.assertEqual("needs_review", output["status"])
        self.assertEqual({"document"}, set(output["artifacts"]["snapshots"]))
        self.assertEqual(["private"], output["artifacts"]["manifest"]["excluded_internal_reports"])
        self.assertEqual({key: ledger.records[key][-1]["hash"] for key in ("scope", "source", "masked")},
                         output["artifacts"]["manifest"]["files"][0]["dependency_hashes"])
        changed = copy.deepcopy(scope)
        changed["metadata"]["version"] = "2"
        ledger.put("scope", changed)
        self.assertEqual("invalidated", ledger.reviews[0]["status"])
        with patch.object(Path, "read_bytes", side_effect=AssertionError("stale scope must not read")):
            with self.assertRaisesRegex(core.ContractError, "candidate_dependencies_stale"):
                dispatch("CORE-07", {"root": str(self.root), "context": context,
                    "files": good_files, "ledger": ledger.export()}, synthetic=True)

    def test_shared_skill_runs_from_independent_installation(self):
        installation = self.root / "installation"
        build_bundle(installation)
        for notice in ("LICENSE", "COMMERCIAL-LICENSE.md", "THIRD-PARTY-NOTICES.md"):
            self.assertEqual((ROOT / notice).read_bytes(), (installation / notice).read_bytes())
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("PYTHON")}
        skill = (installation / "skills/dyz-workbench/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: dyz-workbench\n"))
        for args in (["run", "CORE-02", "--synthetic", "--input",
                      "skills/dyz-workbench/resources/example.json", "--output", "example-result.json"],
                     ["demo", "--synthetic", "--output", "demo-result.json"]):
            process = subprocess.run([sys.executable, "-E", "-s", "-S", "-m", "tools", *args],
                                     cwd=installation, env=environment,
                                     capture_output=True, text=True, check=False)
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual("result_written\n", process.stdout)
        output = json.loads((installation / "example-result.json").read_text(encoding="utf-8"))
        self.assertEqual("needs_evidence", output["status"])
        self.assertEqual("undetermined", output["artifacts"]["ownership"])

    def test_demo_uses_only_synthetic_transport(self):
        output = demo()
        self.assertEqual("not_performed", output["external_action"])
        self.assertEqual("not_asserted", output["official_status"])
        self.assertEqual("removed_after_demo", output["temporary_journal"])


if __name__ == "__main__":
    unittest.main()
