"""纯 Python 标准库 MCP (Model Context Protocol) stdio 服务端。

包装 tools/host_bridge.py 的有界受控工具及只读目录查询，兼容 Content-Length 帧与
行分隔 JSON-RPC 2.0 两种 stdio 传输。不启动模型、不联网、不绕过路径与清单校验，
也不自动修改全局宿主配置。
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import math
import re
import sys
from pathlib import Path
import unicodedata

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools
from tools.cli import catalog
from tools.host_bridge import HostToolBridge, dynamic_tools

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
MAX_MCP_FRAME_BYTES = 32_000_000
MAX_MCP_HEADER_BYTES = 8192
MAX_MCP_HEADERS = 32
MAX_MCP_JSON_DEPTH = 128
_HEADER_NAME = re.compile(rb"[A-Za-z0-9-]+")
_CONTENT_LENGTH = re.compile(rb"[0-9]+")
HOST_PROFILES = ("claude-code", "cursor", "codex", "trae", "generic")

CATALOG_TOOL_SPEC = {
    "name": "dyz_catalog",
    "description": (
        "Return the read-only DYZ 11-domain 83-capability catalog with explicit "
        "synthetic_helper_only support boundaries. Never reads case files or runs models."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Optional capability prefix filter such as CORE, DRAFT, SW, or STD.",
            }
        },
        "additionalProperties": False,
    },
}


def _clean_client_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and all(
        unicodedata.category(ch) not in {"Cc", "Cf", "Cs"} for ch in value
    )


def _mcp_tool_list(*, has_bridge: bool) -> list[dict]:
    tools = [CATALOG_TOOL_SPEC]
    if has_bridge:
        for spec in dynamic_tools():
            tools.append({
                "name": spec["name"],
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            })
    return tools


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _parse_json_bytes(raw: bytes) -> dict:
    def reject_constant(_value: str):
        raise ValueError("nonfinite_json_number")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite_json_number")
        return number

    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object_pairs,
                         parse_constant=reject_constant, parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("invalid_json") from None
    if not isinstance(obj, dict):
        raise ValueError("json_object_required")
    # Python versions enforce different recursion limits inside json.loads.
    levels = [iter(obj.values())]
    exhausted = object()
    while levels:
        value = next(levels[-1], exhausted)
        if isinstance(value, dict):
            levels.append(iter(value.values()))
        elif isinstance(value, list):
            levels.append(iter(value))
        elif value is exhausted:
            levels.pop()
        if len(levels) > MAX_MCP_JSON_DEPTH:
            raise ValueError("json_depth_exceeded")
    return obj


class _FrameError(ValueError):
    def __init__(self, framing: str, code: str):
        super().__init__(code)
        self.framing = framing


def read_mcp_message(stream) -> tuple[dict | None, str]:
    """Read one JSON-RPC message; auto-detects Content-Length framing vs NDJSON."""
    while True:
        first_line = stream.readline(MAX_MCP_HEADER_BYTES + 1)
        if not first_line:
            return None, "ndjson"
        prefix = first_line.lstrip(b" \t\r\n")
        if prefix or not first_line.endswith(b"\n"):
            break
    # Header names are ASCII and begin with a token. JSON objects and other JSON values are line framed.
    possible_name, sep, _ = prefix.partition(b":")
    framed = bool(sep and _HEADER_NAME.fullmatch(possible_name.rstrip(b" \t"))) or prefix.lower().startswith(b"content-length")
    framing = "content-length" if framed else "ndjson"
    try:
        if not framed:
            if not first_line.endswith(b"\n") and len(first_line) == MAX_MCP_HEADER_BYTES + 1:
                first_line += stream.readline(MAX_MCP_FRAME_BYTES + 1 - len(first_line))
            if len(first_line) > MAX_MCP_FRAME_BYTES:
                raise ValueError("frame_too_large")
            return _parse_json_bytes(first_line), framing
        length_value = None
        line = first_line
        for index in range(MAX_MCP_HEADERS + 1):
            if line in (b"\n", b"\r\n"):
                break
            if not line or len(line) > MAX_MCP_HEADER_BYTES or not line.endswith(b"\n"):
                raise ValueError("invalid_header_length")
            if index == MAX_MCP_HEADERS:
                raise ValueError("too_many_headers")
            field = line.removesuffix(b"\n").removesuffix(b"\r")
            name, colon, value = field.partition(b":")
            if not colon or not _HEADER_NAME.fullmatch(name) or any(c < 32 and c != 9 or c >= 127 for c in value):
                raise ValueError("invalid_header")
            if name.lower() == b"content-length":
                if length_value is not None:
                    raise ValueError("duplicate_content_length")
                length_value = value.strip(b" \t")
            line = stream.readline(MAX_MCP_HEADER_BYTES + 1)
        if length_value is None or not _CONTENT_LENGTH.fullmatch(length_value):
            raise ValueError("invalid_content_length")
        digits = length_value.lstrip(b"0")
        if not digits or len(digits) > len(str(MAX_MCP_FRAME_BYTES)):
            raise ValueError("invalid_content_length")
        length = int(digits)
        if length > MAX_MCP_FRAME_BYTES:
            raise ValueError("invalid_content_length")
        body = stream.read(length)
        if len(body) != length:
            raise ValueError("truncated_body")
        return _parse_json_bytes(body), framing
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _FrameError(framing, str(exc)) from None


def write_mcp_message(stream, payload: dict, framing: str) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if framing == "content-length":
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        stream.write(header + encoded)
    else:
        stream.write(encoded + b"\n")
    stream.flush()


class McpServer:
    """Bounded stdio MCP server over HostToolBridge and read-only catalog."""

    def __init__(self, bridge: HostToolBridge | None = None):
        self.bridge = bridge
        self.handshake_initialized = False
        self.initialized = False
        self.protocol_version = PROTOCOL_VERSION

    def _error(self, req_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    def _result(self, req_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def handle(self, message: dict) -> dict | None:
        if "id" not in message:
            if (self.handshake_initialized and message.get("jsonrpc") == "2.0"
                    and message.get("method") == "notifications/initialized"
                    and isinstance(message.get("params", {}), dict)):
                self.initialized = True
            return None
        req_id = message["id"]
        if type(req_id) not in (str, int):
            return self._error(None, -32600, "invalid_request_id")
        if message.get("jsonrpc") != "2.0":
            return self._error(req_id, -32600, "jsonrpc_2_0_required")
        method = message.get("method")
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(method, str):
            return self._error(req_id, -32600, "invalid_request")

        if method == "initialize":
            if self.handshake_initialized:
                return self._error(req_id, -32600, "already_initialized")
            if not isinstance(params, dict):
                return self._error(req_id, -32602, "invalid_initialize_params")
            client_version = params.get("protocolVersion")
            client_info = params.get("clientInfo")
            if (not isinstance(client_version, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", client_version) is None
                    or not isinstance(client_info, dict) or not _clean_client_text(client_info.get("name"))
                    or ("version" in client_info and not _clean_client_text(client_info["version"]))
                    or not isinstance(params.get("capabilities"), dict)):
                return self._error(req_id, -32602, "invalid_initialize_params")
            try:
                date.fromisoformat(client_version)
            except ValueError:
                return self._error(req_id, -32602, "invalid_initialize_params")
            if client_version in SUPPORTED_PROTOCOLS:
                self.protocol_version = client_version
            else:
                self.protocol_version = PROTOCOL_VERSION
            self.handshake_initialized = True
            return self._result(req_id, {
                "protocolVersion": self.protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "dyz-patent-copyright-skills",
                    "version": tools.__version__,
                },
                "instructions": (
                    "DYZ bounded local MCP server. Outputs remain internal candidates "
                    "requiring professional review; no model inference, network calls, "
                    "or formal submissions are executed by this server."
                ),
            })

        if method != "ping" and self.initialized is not True:
            return self._error(req_id, -32002, "server_not_initialized")

        if not isinstance(params, dict):
            return self._error(req_id, -32600, "invalid_request")

        if method == "ping":
            return self._result(req_id, {})

        if method == "tools/list":
            return self._result(req_id, {"tools": _mcp_tool_list(has_bridge=self.bridge is not None)})

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return self._error(req_id, -32602, "invalid_tool_call_params")
            if name == "dyz_catalog":
                allowed = set(arguments) <= {"domain"}
                if not allowed:
                    return self._result(req_id, {
                        "isError": True,
                        "content": [{"type": "text", "text": json.dumps({"error": "invalid_arguments"})}],
                    })
                rows = catalog()
                domain = arguments.get("domain")
                if domain is not None:
                    if not isinstance(domain, str) or not domain.strip():
                        return self._result(req_id, {
                            "isError": True,
                            "content": [{"type": "text", "text": json.dumps({"error": "invalid_domain"})}],
                        })
                    prefix = domain.strip().upper() + "-"
                    rows = [row for row in rows if row["capability"].startswith(prefix)]
                payload = {
                    "count": len(rows),
                    "capability_support": "synthetic_helper_only",
                    "professional_review": "not_performed",
                    "capabilities": rows,
                }
                return self._result(req_id, {
                    "isError": False,
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                })
            if self.bridge is None:
                return self._result(req_id, {
                    "isError": True,
                    "content": [{"type": "text", "text": json.dumps({"error": "case_bridge_not_configured"})}],
                })
            answer = self.bridge.call(name, arguments)
            image_data_url = None
            if answer.get("success") and isinstance(answer.get("result"), dict):
                result_copy = dict(answer["result"])
                image_data_url = result_copy.pop("image_data_url", None)
                answer = {**answer, "result": result_copy}
            content = [{"type": "text", "text": json.dumps(answer, ensure_ascii=False)}]
            if isinstance(image_data_url, str) and image_data_url.startswith("data:image/png;base64,"):
                content.append({
                    "type": "image",
                    "mimeType": "image/png",
                    "data": image_data_url.split(",", 1)[1],
                })
            return self._result(req_id, {
                "isError": not bool(answer.get("success")),
                "content": content,
            })

        return self._error(req_id, -32601, "method_not_found")

    def serve(self, stdin=None, stdout=None) -> int:
        in_stream = stdin if stdin is not None else sys.stdin.buffer
        out_stream = stdout if stdout is not None else sys.stdout.buffer
        while True:
            try:
                message, framing = read_mcp_message(in_stream)
            except _FrameError as exc:
                write_mcp_message(out_stream, self._error(None, -32700, str(exc)), exc.framing)
                return 2
            except (ValueError, UnicodeError, RecursionError):
                write_mcp_message(out_stream, self._error(None, -32700, "invalid_frame"), "ndjson")
                return 2
            if message is None:
                return 0
            try:
                reply = self.handle(message)
                if reply is not None:
                    write_mcp_message(out_stream, reply, framing)
            except (ValueError, UnicodeError, RecursionError):
                if "id" in message:
                    req_id = message["id"]
                    write_mcp_message(out_stream, self._error(req_id if type(req_id) in (str, int) else None,
                                                             -32603, "invalid_request_payload"), framing)


def render_client_config(
    *,
    host: str,
    python_executable: str,
    package_path: str,
    workspace_path: str | None = None,
    control_path: str | None = None,
    manifest_sha256: str | None = None,
) -> dict | str:
    """Render a copy-pasteable MCP configuration snippet without writing global host files."""
    if host not in HOST_PROFILES:
        raise ValueError("unsupported_host_profile")
    script = str(Path(package_path) / "tools" / "mcp_server.py")
    args = ["-I", "-B", "-X", "utf8", script]
    if any(value is not None for value in (workspace_path, control_path, manifest_sha256)):
        if not (isinstance(workspace_path, str) and workspace_path.strip() and isinstance(control_path, str)
                and control_path.strip() and isinstance(manifest_sha256, str)
                and re.fullmatch(r"[0-9a-f]{64}", manifest_sha256)):
            raise ValueError("invalid_case_bridge_config")
        args += [
            "--package", package_path,
            "--workspace", workspace_path,
            "--control", control_path,
            "--manifest-sha256", manifest_sha256,
        ]
    else:
        args.append("--catalog-only")
    if host == "codex":
        command = json.dumps(python_executable, ensure_ascii=False).replace("\x7f", "\\u007f")
        toml_args = json.dumps(args, ensure_ascii=False).replace("\x7f", "\\u007f")
        return f'[mcp_servers."dyz-patent-copyright-skills"]\ncommand = {command}\nargs = {toml_args}\n'
    entry = {"command": python_executable, "args": args, "env": {"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}}
    return {
        "host": host,
        "mcpServers": {"dyz-patent-copyright-skills": entry},
        "note": (
            "Snippet only; not written to global host config. Replace --catalog-only with "
            "--package/--workspace/--control/--manifest-sha256 for bounded case tools."
        ),
    }


def client_config_text(snippet: dict | str) -> str:
    return snippet if isinstance(snippet, str) else json.dumps(snippet, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DYZ pure-stdlib MCP stdio server (no model or network).")
    parser.add_argument("--describe", action="store_true", help="Print MCP tool descriptors and exit.")
    parser.add_argument("--print-config", action="store_true", help="Print a host MCP JSON or Codex TOML snippet and exit.")
    parser.add_argument("--host", default="generic", choices=HOST_PROFILES)
    parser.add_argument("--catalog-only", action="store_true", help="Expose read-only dyz_catalog only.")
    parser.add_argument("--package")
    parser.add_argument("--workspace")
    parser.add_argument("--control")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--max-calls", type=int, default=120)
    args = parser.parse_args(argv)

    if args.describe:
        print(json.dumps({
            "transport": "mcp_stdio_jsonrpc_2_0",
            "protocol_version": PROTOCOL_VERSION,
            "supported_protocols": list(SUPPORTED_PROTOCOLS),
            "tools": _mcp_tool_list(has_bridge=True),
            "scope": "Python file boundaries; not OS isolation, network proxy, or professional certification",
        }, ensure_ascii=False, indent=2))
        return 0

    if args.print_config:
        package_root = args.package or str(Path(__file__).resolve().parents[1])
        try:
            snippet = render_client_config(
                host=args.host,
                python_executable=sys.executable,
                package_path=package_root,
                workspace_path=args.workspace,
                control_path=args.control,
                manifest_sha256=args.manifest_sha256,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(client_config_text(snippet), end="")
        return 0

    bridge = None
    if not args.catalog_only:
        if not all((args.package, args.workspace, args.control, args.manifest_sha256)):
            parser.error("--package, --workspace, --control, and --manifest-sha256 are required unless --catalog-only")
        try:
            bridge = HostToolBridge(
                args.package, args.workspace, args.control, args.manifest_sha256, max_calls=args.max_calls
            )
        except (OSError, ValueError, TypeError, KeyError):
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "bridge_roots_or_manifest_rejected"}}))
            return 2

    return McpServer(bridge).serve()


if __name__ == "__main__":
    raise SystemExit(main())
