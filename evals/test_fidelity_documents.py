"""最终文件消费者必须核当前正文，不能只验证独立的正确示范。"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import struct
import zlib

from tools import documents
from tools.core import ContractError, canonical_bytes, digest, sha256_bytes
from evals.test_fidelity import example, citation, document


class FidelityDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dyz-fidelity-document-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.review = example()
        candidate = self.review["documents"][1]
        raw = candidate["text"].encode("utf-8")
        (self.root / "body.md").write_bytes(raw)
        self.spec = {"sensitivity": "synthetic", "document_id": "BoundDraft", "version": "1", "business": "patent",
            "sources": [{"id": "D", "path": "body.md", "sha256": sha256_bytes(raw)}],
            "blocks": [{"id": "P1", "source_id": "D", "kind": "paragraph", "audience": "body",
                        "start_line": 1, "end_line": 1}],
            "fidelity": {"payload": self.review, "blocks": {"P1": citation(candidate)}}}

    def test_bound_draft_exports_and_rechecks_actual_docx(self):
        result = documents.build(self.root, self.spec, "pack", synthetic=True)
        self.assertEqual("checked", result["fidelity"]["status"])
        self.assertEqual("not_performed", result["professional_review"])
        self.assertTrue((self.root / "pack/internal/fidelity-review.json").is_file())
        verified = documents.verify(self.root, self.spec, "pack", synthetic=True)
        self.assertEqual(result["fidelity"], verified["fidelity"])

    def test_wrong_direction_blocks_before_output_directory_creation(self):
        self.review["assertions"][0]["formula"] = {"implies": ["permission", "release"]}
        with self.assertRaisesRegex(ContractError, "document_fidelity_blocked"):
            documents.build(self.root, self.spec, "pack", synthetic=True)
        self.assertFalse((self.root / "pack").exists())

    def test_changed_actual_text_cannot_borrow_old_correct_audit(self):
        raw = "取得许可即自动发布。".encode("utf-8")
        (self.root / "body.md").write_bytes(raw)
        self.spec["sources"][0]["sha256"] = sha256_bytes(raw)
        with self.assertRaisesRegex(ContractError, "document_fidelity_blocked"):
            documents.build(self.root, self.spec, "pack", synthetic=True)
        self.assertFalse((self.root / "pack").exists())

    def test_every_actual_body_block_requires_its_own_binding(self):
        self.spec["blocks"].append({**self.spec["blocks"][0], "id": "P2"})
        with self.assertRaisesRegex(ContractError, "artifact_binding_members_mismatch"):
            documents.build(self.root, self.spec, "pack", synthetic=True)

    def test_actual_figure_cannot_bypass_fidelity_bindings(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB',1,1,8,2,0,0,0))
        png += chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b'')
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><text x="1" y="12">A</text></svg>'
        (self.root/'figure.png').write_bytes(png);(self.root/'figure.svg').write_bytes(svg)
        p = {'path':'figure.png','sha256':sha256_bytes(png)}
        s = {'path':'figure.svg','sha256':sha256_bytes(svg)}
        self.spec['figures'] = [{'id':'Fig1','png':p,'svg':s,'render_binding':digest({'svg':s['sha256'],'png':p['sha256']})}]
        with self.assertRaisesRegex(ContractError, "artifact_binding_members_mismatch"):
            documents.build(self.root, self.spec, "pack", synthetic=True)
        self.assertFalse((self.root/'pack').exists())

    def test_binding_to_original_instead_of_actual_candidate_is_rejected(self):
        self.spec["fidelity"]["blocks"]["P1"] = citation(self.review["documents"][0])
        with self.assertRaisesRegex(ContractError, "artifact_candidate_required"):
            documents.build(self.root, self.spec, "pack", synthetic=True)

    def test_fidelity_report_tampering_is_rejected_even_if_manifest_hash_is_rewritten(self):
        documents.build(self.root, self.spec, "pack", synthetic=True)
        changed = canonical_bytes({"status": "checked", "professional_review": "passed"}) + b"\n"
        (self.root / "pack/internal/fidelity-review.json").write_bytes(changed)
        path = self.root / "pack/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        row = next(x for x in manifest["files"] if x["path"] == "internal/fidelity-review.json")
        row.update(sha256=sha256_bytes(changed), bytes=len(changed))
        path.write_bytes(canonical_bytes(manifest) + b"\n")
        with self.assertRaisesRegex(ContractError, "document_fidelity_report_changed"):
            documents.verify(self.root, self.spec, "pack", synthetic=True)

    def test_unperformed_check_cannot_be_added_to_legacy_manifest(self):
        del self.spec["fidelity"]
        documents.build(self.root, self.spec, "pack", synthetic=True)
        path = self.root / "pack/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8")); manifest["fidelity"] = {"status": "checked"}
        path.write_bytes(canonical_bytes(manifest) + b"\n")
        with self.assertRaisesRegex(ContractError, "document_fidelity_not_performed"):
            documents.verify(self.root, self.spec, "pack", synthetic=True)

    def test_manifest_cannot_claim_unperformed_review_or_external_action(self):
        documents.build(self.root, self.spec, "pack", synthetic=True)
        path = self.root / "pack/manifest.json"
        initial = json.loads(path.read_text(encoding="utf-8"))
        for key, value in [("status", "checked"), ("professional_review", "passed"),
                           ("visual_review", "passed"), ("external_action", "performed")]:
            with self.subTest(field=key):
                changed = copy.deepcopy(initial);changed[key] = value
                path.write_bytes(canonical_bytes(changed) + b"\n")
                with self.assertRaisesRegex(ContractError, "document_manifest_state_changed"):
                    documents.verify(self.root, self.spec, "pack", synthetic=True)
        path.write_bytes(canonical_bytes(initial) + b"\n")

    def test_internal_analysis_stays_outside_body_docx(self):
        self.review["documents"].append(document("N", "internal", "私审：参数原文尚待核验。"))
        documents.build(self.root, self.spec, "pack", synthetic=True)
        with zipfile.ZipFile(self.root / "pack/body/document.docx") as package:
            self.assertNotIn("私审".encode("utf-8"), package.read("word/document.xml"))


if __name__ == "__main__":
    unittest.main()
