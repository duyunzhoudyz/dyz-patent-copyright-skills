"""R08：逐项目复用获准本地入口；批次只返回内部结果索引。"""

import argparse
import re
from pathlib import Path

from . import core

_REQUIRED = {"id", "root", "authorization", "authorization_sha256", "action"}
_ACTIONS = {"prepare", "build", "verify"}
_STATUSES = ("completed", "needs_confirmation", "failed", "skipped")
# 只公开固定诊断；底层异常和带动态定位的诊断不能进入批次日志。
_ERROR_CODES = {
    "permission_not_proven", "input_snapshot_mismatch", "output_exists",
    "output_parent_missing", "authorized_root_required", "authorization_root_mismatch",
    "authorization_kind_unknown", "input_file_required", "input_too_large",
    "unsafe_path", "path_outside_root", "source_output_collision",
    "source_snapshot_mismatch", "source_not_authorized", "authorized_inventory_mismatch",
    "preparation_field_not_allowed", "delivery_binding_changed", "delivery_code_changed",
    "delivery_file_changed", "delivery_members_changed", "delivery_mapping_changed",
    "delivery_input_snapshot_changed", "software_filesystem_unavailable",
    "data_path_inventory_incomplete", "data_path_unverified", "data_path_mode_unknown",
}
_ISSUE_CODES = {
    "manual_input_missing", "manual_missing", "runtime_not_verified",
    "source_coverage_incomplete", "no_selected_source", "field_confirmation_pending",
    "field_confirmation_required", "manual_block_confirmation_pending",
    "screenshot_missing", "screenshot_visual_review_missing", "pdf_not_generated",
    "physical_layout_not_checked", "physical_layout_not_rechecked",
    "physical_selection_not_verified", "physical_manual_selection_not_verified",
    "public_not_authorized", "cloud_not_authorized", "internal_workflow_marker",
}


def _validate(projects: list[dict]) -> list[dict]:
    core.require(isinstance(projects, list) and bool(projects), "batch_projects_required")
    rows, ids, roots = [], set(), []
    for project in projects:
        core.require(isinstance(project, dict), "batch_project_object_required")
        core.require(_REQUIRED <= set(project) <= _REQUIRED | {"enabled"},
                     "batch_project_fields_invalid")
        identifier = project["id"]
        core.require(isinstance(identifier, str) and
                     re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identifier),
                     "batch_project_id_invalid")
        core.require(identifier not in ids, "batch_project_id_reused")
        ids.add(identifier)
        core.require(isinstance(project["action"], str) and project["action"] in _ACTIONS,
                     "batch_action_invalid")
        core.require(type(project.get("enabled", True)) is bool, "batch_enabled_invalid")
        for field in ("root", "authorization"):
            core.require(isinstance(project[field], str) and bool(project[field].strip()),
                         "batch_control_path_required")
        core.require(Path(project["root"]).is_absolute(), "batch_absolute_root_required")
        relative = project["authorization"].replace("\\", "/")
        core.require(not Path(relative).is_absolute() and ":" not in relative and
                     "\x00" not in relative and
                     all(part not in {"", ".", ".."} for part in relative.split("/")),
                     "batch_authorization_path_invalid")
        expected = project["authorization_sha256"]
        core.require(isinstance(expected, str) and
                     re.fullmatch(r"[0-9a-f]{64}", expected), "invalid_expected_sha256")
        row = dict(project)
        if row.get("enabled", True):
            try:
                root = Path(row["root"]).resolve()
            except (OSError, RuntimeError, ValueError):
                raise core.ContractError("batch_root_invalid") from None
            # 先排除同根、别名和嵌套根，避免前项写入后才发现跨项目重用。
            core.require(not any(root.is_relative_to(other) or
                                 other.is_relative_to(root) for other in roots),
                         "batch_root_reused")
            roots.append(root)
            row["root"] = str(root)
        rows.append(row)
    return rows


def _issue_codes(issues: list) -> list[str]:
    codes = set()
    for issue in issues:
        code = issue.get("code") if isinstance(issue, dict) else issue
        if isinstance(code, str) and code in _ISSUE_CODES:
            codes.add(code)
        else:
            codes.add("project_review_issue")
    return sorted(codes)


def run_batch(projects: list[dict]) -> dict:
    """执行独立prepare/build/verify，返回completed/needs_confirmation/failed/skipped。

    项目只接受id/root/authorization/authorization_sha256/action及可选enabled。
    root必须绝对且相互独立，授权控制路径必须相对，固定hash绑定授权字节。
    结构或根重用导致整批在读取前拒绝；执行失败只影响本项目。enabled=False
    不打开任何项目文件。批次不接收材料、权限、now或PDF工具，亦不自动探测工具。
    成功执行但底层仍为partial/needs_review时记录needs_confirmation；completed
    仅表示底层checked/completed，不代表专业签核或正式提交。所有索引限内部使用。
    """
    rows = _validate(projects)
    # 延迟导入，CLI可以注册批次命令，同时保留单项目读前预检的唯一所有者。
    from .cli import _prepare_software, _read_bound_json

    results = []
    for project in rows:
        row = {key: project[key] for key in ("id", "root", "action")}
        row.update(output=None, binding=None, status="skipped", execution="skipped",
                   issues=["project_disabled"])
        if not project.get("enabled", True):
            results.append(row)
            continue
        row.update(binding={"authorization": project["authorization_sha256"]},
                   status="failed", execution="failed", issues=[])
        try:
            root = Path(project["root"])
            # 控制文件只含路径/hash与准入信息；材料仍由单项目入口预检后读取。
            authorization = _read_bound_json(root, project["authorization"],
                                             project["authorization_sha256"], 1_000_000)
            args = argparse.Namespace(
                root=project["root"], authorization=project["authorization"],
                authorization_sha256=project["authorization_sha256"],
                verify=project["action"] == "verify", pdf_tool=None, pdf_text_tool=None,
            )
            result = _prepare_software(args, document_output=project["action"] != "prepare")
            row["output"] = authorization["output"]
            row["binding"]["request"] = authorization["request"]["sha256"]
            if project["action"] == "prepare":
                row["binding"]["preparation"] = result["artifacts"]["binding"]
            elif project["action"] == "build":
                row["binding"]["preparation"] = result["preparation_binding"]
            row["execution"] = "completed"
            if result["status"] in {"failed", "blocked"}:
                row.update(status="failed", execution="failed")
            else:
                row["status"] = ("completed" if result["status"] in {"checked", "completed"}
                                 else "needs_confirmation")
            row["issues"] = _issue_codes(result.get("issues", []))
            if row["status"] == "needs_confirmation":
                row["issues"] = sorted(set(row["issues"]) | {"project_needs_confirmation"})
        except core.ContractError as exc:
            code = str(exc)
            row["issues"] = [code if code in _ERROR_CODES else "contract_rejected"]
        except (OSError, RuntimeError):
            row["issues"] = ["project_filesystem_unavailable"]
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            row["issues"] = ["project_input_invalid"]
        results.append(row)
    counts = {status: sum(row["status"] == status for row in results)
              for status in _STATUSES}
    status = next((state for state in ("failed", "needs_confirmation", "completed")
                   if counts[state]), "skipped")
    return {"kind": "software_batch", "status": status, "counts": counts,
            "projects": results, "output_scope": "internal_only_not_for_submission",
            "external_action": "not_performed", "official_status": "not_asserted"}
