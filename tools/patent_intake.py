"""Phase B3: 专利三轴材料取材与获准真实/合成双产物成品链。

支持：
1. 三轴任务分类：source_kind (disclosure/paper/code) × task_kind (new_draft/revision/oa_response)
   × tech_domain (software_control/mechanical/circuit/chem_bio/design)；
2. 术语/公式/图去向表 (term_formula_figure_map)，采用目标章节白名单严格隔离
   paper_only / prior_art_review / pending_confirmation 与本案实施例/权项；
3. 同时支持 synthetic 合成示范与 authorized_case 获准真实材料（先验准入再处理敏感材料，
   并复用 documents._case_path 防链接/硬链接）；
4. 独立分层落盘：`document-pack/` 保持纯 documents.build 结构以保证 documents.verify()
   完整通过，外层保存 intake/IR 报告并提供 verify_patent_pack() 联合回验。
"""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path

from tools import documents, omml, patent_ir
from tools.core import (
    ContractError, canonical_bytes, is_reserved_windows_name, require, require_fields, safe_path, sha256_bytes,
    strict_json_loads,
)

VERSION = "1.1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_KINDS = frozenset({"disclosure", "paper", "code"})
TASK_KINDS = frozenset({"new_draft", "revision", "oa_response"})
TECH_DOMAINS = frozenset({"software_control", "mechanical", "circuit", "chem_bio", "design"})
ORIGIN_SCOPES = frozenset({"invention_embodiment", "paper_only", "prior_art_review", "pending_confirmation"})
MATERIAL_ROLES = frozenset({"original", "disclosure", "paper", "code", "prior_art", "figure", "supporting"})
ALLOWED_NON_INVENTION_SECTIONS = frozenset({"background", "prior_art_comparison", "internal_only"})
ALLOWED_INVENTION_SECTIONS = frozenset({
    "claims", "embodiment", "summary_of_invention", "abstract",
    "drawings", "detailed_description", "background", "prior_art_comparison", "internal_only",
})


def _safe_rel_path(value: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), "patent_material_path_invalid")
    norm = value.replace("\\", "/")
    require(
        not norm.startswith("/") and ":" not in norm and "\x00" not in norm
        and all(part and not part.endswith((".", " ")) and not is_reserved_windows_name(part)
                for part in norm.split("/")),
        "patent_material_path_invalid",
    )
    return norm


def _spec_material_refs(document_spec: dict) -> list[tuple[str, str, bool]]:
    refs = []
    for key in ("sources", "dependencies"):
        raw_list = document_spec.get(key, [])
        require(isinstance(raw_list, list), "patent_spec_material_invalid")
        for item in raw_list:
            require(isinstance(item, dict) and isinstance(item.get("path"), str)
                    and isinstance(item.get("sha256"), str), "patent_spec_material_invalid")
            refs.append((_safe_rel_path(item["path"]), item["sha256"], key == "sources"))
    raw_figs = document_spec.get("figures", [])
    require(isinstance(raw_figs, list), "patent_spec_material_invalid")
    for fig in raw_figs:
        require(isinstance(fig, dict), "patent_spec_material_invalid")
        for subkey in ("png", "svg"):
            sub = fig.get(subkey)
            require(isinstance(sub, dict) and isinstance(sub.get("path"), str)
                    and isinstance(sub.get("sha256"), str), "patent_spec_material_invalid")
            refs.append((_safe_rel_path(sub["path"]), sub["sha256"], False))
    return refs


def _check_spec_materials(document_spec, inventory, *, verifying=False):
    by_path = {m["path"]: m["sha256"] for m in inventory["materials"]}
    prior_art_hashes = {m["sha256"] for m in inventory["materials"] if m["role"] == "prior_art"}
    for path, sha, body_source in _spec_material_refs(document_spec):
        if not verifying:
            require(path in by_path, "patent_source_not_in_intake_materials")
        require(by_path.get(path) == sha, "patent_pack_inventory_source_mismatch" if verifying
                else "patent_source_intake_hash_mismatch")
        require(not body_source or sha not in prior_art_hashes, "patent_prior_art_body_source_forbidden")


def _pack_admission(root, spec, admission, out_rel):
    if admission is None:
        return None, None
    # 外层准入覆盖所有产物及源文件重叠检查；内层权限不扩展，唯一路径由外层派生。
    accepted = documents.check_document_admission(root, spec, admission, output=out_rel)
    materials = {_safe_rel_path(row["path"]): row["sha256"] for row in accepted["materials"]}
    return {**admission, "output": f"{out_rel}/document-pack"}, materials


def _check_ir_materials(bindings: list, inventory: dict) -> None:
    require(isinstance(bindings, list) and bool(bindings), "ir_documents_required")
    roles_by_hash = {}
    for material in inventory["materials"]:
        roles_by_hash.setdefault(material["sha256"], set()).add(material["role"])
    for binding in bindings:
        require(isinstance(binding, dict) and isinstance(binding.get("sha256"), str)
                and binding["sha256"] in roles_by_hash, "patent_ir_document_not_admitted")
        roles = roles_by_hash[binding["sha256"]]
        role = binding.get("role")
        require("prior_art" not in roles or role == "prior_art",
                "patent_ir_prior_art_role_mismatch")
        require(isinstance(role, str) and roles == {role} and role not in {"supporting", "figure"},
                "patent_ir_material_role_mismatch")


def _load_pack_json(raw):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ContractError("patent_pack_file_not_utf8") from None
    return strict_json_loads(text)


def _write_outer_json(root, relative, value, *, guarded):
    raw = canonical_bytes(value) + b"\n"
    require(len(raw) <= documents.MAX_BYTES, "patent_pack_file_invalid")
    resolve = documents._case_path if guarded else safe_path
    target = resolve(root, relative, must_exist=False)
    with target.open("xb") as stream:
        if guarded:
            opened = os.fstat(stream.fileno())
            seen = resolve(root, relative).stat()
            require(opened.st_nlink == 1 and os.path.samestat(opened, seen), "patent_pack_file_replaced_during_write")
        stream.write(raw)
    return sha256_bytes(raw)


def build_material_inventory(
    payload: dict,
    *,
    root: str | Path | None = None,
    guarded: bool = False,
    allowed_materials: dict[str, str] | None = None,
) -> dict:
    """生成三轴分类与术语/公式/图去向清单，按白名单严格隔离非本案综述与待确认内容。"""
    require(isinstance(payload, dict), "patent_intake_payload_required")
    require_fields(payload, ("project_id", "source_kind", "task_kind", "tech_domain", "materials"))
    require(isinstance(payload["project_id"], str) and bool(payload["project_id"].strip()), "patent_project_id_required")
    require(isinstance(payload["source_kind"], str) and payload["source_kind"] in SOURCE_KINDS, "patent_source_kind_invalid")
    require(isinstance(payload["task_kind"], str) and payload["task_kind"] in TASK_KINDS, "patent_task_kind_invalid")
    require(isinstance(payload["tech_domain"], str) and payload["tech_domain"] in TECH_DOMAINS, "patent_tech_domain_invalid")

    materials = payload["materials"]
    require(isinstance(materials, list) and bool(materials), "patent_materials_required")
    material_roles: dict[str, str] = {}
    seen_paths: set[str] = set()
    material_bindings: list[dict] = []
    # 先全量校验字段、唯一路径与准入白名单，全部合法后再读取任何文件内容（杜绝未准入预读与重复路径覆盖）。
    for item in materials:
        require(isinstance(item, dict), "patent_material_object_required")
        require_fields(item, ("id", "path", "sha256", "role"))
        mid = item["id"]
        require(isinstance(mid, str) and bool(mid.strip()) and mid not in material_roles, "patent_material_duplicate")
        rel_path = _safe_rel_path(item["path"])
        require(rel_path not in seen_paths, "patent_material_path_duplicate")
        require(isinstance(item["sha256"], str) and SHA256_RE.fullmatch(item["sha256"]) is not None,
                "patent_material_sha256_invalid")
        require(isinstance(item["role"], str) and item["role"] in MATERIAL_ROLES, "patent_material_role_invalid")
        if allowed_materials is not None:
            require(allowed_materials.get(rel_path) == item["sha256"], "patent_material_not_admitted")
        material_roles[mid] = item["role"]
        seen_paths.add(rel_path)
        material_bindings.append({"id": mid, "path": rel_path, "sha256": item["sha256"], "role": item["role"]})

    if root is not None:
        for binding in material_bindings:
            documents._read(root, {"path": binding["path"], "sha256": binding["sha256"]}, guarded=guarded)

    entries = payload.get("term_formula_figure_map", [])
    require(isinstance(entries, list), "patent_tff_map_list_required")
    mapped, issues = [], []
    seen_entry_ids: set[str] = set()
    for row in entries:
        require(isinstance(row, dict), "patent_tff_row_required")
        require_fields(row, ("id", "kind", "label", "origin_scope", "source_material_id", "target_section"))
        eid = row["id"]
        require(isinstance(eid, str) and bool(eid.strip()) and eid not in seen_entry_ids, "patent_tff_id_invalid")
        seen_entry_ids.add(eid)
        require(isinstance(row["kind"], str) and row["kind"] in {"term", "formula", "figure"}, "patent_tff_kind_invalid")
        require(isinstance(row["origin_scope"], str) and row["origin_scope"] in ORIGIN_SCOPES, "patent_tff_origin_invalid")
        mid = row["source_material_id"]
        require(isinstance(mid, str) and mid in material_roles, "patent_tff_source_unknown")
        require(isinstance(row["target_section"], str) and bool(row["target_section"].strip()),
                "patent_tff_target_section_invalid")
        norm_section = row["target_section"].strip().lower()

        omml_status = "not_applicable"
        if row["kind"] == "formula" and row.get("latex") is not None:
            try:
                el = omml.latex_to_omml_element(row["latex"])
                inspected = omml.inspect_omml(el)
                omml_status = "valid_omml" if inspected["valid"] else "invalid_omml"
                if not inspected["valid"]:
                    issues.append({"code": "patent_formula_omml_invalid", "id": eid, "details": inspected["issues"]})
            except ContractError as exc:
                omml_status = "invalid_omml"
                issues.append({"code": "patent_formula_omml_invalid", "id": eid, "details": [str(exc)]})

        # 严格按白名单校验目标章节：未知章节名或非本案材料/待确认项进入非允许章节一律阻断！
        if norm_section not in ALLOWED_INVENTION_SECTIONS:
            issues.append({
                "code": "patent_tff_target_section_unknown",
                "id": eid,
                "target_section": row["target_section"],
            })
        elif row["origin_scope"] in {"paper_only", "prior_art_review", "pending_confirmation"} and (
            norm_section not in ALLOWED_NON_INVENTION_SECTIONS
        ):
            issues.append({
                "code": "patent_non_invention_material_targeted_to_claims_or_embodiment",
                "id": eid,
                "origin_scope": row["origin_scope"],
                "target_section": norm_section,
            })
        if material_roles[mid] == "prior_art" and (
            row["origin_scope"] == "invention_embodiment" or norm_section not in {"background", "prior_art_comparison"}
        ):
            issues.append({"code": "patent_prior_art_invalid_destination", "id": eid, "target_section": norm_section})
        mapped.append({**copy.deepcopy(row), "target_section": norm_section, "omml_status": omml_status})

    return {
        "schema": "dyz-patent-intake-inventory-v1",
        "version": VERSION,
        "project_id": payload["project_id"],
        "axes": {
            "source_kind": payload["source_kind"],
            "task_kind": payload["task_kind"],
            "tech_domain": payload["tech_domain"],
        },
        "material_count": len(material_bindings),
        "materials": material_bindings,
        "term_formula_figure_map": mapped,
        "issues": issues,
        "status": "blocked" if issues else "needs_review",
        "professional_review": "not_performed",
    }


def build_patent_pack(
    root: str | Path,
    *,
    intake_payload: dict,
    document_spec: dict,
    output: str,
    ir_payload: dict | None = None,
    synthetic: bool = False,
    admission: dict | None = None,
) -> dict:
    """统一执行三轴取材审查 + 可选 IR 预检 + documents 双产物 Word 审阅包装配。

    将 documents.build 产物隔离于 <output>/document-pack/，保持 documents.verify() 严格成员完整。
    真实模式的 admission["output"] 绑定本函数收到的外层 output，而不是 document-pack 子目录。
    将返回值的 canonical_bytes 加一行换行后计算 SHA-256，可作为独立保管的验包锚点。
    """
    require(type(synthetic) is bool, "patent_synthetic_flag_invalid")
    require(synthetic ^ (admission is not None), "patent_mode_ambiguous")
    require(isinstance(document_spec, dict) and document_spec.get("business") == "patent",
            "patent_document_spec_required")

    out_rel = _safe_rel_path(output.rstrip("/\\") if isinstance(output, str) else output)
    doc_output_rel = f"{out_rel}/document-pack"

    # 获准真实模式先过准入边界，绝不在准入前探测输出路径或读取敏感业务材料与 IR
    inner_admission, admitted_map = _pack_admission(root, document_spec, admission, out_rel)
    guarded = admission is not None
    resolve = documents._case_path if guarded else safe_path
    out_dir = resolve(root, out_rel, must_exist=False)
    require(not out_dir.exists() and out_dir.parent.is_dir(), "patent_pack_output_exists_or_parent_missing")

    inventory = build_material_inventory(
        intake_payload, root=root, guarded=guarded, allowed_materials=admitted_map,
    )
    require(inventory["status"] != "blocked", "patent_intake_inventory_blocked")

    if ir_payload is not None:
        require(isinstance(ir_payload, dict), "ir_payload_object_required")
        _check_ir_materials(ir_payload.get("documents"), inventory)
    _check_spec_materials(document_spec, inventory)

    ir_report = None
    if ir_payload is not None:
        ir_report = patent_ir.validate_ir(ir_payload)
        require(ir_report["ready_for_prose_drafting"], "patent_ir_blocked")
        require(ir_report["project_id"] == intake_payload["project_id"], "patent_ir_project_id_mismatch")

    out_dir.mkdir(exist_ok=False)
    out_identity = out_dir.stat()
    try:
        doc_result = documents.build(
            root, document_spec, doc_output_rel, synthetic=synthetic, admission=inner_admission,
        )
        inv_rel = f"{out_rel}/patent-intake-inventory.json"
        inv_sha = _write_outer_json(root, inv_rel, inventory, guarded=guarded)

        ir_rel = None
        ir_sha = None
        if ir_report is not None:
            ir_rel = f"{out_rel}/claim-fact-ir-report.json"
            ir_sha = _write_outer_json(root, ir_rel, ir_report, guarded=guarded)

        doc_manifest_path = resolve(root, f"{doc_output_rel}/manifest.json")
        summary = {
            "schema": "dyz-patent-pack-summary-v1",
            "version": VERSION,
            "mode": "synthetic" if synthetic else "authorized_case",
            "project_id": intake_payload["project_id"],
            "axes": inventory["axes"],
            "document_pack_dir": doc_output_rel,
            "document_manifest_sha256": sha256_bytes(doc_manifest_path.read_bytes()),
            "document_status": doc_result["status"],
            "ir_status": ir_report["status"] if ir_report else "not_supplied",
            "final_text_gate": doc_result.get("final_text_gate", {"status": "not_performed"}),
            "output_dir": out_rel,
            "body_docx": f"{doc_output_rel}/body/document.docx",
            "internal_inventory": inv_rel,
            "internal_inventory_sha256": inv_sha,
            "ir_report": ir_rel,
            "ir_report_sha256": ir_sha,
            "professional_review": "not_performed",
            "external_action": "not_performed",
        }
        _write_outer_json(root, f"{out_rel}/patent-pack-summary.json", summary, guarded=guarded)
        return summary
    except BaseException:
        import shutil
        try:
            if resolve(root, out_rel) == out_dir and os.path.samestat(out_identity, out_dir.lstat()):
                shutil.rmtree(out_dir, ignore_errors=True)
        except (ContractError, OSError):
            pass  # 不清理已被替换或无法确认身份的目录。
        raise


def verify_patent_pack(
    root: str | Path,
    *,
    document_spec: dict,
    output: str,
    synthetic: bool = False,
    admission: dict | None = None,
    expected_summary_sha256: str | None = None,
    intake_payload: dict | None = None,
    ir_payload: dict | None = None,
) -> dict:
    """回验内外层包；包外摘要哈希或两份原始输入可完整锚定，单份原始输入仅锚定相应报告。

    仅完成包内自洽检查时，兼容状态 verified_needs_review 不代表防篡改；以 integrity 字段区分。
    无 IR 的成品包应使用包外摘要哈希来锚定 IR 缺席。
    """
    require(type(synthetic) is bool, "patent_synthetic_flag_invalid")
    require(synthetic ^ (admission is not None), "patent_mode_ambiguous")
    require(isinstance(document_spec, dict) and document_spec.get("business") == "patent",
            "patent_document_spec_required")
    out_rel = _safe_rel_path(output.rstrip("/\\") if isinstance(output, str) else output)
    doc_output_rel = f"{out_rel}/document-pack"
    guarded = admission is not None
    require(expected_summary_sha256 is None or (isinstance(expected_summary_sha256, str)
            and SHA256_RE.fullmatch(expected_summary_sha256) is not None), "patent_pack_summary_anchor_invalid")
    inner_admission, admitted_map = _pack_admission(root, document_spec, admission, out_rel)

    try:
        doc_verified = documents.verify(
            root, document_spec, doc_output_rel, synthetic=synthetic, admission=inner_admission,
        )
    except UnicodeDecodeError:
        raise ContractError("patent_pack_file_not_utf8") from None

    def _read_outer_bytes(rel: str) -> bytes:
        p = documents._case_path(root, rel) if guarded else safe_path(root, rel)
        require(p.is_file() and p.stat().st_size <= documents.MAX_BYTES, "patent_pack_file_invalid")
        if guarded:
            before = p.stat()
            stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)
            with p.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                require(opened.st_nlink == 1 and stamp(before) == stamp(opened),
                        "patent_pack_file_replaced_during_read")
                raw = stream.read(documents.MAX_BYTES + 1)
                finished = os.fstat(stream.fileno())
            after = documents._case_path(root, rel).stat()
            require(len(raw) <= documents.MAX_BYTES and stamp(before) == stamp(opened) == stamp(finished) == stamp(after),
                    "patent_pack_file_replaced_during_read")
            return raw
        with p.open("rb") as stream:
            raw = stream.read(documents.MAX_BYTES + 1)
        require(len(raw) <= documents.MAX_BYTES, "patent_pack_file_invalid")
        return raw

    out_dir = documents._case_path(root, out_rel) if guarded else safe_path(root, out_rel)
    require(out_dir.is_dir(), "patent_pack_output_missing")

    summary_raw = _read_outer_bytes(f"{out_rel}/patent-pack-summary.json")
    summary_sha = sha256_bytes(summary_raw)
    if expected_summary_sha256 is not None:
        require(summary_sha == expected_summary_sha256, "patent_pack_summary_anchor_mismatch")
    summary = _load_pack_json(summary_raw)
    expected_summary_keys = {
        "schema", "version", "mode", "project_id", "axes", "document_pack_dir",
        "document_manifest_sha256", "document_status", "ir_status", "final_text_gate",
        "output_dir", "body_docx", "internal_inventory", "internal_inventory_sha256",
        "ir_report", "ir_report_sha256", "professional_review", "external_action",
    }
    require(
        isinstance(summary, dict)
        and set(summary) == expected_summary_keys
        and summary.get("schema") == "dyz-patent-pack-summary-v1"
        and summary.get("version") == VERSION,
        "patent_pack_summary_invalid",
    )
    if expected_summary_sha256 is None and intake_payload is not None and ir_payload is not None:
        require(summary_raw == canonical_bytes(summary) + b"\n", "patent_pack_summary_anchor_mismatch")
    expected_mode = "synthetic" if synthetic else "authorized_case"
    require(summary.get("mode") == expected_mode, "patent_pack_mode_mismatch")
    require(summary.get("output_dir") == out_rel, "patent_pack_layout_invalid")
    require(summary.get("document_pack_dir") == doc_output_rel, "patent_pack_layout_invalid")
    require(summary.get("body_docx") == f"{doc_output_rel}/body/document.docx", "patent_pack_layout_invalid")
    require(summary.get("internal_inventory") == f"{out_rel}/patent-intake-inventory.json",
            "patent_pack_layout_invalid")
    require(summary["ir_report"] is None or summary["ir_report"] == f"{out_rel}/claim-fact-ir-report.json",
            "patent_pack_layout_invalid")
    require(ir_payload is None or summary["ir_report"] is not None, "patent_pack_ir_report_missing")
    require(summary.get("professional_review") == "not_performed"
            and summary.get("external_action") == "not_performed"
            and summary.get("document_status") == "needs_review",
            "patent_pack_summary_state_invalid")

    # 外层目录成员应与已核对的摘要匹配；单靠成员集合不能发现同步改写摘要。
    expected_entries = {"document-pack", "patent-pack-summary.json", "patent-intake-inventory.json"}
    if summary.get("ir_report") is not None:
        expected_entries.add("claim-fact-ir-report.json")
    actual_entries = {child.name for child in out_dir.iterdir()}
    require(actual_entries == expected_entries, "patent_pack_unexpected_members")

    doc_manifest_raw = _read_outer_bytes(f"{doc_output_rel}/manifest.json")
    require(sha256_bytes(doc_manifest_raw) == summary.get("document_manifest_sha256"),
            "patent_pack_manifest_changed")
    doc_manifest = _load_pack_json(doc_manifest_raw)
    expected_gate_summary = doc_manifest.get("final_text_gate", {"status": "not_performed"})
    require(summary.get("final_text_gate") == expected_gate_summary, "patent_pack_summary_gate_mismatch")

    inv_raw = _read_outer_bytes(f"{out_rel}/patent-intake-inventory.json")
    require(sha256_bytes(inv_raw) == summary.get("internal_inventory_sha256"),
            "patent_pack_inventory_changed")
    inv_data = _load_pack_json(inv_raw)
    require(
        isinstance(inv_data, dict)
        and inv_data.get("schema") == "dyz-patent-intake-inventory-v1"
        and isinstance(inv_data.get("axes"), dict)
        and isinstance(inv_data.get("materials"), list)
        and isinstance(inv_data.get("term_formula_figure_map"), list),
        "patent_pack_inventory_invalid",
    )
    # 有包外原始输入时以其为准，否则只做报告内部逻辑与磁盘材料回查。
    rechecked_inv = build_material_inventory(
        intake_payload if intake_payload is not None else {
            "project_id": inv_data.get("project_id"),
            "source_kind": inv_data["axes"].get("source_kind"),
            "task_kind": inv_data["axes"].get("task_kind"),
            "tech_domain": inv_data["axes"].get("tech_domain"),
            "materials": inv_data["materials"],
            "term_formula_figure_map": [
                {k: v for k, v in row.items() if k != "omml_status"} if isinstance(row, dict) else row
                for row in inv_data["term_formula_figure_map"]
            ],
        },
        root=root,
        guarded=guarded,
        allowed_materials=admitted_map,
    )
    require(
        rechecked_inv["status"] != "blocked"
        and rechecked_inv["issues"] == []
        and inv_raw == canonical_bytes(rechecked_inv) + b"\n",
        "patent_pack_inventory_anchor_mismatch" if intake_payload is not None else "patent_pack_inventory_invalid",
    )
    require(summary.get("project_id") == inv_data["project_id"]
            and summary.get("axes") == rechecked_inv["axes"],
            "patent_pack_summary_inventory_mismatch")

    _check_spec_materials(document_spec, rechecked_inv, verifying=True)

    if summary.get("ir_report") is not None:
        ir_raw = _read_outer_bytes(f"{out_rel}/claim-fact-ir-report.json")
        require(sha256_bytes(ir_raw) == summary.get("ir_report_sha256"),
                "patent_pack_ir_report_changed")
        if ir_payload is not None:
            require(isinstance(ir_payload, dict), "ir_payload_object_required")
            _check_ir_materials(ir_payload.get("documents"), rechecked_inv)
            fresh_ir = patent_ir.validate_ir(ir_payload)
            require(ir_raw == canonical_bytes(fresh_ir) + b"\n", "patent_pack_ir_anchor_mismatch")
        ir_data = _load_pack_json(ir_raw)
        expected_ir_keys = {
            "schema", "version", "project_id", "status", "input_hash", "document_bindings",
            "fact_summary", "unknown_boundaries", "claims", "issues", "blocking_issue_count",
            "ready_for_prose_drafting", "natural_language_verified", "professional_review",
        }
        ir_issues = ir_data.get("issues") if isinstance(ir_data, dict) else None
        require(
            isinstance(ir_data, dict)
            and set(ir_data) == expected_ir_keys
            and ir_data.get("schema") == "dyz-patent-claim-fact-ir-v1"
            and ir_data.get("version") == patent_ir.VERSION
            and ir_data.get("project_id") == summary["project_id"]
            and isinstance(ir_data.get("input_hash"), str)
            and SHA256_RE.fullmatch(ir_data["input_hash"]) is not None
            and isinstance(ir_data.get("document_bindings"), list) and bool(ir_data["document_bindings"])
            and isinstance(ir_data.get("fact_summary"), dict)
            and isinstance(ir_data.get("unknown_boundaries"), list)
            and isinstance(ir_data.get("claims"), list) and bool(ir_data["claims"])
            and ir_data.get("ready_for_prose_drafting") is True
            and ir_data.get("natural_language_verified") is False
            and type(ir_data.get("blocking_issue_count")) is int
            and ir_data.get("blocking_issue_count") == 0
            and isinstance(ir_issues, list)
            and all(isinstance(i, dict) and i.get("severity") != "blocking" for i in ir_issues)
            and ir_data.get("status") == ("needs_review" if ir_issues else "checked")
            and ir_data.get("professional_review") == "not_performed"
            and summary.get("ir_status") == ir_data["status"],
            "patent_pack_ir_report_invalid",
        )
        _check_ir_materials(ir_data["document_bindings"], rechecked_inv)
    else:
        require(summary.get("ir_status") == "not_supplied" and summary.get("ir_report_sha256") is None,
                "patent_pack_summary_ir_mismatch")

    if expected_summary_sha256 is not None or (intake_payload is not None and ir_payload is not None):
        integrity = "externally_anchored"
    elif intake_payload is not None or ir_payload is not None:
        integrity = "partially_anchored"
    else:
        integrity = "self_consistent_only_unanchored"
    return {
        "schema": "dyz-patent-pack-verification-v1",
        "status": "verified_needs_review",
        "mode": expected_mode,
        "output_dir": out_rel,
        "integrity": integrity,
        "summary_sha256": summary_sha,
        "ir_report_present": summary["ir_report"] is not None,
        "ir_verified": summary["ir_report"] is not None and (
            expected_summary_sha256 is not None or ir_payload is not None),
        "document_verification": doc_verified,
        "professional_review": "not_performed",
    }
