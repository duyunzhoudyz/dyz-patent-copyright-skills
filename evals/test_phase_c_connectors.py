"""Phase C offline tests: opt-in guard, per-query & per-case budget caps, USPTO ODP,
EPO OPS CQL/XML, External MCP Bridge, SAMR live schema/CAPTCHA stops, and ISO catalog reconciliation.
Zero real network requests are made.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import http.client
import io
import json
from threading import Event
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit

from tools.connectors import (
    BudgetTracker, ConnectorPolicy, DisclosureApproval, EpoOpsConnector, ExternalMcpBridge,
    HttpResponse, IsoCatalogBridge, SamrLiveConnector, UsptoOdpConnector, guarded_https_get,
)
from tools.connectors import base
from tools.standard_sources import SAMR_ENDPOINT
from tools.core import ContractError


def approval(url, purpose="read_only_query", *, cost=0, expiry="2099-01-01T00:00:00Z", headers=None):
    parsed = urlsplit(url)
    target = parsed.path + ("?" + parsed.query if parsed.query else "")
    if headers is None:
        headers = {
            "uspto_odp_v1": (("Accept", "application/json"),),
            "samr_gb_query_live": (("Accept", "application/json"),),
            "epo_ops_v32": (("Accept", "application/xml"), ("X-OPS-Range", "1-10")),
        }.get(purpose, ())
    return DisclosureApproval(parsed.hostname, purpose, target, expiry, cost, request_headers=headers)


def samr_approval(query, page=1, size=15):
    url = (f"{SAMR_ENDPOINT}?searchText={quote(query)}&ics=&state=&ISSUE_DATE="
           f"&sortOrder=asc&pageSize={size}&pageNumber={page}")
    return approval(url, "samr_gb_query_live")


class ConnectorBaseAndBudgetTests(unittest.TestCase):
    def test_network_disabled_by_default_and_host_whitelist_enforced(self):
        policy = ConnectorPolicy()
        budget = BudgetTracker(policy)
        with self.assertRaisesRegex(ContractError, "connector_network_disabled"):
            guarded_https_get("https://api.uspto.gov/x", policy=policy, budget=budget)

        opt_in = ConnectorPolicy(
            opt_in_network=True,
            allowed_hosts=frozenset({"api.uspto.gov"}),
            authority_evidence="user-approved-test",
        )
        with self.assertRaisesRegex(ContractError, "connector_host_not_allowed"):
            guarded_https_get("https://evil.invalid/x", policy=opt_in, budget=BudgetTracker(opt_in))
        with self.assertRaisesRegex(ContractError, "connector_https_origin_required"):
            guarded_https_get("http://api.uspto.gov/x", policy=opt_in, budget=BudgetTracker(opt_in))

    def test_per_case_request_and_cost_hard_caps_block_before_sending(self):
        policy = ConnectorPolicy(
            opt_in_network=True,
            allowed_hosts=frozenset({"api.uspto.gov"}),
            max_requests_per_query=2,
            max_requests_per_case=2,
            max_estimated_cost_usd_per_case=0.05,
            authority_evidence=tuple(approval(f"https://api.uspto.gov/{index}") for index in range(1, 4)),
        )
        budget = BudgetTracker(policy)
        sent = 0

        def fake_transport(url, headers, timeout, max_bytes):
            nonlocal sent
            sent += 1
            return HttpResponse(status=200, headers={}, body=b"{}", url=url)

        guarded_https_get("https://api.uspto.gov/1", policy=policy, budget=budget, estimated_cost_usd=0.03, transport=fake_transport)
        # Second call exceeds cost cap (0.03 + 0.03 > 0.05) BEFORE hitting transport!
        with self.assertRaisesRegex(ContractError, "connector_case_cost_budget_exceeded"):
            guarded_https_get("https://api.uspto.gov/2", policy=policy, budget=budget, estimated_cost_usd=0.03, transport=fake_transport)
        self.assertEqual(1, sent)
        # Cost 0.01 succeeds, then 3rd call hits max_requests_per_case=2
        guarded_https_get("https://api.uspto.gov/2", policy=policy, budget=budget, estimated_cost_usd=0.01, transport=fake_transport)
        with self.assertRaisesRegex(ContractError, "connector_case_request_budget_exceeded"):
            guarded_https_get("https://api.uspto.gov/3", policy=policy, budget=budget, estimated_cost_usd=0.0, transport=fake_transport)
        self.assertEqual(2, sent)

    def test_redirect_ssrf_negative_cost_and_oversized_budget_exhaustion_blocked(self):
        policy = ConnectorPolicy(
            opt_in_network=True,
            allowed_hosts=("api.uspto.gov",),
            max_requests_per_query=2,
            max_requests_per_case=2,
            max_bytes_per_query=10,
            max_bytes_per_case=10,
            max_estimated_cost_usd_per_case=0.05,
            authority_evidence=approval("https://api.uspto.gov/x"),
        )
        # Empty userinfo, non-443 port, IP literals, localhost, DEL char, and malformed IPv6 MUST be rejected!
        with self.assertRaisesRegex(ContractError, "connector_https_origin_required"):
            guarded_https_get("https://:@api.uspto.gov/x", policy=policy, budget=BudgetTracker(policy))
        with self.assertRaisesRegex(ContractError, "connector_https_origin_required"):
            guarded_https_get("https://api.uspto.gov:8443/x", policy=policy, budget=BudgetTracker(policy))
        with self.assertRaisesRegex(ContractError, "connector_https_origin_required"):
            guarded_https_get("https://api.uspto.gov/\x7f", policy=policy, budget=BudgetTracker(policy))
        with self.assertRaisesRegex(ContractError, "connector_https_origin_required"):
            guarded_https_get("https://[::1/x", policy=policy, budget=BudgetTracker(policy))
        for ssrf_host, ssrf_url in (
            ("127.0.0.1", "https://127.0.0.1/x"),
            ("169.254.169.254", "https://169.254.169.254/latest/meta-data/"),
            ("::ffff:127.0.0.1", "https://[::ffff:127.0.0.1]/x"),
            ("localhost", "https://localhost/x"),
        ):
            bad_pol = ConnectorPolicy(opt_in_network=True, allowed_hosts=(ssrf_host,), authority_evidence="test")
            with self.subTest(ssrf_url=ssrf_url), self.assertRaisesRegex(ContractError, "connector_host_not_allowed"):
                guarded_https_get(ssrf_url, policy=bad_pol, budget=BudgetTracker(bad_pol))

        # Negative cost refund MUST be rejected
        b_neg = BudgetTracker(policy)
        with self.assertRaisesRegex(ContractError, "connector_budget_cost_invalid"):
            guarded_https_get("https://api.uspto.gov/x", policy=policy, budget=b_neg, estimated_cost_usd=-0.01,
                              transport=lambda u, h, t, m: HttpResponse(200, {}, b"{}", u))

        # 302 redirect or cross-origin final URL MUST be blocked AND still charge request budget!
        b_redir = BudgetTracker(policy)
        with self.assertRaisesRegex(ContractError, "connector_redirect_blocked"):
            guarded_https_get(
                "https://api.uspto.gov/x", policy=policy, budget=b_redir,
                transport=lambda u, h, t, m: HttpResponse(302, {"location": "http://127.0.0.1/"}, b"", u),
            )
        self.assertEqual(1, b_redir.case_requests)

        # Oversized response MUST charge bytes & request budget so repeated retries hit budget cap!
        b_over = BudgetTracker(policy)
        with self.assertRaisesRegex(ContractError, "connector_response_byte_limit_exceeded"):
            guarded_https_get(
                "https://api.uspto.gov/x", policy=policy, budget=b_over,
                transport=lambda u, h, t, m: HttpResponse(200, {}, b"x" * 20, u),
            )
        self.assertEqual(1, b_over.case_requests)
        self.assertEqual(10, b_over.case_bytes)
        self.assertEqual(20, b_over.history[-1]["received_bytes"])
        with self.assertRaisesRegex(ContractError, "connector_query_byte_budget_exceeded"):
            guarded_https_get(
                "https://api.uspto.gov/x", policy=policy, budget=b_over,
                transport=lambda u, h, t, m: HttpResponse(200, {}, b"{}", u),
            )

    def test_binding_expiry_unknown_cost_and_reserved_headers_stop_before_transport(self):
        url = "https://api.uspto.gov/search?q=approved"
        hosts = [" API.USPTO.GOV. "]
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=hosts, authority_evidence=approval(url))
        hosts.append("other.example")
        transport = Mock(side_effect=AssertionError("must not send"))
        for actual_url, evidence, purpose, headers, error in (
            (url, "an unrelated receipt", "read_only_query", {}, "authority_evidence_required"),
            (url + "-other", approval(url), "read_only_query", {}, "disclosure_not_bound"),
            (url, approval(url), "unapproved_purpose", {}, "disclosure_not_bound"),
            ("https://other.example/search?q=approved", approval(url), "read_only_query", {}, "host_not_allowed"),
            (url, approval(url, expiry="2000-01-01T00:00:00Z"), "read_only_query", {}, "disclosure_expired"),
            (url, approval(url, expiry="2099-01-01T00:00:00"), "read_only_query", {}, "disclosure_expired"),
            (url, approval(url, cost=None), "read_only_query", {}, "budget_cost_invalid"),
            (url, approval(url, cost=0.0000000001), "read_only_query", {}, "case_cost_budget_exceeded"),
            *((url, approval(url), "read_only_query", {name: "synthetic"}, "header_invalid")
              for name in ("hOsT", "Content-Length", "Transfer-Encoding", "Proxy-Authorization", "Invalid Name")),
            *((url, approval(url), "read_only_query", {"Authorization": value}, "header_invalid")
              for value in ("ascii\x7f", "latin-1-\xe9", "non-latin-1-标准")),
        ):
            with self.subTest(error=error, headers=headers), self.assertRaisesRegex(ContractError, error):
                chosen = replace(policy, authority_evidence=evidence)
                guarded_https_get(actual_url, policy=chosen, budget=BudgetTracker(chosen), purpose=purpose,
                                  headers=headers, estimated_cost_usd=0, transport=transport)
        for ip in ("64:ff9b::192.0.2.1", "64:ff9b:1::1"):
            with self.assertRaisesRegex(ContractError, "host_not_allowed"):
                base._require_public_ip(ip)
        with self.assertRaisesRegex(ContractError, "budget_policy_mismatch"):
            guarded_https_get(url, policy=policy, budget=BudgetTracker(replace(policy, max_requests_per_case=31)),
                              transport=transport)
        with self.assertRaises(TypeError):
            guarded_https_get(url, policy=policy, budget=BudgetTracker(policy), query_requests=0, query_bytes=0,
                              transport=transport)
        transport.assert_not_called()

    def test_invalid_budgets_and_transport_failure_cannot_refund_reservation(self):
        url = "https://api.uspto.gov/x"
        for limits in ({"max_requests_per_case": 1}, {"max_bytes_per_case": 1},
                       {"max_bytes_per_case": base.MAX_CASE_BYTES + 1}, {"max_estimated_cost_usd_per_case": float("inf")},
                       {"max_estimated_cost_usd_per_case": base.MAX_CASE_COST_USD + 1}):
            with self.subTest(limits=limits), self.assertRaisesRegex(ContractError, "policy_invalid"):
                ConnectorPolicy(**limits)
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=("api.uspto.gov",), authority_evidence=approval(url, cost=0.02),
                                 max_bytes_per_query=7, max_bytes_per_case=12, max_estimated_cost_usd_per_case=0.04)
        for initial in ({"case_bytes": -1}, {"query_requests": -1}, {"case_estimated_cost_usd": float("nan")}):
            with self.subTest(initial=initial), self.assertRaises(ContractError):
                BudgetTracker(policy, **initial)
        ledger = BudgetTracker(policy)
        transport = Mock(side_effect=RuntimeError("synthetic transport failure"))
        with self.assertRaises(RuntimeError):
            guarded_https_get(url, policy=policy, budget=ledger, estimated_cost_usd=0, transport=transport)
        self.assertEqual((1, 7, 0.02), (ledger.case_requests, ledger.case_bytes, ledger.case_estimated_cost_usd))
        with self.assertRaisesRegex(ContractError, "query_byte_budget_exceeded"):
            guarded_https_get(url, policy=policy, budget=ledger, transport=transport)
        transport.assert_called_once()
        with self.assertRaises(FrozenInstanceError):
            ledger.case_requests = 0

    def test_cost_ceiling_counts_even_a_subcent_reservation_after_exact_cap(self):
        first, second = 'https://api.uspto.gov/x?q=one', 'https://api.uspto.gov/x?q=two'
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=('api.uspto.gov',),
                                 max_estimated_cost_usd_per_case=0.01,
                                 authority_evidence=(approval(first, cost=0.01), approval(second, cost=1e-100)))
        ledger = BudgetTracker(policy)
        transport = Mock(side_effect=lambda u, h, t, m: HttpResponse(200, {}, b'{}', u))
        guarded_https_get(first, policy=policy, budget=ledger, transport=transport)
        with self.assertRaisesRegex(ContractError, 'case_cost_budget_exceeded'):
            guarded_https_get(second, policy=policy, budget=ledger, transport=transport)
        transport.assert_called_once()

    def test_parallel_request_byte_and_cost_cap_never_reaches_transport(self):
        urls = [f"https://api.uspto.gov/x?q={i}" for i in range(5)]
        scenarios = (
            ("query_request", True, dict(max_requests_per_query=1, max_requests_per_case=5)),
            ("case_request", False, dict(max_requests_per_query=1, max_requests_per_case=1)),
            ("query_byte", True, dict(max_bytes_per_query=20, max_bytes_per_case=100)),
            ("case_byte", False, dict(max_bytes_per_query=20, max_bytes_per_case=20)),
            ("case_cost", False, dict(max_estimated_cost_usd_per_case=0.01)),
        )
        for dimension, same_query, settings in scenarios:
            with self.subTest(dimension=dimension), ThreadPoolExecutor(max_workers=5) as pool:
                limits = {"max_estimated_cost_usd_per_case": 1, **settings}
                policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=("api.uspto.gov",),
                                         authority_evidence=tuple(approval(url, cost=0.01) for url in urls), **limits)
                budget = BudgetTracker(policy)
                entered, release = Event(), Event()

                def fake_transport(url, headers, timeout, max_bytes):
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError("reservation test did not release transport")
                    return HttpResponse(200, {}, b"x", url)

                transport = Mock(side_effect=fake_transport)

                def request(url):
                    return guarded_https_get(url, policy=policy, budget=budget, transport=transport)

                first = pool.submit(request, urls[0])
                try:
                    self.assertTrue(entered.wait(5))
                    others = [pool.submit(request, urls[0] if same_query else url) for url in urls[1:]]
                    for future in others:
                        with self.assertRaisesRegex(ContractError, f"{dimension}_budget_exceeded"):
                            future.result(timeout=3)
                    transport.assert_called_once()
                finally:
                    release.set()
                self.assertEqual(200, first.result(timeout=5).status)
                self.assertEqual(1, budget.case_bytes)

    def test_approval_binds_exact_path_query_and_custom_headers(self):
        url = "https://api.uspto.gov/search?q=sample&offset=0&limit=10&page=1"
        allowed_headers = (("Range", "items=0-9"), ("X-Page-Offset", "0"))
        receipt = approval(url, headers=allowed_headers)
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=(receipt.host,), authority_evidence=receipt)
        budget = BudgetTracker(policy)
        transport = Mock(side_effect=lambda u, h, t, m: HttpResponse(200, {}, b"{}", u))
        headers = {name.lower(): value for name, value in allowed_headers}
        for changed_url, changed_headers in (
            (url.replace("/search", "/other"), headers), (url.replace("offset=0", "offset=10"), headers),
            (url.replace("limit=10", "limit=20"), headers), (url.replace("page=1", "page=2"), headers),
            (url, {**headers, "range": "items=10-19"}), (url, {**headers, "x-page-offset": "10"}),
            (url, {"range": headers["range"]}), (url, {**headers, "X-Page-Size": "20"}),
        ):
            with self.subTest(url=changed_url, headers=changed_headers), self.assertRaisesRegex(ContractError, "disclosure_not_bound"):
                guarded_https_get(changed_url, policy=policy, budget=budget, headers=changed_headers, transport=transport)
        with self.assertRaisesRegex(ContractError, "header_invalid"):
            guarded_https_get(url, policy=policy, budget=budget, headers={**headers, "Range": "items=10-19"}, transport=transport)
        transport.assert_not_called()
        self.assertEqual(0, budget.case_requests)
        guarded_https_get(url, policy=policy, budget=budget, headers=headers, transport=transport)
        transport.assert_called_once()


    def test_response_headers_reject_case_insensitive_conflicts_and_preserve_identical_values(self):
        url = "https://api.uspto.gov/sample"
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=("api.uspto.gov",), authority_evidence=approval(url))
        for status in (200, 503):
            for second in (b"application/json", b"text/plain"):
                with self.subTest(status=status, second=second), patch.object(base.OpenerDirector, "open") as open_response:
                    headers = http.client.parse_headers(io.BytesIO(
                        b"Content-Type: application/json\r\ncontent-type: " + second + b"\r\n\r\n"))
                    body = io.BytesIO(b"{}")
                    if status == 200:
                        body.headers, body.status, body.geturl = headers, status, lambda: url
                        open_response.return_value = body
                    else:
                        open_response.side_effect = HTTPError(url, status, "synthetic", headers, body)
                    if second == b"application/json":
                        response = guarded_https_get(url, policy=policy, budget=BudgetTracker(policy))
                        self.assertEqual((status, {"content-type": "application/json"}), (response.status, response.headers))
                    else:
                        with self.assertRaisesRegex(ContractError, "connector_response_header_conflict"):
                            guarded_https_get(url, policy=policy, budget=BudgetTracker(policy))
                    self.assertTrue(body.closed)
        with self.assertRaisesRegex(ContractError, "connector_response_header_conflict"):
            guarded_https_get(url, policy=policy, budget=BudgetTracker(policy), transport=lambda u, h, t, m:
                              HttpResponse(200, {"Content-Type": "application/json", "content-type": "text/plain"}, b"{}", u))

    def test_content_length_rejects_short_http_bodies_even_when_payload_is_valid_json(self):
        url = 'https://api.uspto.gov/sample'
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=('api.uspto.gov',), authority_evidence=approval(url))
        for status, declared in ((200, '0003'), (503, '3'), (200, '9' * 5000)):
            with self.subTest(status=status, digits=len(declared)), patch.object(base.OpenerDirector, 'open') as opener:
                body = io.BytesIO(b'{}')
                headers = http.client.parse_headers(io.BytesIO(f'Content-Length: {declared}\r\n\r\n'.encode('ascii')))
                if status == 200:
                    body.headers, body.status, body.geturl = headers, status, lambda: url
                    opener.return_value = body
                else:
                    opener.side_effect = HTTPError(url, status, 'synthetic', headers, body)
                budget = BudgetTracker(policy)
                with self.assertRaisesRegex(ContractError, 'connector_response_truncated'):
                    guarded_https_get(url, policy=policy, budget=budget)
                self.assertEqual(2, budget.case_bytes)
                self.assertTrue(body.closed)
        for length in ('2', '0002'):
            transport = lambda u, h, t, m: HttpResponse(200, {'CoNtEnT-LeNgTh': length}, b'{}', u)
            self.assertEqual(b'{}', guarded_https_get(url, policy=policy, budget=BudgetTracker(policy), transport=transport).body)
        with self.assertRaisesRegex(ContractError, 'connector_response_truncated'):
            guarded_https_get(url, policy=policy, budget=BudgetTracker(policy), transport=lambda u, h, t, m:
                              HttpResponse(200, {'Content-Length': '5'}, b'{}', u))
        with self.assertRaisesRegex(ContractError, 'connector_response_content_length_mismatch'):
            guarded_https_get(url, policy=policy, budget=BudgetTracker(policy), transport=lambda u, h, t, m:
                              HttpResponse(200, {'Content-Length': '1'}, b'{}', u))

    def test_content_length_rejects_duplicate_combined_and_invalid_raw_values(self):
        url = 'https://api.uspto.gov/sample'
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=('api.uspto.gov',), authority_evidence=approval(url))
        invalid_values = ('10, 5', '5, 10', '5, 5', 'invalid', '-5', '+5', '')
        invalid_headers = [f'Content-Length: {value}\r\n' for value in invalid_values]
        invalid_headers.extend((
            'Content-Length: 5\r\nContent-Length: 10\r\n',
            'Content-Length: 10\r\nContent-Length: 5\r\n',
            'Content-Length: 5\r\ncontent-length: 5\r\n',
        ))
        for status in (200, 404):
            for raw in invalid_headers:
                with self.subTest(status=status, raw=raw), patch.object(base.OpenerDirector, 'open') as opener:
                    headers = http.client.parse_headers(io.BytesIO((raw + '\r\n').encode('ascii')))
                    body = io.BytesIO(b'12345')
                    if status == 200:
                        body.headers, body.status, body.geturl = headers, status, lambda: url
                        opener.return_value = body
                    else:
                        opener.side_effect = HTTPError(url, status, 'synthetic', headers, body)
                    with self.assertRaisesRegex(ContractError, 'connector_response_content_length_invalid'):
                        guarded_https_get(url, policy=policy, budget=BudgetTracker(policy))
                    self.assertTrue(body.closed)
        for headers in [*({'Content-Length': value} for value in invalid_values),
                        {'Content-Length': '5', 'content-length': '5'}]:
            with self.subTest(headers=headers), self.assertRaisesRegex(ContractError, 'connector_response_content_length_invalid'):
                guarded_https_get(url, policy=policy, budget=BudgetTracker(policy), transport=lambda u, h, t, m:
                                  HttpResponse(200, headers, b'12345', u))


class PatentConnectorsTests(unittest.TestCase):
    def _policy(self, *approvals) -> tuple[ConnectorPolicy, BudgetTracker]:
        p = ConnectorPolicy(opt_in_network=True, allowed_hosts={a.host for a in approvals}, authority_evidence=approvals)
        return p, BudgetTracker(p)

    def test_uspto_odp_separates_filing_and_publication_dates_and_handles_auth_429(self):
        p, b = self._policy(approval(UsptoOdpConnector.BASE_URL + "?q=valve&limit=10", "uspto_odp_v1"))
        conn_no_key = UsptoOdpConnector(p, b, api_key_env="DYZ_NONEXISTENT_TEST_KEY")
        missing = conn_no_key.search("valve")
        self.assertEqual("auth_missing", missing["stop_reason"])
        self.assertEqual(0, missing["network_requests"])

        sample = json.dumps({
            "patentFileWrapperDataBag": [
                {
                    "applicationNumberText": "18/123456",
                    "applicationMetaData": {
                        "inventionTitle": "Valve Control",
                        "filingDate": "2024-01-10",
                        "earliestPublicationDate": "2025-07-10",
                        "earliestPublicationNumber": "US20250123456A1",
                        "applicationStatusDescriptionText": "Published",
                    },
                },
                {
                    "applicationNumberText": "18/999999",
                    "applicationMetaData": {"applicationNumberText": "18/999999", "inventionTitle": "Unpublished Draft",
                                            "filingDate": "2026-01-01"},
                },
            ]
        }).encode("utf-8")
        conn = UsptoOdpConnector(p, b, transport=lambda u, h, t, m: HttpResponse(200, {}, sample, u))
        res = conn.search("valve", api_key="synthetic-key")
        self.assertEqual("complete", res["stop_reason"])
        self.assertEqual("bibliographic_only", res["coverage_level"])
        self.assertTrue(res["records"][0]["prior_art_date_qualified"])
        self.assertFalse(res["records"][1]["prior_art_date_qualified"])
        self.assertIn("some_records_missing_publication_date", res["gaps"])

        conn_429 = UsptoOdpConnector(p, b, transport=lambda u, h, t, m: HttpResponse(429, {}, b"slow down", u))
        self.assertEqual("rate_limited", conn_429.search("valve", api_key="k")["stop_reason"])

    def test_uspto_rejects_malformed_count_fields_even_with_short_valid_page(self):
        p, _ = self._policy(approval(UsptoOdpConnector.BASE_URL + "?q=sample&limit=10", "uspto_odp_v1"))
        bag = [{"applicationNumberText": "18/123456", "applicationMetaData": {"patentNumber": "12345678"}}]
        for key in ("count", "total", "totalCount"):
            for invalid in ("100", True, False, -1, None, 1.0):
                with self.subTest(key=key, invalid=invalid):
                    raw = json.dumps({"count": 1, "patentFileWrapperDataBag": bag, key: invalid}).encode()
                    connector = UsptoOdpConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, raw, u))
                    result = connector.search("sample", api_key="synthetic")
                    self.assertEqual("page_changed", result["stop_reason"])
                    self.assertIn("uspto_odp_result_count_invalid", result["gaps"])

    def test_uspto_requires_consistent_counts_numbered_metadata_and_text_publication_dates(self):
        p, _ = self._policy(approval(UsptoOdpConnector.BASE_URL + "?q=sample&limit=10", "uspto_odp_v1"))

        def report(rows, **counts):
            raw = json.dumps({"patentFileWrapperDataBag": rows, **counts}).encode()
            connector = UsptoOdpConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, raw, u))
            return connector.search("sample", api_key="synthetic")

        meta = {"earliestPublicationNumber": "US20250123456A1", "earliestPublicationDate": "2025-07-10"}
        row = {"applicationNumberText": "18/123456", "applicationMetaData": meta}
        for counts in ({"count": 1, "totalCount": 2}, {"total": 0}):
            result = report([row], **counts)
            self.assertEqual(("page_changed", 0), (result["stop_reason"], result["record_count"]))
            self.assertIn("uspto_odp_result_count_invalid", result["gaps"])
        for invalid in ({"applicationNumberText": "18/123456"},
                        *({**row, "applicationMetaData": item} for item in (None, {}, {"inventionTitle": "Synthetic"},
                                                                          {"patentNumber": 123}, {"patentNumber": "  "}))):
            result = report([invalid], count=1)
            self.assertEqual(("page_changed", 0), (result["stop_reason"], result["record_count"]))
            self.assertIn("uspto_odp_record_schema_changed", result["gaps"])
        for date, qualified in ((None, False), (" ", False), (20250101, False), ({"date": "2025-01-01"}, False),
                                ("not-a-date", False), ("US12345678B2", False), ("2023-02-29", False),
                                ("20240101", False), ("2025-01-01 ", False), ("2024-02-29", True)):
            result = report([{**row, "applicationMetaData": {**meta, "earliestPublicationDate": date}}],
                            count=1, totalCount=1, total=1)
            self.assertEqual("complete", result["stop_reason"])
            self.assertIs(qualified, result["records"][0]["prior_art_date_qualified"])
            self.assertEqual(date if qualified else None, result["records"][0]["publication_date"])
            if not qualified:
                self.assertIn('missing_publication_date_cannot_establish_prior_art_cutoff', result['gaps'])

    def test_epo_range_header_requires_its_own_disclosure_approval(self):
        url = EpoOpsConnector.SEARCH_URL + "?q=sample"
        missing_range = approval(url, "epo_ops_v32", headers=(("Accept", "application/xml"),))
        transport = Mock(side_effect=lambda u, h, t, m: HttpResponse(404, {}, b"", u))
        for receipt, requested in ((missing_range, "1-10"), (approval(url, "epo_ops_v32"), "11-20")):
            p, b = self._policy(receipt)
            connector = EpoOpsConnector(p, b, transport=transport)
            with self.assertRaisesRegex(ContractError, "disclosure_not_bound"):
                connector.search_cql("sample", range_header=requested, access_token="synthetic")
            self.assertEqual(0, b.case_requests)
        transport.assert_not_called()
        second_page = approval(url, "epo_ops_v32", headers=(("Accept", "application/xml"), ("x-ops-range", "11-20")))
        p, b = self._policy(second_page)
        EpoOpsConnector(p, b, transport=transport).search_cql("sample", range_header="11-20", access_token="synthetic")
        self.assertEqual("11-20", transport.call_args.args[1]["X-OPS-Range"])

    def test_epo_ops_cql_xml_parsing_and_zero_hits_and_external_mcp_bridge(self):
        p, b = self._policy(*(approval(EpoOpsConnector.SEARCH_URL + "?q=" + quote(cql), "epo_ops_v32")
                              for cql in ('ti="valve"', 'ti="none"')))
        xml_body = (
            b'<ops:world-patent-data xmlns:ops="http://ops.epo.org">'
            b'<ops:biblio-search><ops:search-result>'
            b'<ops:publication-reference family-id="9001">'
            b'<document-id document-id-type="docdb" family-id="9001">'
            b'<country>EP</country><doc-number>4123456</doc-number><kind>A1</kind><date>20250115</date>'
            b'</document-id></ops:publication-reference>'
            b'</ops:search-result></ops:biblio-search></ops:world-patent-data>'
        )
        conn = EpoOpsConnector(p, b, transport=lambda u, h, t, m: HttpResponse(200, {}, xml_body, u))
        res = conn.search_cql('ti="valve"', access_token="synthetic-tok")
        self.assertEqual("complete", res["stop_reason"])
        self.assertEqual("EP4123456A1", res["records"][0]["publication_number"])
        self.assertEqual('2025-01-15', res['records'][0]['publication_date'])
        self.assertIs(True, res['records'][0]['prior_art_date_qualified'])
        self.assertIn("CC BY 4.0", res["attribution"])

        ops_fault = b'<fault xmlns="http://ops.epo.org"><code>CLIENT.NotFound</code><message>No results found</message></fault>'
        conn_404 = EpoOpsConnector(p, b, transport=lambda u, h, t, m: HttpResponse(404, {}, ops_fault, u))
        self.assertEqual('zero_hits', conn_404.search_cql('ti="none"', access_token='t')['stop_reason'])

        # External MCP Bridge normalizes exports and flags missing publication_date
        mcp_raw = json.dumps({
            "records": [{"publication_number": "CN119000001A", "title": "测试", "filing_date": "2024-05-01"}]
        }).encode("utf-8")
        imported = ExternalMcpBridge.import_records(
            provider="patent_mcp_server", query="valve", raw_payload=mcp_raw, coverage_level="abstract_only"
        )
        self.assertEqual("imported_snapshot", imported["stop_reason"])
        self.assertFalse(imported["records"][0]["prior_art_date_qualified"])
        self.assertIn("missing_publication_date_cannot_establish_prior_art_cutoff", imported["gaps"])

    def test_epo_and_external_bridge_reject_non_calendar_dates_without_filing_or_grant_fallback(self):
        p, _ = self._policy(approval(EpoOpsConnector.SEARCH_URL + '?q=sample', 'epo_ops_v32'))
        xml = ('<biblio-search><search-result><publication-reference><document-id><country>EP</country>'
               '<doc-number>1</doc-number><kind>A1</kind><date>{}</date></document-id></publication-reference>'
               '</search-result></biblio-search>')
        gap = 'missing_publication_date_cannot_establish_prior_art_cutoff'
        for value in ('   ', 'not-a-date', 'EP4123456B1', '2023-02-29', '2023-13-01', '2024-02-29 ', '2024-02-29'):
            with self.subTest(value=value):
                raw = xml.format(value).encode()
                transport = lambda u, h, t, m: HttpResponse(200, {}, raw, u)
                epo = EpoOpsConnector(p, BudgetTracker(p), transport=transport).search_cql('sample', access_token='t')
                external = ExternalMcpBridge.import_records(
                    provider='patents-mcp', query='sample', coverage_level='bibliographic_only',
                    raw_payload=json.dumps({'records': [{'publication_number': 'EP1A1', 'publication_date': value,
                                                        'filing_date': '2024-01-01', 'grant_date': '2025-01-01'}]}).encode())
                qualified = value == '2024-02-29'
                for result in (epo, external):
                    self.assertEqual(1, result['record_count'])
                    self.assertIs(qualified, result['records'][0]['prior_art_date_qualified'])
                    self.assertEqual(value if qualified else None, result['records'][0]['publication_date'])
                    self.assertEqual(not qualified, gap in result['gaps'])
        for value, qualified in (('20240229', True), ('20230229', False)):
            raw = xml.format(value).encode()
            connector = EpoOpsConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, raw, u))
            result = connector.search_cql('sample', access_token='t')
            self.assertIs(qualified, result['records'][0]['prior_art_date_qualified'])
            self.assertEqual(not qualified, gap in result['gaps'])

    def test_epo_404_only_recognizes_ops_zero_hit_faults(self):
        url = EpoOpsConnector.SEARCH_URL + '?q=sample'
        receipt = approval(url, 'epo_ops_v32', headers=(('Accept', 'application/xml'), ('X-OPS-Range', '11-20')))
        p, _ = self._policy(approval(url, 'epo_ops_v32'), receipt)
        for body, expected in (
            (b'<html><title>404</title><p>No results found</p></html>', 'http_error'),
            (b'<fault><code>CLIENT.NotFound</code></fault>', 'http_error'),
            (b'<fault xmlns="http://ops.epo.org"><code>CLIENT.UnknownEndpoint</code></fault>', 'http_error'),
            (b'<ops:fault xmlns:ops="http://ops.epo.org"><ops:message>No results found</ops:message></ops:fault>', 'http_error'),
            (b'<ops:fault xmlns:ops="http://ops.epo.org"><ops:code>CLIENT.NotFound</ops:code>'
             b'<ops:message>No results found</ops:message></ops:fault>', 'zero_hits'),
            (b'<ops:fault xmlns:ops="http://ops.epo.org"><code>CLIENT.NotFound</code>'
             b'<ops:message>No results found</ops:message></ops:fault>', 'http_error'),
            (b'<fault xmlns="http://ops.epo.org"><code xmlns="urn:other">CLIENT.NotFound</code>'
             b'<message>No results found</message></fault>', 'http_error'),
            (b'<fault xmlns="http://ops.epo.org"><code>CLIENT.UnknownEndpoint</code>'
             b'<message>No results found</message></fault>', 'http_error'),
            (b'<fault xmlns="http://ops.epo.org"><code>CLIENT.NotFound</code>'
             b'<message>Endpoint disabled</message></fault>', 'http_error'),
            (b'<fault xmlns="http://ops.epo.org"><code>CLIENT.NotFound</code><code>CLIENT.InvalidQuery</code>'
             b'<message>No results found</message></fault>', 'http_error'),
            (b'<fault xmlns="http://ops.epo.org" total-result-count="10"><code>CLIENT.NotFound</code>'
             b'<message>No results found</message></fault>', 'http_error'),
            (b'<fault xmlns="http://ops.epo.org"><code>CLIENT.NotFound</code><message>No results found</message>'
             b'<detail><total-result-count>10</total-result-count></detail></fault>', 'http_error'),
        ):
            with self.subTest(body=body):
                transport = lambda u, h, t, m: HttpResponse(404, {}, body, u)
                connector = EpoOpsConnector(p, BudgetTracker(p), transport=transport)
                first = connector.search_cql('sample', access_token='t')
                later = connector.search_cql('sample', range_header='11-20', access_token='t')
                self.assertEqual((expected, []), (first['stop_reason'], first['records']))
                self.assertEqual('partial' if expected == 'zero_hits' else expected, later['stop_reason'])

    def test_epo_xml_and_response_range_preserve_incomplete_coverage(self):
        p, _ = self._policy(approval(EpoOpsConnector.SEARCH_URL + "?q=sample", "epo_ops_v32"))
        doc_id = b"<document-id><country>EP</country><doc-number>4123456</doc-number><kind>A1</kind></document-id>"
        publication = b"<publication-reference>" + doc_id + b"</publication-reference>"
        application = b"<application-reference>" + doc_id + b"</application-reference>"
        incomplete = publication.replace(b"<doc-number>4123456</doc-number>", b"")
        nested_id = publication.replace(b"4123456", b"4123456<unexpected />")
        unknown = publication.replace(b"<document-id>", b'<document-id document-id-type="unknown">')
        unknown_child = publication.replace(b"</document-id>", b"<unexpected>value</unexpected></document-id>")
        for entries, headers, reason, gap, count in (
            (application, {}, "page_changed", "epo_ops_non_publication_record", 0),
            (publication + application, {}, "partial", "epo_ops_non_publication_record", 1),
            (incomplete, {}, "page_changed", "epo_ops_publication_identifier_missing_or_invalid", 0),
            (nested_id, {}, "page_changed", "epo_ops_publication_identifier_missing_or_invalid", 0),
            (unknown_child, {}, "page_changed", "epo_ops_publication_identifier_missing_or_invalid", 0),
            (unknown, {}, "page_changed", "epo_ops_unknown_publication_entry", 0),
            (publication, {"X-OPS-Range": "1-1/20"}, "partial", "epo_ops_results_truncated", 1),
            (publication, {"Content-Range": "items 2-2/2"}, "partial", "epo_ops_response_range_mismatch", 1),
            (publication, {"X-OPS-Range": "1-1"}, "partial", "epo_ops_response_range_incomplete", 1),
            (publication, {"X-OPS-Range": "1-10"}, "partial", "epo_ops_response_range_count_mismatch", 1),
        ):
            with self.subTest(reason=reason, gap=gap):
                body = b"<biblio-search><search-result>" + entries + b"</search-result></biblio-search>"
                connector = EpoOpsConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, headers, body, u))
                result = connector.search_cql("sample", access_token="synthetic")
                self.assertEqual((reason, count), (result["stop_reason"], result["record_count"]))
                self.assertIn(gap, result["gaps"])

    def test_epo_requires_search_at_supported_root_or_direct_child(self):
        p, _ = self._policy(approval(EpoOpsConnector.SEARCH_URL + "?q=sample", "epo_ops_v32"))
        search = b'<biblio-search total-result-count="0" />'
        for prefix, suffix, expected in (
            (b"", b"", "zero_hits"),
            (b"<world-patent-data>", b"</world-patent-data>", "zero_hits"),
            (b"<fault>", b"</fault>", "page_changed"),
            (b"<world-patent-data><fault>", b"</fault></world-patent-data>", "page_changed"),
        ):
            with self.subTest(prefix=prefix):
                body = prefix + search + suffix
                connector = EpoOpsConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, body, u))
                result = connector.search_cql("sample", access_token="synthetic")
                self.assertEqual((expected, 0), (result["stop_reason"], result["record_count"]))
        for child, gap in ((b'<fault/>', 'epo_ops_fault_in_search_response'),
                           (b'<unrecognized/>', 'epo_ops_unknown_root_entry')):
            body = b'<world-patent-data>' + search + child + b'</world-patent-data>'
            connector = EpoOpsConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, body, u))
            result = connector.search_cql('sample', access_token='synthetic')
            self.assertEqual(('page_changed', []), (result['stop_reason'], result['records']))
            self.assertIn(gap, result['gaps'])

    def test_three_sources_report_http_failure_dry_run_and_partial_without_live_io(self):
        approved = (
            approval(UsptoOdpConnector.BASE_URL + "?q=sample&limit=10", "uspto_odp_v1"),
            approval(EpoOpsConnector.SEARCH_URL + "?q=sample", "epo_ops_v32"),
            samr_approval("sample"),
        )
        policy, _ = self._policy(*approved)
        sources = (
            (UsptoOdpConnector, "search", {"api_key": "  test  "},
             b'{"count":20,"patentFileWrapperDataBag":[{"applicationMetaData":{"patentNumber":"12345678"}}]}'),
            (EpoOpsConnector, "search_cql", {"access_token": "  test  "},
             b'<biblio-search total-result-count="40"><search-result><publication-reference><document-id>'
             b'<country>EP</country><doc-number>1</doc-number><kind>A1</kind></document-id>'
             b'</publication-reference></search-result></biblio-search>'),
            (SamrLiveConnector, "query_catalog", {}, b'{"total":50,"pageNumber":1,"rows":[{"C_STD_CODE":"GB 1","C_C_NAME":"verify"}]}'),
        )
        for connector, operation, params, good in sources:
            with self.subTest(source=connector.__name__):
                dry = replace(policy, dry_run=True)
                blocked_transport = Mock(side_effect=AssertionError("dry run reached transport"))
                with patch('tools.connectors.patent_sources.os.environ', Mock(get=Mock(side_effect=AssertionError("credential read")))):
                    outcome = getattr(connector(dry, BudgetTracker(dry), transport=blocked_transport), operation)("sample")
                self.assertEqual(("dry_run", 0), (outcome["stop_reason"], outcome["network_requests"]))
                blocked_transport.assert_not_called()
                for status, body, reason in ((503, b"service unavailable", "http_error"), (200, good, "partial"),
                                              (200, b"[" * 1500 + b"]" * 1500, "page_changed")):
                    transport = Mock(side_effect=lambda u, h, t, m: HttpResponse(status, {"content-type": "application/json"}, body, u))
                    outcome = getattr(connector(policy, BudgetTracker(policy), transport=transport), operation)("sample", **params)
                    self.assertEqual((reason, status), (outcome["stop_reason"], outcome["http_status"]))
                    if connector is UsptoOdpConnector:
                        self.assertEqual("test", transport.call_args.args[1]["X-API-KEY"])
                    if connector is EpoOpsConnector:
                        self.assertEqual("Bearer test", transport.call_args.args[1]["Authorization"])

    def test_patent_parsers_reject_schema_drift_dtd_range_and_oversized_imports(self):
        us, ub = self._policy(approval(UsptoOdpConnector.BASE_URL + "?q=sample&limit=10", "uspto_odp_v1"))
        for body in (b"[]", b'{"patentFileWrapperDataBag":[1,{"applicationMetaData":[1]}]}'):
            connector = UsptoOdpConnector(us, ub, transport=lambda u, h, t, m: HttpResponse(200, {}, body, u))
            self.assertEqual("page_changed", connector.search("sample", api_key="k")["stop_reason"])
        ep, eb = self._policy(approval(EpoOpsConnector.SEARCH_URL + "?q=sample", "epo_ops_v32"))
        fake = Mock(side_effect=lambda u, h, t, m: HttpResponse(200, {}, b'<!DOCTYPE document><biblio-search/>', u))
        conn = EpoOpsConnector(ep, eb, transport=fake)
        for value in ("10-1", "1-101", "1-10\n", 1):
            with self.assertRaisesRegex(ContractError, "epo_range_invalid"):
                conn.search_cql("sample", range_header=value, access_token="t")
        fake.assert_not_called()
        self.assertIn("epo_ops_xml_dtd_forbidden", conn.search_cql("sample", access_token="t")["gaps"])
        for payload, error in ((b"x" * (ExternalMcpBridge.MAX_PAYLOAD_BYTES + 1), "payload_too_large"),
                               (json.dumps({"records": [None] * (ExternalMcpBridge.MAX_RECORDS + 1)}).encode(), "too_many_records")):
            with self.assertRaisesRegex(ContractError, error):
                ExternalMcpBridge.import_records(provider="patent_mcp_server", query="sample", raw_payload=payload,
                                                 coverage_level="bibliographic_only")


class StandardLiveAndIsoBridgeTests(unittest.TestCase):
    def test_samr_live_handles_ok_zero_captcha_403_and_drift(self):
        p = ConnectorPolicy(opt_in_network=True, allowed_hosts=(SamrLiveConnector.HOST,), authority_evidence=samr_approval("GB/T 1.1"))
        ok_body = json.dumps({
            "total": 1, "pageNumber": 1,
            "rows": [{"id": "1", "C_STD_CODE": "GB/T 1.1-2020", "C_C_NAME": "标准化工作导则", "STATE": "现行"}],
        }).encode("utf-8")
        c_ok = SamrLiveConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, ok_body, u))
        res_ok = c_ok.query_catalog("GB/T 1.1")
        self.assertEqual("complete", res_ok["stop_reason"])
        self.assertEqual("metadata_only_never_guessed", res_ok["records"][0]["fulltext_access"])

        # CAPTCHA / HTML page MUST NOT be treated as zero_hits!
        c_cap = SamrLiveConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, b"<html>captcha</html>", u))
        self.assertEqual("access_denied_or_challenge", c_cap.query_catalog("GB/T 1.1")["stop_reason"])

        # 403 MUST stop cleanly
        c_403 = SamrLiveConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(403, {}, b"denied", u))
        self.assertEqual("access_denied_or_challenge", c_403.query_catalog("GB/T 1.1")["stop_reason"])

        # Structure drift (unexpected JSON keys) -> page_changed, NOT zero_hits!
        c_drift = SamrLiveConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, b'{"unexpected": []}', u))
        self.assertEqual("page_changed", c_drift.query_catalog("GB/T 1.1")["stop_reason"])

    def test_samr_requires_credible_total_and_a_code_for_every_row(self):
        p = ConnectorPolicy(opt_in_network=True, allowed_hosts=(SamrLiveConnector.HOST,),
                            authority_evidence=samr_approval("sample", size=1))
        for total, rows, status, expected in (
            (0, [{"C_STD_CODE": "GB 1"}], "page_changed", "samr_envelope_schema_changed"),
            (1, [{"C_STD_CODE": ""}], "page_changed", "samr_record_schema_changed"),
            (1, [{"C_STD_CODE": " \t"}], "page_changed", "samr_record_schema_changed"),
            (1, [{"C_STD_CODE": 45}], "page_changed", "samr_record_schema_changed"),
            (2, [{"C_STD_CODE": "GB 1"}, {}], "page_changed", "samr_envelope_schema_changed"),
        ):
            with self.subTest(total=total, rows=rows):
                body = json.dumps({"total": total, "pageNumber": 1, "rows": rows}).encode()
                connector = SamrLiveConnector(p, BudgetTracker(p), transport=lambda u, h, t, m: HttpResponse(200, {}, body, u))
                result = connector.query_catalog("sample", page_size=1)
                self.assertEqual((status, 0), (result["stop_reason"], result["record_count"]))
                self.assertIn(expected, result["gaps"])

    def test_samr_rejects_core_field_drift_and_impossible_pages_without_partial_rows(self):
        row = {'id': 'row-1', 'C_STD_CODE': 'GB/T 1.1-2020', 'C_C_NAME': 'Synthetic title',
               'STD_NATURE': 'recommended', 'STATE': 'active', 'ISSUE_DATE': '2020-01-01',
               'ACT_DATE': '2020-02-01', 'PROJECT_ID': 42}
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=(SamrLiveConnector.HOST,),
                                 authority_evidence=tuple(samr_approval('sample', page=i, size=2) for i in (1, 2, 3)))

        def query(page, total, rows):
            body = json.dumps({'total': total, 'pageNumber': page, 'rows': rows}).encode()
            transport = lambda u, h, t, m: HttpResponse(200, {}, body, u)
            return SamrLiveConnector(policy, BudgetTracker(policy), transport=transport).query_catalog(
                'sample', page_size=2, page_number=page)

        for invalid in ([], {**row, 'C_STD_CODE': 'unexpected title'}, {**row, 'C_STD_CODE': '\u2800'},
                        *({**row, field: {}} for field in ('id', 'C_C_NAME', 'STD_NATURE', 'STATE', 'ISSUE_DATE', 'ACT_DATE')),
                        {**row, 'PROJECT_ID': True}):
            with self.subTest(invalid=invalid):
                report = query(1, 2, [row, invalid])
                self.assertEqual(('page_changed', []), (report['stop_reason'], report['records']))
                self.assertIn('samr_record_schema_changed', report['gaps'])
        for page, total, rows in ((2, 0, []), (3, 3, []), (2, 2, [row]), (2, 3, [row, row]),
                                  (1, 1, []), (2, 3, []), (1, 3, [row, row, row])):
            with self.subTest(page=page, total=total, rows=len(rows)):
                report = query(page, total, rows)
                self.assertEqual(('page_changed', []), (report['stop_reason'], report['records']))
                self.assertIn('samr_envelope_schema_changed', report['gaps'])
        self.assertEqual('zero_hits', query(1, 0, [])['stop_reason'])
        self.assertEqual('partial', query(2, 3, [row])['stop_reason'])

    def test_approved_samr_pages_share_query_budget(self):
        policy = ConnectorPolicy(opt_in_network=True, allowed_hosts=(SamrLiveConnector.HOST,), max_requests_per_query=1,
                                 authority_evidence=(samr_approval('sample'), samr_approval('sample', page=2)))
        first = b'{"total":2,"pageNumber":1,"rows":[{"C_STD_CODE":"GB 1"}]}'
        transport = Mock(side_effect=lambda u, h, t, m: HttpResponse(200, {'Content-Type': 'application/json'}, first, u))
        samr = SamrLiveConnector(policy, BudgetTracker(policy), transport=transport)
        self.assertEqual('partial', samr.query_catalog(' sample ')["stop_reason"])
        with self.assertRaisesRegex(ContractError, 'query_request_budget_exceeded'):
            samr.query_catalog('sample', page_number=2)
        transport.assert_called_once()

    def test_iso_catalog_reconciliation_flags_withdrawn_and_edition_mismatch(self):
        report = IsoCatalogBridge.reconcile_references(
            draft_external_references=[
                {"id": "R1", "identifier": "ISO 9001", "edition": "2015"},
                {"id": "R2", "identifier": "ISO 27001", "edition": "2013"},
                {"id": "R3", "identifier": "ISO/IEC 25010", "edition": "2011"},
            ],
            catalog_snapshot=[
                {"identifier": "ISO 9001", "edition": "2015", "state": "current"},
                {"identifier": "ISO 27001", "edition": "2022", "state": "current"},
                {"identifier": "ISO/IEC 25010", "edition": "2011", "state": "withdrawn", "replaced_by": "ISO/IEC 25010:2023"},
            ],
        )
        statuses = {row["ref_id"]: row["status"] for row in report["results"]}
        self.assertEqual("current_in_snapshot", statuses["R1"])
        self.assertEqual("edition_mismatch", statuses["R2"])
        self.assertEqual("withdrawn", statuses["R3"])
        self.assertEqual(["R2", "R3"], report["invalidation_targets"])

    def test_iso_missing_edition_preserves_ambiguity_and_invalid_edition_is_rejected(self):
        snapshot = [{"identifier": "ISO 1", "edition": edition, "state": "current"} for edition in ("2020", "2025")]
        result = IsoCatalogBridge.reconcile_references(draft_external_references=[{"id": "R", "identifier": "ISO 1"}],
                                                      catalog_snapshot=snapshot)
        row = result["results"][0]
        self.assertEqual(("needs_manual_check", ["2020", "2025"]), (row["status"], row["available_editions"]))
        with self.assertRaisesRegex(ContractError, "catalog_row_invalid"):
            IsoCatalogBridge.reconcile_references(draft_external_references=[], catalog_snapshot=[{**snapshot[0], "edition": 2020}])


if __name__ == "__main__":
    unittest.main()
