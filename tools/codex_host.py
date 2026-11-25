"""WP-01/02/10：六Skill的Codex进程配置；只做本地元数据，不启动模型。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools import bundle, core
else:
    from . import bundle, core

SKILLS = frozenset({"dyz-patent", "dyz-procedure", "dyz-software", "dyz-standards", "dyz-rendering", "dyz-workbench"})
CLI_SHA256 = "9ecb9df2ecafcc00542ef0966c6f1737a81397dc9531b0a4b178238e2bf4a46d"
CLI_VERSION = "0.163.0-alpha.10.2"
MAX_FRAME = 4_000_000
MAX_STDERR_LINE = 65536
_WINDOWS = os.name == "nt"
REMOTE_DISABLED_ENV = "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED"
REMOTE_LOG_TARGET = "codex_app_server_transport::transport::remote_control"
PROBE_MODE = "local_skills_plugins_and_remote_control_disabled_synthetic_static_model_catalog"
ENVIRONMENT_KEYS = frozenset({"systemroot", "windir", "comspec", "temp", "tmp", "userprofile", "appdata",
    "localappdata", "path", "pathext", "homedrive", "homepath", "programdata", "os"})


def metadata_catalog():
    """原创虚构占位，不是可用模型目录；仅使元数据进程无需远程刷新模型目录。"""
    return {"models": [{"slug": "dyz-metadata-only-not-a-real-model", "display_name": "Metadata inspection placeholder",
        "description": "Synthetic placeholder, never used for inference.", "supported_reasoning_levels": [],
        "shell_type": "disabled", "visibility": "hide", "supported_in_api": False, "priority": 0,
        "support_verbosity": False, "truncation_policy": {"mode": "bytes", "limit": 1},
        "experimental_supported_tools": [], "base_instructions": "Never start a thread or model turn.",
        "supports_parallel_tool_calls": False, "prefer_websockets": False, "input_modalities": ["text"],
        "tool_mode": "direct"}]}


def metadata_environment():
    result = {k: v for k, v in os.environ.items() if k.lower() in ENVIRONMENT_KEYS}
    # 固定版本的进程启动标记；不能从父会话继承，也不写用户持久设置。
    result[REMOTE_DISABLED_ENV] = "1"
    result["LOG_FORMAT"] = "json"
    result["RUST_LOG"] = "off," + REMOTE_LOG_TARGET + "=info"
    return result


def native_process_counters(process):
    """只读自有Popen句柄；不按PID重开进程，不取名称、栈或配置。"""
    if not _WINDOWS:
        return {"status": "unavailable", "reason": "platform_not_verified"}
    try:
        import ctypes
        from ctypes import wintypes
        handle = getattr(process, "_handle", None)
        if handle is None:
            return {"status": "unavailable", "reason": "native_handle_unavailable"}
        handle = int(handle)
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetProcessId.argtypes = [wintypes.HANDLE]
        api.GetProcessId.restype = wintypes.DWORD
        api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        api.GetProcessTimes.restype = wintypes.BOOL
        api.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.GetProcessHandleCount.restype = wintypes.BOOL
        actual_pid = api.GetProcessId(handle)
        if not actual_pid:
            return {"status": "unavailable", "reason": "native_pid_unavailable", "winerror": getattr(ctypes, "get_last_error", lambda: 0)()}
        if actual_pid != process.pid:
            return {"status": "unavailable", "reason": "native_handle_pid_mismatch"}
        exited_before_query = process.poll() is not None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *[ctypes.byref(item) for item in times]):
            return {"status": "unavailable", "reason": "native_times_unavailable", "winerror": getattr(ctypes, "get_last_error", lambda: 0)()}
        values = [(item.dwHighDateTime << 32) | item.dwLowDateTime for item in times]
        result = {"status": "observed_owned_handle", "pid": actual_pid, "creation_filetime_100ns": values[0],
            "kernel_cpu_100ns": values[2], "user_cpu_100ns": values[3]}
        # 存活进程的退出时间在API中未定义，不能把清零缓冲区当已知状态。
        if exited_before_query:
            result["exit_filetime_100ns"] = values[1]
        count = wintypes.DWORD()
        if api.GetProcessHandleCount(handle, ctypes.byref(count)):
            result["handle_count"] = count.value
        else:
            result.update(handle_count_status="unavailable", handle_count_winerror=getattr(ctypes, "get_last_error", lambda: 0)())
        return result
    except (OSError, TypeError, ValueError, AttributeError):
        return {"status": "unavailable", "reason": "native_counter_observation_failed"}


class HostError(ValueError):
    """Only stable, non-sensitive codes are exposed by this tool."""
    def __init__(self, code, observations=None):
        super().__init__(code)
        self.observations = observations


def require(condition, code):
    if not condition:
        raise HostError(code)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path, *, directory=False, missing=False):
    path = bundle._absolute(path)
    info = core.checked_path(path, missing_leaf=missing)
    if info is None:
        require(missing, "host_path_missing")
    else:
        require(path.is_dir() if directory else path.is_file(), "host_path_kind")
    return path


def skill_metadata(package):
    """The distributed six entries use plain single-line name/description YAML."""
    expected = {}
    for name in sorted(SKILLS):
        path = regular(Path(package) / "skills" / name / "SKILL.md")
        lines = path.read_text(encoding="utf-8").splitlines()
        require(lines and lines[0] == "---" and "---" in lines[1:], "host_skill_frontmatter")
        fields = {}
        for line in lines[1:lines[1:].index("---") + 1]:
            key, separator, value = line.partition(":")
            if key in {"name", "description"}:
                require(separator and key not in fields, "host_skill_frontmatter")
                value = value.strip()
                require(bool(value) and value[0] not in "|>'\"", "host_skill_frontmatter_form")
                fields[key] = value
        require(fields.get("name") == name and bool(fields.get("description")), "host_skill_metadata")
        expected[name] = {"name": name, "description": fields["description"], "path": str(path), "source_sha256": digest(path)}
    return expected


def inventory_from_reply(reply, workspace):
    require(isinstance(reply, dict) and isinstance(reply.get("data"), list) and len(reply["data"]) == 1, "host_inventory_shape")
    group = reply["data"][0]
    require(isinstance(group, dict) and isinstance(group.get("cwd"), str)
            and Path(group["cwd"]).resolve() == workspace.resolve(), "host_inventory_cwd")
    rows = group.get("skills")
    require(isinstance(rows, list), "host_inventory_shape")
    seen = set()
    for row in rows:
        require(isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ("name", "path", "description"))
                and bool(row["name"]) and bool(row["path"])
                and type(row.get("enabled")) is bool, "host_inventory_row")
        key = (row["name"], str(Path(row["path"]).resolve()))
        require(key not in seen, "host_inventory_duplicate")
        seen.add(key)
    errors = group.get("errors", [])
    require(isinstance(errors, list), "host_inventory_errors")
    return rows, len(errors)


def select_six(rows, expected, *, require_enabled=True):
    selected = []
    for name, source in sorted(expected.items()):
        matches = [r for r in rows if r["name"] == name]
        require(len(matches) == 1, "host_skill_name_ambiguous_or_missing")
        row = matches[0]
        require(Path(row["path"]).resolve() == Path(source["path"]).resolve(), "host_skill_wrong_package")
        require(row["description"] == source["description"], "host_skill_description_changed")
        require(not require_enabled or row["enabled"], "host_skill_disabled")
        selected.append(dict(source, enabled=row["enabled"]))
    return selected


def selectors_for(rows, selected):
    return ([{"name": n, "enabled": False} for n in sorted({r["name"] for r in rows} - SKILLS)]
            + [{"path": r["path"], "enabled": True} for r in selected])


def selector_override(selectors):
    require(isinstance(selectors, list) and bool(selectors), "host_selectors_invalid")
    tables = []
    for row in selectors:
        require(isinstance(row, dict) and set(row) in ({"name", "enabled"}, {"path", "enabled"})
                and type(row["enabled"]) is bool, "host_selectors_invalid")
        key = "name" if "name" in row else "path"
        require(isinstance(row[key], str) and bool(row[key]), "host_selectors_invalid")
        tables.append("{" + key + "=" + json.dumps(row[key], ensure_ascii=False) + ",enabled="
                      + ("true" if row["enabled"] else "false") + "}")
    value = "[" + ",".join(tables) + "]"
    require(tomllib.loads("value=" + value)["value"] == selectors, "host_selectors_toml_roundtrip")
    return "skills.config=" + value


def inventory_fingerprint(rows):
    canonical = sorted((r["name"], str(Path(r["path"]).resolve()), r["description"], r["enabled"]) for r in rows)
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode()).hexdigest()


def diagnostic_lifecycle(lifecycle):
    """错误输出只保留参数依据，完整本地选择器只可进入私人profile。"""
    if not isinstance(lifecycle, dict):
        return None
    result = dict(lifecycle)
    arguments = result.pop("argv", None)
    if arguments is not None:
        result["argv_sha256"] = hashlib.sha256(json.dumps(arguments, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
        result["argv_count"] = len(arguments)
    return result


class _MetadataRpc:
    """Bounded stdio reader; no general method or model interface is exposed."""
    def __init__(self, process):
        self.process = process
        self.queue = queue.Queue()
        self.stderr_hash = hashlib.sha256()
        self.stderr_bytes = 0
        self.remote_control_startup_states = []
        self.stderr_observation_rejected = False
        self.stdout_reader = threading.Thread(target=self._read, daemon=True)
        self.stderr_reader = threading.Thread(target=self._stderr, daemon=True)
        self.stdout_reader.start()
        self.stderr_reader.start()

    def _read(self):
        try:
            while True:
                raw = self.process.stdout.readline(MAX_FRAME + 1)
                if not raw:
                    self.queue.put(("eof", None))
                    return
                require(len(raw) <= MAX_FRAME, "host_rpc_frame_limit")
                value = core.strict_json_loads(raw.decode("utf-8"))
                require(isinstance(value, dict), "host_rpc_frame_shape")
                self.queue.put(("message", value))
        except (ValueError, UnicodeError, OSError, RecursionError):
            self.queue.put(("reader_failed", None))
            # 已拒绝该流，仍排空自有管道，避免最终通知因回压阻止宿主退出。
            try:
                while self.process.stdout.read(65536):
                    pass
            except OSError:
                pass

    def _stderr(self):
        try:
            while True:
                raw = self.process.stderr.readline(MAX_STDERR_LINE + 1)
                if not raw:
                    return
                self.stderr_hash.update(raw)
                self.stderr_bytes += len(raw)
                if len(raw) > MAX_STDERR_LINE:
                    self.stderr_observation_rejected = True
                    # 保留拒绝状态并排空管道，不能因日志回压阻塞原生退出。
                    while raw := self.process.stderr.read(65536):
                        self.stderr_hash.update(raw)
                        self.stderr_bytes += len(raw)
                    return
                try:
                    value = core.strict_json_loads(raw.decode("utf-8"))
                except (ValueError, UnicodeError, RecursionError):
                    continue
                if not isinstance(value, dict) or value.get("target") != REMOTE_LOG_TARGET + "::websocket":
                    continue
                fields = value.get("fields")
                if not isinstance(fields, dict) or fields.get("message") != "app-server remote control websocket loop started":
                    continue
                if len(self.remote_control_startup_states) >= 32:
                    self.stderr_observation_rejected = True
                    continue
                state = fields.get("initial_desired_state")
                self.remote_control_startup_states.append(state if state in ("Disabled", "Unknown") else "other_redacted")
        except OSError:
            self.stderr_observation_rejected = True

    def send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False).encode() + b"\n")
        self.process.stdin.flush()

    def request(self, method, params, identity):
        require(method in {"initialize", "skills/list"}, "host_method_not_allowed")
        self.send({"id": identity, "method": method, "params": params})
        deadline = time.monotonic() + 20
        while True:
            try:
                kind, message = self.queue.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                raise HostError("host_rpc_timeout") from None
            require(kind == "message", "host_rpc_" + kind)
            if "method" in message:
                require("id" not in message, "host_unexpected_server_request")
            else:
                require(message.get("id") == identity and "error" not in message and "result" in message, "host_rpc_rejected")
                return message["result"]
            require(time.monotonic() < deadline, "host_rpc_timeout")


def discover(executable, workspace, *, override=None):
    require(_WINDOWS, "host_platform_not_verified")
    require(digest(executable) == CLI_SHA256, "host_cli_not_verified")
    # 默认全局发现会触发插件和模型目录后台活动。本入口明确采用本地Skill元数据模式。
    catalog_bytes = (json.dumps(metadata_catalog(), ensure_ascii=False) + "\n").encode("utf-8")
    control = Path(tempfile.mkdtemp(prefix="dyz-host-metadata-"))
    catalog = control / "metadata-only-model-catalog.json"
    with catalog.open("xb") as stream:
        stream.write(catalog_bytes)
    command = [str(executable), "-c", "analytics.enabled=false", "-c", "features.plugins=false",
        "-c", "model_catalog_json=" + json.dumps(str(catalog))]
    if override is not None:
        command += ["-c", override]
    command += ["app-server", "--listen", "stdio://"]
    try:
        require(len(subprocess.list2cmdline(command).encode("utf-16-le")) // 2 + 1 <= 32767,
                "host_profile_command_line_too_long")
        process = subprocess.Popen(command, cwd=workspace, env=metadata_environment(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (HostError, OSError):
        catalog.unlink()
        control.rmdir()
        raise
    rpc = _MetadataRpc(process)
    lifecycle = {"pid": process.pid, "model_inference_requested": False, "persistent_config_write_requested": False,
        "probe_mode": PROBE_MODE, "argv": command,
        "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(), "catalog_directory": str(control),
        "catalog_retained": True, "environment_keys": sorted(metadata_environment()), "rpc_stages": [],
        "native_process_counters": {"spawn": native_process_counters(process)}}
    pending_error = None
    reply = None
    try:
        require(lifecycle["native_process_counters"]["spawn"].get("status") == "observed_owned_handle",
                "host_native_identity_unverified")
        rpc.request("initialize", {"clientInfo": {"name": "dyz_codex_host_profile", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True, "explicitGatewayOauth": True}}, 1)
        lifecycle["rpc_stages"].append("initialize_completed")
        rpc.send({"method": "initialized", "params": {}})
        reply = rpc.request("skills/list", {"cwds": [str(workspace)], "forceReload": True}, 2)
        lifecycle["rpc_stages"].append("skills_list_completed")
    except HostError as error:
        pending_error = error
    except OSError:
        pending_error = HostError("host_rpc_io_failed")
    finally:
        closed = time.monotonic()
        try:
            process.stdin.close()
        except OSError:
            pass
        lifecycle["native_process_counters"]["stdin_closed"] = native_process_counters(process)
        lifecycle["stdin_closed_then_exit_within5s"] = False
        try:
            process.wait(timeout=5)
            lifecycle["stdin_closed_then_exit_within5s"] = time.monotonic() - closed <= 5
        except subprocess.TimeoutExpired:
            pass
        finally:
            lifecycle["close_to_wait_seconds"] = round(time.monotonic() - closed, 6)
            lifecycle["native_process_counters"]["after_wait"] = native_process_counters(process)
            rpc.stdout_reader.join(timeout=1)
            rpc.stderr_reader.join(timeout=1)
            if process.poll() is not None and not rpc.stdout_reader.is_alive():
                process.stdout.close()
            if process.poll() is not None and not rpc.stderr_reader.is_alive():
                process.stderr.close()
    lifecycle.update(exit_code=process.poll(), stderr_bytes=rpc.stderr_bytes,
        stderr_sha256=rpc.stderr_hash.hexdigest(), readers_finished=not rpc.stdout_reader.is_alive() and not rpc.stderr_reader.is_alive(),
        remote_control_bootstrap_requested_disabled=True,
        remote_control_startup_states=list(rpc.remote_control_startup_states),
        stderr_observation_rejected=rpc.stderr_observation_rejected,
        methods=["initialize", "initialized", "skills/list"])
    if pending_error is not None:
        lifecycle["rpc_error"] = str(pending_error)
    born = lifecycle["native_process_counters"]["spawn"].get("creation_filetime_100ns")
    lifecycle["native_identity_verified"] = type(born) is int and born > 0 and all(
        sample.get("status") == "observed_owned_handle" and sample.get("pid") == process.pid
        and sample.get("creation_filetime_100ns") == born for sample in lifecycle["native_process_counters"].values())
    if not lifecycle["stdin_closed_then_exit_within5s"]:
        raise HostError("host_shutdown_deadline_exceeded_pid_" + str(process.pid), diagnostic_lifecycle(lifecycle))
    if process.returncode != 0 or not lifecycle["readers_finished"]:
        raise HostError("host_exit_failed", diagnostic_lifecycle(lifecycle))
    if not lifecycle["native_identity_verified"]:
        raise HostError("host_native_identity_unverified", diagnostic_lifecycle(lifecycle))
    if pending_error is not None:
        raise HostError(str(pending_error), diagnostic_lifecycle(lifecycle))
    if (not rpc.remote_control_startup_states or any(s != "Disabled" for s in rpc.remote_control_startup_states)
            or rpc.stderr_observation_rejected):
        raise HostError("host_remote_control_startup_not_disabled", diagnostic_lifecycle(lifecycle))
    # 只清理本函数创建的两个确切目标；失败时保留目录供检查，不递归删除。
    catalog.unlink()
    control.rmdir()
    lifecycle["catalog_retained"] = False
    try:
        rows, errors = inventory_from_reply(reply, workspace)
    except HostError as error:
        raise HostError(str(error), diagnostic_lifecycle(lifecycle)) from None
    return rows, errors, lifecycle


def create_profile(package, manifest_sha256, executable, workspace):
    package, executable, workspace = regular(package, directory=True), regular(executable), regular(workspace, directory=True)
    require(manifest_sha256 is not None, "host_external_manifest_hash_required")
    verified = bundle.verify_bundle(package, expected_manifest_sha256=manifest_sha256)
    require(digest(executable) == CLI_SHA256, "host_cli_not_verified")
    expected = skill_metadata(package)
    completed = []
    def observe(phase, override=None):
        try:
            result = discover(executable, workspace, **({"override": override} if override is not None else {}))
        except HostError as error:
            raise HostError(str(error), {"phase": phase,
                "completed_processes": [diagnostic_lifecycle(p) for p in completed],
                "failed_process": diagnostic_lifecycle(error.observations)}) from None
        completed.append(result[2])
        return result
    before, before_errors, first = observe("baseline")
    selected = select_six(before, expected)
    selectors = selectors_for(before, selected)
    override = selector_override(selectors)
    scoped, scoped_errors, second = observe("scoped", override=override)
    selected_scoped = select_six(scoped, expected)
    if {r["name"] for r in scoped if r["enabled"]} != SKILLS or sum(r["enabled"] for r in scoped) != len(SKILLS):
        raise HostError("host_process_selection_not_effective", {
            "baseline_counts": {"discovered": len(before), "enabled": sum(r["enabled"] for r in before)},
            "scoped_counts": {"discovered": len(scoped), "enabled": sum(r["enabled"] for r in scoped)},
            "owned_processes": [diagnostic_lifecycle(first), diagnostic_lifecycle(second)],
            "baseline_recheck": "not_performed_after_failure"})
    after, after_errors, third = observe("baseline_recheck")
    require(inventory_fingerprint(before) == inventory_fingerprint(after) and before_errors == after_errors, "host_baseline_inventory_changed")
    require(digest(executable) == CLI_SHA256, "host_cli_changed_during_check")
    bundle.verify_bundle(package, expected_manifest_sha256=manifest_sha256)
    return {"kind": "codex_process_skill_profile", "status": "local_process_metadata_verified", "version": 3,
        "package": str(package), "manifest_sha256": manifest_sha256, "source_files": verified["source_files"],
        "executable": str(executable), "executable_sha256": CLI_SHA256, "cli_version": CLI_VERSION,
        "workspace": str(workspace), "selected_skills": selected_scoped,
        "thread_config_candidate": {"skills.config": selectors, "features.plugins": False},
        "thread_config_validation": "not_started_or_checked_by_this_tool",
        "process_config_arguments": ["-c", "features.plugins=false", "-c", override],
        "probe_mode": PROBE_MODE,
        "metadata_bootstrap_environment": {REMOTE_DISABLED_ENV: "1", "LOG_FORMAT": "json",
            "RUST_LOG": "off," + REMOTE_LOG_TARGET + "=info"},
        "baseline_before_after_equal": True, "baseline_inventory_sha256": inventory_fingerprint(before),
        "baseline_counts": {"discovered": len(before), "enabled": sum(r["enabled"] for r in before), "errors": before_errors},
        "scoped_counts": {"discovered": len(scoped), "enabled": sum(r["enabled"] for r in scoped), "errors": scoped_errors},
        "after_errors": after_errors, "owned_processes": [first, second, third],
        "model_inference_requested": False, "thread_or_turn_started": False, "persistent_config_write_requested": False,
        "default_global_inventory": "not_checked_this_tool", "native_background_network": "not_monitored_not_network_isolation",
        "model_visibility_and_routing": "not_checked", "business_tools": "host_supplied_not_injected_by_profile",
        "professional_review": "not_performed", "installation": "not_performed",
        "scope": "Only local Skill process metadata with plugins disabled, actual remote-control startup Disabled observed and an owned synthetic static model catalog. Bootstrap environment is for the metadata probe; selection arguments are not a complete model host launch. Synthetic catalog is never suitable for model tasks. Not thread/model, OS/network isolation, business tools, or a default-global fix. Generated selectors contain local Skill inventory names; keep this profile local."}


def _probe_environment():
    keep = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "SYSTEMDRIVE", "HOME", "LANG", "LC_ALL"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def probe_host_capabilities(executable, *, allow_unpinned=False):
    """非破坏性宿主二进制版本与能力探测；不启动模型推理，不将未钉死版本冒充已核验。"""
    require(type(allow_unpinned) is bool, "allow_unpinned_bool_required")
    raw_path = bundle._absolute(executable)
    require(raw_path.suffix.casefold() not in {".bat", ".cmd", ".ps1", ".psm1", ".sh", ".bash", ".zsh", ".fish",
                                              ".py", ".pyw", ".pl", ".rb", ".js", ".vbs", ".wsf"},
            "host_executable_script_rejected")
    exe = regular(raw_path).resolve(strict=True)
    actual_sha = digest(exe)
    pinned = actual_sha == CLI_SHA256
    if not pinned and not allow_unpinned:
        raise HostError("host_cli_not_verified")
    try:
        with tempfile.TemporaryDirectory(prefix="dyz-host-probe-") as probe_directory:
            version_exit, version_text = _probe_version(exe, probe_directory)
    except OSError:
        version_exit, version_text = -1, ""
    try:
        unchanged = regular(raw_path).resolve(strict=True) == exe and digest(exe) == actual_sha
    except (bundle.BundleError, HostError, OSError):
        unchanged = False
    require(unchanged, "host_executable_changed")
    return {
        "kind": "host_capability_probe",
        "platform": sys.platform,
        "executable": str(exe),
        "executable_sha256": actual_sha,
        "pinned_match": pinned,
        "pinned_version": CLI_VERSION,
        "observed_version": version_text,
        "version_exit_code": version_exit,
        "qualification": "pinned_metadata_binary" if pinned else "unpinned_runtime_capability_probe_only",
        "model_inference_requested": False,
        "installation": "not_performed",
    }


def _probe_version(exe, cwd):
    try:
        proc = subprocess.Popen(
            [str(exe), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=_probe_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        chunks: list[bytes] = []
        captured = 0

        def _drain() -> None:
            nonlocal captured
            stream = proc.stdout
            if stream is None:
                return
            try:
                while True:
                    block = stream.read(4096)
                    if not block:
                        break
                    if captured < 8192:
                        take = block[: 8192 - captured]
                        chunks.append(take)
                        captured += len(take)
            except OSError:
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()
        timed_out = False
        try:
            proc.wait(timeout=10)
            version_exit = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            version_exit = -1
        finally:
            reader.join(timeout=1)
        raw_out = b"" if timed_out else b"".join(chunks)
        first_line = raw_out.decode("utf-8", errors="replace").strip().splitlines()
        version_text = first_line[0][:200] if first_line else ""
    except OSError:
        version_exit = -1
        version_text = ""
    return version_exit, version_text


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="核包并实测Codex六入口本地进程配置；关闭本进程插件、使用合成模型元数据；不调用模型、不安装或写持久配置")
    parser.add_argument("--package", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--codex-executable", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        package = regular(args.package, directory=True)
        output = regular(args.output, missing=True)
        require(not output.exists() and output.parent.is_dir(), "host_output_exists_or_parent_missing")
        require(not output.is_relative_to(package), "host_output_inside_package")
        report = create_profile(package, args.manifest_sha256, args.codex_executable, args.workspace)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (HostError, bundle.BundleError, core.ContractError) as error:
        print(json.dumps({"status": "rejected", "error": str(error),
                          "observations": getattr(error, "observations", None)}, ensure_ascii=False))
        return 2
    except (OSError, ValueError, TypeError, UnicodeError):
        print("host_profile_io_or_input_failed")
        return 3
    print(json.dumps({"status": report["status"], "selected": len(report["selected_skills"]),
        "baseline_counts": report["baseline_counts"], "scoped_counts": report["scoped_counts"],
        "baseline_unchanged": True, "default_global_inventory": "not_checked_this_tool",
        "model_inference_requested": False, "profile_written": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
