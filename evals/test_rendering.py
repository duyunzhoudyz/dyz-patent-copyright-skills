"""渲染AC的确定性分支；合成PNG头只测契约，不冒充真实浏览器证据。"""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.core import ContractError, sha256_bytes
from tools.rendering import (CHECKS, preview_scope, render_preview,
                             validate_rendering_evidence, write_preview)

FIXTURE = Path(__file__).parent / "fixtures" / "rendering" / "cases.json"
NOW = "2026-10-31T12:00:00Z"
PACKAGE = sha256_bytes(b"synthetic manifest")


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.content = self.cases["markdown"].encode("utf-8")
        self.preview = render_preview("example.md", self.content, PACKAGE)
        self.scope = preview_scope("example.md")
        self.raw = {"screen": b"\x89PNG\r\n\x1a\nSYNTHETIC_CONTRACT_TEST_NOT_A_REAL_SCREENSHOT"}
        observation = {"status": "passed", "issues": [], "scope": self.scope,
                       "notes": "synthetic assertion for validator unit test only"}
        self.record = {k: self.preview[k] for k in ("source_name", "source_sha256",
                       "manifest_hash", "renderer", "renderer_version", "rendered_artifact_hash")}
        self.record.update(status="passed", reviewer={"id": "unit-test", "kind": "synthetic"},
                           checked_at=NOW, scope=self.scope,
                           evidence={"executed": True, "browser": {"name": "test-double", "version": "0"},
                                     "artifacts": [{"id": "screen", "kind": "screenshot_png",
                                                    "sha256": sha256_bytes(self.raw["screen"])}],
                                     "dom": copy.deepcopy(observation), "visual": copy.deepcopy(observation)})

    def validate(self, **changes):
        args = {"name": "example.md", "content": self.content, "manifest_hash": PACKAGE,
                "artifact": self.preview["html"].encode("utf-8"), "evidence_artifacts": self.raw,
                "required_scope": self.scope, "now": NOW}
        args.update(changes)
        return validate_rendering_evidence(self.record, **args)

    def test_minimal_same_package_install_without_business_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "tools"
            package.mkdir()
            source = Path(__file__).resolve().parents[1] / "tools"
            for name in ("__init__.py", "core.py", "rendering.py"):
                shutil.copy2(source / name, package / name)
            code = ("from tools.rendering import render_preview; "
                    "p=render_preview('demo.md',b'# Demo\\n\\nSafe text','0'*64); "
                    "assert p['status']=='preview_created'; "
                    "assert p['rendering']=='not_executed'; print('isolated package OK')")
            completed = subprocess.run([sys.executable, "-c", code], cwd=folder,
                                       capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "isolated package OK")

    def test_markdown_actual_headings_table_code_and_paragraphs(self):
        html = self.preview["html"]
        self.assertEqual(self.preview["status"], "preview_created")
        for marker in ("<h1>合成候选文档</h1>", "<table>", "<th>参数</th>", "<p>当工作温度",
                       "<code>python counter.py</code>", "class=\"source-page\"", "±1 ms"):
            self.assertIn(marker, html)
        self.assertEqual(self.preview["rendering"], "not_executed")
        self.assertEqual(self.preview["rendered_artifact_hash"], sha256_bytes(html.encode()))

    def test_plain_text_escape_and_preserve_source_lines(self):
        content = '<script>alert(1)</script>\n<img src="file:///secret"> & < >\n'
        preview = render_preview("example.txt", content.encode(), PACKAGE)
        self.assertNotIn("<script>", preview["html"])
        self.assertIn("&lt;script&gt;", preview["html"])
        self.assertIn("&amp; &lt; &gt;", preview["html"])
        self.assertEqual(preview["html"].count('class="source-line"'), 2)

    def test_no_implicit_file_reads_or_network(self):
        with patch.object(Path, "open", side_effect=AssertionError("file read")), patch(
                "socket.socket", side_effect=AssertionError("network")):
            render_preview("example.txt", b"file:///private https://invalid.test", PACKAGE)
            self.assertEqual(self.validate()["status"], "consistent")

    def test_passive_svg_multiline_and_local_marker(self):
        preview = render_preview("good.svg", self.cases["good_svg"].encode(), PACKAGE)
        self.assertIn("<tspan", preview["html"])
        svg = ('<svg viewBox="0 0 100 100"><defs><marker id="arrow" markerWidth="8" markerHeight="8">'
               '<path d="M0,0 L8,4 L0,8 Z"/></marker></defs>'
               '<path d="M10,10 L80,80" marker-end="url(#arrow)"/></svg>')
        self.assertEqual(render_preview("marker.svg", svg.encode(), PACKAGE)["status"], "preview_created")

    def test_malicious_svg_elements_and_attributes_rejected(self):
        attacks = ['<script>alert(1)</script>', '<foreignObject><p>x</p></foreignObject>',
                   '<image href="file:///private"/>', '<use href="#x"/>', '<style>@import "x";</style>',
                   '<a href="https://invalid.test">x</a>', '<animate attributeName="x"/>',
                   '<rect onclick="alert(1)"/>', '<rect style="fill:url(https://invalid.test)"/>',
                   '<rect fill="url(https://invalid.test/x)"/>', '<rect opacity="0"/>',
                   '<rect transform="translate(-1000)"/>', '<metadata>hidden</metadata>',
                   '<svg viewBox="0 0 1 1"/>', '<text xmlns="urn:other">x</text>']
        for attack in attacks:
            with self.subTest(attack=attack), self.assertRaises(ContractError):
                render_preview("attack.svg", ('<svg viewBox="0 0 100 100">' + attack + '</svg>').encode(), PACKAGE)

    def test_svg_declaration_entities_comments_processing_instruction(self):
        for prefix in ('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///private">]>', '<?xml version="1.0"?>', '<!--hidden-->'):
            with self.subTest(prefix=prefix), self.assertRaises(ContractError):
                render_preview("x.svg", (prefix + '<svg viewBox="0 0 100 100"/>').encode(), PACKAGE)

    def test_svg_invalid_geometry_and_unrendered_text(self):
        for svg in ('<svg/>', '<svg viewBox="0 0 nan 100"/>', '<svg viewBox="0 0 0 100"/>',
                    '<svg viewBox="0 0 1 1">hidden</svg>', '<svg viewBox="0 0 1 1"><g/>hidden</svg>',
                    '<svg viewBox="0 0 1 1"><path marker-end="url(#missing)"/></svg>'):
            with self.subTest(svg=svg), self.assertRaises(ContractError):
                render_preview("x.svg", svg.encode(), PACKAGE)

    def test_safe_svg_does_not_claim_no_visual_crop(self):
        preview = render_preview("bad.svg", self.cases["clipped_svg"].encode(), PACKAGE)
        self.assertEqual(preview["status"], "preview_created")
        self.assertEqual(preview["rendering"], "not_executed")

    def test_markdown_unsupported_preserved_and_blocks(self):
        for text in ('![image](file:///private)', '[link](https://invalid.test)', '<script>x</script>',
                     '**bold**', '> quote', '    indented', '~~~python', '---', 'a\\b',
                     '| a | b |\n| --- | --- |\n| one |', '```\nunclosed'):
            with self.subTest(text=text):
                preview = render_preview("x.md", text.encode(), PACKAGE)
                self.assertEqual(preview["status"], "blocked")
                self.assertTrue(preview["issues"])
                self.assertNotIn("<script>", preview["html"])
                self.assertNotIn('<img ', preview["html"])

    def test_literal_markdown_escapes_and_identifiers_render_without_active_content(self):
        source = (r'\[链接\]\(https://example.invalid\) \*保留\* \`原文\` '
                  r'C:\\synthetic\\file \_范围\_ omitted_matches source_partial '
                  r'\#标题 \|表格字符\| &lt;script&gt; &amp; &#20013; &#x6587;')
        preview = render_preview('literal.md', source.encode(), PACKAGE)
        self.assertEqual(preview['status'], 'preview_created')
        self.assertEqual(preview['issues'], [])
        html = preview['html']
        self.assertIn('[链接](https://example.invalid)', html)
        self.assertIn('*保留* `原文`', html)
        self.assertIn('C:\\synthetic\\file _范围_ omitted_matches source_partial', html)
        self.assertIn('#标题 |表格字符| &lt;script&gt; &amp; 中 文', html)
        for active in ('<script>', '<a ', '<em>', '<strong>', '<img '):
            self.assertNotIn(active, html)
        self.assertEqual(preview['rendering'], 'not_executed')

    def test_escaped_code_delimiters_are_not_reinterpreted(self):
        source = r'\`&lt;script&gt;\` 与 `<script>\n&amp;` 与 \[a\]'
        preview = render_preview('code.md', source.encode(), PACKAGE)
        self.assertEqual(preview['status'], 'preview_created')
        self.assertIn('`&lt;script&gt;` 与 <code>&lt;script&gt;\\n&amp;amp;</code> 与 [a]', preview['html'])
        self.assertEqual(preview['html'].count('<code>'), 1)
        self.assertNotIn('<script>', preview['html'])

    def test_unsupported_inline_syntax_still_blocks_and_stays_visible(self):
        for source in (r'a\b', '\\', '**bold**', '_emphasis_', '__strong__',
                       '[link](https://example.invalid)', '<script>x</script>',
                       '`unclosed', '~~deleted~~', 'text  '):
            with self.subTest(source=source):
                preview = render_preview('blocked.md', source.encode(), PACKAGE)
                self.assertEqual(preview['status'], 'blocked')
                self.assertIn('markdown_inline_not_supported', preview['issues'])
                self.assertNotIn('<script>', preview['html'])
                self.assertNotIn('<a ', preview['html'])

    def test_character_references_do_not_hide_control_characters(self):
        for source in ('&#x202e;', '&#8203;', '&NewLine;', '&#9;', '&#x7f;'):
            with self.subTest(source=source), self.assertRaisesRegex(ContractError, 'hidden_control_character'):
                render_preview('control.md', source.encode(), PACKAGE)
        preview = render_preview('literal.md', b'`&#x202e;` &amp;lt;script&amp;gt;', PACKAGE)
        self.assertEqual(preview['status'], 'preview_created')
        self.assertIn('<code>&amp;#x202e;</code>', preview['html'])
        self.assertIn('&amp;lt;script&amp;gt;', preview['html'])

    def test_long_numeric_reference_does_not_exceed_integer_limit(self):
        source = '&#' + '0' * 5000 + '20013; &#' + '9' * 5000 + ';'
        preview = render_preview('numbers.md', source.encode(), PACKAGE)
        self.assertEqual(preview['status'], 'preview_created')
        self.assertIn('<p>中 �</p>', preview['html'])
        with self.assertRaisesRegex(ContractError, 'hidden_control_character'):
            render_preview('control.md', ('&#' + '0' * 5000 + '9;').encode(), PACKAGE)

    def test_paginated_source_no_padding_or_missing_lines(self):
        text = "\n".join(f"第{i}行：" + "中文" * 50 for i in range(1, 86))
        html = render_preview("source.txt", text.encode(), PACKAGE)["html"]
        self.assertEqual(html.count('class="source-page"'), 3)
        self.assertEqual(html.count('class="source-line"'), 85)
        self.assertIn('data-line="85"', html)
        self.assertNotIn('data-line="86"', html)

    def test_encoding_control_and_format_errors(self):
        for name, raw in (("x.txt", b"\xff"), ("x.txt", b"x\x00"), ("x.md", "a\u202eb".encode()),
                          ("x.html", b"<p>x</p>"), ("x.txt", b"x" * 2_000_001)):
            with self.subTest(name=name), self.assertRaises(ContractError):
                render_preview(name, raw, PACKAGE)
        with self.assertRaises(ContractError):
            render_preview("x.txt", b"x", "not-a-hash")

    def test_source_names_reject_paths_and_escape_display(self):
        for name in ("../x.txt", "C:/x.txt", "//server/x.txt", "/x.txt", "x:stream.txt",
                     "a\\x.txt", "a/./x.txt", "a//x.txt", "a\n.txt"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                render_preview(name, b"text", PACKAGE)
        html = render_preview("<b>.txt", b"text", PACKAGE)["html"]
        self.assertIn("&lt;b&gt;.txt", html)
        self.assertNotIn("<b>.txt", html)

    def test_write_new_only_and_root_confinement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_preview(folder, "new.html", self.preview)
            self.assertEqual(path.read_text(encoding="utf-8"), self.preview["html"])
            with self.assertRaises(FileExistsError):
                write_preview(folder, "new.html", self.preview)
            for name in ("../escape.html", "C:/escape.html", "x:stream.html", "new.md"):
                with self.subTest(name=name), self.assertRaises(ContractError):
                    write_preview(folder, name, self.preview)
            altered = {**self.preview, "html": "tampered"}
            with self.assertRaises(ContractError):
                write_preview(folder, "other.html", altered)

    def test_positive_record_is_consistency_not_identity_or_professional_review(self):
        result = self.validate()
        self.assertEqual(result["status"], "consistent")
        self.assertEqual(result["identity_verification"], "not_performed")
        self.assertEqual(result["professional_review"], "not_performed")

    def test_old_source_package_html_renderer_or_name_fails(self):
        for kwargs in ({"content": self.content + b"changed"}, {"manifest_hash": "0" * 64},
                       {"artifact": b"other HTML"}, {"name": "other.md"}):
            with self.subTest(kwargs=list(kwargs)):
                self.assertEqual(self.validate(**kwargs)["status"], "blocked")
        for field in ("renderer", "renderer_version", "rendered_artifact_hash", "source_sha256"):
            original = self.record[field]
            self.record[field] = "old"
            self.assertEqual(self.validate()["status"], "blocked")
            self.record[field] = original

    def test_missing_and_not_executed_records_never_pass(self):
        for field in list(self.record):
            original = self.record.pop(field)
            self.assertEqual(self.validate()["status"], "blocked", field)
            self.record[field] = original
        self.record["evidence"]["executed"] = False
        self.assertIn("rendering_not_executed", self.validate()["issues"])

    def test_scope_mismatch_and_missing_checks(self):
        for scope in ({}, {**self.scope, "media": "print"}, {**self.scope, "checks": CHECKS[:-1]},
                      preview_scope("example.md", width=640)):
            self.record["scope"] = scope
            self.assertEqual(self.validate()["status"], "blocked")
        self.record["scope"] = self.scope
        self.assertIn("required_scope_invalid", self.validate(required_scope={})["issues"])

    def test_failed_dom_or_unexecuted_visual_blocks(self):
        for key in ("dom", "visual"):
            original = self.record["evidence"][key]
            for observation in ({}, {**original, "status": "failed"}, {**original, "issues": ["crop"]},
                                {**original, "notes": ""}, {**original, "scope": {}}):
                self.record["evidence"][key] = observation
                self.assertEqual(self.validate()["status"], "blocked")
            self.record["evidence"][key] = original

    def test_actual_bytes_required_not_path_or_hash_only(self):
        for supplied in ({}, {"screen": b"changed"}, {"screen": "C:/not-read.png"},
                         {**self.raw, "unexpected": b"x"}):
            self.assertEqual(self.validate(evidence_artifacts=supplied)["status"], "blocked")
        self.record["evidence"]["artifacts"] = []
        self.assertEqual(self.validate()["status"], "blocked")

    def test_browser_time_reviewer_and_status_are_required(self):
        for stamp in (None, "bad", "2026-10-31", "2026-11-01T12:00:00Z"):
            self.record["checked_at"] = stamp
            self.assertEqual(self.validate()["status"], "blocked")
        self.record["checked_at"] = NOW
        self.record["evidence"]["browser"] = {"name": "test-double"}
        self.assertIn("browser_version_missing", self.validate()["issues"])
        self.record["status"] = "not_checked"
        self.assertIn("rendering_not_passed", self.validate()["issues"])

    def test_unhashable_record_enums_fail_closed(self):
        self.record["reviewer"]["kind"] = []
        self.assertEqual(self.validate()["status"], "blocked")
        self.record["reviewer"]["kind"] = "synthetic"
        self.record["evidence"]["artifacts"][0]["kind"] = {}
        self.assertEqual(self.validate()["status"], "blocked")

    def test_malformed_evidence_fails_closed(self):
        for evidence in (None, [], {}, {"artifacts": [None, {}, {"id": []}]}):
            self.record["evidence"] = evidence
            self.assertEqual(self.validate()["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
