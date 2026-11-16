"""软件版权材料准备：事实、真实源码、处理决定和版本化交接。

只读取调用者逐项声明的授权文件，不执行源码或外发。所有输出是内部工件，
不能作为权属认定、登记成功、专业签核或完整宿主隔离的证明。
"""

from __future__ import annotations

import copy
import difflib
import re
from datetime import date, datetime, timezone
from pathlib import Path

from tools.core import (
    ContractError, digest, preflight, record_deadline, require, require_fields,
    result, safe_path, sha256_bytes,
)

CAPABILITIES = tuple(f"SW-{number:02d}" for number in range(1, 9))
SOURCE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sql",
    ".vue", ".html", ".css", ".sh", ".ps1", ".r", ".m", ".scala",
}
ORIGINS = {"own", "existing", "adapted", "third_party", "ai", "generated"}
MODES = {"GUI", "API", "CLI", "embedded"}
BASE_FIELD_NAMES = ("software_id", "name", "version", "completed_date",
                    "published_date", "runtime_environment")
from tools.software_discovery import FIELD_CATALOG
FIELD_NAMES = FIELD_CATALOG


def _text(value: object, code: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), code)
    return value


def _items(value: object, code: str, *, nonempty: bool = True) -> list:
    require(isinstance(value, list) and (bool(value) or not nonempty), code)
    require(all(isinstance(item, dict) for item in value), code)
    return value


def _integer(value: object, code: str, minimum: int = 1) -> int:
    require(type(value) is int and value >= minimum, code)
    return value


def _ids(items: list[dict], key: str = "id") -> set[str]:
    values = [_text(item.get(key), "id_required") for item in items]
    require(len(values) == len(set(values)), "duplicate_id")
    return set(values)


def _seal(body: dict) -> dict:
    return {**copy.deepcopy(body), "binding": digest(body)}


def _artifact(value: dict, kind: str) -> dict:
    require(isinstance(value, dict) and value.get("kind") == kind,
            "artifact_kind_mismatch")
    body = {key: item for key, item in value.items() if key != "binding"}
    require(value.get("binding") == digest(body), "artifact_binding_mismatch")
    return value


def _issue(code: str, item_id: str | None = None) -> dict:
    return {"code": code, **({"item_id": item_id} if item_id else {})}


def _metadata(value: dict) -> dict:
    require_fields(value, ("software_id", "name", "version"))
    for key in ("software_id", "name", "version"):
        _text(value[key], "metadata_text_required")
    dates = {}
    for key in ("completed_date", "published_date"):
        entry = value.get(key)
        if entry is None:
            dates[key] = None
            continue
        require_fields(entry, ("value", "evidence_id"))
        try:
            date.fromisoformat(entry["value"])
        except (ValueError, TypeError) as exc:
            raise ContractError("invalid_date_fact") from exc
        dates[key] = copy.deepcopy(entry)
    environment = value.get("runtime_environment")
    if environment is not None:
        require_fields(environment, ("description", "evidence_id"))
    optional = {}
    for key in FIELD_NAMES[len(BASE_FIELD_NAMES):]:
        if key in value:
            item = value[key]
            if item is not None:
                require(isinstance(item, dict) and set(item) == {"value", "evidence_id"},
                        "metadata_optional_value_invalid")
                _text(item["value"], "metadata_optional_value_invalid")
                _text(item["evidence_id"], "metadata_optional_evidence_required")
            optional[key] = copy.deepcopy(item)
    return ({key: value[key] for key in ("software_id", "name", "version")}
            | dates | {"runtime_environment": copy.deepcopy(environment)} | optional)


def _scope(payload: dict) -> tuple[dict, list, str]:
    metadata = _metadata(payload.get("metadata"))
    components = _items(payload.get("components"), "components_required")
    _ids(components)
    rows, issues = [], []
    for component in components:
        require_fields(component, ("id", "kind", "version", "origin", "claim",
                                   "exclusions", "subjects"))
        require(component["kind"] in {"client", "server", "plugin", "service",
                                      "library", "standalone", "firmware"},
                "component_kind_unknown")
        require(component["origin"] in ORIGINS, "origin_unknown")
        require(isinstance(component["claim"], list)
                and isinstance(component["exclusions"], list), "scope_lists_required")
        require(all(isinstance(item, str) and item.strip()
                    for item in component["claim"] + component["exclusions"]),
                "scope_entry_required")
        require(bool(component["claim"] or component["exclusions"]),
                "claim_or_exclusion_required")
        subjects = _items(component["subjects"], "subjects_required", nonempty=False)
        for subject in subjects:
            require_fields(subject, ("subject_id", "basis", "evidence_id"))
        owners = {subject["subject_id"] for subject in subjects}
        if not owners:
            issues.append(_issue("ownership_unknown", component["id"]))
        elif len(owners) > 1 and not component.get("joint_ownership_evidence"):
            issues.append(_issue("ownership_conflict", component["id"]))
        if component["origin"] in {"existing", "adapted"}:
            if not component.get("baseline_evidence") or not component["exclusions"]:
                issues.append(_issue("baseline_or_exclusion_missing", component["id"]))
        if component["origin"] in {"third_party", "generated"} and component["claim"]:
            issues.append(_issue("nonoriginal_claim_requires_review", component["id"]))
        rows.append(copy.deepcopy(component))
    rows.sort(key=lambda item: item["id"])
    for key in ("completed_date", "published_date"):
        if metadata[key] is None:
            issues.append(_issue(f"{key}_unknown"))
    body = {"kind": "software_scope", "metadata": metadata, "components": rows,
            "ownership": "undetermined", "issues": issues,
            "grouping_basis": payload.get("grouping_basis"),
            "git_authorship_is_ownership": False}
    if len(components) > 1 and not payload.get("grouping_basis"):
        issues.append(_issue("component_grouping_basis_missing"))
    return _seal(body), issues, "needs_evidence" if issues else "needs_review"


def _rights(payload: dict) -> tuple[dict, list, str]:
    scope = _artifact(payload.get("scope"), "software_scope")
    records = _items(payload.get("rights"), "rights_required")
    _ids(records, "component_id")
    components = {item["id"]: item for item in scope["components"]}
    require({item["component_id"] for item in records} == set(components),
            "rights_component_coverage_mismatch")
    decisions, issues = [], []
    for record in sorted(records, key=lambda item: item["component_id"]):
        cid = record["component_id"]
        component = components[cid]
        permissions = record.get("permissions", {})
        require(isinstance(permissions, dict), "material_permissions_required")
        require(all(value in {"allow", "deny", "unknown"}
                    for value in permissions.values()), "material_permission_unknown")
        require_fields(record, ("requested_decision",))
        requested = record["requested_decision"]
        require(requested in {"claim", "exclude", "retain_notice", "prohibit"},
                "unknown_material_decision")
        missing = []
        if not record.get("evidence_ids"):
            missing.append("rights_evidence_missing")
        if permissions.get("local_process") == "deny" or requested == "prohibit":
            decision = "prohibit"
        elif permissions.get("local_process") != "allow" or missing:
            decision = "needs_permission"
        elif requested == "exclude" or component["origin"] == "generated":
            decision = "exclude"
        elif component["origin"] == "third_party":
            decision = "retain_notice" if requested == "retain_notice" else "exclude"
            if not record.get("license") or not record.get("notice"):
                decision = "needs_permission"
                missing.append("license_or_notice_missing")
        elif component["origin"] == "ai" and not (
                (record.get("human_contribution") or {}).get("description")
                and (record.get("human_contribution") or {}).get("evidence_ids")):
            decision = "needs_evidence"
            missing.append("human_contribution_unknown")
        elif any(issue.get("item_id") == cid for issue in scope["issues"]):
            decision = "needs_evidence"
            missing.append("scope_issue_unresolved")
        elif requested == "claim" and not component["claim"]:
            decision = "exclude"
            missing.append("no_claimed_expression")
        else:
            decision = requested
        for purpose in ("deposit", "public", "cloud"):
            if permissions.get(purpose) != "allow":
                missing.append(f"{purpose}_not_authorized")
        if component["origin"] == "third_party" and requested == "claim":
            missing.append("third_party_not_original_claim")
        issues.extend(_issue(code, cid) for code in missing)
        decisions.append({"component_id": cid, "decision": decision,
                          "origin": component["origin"],
                          "permissions": copy.deepcopy(permissions),
                          "evidence_ids": record.get("evidence_ids", []),
                          "license": record.get("license"),
                          "notice": record.get("notice"),
                          "human_contribution": record.get("human_contribution"),
                          "issues": missing})
    return _seal({"kind": "software_rights", "scope_binding": scope["binding"],
                  "decisions": decisions}), issues, "needs_review"


def _pagination(value: dict) -> dict:
    require_fields(value, ("lines_per_page", "wrap_columns", "selection", "basis"))
    _integer(value["lines_per_page"], "invalid_lines_per_page")
    _integer(value["wrap_columns"], "invalid_wrap_columns")
    require(value["selection"] in {"all", "head_tail"}, "unknown_selection")
    _text(value["basis"], "pagination_basis_required")
    if value["selection"] == "head_tail":
        _integer(value.get("pages_each_end"), "invalid_pages_each_end")
    return copy.deepcopy(value)


def _render(lines: list[dict], pagination: dict, *, select: bool = True) -> tuple[list, list]:
    segments = []
    width = pagination["wrap_columns"]
    for line in lines:
        text = line["text"]
        for start in range(0, max(1, len(text)), width):
            segments.append({"file_id": line["file_id"], "source_line": line["source_line"],
                             "column_start": start + 1,
                             "column_end": min(start + width, len(text)),
                             "text": text[start:start + width],
                             **({"selection_basis": line["selection_basis"]}
                                if "selection_basis" in line else {})})
    per_page = pagination["lines_per_page"]
    if select and pagination["selection"] == "head_tail":
        count = pagination["pages_each_end"] * per_page
        if len(segments) > count * 2:
            segments = segments[:count] + segments[-count:]
    pages = []
    for start in range(0, len(segments), per_page):
        pages.append({"page": len(pages) + 1, "lines": segments[start:start + per_page]})
    return pages, segments


def _preflight_context(payload: dict, *, use_system_time: bool) -> None:
    require(type(use_system_time) is bool, "system_time_boolean_required")
    require_fields(payload, ("context",))
    context = payload["context"]
    require_fields(context, ("environment", "permissions", "sensitivity", "purpose", "now"))
    require(isinstance(context["environment"], dict), "environment_object_required")
    if use_system_time:
        # 真实入口不能沿用调用者时间；仅替换本次核验副本，保留输入快照。
        context = {**context, "now": datetime.now(timezone.utc).isoformat()}
    preflight(context["environment"], context["permissions"],
              sensitivity=context["sensitivity"], purpose=context["purpose"], now=context["now"])


def _source(payload: dict, *, use_system_time: bool = False) -> tuple[dict, list, str]:
    scope = _artifact(payload.get("scope"), "software_scope")
    rights = _artifact(payload.get("rights_decisions"), "software_rights")
    require(rights["scope_binding"] == scope["binding"], "rights_scope_stale")
    root = _text(payload.get("authorized_root"), "authorized_root_required")
    files = _items(payload.get("files"), "file_inventory_required")
    _ids(files)
    require(type(payload.get("inventory_complete")) is bool,
            "inventory_completeness_required")
    pagination = _pagination(payload.get("pagination"))
    selection_purpose = payload.get("selection_purpose", "deposit")
    require(selection_purpose in {"local_process", "deposit", "public"},
            "selection_purpose_unknown")
    selection_basis = payload.get("selection_basis", "claimed_expression")
    require(selection_basis in {"claimed_expression", "deposit_context"},
            "selection_basis_unknown")
    require(selection_basis != "deposit_context" or selection_purpose != "public",
            "deposit_context_purpose_invalid")
    require_complete = payload.get("require_complete_source", False)
    require(type(require_complete) is bool, "source_completeness_boolean_required")
    decisions = {item["component_id"]: item for item in rights["decisions"]}
    manifest, excluded, source_lines, issues = [], [], [], []
    total, original_total = 0, 0
    omitted = {item["id"] for item in files if item.get("kind") == "source"}
    incomplete_ranges = []
    paths = set()
    max_bytes = _integer(payload.get("max_file_bytes", 10_000_000), "invalid_size_limit")
    for entry in sorted(files, key=lambda item: item["id"]):
        require_fields(entry, ("id", "path", "component_id", "kind", "include"))
        require(type(entry["include"]) is bool, "include_boolean_required")
        require(entry["kind"] in {"source", "dependency", "generated", "other"},
                "file_kind_unknown")
        require(entry["component_id"] in decisions, "file_component_unknown")
        if "expected_sha256" in entry:
            expected = entry["expected_sha256"]
            require(isinstance(expected, str)
                    and re.fullmatch(r"[0-9a-fA-F]{64}", expected) is not None,
                    "source_hash_invalid")
        decision = decisions[entry["component_id"]]
        # 禁止处理的材料连字节也不读取；调用者清单只保留不含正文的ID。
        if decision["decision"] in {"prohibit", "needs_permission"}:
            excluded.append({"file_id": entry["id"], "reason": decision["decision"],
                             "read_status": "not_read"})
            issues.append(_issue("material_not_read", entry["id"]))
            continue
        path = safe_path(root, entry["path"])
        require(path.is_file(), "source_file_required")
        require(path not in paths, "duplicate_source_path")
        paths.add(path)
        try:
            if use_system_time:
                _preflight_context(payload, use_system_time=True)
            with path.open("rb") as stream:
                content = stream.read(max_bytes + 1)
        except OSError:
            raise ContractError("source_read_failed") from None
        require(len(content) <= max_bytes, "source_file_too_large")
        content_hash = sha256_bytes(content)
        if "expected_sha256" in entry:
            require(content_hash == entry["expected_sha256"].lower(),
                    "source_hash_mismatch")
        file_record = {"file_id": entry["id"], "path": entry["path"],
                       "component_id": entry["component_id"], "kind": entry["kind"],
                       "sha256": content_hash, "bytes": len(content),
                       "selection_basis": None, "origin": decision["origin"],
                       "rights_decision": decision["decision"]}
        manifest.append(file_record)
        reason = None
        if entry["kind"] != "source":
            reason = entry["kind"]
        elif selection_basis == "deposit_context" and decision["origin"] == "generated":
            reason = "generated"
        elif Path(entry["path"]).suffix.lower() not in SOURCE_SUFFIXES:
            if not entry.get("source_type_evidence"):
                reason = "unknown_suffix"
        if reason:
            excluded.append({"file_id": entry["id"], "reason": reason})
            issues.append(_issue(reason, entry["id"]))
            continue
        encoding = entry.get("encoding", "utf-8")
        require(encoding in {"utf-8", "utf-8-sig", "utf-16", "gb18030", "ascii"},
                "unsupported_encoding")
        try:
            text = content.decode(encoding, errors="strict")
        except UnicodeError:
            excluded.append({"file_id": entry["id"], "reason": "undecodable"})
            issues.append(_issue("undecodable", entry["id"]))
            continue
        if "\x00" in text:
            excluded.append({"file_id": entry["id"], "reason": "binary_content"})
            issues.append(_issue("binary_content", entry["id"]))
            continue
        lines = text.splitlines()
        file_record["line_count"] = len(lines)
        file_record["encoding"] = encoding
        total += len(lines)
        # 必要上下文不能因进入母本而成为本次原创表达；旧选材口径保持兼容。
        if (decision["origin"] not in {"third_party", "generated", "existing"}
                and (selection_basis == "claimed_expression"
                     or decision["decision"] == "claim")):
            original_total += len(lines)
        if not entry["include"]:
            _text(entry.get("exclusion_reason"), "exclusion_reason_required")
            excluded.append({"file_id": entry["id"], "reason": "caller_excluded",
                             "basis": entry["exclusion_reason"]})
            continue
        line_basis = "claimed_expression"
        if decision["decision"] != "claim":
            if (selection_basis != "deposit_context"
                    or decision["decision"] not in {"exclude", "retain_notice"}):
                excluded.append({"file_id": entry["id"], "reason": decision["decision"]})
                continue
            evidence = entry.get("deposit_context_evidence")
            if not isinstance(evidence, str) or not evidence.strip():
                excluded.append({"file_id": entry["id"],
                                 "reason": "deposit_context_evidence_missing"})
                issues.append(_issue("deposit_context_evidence_missing", entry["id"]))
                continue
            # 旧exclude决定未核第三方声明，进入交存上下文前须补核，不能视作许可。
            if decision["origin"] == "third_party" and not (
                    decision.get("license") and decision.get("notice")):
                excluded.append({"file_id": entry["id"], "reason": "license_or_notice_missing"})
                issues.append(_issue("license_or_notice_missing", entry["id"]))
                continue
            line_basis = "deposit_context"
        if decision["permissions"].get(selection_purpose) != "allow":
            excluded.append({"file_id": entry["id"], "reason": "selection_purpose_not_authorized"})
            issues.append(_issue("selection_purpose_not_authorized", entry["id"]))
            continue
        ranges = entry.get("ranges", [[1, len(lines)]] if lines else [])
        require(isinstance(ranges, list), "line_ranges_required")
        selected = set()
        for interval in ranges:
            require(isinstance(interval, list) and len(interval) == 2, "invalid_line_range")
            first = _integer(interval[0], "invalid_line_range")
            last = _integer(interval[1], "invalid_line_range")
            require(first <= last <= len(lines), "invalid_line_range")
            chosen = set(range(first, last + 1))
            require(not selected.intersection(chosen), "overlapping_line_ranges")
            selected.update(chosen)
        omitted.discard(entry["id"])
        if len(selected) != len(lines):
            incomplete_ranges.append(entry["id"])
        file_record["selection_basis"] = line_basis
        if line_basis == "deposit_context":
            file_record["deposit_context_evidence"] = entry["deposit_context_evidence"]
        for number in sorted(selected):
            source_lines.append({"file_id": entry["id"], "source_line": number,
                                 "text": lines[number - 1], "selection_basis": line_basis})
    # 覆盖范围针对分页前母本，首尾抽取的中间段不算漏读；只证明声明清单。
    coverage = {
        "status": ("complete" if payload["inventory_complete"]
                   and not omitted and not incomplete_ranges else "partial"),
        "basis": "declared_inventory_not_disk_discovery",
        "candidate_source_lines": len(source_lines),
        "omitted_file_ids": sorted(omitted),
        "incomplete_range_file_ids": incomplete_ranges,
    }
    if require_complete and coverage["status"] != "complete":
        issues.append(_issue("source_coverage_incomplete"))
    pages, segments = _render(source_lines, pagination)
    if not payload["inventory_complete"]:
        issues.append(_issue("inventory_incomplete"))
    if not segments:
        issues.append(_issue("no_selected_source"))
    selected_keys = {(item["file_id"], item["source_line"]) for item in segments}
    body = {"kind": "software_source", "metadata": scope["metadata"],
            "scope_binding": scope["binding"], "rights_binding": rights["binding"],
            "selection_purpose": selection_purpose, "selection_basis": selection_basis,
            "source_coverage": coverage,
            "manifest": manifest, "excluded": excluded, "pages": pages,
            "pagination": pagination, "selected_lines": [line for line in source_lines
                if (line["file_id"], line["source_line"]) in selected_keys],
            "total_source_lines": total, "original_source_lines": original_total,
            "selected_source_lines": len(selected_keys), "rendered_lines": len(segments),
            "quantity_scope": "declared_inventory", "inventory_complete": payload["inventory_complete"],
            "notices": [{"component_id": row["component_id"], "notice": row["notice"]}
                        for row in rights["decisions"] if row["notice"]],
            "rule_status": "caller_parameters_not_professionally_verified",
            "issues": issues, "source_storage": "immutable_result_snapshot_not_disk_copy"}
    artifact = _seal(body)
    status = "partial" if issues else "needs_review"
    previous = payload.get("previous_material")
    if previous is not None:
        _artifact(previous, "software_source")
        if previous["binding"] != artifact["binding"]:
            issues = issues + [_issue("previous_material_invalidated")]
            artifact = _seal({**body, "supersedes": previous["binding"]})
            status = "invalidated"
    return artifact, issues, status


def _mask(payload: dict) -> tuple[dict, list, str]:
    material = _artifact(payload.get("material"), "software_source")
    redactions = _items(payload.get("redactions", []), "redactions_list_required",
                        nonempty=False)
    secrets = payload.get("sensitive_literals", [])
    require(isinstance(secrets, list) and all(isinstance(value, str) and value
                                            for value in secrets), "invalid_sensitive_literals")
    require(all("\n" not in value and "\r" not in value for value in secrets),
            "multiline_secret_requires_line_redactions")
    secrets = list(secrets)
    lines = copy.deepcopy(material["selected_lines"])
    by_key = {(line["file_id"], line["source_line"]): line for line in lines}
    spans: dict[tuple, set[int]] = {}
    audit = []
    for entry in redactions:
        require_fields(entry, ("file_id", "line", "start", "end", "basis_id"))
        require(re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", entry["basis_id"]) is not None,
                "redaction_basis_id_required")
        key = (entry["file_id"], entry["line"])
        require(key in by_key, "redaction_line_not_selected")
        start = _integer(entry["start"], "redaction_columns_invalid")
        end = _integer(entry["end"], "redaction_columns_invalid")
        require(start <= end <= len(by_key[key]["text"]), "redaction_columns_invalid")
        spans.setdefault(key, set()).update(range(start - 1, end))
        # 同一秘密在标题、署名或其他行重现时也清除；审计不保存该值。
        secrets.append(by_key[key]["text"][start - 1:end])
        audit.append({"file_id": entry["file_id"], "line": entry["line"],
                      "start": start, "end": end, "reason": "declared_sensitive_span"})
    for line in lines:
        key = (line["file_id"], line["source_line"])
        text = line["text"]
        positions = spans.setdefault(key, set())
        for secret in secrets:
            start = text.find(secret)
            while start != -1:
                positions.update(range(start, start + len(secret)))
                start = text.find(secret, start + 1)
        line["text"] = "".join("█" if index in positions else char
                               for index, char in enumerate(text))
        if positions:
            audit.append({"file_id": line["file_id"], "line": line["source_line"],
                          "masked_characters": len(positions), "reason": "mask_applied"})
    # 不把原manifest、排除理由、许可正文或源行拷入脱敏输出，避免旁路复述。
    def clean(value):
        if isinstance(value, str):
            for secret in sorted(secrets, key=len, reverse=True):
                value = value.replace(secret, "█" * len(secret))
            return value
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    pages, segments = _render(lines, material["pagination"])
    document = clean({"metadata": material["metadata"], "pages": pages,
                      "notices": material["notices"],
                      "selected_source_lines": material["selected_source_lines"],
                      "rendered_lines": len(segments)})
    issues = []
    rule = payload.get("deposit_rule")
    if not rule or not rule.get("evidence_id") or not rule.get("review_evidence"):
        issues.append(_issue("exception_deposit_rule_unverified"))
    if payload.get("target_action", "deposit") != "deposit":
        issues.append(_issue("separate_disclosure_authorization_required"))
    return _seal({"kind": "software_masked", "source_binding": material["binding"],
                  "document": document,
                  "private_audit": clean({"source_binding": material["binding"],
                                          "operations": audit}),
                  "semantic_review": "required", "external_permission": "not_granted"}), issues, "needs_review"


def _manual_blocks(payload: dict, metadata: dict) -> tuple[list | None, list]:
    """正文确认只记录来源声明；缺少依据的块不得从confirmed隐式放行。"""
    document_metadata = payload.get("document_metadata", {})
    require(isinstance(document_metadata, dict)
            and set(document_metadata) <= {"name", "version", "software_id"},
            "manual_metadata_invalid")
    require(all(value == metadata.get(key) for key, value in document_metadata.items()),
            "manual_metadata_conflict")
    if "blocks" not in payload:
        return None, []
    blocks = copy.deepcopy(_items(payload["blocks"], "manual_blocks_required"))
    _ids(blocks)
    issues = []
    operation_ids = {row["id"] for row in payload.get("operations", [])}
    for block in blocks:
        require(set(block) <= {"id", "kind", "text", "evidence_ids", "status", "section",
                               "operation_id", "image_id", "source_locator", "path",
                               "source", "reference_path", "cells", "language", "list_level",
                               "numbering_id", "sha256", "input_binding", "confirmation"},
                "manual_block_shape_invalid")
        require(isinstance(block["id"], str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]{0,127}", block["id"]),
                "manual_block_id_invalid")
        require(block.get("kind") in {"heading1", "heading2", "paragraph", "code",
                                      "list", "table", "image"}, "manual_block_kind_invalid")
        require(isinstance(block.get("text"), str), "manual_block_text_required")
        evidence = block.setdefault("evidence_ids", [])
        require(isinstance(evidence, list)
                and all(isinstance(item, str) and item.strip() for item in evidence),
                "manual_block_evidence_invalid")
        require(block.get("status", "needs_review") in {"confirmed", "needs_review",
                "needs_evidence", "draft", "blocked", "unknown", "invalidated", "not_applicable"},
                "manual_block_status_invalid")
        block["status"] = "confirmed" if evidence and block.get("status") == "confirmed" else "needs_review"
        if block["status"] != "confirmed":
            issues.append(_issue("manual_block_needs_review", block["id"]))
        if "operation_id" in block:
            require(block["operation_id"] in operation_ids, "manual_block_operation_unknown")
        if block["kind"] == "image":
            _text(block.get("image_id"), "manual_block_image_required")
        else:
            _text(block["text"], "manual_block_text_required")
    return blocks, issues


def _bound_manual_input(manual_input: dict, previous: dict | None,
                        scope: dict, source: dict) -> dict:
    """正文或其已声明依赖变化时，旧确认只能由当前内容绑定的人工记录替换。"""
    current = copy.deepcopy(manual_input)
    if "blocks" not in current:
        return current
    current["blocks"], _ = _manual_blocks(current, scope["metadata"])
    old_manual = (previous or {}).get("manual") or {}
    old_blocks = {block["id"]: block for block in old_manual.get("blocks") or []}
    for block in current["blocks"]:
        content = {key: value for key, value in block.items()
                   if key not in {"status", "input_binding", "confirmation"}}
        binding = digest({"block": content, "scope": scope["binding"],
                          "source": source["binding"], "mode": current.get("mode"),
                          "facts": current.get("facts", []),
                          "operations": current.get("operations", []),
                          "runtime_evidence": current.get("runtime_evidence", [])})
        old = old_blocks.get(block["id"])
        unchanged = bool(old and old.get("input_binding") == binding)
        confirmation = block.get("confirmation")
        if confirmation is not None:
            require(isinstance(confirmation, dict) and set(confirmation) == {
                "input_binding", "actor", "role", "evidence_id"},
                "manual_confirmation_invalid")
            for key in ("input_binding", "actor", "role", "evidence_id"):
                _text(confirmation[key], "manual_confirmation_invalid")
        fresh = bool(confirmation and confirmation["input_binding"] == binding)
        inherited = unchanged and old.get("status") == "confirmed"
        if previous is not None and not (fresh or inherited):
            block["status"] = "needs_review"
        if confirmation is not None and not fresh:
            block.pop("confirmation")
        elif inherited and confirmation is None and old.get("confirmation"):
            block["confirmation"] = copy.deepcopy(old["confirmation"])
        block["input_binding"] = binding
    return current


def _manual(payload: dict) -> tuple[dict, list, str]:
    scope = _artifact(payload.get("scope"), "software_scope")
    mode = payload.get("mode")
    require(mode in MODES, "unsupported_software_mode")
    blocks, block_issues = _manual_blocks(payload, scope["metadata"])
    facts = _items(payload.get("facts", []), "software_facts_required", nonempty=blocks is None)
    _ids(facts)
    for fact in facts:
        require_fields(fact, ("id", "text", "evidence_id"))
        _text(fact["text"], "fact_text_required")
    operations = _items(payload.get("operations", []), "operations_required", nonempty=blocks is None)
    _ids(operations)
    for operation in operations:
        require_fields(operation, ("id", "input", "expected_output", "failure", "evidence_id"))
    runtime = payload.get("runtime_evidence", [])
    _items(runtime, "runtime_evidence_list_required", nonempty=False)
    for entry in runtime:
        require_fields(entry, ("id", "version", "evidence_id", "kind"))
        require(entry["version"] == scope["metadata"]["version"], "runtime_version_mismatch")
        require(entry["kind"] in {"screenshot", "transcript", "test", "measurement"},
                "runtime_evidence_kind_unknown")
    if mode != "GUI":
        require(not any(entry["kind"] == "screenshot" for entry in runtime),
                "screenshot_not_applicable_to_mode")
    titles = {"GUI": "界面操作流程", "API": "接口调用流程", "CLI": "命令操作流程",
              "embedded": "嵌入式输入输出与部署流程"}
    meta = scope["metadata"]
    text = [f"# {meta['name']} {meta['version']} 使用与设计说明稿", "",
            f"形态：{mode}。本稿为可编辑事实稿，未作专业签核。", "", "## 软件事实"]
    text += [f"- {fact['text']}（证据：{fact['evidence_id']}）" for fact in facts]
    text += ["", f"## {titles[mode]}"]
    for operation in operations:
        text += [f"### {operation['id']}", f"输入：{operation['input']}",
                 f"预期输出（不是已执行结果）：{operation['expected_output']}",
                 f"失败路径：{operation['failure']}", f"依据：{operation['evidence_id']}", ""]
    issues = block_issues
    if not runtime:
        issues.append(_issue("runtime_not_verified"))
        text += ["## 运行证据", "尚未提供；未生成截图或成功运行记录。"]
    else:
        text += ["## 运行证据引用"] + [f"- {entry['id']}：{entry['kind']} / {entry['evidence_id']}"
                                       for entry in runtime]
    if blocks is not None:
        text = [("# " if block["kind"] == "heading1" else
                 "## " if block["kind"] == "heading2" else "") + block["text"]
                for block in blocks]
    extra = {"blocks": blocks, "document_metadata": payload.get("document_metadata", {})} if blocks is not None else {}
    if "revision" in payload:
        require(isinstance(payload["revision"], dict), "manual_revision_invalid")
        extra["revision"] = copy.deepcopy(payload["revision"])
    return _seal({**extra, "kind": "software_manual", "metadata": meta,
                  "scope_binding": scope["binding"], "mode": mode,
                  "markdown": "\n".join(text) + "\n", "facts": facts,
                  "operations": operations, "runtime_evidence": runtime,
                  "verification": "evidence_referenced_not_executed" if runtime else "static_only",
                  "screenshots": [entry for entry in runtime if entry["kind"] == "screenshot"]}), issues, "needs_review"


def _consistency(payload: dict) -> tuple[dict, list, str]:
    scope = _artifact(payload.get("scope"), "software_scope")
    material = _artifact(payload.get("material"), "software_source")
    manual = _artifact(payload.get("manual"), "software_manual")
    form = payload.get("form")
    require_fields(form, ("name", "version", "total_source_lines", "selected_source_lines"))
    issues, rows = [], []
    for label, item in (("material", material), ("manual", manual)):
        if item["scope_binding"] != scope["binding"]:
            issues.append(_issue("scope_binding_stale", label))
    fields = ("name", "version", "completed_date", "published_date", "runtime_environment") + tuple(
        key for key in FIELD_NAMES[len(BASE_FIELD_NAMES):] if key in scope["metadata"] or key in form)
    for key in fields:
        expected = scope["metadata"].get(key)
        for label, fields in (("material", material["metadata"]),
                              ("manual", manual["metadata"]), ("form", form)):
            actual = fields.get(key)
            consistent = actual == expected
            rows.append({"field": key, "document": label, "matches": consistent,
                         "basis_available": expected is not None})
            if not consistent:
                issues.append(_issue(f"field_mismatch:{key}", label))
            if expected is None:
                issues.append(_issue(f"date_or_field_unverified:{key}", label))
    for key in ("total_source_lines", "selected_source_lines"):
        _integer(form[key], "source_quantity_invalid", minimum=0)
        rows.append({"field": key, "document": "form", "matches": form[key] == material[key]})
        if form[key] != material[key]:
            issues.append(_issue(f"quantity_mismatch:{key}"))
    if not material["inventory_complete"]:
        issues.append(_issue("inventory_completeness_not_confirmed"))
    for field, limit in payload.get("field_limits", {}).items():
        _integer(limit, "invalid_field_limit")
        require(field in form and isinstance(form[field], str), "field_limit_target_invalid")
        if len(form[field]) > limit:
            issues.append(_issue("field_limit_exceeded", field))
    if not payload.get("form_rule_evidence"):
        issues.append(_issue("current_form_rule_unverified"))
    return _seal({"kind": "software_consistency", "rows": rows,
                  "bindings": {"scope": scope["binding"], "material": material["binding"],
                               "manual": manual["binding"], "form": digest(form)},
                  "quantity_scope": material["quantity_scope"],
                  "counts_not_overwritten": True}), issues, "needs_evidence" if issues else "checked"


def _correction(payload: dict) -> tuple[dict, list, str]:
    before = _artifact(payload.get("before"), "software_scope")
    after = _artifact(payload.get("after"), "software_scope")
    event = payload.get("event")
    require_fields(event, ("id", "type", "evidence_id", "source_status"))
    require(event["type"] in {"correction", "change", "succession"}, "event_type_unknown")
    require(event["source_status"] in {"synthetic", "official_record", "unverified"},
            "event_source_status_unknown")
    changed = []
    for key in sorted(set(before) | set(after)):
        if key not in {"binding", "issues"} and before.get(key) != after.get(key):
            changed.append(key)
    notices = _items(payload.get("notice_items", []), "notice_items_required", nonempty=False)
    _ids(notices)
    replies = _items(payload.get("responses", []), "responses_required", nonempty=False)
    _ids(replies, "notice_id")
    require({entry["notice_id"] for entry in replies}.issubset({item["id"] for item in notices}),
            "unknown_notice_response")
    response_map = {entry["notice_id"]: entry for entry in replies}
    issues, dispositions = [], []
    for item in notices:
        require_fields(item, ("id", "evidence_id", "locator"))
        response = response_map.get(item["id"])
        if not response or not response.get("basis_evidence") or not response.get("replacement_locator"):
            issues.append(_issue("notice_item_unanswered", item["id"]))
        dispositions.append({"notice": item, "response": response})
    if event["source_status"] == "unverified":
        issues.append(_issue("notice_authenticity_unknown"))
    deadline = None
    if payload.get("deadline") is not None:
        deadline_input = {**payload["deadline"], "business": "software"}
        deadline = record_deadline(deadline_input)
        if deadline["artifacts"]["missing"]:
            issues.append(_issue("deadline_evidence_incomplete"))
    else:
        issues.append(_issue("deadline_unknown"))
    reviews = _items(payload.get("prior_reviews", []), "reviews_list_required", nonempty=False)
    updated_reviews = []
    for review in reviews:
        require_fields(review, ("id", "binding", "status"))
        item = copy.deepcopy(review)
        if changed and item["binding"] == before["binding"]:
            item["status"] = "invalidated"
            item["reason"] = "software_scope_changed"
        updated_reviews.append(item)
    return _seal({"kind": "software_correction", "event": event,
                  "history": [{"binding": before["binding"], "role": "previous"},
                              {"binding": after["binding"], "role": "replacement"}],
                  "changed_fields": changed, "dispositions": dispositions,
                  "reviews": updated_reviews, "deadline": deadline,
                  "registration_status": "not_asserted", "candidate_status": "draft",
                  "required_review": ["software_facts", "ownership", "disclosure"] if changed else []}), issues, "invalidated" if changed else "needs_review"


def _international(payload: dict) -> tuple[dict, list, str]:
    scope = _artifact(payload.get("scope"), "software_scope")
    branch = payload.get("branch")
    require(branch in {"adaptation", "dispute"}, "software_branch_unknown")
    issues = []
    if branch == "adaptation":
        targets = _items(payload.get("targets"), "adaptation_targets_required")
        _ids(targets, "jurisdiction")
        rows = []
        for target in targets:
            require_fields(target, ("jurisdiction", "route", "requirements"))
            require(target["route"] in {"registration", "protection_without_registration", "unknown"},
                    "copyright_route_unknown")
            requirements = _items(target["requirements"], "requirements_list_required", nonempty=False)
            _ids(requirements)
            mapped = []
            for requirement in requirements:
                require_fields(requirement, ("id", "source_locator"))
                status = "evidence_referenced" if requirement.get("evidence_id") else "missing"
                if status == "missing":
                    issues.append(_issue("regional_requirement_missing", requirement["id"]))
                mapped.append({**requirement, "status": status})
            verified = bool(target.get("rule_evidence") and target.get("professional_review_evidence"))
            if not verified:
                issues.append(_issue("regional_rule_unverified", target["jurisdiction"]))
            rows.append({"jurisdiction": target["jurisdiction"], "route": target["route"],
                         "requirements": mapped,
                         "registration_applicability": "not_applicable" if target["route"] == "protection_without_registration" else "requires_regional_review",
                         "rule_evidence": target.get("rule_evidence"),
                         "professional_review_evidence": target.get("professional_review_evidence"),
                         "support_status": "evidence_referenced_not_independently_verified",
                         "pagination_inherited": False})
        return _seal({"kind": "software_adaptation", "scope_binding": scope["binding"],
                      "targets": rows}), issues, "needs_review"
    pairs = _items(payload.get("pairs"), "comparison_pairs_required")
    _ids(pairs)
    comparisons = []
    for pair in pairs:
        require_fields(pair, ("id", "classification", "left", "right"))
        require(pair["classification"] in {"expression", "function", "third_party", "existing", "unknown"},
                "comparison_classification_unknown")
        for side in ("left", "right"):
            require_fields(pair[side], ("version", "text", "evidence_id", "locator"))
            require(isinstance(pair[side]["text"], str), "comparison_text_required")
        excluded = pair["classification"] in {"function", "third_party", "existing"}
        matches = []
        if pair["classification"] == "expression":
            left, right = pair["left"]["text"], pair["right"]["text"]
            matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
            matches = [{"left_start": block.a + 1, "right_start": block.b + 1,
                        "characters": block.size} for block in matcher.get_matching_blocks() if block.size]
        if pair["classification"] == "unknown":
            issues.append(_issue("expression_function_classification_unknown", pair["id"]))
        for axis in ("access_evidence", "origin_evidence"):
            if not pair.get(axis):
                issues.append(_issue(f"{axis}_unknown", pair["id"]))
        comparisons.append({"id": pair["id"], "classification": pair["classification"],
                            "excluded_from_expression_comparison": excluded,
                            "left": {key: value for key, value in pair["left"].items() if key != "text"},
                            "right": {key: value for key, value in pair["right"].items() if key != "text"},
                            "left_content_hash": sha256_bytes(pair["left"]["text"].encode("utf-8")),
                            "right_content_hash": sha256_bytes(pair["right"]["text"].encode("utf-8")),
                            "literal_matching_spans": matches,
                            "access_evidence": pair.get("access_evidence"),
                            "origin_evidence": pair.get("origin_evidence"),
                            "legal_similarity": "not_determined", "infringement": "not_determined"})
    return _seal({"kind": "software_dispute", "scope_binding": scope["binding"],
                  "comparisons": comparisons,
                  "method": "literal_expression_localization_not_copyright_test"}), issues, "needs_review"


def _field_inputs(payload: dict) -> tuple[list, list]:
    """候选不是事实写入权限；在源码读取前拒绝越界字段及内联确认。"""
    candidates = _items(payload.get("field_candidates", []), "field_candidates_list_required",
                        nonempty=False)
    confirmations = _items(payload.get("confirmations", []), "confirmations_list_required",
                           nonempty=False)
    for candidate in candidates:
        require(set(candidate) == {"field", "value", "status", "sources"},
                "field_candidate_shape_invalid")
        field, value, status = candidate["field"], candidate["value"], candidate["status"]
        require(isinstance(field, str) and field in FIELD_NAMES, "field_candidate_target_invalid")
        require(isinstance(status, str) and status in {"candidate", "inferred", "conflict", "unknown"},
                "field_candidate_status_invalid")
        if status == "unknown":
            require(value is None, "unknown_field_value_required")
        elif value is None:
            require(status == "conflict", "field_candidate_value_required")
        elif field in {"software_id", "name", "version"}:
            _text(value, "field_candidate_value_invalid")
        else:
            value_key = "description" if field == "runtime_environment" else "value"
            require(isinstance(value, dict) and set(value) == {value_key, "evidence_id"},
                    "field_candidate_value_invalid")
            _text(value[value_key], "field_candidate_value_invalid")
            _text(value["evidence_id"], "field_candidate_evidence_required")
            if field in {"completed_date", "published_date"}:
                try:
                    date.fromisoformat(value["value"])
                except ValueError:
                    raise ContractError("invalid_date_fact") from None
        sources = _items(candidate["sources"], "field_candidate_sources_required",
                         nonempty=status != "unknown")
        for source in sources:
            if set(source) == {"path", "sha256", "locator"}:
                path = _text(source["path"], "field_source_path_invalid")
                require(not any(char in path for char in ("\\", ":", "\x00"))
                        and all(part not in {"", ".", ".."} for part in path.split("/")),
                        "field_source_path_invalid")
                require(isinstance(source["sha256"], str)
                        and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is not None,
                        "field_source_hash_invalid")
            else:
                require(set(source) == {"evidence_id", "locator"}, "field_source_shape_invalid")
                _text(source["evidence_id"], "field_source_evidence_required")
            _text(source["locator"], "field_source_locator_required")
    candidate_ids = [digest(item) for item in candidates]
    require(len(candidate_ids) == len(set(candidate_ids)), "field_candidate_duplicate")
    for confirmation in confirmations:
        require(set(confirmation) == {"candidate_digest", "input_binding", "status",
                                      "actor", "role", "evidence_id"},
                "field_confirmation_shape_invalid")
        require(confirmation["status"] == "confirmed", "field_confirmation_status_invalid")
        for key in ("candidate_digest", "input_binding"):
            require(isinstance(confirmation[key], str)
                    and re.fullmatch(r"[0-9a-f]{64}", confirmation[key]) is not None,
                    "field_confirmation_binding_invalid")
        for key in ("actor", "role", "evidence_id"):
            _text(confirmation[key], "field_confirmation_evidence_required")
    _ids(confirmations, "candidate_digest")
    return candidates, confirmations


def _field_worksheet(payload: dict, scope: dict, source: dict, form: dict,
                     candidates: list, confirmations: list) -> tuple[dict, dict, list]:
    """只填form；scope、权属、计数和运行事实仍由原责任输入提供。"""
    input_binding = digest({
        "scope": scope["binding"], "source": source["binding"], "form": form,
        "manual_input": payload.get("manual_input"),
        "form_rule_evidence": payload.get("form_rule_evidence"),
        "field_limits": payload.get("field_limits", {}),
        "candidates": sorted(digest(item) for item in candidates),
    })
    # 文件依据只查已授权读取的manifest，不因为候选给出路径而扩大读取范围。
    hashes = {item["path"]: item["sha256"] for item in source["manifest"]}
    evidence_ids = set()
    references = list(scope["metadata"].values()) + [form.get(field) for field in FIELD_NAMES]
    manual_input = payload.get("manual_input") or {}
    for key in ("facts", "operations", "runtime_evidence"):
        values = manual_input.get(key, [])
        if isinstance(values, list):
            references.extend(values)
    for reference in references:
        if isinstance(reference, dict) and isinstance(reference.get("evidence_id"), str):
            evidence_ids.add(reference["evidence_id"])
    by_digest = {item["candidate_digest"]: item for item in confirmations}
    candidate_ids = {digest(item) for item in candidates}
    unmatched = [item for item in confirmations if item["candidate_digest"] not in candidate_ids]
    issues = [_issue("field_confirmation_candidate_missing") for _ in unmatched]
    rows, questions = [], []
    updated = copy.deepcopy(form)
    active_fields = tuple(field for field in FIELD_NAMES if field in BASE_FIELD_NAMES
                          or field in form or any(item["field"] == field for item in candidates))
    for field in active_fields:
        entries = [item for item in candidates if item["field"] == field]
        conflict = (len({digest(item["value"]) for item in entries}) > 1
                    or any(item["status"] == "conflict" for item in entries))
        if not entries:
            value = form.get(field)
            rows.append({"field": field, "value": copy.deepcopy(value),
                         "status": "declared" if value is not None else "unknown",
                         "origin": "form", "candidate_digest": None, "sources": [],
                         "confirmation": None, "applied": False,
                         "reason": "field_declaration_unconfirmed"})
            questions.append({"field": field, "candidate_digest": None,
                              "reason": "field_declaration_unconfirmed",
                              "prompt": "请核对已声明值；如需确认，提供有依据的候选和独立确认记录。"})
            continue
        for candidate in sorted(entries, key=digest):
            candidate_digest = digest(candidate)
            confirmation = by_digest.get(candidate_digest)
            status = "conflict" if conflict else candidate["status"]
            reason = None
            if status in {"conflict", "unknown"}:
                reason = "field_conflict_unresolved" if status == "conflict" else "field_unknown"
            for origin in candidate["sources"]:
                if "path" in origin:
                    actual = hashes.get(origin["path"])
                    if actual is None:
                        reason = reason or "field_source_unavailable"
                    elif actual != origin["sha256"]:
                        reason = reason or "field_source_stale"
                elif origin["evidence_id"] not in evidence_ids:
                    reason = reason or "field_source_unavailable"
            if confirmation is None:
                reason = reason or "field_confirmation_required"
            elif confirmation["input_binding"] != input_binding:
                reason = reason or "field_confirmation_stale"
            applied = reason is None
            if applied:
                updated[field] = copy.deepcopy(candidate["value"])
                status = "confirmed"
            else:
                issues.append(_issue(reason, field))
                questions.append({"field": field, "candidate_digest": candidate_digest,
                                  "reason": reason,
                                  "prompt": "请核对候选、来源和当前版本；冲突或未知须先补证，旧确认不能沿用。"})
            rows.append({**copy.deepcopy(candidate), "status": status,
                         "candidate_status": candidate["status"], "origin": "candidate",
                         "current_value": copy.deepcopy(form.get(field)),
                         "current_status": "declared" if form.get(field) is not None else "unknown",
                         "candidate_digest": candidate_digest,
                         "confirmation": copy.deepcopy(confirmation), "applied": applied,
                         "reason": reason})
    worksheet = _seal({"kind": "software_field_worksheet", "input_binding": input_binding,
                       "rows": rows, "questions": questions,
                       "unmatched_confirmations": unmatched,
                       "application_target": "form_only",
                       "verification": "references_checked_not_factual_or_identity_verification"})
    return updated, worksheet, issues


def _preparation_dependencies(body: dict) -> dict:
    """截图依赖自身记录及软件版本，不继承表单或说明稿排版的失效。"""
    scope, source, rights = (body.get(key) or {} for key in ("scope", "source", "rights"))
    metadata = scope.get("metadata", {})
    return {
        "rights": {"scope": scope.get("binding")},
        "source": {"scope": scope.get("binding"), "rights": rights.get("binding")},
        "manual": ({"scope": scope.get("binding"), "source": source.get("binding"),
                    "body": digest((body.get("manual") or {}).get("blocks"))}
                   if body.get("manual") else {}),
        "form": {"scope": scope.get("binding"), "source": source.get("binding")},
        "worksheet": {"input": (body.get("worksheet") or {}).get("input_binding")},
        "screenshots": {"software_id": digest(metadata.get("software_id")),
                        "version": digest(metadata.get("version"))},
    }


def _preparation_changes(previous: dict | None, body: dict) -> list:
    if previous is None:
        return []
    old_deps, new_deps = _preparation_dependencies(previous), body["dependencies"]
    changes = []
    for name in ("scope", "rights", "source", "manual", "form", "consistency", "worksheet", "screenshots"):
        if name == "screenshots":
            before = (previous.get("manual") or {}).get("screenshots", [])
            after = (body.get("manual") or {}).get("screenshots", [])
        else:
            before, after = previous.get(name), body.get(name)
        old_binding = (before.get("binding", digest(before)) if isinstance(before, dict)
                       else digest(before)) if before is not None else None
        new_binding = (after.get("binding", digest(after)) if isinstance(after, dict)
                       else digest(after)) if after is not None else None
        dependencies = sorted(key for key in set(old_deps.get(name, {})) | set(new_deps.get(name, {}))
                              if old_deps.get(name, {}).get(key) != new_deps.get(name, {}).get(key))
        # 没有截图不能产生“截图失效”；已有截图则单独核同版记录。
        if name == "screenshots" and not before and not after:
            continue
        if old_binding != new_binding or dependencies:
            changes.append({"artifact": name, "before_binding": old_binding,
                            "after_binding": new_binding, "changed_dependencies": dependencies,
                            "status": ("created" if before is None else "removed" if after is None
                                       else "changed" if old_binding != new_binding else "dependency_changed")})
    return changes


def prepare(payload: dict, *, use_system_time: bool = False) -> dict:
    """编排SW-01/07/02/04/05，返回SW-02内部准备信封，不引入新的能力ID。

    必填context、authorized_root、scope_input、rights、files、inventory_complete、
    pagination；可选manual_input、form、form_rule_evidence、field_limits、
    field_candidates、confirmations和previous_preparation（先前信封的artifacts）。
    候选严格为{field, value, status, sources}；field限FIELD_NAMES可选目录，status限
    candidate/inferred/conflict/unknown（unknown的value为None）。sources的元素为
    {path, sha256, locator}（已读manifest中的相对路径）或{evidence_id, locator}
    （metadata/form/manual_input已有引用）；定位和引用不证明事实真实性。
    确认严格为{candidate_digest, input_binding, status: confirmed, actor, role,
    evidence_id}，分别绑定digest(candidate)及待审worksheet.input_binding。
    确认只填form，不改scope/rights、计数或facts；冲突、未知和失效确认保留待核。
    返回worksheet、dependencies和局部changes；无候选的原表单值标declared非confirmed。
    源码始终按有据的交存上下文选材，
    并核对分页前的完整母本；不猜测日期、运行事实或许可，也不自动外发或写盘。
    输入只接受这些字段；scope和manual的调用参数不能覆盖编排生成的工件或context。
    缺说明书返回partial，保留已生成的源码与已知字段。全部确定性检查成功仍待专业审阅。
    真实授权入口须以仅关键字use_system_time=True逐阶段、逐文件复核当前许可；
    JSON字段不能设置该参数，默认False保留旧调用和合成测试的显式时间契约。
    """
    required = ("context", "authorized_root", "scope_input", "rights", "files",
                "inventory_complete", "pagination")
    require_fields(payload, required)
    allowed = set(required) | {"manual_input", "form", "form_rule_evidence",
                               "field_limits", "previous_preparation", "field_candidates",
                               "confirmations"}
    require(set(payload) <= allowed, "preparation_input_unknown")
    scope_input = payload["scope_input"]
    require_fields(scope_input, ("metadata", "components"))
    require(set(scope_input) <= {"metadata", "components", "grouping_basis"},
            "preparation_input_unknown")
    manual_input = payload.get("manual_input")
    if manual_input is not None:
        require(isinstance(manual_input, dict), "object_required")
        require(set(manual_input) <= {"mode", "facts", "operations", "runtime_evidence",
                                      "blocks", "document_metadata", "revision"},
                "preparation_input_unknown")
    form = payload.get("form")
    if form is not None:
        require_fields(form, ("name", "version", "total_source_lines", "selected_source_lines"))
    field_limits = payload.get("field_limits", {})
    require(isinstance(field_limits, dict), "field_limits_object_required")
    previous = payload.get("previous_preparation")
    if previous is not None:
        _artifact(previous, "software_preparation")
    candidates, confirmations = _field_inputs(payload)

    context = payload["context"]
    scoped = run("SW-01", {"context": context, "metadata": scope_input["metadata"],
                           "components": scope_input["components"],
                           "grouping_basis": scope_input.get("grouping_basis")},
                 use_system_time=use_system_time)
    scope = scoped["artifacts"]
    entitled = run("SW-07", {"context": context, "scope": scope,
                             "rights": payload["rights"]}, use_system_time=use_system_time)
    rights = entitled["artifacts"]
    selected = run("SW-02", {
        "context": context, "scope": scope, "rights_decisions": rights,
        "authorized_root": payload["authorized_root"], "files": payload["files"],
        "inventory_complete": payload["inventory_complete"],
        "pagination": payload["pagination"], "selection_basis": "deposit_context",
        "selection_purpose": "deposit", "require_complete_source": True,
    }, use_system_time=use_system_time)
    source = selected["artifacts"]
    steps = [scoped, entitled, selected]
    if form is None:
        # None明确保留已核未知状态，不补造日期，也不改变既有表单字段契约。
        form = copy.deepcopy(scope["metadata"])
        for key in ("total_source_lines", "selected_source_lines"):
            form[key] = source[key]
    form, worksheet, field_issues = _field_worksheet(
        payload, scope, source, form, candidates, confirmations)
    manual, consistency = None, None
    if manual_input is not None:
        manual_input = _bound_manual_input(manual_input, previous, scope, source)
        documented = run("SW-04", {
            "context": context, "scope": scope, "mode": manual_input.get("mode"),
            "facts": manual_input.get("facts", []), "operations": manual_input.get("operations", []),
            "runtime_evidence": manual_input.get("runtime_evidence", []),
            **{key: manual_input[key] for key in ("blocks", "document_metadata", "revision")
               if key in manual_input},
        }, use_system_time=use_system_time)
        # 编排所得说明稿还依赖实际源码，SW-04独立调用的契约保持不变。
        manual = _seal({key: value for key, value in documented["artifacts"].items()
                        if key != "binding"} | {"source_binding": source["binding"]})
        checked = run("SW-05", {
            "context": context, "scope": scope, "material": source, "manual": manual,
            "form": form, "form_rule_evidence": payload.get("form_rule_evidence"),
            "field_limits": field_limits,
        }, use_system_time=use_system_time)
        consistency = checked["artifacts"]
        steps.extend((documented, checked))
    issues = [{**issue, "capability": step["capability"]}
              for step in steps for issue in step["issues"]]
    issues.extend({**issue, "capability": "SW-05"} for issue in field_issues)
    if manual is None:
        issues.append({"capability": "SW-04", "code": "manual_input_missing"})
    incomplete = manual is None or bool(field_issues) or any(
        step["status"] in {"partial", "needs_evidence"} for step in steps)
    status = "partial" if incomplete else "needs_review"
    # 当前阻塞随工件交接；历史失效提示只在下方结果信封追加，不参与内容快照。
    body = {"kind": "software_preparation", "scope": scope, "rights": rights,
            "source": source, "manual": manual, "form": form, "consistency": consistency,
            "worksheet": worksheet, "issues": copy.deepcopy(issues)}
    body["dependencies"] = _preparation_dependencies(body)
    changes = _preparation_changes(previous, body)
    artifact = _seal({**body, "changes": changes})
    if previous is not None:
        # 比较当前内容而非历史链；相同内容沿用原快照，避免supersedes自增失效。
        previous_body = {key: value for key, value in previous.items()
                         if key not in {"binding", "supersedes", "invalidated", "changes"}}
        if digest(previous_body) == digest(body):
            artifact = copy.deepcopy(previous)
        else:
            artifact = _seal({**body, "changes": changes, "supersedes": previous["binding"],
                              "invalidated": [previous["binding"]]})
            issues.append({"capability": "SW-02", "code": "previous_preparation_invalidated"})
    return result("SW-02", status=status, artifacts=artifact, issues=issues,
                  adaptation={"jurisdiction": "unverified"},
                  checks=["local_deterministic_preparation", "AC-SW-01", "AC-SW-07",
                          "AC-SW-02"] + (["AC-SW-04", "AC-SW-05"] if manual else []))


HANDLERS = {"SW-01": _scope, "SW-02": _source, "SW-03": _mask, "SW-04": _manual,
            "SW-05": _consistency, "SW-06": _correction, "SW-07": _rights,
            "SW-08": _international}


def run(capability: str, payload: dict, *, use_system_time: bool = False) -> dict:
    """返回共享结果信封；无效结构／权限抛出不含材料正文的ContractError。

    context必须显式提供environment、permissions、sensitivity、purpose和now。
    专业规则未知时仍生成可核对的内部工件，绝不自动提交或提升官方状态。
    工件binding用于变更检测，不是数字签名；调用者须保护输入与快照存储。
    use_system_time=True使用当前UTC时间核验，SW-02还在每次读取前复核；
    该控制仅来自Python关键字，不读取payload里的同名字段。
    """
    require(capability in CAPABILITIES, "unsupported_software_capability")
    _preflight_context(payload, use_system_time=use_system_time)
    try:
        if capability == "SW-02":
            artifacts, issues, status = _source(payload, use_system_time=use_system_time)
        else:
            artifacts, issues, status = HANDLERS[capability](payload)
    except OSError:
        # 文件名、绝对路径也可能敏感，不向CLI异常链复制底层错误文本。
        raise ContractError("software_filesystem_unavailable") from None
    return result(capability, status=status, artifacts=artifacts, issues=issues,
                  adaptation=payload.get("adaptation", {"jurisdiction": "unverified"}),
                  checks=["local_deterministic_preparation", f"AC-{capability}"])
