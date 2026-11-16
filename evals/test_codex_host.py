"""Metadata-only product host checks; no actual native/model process in default tests."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from tools import codex_host as host


class ProfileSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-host-profile-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.package = self.base / "package"
        self.package.mkdir()
        self.workspace = self.base / "case"
        self.workspace.mkdir()
        self.executable = self.base / "codex.exe"
        self.executable.write_bytes(b"synthetic unit fixture, never executed")
        for name in host.SKILLS:
            path = self.package / "skills" / name / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"---\nname: {name}\ndescription: Unit fixture {name}\n---\n", encoding="utf-8")
        self.expected = host.skill_metadata(self.package)
        self.rows = [dict(r, enabled=True) for r in self.expected.values()]
        self.rows.append({"name": 'other "技能" $() `name`', "path": str(self.base / "other/SKILL.md"),
                          "description": "", "enabled": True})

    def test_exact_six_and_toml_argument_preserve_untrusted_names_without_shell(self):
        chosen = host.select_six(self.rows, self.expected)
        selectors = host.selectors_for(self.rows, chosen)
        override = host.selector_override(selectors)
        self.assertEqual(selectors, tomllib.loads(override)["skills"]["config"])
        self.assertEqual(6, sum(s["enabled"] for s in selectors))
        self.assertEqual(self.rows[-1]["name"], selectors[0]["name"])

    def test_duplicate_expected_name_in_other_package_is_not_selected(self):
        rows = self.rows + [dict(self.rows[0], path=str(self.base / "other/SKILL.md"))]
        with self.assertRaisesRegex(host.HostError, "ambiguous_or_missing"):
            host.select_six(rows, self.expected)

    def test_wrong_package_stale_description_and_disabled_expected_are_rejected(self):
        for key, value, code in (("path", str(self.base / "wrong/SKILL.md"), "wrong_package"),
                                 ("description", "stale", "description_changed"), ("enabled", False, "disabled")):
            rows = copy.deepcopy(self.rows)
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(host.HostError, code):
                host.select_six(rows, self.expected)

    def test_inventory_preserves_other_empty_description_and_reports_errors(self):
        rows, count = host.inventory_from_reply({"data": [{"cwd": str(self.workspace), "skills": self.rows,
            "errors": [{"path": "other-invalid-skill"}]}]}, self.workspace)
        self.assertEqual((self.rows, 1), (rows, count))
        for value in (None, 4, "wrong-cwd"):
            with self.subTest(cwd=value), self.assertRaises(host.HostError):
                host.inventory_from_reply({"data": [{"cwd": value, "skills": self.rows}]}, self.workspace)

    def test_inventory_duplicate_row_and_nonstrict_enabled_are_rejected(self):
        for rows in (self.rows + [self.rows[0]], [dict(self.rows[0], enabled=1)]):
            with self.subTest(rows=rows), self.assertRaises(host.HostError):
                host.inventory_from_reply({"data": [{"cwd": str(self.workspace), "skills": rows}]}, self.workspace)

    def test_unsupported_frontmatter_is_not_guessed(self):
        path = Path(next(iter(self.expected.values()))["path"])
        path.write_text("---\nname: wrong\ndescription: >\n hidden\n---\n", encoding="utf-8")
        with self.assertRaises(host.HostError):
            host.skill_metadata(self.package)

    def _create(self, inventories):
        life = {"fixture": "synthetic_unit_metadata_only", "exit_code": 0}
        with patch.object(host.bundle, "verify_bundle", return_value={"source_files": 250}), \
                patch.object(host, "digest", return_value=host.CLI_SHA256), \
                patch.object(host, "discover", side_effect=[(r, 1, life) for r in inventories]) as discover:
            result = host.create_profile(self.package, "1" * 64, self.executable, self.workspace)
        return result, discover

    def test_profile_requires_actual_scoped_enabled_flags_then_unchanged_default(self):
        scoped = [dict(r, enabled=r["name"] in host.SKILLS) for r in self.rows]
        result, discover = self._create([self.rows, scoped, self.rows])
        self.assertEqual(3, discover.call_count)
        self.assertIsNotNone(discover.call_args_list[1].kwargs["override"])
        self.assertNotIn("override", discover.call_args_list[2].kwargs)
        self.assertEqual((7, 6), (result["baseline_counts"]["enabled"], result["scoped_counts"]["enabled"]))
        self.assertFalse(result["thread_or_turn_started"])
        self.assertFalse(result["model_inference_requested"])
        self.assertEqual("not_checked", result["model_visibility_and_routing"])
        self.assertEqual("not_checked_this_tool", result["default_global_inventory"])
        self.assertEqual("not_started_or_checked_by_this_tool", result["thread_config_validation"])
        self.assertFalse(result["thread_config_candidate"]["features.plugins"])

    def test_filtered_list_alone_does_not_mask_ignored_configuration(self):
        with self.assertRaisesRegex(host.HostError, "selection_not_effective") as caught:
            self._create([self.rows, self.rows])
        self.assertEqual(7, caught.exception.observations["scoped_counts"]["enabled"])
        self.assertNotIn(self.rows[-1]["name"], json.dumps(caught.exception.observations))

    def test_default_change_does_not_produce_a_verified_profile(self):
        scoped = [dict(r, enabled=r["name"] in host.SKILLS) for r in self.rows]
        changed = copy.deepcopy(self.rows)
        changed[-1]["enabled"] = False
        with self.assertRaisesRegex(host.HostError, "baseline_inventory_changed"):
            self._create([self.rows, scoped, changed])

    def test_second_process_failure_preserves_completed_lifecycle_without_private_arguments(self):
        first = {"pid": 11111, "exit_code": 0, "argv": ["codex.exe", "fixture-private-first-argument"]}
        failed = host.HostError("fixture_native_failure", {"pid": 22222, "argv": ["codex.exe", "fixture-private-second-argument"]})
        with patch.object(host.bundle, "verify_bundle", return_value={"source_files": 250}), \
                patch.object(host, "digest", return_value=host.CLI_SHA256), \
                patch.object(host, "discover", side_effect=[(self.rows, 1, first), failed]), \
                self.assertRaisesRegex(host.HostError, "fixture_native_failure") as caught:
            host.create_profile(self.package, "1" * 64, self.executable, self.workspace)
        observations = caught.exception.observations
        self.assertEqual("scoped", observations.get("phase"))
        self.assertEqual(11111, observations["completed_processes"][0]["pid"])
        self.assertEqual(22222, observations["failed_process"]["pid"])
        self.assertNotIn("fixture-private", json.dumps(observations))

    def test_output_collision_and_package_destination_rejected_before_host_start(self):
        existing = self.base / "profile.json"
        existing.write_text("preserve", encoding="utf-8")
        for path in (existing, self.package / "new-profile.json"):
            with self.subTest(path=path), patch.object(host, "create_profile") as create, \
                    patch("sys.stdout", io.StringIO()):
                code = host.main(["--package", str(self.package), "--manifest-sha256", "1" * 64,
                    "--codex-executable", str(self.executable), "--workspace", str(self.workspace), "--output", str(path)])
                self.assertEqual(2, code)
                create.assert_not_called()
        self.assertEqual("preserve", existing.read_text(encoding="utf-8"))

    def test_direct_entry_help_from_foreign_directory_without_site_paths(self):
        result = subprocess.run([sys.executable, "-B", "-E", "-s", "-S", str(Path(host.__file__).resolve()), "--help"],
            cwd=self.base, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--codex-executable", result.stdout)
        self.assertIn("不调用模型", result.stdout)


class CaptureInput(io.BytesIO):
    def close(self):
        self.sent = self.getvalue()
        super().close()


class FakeProcess:
    pid = 12345
    returncode = 0

    def __init__(self, frames):
        self.stdin = CaptureInput()
        self.stdout = io.BytesIO(frames)
        self.stderr = io.BytesIO(json.dumps({"target": "codex_app_server_transport::transport::remote_control::websocket",
            "fields": {"message": "app-server remote control websocket loop started", "initial_desired_state": "Disabled",
                       "installation_id": "fixture-private-not-for-output", "server_name": "fixture-private-not-for-output"}}).encode() + b"\n")

    def wait(self, timeout):
        return self.returncode

    def poll(self):
        return self.returncode


class MetadataTransportTests(unittest.TestCase):
    def counter_fixture(self, *, birth=134000000000000001, handles=20, cpu=100):
        return {"status": "observed_owned_handle", "pid": 12345, "creation_filetime_100ns": birth,
                "kernel_cpu_100ns": cpu, "user_cpu_100ns": cpu, "handle_count": handles}

    def call(self, frames, process=None, *, override=None, counter_snapshots=None):
        process = process or FakeProcess(frames)
        if counter_snapshots is None:
            counter_snapshots = [self.counter_fixture(), self.counter_fixture(cpu=200), self.counter_fixture(cpu=300)]
        control = tempfile.TemporaryDirectory(prefix="dyz-host-metadata-unit-")
        self.addCleanup(control.cleanup)
        with patch.object(host, "_WINDOWS", True), patch.object(host, "digest", return_value=host.CLI_SHA256), \
                patch.object(host.tempfile, "mkdtemp", return_value=control.name), \
                patch.object(host, "native_process_counters", side_effect=counter_snapshots, create=True), \
                patch.object(host.subprocess, "Popen", return_value=process) as popen:
            result = host.discover(Path("codex.exe"), Path.cwd(), **({"override": override} if override is not None else {}))
        process.command = popen.call_args.args[0]
        process.environment = popen.call_args.kwargs["env"]
        return result, process

    def test_only_metadata_methods_are_sent_and_owned_process_exits(self):
        payload = b'{"id":1,"result":{}}\n' + json.dumps({"id": 2, "result": {
            "data": [{"cwd": str(Path.cwd()), "skills": [], "errors": []}]}}).encode() + b"\n"
        (rows, errors, lifecycle), process = self.call(payload)
        self.assertEqual(([], 0), (rows, errors))
        self.assertEqual(["initialize", "initialized", "skills/list"], [json.loads(x)["method"] for x in process.stdin.sent.splitlines()])
        self.assertTrue(lifecycle["stdin_closed_then_exit_within5s"])
        self.assertIn("features.plugins=false", process.command)
        self.assertTrue(any(x.startswith("model_catalog_json=") for x in process.command))
        self.assertFalse(lifecycle["catalog_retained"])
        self.assertFalse(Path(lifecycle["catalog_directory"]).exists())
        self.assertEqual("off,codex_app_server_transport::transport::remote_control=info", process.environment["RUST_LOG"])
        self.assertEqual({"CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED"},
            {k for k in process.environment if k.upper().startswith("CODEX_")})

    def test_server_request_eof_malformed_and_wrong_response_are_rejected(self):
        for raw in (b'{"id":8,"method":"approval/ask"}\n', b"", b"not-json\n", b'{"id":9,"result":{}}\n'):
            with self.subTest(raw=raw), self.assertRaises(host.HostError):
                self.call(raw)

    def test_frame_limit_and_nonzero_exit_are_not_accepted(self):
        with patch.object(host, "MAX_FRAME", 30), self.assertRaises(host.HostError):
            self.call(b" " * 100 + b"\n")
        process = FakeProcess(b'{"id":1,"result":{}}\n')
        process.returncode = 3
        with self.assertRaisesRegex(host.HostError, "host_exit_failed"):
            self.call(b"", process)

    def test_live_owned_process_on_timeout_is_reported_without_kill(self):
        process = FakeProcess(b"not-json\n")
        process.returncode = None
        def timeout(**kwargs):
            raise subprocess.TimeoutExpired("synthetic fixture", 5)
        process.wait = timeout
        with self.assertRaisesRegex(host.HostError, "shutdown_deadline_exceeded_pid_12345") as caught:
            self.call(b"", process)
        self.assertTrue(caught.exception.observations["catalog_retained"])
        self.assertEqual("host_rpc_reader_failed", caught.exception.observations["rpc_error"])

    def test_exit0_returning_after_deadline_is_still_rejected(self):
        clock = {"now": 0}
        payload = b'{"id":1,"result":{}}\n' + json.dumps({"id": 2, "result": {
            "data": [{"cwd": str(Path.cwd()), "skills": [], "errors": []}]}}).encode() + b"\n"
        process = FakeProcess(payload)
        def slow_wait(timeout):
            clock["now"] = 6
            return 0
        process.wait = slow_wait
        with patch.object(host.time, "monotonic", side_effect=lambda: clock["now"]), \
                self.assertRaisesRegex(host.HostError, "shutdown_deadline_exceeded") as caught:
            self.call(b"", process)
        self.assertEqual(0, caught.exception.observations["exit_code"])
        self.assertFalse(caught.exception.observations["stdin_closed_then_exit_within5s"])

    def test_environment_and_synthetic_catalog_do_not_reuse_session_or_vendor_instructions(self):
        with patch.dict(host.os.environ, {"SystemRoot": "fixture-os", "USERPROFILE": "fixture-user",
                "CODEX_HOME": "do-not-forward", "CODEX_SESSION_ID": "do-not-forward", "RUST_LOG": "trace"}, clear=True):
            self.assertEqual({"SYSTEMROOT": "fixture-os", "USERPROFILE": "fixture-user",
                "RUST_LOG": "off,codex_app_server_transport::transport::remote_control=info", "LOG_FORMAT": "json",
                "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED": "1"},
                {k.upper(): v for k, v in host.metadata_environment().items()})
        model = host.metadata_catalog()["models"][0]
        self.assertIn("not-a-real-model", model["slug"])
        self.assertEqual([], model["experimental_supported_tools"])
        self.assertFalse(model["supported_in_api"])
        self.assertEqual("disabled", model["shell_type"])

    def test_model_methods_are_not_available(self):
        rpc = object.__new__(host._MetadataRpc)
        with self.assertRaisesRegex(host.HostError, "method_not_allowed"):
            rpc.request("turn/start", {}, 1)

    def test_oversized_windows_command_is_rejected_before_process_start(self):
        with patch.object(host, "_WINDOWS", True), patch.object(host, "digest", return_value=host.CLI_SHA256), \
                patch.object(host.subprocess, "Popen") as popen, self.assertRaisesRegex(host.HostError, "command_line_too_long"):
            host.discover(Path("codex.exe"), Path.cwd(), override="skills.config=" + "x" * 40000)
        popen.assert_not_called()

    def test_unverified_runtime_rejected_before_any_process_or_temporary_catalog(self):
        with patch.object(host, "_WINDOWS", True), patch.object(host, "digest", return_value="0" * 64), \
                patch.object(host.tempfile, "mkdtemp") as directory, patch.object(host.subprocess, "Popen") as popen, \
                self.assertRaisesRegex(host.HostError, "cli_not_verified"):
            host.discover(Path("unknown-codex.exe"), Path.cwd())
        directory.assert_not_called()
        popen.assert_not_called()

    def test_remote_startup_absent_unknown_or_wrong_target_never_verifies_metadata(self):
        payload = b'{"id":1,"result":{}}\n' + json.dumps({"id": 2, "result": {
            "data": [{"cwd": str(Path.cwd()), "skills": [], "errors": []}]}}).encode() + b"\n"
        for raw in [b"", json.dumps({"target": "codex_app_server_transport::transport::remote_control::websocket",
                    "fields": {"message": "app-server remote control websocket loop started", "initial_desired_state": "Unknown"}}).encode() + b"\n",
                    json.dumps({"target": "unrelated_fixture_target", "fields": {
                        "message": "app-server remote control websocket loop started", "initial_desired_state": "Disabled"}}).encode() + b"\n"]:
            process = FakeProcess(payload)
            process.stderr = io.BytesIO(raw)
            with self.subTest(stderr=raw), self.assertRaisesRegex(host.HostError, "remote_control_startup_not_disabled"):
                self.call(b"", process)

    def test_explicit_startup_marker_is_owned_not_inherited_and_log_bodies_stay_private(self):
        marker = "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED"
        with patch.dict(host.os.environ, {"USERPROFILE": "fixture-user", marker: "0", "CODEX_SESSION_ID": "fixture-secret-session"}, clear=True):
            environment = host.metadata_environment()
        self.assertEqual("1", environment.get(marker))
        self.assertEqual("json", environment.get("LOG_FORMAT"))
        self.assertNotIn("CODEX_SESSION_ID", environment)
        payload = b'{"id":1,"result":{}}\n' + json.dumps({"id": 2, "result": {
            "data": [{"cwd": str(Path.cwd()), "skills": [], "errors": []}]}}).encode() + b"\n"
        (_, _, lifecycle), _ = self.call(payload)
        self.assertEqual(["Disabled"], lifecycle["remote_control_startup_states"])
        self.assertNotIn("fixture-private-not-for-output", json.dumps(lifecycle))
        self.assertNotIn("fixture-secret-session", json.dumps(lifecycle))

    def test_oversized_stderr_cannot_hide_behind_a_valid_disabled_event(self):
        payload = b'{"id":1,"result":{}}\n' + json.dumps({"id": 2, "result": {
            "data": [{"cwd": str(Path.cwd()), "skills": [], "errors": []}]}}).encode() + b"\n"
        process = FakeProcess(payload)
        process.stderr = io.BytesIO(b"x" * 70000 + b"\n" + process.stderr.getvalue())
        with self.assertRaisesRegex(host.HostError, "remote_control_startup_not_disabled"):
            self.call(b"", process)

    def test_failed_scoped_lifecycle_does_not_disclose_selector_names_in_diagnostics(self):
        process = FakeProcess(b'{"id":1,"result":{}}\n')
        process.returncode = 3
        with self.assertRaises(host.HostError) as caught:
            self.call(b"", process, override='skills.config=[{name="fixture-private-skill-name",enabled=false}]')
        observations = caught.exception.observations
        self.assertNotIn("fixture-private-skill-name", json.dumps(observations))
        self.assertNotIn("argv", observations)
        self.assertEqual(64, len(observations["argv_sha256"]))

    def test_birth_and_resource_observations_survive_success_and_timeout(self):
        payload = b'{"id":1,"result":{}}\n' + json.dumps({"id": 2, "result": {
            "data": [{"cwd": str(Path.cwd()), "skills": [], "errors": []}]}}).encode() + b"\n"
        (_, _, lifecycle), _ = self.call(payload)
        self.assertTrue(lifecycle["native_identity_verified"])
        self.assertEqual(134000000000000001, lifecycle["native_process_counters"]["spawn"]["creation_filetime_100ns"])
        self.assertEqual(200, lifecycle["native_process_counters"]["stdin_closed"]["kernel_cpu_100ns"])
        process = FakeProcess(payload)
        process.returncode = None
        def timeout(**kwargs):
            raise subprocess.TimeoutExpired("synthetic timeout", 5)
        process.wait = timeout
        with self.assertRaisesRegex(host.HostError, "shutdown_deadline_exceeded") as caught:
            self.call(b"", process)
        observations = caught.exception.observations
        self.assertTrue(observations["native_identity_verified"])
        self.assertEqual(300, observations["native_process_counters"]["after_wait"]["kernel_cpu_100ns"])
        self.assertNotIn("argv", observations)

    def test_changed_native_birth_cannot_produce_verified_metadata(self):
        payload = b'{"id":1,"result":{}}\n' + json.dumps({"id": 2, "result": {
            "data": [{"cwd": str(Path.cwd()), "skills": [], "errors": []}]}}).encode() + b"\n"
        snapshots = [self.counter_fixture(), self.counter_fixture(), self.counter_fixture(birth=134000000000000002)]
        with self.assertRaisesRegex(host.HostError, "host_native_identity_unverified") as caught:
            self.call(payload, counter_snapshots=snapshots)
        self.assertFalse(caught.exception.observations["native_identity_verified"])

    def test_missing_native_birth_closes_without_sending_metadata_requests(self):
        process = FakeProcess(b"")
        missing = {"status": "unavailable", "reason": "native_handle_unavailable"}
        with self.assertRaisesRegex(host.HostError, "host_native_identity_unverified") as caught:
            self.call(b"", process, counter_snapshots=[missing, missing, missing])
        self.assertTrue(process.stdin.closed)
        self.assertEqual(b"", process.stdin.sent)
        self.assertEqual([], caught.exception.observations["rpc_stages"])
        self.assertFalse(caught.exception.observations["native_identity_verified"])

    def test_unavailable_handle_count_is_explicit_and_does_not_forge_zero(self):
        payload = b'{"id":1,"result":{}}\n' + json.dumps({"id": 2, "result": {
            "data": [{"cwd": str(Path.cwd()), "skills": [], "errors": []}]}}).encode() + b"\n"
        sample = self.counter_fixture()
        del sample["handle_count"]
        sample.update(handle_count_status="unavailable", handle_count_winerror=5)
        (_, _, lifecycle), _ = self.call(payload, counter_snapshots=[dict(sample) for _ in range(3)])
        self.assertTrue(lifecycle["native_identity_verified"])
        self.assertNotIn("handle_count", lifecycle["native_process_counters"]["after_wait"])
        self.assertEqual("unavailable", lifecycle["native_process_counters"]["after_wait"]["handle_count_status"])


class NativeCounterApiTests(unittest.TestCase):
    def test_mismatched_handle_identity_is_not_reopened_by_pid(self):
        import ctypes
        process = Mock(pid=12345, _handle=99999)
        api = Mock()
        api.GetProcessId.return_value = 54321
        with patch.object(host, "_WINDOWS", True), patch.object(ctypes, "WinDLL", return_value=api, create=True):
            result = host.native_process_counters(process)
        self.assertEqual({"status": "unavailable", "reason": "native_handle_pid_mismatch"}, result)
        api.GetProcessTimes.assert_not_called()
        api.OpenProcess.assert_not_called()

    def test_exit_between_times_query_and_poll_does_not_publish_undefined_exit_time(self):
        import ctypes
        process = Mock(pid=12345, _handle=99999, returncode=None)
        process.poll.side_effect = lambda: process.returncode
        api = Mock()
        api.GetProcessId.return_value = 12345
        def read_times(handle, creation, exited, kernel, user):
            creation._obj.dwHighDateTime = 1
            creation._obj.dwLowDateTime = 9
            kernel._obj.dwLowDateTime = 8
            user._obj.dwLowDateTime = 7
            # The process was live when times were sampled; its zeroed exit buffer is undefined.
            process.returncode = 0
            return True
        api.GetProcessTimes.side_effect = read_times
        api.GetProcessHandleCount.return_value = False
        with patch.object(host, "_WINDOWS", True), patch.object(ctypes, "WinDLL", return_value=api, create=True):
            result = host.native_process_counters(process)
        self.assertEqual("observed_owned_handle", result["status"])
        self.assertEqual(4294967305, result["creation_filetime_100ns"])
        self.assertNotIn("exit_filetime_100ns", result)
        self.assertNotIn("handle_count", result)
        self.assertEqual("unavailable", result["handle_count_status"])


if __name__ == "__main__":
    unittest.main()
