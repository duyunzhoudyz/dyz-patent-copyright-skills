"""SE-05：离线标准证据包与授权本地导入；不联网、不推断下载入口。

支持已观察的SAMR gbQueryPage公开题录JSON和原创synthetic_catalog_v1。
只解析获准本地快照，不包含网络传输；题录不能证明全文权利或发布机构。
PDF工具仅接受调用者明确提供的绝对路径和SHA-256，不能在离线worker内执行。
身份、授权和引用命题的真实性不因字段齐全或hash匹配而获得认证。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from tools.core import (
    ContractError, canonical_bytes, check_permission, digest, is_macos_system_root_symlink,
    parse_time, preflight, require, require_fields, safe_path, sha256_bytes, strict_json_loads,
)

VERSION = "1.3"
MAX_INPUT_BYTES = 16_000_000
MAX_REQUEST_BYTES = 2_000_000
MAX_TEXT_BYTES = 8_000_000
MAX_PAGES = 10_000
MAX_RECORDS = 10_000
IDENTITY_FIELDS = ("number", "edition", "publisher", "title")
ACCESS_STATES = {"metadata_only", "read_only", "downloadable", "restricted",
                 "local_authorized", "unknown"}
DATA_PATHS = {"host_model", "index", "telemetry", "tools", "logs", "subprocess"}
SAMR_ENDPOINT = "https://std.samr.gov.cn/gb/search/gbQueryPage"
# 仅记录公开题录的结构观察和响应指纹，不保存标准全文或个人起草者信息。
SAMR_FORMAT_EVIDENCE = {
    "page_url": "https://std.samr.gov.cn/gb/gbQuery",
    "response_url": SAMR_ENDPOINT + "?searchText=&ics=&state=&ISSUE_DATE=&sortOrder=asc&pageSize=15&pageNumber=1&_=1794576746801",
    "zero_response_url": SAMR_ENDPOINT + "?searchText=SYNTHETIC-NO-SUCH-STANDARD-20261113&ics=&state=&ISSUE_DATE=&sortOrder=asc&pageSize=15&pageNumber=1&_=1794576746801",
    "observed_on": "2026-11-13",
    "evidence_recorded_at": "2026-11-13T13:35:02.920591+00:00",
    "response_sha256": "cfa0d89074f67ac25c3208cca62cdcc80ca0031b149e6637c218c56847d04060",
    "zero_response_sha256": "39c824e6dc6faf61b718b1907496678df9e83ca8558be857ca45718f97060124",
    "response_bytes": 3793, "zero_response_bytes": 36,
    "observed_http_status": 200, "content_type": "application/json;charset=utf-8",
    "envelope_fields": ["total", "pageNumber", "rows"],
    "record_fields": ["id", "C_C_NAME", "C_STD_CODE", "STD_NATURE", "ACT_DATE", "STATE", "ISSUE_DATE", "PROJECT_ID"],
    "scope": "public_catalog_metadata_only_not_standard_fulltext",
}


def _text(value, code):
    require(isinstance(value, str) and bool(value.strip()), code)
    return value


def _hash(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            "sha256_required")
    return value


def _identity(value, *, allow_unknown_publisher=False):
    require(isinstance(value, dict) and set(value) == set(IDENTITY_FIELDS),
            "identity_fields_invalid")
    for name in IDENTITY_FIELDS:
        if name == "publisher" and allow_unknown_publisher and value[name] is None:
            continue
        _text(value[name], "identity_text_required")
    return copy.deepcopy(value)


def scoped_path(root, relative, *, must_exist=True):
    """复用safe_path，另拒绝根内链接、重解析点和硬链接别名。"""
    target = safe_path(root, relative, must_exist=must_exist)
    base = Path(root).absolute()
    candidates = list(reversed(base.parents)) + [base]
    cursor = base
    for piece in relative.replace("\\", "/").split("/"):
        cursor = cursor / piece
        candidates.append(cursor)
    for path in candidates:
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        is_link = stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if is_link:
            if path != candidates[-1] and is_macos_system_root_symlink(path):
                try:
                    info = path.stat()
                except OSError:
                    raise ContractError("linked_path_forbidden") from None
            else:
                require(False, "linked_path_forbidden")
        if stat.S_ISREG(info.st_mode):
            require(info.st_nlink == 1, "file_alias_forbidden")
    return target


def authorize_io(root, *, synthetic=False, admission=None, payload=None,
                 inputs=None, outputs=(), actions=("local_process", "copy")):
    """每次I/O重新用系统UTC核权限；调用者时间不得延长有效期。

    admission输入路径/hash和输出白名单先核；payload绑定在请求文件读后、
    材料读前核。此记录是授权证据索引，不是用户或权利人的身份认证。
    """
    require(type(synthetic) is bool, "synthetic_boolean_required")
    if synthetic:
        require(admission is None, "mode_ambiguous")
        if payload is not None:
            require(payload.get("mode", "synthetic") == "synthetic",
                    "material_mode_mismatch")
        return "synthetic"
    require(isinstance(admission, dict), "authorization_required")
    require_fields(admission, ("root", "inputs", "outputs", "payload_hash",
                               "sensitivity", "purpose", "permissions", "environment"))
    case_root = Path(root).resolve()
    require(Path(admission["root"]).resolve() == case_root, "root_scope_mismatch")
    package_root = Path(__file__).resolve().parents[1]
    # 真实材料和派生副本不能落入源码/分发包，也不能以其祖先作案例根。
    require(not case_root.is_relative_to(package_root)
            and not package_root.is_relative_to(case_root), "case_root_overlaps_package")
    require(admission["sensitivity"] in {"public", "confidential", "restricted"},
            "real_material_sensitivity_required")
    require(isinstance(admission["inputs"], dict)
            and isinstance(admission["outputs"], list), "io_scope_required")
    if payload is not None:
        require(digest(payload) == admission["payload_hash"], "payload_binding_mismatch")
        require(payload.get("mode", "authorized_case") == "authorized_case",
                "material_mode_mismatch")
    for name, expected in (inputs or {}).items():
        _hash(expected)
        require(admission["inputs"].get(name) == expected, "input_scope_mismatch")
    require(all(name in admission["outputs"] for name in outputs), "output_scope_mismatch")
    now = datetime.now(timezone.utc).isoformat()
    # 即使用户声明public，真实入口仍需六条数据路径明示，不继承宽松示例模式。
    preflight(admission["environment"], admission["permissions"],
              sensitivity="restricted", purpose=admission["purpose"], now=now)
    for action in actions:
        check_permission(admission["permissions"], action=action,
                         purpose=admission["purpose"], recipient="local_tool", now=now)
    return "authorized_case"


def read_bound(root, relative, expected, *, synthetic=False, admission=None,
               payload=None, limit=MAX_INPUT_BYTES):
    """读取固定快照；真实入口预检先于open，读取后再核字节hash。"""
    _hash(expected)
    authorize_io(root, synthetic=synthetic, admission=admission, payload=payload,
                 inputs={relative: expected})
    path = scoped_path(root, relative)
    require(path.is_file(), "input_file_required")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        require(before.st_nlink == 1, "file_alias_forbidden")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) <= limit, "input_size_limit")
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "input_changed_during_read")
    require(sha256_bytes(raw) == expected, "input_hash_changed")
    require(scoped_path(root, relative) == path, "input_path_changed")
    return raw


def new_output_path(root, relative, *, synthetic=False, admission=None, payload=None):
    authorize_io(root, synthetic=synthetic, admission=admission, payload=payload,
                 outputs=(relative,))
    target = scoped_path(root, relative, must_exist=False)
    require(target.parent.is_dir(), "output_parent_missing")
    require(not target.exists(), "output_already_exists")
    return target


def write_report(root, relative, report, *, synthetic=False, admission=None, payload=None):
    content = canonical_bytes(report) + b"\n"
    target = new_output_path(root, relative, synthetic=synthetic,
                             admission=admission, payload=payload)
    with target.open("xb") as stream:
        stream.write(content)
    return sha256_bytes(content)


def _samr_request(request):
    require_fields(request, ("url", "retrieved_at", "http_status", "content_type"))
    _text(request["url"], "catalog_url_required")
    try:
        url = urlsplit(request["url"])
    except ValueError as exc:
        raise ContractError("catalog_origin_not_allowed") from exc
    require(url.scheme == "https" and url.netloc == "std.samr.gov.cn"
            and url.path == "/gb/search/gbQueryPage" and not url.fragment,
            "catalog_origin_not_allowed")
    pairs = parse_qsl(url.query, keep_blank_values=True)
    require(len({key for key, _ in pairs}) == len(pairs), "catalog_query_ambiguous")
    parameters = dict(pairs)
    require(set(parameters).issubset({"searchText", "ics", "state", "ISSUE_DATE",
                "sortOrder", "pageSize", "pageNumber", "_"}), "catalog_query_unsupported")
    for key in ("pageSize", "pageNumber"):
        require(re.fullmatch(r"[1-9]\d{0,6}", parameters.get(key, "")) is not None,
                "catalog_pagination_required")
    page_size, page_number = int(parameters["pageSize"]), int(parameters["pageNumber"])
    require(page_size in {10, 15, 20, 30, 50}, "catalog_page_size_unsupported")
    parse_time(request["retrieved_at"])
    require(type(request["http_status"]) is int and 100 <= request["http_status"] <= 599,
            "catalog_http_status_required")
    _text(request["content_type"], "catalog_content_type_required")
    return page_number, page_size


def _parse_samr_catalog(raw, request, synthetic):
    page_number, page_size = _samr_request(request)
    response = {"adapter": "samr_gb_query_v1", "parser_version": VERSION,
        "snapshot_sha256": sha256_bytes(raw),
        "mode": "synthetic" if synthetic else "supplied_snapshot",
        "request": copy.deepcopy(request), "source_endpoint": SAMR_ENDPOINT,
        "format_evidence": copy.deepcopy(SAMR_FORMAT_EVIDENCE),
        "official_source_verified": False,
        "source_authenticity": "caller_supplied_snapshot_not_authenticated",
        "network": "not_performed", "download": "not_performed",
        "professional_review": "not_performed", "official_status": "not_asserted",
        "external_action": "not_performed"}
    failure = {"result_count": None, "total_count": None, "records": [],
               "pagination_complete": False}
    if request["http_status"] != 200:
        state = "access_denied" if request["http_status"] in {401, 403} else "network_failed"
        return {**response, **failure, "state": state}
    try:
        require(request["content_type"].split(";", 1)[0].strip().lower() == "application/json",
                "catalog_response_type_changed")
        value = strict_json_loads(raw.decode("utf-8"))
        require_fields(value, ("total", "pageNumber", "rows"))
        require(type(value["total"]) is int and 0 <= value["total"] <= 10_000_000,
                "catalog_total_invalid")
        require(type(value["pageNumber"]) is int and value["pageNumber"] == page_number,
                "catalog_response_page_mismatch")
        rows = value["rows"]
        require(isinstance(rows, list) and len(rows) <= page_size, "catalog_records_invalid")
        require(len(rows) <= value["total"], "catalog_total_inconsistent")
        records, seen = [], set()
        for row in rows:
            require_fields(row, ("id", "C_C_NAME", "C_STD_CODE", "STD_NATURE", "ACT_DATE",
                                 "STATE", "ISSUE_DATE", "PROJECT_ID"))
            rid = _text(row["id"], "catalog_record_id_required")
            require(rid not in seen, "catalog_record_id_duplicated")
            seen.add(rid)
            title = _text(row["C_C_NAME"], "catalog_title_required")
            code = _text(row["C_STD_CODE"], "catalog_standard_code_required")
            matched = re.fullmatch(r"(GB(?:/[TZ])?)\s+(\d+(?:\.\d+)*)[-—](\d{4})", code)
            require(matched is not None, "catalog_standard_code_unsupported")
            states = {"即将实施": "not_yet_effective", "现行": "current", "废止": "withdrawn"}
            require(isinstance(row["STATE"], str) and row["STATE"] in states,
                    "catalog_state_unsupported")
            require(isinstance(row["STD_NATURE"], str)
                    and row["STD_NATURE"] in {"推荐性", "强制性", "指导性技术文件"},
                    "catalog_standard_nature_unsupported")
            for key in ("ACT_DATE", "ISSUE_DATE"):
                require(isinstance(row[key], str)
                        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[key]) is not None,
                        "catalog_date_invalid")
                datetime.strptime(row[key], "%Y-%m-%d")
            require(type(row["PROJECT_ID"]) is int and row["PROJECT_ID"] > 0,
                    "catalog_project_id_invalid")
            # 平台主管单位不是每份标准的发布机构；缺失关系也不能写成“没有替代”。
            records.append({"catalog_id": rid, "standard_code": code,
                "identity": {"number": matched[1] + " " + matched[2],
                    "edition": matched[3], "title": title, "publisher": None},
                "identity_complete": False, "identity_missing_fields": ["publisher"],
                "status": states[row["STATE"]], "reported_status": row["STATE"],
                "status_as_of": request["retrieved_at"], "standard_nature": row["STD_NATURE"],
                "issue_date": row["ISSUE_DATE"], "implementation_date": row["ACT_DATE"],
                "project_id": row["PROJECT_ID"], "access_status": "metadata_only",
                "replaces": None, "replacement_status": "not_provided",
                "identity_authenticity": "not_verified"})
        total = value["total"]
        expected_rows = min(page_size, max(0, total - (page_number - 1) * page_size))
        require(len(rows) <= expected_rows, "catalog_page_row_count_inconsistent")
        complete = page_number == 1 and len(rows) == total
        state = "zero_results" if complete and total == 0 else "results" if complete else "pagination_incomplete"
        return {**response, "state": state, "result_count": len(records),
            "total_count": total, "records": records, "pagination_complete": complete,
            "pagination": {"page_number": page_number, "page_size": page_size,
                "expected_rows_on_page": expected_rows, "page_rows_complete": len(rows) == expected_rows,
                "all_pages_collected": complete}}
    except (ContractError, UnicodeError, KeyError, TypeError, ValueError):
        return {**response, **failure, "state": "parse_failed"}


def parse_catalog(raw: bytes, *, adapter: str, synthetic: bool = False,
                  request: dict | None = None) -> dict:
    """纯解析已观察的题录快照；真实I/O与权限由CLI或调用者边界负责。"""
    require(type(synthetic) is bool, "synthetic_boolean_required")
    require(isinstance(raw, bytes) and len(raw) <= MAX_REQUEST_BYTES, "catalog_size_limit")
    if adapter == "samr_gb_query_v1":
        return _parse_samr_catalog(raw, request, synthetic)
    require(adapter == "synthetic_catalog_v1", "adapter_not_implemented")
    require(synthetic is True, "synthetic_catalog_only")
    require(isinstance(raw, bytes) and len(raw) <= MAX_REQUEST_BYTES, "catalog_size_limit")
    response = {"adapter": adapter, "parser_version": VERSION,
                "snapshot_sha256": sha256_bytes(raw), "mode": "synthetic",
                "official_source_verified": False, "network": "not_performed"}
    try:
        value = strict_json_loads(raw.decode("utf-8"))
        require_fields(value, ("schema", "records", "complete"))
        require(value["schema"] == adapter, "catalog_schema_changed")
        records = value["records"]
        require(isinstance(records, list) and len(records) <= MAX_RECORDS,
                "catalog_records_invalid")
        require(type(value["complete"]) is bool, "catalog_pagination_unknown")
        for record in records:
            _identity(record["identity"])
            require(record.get("status") in {"current", "superseded", "withdrawn", "draft", "unknown"},
                    "catalog_status_invalid")
            require(record.get("access_status") in ACCESS_STATES, "access_status_invalid")
            require(isinstance(record.get("replaces"), list), "replacement_relationship_required")
            for previous in record["replaces"]:
                _identity(previous)
        state = ("pagination_incomplete" if not value["complete"] else
                 "results" if records else "zero_results")
        return {**response, "state": state, "result_count": len(records),
                "records": copy.deepcopy(records), "pagination_complete": value["complete"]}
    except (ContractError, UnicodeError, KeyError, TypeError):
        return {**response, "state": "parse_failed", "result_count": None,
                "records": [], "pagination_complete": False}


def select_standard(records: list[dict], identity: dict) -> dict:
    """精确标准号、版次、机构和标题全匹配；不默认选择最新版本。"""
    selected = _identity(identity, allow_unknown_publisher=True)
    require(isinstance(records, list), "catalog_records_invalid")
    matches = [row for row in records if row.get("identity") == selected]
    require(len(matches) == 1, "identity_not_unique")
    return copy.deepcopy(matches[0])


def _pages(value):
    require(isinstance(value, list) and 0 < len(value) <= MAX_PAGES, "pages_required")
    seen = set()
    for row in value:
        require(isinstance(row, dict), "page_object_required")
        require(type(row.get("page")) is int and 0 < row["page"] <= MAX_PAGES,
                "page_number_invalid")
        require(row["page"] not in seen, "duplicate_page")
        require(isinstance(row.get("text"), str), "page_text_required")
        seen.add(row["page"])
    require(len(canonical_bytes(value)) <= MAX_TEXT_BYTES, "extracted_text_size_limit")
    return sorted(copy.deepcopy(value), key=lambda row: row["page"])


def _tool(spec, name):
    require_fields(spec, ("path", "sha256"))
    expected = _hash(spec["sha256"])
    path = Path(spec["path"])
    require(path.is_absolute() and path.name.lower() in {name, name + ".exe"},
            "pdf_tool_path_invalid")
    require(path.is_file() and not path.is_symlink(), "pdf_tool_unavailable")
    require(path.stat().st_size <= 64_000_000, "pdf_tool_size_limit")
    require(sha256_bytes(path.read_bytes()) == expected, "pdf_tool_hash_changed")
    return path


def _run_pdf(executable, arguments, output, *, timeout=30):
    # 输出落临时文件，避免不受限的capture_output内存；超时由run结束自有进程。
    try:
        with output.open("xb") as stream:
            completed = subprocess.run([str(executable), *arguments], stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.DEVNULL, shell=False,
                timeout=timeout, check=False)
        require(completed.returncode == 0, "pdf_tool_failed")
        require(output.stat().st_size <= MAX_TEXT_BYTES, "pdf_tool_output_limit")
        return output.read_bytes()
    except subprocess.TimeoutExpired as exc:
        raise ContractError("pdf_tool_timeout") from exc
    except OSError as exc:
        raise ContractError("pdf_tool_io_error") from exc


def _extract_pdf(raw, tools, *, authorize):
    require(isinstance(tools, dict) and set(tools) == {"pdfinfo", "pdftotext"},
            "pdf_tools_required")
    authorize()
    info, text = _tool(tools["pdfinfo"], "pdfinfo"), _tool(tools["pdftotext"], "pdftotext")
    with tempfile.TemporaryDirectory(prefix="dyz-standard-pdf-") as directory:
        folder = Path(directory)
        snapshot = folder / "source.pdf"
        authorize()
        snapshot.write_bytes(raw)
        authorize()
        metadata = _run_pdf(info, [str(snapshot)], folder / "info.txt")
        match = re.findall(rb"^Pages:\s+(\d+)\s*$", metadata, re.M)
        require(len(match) == 1, "pdf_page_count_unavailable")
        total = int(match[0])
        require(0 < total <= MAX_PAGES, "pdf_page_count_limit")
        authorize()
        extracted = _run_pdf(text, ["-enc", "UTF-8", "-layout", str(snapshot), "-"],
                             folder / "text.txt")
    try:
        decoded = extracted.decode("utf-8")
    except UnicodeError as exc:
        raise ContractError("pdf_text_encoding_invalid") from exc
    pieces = decoded.split("\f")
    if pieces and not pieces[-1].strip():
        pieces.pop()
    rows = _pages([{"page": index, "text": value} for index, value in enumerate(pieces, 1)])
    complete = len(rows) == total and all(row["text"].strip() for row in rows)
    return rows, {"tool": "pdfinfo+pdftotext", "tool_version": "executable_sha256_bound",
        "tools": copy.deepcopy(tools), "total_pages": total,
        "page_count_status": "verified", "page_count_basis": "independent_pdfinfo",
        "coverage": "complete" if complete else "partial",
        "extracted_pages": [row["page"] for row in rows],
        "missing_or_unreadable_pages": [n for n in range(1, total + 1)
            if n > len(rows) or not rows[n - 1]["text"].strip()],
        "text_fidelity": "not_verified", "ocr": "not_performed"}


def _citations(citations, pages, *, extraction, original_sha256, extracted_text_sha256):
    """绑定单页旧形状或segments原文；字符区间为零基Unicode左闭右开。

    segments按页/字符有序且不得重叠，不自动排序、拼句或判断附录/表格语义。
    coverage只核声明区间连续性及源提取覆盖，不能证明整条条款或命题完整。
    """
    require(isinstance(citations, list) and len(citations) <= MAX_RECORDS,
            "citations_list_required")
    by_page = {row["page"]: row["text"] for row in pages}
    range_fields = ("page", "start", "end", "quote")
    evidence, seen = [], set()
    for item in citations:
        require(isinstance(item, dict), "citation_object_required")
        require_fields(item, ("id", "proposition", "relation"))
        cid = _text(item["id"], "citation_id_required")
        require(cid not in seen, "duplicate_citation_id")
        seen.add(cid)
        _text(item["proposition"], "citation_proposition_required")
        require(item["relation"] in {"supports", "contradicts", "context"},
                "citation_relation_invalid")
        segmented = "segments" in item
        if segmented:
            require(not any(name in item for name in range_fields),
                    "citation_shape_ambiguous")
            parts = item["segments"]
            require(isinstance(parts, list) and 0 < len(parts) <= MAX_RECORDS,
                    "citation_segments_required")
        else:
            parts = [item]
        bound, contiguous = [], True
        for part in parts:
            require(isinstance(part, dict), "citation_segment_object_required")
            require_fields(part, ("page", "start", "end"))
            page, start, end = part["page"], part["start"], part["end"]
            require(type(page) is int and page in by_page, "citation_page_not_read")
            text = by_page[page]
            require(bool(text.strip()), "citation_page_unreadable")
            require_fields(part, ("quote",))
            require(type(start) is int and type(end) is int
                    and 0 <= start < end <= len(text), "citation_range_invalid")
            require(text[start:end] == part["quote"], "citation_text_mismatch")
            if bound:
                previous = bound[-1]
                require((page, start) >= (previous["page"], previous["end"]),
                        "citation_segments_not_ordered")
                contiguous = contiguous and (
                    (page == previous["page"] and start == previous["end"])
                    or (page == previous["page"] + 1 and start == 0
                        and previous["end"] == len(by_page[previous["page"]])))
            context_start, context_end = max(0, start - 60), min(len(text), end + 60)
            bound.append({"page": page, "start": start, "end": end,
                "quote": text[start:end], "literal_binding": "verified",
                "context": text[context_start:context_end],
                "context_start": context_start, "context_end": context_end})
        unreadable = [page for page in range(bound[0]["page"], bound[-1]["page"] + 1)
                      if not by_page.get(page, "").strip()]
        complete = contiguous and not unreadable and extraction["coverage"] == "complete"
        evidence.append({**copy.deepcopy(item),
            **({"segments": bound} if segmented else bound[0]),
            "literal_binding": "verified", "original_sha256": original_sha256,
            "extracted_text_sha256": extracted_text_sha256,
            "coverage": "complete" if complete else "partial",
            "coverage_scope": "declared_ranges_and_source_extraction_only",
            "range_continuity": "contiguous" if contiguous else "gapped",
            "source_coverage": extraction["coverage"],
            "missing_or_unreadable_pages": unreadable,
            "semantic_completeness": "not_verified", "proposition_support": "not_verified",
            "original_page_reopened": "not_performed"})
    return evidence


def import_local(root, path: str, payload: dict, *, synthetic: bool = False,
                 admission: dict | None = None) -> dict:
    """导入授权本地TXT/PDF固定快照，返回分离hash、覆盖和单页/多段引用。

    citations支持旧page/start/end/quote或有序segments列表，二者不得混用。
    每段含page/start/end/quote；缺页、空页或引文间断不能标覆盖complete。
    PDF无明确工具时，只接受标明自报的转写并保持partial、总页数not_verified。
    不把转写最大页号或用户total_pages当原件页数，不认证自然语言命题。
    """
    require_fields(payload, ("expected_sha256", "identity", "access_status"))
    expected = _hash(payload["expected_sha256"])
    identity = _identity(payload["identity"])
    access = payload["access_status"]
    require(access in ACCESS_STATES, "access_status_invalid")
    require(access in {"local_authorized", "read_only", "downloadable", "restricted"},
            "fulltext_access_not_proven")
    mode = authorize_io(root, synthetic=synthetic, admission=admission, payload=payload,
                         inputs={path: expected})
    raw = read_bound(root, path, expected, synthetic=synthetic,
                     admission=admission, payload=payload)
    suffix = Path(path).suffix.lower()
    if suffix == ".txt":
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ContractError("text_encoding_invalid") from exc
        require(bool(text.strip()), "text_unreadable")
        rows = _pages([{"page": index, "text": value}
            for index, value in enumerate(text.split("\f"), 1)])
        unreadable = [row["page"] for row in rows if not row["text"].strip()]
        extraction = {"tool": "utf8_formfeed", "tool_version": VERSION,
            "total_pages": len(rows), "page_count_status": "verified",
            "page_count_basis": "text_formfeed_segments_not_pdf_or_printed_pages",
            "coverage": "partial" if unreadable else "complete",
            "extracted_pages": [r["page"] for r in rows],
            "missing_or_unreadable_pages": unreadable,
            "text_fidelity": "byte_decoded", "ocr": "not_performed"}
    elif suffix == ".pdf":
        require(raw.startswith(b"%PDF-"), "pdf_signature_invalid")
        if "pdf_tools" in payload:
            def authorize():
                authorize_io(root, synthetic=synthetic, admission=admission, payload=payload,
                             inputs={path: expected}, actions=("local_process", "copy", "subprocess"))
            rows, extraction = _extract_pdf(raw, payload["pdf_tools"], authorize=authorize)
        else:
            transcription = payload.get("transcription", {})
            require(isinstance(transcription, dict), "transcription_object_required")
            rows = _pages(transcription["pages"]) if transcription.get("pages") else []
            extraction = {"tool": "caller_transcription" if rows else "none",
                "tool_version": "not_verified", "total_pages": None,
                "page_count_status": "not_verified", "page_count_basis": "tool_not_executed",
                "coverage": "partial" if rows else "unreadable",
                "extracted_pages": [r["page"] for r in rows],
                "text_fidelity": "not_verified", "ocr": "not_performed"}
    else:
        raise ContractError("source_format_unsupported")
    text_hash = sha256_bytes(canonical_bytes(rows))
    citations = _citations(payload.get("citations", []), rows, extraction=extraction,
                          original_sha256=expected, extracted_text_sha256=text_hash)
    queries = payload.get("queries", [])
    require(isinstance(queries, list) and len(queries) <= MAX_RECORDS, "queries_list_required")
    query_results = []
    for query in queries:
        require_fields(query, ("id", "text"))
        needle = _text(query["text"], "query_text_required")
        hits = [row["page"] for row in rows if needle in row["text"]]
        query_results.append({"id": query["id"], "pages": hits,
            "state": "found_literal_text" if hits else "not_found_in_checked_scope" if rows else "reading_unavailable",
            "semantic_support": "not_verified"})
    return {"tool": "tools.standard_sources", "tool_version": VERSION, "mode": mode,
        "status": "needs_review" if extraction["coverage"] == "complete"
            and all(item["coverage"] == "complete" for item in citations) else "needs_evidence",
        "identity": identity, "identity_digest": digest(identity),
        "identity_authenticity": "not_verified", "access_status": access,
        "path": path, "original_sha256": expected, "original_bytes": len(raw),
        "extracted_text_sha256": text_hash, "text_hash_basis": "canonical_page_records_utf8",
        "extraction": {**extraction, "original_sha256": expected, "text_sha256": text_hash},
        "pages": rows, "citations": citations, "queries": query_results,
        "full_text_absence_allowed": False,
        "authorization_binding": digest(admission) if admission else None,
        "authorization_authenticity": "caller_responsibility_not_authenticated",
        "authorization_binding_scope": "change_detection_not_signature_or_trusted_anchor",
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "material_classification": "caller_declaration_not_verified",
        "professional_review": "not_performed", "visual_review": "not_performed",
        "official_status": "not_asserted", "external_action": "not_performed",
        "network": "not_performed", "download": "not_performed"}


_VERIFICATION_SEAL = object()


class _VerifiedReports(dict):
    """只在本进程的实际文件核验后签发；JSON往返不能继承核验能力。"""

    def __init__(self, value, payload):
        super().__init__(value)
        self._seal = _VERIFICATION_SEAL
        self._payload_hash = digest(payload)
        self._result_hash = digest(value)


def is_current_verification(payload, value):
    """校验消费者交接的原对象和内容绑定，不认证来源身份或专业命题。"""
    return (type(value) is _VerifiedReports
            and value._seal is _VERIFICATION_SEAL
            and value._payload_hash == digest(payload)
            and value._result_hash == digest(dict(value)))


def binding_target(payload, kind, identity):
    """来源绑定的局部依赖；不引入第二份版本台账。

    clause绑定条款；comment/comment_reason绑定原意见和对应理由；
    verification绑定一行验证及其条款；compilation_note绑定一个说明节。
    适用version统一指本次payload.version，而非原意见的收件版次。
    """
    if kind == "clause":
        records = [r for r in payload.get("clauses", []) if r.get("id") == identity]
    elif kind in {"comment", "comment_reason"}:
        comments = [r for r in payload.get("comments", []) if r.get("id") == identity]
        outcomes = [r for r in payload.get("comment_outcomes", [])
                    if r.get("comment_id") == identity]
        return ({"comment": comments[0], "outcomes": outcomes}
                if len(comments) == 1 else None)
    elif kind in {"verification", "verification_basis"}:
        records = [r for r in payload.get("verification_matrix", []) if r.get("id") == identity]
        if len(records) == 1:
            row = records[0]
            return {"verification": row, "clauses": [r for r in payload.get("clauses", [])
                                                      if r.get("id") == row.get("clause_id")]}
        return None
    elif kind in {"compilation_note", "note_section"}:
        records = [r for r in payload.get("compilation_note", {}).get("sections", [])
                   if r.get("id") == identity]
    elif kind == "external_reference":
        records = [r for r in payload.get("external_references", []) if r.get("id") == identity]
    else:
        return None
    return copy.deepcopy(records[0]) if len(records) == 1 else None


def _source_issue(issues, code, record_id, **details):
    issues.append({"code": code, "record_id": record_id, **details})


def _report_rows(value, key, fields):
    rows = value.get(key, [])
    require(isinstance(rows, list) and len(rows) <= MAX_RECORDS, "source_records_required:" + key)
    seen = set()
    for row in rows:
        require_fields(row, fields)
        for field in fields:
            if field not in {"source", "citation_ids"}:
                _text(row[field], "source_record_text_required:" + field)
        identity = row[fields[0]]
        require(identity not in seen, "source_record_id_duplicated:" + key)
        seen.add(identity)
    return rows


def _reopen_report(root, descriptor, payload, *, synthetic, admission):
    """重读报告与原件；所有verified/coverage字段都由实际字节重新计算。"""
    raw = read_bound(root, descriptor["path"], descriptor["sha256"],
                     synthetic=synthetic, admission=admission, payload=payload)
    report = strict_json_loads(raw.decode("utf-8-sig"))
    require_fields(report, ("tool", "identity", "path", "original_sha256",
                            "pages", "citations", "extraction", "extracted_text_sha256"))
    require(report["tool"] == "tools.standard_sources", "source_report_tool_unsupported")
    require(isinstance(report["extraction"], dict), "source_extraction_object_required")
    identity = _identity(report["identity"])
    source = descriptor["source"]
    # source可为项目内来源ID；提供身份对象时必须精确匹配，不升级版次。
    if isinstance(source, dict):
        require(_identity(source) == identity, "source_identity_mismatch")
    else:
        _text(source, "source_identity_required")
    require(report.get("access_status") in {"local_authorized", "read_only", "downloadable", "restricted"},
            "fulltext_access_not_proven")
    original = read_bound(root, report["path"], report["original_sha256"],
                         synthetic=synthetic, admission=admission, payload=payload)
    suffix = Path(report["path"]).suffix.lower()
    reported_pages = report["pages"]
    if suffix == ".txt":
        try:
            text = original.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ContractError("text_encoding_invalid") from exc
        pages = _pages([{"page": index, "text": text}
                        for index, text in enumerate(text.split("\f"), 1)])
        require(bool(text.strip()), "text_unreadable")
        unreadable = [r["page"] for r in pages if not r["text"].strip()]
        extraction = {"tool": "utf8_formfeed", "total_pages": len(pages),
            "page_count_status": "verified", "coverage": "partial" if unreadable else "complete",
            "page_count_basis": "text_formfeed_segments_not_pdf_or_printed_pages",
            "text_fidelity": "byte_decoded", "missing_or_unreadable_pages": unreadable}
    elif suffix == ".pdf":
        require(original.startswith(b"%PDF-"), "pdf_signature_invalid")
        tools = report["extraction"].get("tools")
        if tools:
            def authorize():
                authorize_io(root, synthetic=synthetic, admission=admission, payload=payload,
                    inputs={report["path"]: report["original_sha256"]},
                    actions=("local_process", "copy", "subprocess"))
            pages, extraction = _extract_pdf(original, tools, authorize=authorize)
        else:
            pages = _pages(reported_pages) if reported_pages else []
            extraction = {"tool": "caller_transcription" if pages else "none", "total_pages": None,
                "page_count_status": "not_verified", "coverage": "partial" if pages else "unreadable",
                "page_count_basis": "tool_not_executed", "text_fidelity": "not_verified",
                "missing_or_unreadable_pages": []}
    else:
        raise ContractError("source_format_unsupported")
    require(reported_pages == pages, "source_report_text_changed")
    text_hash = sha256_bytes(canonical_bytes(pages))
    require(report["extracted_text_sha256"] == text_hash, "source_report_text_hash_changed")
    rows = []
    require(isinstance(report["citations"], list) and len(report["citations"]) <= MAX_RECORDS,
            "citations_list_required")
    for citation in report["citations"]:
        require(isinstance(citation, dict), "citation_object_required")
        fields = ("id", "proposition", "relation")
        row = {key: citation[key] for key in fields if key in citation}
        if "segments" in citation:
            require(isinstance(citation["segments"], list), "citation_segments_required")
            row["segments"] = [{key: part[key] for key in ("page", "start", "end", "quote") if key in part}
                               for part in citation["segments"]]
        else:
            row.update({key: citation[key] for key in ("page", "start", "end", "quote") if key in citation})
        rows.append(row)
    citations = _citations(rows, pages, extraction=extraction,
                          original_sha256=sha256_bytes(original), extracted_text_sha256=text_hash)
    return {"report_sha256": sha256_bytes(raw), "original_sha256": sha256_bytes(original),
        "original_path": report["path"], "original_bytes": len(original), "identity": identity,
        "extracted_text_sha256": text_hash, "extraction": extraction, "citations": citations,
        "page_text_binding": "verified" if extraction["tool"] != "caller_transcription" and pages else "not_verified"}


def verify_reports(root, payload, *, synthetic=False, admission=None):
    """消费source_reports/source_bindings的当前文件，返回issues与source_trace。

    source_reports最小字段为report_id/path/sha256/source（来源ID或完整identity）；
    原件路径与hash从import_local报告取得，真实模式须同时在admission.inputs中。
    source_bindings为binding_id/target_type/target_id/report_id/citation_ids/proposition/version；
    可选reviewed_dependency_hash仅用于局部失效，不充当已审结论。结果对象可直接
    交给standard_review.assess(source_verification=...)；序列化后须重新核实际文件。
    """
    require(isinstance(payload, dict), "source_payload_object_required")
    authorize_io(root, synthetic=synthetic, admission=admission, payload=payload)
    reports = _report_rows(payload, "source_reports", ("report_id", "path", "sha256", "source"))
    bindings = _report_rows(payload, "source_bindings", ("binding_id", "target_type", "target_id",
                                "report_id", "citation_ids", "proposition", "version"))
    issues, actual, errors = [], {}, {}
    declared = {row["report_id"]: row for row in reports}
    for row in reports:
        rid = row["report_id"]
        try:
            actual[rid] = _reopen_report(root, row, payload, synthetic=synthetic, admission=admission)
        except (ContractError, OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            code = str(exc) if isinstance(exc, ContractError) else "source_report_unreadable"
            errors[rid] = code
            _source_issue(issues, code, rid, report_id=rid)
    trace = []
    for binding in bindings:
        bid, rid = binding["binding_id"], binding["report_id"]
        ids = binding["citation_ids"]
        require(isinstance(ids, list) and 0 < len(ids) <= MAX_RECORDS
                and all(isinstance(cid, str) and cid.strip() for cid in ids)
                and len(ids) == len(set(ids)), "source_citation_ids_required")
        target = binding_target(payload, binding["target_type"], binding["target_id"])
        problems = []
        if target is None:
            problems.append("source_target_missing_or_ambiguous")
        if binding["version"] != payload.get("version"):
            problems.append("source_target_version_mismatch")
        evidence = actual.get(rid)
        if evidence is None:
            problems.append(errors.get(rid, "source_report_missing"))
            citations, extraction = [], {}
        else:
            by_id = {row["id"]: row for row in evidence["citations"]}
            missing = [cid for cid in ids if cid not in by_id]
            if missing:
                problems.append("source_citation_missing")
            citations = [copy.deepcopy(by_id[cid]) for cid in ids if cid in by_id]
            extraction = evidence["extraction"]
            if evidence["page_text_binding"] != "verified":
                problems.append("source_original_text_not_verified")
            if extraction["coverage"] != "complete":
                problems.append("source_extraction_coverage_partial")
            if any(row["coverage"] != "complete" for row in citations):
                problems.append("source_citation_coverage_partial")
        local = {key: value for key, value in binding.items()
                 if key not in {"reviewed_dependency_hash", "verified", "status", "passed"}}
        dependency = digest({"binding": local, "target": target,
            "report": declared.get(rid), "actual": evidence, "problems": problems})
        reviewed = binding.get("reviewed_dependency_hash")
        if reviewed is not None:
            _hash(reviewed)
        review_status = "not_reviewed" if reviewed is None else "current" if reviewed == dependency else "stale"
        if review_status == "stale":
            problems.append("source_binding_review_stale")
        for code in dict.fromkeys(problems):
            if code != errors.get(rid):
                _source_issue(issues, code, bid, binding_id=bid, target_type=binding["target_type"],
                              target_id=binding["target_id"], report_id=rid)
        complete = bool(evidence and citations and len(citations) == len(ids)
                        and extraction.get("coverage") == "complete"
                        and all(c["coverage"] == "complete" for c in citations))
        trace.append({"binding_id": bid, "target_type": binding["target_type"],
            "target_id": binding["target_id"], "report_id": rid, "citation_ids": list(ids),
            "proposition": binding["proposition"], "proposition_sha256": sha256_bytes(binding["proposition"].encode("utf-8")),
            "version": binding["version"], "target_hash": digest(target) if target is not None else None,
            "report_path": declared.get(rid, {}).get("path"),
            "report_sha256": evidence["report_sha256"] if evidence else None,
            "expected_report_sha256": declared.get(rid, {}).get("sha256"),
            "original_sha256": evidence["original_sha256"] if evidence else None,
            "original_path": evidence["original_path"] if evidence else None,
            "extracted_text_sha256": evidence["extracted_text_sha256"] if evidence else None,
            "identity": evidence["identity"] if evidence else None,
            "citations": citations, "coverage": "complete" if complete else "partial",
            "page_count_status": extraction.get("page_count_status", "not_verified"),
            "total_pages": extraction.get("total_pages"),
            "page_count_basis": extraction.get("page_count_basis", "not_verified"),
            "source_coverage": extraction.get("coverage", "unreadable"),
            "literal_binding": "verified" if citations else "not_verified",
            "state": "verified" if not problems else "needs_evidence",
            "proposition_support": "not_verified", "semantic_completeness": "not_verified",
            "full_text_absence_allowed": False, "review_status": review_status,
            "dependency_hash": dependency,
            "permission_status": "synthetic" if synthetic else "checked_at_each_read" if evidence else "not_verified",
            "identity_authenticity": "not_verified", "professional_review": "not_performed"})
    result = {"tool": "tools.standard_sources.verify_reports", "tool_version": VERSION,
        "status": "needs_evidence" if issues else "needs_review" if trace else "no_sources",
        "issues": issues, "source_trace": trace, "input_hash": digest(payload),
        "reports_checked": len(actual), "reports_declared": len(reports),
        "network": "not_performed", "professional_review": "not_performed"}
    return _VerifiedReports(result, payload)


def classify_acquisition(*, configured=False, raw=None, request=None,
                         adapter="samr_gb_query_v1", transport_status=None,
                         preview_only=False, login_required=False, captcha_required=False):
    """纯离线响应分类；不会获取网络、拼接下载地址或执行认证绕过。"""
    require(type(configured) is bool, "configured_boolean_required")
    state, result = "not_configured", None
    if configured:
        if preview_only or login_required or captcha_required:
            state = "access_denied"
        elif transport_status == "timeout":
            state = "timeout"
        elif (request or {}).get("http_status") in {401, 403}:
            state = "access_denied"
        elif isinstance(raw, bytes) and isinstance(request, dict):
            try:
                result = parse_catalog(raw, adapter=adapter, request=request, synthetic=True)
                state = {"zero_results": "zero_hits", "results": "available",
                         "pagination_incomplete": "partial", "access_denied": "access_denied",
                         "network_failed": "partial"}.get(result["state"], "page_changed")
            except (ContractError, TypeError, ValueError):
                state = "page_changed"
        else:
            state = "partial"
    return {"status": state, "network": "not_performed", "download": "not_performed",
        "scope": "offline_supplied_response_only", "snapshot_sha256": sha256_bytes(raw) if isinstance(raw, bytes) else None,
        "result_count": result.get("result_count") if result else None,
        "pagination_complete": result.get("pagination_complete", False) if result else False,
        "fetch_stopped": state in {"not_configured", "timeout", "access_denied", "page_changed"},
        "official_status": "not_asserted"}


def load_cli_request(args):
    """授权文件只含范围/许可元数据；材料请求仍须先预检、按授权hash读取。"""
    require(args.synthetic or args.authorization, "mode_required")
    require(not (args.synthetic and args.authorization), "mode_ambiguous")
    admission = None
    if args.authorization:
        path = scoped_path(args.root, args.authorization)
        with path.open("rb") as stream:
            raw = stream.read(MAX_REQUEST_BYTES + 1)
        require(len(raw) <= MAX_REQUEST_BYTES, "authorization_size_limit")
        admission = strict_json_loads(raw.decode("utf-8"))
        authorize_io(args.root, admission=admission)
        expected = admission["inputs"].get(args.request)
        raw = read_bound(args.root, args.request, expected, admission=admission,
                         limit=MAX_REQUEST_BYTES)
    else:
        path = scoped_path(args.root, args.request)
        with path.open("rb") as stream:
            raw = stream.read(MAX_REQUEST_BYTES + 1)
        require(len(raw) <= MAX_REQUEST_BYTES, "request_size_limit")
    payload = strict_json_loads(raw.decode("utf-8"))
    require(isinstance(payload, dict), "request_object_required")
    authorize_io(args.root, synthetic=args.synthetic, admission=admission, payload=payload)
    return payload, admission


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--operation", choices=("import", "catalog"), default="import")
    parser.add_argument("--input", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--authorization", help="根内授权JSON；并非身份认证")
    args = parser.parse_args(argv)
    try:
        payload, admission = load_cli_request(args)
        require(Path(args.output).suffix.lower() == ".json", "report_json_required")
        new_output_path(args.root, args.output, synthetic=args.synthetic,
                        admission=admission, payload=payload)
        if args.operation == "catalog":
            require_fields(payload, ("expected_sha256", "adapter"))
            raw = read_bound(args.root, args.input, payload["expected_sha256"],
                synthetic=args.synthetic, admission=admission, payload=payload,
                limit=MAX_REQUEST_BYTES)
            report = parse_catalog(raw, adapter=payload["adapter"], synthetic=args.synthetic,
                                   request=payload.get("request"))
            report.update(input=args.input, authorization_binding=digest(admission) if admission else None,
                authorization_authenticity="caller_responsibility_not_authenticated",
                authorization_binding_scope="change_detection_not_signature_or_trusted_anchor")
        else:
            report = import_local(args.root, args.input, payload, synthetic=args.synthetic,
                                  admission=admission)
        output_hash = write_report(args.root, args.output, report, synthetic=args.synthetic,
                                    admission=admission, payload=payload)
        print(json.dumps({"status": report.get("status", report.get("state")),
            "output": args.output, "sha256": output_hash,
            "coverage": report.get("extraction", {}).get("coverage"),
            "pagination_complete": report.get("pagination_complete")}))
        return 0
    except (ContractError, OSError, UnicodeError, TypeError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ContractError) else "input_or_io_error"
        print(json.dumps({"status": "error", "error": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
