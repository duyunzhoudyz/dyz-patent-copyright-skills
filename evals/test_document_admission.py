"""SE-07A文档层准入：全部材料为临时合成替身，不读取真实受限文件。"""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import documents
from tools.core import ContractError, digest, sha256_bytes
from evals.test_document_quality import source_case


PATHS = ("host_model", "index", "telemetry", "tools", "logs", "subprocess")


def admission_for(root, spec, output="pack"):
    now = datetime.now(timezone.utc)
    permissions = [{"action": action, "purpose": "synthetic-admission-test", "recipient": "local_tool",
                    "decision": "allow", "authority_evidence": "synthetic-authority-fixture-not-a-real-grant",
                    "valid_from": (now - timedelta(hours=1)).isoformat(),
                    "valid_until": (now + timedelta(hours=1)).isoformat()}
                   for action in ("local_read", "local_processing", "copy", "local_output")]
    materials = [{"path": item["path"], "sha256": item["sha256"],
                  "source": {"id": "S" + str(index), "version": "1", "origin": "synthetic-local-fixture", "level": "full_text"},
                  "permissions": copy.deepcopy(permissions)}
                 for index, item in enumerate(spec["sources"] + spec.get("dependencies", []))]
    return {"mode": "authorized_case", "case_root": str(root.resolve()), "spec_sha256": digest(spec),
            "output": output, "purpose": "synthetic-admission-test", "output_roles": ["body", "internal"],
            "environment": {"assessment_evidence": "synthetic-assessment-not-a-real-attestation",
                "data_paths": [{"id": name, "mode": "local" if name == "tools" else "disabled",
                                "verified": True, "evidence": "synthetic-path-fixture"} for name in PATHS]},
            "permissions": permissions, "materials": materials}


class DocumentAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-admission-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = source_case(self.root, "仅当合成条件成立才启动；测试材料不是真实案件。")
        self.spec["sensitivity"] = "restricted"
        raw = b"synthetic dependency only"
        (self.root / "dependency.bin").write_bytes(raw)
        self.spec["dependencies"] = [{"path": "dependency.bin", "sha256": sha256_bytes(raw)}]
        self.admission = admission_for(self.root, self.spec)

    def build(self, admission=None, **kwargs):
        return documents.build(self.root, self.spec, "pack", admission=self.admission if admission is None else admission, **kwargs)

    def test_exact_admission_build_verify_and_no_synthetic_relabel(self):
        result = self.build()
        self.assertEqual("authorized_case", result["mode"])
        self.assertEqual(digest(self.admission), result["admission"]["input_hash"])
        self.assertEqual("not_independently_authenticated", result["admission"]["rights_verification"])
        self.assertEqual("not_performed", result["external_action"])
        verified = documents.verify(self.root, self.spec, "pack", admission=self.admission)
        self.assertEqual(result["admission"], verified["admission"])

    def test_bool_empty_and_synthetic_escape_rejected_before_read(self):
        for admission, flags in [(True, {}), ({}, {}), (self.admission, {"synthetic": True}),
                                 (self.admission, {"research_example": True})]:
            with self.subTest(flags=flags, admission_type=type(admission).__name__), patch.object(documents, "_read") as read:
                with self.assertRaises(ContractError):
                    self.build(admission, **flags)
                read.assert_not_called()
        self.assertFalse((self.root / "pack").exists())

    def test_all_permissions_checked_before_any_source_read(self):
        mutations = [
            lambda a: a["materials"].pop(),
            lambda a: a["materials"][1].update(sha256="0" * 64),
            lambda a: a["materials"][1].update(permissions=[]),
            lambda a: a["materials"][0]["source"].update(origin="unknown"),
            lambda a: a.update(output_roles=["body"]),
            lambda a: a.update(spec_sha256="0" * 64),
            lambda a: a.update(output="elsewhere"),
            lambda a: a["environment"]["data_paths"].pop(),
            lambda a: a["environment"]["data_paths"][0].update(verified=False),
            lambda a: a["environment"]["data_paths"][0].update(mode="external"),
            lambda a: a["permissions"][0].update(revoked=True),
            lambda a: a["materials"][0]["permissions"][1].update(revoked=True),
        ]
        for mutate in mutations:
            admission = copy.deepcopy(self.admission)
            mutate(admission)
            with self.subTest(mutation=mutations.index(mutate)), patch.object(documents, "_read") as read:
                with self.assertRaises(ContractError):
                    self.build(admission)
                read.assert_not_called()
        self.assertFalse((self.root / "pack").exists())

    def test_expired_permission_cannot_use_caller_backdated_now(self):
        admission = copy.deepcopy(self.admission)
        admission["now"] = "2020-01-01T00:00:00Z"
        for permission in admission["permissions"]:
            permission.update(valid_from="2019-01-01T00:00:00Z", valid_until="2021-01-01T00:00:00Z")
        with patch.object(documents, "_read") as read, self.assertRaises(ContractError):
            self.build(admission)
        read.assert_not_called()

    def test_actual_clock_is_rechecked_during_verify(self):
        self.build()
        future = datetime.now(timezone.utc) + timedelta(days=1)
        with patch.object(documents, "_utc_now", return_value=future.isoformat()), patch.object(documents, "_read") as read:
            with self.assertRaisesRegex(ContractError, "permission_not_proven"):
                documents.verify(self.root, self.spec, "pack", admission=self.admission)
            read.assert_not_called()

    def test_source_bytes_or_binding_changed_rejected_without_output(self):
        (self.root / "dependency.bin").write_bytes(b"modified synthetic dependency")
        with self.assertRaisesRegex(ContractError, "document_source_changed"):
            self.build()
        self.assertFalse((self.root / "pack").exists())

    def test_path_alias_and_parent_escape_rejected_before_read(self):
        for value in ("../dependency.bin", "source.txt"):
            spec = copy.deepcopy(self.spec)
            spec["dependencies"][0]["path"] = value
            admission = admission_for(self.root, spec)
            with self.subTest(value=value), patch.object(documents, "_read") as read:
                with self.assertRaises(ContractError):
                    documents.build(self.root, spec, "pack", admission=admission)
                read.assert_not_called()

    def test_hardlink_is_not_an_independent_material(self):
        alias = self.root / "alias.txt"
        try:
            os.link(self.root / "source.txt", alias)
        except OSError as exc:
            self.skipTest("Hardlink not available: " + type(exc).__name__)
        with patch.object(documents, "_read") as read, self.assertRaisesRegex(ContractError, "alias"):
            self.build()
        read.assert_not_called()

    def test_material_reparse_point_rejected_before_content_read(self):
        from types import SimpleNamespace
        original = Path.lstat
        target = self.root / "dependency.bin"
        def changed(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path.name == target.name:
                return SimpleNamespace(st_mode=info.st_mode, st_nlink=info.st_nlink,
                                       st_file_attributes=1024)
            return info
        with patch.object(Path, "lstat", changed), patch.object(documents, "_read") as read:
            with self.assertRaisesRegex(ContractError, "reparse_point"):
                self.build()
            read.assert_not_called()

    def test_change_during_guarded_read_is_rejected(self):
        from types import SimpleNamespace
        original = documents.os.fstat
        calls = []
        def changed(fd):
            info = original(fd)
            calls.append(fd)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                                   st_mtime_ns=info.st_mtime_ns + (1 if len(calls) == 2 else 0))
        with patch.object(documents.os, "fstat", side_effect=changed):
            with self.assertRaisesRegex(ContractError, "replaced_during_read"):
                self.build()
        self.assertFalse((self.root / "pack").exists())

    def test_case_root_cannot_be_code_or_different_root(self):
        for case_root in (str(self.root.parent), str(Path(documents.__file__).resolve().parent.parent)):
            admission = {**self.admission, "case_root": case_root}
            with self.subTest(case_root=case_root), patch.object(documents, "_read") as read:
                with self.assertRaisesRegex(ContractError, "case_root"):
                    self.build(admission)
                read.assert_not_called()

    def test_pdf_process_is_not_implicitly_authorized(self):
        with patch.object(documents.subprocess, "run") as run, patch.object(documents, "_read") as read:
            with self.assertRaisesRegex(ContractError, "authorized_case_pdf_not_supported"):
                self.build(pdf_tool="soffice.exe")
            run.assert_not_called()
            read.assert_not_called()

    def test_direct_resolver_also_requires_actual_admission(self):
        with self.assertRaises(ContractError):
            documents.resolve_document(self.root, self.spec)
        blocks, images = documents.resolve_document(self.root, self.spec, admission=self.admission)
        self.assertEqual(1, len(blocks))
        self.assertEqual([], images)

    def test_permissions_changed_after_build_cannot_borrow_manifest(self):
        self.build()
        changed = copy.deepcopy(self.admission)
        changed["permissions"][0]["authority_evidence"] = "another-synthetic-authority-record"
        with self.assertRaisesRegex(ContractError, "document_admission_binding_changed"):
            documents.verify(self.root, self.spec, "pack", admission=changed)


if __name__ == "__main__":
    unittest.main()
