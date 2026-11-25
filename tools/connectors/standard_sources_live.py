"""Phase C3: 标准公开题录只读连接器（SAMR 在线题录适配 + ISO/IEC/ITU-T 目录版本比对桥）。

严守边界：
1. SAMR 只访问已核公开题录接口，遇 403/登录/验证码/结构漂移立即停止，绝不猜测或拼接标准全文下载链接；
2. ISO/IEC/ITU-T 桥仅比对用户合法取得的目录快照与草案外部引用，输出失效/待复核清单供 VersionLedger 消费。
"""
from __future__ import annotations

from functools import partial
import re
from urllib.parse import quote

from tools.core import ContractError, require, strict_json_loads
from tools.standard_sources import SAMR_ENDPOINT, SAMR_FORMAT_EVIDENCE
from .base import BudgetTracker, ConnectorPolicy, evidence_envelope, guarded_https_get

_SAMR_CODE = re.compile(r"GB(?:/[TZ])? +[0-9]+(?:\.[0-9]+)*(?:[-—][0-9]{4})?")
_SAMR_TEXT_FIELDS = ("id", "C_C_NAME", "STD_NATURE", "STATE", "ISSUE_DATE", "ACT_DATE")


class SamrLiveConnector:
    """SAMR 公开标准题录受控只读查询适配器（仅题录，绝不下载受限全文）。"""

    HOST = "std.samr.gov.cn"

    def __init__(self, policy: ConnectorPolicy, budget: BudgetTracker, *, transport=None):
        self.policy = policy
        self.budget = budget
        self.transport = transport

    def query_catalog(self, search_text: str, *, page_size: int = 15, page_number: int = 1) -> dict:
        require(isinstance(search_text, str) and bool(search_text.strip()), "samr_search_text_required")
        require(type(page_size) is int and 1 <= page_size <= 50, "samr_page_size_invalid")
        require(type(page_number) is int and 1 <= page_number <= 100, "samr_page_number_invalid")

        url = (
            f"{SAMR_ENDPOINT}?searchText={quote(search_text.strip())}"
            f"&ics=&state=&ISSUE_DATE=&sortOrder=asc&pageSize={page_size}&pageNumber={page_number}"
        )
        resp = guarded_https_get(
            url,
            policy=self.policy, budget=self.budget, purpose="samr_gb_query_live",
            headers={"Accept": "application/json"}, transport=self.transport,
        )
        result = partial(evidence_envelope, source_id="samr_gb_query_live", query=search_text, budget=self.budget,
                         coverage_level="none", records=[])
        if self.policy.dry_run and resp.status == 0:
            return result(stop_reason="dry_run", network_requests=0)
        result = partial(result, network_requests=1, raw_bytes=resp.body, http_status=resp.status)
        if resp.status != 200:
            reason = {401: "access_denied_or_challenge", 403: "access_denied_or_challenge", 429: "rate_limited"}
            return result(stop_reason=reason.get(resp.status, "http_error"), gaps=[f"samr_http_{resp.status}"])
        content_type = next((v for k, v in resp.headers.items() if k.lower() == "content-type"), "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json" and not media_type.endswith("+json"):
            prefix = resp.body[:2048].lstrip().lower()
            if media_type in ("text/html", "application/xhtml+xml") or prefix.startswith((b"<html", b"<!doctype html")):
                return result(stop_reason="access_denied_or_challenge", gaps=["samr_html_or_captcha_challenge_stopped"])
            if media_type:
                return result(stop_reason="page_changed", gaps=["samr_unexpected_content_type"])
        try:
            data = strict_json_loads(resp.body.decode("utf-8"))
        except (ContractError, ValueError, RecursionError):
            return result(stop_reason="page_changed", gaps=["samr_invalid_json_structure_drift"])
        expected_env = set(SAMR_FORMAT_EVIDENCE["envelope_fields"])
        if (not isinstance(data, dict) or not expected_env <= data.keys() or not isinstance(data.get("rows"), list)
                or type(data.get("total")) is not int or data["total"] < 0
                or type(data.get("pageNumber")) is not int or data["pageNumber"] != page_number):
            return result(stop_reason="page_changed", gaps=["samr_envelope_schema_changed"])
        rows = data["rows"]
        total = data["total"]
        offset = (page_number - 1) * page_size
        if (page_number > 1 and offset >= total or len(rows) > min(page_size, total - offset)
                or not rows and total > offset):
            return result(stop_reason="page_changed", gaps=["samr_envelope_schema_changed"])
        records = []
        for row in rows:
            code = row.get("C_STD_CODE") if isinstance(row, dict) else None
            if (not isinstance(code, str) or not _SAMR_CODE.fullmatch(code.strip())
                    or any(field in row and not isinstance(row[field], str) for field in _SAMR_TEXT_FIELDS)
                    or "PROJECT_ID" in row and type(row["PROJECT_ID"]) is not int):
                return result(stop_reason="page_changed", gaps=["samr_record_schema_changed"])
            records.append({
                "id": row.get("id"),
                "standard_code": code.strip(),
                "title": row.get("C_C_NAME"),
                "nature": row.get("STD_NATURE"),
                "state": row.get("STATE"),
                "issue_date": row.get("ISSUE_DATE"),
                "act_date": row.get("ACT_DATE"),
                "fulltext_access": "metadata_only_never_guessed",
            })
        truncated = page_number > 1 or total > len(rows)
        gaps = ["public_catalog_metadata_only_fulltext_rights_not_established"]
        if truncated:
            gaps.append("samr_catalog_results_truncated")
        return result(coverage_level="bibliographic_only" if records else "none",
                      stop_reason="partial" if truncated else "complete" if records else "zero_hits",
                      records=records, gaps=gaps)


class IsoCatalogBridge:
    """将 ISO/IEC/ITU-T 公开目录快照与标准草案外部引用比对，识别废止、修订及版次漂移。"""

    @staticmethod
    def reconcile_references(*, draft_external_references: list[dict], catalog_snapshot: list[dict]) -> dict:
        require(isinstance(draft_external_references, list), "draft_external_references_required")
        require(isinstance(catalog_snapshot, list), "catalog_snapshot_required")
        by_ident: dict[str, list[dict]] = {}
        for row in catalog_snapshot:
            require(isinstance(row, dict) and isinstance(row.get("identifier"), str)
                    and isinstance(row.get("edition", ""), str)
                    and isinstance(row.get("state", "unknown"), str), "catalog_row_invalid")
            by_ident.setdefault(row["identifier"].strip(), []).append(row)

        results = []
        invalidation_targets = []
        for ref in draft_external_references:
            require(isinstance(ref, dict) and isinstance(ref.get("id"), str) and isinstance(ref.get("identifier"), str)
                    and isinstance(ref.get("edition", ""), str), "draft_external_ref_invalid")
            ident = ref["identifier"].strip()
            edition = ref.get("edition", "").strip()
            matches = by_ident.get(ident, [])
            available_editions = sorted({m.get("edition", "").strip() for m in matches})
            if not matches:
                status = "needs_manual_check"
                reason = "not_found_in_supplied_catalog_snapshot"
                invalidation_targets.append(ref["id"])
            else:
                exact = [m for m in matches if m.get("edition", "").strip() == edition] if edition else matches
                chosen = exact[0] if len(exact) == 1 else None
                cat_state = (chosen.get("state") or "unknown").strip().lower() if chosen else "unknown"
                if edition and not exact:
                    status = "edition_mismatch"
                    reason = "draft_edition_differs_from_snapshot"
                    invalidation_targets.append(ref["id"])
                elif len(exact) > 1:
                    status = "needs_manual_check"
                    reason = "multiple_catalog_matches"
                    invalidation_targets.append(ref["id"])
                elif cat_state == "withdrawn":
                    status = "withdrawn"
                    reason = f"withdrawn_replaced_by:{chosen.get('replaced_by') or 'unknown'}"
                    invalidation_targets.append(ref["id"])
                elif cat_state == "under_revision":
                    status = "under_revision"
                    reason = "standard_under_revision_verify_transition"
                elif cat_state == "current":
                    status = "current_in_snapshot"
                    reason = "matches_supplied_catalog_snapshot_not_live_legal_certification"
                else:
                    status = "needs_manual_check"
                    reason = f"snapshot_state_{cat_state}"
                    invalidation_targets.append(ref["id"])
            results.append({
                "ref_id": ref["id"],
                "identifier": ident,
                "draft_edition": edition or "unspecified",
                "available_editions": available_editions,
                "status": status,
                "reason": reason,
            })
        return {
            "schema": "dyz-standard-reference-reconciliation-v1",
            "checked_count": len(results),
            "results": results,
            "invalidation_targets": sorted(set(invalidation_targets)),
            "live_authority_verified": False,
            "professional_review": "not_performed",
        }
