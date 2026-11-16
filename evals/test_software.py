"""SW-01..08合成AC；本地准备测试不是专业意见或真实登记验收。"""

import copy
import inspect
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tools import software
from tools.core import ContractError, digest, sha256_bytes
from tools.software import CAPABILITIES, run

FIXTURE = Path(__file__).parent / "fixtures" / "software" / "synthetic.json"


class SoftwareTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.context = self.fixture["context"]
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "counter.py").write_text(self.fixture["source"], encoding="utf-8")
        self.scope = self.call("SW-01", **self.fixture["scope_input"])["artifacts"]
        self.rights = self.call("SW-07", scope=self.scope,
                                rights=self.fixture["rights"])["artifacts"]

    def call(self, capability, **payload):
        return run(capability, {"context": self.context, **payload})

    def source_args(self):
        return {"scope": self.scope, "rights_decisions": self.rights,
                "authorized_root": str(self.root), "inventory_complete": True,
                "files": [{"id": "f1", "path": "counter.py", "component_id": "cli",
                           "kind": "source", "include": True}],
                "pagination": self.fixture["pagination"]}

    def source(self, **changes):
        return self.call("SW-02", **(self.source_args() | changes))

    def manual(self, **changes):
        return self.call("SW-04", scope=self.scope,
                         **(self.fixture["manual_input"] | changes))

    def form(self, material):
        return {**self.scope["metadata"], "total_source_lines": material["total_source_lines"],
                "selected_source_lines": material["selected_source_lines"]}

    def correction(self, **changes):
        args = {"before": self.scope, "after": self.scope,
                "event": {"id": "notice-1", "type": "correction", "evidence_id": "synthetic-notice",
                          "source_status": "synthetic"},
                "notice_items": [{"id": "n1", "evidence_id": "synthetic-notice", "locator": "p1"}],
                "responses": [{"notice_id": "n1", "basis_evidence": "synthetic-basis",
                               "replacement_locator": "form.version"}],
                "prior_reviews": [{"id": "r1", "binding": self.scope["binding"], "status": "recorded"}],
                "deadline": {"event_id": "notice-1", "owner": "synthetic-owner", "rule_id": "synthetic-rule",
                             "service_at": "2026-10-31T10:00:00Z", "due_at": "2026-11-30T10:00:00Z",
                             "basis_evidence": "synthetic-notice", "human_review": "synthetic-review"}}
        return self.call("SW-06", **(args | changes))

    def pair(self, classification="expression"):
        return {"id": "pair-1", "classification": classification,
                "left": {"version": "1", "text": "return count(items)", "evidence_id": "left-evidence", "locator": "f1:2"},
                "right": {"version": "2", "text": "return count(values)", "evidence_id": "right-evidence", "locator": "f2:4"},
                "access_evidence": None, "origin_evidence": None}

    def test_public_capabilities_and_independent_statuses(self):
        self.assertEqual(CAPABILITIES, tuple(f"SW-{i:02d}" for i in range(1, 9)))
        output = self.source()
        self.assertEqual(output["professional_review"], "not_performed")
        self.assertEqual(output["official_status"], "not_asserted")
        self.assertEqual(output["external_action"], "not_performed")

    def test_invalid_capability_and_missing_context(self):
        with self.assertRaises(ContractError):
            run("SW-99", {})
        with self.assertRaises(ContractError):
            run("SW-01", self.fixture["scope_input"])

    def test_preflight_denies_before_any_source_read(self):
        self.context["permissions"] = []
        with patch.object(Path, "open") as opened:
            with self.assertRaisesRegex(ContractError, "permission_not_proven"):
                self.source()
            opened.assert_not_called()

    def test_confidential_host_unknown_denies_before_source_read(self):
        self.context["sensitivity"] = "confidential"
        with patch.object(Path, "open") as opened:
            with self.assertRaises(ContractError):
                self.source()
            opened.assert_not_called()

    def test_ac_sw01_multiple_components_upgrade_conflict(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        second = copy.deepcopy(payload["components"][0])
        second.update(id="server", kind="server", origin="adapted", version="2")
        second["subjects"].append({"subject_id": "other", "basis": "conflict", "evidence_id": "e2"})
        payload["components"].append(second)
        output = self.call("SW-01", **payload)
        codes = {item["code"] for item in output["issues"]}
        self.assertIn("ownership_conflict", codes)
        self.assertIn("baseline_or_exclusion_missing", codes)
        self.assertIn("component_grouping_basis_missing", codes)
        self.assertEqual(len(output["artifacts"]["components"]), 2)
        self.assertEqual(output["artifacts"]["ownership"], "undetermined")

    def test_sw01_normal_scope_preserves_claim_and_exclusion(self):
        self.assertEqual(self.scope["components"][0]["claim"], ["本版独立编写的命令行表达"])
        self.assertFalse(self.scope["git_authorship_is_ownership"])
        self.assertEqual(self.scope["issues"], [])

    def test_sw01_unknown_dates_do_not_infer_from_git(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["metadata"]["completed_date"] = None
        payload["git_commit_date"] = "2026-10-01"
        output = self.call("SW-01", **payload)
        self.assertIsNone(output["artifacts"]["metadata"]["completed_date"])
        self.assertEqual(output["status"], "needs_evidence")

    def test_sw01_invalid_date_duplicate_component(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["metadata"]["completed_date"]["value"] = "2026-02-31"
        with self.assertRaisesRegex(ContractError, "invalid_date_fact"):
            self.call("SW-01", **payload)
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["components"].append(copy.deepcopy(payload["components"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate_id"):
            self.call("SW-01", **payload)

    def test_sw01_excluded_only_component_has_no_original_claim(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["components"][0].update(origin="third_party", claim=[])
        output = self.call("SW-01", **payload)
        self.assertEqual(output["artifacts"]["components"][0]["claim"], [])

    def test_sw01_changed_name_changes_binding(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["metadata"]["name"] = "更名"
        self.assertNotEqual(self.scope["binding"], self.call("SW-01", **payload)["artifacts"]["binding"])

    def test_ac_sw02_short_program_no_padding_real_mapping(self):
        output = self.source()["artifacts"]
        self.assertEqual(output["total_source_lines"], 3)
        self.assertEqual(output["selected_source_lines"], 3)
        segments = [line for page in output["pages"] for line in page["lines"]]
        source = self.fixture["source"].splitlines()
        for segment in segments:
            self.assertEqual(segment["text"], source[segment["source_line"] - 1][segment["column_start"] - 1:segment["column_end"]])
        self.assertEqual(output["rule_status"], "caller_parameters_not_professionally_verified")

    def test_sw02_long_head_tail_and_multibyte_columns(self):
        text = "\n".join("合成源码第" + str(i) + "行中文字符" for i in range(40))
        (self.root / "counter.py").write_text(text, encoding="utf-8")
        pagination = {"lines_per_page": 2, "wrap_columns": 5, "selection": "head_tail",
                      "pages_each_end": 1, "basis": "synthetic"}
        material = self.source(pagination=pagination)["artifacts"]
        segments = [line for page in material["pages"] for line in page["lines"]]
        self.assertEqual(len(segments), 4)
        self.assertEqual(segments[0]["source_line"], 1)
        self.assertEqual(segments[-1]["source_line"], 40)
        for line in segments:
            self.assertEqual(line["text"], text.splitlines()[line["source_line"] - 1][line["column_start"] - 1:line["column_end"]])
        self.assertNotIn("�", json.dumps(material, ensure_ascii=False))

    def test_sw02_stable_order_and_ranges(self):
        (self.root / "second.py").write_text("a\nb\nc\n", encoding="utf-8")
        files = self.source_args()["files"] + [{"id": "f0", "path": "second.py", "component_id": "cli",
                                               "kind": "source", "include": True, "ranges": [[2, 3]]}]
        first = self.source(files=files)["artifacts"]
        second = self.source(files=list(reversed(files)))["artifacts"]
        self.assertEqual(first["binding"], second["binding"])
        self.assertEqual(first["selected_lines"][0]["text"], "b")
        self.assertEqual(first["total_source_lines"], 6)
        self.assertEqual(first["selected_source_lines"], 5)

    def test_sw02_path_traversal_and_windows_ads(self):
        for path in ("../secret.py", "C:/secret.py", "counter.py:stream", "/tmp/secret.py"):
            with self.subTest(path=path):
                files = self.source_args()["files"]
                files[0]["path"] = path
                with self.assertRaises(ContractError):
                    self.source(files=files)

    def test_sw02_symbolic_link_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside, "outside.py")
            target.write_text("synthetic outside", encoding="utf-8")
            link = self.root / "link.py"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {type(exc).__name__}")
            files = self.source_args()["files"]
            files[0]["path"] = "link.py"
            with self.assertRaisesRegex(ContractError, "path_outside_root"):
                self.source(files=files)

    def test_sw02_unknown_suffix_bad_encoding_generated_dependency(self):
        entries = []
        for index, (name, content, kind) in enumerate([
            ("unknown.xyz", b"real source", "source"), ("bad.py", b"\xff\xfe\xff", "source"),
            ("generated.py", b"generated", "generated"), ("dep.py", b"dependency", "dependency")
        ]):
            (self.root / name).write_bytes(content)
            entries.append({"id": f"extra{index}", "path": name, "component_id": "cli",
                            "kind": kind, "include": True})
        output = self.source(files=self.source_args()["files"] + entries)
        self.assertEqual(output["status"], "partial")
        reasons = {row["reason"] for row in output["artifacts"]["excluded"]}
        self.assertEqual(reasons, {"unknown_suffix", "undecodable", "generated", "dependency"})
        self.assertEqual(output["artifacts"]["selected_source_lines"], 3)

    def test_sw02_unknown_suffix_with_explicit_source_evidence(self):
        (self.root / "custom.xyz").write_text("source expression\n", encoding="utf-8")
        entry = {"id": "custom", "path": "custom.xyz", "component_id": "cli", "kind": "source",
                 "include": True, "source_type_evidence": "synthetic-language-review"}
        self.assertEqual(self.source(files=[entry])["artifacts"]["selected_source_lines"], 1)

    def test_sw02_ranges_failure_and_invalid_pagination(self):
        files = self.source_args()["files"]
        files[0]["ranges"] = [[1, 2], [2, 3]]
        with self.assertRaisesRegex(ContractError, "overlapping_line_ranges"):
            self.source(files=files)
        pagination = {**self.fixture["pagination"], "lines_per_page": 0}
        with self.assertRaises(ContractError):
            self.source(pagination=pagination)

    def test_sw02_source_change_invalidates_and_old_snapshot_survives(self):
        before = self.source()["artifacts"]
        frozen = copy.deepcopy(before)
        (self.root / "counter.py").write_text("print('changed')\n", encoding="utf-8")
        output = self.source(previous_material=before)
        self.assertEqual(output["status"], "invalidated")
        self.assertEqual(output["artifacts"]["supersedes"], before["binding"])
        self.assertEqual(before, frozen)

    def test_sw02_stale_rights_or_tampered_artifact_rejected(self):
        changed = copy.deepcopy(self.scope)
        changed["metadata"]["version"] = "2"
        with self.assertRaisesRegex(ContractError, "artifact_binding_mismatch"):
            self.source(scope=changed)
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["metadata"]["version"] = "2"
        changed = self.call("SW-01", **payload)["artifacts"]
        with self.assertRaisesRegex(ContractError, "rights_scope_stale"):
            self.source(scope=changed)

    def test_sw02_prohibited_material_is_not_read(self):
        rights = copy.deepcopy(self.fixture["rights"])
        rights[0]["permissions"]["local_process"] = "deny"
        decisions = self.call("SW-07", scope=self.scope, rights=rights)["artifacts"]
        with patch.object(Path, "open") as opened:
            output = self.source(rights_decisions=decisions)
            opened.assert_not_called()
        self.assertEqual(output["artifacts"]["excluded"][0]["read_status"], "not_read")

    def test_sw02_incomplete_inventory_and_empty_source_explicit(self):
        (self.root / "counter.py").write_bytes(b"")
        output = self.source(inventory_complete=False)
        self.assertEqual(output["artifacts"]["pages"], [])
        self.assertEqual({item["code"] for item in output["issues"]},
                         {"inventory_incomplete", "no_selected_source"})

    def test_ac_sw03_mask_and_audit_do_not_repeat_secret(self):
        secret = "SYNTHETIC-ONLY-SECRET"
        (self.root / "counter.py").write_text(f"value = '{secret}'\n", encoding="utf-8")
        material = self.source()["artifacts"]
        original = copy.deepcopy(material)
        output = self.call("SW-03", material=material, sensitive_literals=[secret], redactions=[])
        self.assertNotIn(secret, json.dumps(output, ensure_ascii=False))
        self.assertIn("█", json.dumps(output, ensure_ascii=False))
        self.assertEqual(output["artifacts"]["external_permission"], "not_granted")
        self.assertEqual(material, original)
        self.assertEqual((self.root / "counter.py").read_text(encoding="utf-8"), f"value = '{secret}'\n")

    def test_sw03_unicode_span_and_head_tail_map_preserved(self):
        (self.root / "counter.py").write_text("合成秘密数据0123456789\n" * 30, encoding="utf-8")
        pagination = {"lines_per_page": 2, "wrap_columns": 5, "selection": "head_tail",
                      "pages_each_end": 1, "basis": "synthetic"}
        material = self.source(pagination=pagination)["artifacts"]
        output = self.call("SW-03", material=material, redactions=[
            {"file_id": "f1", "line": 1, "start": 3, "end": 4, "basis_id": "synthetic-policy"}])
        pages = output["artifacts"]["document"]["pages"]
        self.assertEqual(sum(len(page["lines"]) for page in pages), 4)
        self.assertEqual(pages[0]["lines"][0]["text"], "合成██数")
        self.assertEqual(pages[-1]["lines"][-1]["source_line"], 30)

    def test_sw03_unknown_rule_and_public_action_not_granted(self):
        output = self.call("SW-03", material=self.source()["artifacts"], target_action="public")
        self.assertEqual({item["code"] for item in output["issues"]},
                         {"exception_deposit_rule_unverified", "separate_disclosure_authorization_required"})

    def test_sw03_no_sensitive_items_preserves_pages(self):
        material = self.source()["artifacts"]
        output = self.call("SW-03", material=material,
                           deposit_rule={"evidence_id": "synthetic-rule", "review_evidence": "synthetic-review"})
        self.assertEqual(output["artifacts"]["document"]["pages"], material["pages"])
        self.assertEqual(output["artifacts"]["private_audit"]["operations"], [])

    def test_sw03_invalid_span_and_changed_redactions(self):
        material = self.source()["artifacts"]
        with self.assertRaises(ContractError):
            self.call("SW-03", material=material, redactions=[
                {"file_id": "f1", "line": 1, "start": 1, "end": 999, "basis_id": "r"}])
        a = self.call("SW-03", material=material)["artifacts"]
        b = self.call("SW-03", material=material, sensitive_literals=["count"])["artifacts"]
        self.assertNotEqual(a["binding"], b["binding"])

    def test_ac_sw04_cli_manual_no_fake_gui(self):
        output = self.manual()
        self.assertIn("命令操作流程", output["artifacts"]["markdown"])
        self.assertNotIn("网页登录", output["artifacts"]["markdown"])
        self.assertEqual(output["artifacts"]["screenshots"], [])
        self.assertEqual(output["artifacts"]["verification"], "static_only")

    def test_sw04_all_modes_with_explicit_runtime_evidence(self):
        for mode in ("CLI", "API", "embedded", "GUI"):
            with self.subTest(mode=mode):
                runtime = [{"id": "run1", "version": "1.0", "evidence_id": "synthetic-run",
                            "kind": "screenshot" if mode == "GUI" else "transcript"}]
                output = self.manual(mode=mode, runtime_evidence=runtime)
                self.assertEqual(output["issues"], [])
                self.assertEqual(output["artifacts"]["verification"], "evidence_referenced_not_executed")

    def test_sw04_wrong_mode_stale_runtime_and_screenshot_not_applicable(self):
        with self.assertRaises(ContractError):
            self.manual(mode="unknown")
        runtime = [{"id": "r", "version": "2", "evidence_id": "e", "kind": "test"}]
        with self.assertRaisesRegex(ContractError, "runtime_version_mismatch"):
            self.manual(runtime_evidence=runtime)
        runtime[0].update(version="1.0", kind="screenshot")
        with self.assertRaisesRegex(ContractError, "screenshot_not_applicable"):
            self.manual(runtime_evidence=runtime)

    def test_sw04_fact_change_changes_binding(self):
        facts = copy.deepcopy(self.fixture["manual_input"]["facts"])
        facts[0]["text"] = "更新后的真实事实"
        self.assertNotEqual(self.manual()["artifacts"]["binding"],
                            self.manual(facts=facts)["artifacts"]["binding"])

    def test_ac_sw05_total_not_replaced_by_selection(self):
        files = self.source_args()["files"]
        files[0]["ranges"] = [[1, 1]]
        material = self.source(files=files)["artifacts"]
        form = self.form(material)
        output = self.call("SW-05", scope=self.scope, material=material,
                           manual=self.manual()["artifacts"], form=form,
                           form_rule_evidence="synthetic-current-form")
        self.assertEqual(output["status"], "checked")
        self.assertEqual(form["total_source_lines"], 3)
        self.assertEqual(form["selected_source_lines"], 1)
        self.assertTrue(output["artifacts"]["counts_not_overwritten"])

    def test_sw05_mismatched_quantity_and_name_detected(self):
        material = self.source()["artifacts"]
        form = self.form(material)
        form.update(name="不同名称", total_source_lines=999)
        output = self.call("SW-05", scope=self.scope, material=material,
                           manual=self.manual()["artifacts"], form=form)
        codes = {item["code"] for item in output["issues"]}
        self.assertIn("field_mismatch:name", codes)
        self.assertIn("quantity_mismatch:total_source_lines", codes)
        self.assertIn("current_form_rule_unverified", codes)

    def test_sw05_field_limit_missing_field_and_stale_scope(self):
        material = self.source()["artifacts"]
        form = self.form(material)
        output = self.call("SW-05", scope=self.scope, material=material,
                           manual=self.manual()["artifacts"], form=form, field_limits={"name": 1})
        self.assertIn("field_limit_exceeded", {item["code"] for item in output["issues"]})
        with self.assertRaises(ContractError):
            self.call("SW-05", scope=self.scope, material=material,
                      manual=self.manual()["artifacts"], form={})
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["metadata"]["version"] = "2"
        changed = self.call("SW-01", **payload)["artifacts"]
        output = self.call("SW-05", scope=changed, material=material,
                           manual=self.manual()["artifacts"], form=form)
        self.assertIn("scope_binding_stale", {item["code"] for item in output["issues"]})

    def test_ac_sw06_correction_version_and_owner_invalidates_old_reviews(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["metadata"]["version"] = "2"
        payload["components"][0]["subjects"][0]["subject_id"] = "successor"
        after = self.call("SW-01", **payload)["artifacts"]
        output = self.correction(after=after)
        self.assertEqual(output["status"], "invalidated")
        self.assertEqual(output["artifacts"]["reviews"][0]["status"], "invalidated")
        self.assertEqual(len(output["artifacts"]["history"]), 2)
        self.assertIn("ownership", output["artifacts"]["required_review"])
        self.assertEqual(output["artifacts"]["registration_status"], "not_asserted")

    def test_sw06_normal_unchanged_unrelated_review_and_deadline(self):
        output = self.correction()
        self.assertEqual(output["artifacts"]["changed_fields"], [])
        self.assertEqual(output["artifacts"]["reviews"][0]["status"], "recorded")
        self.assertEqual(output["artifacts"]["deadline"]["artifacts"]["rule_owner"], "SW-06")
        self.assertEqual(output["issues"], [])

    def test_sw06_missing_notice_deadline_and_unknown_source(self):
        event = {"id": "n", "type": "succession", "evidence_id": "e", "source_status": "unverified"}
        output = self.correction(event=event, responses=[], deadline=None)
        self.assertEqual({item["code"] for item in output["issues"]},
                         {"notice_item_unanswered", "deadline_unknown", "notice_authenticity_unknown"})

    def test_sw06_no_notice_items_change_case_and_invalid_response(self):
        output = self.correction(notice_items=[], responses=[])
        self.assertEqual(output["artifacts"]["dispositions"], [])
        with self.assertRaisesRegex(ContractError, "unknown_notice_response"):
            self.correction(notice_items=[])

    def test_ac_sw07_license_is_not_public_or_cloud_permission(self):
        output = self.call("SW-07", scope=self.scope, rights=self.fixture["rights"])
        codes = {item["code"] for item in output["issues"]}
        self.assertIn("public_not_authorized", codes)
        self.assertIn("cloud_not_authorized", codes)
        self.assertEqual(output["artifacts"]["decisions"][0]["decision"], "claim")

    def test_sw07_third_party_excluded_and_not_read_as_original(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["components"][0].update(origin="third_party", claim=[])
        scope = self.call("SW-01", **payload)["artifacts"]
        rights = copy.deepcopy(self.fixture["rights"])
        rights[0].update(license="synthetic-license", notice="synthetic attribution")
        decisions = self.call("SW-07", scope=scope, rights=rights)["artifacts"]
        output = self.source(scope=scope, rights_decisions=decisions)
        self.assertEqual(output["artifacts"]["selected_source_lines"], 0)
        self.assertEqual(decisions["decisions"][0]["decision"], "exclude")

    def test_sw07_ai_contribution_unknown_and_then_evidenced(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["components"][0]["origin"] = "ai"
        scope = self.call("SW-01", **payload)["artifacts"]
        rights = copy.deepcopy(self.fixture["rights"])
        first = self.call("SW-07", scope=scope, rights=rights)["artifacts"]
        self.assertEqual(first["decisions"][0]["decision"], "needs_evidence")
        rights[0]["human_contribution"] = {"description": "合成的人类设计、修改事实", "evidence_ids": ["synthetic-human-work"]}
        second = self.call("SW-07", scope=scope, rights=rights)["artifacts"]
        self.assertEqual(second["decisions"][0]["decision"], "claim")
        self.assertNotEqual(first["binding"], second["binding"])

    def test_sw07_missing_coverage_and_evidence_prohibit_selection(self):
        with self.assertRaises(ContractError):
            self.call("SW-07", scope=self.scope, rights=[])
        rights = copy.deepcopy(self.fixture["rights"])
        rights[0]["evidence_ids"] = []
        output = self.call("SW-07", scope=self.scope, rights=rights)
        self.assertEqual(output["artifacts"]["decisions"][0]["decision"], "needs_permission")

    def test_sw07_nonapplicable_ai_analysis_for_own_source(self):
        row = self.rights["decisions"][0]
        self.assertIsNone(row["human_contribution"])
        self.assertNotIn("human_contribution_unknown", row["issues"])

    def test_ac_sw08_expression_vs_function_thirdparty_and_access_unknown(self):
        pairs = [self.pair(kind) | {"id": kind} for kind in ("expression", "function", "third_party", "existing")]
        output = self.call("SW-08", scope=self.scope, branch="dispute", pairs=pairs)
        rows = output["artifacts"]["comparisons"]
        self.assertTrue(rows[0]["literal_matching_spans"])
        self.assertTrue(all(row["excluded_from_expression_comparison"] for row in rows[1:]))
        self.assertTrue(all(row["literal_matching_spans"] == [] for row in rows[1:]))
        self.assertTrue(all(row["infringement"] == "not_determined" for row in rows))
        self.assertIn("access_evidence_unknown", {item["code"] for item in output["issues"]})
        self.assertIn("origin_evidence_unknown", {item["code"] for item in output["issues"]})

    def test_sw08_dispute_changed_version_and_invalid_branch(self):
        pair = self.pair()
        first = self.call("SW-08", scope=self.scope, branch="dispute", pairs=[pair])["artifacts"]
        pair["right"]["version"] = "3"
        second = self.call("SW-08", scope=self.scope, branch="dispute", pairs=[pair])["artifacts"]
        self.assertNotEqual(first["binding"], second["binding"])
        with self.assertRaises(ContractError):
            self.call("SW-08", scope=self.scope, branch="patent_novelty")

    def test_sw08_regions_no_chinese_pagination_inheritance(self):
        targets = [{"jurisdiction": "SYNTHETIC-A", "route": "registration",
                    "requirements": [{"id": "deposit", "source_locator": "rule:1", "evidence_id": "synthetic-deposit"}]},
                   {"jurisdiction": "SYNTHETIC-B", "route": "protection_without_registration", "requirements": []}]
        output = self.call("SW-08", scope=self.scope, branch="adaptation", targets=targets)
        rows = output["artifacts"]["targets"]
        self.assertTrue(all(row["pagination_inherited"] is False for row in rows))
        self.assertEqual(rows[1]["registration_applicability"], "not_applicable")
        self.assertTrue(all(row["support_status"] != "supported" for row in rows))

    def test_sw08_regional_unknown_missing_evidence_and_rule_change(self):
        target = {"jurisdiction": "SYNTHETIC", "route": "unknown",
                  "requirements": [{"id": "q1", "source_locator": "rule:1"}]}
        first = self.call("SW-08", scope=self.scope, branch="adaptation", targets=[target])
        self.assertEqual({item["code"] for item in first["issues"]},
                         {"regional_requirement_missing", "regional_rule_unverified"})
        target.update(rule_evidence="rule-v2", professional_review_evidence="synthetic-review")
        target["requirements"][0]["evidence_id"] = "synthetic-proof"
        second = self.call("SW-08", scope=self.scope, branch="adaptation", targets=[target])
        self.assertNotEqual(first["artifacts"]["binding"], second["artifacts"]["binding"])
        self.assertEqual(second["issues"], [])
        self.assertEqual(second["professional_review"], "not_performed")

    def test_sw02_deposit_permission_does_not_authorize_public_selection(self):
        output = self.source(selection_purpose="public")
        self.assertEqual(output["artifacts"]["selected_source_lines"], 0)
        self.assertIn("selection_purpose_not_authorized", {item["code"] for item in output["issues"]})
        self.assertEqual(output["artifacts"]["total_source_lines"], 3)

    def test_sw02_size_limit_and_missing_path_errors_are_sanitized(self):
        with self.assertRaisesRegex(ContractError, "source_file_too_large"):
            self.source(max_file_bytes=2)
        files = self.source_args()["files"]
        files[0]["path"] = "SYNTHETIC_PRIVATE_FILENAME.py"
        with self.assertRaisesRegex(ContractError, "software_filesystem_unavailable") as caught:
            self.source(files=files)
        self.assertNotIn("SYNTHETIC_PRIVATE_FILENAME", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_sw03_explicit_span_masks_metadata_and_duplicate_occurrences(self):
        secret = "SYNTHETIC_PRIVATE_TITLE"
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["metadata"]["name"] = secret
        scope = self.call("SW-01", **payload)["artifacts"]
        rights = self.call("SW-07", scope=scope, rights=self.fixture["rights"])["artifacts"]
        (self.root / "counter.py").write_text(secret + "\n" + secret + "\n", encoding="utf-8")
        material = self.source(scope=scope, rights_decisions=rights)["artifacts"]
        output = self.call("SW-03", material=material, redactions=[
            {"file_id": "f1", "line": 1, "start": 1, "end": len(secret), "basis_id": "synthetic-policy"}])
        self.assertNotIn(secret, json.dumps(output, ensure_ascii=False))
        self.assertEqual(output["artifacts"]["document"]["metadata"]["name"], "█" * len(secret))

    def test_sw05_environment_mismatch_and_unpublished_unknown(self):
        material = self.source()["artifacts"]
        form = self.form(material)
        form["runtime_environment"] = {"description": "Different OS", "evidence_id": "e"}
        output = self.call("SW-05", scope=self.scope, material=material,
                           manual=self.manual()["artifacts"], form=form)
        self.assertIn("field_mismatch:runtime_environment", {item["code"] for item in output["issues"]})

    def test_sw07_empty_claim_never_selected_as_original(self):
        payload = copy.deepcopy(self.fixture["scope_input"])
        payload["components"][0]["claim"] = []
        scope = self.call("SW-01", **payload)["artifacts"]
        output = self.call("SW-07", scope=scope, rights=self.fixture["rights"])
        self.assertEqual(output["artifacts"]["decisions"][0]["decision"], "exclude")

    def test_sw08_unknown_expression_classification_and_missing_pair_evidence(self):
        pair = self.pair("unknown")
        output = self.call("SW-08", scope=self.scope, branch="dispute", pairs=[pair])
        self.assertIn("expression_function_classification_unknown", {item["code"] for item in output["issues"]})
        del pair["left"]["evidence_id"]
        with self.assertRaises(ContractError):
            self.call("SW-08", scope=self.scope, branch="dispute", pairs=[pair])

    def context_source_args(self, origin="third_party", requested="retain_notice"):
        scope_input = copy.deepcopy(self.fixture["scope_input"])
        if origin != "own":
            scope_input["components"][0].update(origin=origin, claim=[])
        scope = self.call("SW-01", **scope_input)["artifacts"]
        rights = copy.deepcopy(self.fixture["rights"])
        rights[0].update(requested_decision=requested, license="synthetic-license",
                         notice="synthetic attribution")
        decisions = self.call("SW-07", scope=scope, rights=rights)["artifacts"]
        args = self.source_args()
        args.update(scope=scope, rights_decisions=decisions,
                    selection_basis="deposit_context", require_complete_source=True)
        args["files"][0]["deposit_context_evidence"] = "synthetic-context-necessity"
        return args

    def test_sw02_new_context_retains_notice_without_original_claim(self):
        for origin, requested in (("third_party", "retain_notice"),
                                  ("third_party", "exclude"), ("own", "exclude")):
            with self.subTest(origin=origin, requested=requested):
                args = self.context_source_args(origin, requested)
                output = self.source(**args)
                material = output["artifacts"]
                self.assertEqual(material["selected_source_lines"], 3)
                self.assertEqual(material["original_source_lines"], 0)
                self.assertEqual(material["source_coverage"]["status"], "complete")
                self.assertEqual(material["manifest"][0]["selection_basis"],
                                 "deposit_context")
                self.assertEqual(material["manifest"][0]["deposit_context_evidence"],
                                 "synthetic-context-necessity")
                self.assertTrue(all(line["selection_basis"] == "deposit_context"
                                    for line in material["selected_lines"]))
                self.assertEqual(material["notices"][0]["notice"],
                                 "synthetic attribution")
                self.assertEqual(args["rights_decisions"]["decisions"][0]["decision"],
                                 requested)

    def test_sw02_new_excluded_third_party_context_requires_license_and_notice(self):
        for missing in ("license", "notice"):
            with self.subTest(missing=missing):
                args = self.context_source_args("third_party", "exclude")
                rights = copy.deepcopy(self.fixture["rights"])
                rights[0].update(requested_decision="exclude", license="synthetic-license",
                                 notice="synthetic attribution")
                rights[0].pop(missing)
                decisions = self.call("SW-07", scope=args["scope"], rights=rights)["artifacts"]
                self.assertEqual(decisions["decisions"][0]["decision"], "exclude")
                args["rights_decisions"] = decisions
                output = self.source(**args)
                material = output["artifacts"]
                self.assertEqual(material["selected_source_lines"], 0)
                self.assertEqual(material["original_source_lines"], 0)
                self.assertEqual(material["source_coverage"]["status"], "partial")
                self.assertEqual(material["source_coverage"]["omitted_file_ids"], ["f1"])
                self.assertEqual(output["status"], "partial")
                self.assertIn({"code": "license_or_notice_missing", "item_id": "f1"},
                              output["issues"])
                self.assertEqual(material["excluded"][0]["reason"], "license_or_notice_missing")
                self.assertEqual(material["manifest"][0]["sha256"],
                                 sha256_bytes((self.root / "counter.py").read_bytes()))
                legacy = self.source(**(args | {"selection_basis": "claimed_expression",
                                               "require_complete_source": False}))
                self.assertEqual(legacy["artifacts"]["selected_source_lines"], 0)
                self.assertEqual({issue["code"] for issue in legacy["issues"]},
                                 {"no_selected_source"})

    def test_sw02_new_legacy_selection_still_excludes_context(self):
        args = self.context_source_args()
        del args["selection_basis"]
        del args["require_complete_source"]
        output = self.source(**args)
        self.assertEqual(output["artifacts"]["selected_source_lines"], 0)
        self.assertEqual({item["code"] for item in output["issues"]},
                         {"no_selected_source"})
        self.assertEqual(output["artifacts"]["selection_basis"], "claimed_expression")

    def test_sw02_new_context_requires_nonempty_per_file_evidence(self):
        for evidence in (None, "", "   ", [], {}):
            with self.subTest(evidence=evidence):
                args = self.context_source_args()
                args["files"][0]["deposit_context_evidence"] = evidence
                output = self.source(**args)
                self.assertEqual(output["artifacts"]["selected_source_lines"], 0)
                self.assertIn("deposit_context_evidence_missing",
                              {item["code"] for item in output["issues"]})
                self.assertEqual(output["artifacts"]["source_coverage"]
                                 ["omitted_file_ids"], ["f1"])

    def test_sw02_new_context_cannot_authorize_public_or_unknown_basis(self):
        with patch.object(Path, "open") as opened:
            for changes, code in (({"selection_basis": "deposit_context",
                                    "selection_purpose": "public"},
                                   "deposit_context_purpose_invalid"),
                                  ({"selection_basis": "anything"},
                                   "selection_basis_unknown"),
                                  ({"require_complete_source": "yes"},
                                   "source_completeness_boolean_required")):
                with self.subTest(changes=changes):
                    with self.assertRaisesRegex(ContractError, code):
                        self.source(**changes)
            opened.assert_not_called()

    def test_sw02_new_context_does_not_bypass_permission_or_unresolved_rights(self):
        for permission in ("deny", "unknown"):
            args = self.context_source_args()
            decisions = copy.deepcopy(args["rights_decisions"])
            decisions["decisions"][0]["permissions"]["deposit"] = permission
            decisions["binding"] = digest({k: v for k, v in decisions.items()
                                           if k != "binding"})
            output = self.source(**(args | {"rights_decisions": decisions}))
            self.assertEqual(output["artifacts"]["selected_source_lines"], 0)
            self.assertIn("selection_purpose_not_authorized",
                          {item["code"] for item in output["issues"]})
        args = self.context_source_args("ai", "claim")
        output = self.source(**args)
        self.assertEqual(output["artifacts"]["selected_source_lines"], 0)
        self.assertEqual(output["artifacts"]["excluded"][0]["reason"], "needs_evidence")
        for decision in ("prohibit", "needs_permission"):
            decisions = copy.deepcopy(self.rights)
            decisions["decisions"][0]["decision"] = decision
            decisions["binding"] = digest({k: v for k, v in decisions.items()
                                           if k != "binding"})
            with patch.object(Path, "open") as opened:
                output = self.source(rights_decisions=decisions,
                                     selection_basis="deposit_context",
                                     require_complete_source=True)
                opened.assert_not_called()
            self.assertEqual(output["artifacts"]["source_coverage"]["status"], "partial")

    def test_sw02_new_generated_and_dependency_never_become_context_source(self):
        args = self.context_source_args("generated", "exclude")
        material = self.source(**args)["artifacts"]
        self.assertEqual(material["selected_source_lines"], 0)
        self.assertEqual(material["original_source_lines"], 0)
        self.assertEqual(material["excluded"][0]["reason"], "generated")
        for kind in ("generated", "dependency"):
            args = self.context_source_args()
            args["files"][0]["kind"] = kind
            material = self.source(**args)["artifacts"]
            self.assertEqual(material["selected_source_lines"], 0)
            self.assertEqual(material["excluded"][0]["reason"], kind)

    def test_sw02_new_claim_and_local_context_bases_are_distinct(self):
        material = self.source(selection_basis="deposit_context")["artifacts"]
        self.assertEqual(material["manifest"][0]["selection_basis"], "claimed_expression")
        self.assertTrue(all(line["selection_basis"] == "claimed_expression"
                            for line in material["selected_lines"]))
        args = self.context_source_args()
        args["selection_purpose"] = "local_process"
        material = self.source(**args)["artifacts"]
        self.assertEqual(material["selected_source_lines"], 3)
        self.assertEqual(material["manifest"][0]["selection_basis"], "deposit_context")

    def test_sw02_new_partial_ranges_report_whole_source_coverage(self):
        files = self.source_args()["files"]
        files[0]["ranges"] = [[1, 1]]
        output = self.source(files=files, require_complete_source=True)
        coverage = output["artifacts"]["source_coverage"]
        self.assertEqual(coverage, {
            "status": "partial", "basis": "declared_inventory_not_disk_discovery",
            "candidate_source_lines": 1, "omitted_file_ids": [],
            "incomplete_range_file_ids": ["f1"]})
        self.assertEqual(output["status"], "partial")
        self.assertIn("source_coverage_incomplete", {i["code"] for i in output["issues"]})
        legacy = self.source(files=files)
        self.assertEqual(legacy["issues"], [])
        self.assertEqual(legacy["artifacts"]["source_coverage"]["status"], "partial")

    def test_sw02_new_coverage_omissions_encoding_suffix_and_inventory(self):
        (self.root / "bad.py").write_bytes(b"\xff\xfe\xff")
        (self.root / "custom.xyz").write_bytes(b"synthetic source")
        (self.root / "omit.py").write_bytes(b"synthetic omitted source")
        files = self.source_args()["files"] + [
            {"id": "bad", "path": "bad.py", "component_id": "cli",
             "kind": "source", "include": True},
            {"id": "custom", "path": "custom.xyz", "component_id": "cli",
             "kind": "source", "include": True},
            {"id": "omit", "path": "omit.py", "component_id": "cli",
             "kind": "source", "include": False, "exclusion_reason": "synthetic"}]
        output = self.source(files=files, require_complete_source=True)
        coverage = output["artifacts"]["source_coverage"]
        self.assertEqual(coverage["omitted_file_ids"], ["bad", "custom", "omit"])
        self.assertEqual(coverage["candidate_source_lines"], 3)
        self.assertEqual(coverage["status"], "partial")
        output = self.source(inventory_complete=False, require_complete_source=True)
        self.assertEqual(output["artifacts"]["source_coverage"]["status"], "partial")
        self.assertIn("source_coverage_incomplete", {i["code"] for i in output["issues"]})

    def test_sw02_new_head_tail_uses_complete_mother_source(self):
        (self.root / "counter.py").write_text("\n".join(str(i) for i in range(40)),
                                             encoding="utf-8")
        pagination = {"lines_per_page": 2, "wrap_columns": 8, "selection": "head_tail",
                      "pages_each_end": 1, "basis": "synthetic"}
        output = self.source(pagination=pagination, require_complete_source=True)
        material = output["artifacts"]
        self.assertEqual(output["issues"], [])
        self.assertEqual(material["source_coverage"]["candidate_source_lines"], 40)
        self.assertEqual(material["source_coverage"]["status"], "complete")
        self.assertEqual(material["selected_source_lines"], 4)
        self.assertEqual([line["source_line"] for line in material["selected_lines"]],
                         [1, 2, 39, 40])

    def test_sw02_new_hash_checked_against_bytes_before_material(self):
        files = self.source_args()["files"]
        files[0]["expected_sha256"] = sha256_bytes((self.root / "counter.py").read_bytes())
        material = self.source(files=files)["artifacts"]
        self.assertEqual(material["manifest"][0]["sha256"], files[0]["expected_sha256"])
        (self.root / "counter.py").write_bytes(b"SYNTHETIC_PRIVATE_SOURCE")
        with self.assertRaisesRegex(ContractError, "source_hash_mismatch") as caught:
            self.source(files=files)
        self.assertEqual(str(caught.exception), "source_hash_mismatch")

    def test_sw02_new_hash_format_rejected_without_path_or_value(self):
        for invalid in (None, 123, "secret", "a" * 63, "g" * 64):
            with self.subTest(invalid=invalid):
                files = self.source_args()["files"]
                files[0]["expected_sha256"] = invalid
                with self.assertRaisesRegex(ContractError, "source_hash_invalid") as caught:
                    self.source(files=files)
                self.assertEqual(str(caught.exception), "source_hash_invalid")

    def prepare_args(self):
        source = self.source_args()
        return {"context": self.context, "authorized_root": str(self.root),
                "scope_input": copy.deepcopy(self.fixture["scope_input"]),
                "rights": copy.deepcopy(self.fixture["rights"]),
                "files": source["files"], "inventory_complete": True,
                "pagination": source["pagination"],
                "manual_input": copy.deepcopy(self.fixture["manual_input"]),
                "form_rule_evidence": "synthetic-form-rule"}

    def preparation(self, **changes):
        self.assertTrue(callable(getattr(software, "prepare", None)),
                        "software.prepare must own the preparation chain")
        return software.prepare(self.prepare_args() | changes)

    def test_system_time_rechecks_permission_before_each_source_open(self):
        (self.root / "second.py").write_text("synthetic second source\n", encoding="utf-8")
        files = self.source_args()["files"] + [
            {"id": "f2", "path": "second.py", "component_id": "cli",
             "kind": "source", "include": True}]
        context = copy.deepcopy(self.context)
        context["permissions"][0]["valid_until"] = "2026-11-13T12:00:01Z"
        initial = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
        expired = datetime(2026, 11, 13, 12, 0, 1, tzinfo=timezone.utc)
        frozen = copy.deepcopy(context)
        real_open = Path.open
        for entry_point in ("run", "prepare"):
            with self.subTest(entry_point=entry_point):
                function = getattr(software, entry_point)
                self.assertIn("use_system_time", inspect.signature(function).parameters)
                current = [initial]
                opened = []

                def tracked_open(path, *args, **kwargs):
                    opened.append(path.name)
                    stream = real_open(path, *args, **kwargs)
                    current[0] = expired
                    return stream

                with patch("tools.software.datetime", create=True) as clock:
                    clock.now.side_effect = lambda _tz: current[0]
                    with patch.object(Path, "open", tracked_open):
                        with self.assertRaisesRegex(ContractError, "permission_not_proven"):
                            if entry_point == "prepare":
                                function(self.prepare_args() | {"context": context, "files": files},
                                         use_system_time=True)
                            else:
                                function("SW-02", self.source_args() | {
                                    "context": context, "files": files}, use_system_time=True)
                self.assertEqual(opened, ["counter.py"])
                self.assertEqual(context, frozen)

    def test_system_time_is_keyword_only_and_json_cannot_override_clock(self):
        for function in (run, software.prepare):
            parameter = inspect.signature(function).parameters.get("use_system_time")
            self.assertIsNotNone(parameter)
            self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertIs(parameter.default, False)
        args = self.prepare_args()
        with self.assertRaisesRegex(ContractError, "preparation_input_unknown"):
            software.prepare(args | {"use_system_time": False}, use_system_time=True)
        with patch("tools.software.datetime", create=True) as clock:
            clock.now.return_value = datetime(2027, 2, 1, tzinfo=timezone.utc)
            with patch.object(Path, "open") as opened:
                with self.assertRaisesRegex(ContractError, "permission_not_proven"):
                    run("SW-02", self.source_args() | {
                        "context": self.context, "use_system_time": False}, use_system_time=True)
                opened.assert_not_called()
            legacy = self.source()
            self.assertEqual(legacy["artifacts"]["selected_source_lines"], 3)

    def test_system_time_prepare_leaves_input_unchanged_and_success_is_needs_review(self):
        self.assertIn("use_system_time", inspect.signature(software.prepare).parameters)
        args = self.prepare_args()
        frozen = copy.deepcopy(args)
        with patch("tools.software.datetime", create=True) as clock:
            clock.now.return_value = datetime(2026, 11, 13, tzinfo=timezone.utc)
            output = software.prepare(args, use_system_time=True)
        self.assertEqual(output["status"], "needs_review")
        self.assertEqual(output["artifacts"]["source"]["source_coverage"]["status"], "complete")
        self.assertEqual(args, frozen)

    def test_prepare_chain_owns_bindings_and_caps_status(self):
        output = self.preparation()
        artifacts = output["artifacts"]
        self.assertEqual(output["capability"], "SW-02")
        self.assertEqual(output["status"], "needs_review")
        self.assertEqual(artifacts["kind"], "software_preparation")
        scope, rights, source = (artifacts[key] for key in ("scope", "rights", "source"))
        self.assertEqual(rights["scope_binding"], scope["binding"])
        self.assertEqual(source["rights_binding"], rights["binding"])
        self.assertEqual(source["selection_basis"], "deposit_context")
        self.assertEqual(source["selection_purpose"], "deposit")
        self.assertEqual(source["source_coverage"]["status"], "complete")
        self.assertEqual(artifacts["consistency"]["bindings"]["form"],
                         digest(artifacts["form"]))
        self.assertEqual(artifacts["consistency"]["bindings"]["material"], source["binding"])
        self.assertTrue(all(item["capability"] in CAPABILITIES for item in output["issues"]))
        self.assertIn({"capability": "SW-04", "code": "runtime_not_verified"}, output["issues"])
        self.assertEqual(output["professional_review"], "not_performed")
        self.assertEqual(output["official_status"], "not_asserted")
        self.assertEqual(output["external_action"], "not_performed")
        self.assertEqual(artifacts["binding"], digest({k: v for k, v in artifacts.items()
                                                     if k != "binding"}))

    def test_prepare_missing_manual_preserves_source_and_known_form(self):
        args = self.prepare_args()
        del args["manual_input"]
        self.assertTrue(callable(getattr(software, "prepare", None)))
        output = software.prepare(args)
        artifacts = output["artifacts"]
        self.assertEqual(output["status"], "partial")
        self.assertIsNone(artifacts["manual"])
        self.assertIsNone(artifacts["consistency"])
        self.assertEqual(artifacts["source"]["selected_source_lines"], 3)
        self.assertEqual(artifacts["form"]["total_source_lines"], 3)
        self.assertIn({"capability": "SW-04", "code": "manual_input_missing"}, output["issues"])

    def test_prepare_unknown_dates_remain_unknown_not_filled(self):
        scope_input = copy.deepcopy(self.fixture["scope_input"])
        for key in ("completed_date", "published_date", "runtime_environment"):
            scope_input["metadata"].pop(key)
        output = self.preparation(scope_input=scope_input)
        for key in ("completed_date", "published_date", "runtime_environment"):
            self.assertIn(key, output["artifacts"]["form"])
            self.assertIsNone(output["artifacts"]["form"][key])
            self.assertIsNone(output["artifacts"]["scope"]["metadata"][key])
        self.assertIn({"capability": "SW-01", "code": "completed_date_unknown"}, output["issues"])
        self.assertIsNotNone(output["artifacts"]["manual"])
        self.assertIsNotNone(output["artifacts"]["consistency"])
        self.assertEqual(output["status"], "partial")

    def test_prepare_missing_form_rule_is_partial_but_public_permission_is_not(self):
        output = self.preparation(form_rule_evidence=None)
        self.assertEqual(output["status"], "partial")
        self.assertIn({"capability": "SW-05", "code": "current_form_rule_unverified"},
                      output["issues"])
        output = self.preparation()
        self.assertEqual(output["status"], "needs_review")
        self.assertIn({"capability": "SW-07", "code": "public_not_authorized", "item_id": "cli"},
                      output["issues"])

    def test_prepare_partial_ranges_force_partial_and_true_quantities(self):
        files = self.source_args()["files"]
        files[0]["ranges"] = [[1, 1]]
        output = self.preparation(files=files)
        self.assertEqual(output["status"], "partial")
        self.assertEqual(output["artifacts"]["form"]["total_source_lines"], 3)
        self.assertEqual(output["artifacts"]["form"]["selected_source_lines"], 1)
        self.assertIn({"capability": "SW-02", "code": "source_coverage_incomplete"}, output["issues"])

    def test_prepare_explicit_form_not_replaced_and_mismatch_owned(self):
        form = {"name": "different", "version": "1.0", "total_source_lines": 99,
                "selected_source_lines": 99}
        output = self.preparation(form=form)
        self.assertEqual(output["artifacts"]["form"], form)
        self.assertIn({"capability": "SW-05", "code": "quantity_mismatch:total_source_lines"},
                      output["issues"])
        self.assertIn({"capability": "SW-05", "code": "field_mismatch:name", "item_id": "form"},
                      output["issues"])

    def test_prepare_rejects_overrides_before_read(self):
        for section, key in ((None, "scope"), (None, "rights_decisions"),
                             (None, "material"), (None, "selection_basis"),
                             (None, "require_complete_source"),
                             ("scope_input", "context"), ("scope_input", "authorized_root"),
                             ("manual_input", "scope"), ("manual_input", "context"),
                             ("manual_input", "material")):
            with self.subTest(section=section, key=key):
                args = self.prepare_args()
                target = args if section is None else args[section]
                target[key] = {"SYNTHETIC_PRIVATE_OVERRIDE": True}
                self.assertTrue(callable(getattr(software, "prepare", None)))
                with patch.object(Path, "open") as opened:
                    with self.assertRaisesRegex(ContractError, "preparation_input_unknown") as caught:
                        software.prepare(args)
                    opened.assert_not_called()
                self.assertEqual(str(caught.exception), "preparation_input_unknown")

    def test_prepare_hash_mismatch_and_denied_context_abort(self):
        files = self.source_args()["files"]
        files[0]["expected_sha256"] = "0" * 64
        self.assertTrue(callable(getattr(software, "prepare", None)))
        with self.assertRaisesRegex(ContractError, "source_hash_mismatch"):
            software.prepare(self.prepare_args() | {"files": files})
        context = copy.deepcopy(self.context)
        context["permissions"] = []
        with patch.object(Path, "open") as opened:
            with self.assertRaisesRegex(ContractError, "permission_not_proven"):
                software.prepare(self.prepare_args() | {"context": context})
            opened.assert_not_called()

    def test_prepare_version_change_invalidates_without_mutating_or_chain_drift(self):
        first = self.preparation()["artifacts"]
        frozen = copy.deepcopy(first)
        unchanged = self.preparation(previous_preparation=first)
        self.assertEqual(unchanged["artifacts"], first)
        scope_input = copy.deepcopy(self.fixture["scope_input"])
        scope_input["metadata"]["version"] = "2.0"
        scope_input["components"][0]["version"] = "2.0"
        changed = self.preparation(scope_input=scope_input, previous_preparation=first)
        second = changed["artifacts"]
        self.assertEqual(second["supersedes"], first["binding"])
        self.assertEqual(second["invalidated"], [first["binding"]])
        self.assertIn({"capability": "SW-02", "code": "previous_preparation_invalidated"},
                      changed["issues"])
        self.assertEqual(first, frozen)
        repeated = self.preparation(scope_input=scope_input, previous_preparation=second)
        self.assertEqual(repeated["artifacts"], second)
        self.assertNotIn("previous_preparation_invalidated",
                         {item["code"] for item in repeated["issues"]})
        self.assertEqual(changed["status"], "needs_review")

    def test_prepare_previous_kind_and_binding_checked_before_read(self):
        first = self.preparation()["artifacts"]
        bad = copy.deepcopy(first)
        bad["form"]["name"] = "tampered"
        for previous, code in ((self.scope, "artifact_kind_mismatch"),
                               (bad, "artifact_binding_mismatch")):
            with patch.object(Path, "open") as opened:
                with self.assertRaisesRegex(ContractError, code):
                    self.preparation(previous_preparation=previous)
                opened.assert_not_called()

    def test_vertical_chain_material_manual_consistency_mask_correction(self):
        material = self.source()["artifacts"]
        manual = self.manual()["artifacts"]
        checked = self.call("SW-05", scope=self.scope, material=material, manual=manual,
                            form=self.form(material), form_rule_evidence="synthetic-rule")
        masked = self.call("SW-03", material=material, sensitive_literals=["count"])
        correction = self.correction()
        self.assertEqual(checked["status"], "checked")
        self.assertEqual(masked["artifacts"]["source_binding"], material["binding"])
        self.assertEqual(correction["artifacts"]["history"][0]["binding"], self.scope["binding"])
        self.assertNotIn("count", json.dumps(masked["artifacts"]["document"]["pages"]))
        self.assertEqual(digest({k: v for k, v in material.items() if k != "binding"}), material["binding"])


if __name__ == "__main__":
    unittest.main()
