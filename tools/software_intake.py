"""将操作者的逐项声明收集为获准本地软件准备输入，不扫描或执行源码。

输入和证据引用不等于事实认证、权属认定或专业批准。仅支持单组件；多组件
或外部处理交给有相应独立授权的低层入口，不能从“本地”推定宿主离线。
"""

from __future__ import annotations

import copy
import fnmatch
import io
import json
import os
import re
import stat
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from tools import core, software, software_delivery, software_discovery
from tools.software import MODES, SOURCE_SUFFIXES

DATA_PATHS = ("host_model", "index", "telemetry", "tools", "logs", "subprocess")
PURPOSE = "software_internal_preparation"
GENERATED_DIRECTORIES = {"output", "outputs", "artifacts", "build", "dist"}
ARTIFACT_MARKERS = ("authorization.json", "delivery-manifest.json")
MAX_FILE_BYTES = 10_000_000


def _answer(ask: Callable[[str], str], prompt: str, *, optional: bool = False) -> str:
    value = ask(prompt)
    core.require(isinstance(value, str), "intake_text_required")
    value = value.strip()
    core.require(optional or bool(value), "intake_answer_required")
    return value


def _choice(ask: Callable[[str], str], prompt: str, choices: set[str]) -> str:
    value = _answer(ask, prompt)
    core.require(value in choices, "intake_choice_invalid")
    return value


def _consent(ask: Callable[[str], str], prompt: str) -> None:
    core.require(_answer(ask, prompt) == "yes", "intake_consent_required")


def _check_access(context: dict) -> None:
    # 实际读取与写入均按当前时间复核，问答过程不能延长许可有效期。
    context["now"] = datetime.now(timezone.utc).isoformat()
    core.preflight(context["environment"], context["permissions"],
                   sensitivity=context["sensitivity"], purpose=context["purpose"],
                   now=context["now"])
    core.check_permission(context["permissions"], action="local_write",
                          purpose=context["purpose"], recipient="local_tool",
                          now=context["now"])


def _context(ask: Callable[[str], str]) -> dict:
    sensitivity = _choice(
        ask, "材料敏感等级（synthetic/public/confidential/restricted）：",
        {"synthetic", "public", "confidential", "restricted"},
    )
    assessment = _answer(ask, "覆盖宿主模型、索引、遥测、工具、日志、子进程的评估依据：")
    paths = []
    for path_id in DATA_PATHS:
        mode = _choice(
            ask, f"数据路径 {path_id} 的已核实状态（local/disabled；未知或外部请退出）：",
            {"local", "disabled"},
        )
        evidence = _answer(ask, f"数据路径 {path_id} 的具体核验依据（不能仅写本地）：")
        core.require(evidence.lower() not in {"local", "disabled", "本地", "离线"},
                     "data_path_evidence_required")
        paths.append({"id": path_id, "mode": mode, "verified": True,
                      "evidence": evidence})
    _consent(ask, "是否有权为本次软件内部准备逐项读取随后列明的文件？输入 yes 同意：")
    _consent(ask, "是否有权在指定新目录写入请求、授权及后续内部材料？输入 yes 同意：")
    authority = _answer(ask, "上述 local_read/local_write 授权的真实依据或证据引用：")
    valid_from = _answer(ask, "本地读写授权生效时间（ISO 8601，必须带时区）：")
    valid_until = _answer(ask, "本地读写授权截止时间（ISO 8601，必须带时区）：")
    permission = {"purpose": PURPOSE, "recipient": "local_tool", "decision": "allow",
                  "authority_evidence": authority, "valid_from": valid_from,
                  "valid_until": valid_until}
    context = {
        "environment": {
            "data_paths": paths, "assessment_evidence": assessment,
            "assessment_status": "operator_declaration_not_independently_verified",
        },
        "permissions": [{**permission, "action": action}
                        for action in ("local_read", "local_write")],
        "sensitivity": sensitivity, "purpose": PURPOSE,
    }
    _check_access(context)
    return context


def _date_fact(ask: Callable[[str], str], label: str) -> dict | None:
    value = _answer(ask, f"{label}（YYYY-MM-DD；未知留空）：", optional=True)
    if not value:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        raise core.ContractError("invalid_date_fact") from None
    return {"value": value, "evidence_id": _answer(ask, f"{label}的证据引用：")}


def _scope_and_rights(ask: Callable[[str], str]) -> tuple[dict, list, str]:
    name = _answer(ask, "软件名称（单组件模式）：")
    version = _answer(ask, "本次软件版本：")
    mode = _choice(ask, "软件形态（GUI/API/CLI/embedded）：", MODES)
    _consent(ask, "是否确认刚才输入的软件名称、版本和形态？输入 yes 确认：")
    completed = _date_fact(ask, "开发完成日期")
    published = _date_fact(ask, "首次发表日期")
    runtime = _answer(ask, "运行环境描述（未经核实或未知留空）：", optional=True)
    runtime_fact = None
    if runtime:
        runtime_fact = {"description": runtime,
                        "evidence_id": _answer(ask, "运行环境的证据引用：")}
    origin = _choice(
        ask, "组件来源（own/existing/third_party/ai；不确定请退出，不得默认原创）：",
        {"own", "existing", "third_party", "ai"},
    )
    origin_evidence = _answer(ask, "组件来源的证据引用：")
    claim = _answer(ask, "本次主张的具体表达（无主张或未知留空）：", optional=True)
    exclusion = _answer(ask, "排除的表达或暂不主张的范围（无则留空）：", optional=True)
    core.require(bool(claim or exclusion), "claim_or_exclusion_required")
    owner = _answer(ask, "已知原始权利人（未知留空，不从 Git 或文件日期推定）：", optional=True)
    subjects = []
    if owner:
        subjects.append({"subject_id": owner,
                         "basis": _answer(ask, "该主体的权属依据："),
                         "evidence_id": _answer(ask, "该主体权属依据的证据引用：")})
    component = {
        "id": "main", "kind": "standalone", "version": version, "origin": origin,
        "origin_evidence": origin_evidence, "claim": [claim] if claim else [],
        "exclusions": [exclusion] if exclusion else [], "subjects": subjects,
        "original_right_holder": owner or None,
    }
    if origin == "existing":
        component["baseline_evidence"] = _answer(
            ask, "已有版本的基线证据（未知留空）：", optional=True,
        ) or None
    rights = {"component_id": "main", "requested_decision": "claim" if claim else "exclude"}
    if origin == "third_party":
        rights["requested_decision"] = "retain_notice"
        rights["license"] = _answer(ask, "第三方许可及范围（未知留空）：", optional=True) or None
        rights["notice"] = _answer(ask, "应保留的第三方声明（未知留空）：", optional=True) or None
    if origin == "ai":
        contribution = _answer(ask, "可核实的人类贡献（未知留空）：", optional=True)
        rights["human_contribution"] = None
        if contribution:
            rights["human_contribution"] = {
                "description": contribution,
                "evidence_ids": [_answer(ask, "人类贡献的证据引用：")],
            }
    local_process = _choice(
        ask, "该组件材料的本地处理权限（allow/deny/unknown；不等于权属）：",
        {"allow", "deny", "unknown"},
    )
    deposit = _choice(
        ask, "该组件纳入交存候选材料的权限（allow/deny/unknown；不执行提交）：",
        {"allow", "deny", "unknown"},
    )
    rights_evidence = _answer(ask, "材料权限的证据引用（未知留空）：", optional=True)
    rights.update(
        evidence_ids=[rights_evidence] if rights_evidence else [],
        permissions={"local_process": local_process, "deposit": deposit,
                     "public": "deny", "cloud": "deny"},
    )
    metadata = {"software_id": "software", "name": name, "version": version,
                "completed_date": completed, "published_date": published,
                "runtime_environment": runtime_fact}
    return {"metadata": metadata, "components": [component]}, [rights], mode


def _manual(ask: Callable[[str], str], mode: str) -> dict | None:
    facts = []
    while True:
        fact = _answer(ask, "一项已有证据的软件事实（无或全部输入完毕留空）：", optional=True)
        if not fact:
            break
        facts.append({"id": f"fact-{len(facts) + 1}", "text": fact,
                      "evidence_id": _answer(ask, "这项软件事实的证据引用：")})
    if not facts:
        return None
    operations = []
    while True:
        value = _answer(
            ask, f"真实操作 operation-{len(operations) + 1} 的输入（全部输入完毕留空）：",
            optional=True,
        )
        if not value:
            break
        operations.append({
            "id": f"operation-{len(operations) + 1}", "input": value,
            "expected_output": _answer(ask, "该操作的预期输出（不冒充已执行结果）："),
            "failure": _answer(ask, "该操作的失败路径或错误表现："),
            "evidence_id": _answer(ask, "该操作输入、输出和失败路径的证据引用："),
        })
    core.require(bool(operations), "operations_required")
    return {"mode": mode, "facts": facts, "operations": operations, "runtime_evidence": []}


def _screenshots(ask: Callable[[str], str], base: Path, destination: Path,
                 excluded: list[Path], paths: set[Path], identities: set,
                 manual: dict | None, version: str) -> list[dict]:
    if manual is None or manual["mode"] != "GUI":
        return []
    operations = {row["id"] for row in manual["operations"]}
    screenshots = []
    while True:
        relative = _answer(
            ask, "已有真实 PNG 截图的根内相对路径（不采集；无或输入完毕留空）：", optional=True,
        )
        if not relative:
            return screenshots
        core.require(len(screenshots) < 100, "screenshots_list_required")
        path = core.safe_path(base, relative)
        core.require(path.is_file() and path.suffix.lower() == ".png", "screenshot_png_required")
        core.require(not path.is_relative_to(destination), "source_output_collision")
        core.require(not any(path.is_relative_to(folder) for folder in excluded),
                     "artifact_screenshot_forbidden")
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        core.require(path not in paths and identity not in identities, "screenshot_duplicate_path")
        core.require(stat.st_size <= software_delivery.MAX_IMAGE_BYTES, "screenshot_too_large")
        operation = _choice(ask, "截图对应的操作 ID（" + "/".join(sorted(operations)) + "）：",
                            operations)
        image_version = _answer(ask, "该截图实际软件版本（必须与本次版本一致）：")
        core.require(image_version == version, "screenshot_version_mismatch")
        for action in ("capture", "local_use"):
            decision = _choice(
                ask, f"该现成截图的 {action} 权限（allow/deny/unknown；不授权新采集）：",
                {"allow", "deny", "unknown"},
            )
            core.require(decision == "allow", "screenshot_permission_not_proven")
        capture = _answer(ask, "真实截图采集证据引用（须证明与本次源码清单及构建对应）：")
        local_use = _answer(ask, "该 PNG 本地读取及纳入内部候选材料的授权证据引用：")
        state = _answer(ask, "截图中实际可见的状态（不将预期结果当作已执行）：")
        image_id = f"shot{len(screenshots) + 1}"
        screenshots.append({
            "id": image_id, "path": path.relative_to(base).as_posix(),
            "version": image_version, "operation_id": operation,
            "capture_evidence": capture, "local_use_evidence": local_use, "visible_state": state,
        })
        manual["runtime_evidence"].append({
            "id": image_id, "version": image_version, "evidence_id": capture, "kind": "screenshot",
        })
        paths.add(path)
        identities.add(identity)


def _in_generated_directory(path: Path, root: Path) -> bool:
    for parent in path.parents:
        if parent == root:
            return False
        if parent.name.casefold() in GENERATED_DIRECTORIES:
            return True
        if any((parent / marker).exists() for marker in ARTIFACT_MARKERS):
            return True
    return False


def _collect(root: str | Path, output: str, ask: Callable[[str], str]) -> dict:
    context = _context(ask)
    base = Path(root).resolve(strict=True)
    core.require(base.is_dir(), "authorized_root_required")
    destination = core.safe_path(base, output, must_exist=False)
    core.require(not destination.exists(), "output_exists")
    core.require(destination.parent.is_dir(), "output_parent_missing")
    output_relative = destination.relative_to(base).as_posix()
    material_relative = f"{output_relative}/materials"
    excluded_directories = []
    while True:
        relative = _answer(
            ask, "已有材料/产物目录的根内相对路径（逐项输入；没有或输入完毕留空）：",
            optional=True,
        )
        if not relative:
            break
        directory = core.safe_path(base, relative)
        core.require(directory.is_dir(), "artifact_directory_required")
        excluded_directories.append(directory)
    files, paths, identities = [], set(), set()
    while True:
        relative = _answer(ask, "授权源码文件的根内相对路径（逐项输入；输入完毕留空）：", optional=True)
        if not relative:
            break
        path = core.safe_path(base, relative)
        core.require(path.is_file(), "source_file_required")
        core.require(not path.is_relative_to(destination), "source_output_collision")
        core.require(not _in_generated_directory(path, base), "generated_source_forbidden")
        core.require(not any(path.is_relative_to(folder) for folder in excluded_directories),
                     "generated_source_forbidden")
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        core.require(path not in paths and identity not in identities, "duplicate_source_path")
        core.require(stat.st_size <= MAX_FILE_BYTES, "source_file_too_large")
        paths.add(path)
        identities.add(identity)
        entry = {"id": f"file-{len(files) + 1}", "path": path.relative_to(base).as_posix(),
                 "component_id": "main", "kind": "source", "include": True}
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            entry["source_type_evidence"] = _answer(ask, "该扩展名文件确为源码的证据引用：")
        files.append(entry)
    core.require(bool(files), "file_inventory_required")
    inventory = _choice(
        ask, "上述文件是否构成本版完整源码清单（yes/no/unknown；仅记录声明，不扫描）：",
        {"yes", "no", "unknown"},
    )
    scope, rights, mode = _scope_and_rights(ask)
    if scope["components"][0]["origin"] in {"existing", "third_party"}:
        for entry in files:
            entry["deposit_context_evidence"] = _answer(
                ask, "下一项已列文件纳入交存上下文的必要性证据（按输入顺序；未知留空）：",
                optional=True,
            )
    manual = _manual(ask, mode)
    screenshots = _screenshots(ask, base, destination, excluded_directories, paths, identities,
                               manual, scope["metadata"]["version"])
    selection = _choice(ask, "成品选页（all/head_tail；首尾选页须等物理页验证）：",
                        {"all", "head_tail"})
    secrets = []
    while True:
        # 秘密按原字面值保留，不strip改变待检文本，也不在确认提示中回显。
        value = ask("已知敏感字面值（只存内部请求供成品阻断；逐项输入，输入完毕留空）：")
        core.require(isinstance(value, str), "intake_text_required")
        if not value:
            break
        secrets.append(value)
    # 成功摘要必须保留可直接使用的授权路径；含声明秘密时拒绝，不返回失真的脱敏路径。
    core.require(not any(secret in f"{output_relative}/authorization.json" for secret in secrets),
                 "intake_sensitive_output_path")
    listing = ("本次授权源码：\n" + "\n".join(entry["path"] for entry in files)
               + "\n本次授权 PNG：\n" + ("\n".join(
                   entry["path"] + " -> " + entry["operation_id"] for entry in screenshots) or "无")
               + f"\n新建请求目录：{output_relative}\n")
    for secret in sorted(secrets, key=len, reverse=True):
        listing = listing.replace(secret, "[敏感字面值]")
    _consent(
        ask, listing + "上述均为操作者声明而非专业批准；仅为内部候选、不外发、不执行源码、不生成截图。"
             "是否确认全部输入并允许现在逐文件读取、核验 PNG、计算哈希及写入两个新 JSON？输入 yes：",
    )
    _check_access(context)
    scoped = software.run("SW-01", {"context": context, **scope}, use_system_time=True)
    entitled = software.run(
        "SW-07", {"context": context, "scope": scoped["artifacts"], "rights": rights},
        use_system_time=True,
    )
    # 文件读取许可不能越过组件材料权限；哈希也必须遵守 SW 的禁止读取决定。
    core.require(all(item["decision"] not in {"prohibit", "needs_permission"}
                     for item in entitled["artifacts"]["decisions"]),
                 "material_permission_not_proven")
    core.require(not destination.exists(), "output_exists")
    # 所有路径再次过界限与别名检查后才读任何材料，避免后列坏路径导致前列提前读取。
    materials, paths, identities = [], set(), set()
    for entries, image in ((files, False), (screenshots, True)):
        for entry in entries:
            path = core.safe_path(base, entry["path"])
            core.require(path.is_file() and not path.is_relative_to(destination)
                         and not any(path.is_relative_to(folder) for folder in excluded_directories),
                         "material_path_changed")
            core.require(image or not _in_generated_directory(path, base), "source_path_changed")
            core.require(not image or path.suffix.lower() == ".png", "screenshot_png_required")
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino)
            core.require(path not in paths and identity not in identities, "duplicate_material_path")
            limit = software_delivery.MAX_IMAGE_BYTES if image else MAX_FILE_BYTES
            core.require(stat.st_size <= limit, "material_file_too_large")
            paths.add(path)
            identities.add(identity)
            materials.append((entry, path, limit, image))
    bindings = []
    for entry, path, limit, image in materials:
        _check_access(context)
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
        core.require(len(content) <= limit, "material_file_too_large")
        byte_hash = core.sha256_bytes(content)
        if image:
            software_delivery._png(content)
        del content
        entry["sha256" if image else "expected_sha256"] = byte_hash
        bindings.append({"path": entry["path"], "sha256": byte_hash})
    request = {
        "scope_input": scope, "rights": rights, "files": files,
        "inventory_complete": inventory == "yes",
        "pagination": {"selection": "all", "lines_per_page": 50, "wrap_columns": 78,
                       "basis": "internal_candidate_not_verified_registration_rule"},
        "delivery": {"selection": selection, "screenshots": screenshots,
                     "sensitive_literals": secrets},
    }
    if manual is not None:
        request["manual_input"] = manual
    if screenshots:
        # 使用真正选材manifest的顺序和哈希，不用清单顺序自行拼出另一种构建绑定。
        preparation = software.prepare({
            **{key: value for key, value in request.items() if key != "delivery"},
            "authorized_root": str(base), "context": context,
        }, use_system_time=True)["artifacts"]
        build = software_delivery.build_binding(preparation)
        for image in screenshots:
            image["build_binding"] = build
    request_path = f"{output_relative}/request.json"
    authorization_path = f"{output_relative}/authorization.json"
    request_hash = core.sha256_bytes(core.canonical_bytes(request) + b"\n")
    authorization = {
        "kind": "software_local_authorization", "authorized_root": str(base),
        "context": context, "request": {"path": request_path, "sha256": request_hash},
        "files": bindings, "output": material_relative,
    }
    _check_access(context)
    authorization_hash = core.sha256_bytes(core.canonical_bytes(authorization) + b"\n")
    core.require(core.safe_path(base, output, must_exist=False) == destination,
                 "output_path_changed")
    # 目录和文件均排他创建；材料目录由后续 build-software 负责新建。
    destination.mkdir()
    core.write_new_json(base, request_path, request)
    core.write_new_json(base, authorization_path, authorization)
    return {"status": "collected", "authorization": authorization_path,
            "authorization_sha256": authorization_hash}


def _collect_candidates(root: str | Path, output: str, ask: Callable[[str], str],
                        payload: dict | None) -> dict:
    context = None
    if payload is not None:
        core.require(isinstance(payload, dict), "object_required")
        payload = copy.deepcopy(payload)
        context = payload.get("context")
    if context is None:
        context = _context(ask)
    _check_access(context)
    base = Path(root).resolve(strict=True)
    destination = core.safe_path(base, output, must_exist=False)
    core.require(not destination.exists(), "output_exists")
    core.require(destination.parent.is_dir(), "output_parent_missing")
    relative_output = destination.relative_to(base).as_posix()
    if payload is None:
        files = []
        while True:
            relative = _answer(ask, "明确授权读取的根内文件路径（源码/配置/README，逐项；完毕留空）：",
                               optional=True)
            if not relative:
                break
            files.append({"id": f"file-{len(files) + 1}", "path": relative,
                          "component_id": "main"})
        core.require(bool(files), "file_inventory_required")
        name = _answer(ask, "本次软件全称（由操作者声明，不以包名代替）：")
        version = _answer(ask, "本次软件版本：")
        mode = _choice(ask, "软件形态（GUI/API/CLI/embedded）：", MODES)
        origin = _choice(ask, "组件来源（own/existing/third_party/ai/generated；未知请停止补证）：",
                         {"own", "existing", "third_party", "ai", "generated"})
        origin_evidence = _answer(ask, "本次软件身份及组件来源的依据：")
        decision = _choice(ask, "上列全部文件的本地处理许可（allow/deny/unknown）：",
                           {"allow", "deny", "unknown"})
        deposit = _choice(ask, "上列文件作为交存候选上下文的许可（allow/deny/unknown）：",
                          {"allow", "deny", "unknown"})
        evidence = _answer(ask, "明确覆盖上列全部文件及所声明本地处理/交存范围的许可依据（未知留空）：",
                           optional=True)
        inventory = _choice(ask, "上列是否为完整源码清单（yes/no/unknown；不扫描）：",
                            {"yes", "no", "unknown"})
        secrets = []
        while True:
            value = ask("已知敏感字面值（不回显，逐项输入，完毕留空）：")
            core.require(isinstance(value, str), "intake_text_required")
            if not value:
                break
            secrets.append(value)
        component = {"id": "main", "kind": "standalone", "version": version,
                     "origin": origin, "origin_evidence": origin_evidence,
                     "claim": [], "exclusions": ["本次主张范围待补证"], "subjects": [],
                     "original_right_holder": None}
        request = {
            "scope_input": {"metadata": {"software_id": "software", "name": name,
                                          "version": version, "completed_date": None,
                                          "published_date": None, "runtime_environment": None},
                            "components": [component]},
            "rights": [{"component_id": "main", "requested_decision": "exclude",
                        "evidence_ids": [evidence] if evidence else [],
                        "permissions": {"local_process": decision, "deposit": deposit,
                                        "public": "deny", "cloud": "deny"}}],
            "files": files, "inventory_complete": inventory == "yes",
            "pagination": {"selection": "all", "lines_per_page": 50, "wrap_columns": 78,
                           "basis": "internal_candidate_not_verified_registration_rule"},
        }
        payload = {"context": context, "files": files, "request": request,
                   "material_permissions": [{"paths": [item["path"] for item in files],
                                             "decision": decision, "evidence_id": evidence}],
                   "sensitive_literals": secrets,
                   "options": {"selection": "all", "screenshots": [],
                               "sensitive_literals": secrets}}
    request = copy.deepcopy(payload.get("request"))
    core.require(isinstance(request, dict), "discovery_request_required")
    if "inventory_complete" in request:
        core.require(type(request["inventory_complete"]) is bool, "inventory_complete_bool_required")
    for declared_root in (payload.get("authorized_root"), request.get("authorized_root")):
        if declared_root is not None:
            core.require(Path(declared_root).resolve(strict=True) == base,
                         "discovery_project_mismatch")
    files = payload.get("files", request.get("files"))
    core.require(isinstance(files, list) and bool(files), "file_inventory_required")
    # 在文件、授权请求或配置读取前，统一规范化文件与 material_permissions，阻断反斜杠/大小写/硬链接 deny 绕过。
    normalized_cand_files = []
    cand_lexicals: dict[str, tuple[Path, Path, os.stat_result]] = {}
    for index, entry in enumerate(files, start=1):
        core.require(isinstance(entry, dict) and isinstance(entry.get("path"), str), "source_file_required")
        fpath, lexical, info, rel = _check_source_file_safety(
            base, entry["path"], destination, reject_generated=False,
        )
        item = copy.deepcopy(entry)
        item["path"] = rel
        item.setdefault("id", f"file-{index}")
        normalized_cand_files.append(item)
        cand_lexicals[rel] = (fpath, lexical, info)
    (
        has_explicit_exclusions,
        explicit_paths,
        explicit_dirs,
        exclude_patterns,
        extra_excluded_records,
    ) = _collect_explicit_exclusions(base, payload, request)
    for key in ("excluded_files", "excluded_paths", "excluded_directories", "exclude_patterns", "excluded_sources"):
        request.pop(key, None)
    discovery_input = {**payload, "context": context, "authorized_root": str(base),
                       "request": request, "files": normalized_cand_files}
    if "material_permissions" in payload and payload["material_permissions"] is not None:
        norm_perms, _allowed, blocked_paths, blocked_ids = _normalize_material_permissions(
            base, payload["material_permissions"],
        )
        discovery_input["material_permissions"] = norm_perms
        for item in normalized_cand_files:
            _, _, info = cand_lexicals[item["path"]]
            core.require(
                item["path"] not in blocked_paths and (info.st_dev, info.st_ino) not in blocked_ids,
                "material_permission_not_proven",
            )
    for item in normalized_cand_files:
        _, _, info = cand_lexicals[item["path"]]
        core.require(info.st_nlink == 1, "source_file_or_link_invalid")
        _check_file_permission_denial(item)
    secrets = payload.get("sensitive_literals", payload.get("options", {}).get("sensitive_literals", []))
    core.require(isinstance(secrets, list) and all(isinstance(value, str) and value for value in secrets),
                 "sensitive_literals_required")
    discovery_input["sensitive_literals"] = secrets
    core.require(not any(secret in f"{relative_output}/authorization.json" for secret in secrets),
                 "intake_sensitive_output_path")
    files = normalized_cand_files
    _consent(ask, "是否现在读取上述明确授权清单并生成内部候选供集中核对？输入 yes：")
    excluded_sources = []
    excluded_paths_seen: set[str] = set()
    if has_explicit_exclusions:
        request["inventory_complete"] = False
    probe_targets = []
    for item in files:
        fpath, _, _ = cand_lexicals[item["path"]]
        explicit_hit, explicit_reason = _match_explicit_exclusion(
            item, fpath, explicit_paths, explicit_dirs, exclude_patterns,
        )
        if explicit_hit:
            request["inventory_complete"] = False
            excluded_sources.append({
                "id": item["id"],
                "path": item["path"],
                "read_status": "not_read",
                "exclusion_reason": explicit_reason,
            })
            excluded_paths_seen.add(item["path"])
        else:
            probe_targets.append(item)
    _append_unmatched_explicit_exclusions(
        excluded_sources, excluded_paths_seen, explicit_paths, explicit_dirs, extra_excluded_records,
    )
    if excluded_sources:
        request["inventory_complete"] = False
    discovery_input["files"] = probe_targets
    software_discovery._file_permissions(discovery_input)
    discover_files, unreadable_entries = _probe_readable_for_discovery(
        probe_targets, cand_lexicals, context,
    )
    if unreadable_entries:
        request["inventory_complete"] = False
        excluded_sources.extend(unreadable_entries)
    core.require(bool(discover_files), "file_inventory_required")
    discovery_input["files"] = discover_files
    request_file_kinds = {}
    declared_request_paths: set[str] = set()
    if isinstance(request.get("files"), list):
        for r_idx, r_entry in enumerate(request["files"], start=1):
            if isinstance(r_entry, dict):
                if "kind" in r_entry:
                    request_file_kinds[r_entry.get("id", f"file-{r_idx}")] = r_entry["kind"]
                if isinstance(r_entry.get("path"), str):
                    try:
                        r_rel = core.safe_path(base, r_entry["path"], must_exist=False).relative_to(base).as_posix()
                        declared_request_paths.add(r_rel)
                        if "kind" in r_entry:
                            request_file_kinds[r_rel] = r_entry["kind"]
                    except core.ContractError:
                        request["inventory_complete"] = False
    while True:
        discovery = _discover_with_unreadable_fallback(
            discovery_input, cand_lexicals, excluded_sources, request, "file_inventory_required",
        )
        candidate_files = {entry["id"]: entry for entry in discovery["file_candidates"]}
        normalized = []
        discovery_exclusions = []
        for entry in discover_files:
            item = candidate_files[entry["id"]]
            if item["read_status"] != "read" or item["exclusion_reason"]:
                request["inventory_complete"] = False
                discovery_exclusions.append({key: item[key] for key in
                                             ("id", "path", "read_status", "exclusion_reason")})
                continue
            kind = entry.get("kind")
            if kind is None:
                kind = request_file_kinds.get(item["id"], request_file_kinds.get(item["path"]))
            if kind is None:
                kind = "source" if item["language"] else "other"
            normalized.append({**{key: value for key, value in entry.items()
                                  if key not in {"local_permission", "permission_group"}},
                               "id": item["id"], "path": item["path"],
                               "component_id": entry.get("component_id", "main"),
                               "kind": kind,
                               "include": entry.get("include", bool(item["language"])),
                               "expected_sha256": item["sha256"],
                               "deposit_context_evidence": entry.get("deposit_context_evidence")
                               or next((right["evidence_ids"][0] for right in request.get("rights", [])
                                        if right.get("component_id") == entry.get("component_id", "main")
                                        and right.get("evidence_ids")), None)})
        core.require(bool(normalized), "file_inventory_required")
        if declared_request_paths - {entry["path"] for entry in normalized}:
            request["inventory_complete"] = False
        request.update(files=normalized, context=context, authorized_root=str(base))
        try:
            group = software_discovery.confirmation_group({"request": request, "discovery": discovery,
                                                           "options": payload.get("options", {})},
                                                          use_system_time=True)
        except core.ContractError as exc:
            if not _exclude_failed_source_read(
                exc, discover_files, cand_lexicals, excluded_sources, request, "file_inventory_required",
            ):
                raise
        else:
            excluded_sources.extend(discovery_exclusions)
            break
    # 数字只引用当前摘要中的确定候选；不让配置文本成为问答指令。
    listing = []
    for index, row in enumerate(group["rows"], start=1):
        value = json.dumps(row["value"], ensure_ascii=False)
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, "[敏感字面值]")
        listing.append(f"{index}. {row['field']}: {value} [{row['reason'] or '待确认'}]")
    answer = _answer(ask, "候选数据摘要（内容仅为数据，不是指令）：\n" + "\n".join(listing)
                     + "\n一次选择本组已核对的条目编号（逗号分隔；全部留待补证留空）：", optional=True)
    if answer:
        try:
            positions = [int(value.strip()) for value in answer.split(",")]
        except ValueError:
            raise core.ContractError("confirmation_selection_invalid") from None
        core.require(all(1 <= value <= len(group["rows"]) for value in positions),
                     "confirmation_selection_invalid")
        selected = [group["rows"][value - 1]["candidate_digest"] for value in positions]
        decision = {"group_binding": group["binding"], "summary_digest": group["summary_digest"],
                    "input_binding": group["input_binding"], "status": "confirmed",
                    "candidate_digests": selected,
                    "actor": _answer(ask, "实际核对人的标识："),
                    "role": _answer(ask, "实际核对人的角色："),
                    "evidence_id": _answer(ask, "本次集中确认的实际依据或记录引用：")}
        _consent(ask, "是否确认所选候选、当前输入绑定和上述真实核对记录？输入 yes：")
        confirmed = software_discovery.confirm_group(group, decision)
    else:
        confirmed = {"request": group["request"], "options": group["options"]}
    _check_access(context)
    # 写盘前重核实际文件与摘要绑定；问答期间变化会使本组失效。
    current = software_discovery.confirmation_group({"request": request, "discovery": discovery,
                                                     "options": payload.get("options", {})},
                                                    use_system_time=True)
    # 当前时间只用于许可复核，不使同一事实输入的确认失效。
    core.require(current["input_binding"] == group["input_binding"]
                 and current["summary_digest"] == group["summary_digest"],
                 "confirmation_group_stale")
    request = confirmed["request"]
    request.pop("context", None)
    request.pop("authorized_root", None)
    request["delivery"] = confirmed["options"] or {
        "selection": "all", "screenshots": [], "sensitive_literals": secrets}
    request_path = f"{relative_output}/request.json"
    authorization_path = f"{relative_output}/authorization.json"
    authorization = {"kind": "software_local_authorization", "authorized_root": str(base),
                     "context": context,
                     "request": {"path": request_path,
                                 "sha256": core.sha256_bytes(core.canonical_bytes(request) + b"\n")},
                     "files": [{"path": entry["path"], "sha256": entry["sha256"]}
                               for entry in discovery["file_candidates"]
                               if entry["read_status"] == "read" and not entry["exclusion_reason"]],
                     "output": f"{relative_output}/materials"}
    if excluded_sources:
        authorization["excluded_sources"] = excluded_sources
    _check_access(context)
    core.require(not destination.exists(), "output_exists")
    destination.mkdir()
    core.write_new_json(base, request_path, request)
    core.write_new_json(base, authorization_path, authorization)
    summary = {"status": "collected", "authorization": authorization_path,
               "authorization_sha256": core.sha256_bytes(core.canonical_bytes(authorization) + b"\n"),
               "inventory_complete": request["inventory_complete"]}
    if excluded_sources:
        summary["excluded_sources"] = excluded_sources
    return summary


def collect_candidates(root: str | Path, output: str, *, ask: Callable[[str], str] = input,
                       payload: dict | None = None) -> dict:
    """集中入口；payload 可提供已授权 context/request/files/许可组，省去手写内部 JSON。

    无 payload 时只询问身份、明确文件清单、覆盖该清单的本地许可、候选确认组；
    日期、权属、主张、正文及运行事实未知保留待补。旧 collect 的问答路径不变。
    输出与 collect 一致，供原 build-software 授权入口使用，不写材料正文。
    """
    try:
        return _collect_candidates(root, output, ask, payload)
    except (EOFError, KeyboardInterrupt):
        raise core.ContractError("intake_cancelled") from None
    except (OSError, RuntimeError, OverflowError):
        raise core.ContractError("intake_io_failed") from None


def collect(root: str | Path, output: str, *, ask: Callable[[str], str] = input) -> dict:
    """收集单组件内部材料请求，仅返回授权相对路径、字节哈希及状态。

    输出目录必须不存在且父目录已存在。所有问答和授权检查通过后才读取
    逐项文件；所有文件校验和哈希完成后才排他创建输出目录。EOF、中断及
    文件系统错误只暴露固定诊断码，不回显私有路径、输入或材料正文。
    无法确认来源时拒绝，不将未知来源当作原创；权属、日期和材料权限允许
    保持未知，后续准备应保留 partial；但本地材料处理被拒绝或未获证明时，
    在读取哈希前拒绝本次收集。GUI可引用已有PNG的真实采集及本地使用依据，
    按操作ID、版本、原字节与当前源码构建绑定；不执行程序或截图，也不认证
    调用者所报运行证据的真实性。选页及敏感字面值交由后续成品链检查；不生成
    字段确认或专业批准。
    """
    try:
        return _collect(root, output, ask)
    except (EOFError, KeyboardInterrupt):
        raise core.ContractError("intake_cancelled") from None
    except (OSError, RuntimeError, OverflowError):
        raise core.ContractError("intake_io_failed") from None


def _check_source_file_safety(
    base: Path,
    raw_path: str,
    destination: Path | None,
    *,
    reject_generated: bool = True,
) -> tuple[Path, Path, os.stat_result, str]:
    """校验源码文件路径边界与词法链，拦截越界、符号链接与目录联接。"""
    fpath = core.safe_path(base, raw_path)
    lexical = base.joinpath(*raw_path.replace("\\", "/").split("/"))
    try:
        info = core.checked_path(lexical)
    except (OSError, core.BundleError):
        raise core.ContractError("source_file_or_link_invalid") from None
    core.require(stat.S_ISREG(info.st_mode), "source_file_required")
    if reject_generated:
        core.require(not _in_generated_directory(fpath, base), "generated_source_forbidden")
    if destination is not None:
        core.require(not fpath.is_relative_to(destination), "source_output_collision")
    return fpath, lexical, info, fpath.relative_to(base).as_posix()


def _is_discovery_auto_skipped(relative: str) -> bool:
    """与 software_discovery 一致：生成目录或敏感密钥文件绝不在预检阶段打开。"""
    parts = {part.casefold() for part in Path(relative).parts}
    name = Path(relative).name.casefold()
    return (
        bool(parts & software_discovery.GENERATED_PARTS)
        or name == ".env"
        or name.startswith(".env.")
        or Path(relative).suffix.casefold() in {".pem", ".key", ".p12", ".pfx"}
    )


def _collect_explicit_exclusions(
    base: Path,
    *containers: dict | None,
) -> tuple[bool, dict[str, str], list[tuple[Path, str, str]], list[str], list[dict]]:
    """收集并校验调用方显式声明的排除路径、目录、模式或排除清单。"""
    has_explicit = False
    explicit_paths: dict[str, str] = {}
    explicit_dirs: list[tuple[Path, str, str]] = []
    exclude_patterns: list[str] = []
    extra_records: list[dict] = []

    def parse_path_entry(raw_entry: object, default_reason: str) -> tuple[Path, str, str]:
        if isinstance(raw_entry, str):
            raw_p, reason = raw_entry, default_reason
        elif isinstance(raw_entry, dict) and isinstance(raw_entry.get("path"), str):
            raw_p = raw_entry["path"]
            raw_r = raw_entry.get("exclusion_reason") or raw_entry.get("reason")
            core.require(raw_r is None or isinstance(raw_r, str), "excluded_files_invalid")
            reason = raw_r.strip() if isinstance(raw_r, str) and raw_r.strip() else default_reason
        else:
            raise core.ContractError("excluded_files_invalid")
        resolved = core.safe_path(base, raw_p, must_exist=False)
        lexical = base.joinpath(*raw_p.replace("\\", "/").split("/"))
        try:
            core.checked_path(lexical, missing_leaf=True)
        except core.BundleError as exc:
            if str(exc) != "bundle_path_missing":
                raise core.ContractError("source_file_or_link_invalid") from None
        return resolved, resolved.relative_to(base).as_posix(), reason

    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("excluded_files", "excluded_paths"):
            if key not in container or container[key] is None:
                continue
            entries = container[key]
            core.require(isinstance(entries, list), "excluded_files_invalid")
            if entries:
                has_explicit = True
            for raw_entry in entries:
                _, rel, reason = parse_path_entry(raw_entry, "caller_excluded")
                explicit_paths.setdefault(rel, reason)
        if "excluded_directories" in container and container["excluded_directories"] is not None:
            entries = container["excluded_directories"]
            core.require(isinstance(entries, list), "excluded_files_invalid")
            if entries:
                has_explicit = True
            for raw_entry in entries:
                dpath, rel, reason = parse_path_entry(raw_entry, "caller_excluded_directory")
                explicit_dirs.append((dpath, rel, reason))
        if "exclude_patterns" in container and container["exclude_patterns"] is not None:
            patterns = container["exclude_patterns"]
            core.require(
                isinstance(patterns, list)
                and all(isinstance(pat, str) and bool(pat.strip()) for pat in patterns),
                "excluded_files_invalid",
            )
            if patterns:
                has_explicit = True
                exclude_patterns.extend(pat.strip() for pat in patterns)
        if "excluded_sources" in container and container["excluded_sources"] is not None:
            entries = container["excluded_sources"]
            core.require(isinstance(entries, list), "excluded_files_invalid")
            if entries:
                has_explicit = True
            for idx, raw_entry in enumerate(entries, start=1):
                _, rel, reason = parse_path_entry(raw_entry, "caller_excluded")
                explicit_paths.setdefault(rel, reason)
                entry_id = (
                    raw_entry["id"]
                    if isinstance(raw_entry, dict) and isinstance(raw_entry.get("id"), str) and raw_entry["id"].strip()
                    else f"excluded-source-{idx}"
                )
                extra_records.append({
                    "id": entry_id,
                    "path": rel,
                    "read_status": "not_read",
                    "exclusion_reason": reason,
                })
    return has_explicit, explicit_paths, explicit_dirs, exclude_patterns, extra_records


def _match_explicit_exclusion(
    item: dict,
    fpath: Path,
    explicit_paths: dict[str, str],
    explicit_dirs: list[tuple[Path, str, str]],
    exclude_patterns: list[str],
) -> tuple[bool, str]:
    rel = item["path"]
    raw_reason = item.get("exclusion_reason")
    core.require(raw_reason is None or isinstance(raw_reason, str), "excluded_files_invalid")
    item_reason = raw_reason.strip() if isinstance(raw_reason, str) and raw_reason.strip() else ""
    if "excluded" in item:
        core.require(type(item["excluded"]) is bool, "excluded_files_invalid")
    if item.get("excluded") is True:
        return True, item_reason or "caller_excluded"
    if item.get("include") is False or item_reason:
        return True, item_reason or "caller_excluded"
    if rel in explicit_paths:
        return True, item_reason or explicit_paths[rel]
    for dpath, _, dir_reason in explicit_dirs:
        if fpath.is_relative_to(dpath):
            return True, item_reason or dir_reason
    name = Path(rel).name
    for pat in exclude_patterns:
        if fnmatch.fnmatchcase(rel, pat) or fnmatch.fnmatchcase(name, pat):
            return True, item_reason or "caller_excluded_pattern"
    return False, ""


def _append_unmatched_explicit_exclusions(
    excluded_sources: list[dict],
    seen_paths: set[str],
    explicit_paths: dict[str, str],
    explicit_dirs: list[tuple[Path, str, str]],
    extra_records: list[dict],
) -> None:
    for rec in extra_records:
        if rec["path"] not in seen_paths:
            excluded_sources.append(rec)
            seen_paths.add(rec["path"])
    for rel, reason in explicit_paths.items():
        if rel not in seen_paths:
            excluded_sources.append({
                "id": f"excluded-{len(excluded_sources) + 1}",
                "path": rel,
                "read_status": "not_read",
                "exclusion_reason": reason,
            })
            seen_paths.add(rel)
    for _, rel_dir, reason in explicit_dirs:
        if rel_dir not in seen_paths and not any(
            p == rel_dir or p.startswith(rel_dir + "/") for p in seen_paths
        ):
            excluded_sources.append({
                "id": f"excluded-dir-{len(excluded_sources) + 1}",
                "path": rel_dir,
                "read_status": "not_read",
                "exclusion_reason": reason,
            })
            seen_paths.add(rel_dir)


def _recheck_unreadable_source(lexical: Path, expected: os.stat_result) -> None:
    try:
        info = core.checked_path(lexical)
    except core.BundleError as exc:
        if str(exc) != "bundle_path_missing":
            raise core.ContractError("source_file_or_link_invalid") from None
    except OSError:
        pass
    else:
        core.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "source_file_or_link_invalid")
        core.require(os.path.samestat(expected, info), "source_file_changed")


def _probe_readable_for_discovery(
    items: list[dict],
    lexicals: dict[str, tuple[Path, Path, os.stat_result]],
    context: dict,
) -> tuple[list[dict], list[dict]]:
    """逐文件核验普通可读性：普通 OSError 记为不可读排除项，符号链接/硬链接/TOCTOU 违约立即抛 ContractError。"""
    readable: list[dict] = []
    unreadable: list[dict] = []
    for item in items:
        rel = item["path"]
        if _is_discovery_auto_skipped(rel):
            readable.append(item)
            continue
        fpath, lexical, info = lexicals[rel]
        _check_access(context)
        try:
            with fpath.open("rb") as stream:
                fileno = getattr(stream, "fileno", None)
                if callable(fileno):
                    try:
                        fd = fileno()
                    except (OSError, io.UnsupportedOperation):
                        fd = None
                    if isinstance(fd, int):
                        opened = os.fstat(fd)
                        core.require(
                            stat.S_ISREG(opened.st_mode)
                            and opened.st_nlink == 1
                            and os.path.samestat(info, opened),
                            "source_file_changed",
                        )
                stream.read(1)
        except OSError:
            _recheck_unreadable_source(lexical, info)
            unreadable.append({
                "id": item["id"],
                "path": rel,
                "read_status": "not_read",
                "exclusion_reason": "unreadable",
            })
            continue
        readable.append(item)
    return readable, unreadable


def _exclude_failed_source_read(
    exc: core.ContractError,
    files: list[dict],
    lexicals: dict[str, tuple[Path, Path, os.stat_result]],
    excluded_sources: list[dict],
    request: dict,
    empty_code: str,
) -> bool:
    # 下游用固定诊断码隐藏本机路径。只从实际失败的源码读取帧恢复条目身份。
    error = exc.__context__
    if not isinstance(error, OSError):
        return False
    relative = None
    trace = error.__traceback__
    while trace is not None:
        frame = trace.tb_frame
        if str(exc) == "discovery_io_failed" and frame.f_code is software_discovery.discover.__code__:
            record = frame.f_locals.get("record")
            if record and record["read_status"] == "not_read" and record["exclusion_reason"] is None:
                relative = record["path"]
            break
        if str(exc) == "source_read_failed" and frame.f_code is software._source.__code__:
            relative = frame.f_locals["entry"]["path"]
            break
        trace = trace.tb_next
    for index, item in enumerate(files):
        if item["path"] == relative:
            _, lexical, expected = lexicals[relative]
            _recheck_unreadable_source(lexical, expected)
            excluded_sources.append({"id": item["id"], "path": relative, "read_status": "not_read",
                                     "exclusion_reason": "unreadable"})
            del files[index]
            core.require(bool(files), empty_code)
            request["inventory_complete"] = False
            return True
    return False


def _discover_with_unreadable_fallback(discovery_input, lexicals, excluded_sources, request, empty_code):
    while True:
        try:
            return software_discovery.discover(discovery_input, use_system_time=True)
        except core.ContractError as exc:
            if not _exclude_failed_source_read(
                exc, discovery_input["files"], lexicals, excluded_sources, request, empty_code,
            ):
                raise


def _normalize_material_permissions(
    base: Path,
    raw_permissions: list,
) -> tuple[list[dict], set[str], set[str], set]:
    """统一规范化 material_permissions 中的路径并收集 deny 路径与 (st_dev, st_ino) 身份集合。"""
    core.require(isinstance(raw_permissions, list), "material_permission_invalid")
    normalized_perms: list[dict] = []
    allowed_perm_paths: set[str] = set()
    blocked_perm_paths: set[str] = set()
    blocked_perm_identities: set = set()
    for perm in raw_permissions:
        core.require(isinstance(perm, dict), "material_permission_invalid")
        raw_perm_paths = perm.get("paths")
        core.require(
            isinstance(raw_perm_paths, list) and bool(raw_perm_paths)
            and all(isinstance(p, str) and bool(p.strip()) for p in raw_perm_paths),
            "material_permission_invalid",
        )
        p_copy = copy.deepcopy(perm)
        canonical_paths: list[str] = []
        decision = p_copy.get("decision")
        ev = p_copy.get("evidence_id")
        is_allowed = (decision == "allow" and isinstance(ev, str) and bool(ev.strip()))
        for raw_p in raw_perm_paths:
            resolved_p = core.safe_path(base, raw_p, must_exist=False)
            rel_p = resolved_p.relative_to(base).as_posix()
            canonical_paths.append(rel_p)
            if is_allowed:
                allowed_perm_paths.add(rel_p)
            else:
                blocked_perm_paths.add(rel_p)
                if resolved_p.exists():
                    st_b = resolved_p.stat()
                    blocked_perm_identities.add((st_b.st_dev, st_b.st_ino))
        p_copy["paths"] = canonical_paths
        normalized_perms.append(p_copy)
    return normalized_perms, allowed_perm_paths, blocked_perm_paths, blocked_perm_identities


def _check_sensitive(value: object, secrets: list[str], code: str) -> None:
    if not secrets:
        return
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            core.require(not any(secret in item for secret in secrets), code)
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _check_file_permission_denial(item):
    permission = item.get("local_permission")
    if permission is not None:
        core.require(isinstance(permission, dict) and permission.get("decision") == "allow",
                     "material_permission_not_proven")


def _batch_screenshots(base, destination, far, files, request, delivery, permissions, exclusions):
    allowed, denied, denied_identities = permissions
    shots = delivery.setdefault("screenshots", [])
    core.require(isinstance(shots, list) and len(shots) <= 100, "screenshots_list_required")
    if not shots:
        return []
    paths = {item["path"] for item in files}
    identities = set()
    for relative in paths:
        st = core.safe_path(base, relative).stat()
        identities.add((st.st_dev, st.st_ino))
    checked = []
    for shot in shots:
        core.require(isinstance(shot, dict) and isinstance(shot.get("path"), str), "screenshot_entry_invalid")
        path, _, st, relative = _check_source_file_safety(base, shot["path"], destination, reject_generated=False)
        core.require(path.suffix.lower() == ".png", "screenshot_png_required")
        core.require(not _in_generated_directory(path, base), "artifact_screenshot_forbidden")
        identity = (st.st_dev, st.st_ino)
        core.require(relative not in denied and identity not in denied_identities, "screenshot_permission_required")
        core.require(st.st_nlink == 1, "source_file_or_link_invalid")
        excluded, reason = _match_explicit_exclusion({"path": relative}, path, *exclusions)
        if excluded:
            exclusions[0].setdefault(relative, reason)
            continue
        core.require(relative in allowed, "screenshot_permission_required")
        core.require(relative not in paths and identity not in identities, "screenshot_duplicate_path")
        core.require(st.st_size <= software_delivery.MAX_IMAGE_BYTES, "screenshot_too_large")
        shot["path"] = relative
        paths.add(relative)
        identities.add(identity)
        checked.append((shot, path, identity))
    delivery["screenshots"] = [shot for shot, _, _ in checked]
    if not checked:
        return []

    manual = request.get("manual_input")
    core.require(
        manual is not None
        and manual.get("mode") == "GUI"
        and far.get("manual_mode", "GUI") == "GUI",
        "screenshots_require_gui",
    )
    operations = software._items(manual.get("operations", []), "operations_required")
    operation_ids = software._ids(operations)
    runtime = software._items(manual.setdefault("runtime_evidence", []), "runtime_evidence_list_required", nonempty=False)
    existing_ids = software._ids(runtime)
    anchored_operations = {block.get("operation_id") for block in manual.get("blocks", [])}
    version = far["scope"]["metadata"]["version"]
    for shot in delivery["screenshots"]:
        core.require_fields(shot, ("id", "version", "operation_id", "capture_evidence",
                                  "local_use_evidence", "visible_state"))
        shot_id = shot["id"]
        core.require(isinstance(shot_id, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", shot_id)
                     and shot_id not in existing_ids, "screenshot_id_invalid")
        operation_id = shot["operation_id"]
        core.require(isinstance(operation_id, str) and operation_id in operation_ids,
                     "screenshot_operation_mismatch")
        core.require("blocks" not in manual or operation_id in anchored_operations, "manual_screenshot_unmatched")
        core.require(shot["version"] == version, "screenshot_version_mismatch")
        core.require(all(isinstance(shot[key], str) and shot[key].strip()
                         for key in ("capture_evidence", "local_use_evidence", "visible_state")),
                     "screenshot_evidence_required")
        core.require(isinstance(shot.get("visual_review", {}), dict), "screenshot_entry_invalid")
        for key in ("sha256", "build_binding"):
            if key in shot:
                core.require(isinstance(shot[key], str) and re.fullmatch(r"[0-9a-f]{64}", shot[key]),
                             "screenshot_entry_invalid")
        existing_ids.add(shot_id)
        runtime.append({"id": shot_id, "version": version, "kind": "screenshot",
                        "evidence_id": shot["capture_evidence"]})
    return checked


def _prepare_batch_state(
    base: Path,
    batch_input: dict,
    *,
    destination: Path | None = None,
    manual_markdown_path: str | None = None,
) -> tuple[dict, dict, dict, list[str], bool, list]:
    """校验三批次输入、权限、敏感词与可选 Markdown 手册，并计算一致的 discovery 与 confirmation_group。"""
    from . import software_revision

    core.require(isinstance(batch_input, dict), "batch_input_required")
    core.require_fields(batch_input, ("context_and_permissions", "files_and_rights"))
    context = copy.deepcopy(batch_input["context_and_permissions"])
    _check_access(context)

    far = batch_input["files_and_rights"]
    core.require(isinstance(far, dict), "files_and_rights_required")
    core.require_fields(far, ("scope", "rights", "files", "material_permissions"))
    core.require(isinstance(far["scope"], dict), "scope_object_required")
    core.require(isinstance(far["rights"], list), "rights_list_required")
    core.require(isinstance(far["files"], list) and bool(far["files"]), "file_inventory_required")
    core.require(isinstance(far["material_permissions"], list), "material_permission_invalid")

    raw_far_secrets = far.get("sensitive_literals", [])
    core.require(
        isinstance(raw_far_secrets, list) and all(isinstance(s, str) and bool(s) for s in raw_far_secrets),
        "invalid_sensitive_literals",
    )
    raw_delivery = far.get("delivery")
    if raw_delivery is not None:
        core.require(isinstance(raw_delivery, dict), "delivery_object_required")
        raw_del_secrets = raw_delivery.get("sensitive_literals", [])
        core.require(
            isinstance(raw_del_secrets, list) and all(isinstance(s, str) and bool(s) for s in raw_del_secrets),
            "invalid_sensitive_literals",
        )
    else:
        raw_del_secrets = []
    secrets = list(dict.fromkeys([*raw_far_secrets, *raw_del_secrets]))

    # 校验 SW-01 / SW-07 组件材料权限，拒绝未授权或禁止处理的组件（传入 deepcopy 避免就地改写 context.now）
    scoped = software.run("SW-01", {"context": copy.deepcopy(context), **copy.deepcopy(far["scope"])}, use_system_time=True)
    entitled = software.run(
        "SW-07", {"context": copy.deepcopy(context), "scope": scoped["artifacts"], "rights": copy.deepcopy(far["rights"])},
        use_system_time=True,
    )
    core.require(
        all(item["decision"] not in {"prohibit", "needs_permission"} for item in entitled["artifacts"]["decisions"]),
        "material_permission_not_proven",
    )

    # 规范化文件路径、拦截生成目录/输出目录碰撞与符号链接/目录联接
    normalized_files: list[dict] = []
    file_lexicals: dict[str, tuple[Path, Path, os.stat_result]] = {}
    seen_paths: set[str] = set()
    for idx, entry in enumerate(far["files"], start=1):
        core.require(isinstance(entry, dict) and isinstance(entry.get("path"), str), "source_file_required")
        fpath, lexical, info, rel = _check_source_file_safety(base, entry["path"], destination)
        core.require(rel not in seen_paths, "duplicate_source_path")
        seen_paths.add(rel)
        item = copy.deepcopy(entry)
        item["path"] = rel
        item.setdefault("id", f"file-{idx}")
        item.setdefault("component_id", "main")
        item.setdefault("kind", "source")
        item.setdefault("include", True)
        core.require(type(item["include"]) is bool, "include_boolean_required")
        normalized_files.append(item)
        file_lexicals[rel] = (fpath, lexical, info)

    (
        has_explicit_exclusions,
        explicit_paths,
        explicit_dirs,
        exclude_patterns,
        extra_excluded_records,
    ) = _collect_explicit_exclusions(base, far, batch_input)

    # 严格规范化 material_permissions 中的路径（经 core.safe_path 防 ./、大小写变体与硬链接绕过 deny）
    (
        normalized_perms,
        allowed_perm_paths,
        blocked_perm_paths,
        blocked_perm_identities,
    ) = _normalize_material_permissions(base, far["material_permissions"])

    # 在任何发现或文件读取前，对全部源码文件强制执行 deny 路径与 (st_dev, st_ino) 硬链接/大小写别名拦截，并拒绝硬链接逃逸！
    for item in normalized_files:
        _, _, info = file_lexicals[item["path"]]
        core.require(
            item["path"] not in blocked_perm_paths
            and (info.st_dev, info.st_ino) not in blocked_perm_identities,
            "material_permission_not_proven",
        )
        core.require(info.st_nlink == 1, "source_file_or_link_invalid")
        _check_file_permission_denial(item)

    exclusions = (explicit_paths, explicit_dirs, exclude_patterns)
    excluded_sources: list[dict] = []
    excluded_paths_seen: set[str] = set()
    discover_candidates: list[dict] = []
    for item in normalized_files:
        fpath, _, _ = file_lexicals[item["path"]]
        excluded, reason = _match_explicit_exclusion(item, fpath, *exclusions)
        if excluded:
            explicit_paths.setdefault(item["path"], reason)
            excluded_sources.append({"id": item["id"], "path": item["path"], "read_status": "not_read",
                                     "exclusion_reason": reason})
            excluded_paths_seen.add(item["path"])
        else:
            discover_candidates.append(item)
    core.require(bool(discover_candidates), "no_readable_source_files")

    # 若提供 Markdown 手册，必须在 confirmation_group 之前完成权限、秘密扫描与挂载，防止 input_binding 漂移！
    if "manual_mode" in far:
        core.require(isinstance(far["manual_mode"], str) and far["manual_mode"] in MODES,
                     "manual_mode_invalid")
    manual_input = copy.deepcopy(far.get("manual_input"))
    if manual_input is not None:
        core.require(isinstance(manual_input, dict), "manual_input_object_required")
        if "manual_mode" in far:
            core.require(manual_input.setdefault("mode", far["manual_mode"]) == far["manual_mode"],
                         "manual_mode_mismatch")
    manual_imported = False
    if manual_markdown_path is not None:
        core.require(isinstance(manual_markdown_path, str) and bool(manual_markdown_path.strip()),
                     "manual_markdown_invalid")
        md_file, _, md_st, md_rel = _check_source_file_safety(base, manual_markdown_path, destination)
        core.require(md_st.st_size <= MAX_FILE_BYTES, "manual_markdown_invalid")
        core.require(md_st.st_nlink == 1, "source_file_or_link_invalid")
        core.require(md_rel not in blocked_perm_paths and (md_st.st_dev, md_st.st_ino) not in blocked_perm_identities,
                     "manual_markdown_permission_required")
        excluded, reason = _match_explicit_exclusion({"path": md_rel}, md_file, *exclusions)
        if excluded:
            explicit_paths.setdefault(md_rel, reason)
            manual_markdown_path = None
    if manual_markdown_path is not None:
        core.require(md_rel in allowed_perm_paths, "manual_markdown_permission_required")
        core.require(not any(secret in md_rel for secret in secrets), "sensitive_literal_in_manual_path")
        try:
            _check_access(context)
            with md_file.open("rb") as stream:
                md_raw = stream.read(MAX_FILE_BYTES + 1)
            core.require(len(md_raw) <= MAX_FILE_BYTES, "manual_markdown_invalid")
            md_text = md_raw.decode("utf-8")
        except (OSError, UnicodeError):
            raise core.ContractError("manual_markdown_unreadable") from None
        core.require(not any(secret in md_text for secret in secrets), "sensitive_literal_in_manual")
        parsed = software_revision.parse_markdown(md_text)
        _check_sensitive(parsed, secrets, "sensitive_literal_in_manual")
        # Markdown 内嵌图片须走带逐图授权的 software_import，不得静默注入未授权 image_id
        core.require(not parsed.get("images"), "manual_markdown_images_require_import")
        blocks = copy.deepcopy(parsed["blocks"])
        for block in blocks:
            block["status"] = "needs_review"
        manual_input = {
            "mode": far.get("manual_mode", "CLI"),
            "facts": [],
            "operations": [],
            "runtime_evidence": [],
            **(manual_input or {}),
            "blocks": blocks,
            "revision": {
                "input": {
                    "path": md_rel,
                    "sha256": core.sha256_bytes(md_raw),
                    "format": "markdown",
                },
                "parser_metadata": parsed["metadata"],
                "confirmations": "needs_review",
            },
        }
        manual_imported = True

    pagination = copy.deepcopy(far.get("pagination") or {
        "selection": "all",
        "lines_per_page": 50,
        "wrap_columns": 78,
        "basis": "internal_candidate_not_verified_registration_rule",
    })
    core.require(isinstance(pagination, dict) and pagination.get("selection") == "all",
                 "pagination_selection_must_be_all")

    inventory_complete = far.get("inventory_complete", False)
    core.require(type(inventory_complete) is bool, "inventory_complete_bool_required")
    request = {
        "context": context,
        "authorized_root": str(base),
        "scope_input": copy.deepcopy(far["scope"]),
        "rights": copy.deepcopy(far["rights"]),
        "files": discover_candidates,
        "inventory_complete": inventory_complete,
        "pagination": pagination,
    }
    if manual_input is not None:
        request["manual_input"] = manual_input
    _check_sensitive(request, secrets, "intake_sensitive_request")
    delivery = copy.deepcopy(raw_delivery or {})
    delivery.pop("sensitive_literals", None)
    core.require(set(delivery) <= {"selection", "screenshots"}, "delivery_options_invalid")
    delivery.setdefault("selection", "all")
    software_delivery.select_pages([], delivery["selection"])
    shots = _batch_screenshots(base, destination, far, normalized_files, request, delivery,
                              (allowed_perm_paths, blocked_perm_paths, blocked_perm_identities), exclusions)
    _check_sensitive(delivery, secrets, "intake_sensitive_request")

    _append_unmatched_explicit_exclusions(
        excluded_sources, excluded_paths_seen, explicit_paths, explicit_dirs, extra_excluded_records,
    )
    if excluded_sources or has_explicit_exclusions:
        request["inventory_complete"] = False
    _check_sensitive(excluded_sources, secrets, "intake_sensitive_request")

    # 在打开任何源码文件前先校验整份待发现清单的读取许可；再逐文件隔离普通 OSError 不可读文件。
    discovery_input = {
        "context": context,
        "authorized_root": str(base),
        "files": discover_candidates,
        "material_permissions": normalized_perms,
        "request": request,
        "sensitive_literals": secrets,
    }
    software_discovery._file_permissions(discovery_input)
    discover_files, unreadable_entries = _probe_readable_for_discovery(
        discover_candidates, file_lexicals, context,
    )
    if unreadable_entries:
        request["inventory_complete"] = False
        excluded_sources.extend(unreadable_entries)
    core.require(bool(discover_files), "no_readable_source_files")
    discovery_input["files"] = discover_files

    while True:
        discovery = _discover_with_unreadable_fallback(
            discovery_input, file_lexicals, excluded_sources, request, "no_readable_source_files",
        )
        candidates_by_path = {row["path"]: row for row in discovery["file_candidates"]}
        active_files = []
        discovery_exclusions = []
        for item in discover_files:
            cand = candidates_by_path.get(item["path"])
            if cand is not None and cand["read_status"] == "read" and not cand["exclusion_reason"]:
                active_files.append({**item, "expected_sha256": cand["sha256"]})
            else:
                request["inventory_complete"] = False
                discovery_exclusions.append({
                    "id": item["id"],
                    "path": item["path"],
                    "read_status": cand["read_status"] if cand is not None else "not_read",
                    "exclusion_reason": cand["exclusion_reason"] if cand is not None else "not_discovered",
                })
        core.require(bool(active_files), "no_readable_source_files")
        request["files"] = active_files
        try:
            group = software_discovery.confirmation_group(
                {"request": request, "discovery": discovery, "options": delivery}, use_system_time=True,
            )
        except core.ContractError as exc:
            if not _exclude_failed_source_read(
                exc, discover_files, file_lexicals, excluded_sources, request, "no_readable_source_files",
            ):
                raise
        else:
            excluded_sources.extend(discovery_exclusions)
            break
    _check_sensitive(group["request"], secrets, "intake_sensitive_request")
    return context, discovery, group, secrets, manual_imported, shots, excluded_sources


def _plan_binding(discovery: dict, group: dict) -> str:
    """绑定发现摘要、候选表摘要与输入绑定（不含瞬时墙钟微秒，便于操作者审阅后跨秒提交）。"""
    return core.digest({
        "discovery_binding": discovery["binding"],
        "summary_digest": group["summary_digest"],
        "input_binding": group["input_binding"],
        "delivery": group["options"],
    })


def plan_batch(
    root: str | Path,
    *,
    batch_input: dict,
    manual_markdown_path: str | None = None,
) -> dict:
    """只读批次计划：执行权限核验、多栈发现与 confirmation_group 摘要生成，供操作者审阅后再确认。"""
    try:
        base = Path(root).resolve(strict=True)
        core.require(base.is_dir(), "authorized_root_required")
        _, discovery, group, _, manual_imported, _, excluded_sources = _prepare_batch_state(
            base, batch_input, manual_markdown_path=manual_markdown_path,
        )
    except (OSError, RuntimeError, OverflowError):
        raise core.ContractError("intake_io_failed") from None
    result = {
        "status": "needs_confirm",
        "group_binding": _plan_binding(discovery, group),
        "summary_digest": group["summary_digest"],
        "input_binding": group["input_binding"],
        "eligible_candidates": list(group["eligible_candidates"]),
        "rows": copy.deepcopy(group["rows"]),
        "discovered_field_candidates": sum(1 for row in discovery["field_candidates"] if row["status"] != "unknown"),
        "manual_blocks_imported": manual_imported,
        "inventory_complete": group["request"]["inventory_complete"],
        "professional_review": "not_performed",
    }
    if excluded_sources:
        result["excluded_sources"] = excluded_sources
    return result


def _collect_batch(
    root: str | Path,
    output: str,
    *,
    batch_input: dict,
    manual_markdown_path: str | None = None,
) -> dict:
    """Phase D1: 低摩擦三批次集中采集入口，产出可直接喂入 build-software 的授权与请求包。

    安全红线：
    - 严禁在同一调用内自动盲选确认（confirm_eligible=True 无人工审阅摘要绑定直接拒绝）；
    - 若提交 field_confirmation，必须携带由 plan_batch 返回并经操作者实际核对的
      group_binding、summary_digest、input_binding 与显式 candidate_digests；
    - manual_markdown_path 在 confirmation_group 之前挂载并完成权限与敏感词扫描，确保确认永不陈旧。
    """
    base = Path(root).resolve(strict=True)
    core.require(base.is_dir(), "authorized_root_required")
    destination = core.safe_path(base, output, must_exist=False)
    core.require(not destination.exists(), "output_exists")
    core.require(destination.parent.is_dir(), "output_parent_missing")
    relative_output = destination.relative_to(base).as_posix()

    context, discovery, group, secrets, manual_imported, shots, excluded_sources = _prepare_batch_state(
        base, batch_input, destination=destination, manual_markdown_path=manual_markdown_path,
    )
    core.require(not any(secret in f"{relative_output}/authorization.json" for secret in secrets),
                 "intake_sensitive_output_path")

    final_request = copy.deepcopy(group["request"])
    confirm_meta = batch_input.get("field_confirmation")
    confirmed_count = 0
    if confirm_meta is not None:
        core.require(isinstance(confirm_meta, dict), "field_confirmation_object_required")
        # 严禁盲目全选：必须显式提供经 plan_batch 审阅的绑定摘要与候选列表
        required_confirm_keys = (
            "group_binding", "summary_digest", "input_binding",
            "actor", "role", "evidence_id", "candidate_digests",
        )
        core.require(
            all(key in confirm_meta for key in required_confirm_keys),
            "blind_batch_confirmation_forbidden",
        )
        core.require(isinstance(confirm_meta["candidate_digests"], list), "candidate_digests_list_required")
        expected_plan_binding = _plan_binding(discovery, group)
        core.require(
            confirm_meta["group_binding"] in {expected_plan_binding, group["binding"]}
            and confirm_meta["summary_digest"] == group["summary_digest"]
            and confirm_meta["input_binding"] == group["input_binding"],
            "confirmation_group_stale",
        )
        confirmed = software_discovery.confirm_group(
            group,
            {
                "group_binding": group["binding"],
                "summary_digest": confirm_meta["summary_digest"],
                "input_binding": confirm_meta["input_binding"],
                "status": "confirmed",
                "actor": confirm_meta["actor"],
                "role": confirm_meta["role"],
                "evidence_id": confirm_meta["evidence_id"],
                "candidate_digests": list(confirm_meta["candidate_digests"]),
            },
        )
        final_request = confirmed["request"]
        confirmed_count = len(confirmed["request"].get("confirmations", []))

    _check_sensitive(final_request, secrets, "intake_sensitive_request")
    delivery = copy.deepcopy(group["options"])
    auth_files = [{"path": item["path"], "sha256": item["expected_sha256"]}
                  for item in final_request["files"]]
    if shots:
        preparation = software.prepare(final_request, use_system_time=True)["artifacts"]
        binding = software_delivery.build_binding(preparation)
        for shot in delivery["screenshots"]:
            core.require(shot.get("build_binding", binding) == binding, "screenshot_build_changed")
        for shot, (_, path, identity) in zip(delivery["screenshots"], shots):
            _check_access(context)
            with path.open("rb") as stream:
                st = os.fstat(stream.fileno())
                core.require((st.st_dev, st.st_ino) == identity, "screenshot_file_changed")
                raw = stream.read(software_delivery.MAX_IMAGE_BYTES + 1)
            core.require(len(raw) <= software_delivery.MAX_IMAGE_BYTES, "screenshot_too_large")
            software_delivery._png(raw)
            sha256 = core.sha256_bytes(raw)
            core.require(shot.get("sha256", sha256) == sha256, "screenshot_hash_changed")
            shot.update(sha256=sha256, build_binding=binding)
            auth_files.append({"path": shot["path"], "sha256": sha256})
    _check_sensitive(delivery, secrets, "intake_sensitive_request")
    delivery["sensitive_literals"] = list(secrets)
    final_request.pop("context", None)
    final_request.pop("authorized_root", None)
    final_request["delivery"] = delivery

    request_path = f"{relative_output}/request.json"
    authorization_path = f"{relative_output}/authorization.json"
    authorization = {
        "kind": "software_local_authorization",
        "authorized_root": str(base),
        "context": context,
        "request": {
            "path": request_path,
            "sha256": core.sha256_bytes(core.canonical_bytes(final_request) + b"\n"),
        },
        "files": auth_files,
        "output": f"{relative_output}/materials",
    }
    if excluded_sources:
        authorization["excluded_sources"] = excluded_sources
    _check_access(context)
    destination.mkdir()
    core.write_new_json(base, request_path, final_request)
    core.write_new_json(base, authorization_path, authorization)
    discovered_non_unknown = sum(1 for row in discovery["field_candidates"] if row["status"] != "unknown")
    summary = {
        "status": "collected_batch",
        "batches_consumed": 3 if confirm_meta else 2,
        "discovered_field_candidates": discovered_non_unknown,
        "confirmed_candidates": confirmed_count,
        "manual_blocks_imported": manual_imported,
        "inventory_complete": final_request["inventory_complete"],
        "authorization": authorization_path,
        "authorization_sha256": core.sha256_bytes(core.canonical_bytes(authorization) + b"\n"),
        "professional_review": "not_performed",
    }
    if excluded_sources:
        summary["excluded_sources"] = excluded_sources
    return summary


def collect_batch(
    root: str | Path,
    output: str,
    *,
    batch_input: dict,
    manual_markdown_path: str | None = None,
) -> dict:
    """收集显式授权的材料与截图，产出 build-software 所需授权包。"""
    try:
        return _collect_batch(root, output, batch_input=batch_input, manual_markdown_path=manual_markdown_path)
    except (OSError, RuntimeError, OverflowError):
        raise core.ContractError("intake_io_failed") from None
