"""SE-05 原创合成证据：版次、覆盖、引用及本地权限边界。"""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tools import standard_sources as sources
from tools.core import ContractError, canonical_bytes, digest, sha256_bytes


def identity(edition="2026"):
    return {"number": "SYN-TEST 1", "edition": edition,
            "publisher": "原创工程示例", "title": "合成安全要求"}


def admission(root, files, outputs, payload):
    now = datetime.now(timezone.utc)
    return {"root": str(root), "inputs": files, "outputs": outputs,
            "payload_hash": digest(payload), "sensitivity": "restricted",
            "purpose": "internal_standard_review",
            "environment": {"assessment_evidence": "synthetic-assessment",
                "data_paths": [{"id": name, "verified": True, "mode": "local",
                                "evidence": "synthetic-path-evidence"}
                    for name in ("host_model", "index", "telemetry", "tools", "logs", "subprocess")]},
            "permissions": [{"action": action, "purpose": "internal_standard_review",
                "recipient": "local_tool", "decision": "allow",
                "authority_evidence": "synthetic-permission", "valid_from": (now - timedelta(hours=1)).isoformat(),
                "valid_until": (now + timedelta(hours=1)).isoformat()}
                for action in ("local_read", "local_process", "copy")]}


def pdf_fixture():
    """自行构造两个页面；页数来自PDF目录而不是转写。"""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 45 >>\nstream\nBT /F1 12 Tf 20 250 Td (SYNTHETIC FIRST) Tj ET\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        b"<< /Length 44 >>\nstream\nBT /F1 12 Tf 20 250 Td (SYNTHETIC LAST) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    raw = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(raw))
        raw.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(raw)
    raw.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    raw.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    raw.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(raw)


class StandardSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = "第一条：周期为10 ms。\f第二条：维护模式除外。".encode()
        (self.root / "source.txt").write_bytes(self.raw)
        self.request = {"expected_sha256": sha256_bytes(self.raw), "identity": identity(),
                        "access_status": "local_authorized", "citations": []}

    def test_real_case_root_cannot_overlap_running_package(self):
        permit = admission(self.root, {"source.txt": sha256_bytes(self.raw)}, [], self.request)
        for package_root in (self.root, self.root.parent, self.root / "package"):
            with self.subTest(package_root=package_root), patch.object(
                    sources, "__file__", str(package_root / "tools/standard_sources.py")):
                with self.assertRaisesRegex(ContractError, "case_root_overlaps_package"):
                    sources.authorize_io(self.root, admission=permit, payload=self.request)

    def test_synthetic_catalog_distinguishes_zero_parse_and_partial(self):
        value = {"schema": "synthetic_catalog_v1", "records": [], "complete": True}
        zero = sources.parse_catalog(canonical_bytes(value), adapter="synthetic_catalog_v1", synthetic=True)
        self.assertEqual("zero_results", zero["state"])
        failed = sources.parse_catalog(b"<html>changed</html>", adapter="synthetic_catalog_v1", synthetic=True)
        self.assertEqual("parse_failed", failed["state"])
        self.assertIsNone(failed["result_count"])
        value["complete"] = False
        self.assertEqual("pagination_incomplete", sources.parse_catalog(canonical_bytes(value), adapter="synthetic_catalog_v1", synthetic=True)["state"])
        with self.assertRaisesRegex(ContractError, "adapter_not_implemented"):
            sources.parse_catalog(b"{}", adapter="official_website", synthetic=True)

    def test_samr_observed_json_zero_results_and_parse_failure(self):
        request = {"url": "https://std.samr.gov.cn/gb/search/gbQueryPage?pageSize=15&pageNumber=1&searchText=SYNTHETIC",
                   "retrieved_at": "2026-11-13T12:00:00Z", "http_status": 200,
                   "content_type": "application/json;charset=utf-8"}
        zero = sources.parse_catalog(b'{"total":0,"pageNumber":1,"rows":[]}',
            adapter="samr_gb_query_v1", request=request, synthetic=True)
        self.assertEqual("zero_results", zero["state"])
        self.assertEqual(0, zero["total_count"])
        failed = sources.parse_catalog(b'<html>blocked</html>',
            adapter="samr_gb_query_v1", request=request, synthetic=True)
        self.assertEqual("parse_failed", failed["state"])
        self.assertIsNone(failed["result_count"])
        unavailable = sources.parse_catalog(b'upstream failure', adapter="samr_gb_query_v1",
            request={**request, "http_status": 503}, synthetic=True)
        self.assertEqual("network_failed", unavailable["state"])
        self.assertIsNone(unavailable["result_count"])

    def test_samr_original_same_shape_fixture_pagination_edition_and_gaps(self):
        rows = [{"id": "SYNTHETIC-" + str(n), "C_C_NAME": "原创结构测试标准",
                 "C_STD_CODE": "GB/T 900001-" + year, "STD_NATURE": "推荐性",
                 "ACT_DATE": year + "-12-01", "STATE": state,
                 "ISSUE_DATE": year + "-01-01", "PROJECT_ID": n}
                for n, year, state in ((1, "2025", "废止"), (2, "2026", "现行"))]
        request = {"url": "https://std.samr.gov.cn/gb/search/gbQueryPage?pageSize=15&pageNumber=1",
                   "retrieved_at": "2026-11-13T12:00:00Z", "http_status": 200,
                   "content_type": "application/json"}
        raw = canonical_bytes({"total": 2, "pageNumber": 1, "rows": rows})
        report = sources.parse_catalog(raw, adapter="samr_gb_query_v1", request=request, synthetic=True)
        self.assertEqual("results", report["state"])
        self.assertTrue(report["pagination_complete"])
        selected = sources.select_standard(report["records"], {
            "number": "GB/T 900001", "edition": "2025", "publisher": None,
            "title": "原创结构测试标准"})
        self.assertEqual("withdrawn", selected["status"])
        self.assertEqual("metadata_only", selected["access_status"])
        self.assertIsNone(selected["identity"]["publisher"])
        self.assertFalse(selected["identity_complete"])
        self.assertIsNone(selected["replaces"])
        self.assertEqual("not_provided", selected["replacement_status"])
        with self.assertRaisesRegex(ContractError, "identity_text_required"):
            sources.import_local(self.root, "source.txt", {**self.request, "identity": selected["identity"]}, synthetic=True)
        partial = sources.parse_catalog(canonical_bytes({"total": 100, "pageNumber": 1, "rows": rows}),
            adapter="samr_gb_query_v1", request=request, synthetic=True)
        self.assertEqual("pagination_incomplete", partial["state"])
        self.assertEqual(100, partial["total_count"])
        drift = sources.parse_catalog(canonical_bytes({"total": 2, "pageNumber": 2, "rows": rows}),
            adapter="samr_gb_query_v1", request=request, synthetic=True)
        self.assertEqual("parse_failed", drift["state"])

    def test_samr_url_duplicate_key_and_missing_field_fail_closed(self):
        request = {"url": "https://127.0.0.1/gb/search/gbQueryPage?pageSize=15&pageNumber=1",
                   "retrieved_at": "2026-11-13T12:00:00Z", "http_status": 200,
                   "content_type": "application/json"}
        with self.assertRaisesRegex(ContractError, "catalog_origin_not_allowed"):
            sources.parse_catalog(b'{}', adapter="samr_gb_query_v1", request=request, synthetic=True)
        request["url"] = "https://std.samr.gov.cn/gb/search/gbQueryPage?pageSize=15&pageNumber=1"
        for raw in (b'{"total":1,"total":0,"pageNumber":1,"rows":[]}',
                    b'{"total":1,"pageNumber":1,"rows":[{}]}'):
            result = sources.parse_catalog(raw, adapter="samr_gb_query_v1", request=request, synthetic=True)
            self.assertEqual("parse_failed", result["state"])
            self.assertIsNone(result["result_count"])

    def test_catalog_cli_uses_bound_snapshot_not_network(self):
        raw = b'{"total":0,"pageNumber":1,"rows":[]}'
        (self.root / "catalog.json").write_bytes(raw)
        request = {"expected_sha256": sha256_bytes(raw), "adapter": "samr_gb_query_v1",
            "request": {"url": "https://std.samr.gov.cn/gb/search/gbQueryPage?pageSize=15&pageNumber=1",
                        "retrieved_at": "2026-11-13T12:00:00Z", "http_status": 200,
                        "content_type": "application/json"}}
        (self.root / "catalog-request.json").write_bytes(canonical_bytes(request))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, sources.main(["--root", str(self.root), "--operation", "catalog",
                "--input", "catalog.json", "--request", "catalog-request.json",
                "--output", "catalog-evidence.json", "--synthetic"]))
        result = json.loads((self.root / "catalog-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual("zero_results", result["state"])
        self.assertEqual("not_performed", result["network"])

    def test_exact_edition_required_no_latest_guess(self):
        records = [{"identity": identity(year), "status": "unknown", "access_status": "metadata_only", "replaces": []}
                   for year in ("2025", "2026")]
        selected = sources.select_standard(records, identity("2025"))
        self.assertEqual("2025", selected["identity"]["edition"])
        with self.assertRaises(ContractError):
            sources.select_standard(records, {"number": "SYN-TEST 1"})
        with self.assertRaisesRegex(ContractError, "identity_not_unique"):
            sources.select_standard(records + records[:1], identity("2025"))

    def test_text_import_separates_hashes_and_checks_exact_quote(self):
        quote = "周期为10 ms"
        self.request["citations"] = [{"id": "c1", "page": 1, "start": 4, "end": 12,
            "quote": quote, "proposition": "合成周期", "relation": "supports"}]
        result = sources.import_local(self.root, "source.txt", self.request, synthetic=True)
        self.assertEqual(sha256_bytes(self.raw), result["original_sha256"])
        self.assertNotEqual(result["original_sha256"], result["extracted_text_sha256"])
        self.assertEqual("complete", result["extraction"]["coverage"])
        self.assertEqual(2, result["extraction"]["total_pages"])
        self.assertEqual("verified", result["citations"][0]["literal_binding"])
        self.assertEqual("not_verified", result["identity_authenticity"])
        self.assertEqual("not_performed", result["professional_review"])
        self.request["citations"][0]["quote"] = "周期为20 ms"
        with self.assertRaisesRegex(ContractError, "citation_text_mismatch"):
            sources.import_local(self.root, "source.txt", self.request, synthetic=True)

    def _import_synthetic_pages(self, pages, citations):
        raw = "\f".join(pages).encode("utf-8")
        (self.root / "source.txt").write_bytes(raw)
        request = {**self.request, "expected_sha256": sha256_bytes(raw),
                   "citations": citations}
        return sources.import_local(self.root, "source.txt", request, synthetic=True)

    @staticmethod
    def _segment(page, text, start=0, end=None):
        end = len(text) if end is None else end
        return {"page": page, "start": start, "end": end, "quote": text[start:end]}

    @staticmethod
    def _multi_citation(segments):
        return {"id": "synthetic-citation", "segments": segments,
                "proposition": "合成材料待审命题，不代表真实标准", "relation": "supports"}

    def test_continuation_segments_bind_original_text_hashes_and_context_ranges(self):
        pages = ["原创合成示例\n5.1 设备应在正常运行时保持", "指示灯常亮；维护模式除外。\n5.2 记录。"]
        start = pages[0].index("5.1")
        end = pages[1].index("\n5.2")
        segments = [self._segment(1, pages[0], start), self._segment(2, pages[1], 0, end)]
        citation = self._multi_citation(segments)
        before = copy.deepcopy(citation)
        report = self._import_synthetic_pages(pages, [citation])
        result = report["citations"][0]
        self.assertEqual(before, citation)
        self.assertEqual("synthetic", report["mode"])
        self.assertEqual("complete", result["coverage"])
        self.assertEqual("contiguous", result["range_continuity"])
        self.assertEqual("complete", result["source_coverage"])
        self.assertEqual("declared_ranges_and_source_extraction_only", result["coverage_scope"])
        self.assertEqual(report["original_sha256"], result["original_sha256"])
        self.assertEqual(report["extracted_text_sha256"], result["extracted_text_sha256"])
        self.assertNotEqual(result["original_sha256"], result["extracted_text_sha256"])
        self.assertEqual("not_verified", result["semantic_completeness"])
        self.assertEqual("not_verified", result["proposition_support"])
        self.assertEqual("not_performed", result["original_page_reopened"])
        self.assertNotIn("quote", result)
        for original, bound in zip(segments, result["segments"]):
            text = pages[bound["page"] - 1]
            for key, value in original.items():
                self.assertEqual(value, bound[key])
            self.assertEqual("verified", bound["literal_binding"])
            self.assertEqual(text[bound["context_start"]:bound["context_end"]], bound["context"])
            self.assertEqual(max(0, bound["start"] - 60), bound["context_start"])
            self.assertEqual(min(len(text), bound["end"] + 60), bound["context_end"])

    def test_appendix_a1_and_cross_page_table_are_literal_not_semantic(self):
        pages = ["原创合成附录A（资料性）\nA.1 表A.1 合成项目\n项目\t单位\n时长\tms",
                 "表A.1（续）\n维护模式\t不适用\n注：本表不是真实试验。"]
        citation = self._multi_citation([
            self._segment(1, pages[0], pages[0].index("A.1")),
            self._segment(2, pages[1]),
        ])
        report = self._import_synthetic_pages(pages, [citation])
        bound = report["citations"][0]
        self.assertEqual("complete", bound["coverage"])
        self.assertIn("A.1", bound["segments"][0]["quote"])
        self.assertIn("表A.1（续）", bound["segments"][1]["quote"])
        self.assertIn("不适用", bound["segments"][1]["quote"])
        self.assertEqual("not_verified", bound["proposition_support"])
        self.assertFalse(report["full_text_absence_allowed"])
        self.assertEqual("not_performed", report["professional_review"])

    def test_adjacent_same_page_segments_are_contiguous(self):
        page = "原创合成示例：应保留全部例外。"
        segments = [self._segment(1, page, 0, 7), self._segment(1, page, 7)]
        result = self._import_synthetic_pages([page], [self._multi_citation(segments)])
        self.assertEqual("complete", result["citations"][0]["coverage"])
        self.assertEqual(2, len(result["citations"][0]["segments"]))

    def test_gapped_ranges_keep_literal_evidence_but_not_complete_coverage(self):
        pages = ["原创合成示例：应保存记录。例外：维护模式。", "合成续页。", "合成末页。"]
        cases = [
            [self._segment(1, pages[0], 0, 6), self._segment(1, pages[0], 10)],
            [self._segment(1, pages[0], 0, 6), self._segment(2, pages[1])],
            [self._segment(1, pages[0]), self._segment(2, pages[1], 2)],
            [self._segment(1, pages[0]), self._segment(3, pages[2])],
        ]
        for segments in cases:
            with self.subTest(segments=segments):
                result = self._import_synthetic_pages(pages, [self._multi_citation(segments)])
                bound = result["citations"][0]
                self.assertEqual("partial", bound["coverage"])
                self.assertEqual("gapped", bound["range_continuity"])
                self.assertEqual("verified", bound["literal_binding"])
                self.assertEqual("complete", bound["source_coverage"])
                self.assertEqual("not_verified", bound["semantic_completeness"])
                self.assertEqual("needs_evidence", result["status"])

    def test_blank_middle_or_tail_text_page_is_not_complete(self):
        for pages in (["原创合成首段。", " \n", "合成末段。"], ["原创合成首段。", ""]):
            with self.subTest(pages=pages):
                citation = self._multi_citation([self._segment(1, pages[0])])
                result = self._import_synthetic_pages(pages, [citation])
                self.assertEqual("partial", result["extraction"]["coverage"])
                self.assertEqual([2], result["extraction"]["missing_or_unreadable_pages"])
                self.assertEqual("needs_evidence", result["status"])
                self.assertEqual("partial", result["citations"][0]["coverage"])
                self.assertEqual("contiguous", result["citations"][0]["range_continuity"])

    def test_transcription_missing_middle_page_and_unknown_tail_stay_partial(self):
        raw = pdf_fixture()
        (self.root / "source.pdf").write_bytes(raw)
        rows = [{"page": 1, "text": "原创合成首段。"}, {"page": 3, "text": "合成末段。"}]
        citation = self._multi_citation([self._segment(r["page"], r["text"]) for r in rows])
        request = {**self.request, "expected_sha256": sha256_bytes(raw),
                   "transcription": {"total_pages": 3, "pages": rows}, "citations": [citation]}
        report = sources.import_local(self.root, "source.pdf", request, synthetic=True)
        bound = report["citations"][0]
        self.assertEqual("partial", bound["coverage"])
        self.assertEqual([2], bound["missing_or_unreadable_pages"])
        self.assertEqual("gapped", bound["range_continuity"])
        self.assertIsNone(report["extraction"]["total_pages"])
        self.assertEqual("not_verified", report["extraction"]["page_count_status"])
        request["transcription"]["pages"] = rows[:1]
        request["citations"] = [self._multi_citation(citation["segments"][:1])]
        report = sources.import_local(self.root, "source.pdf", request, synthetic=True)
        self.assertEqual("partial", report["citations"][0]["coverage"])
        self.assertFalse(report["full_text_absence_allowed"])

    def test_duplicate_overlapping_and_out_of_order_segments_are_rejected(self):
        pages = ["原创合成第一页。", "原创合成第二页。"]
        first, second = self._segment(1, pages[0]), self._segment(2, pages[1])
        cases = [[first, first], [second, first],
                 [self._segment(1, pages[0], 0, 6), self._segment(1, pages[0], 4)],
                 [self._segment(1, pages[0], 5), self._segment(1, pages[0], 0, 4)]]
        for segments in cases:
            with self.subTest(segments=segments):
                with self.assertRaisesRegex(ContractError, "citation_segments_not_ordered"):
                    self._import_synthetic_pages(pages, [self._multi_citation(segments)])

    def test_ambiguous_legacy_and_segments_shape_is_rejected(self):
        page = "原创合成示例。"
        item = {**self._multi_citation([self._segment(1, page)]), "quote": page}
        with self.assertRaisesRegex(ContractError, "citation_shape_ambiguous"):
            self._import_synthetic_pages([page], [item])

    def test_missing_unreadable_and_mismatched_cited_segments_are_rejected(self):
        pages = ["原创合成示例。", " \n"]
        cases = [([self._segment(3, "不存在")], "citation_page_not_read"),
                 ([self._segment(2, pages[1])], "citation_page_unreadable"),
                 ([{**self._segment(1, pages[0]), "quote": "改写"}], "citation_text_mismatch"),
                 ([], "citation_segments_required")]
        for segments, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(ContractError, code):
                self._import_synthetic_pages(pages, [self._multi_citation(segments)])

    def test_legacy_single_page_shape_context_and_fields_remain_available(self):
        page = "前" * 80 + "原创合成引用🙂" + "后" * 80
        item = {"id": "legacy", **self._segment(1, page, 80, 87),
                "proposition": "合成命题", "relation": "context"}
        result = self._import_synthetic_pages([page], [item])["citations"][0]
        for key, value in item.items():
            self.assertEqual(value, result[key])
        self.assertNotIn("segments", result)
        self.assertEqual(page[20:147], result["context"])
        self.assertEqual("verified", result["literal_binding"])
        self.assertEqual("not_verified", result["proposition_support"])
        self.assertEqual("not_performed", result["original_page_reopened"])

    def test_known_pdf_tail_omission_keeps_successful_citation_partial(self):
        raw = pdf_fixture()
        (self.root / "source.pdf").write_bytes(raw)
        page = "SYNTHETIC FIRST"
        request = {**self.request, "expected_sha256": sha256_bytes(raw),
            "pdf_tools": {"pdfinfo": {}, "pdftotext": {}},
            "citations": [self._multi_citation([self._segment(1, page)])]}
        # 原创两页PDF，替身只模拟工具漏提尾页；不声称执行了真实工具。
        with patch.object(sources, "_tool", side_effect=[Path("pdfinfo"), Path("pdftotext")]), \
                patch.object(sources, "_run_pdf", side_effect=[b"Pages: 2\n", b"SYNTHETIC FIRST\f"]):
            report = sources.import_local(self.root, "source.pdf", request, synthetic=True)
        self.assertEqual(2, report["extraction"]["total_pages"])
        self.assertEqual([2], report["extraction"]["missing_or_unreadable_pages"])
        self.assertEqual("partial", report["extraction"]["coverage"])
        self.assertEqual("partial", report["citations"][0]["coverage"])
        self.assertEqual("verified", report["citations"][0]["literal_binding"])
        self.assertEqual("needs_evidence", report["status"])
        self.assertFalse(report["full_text_absence_allowed"])

    def test_skipped_blank_middle_page_is_reported_in_citation_span(self):
        pages = ["原创合成首段。", "", "合成末段。"]
        citation = self._multi_citation([self._segment(1, pages[0]), self._segment(3, pages[2])])
        report = self._import_synthetic_pages(pages, [citation])
        self.assertEqual([2], report["citations"][0]["missing_or_unreadable_pages"])
        self.assertEqual("gapped", report["citations"][0]["range_continuity"])
        self.assertEqual("partial", report["citations"][0]["coverage"])
        report = self._import_synthetic_pages(pages, [])
        self.assertEqual("partial", report["extraction"]["coverage"])
        self.assertEqual("needs_evidence", report["status"])

    def test_repeated_words_bind_distinct_offsets_without_text_search(self):
        word = "原创合成原文"
        page = word * 2
        citation = self._multi_citation([
            self._segment(1, page, 0, len(word)), self._segment(1, page, len(word))])
        bound = self._import_synthetic_pages([page], [citation])["citations"][0]
        self.assertEqual("complete", bound["coverage"])
        self.assertEqual([0, len(word)], [part["start"] for part in bound["segments"]])
        self.assertEqual([word, word], [part["quote"] for part in bound["segments"]])

    def test_multi_segment_citation_is_available_through_existing_cli(self):
        pages = self.raw.decode("utf-8").split("\f")
        request = {**self.request, "citations": [self._multi_citation([
            self._segment(1, pages[0]), self._segment(2, pages[1])])]}
        (self.root / "request.json").write_bytes(canonical_bytes(request))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, sources.main(["--root", str(self.root), "--input", "source.txt",
                "--request", "request.json", "--output", "citation.json", "--synthetic"]))
        report = json.loads((self.root / "citation.json").read_text(encoding="utf-8"))
        self.assertEqual("complete", report["citations"][0]["coverage"])
        self.assertEqual(pages, [part["quote"] for part in report["citations"][0]["segments"]])
        self.assertEqual(self.raw, (self.root / "source.txt").read_bytes())

    def test_pdf_user_page_count_is_never_verified(self):
        raw = pdf_fixture()
        (self.root / "source.pdf").write_bytes(raw)
        request = {**self.request, "expected_sha256": sha256_bytes(raw),
            "transcription": {"total_pages": 1, "pages": [{"page": 1, "text": "FIRST"}]}}
        report = sources.import_local(self.root, "source.pdf", request, synthetic=True)
        self.assertIsNone(report["extraction"]["total_pages"])
        self.assertEqual("not_verified", report["extraction"]["page_count_status"])
        self.assertEqual("partial", report["extraction"]["coverage"])
        self.assertFalse(report["full_text_absence_allowed"])

    def test_invalid_pdf_html_and_metadata_only_fail(self):
        (self.root / "fake.pdf").write_bytes(b"<html>denied</html>")
        with self.assertRaisesRegex(ContractError, "pdf_signature_invalid"):
            sources.import_local(self.root, "fake.pdf", {**self.request, "expected_sha256": sha256_bytes(b"<html>denied</html>")}, synthetic=True)
        with self.assertRaisesRegex(ContractError, "fulltext_access_not_proven"):
            sources.import_local(self.root, "source.txt", {**self.request, "access_status": "metadata_only"}, synthetic=True)

    def test_real_preflight_occurs_before_material_read(self):
        proof = admission(self.root, {"source.txt": self.request["expected_sha256"]}, [], self.request)
        proof["environment"]["data_paths"][0]["verified"] = False
        with patch.object(Path, "open", side_effect=AssertionError("material read before preflight")):
            with self.assertRaisesRegex(ContractError, "data_path_unverified"):
                sources.import_local(self.root, "source.txt", self.request, admission=proof)
        with self.assertRaisesRegex(ContractError, "authorization_required"):
            sources.import_local(self.root, "source.txt", self.request)

    def test_authorized_local_entry_uses_current_time_and_binding(self):
        proof = admission(self.root, {"source.txt": self.request["expected_sha256"]}, [], self.request)
        result = sources.import_local(self.root, "source.txt", self.request, admission=proof)
        self.assertEqual("authorized_case", result["mode"])
        self.assertEqual("caller_responsibility_not_authenticated", result["authorization_authenticity"])
        self.assertEqual("change_detection_not_signature_or_trusted_anchor", result["authorization_binding_scope"])
        proof["now"] = "2000-01-01T00:00:00Z"
        proof["permissions"][0]["valid_until"] = "2000-01-02T00:00:00Z"
        with self.assertRaisesRegex(ContractError, "permission_not_proven"):
            sources.import_local(self.root, "source.txt", self.request, admission=proof)
        proof = admission(self.root, {"wrong.txt": self.request["expected_sha256"]}, [], self.request)
        with self.assertRaisesRegex(ContractError, "input_scope_mismatch"):
            sources.import_local(self.root, "source.txt", self.request, admission=proof)

    def test_scope_hash_path_drift_and_payload_change_rejected(self):
        proof = admission(self.root, {"source.txt": self.request["expected_sha256"]}, [], self.request)
        altered = copy.deepcopy(self.request)
        altered["identity"]["edition"] = "2024"
        with self.assertRaisesRegex(ContractError, "payload_binding_mismatch"):
            sources.import_local(self.root, "source.txt", altered, admission=proof)
        (self.root / "source.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(ContractError, "input_hash_changed"):
            sources.import_local(self.root, "source.txt", self.request, admission=proof)
        with self.assertRaises(ContractError):
            sources.import_local(self.root, "../source.txt", self.request, synthetic=True)

    def test_absence_is_only_within_observed_text_not_semantic_certification(self):
        request = {**self.request, "queries": [{"id": "q1", "text": "没有此词"}]}
        report = sources.import_local(self.root, "source.txt", request, synthetic=True)
        self.assertEqual("not_found_in_checked_scope", report["queries"][0]["state"])
        self.assertFalse(report["full_text_absence_allowed"])

    def test_cli_requires_mode_and_writes_new_report(self):
        (self.root / "request.json").write_bytes(canonical_bytes(self.request))
        args = ["--root", str(self.root), "--input", "source.txt", "--request", "request.json", "--output", "evidence.json"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(2, sources.main(args))
            self.assertEqual(0, sources.main(args + ["--synthetic"]))
            self.assertEqual(2, sources.main(args + ["--synthetic"]))
        report = json.loads((self.root / "evidence.json").read_text(encoding="utf-8"))
        self.assertEqual("synthetic", report["mode"])
        self.assertEqual(self.raw, (self.root / "source.txt").read_bytes())

    def test_authorized_cli_request_is_hash_bound_before_parse(self):
        request_raw = canonical_bytes(self.request)
        (self.root / "request.json").write_bytes(request_raw)
        proof = admission(self.root, {"source.txt": self.request["expected_sha256"], "request.json": sha256_bytes(request_raw)}, ["evidence.json"], self.request)
        (self.root / "authorization.json").write_bytes(canonical_bytes(proof))
        args = ["--root", str(self.root), "--input", "source.txt", "--request", "request.json", "--output", "evidence.json", "--authorization", "authorization.json"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, sources.main(args))
        (self.root / "request.json").write_bytes(b"changed")
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(2, sources.main(args))
        self.assertIn("input_hash_changed", output.getvalue())

    def test_actual_pdf_tools_count_and_extract_both_pages(self):
        info = Path("D:/texlive/2026/bin/windows/pdfinfo.exe")
        text = Path("D:/texlive/2026/bin/windows/pdftotext.exe")
        if not info.is_file() or not text.is_file():
            self.skipTest("Explicit local PDF tools unavailable")
        raw = pdf_fixture()
        (self.root / "source.pdf").write_bytes(raw)
        request = {**self.request, "expected_sha256": sha256_bytes(raw),
            "pdf_tools": {"pdfinfo": {"path": str(info), "sha256": sha256_bytes(info.read_bytes())},
                          "pdftotext": {"path": str(text), "sha256": sha256_bytes(text.read_bytes())}}}
        report = sources.import_local(self.root, "source.pdf", request, synthetic=True)
        self.assertEqual(2, report["extraction"]["total_pages"])
        self.assertEqual("verified", report["extraction"]["page_count_status"])
        self.assertEqual("complete", report["extraction"]["coverage"])
        self.assertIn("LAST", report["pages"][1]["text"])
        self.assertEqual("not_performed", report["visual_review"])


def consumption_package(root, texts=None):
    """原创文本原件与实际import报告；报告故意采用非canonical原始编码。"""
    texts = texts or ["仅在设备就绪时设备应启动。维护模式除外。", "设备周期为10 ms。"]
    raw = "\f".join(texts).encode("utf-8")
    (root / "original.txt").write_bytes(raw)
    citations = [{"id": "CITE-1", "proposition": texts[0], "relation": "supports",
                  "segments": [{"page": n, "start": 0, "end": len(text), "quote": text}
                               for n, text in enumerate(texts, 1)]}]
    report = sources.import_local(root, "original.txt", {
        "expected_sha256": sha256_bytes(raw), "identity": identity(),
        "access_status": "local_authorized", "citations": citations}, synthetic=True)
    encoded = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    (root / "report.json").write_bytes(encoded)
    payload = {"version": "v2", "clauses": [{"id": "C-1", "text": "".join(texts)}],
        "source_reports": [{"report_id": "R-1", "path": "report.json",
                            "sha256": sha256_bytes(encoded), "source": identity()}],
        "source_bindings": [{"binding_id": "B-1", "target_type": "clause", "target_id": "C-1",
                             "report_id": "R-1", "citation_ids": ["CITE-1"],
                             "proposition": "".join(texts), "version": "v2"}]}
    return payload, report


class SourceConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.payload, self.report = consumption_package(self.root)

    @staticmethod
    def codes(report):
        return {item["code"] for item in report["issues"]}

    def verify(self, **kwargs):
        return sources.verify_reports(self.root, self.payload, synthetic=True, **kwargs)

    def rewrite_report(self):
        raw = canonical_bytes(self.report) + b"\n"
        (self.root / "report.json").write_bytes(raw)
        self.payload["source_reports"][0]["sha256"] = sha256_bytes(raw)

    def test_consumes_actual_raw_hashes_segments_and_target_proposition(self):
        before = copy.deepcopy(self.payload)
        result = self.verify()
        self.assertEqual([], result["issues"])
        row = result["source_trace"][0]
        self.assertEqual(self.payload["source_reports"][0]["sha256"], row["report_sha256"])
        self.assertNotEqual(digest(self.report), row["report_sha256"])
        self.assertEqual(self.report["original_sha256"], row["original_sha256"])
        self.assertEqual([1, 2], [s["page"] for s in row["citations"][0]["segments"]])
        self.assertEqual("complete", row["coverage"])
        self.assertEqual("not_verified", row["proposition_support"])
        self.assertEqual(self.payload["source_bindings"][0]["proposition"], row["proposition"])
        self.assertEqual("v2", row["version"])
        self.assertEqual(before, self.payload)
        self.assertTrue(sources.is_current_verification(self.payload, result))
        self.assertFalse(sources.is_current_verification(self.payload, dict(result)))

    def test_caller_passed_verified_flags_do_not_replace_actual_files(self):
        self.payload["source_reports"][0]["verified"] = True
        self.payload["source_bindings"][0]["status"] = "passed"
        (self.root / "report.json").unlink()
        result = self.verify()
        self.assertTrue(result["issues"])
        self.assertNotEqual("verified", result["source_trace"][0]["state"])

    def test_current_original_and_report_byte_changes_are_rejected(self):
        (self.root / "original.txt").write_bytes(b"changed")
        self.assertIn("input_hash_changed", self.codes(self.verify()))
        self.payload, self.report = consumption_package(self.root)
        with (self.root / "report.json").open("ab") as stream:
            stream.write(b" ")
        self.assertIn("input_hash_changed", self.codes(self.verify()))

    def test_self_consistent_forged_page_text_is_not_original_evidence(self):
        self.report["pages"][0]["text"] = "伪造内容"
        self.report["extracted_text_sha256"] = digest(self.report["pages"])
        self.rewrite_report()
        self.assertIn("source_report_text_changed", self.codes(self.verify()))

    def test_missing_citation_edition_and_applicable_version_are_explicit(self):
        self.payload["source_bindings"][0]["citation_ids"] = ["missing"]
        self.assertIn("source_citation_missing", self.codes(self.verify()))
        self.payload["source_bindings"][0]["citation_ids"] = ["CITE-1"]
        self.payload["source_reports"][0]["source"]["edition"] = "2025"
        self.assertIn("source_identity_mismatch", self.codes(self.verify()))
        self.payload["source_reports"][0]["source"] = identity()
        self.payload["source_bindings"][0]["version"] = "v1"
        self.assertIn("source_target_version_mismatch", self.codes(self.verify()))

    def test_gapped_and_transcription_coverage_never_upgrade(self):
        self.report["citations"][0]["segments"][0]["start"] = 2
        self.report["citations"][0]["segments"][0]["quote"] = self.report["pages"][0]["text"][2:]
        self.report["citations"][0]["segments"][0]["end"] -= 1
        self.report["citations"][0]["segments"][0]["quote"] = self.report["pages"][0]["text"][2:-1]
        self.rewrite_report()
        self.assertIn("source_citation_coverage_partial", self.codes(self.verify()))
        original = pdf_fixture()
        (self.root / "original.pdf").write_bytes(original)
        text = "原创合成转写。"
        self.report = sources.import_local(self.root, "original.pdf", {
            "expected_sha256": sha256_bytes(original), "identity": identity(),
            "access_status": "read_only", "transcription": {"pages": [{"page": 1, "text": text}]},
            "citations": [{"id": "CITE-1", "page": 1, "start": 0, "end": len(text),
                           "quote": text, "proposition": text, "relation": "supports"}]}, synthetic=True)
        self.rewrite_report()
        result = self.verify()
        self.assertIn("source_original_text_not_verified", self.codes(result))
        self.assertEqual("partial", result["source_trace"][0]["coverage"])
        self.assertEqual("not_verified", result["source_trace"][0]["page_count_status"])

    def test_dependency_hashes_are_local_and_reviewed_hash_expires(self):
        second = copy.deepcopy(self.payload["source_bindings"][0])
        self.payload["clauses"].append({"id": "C-2", "text": "无关条款。"})
        second.update(binding_id="B-2", target_id="C-2", proposition="独立命题")
        self.payload["source_bindings"].append(second)
        initial = self.verify()["source_trace"]
        first_hash, second_hash = [row["dependency_hash"] for row in initial]
        self.payload["source_bindings"][0]["reviewed_dependency_hash"] = first_hash
        self.payload["source_bindings"][0]["proposition"] = "改变命题"
        result = self.verify()["source_trace"]
        self.assertNotEqual(first_hash, result[0]["dependency_hash"])
        self.assertEqual("stale", result[0]["review_status"])
        self.assertEqual(second_hash, result[1]["dependency_hash"])

    def test_comment_reason_verification_and_note_targets_are_bound(self):
        self.payload.update(comments=[{"id": "COM-1", "text": "原意见", "version": "v2"}],
            comment_outcomes=[{"comment_id": "COM-1", "reason": "处理理由"}],
            verification_matrix=[{"id": "V-1", "clause_id": "C-1", "method": "合成检查"}],
            compilation_note={"version": "v2", "sections": [{"id": "N-1", "body": "说明原文"}]})
        template = self.payload["source_bindings"][0]
        for n, (kind, key) in enumerate((("comment_reason", "COM-1"), ("verification", "V-1"),
                                        ("compilation_note", "N-1")), 2):
            self.payload["source_bindings"].append({**template, "binding_id": f"B-{n}",
                                                  "target_type": kind, "target_id": key})
        result = self.verify()
        self.assertEqual([], result["issues"])
        self.assertEqual(4, len(result["source_trace"]))
        self.assertTrue(all(row["target_hash"] for row in result["source_trace"]))

    def test_report_with_string_source_is_identity_bound_and_citations_are_bounded(self):
        self.payload["source_reports"][0]["source"] = "synthetic:S1"
        result = self.verify()
        self.assertEqual(identity(), result["source_trace"][0]["identity"])
        self.assertEqual([], result["issues"])
        self.report["citations"] = [None]
        self.rewrite_report()
        self.assertTrue(self.verify()["issues"])

    def test_admission_precedes_open_and_is_rechecked_for_original(self):
        files = {"report.json": self.payload["source_reports"][0]["sha256"],
                 "original.txt": self.report["original_sha256"]}
        proof = admission(self.root, files, [], self.payload)
        proof["permissions"][0]["valid_until"] = "2000-01-01T00:00:00Z"
        with patch.object(Path, "open", side_effect=AssertionError("read before admission")):
            with self.assertRaisesRegex(ContractError, "permission_not_proven"):
                sources.verify_reports(self.root, self.payload, admission=proof)
        proof = admission(self.root, files, [], self.payload)
        read = sources.read_bound
        def expire_after_report(*args, **kwargs):
            raw = read(*args, **kwargs)
            proof["permissions"][0]["valid_until"] = "2000-01-01T00:00:00Z"
            return raw
        with patch.object(sources, "read_bound", side_effect=expire_after_report):
            result = sources.verify_reports(self.root, self.payload, admission=proof)
        self.assertIn("permission_not_proven", self.codes(result))

    def test_original_must_have_its_own_expected_hash_in_current_admission(self):
        files = {"report.json": self.payload["source_reports"][0]["sha256"]}
        proof = admission(self.root, files, [], self.payload)
        opened = []
        original_open = Path.open
        def track(path, *args, **kwargs):
            opened.append(path.name)
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", track):
            result = sources.verify_reports(self.root, self.payload, admission=proof)
        self.assertIn("input_scope_mismatch", self.codes(result))
        self.assertNotIn("original.txt", opened)

    def test_linked_original_is_rejected_even_inside_root(self):
        import os
        os.link(self.root / "original.txt", self.root / "alias.txt")
        self.assertIn("file_alias_forbidden", self.codes(self.verify()))

    def test_offline_response_classifier_distinguishes_acquisition_states(self):
        request = {"url": "https://std.samr.gov.cn/gb/search/gbQueryPage?pageSize=15&pageNumber=1",
                   "retrieved_at": "2026-11-13T12:00:00Z", "http_status": 200,
                   "content_type": "application/json"}
        cases = [({}, "not_configured"),
                 ({"configured": True, "transport_status": "timeout"}, "timeout"),
                 ({"configured": True, "raw": b"{}", "request": request}, "page_changed"),
                 ({"configured": True, "raw": b'{"total":0,"pageNumber":1,"rows":[]}',
                   "request": request}, "zero_hits"),
                 ({"configured": True, "raw": b'{"total":100,"pageNumber":1,"rows":[]}',
                   "request": request}, "partial"),
                 ({"configured": True, "request": {**request, "http_status": 403}}, "access_denied")]
        cases.extend(({"configured": True, key: True}, "access_denied")
                     for key in ("preview_only", "login_required", "captcha_required"))
        for kwargs, expected in cases:
            with self.subTest(expected=expected, kwargs=kwargs):
                value = sources.classify_acquisition(**kwargs)
                self.assertEqual(expected, value["status"])
                self.assertEqual("not_performed", value["network"])
                self.assertEqual("not_performed", value["download"])


if __name__ == "__main__":
    unittest.main()
