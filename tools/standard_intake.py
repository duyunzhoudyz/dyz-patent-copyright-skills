"""集中收集获准标准材料，生成同一v2内部草稿及后续成件准入描述。

只读取明确列出且有预期原始字节hash的文件；原文不作任意自然语言解析。
控制台声明不认证身份、许可真实性、专业正确性、意见决定或正式外发权限。
"""

from __future__ import annotations

import copy
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from tools import core, standards

DATA_PATHS = ("host_model", "index", "telemetry", "tools", "logs", "subprocess")
PURPOSE = "standard_internal_preparation"
MAX_MATERIALS = 100
MAX_ROWS = 1000
MAX_FILE_BYTES = 20_000_000
MAX_PAYLOAD_BYTES = 5_000_000
MAX_LINE_CHARACTERS = 100_000
MATERIAL_ROLES = {"draft", "source", "comment", "template", "payload", "report", "other"}
STRENGTHS = {"requirement", "recommendation", "permission", "statement"}
KINDS = {"normative", "informative"}


def _line(ask: Callable[[str], str], prompt: str) -> str:
    value = ask(prompt)
    core.require(isinstance(value, str), "standard_intake_text_required")
    core.require(len(value) <= MAX_LINE_CHARACTERS, "standard_intake_line_too_large")
    core.require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value)
                 and "\x00" not in value, "standard_intake_text_invalid")
    return value


def _answer(ask: Callable[[str], str], prompt: str, *, optional: bool = False) -> str:
    value = _line(ask, prompt).strip()
    core.require(optional or bool(value), "standard_intake_answer_required")
    return value


def _choice(ask: Callable[[str], str], prompt: str, choices: set[str],
            *, default: str | None = None) -> str:
    value = _answer(ask, prompt, optional=default is not None) or default
    core.require(value in choices, "standard_intake_choice_invalid")
    return value


def _sha256(value: str) -> None:
    core.require(len(value) == 64 and all(char in "0123456789abcdef" for char in value),
                 "invalid_expected_sha256")


def _plain_path(path: Path, *, file: bool = False) -> None:
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        core.require(not stat.S_ISLNK(info.st_mode)
                     and not getattr(info, "st_file_attributes", 0) & 0x400,
                     "standard_intake_link_rejected")
        if current == path and file:
            core.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                         "standard_intake_file_alias_rejected")
        else:
            core.require(stat.S_ISDIR(info.st_mode), "standard_intake_directory_required")


def _path(base: Path, relative: str, *, exists: bool = True, file: bool = False) -> Path:
    resolved = core.safe_path(base, relative, must_exist=exists)
    # safe_path会解析根内链接；必须另核词法路径，以免内部别名绕过读取范围。
    _plain_path(base / relative.replace("\\", "/"), file=file)
    return resolved


def _check_access(context: dict | None) -> None:
    if context is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    # public也核六数据路径；真实文件不能借公开标签继承合成模式的宽松路径。
    core.preflight(context["environment"], context["permissions"],
                   sensitivity="restricted", purpose=PURPOSE, now=now)
    for action in ("local_process", "copy", "local_write"):
        core.check_permission(context["permissions"], action=action, purpose=PURPOSE,
                              recipient="local_tool", now=now)


def _context(ask: Callable[[str], str]) -> dict:
    sensitivity = _choice(
        ask, "真实材料敏感等级（public/confidential/restricted，不得改标synthetic）：",
        {"public", "confidential", "restricted"},
    )
    assessment = _answer(ask, "覆盖宿主模型、索引、遥测、工具、日志及子进程的核验依据：")
    paths = []
    for path_id in DATA_PATHS:
        mode = _choice(
            ask, f"数据路径 {path_id} 的已核状态（local/disabled；未知或外部停止本入口）：",
            {"local", "disabled"},
        )
        evidence = _answer(ask, f"数据路径 {path_id} 的具体核验依据：")
        core.require(evidence.casefold() not in {"local", "disabled", "本地", "离线"},
                     "data_path_evidence_required")
        paths.append({"id": path_id, "mode": mode, "verified": True, "evidence": evidence})
    authority = _answer(
        ask, "授权随后明确列出的原件用于本地读取、处理、复制和新目录写入的依据"
             "（仅内部准备，不含正式外发）：",
    )
    valid_from = _answer(ask, "上述四项本地许可生效时间（ISO 8601，带时区）：")
    valid_until = _answer(ask, "上述四项本地许可截止时间（ISO 8601，带时区）：")
    permission = {"purpose": PURPOSE, "recipient": "local_tool", "decision": "allow",
                  "authority_evidence": authority, "valid_from": valid_from,
                  "valid_until": valid_until}
    context = {
        "sensitivity": sensitivity,
        "environment": {"data_paths": paths, "assessment_evidence": assessment,
                        "assessment_status": "operator_declaration_not_independently_verified"},
        "permissions": [{**permission, "action": action} for action in
                        ("local_read", "local_process", "copy", "local_write")],
    }
    _check_access(context)
    return context


def _materials(ask: Callable[[str], str]) -> list[dict]:
    rows = []
    while True:
        line = _line(
            ask, "已有获准材料逐行输入 id<TAB>根内相对路径<TAB>预期原字节sha256<TAB>"
                 "角色(draft/source/comment/template/payload/report/other)<TAB>来源及版本定位；"
                 "输入完毕留空（不自动解析正文）：",
        )
        if not line:
            break
        core.require(len(rows) < MAX_MATERIALS, "standard_intake_material_limit")
        fields = line.split("\t")
        core.require(len(fields) == 5 and all(value.strip() for value in fields),
                     "standard_intake_material_line_invalid")
        identity, relative, expected, role, source = (value.strip() for value in fields)
        _sha256(expected)
        core.require(role in MATERIAL_ROLES, "standard_intake_material_role_invalid")
        core.require(identity not in {row["id"] for row in rows}, "standard_intake_duplicate_material")
        rows.append({"id": identity, "path": relative, "expected_sha256": expected,
                     "role": role, "source": source})
    return rows


def _material_paths(base: Path, destination: Path, rows: list[dict]) -> list[Path]:
    paths, identities = [], set()
    for row in rows:
        path = _path(base, row["path"], file=True)
        core.require(not path.is_relative_to(destination), "standard_source_output_collision")
        info = path.stat()
        core.require(info.st_size <= (MAX_PAYLOAD_BYTES if row["role"] == "payload"
                                      else MAX_FILE_BYTES), "standard_intake_material_too_large")
        identity = (info.st_dev, info.st_ino)
        core.require(path not in paths and identity not in identities,
                     "standard_intake_duplicate_material")
        identities.add(identity)
        row["path"] = path.relative_to(base).as_posix()
        paths.append(path)
    return paths


def _read_materials(base: Path, destination: Path, rows: list[dict], context: dict | None,
                    *, payload: bool = False) -> dict | None:
    paths = _material_paths(base, destination, rows)
    document = None
    for row, path in zip(rows, paths, strict=True):
        _check_access(context)
        core.require(_path(base, row["path"], file=True) == path,
                     "standard_intake_material_path_changed")
        limit = MAX_PAYLOAD_BYTES if row["role"] == "payload" else MAX_FILE_BYTES
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        core.require(len(raw) <= limit, "standard_intake_material_too_large")
        actual = core.sha256_bytes(raw)
        core.require(actual == row["expected_sha256"], "standard_intake_material_hash_changed")
        row["sha256"] = actual
        row["content_handling"] = ("strict_v2_json" if row["role"] == "payload"
                                   else "original_retained_not_parsed")
        if payload and row["role"] == "payload":
            try:
                document = core.strict_json_loads(raw.decode("utf-8"))
            except UnicodeDecodeError:
                raise core.ContractError("standard_intake_json_encoding_invalid") from None
    return document


def _record_lines(ask: Callable[[str], str], prompt: str, count: int) -> list[tuple[str, list[str]]]:
    rows = []
    while True:
        line = _line(ask, prompt)
        if not line:
            return rows
        core.require(len(rows) < MAX_ROWS, "standard_intake_record_limit")
        fields = line.split("\t")
        core.require(len(fields) == count, "standard_intake_record_line_invalid")
        core.require(bool(fields[0].strip()) and bool(fields[-1].strip()),
                     "standard_intake_record_line_invalid")
        core.require(fields[0].strip() not in {row[1][0].strip() for row in rows},
                     "standard_intake_duplicate_record")
        rows.append((line, fields))


def _draft(ask: Callable[[str], str], sensitivity: str) -> dict:
    unknowns = []
    labels = ("标准名称", "项目ID", "当前版本", "意见所针对的基线版本",
              "组织", "标准类型", "技术领域", "当前阶段")
    keys = ("standard_name", "project_id", "version", "baseline_version",
            "adaptation/organization", "adaptation/standard_type",
            "adaptation/domain", "adaptation/stage")
    values = []
    for label, key in zip(labels, keys, strict=True):
        value = _answer(ask, label + "（未知留空，保留缺口）：", optional=True)
        if not value:
            unknowns.append(key)
        values.append(value or "unknown")
    name, project, version, baseline = values[:4]
    clauses, raw_clauses = [], []
    for raw, fields in _record_lines(
        ask, "当前条款逐行输入 id<TAB>强度(requirement/recommendation/permission/statement/?)"
             "<TAB>性质(normative/informative/?)<TAB>来源定位或?"
             "<TAB>条件(分号分隔；-明确无；?未知)<TAB>例外(同前)<TAB>完整原文；完毕留空：", 7,
    ):
        identity, strength, kind, source, conditions, exceptions = (
            value.strip() for value in fields[:6]
        )
        core.require(strength in STRENGTHS | {"?"}, "standard_intake_strength_invalid")
        core.require(kind in KINDS | {"?"}, "standard_intake_kind_invalid")
        item = {"id": identity, "text": fields[6]}
        for key, value in (("strength", strength), ("kind", kind), ("source", source),
                           ("conditions", conditions), ("exceptions", exceptions)):
            if value == "?":
                unknowns.append(f"clauses/{len(clauses)}/{key}")
            elif key in {"conditions", "exceptions"}:
                parsed = [] if value == "-" else value.split(";")
                core.require(all(part.strip() for part in parsed),
                             "standard_intake_clause_list_invalid")
                item[key] = parsed
            else:
                core.require(bool(value), "standard_intake_record_line_invalid")
                item[key] = value
        clauses.append(item)
        raw_clauses.append(raw)
    comments, raw_comments = [], []
    for raw, fields in _record_lines(
        ask, "原意见逐行输入 id<TAB>条款ID或document<TAB>针对版本或?"
             "<TAB>提出者ID或?<TAB>来源定位或?<TAB>完整原意见；完毕留空"
             "（只采集原意见，不生成采纳决定）：", 6,
    ):
        identity, target, aimed_version, participant, source = (
            value.strip() for value in fields[:5]
        )
        core.require(bool(target) and target != "?", "standard_intake_comment_target_required")
        item = {"id": identity, "text": fields[5]}
        item["scope" if target == "document" else "clause_id"] = target
        for key, value in (("version", aimed_version), ("participant_id", participant),
                           ("source", source)):
            core.require(bool(value), "standard_intake_record_line_invalid")
            if value == "?":
                unknowns.append(f"comments/{len(comments)}/{key}")
            item[key] = "unknown" if value == "?" else value
        comments.append(item)
        raw_comments.append(raw)
    collection = _choice(
        ask, "意见收集状态（complete/partial/unknown/not_started，留空为unknown）：",
        {"complete", "partial", "unknown", "not_started"}, default="unknown",
    )
    evidence = None
    if collection == "complete":
        evidence = _answer(ask, "完整收集的已有依据（未取得可留空，仍报告缺证）：", optional=True)
    profile = {"id": "internal-eleven", "version": "1", "scope": "internal",
               "required_sections": list(standards.COMPILATION_NOTE_SECTIONS)}
    # 未知语义字段缺省，交同一业务检查产生缺证；不得用空数组、假决定或假说明补齐。
    payload = {
        "contract_version": 2, "standard_name": name, "project_id": project,
        "version": version, "baseline_version": baseline, "sensitivity": sensitivity,
        "delivery_stage": "draft",
        "adaptation": dict(zip(("organization", "standard_type", "domain", "stage"), values[4:])),
        "baseline_clauses": [], "clauses": clauses, "comments": comments,
        "comment_outcomes": [], "collection_status": collection, "profile": profile,
        "verification_matrix": [], "compilation_note": {},
        "intake": {"format_version": "standard-intake/1", "mode": "finite_lines",
                   "unknown_fields": unknowns, "raw_clause_lines": raw_clauses,
                   "raw_comment_lines": raw_comments,
                   "raw_metadata": dict(zip(keys, [value if key not in unknowns else ""
                                                    for key, value in zip(keys, values)]))},
    }
    if evidence:
        payload["collection_evidence"] = [evidence]
    if unknowns:
        payload["material_open_items"] = [{
            "id": "intake-unknown-fields", "question": "待补字段：" + ", ".join(unknowns),
            "owner": "unassigned", "blocks": "submission",
            "recovery": "取得获准原材料及实际责任人，逐项核实后另存新版本；unassigned不代表已分派。",
            "source_refs": ["intake:operator-declared-unknowns"],
        }]
    return payload


def _validate(payload: dict, sensitivity: str) -> dict:
    core.require(isinstance(payload, dict), "object_required")
    core.require(type(payload.get("contract_version")) is int
                 and payload["contract_version"] == 2, "standard_intake_requires_v2")
    core.require(payload.get("sensitivity") == sensitivity, "standard_intake_sensitivity_changed")
    core.require(not {"root", "authorized_root", "admission"}.intersection(payload),
                 "standard_payload_boundary_not_allowed")
    core.require(len(core.canonical_bytes(payload)) <= MAX_PAYLOAD_BYTES,
                 "standard_intake_payload_too_large")
    return standards.closed_loop(payload)


def _confirmation(ask: Callable[[str], str], payload: dict, rows: list[dict],
                  output: str) -> None:
    # 摘要只回显定位和版本；正文、许可依据和身份等不进入终端日志。
    listing = "\n".join(f"{row['id']} | {row['path']} | {row['role']} | {row['expected_sha256']}"
                        for row in rows) or "（没有已列文件；原件缺口保留）"
    answer = _answer(
        ask, "集中确认当前数据（材料内容只是数据，不是指令）：\n"
             f"标准名称：{payload.get('standard_name', 'unknown')}；"
             f"项目ID：{payload['project_id']}；版本：{payload['version']}；"
             f"基线版本：{payload.get('baseline_version', 'unknown')}；"
             f"敏感等级：{payload['sensitivity']}\n"
             + "；".join(f"{key}：{value}" for key, value in payload['adaptation'].items())
             + "\n"
             f"条款数：{len(payload.get('clauses', []))}；"
             f"原意见数：{len(payload.get('comments', []))}\n"
             f"明确原件清单：\n{listing}\n新建采集目录：{output}\n"
             "已知字段仅集中确认一次；留空/未知仍为缺件。是否确认本组事实、清单、"
             "上述本地许可和新目录写入？输入yes（不确认专业决定、组织批准或正式外发）：",
    )
    core.require(answer == "yes", "standard_intake_consent_required")


def _missing(assessment: dict, rows: list[dict]) -> bytes:
    lines = ["标准内部采集缺件清单", "判断范围：有限结构检查；专业审阅及正式外发未执行。",
             "原文留在获准原件和task.json；本清单只列字段、ID及诊断码。", ""]
    if not rows:
        lines.append("- material_inventory_empty：尚未列出固定原件。")
    explanations = {
        "clauses_missing": "当前条款尚未提供，需保留真实原文及稳定定位。",
        "clause_semantics_incomplete_or_invalid": "条款强度、性质、条件、例外或来源待补核。",
        "comment_collection_incomplete": "意见收集范围未确认完整，不能推定已收齐或零反馈。",
        "zero_comment_collection_evidence_missing": "声明零意见且已收齐，但缺完整收集依据。",
        "comment_clause_missing": "原意见的目标条款尚未定位到基线或当前稿。",
        "comment_outcome_missing": "原意见尚无处置建议；不得自动补造采纳决定。",
        "comment_decision_unconfirmed": "处置仍为建议，需真实有权角色另行核对。",
        "verification_matrix_missing": "验证矩阵未提供，不填试验或已执行结果。",
        "compilation_note_structure_missing": "实质编制说明未提供，不用空壳代替。",
        "open_item_stage_blocked": "未决事项阻塞相应阶段，须补证并明确实际责任人。",
    }
    for issue in assessment["issues"]:
        detail = explanations.get(issue["code"], "按同一业务契约核对该记录及缺失依据。")
        lines.append(f"- {issue['code']} | {issue.get('record_id', '')}：{detail}")
    if not assessment["issues"]:
        lines.append("- 没有本范围确定性问题；仍需专业审阅及适用来源核验。")
    lines += ["", "采集未补造来源、试验、决定、阈值、签核或权限；材料索引不证明命题适用。",
              "同意采集仅形成后续prepare-standard的本地准入描述；正式行动须独立授权。"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write(base: Path, relative: str, value: dict | bytes, context: dict | None) -> bytes:
    _check_access(context)
    target = _path(base, relative, exists=False)
    core.require(target.parent.is_dir(), "output_parent_missing")
    if isinstance(value, bytes):
        with target.open("xb") as stream:
            stream.write(value)
        return value
    core.write_new_json(base, relative, value)
    return core.canonical_bytes(value) + b"\n"


def _collect(root: str | Path, output: str, ask: Callable[[str], str], *, synthetic: bool) -> dict:
    core.require(type(synthetic) is bool, "standard_synthetic_flag_invalid")
    lexical_root = Path(root).absolute()
    _plain_path(lexical_root)
    base = lexical_root.resolve(strict=True)
    core.require(base.is_dir(), "authorized_root_required")
    if not synthetic:
        package = Path(__file__).resolve().parents[1]
        core.require(not base.is_relative_to(package) and not package.is_relative_to(base),
                     "standard_case_root_must_be_independent")
    destination = _path(base, output, exists=False)
    core.require(not destination.exists(), "output_exists")
    core.require(destination.parent.is_dir(), "output_parent_missing")
    output_relative = destination.relative_to(base).as_posix()
    context = None if synthetic else _context(ask)
    sensitivity = "synthetic" if synthetic else context["sensitivity"]
    mode = _choice(ask, "采集方式（lines有限行/v2已有获准v2 JSON；留空为lines）：",
                   {"lines", "v2"}, default="lines")
    rows = _materials(ask)
    _material_paths(base, destination, rows)
    payload_rows = [row for row in rows if row["role"] == "payload"]
    core.require(len(payload_rows) == (1 if mode == "v2" else 0),
                 "standard_intake_payload_selection_invalid")
    if mode == "v2":
        # 先完成六路径、当前权限及全部原件路径预检，再读已列v2提取已知字段。
        payload = _read_materials(base, destination, rows, context, payload=True)
        payload = copy.deepcopy(payload)
    else:
        payload = _draft(ask, sensitivity)
    assessment = _validate(payload, sensitivity)
    _confirmation(ask, payload, rows, output_relative)
    _check_access(context)
    # 集中问答后的实际原件仍须符合先前预期hash，不能就地计算新hash当作新授权。
    _read_materials(base, destination, rows, context)
    assessment = _validate(payload, sensitivity)
    task_relative = f"{output_relative}/task.json"
    index_relative = f"{output_relative}/material-index.json"
    missing_relative = f"{output_relative}/missing-items.txt"
    pack_relative = f"{output_relative}/pack"
    task_raw = core.canonical_bytes(payload) + b"\n"
    index = {"format_version": "standard-material-index/1", "mode": "synthetic" if synthetic
             else "authorized_case", "sensitivity": sensitivity, "materials": rows,
             "task": {"path": task_relative, "sha256": core.sha256_bytes(task_raw),
                      "payload_hash": core.digest(payload)},
             "proposition_support": "not_verified", "originals": "not_modified"}
    missing_raw = _missing(assessment, rows)
    authorization_relative = None if synthetic else f"{output_relative}/authorization.json"
    authorization = None if synthetic else {
        "root": str(base), "output": pack_relative, "payload_hash": core.digest(payload),
        "input_hash": core.sha256_bytes(task_raw),
        "inputs": {task_relative: core.sha256_bytes(task_raw),
                   **{row["path"]: row["sha256"] for row in rows}},
        "sensitivity": sensitivity, "purpose": PURPOSE,
        "permissions": context["permissions"], "environment": context["environment"],
    }
    summary = {
        "status": "collected", "mode": "synthetic" if synthetic else "authorized_case",
        "input": task_relative, "input_sha256": core.sha256_bytes(task_raw),
        "payload_hash": core.digest(payload), "output": pack_relative,
        "authorization": authorization_relative,
        "authorization_sha256": None if synthetic else core.sha256_bytes(
            core.canonical_bytes(authorization) + b"\n"),
        "material_index": index_relative, "material_index_sha256": core.sha256_bytes(
            core.canonical_bytes(index) + b"\n"),
        "missing_items": missing_relative, "missing_items_sha256": core.sha256_bytes(missing_raw),
        "issue_codes": sorted({item["code"] for item in assessment["issues"]}),
        "professional_review": "not_performed", "external_action": "not_performed",
    }
    _check_access(context)
    core.require(_path(base, output_relative, exists=False) == destination,
                 "standard_intake_output_path_changed")
    core.require(not destination.exists(), "output_exists")
    destination.mkdir()
    _write(base, task_relative, payload, context)
    _write(base, index_relative, index, context)
    if authorization is not None:
        _write(base, authorization_relative, authorization, context)
    _write(base, missing_relative, missing_raw, context)
    # 完成收据最后写入；失败半目录保留现场，不得覆盖重试或误作完整采集。
    _write(base, f"{output_relative}/summary.json", summary, context)
    return summary


def collect(root: str | Path, output: str, *, input_fn: Callable[[str], str] = input,
            synthetic: bool = False) -> dict:
    """集中收集同一v2草稿，输出目录须不存在且父目录已存在。

    默认真实模式先核独立根、六数据路径和当前四项本地许可。输入有限TAB行
    或一个有预期原字节hash的获准v2文件；已有字段只集中确认一次，未知保留。
    合成路径必须显式synthetic=True，不产生真实授权描述，不重标任何导入材料。
    返回相对input/output、索引/缺件清单及实际字节hash；authorization的固定九字段
    直接供prepare-standard使用，不承载意见确认、包确认或正式外部权限。
    """
    try:
        return _collect(root, output, input_fn, synthetic=synthetic)
    except (EOFError, KeyboardInterrupt):
        raise core.ContractError("standard_intake_cancelled") from None
    except (OSError, RuntimeError, OverflowError):
        raise core.ContractError("standard_intake_io_failed") from None
