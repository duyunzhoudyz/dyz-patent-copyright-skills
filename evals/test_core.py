"""合成WP-01验收；不代表专业预期已由有权人确认。"""

import copy
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import bundle, core
from tools.core import (
    ContractError, VersionLedger, assess_contributions, canonical_bytes,
    capture_evidence, check_permission, digest, parse_time, record_deadline,
    result, route_project, safe_path, select_rules, write_new_json,
)

NOW = "2026-10-31T10:00:00+00:00"


def permission(action="local_read", recipient="local_tool"):
    return {"action": action, "purpose": "synthetic_test", "recipient": recipient,
            "decision": "allow", "authority_evidence": "synthetic-consent",
            "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z"}


class CoreTests(unittest.TestCase):
    def test_ac_core_01_three_independent_tasks(self):
        requests = [
            {"business": business, "goal": "synthetic", "owner": "test-owner",
             "adaptation": {"stage": "draft", "domain": "software", "jurisdiction": "TEST",
                            "right_type": "test", "organization": "TEST", "standard_type": "interface"}}
            for business in ("patent", "software", "standard")
        ]
        project = route_project("synthetic", requests, ["ev-1"])
        project["tasks"][0]["status"] = "needs_evidence"
        self.assertEqual(project["tasks"][1]["status"], "draft")
        self.assertEqual(len({x["task_id"] for x in project["tasks"]}), 3)
        self.assertTrue(all(x["official_status"] == "not_asserted" for x in project["tasks"]))

    def test_unknown_business_and_missing_adaptation(self):
        with self.assertRaises(ContractError):
            route_project("p", [{"business": "other", "goal": "x", "owner": "x", "adaptation": {}}], [])
        with self.assertRaises(ContractError):
            route_project("p", [{"business": "patent", "goal": "x", "owner": "x", "adaptation": {}}], [])

    def test_ac_core_02_conflicting_ownership_retained(self):
        facts = [{"subject": "program", "claim": value, "evidence_id": f"e{index}"}
                 for index, value in enumerate(("company-A", "company-B"))]
        output = assess_contributions(facts)
        self.assertEqual(output["status"], "needs_evidence")
        self.assertEqual(len(output["artifacts"]["facts"]), 2)
        self.assertEqual(output["artifacts"]["ownership"], "undetermined")

    def test_ac_core_03_versions_missing_pages_fixed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "sample.txt")
            path.write_bytes(b"synthetic-v1")
            args = dict(source={"id": "doc", "version": "1", "origin": "synthetic", "level": "test"},
                        permissions=[permission()], environment={}, sensitivity="synthetic",
                        purpose="synthetic_test", acquired_at=NOW, locator="page-1",
                        extraction_status="missing_pages")
            first, snapshot = capture_evidence(directory, "sample.txt", **args)
            same, _ = capture_evidence(directory, "sample.txt", **args)
            path.write_bytes(b"synthetic-v2")
            second, _ = capture_evidence(directory, "sample.txt", **args)
            self.assertEqual(first["evidence_id"], same["evidence_id"])
            self.assertNotEqual(first["evidence_id"], second["evidence_id"])
            self.assertEqual(snapshot, b"synthetic-v1")
            self.assertEqual(first["extraction_status"], "missing_pages")

    def test_preflight_before_read_confidential_unknown_host(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "read_bytes") as reader:
            with self.assertRaises(ContractError):
                capture_evidence(directory, "secret.txt", source={}, permissions=[permission()],
                                 environment={}, sensitivity="confidential", purpose="synthetic_test",
                                 acquired_at=NOW, locator="line-1")
            reader.assert_not_called()

    def test_local_permission_never_allows_cloud(self):
        with self.assertRaises(ContractError):
            check_permission([permission()], action="external_processing", purpose="synthetic_test",
                             recipient="host_model", now=NOW)

    def test_permission_expiry_revoke_recipient(self):
        allowed = permission()
        for changes in ({"valid_until": NOW}, {"revoked": True}, {"recipient": "other"},
                        {"authority_evidence": ""}, {"decision": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                check_permission([{**allowed, **changes}], action="local_read", purpose="synthetic_test",
                                 recipient="local_tool", now=NOW)

    def test_path_traversal_absolute_and_ads(self):
        with tempfile.TemporaryDirectory() as directory:
            for relative in ("../x", "a/../../x", "C:/x", "C:x", "/tmp/x", "a:secret", "a\\..\\x", "a//x"):
                with self.subTest(relative=relative), self.assertRaises(ContractError):
                    safe_path(directory, relative, must_exist=False)

    def test_macos_system_root_links_require_exact_ancestor_and_target(self):
        for name in ("var", "tmp", "etc"):
            entry = Path("/" + name)
            for target in (f"private/{name}", f"/private/{name}", "private/other", f"../private/{name}"):
                with (self.subTest(entry=entry, target=target), patch.object(core.sys, "platform", "darwin"),
                      patch.object(core.os, "readlink", return_value=target)):
                    self.assertEqual(target in (f"private/{name}", f"/private/{name}"),
                                     core.is_macos_system_root_symlink(entry))
        with (patch.object(core.sys, "platform", "darwin"),
              patch.object(core.os, "readlink", side_effect=OSError("private path")) as readlink):
            self.assertFalse(core.is_macos_system_root_symlink(Path("/home/tmp")))
            readlink.assert_not_called()
            self.assertFalse(core.is_macos_system_root_symlink(Path("/tmp")))
            readlink.assert_called_once_with(Path("/tmp"))
        with (patch.object(core.sys, "platform", "win32"), patch.object(core.os, "readlink") as readlink):
            self.assertFalse(core.is_macos_system_root_symlink(Path("/tmp")))
            readlink.assert_not_called()

    def test_checked_path_preserves_bundle_types_and_error_codes(self):
        self.assertIs(bundle._checked_path, core.checked_path)
        self.assertIs(bundle._is_macos_system_root_symlink, core.is_macos_system_root_symlink)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            leaf = base / "item"
            leaf.write_bytes(b"synthetic")
            self.assertTrue(os.path.samestat(leaf.lstat(), core.checked_path(leaf)))
            self.assertIsNone(core.checked_path(base / "missing", missing_leaf=True))
            with self.assertRaisesRegex(bundle.BundleError, "^bundle_path_missing$"):
                core.checked_path(base / "missing")
            with self.assertRaisesRegex(bundle.BundleError, "^bundle_path_missing$"):
                core.checked_path(base / "missing" / "child", missing_leaf=True)
            with self.assertRaisesRegex(bundle.BundleError, "^bundle_parent_not_directory$"):
                core.checked_path(leaf / "child")
            with (patch.object(Path, "lstat", side_effect=PermissionError("private path")),
                  self.assertRaises(PermissionError)):
                core.checked_path(leaf)

    def test_checked_path_rejects_links_and_reparse_points_before_descending(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            parent = base / "alias"
            leaf = parent / "child"
            lstat = Path.lstat
            for mode, attributes in ((stat.S_IFLNK, 0), (stat.S_IFDIR, stat.FILE_ATTRIBUTE_REPARSE_POINT)):
                calls = []
                def path_info(path):
                    calls.append(path)
                    if path == parent:
                        return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                    return lstat(path)
                with (self.subTest(mode=mode, attributes=attributes), patch.object(Path, "lstat", path_info),
                      self.assertRaisesRegex(bundle.BundleError, "^bundle_link_rejected$")):
                    core.checked_path(leaf, missing_leaf=True)
                self.assertEqual([*reversed(parent.parents), parent], calls)

    def test_checked_path_accepts_macos_system_link_only_as_ancestor(self):
        ancestor = Path("/var")
        leaf = ancestor / "item"
        directory = SimpleNamespace(st_mode=stat.S_IFDIR)
        file = SimpleNamespace(st_mode=stat.S_IFREG)
        def path_info(path):
            if path == ancestor:
                return SimpleNamespace(st_mode=stat.S_IFLNK)
            return file if path == leaf else directory
        with (patch.object(core.sys, "platform", "darwin"),
              patch.object(core.os, "readlink", return_value="private/var"),
              patch.object(Path, "lstat", path_info), patch.object(Path, "stat", return_value=directory)):
            self.assertIs(file, core.checked_path(leaf))
            with self.assertRaisesRegex(bundle.BundleError, "^bundle_link_rejected$"):
                core.checked_path(ancestor)
            with (patch.object(Path, "stat", side_effect=OSError("private path")),
                  self.assertRaisesRegex(bundle.BundleError, "^bundle_link_rejected$")):
                core.checked_path(leaf)

    def test_reserved_windows_names_use_windows_rules_on_all_hosts(self):
        for name, reserved in (("CON", True), ("Nul.txt", True), ("Lpt9.DOCX", True),
                               ("com1", True), ("Console.txt", False), ("plain.txt", False)):
            with self.subTest(name=name):
                self.assertEqual(reserved, core.is_reserved_windows_name(name))
        if hasattr(core.ntpath, "isreserved"):
            with patch.object(core.os, "path", SimpleNamespace()):
                self.assertTrue(core.is_reserved_windows_name("NUL.docx"))
                self.assertTrue(core.is_reserved_windows_name("trailing."))
                self.assertFalse(core.is_reserved_windows_name("plain.docx"))

    def test_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_new_json(directory, "output.json", {"a": 1})
            with self.assertRaises(FileExistsError):
                write_new_json(directory, "output.json", {"a": 2})
            self.assertEqual(json.loads(path.read_text()), {"a": 1})

    def test_canonical_hash_and_nonfinite_rejection(self):
        self.assertEqual(digest({"b": 1, "a": 2}), digest({"a": 2, "b": 1}))
        with self.assertRaises(ContractError):
            canonical_bytes({"invalid": float("nan")})

    def test_timezone_required(self):
        with self.assertRaises(ContractError):
            parse_time("2026-10-31T10:00:00")
        self.assertEqual(parse_time(NOW), parse_time("2026-10-31T18:00:00+08:00"))

    def test_ac_core_05_rule_versions_and_unreviewed(self):
        base = {"rule_id": "r", "source": "synthetic-source", "locator": "section-1",
                "scope": {"jurisdiction": "TEST"}, "verified_at": NOW, "license": "synthetic",
                "review_status": "professionally_verified", "review_evidence": "synthetic-only"}
        old = {**base, "version": "1", "effective_from": "2025-01-01T00:00:00Z", "effective_until": "2026-01-01T00:00:00Z"}
        new = {**base, "version": "2", "effective_from": "2026-01-01T00:00:00Z"}
        selected = select_rules([old, new], {"jurisdiction": "TEST"}, as_of=NOW)
        self.assertEqual([x["version"] for x in selected["artifacts"]["selected"]], ["2"])
        new["review_status"] = "not_checked"
        self.assertEqual(select_rules([new], {"jurisdiction": "TEST"}, as_of=NOW)["status"], "needs_review")
        self.assertEqual(select_rules([old], {"jurisdiction": "OTHER"}, as_of=NOW)["status"], "needs_review")

    def ledger(self):
        ledger = VersionLedger()
        ledger.put("attachment", {"data": "v1"})
        ledger.put("draft", {"text": "synthetic"}, dependencies=["attachment"])
        ledger.put("unrelated", {"data": "other"})
        return ledger

    def review(self, ledger, review_id, ids, kind="machine", actor="machine"):
        return ledger.add_review(review_id, ids, reviewer={"actor_id": "test", "actor_type": actor,
                                 "authority_evidence": "synthetic"}, kind=kind, decision="accepted")

    def test_ac_core_06_targeted_transitive_invalidation(self):
        ledger = self.ledger()
        self.review(ledger, "r1", ["draft"])
        self.review(ledger, "r2", ["unrelated"])
        ledger.put("attachment", {"data": "v2"})
        self.assertEqual([r["status"] for r in ledger.reviews], ["invalidated", "recorded"])
        self.assertEqual(len(ledger.records["attachment"]), 2)
        with self.assertRaisesRegex(ContractError, "stale_dependencies"):
            self.review(ledger, "r3", ["draft"])
        ledger.put("draft", {"text": "synthetic"}, dependencies=["attachment"])
        self.review(ledger, "r4", ["draft"])

    def test_identical_put_does_not_invalidate(self):
        ledger = self.ledger()
        self.review(ledger, "r1", ["attachment"])
        ledger.put("attachment", {"data": "v1"})
        self.assertEqual(len(ledger.records["attachment"]), 1)
        self.assertEqual(ledger.reviews[0]["status"], "recorded")

    def test_cycles_and_missing_dependencies_rejected(self):
        ledger = self.ledger()
        with self.assertRaises(ContractError):
            ledger.put("attachment", {}, dependencies=["draft"])
        with self.assertRaises(ContractError):
            ledger.put("missing", {}, dependencies=["unknown"])
        self.assertEqual(len(ledger.records["attachment"]), 1)

    def test_ac_life_03_model_cannot_sign_professional_or_disclosure(self):
        for kind in ("professional", "disclosure"):
            with self.subTest(kind=kind), self.assertRaises(ContractError):
                self.review(self.ledger(), "r", ["draft"], kind=kind)

    def test_ledger_roundtrip_and_defensive_copy(self):
        ledger = self.ledger()
        state = json.loads(json.dumps(ledger.export()))
        restored = VersionLedger(state["records"], state["reviews"])
        self.assertTrue(restored.is_current("draft"))
        state["records"]["draft"][-1]["payload"]["text"] = "tampered-copy"
        self.assertEqual(restored.records["draft"][-1]["payload"]["text"], "synthetic")

    def test_ac_life_01_deadline_owners_and_missing_service(self):
        for business, owner in (("patent", "PROC"), ("software", "SW-06"), ("standard", "STD-09/11")):
            value = record_deadline({"business": business, "event_id": "e", "owner": "test", "rule_id": "synthetic"})
            self.assertEqual(value["artifacts"]["rule_owner"], owner)
            self.assertIn("service_at", value["artifacts"]["missing"])
            self.assertEqual(value["status"], "needs_evidence")

    def test_ac_life_04_rule_update_targets_only_dependants(self):
        ledger = VersionLedger()
        ledger.put("org-A-rule", {"v": 1})
        ledger.put("org-A-task", {}, dependencies=["org-A-rule"])
        ledger.put("org-B-task", {})
        self.review(ledger, "rA", ["org-A-task"])
        self.review(ledger, "rB", ["org-B-task"])
        ledger.put("org-A-rule", {"v": 2})
        self.assertEqual([r["status"] for r in ledger.reviews], ["invalidated", "recorded"])

    def test_result_not_applicable_never_official_pass(self):
        value = result("CORE-01", status="not_applicable", issues=["synthetic_scope_exclusion"])
        self.assertEqual(value["professional_review"], "not_performed")
        self.assertEqual(value["external_action"], "not_performed")
        with self.assertRaises(ContractError):
            result("CORE-01", status="approved")


if __name__ == "__main__":
    unittest.main()
