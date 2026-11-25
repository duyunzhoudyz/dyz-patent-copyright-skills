"""CORE-07：合成稿或显式研究示例的DOCX装配，保留源行映射；不作专业判断。

本模块只用标准库；PDF转换可显式调用已安装LibreOffice，不读取任意Word模板。已有审阅稿应另行处理。
输出正文与内部说明分目录，文件绑定不构成外发授权或视觉验收。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import stat
import struct
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from tools.core import (
    ContractError, canonical_bytes, check_permission, digest, is_macos_system_root_symlink,
    preflight, require, require_fields, safe_path, sha256_bytes, strict_json_loads,
)
from tools.rendering import _svg

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
for prefix, uri in (("w", W), ("r", R), ("wp", WP), ("a", A), ("pic", PIC)):
    ET.register_namespace(prefix, uri)
MAX_BYTES = 5_000_000
# v1.5修正标准v2的Office部件与排版字节；旧包保留原工具或在新目录重建。
# 默认make_docx的字节与低层检查接口继续兼容；包协议升版不代表版式或专业认证。
VERSION = "1.5"


def _el(parent, tag, attrs=None, text=None):
    node = ET.SubElement(parent, tag, attrs or {})
    node.text = text
    return node


def _xml(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,38}", value),
            "document_identifier_invalid")
    return value


def _case_path(root, relative, *, must_exist=True):
    """真实准入拒绝根内别名、重解析点与硬链接，不只检查解析后是否越界。"""
    base = Path(root).absolute()
    target = safe_path(base, relative, must_exist=must_exist)
    nodes = list(reversed(base.parents)) + [base]
    current = base
    for piece in relative.replace("\\", "/").split("/"):
        current = current / piece
        nodes.append(current)
    for node in nodes:
        try:
            info = node.lstat()
        except FileNotFoundError:
            require(not must_exist, "document_case_path_missing")
            continue
        is_link = stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))
        if is_link:
            if node != nodes[-1] and is_macos_system_root_symlink(node):
                try:
                    info = node.stat()
                except OSError:
                    raise ContractError("document_case_reparse_point") from None
            else:
                require(False, "document_case_reparse_point")
        require(not stat.S_ISREG(info.st_mode) or info.st_nlink == 1, "document_case_material_alias")
    return target


def _read(root, item, *, guarded=False):
    path = _case_path(root, item["path"]) if guarded else safe_path(root, item["path"])
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, "document_source_size")
    if guarded:
        before = path.stat()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            raw = stream.read(MAX_BYTES + 1)
            finished = os.fstat(stream.fileno())
        after = _case_path(root, item["path"]).stat()
        stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        require(len(raw) <= MAX_BYTES and stamp(before) == stamp(opened) == stamp(finished) == stamp(after),
                "document_source_replaced_during_read")
    else:
        raw = path.read_bytes()
    require(sha256_bytes(raw) == item["sha256"], "document_source_changed")
    return raw


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _known_declaration(value, code):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 2000
            and value.strip().lower() not in {"unknown", "pending", "n/a", "not_established",
                                              "未知", "待核", "未核", "未建立", "未确认"}, code)


def _admission_permissions(permissions, environment, sensitivity, purpose, now, *, output=False):
    require(isinstance(permissions, list) and bool(permissions), "document_admission_permissions_required")
    for row in permissions:
        require(isinstance(row, dict), "document_admission_permission_invalid")
        _known_declaration(row.get("authority_evidence"), "document_admission_authority_required")
    preflight(environment, permissions, sensitivity=sensitivity, purpose=purpose, now=now)
    for action in ("local_processing", "copy") + (("local_output",) if output else ()):
        check_permission(permissions, action=action, purpose=purpose, recipient="local_tool", now=now)


def check_document_admission(root, spec, admission, *, output=None):
    """在任何内容读取前核真实模式的精确清单、用途权限和六类数据路径。

    admission字段：mode/case_root/spec_sha256/output/purpose/output_roles/environment/
    permissions/materials；每项材料为path/sha256/source/permissions。source含
    id/version/origin/level。真实时钟只由本进程取得，不接受调用者提供now。
    权利与环境证据仍是调用者记录，不冒充身份认证或真实专业核验。
    """
    fields = {"mode", "case_root", "spec_sha256", "output", "purpose", "output_roles",
              "environment", "permissions", "materials"}
    require(isinstance(admission, dict) and set(admission) == fields
            and admission["mode"] == "authorized_case", "document_admission_fields")
    require(isinstance(spec, dict) and spec.get("sensitivity") in {"public", "confidential", "restricted"}
            and "research_materials" not in spec, "document_authorized_sensitivity_required")
    require(isinstance(admission["case_root"], str) and Path(admission["case_root"]).is_absolute()
            and Path(root).is_absolute(), "document_case_root_absolute_required")
    base = Path(root).resolve(strict=True)
    code_root = Path(__file__).resolve().parent.parent
    require(Path(admission["case_root"]).resolve(strict=True) == base
            and not base.is_relative_to(code_root) and not code_root.is_relative_to(base),
            "document_case_root_binding")
    require(admission["spec_sha256"] == digest(spec), "document_admission_spec_binding")
    require(output is None or admission["output"] == output, "document_admission_output_binding")
    require(admission["output_roles"] == ["body", "internal"], "document_admission_output_roles")
    _known_declaration(admission["purpose"], "document_admission_purpose_required")
    environment = admission["environment"]
    require(isinstance(environment, dict), "document_admission_environment_required")
    _known_declaration(environment.get("assessment_evidence"), "document_admission_environment_required")
    paths = environment.get("data_paths")
    required = {"host_model", "index", "telemetry", "tools", "logs", "subprocess"}
    require(isinstance(paths, list) and len(paths) == len(required)
            and all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in paths)
            and {row["id"] for row in paths} == required, "document_admission_data_paths_required")
    for row in paths:
        require(row.get("verified") is True and row.get("mode") in {"disabled", "local", "external"},
                "document_admission_data_path_unverified")
        _known_declaration(row.get("evidence"), "document_admission_data_path_evidence_required")
    require(next(row for row in paths if row["id"] == "tools")["mode"] == "local"
            and next(row for row in paths if row["id"] == "subprocess")["mode"] == "disabled",
            "document_admission_offline_tool_required")
    now = _utc_now()
    # 公开材料也必须核全数据路径；公开可读不等于复制、模型处理或输出许可。
    _admission_permissions(admission["permissions"], environment, "restricted", admission["purpose"], now, output=True)
    sources, dependencies, figures = spec.get("sources"), spec.get("dependencies", []), spec.get("figures", [])
    require(isinstance(sources, list) and 0 < len(sources) <= 100, "document_sources_required")
    require(isinstance(dependencies, list) and len(dependencies) <= 100, "document_dependencies_invalid")
    require(isinstance(figures, list) and len(figures) <= 100, "document_figures_invalid")
    items = sources + dependencies
    for figure in figures:
        require(isinstance(figure, dict) and isinstance(figure.get("png"), dict)
                and isinstance(figure.get("svg"), dict), "document_figure_invalid")
        items.extend([figure["png"], figure["svg"]])
    expected = {}
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get("path"), str)
                and isinstance(item.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
                "document_admission_material_reference")
        path = safe_path(base, item["path"], must_exist=False)
        require(path not in expected, "document_case_material_alias")
        expected[path] = item["sha256"]
    materials = admission["materials"]
    require(isinstance(materials, list) and len(materials) == len(expected), "document_admission_material_coverage")
    declared = {}
    for row in materials:
        require(isinstance(row, dict) and set(row) == {"path", "sha256", "source", "permissions"},
                "document_admission_material_fields")
        path = safe_path(base, row["path"], must_exist=False)
        require(path not in declared and path in expected and row["sha256"] == expected[path],
                "document_admission_material_binding")
        require(isinstance(row["source"], dict), "document_admission_source_required")
        for key in ("id", "version", "origin", "level"):
            _known_declaration(row["source"].get(key), "document_admission_source_required")
        _admission_permissions(row["permissions"], environment, "restricted", admission["purpose"], now)
        declared[path] = row["sha256"]
    require(declared == expected, "document_admission_material_coverage")
    target = _case_path(base, admission["output"], must_exist=False)
    identities = set()
    for item in items:
        path = _case_path(base, item["path"])
        info = path.stat()
        require(path.is_file() and info.st_size <= MAX_BYTES, "document_source_size")
        require(path != target and not path.is_relative_to(target), "document_admission_output_overlaps_source")
        identity = (info.st_dev, info.st_ino)
        require(identity not in identities, "document_case_material_alias")
        identities.add(identity)
    return {"mode": "authorized_case", "input_hash": digest(admission), "spec_sha256": digest(spec),
            "case_root": str(base), "output": admission["output"], "purpose": admission["purpose"],
            "materials": [{"path": row["path"], "sha256": row["sha256"]} for row in materials],
            "clock": "runtime_utc_rechecked_each_call", "rights_verification": "not_independently_authenticated",
            "external_action": "not_performed"}


def _guard_output(root, output):
    target = _case_path(root, output)
    for index, path in enumerate(target.rglob("*")):
        require(index < 1000, "document_output_member_limit")
        _case_path(root, path.relative_to(Path(root).resolve()).as_posix())
    return target


def _mode(synthetic, research_example, admission=None):
    require(type(synthetic) is bool and type(research_example) is bool,
            "document_declaration_invalid")
    require(not (synthetic and research_example), "document_declarations_conflict")
    if admission is not None:
        require(not synthetic and not research_example, "document_declarations_conflict")
        require(isinstance(admission, dict) and admission.get("mode") == "authorized_case", "document_admission_required")
        return "authorized_case"
    require(synthetic or research_example, "synthetic_declaration_required")
    return "research_example" if research_example else "synthetic"


def _research_scope(spec):
    return {"materials": spec["research_materials"],
            "basis_verification": "caller_declarations_not_independently_verified",
            "permission_effect": "does_not_grant_rights_or_external_action"}


def _check_research_materials(root, spec):
    """Validate declarations for the complete read set before reading content.

    This checks the caller's declared scope, not whether content or real rights
    match those declarations. Third-party full text/private material is outside
    this bounded example mode, even if other permissions may exist elsewhere.
    """
    require(spec.get("sensitivity") == "research_example", "research_sensitivity_required")
    require("fidelity" not in spec, "research_fidelity_not_supported")
    sources, dependencies, figures = spec.get("sources"), spec.get("dependencies", []), spec.get("figures", [])
    require(isinstance(sources, list) and 0 < len(sources) <= 100, "document_sources_required")
    require(isinstance(dependencies, list) and len(dependencies) <= 100, "document_dependencies_invalid")
    require(isinstance(figures, list) and len(figures) <= 100, "document_figures_invalid")
    items = sources + dependencies
    for figure in figures:
        require(isinstance(figure, dict) and "png" in figure and "svg" in figure,
                "document_figure_invalid")
        items.extend((figure["png"], figure["svg"]))
    expected = {}
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get("path"), str)
                and isinstance(item.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None,
                "research_material_reference_invalid")
        path = safe_path(root, item["path"], must_exist=False)
        require(path not in expected, "research_material_read_alias")
        expected[path] = item["sha256"]
    declarations = spec.get("research_materials")
    require(isinstance(declarations, list) and len(declarations) == len(expected),
            "research_material_coverage_required")
    actual = {}
    for item in declarations:
        require(isinstance(item, dict) and set(item) == {
            "path", "sha256", "content_kind", "processing_basis", "export_basis", "third_party_text"},
            "research_material_declaration_invalid")
        require(isinstance(item["path"], str) and isinstance(item["sha256"], str),
                "research_material_declaration_invalid")
        path = safe_path(root, item["path"], must_exist=False)
        require(path not in actual, "research_material_declaration_duplicate")
        require(path in expected and item["sha256"] == expected[path],
                "research_material_binding_changed")
        require(item["content_kind"] in {"original_synthetic", "original_public_research",
                                         "original_mixed_research", "original_execution_evidence"}
                and item["third_party_text"] == "not_included", "research_material_kind_unsupported")
        for field in ("processing_basis", "export_basis"):
            require(isinstance(item[field], str) and 0 < len(item[field].strip()) <= 2000
                    and item[field].strip().lower() not in {
                        "unknown", "pending", "not_established", "not established", "n/a",
                        "未知", "待核", "未核", "未建立", "未确认", "不明确"},
                    "research_material_use_basis_required")
        actual[path] = item["sha256"]
    require(actual == expected, "research_material_coverage_required")


def resolve_document(root, spec, *, research_example=False, admission=None):
    """按冻结源文件和一基行区间取正文；真实材料须先核明确准入，不借合成声明。"""
    require(isinstance(spec, dict), "document_spec_required")
    profile = spec.get("profile")
    require(profile is None or isinstance(profile, str), "document_profile_unsupported")
    if admission is not None:
        _mode(False, research_example, admission)
        check_document_admission(root, spec, admission)
    elif research_example:
        _check_research_materials(root, spec)
    else:
        require(spec.get("sensitivity") == "synthetic" and "research_materials" not in spec, "synthetic_only")
    _identifier(spec["document_id"])
    require(spec["business"] in {"patent", "software", "standard"}, "document_business_invalid")
    layout = document_profile(profile)
    formula_allowed = ((profile is None and spec["business"] == "patent")
                       or "formula" in layout["supported_objects"])
    require(isinstance(spec["version"], str) and bool(spec["version"].strip()), "document_version_required")
    dependencies = spec.get("dependencies", [])
    require(isinstance(dependencies, list) and len(dependencies) <= 100, "document_dependencies_invalid")
    dependency_paths = set()
    for dependency in dependencies:
        require(isinstance(dependency, dict) and set(dependency) == {"path", "sha256"},
                "document_dependency_invalid")
        require(isinstance(dependency["path"], str) and bool(dependency["path"])
                and isinstance(dependency["sha256"], str), "document_dependency_invalid")
        require(dependency["path"] not in dependency_paths, "duplicate_document_dependency")
        dependency_paths.add(dependency["path"])
        # Binary evidence is bound but never decoded or silently inserted into the body.
        _read(root, dependency, guarded=admission is not None)
    require(isinstance(spec["sources"], list) and 0 < len(spec["sources"]) <= 100, "document_sources_required")
    sources = {}
    for source in spec["sources"]:
        sid = _identifier(source["id"])
        require(sid not in sources, "duplicate_document_source")
        raw = _read(root, source, guarded=admission is not None)
        sources[sid] = raw.decode("utf-8").splitlines()
    require(isinstance(spec["blocks"], list) and 0 < len(spec["blocks"]) <= 1000, "document_blocks_required")
    ids, resolved = set(), []
    for block in spec["blocks"]:
        bid = _identifier(block["id"])
        require(bid not in ids, "duplicate_document_block")
        ids.add(bid)
        kinds = {"paragraph", "heading1", "heading2", "code", "table", "reading_scope", "formula"}
        if layout.get("max_heading_depth") == 4:
            kinds.update({"heading3", "heading4"})
        require(block["kind"] in kinds, "document_block_kind")
        require(block["audience"] in {"body", "internal"}, "document_audience_required")
        if block["kind"] == "reading_scope":
            require("reading_scope" in spec, "document_reading_scope_required")
            require(block["audience"] == "body", "document_reading_scope_body_required")
            require(type(block.get("generate", False)) is bool, "document_reading_scope_generate_flag")
        lines = sources[block["source_id"]]
        start, end = block["start_line"], block["end_line"]
        require(type(start) is int and type(end) is int and 1 <= start <= end <= len(lines), "document_line_range")
        text = "\n".join(lines[start - 1:end])
        # 只移除显式标题的Markdown层级标记；技术词、数字、单位及否定词不归一化。
        if block["kind"].startswith("heading"):
            require(start == end, "document_heading_multiline")
            text = re.sub(r"^#{1,6} ", "", text)
        require(text.strip() and all(c in "\n\t" or ord(c) >= 32 for c in text), "document_text_invalid")
        require(not any(0xD800 <= ord(c) <= 0xDFFF or ord(c) in {0xFFFE, 0xFFFF} for c in text), "document_xml_character")
        entry = {**block, "text": text, "text_sha256": sha256_bytes(text.encode("utf-8"))}
        if block["kind"] == "table":
            entry["cells"] = _table_cells(text)
        elif block["kind"] == "formula":
            from tools import omml
            require(formula_allowed, "document_formula_profile_unsupported")
            omml.latex_to_omml_element(text)
        resolved.append(entry)
    require(any(b["audience"] == "body" for b in resolved), "document_body_required")
    images = []
    for item in spec.get("figures", []):
        fid = _identifier(item["id"])
        require(fid not in ids, "duplicate_document_block")
        ids.add(fid)
        png = _read(root, item["png"], guarded=admission is not None)
        svg = _read(root, item["svg"], guarded=admission is not None)
        require(png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) >= 24 and png[12:16] == b"IHDR", "document_png_required")
        width, height = struct.unpack(">II", png[16:24])
        require(0 < width <= 20000 and 0 < height <= 20000, "document_png_dimensions")
        _svg(svg.decode("utf-8"))
        require(item.get("render_binding") == digest({"svg": item["svg"]["sha256"], "png": item["png"]["sha256"]}), "figure_binding_changed")
        # 显式绑定只证明指定的两份字节，不能证明PNG忠实显示了SVG。
        images.append({"id": fid, "png": png, "svg": svg, "width": width, "height": height})
    return resolved, images


def _table_cells(text):
    """仅接受矩形管道表；不猜测合并、嵌套、转义管道或跨行单元格。"""
    lines = text.splitlines()
    require(len(lines) >= 3 and all(s.startswith("|") and s.endswith("|") for s in lines), "document_table_shape")
    require("\\|" not in text, "document_table_escaped_pipe_unsupported")
    rows = [[c.strip() for c in s[1:-1].split("|")] for s in lines]
    columns = len(rows[0])
    require(1 <= columns <= 6 and all(len(row) == columns for row in rows), "document_table_columns")
    require(all(re.fullmatch(r":?-{3,}:?", c) for c in rows[1]), "document_table_separator")
    return rows[:1] + rows[2:]


def _layout_resource(name):
    path = Path(__file__).resolve().parent.parent / "skills/dyz-standards/resources/lifecycle" / name
    return strict_json_loads(path.read_text(encoding="utf-8"))


def table_template_profile(profile):
    """返回原创三列／六列的精确映射；外部模板须另有明确许可与映射。"""
    resource = _layout_resource("table-template-profiles.v1.json")
    profiles = [row for row in resource["profiles"] if row["profile_id"] == profile]
    require(isinstance(profile, str) and len(profiles) == 1,
            "document_table_profile_unsupported")
    value = profiles[0]
    return {**value, "hash": digest(value)}


def document_profile(profile=None):
    """只提供原创内部工程版式；profile不是组织规则或GB/T符合性声明。"""
    if isinstance(profile, str) and profile in {"dyz-standard-internal-v2", "dyz-standard-internal-v3"}:
        resource_name = "rendering-profile.v3.json" if profile.endswith("-v3") else "rendering-profile.v2.json"
        value = _layout_resource(resource_name)
        require(value.get("profile_id") == profile and value.get("max_heading_depth") == 4,
                "document_profile_resource_invalid")
        return {**value, "hash": digest(value)}
    require(profile is None or isinstance(profile, str) and profile == "dyz-standard-internal-v1",
            "document_profile_unsupported")
    standard = profile is not None
    value = {"profile_id": profile or "dyz-legacy-a4-v1", "version": "1",
        "template_origin": "original_internal_implementation", "official_format": "not_asserted",
        "professional_review": "not_performed", "dynamic_fields": "not_generated_or_refreshed",
        "supported_objects": ["paragraph", "heading1", "heading2", "code", "rectangular_table", "png_figure"],
        "unsupported_objects": ["dynamic_fields", "merged_or_nested_tables", "formula", "textbox", "ole", "automatic_numbering", "organization_template"],
        "bookmark_scope": "complete_block_text_and_all_table_cells_not_heading_only",
        "page": "A4_body_optional_A3_figure_appendix", "margin_twips": 1440 if standard else 1134,
        "table_width_twips": 9026 if standard else 9638,
        "body_font": "SimSun" if standard else "Microsoft YaHei",
        "heading_font": "SimHei" if standard else "Microsoft YaHei",
        "sizes": {"Normal": "24" if standard else "22", "Heading1": "32" if standard else "30",
                  "Heading2": "28" if standard else "26", "Code": "19", "TableText": "20" if standard else "18"}}
    if standard:
        value.update(version="2", dynamic_fields="generated_not_refreshed",
                     field_cache="（域未刷新）", fields_refreshed=False)
        value["supported_objects"] += ["title", "TOC", "SEQ", "REF", "PAGEREF"]
        value["unsupported_objects"] = [
            "field_refresh", "arbitrary_field_instructions",
            *[kind for kind in value["unsupported_objects"] if kind != "dynamic_fields"],
        ]
        value["sizes"]["Title"] = "36"
        value["pagination"] = "explicit_keep_with_next_and_short_paragraph_keep_lines"
    return {**value, "hash": digest(value)}


_FIELD_CACHE = "（域未刷新）"


def _standard_text(value):
    require(isinstance(value, str) and all(
        c in "\n\t" or 0x20 <= ord(c) <= 0xD7FF
        or 0xE000 <= ord(c) <= 0xFFFD
        or 0x10000 <= ord(c) <= 0x10FFFF for c in value),
        "document_text_invalid")


def _standard_blocks(blocks, images, *, layout):
    """内部版式的书签和域输入是封闭契约；先收齐ID以允许前向引用。"""
    require(isinstance(blocks, list) and 0 < len(blocks) <= 1000,
            "document_blocks_required")
    identities, by_id = set(), {}
    depth = layout.get("max_heading_depth", 2)
    v2 = layout["profile_id"] in {"dyz-standard-internal-v2", "dyz-standard-internal-v3"}
    plain_kinds = {"title", "paragraph", "code", "table", "reading_scope", "formula"}
    plain_kinds.update(f"heading{level}" for level in range(1, depth + 1))
    for block in blocks:
        require(isinstance(block, dict), "document_block_required")
        identity = _identifier(block.get("id"))
        require(identity not in identities, "duplicate_document_block")
        identities.add(identity)
        by_id[identity] = block
        kind = block.get("kind")
        if v2 and isinstance(kind, str) and re.fullmatch(r"heading\d+", kind):
            require(1 <= int(kind[7:]) <= depth, "document_heading_depth_unsupported")
        if v2 and "annex" in block:
            require(type(block["annex"]) is bool and kind in plain_kinds
                    and kind.startswith("heading"), "document_annex_heading_required")
        require(isinstance(kind, str) and kind in plain_kinds | {"field"},
                "document_block_kind")
        if kind == "formula":
            require(kind in layout["supported_objects"], "document_formula_profile_unsupported")
        if "keep_with_next" in block:
            require(type(block["keep_with_next"]) is bool,
                    "document_keep_with_next_invalid")
        if kind == "field":
            field_type = block.get("field_type")
            require(isinstance(field_type, str)
                    and field_type in {"TOC", "SEQ", "REF", "PAGEREF"},
                    "document_field_type_invalid")
            required = {"id", "kind", "field_type"}
            if field_type == "SEQ":
                required.add("sequence")
            elif field_type in {"REF", "PAGEREF"}:
                required.add("target")
            optional = {"audience", "origin", "text_sha256", "prefix", "suffix",
                        "keep_with_next"}
            require(required <= block.keys() <= required | optional,
                    "document_field_keys_invalid")
            for key in ("sequence", "target"):
                if key in block:
                    _identifier(block[key])
            for key in ("prefix", "suffix"):
                _standard_text(block.get(key, ""))
        elif kind == "table":
            cells = block.get("cells")
            require(isinstance(cells, list) and bool(cells)
                    and isinstance(cells[0], list) and 1 <= len(cells[0]) <= 6
                    and all(isinstance(row, list) and len(row) == len(cells[0])
                            for row in cells), "document_table_shape")
            for row in cells:
                for cell in row:
                    _standard_text(cell)
            if v2 and "table_profile" in block:
                table_profile = table_template_profile(block["table_profile"])
                require(cells[0] == [column["header"] for column in table_profile["columns"]],
                        "document_table_profile_header_mismatch")
        else:
            _standard_text(block.get("text"))
    for image in images:
        identity = _identifier(image.get("id"))
        require(identity not in identities, "duplicate_document_block")
        identities.add(identity)
    for block in blocks:
        if block["kind"] == "field" and block["field_type"] in {"REF", "PAGEREF"}:
            target = by_id.get(block["target"])
            require(target is not None and (target["kind"] != "field"
                    or target["field_type"] == "SEQ"),
                    "document_field_target_invalid")


def _field_instruction(block, max_heading_depth=2):
    kind = block["field_type"]
    if kind == "TOC":
        if max_heading_depth == 4:
            return 'TOC \\o "1-4" \\h \\z \\u'
        return 'TOC \\o "1-2" \\h \\z'
    if kind == "SEQ":
        return "SEQ " + block["sequence"] + " \\* ARABIC"
    return kind + " " + block["target"] + " \\h"


def _field_display(block):
    return block.get("prefix", "") + _FIELD_CACHE + block.get("suffix", "")


def _text_run(parent, text):
    run = _el(parent, "{" + W + "}r")
    for part in re.split(r"(\n|\t)", text):
        if part in {"\n", "\t"}:
            _el(run, "{" + W + "}" + ("br" if part == "\n" else "tab"))
        elif part:
            _el(run, "{" + W + "}t",
                {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}, part)


def _pagination(pr, block, *, short=False):
    if "keep_with_next" in block:
        _el(pr, "{" + W + "}keepNext",
            {"{" + W + "}val": "1" if block["keep_with_next"] else "0"})
    if short:
        _el(pr, "{" + W + "}keepLines")


def _field_paragraph(body, block, index, *, max_heading_depth=2):
    p = _el(body, "{" + W + "}p")
    pr = _el(p, "{" + W + "}pPr")
    _el(pr, "{" + W + "}pStyle", {"{" + W + "}val": "Normal"})
    _pagination(pr, block, short=block["field_type"] != "TOC"
                and len(_field_display(block)) <= 180
                and _field_display(block).count("\n") <= 1)
    if block.get("prefix"):
        _text_run(p, block["prefix"])
    # SEQ的书签只包围域，不吞入图表标题；REF得到编号而非整段标题。
    _el(p, "{" + W + "}bookmarkStart",
        {"{" + W + "}id": str(index), "{" + W + "}name": block["id"]})
    _el(_el(p, "{" + W + "}r"), "{" + W + "}fldChar",
        {"{" + W + "}fldCharType": "begin", "{" + W + "}dirty": "true"})
    _el(_el(p, "{" + W + "}r"), "{" + W + "}instrText",
        {"{http://www.w3.org/XML/1998/namespace}space": "preserve"},
        " " + _field_instruction(block, max_heading_depth) + " ")
    _el(_el(p, "{" + W + "}r"), "{" + W + "}fldChar",
        {"{" + W + "}fldCharType": "separate"})
    _text_run(p, _FIELD_CACHE)
    _el(_el(p, "{" + W + "}r"), "{" + W + "}fldChar",
        {"{" + W + "}fldCharType": "end"})
    _el(p, "{" + W + "}bookmarkEnd", {"{" + W + "}id": str(index)})
    if block.get("suffix"):
        _text_run(p, block["suffix"])


def _table(body, block, index, *, width_twips=9638, layout=None):
    # 起止放在首尾单元格段落内；实际LibreOffice另存曾将body外包书签压成空书签。
    table = _el(body, "{" + W + "}tbl")
    pr = _el(table, "{" + W + "}tblPr")
    _el(pr, "{" + W + "}tblW", {"{" + W + "}w": str(width_twips), "{" + W + "}type": "dxa"})
    _el(pr, "{" + W + "}tblLayout", {"{" + W + "}type": "fixed"})
    borders = _el(pr, "{" + W + "}tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        _el(borders, "{" + W + "}" + side, {"{" + W + "}val": "single", "{" + W + "}sz": "4", "{" + W + "}color": "8090A0"})
    cells = block["cells"]
    width = width_twips // len(cells[0])
    widths = [width] * len(cells[0])
    if layout and "table_profile" in block:
        columns = table_template_profile(block["table_profile"])["columns"]
        weight = sum(column["width_weight"] for column in columns)
        widths = [width_twips * column["width_weight"] // weight for column in columns]
        widths[-1] += width_twips - sum(widths)
    grid = _el(table, "{" + W + "}tblGrid")
    for cell_width in widths:
        _el(grid, "{" + W + "}gridCol", {"{" + W + "}w": str(cell_width)})
    for row_index, row in enumerate(cells):
        tr = _el(table, "{" + W + "}tr")
        rp = _el(tr, "{" + W + "}trPr")
        if not layout or row_index == 0 or all(
                len(value) <= layout["table"]["short_row_max_characters"]
                and "\n" not in value for value in row):
            _el(rp, "{" + W + "}cantSplit")
        if row_index == 0:
            _el(rp, "{" + W + "}tblHeader")
        for column_index, value in enumerate(row):
            tc = _el(tr, "{" + W + "}tc")
            cp = _el(tc, "{" + W + "}tcPr")
            _el(cp, "{" + W + "}tcW", {"{" + W + "}w": str(widths[column_index]), "{" + W + "}type": "dxa"})
            p = _el(tc, "{" + W + "}p")
            ppr = _el(p, "{" + W + "}pPr")
            _el(ppr, "{" + W + "}pStyle", {"{" + W + "}val": "TableText"})
            if layout and row_index == 0:
                _el(ppr, "{" + W + "}keepNext")
            if row_index == 0 and column_index == 0:
                _el(p, "{" + W + "}bookmarkStart", {"{" + W + "}id": str(index), "{" + W + "}name": block["id"]})
            run = _el(p, "{" + W + "}r")
            if row_index == 0:
                _el(_el(run, "{" + W + "}rPr"), "{" + W + "}b")
            if layout:
                for part in re.split(r"(\n|\t)", value):
                    if part in {"\n", "\t"}:
                        _el(run, "{" + W + "}" + ("br" if part == "\n" else "tab"))
                    elif part:
                        _el(run, "{" + W + "}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}, part)
            else:
                _el(run, "{" + W + "}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}, value)
            if row_index == len(cells) - 1 and column_index == len(row) - 1:
                _el(p, "{" + W + "}bookmarkEnd", {"{" + W + "}id": str(index)})


def _paragraph(body, block, index, *, standard=False, standard_v2=False):
    p = _el(body, "{" + W + "}p")
    pr = _el(p, "{" + W + "}pPr")
    styles = {"heading1": "Heading1", "heading2": "Heading2", "code": "Code", "paragraph": "Normal", "reading_scope": "Normal", "title": "Title"}
    if standard_v2:
        styles.update(heading3="Heading3", heading4="Heading4")
    style = styles[block["kind"]]
    if standard_v2 and block.get("annex"):
        style = "Annex" + style
    _el(pr, "{" + W + "}pStyle", {"{" + W + "}val": style})
    if standard:
        _pagination(pr, block, short=block["kind"] != "code"
                    and len(block["text"]) <= 180 and block["text"].count("\n") <= 1)
    _el(p, "{" + W + "}bookmarkStart", {"{" + W + "}id": str(index), "{" + W + "}name": block["id"]})
    run = _el(p, "{" + W + "}r")
    for i, part in enumerate(re.split(r"(\n|\t)", block["text"])):
        if part in {"\n", "\t"}:
            _el(run, "{" + W + "}" + ("br" if part == "\n" else "tab"))
        elif part:
            _el(run, "{" + W + "}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}, part)
    _el(p, "{" + W + "}bookmarkEnd", {"{" + W + "}id": str(index)})


def _formula_paragraph(body, block, index):
    from tools import omml
    p = _el(body, "{" + W + "}p")
    pr = _el(p, "{" + W + "}pPr")
    _el(pr, "{" + W + "}pStyle", {"{" + W + "}val": "Normal"})
    require(type(block.get("keep_with_next", False)) is bool, "document_keep_with_next_invalid")
    _pagination(pr, block)
    _el(p, "{" + W + "}bookmarkStart", {"{" + W + "}id": str(index), "{" + W + "}name": block["id"]})
    p.append(omml.latex_to_omml_element(block["text"], display_para=False))
    _el(p, "{" + W + "}bookmarkEnd", {"{" + W + "}id": str(index)})


def _drawing(body, figure, index, *, page_break=True,
             max_width=8208000, max_height=12600000):
    p = _el(body, "{" + W + "}p")
    pr = _el(p, "{" + W + "}pPr")
    if page_break:
        _el(pr, "{" + W + "}pageBreakBefore")
    # 默认保留A3内部审阅图页；软件正文明确传入A4图框，不改变纵横比。
    scale = min(max_width / figure["width"], max_height / figure["height"])
    cx, cy = str(round(scale * figure["width"])), str(round(scale * figure["height"]))
    inline = _el(_el(_el(p, "{" + W + "}r"), "{" + W + "}drawing"), "{" + WP + "}inline")
    _el(inline, "{" + WP + "}extent", {"cx": cx, "cy": cy})
    _el(inline, "{" + WP + "}docPr", {"id": str(index), "name": figure["id"]})
    data = _el(_el(inline, "{" + A + "}graphic"), "{" + A + "}graphicData", {"uri": PIC})
    pic = _el(data, "{" + PIC + "}pic")
    nv = _el(pic, "{" + PIC + "}nvPicPr")
    _el(nv, "{" + PIC + "}cNvPr", {"id": str(index), "name": figure["id"]})
    _el(nv, "{" + PIC + "}cNvPicPr")
    fill = _el(pic, "{" + PIC + "}blipFill")
    _el(fill, "{" + A + "}blip", {"{" + R + "}embed": "image" + str(index)})
    _el(_el(fill, "{" + A + "}stretch"), "{" + A + "}fillRect")
    shape = _el(pic, "{" + PIC + "}spPr")
    xfrm = _el(shape, "{" + A + "}xfrm")
    _el(xfrm, "{" + A + "}off", {"x": "0", "y": "0"})
    _el(xfrm, "{" + A + "}ext", {"cx": cx, "cy": cy})
    _el(_el(shape, "{" + A + "}prstGeom", {"prst": "rect"}), "{" + A + "}avLst")


def make_docx(blocks, images, *, profile=None):
    """装配DOCX字节；内部profile的field只接受TOC/SEQ/REF/PAGEREF。

    v2支持heading1—4，annex=True使用同级附录样式；显示编号由调用者映射
    提供。table_profile可选原创三列／六列表式，按资源的精确表头与列宽生成。
    v2页脚另有独立PAGE，目录、正文、附录与可选A3图页连续编号，从1开始。
    域以field_type及sequence或target描述，文字放prefix/suffix；不得传入任意
    instruction或cache。引用可指向同件普通块或SEQ，允许前向引用。缓存只是
    未刷新标记，生成不等于Office刷新或最终交付放行。keep_with_next可用于
    公式块和内部profile；短段keepLines不承诺具体物理分页。
    """
    layout = document_profile(profile)
    standard_v2 = profile in {"dyz-standard-internal-v2", "dyz-standard-internal-v3"}
    if profile is not None:
        _standard_blocks(blocks, images, layout=layout)
    else:
        require(not any(block.get("kind") == "field" for block in blocks),
                "document_field_profile_required")
        require(not any(block.get("kind") == "title" for block in blocks),
                "document_title_profile_required")
    document = ET.Element("{" + W + "}document")
    body = _el(document, "{" + W + "}body")
    for i, block in enumerate(blocks, 1):
        if block["kind"] == "table":
            _table(body, block, i, width_twips=layout["table_width_twips"],
                   layout=layout if standard_v2 else None)
        elif block["kind"] == "field":
            _field_paragraph(body, block, i, max_heading_depth=layout.get("max_heading_depth", 2))
        elif block["kind"] == "formula":
            _formula_paragraph(body, block, i)
        else:
            _paragraph(body, block, i, standard=profile is not None, standard_v2=standard_v2)
    if images:
        # A4正文的节属性放在最后一段；下一节采用A3，不冒充官方附图格式。
        # 正文末尾为表格时，节属性需要独立段落承载。
        last = list(body)[-1]
        if last.tag != "{" + W + "}p":
            last = _el(body, "{" + W + "}p")
            _el(last, "{" + W + "}pPr")
        previous = last.find("{" + W + "}pPr")
        section = _el(previous, "{" + W + "}sectPr")
        if standard_v2:
            _standard_page_references(section)
        _el(section, "{" + W + "}pgSz", {"{" + W + "}w": "11906", "{" + W + "}h": "16838"})
        _el(section, "{" + W + "}pgMar", {"{" + W + "}" + k: str(layout["margin_twips"]) for k in ("top", "right", "bottom", "left")})
        if standard_v2:
            _standard_page_policy(section, layout, first=True)
    for i, figure in enumerate(images, 1):
        _drawing(body, figure, i)
    section = _el(body, "{" + W + "}sectPr")
    if standard_v2:
        _standard_page_references(section)
    _el(section, "{" + W + "}pgSz", {"{" + W + "}w": "16838" if images else "11906", "{" + W + "}h": "23811" if images else "16838"})
    _el(section, "{" + W + "}pgMar", {"{" + W + "}" + k: str(layout["margin_twips"]) for k in ("top", "right", "bottom", "left")})
    if standard_v2:
        _standard_page_policy(section, layout, first=not images)
    styles = ET.Element("{" + W + "}styles")
    for name, size in layout["sizes"].items():
        s = _el(styles, "{" + W + "}style", {"{" + W + "}type": "paragraph", "{" + W + "}styleId": name})
        _el(s, "{" + W + "}name", {"{" + W + "}val": name})
        pr = _el(s, "{" + W + "}pPr")
        _el(pr, "{" + W + "}spacing", {"{" + W + "}after": "100"})
        if standard_v2:
            # 自动中西文空白及标点悬挂会改变技术片段的可提取文字或越出版心。
            for setting in ("overflowPunct", "autoSpaceDE", "autoSpaceDN"):
                _el(pr, "{" + W + "}" + setting, {"{" + W + "}val": "0"})
        heading = name.startswith("Heading") or standard_v2 and name.startswith("AnnexHeading")
        if heading:
            _el(pr, "{" + W + "}keepNext")
            _el(pr, "{" + W + "}outlineLvl", {"{" + W + "}val": str(int(name[-1]) - 1)})
        if name == "Title":
            _el(pr, "{" + W + "}keepNext")
            _el(pr, "{" + W + "}outlineLvl", {"{" + W + "}val": "9"})
        rp = _el(s, "{" + W + "}rPr")
        font = layout["heading_font"] if heading or name == "Title" else layout["body_font"]
        _el(rp, "{" + W + "}rFonts", {"{" + W + "}" + k: ("Consolas" if name == "Code" and k != "eastAsia" else font) for k in ("ascii", "hAnsi", "eastAsia")})
        _el(rp, "{" + W + "}sz", {"{" + W + "}val": size})
    # LibreOffice导入器要求该关系部件使用默认命名空间；ns0前缀版本实际打开失败。
    rels = ET.Element("Relationships", {"xmlns": REL})
    _el(rels, "Relationship", {"Id": "styles", "Type": R + "/styles", "Target": "styles.xml"})
    for i in range(1, len(images) + 1):
        _el(rels, "Relationship", {"Id": "image" + str(i), "Type": R + "/image", "Target": f"media/image{i}.png"})
    parts = {"word/document.xml": _xml(document), "word/styles.xml": _xml(styles), "word/_rels/document.xml.rels": _xml(rels),
        "_rels/.rels": ('<Relationships xmlns="' + REL + '"><Relationship Id="doc" Type="' + R + '/officeDocument" Target="word/document.xml"/></Relationships>').encode(),
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'}
    if standard_v2:
        for name, content in _standard_header_footer(layout).items():
            parts["word/" + name + "1.xml"] = content
            _el(rels, "Relationship", {"Id": name, "Type": R + "/" + name, "Target": name + "1.xml"})
        parts["word/_rels/document.xml.rels"] = _xml(rels)
        types = ET.fromstring(parts["[Content_Types].xml"])
        # LibreOffice实际拒绝带ns0前缀的Content Types；局部默认命名空间避免改全局注册表。
        types.tag = "Types"
        types.set("xmlns", "http://schemas.openxmlformats.org/package/2006/content-types")
        for child in types:
            child.tag = child.tag.rsplit("}", 1)[-1]
        for name in ("header", "footer"):
            _el(types, "Override", {
                "PartName": "/word/" + name + "1.xml",
                "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml." + name + "+xml"})
        parts["[Content_Types].xml"] = _xml(types)
    parts.update({f"word/media/image{i}.png": f["png"] for i, f in enumerate(images, 1)})
    return _zip_docx(parts)


def _standard_page_references(section):
    for name in ("header", "footer"):
        _el(section, "{" + W + "}" + name + "Reference", {
            "{" + W + "}type": "default", "{" + R + "}id": name})


def _standard_page_policy(section, layout, *, first):
    margins = section.find("{" + W + "}pgMar")
    for name in ("header", "footer"):
        margins.set("{" + W + "}" + name,
                    str(layout["header_footer"][name + "_distance_twips"]))
    attrs = {"{" + W + "}fmt": layout["page_numbering"]["format"]}
    if first:
        attrs["{" + W + "}start"] = str(layout["page_numbering"]["start"])
    _el(section, "{" + W + "}pgNumType", attrs)


def _standard_header_footer(layout):
    header = ET.Element("{" + W + "}hdr")
    p = _el(header, "{" + W + "}p")
    _el(_el(p, "{" + W + "}pPr"), "{" + W + "}pStyle", {"{" + W + "}val": "Header"})
    _text_run(p, layout["header_footer"]["header_text"])
    footer = ET.Element("{" + W + "}ftr")
    p = _el(footer, "{" + W + "}p")
    pr = _el(p, "{" + W + "}pPr")
    _el(pr, "{" + W + "}pStyle", {"{" + W + "}val": "Footer"})
    _el(pr, "{" + W + "}jc", {"{" + W + "}val": "center"})
    _el(_el(p, "{" + W + "}r"), "{" + W + "}fldChar", {
        "{" + W + "}fldCharType": "begin", "{" + W + "}dirty": "true"})
    _el(_el(p, "{" + W + "}r"), "{" + W + "}instrText", {
        "{http://www.w3.org/XML/1998/namespace}space": "preserve"}, " PAGE ")
    _el(_el(p, "{" + W + "}r"), "{" + W + "}fldChar", {"{" + W + "}fldCharType": "separate"})
    _text_run(p, layout["header_footer"]["cached_value"])
    _el(_el(p, "{" + W + "}r"), "{" + W + "}fldChar", {"{" + W + "}fldCharType": "end"})
    return {"header": _xml(header), "footer": _xml(footer)}


def _zip_docx(parts):
    """固定成员顺序与ZIP元数据，保留既有Windows产物字节。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in sorted(parts.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.external_attr = 0o600 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, data)
    return buffer.getvalue()


def _inspect_generated_fields(xml, blocks, *, max_heading_depth=2):
    """只核本生成器的扁平复杂域；实际指令、缓存和书签均来自OOXML。"""
    w = "{" + W + "}"
    starts = list(xml.iter(w + "bookmarkStart"))
    names = [node.get(w + "name") for node in starts]
    identities = [node.get(w + "id") for node in starts]
    ends = [node.get(w + "id") for node in xml.iter(w + "bookmarkEnd")]
    require(len(names) == len(set(names)) == len(blocks)
            and set(names) == {block["id"] for block in blocks}
            and len(identities) == len(set(identities))
            and sorted(identities) == sorted(ends), "document_bookmark_changed")
    definitions = {block["id"]: block for block in blocks if block["kind"] == "field"}
    actual = []
    for paragraph in xml.findall("./" + w + "body/" + w + "p"):
        chars = list(paragraph.iter(w + "fldChar"))
        if not chars:
            continue
        start = paragraph.find(w + "bookmarkStart")
        identity = start.get(w + "name") if start is not None else None
        require(identity in definitions, "document_field_binding_changed")
        block = definitions[identity]
        tokens, instructions, cache = [], [], []
        inside_cache = False
        for node in paragraph.iter():
            if node.tag == w + "fldChar":
                event = node.get(w + "fldCharType")
                tokens.append(event)
                inside_cache = event == "separate"
            elif node.tag == w + "instrText":
                tokens.append("instruction")
                instructions.append(node.text or "")
            elif node.tag == w + "t" and inside_cache:
                tokens.append("cache")
                cache.append(node.text or "")
        instruction = "".join(instructions).strip()
        require(tokens == ["begin", "instruction", "separate", "cache", "end"]
                and chars[0].get(w + "dirty") == "true"
                and "".join(cache) == _FIELD_CACHE,
                "document_field_structure_changed")
        require(instruction == _field_instruction(block, max_heading_depth), "document_field_instruction_changed")
        if block["field_type"] in {"REF", "PAGEREF"}:
            require(block["target"] in names, "document_field_target_invalid")
        actual.append({"id": identity, "field_type": block["field_type"],
                       "instruction": instruction, "cached_text": "".join(cache),
                       "dirty": True})
    require([row["id"] for row in actual] == list(definitions)
            and len(list(xml.iter(w + "fldChar"))) == 3 * len(actual)
            and len(list(xml.iter(w + "instrText"))) == len(actual)
            and not list(xml.iter(w + "fldSimple")), "document_field_structure_changed")
    return {"fields": actual, "field_structure_equal": True,
            "field_targets_valid": True, "fields_refreshed": False}


def inspect_generated_docx(raw, blocks, images, *, profile=None):
    """核内部版式完整部件、书签和真实域结构；不执行或刷新Word域。"""
    expected = make_docx(blocks, images, profile=profile)
    with zipfile.ZipFile(io.BytesIO(raw)) as got, zipfile.ZipFile(io.BytesIO(expected)) as want:
        names = got.namelist()
        require(len(names) == len(set(names)) and set(names) == set(want.namelist()), "document_package_members_changed")
        require(all(got.getinfo(n).file_size == want.getinfo(n).file_size for n in names), "document_package_sizes_changed")
        # 逐部件比对包括正文、样式、关系及图片；不会静默忽略新增批注、外链、隐藏或修订。
        require(all(got.read(n) == want.read(n) for n in names), "document_package_content_changed")
        xml = ET.fromstring(got.read("word/document.xml"))
        from tools import omml
        text = []
        omml_count = 0
        for paragraph in xml.findall("./{" + W + "}body/{" + W + "}p"):
            if paragraph.find(".//{" + W + "}drawing") is not None:
                continue
            math_node = paragraph.find(".//{" + omml.M + "}oMath")
            if math_node is not None:
                inspected = omml.inspect_omml(math_node)
                require(inspected["valid"], "document_omml_invalid")
                omml_count += 1
                text.append(inspected["canonical_form"])
                continue
            text.append("".join(n.text or "" if n.tag == "{" + W + "}t" else "\n" if n.tag == "{" + W + "}br" else "\t" if n.tag == "{" + W + "}tab" else "" for n in paragraph.iter()))
        if blocks[-1]["kind"] == "table" and images:
            require(text[-1] == "", "document_section_paragraph_changed")
            text.pop()
        expected_texts = []
        for b in blocks:
            if b["kind"] == "table":
                continue
            if b["kind"] == "field":
                expected_texts.append(_field_display(b))
            elif b["kind"] == "formula":
                expected_texts.append(omml.inspect_omml(omml.latex_to_omml_element(b["text"]))["canonical_form"])
            else:
                expected_texts.append(b["text"])
        require(text == expected_texts, "document_text_changed")
        tables = []
        for table in xml.findall("./{" + W + "}body/{" + W + "}tbl"):
            tables.append([["".join(n.text or "" if n.tag == "{" + W + "}t" else "\n" if n.tag == "{" + W + "}br" else "\t" if n.tag == "{" + W + "}tab" else "" for n in cell.iter()) for cell in row.findall("{" + W + "}tc")] for row in table.findall("{" + W + "}tr")])
        require(tables == [b["cells"] for b in blocks if b["kind"] == "table"], "document_table_text_changed")
    checks = {"paragraphs": sum(b["kind"] != "table" for b in blocks), "tables": sum(b["kind"] == "table" for b in blocks), "figures": len(images), "formulas": omml_count, "source_text_equal": True, "generated_package_parts_equal": True}
    if profile is not None:
        checks.update(_inspect_generated_fields(xml, blocks,
                      max_heading_depth=4 if profile in {"dyz-standard-internal-v2", "dyz-standard-internal-v3"} else 2))
    if isinstance(profile, str) and profile in {"dyz-standard-internal-v2", "dyz-standard-internal-v3"}:
        layout = document_profile(profile)
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            footer = ET.fromstring(package.read("word/footer1.xml"))
            instructions = [(node.text or "").strip() for node in footer.iter("{" + W + "}instrText")]
        require(instructions == ["PAGE"], "document_page_field_changed")
        checks["header_footer"] = {"parts": ["word/header1.xml", "word/footer1.xml"],
            "relationships_and_content_types_equal": True}
        checks["page_numbering"] = {**layout["page_numbering"], "part": "word/footer1.xml",
            "instruction": "PAGE", "cached_text": layout["header_footer"]["cached_value"],
            "fields_refreshed": False, "field_state": "generated_not_refreshed"}
    return checks


def _software_text(value, *, metadata=False):
    require(isinstance(value, str), "software_document_text_required")
    # XML会把原始CR归一化；拒绝它而非悄悄更改源码，调用方应显式解析源行。
    require(all(c in "\n\t" or 0x20 <= ord(c) <= 0xD7FF
                or 0xE000 <= ord(c) <= 0xFFFD
                or 0x10000 <= ord(c) <= 0x10FFFF for c in value),
            "software_document_xml_character")
    if metadata:
        require(bool(value.strip()) and "\n" not in value and "\t" not in value,
                "software_document_metadata_invalid")


def _software_png(block):
    """核PNG容器、CRC和像素尺寸；不认证截图内容或来源。"""
    raw = block.get("png")
    require(isinstance(raw, bytes) and 33 <= len(raw) <= MAX_BYTES
            and raw.startswith(b"\x89PNG\r\n\x1a\n")
            and raw[8:16] == b"\x00\x00\x00\rIHDR",
            "software_document_png_required")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", raw[16:29])
    require(type(block.get("width")) is int and type(block.get("height")) is int
            and 0 < width <= 20000 and 0 < height <= 20000
            and (width, height) == (block["width"], block["height"]),
            "software_document_png_dimensions")
    depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
              4: {8, 16}, 6: {8, 16}}
    require(depth in depths.get(color, set()) and compression == filtering == 0
            and interlace in {0, 1}, "software_document_png_header")
    offset, image_data = 8, False
    while offset < len(raw):
        require(offset + 12 <= len(raw), "software_document_png_truncated")
        size = struct.unpack(">I", raw[offset:offset + 4])[0]
        end = offset + 12 + size
        require(end <= len(raw), "software_document_png_truncated")
        chunk = raw[offset + 4:offset + 8]
        checksum = struct.unpack(">I", raw[end - 4:end])[0]
        require(checksum == zlib.crc32(raw[offset + 4:end - 4]),
                "software_document_png_crc")
        require(chunk != b"IHDR" or offset == 8, "software_document_png_header")
        if chunk == b"IDAT" and size:
            image_data = True
        if chunk == b"IEND":
            require(size == 0 and end == len(raw) and image_data,
                    "software_document_png_end")
            return
        offset = end
    raise ContractError("software_document_png_end")


def _software_input(pages, title, version, kind):
    require(isinstance(kind, str) and kind in {"source", "manual", "worksheet"},
            "software_document_kind")
    _software_text(title, metadata=True)
    _software_text(version, metadata=True)
    require(isinstance(pages, list) and bool(pages), "software_document_pages_required")
    identifiers = set()
    for page in pages:
        require(isinstance(page, list) and bool(page), "software_document_page_required")
        for block in page:
            require(isinstance(block, dict) and {"id", "kind"} <= block.keys(),
                    "software_document_block_required")
            identity = _identifier(block["id"])
            require(identity not in identifiers, "software_document_duplicate_block")
            identifiers.add(identity)
            block_kind = block["kind"]
            require(isinstance(block_kind, str) and block_kind in {
                "code", "paragraph", "heading1", "heading2", "image"},
                "software_document_block_kind")
            if block_kind == "image":
                _software_png(block)
                _software_text(block.get("text", ""))
            else:
                _software_text(block.get("text"))


def make_software_docx(pages: list[list[dict]], *, title: str,
                       version: str, kind: str) -> bytes:
    """在内存装配source/manual/worksheet候选逻辑页，不读写文件或执行转换。

    每页为非空block列表，每个block的ASCII id在全文唯一；文本kind为code、
    paragraph、heading1或heading2，image直接携带png字节与匹配的width/height，
    可带text作为图注。code按LF拆成独立段落，包括空行与末尾空行，不预折行、
    裁切或清洗源码。显式页起点不证明物理分页；调用方负责源行映射、实际PDF
    回读及视觉复核，也负责材料权限和真实性，不得借此绕过旧入口的门禁。
    """
    _software_input(pages, title, version, kind)
    document = ET.Element("{" + W + "}document")
    body = _el(document, "{" + W + "}body")
    images, index = [], 0
    for page in pages:
        first_paragraph = len(body)
        for block in page:
            index += 1
            if block["kind"] == "image":
                images.append(block)
                _drawing(body, block, len(images), page_break=False,
                         max_width=5940000, max_height=3600000)
                paragraph = body[-1]
                start = ET.Element("{" + W + "}bookmarkStart", {
                    "{" + W + "}id": str(index), "{" + W + "}name": block["id"]})
                paragraph.insert(1, start)
                _el(paragraph, "{" + W + "}bookmarkEnd", {"{" + W + "}id": str(index)})
                if block.get("text"):
                    _paragraph(body, {**block, "kind": "paragraph"}, index)
                    caption = body[-1]
                    caption.remove(caption.find("{" + W + "}bookmarkStart"))
                    caption.remove(caption.find("{" + W + "}bookmarkEnd"))
            else:
                lines = block["text"].split("\n") if block["kind"] == "code" else [block["text"]]
                for line_index, line in enumerate(lines):
                    _paragraph(body, {**block, "text": line}, index)
                    paragraph = body[-1]
                    # 一个输入block的书签可跨多个展示行，不伪造新的源行身份。
                    if line_index:
                        paragraph.remove(paragraph.find("{" + W + "}bookmarkStart"))
                    if line_index < len(lines) - 1:
                        paragraph.remove(paragraph.find("{" + W + "}bookmarkEnd"))
        _el(body[first_paragraph].find("{" + W + "}pPr"), "{" + W + "}pageBreakBefore")
    section = _el(body, "{" + W + "}sectPr")
    for part in ("header", "footer"):
        _el(section, "{" + W + "}" + part + "Reference", {
            "{" + W + "}type": "default", "{" + R + "}id": part})
    _el(section, "{" + W + "}pgSz", {"{" + W + "}w": "11906", "{" + W + "}h": "16838"})
    margins = {"{" + W + "}" + k: "1134" for k in ("top", "right", "bottom", "left")}
    margins.update({"{" + W + "}header": "567", "{" + W + "}footer": "567", "{" + W + "}gutter": "0"})
    _el(section, "{" + W + "}pgMar", margins)

    styles = ET.Element("{" + W + "}styles")
    for name, size in (("Normal", "22"), ("Heading1", "28"), ("Heading2", "24"),
                       ("Code", "18"), ("Header", "18"), ("Footer", "18")):
        attrs = {"{" + W + "}type": "paragraph", "{" + W + "}styleId": name}
        if name == "Normal":
            attrs["{" + W + "}default"] = "1"
        style = _el(styles, "{" + W + "}style", attrs)
        _el(style, "{" + W + "}name", {"{" + W + "}val": f"Software {kind} {name}"})
        pr = _el(style, "{" + W + "}pPr")
        if name.startswith("Heading"):
            _el(pr, "{" + W + "}keepNext")
        _el(pr, "{" + W + "}widowControl", {"{" + W + "}val": "0"})
        if name == "Code":
            # Consolas 9pt四字符实测395.859twip，取整396；只布置在A4正文9638twip内。
            tabs = _el(pr, "{" + W + "}tabs")
            for position in range(396, 9639, 396):
                _el(tabs, "{" + W + "}tab", {"{" + W + "}val": "left", "{" + W + "}pos": str(position)})
        _el(pr, "{" + W + "}spacing", {"{" + W + "}before": "0", "{" + W + "}after": "0",
            "{" + W + "}line": "240" if name in {"Code", "Header", "Footer"} else "280",
            "{" + W + "}lineRule": "exact" if name == "Code" else "atLeast"})
        if name.startswith("Heading"):
            _el(pr, "{" + W + "}outlineLvl", {"{" + W + "}val": "0" if name == "Heading1" else "1"})
        rp = _el(style, "{" + W + "}rPr")
        _el(rp, "{" + W + "}rFonts", {"{" + W + "}" + k:
            "Consolas" if name == "Code" and k != "eastAsia" else "Microsoft YaHei"
            for k in ("ascii", "hAnsi", "eastAsia")})
        if name.startswith("Heading"):
            _el(rp, "{" + W + "}b")
        _el(rp, "{" + W + "}sz", {"{" + W + "}val": size})
        _el(rp, "{" + W + "}szCs", {"{" + W + "}val": size})

    header = ET.Element("{" + W + "}hdr")
    p = _el(header, "{" + W + "}p")
    _el(_el(p, "{" + W + "}pPr"), "{" + W + "}pStyle", {"{" + W + "}val": "Header"})
    _el(_el(p, "{" + W + "}r"), "{" + W + "}t",
        {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}, title + " " + version)
    footer = ET.Element("{" + W + "}ftr")
    p = _el(footer, "{" + W + "}p")
    pr = _el(p, "{" + W + "}pPr")
    _el(pr, "{" + W + "}pStyle", {"{" + W + "}val": "Footer"})
    _el(pr, "{" + W + "}jc", {"{" + W + "}val": "center"})
    field = _el(p, "{" + W + "}fldSimple", {"{" + W + "}instr": " PAGE ", "{" + W + "}dirty": "true"})
    _el(_el(field, "{" + W + "}r"), "{" + W + "}t", text="1")

    rels = ET.Element("Relationships", {"xmlns": REL})
    for identity, target in (("styles", "styles.xml"), ("header", "header1.xml"), ("footer", "footer1.xml")):
        _el(rels, "Relationship", {"Id": identity, "Type": R + "/" + identity, "Target": target})
    for i in range(1, len(images) + 1):
        _el(rels, "Relationship", {"Id": f"image{i}", "Type": R + "/image", "Target": f"media/image{i}.png"})
    root_rels = ET.Element("Relationships", {"xmlns": REL})
    _el(root_rels, "Relationship", {"Id": "doc", "Type": R + "/officeDocument", "Target": "word/document.xml"})
    types = ET.Element("Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"})
    for extension, content_type in (("rels", "application/vnd.openxmlformats-package.relationships+xml"),
                                    ("xml", "application/xml"), ("png", "image/png")):
        _el(types, "Default", {"Extension": extension, "ContentType": content_type})
    for part, content_type in (("document", "document.main"), ("styles", "styles"),
                               ("header1", "header"), ("footer1", "footer")):
        _el(types, "Override", {"PartName": f"/word/{part}.xml",
            "ContentType": f"application/vnd.openxmlformats-officedocument.wordprocessingml.{content_type}+xml"})
    parts = {"word/document.xml": _xml(document), "word/styles.xml": _xml(styles),
             "word/header1.xml": _xml(header), "word/footer1.xml": _xml(footer),
             "word/_rels/document.xml.rels": _xml(rels), "_rels/.rels": _xml(root_rels),
             "[Content_Types].xml": _xml(types)}
    parts.update({f"word/media/image{i}.png": block["png"] for i, block in enumerate(images, 1)})
    return _zip_docx(parts)


def inspect_software_docx(raw: bytes, pages: list[list[dict]], *, title: str,
                          version: str, kind: str) -> dict:
    """严格回读本软件装配器的包和原文；不接纳另存编辑，也不证明物理分页。"""
    expected = make_software_docx(pages, title=title, version=version, kind=kind)
    require(isinstance(raw, bytes), "software_document_package_required")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as got, zipfile.ZipFile(io.BytesIO(expected)) as want:
            names = got.namelist()
            require(len(names) == len(set(names)) and set(names) == set(want.namelist()),
                    "software_document_package_members_changed")
            require(all(got.getinfo(n).file_size == want.getinfo(n).file_size for n in names),
                    "software_document_package_sizes_changed")
            require(all(got.read(n) == want.read(n) for n in names),
                    "software_document_package_content_changed")
            for name in names:
                if name.endswith(".rels"):
                    relations = ET.fromstring(got.read(name))
                    require(all(r.get("TargetMode") != "External" for r in relations),
                            "software_document_external_relationship")
            document = ET.fromstring(got.read("word/document.xml"))
            paragraphs = document.findall("./{" + W + "}body/{" + W + "}p")
            texts = ["".join(n.text or "" if n.tag == "{" + W + "}t"
                            else "\t" if n.tag == "{" + W + "}tab"
                            else "\n" if n.tag == "{" + W + "}br" else ""
                            for n in p.iter()) for p in paragraphs]
            wanted_texts, figures = [], []
            for page in pages:
                for block in page:
                    if block["kind"] == "image":
                        figures.append(block)
                        wanted_texts.append("")
                        if block.get("text"):
                            wanted_texts.append(block["text"])
                    else:
                        wanted_texts.extend(block["text"].split("\n") if block["kind"] == "code"
                                            else [block["text"]])
            require(texts == wanted_texts, "software_document_text_changed")
            require(all(got.read(f"word/media/image{i}.png") == block["png"]
                        for i, block in enumerate(figures, 1)), "software_document_media_changed")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as error:
        raise ContractError("software_document_package_invalid") from error
    return {"kind": kind, "logical_pages": len(pages), "paragraphs": len(paragraphs),
            "figures": len(figures), "source_text_equal": True, "media_equal": True,
            "generated_package_parts_equal": True, "no_external_relationships": True,
            "pagination_basis": "candidate_logical_pages", "physical_pagination_verified": False,
            "visual_review": "not_performed"}


def quality_docx(raw, *, stage="draft", business="standard"):
    """扫描实际OOXML文字，包括表格、页眉页脚、批注、修订和隐藏文字。

    不执行域、不解码图片/OLE、不认证版式或专业正确性；未解释对象使覆盖为
    partial。调用者仍须用inspect_generated_docx核本生成器的完整包身份。
    """
    from .fidelity import audit_text_quality
    require(isinstance(raw, bytes) and len(raw) <= 20_000_000, "quality_docx_size")
    texts, covered, unsupported, observations = {}, [], [], []
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        members = package.infolist()
        names = [row.filename for row in members]
        require(len(names) <= 256 and len(names) == len(set(names)), "quality_docx_members")
        require("word/document.xml" in names, "quality_docx_main_part_required")
        require(sum(row.file_size for row in members) <= 40_000_000
                and all(row.file_size <= 8_000_000 and not row.flag_bits & 1 for row in members),
                "quality_docx_expansion_limit")
        total_quality_bytes = 0
        for name in sorted(names):
            require(not name.startswith(("/", "\\")) and "\\" not in name
                    and all(part not in {"", ".", ".."} for part in name.split("/")), "quality_docx_member_path")
            content_part = bool(re.fullmatch(r"word/(?:document|header\d*|footer\d*|comments|footnotes|endnotes)\.xml", name))
            if not content_part:
                if name not in {"[Content_Types].xml", "_rels/.rels", "word/styles.xml", "word/_rels/document.xml.rels"}:
                    unsupported.append({"part": name, "reason": "nontext_or_uninterpreted_part"})
                continue
            with package.open(name) as stream:
                part = stream.read(8_000_001)
            require(len(part) <= 8_000_000, "quality_docx_expansion_limit")
            total_quality_bytes += len(part)
            require(total_quality_bytes <= 40_000_000, "quality_docx_expansion_limit")
            require(not re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", part.replace(b"\0", b""), re.I),
                    "quality_docx_dtd_unsupported")
            try:
                tree = ET.fromstring(part)
            except ET.ParseError as exc:
                raise ContractError("quality_docx_xml_invalid") from exc
            # 迭代校验 XML 嵌套深度与节点数，防深层嵌套触发 RecursionError DoS
            xml_stack = [(tree, 0)]
            xml_nodes = 0
            while xml_stack:
                cur, depth = xml_stack.pop()
                xml_nodes += 1
                require(depth <= 128 and xml_nodes <= 100_000, "quality_docx_xml_complexity_exceeded")
                for child in cur:
                    xml_stack.append((child, depth + 1))
            covered.append(name)
            located = set()
            from . import omml
            math_t = "{" + omml.M + "}t"
            text_tags = {"{" + W + "}t", "{" + W + "}delText", "{" + W + "}instrText", "{" + A + "}t", math_t}
            for index, paragraph in enumerate(tree.iter("{" + W + "}p"), 1):
                located.update(id(node) for node in paragraph.iter() if node.tag in text_tags)
                text = "".join(node.text or "" if node.tag in text_tags
                    else "\n" if node.tag == "{" + W + "}br" else "\t" if node.tag == "{" + W + "}tab" else ""
                    for node in paragraph.iter())
                if text:
                    texts[name + "#p" + str(index)] = text
            for index, node in enumerate(tree.iter()):
                if node.tag in text_tags and id(node) not in located:
                    # 非支持布局中的文字仍要扫描；保留位置并降低覆盖，不能静默丢弃。
                    texts[name + "#unlocated" + str(index)] = node.text or ""
                    unsupported.append({"part": name, "object_index": index, "reason": "text_outside_supported_paragraph"})
                local = node.tag.rsplit("}", 1)[-1]
                if local in {"oMath", "oMathPara"} and node.tag.startswith("{" + omml.M + "}"):
                    try:
                        inspected_math = omml.inspect_omml(node)
                        if not inspected_math["valid"]:
                            unsupported.append({"part": name, "object": local, "reason": "omml_invalid_or_unsupported"})
                    except (ContractError, RecursionError):
                        unsupported.append({"part": name, "object": local, "reason": "omml_invalid_or_unsupported"})
                elif local in {"object", "oMath", "oMathPara", "altChunk", "txbxContent", "fldSimple", "fldChar", "instrText", "drawing", "pict", "AlternateContent"}:
                    unsupported.append({"part": name, "object": local, "reason": "object_semantics_not_interpreted"})
                if local in {"vanish", "webHidden", "ins", "del"}:
                    observations.append({"part": name, "object": local, "text_policy": "included_not_silently_discarded"})
    report = audit_text_quality(texts, business=business, stage=stage,
        coverage={"state": "partial" if unsupported else "complete_supported_subset",
                  "scope": "actual_docx_wordprocessing_text_including_hidden_and_revisions",
                  "covered_parts": covered, "unsupported_objects": unsupported, "observations": observations})
    report["artifact_sha256"] = sha256_bytes(raw)
    return report


inspect_docx_quality = quality_docx


def _quality_summary(report):
    return {key: report[key] for key in ("contract_version", "status", "stage", "input_hash", "artifact_sha256",
            "coverage", "semantic_fidelity")} | {"report": "internal/quality-review.json"}


def _quality_gate(report):
    require(report["stage"] != "final" or report["status"] != "blocked", "document_quality_blocked")


def _source_map(spec, blocks):
    mapping = {"sources": spec["sources"], "blocks": blocks}
    if "dependencies" in spec:
        mapping["dependencies"] = spec["dependencies"]
    if "research_materials" in spec:
        mapping["research_materials"] = spec["research_materials"]
    return canonical_bytes(mapping) + b"\n"


def _fidelity(spec, public, figures):
    if "fidelity" not in spec:
        return None
    from .fidelity import audit_bound_text
    value = spec["fidelity"]
    require_fields(value, ("payload", "blocks"))
    texts = {block["id"]: block["text"] for block in public}
    texts.update({figure["id"]: figure["svg"].decode("utf-8") for figure in figures})
    report = audit_bound_text(value["payload"], texts, value["blocks"])
    require(report["status"] != "blocked", "document_fidelity_blocked")
    return report


def _fidelity_summary(report):
    return {"contract_version": "1", "status": report["status"], "input_hash": report["input_hash"],
            "scope": report["scope"], "natural_language_verified": False,
            "professional_review": "not_performed", "report": "internal/fidelity-review.json"}


def _reading_scope(root, spec, public, *, admission=None):
    if "reading_scope" not in spec:
        return None
    from .fidelity import audit_reading_scope
    value = spec["reading_scope"]
    require(isinstance(value, dict) and set(value) == {"payload", "blocks"}, "document_reading_scope_fields")
    scoped = [block for block in public if block["kind"] == "reading_scope"]
    require(bool(scoped) and isinstance(value["blocks"], dict) and set(value["blocks"]) == {b["id"] for b in scoped},
            "document_reading_scope_blocks_required")
    projected = audit_reading_scope(value["payload"])
    sources = {source["id"]: source for source in spec["sources"]}
    for document in value["payload"]["documents"]:
        source = sources.get(document["id"])
        require(source is not None and source.get("version") == document["version"]
                and source["sha256"] == document["sha256"]
                and _read(root, source, guarded=admission is not None).decode("utf-8") == document["text"], "document_reading_scope_source_binding")
    require(projected["status"] != "blocked", "document_reading_scope_blocked")
    statements = {row["id"]: row for row in projected["statements"]}
    records = {row["id"]: row for row in projected["readings"]}
    evidence = {row["id"]: row for row in value["payload"]["documents"]}
    for block in scoped:
        ref = value["blocks"][block["id"]]
        require(isinstance(ref, str) and ref in statements, "document_reading_scope_statement_unknown")
        if block.get("generate", False):
            citations = [records[identity]["citation"] for identity in statements[ref]["reading_ids"]]
            primary = [cite for cite in citations if cite["document_id"] == block["source_id"]]
            require(bool(primary), "document_reading_scope_source_range")
            source_lines = evidence[block["source_id"]]["text"].splitlines(keepends=True)
            span_start = sum(map(len, source_lines[:block["start_line"] - 1]))
            span_end = span_start + sum(map(len, source_lines[block["start_line"] - 1:block["end_line"]]))
            require(all(span_start <= cite["start"] < cite["end"] <= span_end for cite in primary),
                    "document_reading_scope_source_range")
            block["derivation"] = {"kind": "reading_scope_projection_v1", "statement_id": ref,
                "citations": citations, "source_text_sha256": block["text_sha256"],
                "primary_source_span": {"start": span_start, "end": span_end},
                "literal_source_copy": False}
            block["text"] = statements[ref]["projection"]
            block["text_sha256"] = sha256_bytes(block["text"].encode("utf-8"))
    report = audit_reading_scope(value["payload"], texts={b["id"]: b["text"] for b in scoped}, bindings=value["blocks"])
    require(report["status"] != "blocked", "document_reading_scope_blocked")
    return report


def _reading_scope_summary(report):
    return {"contract_version": "1", "status": report["status"], "input_hash": report["input_hash"],
            "scope": report["scope"], "natural_language_verified": False, "evidence_authentication": "not_performed",
            "professional_review": "not_performed", "bound_blocks": len(report["artifact_bindings"]),
            "report": "internal/reading-scope-review.json"}


def _patent_final_gate(spec, public):
    if spec["business"] != "patent" or not (spec.get("delivery_stage") == "final"
                                           or "final_text_sources" in spec):
        return None
    from .patent_gate import require_final_document
    sources = spec.get("final_text_sources")
    if sources is None:
        sources = [row for row in spec.get("fidelity", {}).get("payload", {}).get("documents", [])
                   if row.get("role") == "original"]
    return require_final_document(public, sources)


def build(root, spec, output, *, synthetic=False, research_example=False, pdf_tool=None, admission=None):
    mode = _mode(synthetic, research_example, admission)
    admission_report = None
    if admission is not None:
        require(pdf_tool is None, "authorized_case_pdf_not_supported")
        admission_report = check_document_admission(root, spec, admission, output=output)
    executable = None
    if pdf_tool is not None:
        executable = Path(pdf_tool)
        require(executable.is_absolute() and executable.is_file(), "pdf_tool_absolute_file_required")
        require(executable.name.lower() in {"soffice", "soffice.exe", "soffice.com"}, "pdf_tool_not_supported")
        executable = executable.resolve(strict=True)
    blocks, images = resolve_document(root, spec, research_example=research_example, admission=admission)
    public = [b for b in blocks if b["audience"] == "body"]
    internal = [b for b in blocks if b["audience"] == "internal"]
    reading_scope = _reading_scope(root, spec, public, admission=admission)
    fidelity = _fidelity(spec, public, images)
    docx = make_docx(public, images, profile=spec.get("profile"))
    checks = inspect_generated_docx(docx, public, images, profile=spec.get("profile"))
    quality = quality_docx(docx, stage=spec.get("delivery_stage", "draft"), business=spec["business"])
    _quality_gate(quality)
    final_text_gate = _patent_final_gate(spec, public)
    files = {"body/document.docx": docx, "body/source.txt": ("\n\n".join(b["text"] for b in public) + "\n").encode("utf-8"),
             "internal/notes.txt": ("\n\n".join(b["text"] for b in internal) + "\n").encode("utf-8"),
             "internal/source-map.json": _source_map(spec, blocks),
             "internal/quality-review.json": canonical_bytes(quality) + b"\n"}
    if fidelity is not None:
        files["internal/fidelity-review.json"] = canonical_bytes(fidelity) + b"\n"
    if final_text_gate is not None:
        files["internal/final-text-gate.json"] = canonical_bytes(final_text_gate) + b"\n"
    if reading_scope is not None:
        files["internal/reading-scope-review.json"] = canonical_bytes(reading_scope) + b"\n"
    for f in images:
        files[f"body/{f['id']}.svg"] = f["svg"]
    manifest = {"generator": "dyz-documents", "generator_version": VERSION, "document_id": spec["document_id"],
        "version": spec["version"], "business": spec["business"], "input_sha256": digest(spec), "checks": checks,
        "files": [{"path": p, "sha256": sha256_bytes(data), "bytes": len(data)} for p, data in sorted(files.items())],
        "status": "needs_review", "visual_review": "not_performed", "pdf": "not_generated",
        "professional_review": "not_performed", "external_action": "not_performed", "mode": mode,
        "limitations": ["A4 body and optional A3 internal review figure appendix; no official format assertion.", "Image binding does not prove rendering fidelity.", "Fixed source text does not prove technical or legal correctness.", "Caller must protect the authorized root against concurrent replacement."]}
    if spec.get("profile") is not None:
        manifest["profile"] = document_profile(spec["profile"])
    manifest["quality"] = _quality_summary(quality)
    if final_text_gate is not None:
        manifest["final_text_gate"] = {"status": final_text_gate["status"],
                                       "input_hash": final_text_gate["input_hash"]}
    manifest["delivery_state"] = "internal_draft" if quality["stage"] == "draft" else "needs_review"
    if fidelity is not None:
        manifest["fidelity"] = _fidelity_summary(fidelity)
    if reading_scope is not None:
        manifest["reading_scope"] = _reading_scope_summary(reading_scope)
    if research_example:
        manifest["research_scope"] = _research_scope(spec)
    if admission_report is not None:
        manifest["admission"] = check_document_admission(root, spec, admission, output=output)
    target = _case_path(root, output, must_exist=False) if admission is not None else safe_path(root, output, must_exist=False)
    require(target.parent.is_dir(), "output_parent_missing")
    require(not target.exists(), "output_exists")
    target.mkdir()  # 原子占用新目录，不覆盖原件；失败时保留部分结果供检查。
    (target / "body").mkdir()
    (target / "internal").mkdir()
    for name, data in files.items():
        with (target / name).open("xb") as stream:
            stream.write(data)
    if executable is not None:
        # 显式选择已安装的LibreOffice；参数列表不经shell，也不复用日常办公profile。
        # 输入是本模块生成、核对且无外链的DOCX；超时或失败保留产物，不能标为成功。
        with tempfile.TemporaryDirectory(prefix="dyz-office-") as profile:
            process = subprocess.run([str(executable), "-env:UserInstallation=" + Path(profile).as_uri(),
                "--headless", "--convert-to", "pdf", "--outdir", str(target / "body"),
                str(target / "body/document.docx")], capture_output=True, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        pdf = target / "body/document.pdf"
        require(process.returncode == 0 and pdf.is_file() and pdf.read_bytes().startswith(b"%PDF-"), "pdf_conversion_failed")
        raw_pdf = pdf.read_bytes()
        manifest["files"].append({"path": "body/document.pdf", "sha256": sha256_bytes(raw_pdf), "bytes": len(raw_pdf)})
        manifest["pdf"] = "generated_needs_content_and_visual_review"
        manifest["pdf_tool"] = {"name": executable.name, "sha256": sha256_bytes(executable.read_bytes())}
    with (target / "manifest.json").open("xb") as stream:
        stream.write(canonical_bytes(manifest) + b"\n")
    return manifest


def verify(root, spec, output, *, synthetic=False, research_example=False, admission=None):
    """回读整个明确产物目录，新增文件或改后未重建均拒绝；不认可视觉或专业状态。"""
    mode = _mode(synthetic, research_example, admission)
    admission_report = check_document_admission(root, spec, admission, output=output) if admission is not None else None
    blocks, figures = resolve_document(root, spec, research_example=research_example, admission=admission)
    public = [b for b in blocks if b["audience"] == "body"]
    internal = [b for b in blocks if b["audience"] == "internal"]
    reading_scope = _reading_scope(root, spec, public, admission=admission)
    fidelity = _fidelity(spec, public, figures)
    final_text_gate = _patent_final_gate(spec, public)
    target = _guard_output(root, output) if admission is not None else safe_path(root, output)
    manifest = strict_json_loads((target / "manifest.json").read_text(encoding="utf-8"))
    if admission_report is not None:
        require(manifest.get("admission") == admission_report, "document_admission_binding_changed")
    else:
        require("admission" not in manifest, "document_admission_binding_changed")
    require(manifest["input_sha256"] == digest(spec), "document_input_binding_changed")
    identity = {"generator": "dyz-documents", "generator_version": VERSION,
                "document_id": spec["document_id"], "version": spec["version"],
                "business": spec["business"], "mode": mode}
    require(all(manifest.get(key) == value for key, value in identity.items()),
            "document_manifest_identity_changed")
    state = {"status": "needs_review", "visual_review": "not_performed",
             "professional_review": "not_performed", "external_action": "not_performed"}
    require(all(manifest.get(key) == value for key, value in state.items()),
            "document_manifest_state_changed")
    if research_example:
        require(manifest.get("research_scope") == _research_scope(spec), "document_research_scope_changed")
    else:
        require("research_scope" not in manifest, "document_research_scope_changed")
    expected = {"body/document.docx", "body/source.txt", "internal/notes.txt", "internal/source-map.json", "internal/quality-review.json"}
    if final_text_gate is not None:
        expected.add("internal/final-text-gate.json")
        require(manifest.get("final_text_gate") == {"status": final_text_gate["status"],
                "input_hash": final_text_gate["input_hash"]}, "document_final_gate_summary_changed")
        require((target / "internal/final-text-gate.json").read_bytes()
                == canonical_bytes(final_text_gate) + b"\n", "document_final_gate_report_changed")
    else:
        require("final_text_gate" not in manifest, "document_final_gate_not_performed")
    if fidelity is not None:
        expected.add("internal/fidelity-review.json")
        require(manifest.get("fidelity") == _fidelity_summary(fidelity), "document_fidelity_summary_changed")
        require((target / "internal/fidelity-review.json").read_bytes() == canonical_bytes(fidelity) + b"\n",
                "document_fidelity_report_changed")
    else:
        require("fidelity" not in manifest, "document_fidelity_not_performed")
    if reading_scope is not None:
        expected.add("internal/reading-scope-review.json")
        require(manifest.get("reading_scope") == _reading_scope_summary(reading_scope), "document_reading_scope_summary_changed")
        require((target / "internal/reading-scope-review.json").read_bytes() == canonical_bytes(reading_scope) + b"\n",
                "document_reading_scope_report_changed")
    else:
        require("reading_scope" not in manifest, "document_reading_scope_not_performed")
    expected.update(f"body/{f['id']}.svg" for f in figures)
    if manifest["pdf"] == "generated_needs_content_and_visual_review":
        expected.add("body/document.pdf")
    else:
        require(manifest["pdf"] == "not_generated", "document_pdf_status_invalid")
    rows = manifest["files"]
    require(len(rows) == len(expected) and {r["path"] for r in rows} == expected, "document_manifest_members_changed")
    require({p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()} == expected | {"manifest.json"}, "document_directory_members_changed")
    for row in rows:
        path = safe_path(target, row["path"])
        raw = path.read_bytes()
        require(len(raw) == row["bytes"] and sha256_bytes(raw) == row["sha256"], "document_artifact_changed")
    raw_docx = (target / "body/document.docx").read_bytes()
    checks = inspect_generated_docx(raw_docx, public, figures, profile=spec.get("profile"))
    if spec.get("profile") is not None:
        require(manifest.get("profile") == document_profile(spec["profile"]), "document_profile_binding_changed")
    else:
        require("profile" not in manifest, "document_profile_binding_changed")
    quality = quality_docx(raw_docx, stage=spec.get("delivery_stage", "draft"), business=spec["business"])
    _quality_gate(quality)
    require((target / "internal/quality-review.json").read_bytes() == canonical_bytes(quality) + b"\n",
            "document_quality_report_changed")
    require(manifest.get("quality") == _quality_summary(quality), "document_quality_summary_changed")
    delivery_state = "internal_draft" if quality["stage"] == "draft" else "needs_review"
    require(manifest.get("delivery_state") == delivery_state, "document_delivery_state_changed")
    require(manifest.get("checks") == checks, "document_manifest_checks_changed")
    for name, content in (("body/source.txt", "\n\n".join(b["text"] for b in public) + "\n"),
                          ("internal/notes.txt", "\n\n".join(b["text"] for b in internal) + "\n")):
        require((target / name).read_bytes() == content.encode("utf-8"), "document_text_file_changed")
    require((target / "internal/source-map.json").read_bytes() == _source_map(spec, blocks), "document_source_map_changed")
    for figure in figures:
        require((target / f"body/{figure['id']}.svg").read_bytes() == figure["svg"], "document_figure_changed")
    result = {"status": "needs_review", "checks": checks, "file_hashes_equal": True,
              "visual_review": "not_performed", "professional_review": "not_performed"}
    if spec.get("profile") is not None:
        result["profile"] = document_profile(spec["profile"])
    if admission_report is not None:
        result["admission"] = admission_report
    result["quality"] = _quality_summary(quality)
    if final_text_gate is not None:
        result["final_text_gate"] = {"status": final_text_gate["status"],
                                     "input_hash": final_text_gate["input_hash"]}
    result["delivery_state"] = delivery_state
    if fidelity is not None:
        result["fidelity"] = _fidelity_summary(fidelity)
    if reading_scope is not None:
        result["reading_scope"] = _reading_scope_summary(reading_scope)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="合成稿或显式研究示例DOCX与源行映射；可选本地PDF，不发送")
    declarations = parser.add_mutually_exclusive_group()
    declarations.add_argument("--synthetic", action="store_true")
    declarations.add_argument("--research-example", action="store_true", help="原创研究/合成文本及逐文件依据；不验证真实权利")
    parser.add_argument("--root", default=".")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pdf-tool", help="显式指定已安装soffice的绝对路径；不安装依赖")
    parser.add_argument("--verify", action="store_true", help="只回读已有产物，拒绝多余成员或改后未重建")
    args = parser.parse_args(argv)
    try:
        _mode(args.synthetic, args.research_example)
        path = safe_path(args.root, args.input)
        require(path.stat().st_size <= MAX_BYTES, "document_input_size")
        spec = strict_json_loads(path.read_text(encoding="utf-8"))
        if args.verify:
            require(args.pdf_tool is None, "verify_does_not_convert")
            verify(args.root, spec, args.output, synthetic=args.synthetic, research_example=args.research_example)
            print("document_verified_needs_review")
        else:
            build(args.root, spec, args.output, synthetic=args.synthetic,
                  research_example=args.research_example, pdf_tool=args.pdf_tool)
            print("document_written_needs_review")
        return 0
    except (ContractError, ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile):
        print("document_contract_rejected")
        return 2
    except (OSError, subprocess.TimeoutExpired):
        print("document_io_failed_partial_output_may_remain")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
