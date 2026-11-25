"""Phase C2: 专利官方只读连接器（USPTO ODP / EPO OPS）与外部 MCP 证据导入桥。

全部采用用户自带凭据 + 默认离线策略 + 关键日严格分离（申请日/优先权日/公开日/授权日绝不混用）。
"""
from __future__ import annotations

from datetime import date
from functools import partial
import os
import re
from urllib.parse import quote
from xml.etree import ElementTree as ET

from tools.core import ContractError, require, strict_json_loads
from .base import BudgetTracker, ConnectorPolicy, evidence_envelope, guarded_https_get

_EPO_OPS_NS = "{http://ops.epo.org}"
_MISSING_PUBLICATION_DATE = "missing_publication_date_cannot_establish_prior_art_cutoff"


def _valid_iso_date(value) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _uspto_number(value) -> str | None:
    if not isinstance(value, str):
        return None
    number = value.strip()
    if re.fullmatch(r"[A-Z0-9/, .-]+", number, re.ASCII | re.I) and any("0" <= ch <= "9" for ch in number):
        return number
    return None


class UsptoOdpConnector:
    """USPTO Open Data Portal (ODP) 只读元数据与审查历史检索连接器。"""

    HOST = "api.uspto.gov"
    BASE_URL = "https://api.uspto.gov/api/v1/patent/applications/search"

    def __init__(self, policy: ConnectorPolicy, budget: BudgetTracker, *, api_key_env: str = "USPTO_ODP_API_KEY", transport=None):
        self.policy = policy
        self.budget = budget
        self.api_key_env = api_key_env
        self.transport = transport

    def search(self, query: str, *, limit: int = 10, api_key: str | None = None) -> dict:
        require(isinstance(query, str) and bool(query.strip()), "uspto_query_required")
        require(type(limit) is int and 1 <= limit <= 50, "uspto_limit_invalid")
        result = partial(evidence_envelope, source_id="uspto_odp_v1", query=query, budget=self.budget,
                         coverage_level="none", records=[])
        require(self.policy.opt_in_network, "connector_network_disabled")
        key = "" if self.policy.dry_run else (api_key if api_key is not None else os.environ.get(self.api_key_env, ""))
        require(isinstance(key, str), "uspto_api_key_invalid")
        if not key.strip() and not self.policy.dry_run:
            return result(stop_reason="auth_missing", gaps=[f"missing_user_api_key_env:{self.api_key_env}"])
        url = f"{self.BASE_URL}?q={quote(query.strip())}&limit={limit}"
        resp = guarded_https_get(
            url, policy=self.policy, budget=self.budget, purpose="uspto_odp_v1",
            headers={"X-API-KEY": key.strip(), "Accept": "application/json"}, transport=self.transport,
        )
        if self.policy.dry_run and resp.status == 0:
            return result(stop_reason="dry_run", network_requests=0)
        result = partial(result, network_requests=1, raw_bytes=resp.body, http_status=resp.status)
        if resp.status != 200:
            reason = {401: "access_denied_or_challenge", 403: "access_denied_or_challenge", 429: "rate_limited"}
            return result(stop_reason=reason.get(resp.status, "http_error"), gaps=[f"uspto_odp_http_{resp.status}"])
        try:
            data = strict_json_loads(resp.body.decode("utf-8"))
        except (ContractError, ValueError, RecursionError):
            return result(stop_reason="page_changed", gaps=["uspto_odp_invalid_json_envelope"])
        bag = data.get("patentFileWrapperDataBag") if isinstance(data, dict) else None
        if not isinstance(bag, list):
            return result(stop_reason="page_changed", gaps=["uspto_odp_missing_data_bag"])
        records = []
        gaps = ["bibliographic_metadata_only_fulltext_not_fetched"]
        counts = [data[key] for key in ("count", "totalCount", "total") if key in data]
        if any(type(count) is not int or count < 0 for count in counts):
            return result(stop_reason="page_changed", gaps=["uspto_odp_result_count_invalid"])
        total = counts[0] if counts else None
        if len(set(counts)) > 1 or (total is not None and total < len(bag)):
            return result(stop_reason="page_changed", gaps=["uspto_odp_result_count_invalid"])
        truncated = len(bag) > limit or (type(total) is int and total > len(bag))
        if type(total) is not int and len(bag) >= limit:
            truncated = True
        malformed = False
        for item in bag:
            meta = item.get("applicationMetaData") if isinstance(item, dict) else None
            if not isinstance(meta, dict):
                malformed = True
                continue
            meta_application = _uspto_number(meta.get("applicationNumberText"))
            publication_number = _uspto_number(meta.get("earliestPublicationNumber")) or _uspto_number(meta.get("patentNumber"))
            if meta_application is None and publication_number is None:
                malformed = True
                continue
            if len(records) >= limit:
                continue
            pub_date = meta.get("earliestPublicationDate") or meta.get("publicationDate")
            qualified = _valid_iso_date(pub_date)
            if not qualified and _MISSING_PUBLICATION_DATE not in gaps:
                gaps.extend(["some_records_missing_publication_date", _MISSING_PUBLICATION_DATE])
            records.append({
                "application_number": _uspto_number(item.get("applicationNumberText")) or meta_application,
                "publication_number": publication_number,
                "title": meta.get("inventionTitle"),
                "filing_date": meta.get("filingDate"),
                "publication_date": pub_date if qualified else None,
                "grant_date": meta.get("grantDate"),
                "prior_art_date_qualified": qualified,
                "legal_status": meta.get("applicationStatusDescriptionText") or "unknown",
                "jurisdiction": "US",
            })
        if malformed:
            gaps.append("uspto_odp_record_schema_changed")
        if truncated:
            gaps.append("uspto_odp_results_truncated")
        reason = "complete" if records else "zero_hits"
        if malformed and not records:
            reason = "page_changed"
        elif truncated or malformed:
            reason = "partial"
        return result(coverage_level="bibliographic_only" if records else "none", stop_reason=reason,
                      records=records, gaps=gaps, attribution="USPTO Open Data Portal (user-authorized API query)")


def _xml_name(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _epo_publications(search_result) -> tuple[list[dict], set[str]]:
    records = []
    gaps = set()
    seen_publications = set()
    for reference in search_result:
        if _xml_name(reference) != "publication-reference":
            gaps.add("epo_ops_non_publication_record")
            continue
        publication = None
        for doc_id in reference:
            if _xml_name(doc_id) != "document-id":
                gaps.add("epo_ops_unknown_publication_entry")
                continue
            id_type = doc_id.get("document-id-type")
            fields = {_xml_name(child): child.text or "" for child in doc_id}
            if (len(fields) != len(doc_id) or not fields.keys() <= {"country", "doc-number", "kind", "date"}
                    or any(len(child) for child in doc_id)):
                gaps.add("epo_ops_publication_identifier_missing_or_invalid")
                continue
            if id_type == "epodoc" and re.fullmatch(r"[A-Z]{2}[A-Z0-9]+", fields.get("doc-number", "").strip()):
                continue  # OPS 也可能返回不含完整出版标识的备选编号。
            if id_type not in (None, "docdb"):
                gaps.add("epo_ops_unknown_publication_entry")
                continue
            country, number, kind = (fields.get(name, "").strip() for name in ("country", "doc-number", "kind"))
            if (not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[A-Z0-9]+", number)
                    or not re.fullmatch(r"[A-Z][A-Z0-9]{0,2}", kind)):
                gaps.add("epo_ops_publication_identifier_missing_or_invalid")
                continue
            if publication is not None:
                gaps.add("epo_ops_multiple_publication_identifiers")
                continue
            pub_date = fields.get("date", "")
            if re.fullmatch(r"[0-9]{8}", pub_date):
                pub_date = f"{pub_date[:4]}-{pub_date[4:6]}-{pub_date[6:]}"
            qualified = _valid_iso_date(pub_date)
            publication = {
                "publication_number": f"{country}{number}{kind}",
                "jurisdiction": country,
                "kind_code": kind,
                "publication_date": pub_date if qualified else None,
                "prior_art_date_qualified": qualified,
                "family_id": reference.get("family-id") or doc_id.get("family-id"),
            }
        if publication is None:
            gaps.add("epo_ops_publication_identifier_missing_or_invalid")
        elif publication["publication_number"] in seen_publications:
            gaps.add("epo_ops_duplicate_publication")
        else:
            seen_publications.add(publication["publication_number"])
            records.append(publication)
    return records, gaps


class EpoOpsConnector:
    """EPO Open Patent Services (OPS) 只读 CQL 检索与 INPADOC 同族/法律状态解析器。"""

    HOST = "ops.epo.org"
    SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"

    def __init__(self, policy: ConnectorPolicy, budget: BudgetTracker, *, token_env: str = "EPO_OPS_ACCESS_TOKEN", transport=None):
        self.policy = policy
        self.budget = budget
        self.token_env = token_env
        self.transport = transport

    def search_cql(self, cql: str, *, range_header: str = "1-10", access_token: str | None = None) -> dict:
        require(isinstance(cql, str) and bool(cql.strip()), "epo_cql_required")
        match = re.fullmatch(r"([1-9][0-9]{0,5})-([1-9][0-9]{0,5})", range_header) if isinstance(range_header, str) else None
        require(match is not None, "epo_range_invalid")
        start, end = map(int, match.groups())
        require(0 <= end - start < 100, "epo_range_invalid")
        result = partial(evidence_envelope, source_id="epo_ops_v32", query=cql, budget=self.budget,
                         coverage_level="none", records=[], attribution="EPO OPS (CC BY 4.0 where applicable)")
        require(self.policy.opt_in_network, "connector_network_disabled")
        token = "" if self.policy.dry_run else (access_token if access_token is not None else os.environ.get(self.token_env, ""))
        require(isinstance(token, str), "epo_token_invalid")
        if not token.strip() and not self.policy.dry_run:
            return result(stop_reason="auth_missing", gaps=[f"missing_user_token_env:{self.token_env}"])
        url = f"{self.SEARCH_URL}?q={quote(cql.strip())}"
        resp = guarded_https_get(
            url, policy=self.policy, budget=self.budget, purpose="epo_ops_v32",
            headers={"Authorization": f"Bearer {token.strip()}", "Accept": "application/xml", "X-OPS-Range": range_header},
            transport=self.transport,
        )
        if self.policy.dry_run and resp.status == 0:
            return result(stop_reason="dry_run", network_requests=0)
        result = partial(result, network_requests=1, raw_bytes=resp.body, http_status=resp.status)
        if resp.status == 429 or (resp.status == 403 and b"quota" in resp.body.lower()):
            return result(stop_reason="rate_limited", gaps=["epo_ops_quota_or_rate_limited"])
        if resp.status not in (200, 404):
            reason = "access_denied_or_challenge" if resp.status in (401, 403) else "http_error"
            return result(stop_reason=reason, gaps=[f"epo_ops_http_{resp.status}"])
        try:
            xml_text = resp.body.decode("utf-8-sig")
            if re.search(r"<!DOCTYPE|<!ENTITY", xml_text, re.IGNORECASE) or "\x00" in xml_text:
                return result(stop_reason="page_changed", gaps=["epo_ops_xml_dtd_forbidden"])
            root = ET.fromstring(xml_text)
        except (ET.ParseError, ValueError, RecursionError):
            return result(stop_reason="page_changed", gaps=["epo_ops_xml_parse_failed"])
        if resp.status == 404:
            if (root.tag == _EPO_OPS_NS + "fault" and not root.attrib and not (root.text or "").strip()
                    and all(len(item) == 0 and not item.attrib and not (item.tail or "").strip() for item in root)
                    and [(item.tag, (item.text or "").strip()) for item in root] == [
                        (_EPO_OPS_NS + "code", "CLIENT.NotFound"),
                        (_EPO_OPS_NS + "message", "No results found"),
                    ]):
                return result(stop_reason="partial" if start > 1 else "zero_hits", gaps=["epo_ops_no_hits_in_requested_range"])
            return result(stop_reason="http_error", gaps=["epo_ops_http_404"])
        root_name = _xml_name(root)
        searches = [root] if root_name == "biblio-search" else []
        root_gaps = []
        if root_name == "world-patent-data":
            root_entries = {_xml_name(item) for item in root}
            if root_entries - {"biblio-search", "meta", "fault"}:
                root_gaps.append("epo_ops_unknown_root_entry")
            if "fault" in root_entries:
                return result(stop_reason="page_changed", gaps=["epo_ops_fault_in_search_response", *root_gaps])
            searches = [item for item in root if _xml_name(item) == "biblio-search"]
        if len(searches) != 1:
            return result(stop_reason="page_changed", gaps=["epo_ops_xml_search_schema_changed", *root_gaps])
        search = searches[0]
        total_text = search.get("total-result-count")
        if total_text is not None and not re.fullmatch(r"[0-9]{1,12}", total_text):
            return result(stop_reason="page_changed", gaps=["epo_ops_result_count_invalid", *root_gaps])
        total = int(total_text) if total_text is not None else None
        result_sets = [item for item in search if _xml_name(item) == "search-result"]
        if len(result_sets) != 1 and not (total == 0 and not result_sets):
            return result(stop_reason="page_changed", gaps=["epo_ops_xml_search_result_missing_or_ambiguous", *root_gaps])
        records, issues = _epo_publications(result_sets[0] if result_sets else ())
        issues.update(root_gaps)
        if any(_xml_name(item) not in {"query", "range", "search-result"} for item in search):
            issues.add("epo_ops_unknown_search_entry")
        reported_ranges = []
        for span in search:
            if _xml_name(span) == "range":
                xml_range = (span.get("begin", ""), span.get("end", ""))
                if all(re.fullmatch(r"[1-9][0-9]{0,5}", value) for value in xml_range):
                    reported_ranges.append(tuple(map(int, xml_range)))
                else:
                    issues.add("epo_ops_response_range_invalid")
        for name, value in resp.headers.items():
            if name.lower() not in {"x-ops-range", "content-range"}:
                continue
            response_range = re.fullmatch(r"(?:items )?([1-9][0-9]{0,5})-([1-9][0-9]{0,5})(?:/([0-9]{1,12}|\*))?", value.strip())
            if response_range is None:
                issues.add("epo_ops_response_range_invalid")
                continue
            reported_ranges.append(tuple(map(int, response_range.groups()[:2])))
            response_total = response_range[3]
            if response_total not in (None, "*"):
                header_total = int(response_total)
                if total is not None and total != header_total:
                    issues.add("epo_ops_response_range_total_mismatch")
                total = max(total or 0, header_total)
        for first, last in reported_ranges:
            if not (first == start <= last <= end):
                issues.add("epo_ops_response_range_mismatch")
            last_available = last if total is None else min(last, total)
            if len(records) != max(0, last_available - first + 1):
                issues.add("epo_ops_response_range_count_mismatch")
            if last < end and (total is None or total > last):
                issues.add("epo_ops_response_range_incomplete")
        page_size = end - start + 1
        truncated = (start > 1 or len(records) > page_size or (total is not None and total > len(records))
                     or (total is None and len(records) >= page_size))
        if total is not None and total < len(records):
            issues.add("epo_ops_result_count_mismatch")
        gaps = ["epo_cql_bibliographic_only_claims_and_fulltext_require_separate_fetch"]
        if any(not record["prior_art_date_qualified"] for record in records[:page_size]):
            gaps.append(_MISSING_PUBLICATION_DATE)
        if truncated:
            gaps.append("epo_ops_results_truncated")
        gaps.extend(sorted(issues))
        reason = "complete" if records else "zero_hits"
        if issues and not records:
            reason = "page_changed"
        elif issues or truncated:
            reason = "partial"
        return result(coverage_level="bibliographic_only" if records else "none",
                      stop_reason=reason,
                      records=records[:page_size], gaps=gaps,
                      attribution="European Patent Office OPS (CC BY 4.0 notice preserved)")


class ExternalMcpBridge:
    """将外部合规 MCP（如 patent_mcp_server / patents-mcp / patsnap）或用户导出快照归一入账。"""

    SUPPORTED_PROVIDERS = frozenset({
        "patent_mcp_server", "patents-mcp", "patsnap_mcp", "epo_ops_mcp", "google_patents_export", "cnipa_export",
    })
    MAX_PAYLOAD_BYTES = 2_000_000
    MAX_RECORDS = 1_000

    @classmethod
    def import_records(cls, *, provider: str, query: str, raw_payload: bytes, coverage_level: str) -> dict:
        require(provider in cls.SUPPORTED_PROVIDERS, "external_mcp_provider_unsupported")
        require(isinstance(raw_payload, bytes) and bool(raw_payload), "external_mcp_payload_required")
        require(len(raw_payload) <= cls.MAX_PAYLOAD_BYTES, "external_mcp_payload_too_large")
        try:
            data = strict_json_loads(raw_payload.decode("utf-8"))
        except (ValueError, RecursionError):
            raise ContractError("external_mcp_payload_invalid") from None
        rows = data.get("records") if isinstance(data, dict) else None
        require(isinstance(rows, list), "external_mcp_records_list_required")
        require(len(rows) <= cls.MAX_RECORDS, "external_mcp_too_many_records")

        normalized = []
        gaps = ["source_authenticity_caller_imported_not_independently_verified"]
        for row in rows:
            require(isinstance(row, dict), "external_mcp_record_object_required")
            pub_num = row.get("publication_number") or row.get("patent_number") or row.get("id")
            require(isinstance(pub_num, str) and bool(pub_num.strip()), "external_mcp_publication_id_required")
            pub_date = row.get("publication_date")
            filing_date = row.get("filing_date")
            qualified = _valid_iso_date(pub_date)
            if not qualified and _MISSING_PUBLICATION_DATE not in gaps:
                gaps.append(_MISSING_PUBLICATION_DATE)
            normalized.append({
                "publication_number": pub_num.strip(),
                "title": row.get("title") or "",
                "jurisdiction": row.get("jurisdiction") or "unknown",
                "filing_date": filing_date,
                "publication_date": pub_date if qualified else None,
                "grant_date": row.get("grant_date"),
                "prior_art_date_qualified": qualified,
                "abstract_or_snippet": row.get("abstract") or row.get("snippet") or "",
                "fulltext_available": bool(row.get("fulltext")),
            })
        return evidence_envelope(
            source_id=f"external_mcp:{provider}",
            query=query,
            coverage_level=coverage_level,
            stop_reason="imported_snapshot",
            network_requests=0,
            raw_bytes=raw_payload,
            records=normalized,
            gaps=gaps,
            attribution=f"Imported from external source {provider} (offline normalization only)",
        )
