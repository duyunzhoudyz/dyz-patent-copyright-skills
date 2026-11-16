"""新增软件 CLI 的真实入口回归；全部材料、许可与图片均为临时合成数据。"""

import io
import json
import os
import subprocess
import sys
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from evals import test_software_prepare as prepare_tests
from evals.test_software_delivery import png
from tools import core, documents, software, software_delivery

ROOT = Path(__file__).resolve().parents[1]


class SoftwareEntrypointTests(unittest.TestCase):
    # 仅复用夹具与调用助手，不继承旧测试，避免整套重复执行。
    setUp = prepare_tests.SoftwarePrepareCliTests.setUp
    save_request = prepare_tests.SoftwarePrepareCliTests.save_request
    args = prepare_tests.SoftwarePrepareCliTests.args
    invoke = prepare_tests.SoftwarePrepareCliTests.invoke

    def command(self, name, *extra):
        args = self.args()
        args[0] = name
        return args + list(extra)

    def process(self, args, *, stdin=None):
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-m", "tools", *args],
            cwd=ROOT, input=stdin, capture_output=True, text=True,
            encoding="utf-8", timeout=30,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    def read_json(self, relative):
        return core.strict_json_loads(
            (self.root / relative).read_text(encoding="utf-8")
        )

    def rejected(self, args, *, output):
        code, out, err = self.invoke(args)
        self.assertEqual((code, out, err), (2, "", "contract_rejected\n"))
        self.assertFalse((self.root / output).exists())

    def discovery_request(self):
        raw = core.canonical_bytes({"name": "unconfirmed-package", "version": "1.0"})
        (self.root / "package.json").write_bytes(raw)
        self.request["files"].append({
            "id": "config", "path": "package.json", "component_id": "cli",
            "kind": "other", "include": False,
        })
        self.authorization["files"].append({
            "path": "package.json", "sha256": core.sha256_bytes(raw),
        })
        for field in ("completed_date", "published_date", "runtime_environment"):
            self.request["scope_input"]["metadata"][field] = None
        self.authorization["output"] = "candidates.json"
        self.save_request()

    def build_request(self, *, purpose=None):
        self.authorization["output"] = "materials"
        self.request["delivery"] = {
            "selection": "all", "screenshots": [], "sensitive_literals": [],
        }
        if purpose:
            self.authorization["context"]["purpose"] = purpose
            for permission in self.authorization["context"]["permissions"]:
                permission["purpose"] = purpose
        self.save_request()

    def build_old_package(self):
        process = self.process(self.command("build-software"))
        self.assertEqual(
            (process.returncode, process.stdout, process.stderr),
            (4, "software_documents_partial\n", ""),
        )
        return {
            path.relative_to(self.root / "materials").as_posix(): path.read_bytes()
            for path in (self.root / "materials").rglob("*") if path.is_file()
        }

    def assert_old_package(self, snapshot):
        self.assertEqual({
            path.relative_to(self.root / "materials").as_posix(): path.read_bytes()
            for path in (self.root / "materials").rglob("*") if path.is_file()
        }, snapshot)
        self.assertEqual((self.root / "counter.py").read_bytes(), self.source)

    def export_request(self, names=("body/source.docx",)):
        self.build_request(purpose="deposit")
        snapshot = self.build_old_package()
        self.request["package"] = "materials"
        self.request["export_approval"] = {
            "files": [{"path": name, "sha256": core.sha256_bytes(
                (self.root / "materials" / name).read_bytes())} for name in names],
            "recipient": "synthetic-reviewer", "purpose": "deposit",
            "channel": "local_handoff", "evidence_id": "synthetic-file-approval",
        }
        template = self.authorization["context"]["permissions"][0]
        self.authorization["context"]["permissions"].append({
            **template, "action": "copy", "recipient": "synthetic-reviewer",
        })
        self.authorization["output"] = "recipient-copy"
        self.save_request()
        return snapshot

    def revision_request(self, raw, format_name):
        path = "revised.md" if format_name == "markdown" else "revised.docx"
        (self.root / path).write_bytes(raw)
        expected = core.sha256_bytes(raw)
        self.authorization["files"].append({"path": path, "sha256": expected})
        self.request["manual_revision"] = {
            "path": path, "sha256": expected, "format": format_name,
        }
        self.request["previous_preparation"] = self.read_json(
            "materials/internal/preparation.json"
        )
        self.authorization["output"] = "revised-materials"
        self.save_request()

    def docx(self, text, *, image=None):
        blocks = [{"id": "Title", "kind": "heading1", "text": "修订说明稿"},
                  {"id": "Prose", "kind": "paragraph", "text": text}]
        if image is not None:
            blocks.append({"id": "Figure", "kind": "image", "text": "操作图",
                           "png": image, "width": 2, "height": 2})
        metadata = self.request["scope_input"]["metadata"]
        return documents.make_software_docx(
            [blocks], title=metadata["name"], version=metadata["version"],
            kind="manual",
        )

    def test_discovery_reads_only_bound_inventory_and_keeps_unknowns(self):
        self.discovery_request()
        sentinel = self.root / "unlisted.py"
        sentinel.write_text("SYNTHETIC_UNAUTHORIZED_SENTINEL", encoding="utf-8")
        args = self.command("discover-software")
        opened = []
        original = Path.open

        def tracked(path, *values, **kwargs):
            opened.append(path.resolve())
            return original(path, *values, **kwargs)

        with patch.object(Path, "open", tracked), \
                patch.object(Path, "rglob", side_effect=AssertionError("scan")), \
                patch.object(Path, "iterdir", side_effect=AssertionError("scan")):
            code, _, err = self.invoke(args)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(set(opened), {
            (self.root / name).resolve() for name in ("authorization.json", "request.json",
                                         "counter.py", "package.json", "candidates.json")
        })
        result = self.read_json("candidates.json")
        self.assertEqual({row["path"] for row in result["file_candidates"]},
                         {"counter.py", "package.json"})
        fields = {row["field"]: row for row in result["field_candidates"]}
        for field in ("completed_date", "published_date", "runtime_environment"):
            self.assertEqual((fields[field]["status"], fields[field]["value"]),
                             ("unknown", None))
        self.assertTrue(all(row["needs_confirm"] for row in result["facts"]))
        self.assertNotIn("confirmations", result)
        self.assertNotIn("SYNTHETIC_UNAUTHORIZED_SENTINEL", json.dumps(result))
        self.assertFalse((self.root / "materials").exists())

    def test_discovery_actual_process_binds_authorization_hash(self):
        self.discovery_request()
        args = self.command("discover-software")
        args[-1] = "0" * 64
        process = self.process(args)
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (2, "", "contract_rejected\n"))
        self.assertFalse((self.root / "candidates.json").exists())

    def test_discovery_denied_component_stops_before_any_material_read(self):
        self.discovery_request()
        self.request["rights"][0]["permissions"]["local_process"] = "deny"
        self.save_request()
        args = self.command("discover-software")
        opened = []
        original = Path.open

        def tracked(path, *values, **kwargs):
            opened.append(path.name)
            return original(path, *values, **kwargs)

        with patch.object(Path, "open", tracked):
            self.rejected(args, output="candidates.json")
        self.assertEqual(opened, ["authorization.json", "request.json"])

    def test_candidates_intake_reads_real_stdin_without_confirming_unknowns(self):
        (self.root / "package.json").write_text(
            '{"name":"package-not-legal-name","version":"1.0"}', encoding="utf-8"
        )
        now = datetime.now(timezone.utc)
        answers = ["confidential", "synthetic-path-assessment"]
        for key in ("host_model", "index", "telemetry", "tools", "logs", "subprocess"):
            answers.extend(["local", "synthetic-measurement-" + key])
        answers.extend([
            "yes", "yes", "synthetic-authority",
            (now - timedelta(hours=1)).isoformat(),
            (now + timedelta(hours=1)).isoformat(),
            "counter.py", "package.json", "", "合成入口软件", "1.0", "CLI",
            "own", "synthetic-origin", "allow", "unknown", "synthetic-license",
            "unknown", "", "yes", "",
        ])
        process = self.process([
            "software-intake", "--root", str(self.root), "--output", "intake",
            "--candidates",
        ], stdin="\n".join(answers) + "\n")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(process.stdout.count("一次选择"), 1)
        summary = json.loads(process.stdout[process.stdout.rfind('{"status"'):])
        authorization = self.read_json(summary["authorization"])
        self.assertEqual(core.sha256_bytes(
            (self.root / summary["authorization"]).read_bytes()),
            summary["authorization_sha256"])
        request = self.read_json(authorization["request"]["path"])
        self.assertNotIn("confirmations", request)
        self.assertNotIn("manual_input", request)
        for field in ("completed_date", "published_date", "runtime_environment"):
            self.assertIsNone(request["scope_input"]["metadata"][field])
        self.assertEqual(request["rights"][0]["permissions"]["deposit"], "unknown")
        self.assertFalse((self.root / authorization["output"]).exists())

    def batch_projects(self):
        projects, cases = [], []
        for index in range(3):
            case = prepare_tests.SoftwarePrepareCliTests()
            case.setUp()
            self.addCleanup(case.doCleanups)
            action = "build" if index == 2 else "prepare"
            if action == "build":
                case.authorization["output"] = "materials"
                case.request["delivery"] = {"selection": "all", "screenshots": [],
                                            "sensitive_literals": []}
                case.save_request()
            args = case.args()
            projects.append({"id": f"project-{index}", "root": str(case.root),
                             "authorization": "authorization.json",
                             "authorization_sha256": args[-1], "action": action})
            cases.append(case)
        return projects, cases

    def batch_command(self, projects):
        raw = core.canonical_bytes({"projects": projects})
        (self.root / "batch.json").write_bytes(raw)
        return ["software-batch", "--root", str(self.root), "--input", "batch.json",
                "--input-sha256", core.sha256_bytes(raw), "--output", "report.json"]

    def test_batch_failed_project_does_not_block_or_pollute_other_projects(self):
        projects, cases = self.batch_projects()
        projects[1]["authorization_sha256"] = "0" * 64
        process = self.process(self.batch_command(projects))
        self.assertEqual((process.returncode, process.stderr), (4, ""))
        report = self.read_json("report.json")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["counts"]["failed"], 1)
        self.assertEqual([row["execution"] for row in report["projects"]],
                         ["completed", "failed", "completed"])
        self.assertTrue((cases[0].root / "prepared.json").is_file())
        self.assertFalse((cases[1].root / "prepared.json").exists())
        self.assertTrue((cases[2].root / "materials/body/manual.docx").is_file())
        for case in cases:
            self.assertEqual((case.root / "counter.py").read_bytes(), case.source)
        self.assertNotIn(self.source.decode("utf-8"), json.dumps(report))
        self.assertEqual(report["external_action"], "not_performed")

    def test_batch_control_hash_and_reused_roots_reject_before_project_reads(self):
        projects, cases = self.batch_projects()
        args = self.batch_command(projects)
        args[args.index("--input-sha256") + 1] = "0" * 64
        self.rejected(args, output="report.json")
        projects[1]["root"] = projects[0]["root"]
        args = self.batch_command(projects)
        original = Path.open
        opened = []

        def tracked(path, *values, **kwargs):
            opened.append(path.resolve())
            return original(path, *values, **kwargs)

        with patch.object(Path, "open", tracked):
            self.rejected(args, output="report.json")
        self.assertEqual(opened, [(self.root / "batch.json").resolve()])
        self.assertFalse(any((case.root / "prepared.json").exists() for case in cases))

    def test_export_process_copies_only_approved_bytes_without_sending(self):
        snapshot = self.export_request(("body/source.docx", "body/source.txt"))
        process = self.process(self.command("export-software"))
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (0, "software_export_written_not_sent\n", ""))
        exported = {
            path.relative_to(self.root / "recipient-copy").as_posix(): path.read_bytes()
            for path in (self.root / "recipient-copy").rglob("*") if path.is_file()
        }
        self.assertEqual(set(exported), {"body/source.docx", "body/source.txt"})
        for approval in self.request["export_approval"]["files"]:
            self.assertEqual(core.sha256_bytes(exported[approval["path"]]),
                             approval["sha256"])
            self.assertEqual(exported[approval["path"]], snapshot[approval["path"]])
        self.assert_old_package(snapshot)

    def test_export_rejects_internal_members_even_with_matching_approval_hash(self):
        self.export_request()
        for name in ("body/worksheet.txt", "internal/preparation.json", "manifest.json"):
            with self.subTest(name=name):
                self.request["export_approval"]["files"] = [{
                    "path": name, "sha256": core.sha256_bytes(
                        (self.root / "materials" / name).read_bytes()),
                }]
                self.save_request()
                self.rejected(self.command("export-software"), output="recipient-copy")

    def test_export_rejects_stale_hash_and_wrong_recipient_copy_permission(self):
        snapshot = self.export_request()
        approval = self.request["export_approval"]
        valid_hash = approval["files"][0]["sha256"]
        approval["files"][0]["sha256"] = "0" * 64
        self.save_request()
        self.rejected(self.command("export-software"), output="recipient-copy")
        approval["files"][0]["sha256"] = valid_hash
        self.authorization["context"]["permissions"][-1]["recipient"] = "another-reviewer"
        self.save_request()
        self.rejected(self.command("export-software"), output="recipient-copy")
        self.assert_old_package(snapshot)

    def test_markdown_import_builds_new_package_and_invalidates_claimed_confirmation(self):
        self.build_request()
        snapshot = self.build_old_package()
        raw = ("# 修订说明稿\n\n"
               "<!-- block:Flow evidence:EV1 status:confirmed operation:count -->\n"
               "修改后的操作正文。\n").encode("utf-8")
        self.revision_request(raw, "markdown")
        process = self.process(self.command("import-software-manual", "--build"))
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (4, "software_documents_partial\n", ""))
        self.assertIn("修改后的操作正文。", (
            self.root / "revised-materials/body/manual.txt").read_text("utf-8"))
        revised = self.read_json("revised-materials/internal/preparation.json")
        manual = revised["manual"]
        self.assertTrue(all(block["status"] == "needs_review" for block in manual["blocks"]))
        self.assertEqual(manual["revision"]["input"]["sha256"], core.sha256_bytes(raw))
        self.assertEqual(manual["revision"]["confirmations"],
                         "invalidated_reconfirmation_required")
        self.assertEqual(manual["revision"]["previous_manual_binding"],
                         self.request["previous_preparation"]["manual"]["binding"])
        self.assertEqual((self.root / "revised.md").read_bytes(), raw)
        self.assert_old_package(snapshot)

    def test_docx_import_builds_new_package_without_overwriting_old_package(self):
        self.build_request()
        snapshot = self.build_old_package()
        raw = self.docx("Word 修改正文。\n保留第二行。")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        document = ET.fromstring(parts["word/document.xml"])
        body = document.find(f"{{{namespace}}}body")
        # Word 的普通空段落必须贯通解析、prepare 与重新成件。
        body.insert(1, ET.Element(f"{{{namespace}}}p"))
        parts["word/document.xml"] = ET.tostring(
            document, encoding="utf-8", xml_declaration=True
        )
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content)
        raw = stream.getvalue()
        self.revision_request(raw, "docx")
        process = self.process(self.command("import-software-manual", "--build"))
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (4, "software_documents_partial\n", ""))
        manual = self.read_json("revised-materials/internal/preparation.json")["manual"]
        self.assertTrue(any(block["text"] == "Word 修改正文。\n保留第二行。"
                            for block in manual["blocks"]))
        self.assertEqual(manual["revision"]["input"]["format"], "docx")
        self.assertEqual((self.root / "revised.docx").read_bytes(), raw)
        self.assert_old_package(snapshot)

    def test_import_sensitive_literals_rejects_markdown_and_docx_before_output(self):
        self.build_request()
        snapshot = self.build_old_package()
        for format_name in ("markdown", "docx"):
            with self.subTest(format_name=format_name):
                self.authorization["files"] = self.authorization["files"][:1]
                raw = (b"# Revised\n\nSYNTHETIC_PRIVATE_SENTINEL\n"
                       if format_name == "markdown"
                       else self.docx("SYNTHETIC_PRIVATE_SENTINEL"))
                self.revision_request(raw, format_name)
                self.request["delivery"]["sensitive_literals"] = [
                    "SYNTHETIC_PRIVATE_SENTINEL"
                ]
                self.save_request()
                self.rejected(self.command("import-software-manual", "--build"),
                              output="revised-materials")
        self.assert_old_package(snapshot)

    def test_import_changed_revision_hash_rejects_without_touching_old_package(self):
        self.build_request()
        snapshot = self.build_old_package()
        self.revision_request(b"# Revised\n\nApproved text.\n", "markdown")
        (self.root / "revised.md").write_bytes(b"# Changed after approval\n")
        self.rejected(self.command("import-software-manual", "--build"),
                      output="revised-materials")
        self.assert_old_package(snapshot)

    def test_markdown_png_import_requires_explicit_mapping_before_image_read(self):
        self.build_request()
        snapshot = self.build_old_package()
        (self.root / "screen.png").write_bytes(png())
        self.revision_request(b"# Revised\n\n![operation](screen.png)\n", "markdown")
        args = self.command("import-software-manual", "--build")
        original = Path.open

        def guarded(path, *values, **kwargs):
            self.assertNotEqual(path.name, "screen.png")
            return original(path, *values, **kwargs)

        with patch.object(Path, "open", guarded):
            self.rejected(args, output="revised-materials")
        self.assert_old_package(snapshot)

    def test_docx_png_import_uses_authorized_original_bytes_and_operation_mapping(self):
        self.build_request()
        image = png()
        expected = core.sha256_bytes(image)
        (self.root / "screen.png").write_bytes(image)
        self.request["manual_input"].update(mode="GUI", runtime_evidence=[{
            "id": "shot1", "version": "1.0", "evidence_id": "synthetic-capture",
            "kind": "screenshot",
        }])
        self.authorization["context"]["now"] = datetime.now(timezone.utc).isoformat()
        prepared = software.prepare({
            **{key: value for key, value in self.request.items() if key != "delivery"},
            "context": self.authorization["context"], "authorized_root": str(self.root),
        }, use_system_time=True)["artifacts"]
        self.request["delivery"]["screenshots"] = [{
            "id": "shot1", "path": "screen.png", "sha256": expected,
            "version": "1.0", "operation_id": "count",
            "build_binding": software_delivery.build_binding(prepared),
            "capture_evidence": "synthetic-not-real-screenshot",
            "local_use_evidence": "synthetic-use", "visible_state": "Synthetic image",
        }]
        self.authorization["files"].append({"path": "screen.png", "sha256": expected})
        self.save_request()
        snapshot = self.build_old_package()
        raw = self.docx("图文修改正文。", image=image)
        self.revision_request(raw, "docx")
        process = self.process(self.command("import-software-manual", "--build"))
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (4, "software_documents_partial\n", ""))
        manual = self.read_json("revised-materials/internal/preparation.json")["manual"]
        block = next(block for block in manual["blocks"] if block["kind"] == "image")
        self.assertEqual((block["image_id"], block["operation_id"], block["sha256"]),
                         ("shot1", "count", expected))
        with zipfile.ZipFile(self.root / "revised-materials/body/manual.docx") as archive:
            images = [archive.read(name) for name in archive.namelist()
                      if name.startswith("word/media/")]
        self.assertEqual(images, [image])
        self.assertEqual((self.root / "screen.png").read_bytes(), image)
        self.assert_old_package(snapshot)


if __name__ == "__main__":
    unittest.main()
