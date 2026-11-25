"""跨平台多宿主本地安装包与配置生成器；不改写用户全局目录，不联网。

通过 tools.bundle 构建白名单冻结包，并生成指向共享包根的 6 入口索引与
MCP 客户端配置样例，避免单拆某个 SKILL.md 导致共享 tools/ 失效。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools
from tools import bundle, core, mcp_server

INSTALL_MANIFEST_NAME = "dyz-install-manifest.json"
SKILLS_MANIFEST_NAME = "skills-manifest.json"
MAX_INSTALL_FILE_BYTES = 1_000_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SKILL_NAMES = (
    "dyz-patent",
    "dyz-procedure",
    "dyz-software",
    "dyz-standards",
    "dyz-rendering",
    "dyz-workbench",
)
SUPPORTED_HOSTS = mcp_server.HOST_PROFILES


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_checked_regular(path: Path, *, max_bytes: int = MAX_INSTALL_FILE_BYTES) -> bytes:
    info = core.checked_path(path)
    if info is None or not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
        raise bundle.BundleError("install_file_invalid")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise bundle.BundleError("install_file_invalid")
    return raw


def _build_skills_manifest_bytes(bundle_dir: Path, *, host: str, manifest_sha: str, version: str) -> bytes:
    skills_index = []
    for name in SKILL_NAMES:
        skill_file = bundle_dir / "skills" / name / "SKILL.md"
        skills_index.append({
            "name": name,
            "skill_md": str(skill_file),
            "relative_path": f"bundle/skills/{name}/SKILL.md",
            "sha256": _sha256_file(skill_file),
            "shared_bundle_root": str(bundle_dir),
        })
    payload = {
        "schema": "dyz-skills-index-v1",
        "version": version,
        "host": host,
        "shared_bundle_root": str(bundle_dir),
        "bundle_manifest_sha256": manifest_sha,
        "skills": skills_index,
        "note": "All six skills share bundle/tools and bundle/references; do not split single SKILL.md folders.",
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


_PYTHON_BASENAME_RE = re.compile(r"^(?:python(?:\d+(?:\.\d+)*)?(?:-(?:32|64))?|py)(?:\.exe)?$", re.IGNORECASE)
_FORBIDDEN_CMD_CHARS = frozenset(";|&`$%><*?\"'")


def _safe_python_command(command: str) -> bool:
    if not isinstance(command, str) or not command:
        return False
    if any(ch.isspace() or ord(ch) < 32 or 127 <= ord(ch) <= 159 or ch in _FORBIDDEN_CMD_CHARS for ch in command):
        return False
    norm = command.replace("\\", "/")
    if norm.startswith(("//", "-")) or norm.endswith(("/", "/.")):
        return False
    win_path = PureWindowsPath(command)
    if win_path.drive.startswith("\\\\"):
        return False
    if command.startswith("\\"):
        return False
    # 按路径语法而非当前宿主 OS 选择纯路径解析器，保证 Windows 与 POSIX 路径在所有 CI/宿主机上行为一致！
    parsed = win_path if (win_path.drive or "\\" in command) else PurePosixPath(command)
    if ".." in parsed.parts:
        return False
    if not parsed.is_absolute() and ("/" in norm or command.startswith(".") or parsed.drive):
        return False
    if any(":" in part for part in parsed.parts if part != parsed.anchor):
        return False
    return _PYTHON_BASENAME_RE.fullmatch(parsed.name) is not None


def _require_target_arg(target: str | Path) -> Path:
    if not isinstance(target, (str, Path)) or not str(target).strip() or "\x00" in str(target):
        raise bundle.BundleError("bundle_path_invalid")
    return bundle._absolute(target)

def _check_new_target(target: Path) -> None:
    if core.checked_path(target, missing_leaf=True) is not None:
        raise bundle.BundleError("install_target_exists")


def _mcp_config_name(host: str) -> str:
    return f"mcp-config.{host}.{'toml' if host == 'codex' else 'json'}"



def plan_install(target: str | Path, *, host: str = "generic", source_root: str | Path | None = None) -> dict:
    if host not in SUPPORTED_HOSTS:
        raise ValueError("unsupported_host_profile")
    dest = _require_target_arg(target)
    _check_new_target(dest)
    root = bundle._absolute(source_root if source_root is not None else Path(__file__).resolve().parents[1])
    bundle_dir = dest / "bundle"
    return {
        "action": "dry_run_plan",
        "version": tools.__version__,
        "host": host,
        "platform": sys.platform,
        "python": ".".join(map(str, sys.version_info[:3])),
        "source_root": str(root),
        "target_dir": str(dest),
        "bundle_dir": str(bundle_dir),
        "planned_source_files": len(bundle.BUNDLE_FILES),
        "skills": list(SKILL_NAMES),
        "global_host_config_modified": False,
    }


def install_bundle(
    target: str | Path,
    *,
    host: str = "generic",
    source_root: str | Path | None = None,
    python_executable: str | None = None,
) -> dict:
    """Install a verified bundle + host skill index + MCP config into a new target directory.

    Atomicity: cleans up only files/directories created by this call on failure.
    """
    if host not in SUPPORTED_HOSTS:
        raise ValueError("unsupported_host_profile")
    py_exe = sys.executable if python_executable is None else python_executable
    if not _safe_python_command(py_exe):
        raise ValueError("invalid_python_executable")

    dest = _require_target_arg(target)
    _check_new_target(dest)

    dest.mkdir(exist_ok=False)
    bundle_dir = dest / "bundle"
    created_files: list[Path] = []
    copied = ()
    try:
        copied = bundle.build_bundle(bundle_dir, source_root=source_root)
        manifest_path = bundle_dir / bundle.MANIFEST_NAME
        manifest_sha = _sha256_file(manifest_path)
        verified = bundle.verify_bundle(bundle_dir, expected_manifest_sha256=manifest_sha)

        skills_bytes = _build_skills_manifest_bytes(
            bundle_dir, host=host, manifest_sha=manifest_sha, version=tools.__version__,
        )
        skills_manifest_path = dest / SKILLS_MANIFEST_NAME
        with skills_manifest_path.open("xb") as fh:
            created_files.append(skills_manifest_path)
            fh.write(skills_bytes)

        mcp_snippet = mcp_server.render_client_config(
            host=host,
            python_executable=py_exe,
            package_path=str(bundle_dir),
        )
        mcp_config_bytes = mcp_server.client_config_text(mcp_snippet).encode("utf-8")
        mcp_config_path = dest / _mcp_config_name(host)
        with mcp_config_path.open("xb") as fh:
            created_files.append(mcp_config_path)
            fh.write(mcp_config_bytes)

        record = {
            "schema": "dyz-install-manifest-v1",
            "status": "installed_locally_needs_host_registration",
            "version": tools.__version__,
            "host": host,
            "platform": sys.platform,
            "python": ".".join(map(str, sys.version_info[:3])),
            "python_executable": py_exe,
            "bundle_dir": "bundle",
            "bundle_files": len(copied) - 1,
            "bundle_manifest_sha256": manifest_sha,
            "skills_manifest": skills_manifest_path.name,
            "skills_manifest_sha256": hashlib.sha256(skills_bytes).hexdigest(),
            "mcp_config": mcp_config_path.name,
            "mcp_config_sha256": hashlib.sha256(mcp_config_bytes).hexdigest(),
            "global_host_config_modified": False,
            "host_auto_discovery_verified": False,
            "professional_review": "not_performed",
            "verified_source_files": verified["source_files"],
        }
        install_manifest_path = dest / INSTALL_MANIFEST_NAME
        manifest_bytes = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with install_manifest_path.open("xb") as fh:
            created_files.append(install_manifest_path)
            fh.write(manifest_bytes)
        return {**record, "install_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}
    except BaseException:
        bundle_files = [bundle_dir / path for path in copied]
        bundle_dirs = {parent for path in bundle_files for parent in path.parents if parent.is_relative_to(bundle_dir)}
        for path in (*reversed(created_files), *reversed(bundle_files)):
            try:
                if core.checked_path(path, missing_leaf=True) is not None:
                    path.unlink()
            except (OSError, bundle.BundleError):
                pass
        for path in (*sorted(bundle_dirs, key=lambda p: len(p.parts), reverse=True), dest):
            try:
                if core.checked_path(path, missing_leaf=True) is not None:
                    path.rmdir()
            except (OSError, bundle.BundleError):
                pass
        raise


def verify_installation(
    target: str | Path,
    *,
    expected_bundle_manifest_sha256: str | None = None,
    expected_install_manifest_sha256: str | None = None,
    expected_python_executable: str | None = None,
    expected_host: str | None = None,
) -> dict:
    """Verify an installed directory strictly against path traversal, symlinks, and config tampering."""
    if expected_bundle_manifest_sha256 is not None and (
        not isinstance(expected_bundle_manifest_sha256, str)
        or SHA256_RE.fullmatch(expected_bundle_manifest_sha256) is None
    ):
        raise bundle.BundleError("bundle_manifest_hash_invalid")
    if expected_install_manifest_sha256 is not None and (
        not isinstance(expected_install_manifest_sha256, str)
        or SHA256_RE.fullmatch(expected_install_manifest_sha256) is None
    ):
        raise bundle.BundleError("install_manifest_hash_invalid")
    if expected_python_executable is not None and not _safe_python_command(expected_python_executable):
        raise bundle.BundleError("invalid_expected_python_executable")
    if expected_host is not None and expected_host not in SUPPORTED_HOSTS:
        raise bundle.BundleError("unsupported_host_profile")

    dest = _require_target_arg(target)
    info = core.checked_path(dest)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise bundle.BundleError("install_target_not_directory")

    manifest_file = dest / INSTALL_MANIFEST_NAME
    try:
        raw_manifest = _read_checked_regular(manifest_file)
    except bundle.BundleError as exc:
        if str(exc) == "bundle_path_missing":
            raise bundle.BundleError("install_manifest_missing") from None
        raise
    install_manifest_sha = hashlib.sha256(raw_manifest).hexdigest()
    if expected_install_manifest_sha256 is not None and install_manifest_sha != expected_install_manifest_sha256:
        raise bundle.BundleError("install_manifest_binding_changed")

    try:
        record = json.loads(raw_manifest.decode("utf-8"), object_pairs_hook=bundle._manifest_object)
    except (ValueError, UnicodeError, RecursionError):
        raise bundle.BundleError("install_manifest_invalid") from None
    expected_keys = {
        "schema", "status", "version", "host", "platform", "python", "python_executable",
        "bundle_dir", "bundle_files", "bundle_manifest_sha256",
        "skills_manifest", "skills_manifest_sha256", "mcp_config", "mcp_config_sha256",
        "global_host_config_modified", "host_auto_discovery_verified",
        "professional_review", "verified_source_files",
    }
    if (
        not isinstance(record, dict)
        or set(record) != expected_keys
        or record.get("schema") != "dyz-install-manifest-v1"
        or record.get("status") != "installed_locally_needs_host_registration"
        or record.get("global_host_config_modified") is not False
        or record.get("host_auto_discovery_verified") is not False
        or record.get("professional_review") != "not_performed"
    ):
        raise bundle.BundleError("install_manifest_invalid")

    host = record.get("host")
    version = record.get("version")
    py_exe = record.get("python_executable")
    rec_bundle_sha = record.get("bundle_manifest_sha256")
    if (
        host not in SUPPORTED_HOSTS
        or not isinstance(version, str) or not version.strip()
        or not isinstance(record.get("platform"), str) or not record["platform"].strip()
        or not isinstance(record.get("python"), str) or not record["python"].strip()
        or not _safe_python_command(py_exe)
        or not isinstance(rec_bundle_sha, str) or SHA256_RE.fullmatch(rec_bundle_sha) is None
        or record.get("bundle_dir") != "bundle"
        or record.get("skills_manifest") != SKILLS_MANIFEST_NAME
        or record.get("mcp_config") != _mcp_config_name(host)
    ):
        raise bundle.BundleError("install_manifest_invalid")
    if expected_host is not None and host != expected_host:
        raise bundle.BundleError("install_host_binding_changed")
    if expected_python_executable is not None and py_exe != expected_python_executable:
        raise bundle.BundleError("mcp_command_binding_changed")

    if expected_bundle_manifest_sha256 is not None and rec_bundle_sha != expected_bundle_manifest_sha256:
        raise bundle.BundleError("bundle_manifest_binding_changed")
    expected_sha = expected_bundle_manifest_sha256 if expected_bundle_manifest_sha256 is not None else rec_bundle_sha

    bundle_dir = dest / "bundle"
    verified = bundle.verify_bundle(bundle_dir, expected_manifest_sha256=expected_sha)
    if (
        record.get("bundle_files") != verified["source_files"]
        or record.get("verified_source_files") != verified["source_files"]
    ):
        raise bundle.BundleError("install_manifest_invalid")

    # Reconstruct expected skills-manifest.json deterministically from the verified bundle!
    skills_path = dest / SKILLS_MANIFEST_NAME
    actual_skills_raw = _read_checked_regular(skills_path)
    expected_skills_raw = _build_skills_manifest_bytes(
        bundle_dir, host=host, manifest_sha=expected_sha, version=version,
    )
    if (
        actual_skills_raw != expected_skills_raw
        or hashlib.sha256(actual_skills_raw).hexdigest() != record.get("skills_manifest_sha256")
    ):
        raise bundle.BundleError("skills_manifest_tampered")

    mcp_path = dest / _mcp_config_name(host)
    actual_mcp_raw = _read_checked_regular(mcp_path)
    expected_mcp_snippet = mcp_server.render_client_config(
        host=host,
        python_executable=py_exe,
        package_path=str(bundle_dir),
    )
    expected_mcp_raw = mcp_server.client_config_text(expected_mcp_snippet).encode("utf-8")
    if (
        actual_mcp_raw != expected_mcp_raw
        or hashlib.sha256(actual_mcp_raw).hexdigest() != record.get("mcp_config_sha256")
    ):
        raise bundle.BundleError("mcp_config_tampered")

    binding = (
        "expected_install_and_bundle_hashes_matched"
        if expected_install_manifest_sha256 is not None and expected_bundle_manifest_sha256 is not None
        else "expected_install_manifest_hash_matched"
        if expected_install_manifest_sha256 is not None
        else "expected_bundle_manifest_hash_matched"
        if expected_bundle_manifest_sha256 is not None
        else "install_manifest_internal_consistency_only"
    )
    return {
        "status": "matched",
        "version": version,
        "host": host,
        "bundle_manifest_sha256": expected_sha,
        "install_manifest_sha256": install_manifest_sha,
        "install_manifest_bound": expected_install_manifest_sha256 is not None,
        "mcp_command_bound": expected_install_manifest_sha256 is not None or expected_python_executable is not None,
        "python_executable": py_exe,
        "binding": binding,
        "source_files": verified["source_files"],
        "global_host_config_modified": False,
        "host_auto_discovery_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or verify a self-contained DYZ bundle and MCP config snippet.")
    parser.add_argument("--target", required=True, help="New target directory (or existing directory with --verify).")
    parser.add_argument("--host", choices=SUPPORTED_HOSTS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Print dry-run installation plan without writing.")
    mode.add_argument("--verify", action="store_true", help="Verify an existing installation directory.")
    parser.add_argument("--manifest-sha256", help="Optional out-of-band bundle-manifest.json SHA-256 for --verify.")
    parser.add_argument("--install-manifest-sha256", help="Optional out-of-band dyz-install-manifest.json SHA-256 for --verify.")
    parser.add_argument("--expected-python-executable", help="Optional out-of-band expected MCP command for --verify.")
    args = parser.parse_args(argv)
    if any(value is not None for value in (args.manifest_sha256, args.install_manifest_sha256,
                                           args.expected_python_executable)) and not args.verify:
        parser.error("verification bindings require --verify")
    try:
        if args.plan:
            result = plan_install(args.target, host=args.host or "generic")
        elif args.verify:
            result = verify_installation(
                args.target,
                expected_bundle_manifest_sha256=args.manifest_sha256,
                expected_install_manifest_sha256=args.install_manifest_sha256,
                expected_python_executable=args.expected_python_executable,
                expected_host=args.host,
            )
        else:
            result = install_bundle(args.target, host=args.host or "generic")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (bundle.BundleError, ValueError, KeyError, TypeError, OSError) as exc:
        error = "install_io_error" if isinstance(exc, OSError) else str(exc)
        print(json.dumps({"status": "rejected", "error": error}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
