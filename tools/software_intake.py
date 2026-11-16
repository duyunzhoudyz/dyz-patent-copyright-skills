"""将操作者的逐项声明收集为获准本地软件准备输入，不扫描或执行源码。

输入和证据引用不等于事实认证、权属认定或专业批准。仅支持单组件；多组件
或外部处理交给有相应独立授权的低层入口，不能从“本地”推定宿主离线。
"""

from __future__ import annotations

import copy
import json
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
    for declared_root in (payload.get("authorized_root"), request.get("authorized_root")):
        if declared_root is not None:
            core.require(Path(declared_root).resolve(strict=True) == base,
                         "discovery_project_mismatch")
    files = payload.get("files", request.get("files"))
    core.require(isinstance(files, list) and bool(files), "file_inventory_required")
    # 在文件、授权请求或配置读取前，当前 context 和整份清单许可均须成立。
    discovery_input = {**payload, "context": context, "authorized_root": str(base),
                       "request": request, "files": files}
    software_discovery._file_permissions(discovery_input)
    secrets = payload.get("sensitive_literals", payload.get("options", {}).get("sensitive_literals", []))
    core.require(isinstance(secrets, list) and all(isinstance(value, str) and value for value in secrets),
                 "sensitive_literals_required")
    discovery_input["sensitive_literals"] = secrets
    core.require(not any(secret in f"{relative_output}/authorization.json" for secret in secrets),
                 "intake_sensitive_output_path")
    for entry in files:
        path = core.safe_path(base, entry["path"])
        core.require(not path.is_relative_to(destination), "source_output_collision")
    _consent(ask, "是否现在读取上述明确授权清单并生成内部候选供集中核对？输入 yes：")
    discovery = software_discovery.discover(discovery_input, use_system_time=True)
    candidate_files = {entry["id"]: entry for entry in discovery["file_candidates"]}
    normalized = []
    for index, entry in enumerate(files, start=1):
        item = candidate_files[entry.get("id", f"file-{index}")]
        if item["read_status"] != "read" or item["exclusion_reason"]:
            continue
        normalized.append({**{key: value for key, value in entry.items()
                              if key not in {"local_permission", "permission_group"}},
                           "id": item["id"], "path": item["path"],
                           "component_id": entry.get("component_id", "main"),
                           "kind": entry.get("kind", "source" if item["language"] else "other"),
                           "include": entry.get("include", bool(item["language"])),
                           "expected_sha256": item["sha256"],
                           "deposit_context_evidence": entry.get("deposit_context_evidence")
                           or next((right["evidence_ids"][0] for right in request.get("rights", [])
                                    if right.get("component_id") == entry.get("component_id", "main")
                                    and right.get("evidence_ids")), None)})
    core.require(bool(normalized), "file_inventory_required")
    request.update(files=normalized, context=context, authorized_root=str(base))
    group = software_discovery.confirmation_group({"request": request, "discovery": discovery,
                                                   "options": payload.get("options", {})},
                                                  use_system_time=True)
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
    _check_access(context)
    core.require(not destination.exists(), "output_exists")
    destination.mkdir()
    core.write_new_json(base, request_path, request)
    core.write_new_json(base, authorization_path, authorization)
    return {"status": "collected", "authorization": authorization_path,
            "authorization_sha256": core.sha256_bytes(core.canonical_bytes(authorization) + b"\n")}


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
