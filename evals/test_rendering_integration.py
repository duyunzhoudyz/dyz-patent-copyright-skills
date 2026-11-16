"""WP02/04跨模块契约回归；PNG头是明确的合成替身，不是真实截图。"""
import base64
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from html.parser import HTMLParser
from unittest.mock import patch

from tools import cli, core, disclosure, rendering
from evals.test_disclosure import NOW, make_case
from evals.test_patent import document, search_payload

REPO = Path(__file__).resolve().parents[1]
SYNTHETIC_PNG = b"\x89PNG\r\n\x1a\nSYNTHETIC_CONTRACT_DOUBLE_NOT_A_SCREENSHOT"


class RenderingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-render-integration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = make_case(self.root)
        self.candidate = self.case["candidate"]
        self.context = self.case["context"]

    def preview_payload(self):
        return {"candidate": self.candidate, "file_id": "f1", "context": self.context,
                "width": 1280, "height": 800}

    def evidence(self, candidate=None, file_id="f1"):
        candidate = candidate or self.candidate
        entry = next(f for f in candidate["manifest"]["files"] if f["file_id"] == file_id)
        raw = base64.b64decode(candidate["snapshots"][file_id])
        preview = rendering.render_preview(entry["path"], raw, candidate["manifest_hash"])
        scope = rendering.preview_scope(entry["path"], width=1280, height=800)
        observation = {"status": "passed", "issues": [], "scope": scope,
                       "notes": "合成契约替身；未运行浏览器，不能作为真实观察。"}
        record = {key: preview[key] for key in ("source_name", "source_sha256", "manifest_hash",
                  "renderer", "renderer_version", "rendered_artifact_hash")}
        record.update(status="passed", reviewer={"id": "contract-double", "kind": "synthetic"},
                      checked_at=NOW, scope=scope, evidence={
                          "executed": True, "browser": {"name": "synthetic-double", "version": "0"},
                          "artifacts": [{"id": "screen", "kind": "screenshot_png",
                                         "sha256": core.sha256_bytes(SYNTHETIC_PNG)}],
                          "dom": copy.deepcopy(observation), "visual": copy.deepcopy(observation)})
        (self.root / "record.json").write_bytes(core.canonical_bytes(record))
        (self.root / "preview.html").write_bytes(preview["html"].encode("utf-8"))
        (self.root / "screen.png").write_bytes(SYNTHETIC_PNG)
        evidence = {file_id: {"record_path": "record.json", "artifact_path": "preview.html",
                    "evidence_paths": {"screen": "screen.png"}, "required_scope": scope}}
        return evidence, record

    def check(self, evidence, **kwargs):
        args = {"authorized_root": self.root, "context": self.context, "now": NOW}
        args.update(kwargs)
        return disclosure.check_candidate_rendering(self.candidate, evidence, **args)

    def review(self, evidence=None, **changes):
        args = {key: self.case[key] for key in ("candidate", "request", "assessment", "registry")}
        args.update(signatures=[], now=NOW)
        if evidence is not None:
            args.update(rendering_evidence=evidence, authorized_root=str(self.root), context=self.context)
        args.update(changes)
        return disclosure.review_candidate(**args)

    def invoke(self, payload, *, command="preview", output="result.json", extra=()):
        (self.root / "input.json").write_text(
            payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        args = [command]
        if command == "run":
            args.append("REVIEW-07")
        args += ["--synthetic", "--root", str(self.root), "--input", "input.json", "--output", output]
        if command == "preview":
            args += ["--html-output", "cli-preview.html"]
        args += list(extra)
        return subprocess.run([sys.executable, "-m", "tools", *args], cwd=REPO,
                              capture_output=True, text=True, timeout=15)

    def test_preview_from_verified_fixed_bytes_not_mutable_source(self):
        expected = base64.b64decode(self.candidate["snapshots"]["f1"])
        (self.root / "file1.txt").write_bytes(b"replacement-not-in-fixed-package")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("no source reread")):
            preview = disclosure.preview_candidate(**self.preview_payload())
        self.assertEqual(core.sha256_bytes(expected), preview["source_sha256"])
        self.assertEqual(self.candidate["manifest_hash"], preview["manifest_hash"])
        self.assertEqual({"width": 1280, "height": 800}, preview["scope"]["viewport"])
        self.assertEqual("not_executed", preview["rendering"])
        self.assertEqual("synthetic", preview["mode"])

    def test_real_cli_creates_html_and_bound_metadata(self):
        process = self.invoke(self.preview_payload())
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("result_written\n", process.stdout)
        result = core.strict_json_loads((self.root / "result.json").read_text(encoding="utf-8"))
        preview = result["artifacts"]
        self.assertEqual("needs_review", result["status"])
        self.assertEqual("not_executed", preview["rendering"])
        self.assertEqual(core.sha256_bytes((self.root / "cli-preview.html").read_bytes()),
                         preview["rendered_artifact_hash"])
        self.assertEqual("not_performed", result["external_action"])
        self.assertEqual(self.candidate["manifest_hash"], preview["manifest_hash"])

    def test_search_report_fixed_candidate_cli_preserves_literal_evidence(self):
        title = '<script>synthetic</script> [链接](https://example.invalid) `参数` | *条件*'
        payload = search_payload(critical_date='2010-01-01')
        payload['sources'][0]['documents'] = [document(title=title)]
        payload['sources'].append({'id': 'missing', 'status': 'network_error'})
        search = cli.dispatch('SEARCH-06', payload, synthetic=True)
        self.assertEqual(search['status'], 'partial')
        raw = search['artifacts']['report'].encode('utf-8')
        source = self.root / 'search.md'
        source.write_bytes(raw)
        files = copy.deepcopy(self.case['files'])
        files[0].update(path='search.md', expected_sha256=core.sha256_bytes(raw))
        self.candidate = disclosure.freeze_candidate(self.root, files, self.context)
        self.assertIn('rendering_not_checked', self.candidate['manifest']['files'][0]['inspection']['issues'])
        source.write_text('not the approved snapshot', encoding='utf-8')
        process = self.invoke(self.preview_payload())
        self.assertEqual(process.returncode, 0, process.stderr)
        output = core.strict_json_loads((self.root / 'result.json').read_text(encoding='utf-8'))
        preview = output['artifacts']
        self.assertEqual(preview['status'], 'preview_created')
        self.assertEqual(preview['issues'], [])
        self.assertEqual(preview['source_sha256'], core.sha256_bytes(raw))
        self.assertEqual(preview['manifest_hash'], self.candidate['manifest_hash'])
        self.assertEqual(preview['rendering'], 'not_executed')
        html = (self.root / 'cli-preview.html').read_text(encoding='utf-8')
        self.assertEqual(core.sha256_bytes(html.encode()), preview['rendered_artifact_hash'])

        class VisibleText(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.parts, self.tags = [], []

            def handle_starttag(self, tag, attrs):
                self.tags.append(tag)

            def handle_data(self, value):
                self.parts.append(value)

        parsed = VisibleText()
        parsed.feed(html)
        visible = ''.join(parsed.parts)
        for text in (title, 'network_error', 'source_unavailable', 'published_before',
                     'date-evidence', '2000-01-01', '2026-10-31', '2020-01-01',
                     'collection_complete', 'local / D1 / 1', '不构成新颖性、创造性或法律可用性结论'):
            self.assertIn(text, visible)
        self.assertNotIn('not the approved snapshot', visible)
        self.assertFalse({'script', 'a', 'img', 'iframe'}.intersection(parsed.tags))
        validation = rendering.validate_rendering_evidence({}, name='search.md', content=raw,
            manifest_hash=self.candidate['manifest_hash'], artifact=html.encode(), evidence_artifacts={},
            required_scope=preview['scope'], now=NOW)
        self.assertEqual(validation['status'], 'blocked')
        self.assertIn('screen_screenshot_required', validation['issues'])
        review = self.review()
        self.assertEqual(review['status'], 'blocked')
        self.assertIn('required_signature_missing', [issue['code'] for issue in review['issues']])
        self.assertEqual(output['external_action'], 'not_performed')

    def test_renderer_1_0_record_requires_recheck(self):
        evidence, record = self.evidence()
        record['renderer_version'] = '1.0'
        (self.root / 'record.json').write_bytes(core.canonical_bytes(record))
        result = self.check(evidence)['f1']
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('renderer_version_mismatch', result['issues'])

    def test_preview_requires_explicit_viewport_file_and_intact_snapshot(self):
        for field, value in (("file_id", "unknown"), ("file_id", "internal"),
                             ("width", 0), ("height", True)):
            with self.subTest(field=field, value=value), self.assertRaises(core.ContractError):
                disclosure.preview_candidate(**{**self.preview_payload(), field: value})
        broken = copy.deepcopy(self.candidate)
        broken["snapshots"]["f1"] = base64.b64encode(b"changed").decode()
        with self.assertRaisesRegex(core.ContractError, "snapshot_hash_mismatch"):
            disclosure.preview_candidate(**{**self.preview_payload(), "candidate": broken})
        payload = self.preview_payload()
        del payload["width"]
        self.assertEqual(2, self.invoke(payload).returncode)
        self.assertFalse((self.root / "cli-preview.html").exists())

    def test_preview_denies_before_input_and_before_render(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("must not read")):
            with contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(["preview", "--root", str(self.root), "--input", "missing.json",
                                 "--output", "result.json", "--html-output", "new.html"])
        self.assertEqual(2, code)
        for context in ({**self.context, "permissions": []}, {**self.context, "sensitivity": "confidential"}):
            with patch("tools.rendering.render_preview", side_effect=AssertionError("must not render")):
                with self.assertRaises(core.ContractError):
                    disclosure.preview_candidate(**{**self.preview_payload(), "context": context})

    def test_cli_strict_json_and_root_escape_no_outputs(self):
        for text in ('{"context":{"sensitivity":"confidential","sensitivity":"synthetic"}}',
                     '{"unused":NaN}', '{"unused":1e999}'):
            with self.subTest(text=text):
                self.assertEqual(2, self.invoke(text).returncode)
                self.assertFalse((self.root / "cli-preview.html").exists())
        with tempfile.TemporaryDirectory() as outside:
            for field in ("root", "authorized_root"):
                payload = {**self.preview_payload(), field: outside}
                self.assertEqual(2, self.invoke(payload).returncode)
                self.assertFalse((self.root / "cli-preview.html").exists())

    def test_cli_checks_both_outputs_before_write(self):
        for occupied in ("result.json", "cli-preview.html"):
            with self.subTest(occupied=occupied):
                path = self.root / occupied
                path.write_bytes(b"original")
                self.assertEqual(2, self.invoke(self.preview_payload()).returncode)
                self.assertEqual(b"original", path.read_bytes())
                other = "cli-preview.html" if occupied == "result.json" else "result.json"
                self.assertFalse((self.root / other).exists())
                path.unlink()
        self.assertEqual(2, self.invoke(self.preview_payload(), output="cli-preview.html").returncode)
        self.assertFalse((self.root / "cli-preview.html").exists())
        self.assertEqual(2, self.invoke(self.preview_payload(), extra=("--html-output", "../escape.html")).returncode)

    def test_second_output_failure_reports_partial_html_without_success_or_deletion(self):
        (self.root / "input.json").write_bytes(core.canonical_bytes(self.preview_payload()))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch(
                "tools.core.write_new_json", side_effect=OSError("synthetic second output failure")):
            code = cli.main(["preview", "--synthetic", "--root", str(self.root), "--input", "input.json",
                             "--output", "result.json", "--html-output", "new.html"])
        self.assertEqual(3, code)
        self.assertEqual("", out.getvalue())
        self.assertEqual("preview_html_retained_json_failed\n", err.getvalue())
        self.assertTrue((self.root / "new.html").is_file())
        self.assertFalse((self.root / "result.json").exists())

    def test_case_alias_output_collision_rejected_on_windows(self):
        if sys.platform != "win32":
            self.skipTest("大小写别名适用于Windows文件系统")
        process = self.invoke(self.preview_payload(), output="CLI-PREVIEW.HTML")
        self.assertEqual(2, process.returncode)
        self.assertFalse((self.root / "cli-preview.html").exists())

    def test_old_sidecar_results_require_recheck_even_if_claimed_consistent(self):
        for status in ("consistent", "blocked"):
            candidate = copy.deepcopy(self.candidate)
            candidate["rendering_evidence"] = {"f1": {"status": status, "issues": []}}
            result = self.review(candidate=candidate)
            self.assertIn("rendering_evidence_recheck_required", [i["code"] for i in result["issues"]])

    def test_positive_substitute_is_consistency_only_and_dg09_stays_blocked(self):
        evidence, _ = self.evidence()
        result = self.check(evidence)["f1"]
        self.assertEqual("consistent", result["status"])
        self.assertEqual("not_performed", result["identity_verification"])
        self.assertEqual("not_performed", result["professional_review"])
        self.assertEqual("not_established_by_hash", result["evidence_authenticity"])
        review = self.review(evidence)
        self.assertEqual("blocked", review["status"])
        self.assertIn("required_signature_missing", [x["code"] for x in review["issues"]])

    def test_unknown_file_and_duplicate_record_json_fail_before_artifact_read(self):
        evidence, _ = self.evidence()
        with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(core.ContractError, "rendering_file_id_unknown"):
                self.check({"unknown": evidence["f1"]})
        (self.root / "record.json").write_text('{"status":"failed","status":"passed"}', encoding="utf-8")
        with self.assertRaisesRegex(core.ContractError, "duplicate_json_key"):
            self.check(evidence)
        (self.root / "record.json").write_text('{"value":1e999}', encoding="utf-8")
        with self.assertRaises(core.ContractError):
            self.check(evidence)

    def test_local_evidence_permissions_and_current_time_precede_read(self):
        evidence, _ = self.evidence()
        for change in ({"context": {**self.context, "permissions": []}},
                       {"context": {**self.context, "sensitivity": "restricted"}},
                       {"now": "2027-02-01T12:00:00Z"}):
            with self.subTest(change=list(change)), patch.object(
                    Path, "read_bytes", side_effect=AssertionError("must not read")), patch.object(
                    Path, "read_text", side_effect=AssertionError("must not read")):
                with self.assertRaises(core.ContractError):
                    self.check(evidence, **change)

    def test_dependency_change_rejected_before_preview_or_evidence_read(self):
        ledger = core.VersionLedger()
        ledger.put("scope", {"v": 1})
        files = copy.deepcopy(self.case["files"])
        files[0]["dependency_ids"] = ["scope"]
        self.candidate = disclosure.freeze_candidate(self.root, files, self.context, ledger=ledger.export())
        evidence, _ = self.evidence()
        self.assertEqual("consistent", self.check(evidence, ledger=ledger.export())["f1"]["status"])
        ledger.put("scope", {"v": 2})
        for state in (None, ledger.export()):
            with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
                with self.assertRaisesRegex(core.ContractError, "candidate_dependencies_stale"):
                    self.check(evidence, ledger=state)
                with self.assertRaisesRegex(core.ContractError, "candidate_dependencies_stale"):
                    disclosure.preview_candidate(**self.preview_payload(), ledger=state)

    def test_evidence_paths_all_confined_before_read(self):
        evidence, _ = self.evidence()
        for field in ("record_path", "artifact_path", "evidence_paths"):
            changed = copy.deepcopy(evidence)
            changed["f1"][field] = {"screen": "../outside.png"} if field == "evidence_paths" else "../outside"
            with self.subTest(field=field), patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
                with self.assertRaises(core.ContractError):
                    self.check(changed)

    def test_root_external_symlink_rejected(self):
        evidence, _ = self.evidence()
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.png"
            external.write_bytes(SYNTHETIC_PNG)
            link = self.root / "link.png"
            try:
                link.symlink_to(external)
            except OSError:
                self.skipTest("当前账户无符号链接创建权限；该真实链接用例未执行")
            evidence["f1"]["evidence_paths"]["screen"] = "link.png"
            with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read")):
                with self.assertRaisesRegex(core.ContractError, "path_outside_root"):
                    self.check(evidence)

    def test_missing_screenshot_and_extra_evidence_block(self):
        evidence, _ = self.evidence()
        for paths in ({}, {"screen": "screen.png", "extra": "screen.png"}):
            evidence["f1"]["evidence_paths"] = paths
            result = self.check(evidence)["f1"]
            self.assertEqual("blocked", result["status"])
            self.assertIn("evidence_inventory_mismatch", result["issues"])
        evidence["f1"]["evidence_paths"] = {"screen": "missing.png"}
        self.assertEqual("blocked", self.check(evidence)["f1"]["status"])

    def test_old_source_package_html_renderer_and_future_or_failed_observations_block(self):
        evidence, record = self.evidence()
        mutations = [("source_sha256", "0" * 64), ("manifest_hash", "0" * 64),
                     ("renderer", "old"), ("renderer_version", "old"),
                     ("rendered_artifact_hash", "0" * 64), ("status", "failed"),
                     ("checked_at", "2026-11-01T12:00:00Z")]
        for key, value in mutations:
            with self.subTest(key=key):
                (self.root / "record.json").write_bytes(core.canonical_bytes({**record, key: value}))
                self.assertEqual("blocked", self.check(evidence)["f1"]["status"])
        for component in ("dom", "visual"):
            changed = copy.deepcopy(record)
            changed["evidence"][component]["status"] = "failed"
            (self.root / "record.json").write_bytes(core.canonical_bytes(changed))
            self.assertEqual("blocked", self.check(evidence)["f1"]["status"])
        (self.root / "record.json").write_bytes(core.canonical_bytes(record))
        (self.root / "preview.html").write_bytes(b"changed HTML")
        self.assertIn("html_bytes_mismatch", self.check(evidence)["f1"]["issues"])

    def test_independent_scope_requirement_not_inferred_from_record(self):
        evidence, _ = self.evidence()
        evidence["f1"]["required_scope"]["viewport"]["width"] = 640
        self.assertIn("rendering_scope_mismatch", self.check(evidence)["f1"]["issues"])
        del evidence["f1"]["required_scope"]
        with self.assertRaises(core.ContractError):
            self.check(evidence)

    def test_core07_optional_evidence_bound_to_new_fixed_manifest(self):
        evidence, _ = self.evidence()
        payload = {"root": str(self.root), "files": self.case["files"], "context": self.context,
                   "rendering_evidence": evidence}
        first = cli.dispatch("CORE-07", payload, synthetic=True)
        self.assertEqual("consistent", first["artifacts"]["rendering_evidence"]["f1"]["status"])
        self.assertEqual("needs_review", first["status"])
        (self.root / "file1.txt").write_bytes(b"new source")
        second = cli.dispatch("CORE-07", payload, synthetic=True)
        self.assertEqual("blocked", second["status"])
        self.assertEqual("blocked", second["artifacts"]["rendering_evidence"]["f1"]["status"])
        self.assertIn("stale_source_version", [i["code"] for i in second["issues"]])

    def test_dg06_consistent_md_svg_never_removes_default_rendering_block(self):
        for name, content in (("doc.md", b"# Synthetic heading"),
                              ("diagram.svg", b'<svg viewBox="0 0 100 100"><text x="1" y="20">Synthetic</text></svg>')):
            with self.subTest(name=name):
                (self.root / name).write_bytes(content)
                files = [{"file_id": "f1", "path": name, "kind": "external", "version": "1",
                          "expected_sha256": core.sha256_bytes(content), "content_ids": ["c1"]}]
                candidate = disclosure.freeze_candidate(self.root, files, self.context)
                evidence, _ = self.evidence(candidate)
                result = cli.dispatch("CORE-07", {"root": str(self.root), "files": files,
                    "context": self.context, "rendering_evidence": evidence}, synthetic=True)
                self.assertEqual("consistent", result["artifacts"]["rendering_evidence"]["f1"]["status"])
                self.assertEqual("blocked", result["status"])
                self.assertIn("rendering_not_checked", [i["code"] for i in result["issues"]])

    def test_dg06_hidden_review_and_dg07_joint_review_still_required(self):
        evidence, _ = self.evidence()
        assessment = copy.deepcopy(self.case["assessment"])
        assessment["hidden_review"]["status"] = "not_checked"
        assessment["joint_review"]["status"] = "not_checked"
        result = self.review(evidence, assessment=assessment)
        codes = {i["code"] for i in result["issues"]}
        self.assertTrue({"full_content_review_required", "joint_semantic_review_required"} <= codes)

    def test_supplied_bad_evidence_blocks_even_with_all_matching_signatures(self):
        evidence, record = self.evidence()
        record["evidence"]["visual"]["status"] = "failed"
        (self.root / "record.json").write_bytes(core.canonical_bytes(record))
        body = {k: self.case[k] for k in ("candidate", "request", "assessment", "registry")}
        binding = disclosure.approval_binding(**body)
        signatures = [{"role": role, "actor_id": role, "binding": binding, "evidence": "synthetic"}
                      for role in disclosure.required_roles(body["request"], body["assessment"])]
        result = self.review(evidence, signatures=signatures)
        self.assertEqual("blocked", result["status"])
        self.assertEqual([{"code": "visual_review_incomplete", "file_id": "f1"}], result["issues"])
        payload = {**body, "signatures": signatures, "now": NOW, "authorized_root": str(self.root),
                   "context": self.context, "rendering_evidence": evidence}
        process = self.invoke(payload, command="run")
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("blocked", core.strict_json_loads(
            (self.root / "result.json").read_text(encoding="utf-8"))["status"])

    def test_recheck_cannot_drop_previously_checked_file(self):
        evidence, _ = self.evidence()
        candidate = copy.deepcopy(self.candidate)
        candidate["rendering_evidence"] = {"f2": {"status": "blocked", "issues": ["visual_review_incomplete"]}}
        with self.assertRaisesRegex(core.ContractError, "rendering_recheck_inventory_incomplete"):
            self.review(evidence, candidate=candidate)

    def test_duplicate_file_evidence_json_rejected_before_file_reads(self):
        payload = '{"rendering_evidence":{"f1":{},"f1":{}}}'
        result = self.invoke(payload, command="run")
        self.assertEqual(2, result.returncode)
        self.assertFalse((self.root / "result.json").exists())

    def test_no_evidence_preserves_original_candidate_and_review_shape(self):
        candidate = disclosure.freeze_candidate(self.root, self.case["files"], self.context)
        self.assertEqual({"manifest", "manifest_hash", "snapshots"}, set(candidate))
        self.assertEqual(self.candidate, candidate)
        self.assertNotIn("rendering_evidence", self.review())
        self.assertEqual(83, len(cli.catalog()))
        self.assertEqual("tools.patent", next(row for row in cli.catalog() if row["capability"] == "FIG-05")["module"])


if __name__ == "__main__":
    unittest.main()
