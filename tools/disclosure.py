"""固定合成包的披露演练：不联网、不提交、不认证真实身份。

SQLite journal 负责跨进程单次执行和保全；有写权限的本机操作者仍可篡改数据库。
所有签核均为合成角色记录，不能升级为真实专业意见或电子签章。
"""
from __future__ import annotations

import base64
import copy
import json
import re
import sqlite3
import unicodedata
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from xml.etree import ElementTree

from .core import (ContractError, VersionLedger, canonical_bytes, check_permission, digest,
                   parse_time, preflight, require, require_fields, safe_path,
                   sha256_bytes, strict_json_loads)
from . import rendering

FORMAT_BOUNDARIES = {
    ".txt": "UTF-8原始文本；控制字符检查；无版式或语义保证",
    ".json": "UTF-8完整JSON；重复键/非有限数拒绝；所有字段均纳入审核",
    ".md": "仅源文本；隐藏标记初筛；未渲染，候选阻断",
    ".svg": "仅XML结构；隐藏/活动内容初筛；未渲染，候选阻断",
}
ACTIONS = {"controlled_share", "public_disclosure", "service_processing",
           "formal_submission"}
ROLES = {"technical", "materials", "approver", "independent", "patent",
         "software", "standard"}


def _json(text: str):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate_json_key")
            value[key] = item
        return value

    def constant(_):
        raise ContractError("nonfinite_json")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def inspect_bytes(name: str, content: bytes) -> dict:
    """检查的是完整源字节，不把关键词扫描冒充联合语义/视觉审阅。"""
    suffix = Path(name).suffix.lower()
    issues = []
    if suffix not in FORMAT_BOUNDARIES:
        return {"status": "not_checked", "issues": ["unsupported_format"],
                "rendering": "not_checked", "hidden_scan": "not_checked"}
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {"status": "blocked", "issues": ["invalid_utf8"],
                "rendering": "not_checked", "hidden_scan": "not_checked"}
    if any(unicodedata.category(c) in {"Cc", "Cf"} and c not in "\n\r\t"
           for c in text):
        issues.append("hidden_control_character")
    if suffix == ".json":
        try:
            parsed = _json(text)
            canonical_bytes(parsed)
            # 识别本项目结构化内部工件，不以正文关键词猜测秘密或专业语义。
            def internal_artifact(value):
                if isinstance(value, dict):
                    if ("private_audit" in value or "selected_lines" in value
                            or value.get("kind") in ("software_source", "software_masked", "internal_report",
                                                      "software_delivery", "software_field_worksheet",
                                                      "software_local_authorization")
                            or {"source_binding", "operations"}.issubset(value)):
                        return True
                    return any(internal_artifact(item) for item in value.values())
                if isinstance(value, list):
                    return any(internal_artifact(item) for item in value)
                return False
            if internal_artifact(parsed):
                issues.append("internal_artifact_not_exportable")
        except (ValueError, RecursionError):
            issues.append("invalid_json")
    if suffix == ".md" and re.search(r"<!--|<[^>]+>|!\[|\]\(", text):
        issues.append("markup_or_embedded_content_requires_review")
    if suffix == ".svg":
        try:
            if "<!" in text:
                issues.append("xml_declaration_or_hidden_content")
            tree = ElementTree.fromstring(text)
            if tree.tag.split("}")[-1] != "svg":
                issues.append("invalid_svg_root")
            for node in tree.iter():
                tag = node.tag.split("}")[-1]
                if tag in {"script", "foreignObject", "image", "metadata", "style"}:
                    issues.append("svg_embedded_or_hidden_content")
                if any(key.split("}")[-1] in {"href", "style", "display", "opacity"}
                       or key.lower().startswith("on") for key in node.attrib):
                    issues.append("svg_active_or_visibility_attribute")
        except (ElementTree.ParseError, ValueError):
            issues.append("invalid_svg")
    rendering = "not_required_raw_text" if suffix in {".txt", ".json"} else "not_checked"
    if rendering == "not_checked":
        issues.append("rendering_not_checked")
    return {"status": "blocked" if issues else "source_checked",
            "issues": sorted(set(issues)), "rendering": rendering,
            "hidden_scan": "source_only", "semantic_review": "not_performed"}


def freeze_candidate(root: str | Path, files: list[dict], context: dict, *,
                     ledger: dict | None = None,
                     rendering_evidence: dict | None = None) -> dict:
    """只读取声明为合成且获准的材料一次；可选旁证不改变固定清单或原有门禁。"""
    require(context.get("sensitivity") == "synthetic", "synthetic_only")
    require_fields(context, ("environment", "permissions", "purpose", "now"))
    preflight(context["environment"], context["permissions"], sensitivity="synthetic",
              purpose=context["purpose"], now=context["now"])
    require(isinstance(files, list) and bool(files), "files_required")
    entries, snapshots, excluded, seen, contents = [], {}, [], set(), set()
    versions = VersionLedger((ledger or {}).get("records"), (ledger or {}).get("reviews"))
    for item in files:
        require_fields(item, ("file_id", "path", "version", "expected_sha256", "kind"))
        file_id = item["file_id"]
        require(isinstance(file_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", file_id)
                is not None, "invalid_file_id")
        require(file_id not in seen, "duplicate_file_id")
        seen.add(file_id)
        require(item["kind"] in {"external", "internal_report"}, "invalid_file_kind")
        if item["kind"] == "internal_report":
            excluded.append(file_id)
            continue
        require_fields(item, ("content_ids",))
        require(isinstance(item["content_ids"], list) and bool(item["content_ids"]),
                "content_inventory_required")
        require(all(isinstance(c, str) and c for c in item["content_ids"]),
                "invalid_content_id")
        require(len(set(item["content_ids"])) == len(item["content_ids"])
                and not contents.intersection(item["content_ids"]), "duplicate_content_id")
        contents.update(item["content_ids"])
        dependencies = item.get("dependency_ids", [])
        require(isinstance(dependencies, list) and len(set(dependencies)) == len(dependencies),
                "invalid_candidate_dependencies")
        require(all(versions.is_current(key) for key in dependencies), "candidate_dependencies_stale")
        dependency_hashes = {key: versions.records[key][-1]["hash"] for key in dependencies}
        path = safe_path(root, item["path"])
        require(path.is_file(), "file_required")
        content = path.read_bytes()
        byte_hash = sha256_bytes(content)
        scan = inspect_bytes(item["path"], content)
        if byte_hash != item["expected_sha256"]:
            scan["issues"].append("stale_source_version")
            scan["status"] = "blocked"
        entries.append({"file_id": file_id, "path": item["path"],
                        "version": item["version"], "sha256": byte_hash,
                        "expected_sha256": item["expected_sha256"], "size": len(content),
                        "content_ids": item["content_ids"], "inspection": scan,
                        "dependency_hashes": dependency_hashes})
        snapshots[file_id] = base64.b64encode(content).decode("ascii")
    require(bool(entries), "external_files_required")
    manifest = {"mode": "synthetic", "files": sorted(entries, key=lambda f: f["file_id"]),
                "excluded_internal_reports": sorted(excluded),
                "source_scope": "complete_raw_bytes_not_semantic_or_visual_review"}
    candidate = {"manifest": manifest, "manifest_hash": digest(manifest), "snapshots": snapshots}
    if rendering_evidence is not None:
        candidate["rendering_evidence"] = check_candidate_rendering(
            candidate, rendering_evidence, authorized_root=root, context=context,
            ledger=ledger, now=context["now"])
    return candidate


def validate_candidate(candidate: dict) -> None:
    require_fields(candidate, ("manifest", "manifest_hash", "snapshots"))
    manifest = candidate["manifest"]
    require(manifest.get("mode") == "synthetic", "synthetic_only")
    require(digest(manifest) == candidate["manifest_hash"], "manifest_hash_mismatch")
    require(bool(manifest.get("files")), "external_files_required")
    ids = [entry["file_id"] for entry in manifest["files"]]
    require(len(set(ids)) == len(ids), "duplicate_file_id")
    require(set(ids) == set(candidate["snapshots"]), "snapshot_inventory_mismatch")
    require(not set(ids).intersection(manifest.get("excluded_internal_reports", [])),
            "internal_report_in_candidate")
    for entry in manifest["files"]:
        try:
            content = base64.b64decode(candidate["snapshots"][entry["file_id"]], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError("invalid_snapshot") from exc
        require(sha256_bytes(content) == entry["sha256"] and len(content) == entry["size"],
                "snapshot_hash_mismatch")
        # 不信任载入JSON中的“检查通过”，始终检查固定字节。
        scan = inspect_bytes(entry["path"], content)
        if entry["sha256"] != entry.get("expected_sha256"):
            scan["issues"].append("stale_source_version")
            scan["status"] = "blocked"
        require(scan == entry["inspection"], "inspection_mismatch")


def _rendering_preflight(candidate: dict, context: dict, ledger: dict | None,
                         now: str) -> None:
    """旁证与预览只使用合成固定快照；权限及当前依赖先于旁证文件读取。"""
    require(isinstance(context, dict) and context.get("sensitivity") == "synthetic",
            "synthetic_only")
    require_fields(context, ("environment", "permissions", "purpose", "now"))
    require(parse_time(context["now"]) == parse_time(now), "rendering_context_time_mismatch")
    preflight(context["environment"], context["permissions"], sensitivity="synthetic",
              purpose=context["purpose"], now=now)
    validate_candidate(candidate)
    require(candidate.get("sensitivity", "synthetic") == "synthetic"
            and candidate["manifest"].get("sensitivity", "synthetic") == "synthetic",
            "synthetic_only")
    versions = VersionLedger((ledger or {}).get("records"), (ledger or {}).get("reviews"))
    for entry in candidate["manifest"]["files"]:
        dependencies = entry.get("dependency_hashes", {})
        require(isinstance(dependencies, dict), "invalid_candidate_dependencies")
        require(all(key in versions.records and versions.is_current(key)
                    and versions.records[key][-1]["hash"] == value
                    for key, value in dependencies.items()), "candidate_dependencies_stale")


def preview_candidate(candidate: dict, file_id: str, context: dict, *,
                      width: int, height: int, ledger: dict | None = None) -> dict:
    """按显式视口预览已校验快照；不重读可变源文件，不执行浏览器或专业审阅。"""
    require(isinstance(context, dict), "context_required")
    _rendering_preflight(candidate, context, ledger, context.get("now"))
    entry = next((f for f in candidate["manifest"]["files"] if f["file_id"] == file_id), None)
    require(entry is not None, "rendering_file_id_unknown")
    scope = rendering.preview_scope(entry["path"], width=width, height=height)
    content = base64.b64decode(candidate["snapshots"][file_id], validate=True)
    preview = rendering.render_preview(entry["path"], content, candidate["manifest_hash"])
    return {**preview, "mode": "synthetic", "file_id": file_id, "scope": scope}


def check_candidate_rendering(candidate: dict, rendering_evidence: dict, *,
                              authorized_root: str | Path, context: dict,
                              now: str, ledger: dict | None = None) -> dict:
    """逐文件旁证：file_id映射record_path/artifact_path/evidence_paths/required_scope。

    先校验整个快照及全部路径，再读授权根内的严格JSON、HTML和截图字节。
    返回值仅是本次字节/声明一致性，不写入manifest或替代隐藏信息及专业门禁。
    未提供旁证的文件不继承任何检查结论；记录内其他路径一概不读取。
    """
    _rendering_preflight(candidate, context, ledger, now)
    require(isinstance(rendering_evidence, dict) and bool(rendering_evidence),
            "rendering_evidence_required")
    entries = {f["file_id"]: f for f in candidate["manifest"]["files"]}
    require(set(rendering_evidence).issubset(entries), "rendering_file_id_unknown")
    paths = {}
    for file_id, item in rendering_evidence.items():
        require_fields(item, ("record_path", "artifact_path", "evidence_paths", "required_scope"))
        require(isinstance(item["evidence_paths"], dict)
                and all(isinstance(key, str) and key for key in item["evidence_paths"])
                and isinstance(item["required_scope"], dict), "rendering_evidence_invalid")
        paths[file_id] = {
            "record": safe_path(authorized_root, item["record_path"], must_exist=False),
            "artifact": safe_path(authorized_root, item["artifact_path"], must_exist=False),
            "evidence": {key: safe_path(authorized_root, path, must_exist=False)
                         for key, path in item["evidence_paths"].items()}}
    results = {}
    for file_id, item in rendering_evidence.items():
        resolved = paths[file_id]
        try:
            record = strict_json_loads(resolved["record"].read_text(encoding="utf-8"))
            artifact = resolved["artifact"].read_bytes()
            evidence_artifacts = {key: path.read_bytes() for key, path in resolved["evidence"].items()}
        except OSError:
            results[file_id] = {"status": "blocked", "issues": ["rendering_evidence_unreadable"],
                "identity_verification": "not_performed", "professional_review": "not_performed",
                "evidence_authenticity": "not_established_by_hash", "external_action": "not_performed"}
            continue
        results[file_id] = rendering.validate_rendering_evidence(
            record, name=entries[file_id]["path"],
            content=base64.b64decode(candidate["snapshots"][file_id], validate=True),
            manifest_hash=candidate["manifest_hash"], artifact=artifact,
            evidence_artifacts=evidence_artifacts, required_scope=item["required_scope"], now=now)
    return results


def approval_binding(candidate: dict, request: dict, assessment: dict,
                     registry: dict) -> str:
    return digest({"manifest_hash": candidate["manifest_hash"], "request": request,
                   "assessment": assessment, "registry": registry})


def _request(request: dict) -> None:
    require_fields(request, ("release_id", "project_id", "businesses", "purpose", "action",
                             "recipient", "channel", "access", "targets", "valid_from",
                             "valid_until", "max_uses", "conditions"))
    require(request["action"] in ACTIONS, "unknown_action")
    require(request["channel"] == "synthetic", "synthetic_channel_only")
    require(request["max_uses"] == 1, "single_use_only")
    require(isinstance(request["businesses"], list) and bool(request["businesses"])
            and set(request["businesses"]).issubset({"patent", "software", "standard"}),
            "invalid_businesses")
    require(isinstance(request["targets"], list) and bool(request["targets"])
            and all(isinstance(t, str) and t for t in request["targets"]), "targets_required")
    require(len(set(request["targets"])) == len(request["targets"]), "duplicate_target")
    require_fields(request["access"], ("audience", "download", "forward", "archive", "retention"))
    require(parse_time(request["valid_from"]) < parse_time(request["valid_until"]),
            "invalid_validity_interval")
    require(isinstance(request["conditions"], list), "conditions_required")


def required_roles(request: dict, assessment: dict) -> set[str]:
    roles = {"technical", "materials", "approver", "independent"}
    roles.update(set(request["businesses"]) - {"patent"})
    if assessment.get("strategy") == "protect":
        roles.add("patent")
    return roles


def _actor(registry: dict, actor_id: str, role: str, request: dict, now: str) -> dict:
    require(registry.get("mode") == "synthetic" and registry.get("version"),
            "synthetic_registry_required")
    actors = registry.get("actors", [])
    require(len({a.get("actor_id") for a in actors}) == len(actors), "duplicate_actor")
    actor = next((a for a in actors if a.get("actor_id") == actor_id), None)
    require(actor is not None, "actor_not_registered")
    require(actor.get("kind") == "synthetic_human", "human_role_required")
    require(actor.get("active") is True and role in actor.get("roles", []), "role_not_authorized")
    require(bool(actor.get("authority_evidence")), "authority_not_proven")
    require(parse_time(actor["valid_from"]) <= parse_time(now) < parse_time(actor["valid_until"]),
            "actor_authority_expired")
    scope = actor.get("scope", {})
    require(scope.get("project_id") == request["project_id"]
            and request["action"] in scope.get("actions", [])
            and request["recipient"] in scope.get("recipients", [])
            and request["purpose"] in scope.get("purposes", []), "actor_scope_mismatch")
    return actor


def review_candidate(candidate: dict, request: dict, assessment: dict,
                     registry: dict, signatures: list[dict], now: str, *,
                     rendering_evidence: dict | None = None,
                     authorized_root: str | Path | None = None,
                     context: dict | None = None, ledger: dict | None = None) -> dict:
    """验证合成审核及可选本地旁证；consistent不放宽原有专业/隐藏信息门禁。"""
    validate_candidate(candidate)
    _request(request)
    issues = []
    rendering_results = None
    # 载入的旁证结果不是可重用签核；无本次原始旁证时也不得把旧失败静默丢掉。
    if "rendering_evidence" in candidate and rendering_evidence is None:
        issues.append({"code": "rendering_evidence_recheck_required"})
    if rendering_evidence is not None:
        require(authorized_root is not None and context is not None, "rendering_read_context_required")
        prior = candidate.get("rendering_evidence", {})
        require(isinstance(prior, dict) and isinstance(rendering_evidence, dict)
                and set(prior).issubset(rendering_evidence), "rendering_recheck_inventory_incomplete")
        rendering_results = check_candidate_rendering(
            candidate, rendering_evidence, authorized_root=authorized_root,
            context=context, ledger=ledger, now=now)
        issues.extend({"code": code, "file_id": file_id}
                      for file_id, result in rendering_results.items() for code in result["issues"])
    files = candidate["manifest"]["files"]
    for entry in files:
        issues.extend({"code": code, "file_id": entry["file_id"]}
                      for code in entry["inspection"]["issues"])
    def missing(condition, code, **location):
        if not condition:
            issues.append({"code": code, **location})
    strategy = assessment.get("strategy")
    missing(strategy in {"protect", "already_public", "defensive"}, "strategy_unknown")
    missing(not assessment.get("unresolved"), "unresolved_professional_issue")
    rules = assessment.get("rules", {})
    missing(rules.get("status") == "available" and rules.get("version")
            and rules.get("evidence"), "rules_unavailable")
    policy = assessment.get("policy", {})
    missing(policy.get("status") == "reviewed" and policy.get("evidence")
            and not policy.get("conflicts"), "policy_conflict_or_unknown")
    missing(policy.get("license_status") in {"confirmed", "not_applicable"}
            and policy.get("fto_status") in {"reviewed", "not_applicable"},
            "sep_not_license_or_fto")
    if strategy in {"already_public", "defensive"}:
        na = assessment.get("patent_not_applicable", {})
        missing(na.get("reason") and na.get("evidence"), "patent_na_evidence_required")
        if strategy == "defensive":
            missing(assessment.get("opportunities_lost") and assessment.get("strategy_authority"),
                    "defensive_strategy_authority_required")
    application = assessment.get("application", {})
    if strategy == "protect":
        missing(application.get("status") == "verified" and application.get("version")
                and application.get("application_id") and application.get("receipt_evidence")
                and application.get("files") and application.get("date_evidence"),
                "actual_application_unverified")
    inventory = {c for f in files for c in f["content_ids"]}
    combinations = assessment.get("combinations", [])
    missing(isinstance(combinations, list) and all(isinstance(c, str) and c for c in combinations)
            and len(set(combinations)) == len(combinations), "combination_inventory_required")
    joint = assessment.get("joint_review", {})
    missing(joint.get("status") == "confirmed" and joint.get("evidence")
            and joint.get("manifest_hash") == candidate["manifest_hash"]
            and set(joint.get("file_ids", [])) == {f["file_id"] for f in files}
            and set(joint.get("content_ids", [])) == inventory
            and set(joint.get("combination_ids", [])) == set(combinations)
            and joint.get("inventory_complete") is True,
            "joint_semantic_review_required")
    hidden = assessment.get("hidden_review", {})
    missing(hidden.get("status") == "confirmed" and hidden.get("evidence")
            and hidden.get("manifest_hash") == candidate["manifest_hash"],
            "full_content_review_required")
    if strategy == "protect":
        support = assessment.get("support", [])
        for content_id in sorted(inventory | set(combinations)):
            for target in request["targets"]:
                records = [s for s in support if s.get("content_id") == content_id
                           and s.get("target") == target]
                good = len(records) == 1 and all(
                    s.get("status") == "confirmed" and s.get("original_locator")
                    and s.get("evidence") and s.get("date_evidence")
                    and s.get("application_version") == application.get("version")
                    and s.get("document_sha256") in application.get("files", [])
                    for s in records)
                missing(good, "content_or_region_support_unknown", content_id=content_id,
                        target=target)
    rights = assessment.get("rights", {})
    for entry in files:
        right = rights.get(entry["file_id"], {})
        missing(right.get("source_evidence") and right.get("contribution_evidence")
                and not right.get("restrictions"), "material_rights_unresolved",
                file_id=entry["file_id"])
        try:
            check_permission(right.get("permissions", []), action=request["action"],
                             purpose=request["purpose"], recipient=request["recipient"], now=now)
        except ContractError:
            issues.append({"code": "material_action_not_authorized", "file_id": entry["file_id"]})
    roles = required_roles(request, assessment)
    for role in ROLES - roles:
        missing(bool(assessment.get("roles_not_applicable", {}).get(role)),
                "role_na_reason_required", role=role)
    binding = approval_binding(candidate, request, assessment, registry)
    valid = {}
    for signature in signatures:
        role = signature.get("role")
        if signature.get("binding") != binding or not signature.get("evidence"):
            continue
        try:
            _actor(registry, signature["actor_id"], role, request, now)
        except (ContractError, KeyError):
            continue
        valid[role] = signature["actor_id"]
    for role in sorted(roles - set(valid)):
        issues.append({"code": "required_signature_missing", "role": role})
    if "independent" in valid:
        missing(valid["independent"] not in {actor for role, actor in valid.items()
                                            if role != "independent"}, "independent_review_required")
    conditions = assessment.get("condition_evidence", {})
    for condition in request["conditions"]:
        record = conditions.get(condition, {})
        missing(record.get("status") == "satisfied" and record.get("evidence"),
                "condition_not_satisfied", condition_id=condition)
    instant = parse_time(now)
    missing(parse_time(request["valid_from"]) <= instant < parse_time(request["valid_until"]),
            "approval_expired_or_not_started")
    return {"mode": "synthetic", "status": "blocked" if issues else "synthetic_ready",
            "manifest": candidate["manifest"], "manifest_hash": candidate["manifest_hash"],
            "binding": binding, "issues": issues, "required_roles": sorted(roles),
            **({"rendering_evidence": rendering_results} if rendering_results is not None else {}),
            "professional_review": "synthetic_attestations_only",
            "identity_verification": "not_performed", "official_status": "not_asserted",
            "external_action": "not_performed", "host_egress": "not_controlled"}


class DisclosureJournal:
    """只内建SQLite合成收件箱；不接受transport callable或外部目的地址执行。"""

    def __init__(self, path: str | Path, *, synthetic: bool = False):
        require(synthetic is True, "synthetic_only")
        path = Path(path)
        require(path.parent.is_dir(), "journal_parent_missing")
        self.path = path
        with closing(self._connect()) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            require(not tables or "dyz_meta" in tables, "foreign_database")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS dyz_meta (version TEXT PRIMARY KEY);
                INSERT OR IGNORE INTO dyz_meta VALUES ('synthetic-1');
                CREATE TABLE IF NOT EXISTS releases (
                    release_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    body TEXT NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS signatures (
                    release_id TEXT NOT NULL, role TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(release_id, role));
                CREATE TABLE IF NOT EXISTS executions (
                    release_id TEXT PRIMARY KEY, execution_id TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                    execution_id TEXT PRIMARY KEY, receipt TEXT NOT NULL, snapshots TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, release_id TEXT NOT NULL,
                    event TEXT NOT NULL, body TEXT NOT NULL);
            """)
            require(db.execute("SELECT version FROM dyz_meta").fetchall() == [("synthetic-1",)],
                    "journal_version_unsupported")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def _transaction(self):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _load(db, release_id):
        row = db.execute("SELECT body,state FROM releases WHERE release_id=?", (release_id,)).fetchone()
        require(row is not None, "release_not_found")
        return json.loads(row[0]), row[1]

    @staticmethod
    def _audit(db, release_id, event, body):
        db.execute("INSERT INTO audit(release_id,event,body) VALUES (?,?,?)",
                   (release_id, event, canonical_bytes(body).decode()))

    def create_release(self, candidate: dict, request: dict, assessment: dict,
                       registry: dict) -> dict:
        validate_candidate(candidate)
        _request(request)
        require(registry.get("mode") == "synthetic", "synthetic_registry_required")
        body = {"candidate": candidate, "request": request, "assessment": assessment,
                "registry": registry}
        binding = approval_binding(**body)
        with self._transaction() as db:
            require(db.execute("SELECT 1 FROM releases WHERE release_id=?",
                               (request["release_id"],)).fetchone() is None, "duplicate_release")
            require(db.execute("SELECT 1 FROM incidents WHERE project_id=?",
                               (request["project_id"],)).fetchone() is None, "project_incident_stop")
            db.execute("INSERT INTO releases VALUES (?,?,?,?)",
                       (request["release_id"], request["project_id"],
                        canonical_bytes(body).decode(), "draft"))
            self._audit(db, request["release_id"], "frozen", {"binding": binding})
        return {"mode": "synthetic", "release_id": request["release_id"], "binding": binding,
                "manifest_hash": candidate["manifest_hash"], "state": "draft"}

    def sign(self, release_id: str, *, role: str, actor_id: str, evidence: str,
             binding: str, now: str) -> dict:
        require(role in ROLES and bool(evidence), "signature_fields_required")
        with self._transaction() as db:
            body, state = self._load(db, release_id)
            require(state == "draft", "release_not_signable")
            require(binding == approval_binding(**body), "signature_binding_mismatch")
            _actor(body["registry"], actor_id, role, body["request"], now)
            signature = {"mode": "synthetic", "role": role, "actor_id": actor_id,
                         "evidence": evidence, "binding": binding, "at": now}
            require(db.execute("SELECT 1 FROM signatures WHERE release_id=? AND role=?",
                               (release_id, role)).fetchone() is None, "duplicate_signature")
            db.execute("INSERT INTO signatures VALUES (?,?,?)",
                       (release_id, role, canonical_bytes(signature).decode()))
            self._audit(db, release_id, "synthetic_signature", {"role": role, "binding": binding})
        return signature

    def review(self, release_id: str, *, now: str) -> dict:
        with self._transaction() as db:
            body, state = self._load(db, release_id)
            signatures = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM signatures WHERE release_id=?", (release_id,))]
            result = review_candidate(**body, signatures=signatures, now=now)
            if state == "draft" and parse_time(now) >= parse_time(body["request"]["valid_until"]):
                state = "expired"
                db.execute("UPDATE releases SET state='expired' WHERE release_id=?", (release_id,))
            if state != "draft":
                result["issues"].append({"code": "release_" + state})
                result["status"] = "blocked"
            if db.execute("SELECT 1 FROM incidents WHERE project_id=?",
                          (body["request"]["project_id"],)).fetchone():
                result["issues"].append({"code": "project_incident_stop"})
                result["status"] = "blocked"
            self._audit(db, release_id, "candidate_review", {"at": now, "status": result["status"],
                        "codes": sorted({issue["code"] for issue in result["issues"]})})
            return result

    def invalidate(self, release_id: str, *, current: dict, now: str) -> dict:
        """持久保存相关变化指纹，不覆盖历史审批对象。"""
        parse_time(now)
        with self._transaction() as db:
            body, state = self._load(db, release_id)
            changed = [key for key in ("request", "assessment", "registry")
                       if digest(current.get(key)) != digest(body[key])]
            if current.get("manifest_hash") != body["candidate"]["manifest_hash"]:
                changed.append("manifest_hash")
            dependencies = {key: value for entry in body["candidate"]["manifest"]["files"]
                            for key, value in entry.get("dependency_hashes", {}).items()}
            if dependencies and current.get("dependency_hashes") != dependencies:
                changed.append("dependency_hashes")
            if changed:
                db.execute("UPDATE releases SET state='invalidated' WHERE release_id=?", (release_id,))
                self._audit(db, release_id, "invalidated", {"at": now, "changed": changed,
                                                           "current_hash": digest(current)})
        return {"state": "invalidated" if changed else state, "changed": changed}

    def revoke(self, release_id: str, *, evidence: str, now: str) -> dict:
        require(bool(evidence), "revocation_evidence_required")
        parse_time(now)
        with self._transaction() as db:
            self._load(db, release_id)
            db.execute("UPDATE releases SET state='revoked' WHERE release_id=?", (release_id,))
            self._audit(db, release_id, "revoked", {"at": now, "evidence_hash": digest(evidence)})
        return {"mode": "synthetic", "state": "revoked"}

    def execute(self, release_id: str, *, current: dict, now: str,
                outcome: str = "confirmed") -> dict:
        """持久预留先于替身执行。崩溃/超时保持unknown；同release永不盲重试。"""
        require(outcome in {"confirmed", "timeout", "not_sent", "crash_before_transport"},
                "unknown_synthetic_outcome")
        self.invalidate(release_id, current=current, now=now)
        # 先持久记录拒绝原因，再在预留事务内重检；事务回滚不丢失预检证据。
        preview = self.review(release_id, now=now)
        require(preview["status"] == "synthetic_ready", "pre_execution_review_blocked")
        with self._transaction() as db:
            body, state = self._load(db, release_id)
            require(state == "draft", "release_not_executable")
            require(db.execute("SELECT 1 FROM incidents WHERE project_id=?",
                               (body["request"]["project_id"],)).fetchone() is None,
                    "project_incident_stop")
            require(db.execute("SELECT 1 FROM executions WHERE release_id=?",
                               (release_id,)).fetchone() is None, "release_already_attempted")
            signatures = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM signatures WHERE release_id=?", (release_id,))]
            review = review_candidate(**body, signatures=signatures, now=now)
            require(review["status"] == "synthetic_ready", "pre_execution_review_blocked")
            execution = {"mode": "synthetic", "release_id": release_id,
                         "execution_id": "sim-" + uuid.uuid4().hex, "at": now,
                         "manifest_hash": body["candidate"]["manifest_hash"],
                         "recipient": body["request"]["recipient"],
                         "binding": review["binding"], "state": "unknown",
                         "external_action": "not_performed", "official_status": "not_asserted"}
            db.execute("INSERT INTO executions VALUES (?,?,?,?)",
                       (release_id, execution["execution_id"], "unknown", canonical_bytes(execution).decode()))
            self._audit(db, release_id, "execution_reserved", execution)
        if outcome == "crash_before_transport":
            return execution
        # 第二笔事务仍检查撤销/事件；仅使用数据库中已冻结的字节，不重读源文件。
        with self._transaction() as db:
            body, state = self._load(db, release_id)
            require(state == "draft", "release_stopped_after_reservation")
            require(db.execute("SELECT 1 FROM incidents WHERE project_id=?",
                               (body["request"]["project_id"],)).fetchone() is None,
                    "project_incident_stop")
            validate_candidate(body["candidate"])
            if outcome != "not_sent":
                receipt = {"mode": "synthetic", "execution_id": execution["execution_id"],
                           "release_id": release_id, "manifest_hash": execution["manifest_hash"],
                           "recipient": execution["recipient"], "binding": execution["binding"],
                           "received_hashes": {f["file_id"]: sha256_bytes(base64.b64decode(
                               body["candidate"]["snapshots"][f["file_id"]]))
                               for f in body["candidate"]["manifest"]["files"]}}
                db.execute("INSERT INTO outbox VALUES (?,?,?)",
                           (execution["execution_id"], canonical_bytes(receipt).decode(),
                            canonical_bytes(body["candidate"]["snapshots"]).decode()))
                if outcome == "confirmed":
                    execution["receipt"] = receipt
            execution["state"] = {"confirmed": "synthetic_confirmed", "timeout": "unknown",
                                  "not_sent": "confirmed_not_sent"}[outcome]
            db.execute("UPDATE executions SET state=?,body=? WHERE release_id=?",
                       (execution["state"], canonical_bytes(execution).decode(), release_id))
            self._audit(db, release_id, "synthetic_transport_result",
                        {"execution_id": execution["execution_id"], "state": execution["state"]})
        return execution

    def simulated_receipt(self, execution_id: str) -> dict:
        """仅查询本地替身收件记录，不等于外部平台核实。"""
        with closing(self._connect()) as db:
            row = db.execute("SELECT receipt FROM outbox WHERE execution_id=?", (execution_id,)).fetchone()
            require(row is not None, "synthetic_receipt_not_found")
            return json.loads(row[0])

    def verify_receipt(self, release_id: str, *, receipt: dict, evidence: str, now: str) -> dict:
        require(bool(evidence), "verification_evidence_required")
        parse_time(now)
        with self._transaction() as db:
            self._load(db, release_id)
            row = db.execute("SELECT execution_id,body FROM executions WHERE release_id=?",
                             (release_id,)).fetchone()
            require(row is not None, "execution_not_found")
            actual = db.execute("SELECT receipt FROM outbox WHERE execution_id=?", (row[0],)).fetchone()
            require(actual is not None and digest(receipt) == digest(json.loads(actual[0])),
                    "receipt_binding_mismatch")
            execution = json.loads(row[1])
            execution.update(state="synthetic_confirmed", receipt=receipt,
                             verification={"at": now, "evidence_hash": digest(evidence)})
            db.execute("UPDATE executions SET state=?,body=? WHERE release_id=?",
                       (execution["state"], canonical_bytes(execution).decode(), release_id))
            self._audit(db, release_id, "receipt_verified", execution["verification"])
            return execution

    def report_incident(self, release_id: str, *, facts: dict, now: str) -> dict:
        require_fields(facts, ("observed_at", "known_access", "evidence", "containment_authority"))
        parse_time(now)
        parse_time(facts["observed_at"])
        with self._transaction() as db:
            body, _ = self._load(db, release_id)
            incident = {"mode": "synthetic", "incident_id": "incident-" + uuid.uuid4().hex,
                        "release_id": release_id, "project_id": body["request"]["project_id"],
                        "at": now, "facts": copy.deepcopy(facts), "state": "reported_stopped",
                        "manifest_hash": body["candidate"]["manifest_hash"],
                        "evidence_preserved": True, "novelty_restored": False,
                        "external_containment": "not_performed", "professional_disposition": "required"}
            db.execute("INSERT INTO incidents VALUES (?,?,?)", (incident["incident_id"],
                       incident["project_id"], canonical_bytes(incident).decode()))
            db.execute("UPDATE releases SET state='incident_stop' WHERE project_id=?",
                       (incident["project_id"],))
            self._audit(db, release_id, "incident_reported", {"incident_id": incident["incident_id"]})
            return incident

    def status(self, release_id: str) -> dict:
        with closing(self._connect()) as db:
            body, state = self._load(db, release_id)
            row = db.execute("SELECT body FROM executions WHERE release_id=?", (release_id,)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM executions WHERE release_id=?", (release_id,)).fetchone()[0]
            return {"mode": "synthetic", "release_id": release_id, "approval_state": state,
                    "manifest_hash": body["candidate"]["manifest_hash"], "attempts": count,
                    "execution": json.loads(row[0]) if row else {"state": "not_executed"},
                    "official_status": "not_asserted", "external_action": "not_performed"}
