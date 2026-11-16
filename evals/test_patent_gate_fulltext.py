"""冻结完整合成稿的API、强制门禁、真实CLI及DOCX验收；不调用模型或网络。"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from tools import documents, patent_gate
from tools.core import ContractError


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "patent_gate"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CASES = {
    "cn": {
        "candidate": "cn-candidate.txt",
        "candidate_sha256": "162acd11a12d2c2b56b629d851321432edaf3fc7f49748671ec88a780eb57478",
        "source_sha256": "b6af7e2145aa1113d2514e64715f620280b5446b738a02012ebe06bab940f803",
        "historical_snapshot_sha256": "829a806a40781552bf3aad9292474fb0bde1f1bb069734c7eb4dcd751aafe4c3",
    },
    "mechanical": {
        "candidate": "mechanical-candidate.md",
        "candidate_sha256": "e96d04397b15daa51e1fbc416fbc2088c5eaceedca875655692a2b1330b8e628",
        "source_sha256": "4b86a843ad67b57f15cb207dda06cb54860ccfec51d437e93efb0a6f9bb048f6",
        "historical_snapshot_sha256": "361063ed7141f630c074f4a70cc60e2b649624514a71c85ebb64ff8483533cd4",
    },
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_case(key):
    payload = json.loads((FIXTURES / (key + "-source.json")).read_text(encoding="utf-8"))
    raw = (FIXTURES / CASES[key]["candidate"]).read_bytes()
    return raw, payload


def variants(key, text):
    payload = json.loads((FIXTURES / "variants.json").read_text(encoding="utf-8"))
    for variant in payload[key]:
        before = variant["before"]
        count = text.count(before)
        if count == 0 or "occurrences" in variant and count != variant["occurrences"]:
            raise AssertionError("mutation_anchor_not_exact: " + key + "/" + variant["name"])
        changed = text.replace(before, variant["after"])
        if changed == text:
            raise AssertionError("mutation_did_not_change_body: " + variant["name"])
        yield variant["name"], changed.encode("utf-8")


def docx_text(path):
    with zipfile.ZipFile(path) as archive:
        tree = ET.fromstring(archive.read("word/document.xml"))
    parts = []
    for paragraph in tree.findall("./" + W + "body/" + W + "p"):
        parts.append("".join(node.text or "" if node.tag == W + "t" else
                             "\n" if node.tag == W + "br" else "\t" if node.tag == W + "tab" else ""
                             for node in paragraph.iter()))
    return "\n".join(parts)


def diagnostic(report):
    return json.dumps({"status": report.get("status"), "issues": report.get("issues", [])[:6]},
                      ensure_ascii=False)


class PatentFullTextFixtureTests(unittest.TestCase):
    def test_frozen_candidates_and_source_text_match_recovered_hashes(self):
        for key, expected in CASES.items():
            with self.subTest(case=key):
                raw, payload = load_case(key)
                self.assertEqual(expected["candidate_sha256"], sha(raw))
                self.assertEqual(expected["candidate_sha256"], payload["provenance"]["candidate_sha256"])
                self.assertEqual("synthetic", payload["sensitivity"])
                self.assertEqual(1, len(payload["documents"]))
                source = payload["documents"][0]
                self.assertEqual("original", source["role"])
                self.assertEqual(expected["source_sha256"], source["sha256"])
                self.assertEqual(source["sha256"], sha(source["text"].encode("utf-8")))
                material = re.split(r"请(?:直接)?交", payload["provenance"]["task_text"], maxsplit=1)[0]
                self.assertEqual(material, source["text"])
                self.assertTrue(payload["provenance"]["full_technical_material_preserved"])
                self.assertFalse(payload["provenance"]["rewritten"])
                self.assertFalse(payload["provenance"]["natural_language_verified"])
                self.assertEqual("not_performed", payload["provenance"]["source_authentication"])
                self.assertEqual("not_performed", payload["provenance"]["professional_review"])

    def test_complete_historical_bad_snapshots_are_preserved(self):
        for key, expected in CASES.items():
            with self.subTest(case=key):
                raw = (FIXTURES / (key + "-historical-bad.md")).read_bytes()
                self.assertEqual(expected["historical_snapshot_sha256"], sha(raw))
                self.assertIn("##", raw.decode("utf-8"))
                self.assertIn("内部", raw.decode("utf-8"))

    def test_unknowns_and_original_single_structure_scope_are_not_removed(self):
        cn = load_case("cn")[1]["documents"][0]["text"]
        mechanical = load_case("mechanical")[1]["documents"][0]["text"]
        for unknown in ("中间区间与等号处的行为未给出", "等待确认时的既有物理阀位未给出",
                        "L、H均未给具体数值", "未提供实验或现有专利"):
            self.assertIn(unknown, cn)
        self.assertTrue(mechanical.startswith("原创合成夹具仅有这一种结构："))
        self.assertIn("没有尺寸、公差、弹簧或防丢结构，也没有其他方案", mechanical)
        self.assertNotIn("同一方案", cn + mechanical)

    def test_cn_missing_second_dependent_is_not_promoted_to_quantity_complete(self):
        raw, payload = load_case("cn")
        claims = re.findall(r"(?m)^(\d+)\.\s*(.+)$", raw.decode("utf-8"))
        self.assertEqual(["1", "2"], [number for number, _ in claims])
        self.assertEqual(1, sum("根据权利要求" in body for _, body in claims))
        self.assertIn("两条有支持的从属项", payload["provenance"]["task_text"])
        self.assertEqual({"independent": 1, "dependent": 1, "requested_dependent": 2},
                         payload["provenance"]["claim_count"])
        self.assertEqual("not_met_no_unsupported_second_dependent_created",
                         payload["provenance"]["quantity_result"])

    def test_all_adversarial_variants_change_real_full_text(self):
        for key in CASES:
            raw = load_case(key)[0]
            changed = list(variants(key, raw.decode("utf-8")))
            self.assertGreaterEqual(len(changed), 4)
            self.assertEqual(len(changed), len({name for name, _ in changed}))
            for name, body in changed:
                with self.subTest(case=key, variant=name):
                    self.assertNotEqual(raw, body)
                    self.assertIn("具体实施方式", body.decode("utf-8"))
                    self.assertIn("摘要", body.decode("utf-8"))


class PatentFullTextAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dyz-patent-fulltext-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def inputs(self, label, raw, sources):
        root = self.root / label
        root.mkdir()
        (root / "manuscript.txt").write_bytes(raw)
        (root / "sources.json").write_bytes((json.dumps({"sensitivity": "synthetic", "documents": sources},
            ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        return root

    def cli(self, root):
        run = subprocess.run([sys.executable, "-B", "-m", "tools.patent_gate", "--synthetic",
            "--root", str(root), "--manuscript", "manuscript.txt", "--sources", "sources.json",
            "--report", "cli-report.json", "--deliver", "accepted.txt"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=20)
        self.assertTrue((root / "cli-report.json").is_file(), run.stderr)
        report = json.loads((root / "cli-report.json").read_text(encoding="utf-8"))
        return run, report

    def word_spec(self, root, raw, sources):
        text = raw.decode("utf-8")
        # 行范围装配会省略文件结尾换行；额外空行和不入稿哨兵保全原稿末尾字符。
        carrier = raw + b"\nSYNTHETIC_INTERNAL_CARRIER_END"
        (root / "word-carrier.txt").write_bytes(carrier)
        line_count = text.count("\n") + 1
        self.assertEqual(text, "\n".join(carrier.decode("utf-8").splitlines()[:line_count]))
        return {"sensitivity": "synthetic", "business": "patent", "document_id": "FrozenFullText",
            "version": "1", "delivery_stage": "final", "sources": [{"id": "SRC",
            "path": "word-carrier.txt", "sha256": sha(carrier)}], "blocks": [{"id": "manuscript",
            "source_id": "SRC", "start_line": 1, "end_line": line_count,
            "kind": "paragraph", "audience": "body"}], "figures": [], "final_text_sources": sources}

    def assert_unverified_boundaries(self, report):
        self.assertFalse(report["natural_language_verified"])
        self.assertEqual("not_performed", report["professional_review"])
        self.assertEqual("not_performed", report["external_action"])

    def assert_checked_across_exits(self, key):
        raw, payload = load_case(key)
        text = raw.decode("utf-8")
        sources = payload["documents"]
        originals = copy.deepcopy(sources)
        root = self.inputs(key, raw, sources)
        api = patent_gate.audit_final_text({"manuscript": text}, sources)
        with self.subTest(boundary="API"):
            self.assertEqual("checked", api["status"], diagnostic(api))
            self.assertEqual([], api["issues"])
            self.assert_unverified_boundaries(api)
        with self.subTest(boundary="require_final_text"):
            required = patent_gate.require_final_text({"manuscript": text}, sources)
            self.assertEqual("checked", required["status"])
            self.assertEqual(api["input_binding"], required["input_binding"])
        with self.subTest(boundary="CLI"):
            run, cli = self.cli(root)
            self.assertEqual(0, run.returncode, diagnostic(cli))
            self.assertEqual("checked", cli["status"], diagnostic(cli))
            self.assertEqual(api["input_binding"], cli["input_binding"])
            self.assertEqual(raw, (root / "accepted.txt").read_bytes())
            self.assert_unverified_boundaries(cli)
        with self.subTest(boundary="Word"):
            spec = self.word_spec(root, raw, sources)
            manifest = documents.build(root, spec, "word-final", synthetic=True)
            report = json.loads((root / "word-final/internal/final-text-gate.json").read_text(encoding="utf-8"))
            self.assertEqual("checked", report["status"], diagnostic(report))
            self.assertEqual("checked", manifest["final_text_gate"]["status"])
            self.assertEqual(api["input_binding"], report["input_binding"])
            self.assertEqual(text, docx_text(root / "word-final/body/document.docx"))
            documents.verify(root, spec, "word-final", synthetic=True)
            self.assert_unverified_boundaries(report)
        self.assertEqual(raw, (root / "manuscript.txt").read_bytes())
        self.assertEqual(originals, sources)
        self.assertEqual(CASES[key]["candidate_sha256"], sha((FIXTURES / CASES[key]["candidate"]).read_bytes()))

    def assert_blocked_across_exits(self, label, raw, sources):
        text = raw.decode("utf-8")
        root = self.inputs(label, raw, sources)
        api = patent_gate.audit_final_text({"manuscript": text}, sources)
        with self.subTest(boundary="API"):
            self.assertEqual("blocked", api["status"], diagnostic(api))
            self.assertTrue(api["issues"])
        with self.subTest(boundary="require_final_text"):
            with self.assertRaisesRegex(ContractError, "^final_text_gate_blocked$") as raised:
                patent_gate.require_final_text({"manuscript": text}, sources)
            self.assertEqual("blocked", raised.exception.report["status"])
            self.assertEqual(api["input_binding"], raised.exception.report["input_binding"])
        with self.subTest(boundary="CLI"):
            run, cli = self.cli(root)
            self.assertEqual(2, run.returncode, diagnostic(cli))
            self.assertEqual("blocked", cli["status"], diagnostic(cli))
            self.assertEqual(api["input_binding"], cli["input_binding"])
            self.assertFalse((root / "accepted.txt").exists())
        with self.subTest(boundary="Word"):
            spec = self.word_spec(root, raw, sources)
            with self.assertRaisesRegex(ContractError, "^final_text_gate_blocked$") as raised:
                documents.build(root, spec, "word-final", synthetic=True)
            self.assertEqual("blocked", raised.exception.report["status"])
            self.assertEqual(api["input_binding"], raised.exception.report["input_binding"])
            self.assertFalse((root / "word-final").exists())
        self.assertEqual(raw, (root / "manuscript.txt").read_bytes())
        self.assertFalse((root / "accepted.txt").exists())
        self.assertFalse((root / "word-final").exists())

    def test_frozen_cn_reference_is_checked_at_every_exit(self):
        self.assert_checked_across_exits("cn")

    def test_frozen_mechanical_reference_is_checked_at_every_exit(self):
        self.assert_checked_across_exits("mechanical")

    def test_cn_full_text_variants_are_refused_before_delivery(self):
        raw, payload = load_case("cn")
        for name, body in variants("cn", raw.decode("utf-8")):
            with self.subTest(variant=name):
                self.assert_blocked_across_exits("cn-" + name, body, payload["documents"])

    def test_mechanical_full_text_variants_are_refused_before_delivery(self):
        raw, payload = load_case("mechanical")
        for name, body in variants("mechanical", raw.decode("utf-8")):
            with self.subTest(variant=name):
                self.assert_blocked_across_exits("mechanical-" + name, body, payload["documents"])

    def test_explicit_word_heading_blocks_keep_technical_titles_checked(self):
        raw, payload = load_case("mechanical")
        root = self.inputs("word-headings", raw, payload["documents"])
        text = raw.decode("utf-8")
        spec = self.word_spec(root, raw, payload["documents"])
        spec["blocks"] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line:
                continue
            heading = line.startswith("#")
            spec["blocks"].append({"id": "B" + str(line_number), "source_id": "SRC",
                "start_line": line_number, "end_line": line_number,
                "kind": "heading2" if line.startswith("##") else "heading1" if heading else "paragraph",
                "audience": "body"})
        # 装配器保留来源文字；使用独立、无Markdown符号的同内容标题载体。
        lines = [re.sub(r"^#{1,6}\s+", "", line) for line in text.splitlines()]
        carrier = ("\n".join(lines) + "\n").encode("utf-8")
        (root / "heading-carrier.txt").write_bytes(carrier)
        spec["sources"] = [{"id": "SRC", "path": "heading-carrier.txt", "sha256": sha(carrier)}]
        documents.build(root, spec, "word-split", synthetic=True)
        documents.verify(root, spec, "word-split", synthetic=True)
        self.assertEqual("\n".join(line for line in lines if line), docx_text(root / "word-split/body/document.docx"))
        changed = carrier.decode("utf-8").replace("夹具\n", "故障时阀门自动关闭\n", 1).encode("utf-8")
        (root / "bad-heading.txt").write_bytes(changed)
        bad = copy.deepcopy(spec)
        bad["sources"] = [{"id": "SRC", "path": "bad-heading.txt", "sha256": sha(changed)}]
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            documents.build(root, bad, "word-bad-heading", synthetic=True)
        self.assertFalse((root / "word-bad-heading").exists())

    def test_complete_historical_bad_outputs_are_refused_before_delivery(self):
        for key in CASES:
            with self.subTest(case=key):
                payload = load_case(key)[1]
                raw = (FIXTURES / (key + "-historical-bad.md")).read_bytes()
                self.assert_blocked_across_exits(key + "-historical", raw, payload["documents"])

    def test_mechanical_combination_cannot_rely_on_ordinary_cooccurrence(self):
        raw, payload = load_case("mechanical")
        sources = copy.deepcopy(payload["documents"])
        sources[0]["text"] = sources[0]["text"].replace("原创合成夹具仅有这一种结构：", "", 1)
        sources[0]["sha256"] = sha(sources[0]["text"].encode("utf-8"))
        self.assert_blocked_across_exits("mechanical-without-combination-scope", raw, sources)


if __name__ == "__main__":
    unittest.main()
