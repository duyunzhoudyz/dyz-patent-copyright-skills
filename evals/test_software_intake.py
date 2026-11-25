"""控制台逐项收集的合成回归；不读取用户资料、不连接外部服务。"""

import contextlib
import io
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools import core, software, software_delivery, software_intake

ROOT = Path(__file__).resolve().parents[1]


def png():
    """已有PNG合成原件；测试不截屏或冒充真实软件运行。"""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" + b"\xff\x00\x00" * 2
                                          + b"\x00" + b"\x00\xff\x00" * 2))
            + chunk(b"IEND", b""))


class Answers:
    def __init__(self, values):
        self.values = list(values)
        self.prompts = []
        self.position = 0

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.position >= len(self.values):
            raise EOFError
        value = self.values[self.position]
        self.position += 1
        if isinstance(value, BaseException):
            raise value
        return value

    @property
    def finished(self):
        return self.position == len(self.values)


class SoftwareIntakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dyz-intake-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = b"def count(items):\n    return len(items)\n"
        (self.root / "counter.py").write_bytes(self.source)
        self.now = datetime.now(timezone.utc)

    def context_answers(self, sensitivity="synthetic"):
        answers = [sensitivity, "synthetic-six-path-assessment"]
        for path_id in software_intake.DATA_PATHS:
            answers.extend(["local", "synthetic-measured-" + path_id])
        answers.extend([
            "yes", "yes", "synthetic-local-authority",
            (self.now - timedelta(hours=1)).isoformat(),
            (self.now + timedelta(hours=1)).isoformat(),
        ])
        return answers

    def answers(self, *, sensitivity="synthetic", owner="合成权利人",
                origin="own", local_process="allow", deposit="allow",
                evidence="synthetic-rights", manual=True, mode="CLI",
                files=None, excluded=None, inventory="yes", claim="独立编写的计数表达",
                screenshots=None, selection="all", sensitive_literals=None):
        answers = self.context_answers(sensitivity)
        answers.extend([*(excluded or []), "", *(files or ["counter.py"]), "", inventory])
        answers.extend([
            "合成计数器", "1.0", mode, "yes", "", "", "",
            origin, "synthetic-origin", claim, "运行时与外部依赖", owner,
        ])
        if owner:
            answers.extend(["合成权属依据", "synthetic-owner-evidence"])
        if origin == "existing":
            answers.append("synthetic-baseline")
        if origin == "third_party":
            answers.extend(["synthetic-license", "synthetic-notice"])
        if origin == "ai":
            answers.extend(["人工改写计数逻辑", "synthetic-human-contribution"])
        answers.extend([local_process, deposit, evidence])
        if origin in {"existing", "third_party"}:
            answers.extend("synthetic-deposit-context" for _ in (files or ["counter.py"]))
        if manual:
            answers.extend([
                "函数接收列表并返回计数", "synthetic-fact-evidence", "",
                "count([1, 2])", "2", "参数无长度时报告类型错误",
                "synthetic-operation-evidence", "",
            ])
        else:
            answers.append("")
        if manual and mode == "GUI":
            for image in screenshots or []:
                answers.extend(self.image_answers(**image))
            answers.append("")
        answers.extend([selection, *(sensitive_literals or []), "", "yes"])
        return Answers(answers)

    def image_answers(self, path="screen.png", operation_id="operation-1", version="1.0",
                      capture="allow", local_use="allow", capture_evidence="synthetic-capture",
                      local_use_evidence="synthetic-image-use", visible_state="合成双色图，不是实测"):
        return [path, operation_id, version, capture, local_use,
                capture_evidence, local_use_evidence, visible_state]

    def invoke_cli(self, arguments, values=None):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools", *arguments], cwd=ROOT,
            input=None if values is None else "\n".join(values) + "\n",
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    def collect(self, answers=None, output="intake"):
        return software_intake.collect(self.root, output, ask=answers or self.answers())

    def load(self, relative):
        return core.strict_json_loads((self.root / relative).read_text(encoding="utf-8"))

    def request_path(self, summary):
        return self.load(summary["authorization"])["request"]["path"]

    def prepare(self, summary):
        authorization = self.load(summary["authorization"])
        request = self.load(authorization["request"]["path"])
        request.pop("delivery")
        return software.prepare({**request, "authorized_root": str(self.root),
                                 "context": authorization["context"]}, use_system_time=True)

    def assert_no_reads_or_output(self, answers, code=None, output="intake"):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with patch.object(Path, "open", side_effect=AssertionError("unexpected file read")):
                with self.assertRaises(core.ContractError) as caught:
                    self.collect(answers, output)
        if code is not None:
            self.assertEqual(str(caught.exception), code)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertFalse((self.root / output).exists())

    def test_success_binds_each_file_and_both_json_bytes(self):
        (self.root / "other.py").write_bytes(b"value = 1\n")
        answers = self.answers(files=["counter.py", "other.py"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            summary = self.collect(answers)
        self.assertTrue(answers.finished)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(set(summary), {"status", "authorization", "authorization_sha256"})
        self.assertEqual(summary["status"], "collected")
        self.assertEqual(summary["authorization"], "intake/authorization.json")
        content = (self.root / summary["authorization"]).read_bytes()
        self.assertEqual(core.sha256_bytes(content), summary["authorization_sha256"])
        authorization = self.load(summary["authorization"])
        request = self.load(authorization["request"]["path"])
        self.assertEqual(authorization["kind"], "software_local_authorization")
        self.assertEqual(authorization["authorized_root"], str(self.root.resolve()))
        self.assertEqual(authorization["request"]["path"], "intake/request.json")
        content = (self.root / authorization["request"]["path"]).read_bytes()
        self.assertEqual(authorization["request"]["sha256"], core.sha256_bytes(content))
        self.assertEqual(authorization["output"], "intake/materials")
        self.assertFalse((self.root / authorization["output"]).exists())
        self.assertEqual(len(authorization["files"]), 2)
        for file, binding in zip(request["files"], authorization["files"], strict=True):
            self.assertEqual(file["path"], binding["path"])
            expected = core.sha256_bytes((self.root / binding["path"]).read_bytes())
            self.assertEqual(file["expected_sha256"], expected)
            self.assertEqual(binding["sha256"], expected)
        self.assertEqual(request["pagination"], {
            "selection": "all", "lines_per_page": 50, "wrap_columns": 78,
            "basis": "internal_candidate_not_verified_registration_rule",
        })
        self.assertEqual(request["delivery"], {
            "selection": "all", "screenshots": [], "sensitive_literals": [],
        })
        self.assertNotIn("confirmations", request)
        self.assertEqual(self.prepare(summary)["artifacts"]["source"]["selected_source_lines"], 3)
        self.assertEqual((self.root / "counter.py").read_bytes(), self.source)

    def test_preflight_and_all_questions_precede_source_reads(self):
        answers = self.answers(sensitivity="confidential")
        original = Path.open
        opened = []
        def tracked(path, *args, **kwargs):
            self.assertTrue(answers.finished)
            self.assertGreater(preflight.call_count, 0)
            opened.append(path.name)
            return original(path, *args, **kwargs)
        with patch.object(core, "preflight", wraps=core.preflight) as preflight:
            with patch.object(Path, "open", tracked):
                self.collect(answers)
        self.assertEqual(opened, ["counter.py", "request.json", "authorization.json"])
        self.assertGreaterEqual(preflight.call_count, 4)

    def test_unknown_owner_dates_and_deposit_remain_unknown_and_partial(self):
        summary = self.collect(self.answers(owner="", deposit="unknown", inventory="unknown"))
        request = self.load(self.request_path(summary))
        component = request["scope_input"]["components"][0]
        self.assertEqual(component["subjects"], [])
        self.assertIsNone(component["original_right_holder"])
        for key in ("completed_date", "published_date", "runtime_environment"):
            self.assertIsNone(request["scope_input"]["metadata"][key])
        self.assertFalse(request["inventory_complete"])
        self.assertEqual(request["rights"][0]["evidence_ids"], ["synthetic-rights"])
        self.assertEqual(request["rights"][0]["permissions"]["local_process"], "allow")
        self.assertEqual(request["rights"][0]["permissions"]["deposit"], "unknown")
        result = self.prepare(summary)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["artifacts"]["source"]["selected_source_lines"], 0)
        self.assertIn("ownership_unknown", {issue["code"] for issue in result["issues"]})

    def test_gui_does_not_invent_screenshots_or_runtime(self):
        summary = self.collect(self.answers(mode="GUI"))
        request = self.load(self.request_path(summary))
        self.assertEqual(request["manual_input"]["runtime_evidence"], [])
        result = self.prepare(summary)
        self.assertEqual(result["artifacts"]["manual"]["screenshots"], [])
        self.assertIn("runtime_not_verified", {issue["code"] for issue in result["issues"]})

    def test_existing_png_binds_operation_runtime_build_and_authorized_union(self):
        original_png = png()
        (self.root / "screen.png").write_bytes(original_png)
        answers = self.answers(mode="GUI", screenshots=[{}], selection="head_tail",
                               sensitive_literals=["  synthetic-sensitive-exact  "])
        original_open = Path.open
        opened = []
        def tracked(path, *args, **kwargs):
            self.assertTrue(answers.finished)
            opened.append(path.name)
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", tracked):
            with patch.object(software, "prepare", wraps=software.prepare) as prepare:
                with patch.object(subprocess, "run", side_effect=AssertionError("must not run")):
                    summary = self.collect(answers)
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(opened, ["counter.py", "screen.png", "counter.py",
                                  "request.json", "authorization.json"])
        self.assertIn("counter.py", answers.prompts[-1])
        self.assertIn("screen.png -> operation-1", answers.prompts[-1])
        self.assertNotIn("synthetic-sensitive-exact", "".join(answers.prompts))
        authorization = self.load(summary["authorization"])
        request = self.load(authorization["request"]["path"])
        self.assertEqual([row["path"] for row in request["files"]], ["counter.py"])
        self.assertEqual(authorization["files"], [
            {"path": "counter.py", "sha256": core.sha256_bytes(self.source)},
            {"path": "screen.png", "sha256": core.sha256_bytes(original_png)},
        ])
        self.assertEqual(request["pagination"]["selection"], "all")
        self.assertEqual(request["delivery"]["selection"], "head_tail")
        self.assertEqual(request["delivery"]["sensitive_literals"], ["  synthetic-sensitive-exact  "])
        self.assertEqual(request["manual_input"]["runtime_evidence"], [{
            "id": "shot1", "version": "1.0", "kind": "screenshot",
            "evidence_id": "synthetic-capture",
        }])
        prepared = self.prepare(summary)["artifacts"]
        self.assertEqual(request["delivery"]["screenshots"], [{
            "id": "shot1", "path": "screen.png", "sha256": core.sha256_bytes(original_png),
            "version": "1.0", "operation_id": "operation-1",
            "capture_evidence": "synthetic-capture", "local_use_evidence": "synthetic-image-use",
            "visible_state": "合成双色图，不是实测",
            "build_binding": software_delivery.build_binding(prepared),
        }])
        self.assertEqual(prepared["manual"]["verification"], "evidence_referenced_not_executed")
        self.assertNotIn("confirmations", request)
        self.assertEqual((self.root / "counter.py").read_bytes(), self.source)
        self.assertEqual((self.root / "screen.png").read_bytes(), original_png)

    def test_batch_excluded_screenshot_never_becomes_runtime_evidence(self):
        seed = self.collect(self.answers(mode="GUI"), output="batch-seed")
        seed_auth = self.load(seed["authorization"])
        seed_request = self.load(seed_auth["request"]["path"])
        kept_path, excluded_path = "screen.png", "excluded.png"
        for name in (kept_path, excluded_path):
            (self.root / name).write_bytes(png())
        shot = {"id": "shot1", "path": kept_path, "version": "1.0", "operation_id": "operation-1",
                "capture_evidence": "EV-CAP", "local_use_evidence": "EV-USE", "visible_state": "Synthetic image"}
        far = {
            "scope": seed_request["scope_input"], "rights": seed_request["rights"],
            "files": seed_request["files"], "manual_input": seed_request["manual_input"],
            "material_permissions": [{"paths": ["counter.py", kept_path], "decision": "allow", "evidence_id": "EV"}],
            "excluded_sources": [{"path": excluded_path}],
        }
        original_open = Path.open

        def forbid_excluded_open(path, *args, **kwargs):
            self.assertNotEqual(path.name, excluded_path, "excluded screenshot opened")
            return original_open(path, *args, **kwargs)

        excluded = dict(shot, id="shot2", path=excluded_path, capture_evidence="EV-EXCLUDED")
        for idx, other in enumerate((excluded, dict(excluded, version="2.0"), {"path": excluded_path})):
            with self.subTest(excluded=other):
                batch = {
                    "context_and_permissions": seed_auth["context"],
                    "files_and_rights": {**far, "delivery": {"screenshots": [shot, other]}},
                }
                with patch.object(Path, "open", forbid_excluded_open):
                    result = software_intake.collect_batch(self.root, f"batch-{idx}", batch_input=batch)
                authorization = self.load(result["authorization"])
                request = self.load(authorization["request"]["path"])
                self.assertEqual([(excluded_path, "not_read")],
                                 [(row["path"], row["read_status"]) for row in result["excluded_sources"]])
                self.assertEqual(["counter.py", kept_path], [row["path"] for row in authorization["files"]])
                self.assertEqual([kept_path], [row["path"] for row in request["delivery"]["screenshots"]])
                self.assertEqual([{"id": "shot1", "version": "1.0", "kind": "screenshot", "evidence_id": "EV-CAP"}],
                                 request["manual_input"]["runtime_evidence"])

    def test_screenshot_denied_unknown_or_missing_evidence_prevents_all_reads(self):
        (self.root / "screen.png").write_bytes(png())
        cases = [{action: decision} for action in ("capture", "local_use")
                 for decision in ("deny", "unknown")]
        cases += [{field: ""} for field in
                  ("capture_evidence", "local_use_evidence", "visible_state")]
        cases += [{"version": "2.0"}, {"operation_id": "absent"}]
        for image in cases:
            with self.subTest(image=image):
                self.assert_no_reads_or_output(self.answers(mode="GUI", screenshots=[image]))
        for decision in ("deny", "unknown"):
            self.assert_no_reads_or_output(
                self.answers(mode="GUI", screenshots=[{}], local_process=decision),
                "material_permission_not_proven",
            )
        self.assert_no_reads_or_output(
            self.answers(mode="GUI", screenshots=[{}], evidence=""),
            "material_permission_not_proven",
        )

    def test_screenshot_paths_and_duplicates_reject_before_any_material_read(self):
        (self.root / "screen.png").write_bytes(png())
        cases = [[{"path": path}] for path in
                 ("../screen.png", str(self.root / "screen.png"), "absent.png", "counter.py")]
        cases += [[{}, {}]]
        for images in cases:
            with self.subTest(images=images):
                self.assert_no_reads_or_output(self.answers(mode="GUI", screenshots=images))
        directory = self.root / "previous"
        directory.mkdir()
        (directory / "screen.png").write_bytes(png())
        self.assert_no_reads_or_output(
            self.answers(mode="GUI", excluded=["previous"],
                         screenshots=[{"path": "previous/screen.png"}]),
            "artifact_screenshot_forbidden",
        )

    def test_screenshot_hardlinks_reject_duplicates_across_images_and_source(self):
        (self.root / "screen.png").write_bytes(png())
        try:
            os.link(self.root / "screen.png", self.root / "alias.png")
            os.link(self.root / "counter.py", self.root / "source-alias.png")
        except OSError:
            self.skipTest("hardlinks unavailable")
        for images in ([{}, {"path": "alias.png"}], [{"path": "source-alias.png"}]):
            self.assert_no_reads_or_output(
                self.answers(mode="GUI", screenshots=images), "screenshot_duplicate_path",
            )

    def test_late_screenshot_path_change_rejects_before_source_read(self):
        image = self.root / "screen.png"
        image.write_bytes(png())
        answers = self.answers(mode="GUI", screenshots=[{}])
        def ask(prompt):
            answer = answers(prompt)
            if answers.finished:
                image.unlink()
            return answer
        self.assert_no_reads_or_output(ask)

    def test_screenshot_refusal_and_new_question_eof_leave_no_material_read_or_output(self):
        (self.root / "screen.png").write_bytes(png())
        refusal = self.answers(mode="GUI", screenshots=[{}])
        refusal.values[-1] = "no"
        self.assert_no_reads_or_output(refusal, "intake_consent_required")
        values = self.answers(mode="GUI", screenshots=[{}], sensitive_literals=["synthetic-secret"])
        for position in range(values.values.index("screen.png"), len(values.values)):
            with self.subTest(position=position):
                self.assert_no_reads_or_output(Answers(values.values[:position]), "intake_cancelled")
        self.assert_no_reads_or_output(self.answers(selection="invalid"), "intake_choice_invalid")

    def test_invalid_png_bytes_and_source_changed_during_binding_leave_no_output(self):
        for raw in (b"not-a-png", png()[:-1], png()[:29] + b"bad!" + png()[33:]):
            with self.subTest(raw=raw[:12]):
                (self.root / "screen.png").write_bytes(raw)
                with self.assertRaises(core.ContractError):
                    self.collect(self.answers(mode="GUI", screenshots=[{}]))
                self.assertFalse((self.root / "intake").exists())
        (self.root / "screen.png").write_bytes(png())
        original_prepare = software.prepare
        def changed(payload, **kwargs):
            (self.root / "counter.py").write_bytes(b"changed = True\n")
            return original_prepare(payload, **kwargs)
        with patch.object(software, "prepare", changed):
            with self.assertRaisesRegex(core.ContractError, "^source_hash_mismatch$"):
                self.collect(self.answers(mode="GUI", screenshots=[{}]))
        self.assertFalse((self.root / "intake").exists())

    def test_missing_manual_remains_partial_instead_of_inventing_facts(self):
        summary = self.collect(self.answers(manual=False))
        self.assertNotIn("manual_input", self.load(self.request_path(summary)))
        result = self.prepare(summary)
        self.assertEqual(result["status"], "partial")
        self.assertIn("manual_input_missing", {issue["code"] for issue in result["issues"]})

    def test_origins_are_preserved_without_claiming_third_party_as_original(self):
        for origin in ("existing", "third_party", "ai"):
            with self.subTest(origin=origin):
                summary = self.collect(self.answers(origin=origin, claim=""), output=origin)
                request = self.load(self.request_path(summary))
                self.assertEqual(request["scope_input"]["components"][0]["origin"], origin)
                result = self.prepare(summary)
                self.assertEqual(result["professional_review"], "not_performed")
                self.assertEqual(result["artifacts"]["source"]["original_source_lines"], 0)

    def test_unknown_origin_is_rejected_not_coerced_to_own(self):
        answers = self.answers()
        answers.values[answers.values.index("own")] = "unknown"
        self.assert_no_reads_or_output(answers, "intake_choice_invalid")

    def test_material_permission_denied_or_unknown_prevents_hash_reads(self):
        for decision in ("deny", "unknown"):
            with self.subTest(local_process=decision):
                self.assert_no_reads_or_output(
                    self.answers(local_process=decision), "material_permission_not_proven",
                )

    def test_material_permission_without_evidence_prevents_hash_reads(self):
        self.assert_no_reads_or_output(
            self.answers(evidence=""), "material_permission_not_proven",
        )

    def test_final_refusal_does_not_read_or_create(self):
        answers = self.answers()
        answers.values[-1] = "no"
        self.assert_no_reads_or_output(answers, "intake_consent_required")

    def test_missing_authority_and_expired_permissions_reject_before_read(self):
        for index, value, code in ((16, "", "intake_answer_required"),
                                   (18, "2000-01-01T00:00:00Z", "permission_not_proven")):
            with self.subTest(index=index):
                answers = self.answers()
                answers.values[index] = value
                self.assert_no_reads_or_output(answers, code)

    def test_each_sensitivity_requires_six_explicit_path_evidence_records(self):
        for sensitivity in ("synthetic", "public", "confidential", "restricted"):
            with self.subTest(sensitivity=sensitivity):
                summary = self.collect(self.answers(sensitivity=sensitivity), output=sensitivity)
                environment = self.load(summary["authorization"])["context"]["environment"]
                self.assertEqual([p["id"] for p in environment["data_paths"]],
                                 list(software_intake.DATA_PATHS))
                self.assertTrue(all(p["verified"] and p["evidence"] for p in environment["data_paths"]))

    def test_unknown_external_and_bare_local_claims_reject(self):
        for index, value, code in ((2, "unknown", "intake_choice_invalid"),
                                   (2, "external", "intake_choice_invalid"),
                                   (3, "本地", "data_path_evidence_required")):
            with self.subTest(value=value):
                answers = self.answers()
                answers.values[index] = value
                self.assert_no_reads_or_output(answers, code)

    def test_existing_output_is_never_overwritten_or_read(self):
        output = self.root / "intake"
        output.mkdir()
        (output / "request.json").write_bytes(b"retained-secret-sentinel")
        with patch.object(Path, "open", side_effect=AssertionError("unexpected file read")):
            with self.assertRaisesRegex(core.ContractError, "^output_exists$"):
                self.collect()
        self.assertEqual((output / "request.json").read_bytes(), b"retained-secret-sentinel")

    def test_paths_outside_root_duplicates_and_missing_files_reject_before_read(self):
        for files in (["../counter.py"], ["counter.py", "counter.py"], ["absent.py"],
                      [str(self.root / "counter.py")]):
            with self.subTest(files=files):
                self.assert_no_reads_or_output(self.answers(files=files))

    def test_hardlink_duplicates_reject_before_read(self):
        try:
            os.link(self.root / "counter.py", self.root / "alias.py")
        except OSError:
            self.skipTest("hardlinks unavailable")
        self.assert_no_reads_or_output(self.answers(files=["counter.py", "alias.py"]),
                                      "duplicate_source_path")

    def test_generated_and_declared_artifact_directories_reject_before_read(self):
        for name in ("output", "outputs", "artifacts", "build", "dist", "old-materials"):
            with self.subTest(name=name):
                directory = self.root / name
                directory.mkdir()
                (directory / "copy.py").write_bytes(self.source)
                excluded = [name] if name == "old-materials" else []
                self.assert_no_reads_or_output(
                    self.answers(files=[name + "/copy.py"], excluded=excluded),
                    "generated_source_forbidden",
                )

    def test_old_intake_marker_directory_rejects_without_reading_marker(self):
        directory = self.root / "previous"
        directory.mkdir()
        (directory / "authorization.json").write_bytes(b"private-marker")
        (directory / "copy.py").write_bytes(self.source)
        self.assert_no_reads_or_output(self.answers(files=["previous/copy.py"]),
                                      "generated_source_forbidden")

    def test_end_of_input_and_interrupt_do_not_echo_or_read(self):
        for error in (EOFError("private-input"), KeyboardInterrupt("private-input")):
            for position in (0, 15, -1):
                with self.subTest(error=type(error).__name__, position=position):
                    answers = self.answers()
                    answers.values[position] = error
                    self.assert_no_reads_or_output(answers, "intake_cancelled")

    def test_interruption_during_hashing_does_not_create_or_print_source(self):
        original = Path.open
        out, err = io.StringIO(), io.StringIO()
        def interrupted(path, *args, **kwargs):
            if path.name == "counter.py":
                raise KeyboardInterrupt("private-source-sentinel")
            return original(path, *args, **kwargs)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with patch.object(Path, "open", interrupted):
                with self.assertRaisesRegex(core.ContractError, "^intake_cancelled$"):
                    self.collect()
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertFalse((self.root / "intake").exists())

    def test_permission_expiration_during_questions_is_rechecked(self):
        answers = self.answers()
        original = answers.__call__
        def ask(prompt):
            answer = original(prompt)
            if answers.finished:
                clock.now.return_value = self.now + timedelta(hours=2)
            return answer
        with patch.object(software_intake, "datetime") as clock:
            clock.now.return_value = self.now
            with patch.object(Path, "open", side_effect=AssertionError("unexpected file read")):
                with self.assertRaisesRegex(core.ContractError, "^permission_not_proven$"):
                    software_intake.collect(self.root, "intake", ask=ask)
        self.assertFalse((self.root / "intake").exists())

    def test_real_stdin_cli_intake_build_verify_retains_partial(self):
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        intake = subprocess.run(
            [sys.executable, "-B", "-m", "tools", "software-intake",
             "--root", str(self.root), "--output", "cli-intake"],
            cwd=ROOT, input="\n".join(self.answers(mode="GUI").values) + "\n",
            capture_output=True, text=True, encoding="utf-8", env=environment,
        )
        self.assertEqual(intake.returncode, 0, intake.stderr)
        self.assertEqual(intake.stderr, "")
        start = intake.stdout.rfind('{"status":')
        self.assertGreaterEqual(start, 0)
        summary = core.strict_json_loads(intake.stdout[start:])
        self.assertEqual(set(summary), {"status", "authorization", "authorization_sha256"})
        self.assertEqual(summary["status"], "collected")
        self.assertNotIn("synthetic-local-authority", intake.stdout)
        self.assertNotIn("def count(items)", intake.stdout)
        self.assertNotIn("合成权利人", intake.stdout)
        authorization = self.load(summary["authorization"])
        self.assertEqual(summary["authorization_sha256"], core.sha256_bytes(
            (self.root / summary["authorization"]).read_bytes()))
        request = self.load(authorization["request"]["path"])
        self.assertEqual(request["manual_input"]["mode"], "GUI")
        self.assertEqual(request["manual_input"]["runtime_evidence"], [])
        self.assertEqual(request["delivery"]["screenshots"], [])
        command = [
            sys.executable, "-B", "-m", "tools", "build-software",
            "--root", str(self.root), "--authorization", summary["authorization"],
            "--authorization-sha256", summary["authorization_sha256"],
        ]
        for arguments in (command, command + ["--verify"]):
            process = subprocess.run(arguments, cwd=ROOT, capture_output=True,
                                     text=True, encoding="utf-8", env=environment)
            self.assertEqual((process.returncode, process.stdout, process.stderr),
                             (4, "software_documents_partial\n", ""))
        materials = self.root / authorization["output"]
        self.assertTrue((materials / "body/source.docx").is_file())
        self.assertTrue((materials / "body/manual.docx").is_file())
        manifest = self.load(authorization["output"] + "/manifest.json")
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(manifest["pdf"], "not_generated")
        self.assertEqual(manifest["pdf_documents"], [])
        self.assertTrue({"pdf_not_generated", "physical_layout_not_checked",
                         "runtime_not_verified"}.issubset(manifest["issues"]))
        self.assertEqual(manifest["visual_review"], "not_performed")
        self.assertEqual(manifest["professional_review"], "not_performed")
        self.assertEqual(manifest["external_action"], "not_performed")
        preparation = self.load(authorization["output"] + "/internal/preparation.json")
        self.assertEqual(preparation["manual"]["screenshots"], [])
        self.assertEqual(preparation["manual"]["runtime_evidence"], [])
        self.assertEqual((self.root / "counter.py").read_bytes(), self.source)

    def test_real_stdin_png_intake_build_verify_embeds_original_and_preserves_limits(self):
        original_png = png()
        (self.root / "screen.png").write_bytes(original_png)
        sentinel = "SYNTHETIC_PRIVATE_LITERAL_NOT_FOR_STDOUT"
        answers = self.answers(mode="GUI", screenshots=[{}], selection="head_tail",
                               sensitive_literals=[sentinel])
        intake = self.invoke_cli(
            ["software-intake", "--root", str(self.root), "--output", "png-intake"], answers.values,
        )
        self.assertEqual((intake.returncode, intake.stderr), (0, ""))
        self.assertNotIn(sentinel, intake.stdout)
        self.assertNotIn("synthetic-capture", intake.stdout)
        self.assertNotIn("synthetic-image-use", intake.stdout)
        self.assertNotIn("合成双色图，不是实测", intake.stdout)
        self.assertIn("counter.py", intake.stdout)
        self.assertIn("screen.png -> operation-1", intake.stdout)
        start = intake.stdout.rfind('{"status":')
        self.assertGreaterEqual(start, 0)
        summary = core.strict_json_loads(intake.stdout[start:])
        authorization = self.load(summary["authorization"])
        self.assertEqual(summary["authorization_sha256"], core.sha256_bytes(
            (self.root / summary["authorization"]).read_bytes()))
        self.assertEqual(authorization["request"]["sha256"], core.sha256_bytes(
            (self.root / authorization["request"]["path"]).read_bytes()))
        command = ["build-software", "--root", str(self.root),
                   "--authorization", summary["authorization"],
                   "--authorization-sha256", summary["authorization_sha256"]]
        for args in (command, command + ["--verify"]):
            process = self.invoke_cli(args)
            self.assertEqual((process.returncode, process.stdout, process.stderr),
                             (4, "software_documents_partial\n", ""))
        output = authorization["output"]
        manifest = self.load(output + "/manifest.json")
        self.assertEqual(manifest["selection_requested"], "head_tail")
        self.assertEqual(manifest["selection_applied"], "all_pending_physical_validation")
        self.assertEqual(manifest["pdf"], "not_generated")
        self.assertEqual(manifest["pdf_documents"], [])
        self.assertTrue({"pdf_not_generated", "physical_layout_not_checked",
                         "physical_selection_not_verified", "screenshot_visual_review_missing"}
                        .issubset(manifest["issues"]))
        self.assertNotIn("runtime_not_verified", manifest["issues"])
        for field in ("visual_review", "professional_review", "external_action"):
            self.assertEqual(manifest[field], "not_performed")
        preparation = self.load(output + "/internal/preparation.json")
        mapping = self.load(output + "/internal/source-map.json")
        self.assertEqual(len(preparation["source"]["manifest"]), 1)
        self.assertEqual(preparation["manual"]["verification"], "evidence_referenced_not_executed")
        self.assertEqual(mapping["screenshots"][0]["operation_id"], "operation-1")
        self.assertEqual(mapping["screenshots"][0]["sha256"], core.sha256_bytes(original_png))
        self.assertEqual(mapping["screenshots"][0]["build_binding"],
                         software_delivery.build_binding(preparation))
        self.assertEqual(mapping["screenshots"][0]["authenticity"], "not_independently_verified")
        with zipfile.ZipFile(self.root / output / "body/manual.docx") as archive:
            media = [name for name in archive.namelist() if name.startswith("word/media/")]
            self.assertEqual(len(media), 1)
            self.assertEqual(archive.read(media[0]), original_png)
            document = archive.read("word/document.xml").decode("utf-8")
            self.assertLess(document.index("operation-1"), document.index("<w:drawing>"))
        self.assertEqual((self.root / "counter.py").read_bytes(), self.source)
        self.assertEqual((self.root / "screen.png").read_bytes(), original_png)

    def test_sensitive_output_path_rejects_before_material_reads(self):
        (self.root / "screen.png").write_bytes(png())
        for secret in ("png-intake", "authorization.json"):
            with self.subTest(secret=secret):
                self.assert_no_reads_or_output(
                    self.answers(mode="GUI", screenshots=[{}], sensitive_literals=[secret]),
                    "intake_sensitive_output_path", output="png-intake",
                )

    def test_real_stdin_sensitive_output_path_never_leaks_in_success_summary(self):
        (self.root / "screen.png").write_bytes(png())
        output = "private-output-sentinel"
        answers = self.answers(mode="GUI", screenshots=[{}], sensitive_literals=[output])
        intake = self.invoke_cli(
            ["software-intake", "--root", str(self.root), "--output", output], answers.values,
        )
        self.assertNotIn(output, intake.stdout + intake.stderr)
        self.assertEqual((intake.returncode, intake.stderr), (2, "contract_rejected\n"))
        self.assertNotIn('{"status":', intake.stdout)
        self.assertFalse((self.root / output).exists())
        self.assertEqual((self.root / "counter.py").read_bytes(), self.source)
        self.assertEqual((self.root / "screen.png").read_bytes(), png())

    def test_real_stdin_png_permission_refusal_and_eof_create_nothing(self):
        (self.root / "screen.png").write_bytes(png())
        denied = self.answers(mode="GUI", screenshots=[{"local_use": "deny"}]).values
        missing = self.answers(mode="GUI", screenshots=[{"capture_evidence": ""}]).values
        eof = self.answers(mode="GUI", screenshots=[{}]).values[:-1]
        for values in (denied, missing, eof):
            process = self.invoke_cli(
                ["software-intake", "--root", str(self.root), "--output", "denied-intake"], values,
            )
            self.assertEqual((process.returncode, process.stderr), (2, "contract_rejected\n"))
            self.assertNotIn('{"status":', process.stdout)
            self.assertNotIn("synthetic-capture", process.stdout)
            self.assertFalse((self.root / "denied-intake").exists())

    def test_collected_png_changed_bytes_or_sensitive_text_block_build_before_output(self):
        original_png = png()
        (self.root / "screen.png").write_bytes(original_png)
        for case in ("changed-png", "changed-source", "sensitive-source", "sensitive-caption"):
            with self.subTest(case=case):
                (self.root / "screen.png").write_bytes(original_png)
                (self.root / "counter.py").write_bytes(self.source)
                secrets = {"sensitive-source": ["def count(items)"],
                           "sensitive-caption": ["合成双色图"]}.get(case, [])
                answers = self.answers(mode="GUI", screenshots=[{}], sensitive_literals=secrets)
                intake = self.invoke_cli(
                    ["software-intake", "--root", str(self.root), "--output", case], answers.values,
                )
                self.assertEqual((intake.returncode, intake.stderr), (0, ""))
                self.assertTrue(all(secret not in intake.stdout for secret in secrets))
                summary = core.strict_json_loads(intake.stdout[intake.stdout.rfind('{"status":'):])
                authorization = self.load(summary["authorization"])
                if case == "changed-png":
                    (self.root / "screen.png").write_bytes(original_png + b"changed")
                elif case == "changed-source":
                    (self.root / "counter.py").write_bytes(b"changed = True\n")
                build = self.invoke_cli([
                    "build-software", "--root", str(self.root),
                    "--authorization", summary["authorization"],
                    "--authorization-sha256", summary["authorization_sha256"],
                ])
                self.assertEqual((build.returncode, build.stdout, build.stderr),
                                 (2, "", "contract_rejected\n"))
                self.assertFalse((self.root / authorization["output"]).exists())

    def test_real_stdin_input_collects_without_echoing_material(self):
        values = self.answers().values
        script = ("from tools.software_intake import collect; import sys; "
                  "r = collect(sys.argv[1], 'console-intake'); "
                  "print('\\nCOLLECTED:' + r['authorization_sha256'])")
        process = subprocess.run(
            [sys.executable, "-B", "-c", script, str(self.root)], cwd=ROOT,
            input="\n".join(values) + "\n", capture_output=True, text=True,
            encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertNotIn("synthetic-local-authority", process.stdout)
        self.assertNotIn("def count(items)", process.stdout)
        self.assertNotIn("合成权利人", process.stdout)
        authorization = self.root / "console-intake/authorization.json"
        self.assertIn("COLLECTED:" + core.sha256_bytes(authorization.read_bytes()), process.stdout)

    def test_collect_candidates_downgrades_inventory_complete_when_source_excluded_and_rejects_nonbool(self):
        from tools import software_discovery

        (self.root / "unreadable.py").write_bytes(b"\xff\xfe\x80")
        context = {
            "environment": {
                "assessment_evidence": "synthetic-assessment",
                "data_paths": [
                    {"id": pid, "mode": "local", "verified": True, "evidence": "synthetic-measured-" + pid}
                    for pid in software_intake.DATA_PATHS
                ],
            },
            "permissions": [
                {
                    "action": act,
                    "purpose": software_intake.PURPOSE,
                    "recipient": "local_tool",
                    "decision": "allow",
                    "authority_evidence": "synthetic-authority",
                    "valid_from": (self.now - timedelta(hours=1)).isoformat(),
                    "valid_until": (self.now + timedelta(hours=1)).isoformat(),
                }
                for act in ("local_read", "local_write")
            ],
            "sensitivity": "synthetic",
            "purpose": software_intake.PURPOSE,
            "now": self.now.isoformat(),
        }
        files = [
            {"id": "file-1", "path": "counter.py", "component_id": "main", "kind": "source", "include": True},
            {"id": "file-2", "path": "unreadable.py", "component_id": "main", "kind": "source", "include": True},
        ]
        base_payload = {
            "context": context,
            "files": files,
            "material_permissions": [{"paths": ["counter.py", "unreadable.py"], "decision": "allow", "evidence_id": "EV"}],
            "request": {
                "scope_input": {
                    "metadata": {"software_id": "demo", "name": "合成软件", "version": "1.0",
                                 "completed_date": None, "published_date": None, "runtime_environment": None},
                    "components": [{"id": "main", "kind": "standalone", "version": "1.0",
                                    "origin": "own", "origin_evidence": "EV-O", "claim": ["计数表达"],
                                    "exclusions": [], "subjects": []}],
                },
                "rights": [{"component_id": "main", "requested_decision": "claim", "evidence_ids": ["EV"],
                            "permissions": {"local_process": "allow", "deposit": "allow", "public": "deny", "cloud": "deny"}}],
                "files": files,
                "inventory_complete": True,
                "pagination": {"selection": "all", "lines_per_page": 50, "wrap_columns": 78, "basis": "synthetic"},
            },
        }
        # Non-bool inventory_complete MUST be rejected
        bad_payload = core.strict_json_loads(core.canonical_bytes(base_payload).decode("utf-8"))
        bad_payload["request"]["inventory_complete"] = "false"
        with self.assertRaisesRegex(core.ContractError, "inventory_complete_bool_required"):
            software_intake.collect_candidates(self.root, "bad-inv", payload=bad_payload, ask=lambda p: "" if "一次选择" in p else "yes")
        self.assertFalse((self.root / "bad-inv").exists())

        # Excluded source file MUST downgrade inventory_complete to False and record excluded_sources
        summary = software_intake.collect_candidates(
            self.root, "excluded-cand", payload=base_payload,
            ask=lambda p: "" if "一次选择" in p else "yes",
        )
        self.assertFalse(summary["inventory_complete"])
        self.assertEqual([{"id": "file-2", "path": "unreadable.py", "read_status": "read",
                           "exclusion_reason": "undecodable"}], summary["excluded_sources"])
        authorization = self.load(summary["authorization"])
        self.assertEqual(summary["excluded_sources"], authorization["excluded_sources"])
        request = self.load(authorization["request"]["path"])
        self.assertFalse(request["inventory_complete"])
        prepared = self.prepare(summary)
        self.assertIn("source_coverage_incomplete", {issue["code"] for issue in prepared["issues"]})

        # confirmation_group OSError on missing authorized_root MUST be sanitized to discovery_io_failed
        disc = software_discovery.discover({
            "context": context, "authorized_root": str(self.root),
            "files": [{"id": "file-1", "path": "counter.py", "component_id": "main"}],
            "material_permissions": [{"paths": ["counter.py"], "decision": "allow", "evidence_id": "EV"}],
        })
        broken_req = {**request, "context": context, "authorized_root": str(self.root / "nonexistent-root")}
        broken_req.pop("delivery", None)
        with self.assertRaisesRegex(core.ContractError, "^discovery_io_failed$"):
            software_discovery.confirmation_group({"request": broken_req, "discovery": disc})

    def test_collect_candidates_downgrades_inventory_complete_for_non_source_kind_excluded_files(self):
        (self.root / "bad_code.py").write_bytes(b"\xff\xfe\x80")
        (self.root / "bin_mod.c").write_bytes(b"int main(){\x00return 0;}\n")
        (self.root / "secret_code.py").write_text("TOKEN = 'TOP_SECRET_MARKER'\n", encoding="utf-8")
        (self.root / ".env").write_text("KEY=1\n", encoding="utf-8")
        context = {
            "environment": {
                "assessment_evidence": "synthetic-assessment",
                "data_paths": [
                    {"id": pid, "mode": "local", "verified": True, "evidence": "synthetic-measured-" + pid}
                    for pid in software_intake.DATA_PATHS
                ],
            },
            "permissions": [
                {
                    "action": act,
                    "purpose": software_intake.PURPOSE,
                    "recipient": "local_tool",
                    "decision": "allow",
                    "authority_evidence": "synthetic-authority",
                    "valid_from": (self.now - timedelta(hours=1)).isoformat(),
                    "valid_until": (self.now + timedelta(hours=1)).isoformat(),
                }
                for act in ("local_read", "local_write")
            ],
            "sensitivity": "synthetic",
            "purpose": software_intake.PURPOSE,
            "now": self.now.isoformat(),
        }

        def make_payload(extra_entry, *, secrets=()):
            files = [
                {"id": "file-1", "path": "counter.py", "component_id": "main", "kind": "source", "include": True},
                *([] if extra_entry is None else [extra_entry]),
            ]
            return {
                "context": context,
                "files": files,
                "sensitive_literals": list(secrets),
                "material_permissions": [{"paths": [f["path"] for f in files], "decision": "allow", "evidence_id": "EV"}],
                "request": {
                    "scope_input": {
                        "metadata": {"software_id": "demo", "name": "合成软件", "version": "1.0",
                                     "completed_date": None, "published_date": None, "runtime_environment": None},
                        "components": [{"id": "main", "kind": "standalone", "version": "1.0",
                                        "origin": "own", "origin_evidence": "EV-O", "claim": ["计数表达"],
                                        "exclusions": [], "subjects": []}],
                    },
                    "rights": [{"component_id": "main", "requested_decision": "claim", "evidence_ids": ["EV"],
                                "permissions": {"local_process": "allow", "deposit": "allow", "public": "deny", "cloud": "deny"}}],
                    "files": files,
                    "inventory_complete": True,
                    "pagination": {"selection": "all", "lines_per_page": 50, "wrap_columns": 78, "basis": "synthetic"},
                },
            }

        ask = lambda p: "" if "一次选择" in p else "yes"

        # Clean complete inventory MUST remain inventory_complete=True
        clean_summary = software_intake.collect_candidates(
            self.root, "clean-complete", payload=make_payload(None), ask=ask,
        )
        self.assertTrue(clean_summary["inventory_complete"])
        self.assertNotIn("excluded_sources", clean_summary)

        # Any excluded/unreadable file with non-"source" kind variant MUST force inventory_complete=False
        bypass_cases = [
            ("other_py_undecodable", {"id": "file-2", "path": "bad_code.py", "component_id": "main", "kind": "other", "include": False}, ()),
            ("upper_SOURCE_py", {"id": "file-2", "path": "bad_code.py", "component_id": "main", "kind": "SOURCE", "include": True}, ()),
            ("program_kind_py", {"id": "file-2", "path": "bad_code.py", "component_id": "main", "kind": "program", "include": True}, ()),
            ("code_kind_binary", {"id": "file-2", "path": "bin_mod.c", "component_id": "main", "kind": "code", "include": True}, ()),
            ("generated_kind_sensitive", {"id": "file-2", "path": "secret_code.py", "component_id": "main", "kind": "generated", "include": False}, ("TOP_SECRET_MARKER",)),
            ("other_kind_env", {"id": "file-2", "path": ".env", "component_id": "main", "kind": "other", "include": False}, ()),
        ]
        for idx, (label, extra, secrets) in enumerate(bypass_cases):
            with self.subTest(case=label):
                summary = software_intake.collect_candidates(
                    self.root, f"bypass-{idx}", payload=make_payload(extra, secrets=secrets), ask=ask,
                )
                self.assertFalse(summary["inventory_complete"])
                self.assertEqual(1, len(summary["excluded_sources"]))
                self.assertEqual(extra["path"], summary["excluded_sources"][0]["path"])
                req = self.load(self.request_path(summary))
                self.assertFalse(req["inventory_complete"])
                prepared = self.prepare(summary)
                self.assertIn("source_coverage_incomplete", {issue["code"] for issue in prepared["issues"]})

    def test_collect_candidates_isolates_single_file_open_failure_and_explicit_exclusions(self):
        (self.root / "locked.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "helper.py").write_text("y = 2\n", encoding="utf-8")
        context = {
            "environment": {
                "assessment_evidence": "synthetic-assessment",
                "data_paths": [
                    {"id": pid, "mode": "local", "verified": True, "evidence": "synthetic-measured-" + pid}
                    for pid in software_intake.DATA_PATHS
                ],
            },
            "permissions": [
                {
                    "action": act,
                    "purpose": software_intake.PURPOSE,
                    "recipient": "local_tool",
                    "decision": "allow",
                    "authority_evidence": "synthetic-authority",
                    "valid_from": (self.now - timedelta(hours=1)).isoformat(),
                    "valid_until": (self.now + timedelta(hours=1)).isoformat(),
                }
                for act in ("local_read", "local_write")
            ],
            "sensitivity": "synthetic",
            "purpose": software_intake.PURPOSE,
            "now": self.now.isoformat(),
        }
        ask = lambda p: "" if "一次选择" in p else "yes"

        def make_payload(file_entries, **extra_top):
            return {
                "context": context,
                "files": file_entries,
                "material_permissions": [
                    {"paths": [f["path"] for f in file_entries], "decision": "allow", "evidence_id": "EV"}
                ],
                "request": {
                    "scope_input": {
                        "metadata": {"software_id": "demo", "name": "合成软件", "version": "1.0",
                                     "completed_date": None, "published_date": None, "runtime_environment": None},
                        "components": [{"id": "main", "kind": "standalone", "version": "1.0",
                                        "origin": "own", "origin_evidence": "EV-O", "claim": ["计数表达"],
                                        "exclusions": [], "subjects": []}],
                    },
                    "rights": [{"component_id": "main", "requested_decision": "claim", "evidence_ids": ["EV"],
                                "permissions": {"local_process": "allow", "deposit": "allow", "public": "deny", "cloud": "deny"}}],
                    "files": file_entries,
                    "inventory_complete": True,
                    "pagination": {"selection": "all", "lines_per_page": 50, "wrap_columns": 78, "basis": "synthetic"},
                },
                **extra_top,
            }

        # 1) Single-file PermissionError on open() MUST record unreadable exclusion and downgrade inventory_complete
        original_open = Path.open

        def deny_locked_open(path, *args, **kwargs):
            if path.name == "locked.py":
                raise PermissionError("simulated file lock")
            return original_open(path, *args, **kwargs)

        files = [
            {"id": "file-1", "path": "counter.py", "component_id": "main", "kind": "source", "include": True},
            {"id": "file-2", "path": "locked.py", "component_id": "main", "kind": "source", "include": True},
        ]
        with patch.object(Path, "open", deny_locked_open):
            summary = software_intake.collect_candidates(
                self.root, "cand-open-err", payload=make_payload(files), ask=ask,
            )
        self.assertFalse(summary["inventory_complete"])
        self.assertEqual([{"id": "file-2", "path": "locked.py", "read_status": "not_read",
                           "exclusion_reason": "unreadable"}], summary["excluded_sources"])

        listed = {"id": "file-2", "path": "helper.py", "component_id": "main", "kind": "source", "include": True}
        explicit_files = [files[0], listed]
        exp_payload = make_payload(explicit_files)
        exp_payload["request"]["excluded_sources"] = [{"id": "X1", "path": "helper.py", "reason": "out_of_scope"}]

        def forbid_helper_open(path, *args, **kwargs):
            if path.name == "helper.py":
                self.fail("excluded helper.py opened")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", forbid_helper_open):
            exp_summary = software_intake.collect_candidates(
                self.root, "cand-explicit-excl", payload=exp_payload, ask=ask,
            )
        self.assertFalse(exp_summary["inventory_complete"])
        self.assertEqual("helper.py", exp_summary["excluded_sources"][0]["path"])
        self.assertEqual("not_read", exp_summary["excluded_sources"][0]["read_status"])
        auth = self.load(exp_summary["authorization"])
        self.assertEqual(["counter.py"], [row["path"] for row in auth["files"]])
        request = self.load(auth["request"]["path"])
        self.assertEqual(["counter.py"], [row["path"] for row in request["files"]])

        # 3) Security violation: outside hardlink MUST be rejected immediately (never swallowed)
        with tempfile.TemporaryDirectory(prefix="dyz-cand-outside-") as outside:
            outside_file = Path(outside) / "secret.py"
            outside_file.write_text("SECRET = 1\n", encoding="utf-8")
            os.link(outside_file, self.root / "escaped.py")
            bad_files = [
                {"id": "file-1", "path": "counter.py", "component_id": "main", "kind": "source", "include": True},
                {"id": "file-2", "path": "escaped.py", "component_id": "main", "kind": "source", "include": True},
            ]
            with self.assertRaisesRegex(core.ContractError, "source_file_or_link_invalid"):
                software_intake.collect_candidates(
                    self.root, "cand-hardlink-reject", payload=make_payload(bad_files), ask=ask,
                )
            self.assertFalse((self.root / "cand-hardlink-reject").exists())
            (self.root / "escaped.py").unlink()


if __name__ == "__main__":
    unittest.main()
