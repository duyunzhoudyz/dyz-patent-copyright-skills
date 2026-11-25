"""Phase E4: 多模态页面与附图视觉覆盖台账（显式记录总页数、实看页、跳过页与观察者身份）。

杜绝“抽看 4 页却按全册通过汇报”或“将 AI 页图观察冒充人类专业视觉签核”。
"""
from __future__ import annotations

import re

from tools.core import digest, require, require_fields

VERSION = "1.0"
OBSERVER_KINDS = frozenset({"automated_bbox", "ai_page_observation", "human_visual_review"})
PAGE_STATES = frozenset({"inspected", "skipped", "unrendered"})


def build_visual_coverage_ledger(payload: dict) -> dict:
    """构建逐页视觉覆盖台账；漏页、跳过页或仅有 AI/自动观察时严格保留相应待审状态。"""
    require(isinstance(payload, dict), "visual_ledger_payload_required")
    require_fields(payload, ("artifact_id", "artifact_sha256", "total_pages", "pages"))
    require(isinstance(payload["artifact_id"], str), "visual_artifact_id_invalid")
    artifact_sha = payload["artifact_sha256"]
    require(isinstance(artifact_sha, str) and re.fullmatch(r"[0-9a-f]{64}", artifact_sha) is not None,
            "visual_artifact_sha256_invalid")
    total = payload["total_pages"]
    require(type(total) is int and 1 <= total <= 5000, "visual_total_pages_invalid")
    pages = payload["pages"]
    require(isinstance(pages, list), "visual_pages_list_required")

    seen: set[int] = set()
    inspected_pages: list[int] = []
    skipped_pages: list[dict] = []
    unrendered_pages: list[int] = []
    findings: list[dict] = []
    observers_used: set[str] = set()
    human_inspected_pages: set[int] = set()

    for row in pages:
        require(isinstance(row, dict), "visual_page_row_required")
        require_fields(row, ("page", "status"))
        pno = row["page"]
        require(type(pno) is int and 1 <= pno <= total, "visual_page_number_out_of_range")
        require(pno not in seen, "visual_page_duplicate")
        seen.add(pno)
        state = row["status"]
        require(isinstance(state, str) and state in PAGE_STATES, "visual_page_state_invalid")

        if state == "inspected":
            obs = row.get("observer_kind")
            require(isinstance(obs, str) and obs in OBSERVER_KINDS, "visual_observer_kind_invalid")
            img_sha = row.get("image_sha256")
            require(isinstance(img_sha, str) and re.fullmatch(r"[0-9a-f]{64}", img_sha) is not None,
                    "visual_inspected_page_image_sha256_required")
            observers_used.add(obs)
            inspected_pages.append(pno)
            if obs == "human_visual_review":
                human_inspected_pages.add(pno)
            page_findings = row.get("findings", [])
            require(isinstance(page_findings, list), "visual_findings_list_required")
            for item in page_findings:
                require(isinstance(item, dict) and isinstance(item.get("code"), str) and bool(item["code"].strip()),
                        "visual_finding_invalid")
                findings.append({**item, "page": pno})
        elif state == "skipped":
            reason = row.get("skip_reason")
            require(isinstance(reason, str) and bool(reason.strip()), "visual_skip_reason_required")
            skipped_pages.append({"page": pno, "reason": reason.strip()})
        else:
            unrendered_pages.append(pno)

    unaccounted = sorted(set(range(1, total + 1)) - seen)
    all_inspected = len(inspected_pages) == total and not skipped_pages and not unrendered_pages and not unaccounted
    human_complete = len(human_inspected_pages) == total

    if findings:
        overall = "findings_present_needs_remediation"
    elif all_inspected and human_complete:
        overall = "human_visual_complete"
    elif all_inspected and human_inspected_pages:
        overall = "mixed_observers_complete_human_visual_partial_recorded"
    elif all_inspected:
        overall = "machine_or_ai_complete_human_visual_not_performed"
    else:
        overall = "partial_visual_coverage"

    return {
        "schema": "dyz-visual-coverage-ledger-v1",
        "version": VERSION,
        "artifact_id": payload["artifact_id"],
        "artifact_sha256": artifact_sha,
        "input_hash": digest(payload),
        "total_pages": total,
        "inspected_count": len(inspected_pages),
        "skipped_count": len(skipped_pages),
        "unrendered_count": len(unrendered_pages),
        "unrendered_pages": sorted(unrendered_pages),
        "unaccounted_pages": unaccounted,
        "coverage_ratio": round(len(inspected_pages) / total, 4),
        "coverage_status": "complete" if all_inspected else "partial",
        "observers_used": sorted(observers_used),
        "human_visual_review": "complete_recorded" if human_complete else (
            "partial_recorded" if human_inspected_pages else "not_performed"
        ),
        "skipped_pages": skipped_pages,
        "findings": findings,
        "overall_status": overall,
        "image_bytes_verified": False,
        "reviewer_identity_verified": False,
        "professional_review": "not_performed",
    }
