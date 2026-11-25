"""WP-01 的证据、权限、版本与责任契约。只使用标准库。

所有时间必须带时区；路径相对于调用者明确授权的根目录。
哈希证明字节一致，不证明真实性、权属或审阅人的权限。
"""

from __future__ import annotations

import copy
import hashlib
import json
import ntpath
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

SCHEMA_VERSION = "1.0"
BUSINESSES = ("patent", "software", "standard")
STATUSES = {
    "draft", "needs_evidence", "needs_review", "blocked", "not_applicable",
    "invalidated", "checked", "partial", "unknown", "failed",
}


class ContractError(ValueError):
    """错误消息只包含结构诊断，不复制材料正文。"""


class BundleError(ValueError):
    """路径或包契约失败；bundle 保留原异常类型和诊断码。"""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def require_fields(data: dict, fields: tuple[str, ...] | list[str]) -> None:
    require(isinstance(data, dict), "object_required")
    for field in fields:
        require(field in data and data[field] is not None, f"missing:{field}")
        if isinstance(data[field], str):
            require(bool(data[field].strip()), f"empty:{field}")


def canonical_bytes(value: Any) -> bytes:
    """固定JSON编码，拒绝NaN/Infinity，避免同一记录有歧义。"""
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("not_canonical_json") from exc


def strict_json_loads(text: str) -> Any:
    """安全边界不得按最后值静默覆盖重复键，亦不得接受非JSON数值。"""
    def pairs(items: list[tuple[str, Any]]) -> dict:
        output = {}
        for key, value in items:
            require(key not in output, "duplicate_json_key")
            output[key] = value
        return output

    def constant(_value: str) -> None:
        raise ContractError("nonfinite_json_number")

    try:
        output = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        canonical_bytes(output)
        return output
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ContractError("invalid_json") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(content: bytes) -> str:
    require(isinstance(content, bytes), "bytes_required")
    return hashlib.sha256(content).hexdigest()


def parse_time(value: str) -> datetime:
    require(isinstance(value, str), "timestamp_required")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("invalid_timestamp") from exc
    require(stamp.tzinfo is not None, "timezone_required")
    return stamp.astimezone(timezone.utc)


def is_macos_system_root_symlink(entry: Path) -> bool:
    """只允许 macOS 自带的 /var、/tmp、/etc 指向各自的 /private 目录。"""
    if sys.platform != "darwin" or entry not in (Path("/var"), Path("/tmp"), Path("/etc")):
        return False
    try:
        target = os.readlink(entry)
    except OSError:
        return False
    return target in (f"private/{entry.name}", f"/private/{entry.name}")


def checked_path(path: Path, *, missing_leaf: bool = False) -> os.stat_result | None:
    """先 lstat 词法父链，不先 resolve；只允许显式缺失的叶节点。"""
    info = None
    for entry in (*reversed(path.parents), path):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            if missing_leaf and entry == path:
                return None
            raise BundleError("bundle_path_missing") from None
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            if entry != path and is_macos_system_root_symlink(entry):
                try:
                    info = entry.stat()
                except OSError:
                    raise BundleError("bundle_link_rejected") from None
            else:
                raise BundleError("bundle_link_rejected")
        if entry != path and not stat.S_ISDIR(info.st_mode):
            raise BundleError("bundle_parent_not_directory")
    return info


def is_reserved_windows_name(name: str) -> bool:
    """无论宿主平台如何，都按 Windows 的保留名称规则判断。"""
    checker = getattr(os.path, "isreserved", None) or getattr(ntpath, "isreserved", None)
    return checker(name) if checker is not None else PureWindowsPath(name).is_reserved()


def safe_path(root: str | Path, relative: str, *, must_exist: bool = True) -> Path:
    """拒绝父目录、绝对路径、Windows盘符/ADS和根外符号链接。"""
    require(isinstance(relative, str) and bool(relative), "relative_path_required")
    parts = relative.replace("\\", "/").split("/")
    require(
        not PureWindowsPath(relative).drive and not relative.startswith(("/", "\\"))
        and all(part not in ("", ".", "..") for part in parts)
        and ":" not in relative and "\x00" not in relative,
        "unsafe_path",
    )
    base = Path(root).resolve(strict=True)
    target = base.joinpath(*parts).resolve(strict=must_exist)
    require(target.is_relative_to(base) and target != base, "path_outside_root")
    return target


def write_new_json(root: str | Path, relative: str, value: Any) -> Path:
    """不覆盖原件；调用者负责保护授权根目录不被其他进程修改。"""
    content = canonical_bytes(value) + b"\n"
    target = safe_path(root, relative, must_exist=False)
    require(target.parent.is_dir(), "parent_directory_missing")
    with target.open("xb") as stream:
        stream.write(content)
    return target


def result(capability: str, *, status: str = "needs_review", artifacts: Any = None,
           issues: list | None = None, evidence: list | None = None,
           adaptation: dict | None = None, checks: list | None = None) -> dict:
    """共享结果信封；checked只表示确定性检查，不表示专业通过。"""
    require(bool(re.fullmatch(r"[A-Z]+-\d{2}", capability)), "invalid_capability_id")
    require(status in STATUSES, "invalid_result_status")
    return {
        "schema_version": SCHEMA_VERSION, "capability": capability,
        "status": status, "artifacts": copy.deepcopy(artifacts if artifacts is not None else {}),
        "issues": copy.deepcopy(issues or []), "evidence": copy.deepcopy(evidence or []),
        "adaptation": copy.deepcopy(adaptation or {}), "checks": copy.deepcopy(checks or []),
        "professional_review": "not_performed", "official_status": "not_asserted",
        "external_action": "not_performed",
    }


def check_permission(permissions: list[dict], *, action: str, purpose: str,
                     recipient: str, now: str) -> dict:
    """获取、处理、复制、再分发及不同接收人必须分别授权。"""
    instant = parse_time(now)
    require(isinstance(permissions, list), "permissions_list_required")
    for permission in permissions:
        require_fields(permission, ("action", "purpose", "recipient", "decision"))
        if (permission["action"], permission["purpose"], permission["recipient"]) != (
            action, purpose, recipient,
        ):
            continue
        if permission["decision"] != "allow":
            continue
        if not permission.get("authority_evidence"):
            continue
        if permission.get("revoked"):
            continue
        if not permission.get("valid_from") or not permission.get("valid_until"):
            continue
        if parse_time(permission["valid_from"]) <= instant < parse_time(permission["valid_until"]):
            return copy.deepcopy(permission)
    raise ContractError("permission_not_proven")


def preflight(environment: dict, permissions: list[dict], *, sensitivity: str,
              purpose: str, now: str) -> None:
    """在文件读取之前调用；未知宿主路径不能因本地工具而被豁免。"""
    require(sensitivity in {"synthetic", "public", "confidential", "restricted"},
            "invalid_sensitivity")
    check_permission(permissions, action="local_read", purpose=purpose,
                     recipient="local_tool", now=now)
    if sensitivity in {"confidential", "restricted"}:
        require_fields(environment, ("data_paths", "assessment_evidence"))
        paths = environment["data_paths"]
        require(isinstance(paths, list) and bool(paths), "data_paths_required")
        required = {"host_model", "index", "telemetry", "tools", "logs", "subprocess"}
        require(required.issubset({p.get("id") for p in paths}), "data_path_inventory_incomplete")
        for path in paths:
            require(path.get("verified") is True and bool(path.get("evidence")),
                    "data_path_unverified")
            require(path.get("mode") in {"local", "disabled", "external"},
                    "data_path_mode_unknown")
            if path["mode"] == "external":
                check_permission(permissions, action="external_processing", purpose=purpose,
                                 recipient=path["id"], now=now)


def capture_evidence(root: str | Path, relative: str, *, source: dict,
                     permissions: list[dict], environment: dict, sensitivity: str,
                     purpose: str, acquired_at: str, locator: str,
                     extraction_status: str = "not_checked") -> tuple[dict, bytes]:
    """读取一次并返回固定快照字节，调用者可保存到明确授权的私人存储。"""
    preflight(environment, permissions, sensitivity=sensitivity, purpose=purpose,
              now=acquired_at)
    require_fields(source, ("id", "version", "origin", "level"))
    require(bool(locator.strip()), "locator_required")
    require(extraction_status in {"not_checked", "complete", "partial", "unreadable",
                                  "ocr_uncertain", "missing_pages"}, "invalid_extraction_status")
    path = safe_path(root, relative)
    require(path.is_file(), "evidence_file_required")
    content = path.read_bytes()
    byte_hash = sha256_bytes(content)
    record = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": "ev-" + digest({"source_id": source["id"], "sha256": byte_hash}),
        "sha256": byte_hash, "size": len(content), "path": relative,
        "source": copy.deepcopy(source), "locator": locator, "acquired_at": acquired_at,
        "sensitivity": sensitivity, "extraction_status": extraction_status,
        "permissions": copy.deepcopy(permissions), "authenticity": "not_verified",
    }
    return record, content


def route_project(project_id: str, requests: list[dict], evidence_ids: list[str]) -> dict:
    require(bool(project_id.strip()) and bool(requests), "project_and_requests_required")
    tasks = []
    for index, request in enumerate(requests, start=1):
        require_fields(request, ("business", "goal", "adaptation", "owner"))
        require(request["business"] in BUSINESSES, "unknown_business")
        adaptation = request["adaptation"]
        require_fields(adaptation, ("stage", "domain"))
        axes = ("organization", "standard_type") if request["business"] == "standard" else ("jurisdiction", "right_type")
        require_fields(adaptation, axes)
        tasks.append({
            "task_id": f"{project_id}-{index}", **copy.deepcopy(request),
            "evidence_ids": list(evidence_ids), "status": "draft",
            "disclosure_status": "not_authorized", "official_status": "not_asserted",
        })
    return {"schema_version": SCHEMA_VERSION, "project_id": project_id, "tasks": tasks}


def assess_contributions(facts: list[dict]) -> dict:
    require(bool(facts), "contribution_facts_required")
    for fact in facts:
        require_fields(fact, ("subject", "claim", "evidence_id"))
    claims: dict[str, set[str]] = {}
    for fact in facts:
        claims.setdefault(fact["subject"], set()).add(fact["claim"])
    conflicts = sorted(subject for subject, values in claims.items() if len(values) > 1)
    return result("CORE-02", status="needs_evidence" if conflicts else "needs_review",
                  artifacts={"facts": facts, "conflicts": conflicts, "ownership": "undetermined"})


def select_rules(rules: list[dict], adaptation: dict, *, as_of: str) -> dict:
    """选择已声明适用的版本，不凭URL或核验日期自行认定法律有效性。"""
    instant = parse_time(as_of)
    selected, unresolved = [], []
    for rule in rules:
        require_fields(rule, ("rule_id", "version", "source", "locator", "scope",
                              "effective_from", "verified_at", "license", "review_status"))
        parse_time(rule["verified_at"])
        if not isinstance(rule["scope"], dict) or not rule["scope"]:
            raise ContractError("rule_scope_required")
        if not all(adaptation.get(key) == value for key, value in rule["scope"].items()):
            continue
        if instant < parse_time(rule["effective_from"]):
            continue
        if rule.get("effective_until") and instant >= parse_time(rule["effective_until"]):
            continue
        if rule["review_status"] != "professionally_verified" or not rule.get("review_evidence"):
            unresolved.append(rule["rule_id"])
        else:
            selected.append(copy.deepcopy(rule))
    duplicate_ids = {item["rule_id"] for item in selected if sum(
        other["rule_id"] == item["rule_id"] for other in selected
    ) > 1}
    unresolved.extend(sorted(duplicate_ids))
    return result("CORE-05", status="needs_review" if unresolved or not selected else "checked",
                  artifacts={"selected": selected, "unresolved": sorted(set(unresolved))},
                  adaptation=adaptation, checks=["scope_and_effective_interval_only"])


class VersionLedger:
    """本地单写者版本图；不作为防篡改审计或电子签名系统。"""

    def __init__(self, records: dict | None = None, reviews: list | None = None):
        require(records is None or isinstance(records, dict), "ledger_records_required")
        require(reviews is None or isinstance(reviews, list), "ledger_reviews_required")
        self.records = copy.deepcopy(records if records is not None else {})
        self.reviews = copy.deepcopy(reviews if reviews is not None else [])
        self._validate_restored_state()

    def _validate_restored_state(self) -> None:
        """校验历史内部一致性，不把可重算哈希宣传成防篡改认证。"""
        hashes = {}
        for record_id, history in self.records.items():
            require(isinstance(record_id, str) and bool(record_id.strip()), "record_id_required")
            require(isinstance(history, list) and bool(history), "record_history_required")
            hashes[record_id] = set()
            for number, version in enumerate(history, start=1):
                require_fields(version, ("version", "hash", "dependencies"))
                require("payload" in version, "record_payload_missing")
                require(type(version["version"]) is int and version["version"] == number,
                        "history_version_mismatch")
                dependencies = version["dependencies"]
                require(isinstance(dependencies, dict), "dependency_bindings_required")
                require(all(isinstance(key, str) and bool(key) and isinstance(value, str)
                            for key, value in dependencies.items()), "invalid_dependency_binding")
                require(record_id not in dependencies, "self_dependency")
                expected = digest({"payload": version["payload"], "dependencies": dependencies})
                require(version["hash"] == expected, "record_hash_mismatch")
                hashes[record_id].add(expected)
        for history in self.records.values():
            for version in history:
                require(all(key in hashes and value in hashes[key]
                            for key, value in version["dependencies"].items()),
                        "dependency_version_missing")
        visited, visiting = set(), set()

        def visit(record_id: str) -> None:
            require(record_id not in visiting, "dependency_cycle")
            if record_id in visited:
                return
            visiting.add(record_id)
            for dependency in self.records[record_id][-1]["dependencies"]:
                visit(dependency)
            visiting.remove(record_id)
            visited.add(record_id)

        for record_id in self.records:
            visit(record_id)
        review_ids = set()
        for review in self.reviews:
            require_fields(review, ("review_id", "kind", "decision", "reviewer", "status", "bindings"))
            require(isinstance(review["review_id"], str) and review["review_id"] not in review_ids,
                    "duplicate_or_invalid_review_id")
            review_ids.add(review["review_id"])
            require(review["kind"] in {"machine", "professional", "disclosure"}, "unknown_review_kind")
            require(review["decision"] in {"accepted", "rejected", "conditional"}, "unknown_decision")
            require(review["status"] in {"recorded", "invalidated"}, "invalid_review_status")
            require_fields(review["reviewer"], ("actor_id", "actor_type", "authority_evidence"))
            require(review["reviewer"]["actor_type"] in {"human", "machine"}, "unknown_actor_type")
            if review["kind"] != "machine":
                require(review["reviewer"]["actor_type"] == "human", "human_attestation_required")
            bindings = review["bindings"]
            require(isinstance(bindings, dict) and bool(bindings), "review_bindings_required")
            require(all(key in hashes and value in hashes[key] for key, value in bindings.items()),
                    "review_version_missing")
            if review["status"] == "recorded":
                require(all(self.records[key][-1]["hash"] == value and self.is_current(key)
                            for key, value in bindings.items()), "review_binding_stale")

    def put(self, record_id: str, payload: Any, *, dependencies: list[str] | None = None) -> dict:
        require(bool(record_id.strip()), "record_id_required")
        dependencies = dependencies or []
        require(record_id not in dependencies, "self_dependency")
        require(len(set(dependencies)) == len(dependencies), "duplicate_dependency")
        require(all(dep in self.records for dep in dependencies), "dependency_missing")
        # 更新已有节点时，也不得让依赖图形成环。
        def reaches(start: str, target: str, seen: set[str]) -> bool:
            if start == target:
                return True
            if start in seen:
                return False
            seen.add(start)
            return any(reaches(dep, target, seen) for dep in self.records[start][-1]["dependencies"])

        require(not any(reaches(dep, record_id, set()) for dep in dependencies), "dependency_cycle")
        dependency_hashes = {dep: self.records[dep][-1]["hash"] for dep in dependencies}
        version_hash = digest({"payload": payload, "dependencies": dependency_hashes})
        history = self.records.setdefault(record_id, [])
        if history and history[-1]["hash"] == version_hash:
            return copy.deepcopy(history[-1])
        version = {"version": len(history) + 1, "hash": version_hash,
                   "payload": copy.deepcopy(payload), "dependencies": dependency_hashes}
        history.append(version)
        affected = {record_id}
        changed = True
        while changed:
            changed = False
            for key, versions in self.records.items():
                if key not in affected and affected.intersection(versions[-1]["dependencies"]):
                    affected.add(key)
                    changed = True
        for review in self.reviews:
            if affected.intersection(review["bindings"]):
                review["status"] = "invalidated"
                review["invalidated_by"] = record_id
        return copy.deepcopy(version)

    def is_current(self, record_id: str, seen: set[str] | None = None) -> bool:
        require(record_id in self.records, "record_missing")
        seen = set() if seen is None else set(seen)
        require(record_id not in seen, "dependency_cycle")
        seen.add(record_id)
        current = self.records[record_id][-1]
        return all(dep in self.records and self.records[dep][-1]["hash"] == version_hash
                   and self.is_current(dep, seen)
                   for dep, version_hash in current["dependencies"].items())

    def add_review(self, review_id: str, record_ids: list[str], *, reviewer: dict,
                   kind: str, decision: str) -> dict:
        require(kind in {"machine", "professional", "disclosure"}, "unknown_review_kind")
        require(decision in {"accepted", "rejected", "conditional"}, "unknown_decision")
        require_fields(reviewer, ("actor_id", "actor_type", "authority_evidence"))
        require(reviewer["actor_type"] in {"human", "machine"}, "unknown_actor_type")
        if kind != "machine":
            require(reviewer["actor_type"] == "human", "human_attestation_required")
        require(not any(r["review_id"] == review_id for r in self.reviews), "duplicate_review")
        require(bool(record_ids) and all(key in self.records for key in record_ids), "review_records_required")
        require(all(self.is_current(key) for key in record_ids), "stale_dependencies")
        review = {"review_id": review_id, "kind": kind, "decision": decision,
                  "reviewer": copy.deepcopy(reviewer), "status": "recorded",
                  "identity_verification": "caller_responsibility",
                  "bindings": {key: self.records[key][-1]["hash"] for key in record_ids}}
        self.reviews.append(review)
        return copy.deepcopy(review)

    def export(self) -> dict:
        return copy.deepcopy({"schema_version": SCHEMA_VERSION,
                              "records": self.records, "reviews": self.reviews})


def record_deadline(event: dict) -> dict:
    """记录专业人员提供的期限，不以固定日数推导法律截止日。"""
    require_fields(event, ("business", "event_id", "owner", "rule_id"))
    require(event["business"] in BUSINESSES, "unknown_business")
    owners = {"patent": "PROC", "software": "SW-06", "standard": "STD-09/11"}
    missing = [field for field in ("service_at", "due_at", "basis_evidence", "human_review")
               if not event.get(field)]
    for field in ("service_at", "due_at"):
        if event.get(field):
            parse_time(event[field])
    return result("LIFE-01", status="needs_evidence" if missing else "needs_review",
                  artifacts={"event": event, "rule_owner": owners[event["business"]],
                             "missing": missing, "reminder_is_performance": False})
