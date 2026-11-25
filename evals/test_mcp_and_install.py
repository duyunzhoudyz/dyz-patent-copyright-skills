"""Phase A tests: pure-stdlib MCP stdio server, multi-host installer, and unpinned host probe."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import subprocess
import stat
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import bundle, codex_host, install, mcp_server
from tools.host_bridge import HostToolBridge

ROOT = Path(__file__).resolve().parents[1]


def _frame_content_length(payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _initialize_params(version="2024-11-05"):
    return {"protocolVersion": version, "clientInfo": {"name": "synthetic-client"}, "capabilities": {}}


class McpServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.group = tempfile.TemporaryDirectory(prefix="dyz-mcp-test-")
        cls.base = Path(cls.group.name).resolve()
        cls.package = cls.base / "package"
        bundle.build_bundle(cls.package, source_root=ROOT)
        cls.manifest_sha = hashlib.sha256((cls.package / bundle.MANIFEST_NAME).read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.group.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name).resolve()
        self.workspace = self.case / "workspace"
        self.control = self.case / "control"
        (self.workspace / "input").mkdir(parents=True)
        self.control.mkdir()
        (self.workspace / "input" / "note.txt").write_text("SYNTHETIC-mcp-line-1\nline-2\n", encoding="utf-8")

    def test_mcp_ndjson_lifecycle_catalog_and_bounded_bridge_calls(self):
        bridge = HostToolBridge(self.package, self.workspace, self.control, self.manifest_sha)
        server = mcp_server.McpServer(bridge)
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": _initialize_params()},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "dyz_catalog", "arguments": {"domain": "SW"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
                "name": "case_read", "arguments": {"scope": "workspace", "path": "input/note.txt"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
                "name": "case_write", "arguments": {"path": "work/out.md", "text": "hello mcp\n"}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
                "name": "case_read", "arguments": {"scope": "workspace", "path": "../escape.txt"}}},
        ]
        stdin = io.BytesIO(b"".join((json.dumps(m) + "\n").encode("utf-8") for m in messages))
        stdout = io.BytesIO()
        rc = server.serve(stdin, stdout)
        self.assertEqual(0, rc)
        replies = [json.loads(line) for line in stdout.getvalue().decode("utf-8").splitlines()]
        self.assertEqual(7, len(replies))
        self.assertEqual("dyz-patent-copyright-skills", replies[0]["result"]["serverInfo"]["name"])
        self.assertEqual({}, replies[1]["result"])
        tool_names = [t["name"] for t in replies[2]["result"]["tools"]]
        self.assertIn("dyz_catalog", tool_names)
        self.assertIn("case_read", tool_names)
        self.assertEqual(11, len(tool_names))
        cat = json.loads(replies[3]["result"]["content"][0]["text"])
        self.assertEqual(8, cat["count"])
        self.assertEqual("synthetic_helper_only", cat["capability_support"])
        read_res = json.loads(replies[4]["result"]["content"][0]["text"])
        self.assertTrue(read_res["success"])
        self.assertEqual("SYNTHETIC-mcp-line-1", read_res["result"]["lines"][0]["text"])
        self.assertFalse(replies[5]["result"]["isError"])
        self.assertEqual("hello mcp\n", (self.workspace / "work/out.md").read_text(encoding="utf-8"))
        # Path traversal must be rejected
        self.assertTrue(replies[6]["result"]["isError"])
        self.assertEqual("unsafe_path", json.loads(replies[6]["result"]["content"][0]["text"])["error"])

    def test_mcp_content_length_framing_and_catalog_only_subprocess(self):
        wire = (
            _frame_content_length({"jsonrpc": "2.0", "id": "init", "method": "initialize",
                                   "params": _initialize_params("2025-03-26")})
            + _frame_content_length({"jsonrpc": "2.0", "method": "notifications/initialized"})
            + _frame_content_length({"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
            + _frame_content_length({"jsonrpc": "2.0", "id": "bad", "method": "tools/call", "params": {"name": "case_read", "arguments": {}}})
        )
        proc = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(self.package / "tools" / "mcp_server.py"), "--catalog-only"],
            cwd=self.case,
            input=wire,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        stream = io.BytesIO(proc.stdout)
        r1, f1 = mcp_server.read_mcp_message(stream)
        r2, f2 = mcp_server.read_mcp_message(stream)
        r3, f3 = mcp_server.read_mcp_message(stream)
        self.assertEqual(("content-length", "content-length", "content-length"), (f1, f2, f3))
        self.assertEqual("2025-03-26", r1["result"]["protocolVersion"])
        self.assertEqual(["dyz_catalog"], [t["name"] for t in r2["result"]["tools"]])
        self.assertTrue(r3["result"]["isError"])

    def test_print_config_and_describe(self):
        proc = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(ROOT / "tools" / "mcp_server.py"), "--print-config", "--host", "claude-code"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        cfg = json.loads(proc.stdout)
        self.assertEqual("claude-code", cfg["host"])
        self.assertIn("dyz-patent-copyright-skills", cfg["mcpServers"])
        self.assertIn('-I', cfg['mcpServers']['dyz-patent-copyright-skills']['args'])
        with self.assertRaisesRegex(ValueError, 'invalid_case_bridge_config'):
            mcp_server.render_client_config(host='codex', python_executable='python3', package_path=str(self.package),
                                            workspace_path=str(self.workspace))

    def test_framing_rejects_invalid_headers_and_json_with_matching_error_frame(self):
        nested = b'{"value":' + b'[' * 1500 + b']' * 1500 + b'}'
        cases = (
            (b'Content-Length: 2\ncontent-length: 2\n\n{}', 'content-length'),
            (b'Content-Length: 1_0\n\n', 'content-length'),
            (b'Content-Length: +10\n\n', 'content-length'),
            (b'Content-Length: 2\n' + b'X-Extra: a\n' * 32 + b'\n{}', 'content-length'),
            (b'Content-Length: 2\nX-Extra: ' + b'a' * 8192 + b'\n\n{}', 'content-length'),
            (b'Content-Length: 2\nX-Extra: missing newline', 'content-length'),
            (b'Content-Length: 3\n\n{}', 'content-length'),
            (f'Content-Length: {len(nested)}\n\n'.encode() + nested, 'content-length'),
            (nested + b'\n', 'ndjson'),
            (b'{"text":"\xff"}\n', 'ndjson'),
        )
        for raw, expected in cases:
            with self.subTest(framing=expected, length=len(raw)):
                output = io.BytesIO()
                self.assertEqual(2, mcp_server.McpServer().serve(io.BytesIO(raw), output))
                reply, framing = mcp_server.read_mcp_message(io.BytesIO(output.getvalue()))
                self.assertEqual(expected, framing)
                self.assertEqual(-32700, reply['error']['code'])
                self.assertNotIn(b'Traceback', output.getvalue())
        with patch.object(mcp_server.json, 'loads', side_effect=RecursionError('private implementation context')):
            with self.assertRaisesRegex(ValueError, '^invalid_json$'):
                mcp_server.read_mcp_message(io.BytesIO(b'{}\n'))

    def test_tools_require_initialize_request_and_notifications_cannot_write(self):
        bridge = HostToolBridge(self.package, self.workspace, self.control, self.manifest_sha)
        server = mcp_server.McpServer(bridge)
        base = {'jsonrpc': '2.0'}
        write = {**base, 'method': 'tools/call', 'params': {'name': 'case_write',
                                                           'arguments': {'path': 'work/notice.md', 'text': 'synthetic'}}}
        self.assertIsNone(server.handle({**base, 'method': 'initialize'}))
        self.assertIsNone(server.handle({**base, 'method': 'notifications/initialized'}))
        self.assertEqual(-32002, server.handle({**base, 'id': 1, 'method': 'tools/list'})['error']['code'])
        self.assertEqual(-32002, server.handle({**write, 'id': 2})['error']['code'])
        for invalid_id in (True, False, None, 1.5, [], {}):
            self.assertEqual(-32600, server.handle({**base, 'method': 'initialize', 'id': invalid_id})['error']['code'])
        self.assertFalse(server.initialized)
        self.assertIn('result', server.handle({**base, 'id': 0, 'method': 'initialize', 'params': _initialize_params()}))
        ready = {**base, 'method': 'notifications/initialized'}
        for invalid_notice in ({**ready, 'id': 9}, {**ready, 'jsonrpc': '1.0'}, {**ready, 'params': []}):
            server.handle(invalid_notice)
        self.assertFalse(server.initialized)
        expected = {'code': -32002, 'message': 'server_not_initialized'}
        self.assertEqual(expected, server.handle({**base, 'id': 3, 'method': 'tools/list'})['error'])
        self.assertEqual(expected, server.handle({**write, 'id': 4})['error'])
        output = io.BytesIO()
        self.assertEqual(0, server.serve(io.BytesIO(_frame_content_length(write)), output))
        self.assertEqual(b'', output.getvalue())
        self.assertFalse((self.workspace / 'work/notice.md').exists())
        self.assertEqual([], bridge.calls)
        self.assertIsNone(server.handle(ready))
        self.assertIn('result', server.handle({**base, 'id': 5, 'method': 'tools/list'}))
        self.assertFalse(server.handle({**write, 'id': 6})['result']['isError'])
        self.assertEqual('synthetic', (self.workspace / 'work/notice.md').read_text(encoding='utf-8'))

    def test_handshake_blocks_all_requests_except_ping_and_keeps_negotiated_version(self):
        server = mcp_server.McpServer()
        request = {"jsonrpc": "2.0", "id": 1}
        self.assertEqual({}, server.handle({**request, "method": "ping"})["result"])
        for method in ("resources/list", "prompts/list", "unrecognized", "tools/list"):
            with self.subTest(method=method):
                blocked = server.handle({**request, "method": method, "params": []})
                self.assertEqual({"code": -32002, "message": "server_not_initialized"}, blocked["error"])
        params = _initialize_params("2025-06-18")
        params["clientInfo"] = {"name": "测试客户端", "version": "2026.1"}
        initialized = server.handle({**request, "method": "initialize", "params": params})
        self.assertEqual("2025-06-18", initialized["result"]["protocolVersion"])
        for params in (_initialize_params(), []):
            duplicate = server.handle({**request, "method": "initialize", "params": params})
            self.assertEqual({"code": -32600, "message": "already_initialized"}, duplicate["error"])
            self.assertEqual("2025-06-18", server.protocol_version)
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(-32601, server.handle({**request, "method": "resources/list"})["error"]["code"])

    def test_invalid_initialize_params_keep_tools_unavailable(self):
        params = _initialize_params()
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        for invalid in (None, {}, [], "wrong", {"protocolVersion": params["protocolVersion"]},
                        {**params, "clientInfo": {}}, {**params, "clientInfo": {"name": "  "}},
                        {**params, "clientInfo": {"name": 42}}, {**params, "capabilities": []},
                        {**params, "protocolVersion": ""}, {**params, "protocolVersion": 20241105},
                        {**params, "protocolVersion": "2026-99-01"},
                        *({**params, "clientInfo": {"name": value}} for value in ("client\u200b", "client\x01", "\ud800")),
                        *({**params, "clientInfo": {"name": "client", "version": value}}
                          for value in (None, 42, "", " ", "1\u200b", "1\x01", "\ud800")),
                        {k: v for k, v in params.items() if k != "protocolVersion"},
                        {k: v for k, v in params.items() if k != "capabilities"}):
            with self.subTest(params=invalid):
                server = mcp_server.McpServer()
                reply = server.handle({**request, "params": invalid})
                self.assertEqual(-32602, reply["error"]["code"])
                self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
                self.assertFalse(server.initialized)
                blocked = server.handle({**request, "method": "tools/list"})
                self.assertEqual(-32002, blocked["error"]["code"])
                negotiated = server.handle({**request, "params": _initialize_params("2099-01-01")})
                self.assertEqual(mcp_server.PROTOCOL_VERSION, negotiated["result"]["protocolVersion"])


class InstallerAndHostProbeTests(unittest.TestCase):
    def test_plan_install_verify_and_tamper_detection(self):
        with tempfile.TemporaryDirectory(prefix="dyz-install-test-") as folder:
            target = Path(folder) / "installed-claude"
            plan = install.plan_install(target, host="claude-code", source_root=ROOT)
            self.assertEqual("dry_run_plan", plan["action"])
            self.assertFalse(target.exists())

            record = install.install_bundle(target, host="claude-code", source_root=ROOT)
            self.assertEqual("installed_locally_needs_host_registration", record["status"])
            self.assertFalse(record["global_host_config_modified"])
            self.assertEqual(len(bundle.BUNDLE_FILES), record["bundle_files"])

            verified = install.verify_installation(target, expected_bundle_manifest_sha256=record["bundle_manifest_sha256"])
            self.assertEqual("matched", verified["status"])

            # Existing target cannot be overwritten
            with self.assertRaisesRegex(bundle.BundleError, "install_target_exists"):
                install.install_bundle(target, host="claude-code", source_root=ROOT)

            # Tampering with MCP config is caught even if attacker ALSO self-signs dyz-install-manifest.json!
            mcp_file = target / record["mcp_config"]
            mcp_file.write_text('{"tampered": true}\n', encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "mcp_config_tampered"):
                install.verify_installation(target)
            # Re-sign dyz-install-manifest.json with the tampered mcp_config hash -> MUST STILL BE REJECTED!
            im_file = target / install.INSTALL_MANIFEST_NAME
            im_data = json.loads(im_file.read_text(encoding="utf-8"))
            im_data["mcp_config_sha256"] = hashlib.sha256(mcp_file.read_bytes()).hexdigest()
            im_file.write_text(json.dumps(im_data), encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "mcp_config_tampered"):
                install.verify_installation(target, expected_bundle_manifest_sha256=record["bundle_manifest_sha256"])

            # Empty-string expected hash MUST be rejected (never silently fall back to manifest)
            with self.assertRaisesRegex(bundle.BundleError, "bundle_manifest_hash_invalid"):
                install.verify_installation(target, expected_bundle_manifest_sha256="")

            # Path traversal in dyz-install-manifest.json MUST be rejected
            im_data["mcp_config"] = "../escape.json"
            im_file.write_text(json.dumps(im_data), encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "install_manifest_invalid"):
                install.verify_installation(target)

            # Failed installation MUST clean up target directory atomically!
            bad_target = Path(folder) / "atomic-fail"
            with self.assertRaises(bundle.BundleError):
                install.install_bundle(bad_target, host="claude-code", source_root=Path(folder))
            self.assertFalse(bad_target.exists())

            # Only bare interpreter names and absolute commands without whitespace can be configured.
            for bad_py in (
                "python3 -c 'import os'", "python_evil.bat", "python_backdoor.sh", "python3 > pwn.txt",
                r"\\attacker.example\share\python.exe", "//attacker.example/share/python3",
                r"/\attacker\share\python.exe", r"\/attacker/share/python.exe",
                r"\windows_root\python.exe", "python3/",
                "C:python.exe", "http://evil.invalid/python3", "-e/python3", "",
                "./python3", "sub/python3", r"sub\python.exe", "~/python3", ".python3",
                r"C:\Program Files\Python312\python.exe", "/opt/my dir/python3", "/opt/dir\u00a0/python3",
                "/opt/dir\x85/python3", "/opt/dir\x9f/python3", "\x01python",
            ):
                with self.subTest(bad_py=bad_py), self.assertRaisesRegex(ValueError, "invalid_python_executable"):
                    install.install_bundle(
                        Path(folder) / "p-bad", host="claude-code", python_executable=bad_py, source_root=ROOT
                    )
            for good_py in (
                r"C:\Users\Administrator\AppData\Local\Python\bin\python3.14-64.exe",
                "/usr/bin/python3.12",
                "python3",
            ):
                with self.subTest(good_py=good_py):
                    self.assertTrue(install._safe_python_command(good_py))

            # Binding status MUST accurately report all 4 hash verification combinations!
            target2 = Path(folder) / "installed-binding"
            rec2 = install.install_bundle(target2, host="claude-code", source_root=ROOT)
            v_unpinned = install.verify_installation(target2)
            self.assertEqual("install_manifest_internal_consistency_only", v_unpinned["binding"])
            v_bundle_only = install.verify_installation(target2, expected_bundle_manifest_sha256=rec2["bundle_manifest_sha256"])
            self.assertEqual("expected_bundle_manifest_hash_matched", v_bundle_only["binding"])
            v_install_only = install.verify_installation(target2, expected_install_manifest_sha256=rec2["install_manifest_sha256"])
            self.assertEqual("expected_install_manifest_hash_matched", v_install_only["binding"])
            v_both = install.verify_installation(
                target2,
                expected_bundle_manifest_sha256=rec2["bundle_manifest_sha256"],
                expected_install_manifest_sha256=rec2["install_manifest_sha256"],
            )
            self.assertEqual("expected_install_and_bundle_hashes_matched", v_both["binding"])
            self.assertTrue(v_both["install_manifest_bound"])
            self.assertFalse(v_bundle_only['mcp_command_bound'])
            self.assertTrue(v_install_only['mcp_command_bound'])

    def test_bundle_pin_report_exposes_unbound_command_and_independent_pins_reject_change(self):
        with tempfile.TemporaryDirectory(prefix='dyz-command-binding-') as folder:
            target = Path(folder).resolve() / 'local-codex'
            installed = install.install_bundle(target, host='codex', source_root=ROOT, python_executable='python3')
            snippet = target / installed['mcp_config']
            self.assertEqual('.toml', snippet.suffix)
            cfg = tomllib.loads(snippet.read_text(encoding='utf-8'))['mcp_servers']['dyz-patent-copyright-skills']
            self.assertEqual('python3', cfg['command'])
            self.assertIn('-I', cfg['args'])
            verified = install.verify_installation(target, expected_python_executable='python3', expected_host='codex')
            self.assertTrue(verified['mcp_command_bound'])
            self.assertEqual('python3', verified['python_executable'])

            replacement = 'python3.14'
            config = mcp_server.render_client_config(host='codex', python_executable=replacement, package_path=str(target / 'bundle'))
            snippet.write_bytes(config.encode('utf-8'))
            manifest = target / install.INSTALL_MANIFEST_NAME
            record = json.loads(manifest.read_bytes())
            record.update(python_executable=replacement, mcp_config_sha256=hashlib.sha256(snippet.read_bytes()).hexdigest())
            manifest.write_text(json.dumps(record), encoding='utf-8')
            only_bundle = install.verify_installation(target, expected_bundle_manifest_sha256=installed['bundle_manifest_sha256'])
            self.assertFalse(only_bundle['mcp_command_bound'])
            self.assertEqual(replacement, only_bundle['python_executable'])
            for key, value, error in (
                ('expected_python_executable', 'python3', 'mcp_command_binding_changed'),
                ('expected_install_manifest_sha256', installed['install_manifest_sha256'], 'install_manifest_binding_changed'),
                ('expected_host', 'cursor', 'install_host_binding_changed'),
            ):
                with self.subTest(key=key), self.assertRaisesRegex(bundle.BundleError, error):
                    install.verify_installation(target, **{key: value})
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(2, install.main(['--target', str(target), '--verify', '--host', 'cursor']))
            self.assertEqual('install_host_binding_changed', json.loads(out.getvalue())['error'])

    def test_plan_checks_target_and_link_and_rollback_only_removes_owned_files(self):
        with tempfile.TemporaryDirectory(prefix='dyz-install-rollback-') as folder:
            parent = Path(folder).resolve()
            with self.assertRaisesRegex(bundle.BundleError, 'install_target_exists'):
                install.plan_install(parent)
            with self.assertRaisesRegex(bundle.BundleError, 'bundle_path_missing'):
                install.plan_install(parent / 'missing' / 'target')
            link = parent / 'linked'
            link.mkdir()
            original = Path.lstat

            def lexical_info(path):
                info = original(path)
                return type(info)((stat.S_IFLNK, *tuple(info)[1:])) if path == link else info

            with patch.object(Path, 'lstat', lexical_info), self.assertRaisesRegex(bundle.BundleError, 'bundle_link_rejected'):
                install.plan_install(link / 'target')

            target = parent / 'partial'
            foreign = target / 'bundle' / 'foreign.txt'

            def fail_after_bundle(**_):
                foreign.write_text('unowned file', encoding='utf-8')
                raise PermissionError('local path detail')

            out = io.StringIO()
            with patch.object(mcp_server, 'render_client_config', side_effect=fail_after_bundle), redirect_stdout(out):
                self.assertEqual(2, install.main(['--target', str(target)]))
            self.assertEqual({'status': 'rejected', 'error': 'install_io_error'}, json.loads(out.getvalue()))
            self.assertEqual([foreign], list(target.glob('**/*.*')))
            self.assertEqual('unowned file', foreign.read_text(encoding='utf-8'))

    def test_unpinned_host_capability_probe_distinguishes_qualification(self):
        with self.assertRaisesRegex(codex_host.HostError, "host_cli_not_verified"):
            codex_host.probe_host_capabilities(Path(sys.executable).resolve(), allow_unpinned=False)
        probed = codex_host.probe_host_capabilities(Path(sys.executable).resolve(), allow_unpinned=True)
        self.assertEqual("unpinned_runtime_capability_probe_only", probed["qualification"])
        self.assertFalse(probed["pinned_match"])
        self.assertFalse(probed["model_inference_requested"])
        self.assertEqual(0, probed["version_exit_code"])
        self.assertIn("Python", probed["observed_version"])


if __name__ == "__main__":
    unittest.main()
