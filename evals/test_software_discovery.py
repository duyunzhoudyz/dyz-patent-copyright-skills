"""候选发现及一次集中确认的合成回归，不使用私人软件或外部服务。"""

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools import core, software, software_discovery as discovery, software_intake


class SoftwareDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dyz-discovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        now = datetime.now(timezone.utc)
        self.context = {
            "environment": {"assessment_evidence": "synthetic-assessment",
                            "data_paths": [{"id": key, "mode": "local", "verified": True,
                                            "evidence": "synthetic-measurement"}
                                           for key in software_intake.DATA_PATHS]},
            "permissions": [{"action": action, "purpose": software_intake.PURPOSE,
                             "recipient": "local_tool", "decision": "allow",
                             "authority_evidence": "synthetic-authority",
                             "valid_from": (now - timedelta(hours=1)).isoformat(),
                             "valid_until": (now + timedelta(hours=1)).isoformat()}
                            for action in ("local_read", "local_write")],
            "sensitivity": "confidential", "purpose": software_intake.PURPOSE,
            "now": now.isoformat(),
        }
        (self.root / "中文 目录").mkdir()
        (self.root / "中文 目录/main.py").write_text("def count(values):\n    return len(values)\n",
                                                         encoding="utf-8")
        (self.root / "package.json").write_text(json.dumps({
            "name": "package-name-not-legal-name", "version": "1.0",
            "description": "按列表统计数量", "engines": {"node": ">=20"},
        }), encoding="utf-8")

    def payload(self, paths=None):
        paths = paths or ["中文 目录/main.py", "package.json"]
        return {"context": copy.deepcopy(self.context), "authorized_root": str(self.root),
                "files": [{"id": f"file-{index}", "path": path, "component_id": "main"}
                          for index, path in enumerate(paths, start=1)],
                "material_permissions": [{"paths": paths, "decision": "allow",
                                          "evidence_id": "synthetic-local-evidence"}]}

    def request(self, payload):
        return {
            "context": copy.deepcopy(self.context), "authorized_root": str(self.root),
            "scope_input": {"metadata": {"software_id": "demo", "name": "合成软件",
                                          "version": "1.0", "completed_date": None,
                                          "published_date": None, "runtime_environment": None},
                            "components": [{"id": "main", "kind": "standalone", "version": "1.0",
                                            "origin": "own", "origin_evidence": "synthetic-origin",
                                            "claim": ["计数表达"], "exclusions": [],
                                            "subjects": []}]},
            "rights": [{"component_id": "main", "requested_decision": "claim",
                        "evidence_ids": ["synthetic-local-evidence"],
                        "permissions": {"local_process": "allow", "deposit": "allow",
                                        "public": "deny", "cloud": "deny"}}],
            "files": [{**entry, "kind": "source" if entry["path"].endswith(".py") else "other",
                       "include": entry["path"].endswith(".py")}
                      for entry in payload["files"]], "inventory_complete": False,
            "pagination": {"selection": "all", "lines_per_page": 50, "wrap_columns": 78,
                           "basis": "synthetic-only"},
        }

    def test_explicit_relative_unicode_paths_are_rooted_independently_of_cwd(self):
        payload = self.payload()
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as elsewhere:
            try:
                os.chdir(elsewhere)
                result = discovery.discover(payload)
            finally:
                os.chdir(previous)
        self.assertEqual([row["path"] for row in result["file_candidates"]],
                         ["中文 目录/main.py", "package.json"])
        for row in result["file_candidates"]:
            self.assertEqual(row["sha256"], core.sha256_bytes((self.root / row["path"]).read_bytes()))
        name = next(row for row in result["field_candidates"] if row["field"] == "name")
        self.assertEqual(name["status"], "inferred")
        self.assertEqual(name["sources"][0]["locator"], "$.name")
        self.assertTrue(all(row["needs_confirm"] for row in result["facts"]))
        self.assertEqual(result["professional_review"], "not_performed")
        self.assertFalse((self.root / "materials").exists())

    def test_context_and_every_file_permission_precede_any_read(self):
        for case in ("context", "deny", "unknown", "evidence", "conflict", "rights"):
            with self.subTest(case=case):
                payload = self.payload()
                if case == "context":
                    payload["context"]["environment"]["data_paths"][0]["mode"] = "unknown"
                elif case == "evidence":
                    payload["material_permissions"][0]["evidence_id"] = ""
                elif case == "conflict":
                    payload["material_permissions"].append({"paths": ["package.json"],
                                                            "decision": "deny", "evidence_id": "deny"})
                elif case == "rights":
                    payload["request"] = self.request(payload)
                    payload["request"]["rights"][0]["permissions"]["local_process"] = "deny"
                else:
                    payload["files"][-1]["local_permission"] = {"decision": case, "evidence_id": "e"}
                with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                    with self.assertRaises(core.ContractError):
                        discovery.discover(payload)

    def test_all_paths_validate_before_first_read_and_no_directory_scanning(self):
        for paths in (["中文 目录/main.py", "../outside.py"],
                      ["中文 目录/main.py", "absent.py"],
                      ["中文 目录/main.py", "中文 目录/main.py"]):
            with self.subTest(paths=paths):
                with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                    with self.assertRaises(core.ContractError):
                        discovery.discover(self.payload(paths))
        with patch.object(Path, "rglob", side_effect=AssertionError("scan forbidden")), \
                patch.object(Path, "iterdir", side_effect=AssertionError("scan forbidden")):
            result = discovery.discover(self.payload(["中文 目录/main.py"]))
        self.assertEqual(len(result["file_candidates"]), 1)

    def test_secret_values_and_sensitive_files_are_not_returned_or_opened(self):
        secret = "SYNTHETIC_PRIVATE_VALUE"
        (self.root / "package.json").write_text(json.dumps({"name": secret, "version": "1",
                                                            "description": "password=" + secret}),
                                               encoding="utf-8")
        (self.root / ".env").write_text(secret, encoding="utf-8")
        payload = self.payload(["package.json", ".env"])
        payload["sensitive_literals"] = [secret]
        original = Path.open
        opened = []
        def tracked(path, *args, **kwargs):
            opened.append(path.name)
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", tracked):
            result = discovery.discover(payload)
        self.assertEqual(opened, ["package.json"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result["file_candidates"][-1]["read_status"], "not_read")

    def test_unknown_dates_ownership_and_runtime_not_inferred_from_timestamps(self):
        result = discovery.discover(self.payload(["中文 目录/main.py"]))
        fields = {row["field"]: row for row in result["field_candidates"]}
        for field in ("completed_date", "published_date", "runtime_environment"):
            self.assertEqual(fields[field]["status"], "unknown")
            self.assertIsNone(fields[field]["value"])
        self.assertNotIn("ownership", fields)
        self.assertIn("Python", fields["programming_language"]["value"]["value"])

    def test_package_readme_conflicts_are_explicit_and_not_eligible(self):
        (self.root / "README.md").write_text("# 另一个名称\n版本：2.0\n", encoding="utf-8")
        payload = self.payload(["package.json", "README.md", "中文 目录/main.py"])
        artifact = discovery.discover(payload)
        for field in ("name", "version"):
            rows = [row for row in artifact["field_candidates"] if row["field"] == field]
            self.assertEqual({row["status"] for row in rows}, {"conflict"})
        group = discovery.confirmation_group({"request": self.request(payload),
                                              "discovery": artifact})
        forbidden = {row["candidate_digest"] for row in group["rows"]
                     if row["field"] in {"name", "version"}}
        self.assertFalse(forbidden.intersection(group["eligible_candidates"]))

    def test_same_configuration_fact_merges_evidence_instead_of_false_conflict(self):
        (self.root / "app.json").write_text('{"version":"1.0"}', encoding="utf-8")
        payload = self.payload(["package.json", "app.json"])
        artifact = discovery.discover(payload)
        versions = [row for row in artifact["field_candidates"] if row["field"] == "version"]
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["status"], "candidate")
        self.assertEqual(len(versions[0]["sources"]), 2)
        group = discovery.confirmation_group({"request": self.request(payload), "discovery": artifact})
        self.assertTrue(any(row["field"] == "version" and row["candidate_digest"]
                            in group["eligible_candidates"] for row in group["rows"]))

    def test_intake_single_group_records_actual_selected_confirmation(self):
        payload = self.payload()
        payload["request"] = self.request(payload)
        def ask(prompt):
            if "一次选择" in prompt:
                return "3"  # 第三项为 package.json 的 version 候选。
            if "实际核对人的标识" in prompt:
                return "synthetic-fact-reviewer"
            if "实际核对人的角色" in prompt:
                return "operator"
            if "集中确认的实际依据" in prompt:
                return "synthetic-confirmation-record"
            return "yes"
        summary = software_intake.collect_candidates(self.root, "confirmed", payload=payload, ask=ask)
        authorization = core.strict_json_loads((self.root / summary["authorization"]).read_text("utf-8"))
        request = core.strict_json_loads((self.root / authorization["request"]["path"]).read_text("utf-8"))
        self.assertEqual(len(request["confirmations"]), 1)
        self.assertEqual(request["confirmations"][0]["actor"], "synthetic-fact-reviewer")
        request.pop("delivery")
        result = software.prepare({**request, "context": authorization["context"],
                                   "authorized_root": str(self.root)})
        self.assertTrue(any(row["applied"] for row in result["artifacts"]["worksheet"]["rows"]))

    def test_configuration_variants_include_hash_and_locator(self):
        fixtures = {
            "app.json": '{"expo":{"name":"示例应用","version":"1.0"}}',
            "project.config.json": '{"projectname":"示例项目"}',
            "pyproject.toml": '[project]\nname="python-package"\nversion="1.0"\nrequires-python=">=3.11"\n',
        }
        for name, content in fixtures.items():
            (self.root / name).write_text(content, encoding="utf-8")
        artifact = discovery.discover(self.payload(list(fixtures)))
        sources = [source for row in artifact["field_candidates"] for source in row["sources"]]
        self.assertEqual({source["path"] for source in sources}, set(fixtures))
        self.assertTrue(all(len(source["sha256"]) == 64 and source["locator"] for source in sources))

    def test_group_requires_actual_bound_confirmation_and_preserves_old_contract(self):
        payload = self.payload()
        artifact = discovery.discover(payload)
        group = discovery.confirmation_group({"request": self.request(payload), "discovery": artifact,
                                              "options": {"selection": "all"}})
        self.assertNotIn("confirmations", group["request"])
        self.assertTrue(group["eligible_candidates"])
        decision = {"group_binding": group["binding"], "summary_digest": group["summary_digest"],
                    "input_binding": group["input_binding"], "status": "confirmed",
                    "actor": "synthetic-operator", "role": "fact-reviewer", "evidence_id": "actual-record",
                    "candidate_digests": group["eligible_candidates"]}
        confirmed = discovery.confirm_group(group, decision)
        prepared = software.prepare(confirmed["request"])["artifacts"]
        self.assertTrue(any(row["applied"] for row in prepared["worksheet"]["rows"]))
        self.assertIsNone(prepared["scope"]["metadata"]["completed_date"])
        for key in ("group_binding", "summary_digest", "input_binding"):
            invalid = {**decision, key: "0" * 64}
            with self.assertRaisesRegex(core.ContractError, "confirmation_group_stale"):
                discovery.confirm_group(group, invalid)
        self.assertEqual(confirmed["options"], {"selection": "all"})

    def test_stale_bytes_cross_project_and_undeclared_file_reject(self):
        payload = self.payload()
        artifact = discovery.discover(payload)
        request = self.request(payload)
        with tempfile.TemporaryDirectory() as elsewhere:
            foreign = {**request, "authorized_root": elsewhere}
            with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                with self.assertRaisesRegex(core.ContractError, "discovery_project_mismatch"):
                    discovery.confirmation_group({"request": foreign, "discovery": artifact})
        (self.root / "extra.py").write_text("extra=1\n", encoding="utf-8")
        unknown = copy.deepcopy(request)
        unknown["files"].append({"id": "extra", "path": "extra.py", "component_id": "main",
                                 "kind": "source", "include": True})
        with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
            with self.assertRaisesRegex(core.ContractError, "confirmation_source_not_discovered"):
                discovery.confirmation_group({"request": unknown, "discovery": artifact})
        (self.root / "package.json").write_text('{"version":"2"}', encoding="utf-8")
        with self.assertRaisesRegex(core.ContractError, "source_hash_mismatch"):
            discovery.confirmation_group({"request": request, "discovery": artifact})

    def test_intake_payload_saves_bound_request_without_materials_or_fabricated_confirmation(self):
        payload = self.payload()
        payload["request"] = self.request(payload)
        prompts = []
        def ask(prompt):
            prompts.append(prompt)
            return "" if "一次选择" in prompt else "yes"
        summary = software_intake.collect_candidates(self.root, "候选 请求", payload=payload, ask=ask)
        authorization = core.strict_json_loads((self.root / summary["authorization"]).read_text("utf-8"))
        request = core.strict_json_loads((self.root / authorization["request"]["path"]).read_text("utf-8"))
        self.assertEqual(core.sha256_bytes((self.root / summary["authorization"]).read_bytes()),
                         summary["authorization_sha256"])
        self.assertNotIn("confirmations", request)
        self.assertNotIn("manual_input", request)
        self.assertIsNone(request["scope_input"]["metadata"]["completed_date"])
        self.assertFalse((self.root / authorization["output"]).exists())
        request.pop("delivery")
        prepared = software.prepare({**request, "context": authorization["context"],
                                     "authorized_root": str(self.root)})
        self.assertEqual(prepared["status"], "partial")
        self.assertEqual(len([prompt for prompt in prompts if "一次选择" in prompt]), 1)

    def test_interactive_intake_does_not_require_internal_json_or_manual_facts(self):
        context_answers = ["confidential", "synthetic-assessment"]
        for key in software_intake.DATA_PATHS:
            context_answers.extend(["local", "synthetic-measurement-" + key])
        permissions = self.context["permissions"][0]
        context_answers.extend(["yes", "yes", "synthetic-authority",
                                permissions["valid_from"], permissions["valid_until"]])
        answers = iter(context_answers + ["中文 目录/main.py", "package.json", "",
                                          "合成软件全称", "1.0", "CLI", "own", "synthetic-origin",
                                          "allow", "unknown", "synthetic-unified-license", "unknown",
                                          "", "yes", ""])
        prompts = []
        def ask(prompt):
            prompts.append(prompt)
            return next(answers)
        summary = software_intake.collect_candidates(self.root, "interactive", ask=ask)
        self.assertTrue((self.root / summary["authorization"]).is_file())
        self.assertEqual(len([prompt for prompt in prompts if "一次选择" in prompt]), 1)
        self.assertFalse(any("事实的证据" in prompt or "expected_output" in prompt for prompt in prompts))

    def test_intake_refusal_secret_prompt_and_change_during_confirmation(self):
        for case in ("refuse", "secret", "change"):
            with self.subTest(case=case):
                payload = self.payload()
                payload["request"] = self.request(payload)
                payload["sensitive_literals"] = ["SYNTHETIC_PRIVATE"]
                payload["request"]["scope_input"]["metadata"]["name"] = "SYNTHETIC_PRIVATE"
                prompts = []
                def ask(prompt):
                    prompts.append(prompt)
                    if case == "refuse":
                        return "no"
                    if "一次选择" in prompt:
                        if case == "change":
                            (self.root / "package.json").write_text('{"version":"2"}', encoding="utf-8")
                        return ""
                    return "yes"
                if case in {"refuse", "change"}:
                    with self.assertRaises(core.ContractError):
                        software_intake.collect_candidates(self.root, case, payload=payload, ask=ask)
                    self.assertFalse((self.root / case).exists())
                else:
                    software_intake.collect_candidates(self.root, case, payload=payload, ask=ask)
                self.assertNotIn("SYNTHETIC_PRIVATE", "".join(prompts))

    def test_intake_cross_project_request_rejects_before_read(self):
        payload = self.payload()
        payload["request"] = self.request(payload)
        with tempfile.TemporaryDirectory() as foreign:
            payload["request"]["authorized_root"] = foreign
            with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                with self.assertRaisesRegex(core.ContractError, "discovery_project_mismatch"):
                    software_intake.collect_candidates(self.root, "foreign", payload=payload,
                                                        ask=lambda prompt: "yes")
        self.assertFalse((self.root / "foreign").exists())

    def test_intake_payload_denied_has_zero_reads_and_zero_output(self):
        payload = self.payload()
        payload["request"] = self.request(payload)
        payload["files"][-1]["local_permission"] = {"decision": "deny", "evidence_id": "deny"}
        with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
            with self.assertRaises(core.ContractError):
                software_intake.collect_candidates(self.root, "intake", payload=payload,
                                                    ask=lambda prompt: "yes")
        self.assertFalse((self.root / "intake").exists())


if __name__ == "__main__":
    unittest.main()
