"""Local relay fault tests: synthetic Python child, mocked HTTPS, no account/inference."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from evals import codex_cli_transport as transport


SECRET = "SYNTHETIC_KEEP_OUT_OF_LOG"
CLIENT = r'''
import json,sys,urllib.request,urllib.error
user=sys.stdin.buffer.read().decode('utf-8')
body={'model':'gpt-6.1-sol','reasoning':{'effort':'high'},
 'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':user}]}],
 'instructions':'SYNTHETIC_NATIVE_WRAPPER','tools':[{'type':'synthetic_forbidden_tool'}],
 'previous_response_id':'synthetic-not-a-real-response'}
if sys.argv[3]=='cap': body['max_output_tokens']=1
payload=json.dumps(body).encode()
request=urllib.request.Request(sys.argv[1]+'/responses',data=payload,
 headers={'Content-Type':'application/json','Authorization':'Bearer SYNTHETIC_KEEP_OUT_OF_LOG'})
try:
 with urllib.request.urlopen(request,timeout=float(sys.argv[2])) as response: response.read()
 if sys.argv[3]=='two':
  try: urllib.request.urlopen(request,timeout=1).read()
  except urllib.error.HTTPError as error:
   if error.code!=400: sys.exit(4)
  else: sys.exit(5)
except Exception: sys.exit(1)
'''


class ProbeSocket:
    def __init__(self, event):
        self.event = event
        self.shutdown_called = False

    def settimeout(self, seconds):
        self.timeout = seconds

    def shutdown(self, _):
        self.shutdown_called = True
        self.event.set()


class ProbeResponse:
    status = 200

    def __init__(self, connection, mode):
        self.connection, self.mode = connection, mode
        self.lines = [b'data: {"type":"response.created"}\n', b'\n',
                      b'data: {"type":"response.output_text.delta","delta":"LOCAL_PROBE"}\n', b'\n']
        if mode in {"complete", "close_error"}:
            self.lines += [b'data: {"type":"response.completed","response":{"id":"local-probe","status":"completed"}}\n', b'\n']
        self.closed = False

    def getheader(self, name, default=None):
        return {"Content-Type":"text/event-stream", "x-request-id":"local-probe"}.get(name, default)

    def readline(self):
        if self.lines:
            return self.lines.pop(0)
        if self.mode == "stall":
            if self.connection.event.wait(4):
                raise ConnectionAbortedError("synthetic cancellation")
            raise TimeoutError("synthetic fallback timeout")
        return b""

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def probe(self, mode="complete", two=False, cap=False, forward=True):
        temporary = tempfile.TemporaryDirectory(prefix="dyz-relay-test-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        protocol = base / "protocol.txt"
        protocol.write_text("Local transport probe; no case or model.\n", encoding="utf-8")
        prepared = base / "prepared.json"
        prepared.write_text(json.dumps({"messages":[{"role":"developer","content":protocol.read_text(encoding="utf-8")},
            {"role":"user","content":"LOCAL_TRANSPORT_PROBE"}]}), encoding="utf-8")
        connections, timing = [], {}
        class Connection:
            def __init__(self, host, timeout=None, context=None):
                self.host, self.timeout = host, timeout
                self.event = threading.Event()
                self.sock = ProbeSocket(self.event)
                self.closed = False
                self.response = ProbeResponse(self, mode)
                connections.append(self)

            def request(self, method, path, body=None, headers=None):
                if self.host != "chatgpt.com" or method != "POST" or path != "/backend-api/codex/responses":
                    raise AssertionError("fixed destination changed")
                self.body = body

            def getresponse(self):
                if mode == "headers_error":
                    raise ConnectionResetError(SECRET)
                return self.response

            def close(self):
                self.closed = True
                self.event.set()
                if mode == "close_error":
                    raise OSError(SECRET)
        real_popen = subprocess.Popen
        def spawn(args, **kwargs):
            value = next(arg.split("=",1)[1] for arg in args if arg.startswith("openai_base_url="))
            url = json.loads(value)
            process = real_popen([sys.executable, "-B", "-c", CLIENT, url,
                "0.2" if mode == "stall" else "2", "cap" if cap else "two" if two else "one"], **kwargs)
            communicate = process.communicate
            def observed(*a, **kw):
                result = communicate(*a, **kw)
                timing["child_exit"] = time.monotonic()
                return result
            process.communicate = observed
            return process
        with patch.object(transport.http.client, "HTTPSConnection", Connection), \
                patch.object(transport.subprocess, "Popen", spawn), contextlib.redirect_stdout(io.StringIO()):
            code = transport.run("probe", base=base, protocol=protocol, prepared=prepared,
                                 cli=Path(sys.executable), forward=forward)
        timing["after_child_seconds"] = time.monotonic() - timing["child_exit"]
        folder = base / "channel/probe"
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        return base, folder, connections, timing, summary, code

    def test_cli_exit_cancels_only_its_active_upstream_and_returns_promptly(self):
        _, _, connections, timing, _, _ = self.probe("stall")
        self.shutdown_evidence = {"after_child_seconds":timing["after_child_seconds"],
            "owned_connections":len(connections), "all_closed":all(c.closed for c in connections)}
        self.assertTrue(all(c.closed for c in connections))
        self.assertTrue(connections[0].sock.shutdown_called)
        self.assertLess(timing["after_child_seconds"], 2)

    def test_completed_stream_is_retained_with_terminal_delimiter(self):
        _, folder, connections, _, summary, code = self.probe()
        self.assertEqual(0, code)
        self.assertEqual(0, summary["exit_code"])
        self.assertTrue(summary["transport_complete"])
        raw = (folder / "response-1.sse").read_bytes()
        self.assertTrue(raw.endswith(b"\n\n"))
        audit = json.loads((folder / "request-1-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), audit["response_sha256"])
        self.assertEqual("completed", audit["stream_outcome"])
        self.assertTrue(connections[0].closed)

    def test_eof_without_terminal_is_not_success_even_if_child_returns_zero(self):
        _, folder, _, _, summary, code = self.probe("eof")
        self.assertEqual(0, summary["exit_code"])
        self.assertEqual(1, code)
        self.assertFalse(summary["transport_complete"])
        audit = json.loads((folder / "request-1-audit.json").read_text(encoding="utf-8"))
        self.assertEqual("eof_without_terminal", audit["stream_outcome"])
        self.assertEqual("unknown_not_zero", audit["usage_status"])
        self.assertEqual(hashlib.sha256((folder / "response-1.sse").read_bytes()).hexdigest(), audit["response_sha256"])

    def test_request_sent_but_headers_missing_is_preserved_as_unknown_usage(self):
        base, folder, connections, _, summary, _ = self.probe("headers_error")
        self.assertTrue(connections[0].closed)
        self.assertEqual(1, summary["model_requests_forwarded"])
        self.assertEqual(0, summary["upstream_responses_started"])
        audit = json.loads((folder / "request-1-audit.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["request_sent"])
        self.assertEqual("unknown_not_zero", audit["usage_status"])
        self.assertFalse((folder / "response-1.sse").exists())
        self.assertTrue(all(SECRET.encode() not in p.read_bytes() for p in base.rglob("*") if p.is_file()))

    def test_second_POST_is_recorded_but_never_forwarded(self):
        _, folder, connections, _, summary, _ = self.probe(two=True)
        self.assertEqual(1, len(connections))
        self.assertEqual(2, len(summary["requests"]))
        self.assertEqual(1, summary["model_requests_forwarded"])
        self.assertFalse((folder / "request-2.json").exists())
        self.assertFalse(json.loads((folder / "request-2-audit.json").read_text(encoding="utf-8"))["allowlisted_request"])

    def test_config_disables_reconnect_and_extends_client_idle_past_upstream(self):
        value = transport.settings(12345, Path("protocol.txt"))
        self.assertEqual(transport.LOCAL_PROVIDER_ID, value["model_provider"])
        prefix = "model_providers." + transport.LOCAL_PROVIDER_ID + "."
        self.assertFalse(value[prefix + "supports_websockets"])
        self.assertEqual(0, value[prefix + "stream_max_retries"])
        self.assertEqual(0, value[prefix + "request_max_retries"])
        self.assertEqual(660000, value[prefix + "stream_idle_timeout_ms"])
        self.assertTrue(value[prefix + "requires_openai_auth"])
        self.assertEqual("http://127.0.0.1:12345/backend-api/codex", value[prefix + "base_url"])

    def test_only_frozen_messages_and_no_tools_are_forwarded(self):
        base, folder, connections, _, _, _ = self.probe()
        body = connections[0].body
        request = json.loads(body)
        self.assertEqual([{"type":"message", "role":"developer", "content":[{"type":"input_text", "text":(base/"protocol.txt").read_text(encoding="utf-8")}]},
            {"type":"message", "role":"user", "content":[{"type":"input_text", "text":"LOCAL_TRANSPORT_PROBE"}]}], request["input"])
        self.assertEqual([], request["tools"])
        self.assertEqual("none", request["tool_choice"])
        self.assertNotIn("previous_response_id", request)
        self.assertNotIn("max_output_tokens", request)
        self.assertNotIn(b"SYNTHETIC_NATIVE_WRAPPER", body)
        self.assertEqual(body, (folder/"request-1.json").read_bytes())
        audit = json.loads((folder/"request-1-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(body).hexdigest(), audit["forwarded_body_sha256"])
        self.assertTrue(all(SECRET.encode() not in p.read_bytes() for p in base.rglob("*") if p.is_file()))

    def test_client_token_cap_is_rejected_without_forwarding(self):
        _, folder, connections, _, summary, _ = self.probe(cap=True)
        self.assertEqual([], connections)
        self.assertEqual(0, summary["forward_attempts"])
        self.assertFalse((folder/"request-1.json").exists())

    def test_inspection_mode_never_connects_upstream(self):
        _, _, connections, _, summary, _ = self.probe(forward=False)
        self.assertEqual([], connections)
        self.assertEqual(0, summary["forward_attempts"])
        self.assertEqual(0, summary["model_requests_forwarded"])
        self.assertEqual("inspection_only", summary["mode"])

    def test_resource_close_error_keeps_raw_evidence_and_cannot_report_success(self):
        base, folder, _, _, summary, code = self.probe("close_error")
        self.assertFalse(summary["transport_complete"])
        self.assertEqual(1, code)
        audit = json.loads((folder/"request-1-audit.json").read_text(encoding="utf-8"))
        self.assertIn("OSError", audit["cleanup_exception_types"])
        self.assertTrue(audit["archive_saved"])
        self.assertTrue((folder/"response-1.sse").exists())
        self.assertTrue(all(SECRET.encode() not in p.read_bytes() for p in base.rglob("*") if p.is_file()))

    def test_launch_record_failure_closes_listener_without_starting_a_child(self):
        with tempfile.TemporaryDirectory(prefix="dyz-relay-setup-") as temporary:
            base = Path(temporary)
            protocol, prepared = base/"protocol.txt", base/"prepared.json"
            protocol.write_text("Local setup probe", encoding="utf-8")
            prepared.write_text(json.dumps({"messages":[{"role":"developer","content":"Local setup probe"},
                {"role":"user","content":"LOCAL_PROBE"}]}), encoding="utf-8")
            servers = []
            original = transport.http.server.ThreadingHTTPServer
            def create(*a, **kw):
                server = original(*a, **kw)
                servers.append(server)
                return server
            with patch.object(transport.http.server, "ThreadingHTTPServer", create), \
                    patch.object(transport, "save", side_effect=OSError("synthetic disk error")), \
                    patch.object(transport.subprocess, "Popen", side_effect=AssertionError("must not start child")):
                with self.assertRaises(OSError):
                    transport.run("setup", base=base, protocol=protocol, prepared=prepared,
                                  cli=Path(sys.executable), forward=True)
            self.assertEqual(-1, servers[0].socket.fileno())

    def test_wrong_packet_or_traversing_name_fails_before_starting_anything(self):
        with tempfile.TemporaryDirectory(prefix="dyz-relay-input-") as temporary:
            base = Path(temporary)
            protocol, prepared = base/"protocol.txt", base/"prepared.json"
            protocol.write_text("Local protocol", encoding="utf-8")
            for name, packet in [("valid", []), ("valid", {"messages":[1,2]}),
                    ("valid", {"messages":[{"role":"developer","content":"wrong"},{"role":"user","content":"LOCAL"}]}),
                    ("../escape", {})]:
                with self.subTest(name=name, packet=packet):
                    prepared.write_text(json.dumps(packet), encoding="utf-8")
                    with patch.object(transport.subprocess, "Popen", side_effect=AssertionError("must not start")):
                        with self.assertRaises(ValueError):
                            transport.run(name, base=base, protocol=protocol, prepared=prepared,
                                          cli=Path(sys.executable), forward=True)
                    self.assertFalse((base/"channel").exists())


if __name__ == "__main__":
    unittest.main()
