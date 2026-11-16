"""PDF 物理页核验；仅使用临时合成材料和本地子进程替身。"""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

from tools.software_layout import inspect_pdf


TITLE = "合成软件"
VERSION = "V1.0"


def line(text, y=70, x=60, width=240, height=9):
    attrs = f'xMin="{x}" yMin="{y}" xMax="{x + width}" yMax="{y + height}"'
    return f'<line {attrs}><word {attrs}>{escape(text)}</word></line>'


def pdf_page(lines, number=1, *, header=None, footer=None, width=595.276,
             height=841.89):
    top = line(TITLE + " " + VERSION if header is None else header, 30)
    bottom = line(str(number) if footer is None else footer, 806, x=290, width=15)
    return (f'<page width="{width}" height="{height}"><flow><block>'
            + top + "".join(lines) + bottom + '</block></flow></page>')


def bbox_xml(*pages):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
            '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body><doc>'
            + "".join(pages) + '</doc></body></html>').encode("utf-8")


def code(text="return value", id="row_1"):
    return {"id": id, "kind": "code", "text": text}


class SoftwareLayoutTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dyz-layout-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pdf = self.root / "generated.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\nsynthetic mock input\n")
        self.tool = self.root / "pdftotext.exe"
        self.tool.write_bytes(b"synthetic mocked executable")

    def inspect(self, pages, payload, *, kind="source", side_effect=None,
                returncode=0, **kwargs):
        def run(args, **options):
            if side_effect:
                raise side_effect
            Path(args[-1]).write_bytes(payload)
            return subprocess.CompletedProcess(args, returncode)
        with patch("tools.software_layout.subprocess.run", side_effect=run) as process:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                result = inspect_pdf(
                    self.pdf, pages, kind=kind, title=TITLE, version=VERSION,
                    pdf_text_tool=kwargs.pop("pdf_text_tool", str(self.tool)), **kwargs)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue(), "")
        return result, process

    def codes(self, report):
        return {issue["code"] for issue in report["issues"]}

    def test_missing_glyph_is_blocked_without_echoing_content(self):
        secret = "PRIVATE_SYNTHETIC_哨兵"
        report, _ = self.inspect([[code(secret)]], bbox_xml(pdf_page([line("PRIVATE")])))
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["content_fidelity"]["status"], "blocked")
        self.assertIn("body_text_mismatch", self.codes(report))
        self.assertNotIn(secret, json.dumps(report, ensure_ascii=False))
        self.assertEqual(report["issues"][0]["physical_page"], 1)

    def test_duplicate_and_reordered_text_are_not_normalized_away(self):
        for actual in ("alphaalpha beta", "beta alpha"):
            with self.subTest(actual=actual):
                report, _ = self.inspect([[code("alpha beta")]],
                                         bbox_xml(pdf_page([line(actual)])))
                self.assertIn("body_text_mismatch", self.codes(report))

    def test_actual_extra_and_missing_physical_pages_block(self):
        for pages, payload in (
                ([[code()]], bbox_xml(pdf_page([line("return value")]),
                                    pdf_page([], 2))),
                ([[code()], [code(id="row_2")]],
                 bbox_xml(pdf_page([line("return value")])))):
            with self.subTest(page_count=len(pages)):
                report, _ = self.inspect(pages, payload)
                self.assertIn("physical_page_count_mismatch", self.codes(report))
                self.assertEqual(report["status"], "blocked")

    def test_ordered_unicode_whitespace_and_locator_mapping(self):
        text = "调用(\"雪🚀𠀀\",\t变量)"
        report, process = self.inspect(
            [[code(text)]], bbox_xml(pdf_page([line('调 用 ( "雪🚀𠀀", 变量 )')])))
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["actual_page_count"], 1)
        row = report["physical_pages"][0]["rows"][0]
        self.assertEqual(row["sources"][0]["block_id"], "row_1")
        self.assertEqual(row["sources"][0]["display_row"], 1)
        self.assertEqual(row["bbox"], [60.0, 70.0, 300.0, 79.0])
        args, options = process.call_args
        self.assertEqual(args[0][:4], [str(self.tool), "-bbox-layout", "-enc", "UTF-8"])
        self.assertEqual(args[0][4], str(self.pdf))
        self.assertFalse(options["shell"])
        self.assertLessEqual(options["timeout"], 60)
        self.assertEqual(options["stderr"], subprocess.DEVNULL)
        self.assertFalse(Path(args[0][-1]).exists())

    def test_zero_width_char_is_not_whitespace_normalization(self):
        report, _ = self.inspect([[code("ab")]],
                                 bbox_xml(pdf_page([line("a\u200bb")])))
        self.assertIn("body_text_mismatch", self.codes(report))

    def test_header_body_repetition_is_not_globally_removed(self):
        text = TITLE + " " + VERSION
        report, _ = self.inspect([[code(text)]], bbox_xml(pdf_page([line(text)])))
        self.assertEqual(report["status"], "checked")
        report, _ = self.inspect([[code(text)]], bbox_xml(pdf_page([])))
        self.assertIn("body_text_mismatch", self.codes(report))

    def test_header_footer_have_exact_region_and_page_checks(self):
        for args, issue in (({"header": TITLE + " V9"}, "header_mismatch"),
                            ({"footer": "2"}, "footer_mismatch")):
            with self.subTest(issue=issue):
                report, _ = self.inspect([[code()]],
                    bbox_xml(pdf_page([line("return value")], **args)))
                self.assertIn(issue, self.codes(report))
                self.assertEqual(report["status"], "blocked")

    def test_other_content_in_header_is_not_discarded(self):
        report, _ = self.inspect([[code()]], bbox_xml(pdf_page(
            [line("unrequested body", 45), line("return value")])) )
        self.assertIn("header_mismatch", self.codes(report))
        self.assertIn("body_text_mismatch", self.codes(report))

    def test_non_a4_page_cannot_pass_on_text_alone(self):
        report, _ = self.inspect([[code()]], bbox_xml(pdf_page(
            [line("return value")], width=612, height=792)))
        self.assertIn("page_size_not_a4", self.codes(report))
        self.assertEqual(report["content_fidelity"]["status"], "checked")

    def test_bounds_and_bad_numbers_fail_closed(self):
        payloads = [pdf_page([line("return value", x=530, width=70)]),
                    pdf_page([line("return value", x=-1)]),
                    pdf_page([line("return value", y=782)]),
                    pdf_page([line("return value")]).replace('xMax="300"', 'xMax="NaN"'),
                    pdf_page([line("return value")]).replace('xMin="60"', 'xMin="inf"'),
                    pdf_page([line("return value")]).replace('width="595.276"', 'width="NaN"'),
                    pdf_page([line("return value")]).replace('yMax="79"', 'yMax="69"')]
        for payload in payloads:
            with self.subTest(payload=payload[:65]):
                report, _ = self.inspect([[code()]], bbox_xml(payload))
                self.assertEqual(report["status"], "blocked")
                self.assertTrue(self.codes(report) & {
                    "body_out_of_bounds", "bbox_out_of_page", "invalid_bbox",
                    "invalid_page_size"})

    def test_source_wrap_keeps_text_but_blocks_physical_line_count(self):
        report, _ = self.inspect([[code("long " * 20)]], bbox_xml(pdf_page(
            [line("long " * 10, 70), line("long " * 10, 82)])))
        self.assertEqual(report["content_fidelity"]["status"], "checked")
        self.assertIn("code_line_count_mismatch", self.codes(report))
        self.assertEqual(report["status"], "blocked")

    def test_code_row_boundaries_must_match_even_with_same_page_text(self):
        report, _ = self.inspect([[code("abc"), code("def", "row_2")]],
            bbox_xml(pdf_page([line("ab", 70), line("cdef", 82)])))
        self.assertEqual(report["content_fidelity"]["status"], "checked")
        self.assertIn("code_row_text_mismatch", self.codes(report))
        self.assertEqual(report["status"], "blocked")

    def test_malformed_kind_is_rejected_before_tool(self):
        report, process = self.inspect([[{"id": "x", "kind": [], "text": "x"}]], b"")
        self.assertIn("invalid_page_plan", self.codes(report))
        process.assert_not_called()

    def test_code_fixed_pitch_and_overlap_are_checked(self):
        pages = [[code("one"), code("two", "row_2")]]
        for y, issue in ((84, "code_line_pitch_mismatch"), (75, "body_rows_overlap")):
            with self.subTest(y=y):
                report, _ = self.inspect(pages,
                    bbox_xml(pdf_page([line("one", 70), line("two", y)])))
                self.assertIn(issue, self.codes(report))
        report, _ = self.inspect(pages,
            bbox_xml(pdf_page([line("one", 70, height=16), line("two", 82)])))
        self.assertIn("code_glyph_height_exceeds_pitch", self.codes(report))

    def test_mixed_font_boxes_do_not_pretend_to_measure_baseline_pitch(self):
        blocks = [code("ascii"), code("中文", "row_2"), code("末行", "row_3")]
        report, _ = self.inspect([blocks], bbox_xml(pdf_page([
            line("ascii", 70, height=10.521),
            line("中文", 80.749, height=11.871),
            line("末行", 92.749, height=11.871),
        ])))
        self.assertEqual(report["status"], "checked")
        pitch = report["physical_pages"][0]["line_pitch_check"]
        self.assertEqual(pitch["status"], "partial_font_metrics")
        self.assertEqual(pitch["checked_pairs"], 1)
        self.assertEqual(pitch["unmeasured_pairs"], 1)
        self.assertEqual(pitch["baseline_verified"], False)
        self.assertIn("mixed_font_baselines_not_observable", report["limitations"])

    def test_blank_code_rows_not_counted_and_pitch_accounts_for_gaps(self):
        blocks = [code("one"), code("\t  ", "row_2"), code("two", "row_3")]
        report, _ = self.inspect([blocks],
            bbox_xml(pdf_page([line("one", 70), line("two", 94)])))
        self.assertEqual(report["status"], "checked")
        page = report["physical_pages"][0]
        self.assertEqual(page["nonblank_physical_lines"], 2)
        self.assertEqual(page["unobservable_blank_rows"], 1)
        self.assertIsNone(page["blocks"][1]["bbox"])
        self.assertIn("blank_rows_not_observable", report["limitations"])

    def test_source_and_manual_thresholds_only_apply_to_nonfinal_pages(self):
        for kind, minimum in (("source", 50), ("manual", 30)):
            with self.subTest(kind=kind):
                block = code() if kind == "source" else {
                    "id": "paragraph_1", "kind": "paragraph", "text": "return value"}
                report, _ = self.inspect([[block], [dict(block, id="last")]],
                    bbox_xml(pdf_page([line("return value")]),
                             pdf_page([line("return value")], 2)), kind=kind)
                self.assertEqual(report["content_fidelity"]["status"], "checked")
                issues = [i for i in report["issues"] if i["code"] == "min_lines_unmet"]
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]["physical_page"], 1)
                self.assertEqual(issues[0]["required"], minimum)
                self.assertEqual(report["layout_compliance"]["status"], "blocked")

    def test_fifty_nonblank_code_rows_can_pass(self):
        blocks = [code(f"value_{n} = {n}", f"row_{n}") for n in range(50)]
        text_lines = [line(b["text"], 70 + 12 * n) for n, b in enumerate(blocks)]
        report, _ = self.inspect([blocks, [code("last", "last")]],
            bbox_xml(pdf_page(text_lines), pdf_page([line("last")], 2)))
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["physical_pages"][0]["nonblank_physical_lines"], 50)

    def test_manual_wrapping_maps_multiple_rows_to_block(self):
        blocks = [{"id": "p1", "kind": "paragraph", "text": "First second third"}]
        report, _ = self.inspect([blocks], bbox_xml(pdf_page(
            [line("First second", 70), line("third", 84)])), kind="manual")
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["physical_pages"][0]["blocks"][0]["physical_lines"], [1, 2])

    def test_image_text_is_checked_but_image_layout_not_auto_approved(self):
        image = {"id": "image_1", "kind": "image", "text": "画面说明",
                 "png": b"synthetic", "width": 50, "height": 30}
        report, _ = self.inspect([[image]], bbox_xml(pdf_page([line("画面说明")])),
                                 kind="manual")
        self.assertEqual(report["content_fidelity"]["status"], "checked")
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["check_scope"], "pdf_text_geometry_and_candidate_pagination")
        self.assertEqual(report["image_rendering"], "not_verified")
        self.assertEqual(report["visual_review"], "not_performed")
        self.assertEqual(report["physical_pages"][0]["image_rendering"], "not_verified")
        self.assertEqual(report["physical_pages"][0]["visual_review"], "not_performed")
        self.assertEqual(report["image_fidelity"]["status"], "not_checked")

    def test_image_threshold_exception_requires_separate_evidence(self):
        image = {"id": "img", "kind": "image", "text": "caption",
                 "png": b"synthetic", "width": 20, "height": 20}
        report, _ = self.inspect([[image], [{"id": "p", "kind": "paragraph",
                                            "text": "last"}]], bbox_xml(
            pdf_page([line("caption")]), pdf_page([line("last")], 2)), kind="manual")
        self.assertIn("image_min_lines_exception_unconfirmed", self.codes(report))

    def test_worksheet_does_not_apply_manual_threshold(self):
        pages = [[{"id": "p1", "kind": "paragraph", "text": "first"}],
                 [{"id": "p2", "kind": "paragraph", "text": "last"}]]
        report, _ = self.inspect(pages, bbox_xml(pdf_page([line("first")]),
            pdf_page([line("last")], 2)), kind="worksheet")
        self.assertEqual(report["status"], "checked")

    def test_missing_relative_or_wrong_tool_never_spawns(self):
        for tool in ("pdftotext", str(self.root / "missing" / "pdftotext.exe"),
                     str(self.root / "python.exe")):
            with self.subTest(tool=tool):
                report, process = self.inspect([[code()]], b"", pdf_text_tool=tool)
                self.assertEqual(report["status"], "blocked")
                process.assert_not_called()

    def test_tool_failure_and_timeout_never_expose_stderr(self):
        for error in (subprocess.TimeoutExpired("synthetic", 60,
                         output=b"PRIVATE_SOURCE", stderr=b"PRIVATE_SOURCE"),
                      OSError("PRIVATE_SOURCE")):
            with self.subTest(type=type(error).__name__):
                report, _ = self.inspect([[code()]], b"", side_effect=error)
                self.assertEqual(report["status"], "blocked")
                self.assertNotIn("PRIVATE_SOURCE", json.dumps(report))
        report, _ = self.inspect([[code()]], b"PRIVATE_SOURCE", returncode=1)
        self.assertIn("pdf_text_tool_failed", self.codes(report))
        self.assertNotIn("PRIVATE_SOURCE", json.dumps(report))

    def test_malformed_empty_and_entity_xml_fail_closed(self):
        for payload in (b"", b"PRIVATE_SOURCE", bbox_xml(),
                        b'<!DOCTYPE doc [<!ENTITY body "PRIVATE_SOURCE">]><doc>&body;</doc>'):
            with self.subTest(payload=payload[:20]):
                report, _ = self.inspect([[code()]], payload)
                self.assertEqual(report["status"], "blocked")
                self.assertNotIn("PRIVATE_SOURCE", json.dumps(report))

    def test_invalid_plan_fails_before_tool(self):
        invalid = [[], [[]], [[code("line1\nline2")]],
                   [[code(), code("duplicate", "row_1")]],
                   [[{"id": "x", "kind": "unknown", "text": "abc"}]]]
        for pages in invalid:
            with self.subTest(pages=pages):
                report, process = self.inspect(pages, b"")
                self.assertIn("invalid_page_plan", self.codes(report))
                process.assert_not_called()

    def test_non_pdf_input_fails_without_tool(self):
        self.pdf.write_bytes(b"PRIVATE_SOURCE")
        report, process = self.inspect([[code()]], b"")
        self.assertIn("invalid_pdf_input", self.codes(report))
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
