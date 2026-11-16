"""R08批次隔离；仅临时合成项目，不调用PDF转换或真实外部服务。"""

import contextlib
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools import core
from tools.software_batch import run_batch

ROOT = Path(__file__).resolve().parents[1]


class SoftwareBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-software-batch-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.fixture = json.loads(
            (ROOT / "evals/fixtures/software/synthetic.json").read_text(encoding="utf-8")
        )

    def project(self, identifier, *, action="prepare", manual=True):
        root = self.base / ("中文 空格 " + identifier)
        root.mkdir()
        source = (self.fixture["source"] + "# project " + identifier + "\n").encode()
        (root / "counter.py").write_bytes(source)
        request = {key: copy.deepcopy(self.fixture[key]) for key in
                   ("scope_input", "rights", "pagination", "manual_input")}
        request["scope_input"]["metadata"].update(
            software_id=identifier, name="合成软件 " + identifier,
        )
        request.update(files=[{"id": "f1", "path": "counter.py", "component_id": "cli",
                               "kind": "source", "include": True}],
                       inventory_complete=True,
                       form_rule_evidence="synthetic-not-official-rule")
        if not manual:
            del request["manual_input"]
        if action != "prepare":
            request["delivery"] = {"selection": "all", "screenshots": []}
        raw = core.canonical_bytes(request)
        (root / "request.json").write_bytes(raw)
        now = datetime.now(timezone.utc)
        permission = {
            "purpose": "software_internal_preparation", "recipient": "local_tool",
            "decision": "allow", "authority_evidence": "SYNTHETIC_PRIVATE_AUTHORITY",
            "valid_from": (now - timedelta(days=1)).isoformat(),
            "valid_until": (now + timedelta(days=1)).isoformat(),
        }
        authorization = {
            "kind": "software_local_authorization", "authorized_root": str(root),
            "context": {"environment": {}, "sensitivity": "synthetic",
                        "purpose": permission["purpose"], "permissions": [
                            {**permission, "action": "local_read"},
                            {**permission, "action": "local_write"}]},
            "request": {"path": "request.json", "sha256": core.sha256_bytes(raw)},
            "files": [{"path": "counter.py", "sha256": core.sha256_bytes(source)}],
            "output": "prepared.json" if action == "prepare" else "pack",
        }
        project = {"id": identifier, "root": str(root), "action": action,
                   "authorization": "authorization.json", "authorization_sha256": ""}
        self.save_authorization(project, authorization)
        return project

    def save_authorization(self, project, authorization):
        raw = core.canonical_bytes(authorization)
        (Path(project["root"]) / project["authorization"]).write_bytes(raw)
        project["authorization_sha256"] = core.sha256_bytes(raw)

    def authorization(self, project):
        return json.loads((Path(project["root"]) / project["authorization"]).read_bytes())

    def prepared(self, project):
        return json.loads((Path(project["root"]) / "prepared.json").read_bytes())

    def test_two_real_projects_and_failure_are_independent_from_any_cwd(self):
        first = self.project("alpha")
        broken = self.project("broken")
        broken["authorization_sha256"] = "0" * 64
        second = self.project("beta", manual=False)
        elsewhere = self.base / "unrelated cwd"
        elsewhere.mkdir()
        with contextlib.chdir(elsewhere):
            result = run_batch([first, broken, second])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["counts"], {
            "completed": 0, "needs_confirmation": 2, "failed": 1, "skipped": 0,
        })
        rows = result["projects"]
        self.assertEqual([row["id"] for row in rows], ["alpha", "broken", "beta"])
        self.assertEqual(rows[1]["issues"], ["input_snapshot_mismatch"])
        self.assertIn("manual_input_missing", rows[2]["issues"])
        for project, row in ((first, rows[0]), (second, rows[2])):
            artifact = self.prepared(project)["artifacts"]
            self.assertEqual(artifact["scope"]["metadata"]["software_id"], project["id"])
            self.assertEqual(row["binding"]["preparation"], artifact["binding"])
            self.assertEqual(row["output"], "prepared.json")
            self.assertEqual(row["execution"], "completed")
        self.assertNotEqual(rows[0]["binding"], rows[2]["binding"])
        self.assertFalse((Path(broken["root"]) / "prepared.json").exists())
        self.assertIsNone(self.prepared(second)["artifacts"]["manual"])
        self.assertIsNotNone(self.prepared(first)["artifacts"]["manual"])
        encoded = json.dumps(result, ensure_ascii=False)
        for material in (self.fixture["source"], "SYNTHETIC_PRIVATE_AUTHORITY",
                         "合成软件 alpha", "permissions", "artifacts"):
            self.assertNotIn(material, encoded)

    def test_real_build_and_verify_keep_each_package_and_bindings(self):
        projects = [self.project("alpha", action="build"),
                    self.project("beta", action="build")]
        built = run_batch(projects)
        self.assertEqual(built["status"], "needs_confirmation")
        self.assertEqual(built["counts"]["needs_confirmation"], 2)
        manifests = []
        for project, row in zip(projects, built["projects"], strict=True):
            root = Path(project["root"])
            manifest = json.loads((root / "pack/manifest.json").read_bytes())
            manifests.append(manifest)
            self.assertEqual(row["binding"]["preparation"], manifest["preparation_binding"])
            text = (root / "pack/body/worksheet.txt").read_text(encoding="utf-8")
            self.assertIn(project["id"], text)
            other = "beta" if project["id"] == "alpha" else "alpha"
            self.assertNotIn("合成软件 " + other, text)
            self.assertIn("pdf_not_generated", row["issues"])
        self.assertNotEqual(manifests[0]["preparation_binding"],
                            manifests[1]["preparation_binding"])
        before = [(Path(project["root"]) / "pack/manifest.json").read_bytes()
                  for project in projects]
        verified = run_batch([{**project, "action": "verify"} for project in projects])
        self.assertEqual(verified["counts"]["needs_confirmation"], 2)
        self.assertTrue(all(row["execution"] == "completed"
                            for row in verified["projects"]))
        self.assertEqual(before, [(Path(project["root"]) / "pack/manifest.json").read_bytes()
                                  for project in projects])

    def test_denied_project_reads_no_request_and_next_project_runs(self):
        denied = self.project("denied")
        allowed = self.project("allowed")
        authorization = self.authorization(denied)
        authorization["context"]["permissions"] = []
        self.save_authorization(denied, authorization)
        opened = []
        original = Path.open

        def guarded(path, *args, **kwargs):
            if path.parent.name == Path(denied["root"]).name:
                opened.append(path.name)
                self.assertEqual(path.name, "authorization.json")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            result = run_batch([denied, allowed])
        self.assertTrue(opened)
        self.assertEqual(result["projects"][0]["issues"], ["permission_not_proven"])
        self.assertEqual(result["projects"][1]["execution"], "completed")

    def test_disabled_missing_project_opens_no_files(self):
        project = {"id": "disabled", "root": str(self.base / "absent"),
                   "authorization": "absent.json", "authorization_sha256": "0" * 64,
                   "action": "build", "enabled": False}
        with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
            result = run_batch([project])
        self.assertEqual(result["status"], "skipped")
        row = result["projects"][0]
        self.assertEqual(row["status"], "skipped")
        self.assertIsNone(row["output"])
        self.assertIsNone(row["binding"])

    def test_all_descriptors_validate_before_any_material_or_output(self):
        project = self.project("alpha")
        for forbidden in ("context", "environment", "permissions", "now", "output",
                          "pdf_tool", "pdf_text_tool", "request", "files"):
            with self.subTest(field=forbidden):
                invalid = {**project, "id": "invalid", forbidden: "SYNTHETIC_SECRET"}
                with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                    with self.assertRaisesRegex(core.ContractError, "batch_project_fields_invalid"):
                        run_batch([project, invalid])
                self.assertFalse((Path(project["root"]) / "prepared.json").exists())

    def test_duplicate_and_nested_roots_reject_whole_batch_before_reads(self):
        project = self.project("alpha")
        for root in (project["root"], str(Path(project["root"]) / "child"),
                     str(Path(project["root"]) / ".." / Path(project["root"]).name)):
            with self.subTest(root=root):
                with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                    with self.assertRaisesRegex(core.ContractError, "batch_root_reused"):
                        run_batch([project, {**project, "id": "beta", "root": root}])
        self.assertFalse((Path(project["root"]) / "prepared.json").exists())

    def test_repeated_output_fails_without_overwrite_and_other_root_continues(self):
        first = self.project("alpha")
        run_batch([first])
        before = (Path(first["root"]) / "prepared.json").read_bytes()
        second = self.project("beta")
        result = run_batch([first, second])
        self.assertEqual(result["projects"][0]["issues"], ["output_exists"])
        self.assertEqual(result["projects"][1]["execution"], "completed")
        self.assertEqual((Path(first["root"]) / "prepared.json").read_bytes(), before)

    def test_output_inside_other_project_root_is_rejected_by_existing_boundary(self):
        first = self.project("alpha")
        second = self.project("beta")
        authorization = self.authorization(first)
        authorization["output"] = "../" + Path(second["root"]).name + "/prepared.json"
        self.save_authorization(first, authorization)
        result = run_batch([first, second])
        self.assertEqual(result["projects"][0]["issues"], ["unsafe_path"])
        self.assertEqual(result["projects"][1]["execution"], "completed")

    def test_invalid_controls_are_rejected_before_opening(self):
        project = self.project("alpha")
        variants = [[], {}, [None], [{**project, "action": "export"}],
                    [{**project, "enabled": "false"}], [{**project, "root": "relative"}],
                    [{**project, "authorization": "../private.json"}],
                    [{**project, "authorization_sha256": "not-a-hash"}],
                    [{**project, "id": "invalid\nsecret"}], [project, dict(project)]]
        for projects in variants:
            with self.subTest(projects=projects):
                with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                    with self.assertRaises(core.ContractError):
                        run_batch(projects)

    def test_exception_text_and_unknown_issue_details_are_sanitized(self):
        project = self.project("alpha")
        for exception, code in (
            (core.ContractError("SYNTHETIC_SECRET"), "contract_rejected"),
            (OSError("SYNTHETIC_SECRET"), "project_filesystem_unavailable"),
            (ValueError("SYNTHETIC_SECRET"), "project_input_invalid"),
        ):
            with self.subTest(exception=type(exception).__name__):
                with patch("tools.cli._prepare_software", side_effect=exception):
                    result = run_batch([project])
                self.assertEqual(result["projects"][0]["issues"], [code])
                self.assertNotIn("SYNTHETIC_SECRET", json.dumps(result))
        response = {"status": "needs_review", "issues": [
            {"code": "unknown:SYNTHETIC_SECRET", "material": "SYNTHETIC_SECRET"}],
            "artifacts": {"binding": "1" * 64, "source": "SYNTHETIC_SECRET"}}
        with patch("tools.cli._prepare_software", return_value=response):
            result = run_batch([project])
        self.assertIn("project_review_issue", result["projects"][0]["issues"])
        self.assertNotIn("SYNTHETIC_SECRET", json.dumps(result))

    def test_completed_is_distinct_from_pending_review_and_disabled(self):
        project = self.project("alpha")
        response = {"status": "checked", "issues": [], "artifacts": {"binding": "1" * 64}}
        with patch("tools.cli._prepare_software", return_value=response) as prepare:
            result = run_batch([project])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["counts"]["completed"], 1)
        args = prepare.call_args.args[0]
        self.assertFalse(args.verify)
        self.assertIsNone(args.pdf_tool)
        self.assertIsNone(args.pdf_text_tool)
        self.assertFalse(prepare.call_args.kwargs["document_output"])

    def test_changed_package_failure_does_not_hide_other_verification(self):
        projects = [self.project("alpha", action="build"),
                    self.project("beta", action="build")]
        run_batch(projects)
        (Path(projects[0]["root"]) / "pack/body/source.txt").write_text(
            "SYNTHETIC_PRIVATE_CHANGED_SOURCE", encoding="utf-8")
        result = run_batch([{**project, "action": "verify"} for project in projects])
        self.assertEqual(result["projects"][0]["status"], "failed")
        self.assertEqual(result["projects"][1]["execution"], "completed")
        self.assertNotIn("SYNTHETIC_PRIVATE_CHANGED_SOURCE", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
