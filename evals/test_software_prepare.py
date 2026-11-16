"""获准本地软件准备入口；资料、许可和秘密哨兵均为临时合成数据。"""

import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools import core
from tools.cli import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals/fixtures/software/synthetic.json"


class SoftwarePrepareCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-software-prepare-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.fixture["source"].encode("utf-8")
        (self.root / "counter.py").write_bytes(self.source)
        self.request = {
            "scope_input": self.fixture["scope_input"], "rights": self.fixture["rights"],
            "files": [{"id": "f1", "path": "counter.py", "component_id": "cli",
                       "kind": "source", "include": True}],
            "inventory_complete": True, "pagination": self.fixture["pagination"],
            "manual_input": self.fixture["manual_input"],
            "form_rule_evidence": "synthetic-not-official-rule",
        }
        now = datetime.now(timezone.utc)
        permission = {"purpose": "software_internal_preparation", "recipient": "local_tool",
                      "decision": "allow", "authority_evidence": "synthetic-authority-only",
                      "valid_from": (now - timedelta(days=1)).isoformat(),
                      "valid_until": (now + timedelta(days=1)).isoformat()}
        self.authorization = {
            "kind": "software_local_authorization", "authorized_root": str(self.root),
            "context": {"sensitivity": "synthetic", "purpose": permission["purpose"],
                        "environment": {}, "permissions": [
                            {**permission, "action": "local_read"},
                            {**permission, "action": "local_write"}]},
            "request": {"path": "request.json", "sha256": ""},
            "files": [{"path": "counter.py", "sha256": core.sha256_bytes(self.source)}],
            "output": "prepared.json",
        }
        self.save_request()

    def save_request(self):
        content = core.canonical_bytes(self.request)
        (self.root / "request.json").write_bytes(content)
        self.authorization["request"]["sha256"] = core.sha256_bytes(content)

    def args(self):
        content = core.canonical_bytes(self.authorization)
        (self.root / "authorization.json").write_bytes(content)
        return ["prepare-software", "--root", str(self.root),
                "--authorization", "authorization.json",
                "--authorization-sha256", core.sha256_bytes(content)]

    def invoke(self, args=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args if args is not None else self.args())
        return code, out.getvalue(), err.getvalue()

    def result(self):
        return core.strict_json_loads((self.root / "prepared.json").read_text(encoding="utf-8"))

    def assert_rejected(self, args=None):
        code, out, err = self.invoke(args)
        self.assertEqual((code, out, err), (2, "", "contract_rejected\n"))
        self.assertFalse((self.root / "prepared.json").exists())

    def test_command_is_registered_without_changing_synthetic_run(self):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            with self.assertRaises(SystemExit) as caught:
                main(["prepare-software", "--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--authorization-sha256", stream.getvalue())
        self.assertNotIn("--synthetic", stream.getvalue())

    def test_actual_cli_prepares_same_version_internal_bundle(self):
        process = subprocess.run([sys.executable, "-B", "-m", "tools", *self.args()],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, "result_written\n")
        output = self.result()
        self.assertEqual(output["mode"], "authorized_local_preparation")
        self.assertEqual(output["host_egress"], "not_controlled")
        self.assertEqual(output["external_action"], "not_performed")
        self.assertEqual(output["official_status"], "not_asserted")
        pack = output["artifacts"]
        self.assertEqual(pack["kind"], "software_preparation")
        self.assertEqual(pack["source"]["selected_source_lines"], 3)
        self.assertEqual(pack["source"]["source_coverage"]["status"], "complete")
        self.assertEqual(pack["form"]["name"], pack["scope"]["metadata"]["name"])
        self.assertIn("命令操作流程", pack["manual"]["markdown"])
        self.assertEqual((self.root / "counter.py").read_bytes(), self.source)

    def test_copied_package_runs_without_checkout_imports(self):
        from tools.bundle import build_bundle
        installation = self.root / "installation"
        build_bundle(installation)
        process = subprocess.run([sys.executable, "-B", "-E", "-s", "-S", "-m", "tools", *self.args()],
                                 cwd=installation, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(self.result()["artifacts"]["kind"], "software_preparation")

    def test_internal_pack_is_not_exportable_by_existing_inspector(self):
        from tools.disclosure import inspect_bytes
        code, _, err = self.invoke()
        self.assertEqual(code, 0, err)
        inspected = inspect_bytes("prepared.json", (self.root / "prepared.json").read_bytes())
        self.assertIn("internal_artifact_not_exportable", inspected["issues"])

    def test_confidential_path_requires_all_six_assessments(self):
        self.authorization["context"]["sensitivity"] = "confidential"
        args = self.args()
        opened = []
        original = Path.open
        def track(path, *values, **kwargs):
            opened.append(path.name)
            return original(path, *values, **kwargs)
        with patch.object(Path, "open", track):
            self.assert_rejected(args)
        self.assertEqual(opened, ["authorization.json"])

    def test_confidential_and_restricted_use_evidenced_paths(self):
        for sensitivity in ("confidential", "restricted"):
            with self.subTest(sensitivity=sensitivity):
                self.authorization["output"] = sensitivity + ".json"
                self.authorization["context"].update(sensitivity=sensitivity, environment={
                    "assessment_evidence": "synthetic-path-assessment",
                    "data_paths": [{"id": key, "verified": True, "mode": "local",
                                    "evidence": "synthetic-path-evidence"} for key in
                                   ("host_model", "index", "telemetry", "tools", "logs", "subprocess")]})
                code, _, err = self.invoke()
                self.assertEqual(code, 0, err)
                output = core.strict_json_loads((self.root / (sensitivity + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(output["sensitivity"], sensitivity)
                self.assertEqual(output["professional_review"], "not_performed")

    def test_external_host_processing_needs_separate_permission(self):
        self.authorization["context"].update(sensitivity="confidential", environment={
            "assessment_evidence": "synthetic-assessment",
            "data_paths": [{"id": key, "verified": True,
                            "mode": "external" if key == "host_model" else "local",
                            "evidence": "synthetic-evidence"} for key in
                           ("host_model", "index", "telemetry", "tools", "logs", "subprocess")]})
        self.assert_rejected()

    def test_no_read_or_write_permission_rejects_before_request(self):
        for action in ("local_read", "local_write"):
            with self.subTest(action=action):
                old = self.authorization["context"]["permissions"]
                self.authorization["context"]["permissions"] = [p for p in old if p["action"] != action]
                args = self.args()
                original = Path.open
                def guarded(path, *values, **kwargs):
                    self.assertEqual(path.name, "authorization.json")
                    return original(path, *values, **kwargs)
                with patch.object(Path, "open", guarded):
                    self.assert_rejected(args)
                self.authorization["context"]["permissions"] = old

    def test_expired_permission_cannot_use_forged_past_now(self):
        self.authorization["context"]["now"] = "2000-01-02T00:00:00Z"
        for permission in self.authorization["context"]["permissions"]:
            permission.update(valid_from="2000-01-01T00:00:00Z", valid_until="2000-01-03T00:00:00Z")
        self.assert_rejected()

    def test_permission_expiry_during_preparation_prevents_write(self):
        now = datetime.now(timezone.utc)
        with patch("tools.cli.datetime") as clock:
            clock.now.side_effect = [now, now, now + timedelta(days=3)]
            self.assert_rejected()

    def test_permission_expiry_during_inventory_prevents_request_read(self):
        now = datetime.now(timezone.utc)
        args = self.args()
        original = Path.open
        def guarded(path, *values, **kwargs):
            self.assertEqual(path.name, "authorization.json")
            return original(path, *values, **kwargs)
        with patch("tools.cli.datetime") as clock, patch.object(Path, "open", guarded):
            clock.now.side_effect = [now, now + timedelta(days=3)]
            self.assert_rejected(args)

    def test_symlink_loop_error_is_sanitized_in_actual_process(self):
        filename = "SYNTHETIC_PRIVATE_PATH.json"
        link = self.root / filename
        try:
            link.symlink_to(link)
        except OSError as exc:
            self.skipTest(f"symlink unavailable: {type(exc).__name__}")
        args = ["prepare-software", "--root", str(self.root), "--authorization", filename,
                "--authorization-sha256", "0" * 64]
        process = subprocess.run([sys.executable, "-B", "-m", "tools", *args], cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (2, "", "contract_rejected\n"))
        self.assertNotIn(filename, process.stdout + process.stderr)

    def test_extreme_timezone_error_is_sanitized_in_actual_process(self):
        self.authorization["context"]["permissions"][0]["valid_from"] = "0001-01-01T00:00:00+01:00"
        process = subprocess.run([sys.executable, "-B", "-m", "tools", *self.args()], cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (2, "", "contract_rejected\n"))

    def test_authorization_size_limit_rejects_before_request(self):
        args = self.args()
        content = core.canonical_bytes({**self.authorization, "padding": "x" * 1_000_001})
        (self.root / "authorization.json").write_bytes(content)
        args[-1] = core.sha256_bytes(content)
        original = Path.open
        def guarded(path, *values, **kwargs):
            self.assertEqual(path.name, "authorization.json")
            return original(path, *values, **kwargs)
        with patch.object(Path, "open", guarded):
            self.assert_rejected(args)

    def test_authorization_hash_mismatch_reads_nothing_else(self):
        args = self.args()
        args[-1] = "0" * 64
        original = Path.open
        def guarded(path, *values, **kwargs):
            self.assertEqual(path.name, "authorization.json")
            return original(path, *values, **kwargs)
        with patch.object(Path, "open", guarded):
            self.assert_rejected(args)

    def test_changed_request_does_not_read_sources(self):
        args = self.args()
        (self.root / "request.json").write_text('{"SYNTHETIC_PRIVATE_MARKER": true}', encoding="utf-8")
        original = Path.open
        def guarded(path, *values, **kwargs):
            self.assertNotEqual(path.name, "counter.py")
            return original(path, *values, **kwargs)
        with patch.object(Path, "open", guarded):
            self.assert_rejected(args)

    def test_changed_source_rejected_without_output_or_payload_in_logs(self):
        (self.root / "counter.py").write_text("SYNTHETIC_PRIVATE_MARKER", encoding="utf-8")
        self.assert_rejected()

    def test_unapproved_file_and_duplicate_authorization_rejected(self):
        self.request["files"][0]["path"] = "not-approved.py"
        self.save_request()
        self.assert_rejected()
        self.request["files"][0]["path"] = "counter.py"
        self.save_request()
        self.authorization["files"].append(copy.deepcopy(self.authorization["files"][0]))
        self.assert_rejected()

    def test_omitting_authorized_file_is_not_complete_inventory(self):
        self.authorization["files"].append({"path": "omitted.py", "sha256": "0" * 64})
        self.assert_rejected()

    def test_public_context_still_requires_local_permissions(self):
        self.authorization["context"]["sensitivity"] = "public"
        code, _, err = self.invoke()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.result()["sensitivity"], "public")

    def test_request_expected_hash_cannot_override_authorized_hash(self):
        self.request["files"][0]["expected_sha256"] = "0" * 64
        self.save_request()
        self.assert_rejected()

    def test_root_output_and_input_boundaries(self):
        original = copy.deepcopy(self.authorization)
        for key, value in (("authorized_root", str(self.root.parent)),
                           ("output", "../outside.json"), ("output", "prepared.txt"),
                           ("output", "request.json"),
                           ("output", "counter.py"), ("output", "authorization.json")):
            with self.subTest(key=key, value=value):
                self.authorization = copy.deepcopy(original)
                self.authorization[key] = value
                self.assert_rejected()

    def test_symlink_outside_root_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="dyz-software-outside-") as folder:
            outside = Path(folder) / "outside.py"
            outside.write_bytes(self.source)
            try:
                (self.root / "linked.py").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {type(exc).__name__}")
            self.request["files"][0]["path"] = "linked.py"
            self.authorization["files"][0]["path"] = "linked.py"
            self.save_request()
            self.assert_rejected()

    def test_request_cannot_override_preflight_scope_or_selection(self):
        for key, value in (("context", {"sensitivity": "synthetic"}),
                           ("authorized_root", str(self.root.parent)),
                           ("selection_purpose", "public"), ("require_complete_source", False)):
            with self.subTest(key=key):
                self.request[key] = value
                self.save_request()
                self.assert_rejected()
                del self.request[key]

    def test_partial_draft_retains_unknown_dates_and_missing_manual(self):
        self.request["scope_input"]["metadata"]["completed_date"] = None
        del self.request["manual_input"]
        self.save_request()
        code, _, err = self.invoke()
        self.assertEqual(code, 0, err)
        output = self.result()
        self.assertEqual(output["status"], "partial")
        self.assertIsNone(output["artifacts"]["form"]["completed_date"])
        self.assertIsNone(output["artifacts"]["manual"])
        self.assertIn("manual_input_missing", {item["code"] for item in output["issues"]})

    def test_repeated_output_is_not_overwritten(self):
        code, _, err = self.invoke()
        self.assertEqual(code, 0, err)
        original = (self.root / "prepared.json").read_bytes()
        code, out, err = self.invoke()
        self.assertEqual((code, out, err), (2, "", "contract_rejected\n"))
        self.assertEqual((self.root / "prepared.json").read_bytes(), original)

    def test_parse_failure_and_duplicate_keys_never_expose_material(self):
        for content in (b'SYNTHETIC_PRIVATE_MARKER', b'{"files":[],"files":[]}'):
            with self.subTest(content=content):
                (self.root / "request.json").write_bytes(content)
                self.authorization["request"]["sha256"] = core.sha256_bytes(content)
                self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
