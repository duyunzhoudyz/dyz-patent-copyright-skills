"""R04/R06：专利合成成品与普通阶段确认的薄编排。

正文和附图均由调用者提供；OOXML、质量与保真检查由documents持有。
完整性只核声明的角色/块，不能证明法律要求、自然语言支持或专业通过。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tools import documents
from tools.core import (
    VersionLedger, canonical_bytes, digest, parse_time, require, require_fields,
    safe_path, sha256_bytes, strict_json_loads,
)

VERSION = "1.0"
ROLES = ("claims", "specification", "abstract")
WORKING_NOTICE = "合成示例；内部工作稿，待专业审阅，不得据此提交或外发。"


def _admit(spec, synthetic):
    # 此编排只开放本地合成入口；documents的研究/真实准入不在此转授权。
    require(synthetic is True and isinstance(spec, dict)
            and spec.get("sensitivity") == "synthetic"
            and "research_materials" not in spec, "patent_synthetic_only")
    require(spec.get("business") == "patent", "patent_business_required")
    require(len(canonical_bytes(spec)) <= 5_000_000, "patent_input_size")
    require(spec.get("delivery_stage", "draft") in {"draft", "final"}, "patent_stage_invalid")
    declaration = spec.get("patent_delivery")
    require(isinstance(declaration, dict), "patent_delivery_declaration_required")
    require_fields(declaration, ("project_id", "scope", "purpose", "rules", "notice_block",
                                 "expected_roles", "drawings"))
    for key in ("project_id", "scope", "purpose", "notice_block"):
        require(isinstance(declaration[key], str) and bool(declaration[key].strip()),
                "patent_delivery_text_required")
    rules = declaration["rules"]
    require(isinstance(rules, list) and bool(rules), "patent_rules_required")
    for rule in rules:
        require(isinstance(rule, dict), "patent_rule_invalid")
        require_fields(rule, ("id", "version"))
        require(all(isinstance(rule[key], str) and rule[key].strip() for key in ("id", "version")),
                "patent_rule_invalid")
    roles = declaration["expected_roles"]
    require(isinstance(roles, dict) and set(roles) == set(ROLES), "patent_expected_roles_required")
    for ids in roles.values():
        require(isinstance(ids, list) and all(isinstance(key, str) and key.strip() for key in ids),
                "patent_role_blocks_invalid")
    drawings = declaration["drawings"]
    require(isinstance(drawings, dict) and type(drawings.get("applicable")) is bool,
            "patent_drawings_applicability_required")
    ids = drawings.get("figure_ids")
    require(isinstance(ids, list) and all(isinstance(key, str) and key.strip() for key in ids)
            and len(ids) == len(set(ids)), "patent_figure_ids_invalid")
    if not drawings["applicable"]:
        reason = drawings.get("not_applicable_reason")
        require(isinstance(reason, str) and bool(reason.strip()), "patent_drawings_reason_required")
        require(not ids, "patent_drawings_not_applicable_conflict")
    return declaration


def _inventory(spec, blocks, figures):
    declaration = spec["patent_delivery"]
    by_id = {block["id"]: block for block in blocks}
    notice_id = declaration["notice_block"]
    notice = by_id.get(notice_id, {})
    require(notice.get("audience") == "body" and notice.get("text") == WORKING_NOTICE,
            "patent_working_notice_required")
    issues, assigned, roles = [], {notice_id}, []
    for role, ids in declaration["expected_roles"].items():
        if not ids:
            issues.append({"code": "patent_role_empty", "role": role})
        locations = []
        for identity in ids:
            block = by_id.get(identity)
            if block is None or block["audience"] != "body":
                issues.append({"code": "patent_role_block_missing", "role": role, "block_id": identity})
            elif identity in assigned:
                issues.append({"code": "patent_role_block_reused", "role": role, "block_id": identity})
            else:
                locations.append({key: block[key] for key in
                                  ("id", "source_id", "start_line", "end_line", "text_sha256")})
            assigned.add(identity)
        roles.append({"role": role, "path": "document/body/document.docx", "blocks": locations})
    for block in blocks:
        if block["audience"] == "body" and block["id"] not in assigned:
            issues.append({"code": "patent_body_role_unassigned", "block_id": block["id"]})
    drawings = declaration["drawings"]
    expected = set(drawings["figure_ids"])
    actual = {figure["id"] for figure in figures}
    if expected != actual or drawings["applicable"] and not expected:
        issues.append({"code": "patent_drawings_incomplete", "expected": sorted(expected), "actual": sorted(actual)})
    return roles, issues


def _source_derivations(root, spec, blocks):
    """只核已有取证快照与已回读文件的关联声明，不认证提取或原件真实性。"""
    links = spec["patent_delivery"].get("source_derivations", [])
    require(isinstance(links, list) and len(links) <= 100, "patent_derivations_invalid")
    result = {"status": "bindings_checked" if links else "not_performed",
              "coverage": "declared_scope_only" if links else "not_performed", "records": [],
              "original_verification": "not_performed", "extraction_authenticity": "not_verified",
              "legal_support": "not_assessed", "scope": "caller_declarations_and_byte_bindings_only"}
    sources = {row["id"]: row for row in spec["sources"]}
    dependencies = {row["path"]: row for row in spec.get("dependencies", [])}
    by_id = {block["id"]: block for block in blocks}
    seen, covered = set(), set()
    for link in links:
        require(isinstance(link, dict), "patent_derivation_invalid")
        require_fields(link, ("source_id", "source_sha256", "original_evidence", "method", "scope",
                              "block_ids", "location_status"))
        source_id = link["source_id"]
        require(isinstance(source_id, str) and source_id in sources and source_id not in seen,
                "patent_derivation_source_invalid")
        seen.add(source_id)
        source = sources[source_id]
        require(link["source_sha256"] == source["sha256"], "patent_derived_source_binding_changed")
        evidence = link["original_evidence"]
        require(isinstance(evidence, dict), "patent_original_evidence_required")
        require_fields(evidence, ("evidence_id", "sha256", "size", "path", "source", "locator",
                                  "acquired_at", "sensitivity", "extraction_status", "authenticity"))
        require(evidence["sensitivity"] == "synthetic" and evidence["authenticity"] == "not_verified",
                "patent_original_evidence_boundary")
        require(isinstance(evidence["source"], dict), "patent_original_source_required")
        require_fields(evidence["source"], ("id", "version", "origin", "level"))
        require(all(isinstance(evidence["source"][key], str) and evidence["source"][key].strip()
                    for key in ("id", "version", "origin", "level")), "patent_original_source_required")
        require(isinstance(evidence["path"], str) and evidence["path"] in dependencies,
                "patent_original_dependency_missing")
        require(evidence["sha256"] == dependencies[evidence["path"]]["sha256"]
                and evidence["evidence_id"] == "ev-" + digest({"source_id": evidence["source"]["id"],
                                                               "sha256": evidence["sha256"]}),
                "patent_original_evidence_binding_changed")
        # 字节核验由前置resolve_document完成；这里核快照身份和关联，避免另造抽取器。
        original = safe_path(root, evidence["path"])
        require(original != safe_path(root, source["path"]), "patent_original_derived_file_alias")
        require(type(evidence["size"]) is int and evidence["size"] == original.stat().st_size,
                "patent_original_evidence_size_changed")
        parse_time(evidence["acquired_at"])
        require(isinstance(evidence["locator"], str) and evidence["locator"].strip(), "patent_original_locator_required")
        require(evidence["extraction_status"] in {"not_checked", "complete", "partial", "unreadable",
                                                  "ocr_uncertain", "missing_pages"}, "invalid_extraction_status")
        require(link["location_status"] in {"located", "unlocated"}, "patent_derivation_location_invalid")
        require(all(isinstance(link[key], str) and link[key].strip() for key in ("method", "scope")),
                "patent_extraction_description_required")
        ids = link["block_ids"]
        require(isinstance(ids, list) and bool(ids) and all(isinstance(key, str) for key in ids)
                and len(ids) == len(set(ids)), "patent_derivation_blocks_invalid")
        require(all(key in by_id and by_id[key]["source_id"] == source_id for key in ids),
                "patent_derivation_blocks_mismatch")
        covered.update(ids)
        if evidence["extraction_status"] != "complete" or link["location_status"] != "located":
            result["coverage"] = "partial"
        result["records"].append({"source_id": source_id, "source_path": source["path"],
            "source_sha256": source["sha256"], "original_path": evidence["path"],
            "original_sha256": evidence["sha256"], "evidence_id": evidence["evidence_id"],
            "original_locator": evidence["locator"], "extraction_status": evidence["extraction_status"],
            "location_status": link["location_status"], "method": link["method"], "scope": link["scope"],
            "blocks": [{key: by_id[identity][key] for key in
                        ("id", "source_id", "start_line", "end_line", "text_sha256")} for identity in ids]})
    expected = {identity for ids in spec["patent_delivery"]["expected_roles"].values() for identity in ids}
    if links and not expected.issubset(covered):
        result["coverage"] = "partial"
    result["unmapped_blocks"] = sorted(expected - covered)
    return result


def _assessment(spec, blocks, figures, checked, derivations):
    roles, issues = _inventory(spec, blocks, figures)
    complete = not issues
    fidelity = checked.get("fidelity", {}).get("status", "not_performed")
    quality = checked["quality"]
    final_text_gate = checked.get("final_text_gate", {"status": "not_performed"})
    if final_text_gate["status"] != "checked":
        issues.append({"code": "patent_final_text_not_checked", "state": final_text_gate["status"]})
    if fidelity != "checked":
        issues.append({"code": "patent_fidelity_not_checked", "state": fidelity})
    if derivations["coverage"] == "partial":
        issues.append({"code": "patent_source_derivation_incomplete", "state": "partial"})
    if quality["status"] != "checked":
        issues.append({"code": "patent_quality_needs_review", "state": quality["status"],
                       "report": "document/internal/quality-review.json"})
    ready = complete and not issues
    require(spec.get("delivery_stage", "draft") != "final" or ready,
            "patent_final_requirements_missing")
    return {"roles": roles, "drawings": spec["patent_delivery"]["drawings"],
            "completeness": "complete_declared_roles" if complete else "incomplete",
            "fidelity": fidelity, "quality": quality, "issues": issues, "source_derivations": derivations,
            "final_text_gate": final_text_gate,
            "checks_ready": ready,
            "delivery_state": "candidate_needs_professional_review" if spec.get("delivery_stage") == "final"
                              else "internal_draft" if complete else "incomplete_internal_draft"}


def _report(spec, assessment):
    return {"input_sha256": digest(spec), "declaration": spec["patent_delivery"], **assessment,
            "completeness_scope": "declared_nonempty_body_blocks_and_figure_members_not_legal_sufficiency",
            "semantic_review": "not_performed", "visual_review": "not_performed",
            "professional_review": "not_performed", "external_action": "not_performed"}


def _manifest(spec, assessment, files):
    return {"generator": "dyz-patent-delivery", "generator_version": VERSION,
            "project_id": spec["patent_delivery"]["project_id"], "version": spec["version"],
            "input_sha256": digest(spec), "mode": "synthetic", "status": "needs_review",
            **assessment, "files": files, "visual_review": "not_performed",
            "professional_review": "not_performed", "external_action": "not_performed",
            "official_status": "not_asserted", "identity_verification": "caller_responsibility",
            "disclosure_scope": "internal_candidate_not_approved_for_external_use"}


def _members(target):
    files = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(target).as_posix()
        if name == "manifest.json":
            continue
        raw = safe_path(target, name).read_bytes()
        purpose = "manuscript_candidate" if name.startswith("document/body/") else "internal_only"
        files.append({"path": name, "sha256": sha256_bytes(raw), "bytes": len(raw), "purpose": purpose})
    return files


def prepare(root, spec, output, *, synthetic=False):
    """装配新目录中的完整调用者稿件；缺件可交草稿，final须有当前绑定检查。"""
    _admit(spec, synthetic)
    blocks, figures = documents.resolve_document(root, spec)
    derivations = _source_derivations(root, spec, blocks)
    _, issues = _inventory(spec, blocks, figures)
    require(spec.get("delivery_stage", "draft") != "final"
            or not issues and "fidelity" in spec and derivations["coverage"] != "partial",
            "patent_final_requirements_missing")
    # 创建目录前复用文档拥有层门禁，坏稿不留下可误用的成品目录。
    documents._patent_final_gate(spec, [block for block in blocks if block["audience"] == "body"])
    target = safe_path(root, output, must_exist=False)
    require(target.parent.is_dir(), "output_parent_missing")
    require(not target.exists(), "output_exists")
    target.mkdir()
    child = (Path(output) / "document").as_posix()
    documents.build(root, spec, child, synthetic=True)
    checked = documents.verify(root, spec, child, synthetic=True)
    assessment = _assessment(spec, blocks, figures, checked, derivations)
    (target / "internal").mkdir()
    for name, value in (("input.json", spec), ("delivery-review.json", _report(spec, assessment))):
        with (target / "internal" / name).open("xb") as stream:
            stream.write(canonical_bytes(value) + b"\n")
    manifest = _manifest(spec, assessment, _members(target))
    # 只有所有实物回验完成才落外层清单；失败现场不冒充完整包，也不清理用户材料。
    with (target / "manifest.json").open("xb") as stream:
        stream.write(canonical_bytes(manifest) + b"\n")
    return manifest


def verify(root, spec, output, *, synthetic=False):
    """重读当前源与实际包；清单自报hash、旧检查或旧确认均不能代替回验。"""
    _admit(spec, synthetic)
    blocks, figures = documents.resolve_document(root, spec)
    derivations = _source_derivations(root, spec, blocks)
    target = safe_path(root, output)
    checked = documents.verify(root, spec, (Path(output) / "document").as_posix(), synthetic=True)
    assessment = _assessment(spec, blocks, figures, checked, derivations)
    for name, value in (("input.json", spec), ("delivery-review.json", _report(spec, assessment))):
        require(safe_path(target, "internal/" + name).read_bytes() == canonical_bytes(value) + b"\n",
                "patent_internal_report_changed")
    child_manifest = strict_json_loads(safe_path(target, "document/manifest.json").read_text(encoding="utf-8"))
    expected = {"document/" + row["path"] for row in child_manifest["files"]}
    expected.update({"document/manifest.json", "internal/input.json", "internal/delivery-review.json"})
    files = _members(target)
    require({row["path"] for row in files} == expected, "patent_package_members_changed")
    manifest = _manifest(spec, assessment, files)
    raw = canonical_bytes(manifest) + b"\n"
    require(safe_path(target, "manifest.json").read_bytes() == raw, "patent_manifest_changed")
    return {**manifest, "file_hashes_equal": True, "manifest_sha256": sha256_bytes(raw)}


def register_package(ledger, root, spec, output, *, synthetic=False):
    """实物回验后更新项目当前选择；依赖变化使既有确认失效而不清除历史。"""
    require(isinstance(ledger, VersionLedger), "patent_ledger_required")
    checked = verify(root, spec, output, synthetic=synthetic)
    prefix = "patent/" + digest(spec["patent_delivery"]["project_id"])[:24]
    dependencies = []
    nodes = {"sources": {"sources": spec["sources"], "dependencies": spec.get("dependencies", [])},
             "manuscript": {"blocks": spec["blocks"], "fidelity": spec.get("fidelity")},
             "figures": spec.get("figures", []), "scope": spec["patent_delivery"]}
    for name, value in nodes.items():
        identity = prefix + "/" + name
        ledger.put(identity, value)
        dependencies.append(identity)
    selection_id = prefix + "/selection"
    selection = ledger.put(selection_id, {"input_sha256": digest(spec),
        "root": str(Path(root).resolve()), "output": output,
        "manifest_sha256": checked["manifest_sha256"]}, dependencies=dependencies)
    package_id = prefix + "/package/" + checked["manifest_sha256"]
    ledger.put(package_id, {"manifest_sha256": checked["manifest_sha256"],
                           "checks_ready": checked["checks_ready"]}, dependencies=[selection_id])
    return {"selection_id": selection_id, "selection_hash": selection["hash"],
            "package_id": package_id, "manifest_sha256": checked["manifest_sha256"]}


def _binding_current(ledger, binding, root, spec, output, checked):
    require(isinstance(binding, dict), "patent_confirmation_binding_required")
    require_fields(binding, ("selection_id", "selection_hash", "package_id", "manifest_sha256"))
    selection_id, package_id = binding["selection_id"], binding["package_id"]
    require(selection_id in ledger.records and package_id in ledger.records,
            "patent_confirmation_binding_missing")
    selection = ledger.records[selection_id][-1]
    current = {"input_sha256": digest(spec), "root": str(Path(root).resolve()),
               "output": output, "manifest_sha256": checked["manifest_sha256"]}
    package = ledger.records[package_id][-1]
    return (ledger.is_current(selection_id) and ledger.is_current(package_id)
            and selection["hash"] == binding["selection_hash"] and selection["payload"] == current
            and package["dependencies"].get(selection_id) == selection["hash"]
            and package["payload"]["manifest_sha256"] == binding["manifest_sha256"] == checked["manifest_sha256"])


def record_confirmation(ledger, binding, confirmation, root, spec, output, *, synthetic=False):
    """登记普通内部确认并当场回验文件；不调用professional add_review。"""
    require(isinstance(ledger, VersionLedger), "patent_ledger_required")
    require(isinstance(confirmation, dict), "patent_confirmation_required")
    require_fields(confirmation, ("id", "actor_id", "actor_type", "stage", "decision", "conditions",
                                  "confirmed_at", "manifest_sha256"))
    require(all(isinstance(confirmation[key], str) and confirmation[key].strip()
                for key in ("id", "actor_id", "confirmed_at")), "patent_confirmation_identity_required")
    require(confirmation["actor_type"] == "human", "human_confirmation_required")
    require(confirmation["stage"] == "internal_review", "patent_confirmation_stage_invalid")
    require(confirmation["decision"] in {"accepted", "conditional", "rejected"}, "patent_confirmation_decision")
    conditions = confirmation["conditions"]
    require(isinstance(conditions, list) and all(isinstance(item, str) and item.strip() for item in conditions),
            "patent_confirmation_conditions_required")
    require(confirmation["decision"] != "conditional" or bool(conditions), "patent_confirmation_conditions_required")
    require(parse_time(confirmation["confirmed_at"]) <= datetime.now(timezone.utc), "patent_confirmation_in_future")
    checked = verify(root, spec, output, synthetic=synthetic)
    require(_binding_current(ledger, binding, root, spec, output, checked), "patent_confirmation_binding_stale")
    require(confirmation["manifest_sha256"] == checked["manifest_sha256"], "patent_confirmation_manifest_changed")
    record_id = binding["selection_id"].rsplit("/", 1)[0] + "/confirmation/" + digest(confirmation["id"])
    require(record_id not in ledger.records, "patent_confirmation_already_recorded")
    ledger.put(record_id, {"kind": "stage_confirmation", "event": confirmation, "binding": binding,
        "identity_verification": "caller_responsibility", "professional_review": "not_performed",
        "external_action": "not_performed"}, dependencies=[binding["selection_id"], binding["package_id"]])
    return record_id


def confirmation_status(ledger, record_id, root, spec, output, *, synthetic=False):
    """绑定当前不等于接受；附条件即使标accepted也须新确认，绝不自动放行。"""
    require(isinstance(ledger, VersionLedger), "patent_ledger_required")
    checked = verify(root, spec, output, synthetic=synthetic)
    require(record_id in ledger.records, "patent_confirmation_missing")
    record = ledger.records[record_id][-1]["payload"]
    require(record.get("kind") == "stage_confirmation", "patent_confirmation_kind")
    current = ledger.is_current(record_id) and _binding_current(ledger, record["binding"], root, spec, output, checked)
    event = record["event"]
    return {"binding_current": current, "decision": event["decision"], "conditions": list(event["conditions"]),
            "may_continue": current and event["decision"] == "accepted" and not event["conditions"] and checked["checks_ready"],
            "continuation_scope": "local_internal_review_only", "identity_verification": "caller_responsibility",
            "professional_review": "not_performed", "external_action": "not_performed"}
