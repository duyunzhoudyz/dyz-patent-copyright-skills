"""标准闭环v2的纯JSON契约；不读取文件，不认证决定权限或专业正确性。"""

from __future__ import annotations

import copy
import re
from collections import Counter

from tools.core import ContractError, canonical_bytes, digest, require, require_fields

OUTCOMES = ("accepted", "partially_accepted", "rejected", "pending")
CLASSIFICATIONS = ("technical", "editorial", "procedural", "ip", "insufficient_evidence")
IMPACT_FIELDS = ("verification", "references", "compilation_note", "downstream_products")
BLOCKS = ("submission", "approval", "publication", "none")
ASSESSMENT_VERSION = "standards-consistency/1"
CONTENT_BINDING_VERSION = "comment-content/2"


def contract_version(payload: dict) -> int:
    """缺省只选择v1；bool和浮点数不能冒充整数契约版本。"""
    require(isinstance(payload, dict), "object_required")
    version = payload.get("contract_version", 1)
    require(type(version) is int and version in (1, 2),
            "unsupported_standard_contract_version")
    return version


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _texts(value, *, nonempty=False) -> bool:
    return (isinstance(value, list) and (bool(value) or not nonempty)
            and all(_text(item) for item in value))


def _optional_strings(record, fields, scope):
    # 缺证或空串仍交业务层生成issue；已提供但类型错误不能伪装成缺证。
    for field in fields:
        if field in record:
            require(isinstance(record[field], str), f"{scope}_string_required:{field}")


def _records(value, fields=()) -> list[dict]:
    require(isinstance(value, list), "records_list_required")
    for row in value:
        require(isinstance(row, dict), "record_object_required")
        for field in fields:
            require(_text(row.get(field)), f"string_required:{field}")
    return value


def _issue(issues, code, record_id="", **details):
    issues.append({"code": code, "record_id": record_id, **details})


def _clause_map(rows, validator, issues, scope):
    rows = _records(rows, ("id", "text"))
    require(len({row["id"] for row in rows}) == len(rows), "duplicate_clause_id")
    for row in rows:
        try:
            validator([row])
        except ContractError as error:
            # 缺语义字段仍可留作内部草稿，但不能跳过原STD条款契约而就绪。
            _issue(issues, "clause_semantics_incomplete_or_invalid", row["id"],
                   scope=scope, detail=str(error))
    return {row["id"]: row for row in rows}


def _open_item(row, fallback_id=None, source_ref=None):
    require(isinstance(row, dict), "open_item_object_required")
    require(all(_text(row.get(key)) for key in
                ("question", "owner", "blocks", "recovery")), "pending_item_unowned")
    require(row["blocks"] in BLOCKS, "open_item_blocks_unknown")
    item = copy.deepcopy(row)
    if "id" not in item and fallback_id:
        item["id"] = fallback_id
    require(_text(item.get("id")), "open_item_id_required")
    refs = item.get("source_refs", [])
    require(_texts(refs), "open_item_source_refs_required")
    refs = sorted(set(refs + ([source_ref] if source_ref else [])))
    require(bool(refs), "open_item_source_refs_required")
    item["source_refs"] = refs
    return item


def _merge_open_items(items, issues):
    merged = {}
    for item in items:
        previous = merged.get(item["id"])
        if previous is None:
            merged[item["id"]] = copy.deepcopy(item)
            continue
        fields = ("question", "owner", "blocks", "recovery")
        if any(item[key] != previous[key] for key in fields):
            _issue(issues, "open_item_conflict", item["id"], conflicting_item=item)
        previous["source_refs"] = sorted(set(previous["source_refs"] + item["source_refs"]))
    return [merged[key] for key in sorted(merged)]


def _changes(row):
    require(_texts(row.get("no_change_targets", [])), "no_change_targets_required")
    require(row.get("no_change_scope") in (None, "document"), "no_change_scope_unknown")
    changes = row.get("changes", [])
    _records(changes, ("operation", "clause_id"))
    if "clause_id" in row or "proposed_text" in row:
        require(_text(row.get("clause_id")) and _text(row.get("proposed_text")),
                "accepted_text_unresolved")
        require(not changes, "comment_change_forms_conflict")
        changes = [{"operation": "replace", "clause_id": row["clause_id"],
                    "proposed_text": row["proposed_text"]}]
    if "no_change" in row:
        require(type(row["no_change"]) is bool, "comment_no_change_boolean_required")
    require(not (changes and row.get("no_change") is True), "comment_change_forms_conflict")
    if row["outcome"] in ("accepted", "partially_accepted"):
        require(bool(changes) or row.get("no_change") is True, "accepted_text_unresolved")
        if row.get("no_change") is True:
            require(_text(row.get("reason_source")), "no_change_reason_unsourced")
    else:
        require(not changes and row.get("no_change") is not True,
                "nonaccepted_comment_change_forbidden")
    require(len({c["clause_id"] for c in changes}) == len(changes),
            "duplicate_comment_change_target")
    for change in changes:
        require(change["operation"] in ("replace", "add", "delete"), "comment_change_operation_unknown")
        if "dependency_resolution" in change:
            dependency = change["dependency_resolution"]
            require(isinstance(dependency, dict), "dependency_resolution_object_required")
            _optional_strings(dependency, ("status", "source", "reason"), "dependency_resolution")
        if change["operation"] == "delete":
            require(change.get("proposed_text", "") == "", "delete_proposed_text_must_be_empty")
        else:
            require(_text(change.get("proposed_text")), "accepted_text_unresolved")
    return changes


def _check_changes(cid, changes, old, new, issues, proposals):
    for change in changes:
        key, operation = change["clause_id"], change["operation"]
        proposals.setdefault(key, []).append((cid, operation, change.get("proposed_text", "")))
        if operation == "replace":
            valid = key in old and key in new
        elif operation == "add":
            valid = key not in old and key in new
        else:
            valid = key in old and key not in new
            dependency = change.get("dependency_resolution", {})
            require(isinstance(dependency, dict), "dependency_resolution_object_required")
            resolved = (dependency.get("status") == "resolved" and _text(dependency.get("source")))
            not_applicable = (dependency.get("status") == "not_applicable"
                              and _text(dependency.get("reason")))
            if not (resolved or not_applicable):
                _issue(issues, "deleted_clause_dependencies_unresolved", cid, clause_id=key)
            for clause in new.values():
                if key in clause.get("references", []):
                    _issue(issues, "deleted_clause_reference_retained", cid,
                           clause_id=key, referring_clause_id=clause["id"])
        if not valid:
            _issue(issues, "comment_change_target_invalid", cid, clause_id=key, operation=operation)
        elif operation != "delete" and new[key]["text"] != change["proposed_text"]:
            # 此处只比结构化正文，不声称实际Word已落地；实物证明另行绑定。
            _issue(issues, "comment_change_not_applied", cid, clause_id=key)


def _check_no_change(row, comment, old, new, issues, semantic_fields):
    cid = row["comment_id"]
    targets = row.get("no_change_targets", [])
    scope = row.get("no_change_scope")
    require(_texts(targets), "no_change_targets_required")
    require(scope in (None, "document"), "no_change_scope_unknown")
    require(not (targets and scope), "no_change_scope_conflict")
    if not targets and scope is None:
        if comment.get("scope") == "document":
            scope = "document"
        elif _text(comment.get("clause_id")):
            targets = [comment["clause_id"]]
    check = {"comment_id": cid, "clause_ids": [], "structure_status": "unresolved",
             "reason_source": row["reason_source"], "implementation_verification": "not_performed"}
    if not targets and scope is None:
        _issue(issues, "no_change_scope_missing", cid)
        return check
    if scope == "document":
        targets = sorted(set(old) | set(new))
    check["clause_ids"] = sorted(set(targets))
    issue_count = len(issues)
    for key in check["clause_ids"]:
        if key not in old or key not in new:
            _issue(issues, "no_change_target_missing", cid, clause_id=key)
        elif any(old[key].get(field) != new[key].get(field) for field in semantic_fields):
            _issue(issues, "no_change_target_changed", cid, clause_id=key)
    if len(issues) == issue_count and check["clause_ids"]:
        check["structure_status"] = "matched"
    return check


def _dated_reference(value):
    match = re.fullmatch(r"(.+?)[\-:：—–](\d{4})", value)
    return (match.group(1), match.group(2)) if match else (value, None)


def _reference_registry(payload, clauses):
    legacy = payload.get("external_reference_ids", [])
    require(_texts(legacy), "external_reference_ids_list_required")
    require(len(set(legacy)) == len(legacy), "duplicate_external_reference_id")
    external = _records(payload.get("external_references", []),
                        ("id", "identifier", "edition", "title", "source"))
    require(len({row["id"] for row in external}) == len(external), "duplicate_external_reference_id")
    identities = [(_dated_reference(row["identifier"])[0], row["edition"]) for row in external]
    require(len(set(identities)) == len(identities), "duplicate_external_reference_identity")
    for row in external:
        if "citation_ids" in row:
            require(_texts(row["citation_ids"]), "external_reference_citation_ids_required")
    by_id = {row["id"]: row for row in external}
    bindings = {}
    for row in _records(payload.get("reference_bindings", []),
                        ("clause_id", "reference", "kind", "target_id")):
        key = row["clause_id"], row["reference"]
        require(key not in bindings, "duplicate_reference_binding")
        require(row["clause_id"] in clauses, "reference_binding_clause_missing")
        require(_texts(clauses[row["clause_id"]].get("references", [])), "list_required:references")
        require(row["reference"] in clauses[row["clause_id"]].get("references", []),
                "reference_binding_reference_missing")
        require(row["kind"] in ("internal", "external"), "reference_binding_kind_unknown")
        targets = clauses if row["kind"] == "internal" else set(by_id) | set(legacy)
        require(row["target_id"] in targets, "reference_binding_target_missing")
        bindings[key] = row
    return {"external": by_id, "legacy": set(legacy) - set(by_id), "bindings": bindings}


def _external_identity_state(reference, row):
    identifier, identifier_year = _dated_reference(row["identifier"])
    raw_identifier, raw_year = _dated_reference(reference)
    if identifier_year is not None and identifier_year != row["edition"]:
        return "version_mismatch"
    if reference == row["id"]:
        return "resolved"
    if raw_identifier != identifier:
        return "identity_mismatch"
    if raw_year is not None and raw_year != row["edition"]:
        return "version_mismatch"
    return "resolved"


def _resolve_reference(clause_id, reference, clauses, registry):
    """仅按记录精确匹配；题录可定位不等于全文、版次适用性或现行性已核。"""
    external, legacy = registry["external"], registry["legacy"]
    explicit = registry["bindings"].get((clause_id, reference))
    candidates = []
    if explicit:
        candidates = [(explicit["kind"], explicit["target_id"])]
    else:
        if reference in clauses:
            candidates.append(("internal", reference))
        if reference in legacy:
            candidates.append(("external", reference))
        for row in external.values():
            base, _ = _dated_reference(row["identifier"])
            aliases = {row["id"], row["identifier"], base,
                       base + "-" + row["edition"], base + ":" + row["edition"],
                       base + "：" + row["edition"]}
            if reference in aliases:
                candidates.append(("external", row["id"]))
    check = {"clause_id": clause_id, "reference": reference, "kind": None,
             "target_id": None, "identity": None, "status": "unresolved", "issue": None}
    if len(candidates) > 1:
        check.update(status="ambiguous", candidates=[{"kind": kind, "target_id": key}
                                                     for kind, key in candidates])
    elif candidates:
        kind, key = candidates[0]
        check.update(kind=kind, target_id=key)
        if kind == "internal":
            check.update(identity={"id": key}, status="resolved" if key in clauses else "unresolved")
        elif key in external:
            check.update(identity=copy.deepcopy(external[key]),
                         status=_external_identity_state(reference, external[key]))
        else:
            check.update(identity={"id": key}, status="registered_only")
    else:
        base, year = _dated_reference(reference)
        editions = [row for row in external.values() if _dated_reference(row["identifier"])[0] == base]
        if year and editions:
            check.update(kind="external", status="version_mismatch",
                         candidates=[{"kind": "external", "target_id": row["id"],
                                      "identity": copy.deepcopy(row)} for row in editions])
    code = {"unresolved": "unresolved_clause_reference", "ambiguous": "ambiguous_clause_reference",
            "version_mismatch": "clause_reference_version_mismatch",
            "identity_mismatch": "clause_reference_identity_mismatch",
            "registered_only": "external_reference_identity_missing"}.get(check["status"])
    if code:
        check["issue"] = {"code": code, "record_id": clause_id, "target": reference}
    return check


def _reference_checks(clauses, registry, issues):
    checks = []
    for clause in clauses.values():
        references = clause.get("references", [])
        require(_texts(references), "list_required:references")
        for reference in references:
            check = _resolve_reference(clause["id"], reference, clauses, registry)
            checks.append(check)
            if check["issue"]:
                issues.append(copy.deepcopy(check["issue"]))
    return checks


def _binding_shape(binding):
    require(isinstance(binding, dict), "comment_content_binding_object_required")
    fields = {"binding_version", "comment_hash", "baseline_scope", "baseline_scope_hash", "decision_hash"}
    require(set(binding) == fields and _text(binding.get("binding_version")),
            "comment_content_binding_fields_required")
    for field in ("comment_hash", "baseline_scope_hash", "decision_hash"):
        require(isinstance(binding[field], str) and re.fullmatch(r"[0-9a-f]{64}", binding[field]) is not None,
                "comment_content_binding_hash_invalid:" + field)
    scope = binding["baseline_scope"]
    require(isinstance(scope, dict) and set(scope) == {"kind", "clause_ids"},
            "comment_baseline_scope_fields_required")
    require(scope["kind"] in ("targets", "document") and _texts(scope["clause_ids"])
            and len(set(scope["clause_ids"])) == len(scope["clause_ids"]),
            "comment_baseline_scope_invalid")
    require(scope["kind"] != "targets" or bool(scope["clause_ids"]), "comment_baseline_scope_invalid")


def _confirmation_shape(confirmation, *, history=False):
    require(isinstance(confirmation, dict), "confirmation_history_record_invalid" if history
            else "comment_confirmation_object_required")
    if history:
        require(bool(confirmation) and set(confirmation) <= {*_CONFIRMATION_FIELDS, "content_binding"},
                "confirmation_history_record_invalid")
    _optional_strings(confirmation, _CONFIRMATION_FIELDS, "comment_confirmation")
    if "content_binding" in confirmation:
        _binding_shape(confirmation["content_binding"])


def _confirmation_history(row):
    history = row.get("confirmation_history", [])
    require(isinstance(history, list), "comment_confirmation_history_list_required")
    for confirmation in history:
        _confirmation_shape(confirmation, history=True)
    return history


def _confirmation_source_dependencies(payload, comment_id, clause_ids, external_ids, *, document_scope):
    """仅绑定完整声明及预期hash；报告和原件实际字节由来源拥有层另核。"""
    bindings = _records(payload.get("source_bindings", []),
                        ("binding_id", "target_type", "target_id", "report_id", "proposition", "version"))
    reports = _records(payload.get("source_reports", []), ("report_id", "path", "sha256"))
    if document_scope:
        # 全文或未解析引用无法证明来源无关，连未绑定的报告声明也保守纳入。
        selected_bindings, selected_reports = bindings, reports
    else:
        clauses = payload.get("baseline_clauses", []) + payload.get("clauses", [])
        method_ids = set()
        for clause in clauses:
            if clause["id"] in clause_ids:
                methods = clause.get("method_ids", [])
                require(_texts(methods), "list_required:method_ids")
                method_ids.update(methods)
        verification = _records(payload.get("verification_matrix", []), ("id", "clause_id"))
        verification_ids = {row["id"] for row in verification
                            if row["clause_id"] in clause_ids or row["id"] in method_ids}
        note = payload.get("compilation_note", {})
        require(isinstance(note, dict), "compilation_note_object_required")
        section_ids = {row["id"] for row in _records(note.get("sections", []), ("id",))}
        comment_ids = {row["id"] for row in _records(payload.get("comments", []), ("id",))}
        known_external_ids = set(payload.get("external_reference_ids", [])) | {
            row["id"] for row in payload.get("external_references", [])}
        known = {"clause": {row["id"] for row in clauses},
                 "comment": comment_ids, "comment_reason": comment_ids,
                 "verification": {row["id"] for row in verification},
                 "verification_basis": {row["id"] for row in verification},
                 "compilation_note": section_ids, "note_section": section_ids,
                 "external_reference": known_external_ids}
        related = {"clause": clause_ids, "comment": {comment_id}, "comment_reason": {comment_id},
                   "verification": verification_ids, "verification_basis": verification_ids,
                   "compilation_note": section_ids, "note_section": section_ids,
                   "external_reference": external_ids}
        # 说明节没有局部目标契约，按共享文档依据处理；不采信impact或自报绑定范围来删依赖。
        # 无法定位的来源目标也不能证明无关，保留其声明供拥有层诊断。
        selected_bindings = [row for row in bindings
                             if row["target_type"] not in known
                             or row["target_id"] not in known[row["target_type"]]
                             or row["target_id"] in related[row["target_type"]]]
        report_ids = {row["report_id"] for row in selected_bindings}
        selected_reports = [row for row in reports if row["report_id"] in report_ids]
    # 不以ID字典覆盖重复声明；同一来源的扩展字段和全部报告声明都属于确认内容。
    return {"source_bindings": sorted(copy.deepcopy(selected_bindings), key=canonical_bytes),
            "source_reports": sorted(copy.deepcopy(selected_reports), key=canonical_bytes)}


def _content_binding(payload, outcome, comment, old, new, registry):
    changes = _changes(outcome)
    targets = {change["clause_id"] for change in changes} | set(outcome.get("no_change_targets", []))
    if _text(comment.get("clause_id")):
        targets.add(comment["clause_id"])
    document_scope = (bool(comment.get("scope")) or outcome.get("no_change_scope") == "document"
                      or not targets)
    graph = {key: set() for key in set(old) | set(new) | targets}
    dependency_rows = []
    for name, clauses in (("baseline", old), ("current", new)):
        for clause in clauses.values():
            references = clause.get("references", [])
            require(_texts(references), "list_required:references")
            for reference in references:
                check = _resolve_reference(clause["id"], reference, clauses, registry)
                dependency_rows.append({"scope": name, **check})
                if check["kind"] == "internal" and check["status"] == "resolved":
                    other = check["target_id"]
                    graph[clause["id"]].add(other)
                    graph[other].add(clause["id"])
                elif check["status"] in ("unresolved", "ambiguous", "version_mismatch", "identity_mismatch"):
                    # 未解析的边无法证明与当前决定无关，不能让调用者用局部目标缩小绑定。
                    document_scope = True
    selected = set(graph) if document_scope else set(targets)
    pending = list(selected)
    while pending:
        for target in graph[pending.pop()] - selected:
            selected.add(target)
            pending.append(target)
    scope = {"kind": "document" if document_scope else "targets", "clause_ids": sorted(selected)}
    dependencies = [row for row in dependency_rows if row["clause_id"] in selected]
    dependencies.sort(key=lambda row: (row["scope"], row["clause_id"]))
    bindings = [copy.deepcopy(row) for key, row in sorted(registry["bindings"].items()) if key[0] in selected]
    external_ids = {row["target_id"] for row in dependencies if row["kind"] == "external" and row["target_id"]}
    external_ids.update(candidate["target_id"] for row in dependencies for candidate in row.get("candidates", [])
                        if candidate["kind"] == "external")
    sources = _confirmation_source_dependencies(payload, comment["id"], selected, external_ids,
                                                document_scope=document_scope)
    baseline = {"project_id": payload.get("project_id"), "baseline_version": payload.get("baseline_version"),
                "adaptation": payload.get("adaptation"), "baseline_scope": scope,
                "clauses": [{"clause_id": key, "record": old[key]} if key in old else
                            {"clause_id": key, "missing": True} for key in sorted(selected)],
                "reference_dependencies": dependencies, "reference_bindings": bindings, **sources}
    decision = {key: value for key, value in outcome.items()
                if key not in ("confirmation", "confirmation_history")}
    return {"binding_version": CONTENT_BINDING_VERSION, "comment_hash": digest(comment),
            "baseline_scope": scope, "baseline_scope_hash": digest(baseline), "decision_hash": digest(decision)}


def comment_content_binding(payload: dict, outcome: dict) -> dict:
    """重算完整意见／决定及系统推导基线依赖；不修改或确认任何记录。"""
    require(contract_version(payload) == 2, "closed_loop_requires_contract_v2")
    require_fields(payload, ("project_id", "baseline_version", "adaptation"))
    _records([outcome], ("comment_id", "outcome", "classification", "reason", "decision_status", "major_change"))
    require(outcome["outcome"] in OUTCOMES, "comment_outcome_unknown")
    require(outcome["classification"] in CLASSIFICATIONS, "comment_classification_unknown")
    require(outcome["major_change"] in ("yes", "no", "undetermined"), "comment_major_change_unknown")
    require(outcome["decision_status"] in ("proposed", "confirmed"), "comment_decision_status_unknown")
    canonical_bytes(payload)
    canonical_bytes(outcome)
    comments = _records(payload.get("comments", []), ("id",))
    matching = [row for row in comments if row["id"] == outcome["comment_id"]]
    require(len(matching) == 1, "comment_binding_original_not_unique")
    old_rows = _records(payload.get("baseline_clauses", []), ("id", "text"))
    new_rows = _records(payload.get("clauses", []), ("id", "text"))
    require(len({row["id"] for row in old_rows}) == len(old_rows)
            and len({row["id"] for row in new_rows}) == len(new_rows), "duplicate_clause_id")
    old, new = ({row["id"]: row for row in rows} for rows in (old_rows, new_rows))
    return _content_binding(payload, outcome, matching[0], old, new, _reference_registry(payload, new))


def confirm_comment(payload: dict, comment_id: str, confirmation: dict) -> dict:
    """显式记录本次确认到新payload，保留旧确认；hash不认证角色、权限或专业判断。"""
    require(contract_version(payload) == 2, "closed_loop_requires_contract_v2")
    require(_text(comment_id), "comment_id_required")
    canonical_bytes(payload)
    canonical_bytes(confirmation)
    _confirmation_shape(confirmation)
    require(all(_text(confirmation.get(field)) for field in _CONFIRMATION_FIELDS),
            "comment_confirmation_evidence_required")
    comments = _records(payload.get("comments", []), ("id", "text", "source", "participant_id", "version"))
    originals = [row for row in comments if row["id"] == comment_id]
    outcomes = _records(payload.get("comment_outcomes", []),
                       ("comment_id", "outcome", "classification", "reason", "decision_status", "major_change"))
    positions = [index for index, row in enumerate(outcomes) if row["comment_id"] == comment_id]
    require(len(originals) == 1 and len(positions) == 1, "comment_confirmation_target_not_unique")
    require(_text(payload.get("baseline_version"))
            and confirmation["baseline_version"] == payload["baseline_version"]
            and originals[0]["version"] == payload["baseline_version"],
            "comment_confirmation_baseline_mismatch")
    data = copy.deepcopy(payload)
    row = data["comment_outcomes"][positions[0]]
    history = _confirmation_history(row)
    if row.get("confirmation"):
        _confirmation_shape(row["confirmation"], history=True)
        history = history + [copy.deepcopy(row["confirmation"])]
    if history:
        row["confirmation_history"] = history
    row["decision_status"] = "confirmed"
    row["decision_version"] = confirmation["version"]
    row["confirmation"] = copy.deepcopy(confirmation)
    row["confirmation"]["content_binding"] = comment_content_binding(data, row)
    return data


def _confirmation_check(payload, row, comments, old, new, registry, issues):
    cid, confirmation = row["comment_id"], row.get("confirmation", {})
    check = {"comment_id": cid, "status": "unconfirmed", "content_binding": confirmation.get("content_binding"),
             "expected_content_binding": None}
    originals = [comment for comment in comments if comment["id"] == cid]
    if len(originals) == 1:
        check["expected_content_binding"] = _content_binding(payload, row, originals[0], old, new, registry)
    if row["decision_status"] != "confirmed":
        return check
    if "content_binding" not in confirmation:
        check["status"] = "unbound"
        _issue(issues, "comment_decision_content_binding_unbound", cid)
    elif (check["expected_content_binding"] != confirmation["content_binding"]
          or confirmation.get("version") != row.get("decision_version")
          or confirmation.get("baseline_version") != payload.get("baseline_version")
          or any(comment["version"] != payload.get("baseline_version") for comment in originals)):
        check["status"] = "stale"
        _issue(issues, "comment_decision_content_binding_stale", cid)
    else:
        check["status"] = "current"
    return check


def _profile(payload, section_ids):
    default = {"id": "internal-eleven", "version": "1", "scope": "internal",
               "required_sections": list(section_ids)}
    profile = payload.get("profile", default)
    require_fields(profile, ("id", "version", "scope", "required_sections"))
    require(all(_text(profile[key]) for key in ("id", "version", "scope")), "profile_identity_required")
    _optional_strings(profile, ("source",), "profile")
    if "section_semantics" in profile:
        require(isinstance(profile["section_semantics"], dict), "profile_section_semantics_required")
    required = profile["required_sections"]
    require(_texts(required, nonempty=True) or required == [], "profile_sections_required")
    require(profile["scope"] in ("internal", "organization"), "profile_scope_unknown")
    if profile["scope"] == "internal":
        require(required == list(section_ids), "internal_profile_sections_invalid")
    else:
        require(bool(required) and len(set(required)) == len(required), "profile_sections_required")
        require(_text(profile.get("source")), "organization_profile_source_required")
        semantics = profile.get("section_semantics", {})
        require(isinstance(semantics, dict), "profile_section_semantics_required")
        require(set(semantics) == set(required)
                and all(_text(value) and value in section_ids for value in semantics.values()),
                "profile_section_semantics_required")
    return profile


def _verification(payload, clauses, issues):
    matrix = _records(payload.get("verification_matrix", []), ("id", "clause_id", "source"))
    counts = {"total": len(matrix), "planned": len(matrix), "executed": 0,
              "results": 0, "reviewed": 0, "not_applicable": 0}
    ids = Counter(row["id"] for row in matrix)
    if not matrix:
        _issue(issues, "verification_matrix_missing")
    for key, count in ids.items():
        if count > 1:
            _issue(issues, "duplicate_verification_id", key)
    bound = {}
    for row in matrix:
        _optional_strings(row, ("clause_hash", "method", "reason", "applicability_source",
                                "execution_evidence", "result_evidence", "review_evidence"),
                          "verification")
        key = row["id"]
        clause = clauses.get(row["clause_id"])
        state = row.get("status", "planned")
        require(state in ("planned", "performed", "reviewed", "not_applicable"),
                "verification_status_unknown")
        if clause is None or row.get("clause_hash") != digest(clause):
            _issue(issues, "verification_binding_missing_or_stale", key)
            continue
        if ids[key] != 1:
            continue
        bound.setdefault(row["clause_id"], []).append(row)
        if not _text(row.get("method")):
            _issue(issues, "verification_method_missing", key)
        if state == "not_applicable":
            if not (_text(row.get("reason")) and _text(row.get("applicability_source"))):
                _issue(issues, "verification_not_applicable_unreasoned", key)
            else:
                counts["not_applicable"] += 1
            continue
        execution = _text(row.get("execution_evidence"))
        result = _text(row.get("result_evidence"))
        review = _text(row.get("review_evidence"))
        counts["executed"] += execution
        counts["results"] += result
        counts["reviewed"] += review
        if state == "planned":
            _issue(issues, "verification_not_performed", key)
        if not execution:
            _issue(issues, "verification_execution_missing", key)
        if not result:
            _issue(issues, "verification_result_missing", key)
        if state == "reviewed" and not review:
            _issue(issues, "verification_review_missing", key)
    for key, clause in clauses.items():
        if clause.get("strength") != "requirement":
            continue
        rows = bound.get(key, [])
        if not rows:
            _issue(issues, "required_verification_missing", key)
        methods = clause.get("method_ids", [])
        if not methods:
            _issue(issues, "verification_method_missing", key)
        elif _texts(methods):
            for method_id in methods:
                if method_id not in {row["id"] for row in rows}:
                    _issue(issues, "declared_verification_method_missing", key, method_id=method_id)
    counts["status"] = "records_supplied_unverified" if matrix else "not_provided"
    counts["conformity"] = "not_determined"
    return counts


def _note(payload, profile, clause_digest, issues, open_items, section_ids):
    note = payload.get("compilation_note", {})
    require(isinstance(note, dict), "compilation_note_object_required")
    if not note:
        _issue(issues, "compilation_note_structure_missing")
        return note, []
    fields = ("standard_name", "version", "clause_digest", "profile_id", "profile_hash")
    _optional_strings(note, fields, "compilation_note")
    for key in fields:
        if not _text(note.get(key)):
            _issue(issues, "compilation_note_field_missing", key)
    if note.get("version") != payload["version"]:
        _issue(issues, "compilation_note_version_mismatch")
    if note.get("clause_digest") != clause_digest:
        _issue(issues, "compilation_note_stale")
    if (note.get("profile_id") != profile["id"]
            or note.get("profile_hash") != digest(profile)):
        _issue(issues, "compilation_note_profile_mismatch")
    if payload.get("standard_name") and note.get("standard_name") != payload["standard_name"]:
        _issue(issues, "compilation_note_standard_name_mismatch")
    sections = _records(note.get("sections", []), ("id", "heading", "state", "owner"))
    seen = Counter(section["id"] for section in sections)
    required = profile["required_sections"]
    for key in required:
        if key not in seen:
            _issue(issues, "compilation_note_section_missing", key)
    for key, count in seen.items():
        if count > 1:
            _issue(issues, "compilation_note_section_duplicate", key)
        if key not in required:
            _issue(issues, "compilation_note_section_unknown", key)
    for section in sections:
        _optional_strings(section, ("body", "inference_basis", "reason", "question", "recovery"),
                          "compilation_note")
        if "review_required" in section:
            require(type(section["review_required"]) is bool, "compilation_note_review_boolean_required")
        if "blocks" in section:
            require(section["blocks"] in BLOCKS, "open_item_blocks_unknown")
        key, state = section["id"], section["state"]
        require(state in ("explicit", "inferred", "unknown", "not_applicable"),
                "compilation_note_state_unknown")
        if not _text(section.get("body")):
            _issue(issues, "compilation_note_body_missing", key)
        if "source" in section:
            require(_texts(section["source"]), "compilation_note_source_list_required")
        if state == "explicit" and not _texts(section.get("source"), nonempty=True):
            _issue(issues, "compilation_note_source_missing", key)
        if state == "inferred":
            if not (_texts(section.get("source"), nonempty=True)
                    and _text(section.get("inference_basis"))
                    and section.get("review_required") is True):
                _issue(issues, "compilation_note_inference_unreviewed", key)
            _issue(issues, "compilation_note_inference_review_required", key)
        if state == "not_applicable" and not _text(section.get("reason")):
            _issue(issues, "compilation_note_not_applicable_unreasoned", key)
        semantic = profile.get("section_semantics", {}).get(key, key)
        if state == "unknown":
            valid = all(_text(section.get(k)) for k in ("question", "owner", "recovery"))
            valid = valid and section.get("blocks") in BLOCKS
            _issue(issues, "compilation_note_unknown" if valid else "compilation_note_state_unowned", key)
            if valid:
                item = {k: section[k] for k in ("question", "owner", "blocks", "recovery")}
                open_items.append(_open_item(item, f"note:{key}", f"note:{key}"))
        if semantic != section_ids[10]:
            for item in _records(section.get("open_items", [])):
                open_items.append(_open_item(item, source_ref=f"note:{key}"))
    return note, sections


_DISPOSITION_SCHEMA = "dyz/standards/comment-disposition/v{}"
_V1_HEADER_TEXT = ("standard_name", "standard_number", "draft_version", "version_date",
                   "consultation_window", "compiled_by", "compiled_date", "reviewed_by")
_ORIGIN_FIELDS = ("organization", "representative_scope", "participant_id")
_PENDING_FIELDS = ("question", "owner", "blocks", "recovery")
_CONFIRMATION_FIELDS = ("actor", "authority_evidence", "source", "version", "baseline_version")


def _pointer(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _migration_leaves(value, path=""):
    """空容器也计入映射/损失；JSON Pointer用于定位，不以字段名模糊汇总。"""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            require(isinstance(key, str), "migration_json_key_required")
            yield from _migration_leaves(item, _pointer(path, key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _migration_leaves(item, _pointer(path, index))
    else:
        require(value is None or type(value) in (str, int, float, bool, dict, list),
                "migration_json_value_required")
        yield path, value


def _migration_strings(record, path, fields):
    require(isinstance(record, dict), "migration_object_required:" + path)
    for field in fields:
        if field in record:
            require(isinstance(record[field], str), "migration_string_required:" + _pointer(path, field))


def _migration_enum(record, field, values, path):
    if field in record:
        require(isinstance(record[field], str) and record[field] in values,
                "migration_enum_unknown:" + _pointer(path, field))


def _migration_issue(issues, code, source_path, target_path, record_id="", **details):
    issues.append({"code": code, "source_path": source_path, "target_path": target_path,
                   "record_id": record_id, **details})


def _migration_identity(version):
    return {"contract_version": version, "schema_id": _DISPOSITION_SCHEMA.format(version)}


def _migration_boundary(value, version):
    require(isinstance(value, dict), "migration_object_required")
    require(contract_version(value) == version, "migration_source_version_mismatch")
    for field in ("$id", "schema_id"):
        if field in value:
            require(value[field] == _DISPOSITION_SCHEMA.format(version), "migration_schema_version_unknown")
    canonical_bytes(value)
    return list(_migration_leaves(value))


def _legacy_shape(table):
    """只核本转换支持的特定形状；缺证交报告，不宣称通用schema校验。"""
    require_fields(table, ("header", "items", "summary"))
    header, rows, summary = table["header"], table["items"], table["summary"]
    _migration_strings(header, "/header", _V1_HEADER_TEXT)
    require(isinstance(rows, list) and bool(rows), "v1_items_nonempty_list_required")
    require(isinstance(summary, dict), "migration_object_required:/summary")
    for field in ("total_received", "sent_count", "received_count"):
        if field in header:
            value = header[field]
            require((type(value) is int and value >= 0)
                    or (field != "total_received" and value == "record_unavailable"),
                    "migration_count_required:/header/" + field)
    for field in ("total", *OUTCOMES, "clauses_touched", "substantive_changes", "major_changes"):
        if field in summary:
            require(type(summary[field]) is int and summary[field] >= 0,
                    "migration_count_required:/summary/" + field)
    if "by_classification" in summary:
        counts = summary["by_classification"]
        require(isinstance(counts, dict), "migration_object_required:/summary/by_classification")
        require(all(type(value) is int and value >= 0 for value in counts.values()),
                "migration_count_required:/summary/by_classification")
    seqs = set()
    for index, row in enumerate(rows):
        path = f"/items/{index}"
        _migration_strings(row, path, ("clause_id", "text", "reason", "reason_source", "proposed_text",
                                      "accepted_part", "rejected_part", "rejected_reason", "decision_version"))
        seq = row.get("seq")
        require(type(seq) is int and seq > 0, "migration_positive_seq_required:" + path)
        require(seq not in seqs, "migration_duplicate_seq")
        seqs.add(seq)
        if "origin" in row:
            _migration_strings(row["origin"], path + "/origin", _ORIGIN_FIELDS)
        for field, values in (("outcome", OUTCOMES), ("classification", CLASSIFICATIONS),
                              ("major_change", ("yes", "no", "undetermined")),
                              ("decision_status", ("proposed", "confirmed")),
                              ("operation", ("replace", "add", "delete"))):
            _migration_enum(row, field, values, path)
        if "no_change" in row:
            require(type(row["no_change"]) is bool, "migration_boolean_required:" + path + "/no_change")
        if "impact" in row:
            impact = row["impact"]
            require(isinstance(impact, dict), "migration_object_required:" + path + "/impact")
            require(set(impact) <= set(IMPACT_FIELDS), "migration_impact_fields_unknown")
            require(all(type(value) is bool or value in ("unknown", "undetermined")
                        for value in impact.values()), "migration_impact_value_unknown")
        if "confirmation" in row:
            _migration_strings(row["confirmation"], path + "/confirmation", _CONFIRMATION_FIELDS)
        if "unresolved_item" in row:
            pending = row["unresolved_item"]
            require(isinstance(pending, (str, dict)), "migration_pending_shape_required:" + path)
            if isinstance(pending, dict):
                _migration_strings(pending, path + "/unresolved_item", _PENDING_FIELDS)
                _migration_enum(pending, "blocks", BLOCKS, path + "/unresolved_item")
    if "minority_opinions" in table:
        require(isinstance(table["minority_opinions"], list), "migration_minority_list_required")
        for row in table["minority_opinions"]:
            _migration_strings(row, "/minority_opinions", ("text", "retained_basis"))
            require(type(row.get("seq")) is int and row["seq"] > 0, "migration_positive_seq_required:minority")
            if "origin" in row:
                _migration_strings(row["origin"], "/minority_opinions/origin", _ORIGIN_FIELDS)
    if "reconsultation" in table:
        _migration_strings(table["reconsultation"], "/reconsultation", ("required", "basis"))
        _migration_enum(table["reconsultation"], "required",
                        ("yes", "no", "organization_decision_required", "undetermined"), "/reconsultation")


def _migration_tally(rows):
    return {"total": len(rows), **{key: sum(row.get("outcome") == key for row in rows) for key in OUTCOMES},
            "by_classification": {key: sum(row.get("classification") == key for row in rows)
                                  for key in CLASSIFICATIONS}}


def import_v1_disposition(table: dict, *, source_sha256: str, source_locator: str) -> dict:
    """将旧表转为独立v2候选及逐字段报告，不做I/O或专业/阶段放行。

    hash是调用者提供的原件字节身份，本函数不认证原件；定位参与ID，区分同件多表。
    原表完整保留在candidate.migration_source.table；缺字段不编造，候选可能尚不能
    被v2消费者接受。只有补齐报告指明的字段后才能调用既有消费者，门禁不因此放宽。
    """
    leaves = _migration_boundary(table, 1)
    require(isinstance(source_sha256, str) and len(source_sha256) == 64
            and all(char in "0123456789abcdefABCDEF" for char in source_sha256),
            "migration_source_sha256_invalid")
    require(_text(source_locator), "migration_source_locator_required")
    _legacy_shape(table)
    source = {**_migration_identity(1), "sha256": source_sha256.lower(), "locator": source_locator}
    data = copy.deepcopy(table)
    candidate = {"contract_version": 2, "comments": [], "comment_outcomes": [],
                 "migration_source": {**source, "table": copy.deepcopy(data)}}
    issues = []
    mapping = [{"source_path": path, "target_path": "/migration_source/table" + path,
                "action": "preserved_original"} for path, _ in leaves]

    def put(target, field, value, src, dest, action="copied"):
        target[field] = copy.deepcopy(value)
        mapping.append({"source_path": src, "target_path": dest, "action": action})

    def missing(src, dest, cid="", code="migration_information_missing"):
        _migration_issue(issues, code, src, dest, cid)

    header = data["header"]
    for old, new in (("standard_name", "standard_name"), ("draft_version", "version")):
        if _text(header.get(old)):
            put(candidate, new, header[old], "/header/" + old, "/" + new)
        else:
            missing("/header/" + old, "/" + new)
    for path in ("/project_id", "/adaptation/organization", "/adaptation/standard_type",
                 "/adaptation/domain", "/adaptation/stage", "/collection_status", "/baseline_version"):
        missing("", path)
    if "decisions" in data:
        put(candidate, "decisions", data["decisions"], "/decisions", "/decisions", "uninterpreted")
    for index, original in enumerate(data["items"]):
        src, cp, op = f"/items/{index}", f"/comments/{index}", f"/comment_outcomes/{index}"
        cid = "v1-" + digest({"sha256": source["sha256"], "locator": source_locator, "seq": original["seq"]})
        origin = original.get("origin", {})
        comment = {"id": cid, "source": f"sha256:{source['sha256']}@{source_locator}{src}",
                   "provenance": {"source_sha256": source["sha256"], "source_locator": source_locator + src,
                                  "seq": original["seq"], "origin": copy.deepcopy(origin)}}
        row = {"comment_id": cid}
        mapping.append({"source_path": src + "/seq", "target_path": cp + "/id", "action": "source_identity_id"})
        mapping.append({"source_path": src + "/origin", "target_path": cp + "/provenance/origin", "action": "copied"})
        for field in ("organization", "representative_scope"):
            if not _text(origin.get(field)):
                missing(src + "/origin/" + field, cp + "/provenance/origin/" + field, cid)
        for field, value, from_path in (("text", original.get("text"), src + "/text"),
                                        ("participant_id", origin.get("participant_id"), src + "/origin/participant_id"),
                                        ("version", header.get("draft_version"), "/header/draft_version")):
            if _text(value):
                put(comment, field, value, from_path, cp + "/" + field)
            else:
                missing(from_path, cp + "/" + field, cid)
        target = original.get("clause_id")
        if target == "全文":
            put(comment, "scope", "document", src + "/clause_id", cp + "/scope", "document_scope")
        elif _text(target):
            put(comment, "clause_id", target, src + "/clause_id", cp + "/clause_id")
        else:
            missing(src + "/clause_id", cp + "/clause_id", cid)
        for field in ("outcome", "classification", "reason", "reason_source", "decision_version",
                      "accepted_part", "rejected_part", "rejected_reason", "confirmation", "no_change"):
            if field in original:
                put(row, field, original[field], src + "/" + field, op + "/" + field)
        for field in ("outcome", "classification", "reason"):
            if not _text(row.get(field)):
                missing(src + "/" + field, op + "/" + field, cid,
                        "outcome_missing" if field == "outcome" else "migration_information_missing")
        missing(src + "/confirmation/content_binding", op + "/confirmation/content_binding", cid,
                "comment_decision_content_binding_unbound")
        row["decision_status"] = original.get("decision_status", "proposed")
        if "decision_status" in original:
            put(row, "decision_status", original["decision_status"], src + "/decision_status", op + "/decision_status")
        else:
            missing(src + "/decision_status", op + "/decision_status", cid, "human_confirmation_required")
        if row["decision_status"] == "confirmed":
            for field in _CONFIRMATION_FIELDS:
                if not _text(row.get("confirmation", {}).get(field)):
                    missing(src + "/confirmation/" + field, op + "/confirmation/" + field, cid)
            if not _text(row.get("decision_version")):
                missing(src + "/decision_version", op + "/decision_version", cid)
        row["major_change"] = original.get("major_change", "undetermined")
        if "major_change" in original:
            put(row, "major_change", original["major_change"], src + "/major_change", op + "/major_change")
        else:
            missing(src + "/major_change", op + "/major_change", cid)
        row["impact"] = {}
        for field in IMPACT_FIELDS:
            value = original.get("impact", {}).get(field, "unknown")
            row["impact"][field] = value
            if field in original.get("impact", {}):
                put(row["impact"], field, value, src + "/impact/" + field, op + "/impact/" + field)
            if type(value) is not bool:
                missing(src + "/impact/" + field, op + "/impact/" + field, cid, "impact_assessment_unknown")
        if row.get("outcome") in ("accepted", "partially_accepted"):
            if "proposed_text" in original or "operation" in original:
                change = {}
                for field in ("operation", "proposed_text"):
                    if field in original:
                        put(change, field, original[field], src + "/" + field, op + "/changes/0/" + field)
                if _text(target) and target != "全文":
                    put(change, "clause_id", target, src + "/clause_id", op + "/changes/0/clause_id")
                for field in ("clause_id", "operation"):
                    if not _text(change.get(field)):
                        missing(src + "/" + field, op + "/changes/0/" + field, cid)
                if change.get("operation") != "delete" and not _text(change.get("proposed_text")):
                    missing(src + "/proposed_text", op + "/changes/0/proposed_text", cid)
                if change.get("operation") == "delete" and change.get("proposed_text", "") != "":
                    missing(src + "/proposed_text", op + "/changes/0/proposed_text", cid, "delete_text_conflict")
                row["changes"] = [change]
            elif row.get("no_change") is not True:
                missing(src + "/proposed_text", op + "/changes", cid)
            if row.get("no_change") is True and row.get("changes"):
                missing(src, op, cid, "change_forms_conflict")
        elif "proposed_text" in original or original.get("no_change") is True:
            missing(src, op, cid, "unapplied_legacy_proposal")
        required_details = []
        if row.get("outcome") == "partially_accepted":
            required_details.extend(("accepted_part", "rejected_part", "rejected_reason", "reason_source"))
        if row.get("outcome") == "rejected" or row.get("no_change") is True:
            required_details.append("reason_source")
        for field in dict.fromkeys(required_details):
            if not _text(row.get(field)):
                missing(src + "/" + field, op + "/" + field, cid)
        if "unresolved_item" in original or row.get("outcome") == "pending":
            pending = original.get("unresolved_item", {})
            if isinstance(pending, str):
                row["unresolved_item"] = {"question": pending}
                mapping.append({"source_path": src + "/unresolved_item", "target_path": op + "/unresolved_item/question",
                                "action": "question_only"})
            else:
                put(row, "unresolved_item", pending, src + "/unresolved_item", op + "/unresolved_item")
            for field in _PENDING_FIELDS:
                if not _text(row["unresolved_item"].get(field)):
                    missing(src + "/unresolved_item/" + field, op + "/unresolved_item/" + field, cid)
        candidate["comments"].append(comment)
        candidate["comment_outcomes"].append(row)
    derived = _migration_tally(data["items"])
    derived["unmapped_outcomes"] = sum(row.get("outcome") not in OUTCOMES for row in data["items"])
    derived["major_changes"] = (sum(row.get("major_change") == "yes" for row in data["items"])
                                if all(row.get("major_change") in ("yes", "no") for row in data["items"]) else None)
    # 旧目标列是意见位置，不足以证明涉及修改/实质变化的条数。
    derived.update(clauses_touched=None, substantive_changes=None)
    for field in ("total", *OUTCOMES):
        if field not in data["summary"]:
            _migration_issue(issues, "summary_field_missing", "/summary/" + field, "")
    for field in CLASSIFICATIONS:
        if field not in data["summary"].get("by_classification", {}):
            _migration_issue(issues, "summary_field_missing", "/summary/by_classification/" + field, "")
    for path, declared in _migration_leaves(data["summary"], "/summary"):
        parts = path.split("/")[2:]
        if not parts:
            continue
        expected = derived.get(parts[0])
        if len(parts) == 2 and isinstance(expected, dict):
            expected = expected.get(parts[1])
        if expected is None:
            _migration_issue(issues, "summary_unverifiable", path, "", declared=declared)
        elif expected != declared:
            _migration_issue(issues, "summary_mismatch", path, "", declared=declared, derived=expected)
    if header.get("total_received") != len(data["items"]):
        _migration_issue(issues, "header_total_mismatch", "/header/total_received", "",
                         declared=header.get("total_received"), derived=len(data["items"]))
    return {"source": source, "target": _migration_identity(2), "status": "needs_review",
            "candidate": candidate, "mapping": mapping, "issues": issues, "losses": [],
            "summary_comparison": {"declared": copy.deepcopy(data["summary"]), "derived": derived},
            "source_identity": "caller_supplied_unverified", "schema_validation": "not_performed",
            "professional_review": "not_performed", "organization_approval": "not_asserted"}


def export_v1_disposition(payload: dict) -> dict:
    """投影可安全表示的记录；拒绝歧义行，并逐叶列出冻结v1无法承载的信息。

    table是待核投影，不承诺满足v1 schema。只复制当前显式值；旧表头的日期/人员
    仅在同版时保留。原v2及migration_source不变，losses保留每个损失字段的原值。
    """
    leaves = _migration_boundary(payload, 2)
    data = copy.deepcopy(payload)
    comments = _records(data.get("comments", []), ("id", "text"))
    outcomes = _records(data.get("comment_outcomes", []), ("comment_id",))
    require(len({row["id"] for row in comments}) == len(comments), "migration_duplicate_comment_id")
    require(len({row["comment_id"] for row in outcomes}) == len(outcomes), "migration_duplicate_outcome_id")
    known = {row["id"] for row in comments}
    require(all(row["comment_id"] in known for row in outcomes), "migration_outcome_comment_missing")
    table, mapping, issues, used, reasons, rejected = {"header": {}, "items": []}, [], [], set(), {}, []

    def mapped(value, src, dst, action="copied"):
        used.update(path for path, _ in _migration_leaves(value, src))
        mapping.append({"source_path": src, "target_path": dst, "action": action})
        return copy.deepcopy(value)

    def problem(code, src, dst, cid=""):
        _migration_issue(issues, code, src, dst, cid)

    historical = data.get("migration_source", {})
    require(isinstance(historical, dict), "migration_source_object_required")
    historical_table = historical.get("table", {})
    require(isinstance(historical_table, dict), "migration_source_table_object_required")
    old_header = historical_table.get("header", {})
    _migration_strings(old_header, "/migration_source/table/header", _V1_HEADER_TEXT)
    if old_header.get("draft_version") == data.get("version") and _text(data.get("version")):
        for field in _V1_HEADER_TEXT:
            if field in old_header:
                table["header"][field] = mapped(old_header[field], "/migration_source/table/header/" + field,
                                                  "/header/" + field)
    for field, target in (("standard_name", "standard_name"), ("version", "draft_version")):
        _migration_strings(data, "", (field,))
        if _text(data.get(field)):
            table["header"][target] = mapped(data[field], "/" + field, "/header/" + target)
    by_id = {row["comment_id"]: (i, row) for i, row in enumerate(outcomes)}
    for index, comment in enumerate(comments):
        cp, cid = f"/comments/{index}", comment["id"]
        _migration_strings(comment, cp, ("clause_id", "scope", "participant_id", "version", "source"))
        entry = by_id.get(cid)
        if entry is None:
            problem("outcome_missing", cp, "/items", cid)
            rejected.append(cid)
            continue
        oi, row = entry
        op = f"/comment_outcomes/{oi}"
        if "confirmation" in row:
            _confirmation_shape(row["confirmation"])
        _confirmation_history(row)
        for field, values in (("outcome", OUTCOMES), ("classification", CLASSIFICATIONS),
                              ("major_change", ("yes", "no", "undetermined")),
                              ("decision_status", ("proposed", "confirmed"))):
            _migration_enum(row, field, values, op)
        _migration_strings(row, op, ("reason", "reason_source", "clause_id", "proposed_text"))
        provenance = comment.get("provenance", {})
        require(isinstance(provenance, dict), "migration_provenance_object_required")
        origin = comment.get("origin", provenance.get("origin", {}))
        origin_path = cp + ("/origin" if "origin" in comment else "/provenance/origin")
        _migration_strings(origin, origin_path, _ORIGIN_FIELDS)
        before = len(issues)
        for field in ("organization", "representative_scope"):
            if not _text(origin.get(field)):
                problem("v1_origin_missing", origin_path + "/" + field, "/items/origin/" + field, cid)
        for field in ("outcome", "classification"):
            if not _text(row.get(field)):
                problem("v1_required_field_missing", op + "/" + field, "/items/" + field, cid)
        scope, target = comment.get("scope"), comment.get("clause_id")
        if scope == "document" and not _text(target):
            target = "全文"
        elif _text(scope) or not _text(target) or target == "全文":
            problem("v1_comment_scope_unrepresentable", cp, "/items/clause_id", cid)
        changes = row.get("changes", [])
        _records(changes)
        direct = "clause_id" in row or "proposed_text" in row
        if direct:
            if changes:
                problem("v1_change_forms_conflict", op, "/items/proposed_text", cid)
            changes = [{"operation": "replace", "clause_id": row.get("clause_id"),
                        "proposed_text": row.get("proposed_text")}]
        no_change = row.get("no_change") is True
        if "no_change" in row:
            require(type(row["no_change"]) is bool, "migration_no_change_boolean_required")
        accepted = row.get("outcome") in ("accepted", "partially_accepted")
        if len(changes) > 1:
            problem("v1_multiple_changes_unrepresentable", op + "/changes", "/items", cid)
        if accepted and not changes and not no_change:
            problem("v1_proposal_missing", op, "/items/proposed_text", cid)
        if (no_change and changes) or (not accepted and (changes or no_change)):
            problem("v1_change_forms_conflict", op, "/items", cid)
        for ci, change in enumerate(changes):
            path = op if direct else op + f"/changes/{ci}"
            _migration_strings(change, path, ("operation", "clause_id", "proposed_text"))
            if change.get("operation") != "replace" or change.get("clause_id") != target or target == "全文":
                problem("v1_change_unrepresentable", path, "/items/proposed_text", cid)
            if not _text(change.get("proposed_text")):
                problem("v1_proposal_missing", path + "/proposed_text", "/items/proposed_text", cid)
        if no_change:
            targets = row.get("no_change_targets", [])
            require(_texts(targets), "migration_no_change_targets_required")
            explicit_scope = row.get("no_change_scope")
            require(explicit_scope in (None, "document"), "migration_no_change_scope_unknown")
            if (targets and (targets != [target] or explicit_scope is not None)) or (
                    explicit_scope == "document" and target != "全文"):
                problem("v1_no_change_scope_unrepresentable", op, "/items/clause_id", cid)
        if accepted or row.get("outcome") == "rejected":
            if not _text(row.get("reason")):
                problem("v1_reason_missing", op + "/reason", "/items/reason", cid)
        if row.get("outcome") == "rejected" or no_change:
            if not _text(row.get("reason_source")):
                problem("v1_reason_source_missing", op + "/reason_source", "/items/reason_source", cid)
        pending = row.get("unresolved_item", {})
        if "unresolved_item" in row or row.get("outcome") == "pending":
            _migration_strings(pending, op + "/unresolved_item", _PENDING_FIELDS)
            _migration_enum(pending, "blocks", BLOCKS, op + "/unresolved_item")
            for field in _PENDING_FIELDS:
                if not _text(pending.get(field)):
                    problem("v1_pending_field_missing", op + "/unresolved_item/" + field,
                            "/items/unresolved_item/" + field, cid)
        impact = row.get("impact", {})
        require(impact == [] or isinstance(impact, dict), "migration_impact_object_required")
        if isinstance(impact, dict):
            require(set(impact) <= set(IMPACT_FIELDS), "migration_impact_fields_unknown")
            require(all(type(value) is bool or value in ("unknown", "undetermined")
                        for value in impact.values()), "migration_impact_value_unknown")
        if len(issues) != before:
            rejected.append(cid)
            continue
        dest = f"/items/{len(table['items'])}"
        item = {"seq": len(table["items"]) + 1, "origin": {}}
        mapping.append({"source_path": cp + "/id", "target_path": dest + "/seq", "action": "export_order_only"})
        item["text"] = mapped(comment["text"], cp + "/text", dest + "/text")
        if target == "全文":
            item["clause_id"] = "全文"
            mapped(scope, cp + "/scope", dest + "/clause_id", "document_scope_label")
        else:
            item["clause_id"] = mapped(target, cp + "/clause_id", dest + "/clause_id")
        for field in _ORIGIN_FIELDS:
            if field in origin:
                item["origin"][field] = mapped(origin[field], origin_path + "/" + field, dest + "/origin/" + field)
        if _text(comment.get("participant_id")):
            if item["origin"].get("participant_id") not in (None, comment["participant_id"]):
                # 不覆盖原提出者；两份关联矛盾交损失报告，不代做身份选择。
                reasons[cp + "/participant_id"] = "participant_identity_conflict"
            else:
                item["origin"]["participant_id"] = mapped(comment["participant_id"], cp + "/participant_id",
                                                            dest + "/origin/participant_id")
        for field in ("outcome", "classification", "reason", "reason_source", "major_change", "no_change"):
            if field in row:
                item[field] = mapped(row[field], op + "/" + field, dest + "/" + field)
        if changes:
            path = op if direct else op + "/changes/0"
            item["proposed_text"] = mapped(changes[0]["proposed_text"], path + "/proposed_text", dest + "/proposed_text")
            if not direct:
                reasons[path + "/operation"] = "v1_has_no_explicit_operation_field"
        if "unresolved_item" in row:
            item["unresolved_item"] = {field: mapped(pending[field], op + "/unresolved_item/" + field,
                                                       dest + "/unresolved_item/" + field) for field in _PENDING_FIELDS}
        if isinstance(impact, dict) and impact:
            item["impact"] = {}
            for field in IMPACT_FIELDS:
                if field in impact and type(impact[field]) is bool:
                    item["impact"][field] = mapped(impact[field], op + "/impact/" + field, dest + "/impact/" + field)
                elif field in impact:
                    reasons[op + "/impact/" + field] = "v1_boolean_cannot_represent_unknown_impact"
        table["items"].append(item)
    table["summary"] = _migration_tally(table["items"])
    # 表头总量指原收集，投影行数仅指本次可导出集合，不能相互冒充。
    if (old_header.get("draft_version") == data.get("version") and not rejected
            and old_header.get("total_received") == len(comments) and type(old_header.get("total_received")) is int):
        table["header"]["total_received"] = mapped(old_header["total_received"],
            "/migration_source/table/header/total_received", "/header/total_received")
    for field in ("standard_name", "draft_version", "version_date", "total_received"):
        if field not in table["header"] or table["header"][field] == "":
            problem("v1_header_missing", "", "/header/" + field)
    if not table["items"]:
        problem("v1_min_items_unsatisfied", "/comments", "/items")
    for path, _ in leaves:
        if re.match(r"/comment_outcomes/\d+/confirmation/content_binding(?:/|$)", path):
            reasons[path] = "v1_cannot_represent_comment_content_binding"
        elif re.match(r"/comment_outcomes/\d+/confirmation_history(?:/|$)", path):
            reasons[path] = "v1_cannot_represent_confirmation_history"
        elif path in ("/external_references", "/reference_bindings") or path.startswith(
                ("/external_references/", "/reference_bindings/")):
            reasons[path] = "v1_cannot_represent_reference_identity_or_binding"
    losses = [{"path": path, "reason": reasons.get(path, "no_frozen_v1_projection_for_field"),
               "value": copy.deepcopy(value)} for path, value in leaves if path not in used]
    return {"source": _migration_identity(2), "target": _migration_identity(1),
            "status": "refused" if not table["items"] else "partial" if issues or losses else "projected",
            "table": table, "mapping": mapping, "issues": issues, "losses": losses,
            "rejected_record_ids": rejected, "summary_scope": "exported_rows_only",
            "schema_validation": "not_performed", "professional_review": "not_performed",
            "organization_approval": "not_asserted"}


def evaluate(payload: dict, *, section_ids: tuple[str, ...], clause_validator,
             semantic_fields: tuple[str, ...], initial_issues: list | None = None) -> dict:
    """返回v2确定性诊断；issues为空仍不表示专业或实物通过。

    v2 schema记录与运行时comments/comment_outcomes/compilation_note同形，
    使用identity mapping保留全部字段；派生结果另存，不回写源记录。
    compilation-note schema描述完整记录，缺证草稿仍返回原值及具体issues。
    """
    require(contract_version(payload) == 2, "closed_loop_requires_contract_v2")
    require_fields(payload, ("project_id", "version", "adaptation"))
    require(_text(payload["project_id"]) and _text(payload["version"]), "project_version_required")
    adaptation = payload["adaptation"]
    require_fields(adaptation, ("organization", "standard_type", "domain", "stage"))
    require(all(_text(adaptation[key]) for key in ("organization", "standard_type", "domain", "stage")),
            "adaptation_values_required")
    canonical_bytes(payload)
    data = copy.deepcopy(payload)
    _optional_strings(data, ("baseline_version", "standard_name"), "comment")
    # 表决等前置诊断须先参与派生统计，再核说明中声明的闭环状态。
    issues, open_items, proposals, no_change_checks = copy.deepcopy(initial_issues or []), [], {}, []
    clauses = data.get("clauses", [])
    old = _clause_map(data.get("baseline_clauses", []), clause_validator, issues, "baseline")
    new = _clause_map(clauses, clause_validator, issues, "current")
    if not new:
        _issue(issues, "clauses_missing")
    registry = _reference_registry(data, new)
    reference_checks = _reference_checks(new, registry, issues)
    confirmation_checks = []
    profile = _profile(data, section_ids)
    if profile["scope"] == "organization":
        _issue(issues, "organization_profile_needs_review", profile["id"])
    comments = _records(data.get("comments", []), ("id", "text", "source", "participant_id", "version"))
    comment_counts = Counter(c["id"] for c in comments)
    known_comments = set(comment_counts)
    for comment in comments:
        _optional_strings(comment, ("clause_id", "scope"), "comment")
        require(_text(comment.get("clause_id")) != _text(comment.get("scope")),
                "comment_target_or_scope_required")
        if comment.get("clause_id") and comment["clause_id"] not in old and comment["clause_id"] not in new:
            _issue(issues, "comment_clause_missing", comment["id"])
    collection = data.get("collection_status", "unknown")
    require(collection in ("complete", "partial", "unknown", "not_started"), "collection_status_unknown")
    if collection != "complete":
        _issue(issues, "comment_collection_incomplete", state=collection)
    collection_evidence = data.get("collection_evidence", [])
    require(_texts(collection_evidence), "comment_collection_evidence_list_required")
    zero_collection_supported = bool(comments) or bool(collection_evidence)
    if collection == "complete" and not zero_collection_supported:
        _issue(issues, "zero_comment_collection_evidence_missing")
    rows = _records(data.get("comment_outcomes", []),
                    ("comment_id", "outcome", "classification", "reason", "decision_status", "major_change"))
    outcome_counts = Counter(row["comment_id"] for row in rows)
    forbidden = {"comment_realizations", "realization", "realization_evidence", "applied", "document_hash"}
    for row in rows:
        cid = row["comment_id"]
        require(cid in known_comments, "comment_outcome_comment_missing")
        require(row["outcome"] in OUTCOMES, "comment_outcome_unknown")
        require(row["classification"] in CLASSIFICATIONS, "comment_classification_unknown")
        require(row["decision_status"] in ("proposed", "confirmed"), "comment_decision_status_unknown")
        require(row["major_change"] in ("yes", "no", "undetermined"), "comment_major_change_unknown")
        require(not (set(row) & forbidden), "comment_realization_separate_required")
        _optional_strings(row, ("reason_source", "decision_version", "accepted_part",
                                "rejected_part", "rejected_reason"), "comment_outcome")
        confirmation = row.get("confirmation", {})
        _confirmation_shape(confirmation)
        _confirmation_history(row)
        impact = row.get("impact", [])
        # 空评估表示尚未逐项核查，允许内部草稿，但不能推成四项均无影响。
        if impact == [] or impact == {}:
            _issue(issues, "comment_impact_assessment_missing", cid)
        else:
            require(isinstance(impact, dict) and set(impact) == set(IMPACT_FIELDS),
                    "comment_impact_fields_required")
            require(all(type(value) is bool or value in ("unknown", "undetermined")
                        for value in impact.values()), "comment_impact_value_unknown")
        if row["outcome"] == "partially_accepted":
            require(all(_text(row.get(key)) for key in
                        ("accepted_part", "rejected_part", "rejected_reason", "reason_source")),
                    "partial_acceptance_details_required")
        if row["outcome"] == "rejected":
            require(_text(row.get("reason_source")), "rejection_reason_unsourced")
        if row["outcome"] == "pending":
            open_items.append(_open_item(row.get("unresolved_item"), f"comment:{cid}", f"comment:{cid}"))
            _issue(issues, "comment_pending", cid)
        elif "unresolved_item" in row:
            _open_item(row["unresolved_item"], f"comment:{cid}", f"comment:{cid}")
        if row["decision_status"] == "proposed":
            _issue(issues, "comment_decision_unconfirmed", cid)
        else:
            if not all(_text(confirmation.get(key)) for key in
                       ("actor", "authority_evidence", "source", "version")):
                _issue(issues, "comment_decision_authority_unproven", cid)
            if not _text(row.get("decision_version")):
                _issue(issues, "comment_decision_version_missing", cid)
            elif confirmation.get("version") != row["decision_version"]:
                _issue(issues, "comment_decision_confirmation_stale", cid)
            baseline_version = data.get("baseline_version")
            if (not _text(baseline_version)
                    or confirmation.get("baseline_version") != baseline_version
                    or any(c["version"] != baseline_version for c in comments if c["id"] == cid)):
                _issue(issues, "comment_decision_baseline_unbound_or_stale", cid)
        if row["major_change"] != "no":
            _issue(issues, "comment_major_change_review_required", cid, state=row["major_change"])
        if isinstance(impact, dict) and any(value is not False for value in impact.values()):
            _issue(issues, "comment_impact_review_required", cid, impact=impact)
        changes = _changes(row)
        confirmation_checks.append(_confirmation_check(data, row, comments, old, new, registry, issues))
        _check_changes(cid, changes, old, new, issues, proposals)
        if row.get("no_change") is True:
            originals = [comment for comment in comments if comment["id"] == cid]
            original = originals[0] if len(originals) == 1 else {}
            no_change_checks.append(_check_no_change(row, original, old, new, issues, semantic_fields))
    for key, entries in sorted(proposals.items()):
        if len({(op, text) for _, op, text in entries}) > 1:
            _issue(issues, "conflicting_comment_changes", key,
                   comment_ids=sorted({cid for cid, _, _ in entries}))
    duplicates = sorted(cid for cid, count in comment_counts.items() if count > 1)
    duplicate_outcomes = sorted(cid for cid, count in outcome_counts.items() if count > 1)
    missing = sorted(known_comments - set(outcome_counts))
    for cid in duplicates:
        _issue(issues, "duplicate_comment_id", cid)
    for cid in duplicate_outcomes:
        _issue(issues, "duplicate_comment_outcome", cid)
    for cid in missing:
        _issue(issues, "comment_outcome_missing", cid)
    unique_rows = [row for row in rows if outcome_counts[row["comment_id"]] == 1
                   and comment_counts[row["comment_id"]] == 1]
    tally = {key: sum(row["outcome"] == key for row in unique_rows) for key in OUTCOMES}
    complete = (collection == "complete" and zero_collection_supported
                and not (missing or duplicates or duplicate_outcomes))
    tally.update({
        "total": len(comments) if collection == "complete" and zero_collection_supported else None,
        "registered_count": len(comments), "original_count": len(comments),
        "processed_count": len(unique_rows), "total_ranked": len(unique_rows),
        "pending_count": tally["pending"], "unprocessed_ids": missing,
        "duplicate_comment_ids": duplicates, "duplicate_outcome_ids": duplicate_outcomes,
        "by_classification": {key: sum(row["classification"] == key for row in unique_rows)
                              for key in CLASSIFICATIONS},
        "collection_status": collection, "complete": complete,
        "closed": complete and not issues and tally["pending"] == 0,
        "tally_balanced": sum(tally.values()) == len(unique_rows),
        "tally_balanced_scope": "unique_unambiguous_outcome_rows_only",
        "clauses_touched": len(proposals),
    })
    for name in ("open_items", "verification_open_items", "reference_open_items", "profile_open_items", "material_open_items"):
        for item in _records(data.get(name, [])):
            open_items.append(_open_item(item))
    clause_digest = digest(clauses)
    verification = _verification(data, new, issues)
    note, sections = _note(data, profile, clause_digest, issues, open_items, section_ids)
    merged_open = _merge_open_items(open_items, issues)
    for item in merged_open:
        if item["blocks"] != "none":
            _issue(issues, "open_item_stage_blocked", item["id"], stage=item["blocks"])
    # 说明、验证和各来源未决也参与就绪；不能在这些检查运行前封存closed。
    tally["closed"] = complete and not issues and not merged_open and tally["pending"] == 0
    for section in sections:
        key = profile.get("section_semantics", {}).get(section["id"], section["id"])
        for field, expected, code in (
            ("outcome_tally", tally, "compilation_note_tally_mismatch"),
            ("verification_summary", verification, "compilation_note_verification_mismatch"),
        ):
            if field in section:
                declared = section[field]
                require(isinstance(declared, dict), f"{field}_object_required")
                if any(name not in expected or canonical_bytes(value) != canonical_bytes(expected[name])
                       for name, value in declared.items()):
                    _issue(issues, code, section["id"], declared=declared, derived=expected)
        if key == section_ids[10] and "open_items" in section:
            declared = [_open_item(item) for item in _records(section["open_items"])]
            if sorted(declared, key=lambda item: item["id"]) != merged_open:
                _issue(issues, "compilation_note_open_items_mismatch", section["id"],
                       declared=declared, derived=merged_open)
    tally["closed"] = tally["closed"] and not issues
    return {
        "contract_version": 2, "contract_mode": "closed_loop", "assessment_version": ASSESSMENT_VERSION,
        "reference_checks": reference_checks, "confirmation_checks": confirmation_checks,
        "issues": issues, "comments": comments, "comment_outcomes": rows,
        "collection_evidence": collection_evidence, "no_change_checks": no_change_checks,
        "outcome_tally": tally, "open_items": merged_open, "clause_digest": clause_digest,
        "profile": profile, "profile_hash": digest(profile), "compilation_note": note,
        "compilation_note_derived": {"outcome_tally": tally, "verification_summary": verification,
                                     "open_items": merged_open},
        "verification_summary": verification, "decisions": data.get("decisions", []),
        "professional_review": "not_performed", "organization_approval": "not_asserted",
        "consensus": "not_inferred", "submission": "not_performed",
        "implementation_verification": "not_performed",
    }
