"""SW-01/02 的只读候选发现及 SW-05 集中确认；不生成材料或事实认证。"""

from __future__ import annotations

import copy
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from tools import core

# 前六项保持旧表单契约；新增可选项统一使用 value/evidence_id。
FIELD_CATALOG = (
    "software_id", "name", "version", "completed_date", "published_date",
    "runtime_environment", "development_hardware", "runtime_hardware",
    "development_os", "development_tools", "runtime_platform",
    "runtime_dependencies", "programming_language", "development_purpose",
    "application_domain", "main_functions", "technical_features",
)
OPTIONAL_VALUE_FIELDS = FIELD_CATALOG[6:]
MAX_FILE_BYTES = 10_000_000
LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".vue": "Vue",
    ".java": "Java", ".c": "C", ".h": "C", ".cpp": "C++",
    ".hpp": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin",
    ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".sh": "Shell",
    ".ps1": "PowerShell", ".r": "R", ".m": "Objective-C/Matlab",
    ".scala": "Scala",
}
GENERATED_PARTS = {"node_modules", ".git", ".venv", "__pycache__", "build",
                   "dist", "output", "outputs", "artifacts"}
SECRET_TEXT = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key)"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
CONFIG_NAMES = {
    "package.json", "app.json", "project.json", "project.config.json",
    "pyproject.toml", "cargo.toml", "go.mod", "pom.xml",
    "requirements.txt", "setup.cfg", "composer.json",
}
URL_CREDENTIALS = re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^\s/?#]*@")


class _PomTreeBuilder(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.depth = 0

    def doctype(self, name, pubid, system):
        raise ET.ParseError("pom_dtd_forbidden")

    def start(self, tag, attrs):
        self.depth += 1
        if self.depth > 64:
            raise ET.ParseError("pom_depth_exceeded")
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)


def _text(value: object, code: str) -> str:
    core.require(isinstance(value, str) and bool(value.strip()), code)
    return value


def _preflight(context: dict, use_system_time: bool) -> None:
    core.require_fields(context, ("environment", "permissions", "sensitivity", "purpose"))
    now = (datetime.now(timezone.utc).isoformat() if use_system_time else context.get("now"))
    core.preflight(context["environment"], context["permissions"],
                   sensitivity=context["sensitivity"], purpose=context["purpose"], now=now)


def _file_permissions(payload: dict) -> None:
    """整份清单先核许可；后列 deny/unknown 不能使前列提前读取。"""
    files = payload.get("files")
    core.require(isinstance(files, list) and bool(files), "file_inventory_required")
    groups = payload.get("material_permissions", [])
    core.require(isinstance(groups, list), "discovery_permissions_required")
    request = payload.get("request") or {}
    core.require(all(isinstance(item, dict) and isinstance(item.get("paths"), list)
                     and all(isinstance(path, str) for path in item["paths"])
                     for item in groups), "discovery_permissions_required")
    rights = {item.get("component_id"): item for item in request.get("rights", [])}
    ids = [entry.get("id", f"file-{index}") for index, entry in enumerate(files, start=1)
           if isinstance(entry, dict)]
    core.require(all(isinstance(value, str) and value for value in ids)
                 and len(ids) == len(set(ids)), "duplicate_file_id")
    for entry in files:
        core.require(isinstance(entry, dict), "discovery_file_required")
        path = _text(entry.get("path"), "relative_path_required")
        right = rights.get(entry.get("component_id"))
        if right is not None:
            core.require(right.get("permissions", {}).get("local_process") == "allow"
                         and right.get("requested_decision") != "prohibit"
                         and bool(right.get("evidence_ids")), "material_permission_not_proven")
        permission = entry.get("local_permission")
        if permission is None:
            covering = [item for item in groups if path in item.get("paths", [])]
            if covering:
                # 矛盾许可不默选 allow；同一清单不接受 deny 被宽许可覆盖。
                core.require(all(item.get("decision") == "allow" for item in covering),
                             "material_permission_not_proven")
                permission = covering[0]
        if permission is None:
            right = rights.get(entry.get("component_id"))
            if right:
                permission = {"decision": right.get("permissions", {}).get("local_process"),
                              "evidence_id": next(iter(right.get("evidence_ids", [])), None)}
        core.require(isinstance(permission, dict) and permission.get("decision") == "allow",
                     "material_permission_not_proven")
        _text(permission.get("evidence_id"), "material_permission_evidence_required")
        if entry.get("local_permission") is not None:
            core.require(not any(item.get("decision") != "allow" for item in groups
                                 if path in item.get("paths", [])),
                         "material_permission_not_proven")


def _sealed(body: dict) -> dict:
    return {**body, "binding": core.digest(body)}


def _verify(artifact: dict, kind: str) -> None:
    core.require(isinstance(artifact, dict) and artifact.get("kind") == kind,
                 "discovery_artifact_required")
    core.require(artifact.get("binding") == core.digest(
        {key: value for key, value in artifact.items() if key != "binding"}),
        "discovery_artifact_stale")


def _safe_value(value: object, secrets: list[str]) -> str | None:
    if isinstance(value, (dict, list)):
        value = ", ".join(str(item) for item in value) if isinstance(value, list) else None
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        return None
    if SECRET_TEXT.search(value) or any(secret in value for secret in secrets):
        return None
    return value.strip()


def _extract(path: str, text: str, sha256: str, secrets: list[str]) -> tuple[list, list]:
    candidates, facts = [], []

    def add(field: str, value: object, locator: str, *, inferred: bool = False) -> None:
        safe = _safe_value(value, secrets)
        if safe is None:
            return
        source = {"path": path, "sha256": sha256, "locator": locator}
        evidence = "discovery-" + core.digest(source)
        normalized = (safe if field in {"name", "version", "software_id"} else
                      {"description" if field == "runtime_environment" else "value": safe,
                       "evidence_id": evidence})
        candidate = {"field": field, "value": normalized,
                     "status": "inferred" if inferred else "candidate", "sources": [source]}
        candidates.append(candidate)
        facts.append({"id": evidence, "field": field, "value": safe,
                      "status": "candidate", "needs_confirm": True,
                      "source": {**source, "evidence_id": evidence},
                      "qualification": "file_declaration_not_verified_software_fact"})

    name = Path(path).name.casefold()
    if name in CONFIG_NAMES:
        if name == "go.mod":
            req_deps = []
            for lineno, raw_line in enumerate(text.splitlines(), start=1):
                line = raw_line.split("//", 1)[0].strip()
                if line.startswith("module "):
                    add("name", line[7:].strip().split("/")[-1], f"line:{lineno}", inferred=True)
                    add("development_tools", "Go toolchain", f"line:{lineno}", inferred=True)
                elif line.startswith("go "):
                    add("runtime_environment", "Go " + line[3:].strip(), f"line:{lineno}")
                elif re.match(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._/-]+\s+v\d", line):
                    req_deps.append(line.split()[0])
            if req_deps:
                add("runtime_dependencies", ", ".join(sorted(set(req_deps))[:40]), "go.mod:require", inferred=True)
            return candidates, facts
        if name == "requirements.txt":
            pkgs = []
            for raw_line in text.splitlines():
                if URL_CREDENTIALS.search(raw_line):
                    continue
                line = raw_line.split("#", 1)[0].strip()
                if line and not line.startswith("-"):
                    pkgs.append(re.split(r"[=<>!~;\s]", line, maxsplit=1)[0])
            if pkgs:
                add("runtime_dependencies", ", ".join(sorted(set(pkgs))[:40]), "requirements.txt", inferred=True)
                add("development_tools", "Python / pip", "requirements.txt", inferred=True)
            return candidates, facts
        if name == "setup.cfg":
            section = ""
            for lineno, raw_line in enumerate(text.splitlines(), start=1):
                line = raw_line.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip().lower()
                elif "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    k, v = k.strip().lower(), v.strip()
                    if section == "metadata":
                        if k == "name":
                            add("name", v, f"line:{lineno}", inferred=True)
                        elif k == "version":
                            add("version", v, f"line:{lineno}")
                        elif k == "description":
                            add("main_functions", v, f"line:{lineno}", inferred=True)
                    elif section == "options" and k == "python_requires":
                        add("runtime_environment", "Python " + v, f"line:{lineno}")
            return candidates, facts
        if name == "pom.xml":
            try:
                root_el = ET.fromstring(text, parser=ET.XMLParser(target=_PomTreeBuilder()))
            except ET.ParseError:
                return [], [{"status": "candidate", "needs_confirm": True,
                             "source": {"path": path, "sha256": sha256, "locator": "document"},
                             "reason": "configuration_unreadable"}]
            def _xml_child(el, tag_name):
                for child in el:
                    if child.tag.rsplit("}", 1)[-1] == tag_name and (child.text or "").strip():
                        return child.text.strip()
                return None
            for tag_name in ("name", "artifactId"):
                val = _xml_child(root_el, tag_name)
                if val:
                    add("name", val, f"pom.{tag_name}", inferred=True)
                    break
            ver = _xml_child(root_el, "version")
            if ver:
                add("version", ver, "pom.version")
            desc = _xml_child(root_el, "description")
            if desc:
                add("main_functions", desc, "pom.description", inferred=True)
            add("development_tools", "Apache Maven", "pom.xml", inferred=True)
            for child in root_el:
                if child.tag.rsplit("}", 1)[-1] == "properties":
                    jver = _xml_child(child, "java.version") or _xml_child(child, "maven.compiler.release")
                    if jver:
                        add("runtime_environment", "Java " + jver, "pom.properties.java.version")
            return candidates, facts
        try:
            data = tomllib.loads(text) if name in {"pyproject.toml", "cargo.toml"} else core.strict_json_loads(text)
        except (core.ContractError, ValueError, TypeError):
            return [], [{"status": "candidate", "needs_confirm": True,
                         "source": {"path": path, "sha256": sha256, "locator": "document"},
                         "reason": "configuration_unreadable"}]
        if not isinstance(data, dict):
            return [], []
        if name == "cargo.toml":
            add("development_tools", "Cargo / Rust", "cargo.toml", inferred=True)
        elif name == "pyproject.toml":
            add("development_tools", "Python / pyproject", "pyproject.toml", inferred=True)
        elif name == "package.json":
            add("development_tools", "Node.js / npm", "package.json", inferred=True)
        elif name == "composer.json":
            add("development_tools", "PHP / Composer", "composer.json", inferred=True)
        blocks = [("$", data)]
        for key in ("project", "package", "app", "expo"):
            if isinstance(data.get(key), dict):
                blocks.append(("$." + key, data[key]))
        for locator, block in blocks:
            for key in ("name", "displayName", "productName", "projectname"):
                # 包名、标题及导航名只提供线索，不能直接认定登记全称。
                if key in block:
                    add("name", block[key], locator + "." + key, inferred=True)
            if "version" in block:
                add("version", block["version"], locator + ".version")
            if "description" in block:
                add("main_functions", block["description"], locator + ".description", inferred=True)
            if "requires-python" in block:
                add("runtime_environment", "Python " + str(block["requires-python"]),
                    locator + ".requires-python")
            if "rust-version" in block:
                add("runtime_environment", "Rust " + str(block["rust-version"]),
                    locator + ".rust-version")
            elif "edition" in block and name == "cargo.toml":
                add("runtime_environment", "Rust edition " + str(block["edition"]),
                    locator + ".edition", inferred=True)
            engines = block.get("engines")
            if isinstance(engines, dict):
                for engine, version in sorted(engines.items()):
                    if engine in {"node", "python", "npm", "yarn"}:
                        add("runtime_environment", f"{engine} {version}",
                            locator + ".engines." + engine)
            dependencies = block.get("dependencies")
            if isinstance(dependencies, dict):
                add("runtime_dependencies", ", ".join(sorted(dependencies)),
                    locator + ".dependencies", inferred=True)
            elif isinstance(dependencies, list):
                add("runtime_dependencies", dependencies, locator + ".dependencies", inferred=True)
            require_map = block.get("require")
            if isinstance(require_map, dict) and name == "composer.json":
                add("runtime_dependencies", ", ".join(sorted(require_map)),
                    locator + ".require", inferred=True)
    elif name.startswith("readme"):
        for number, line in enumerate(text.splitlines(), start=1):
            if line.startswith("# "):
                add("name", line[2:].strip(), f"line:{number}", inferred=True)
                break
        # 同时识别中英文明示标签，不把随意正文或命令当作已验证功能；仍保持 inferred + needs_confirm。
        labels = {
            "功能：": "main_functions", "功能:": "main_functions",
            "主要功能：": "main_functions", "主要功能:": "main_functions",
            "技术特点：": "technical_features", "技术特点:": "technical_features",
            "用途：": "development_purpose", "用途:": "development_purpose",
            "开发目的：": "development_purpose", "开发目的:": "development_purpose",
            "所属领域：": "application_domain", "所属领域:": "application_domain",
            "运行环境：": "runtime_environment", "运行环境:": "runtime_environment",
            "运行平台：": "runtime_platform", "运行平台:": "runtime_platform",
            "开发工具：": "development_tools", "开发工具:": "development_tools",
            "开发操作系统：": "development_os", "开发操作系统:": "development_os",
            "版本：": "version", "版本:": "version",
            "version:": "version", "runtime:": "runtime_environment",
            "requirements:": "runtime_environment", "platform:": "runtime_platform",
            "os:": "development_os", "purpose:": "development_purpose",
            "domain:": "application_domain", "features:": "main_functions",
            "technical features:": "technical_features", "tools:": "development_tools",
        }
        for number, raw_line in enumerate(text.splitlines(), start=1):
            stripped = raw_line.strip().lstrip("-* ").strip()
            low = stripped.casefold()
            for prefix, field in labels.items():
                if low.startswith(prefix.casefold()):
                    val = stripped[len(prefix):].strip().strip("`*")
                    if val:
                        add(field, val, f"line:{number}", inferred=True)
                    break
            else:
                ver_match = re.match(r"(?i)^version\s*[:=]?\s*`?v?(\d+\.\d+(?:\.\d+)?(?:[a-z0-9.-]*)?)`?\s*$", stripped)
                if ver_match and not any(c["field"] == "version" for c in candidates):
                    add("version", ver_match[1], f"line:{number}", inferred=True)
    return candidates, facts


def discover(payload: dict, *, use_system_time: bool = False) -> dict:
    """只读显式 files；context 与整份文件 local_process/evidence 先于任何读取。

    必填 context/authorized_root/files。文件许可可为逐文件 local_permission
    {decision,evidence_id}，material_permissions 中明确 paths 的许可组，或 request
    内原有 rights 的 local_process/evidence_ids。返回内部候选工件，不写盘、不执行
    程序、不发现未声明文件。use_system_time 只能由可信调用者以关键字传入。
    """
    core.require_fields(payload, ("context", "authorized_root", "files"))
    _preflight(payload["context"], use_system_time)
    secrets = payload.get("sensitive_literals", [])
    core.require(isinstance(secrets, list) and all(isinstance(s, str) and s for s in secrets),
                 "sensitive_literals_required")
    try:
        root = Path(payload["authorized_root"]).resolve(strict=True)
        core.require(root.is_dir(), "authorized_root_required")
        core.require(isinstance(payload["files"], list) and bool(payload["files"]), "file_inventory_required")
        groups = payload.get("material_permissions", [])
        core.require(isinstance(groups, list), "discovery_permissions_required")
        normalized_groups, denied_identities = [], set()
        for group in groups:
            core.require(isinstance(group, dict) and isinstance(group.get("paths"), list),
                         "discovery_permissions_required")
            normalized = []
            for relative in group["paths"]:
                path = core.safe_path(root, _text(relative, "relative_path_required"), must_exist=False)
                normalized.append(path.relative_to(root).as_posix())
                evidence = group.get("evidence_id")
                if group.get("decision") != "allow" or not isinstance(evidence, str) or not evidence.strip():
                    try:
                        st = path.stat()
                    except FileNotFoundError:
                        continue
                    denied_identities.add((st.st_dev, st.st_ino))
            normalized_groups.append({**group, "paths": normalized})
        paths, identities, checked = set(), set(), []
        for index, entry in enumerate(payload["files"], start=1):
            core.require(isinstance(entry, dict), "discovery_file_required")
            path = core.safe_path(root, _text(entry.get("path"), "relative_path_required"))
            core.require(path.is_file(), "source_file_required")
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino)
            core.require(identity not in denied_identities, "material_permission_not_proven")
            core.require(path not in paths and identity not in identities, "duplicate_source_path")
            core.require(stat.st_size <= MAX_FILE_BYTES, "source_file_too_large")
            paths.add(path)
            identities.add(identity)
            relative = path.relative_to(root).as_posix()
            core.require(not any(s in relative for s in secrets), "discovery_sensitive_path")
            parts = {part.casefold() for part in Path(relative).parts}
            name = path.name.casefold()
            reason = ("generated_or_dependency" if parts & GENERATED_PARTS else
                      "sensitive_file" if name == ".env" or name.startswith(".env.")
                      or path.suffix.casefold() in {".pem", ".key", ".p12", ".pfx"} else None)
            checked.append(({**entry, "path": relative}, path, relative, reason, index))
        _file_permissions({**payload, "files": [row[0] for row in checked],
                           "material_permissions": normalized_groups})
        file_candidates, candidates, facts, language_sources, languages = [], [], [], [], set()
        for entry, path, relative, reason, index in checked:
            language = LANGUAGES.get(path.suffix.casefold())
            record = {"id": entry.get("id", f"file-{index}"), "path": relative,
                      "sha256": None, "language": language, "exclusion_reason": reason,
                      "read_status": "not_read", "status": "candidate", "needs_confirm": True}
            if reason:
                file_candidates.append(record)
                continue
            _preflight(payload["context"], use_system_time)
            with path.open("rb") as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
            core.require(len(content) <= MAX_FILE_BYTES, "source_file_too_large")
            sha256 = core.sha256_bytes(content)
            if entry.get("expected_sha256") is not None:
                core.require(entry["expected_sha256"] == sha256, "source_hash_mismatch")
            record.update(sha256=sha256, read_status="read")
            try:
                text = content.decode(entry.get("encoding", "utf-8-sig"))
            except (UnicodeError, LookupError):
                record["exclusion_reason"] = "undecodable"
                file_candidates.append(record)
                continue
            if "\x00" in text:
                record["exclusion_reason"] = "binary_content"
            elif any(secret in text for secret in secrets):
                record["exclusion_reason"] = "sensitive_content"
            else:
                if language:
                    languages.add(language)
                    language_sources.append({"path": relative, "sha256": sha256, "locator": "suffix"})
                fields, clues = _extract(relative, text, sha256, secrets)
                candidates.extend(fields)
                facts.extend(clues)
            file_candidates.append(record)
        if languages:
            candidates.append({"field": "programming_language",
                               "value": {"value": ", ".join(sorted(languages)),
                                         "evidence_id": "discovery-" + core.digest(language_sources)},
                               "status": "inferred", "sources": language_sources})
        # 同一事实的重复引用合并来源，不把不同 evidence_id 当作值冲突。
        merged = {}
        for candidate in candidates:
            value = candidate["value"]
            semantic = ({key: item for key, item in value.items() if key != "evidence_id"}
                        if isinstance(value, dict) else value)
            key = (candidate["field"], core.digest(semantic))
            if key in merged:
                merged[key]["sources"].extend(candidate["sources"])
            else:
                merged[key] = copy.deepcopy(candidate)
        candidates = list(merged.values())
        for candidate in candidates:
            if isinstance(candidate["value"], dict):
                candidate["value"]["evidence_id"] = "discovery-" + core.digest(candidate["sources"])
        for field in FIELD_CATALOG:
            entries = [entry for entry in candidates if entry["field"] == field]
            if not entries:
                candidates.append({"field": field, "value": None, "status": "unknown", "sources": []})
            elif len({core.digest(entry["value"] if not isinstance(entry["value"], dict)
                                   else {key: value for key, value in entry["value"].items()
                                         if key != "evidence_id"}) for entry in entries}) > 1:
                for entry in entries:
                    entry["status"] = "conflict"
        body = {"kind": "software_discovery", "project_binding": core.digest(str(root)),
                "file_candidates": file_candidates, "field_candidates": candidates,
                "facts": facts, "needs_confirm": list(FIELD_CATALOG),
                "professional_review": "not_performed", "external_action": "not_performed"}
        return _sealed(body)
    except (OSError, RuntimeError, OverflowError):
        raise core.ContractError("discovery_io_failed") from None


def confirmation_group(payload: dict, *, use_system_time: bool = False) -> dict:
    """为一次核对生成绑定摘要；不制造任何 confirmed 记录。

    payload 的 request 是完整 prepare 输入，options 是交付选项（不交 prepare），
    discovery 为本模块工件。只可确认 worksheet 中来源有效且无冲突的候选。
    """
    from tools import software

    core.require_fields(payload, ("request", "discovery"))
    discovery = payload["discovery"]
    _verify(discovery, "software_discovery")
    request = copy.deepcopy(payload["request"])
    _preflight(request["context"], use_system_time)
    try:
        core.require(isinstance(request.get("authorized_root"), (str, Path)), "authorized_root_required")
        root = Path(request["authorized_root"]).resolve(strict=True)
        core.require(root.is_dir(), "authorized_root_required")
        core.require(core.digest(str(root)) == discovery["project_binding"], "discovery_project_mismatch")
        _file_permissions({"files": request["files"], "request": request})
        discovered = {row["path"]: row for row in discovery["file_candidates"]
                      if row["read_status"] == "read" and not row["exclusion_reason"]}
        for entry in request["files"]:
            actual = core.safe_path(root, entry["path"]).relative_to(root).as_posix()
            core.require(actual in discovered, "confirmation_source_not_discovered")
            expected = discovered[actual]["sha256"]
            core.require(entry.get("expected_sha256", expected) == expected,
                         "confirmation_source_binding_invalid")
            entry["expected_sha256"] = expected
    except (OSError, RuntimeError, OverflowError):
        raise core.ContractError("discovery_io_failed") from None
    request["field_candidates"] = copy.deepcopy(discovery["field_candidates"])
    # 旧独立确认可继续带入；新增组只绑定当前实际输入和候选摘要。
    prepared = software.prepare(request, use_system_time=use_system_time)["artifacts"]
    worksheet = prepared["worksheet"]
    rows = [{key: copy.deepcopy(row.get(key)) for key in
             ("field", "value", "candidate_digest", "sources", "reason", "candidate_status")}
            for row in worksheet["rows"]]
    eligible = [row["candidate_digest"] for row in rows
                if row["candidate_digest"] and row["candidate_status"] in {"candidate", "inferred"}
                and row["reason"] in {None, "field_confirmation_required", "field_confirmation_stale"}]
    return _sealed({"kind": "software_confirmation_group", "request": request,
                    "options": copy.deepcopy(payload.get("options", {})),
                    "discovery_binding": discovery["binding"], "input_binding": worksheet["input_binding"],
                    "rows": rows, "eligible_candidates": eligible,
                    "summary_digest": core.digest(rows), "status": "needs_confirm"})


def confirm_group(group: dict, decision: dict) -> dict:
    """把操作者实际确认展开为原有独立确认契约；拒绝旧组及未核对的全选。"""
    _verify(group, "software_confirmation_group")
    core.require_fields(decision, ("group_binding", "summary_digest", "input_binding",
                                  "status", "actor", "role", "evidence_id", "candidate_digests"))
    core.require(decision["group_binding"] == group["binding"]
                 and decision["summary_digest"] == group["summary_digest"]
                 and decision["input_binding"] == group["input_binding"], "confirmation_group_stale")
    core.require(decision["status"] == "confirmed", "field_confirmation_status_invalid")
    for key in ("actor", "role", "evidence_id"):
        _text(decision[key], "field_confirmation_evidence_required")
    selected = decision["candidate_digests"]
    core.require(isinstance(selected, list) and bool(selected)
                 and all(isinstance(item, str) for item in selected)
                 and len(selected) == len(set(selected))
                 and set(selected) <= set(group["eligible_candidates"]), "confirmation_selection_invalid")
    request = copy.deepcopy(group["request"])
    existing = {item["candidate_digest"]: item for item in request.get("confirmations", [])}
    for candidate_digest in selected:
        existing[candidate_digest] = {"candidate_digest": candidate_digest,
                                      "input_binding": group["input_binding"], "status": "confirmed",
                                      **{key: decision[key] for key in ("actor", "role", "evidence_id")}}
    request["confirmations"] = list(existing.values())
    return {"request": request, "options": copy.deepcopy(group["options"])}
