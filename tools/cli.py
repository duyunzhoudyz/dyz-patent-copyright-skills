"""合成能力入口与获准本地软件准备；不打印材料或补造权限、适配事实。"""
from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import core, rendering
from .disclosure import (DisclosureJournal, freeze_candidate, preview_candidate, review_candidate)

CAPABILITIES = tuple([f"CORE-{i:02}" for i in range(1, 8)] +
                     ["REVIEW-07", "LIFE-01", "LIFE-03", "LIFE-04"])
MODULE_CAPABILITIES = {
    "tools.patent": tuple(f"{group}-{i:02}" for group, count in
                          (("SEARCH", 6), ("ANALYSIS", 8), ("DRAFT", 8),
                           ("FIG", 5), ("REVIEW", 6)) for i in range(1, count + 1)),
    "tools.procedure": tuple([f"PROC-{i:02}" for i in range(1, 10)] +
                             [f"RIGHTS-{i:02}" for i in range(1, 8)] +
                             ["SEARCH-07", "SEARCH-08", "LIFE-02"]),
    "tools.software": tuple(f"SW-{i:02}" for i in range(1, 9)),
    "tools.standards": tuple(f"STD-{i:02}" for i in range(1, 13)),
}


def catalog() -> list[dict]:
    rows = [{"capability": cap, "module": "tools.cli", "availability": "available",
             "support": "synthetic_helper_only"} for cap in CAPABILITIES]
    for name, ids in MODULE_CAPABILITIES.items():
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise core.ContractError("module_dependency_unavailable") from exc
            module = None
        for cap in ids:
            available = module is not None and cap in getattr(module, "CAPABILITIES", ())
            rows.append({"capability": cap, "module": name,
                         "availability": "available" if available else "unavailable",
                         "support": "synthetic_helper_only" if available else "not_implemented"})
    return sorted(rows, key=lambda row: row["capability"])


def _version(payload: dict) -> dict:
    prior = payload.get("ledger", {})
    ledger = core.VersionLedger(prior.get("records"), prior.get("reviews"))
    for change in payload.get("changes", []):
        ledger.put(change["record_id"], change["payload"], dependencies=change.get("dependencies"))
    for review in payload.get("reviews", []):
        ledger.add_review(**review)
    return core.result("CORE-06", status="checked", artifacts=ledger.export(),
                       checks=["dependency_hashes_and_review_invalidation"])


def _handoff(payload: dict) -> dict:
    core.require_fields(payload, ("handoff", "permissions", "now"))
    handoff = payload["handoff"]
    core.require_fields(handoff, ("record_id", "version", "recipient", "purpose",
                                  "owner", "pending", "expected_hash", "record"))
    core.check_permission(payload["permissions"], action="handoff", purpose=handoff["purpose"],
                          recipient=handoff["recipient"], now=payload["now"])
    current_hash = core.digest(handoff["record"])
    issues = []
    if current_hash != handoff["expected_hash"]:
        issues.append({"code": "handoff_version_changed"})
    reviewers = payload.get("reviewers", [])
    independent = any(r.get("kind") == "synthetic_human" and r.get("actor_id") != handoff["owner"]
                      and r.get("binding") == current_hash and r.get("authority_evidence")
                      and r.get("evidence") for r in reviewers)
    if not independent:
        issues.append({"code": "independent_signature_missing"})
    return core.result("LIFE-03", status="blocked" if issues else "checked", issues=issues,
                       artifacts={"handoff": handoff, "binding": current_hash,
                                  "identity_verification": "not_performed",
                                  "signature_scope": "synthetic_records_only",
                                  "privilege": "not_asserted"})


def _regression(payload: dict) -> dict:
    """汇总调用者检查记录；可选版本图只证明绑定一致，不执行检查或认证证据。"""
    core.require_fields(payload, ("combinations", "changed_dependencies"))
    core.require(isinstance(payload["combinations"], list), "regression_combinations_required")

    def identifiers(value: list) -> set[str]:
        core.require(isinstance(value, list) and all(isinstance(item, str) and item.strip()
                                                     for item in value), "regression_dependencies_required")
        core.require(len(set(value)) == len(value), "duplicate_regression_dependency")
        return set(value)

    changed = identifiers(payload["changed_dependencies"])
    ledger = None
    if "ledger" in payload:
        prior = payload["ledger"]
        core.require(isinstance(prior, dict), "regression_ledger_required")
        ledger = core.VersionLedger(prior.get("records"), prior.get("reviews"))
        core.require(changed.issubset(ledger.records), "regression_dependency_missing")
    # 能力范围复用现有注册表；目录覆盖不意味着业务模块或适配组合已验证。
    capabilities = sorted(set(CAPABILITIES).union(*map(set, MODULE_CAPABILITIES.values())))
    coverage = {capability: [] for capability in capabilities}
    rows = []
    for combination in payload["combinations"]:
        core.require_fields(combination, ("capability", "adaptation", "dependencies", "checks"))
        capability, adaptation = combination["capability"], combination["adaptation"]
        core.require(isinstance(capability, str) and capability in coverage, "regression_capability_unknown")
        core.require(isinstance(adaptation, dict) and bool(adaptation), "regression_adaptation_required")
        dependencies = identifiers(combination["dependencies"])
        checks = combination["checks"]
        core.require(isinstance(checks, list) and all(isinstance(check, dict) for check in checks),
                     "regression_checks_required")
        scope, stale, bindings, versions, binding = set(dependencies), [], {}, {}, None
        if ledger is not None:
            core.require(dependencies.issubset(ledger.records), "regression_dependency_missing")
            pending = list(dependencies)
            while pending:
                record_id = pending.pop()
                for dependency in ledger.records[record_id][-1]["dependencies"]:
                    if dependency not in scope:
                        scope.add(dependency)
                        pending.append(dependency)
            stale = sorted(record_id for record_id in dependencies if not ledger.is_current(record_id))
            bindings = {record_id: ledger.records[record_id][-1]["hash"] for record_id in sorted(scope)}
            versions = {record_id: ledger.records[record_id][-1]["version"] for record_id in sorted(scope)}
            # 恢复为相同内容仍是新版本，不能复活早期检查记录。
            binding = core.digest({"capability": capability, "adaptation": adaptation,
                                   "dependencies": bindings, "dependency_versions": versions})
        affected = sorted(scope.intersection(changed))
        gaps = []
        if affected:
            gaps.append({"code": "changed_dependencies", "dependencies": affected})
        if stale:
            gaps.append({"code": "stale_dependencies", "dependencies": stale})
        if not checks:
            gaps.append({"code": "checks_missing"})
        for index, check in enumerate(checks):
            if check.get("status") != "passed":
                gaps.append({"code": "check_not_passed", "check_index": index,
                             "status": check.get("status", "unknown")})
            evidence = check.get("evidence")
            if not isinstance(evidence, str) or not evidence.strip():
                gaps.append({"code": "check_evidence_missing", "check_index": index})
            if ledger is not None and check.get("binding") != binding:
                gaps.append({"code": "check_binding_missing" if not check.get("binding") else
                             "check_binding_mismatch", "check_index": index})
        status = "needs_regression" if affected or stale else ("unverified" if gaps else "recorded_checks_passed")
        coverage[capability].append(len(rows))
        rows.append({**combination, "affected_dependencies": affected, "status": status,
                     "dependency_scope": sorted(scope), "stale_dependencies": stale,
                     "dependency_bindings": bindings, "dependency_versions": versions,
                     "binding": binding, "validation_gaps": gaps,
                     "dependency_verification": "ledger_hashes_only" if ledger is not None else
                     "declared_dependencies_only", "professional_support": "unverified",
                     "evidence_verification": "caller_records_only"})
    table = [{"capability": capability, "combination_indexes": indexes,
              "status": "recorded_combinations_only" if indexes else "not_evaluated",
              "professional_support": "unverified"} for capability, indexes in coverage.items()]
    return core.result("LIFE-04", status="checked" if rows and all(
        row["status"] == "recorded_checks_passed" for row in rows) else "needs_review",
        issues=[] if rows else [{"code": "combinations_missing"}],
        artifacts={"combinations": rows, "support_table": table,
                   "unassessed_capabilities": [capability for capability, indexes in coverage.items() if not indexes],
                   "assessment_scope": "provided_combinations_only", "cross_combination_inheritance": False})


def _disclosure(payload: dict) -> dict:
    core.require_fields(payload, ("root", "journal", "operation"))
    path = core.safe_path(payload["root"], payload["journal"], must_exist=False)
    journal = DisclosureJournal(path, synthetic=True)
    operation = payload["operation"]
    args = payload.get("arguments", {})
    methods = {"create": journal.create_release, "sign": journal.sign,
               "review": journal.review, "execute": journal.execute,
               "invalidate": journal.invalidate, "revoke": journal.revoke,
               "receipt": journal.simulated_receipt, "verify_receipt": journal.verify_receipt,
               "incident": journal.report_incident, "status": journal.status}
    core.require(operation in methods, "unknown_disclosure_operation")
    artifact = methods[operation](**args)
    blocked = artifact.get("status") == "blocked" or artifact.get("state") in {
        "revoked", "invalidated", "reported_stopped"}
    return core.result("CORE-04", status="blocked" if blocked else "checked", artifacts=artifact,
                       checks=["synthetic_journal_only_not_host_egress_control"])


def run_shared(capability: str, payload: dict) -> dict:
    if capability == "CORE-01":
        return core.result(capability, status="checked", artifacts=core.route_project(
            payload["project_id"], payload["requests"], payload.get("evidence_ids", [])))
    if capability == "CORE-02":
        return core.assess_contributions(payload["facts"])
    if capability == "CORE-03":
        core.require(payload["context"].get("sensitivity") == "synthetic", "synthetic_only")
        context = payload["context"]
        evidence, _ = core.capture_evidence(
            payload["root"], payload["path"], source=payload["source"],
            permissions=context["permissions"], environment=context["environment"],
            sensitivity=context["sensitivity"], purpose=context["purpose"],
            acquired_at=context["now"], locator=payload["locator"],
            extraction_status=payload.get("extraction_status", "not_checked"))
        return core.result(capability, status="checked", artifacts=evidence,
                           checks=["raw_snapshot_hash_only"])
    if capability == "CORE-04":
        return _disclosure(payload)
    if capability == "CORE-05":
        return core.select_rules(payload["rules"], payload["adaptation"], as_of=payload["as_of"])
    if capability == "CORE-06":
        return _version(payload)
    if capability == "CORE-07":
        candidate = freeze_candidate(payload["root"], payload["files"], payload["context"],
                                     ledger=payload.get("ledger"),
                                     rendering_evidence=payload.get("rendering_evidence"))
        issues = [{"code": code, "file_id": entry["file_id"]}
                  for entry in candidate["manifest"]["files"] for code in entry["inspection"]["issues"]]
        issues.extend({"code": code, "file_id": file_id}
                      for file_id, result in candidate.get("rendering_evidence", {}).items()
                      for code in result["issues"])
        return core.result(capability, status="blocked" if issues else "needs_review",
                           artifacts=candidate, issues=issues, checks=["fixed_raw_bytes_manifest"])
    if capability == "REVIEW-07":
        review = review_candidate(**payload)
        return core.result(capability, status="blocked" if review["issues"] else "checked",
                           artifacts=review, issues=review["issues"],
                           checks=["synthetic_candidate_checks_not_professional_approval"])
    if capability == "LIFE-01":
        return core.record_deadline(payload["event"])
    if capability == "LIFE-03":
        return _handoff(payload)
    if capability == "LIFE-04":
        return _regression(payload)
    raise core.ContractError("capability_unavailable")


def dispatch(capability: str, payload: dict, *, synthetic: bool = False) -> dict:
    core.require(synthetic is True, "synthetic_declaration_required")
    core.require(isinstance(payload, dict), "object_required")
    core.canonical_bytes(payload)
    core.require(payload.get("sensitivity", "synthetic") == "synthetic"
                 and payload.get("context", {}).get("sensitivity", "synthetic") == "synthetic",
                 "synthetic_only")
    if capability in CAPABILITIES:
        output = run_shared(capability, payload)
    else:
        row = next((r for r in catalog() if r["capability"] == capability), None)
        core.require(row is not None and row["availability"] == "available", "capability_unavailable")
        output = importlib.import_module(row["module"]).run(capability, payload)
    core.require(isinstance(output, dict), "module_result_invalid")
    return {**output, "mode": "synthetic", "host_egress": "not_controlled",
            "external_action": "not_performed", "official_status": "not_asserted"}


def demo() -> dict:
    """内建合成例验证固定包、必需签核、一次执行、同版本回执；无真实发送。"""
    from .disclosure import required_roles
    now = "2026-10-31T12:00:00+00:00"
    start, end = "2026-01-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="dyz-synthetic-") as folder:
        root = Path(folder)
        content = b"Synthetic public example.\n"
        (root / "example.txt").write_bytes(content)
        permission = {"action": "local_read", "purpose": "demo", "recipient": "local_tool",
                      "decision": "allow", "authority_evidence": "synthetic-fixture",
                      "valid_from": start, "valid_until": end}
        candidate = freeze_candidate(root, [{"file_id": "f1", "path": "example.txt", "version": "1",
                    "expected_sha256": core.sha256_bytes(content), "kind": "external", "content_ids": ["c1"]}],
                    {"sensitivity": "synthetic", "environment": {}, "permissions": [permission],
                     "purpose": "demo", "now": now})
        request = {"release_id": "demo-1", "project_id": "demo", "businesses": ["patent"],
                   "purpose": "demo", "action": "controlled_share", "recipient": "synthetic-reviewer",
                   "channel": "synthetic", "access": {"audience": "named", "download": True,
                   "forward": False, "archive": False, "retention": "demo-only"},
                   "targets": ["synthetic-region"], "valid_from": start, "valid_until": end,
                   "max_uses": 1, "conditions": []}
        right = {**permission, "action": request["action"], "recipient": request["recipient"]}
        assessment = {"strategy": "already_public", "patent_not_applicable": {
                      "reason": "synthetic public material without protection goal", "evidence": "fixture"},
                      "rules": {"status": "available", "version": "synthetic-1", "evidence": "fixture"},
                      "policy": {"status": "reviewed", "evidence": "fixture", "conflicts": [],
                                 "license_status": "confirmed", "fto_status": "not_applicable"},
                      "combinations": [], "joint_review": {"status": "confirmed", "evidence": "fixture",
                      "manifest_hash": candidate["manifest_hash"], "file_ids": ["f1"], "content_ids": ["c1"],
                      "combination_ids": [], "inventory_complete": True}, "hidden_review": {
                      "status": "confirmed", "evidence": "fixture", "manifest_hash": candidate["manifest_hash"]},
                      "rights": {"f1": {"source_evidence": "fixture", "contribution_evidence": "fixture",
                                       "permissions": [right], "restrictions": []}},
                      "roles_not_applicable": {"patent": "no protection goal", "software": "no software",
                                               "standard": "no standard"}, "unresolved": []}
        roles = required_roles(request, assessment)
        registry = {"mode": "synthetic", "version": "1", "actors": [
            {"actor_id": role, "kind": "synthetic_human", "roles": [role], "active": True,
             "authority_evidence": "fixture-not-real-authentication", "valid_from": start, "valid_until": end,
             "scope": {"project_id": "demo", "actions": [request["action"]],
                       "recipients": [request["recipient"]], "purposes": ["demo"]}} for role in sorted(roles)]}
        journal = DisclosureJournal(root / "journal.sqlite", synthetic=True)
        release = journal.create_release(candidate, request, assessment, registry)
        for role in sorted(roles):
            journal.sign("demo-1", role=role, actor_id=role, evidence="synthetic-fixture",
                         binding=release["binding"], now=now)
        output = journal.execute("demo-1", current={"request": request, "assessment": assessment,
                                 "registry": registry, "manifest_hash": candidate["manifest_hash"]}, now=now)
        return {"mode": "synthetic", "execution": output, "attempts": journal.status("demo-1")["attempts"],
                "external_action": "not_performed", "official_status": "not_asserted",
                "host_egress": "not_controlled", "temporary_journal": "removed_after_demo"}


def _confine_payload_roots(payload: dict, authorized_root: str) -> dict:
    """CLI只授权一个文件根；业务根不得从输入JSON扩大读取/写入范围。"""
    core.require(isinstance(payload, dict), "object_required")
    base = Path(authorized_root).resolve(strict=True)
    output = dict(payload)
    for key in ("root", "authorized_root"):
        if key not in output:
            continue
        value = output[key]
        core.require(isinstance(value, str) and bool(value.strip()), "payload_root_required")
        path = Path(value)
        resolved = (path if path.is_absolute() else base / path).resolve(strict=True)
        core.require(resolved.is_dir() and resolved.is_relative_to(base), "payload_root_outside_scope")
        output[key] = str(resolved)
    return output


def _read_bound_json(root: Path, relative: str, expected: str, limit: int) -> dict:
    """先核固定字节再解析；授权描述自身只应包含非敏感控制信息。"""
    core.require(isinstance(expected, str) and len(expected) == 64
                 and all(char in "0123456789abcdef" for char in expected), "invalid_expected_sha256")
    path = core.safe_path(root, relative)
    core.require(path.is_file(), "input_file_required")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    core.require(len(content) <= limit, "input_too_large")
    core.require(core.sha256_bytes(content) == expected, "input_snapshot_mismatch")
    output = core.strict_json_loads(content.decode("utf-8"))
    core.require(isinstance(output, dict), "object_required")
    return output


def _prepare_software(args: argparse.Namespace, *, document_output: bool = False) -> dict:
    """授权控制文件先读，任务正文后读；该路径不开放通用dispatch。"""
    root = Path(args.root).resolve(strict=True)
    core.require(root.is_dir(), "authorized_root_required")
    authorization = _read_bound_json(root, args.authorization, args.authorization_sha256, 1_000_000)
    core.require_fields(authorization, ("kind", "authorized_root", "context", "request", "files", "output"))
    core.require(authorization["kind"] == "software_local_authorization", "authorization_kind_unknown")
    declared_root = Path(authorization["authorized_root"])
    core.require(declared_root.is_absolute() and declared_root.resolve(strict=True) == root,
                 "authorization_root_mismatch")
    context = dict(authorization["context"])
    core.require_fields(context, ("environment", "permissions", "sensitivity", "purpose"))
    core.require(isinstance(context["environment"], dict), "environment_object_required")

    def check_access() -> None:
        # 真正执行的时间决定授权有效期，不能以载荷中的旧now恢复过期许可。
        context["now"] = datetime.now(timezone.utc).isoformat()
        core.preflight(context["environment"], context["permissions"],
                       sensitivity=context["sensitivity"], purpose=context["purpose"], now=context["now"])
        core.check_permission(context["permissions"], action="local_write", purpose=context["purpose"],
                              recipient="local_tool", now=context["now"])

    check_access()
    request = authorization["request"]
    core.require_fields(request, ("path", "sha256"))
    output_path = core.safe_path(root, authorization["output"], must_exist=False)
    if not document_output:
        core.require(output_path.suffix.lower() == ".json", "json_output_required")
    if not (document_output and args.verify):
        core.require(not output_path.exists(), "output_exists")
    core.require(output_path.parent.is_dir(), "output_parent_missing")
    files = authorization["files"]
    core.require(isinstance(files, list) and bool(files), "authorized_files_required")
    allowed, resolved = {}, set()
    for entry in files:
        core.require_fields(entry, ("path", "sha256"))
        path = core.safe_path(root, entry["path"], must_exist=False)
        core.require(entry["path"] not in allowed and path not in resolved, "duplicate_authorized_file")
        core.require(path != output_path, "source_output_collision")
        expected = entry["sha256"]
        core.require(isinstance(expected, str) and len(expected) == 64
                     and all(char in "0123456789abcdef" for char in expected), "invalid_expected_sha256")
        allowed[entry["path"]] = expected
        resolved.add(path)
    check_access()
    payload = _read_bound_json(root, request["path"], request["sha256"], 10_000_000)
    # 不允许请求覆盖授权环境、范围或严格母本检查；专业字段仅交给软件模块。
    fields = {"scope_input", "rights", "files", "inventory_complete", "pagination", "manual_input",
              "form", "form_rule_evidence", "field_limits", "previous_preparation",
              "field_candidates", "confirmations"}
    export = getattr(args, "command", None) == "export-software"
    revision_import = getattr(args, "command", None) == "import-software-manual"
    if document_output or revision_import:
        fields.add("delivery")
    discovery = getattr(args, "command", None) == "discover-software"
    if revision_import:
        fields.add("manual_revision")
    if discovery:
        fields.add("sensitive_literals")
    if export:
        fields.update(("package", "export_approval"))
    core.require(set(payload).issubset(fields), "preparation_field_not_allowed")
    package = payload.pop("package", None)
    export_approval = payload.pop("export_approval", None)
    delivery_options = payload.pop("delivery", {})
    core.require(isinstance(delivery_options, dict), "delivery_options_invalid")
    core.require(isinstance(payload.get("files"), list) and bool(payload["files"]), "file_inventory_required")
    selected = set()
    for entry in payload["files"]:
        core.require_fields(entry, ("path",))
        core.require(entry["path"] in allowed, "source_not_authorized")
        core.require(entry["path"] not in selected, "duplicate_source_path")
        expected = allowed[entry["path"]]
        core.require(entry.get("expected_sha256", expected) == expected, "source_snapshot_mismatch")
        entry["expected_sha256"] = expected
        selected.add(entry["path"])
    if revision_import:
        core.require("manual_revision" in payload, "revision_request_required")
        revision = payload["manual_revision"]
        core.require(isinstance(revision, dict) and revision.get("path") in allowed,
                     "revision_not_authorized")
        core.require(revision["path"] not in selected, "revision_source_collision")
        selected.add(revision["path"])
        from .software_import import import_manual
        payload = import_manual(root, {**payload, "delivery": delivery_options}, allowed,
                                check_access=check_access)
        payload.pop("delivery", None)
    if document_output or revision_import:
        screenshots = delivery_options.get("screenshots", [])
        core.require(isinstance(screenshots, list), "screenshots_list_required")
        for image in screenshots:
            core.require_fields(image, ("path", "sha256"))
            core.require(image["path"] in allowed and image["path"] not in selected,
                         "screenshot_not_authorized")
            core.require(image["sha256"] == allowed[image["path"]], "screenshot_snapshot_mismatch")
            selected.add(image["path"])
    if document_output:
        # 成品链先构造完整母本；首尾页只在实际PDF检查之后决定。
        core.require(isinstance(payload.get("pagination"), dict), "pagination_required")
        payload["pagination"] = {**payload["pagination"], "selection": "all"}
    core.require(selected == set(allowed), "authorized_inventory_mismatch")
    if discovery:
        from .software_discovery import discover
        output = discover({"context": context, "authorized_root": str(root),
                           "files": payload["files"], "request": payload,
                           "sensitive_literals": payload.get("sensitive_literals", [])},
                          use_system_time=True)
        check_access()
        core.write_new_json(root, authorization["output"], output)
        return output
    from .software import prepare
    output = prepare({**payload, "authorized_root": str(root), "context": context},
                     use_system_time=True)
    output.update(mode="authorized_local_preparation", sensitivity=context["sensitivity"],
                  host_egress="not_controlled", external_action="not_performed",
                  authorization_binding=args.authorization_sha256, request_binding=request["sha256"],
                  output_scope="internal_only_not_for_submission")
    check_access()
    if document_output:
        from . import software_delivery
        if export:
            core.require(isinstance(package, str) and isinstance(export_approval, dict),
                         "export_request_required")
            return software_delivery.export_package(root, output["artifacts"], delivery_options,
                package, authorization["output"], context=context, approval=export_approval,
                pdf_text_tool=args.pdf_text_tool)
        if args.verify:
            core.require(args.pdf_tool is None, "verify_does_not_convert")
            return software_delivery.verify(root, output["artifacts"], delivery_options,
                authorization["output"], context=context, pdf_text_tool=args.pdf_text_tool)
        return software_delivery.build(root, output["artifacts"], delivery_options,
            authorization["output"], context=context, pdf_tool=args.pdf_tool,
            pdf_text_tool=args.pdf_text_tool)
    core.write_new_json(root, authorization["output"], output)
    return output


def _read_standard_input(args: argparse.Namespace) -> tuple[Path, dict, dict | None, str]:
    """成件与迁移共用读前准入；返回实际输入字节绑定，不认证授权身份。"""
    if args.synthetic:
        core.require(args.authorization is None and args.authorization_sha256 is None,
                     "standard_mode_ambiguous")
    else:
        core.require(args.authorization is not None and args.authorization_sha256 is not None,
                     "standard_authorized_case_unsupported")
    root = Path(args.root).absolute()
    core.require(root.is_dir(), "authorized_root_required")
    if not args.synthetic:
        case_root = root.resolve(strict=True)
        package_root = Path(__file__).resolve().parents[1]
        core.require(not case_root.is_relative_to(package_root) and
                     not package_root.is_relative_to(case_root), "standard_case_root_overlaps_package")
    input_path = core.safe_path(root, args.input, must_exist=False)
    output_path = core.safe_path(root, args.output, must_exist=False)
    core.require(input_path != output_path and not input_path.is_relative_to(output_path),
                 "standard_source_output_collision")
    paths = [root, root / args.input, root / args.output]
    if args.authorization is not None:
        authorization_path = core.safe_path(root, args.authorization)
        core.require(authorization_path != input_path and authorization_path != output_path
                     and not authorization_path.is_relative_to(output_path),
                     "standard_authorization_path_collision")
        paths.append(root / args.authorization)
    # 解析根内路径后仍检查词法父链，不让resolve掩去根内链接或别名原件。
    for path in paths:
        for item in reversed((path, *path.parents)):
            try:
                info = item.lstat()
            except FileNotFoundError:
                core.require(item == path and path == root / args.output, "standard_path_missing")
                continue
            core.require(not stat.S_ISLNK(info.st_mode) and not (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                "standard_link_rejected")
            core.require(stat.S_ISDIR(info.st_mode) or (item == path and
                         stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                         "standard_nonregular_or_aliased_file")
    core.require(output_path.is_dir() if args.verify else not output_path.exists(),
                 "standard_output_missing" if args.verify else "output_exists")
    core.require(output_path.parent.is_dir(), "output_parent_missing")
    core.require(input_path.is_file() and input_path.suffix.lower() == ".json",
                 "standard_json_input_required")
    admission = None
    if args.synthetic:
        with input_path.open("rb") as stream:
            raw = stream.read(5_000_001)
        core.require(len(raw) <= 5_000_000, "standard_input_too_large")
        payload = core.strict_json_loads(raw.decode("utf-8"))
        input_hash = core.sha256_bytes(raw)
    else:
        # 授权描述只承载控制信息；外部固定hash先于其中权限和材料清单生效。
        admission = _read_bound_json(root, args.authorization, args.authorization_sha256, 1_000_000)
        fields = {"root", "output", "payload_hash", "input_hash", "inputs", "sensitivity",
                  "purpose", "permissions", "environment"}
        core.require(set(admission) == fields, "standard_authorization_fields")
        core.require(isinstance(admission["root"], str), "standard_authorization_root")
        declared_root = Path(admission["root"])
        core.require(declared_root.is_absolute() and declared_root.resolve(strict=True) == root.resolve(),
                     "standard_authorization_root")
        core.require(admission["output"] == args.output, "standard_authorization_output")
        inputs = admission["inputs"]
        core.require(isinstance(inputs, dict) and 0 < len(inputs) <= 500
                     and inputs.get(args.input) == admission["input_hash"],
                     "standard_authorization_inputs")
        source_paths = set()
        for relative, expected in inputs.items():
            core.require(isinstance(relative, str) and isinstance(expected, str)
                         and len(expected) == 64 and all(char in "0123456789abcdef" for char in expected),
                         "standard_authorization_inputs")
            source_path = core.safe_path(root, relative, must_exist=False)
            core.require(source_path not in source_paths and source_path != authorization_path
                         and not source_path.is_relative_to(output_path),
                         "standard_authorization_path_collision")
            source_paths.add(source_path)
        core.require(all(isinstance(admission[key], str) and len(admission[key]) == 64 and
                         all(char in "0123456789abcdef" for char in admission[key])
                         for key in ("input_hash", "payload_hash")), "invalid_expected_sha256")
        core.require(admission["sensitivity"] in {"public", "confidential", "restricted"},
                     "standard_authorization_sensitivity")
        core.require(isinstance(admission["purpose"], str) and bool(admission["purpose"].strip())
                     and isinstance(admission["environment"], dict), "standard_authorization_context")

        def check_access():
            now = datetime.now(timezone.utc).isoformat()
            # 真实入口即使标public也逐项核六条路径；未知宿主不能继承合成宽松路径。
            core.preflight(admission["environment"], admission["permissions"],
                           sensitivity="restricted", purpose=admission["purpose"], now=now)
            actions = ("local_process", "copy") + (() if args.verify else ("local_write",))
            for action in actions:
                core.check_permission(admission["permissions"], action=action,
                                      purpose=admission["purpose"], recipient="local_tool", now=now)

        check_access()
        payload = _read_bound_json(root, args.input, admission["input_hash"], 5_000_000)
        input_hash = admission["input_hash"]
        core.require(core.digest(payload) == admission["payload_hash"], "standard_input_binding_changed")
        core.require(payload.get("sensitivity") == admission["sensitivity"],
                     "standard_input_sensitivity_changed")
    core.require(isinstance(payload, dict), "object_required")
    core.require(not {"root", "authorized_root", "admission"}.intersection(payload),
                 "standard_payload_boundary_not_allowed")
    if args.synthetic:
        core.require(payload.get("sensitivity") == "synthetic", "synthetic_only")
    else:
        check_access()
    return root, payload, admission, input_hash


def _prepare_standard(args: argparse.Namespace) -> dict:
    root, payload, admission, _ = _read_standard_input(args)
    core.require(type(payload.get("contract_version")) is int and payload["contract_version"] == 2,
                 "unsupported_standard_contract_version")
    from . import standards_delivery
    operation = standards_delivery.verify if args.verify else standards_delivery.prepare
    if args.synthetic:
        return operation(root, payload, args.output, synthetic=True)
    return operation(root, payload, args.output, synthetic=False, admission=admission)


def _convert_standard_pdf(args: argparse.Namespace) -> dict:
    """目录入口只读固定控制文件；材料集合交给PDF拥有层逐字节准入。"""
    if args.synthetic:
        core.require(args.authorization is None and args.authorization_sha256 is None,
                     "standard_pdf_mode_ambiguous")
    else:
        core.require(args.authorization is not None and args.authorization_sha256 is not None,
                     "standard_pdf_authorization_required")
    from .standard_pdf import convert
    tool_paths = {key: getattr(args, key) for key in
                  ("soffice", "pdfinfo", "pdftotext", "pdftoppm")}
    if args.office_python:
        tool_paths["office_python"] = args.office_python
    if args.synthetic:
        return convert(args.root, args.input, args.output, synthetic=True, tool_paths=tool_paths)
    root = Path(args.root).absolute()
    core.require(root.is_dir(), "authorized_root_required")
    from .standards_delivery import _plain_path
    _plain_path(root)
    authorization_path = core.safe_path(root, args.authorization)
    _plain_path(root / args.authorization, file=True)
    package_path = core.safe_path(root, args.input, must_exist=False)
    output_path = core.safe_path(root, args.output, must_exist=False)
    core.require(not authorization_path.is_relative_to(package_path)
                 and not authorization_path.is_relative_to(output_path),
                 "standard_pdf_authorization_path_collision")
    admission = _read_bound_json(root, args.authorization, args.authorization_sha256, 1_000_000)
    return convert(root, args.input, args.output, synthetic=False,
                   tool_paths=tool_paths, admission=admission)


def _migrate_standard_comments(args: argparse.Namespace) -> None:
    """显式转换旧表式的新副本；报告缺口/损失，不生成决定或阶段确认。"""
    root, payload, _, input_hash = _read_standard_input(args)
    core.require(set(payload) == {"sensitivity", "document"}, "standard_migration_envelope_required")
    document = payload["document"]
    core.require(isinstance(document, dict), "object_required")
    core.require("sensitivity" not in document or document["sensitivity"] == payload["sensitivity"],
                 "standard_input_sensitivity_changed")
    from .standards_contract import import_v1_disposition, export_v1_disposition
    if args.direction == "v1-to-v2":
        report = import_v1_disposition(document, source_sha256=input_hash, source_locator="/document")
    else:
        report = export_v1_disposition(document)
    # 导出也绑定本次读取的原文件；纯函数中的内容digest不能冒充原件字节hash。
    output = {"input_binding": {"sha256": input_hash, "locator": "/document"},
              "mode": "synthetic" if args.synthetic else "authorized_case", "conversion": report}
    core.write_new_json(root, args.output, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools", description="合成辅助与获准本地软件准备；不证明宿主离线")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出83项能力的实际模块可用性")
    software_parser = sub.add_parser("prepare-software", help="按固定授权及清单生成内部软件准备JSON；不外发")
    software_parser.add_argument("--root", required=True)
    software_parser.add_argument("--authorization", required=True)
    software_parser.add_argument("--authorization-sha256", required=True)
    revision_parser = sub.add_parser("import-software-manual", help="将固定授权Markdown/DOCX新稿纳入准备JSON；不覆盖旧包")
    revision_parser.add_argument("--root", required=True)
    revision_parser.add_argument("--authorization", required=True)
    revision_parser.add_argument("--authorization-sha256", required=True)
    revision_parser.add_argument("--build", action="store_true", help="同一授权动作直接重建到新的成品目录")
    revision_parser.add_argument("--pdf-tool")
    revision_parser.add_argument("--pdf-text-tool")
    revision_parser.set_defaults(verify=False)
    discovery_parser = sub.add_parser("discover-software", help="只从逐项授权清单发现候选；不自动确认")
    discovery_parser.add_argument("--root", required=True)
    discovery_parser.add_argument("--authorization", required=True)
    discovery_parser.add_argument("--authorization-sha256", required=True)
    batch_parser = sub.add_parser("software-batch", help="隔离执行固定授权的软件项目；仅输出状态索引")
    batch_parser.add_argument("--root", required=True)
    batch_parser.add_argument("--input", required=True)
    batch_parser.add_argument("--input-sha256", required=True)
    batch_parser.add_argument("--output", required=True)
    standard_parser = sub.add_parser("prepare-standard", help="生成或回验标准v2内部包；真实材料须固定授权与清单")
    standard_parser.add_argument("--synthetic", action="store_true")
    standard_parser.add_argument("--root", required=True)
    standard_parser.add_argument("--input", required=True)
    standard_parser.add_argument("--output", required=True)
    standard_parser.add_argument("--verify", action="store_true")
    standard_parser.add_argument("--authorization", help="根内授权控制JSON；不是身份认证")
    standard_parser.add_argument("--authorization-sha256", help="授权描述原始字节SHA-256，来自受信确认")
    intake_parser = sub.add_parser("standard-intake", help="集中采集固定材料并生成标准v2草稿、索引和缺件清单")
    intake_parser.add_argument("--root", required=True)
    intake_parser.add_argument("--output", required=True, help="不存在的新目录；父目录须存在")
    intake_parser.add_argument("--synthetic", action="store_true")
    migration_parser = sub.add_parser("migrate-standard-comments", help="显式导入或导出旧意见表新副本；保留缺口及有损报告")
    migration_parser.add_argument("--direction", choices=("v1-to-v2", "v2-to-v1"), required=True)
    migration_parser.add_argument("--synthetic", action="store_true")
    migration_parser.add_argument("--root", required=True)
    migration_parser.add_argument("--input", required=True)
    migration_parser.add_argument("--output", required=True)
    migration_parser.add_argument("--authorization", help="根内固定授权控制JSON")
    migration_parser.add_argument("--authorization-sha256", help="来自受信确认的授权描述字节SHA-256")
    migration_parser.set_defaults(verify=False)
    pdf_parser = sub.add_parser("standard-pdf", help="按固定包字节与授权转换标准PDF并取逐页证据；页面观察另计")
    pdf_parser.add_argument("--synthetic", action="store_true")
    pdf_parser.add_argument("--root", required=True)
    pdf_parser.add_argument("--input", required=True, help="已回验的五文书包目录")
    pdf_parser.add_argument("--output", required=True)
    pdf_parser.add_argument("--authorization", help="真实包的根内授权控制JSON")
    pdf_parser.add_argument("--authorization-sha256", help="来自受信确认的控制文件原始字节SHA-256")
    for tool in ("soffice", "pdfinfo", "pdftotext", "pdftoppm"):
        pdf_parser.add_argument("--" + tool, required=True, help="获准本地工具的绝对可执行文件路径")
    pdf_parser.add_argument("--office-python", help="同一Office安装随附Python的绝对路径；用于隔离更新域，不安装")
    document_parser = sub.add_parser("build-software", help="从获准清单生成软件DOCX/PDF内部候选及实际分页报告")
    document_parser.add_argument("--root", required=True)
    document_parser.add_argument("--authorization", required=True)
    document_parser.add_argument("--authorization-sha256", required=True)
    document_parser.add_argument("--pdf-tool", help="已安装soffice绝对路径；不安装")
    document_parser.add_argument("--pdf-text-tool", help="已安装pdftotext绝对路径；回读实际物理页")
    document_parser.add_argument("--verify", action="store_true")
    export_parser = sub.add_parser("export-software", help="按固定文件审批生成本地接收方副本；不发送")
    export_parser.add_argument("--root", required=True)
    export_parser.add_argument("--authorization", required=True)
    export_parser.add_argument("--authorization-sha256", required=True)
    export_parser.add_argument("--pdf-text-tool")
    export_parser.set_defaults(verify=False, pdf_tool=None)
    intake_parser = sub.add_parser("software-intake", help="通过控制台集中收集许可、源码清单和事实，无需手写内部JSON")
    intake_parser.add_argument("--root", required=True)
    intake_parser.add_argument("--output", required=True, help="新的采集目录，不覆盖")
    intake_parser.add_argument("--candidates", action="store_true", help="从获准文件发现候选并集中确认")
    run_parser = sub.add_parser("run", help="读取合成JSON并创建新的结果文件")
    run_parser.add_argument("capability")
    preview_parser = sub.add_parser("preview", help="从合成固定候选生成HTML和JSON；不执行浏览器")
    preview_parser.add_argument("--input", required=True)
    preview_parser.add_argument("--html-output", required=True)
    for command in (run_parser, preview_parser, sub.add_parser("demo", help="内建合成披露演练")):
        command.add_argument("--synthetic", action="store_true")
        command.add_argument("--root", default=".")
        command.add_argument("--output", required=True)
    run_parser.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    preview_html_written = False
    try:
        if args.command == "list":
            print(json.dumps(catalog(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "software-batch":
            root = Path(args.root).resolve(strict=True)
            control = _read_bound_json(root, args.input, args.input_sha256, 1_000_000)
            core.require(set(control) == {"projects"}, "software_batch_control_invalid")
            destination = core.safe_path(root, args.output, must_exist=False)
            core.require(not destination.exists() and destination.parent.is_dir(), "output_exists")
            from .software_batch import run_batch
            report = run_batch(control["projects"])
            core.write_new_json(root, args.output, report)
            print(json.dumps({"status": report["status"]}, ensure_ascii=False))
            return 0 if report["status"] == "completed" else 4
        if args.command == "software-intake":
            from .software_intake import collect, collect_candidates
            operation = collect_candidates if args.candidates else collect
            summary = operation(args.root, args.output)
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        if args.command == "standard-intake":
            from .standard_intake import collect
            summary = collect(args.root, args.output, synthetic=args.synthetic)
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        if args.command == "standard-pdf":
            report = _convert_standard_pdf(args)
            summary = {key: report[key] for key in
                       ("status", "total_documents", "total_pages", "visual_review",
                        "professional_review", "external_action")}
            if "field_refresh" in report:
                summary["field_refresh"] = report["field_refresh"]
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        if args.command == "migrate-standard-comments":
            try:
                _migrate_standard_comments(args)
            except (RuntimeError, OverflowError):
                raise core.ContractError("standard_migration_boundary_invalid") from None
            print("result_written")
            return 0
        if args.command == "prepare-standard":
            try:
                report = _prepare_standard(args)
            except (RuntimeError, OverflowError):
                raise core.ContractError("standard_preparation_boundary_invalid") from None
            print(json.dumps({key: report[key] for key in
                              ("status", "professional_review", "external_action")}, ensure_ascii=False))
            return 0
        if args.command in {"prepare-software", "build-software", "import-software-manual", "discover-software", "export-software"}:
            build_output = args.command in {"build-software", "export-software"} or bool(getattr(args, "build", False))
            try:
                report = _prepare_software(args, document_output=build_output)
            except (RuntimeError, OverflowError):
                # 路径链接环与极端时间转换异常可能含私有路径，不能漏出traceback。
                raise core.ContractError("preparation_boundary_invalid") from None
            if args.command == "export-software":
                print("software_export_written_not_sent")
                return 0
            if build_output:
                print("software_documents_partial" if report["status"] == "partial" else "software_documents_verified_needs_review")
                return 4 if report["status"] == "partial" else 0
            print("result_written")
            return 0
        # 必须先声明，再读取输入；声明不是材料真实性或宿主离线证明。
        core.require(args.synthetic, "synthetic_declaration_required")
        output_path = core.safe_path(args.root, args.output, must_exist=False)
        core.require(not output_path.exists(), "output_exists")
        core.require(output_path.parent.is_dir(), "output_parent_missing")
        if args.command == "preview":
            html_path = core.safe_path(args.root, args.html_output, must_exist=False)
            core.require(html_path != output_path, "preview_output_collision")
            core.require(html_path.suffix.lower() == ".html", "html_output_required")
            core.require(not html_path.exists(), "output_exists")
            core.require(html_path.parent.is_dir(), "output_parent_missing")
        if args.command == "demo":
            output = demo()
        else:
            input_path = core.safe_path(args.root, args.input)
            payload = core.strict_json_loads(input_path.read_text(encoding="utf-8"))
            payload = _confine_payload_roots(payload, args.root)
            if args.command == "preview":
                core.require_fields(payload, ("candidate", "file_id", "context", "width", "height"))
                core.require(payload.get("sensitivity", "synthetic") == "synthetic", "synthetic_only")
                preview = preview_candidate(
                    payload["candidate"], payload["file_id"], payload["context"],
                    width=payload["width"], height=payload["height"], ledger=payload.get("ledger"))
                output = core.result("CORE-07", status="blocked" if preview["issues"] else "needs_review",
                                     artifacts=preview, issues=[{"code": code} for code in preview["issues"]],
                                     checks=["fixed_snapshot_preview_not_browser_execution"])
                output.update(mode="synthetic", host_egress="not_controlled")
                # 双输出不是事务；后续JSON写失败保留本次HTML，不删改可能被其他进程替换的文件。
                rendering.write_preview(args.root, args.html_output, preview)
                preview_html_written = True
            else:
                output = dispatch(args.capability, payload, synthetic=True)
        core.write_new_json(args.root, args.output, output)
        print("result_written")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("input_cancelled", file=sys.stderr)
        return 2
    except core.ContractError as error:
        print("standard_authorized_case_unsupported" if args.command == "prepare-standard" and
              str(error) == "standard_authorized_case_unsupported" else "contract_rejected", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error):
        print("preview_html_retained_json_failed" if preview_html_written else "local_io_failed",
              file=sys.stderr)
        return 3
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print("input_or_contract_invalid", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
