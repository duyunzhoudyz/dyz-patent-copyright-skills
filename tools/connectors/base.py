"""Phase C1: 可选外部只读数据源连接器的统一契约、默认离线门禁、防重定向 SSRF 与双预算硬限。

严格约束：
1. 默认完全离线（opt_in_network=False）；未显式开启并给出权限依据时，任何请求直接拒绝；
2. 只允许 HTTPS、标准 443 端口、显式域名白名单，严禁空/非空 URL 凭据与环境代理劫持；
3. 严禁自动跟随 HTTP 重定向（防止白名单主机 302 跳转至内网或外部域名并泄露 API Key/Bearer Token）；
4. 实行按查询与按案双重请求数/字节数/估算费用硬上限，且失败或超限响应同样计入已耗配额，防负成本退款；
5. 所有外联返回结果必须带来源、时间戳、原始字节哈希、覆盖状态与停止原因，不冒充完整检索或专业结论。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
import http.client
import ipaddress
import math
import re
import socket
import ssl
import sys
from threading import Lock
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import (
    HTTPDefaultErrorHandler, HTTPErrorProcessor, HTTPRedirectHandler, HTTPSHandler,
    OpenerDirector, ProxyHandler, Request,
)

from tools.core import ContractError, digest, require, sha256_bytes

STOP_REASONS = frozenset({
    "complete",
    "partial",
    "zero_hits",
    "http_error",
    "not_configured",
    "budget_exceeded",
    "rate_limited",
    "access_denied_or_challenge",
    "page_changed",
    "auth_missing",
    "network_disabled",
    "redirect_blocked",
    "imported_snapshot",
    "dry_run",
})


def _is_nonneg_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_pos_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _is_nonneg_finite(value: Any) -> bool:
    return (type(value) is int and 0 <= value <= sys.float_info.max
            or type(value) is float and value >= 0 and math.isfinite(value))


@dataclass(frozen=True)
class DisclosureApproval:
    """审批绑定原始请求路径、查询参数和非凭据请求头。"""
    host: str
    purpose: str
    request_target: str = field(repr=False)
    expires_at: str
    estimated_cost_usd: float
    request_headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    normalized_query_sha256: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        require(isinstance(self.request_headers, tuple)
                and all(isinstance(pair, tuple) and len(pair) == 2 for pair in self.request_headers),
                "connector_header_invalid")
        headers = _clean_request_headers(self.request_headers)
        scope_headers = tuple(sorted((name.lower(), value) for name, value in headers.items()))
        require(all(name not in _CREDENTIAL_HEADERS for name, _ in scope_headers), "connector_header_invalid")
        require(isinstance(self.request_target, str) and self.request_target.startswith("/"),
                "connector_disclosure_not_bound")
        object.__setattr__(self, "request_headers", scope_headers)
        object.__setattr__(self, "normalized_query_sha256", _request_scope_sha256(self.request_target, scope_headers))


MAX_CASE_BYTES = 10_000_000
MAX_CASE_COST_USD = 100


@dataclass(frozen=True)
class ConnectorPolicy:
    """只读外联策略配置；默认离线。"""
    opt_in_network: bool = False
    allowed_hosts: tuple[str, ...] = ()
    max_requests_per_query: int = 5
    max_requests_per_case: int = 30
    max_bytes_per_query: int = 2_000_000
    max_bytes_per_case: int = 10_000_000
    max_estimated_cost_usd_per_case: float = 0.0
    timeout_seconds: float = 15.0
    authority_evidence: DisclosureApproval | tuple[DisclosureApproval, ...] | str = ""
    dry_run: bool = False

    def __post_init__(self) -> None:
        require(type(self.opt_in_network) is bool, "connector_policy_invalid")
        require(type(self.dry_run) is bool, "connector_policy_invalid")
        require(
            isinstance(self.allowed_hosts, (tuple, frozenset, set, list))
            and all(isinstance(h, str) and h.strip() for h in self.allowed_hosts),
            "connector_policy_invalid",
        )
        object.__setattr__(self, "allowed_hosts", tuple(sorted({h.strip().lower().removesuffix(".") for h in self.allowed_hosts})))
        if isinstance(self.authority_evidence, DisclosureApproval):
            object.__setattr__(self, "authority_evidence", (self.authority_evidence,))
        if isinstance(self.authority_evidence, tuple):
            require(all(type(a) is DisclosureApproval for a in self.authority_evidence), "connector_policy_invalid")
        require(_is_pos_int(self.max_requests_per_query) and _is_pos_int(self.max_requests_per_case)
                and self.max_requests_per_query <= self.max_requests_per_case, "connector_policy_invalid")
        require(_is_pos_int(self.max_bytes_per_query) and _is_pos_int(self.max_bytes_per_case)
                and self.max_bytes_per_query <= self.max_bytes_per_case <= MAX_CASE_BYTES, "connector_policy_invalid")
        require(_is_nonneg_finite(self.max_estimated_cost_usd_per_case)
                and self.max_estimated_cost_usd_per_case <= MAX_CASE_COST_USD, "connector_policy_invalid")
        require(_is_nonneg_finite(self.timeout_seconds) and 0 < self.timeout_seconds <= 120,
                "connector_policy_invalid")


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str


@dataclass(eq=False, frozen=True)
class BudgetTracker:
    """Atomically reserve per-query and per-case capacity before sending."""
    policy: ConnectorPolicy
    case_requests: int = 0
    case_bytes: int = 0
    case_estimated_cost_usd: float = 0.0
    query_requests: int = 0
    query_bytes: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    _lock: Any = field(default_factory=Lock, init=False, repr=False, compare=False)
    _queries: dict[tuple, list[int]] = field(default_factory=dict, init=False, repr=False)
    _last_query: tuple | None = field(default=None, init=False, repr=False)
    _cost: Fraction = field(init=False, repr=False)
    _cost_limit: Fraction = field(init=False, repr=False)

    def __post_init__(self) -> None:
        require(all(_is_nonneg_int(n) for n in (self.case_requests, self.case_bytes,
                                                 self.query_requests, self.query_bytes))
                and self.query_requests <= self.case_requests and self.query_bytes <= self.case_bytes,
                "connector_budget_argument_invalid")
        require(_is_nonneg_finite(self.case_estimated_cost_usd), "connector_budget_cost_invalid")
        object.__setattr__(self, "_cost", Fraction(str(self.case_estimated_cost_usd)))
        object.__setattr__(self, "_cost_limit", Fraction(str(self.policy.max_estimated_cost_usd_per_case)))

    def _reserve(self, query_key: tuple, estimated_cost: Fraction) -> tuple[int, list[int]]:
        with self._lock:
            previous = (self.query_requests, self.query_bytes) if self._last_query is None else (0, 0)
            query = self._queries.get(query_key)
            if query is None:
                query = list(previous)
            if query[0] >= self.policy.max_requests_per_query:
                raise ContractError("connector_query_request_budget_exceeded")
            if self.case_requests >= self.policy.max_requests_per_case:
                raise ContractError("connector_case_request_budget_exceeded")
            if query[1] >= self.policy.max_bytes_per_query:
                raise ContractError("connector_query_byte_budget_exceeded")
            if self.case_bytes >= self.policy.max_bytes_per_case:
                raise ContractError("connector_case_byte_budget_exceeded")
            total_cost = self._cost + estimated_cost
            if total_cost > self._cost_limit:
                raise ContractError("connector_case_cost_budget_exceeded")
            reserved = min(self.policy.max_bytes_per_query - query[1],
                           self.policy.max_bytes_per_case - self.case_bytes)
            object.__setattr__(self, "case_requests", self.case_requests + 1)
            object.__setattr__(self, "case_bytes", self.case_bytes + reserved)
            object.__setattr__(self, "_cost", total_cost)
            object.__setattr__(self, "case_estimated_cost_usd", float(total_cost))
            query[0] += 1
            query[1] += reserved
            self._queries[query_key] = query
            object.__setattr__(self, "_last_query", query_key)
            object.__setattr__(self, "query_requests", query[0])
            object.__setattr__(self, "query_bytes", query[1])
            return reserved, query

    def _settle(self, query: list[int], reserved: int, received: int | None,
                estimated_cost: Fraction, status: str) -> None:
        with self._lock:
            # A failed or truncated read can have consumed its entire reservation.
            charged = reserved if received is None else min(received, reserved)
            object.__setattr__(self, "case_bytes", self.case_bytes - (reserved - charged))
            query[1] -= reserved - charged
            object.__setattr__(self, "query_bytes", self._queries[self._last_query][1])
            self.history.append({"bytes": charged, "received_bytes": received,
                                 "estimated_cost_usd": float(estimated_cost), "status": status})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "case_requests": self.case_requests,
                "case_bytes": self.case_bytes,
                "query_requests": self.query_requests,
                "query_bytes": self.query_bytes,
                "case_estimated_cost_usd": self.case_estimated_cost_usd,
                "max_requests_per_query": self.policy.max_requests_per_query,
                "max_requests_per_case": self.policy.max_requests_per_case,
                "max_bytes_per_query": self.policy.max_bytes_per_query,
                "max_bytes_per_case": self.policy.max_bytes_per_case,
                "max_estimated_cost_usd_per_case": self.policy.max_estimated_cost_usd_per_case,
            }


_DNS_HOST_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_TLD_RE = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_NAT64_NETWORKS = tuple(map(ipaddress.IPv6Network, ("64:ff9b::/96", "64:ff9b:1::/48")))
_HEADER_NAME = re.compile(r"[A-Za-z0-9-]+")
_RESERVED_HEADERS = frozenset({"host", "proxy-authorization", "proxy-connection", "content-length",
                               "transfer-encoding", "connection", "upgrade", "te", "trailer", "expect"})


def _require_public_ip(ip_text: str) -> None:
    """严格拦截环回/内网/链路本地/云元数据/映射 IPv6 等非公网地址（含 DNS 绑定校验）。"""
    require(isinstance(ip_text, str) and "%" not in ip_text, "connector_host_not_allowed")
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError as exc:
        raise ContractError("connector_host_not_allowed") from exc
    candidates = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        require(not any(ip in network for network in _NAT64_NETWORKS), "connector_host_not_allowed")
        if ip.ipv4_mapped is not None:
            candidates.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            candidates.append(ip.sixtofour)
        if ip.teredo is not None:
            candidates.extend(ip.teredo)
    for addr in candidates:
        require(
            addr.is_global
            and not addr.is_private
            and not addr.is_loopback
            and not addr.is_link_local
            and not addr.is_multicast
            and not addr.is_reserved
            and not addr.is_unspecified,
            "connector_host_not_allowed",
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """在连接前解析 DNS、核验全部解析 IP 均为公网地址并直接连接已校验 IP，同时保留 TLS SNI 校验。"""
    def connect(self):
        target_port = self.port or 443
        try:
            infos = socket.getaddrinfo(self.host, target_port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ContractError("connector_network_error") from exc
        if not infos:
            raise ContractError("connector_network_error")
        pinned = []
        for family, socktype, proto, _canon, sockaddr in infos:
            _require_public_ip(sockaddr[0])
            pinned.append((family, socktype, proto, sockaddr))
        raw_sock = None
        last_exc = None
        for family, socktype, proto, sockaddr in pinned:
            sock = None
            try:
                sock = socket.socket(family, socktype, proto)
                if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(self.timeout)
                sock.connect(sockaddr)
                raw_sock = sock
                break
            except OSError as exc:
                last_exc = exc
                if sock is not None:
                    sock.close()
        if raw_sock is None:
            raise ContractError("connector_network_error") from last_exc
        try:
            self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)
        except BaseException:
            raw_sock.close()
            raise


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self):
        super().__init__(context=ssl.create_default_context())

    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


class _NoRedirectHandler(HTTPRedirectHandler):
    """严格禁止自动跟随任何 HTTP 重定向，防跨源 SSRF 与凭据头外泄。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ContractError("connector_redirect_blocked")


def _read_response_body(response, max_bytes: int) -> bytes:
    body = response.read(max_bytes)
    # At the exact ceiling, urllib must know the response ended without a lookahead byte.
    if len(body) == max_bytes and getattr(response, "length", None) != 0:
        raise ContractError("connector_response_byte_limit_exceeded")
    return body


def _response_headers(items) -> dict[str, str]:
    headers = {}
    for name, value in items:
        name = name.lower()
        if name == "content-length":
            require(name not in headers and isinstance(value, str)
                    and re.fullmatch(r"[0-9]+", value.strip(" \t")) is not None,
                    "connector_response_content_length_invalid")
        require(headers.setdefault(name, value) == value, "connector_response_header_conflict")
    return headers


def _default_transport(url: str, headers: dict[str, str], timeout: float, max_bytes: int) -> HttpResponse:
    req = Request(url, headers=headers, method="GET")
    opener = OpenerDirector()
    for handler in (_PinnedHTTPSHandler(), _NoRedirectHandler(), ProxyHandler({}),
                    HTTPDefaultErrorHandler(), HTTPErrorProcessor()):
        opener.add_handler(handler)
    try:
        with opener.open(req, timeout=timeout) as resp:
            hdrs = _response_headers(resp.headers.items())
            body = _read_response_body(resp, max_bytes)
            return HttpResponse(status=resp.status, headers=hdrs, body=body, url=resp.geturl())
    except ContractError:
        raise
    except HTTPError as exc:
        try:
            hdrs = _response_headers(exc.headers.items() if exc.headers else ())
            body = _read_response_body(exc.fp, max_bytes) if exc.fp else b""
            return HttpResponse(status=exc.code, headers=hdrs, body=body, url=url)
        finally:
            exc.close()
    except (URLError, TimeoutError, http.client.HTTPException, ssl.SSLError, OSError) as exc:
        raise ContractError("connector_network_error") from exc


def _validate_https_url(url: str, allowed_hosts: tuple[str, ...]):
    require(isinstance(url, str) and bool(url.strip()), "connector_https_origin_required")
    require(not any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url),
            "connector_https_origin_required")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ContractError("connector_https_origin_required") from exc
    require(
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and "@" not in parsed.netloc
        and not parsed.username
        and not parsed.password
        and "#" not in url
        and port in (None, 443),
        "connector_https_origin_required",
    )
    raw_host = parsed.hostname.lower()
    host = raw_host[:-1] if raw_host.endswith(".") else raw_host
    # 拒绝所有 IP 字面量（IPv4/十六进制 IP/IPv6/映射 IPv6）、多尾点、本地域名与非法顶级域，防止 SSRF
    require(
        bool(host)
        and not host.endswith(".")
        and host != "localhost"
        and not host.endswith((".localhost", ".local", ".internal"))
        and _DNS_HOST_RE.fullmatch(host) is not None
        and _TLD_RE.fullmatch(host.rsplit(".", 1)[-1]) is not None,
        "connector_host_not_allowed",
    )
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        raise ContractError("connector_host_not_allowed")
    except ValueError:
        pass
    require(host in allowed_hosts, "connector_host_not_allowed")
    return host, parsed


_CREDENTIAL_HEADERS = frozenset({"authorization", "x-api-key"})


def _clean_request_headers(items):
    clean = {}
    names = set()
    for name, value in items:
        require(isinstance(name, str) and isinstance(value, str) and _HEADER_NAME.fullmatch(name) is not None
                and name.lower() not in _RESERVED_HEADERS and name.lower() not in names
                and not any((ord(ch) < 32 and ch != "\t") or ord(ch) >= 127 for ch in value),
                "connector_header_invalid")
        names.add(name.lower())
        clean[name] = value
    return clean


def _request_scope_sha256(target: str, headers: tuple) -> str:
    # 同时保留线上编码和解码参数，避免把远端可能不同解释的目标合为同一审批。
    path, _, query = target.partition("?")
    parameters = sorted(parse_qsl(query, keep_blank_values=True))
    scope_headers = sorted((name.lower(), value) for name, value in headers)
    return digest({"target": target, "path": path, "parameters": parameters, "headers": scope_headers})


def _approved_cost(policy: ConnectorPolicy, host: str, target: str, purpose: str, headers: tuple) -> Fraction:
    scope_sha256 = _request_scope_sha256(target, headers)
    require(isinstance(policy.authority_evidence, tuple), "connector_authority_evidence_required")
    matches = [a for a in policy.authority_evidence
               if a.host == host and a.purpose == purpose and a.normalized_query_sha256 == scope_sha256]
    require(len(matches) == 1, "connector_disclosure_not_bound")
    approval = matches[0]
    try:
        expires = datetime.fromisoformat(approval.expires_at)
    except (TypeError, ValueError):
        raise ContractError("connector_disclosure_expiry_invalid") from None
    require(expires.tzinfo is not None and expires > datetime.now(timezone.utc), "connector_disclosure_expired")
    require(_is_nonneg_finite(approval.estimated_cost_usd), "connector_budget_cost_invalid")
    return Fraction(str(approval.estimated_cost_usd))


_PAGINATION_KEYS = {"uspto_odp_v1": {"limit", "offset"}, "samr_gb_query_live": {"pageSize", "pageNumber"}}


def guarded_https_get(
    url: str,
    *,
    policy: ConnectorPolicy,
    budget: BudgetTracker,
    purpose: str = "read_only_query",
    headers: dict[str, str] | None = None,
    estimated_cost_usd: float | None = None,
    transport: Callable[[str, dict[str, str], float, int], HttpResponse] | None = None,
) -> HttpResponse:
    """所有外部只读 HTTP 请求的唯一受控出口。"""
    require(policy.opt_in_network is True, "connector_network_disabled")
    require(budget.policy == policy, "connector_budget_policy_mismatch")
    host, parsed = _validate_https_url(url, policy.allowed_hosts)
    if policy.dry_run:
        return HttpResponse(status=0, headers={}, body=b"", url=url)

    require(isinstance(purpose, str) and bool(purpose.strip()), "connector_disclosure_not_bound")
    target = (parsed.path or "/") + ("?" + parsed.query if "?" in url else "")

    clean_headers = _clean_request_headers((headers or {}).items())
    scope_headers = tuple((name, value) for name, value in clean_headers.items() if name.lower() not in _CREDENTIAL_HEADERS)

    paging = _PAGINATION_KEYS.get(purpose, ())
    parameters = tuple(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in paging))
    cost = _approved_cost(policy, host, target, purpose, scope_headers)
    if estimated_cost_usd is not None:
        require(_is_nonneg_finite(estimated_cost_usd), "connector_budget_cost_invalid")
        cost = max(cost, Fraction(str(estimated_cost_usd)))
    remaining_bytes, query = budget._reserve((host, parsed.path or "/", parameters), cost)
    received = None
    status = "transport_failed"
    fn = transport if transport is not None else _default_transport
    try:
        resp = fn(url, clean_headers, policy.timeout_seconds, remaining_bytes)
        received = len(resp.body)
        if 300 <= resp.status < 400 or resp.url != url:
            status = "redirect_blocked"
            raise ContractError("connector_redirect_blocked")
        if received > remaining_bytes:
            status = "byte_limit_exceeded"
            raise ContractError("connector_response_byte_limit_exceeded")
        if transport is not None:
            resp = HttpResponse(resp.status, _response_headers(resp.headers.items()), resp.body, resp.url)
        content_length = resp.headers.get("content-length")
        if content_length is not None:
            # 字符串比较保留任意长度的十进制表示，避免整数转换上限。
            declared = content_length.strip(" \t").lstrip("0") or "0"
            actual = str(received)
            if declared != actual:
                if (len(declared), declared) > (len(actual), actual):
                    status = "response_truncated"
                    raise ContractError("connector_response_truncated")
                status = "content_length_mismatch"
                raise ContractError("connector_response_content_length_mismatch")
        status = "ok"
        return resp
    finally:
        budget._settle(query, remaining_bytes, received, cost, status)


def evidence_envelope(
    *,
    source_id: str,
    query: str,
    stop_reason: str,
    records: list[dict[str, Any]],
    budget: BudgetTracker | None = None,
    coverage_level: str = "bibliographic_only",
    network_requests: int = 0,
    raw_bytes: bytes = b"",
    raw_body: bytes | None = None,
    gaps: list[str] | None = None,
    attribution: str | None = None,
    retrieved_at: str | None = None,
    http_status: int | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """统一外部来源返回信封，区分零命中、受限、页面变更与完整结果。"""
    require(stop_reason in STOP_REASONS, "connector_stop_reason_invalid")
    payload_bytes = raw_body if raw_body is not None else raw_bytes
    envelope = {
        "schema": "dyz-connector-evidence-v1",
        "source_id": source_id,
        "query": query,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
        "http_status": http_status,
        "coverage_level": coverage_level,
        "stop_reason": stop_reason,
        "network_requests": network_requests,
        "record_count": len(records),
        "records": records,
        "raw_bytes": len(payload_bytes),
        "raw_sha256": sha256_bytes(payload_bytes),
        "gaps": list(gaps or []),
        "budget": budget.snapshot() if budget is not None else None,
        "notes": list(notes or []),
        "exhaustive_search_claimed": False,
        "professional_review": "not_performed",
    }
    if attribution is not None:
        envelope["attribution"] = attribution
    return envelope
