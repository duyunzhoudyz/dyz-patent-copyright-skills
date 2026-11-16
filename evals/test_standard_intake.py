"""集中采集的原创本地反例；不联网、不接触真实业务材料。"""

import contextlib
import copy
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tools import cli, core, standard_intake, standards, standards_delivery

ROOT = Path(__file__).resolve().parents[1]


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


class StandardIntakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dyz-standard-intake-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = b"Original supplied text; not automatically parsed.\n"
        (self.root / "draft.txt").write_bytes(self.raw)
        self.now = datetime.now(timezone.utc)

    def context(self, sensitivity="confidential"):
        values = [sensitivity, "synthetic-test-six-path-assessment"]
        for path_id in standard_intake.DATA_PATHS:
            values += ["local", "synthetic-measured-" + path_id]
        return values + [
            "synthetic-test-local-authority",
            (self.now - timedelta(hours=1)).isoformat(),
            (self.now + timedelta(hours=1)).isoformat(),
        ]

    def answers(self, *, synthetic=False, sensitivity="confidential", mode="lines",
                materials=None, clauses=None, comments=None, metadata=None,
                collection="unknown", collection_evidence="", consent="yes"):
        values = [] if synthetic else self.context(sensitivity)
        values += [mode]
        if materials is None:
            materials = ["M-1\tdraft.txt\t" + core.sha256_bytes(self.raw)
                         + "\tdraft\toperator-provided:draft-v1"]
        values += [*materials, ""]
        if mode == "lines":
            values += metadata or [
                "原创内部测试标准", "INTAKE-1", "2", "1",
                "synthetic-test-organization", "internal", "interface", "draft",
            ]
            values += [*([] if clauses is None else clauses), "",
                       *([] if comments is None else comments), "", collection]
            if collection == "complete":
                values += [collection_evidence]
        return Answers(values + [consent])

    def clause(self, **kwargs):
        fields = {"id": "C-1", "strength": "requirement", "kind": "normative",
                  "source": "M-1#paragraph-1", "conditions": "收到记录时",
                  "exceptions": "-", "text": "  接口应保留原始记录。  "}
        fields.update(kwargs)
        return "\t".join(fields.values())

    def comment(self, **kwargs):
        fields = {"id": "COM-1", "target": "C-1", "version": "1",
                  "participant": "synthetic-reviewer", "source": "M-1#comment-1",
                  "text": "  请保留未知例外，不自动补阈值。  "}
        fields.update(kwargs)
        return "\t".join(fields.values())

    def collect(self, answers=None, *, output="intake", synthetic=False):
        return standard_intake.collect(
            self.root, output, input_fn=answers or self.answers(synthetic=synthetic),
            synthetic=synthetic,
        )

    def load(self, relative):
        return core.strict_json_loads((self.root / relative).read_text(encoding="utf-8"))

    def imported_payload(self, sensitivity="confidential"):
        return {
            "contract_version": 2, "project_id": "EXISTING-1", "version": "2",
            "standard_name": "已有内部标准", "baseline_version": "1",
            "adaptation": {"organization": "test-organization", "standard_type": "internal",
                           "domain": "interface", "stage": "draft"},
            "sensitivity": sensitivity, "delivery_stage": "draft",
            "baseline_clauses": [], "clauses": [], "comments": [],
            "comment_outcomes": [], "collection_status": "unknown",
            "extension_to_preserve": {"unknown_fact": None, "original": "  原文  "},
        }

    def payload_answers(self, payload, **kwargs):
        raw = core.canonical_bytes(payload) + b"\n"
        (self.root / "approved-v2.json").write_bytes(raw)
        material = "P-1\tapproved-v2.json\t" + core.sha256_bytes(raw) + "\tpayload\tprovided-v2"
        return self.answers(mode="v2", materials=[material], **kwargs)

    def no_io(self, answers, code=None, *, synthetic=False):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with patch.object(Path, "open", side_effect=AssertionError("unexpected file access")):
                with self.assertRaises(core.ContractError) as caught:
                    self.collect(answers, synthetic=synthetic)
        if code is not None:
            self.assertEqual(str(caught.exception), code)
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))
        self.assertFalse((self.root / "intake").exists())

    def test_line_draft_preserves_text_unknowns_and_creates_no_confirmed_rows(self):
        answers = self.answers(clauses=[self.clause(conditions="?", strength="?")],
                               comments=[self.comment()])
        summary = self.collect(answers)
        self.assertTrue(answers.finished)
        payload = self.load(summary["input"])
        self.assertEqual(payload["contract_version"], 2)
        self.assertEqual(payload["sensitivity"], "confidential")
        self.assertEqual(payload["clauses"][0]["text"], "  接口应保留原始记录。  ")
        self.assertNotIn("conditions", payload["clauses"][0])
        self.assertNotIn("strength", payload["clauses"][0])
        self.assertEqual(payload["comments"][0]["text"], self.comment().split("\t")[-1])
        self.assertEqual(payload["comment_outcomes"], [])
        self.assertEqual(payload["baseline_clauses"], [])
        self.assertEqual(payload["verification_matrix"], [])
        self.assertEqual(payload["compilation_note"], {})
        self.assertEqual(payload["collection_status"], "unknown")
        self.assertIn("clauses/0/conditions", payload["intake"]["unknown_fields"])
        self.assertIn("clauses/0/strength", payload["intake"]["unknown_fields"])
        self.assertEqual(payload["intake"]["raw_clause_lines"], [self.clause(conditions="?", strength="?")])
        result = standards.closed_loop(payload)
        codes = {item["code"] for item in result["issues"]}
        self.assertTrue({"comment_outcome_missing", "verification_matrix_missing",
                         "compilation_note_structure_missing"}.issubset(codes))
        missing = (self.root / summary["missing_items"]).read_text(encoding="utf-8")
        self.assertIn("comment_outcome_missing", missing)
        self.assertIn("原意见尚无处置建议", missing)
        self.assertIn("实质编制说明未提供", missing)
        self.assertNotIn("请保留未知例外", missing)
        self.assertEqual((self.root / "draft.txt").read_bytes(), self.raw)
        self.assertEqual(len([p for p in answers.prompts if "集中确认" in p]), 1)
        self.assertNotIn("接口应保留原始记录", "".join(answers.prompts))
        original_payload = copy.deepcopy(payload)
        admission = self.load(summary["authorization"])
        manifest = standards_delivery.prepare(self.root, payload, summary["output"],
                                              admission=admission)
        self.assertEqual(payload, original_payload)
        self.assertEqual(manifest["delivery_state"], "internal_draft_needs_evidence")
        self.assertTrue(standards_delivery.verify(
            self.root, payload, summary["output"], admission=admission)["file_hashes_equal"])
        stored = self.load(summary["output"] + "/internal/input.json")
        self.assertEqual(stored, original_payload)
        self.assertNotIn("conditions", stored["clauses"][0])
        self.assertNotIn("strength", stored["clauses"][0])
        self.assertEqual(stored["compilation_note"], {})
        self.assertEqual(stored["comment_outcomes"], [])
        with zipfile.ZipFile(self.root / summary["output"] / "body/standard.docx") as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("原创内部测试标准", body)
        self.assertIn("接口应保留原始记录。", body)

    def test_real_authorization_exactly_matches_existing_prepare_cli_contract(self):
        summary = self.collect(self.answers(clauses=[self.clause()]))
        authorization = self.load(summary["authorization"])
        self.assertEqual(set(authorization), {
            "root", "output", "payload_hash", "input_hash", "inputs", "sensitivity",
            "purpose", "permissions", "environment",
        })
        self.assertEqual(authorization["inputs"], {
            summary["input"]: summary["input_sha256"], "draft.txt": core.sha256_bytes(self.raw),
        })
        self.assertEqual(authorization["output"], "intake/pack")
        self.assertEqual(authorization["root"], str(self.root.resolve()))
        self.assertEqual(authorization["sensitivity"], "confidential")
        for field in ("input", "authorization", "material_index"):
            self.assertEqual(summary[field + "_sha256"], core.sha256_bytes(
                (self.root / summary[field]).read_bytes()))
        payload = self.load(summary["input"])
        self.assertEqual(authorization["payload_hash"], core.digest(payload))
        args = type("Args", (), {
            "root": str(self.root), "input": summary["input"], "output": summary["output"],
            "authorization": summary["authorization"],
            "authorization_sha256": summary["authorization_sha256"],
            "synthetic": False, "verify": False,
        })()
        root, reread, admission, byte_hash = cli._read_standard_input(args)
        self.assertEqual(root.resolve(), self.root.resolve())
        self.assertEqual(reread, payload)
        self.assertEqual(admission, authorization)
        self.assertEqual(byte_hash, summary["input_sha256"])
        manifest = standards_delivery.prepare(root, reread, summary["output"], admission=admission)
        self.assertEqual(manifest["delivery_state"], "internal_draft_needs_evidence")
        self.assertTrue(standards_delivery.verify(
            root, reread, summary["output"], admission=admission)["file_hashes_equal"])
        self.assertEqual(manifest["professional_review"], "not_performed")

    def test_inventory_binds_supplied_raw_hashes_and_does_not_claim_text_extraction(self):
        summary = self.collect()
        index = self.load(summary["material_index"])
        row = index["materials"][0]
        self.assertEqual(row["path"], "draft.txt")
        self.assertEqual(row["sha256"], core.sha256_bytes(self.raw))
        self.assertEqual(row["expected_sha256"], row["sha256"])
        self.assertEqual(row["content_handling"], "original_retained_not_parsed")
        self.assertEqual(index["proposition_support"], "not_verified")
        self.assertNotIn("Original supplied text", str(summary))
        self.assertFalse((self.root / summary["output"]).exists())

    def test_existing_v2_preserves_all_fields_and_does_not_reask_known_metadata(self):
        payload = self.imported_payload()
        answers = self.payload_answers(payload)
        summary = self.collect(answers)
        self.assertTrue(answers.finished)
        self.assertEqual(self.load(summary["input"]), payload)
        self.assertTrue(any("EXISTING-1" in p and "集中确认" in p for p in answers.prompts))
        self.assertFalse(any(p.startswith("标准名称") for p in answers.prompts))
        self.assertEqual(sum("集中确认" in p for p in answers.prompts), 1)

    def test_synthetic_is_explicit_and_never_relabels_real_material(self):
        summary = self.collect(self.answers(synthetic=True, materials=[]),
                               output="synthetic", synthetic=True)
        self.assertEqual(summary["mode"], "synthetic")
        self.assertEqual(self.load(summary["input"])["sensitivity"], "synthetic")
        self.assertIsNone(summary["authorization"])
        self.assertFalse((self.root / "synthetic/authorization.json").exists())
        with self.assertRaisesRegex(core.ContractError, "^standard_intake_sensitivity_changed$"):
            self.collect(self.payload_answers(self.imported_payload(), synthetic=True),
                         output="bad", synthetic=True)
        self.assertFalse((self.root / "bad").exists())
        values = self.context("synthetic")
        self.no_io(Answers(values), "standard_intake_choice_invalid")

    def test_all_named_source_materials_are_authorized_with_canonical_paths(self):
        folder = self.root / "sources"
        folder.mkdir()
        raw = b"original-source-bytes"
        (folder / "original.pdf").write_bytes(raw)
        materials = [
            "M-1\tdraft.txt\t" + core.sha256_bytes(self.raw) + "\tdraft\tprovided:draft",
            "S-1\tsources\\original.pdf\t" + core.sha256_bytes(raw) + "\tsource\tprovided:source-v1",
        ]
        summary = self.collect(self.answers(materials=materials))
        authorization = self.load(summary["authorization"])
        index = self.load(summary["material_index"])
        self.assertEqual(authorization["inputs"], {
            summary["input"]: summary["input_sha256"],
            "draft.txt": core.sha256_bytes(self.raw),
            "sources/original.pdf": core.sha256_bytes(raw),
        })
        self.assertEqual(index["materials"][1]["path"], "sources/original.pdf")
        self.assertEqual((folder / "original.pdf").read_bytes(), raw)

    def test_real_public_also_requires_all_six_data_paths_before_reading(self):
        answers = self.answers(sensitivity="public")
        original_open = Path.open
        opened = []
        def tracked(path, *args, **kwargs):
            self.assertTrue(answers.finished)
            self.assertGreater(preflight.call_count, 0)
            opened.append(path.name)
            return original_open(path, *args, **kwargs)
        with patch.object(core, "preflight", wraps=core.preflight) as preflight:
            with patch.object(Path, "open", tracked):
                summary = self.collect(answers)
        environment = self.load(summary["authorization"])["environment"]
        self.assertEqual([row["id"] for row in environment["data_paths"]], list(standard_intake.DATA_PATHS))
        self.assertTrue(all(call.kwargs["sensitivity"] == "restricted" for call in preflight.call_args_list))
        self.assertEqual(opened[0], "draft.txt")
        self.assertGreaterEqual(preflight.call_count, 6)

    def test_unknown_external_bare_local_and_expired_permissions_prevent_reads(self):
        for index, value, code in (
            (2, "unknown", "standard_intake_choice_invalid"),
            (2, "external", "standard_intake_choice_invalid"),
            (3, "本地", "data_path_evidence_required"),
            (14, "", "standard_intake_answer_required"),
            (16, "2000-01-01T00:00:00Z", "permission_not_proven"),
        ):
            with self.subTest(value=value):
                answers = self.answers()
                answers.values[index] = value
                self.no_io(answers, code)

    def test_expiration_during_questions_is_rechecked_before_first_material_read(self):
        answers = self.answers()
        def ask(prompt):
            value = answers(prompt)
            if answers.finished:
                clock.now.return_value = self.now + timedelta(hours=2)
            return value
        with patch.object(standard_intake, "datetime") as clock:
            clock.now.return_value = self.now
            self.no_io(ask, "permission_not_proven")

    def test_missing_wrong_and_duplicate_expected_hashes_or_paths_reject_before_output(self):
        for materials in (
            ["M-1\tdraft.txt\t\tdraft\tsource"],
            ["M-1\tdraft.txt\tnot-a-sha\tdraft\tsource"],
            ["M-1\t../draft.txt\t" + core.sha256_bytes(self.raw) + "\tdraft\tsource"],
            ["M-1\tdraft.txt\t" + core.sha256_bytes(self.raw) + "\tdraft\tsource",
             "M-2\tdraft.txt\t" + core.sha256_bytes(self.raw) + "\tdraft\tsource"],
        ):
            with self.subTest(materials=materials):
                self.no_io(self.answers(materials=materials))
        answers = self.answers(materials=["M-1\tdraft.txt\t" + "0" * 64 + "\tdraft\tsource"])
        with self.assertRaisesRegex(core.ContractError, "^standard_intake_material_hash_changed$"):
            self.collect(answers)
        self.assertFalse((self.root / "intake").exists())

    def test_all_paths_preflighted_before_reading_first_valid_material(self):
        materials = ["M-1\tdraft.txt\t" + core.sha256_bytes(self.raw) + "\tdraft\tsource",
                     "M-2\tmissing.txt\t" + "0" * 64 + "\tsource\tunknown"]
        self.no_io(self.answers(materials=materials))

    def test_existing_output_is_rejected_without_prompt_or_overwrite(self):
        (self.root / "intake").mkdir()
        sentinel = self.root / "intake/retained.txt"
        sentinel.write_bytes(b"retained")
        with patch.object(Path, "open", side_effect=AssertionError("unexpected access")):
            with self.assertRaisesRegex(core.ContractError, "^output_exists$"):
                self.collect(lambda _: self.fail("must reject before asking"))
        self.assertEqual(sentinel.read_bytes(), b"retained")

    def test_real_root_cannot_contain_runtime_or_live_inside_it(self):
        with self.assertRaisesRegex(core.ContractError, "^standard_case_root_must_be_independent$"):
            standard_intake.collect(ROOT, "new-intake-forbidden", input_fn=self.answers())
        self.assertFalse((ROOT / "new-intake-forbidden").exists())

    def test_hardlink_alias_rejected_before_reads(self):
        try:
            os.link(self.root / "draft.txt", self.root / "alias.txt")
        except OSError:
            self.skipTest("hardlinks unavailable")
        self.no_io(self.answers(), "standard_intake_file_alias_rejected")

    def test_link_paths_rejected_even_when_resolving_inside_root(self):
        linked = self.root / "linked"
        folder = self.root / "actual"
        folder.mkdir()
        (folder / "draft.txt").write_bytes(self.raw)
        if os.name == "nt":
            process = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(folder)],
                                     capture_output=True, text=True)
            if process.returncode:
                self.skipTest("directory junction unavailable")
        else:
            linked.symlink_to(folder, target_is_directory=True)
        self.addCleanup(lambda: linked.rmdir() if os.name == "nt" else linked.unlink())
        materials = ["M-1\tlinked/draft.txt\t" + core.sha256_bytes(self.raw) + "\tdraft\tsource"]
        self.no_io(self.answers(materials=materials), "standard_intake_link_rejected")

    def test_refusal_and_cancel_do_not_echo_or_read_line_material(self):
        self.no_io(self.answers(consent="no"), "standard_intake_consent_required")
        for position in (0, -1):
            for error in (EOFError("private-text"), KeyboardInterrupt("private-text")):
                answers = self.answers()
                answers.values[position] = error
                self.no_io(answers, "standard_intake_cancelled")

    def test_import_is_strict_json_and_sensitivity_cannot_change(self):
        for raw, code in (
            (b'{"contract_version":2,"contract_version":2}', "duplicate_json_key"),
            (b'{"value":NaN}', "nonfinite_json_number"),
            (core.canonical_bytes({**self.imported_payload(), "contract_version": 1}),
             "standard_intake_requires_v2"),
            (core.canonical_bytes(self.imported_payload("public")),
             "standard_intake_sensitivity_changed"),
        ):
            with self.subTest(code=code):
                (self.root / "approved-v2.json").write_bytes(raw)
                material = "P-1\tapproved-v2.json\t" + core.sha256_bytes(raw) + "\tpayload\tprovided"
                with self.assertRaisesRegex(core.ContractError, "^" + code + "$"):
                    self.collect(self.answers(mode="v2", materials=[material]))
                self.assertFalse((self.root / "intake").exists())

    def test_material_changed_at_confirmation_does_not_get_new_implicit_authorization(self):
        payload = self.imported_payload()
        answers = self.payload_answers(payload)
        def ask(prompt):
            value = answers(prompt)
            if "集中确认" in prompt:
                (self.root / "approved-v2.json").write_bytes(core.canonical_bytes({**payload, "version": "3"}))
            return value
        with self.assertRaisesRegex(core.ContractError, "^standard_intake_material_hash_changed$"):
            self.collect(ask)
        self.assertFalse((self.root / "intake").exists())

    def test_finite_line_format_rejects_ambiguous_rows_without_dropping_text(self):
        cases = [self.clause() + "\textra", self.clause(strength="mandatory"),
                 self.clause(kind="technical"), "arbitrary prose is not a clause row"]
        for clause in cases:
            with self.subTest(clause=clause):
                self.no_io(self.answers(clauses=[clause]))
        self.no_io(self.answers(clauses=[self.clause(), self.clause()]))

    def test_unknown_metadata_keeps_visible_draft_gap_instead_of_inventing_organization(self):
        summary = self.collect(self.answers(
            metadata=["", "", "", "", "", "", "", ""],
            clauses=[self.clause(strength="?", conditions="?")],
        ))
        payload = self.load(summary["input"])
        self.assertEqual(payload["adaptation"]["organization"], "unknown")
        self.assertEqual(payload["project_id"], "unknown")
        self.assertIn("adaptation/organization", payload["intake"]["unknown_fields"])
        self.assertTrue(payload["material_open_items"])
        self.assertTrue(all(item["blocks"] == "submission" for item in payload["material_open_items"]))
        self.assertFalse(standards.closed_loop(payload)["outcome_tally"]["closed"])
        admission = self.load(summary["authorization"])
        manifest = standards_delivery.prepare(self.root, payload, summary["output"],
                                              admission=admission)
        self.assertEqual(manifest["delivery_state"], "internal_draft_needs_evidence")
        self.assertTrue(standards_delivery.verify(
            self.root, payload, summary["output"], admission=admission)["file_hashes_equal"])
        self.assertEqual(self.load(summary["output"] + "/internal/input.json"), payload)

    def test_collecting_no_comments_does_not_declare_complete_or_zero_feedback(self):
        summary = self.collect(self.answers(materials=[]))
        payload = self.load(summary["input"])
        self.assertEqual(payload["comments"], [])
        self.assertEqual(payload["collection_status"], "unknown")
        self.assertNotIn("collection_evidence", payload)
        missing = (self.root / summary["missing_items"]).read_text(encoding="utf-8")
        self.assertIn("comment_collection_incomplete", missing)
        self.assertIn("material_inventory_empty", missing)

    def test_absent_clause_is_collected_as_gap_but_never_fabricated_for_delivery(self):
        summary = self.collect(self.answers(clauses=[]))
        payload = self.load(summary["input"])
        self.assertEqual(payload["clauses"], [])
        self.assertIn("clauses_missing", summary["issue_codes"])
        admission = self.load(summary["authorization"])
        with self.assertRaisesRegex(core.ContractError, "^standard_clauses_required$"):
            standards_delivery.prepare(self.root, payload, summary["output"], admission=admission)
        self.assertFalse((self.root / summary["output"]).exists())
        self.assertEqual(self.load(summary["input"])["clauses"], [])

    def test_summary_is_written_last_and_failure_keeps_no_success_receipt(self):
        real_open = Path.open
        def failed(path, *args, **kwargs):
            if path.name == "missing-items.txt":
                raise OSError("private-disk-failure")
            return real_open(path, *args, **kwargs)
        with patch.object(Path, "open", failed):
            with self.assertRaisesRegex(core.ContractError, "^standard_intake_io_failed$"):
                self.collect()
        self.assertTrue((self.root / "intake").is_dir())
        self.assertFalse((self.root / "intake/summary.json").exists())
        self.assertEqual((self.root / "draft.txt").read_bytes(), self.raw)

    def test_integrated_cli_real_and_synthetic_both_reach_prepare_and_verify(self):
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        for synthetic in (False, True):
            with self.subTest(synthetic=synthetic):
                output = "cli-synthetic" if synthetic else "cli-real"
                answers = self.answers(synthetic=synthetic, clauses=[self.clause()])
                command = [sys.executable, "-B", "-X", "utf8", "-m", "tools",
                           "standard-intake", "--root", str(self.root), "--output", output]
                if synthetic:
                    command.append("--synthetic")
                collected = subprocess.run(command, cwd=ROOT,
                                           input="\n".join(answers.values) + "\n",
                                           capture_output=True, text=True,
                                           encoding="utf-8", env=environment)
                self.assertEqual(collected.returncode, 0, collected.stderr)
                summary = self.load(output + "/summary.json")
                self.assertNotIn("接口应保留原始记录", collected.stdout)
                self.assertNotIn("synthetic-test-local-authority", collected.stdout)
                prepare = [sys.executable, "-B", "-X", "utf8", "-m", "tools",
                           "prepare-standard", "--root", str(self.root),
                           "--input", summary["input"], "--output", summary["output"]]
                if synthetic:
                    prepare.append("--synthetic")
                else:
                    prepare += ["--authorization", summary["authorization"],
                                "--authorization-sha256", summary["authorization_sha256"]]
                for arguments in (prepare, prepare + ["--verify"]):
                    process = subprocess.run(arguments, cwd=ROOT, capture_output=True,
                                             text=True, encoding="utf-8", env=environment)
                    self.assertIn(process.returncode, (0, 4), process.stderr + process.stdout)
                    self.assertEqual(process.stderr, "")
                self.assertEqual(len(list((self.root / summary["output"] / "body").glob("*.docx"))), 5)
                self.assertEqual((self.root / "draft.txt").read_bytes(), self.raw)

    def test_console_input_requires_no_engine_json_and_does_not_echo_body_or_authority(self):
        answers = self.answers(clauses=[self.clause()], comments=[self.comment()])
        script = ("import json,sys; from tools.standard_intake import collect; "
                  "print('\\nRESULT:' + json.dumps(collect(sys.argv[1], 'console'), ensure_ascii=False))")
        process = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", script, str(self.root)], cwd=ROOT,
            input="\n".join(answers.values) + "\n", capture_output=True, text=True,
            encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertNotIn("接口应保留原始记录", process.stdout)
        self.assertNotIn("synthetic-test-local-authority", process.stdout)
        self.assertNotIn("请保留未知例外", process.stdout)
        self.assertIn("RESULT:", process.stdout)
        self.assertTrue((self.root / "console/task.json").is_file())


if __name__ == "__main__":
    unittest.main()
