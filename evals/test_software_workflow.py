"""独立合成API的真实CLI纵向检查；测试操作者不是人类或专业签核人。"""

import argparse
import copy
import json
import platform
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import core
from tools.software_delivery import build_binding

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "outputs/software-upgrade-20261113/independent-workflow.json"
SOURCE = '''"""合成包裹分档接口，仅供本地工作流测试。"""
SOFTWARE_ID = "synthetic-parcel-bands"
VERSION = "2.4"


def dispatch(method, path, body):
    if method != "POST" or path != "/v2/parcels/classify":
        return 404, {"error": "route_not_found"}
    grams = body.get("grams")
    if type(grams) is not int or grams <= 0:
        return 400, {"error": "positive_integer_grams_required"}
    band = "light" if grams <= 500 else "standard"
    return 200, {"band": band, "grams": grams}
'''
SECRET_SENTINEL = "SYNTHETIC_PARCEL_PRIVATE_SENTINEL_73"

# 固定选择模拟独立的操作者输入，不把工具候选默认全选，也不代表真实用户确认。
SYNTHETIC_OPERATOR_CHOICES = {
    "software_id": "synthetic-parcel-bands",
    "name": "合成包裹分档接口",
    "version": "2.4",
    "completed_date": {"value": "2026-06-04", "evidence_id": "synthetic-parcel-date"},
    "runtime_environment": {
        "description": "Python 3.11；内存中的API分派函数，无网络监听器",
        "evidence_id": "synthetic-parcel-environment",
    },
}


class SoftwareWorkflowTests(unittest.TestCase):
    observation = None

    def setUp(self):
        started = time.perf_counter()
        self.observation = {
            "scenario": "synthetic_parcel_bands_api",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "platform": platform.system(),
            "python": platform.python_version(),
            "cli_interactions": [],
            "coverage": [],
            "synthetic_operator_confirmations": len(SYNTHETIC_OPERATOR_CHOICES),
            "real_human_confirmations": 0,
            "professional_review": "not_performed",
            "efficiency_comparison": "not_performed",
            "api_runtime": "not_executed_static_source_only",
            "gui_screenshots": "not_applicable_api",
            "pdf": "not_generated",
            "limitations": [
                "合成事实、证据和操作者选择，不认证真实身份、权属或专业质量。",
                "仅验证真实CLI与DOCX结构，不执行API、不提供运行成功证据。",
                "未启动PDF工具、浏览器、长期服务、外部模型或安装依赖。",
                "独立执行者的技术回归，不是独立专业验收或同条件效率比较。",
            ],
            "tool_sha256": {
                name: core.sha256_bytes((ROOT / "tools" / name).read_bytes())
                for name in ("cli.py", "software.py", "software_delivery.py",
                             "documents.py", "core.py")
            },
        }
        type(self).observation = self.observation
        self.addCleanup(lambda: self.observation.update(
            elapsed_seconds=round(time.perf_counter() - started, 6),
            cli_interaction_count=len(self.observation["cli_interactions"])))
        directory = tempfile.TemporaryDirectory(prefix="dyz-parcel-workflow-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "parcel_api.py").write_bytes(SOURCE.encode("utf-8"))
        self.request = {
            "scope_input": {
                "metadata": {**copy.deepcopy(SYNTHETIC_OPERATOR_CHOICES), "published_date": None},
                "components": [{
                    "id": "parcel_api", "kind": "library", "version": "2.4", "origin": "own",
                    "claim": ["合成测试设定的包裹重量分档分支表达"],
                    "exclusions": ["Python运行时及HTTP传输层"],
                    "subjects": [{"subject_id": "synthetic-parcel-owner",
                                  "basis": "仅测试用合成主体声明，不是真实权属认定",
                                  "evidence_id": "synthetic-parcel-owner-declaration"}],
                }],
            },
            "rights": [{
                "component_id": "parcel_api", "requested_decision": "claim",
                "evidence_ids": ["synthetic-parcel-material-permission"],
                "permissions": {"local_process": "allow", "deposit": "allow",
                                "public": "deny", "cloud": "deny"},
            }],
            "files": [{"id": "parcel_source", "path": "parcel_api.py",
                       "component_id": "parcel_api", "kind": "source", "include": True}],
            "inventory_complete": True,
            "pagination": {"lines_per_page": 50, "wrap_columns": 78,
                           "selection": "all", "basis": "synthetic-internal-layout-only"},
            "manual_input": {
                "mode": "API",
                "facts": [{"id": "classification", "evidence_id": "synthetic-parcel-source-review",
                           "text": "静态源码按500克阈值分档；未实测API运行或运输业务。"}],
                "operations": [{
                    "id": "classify_parcel", "input": 'POST /v2/parcels/classify，{"grams": 720}',
                    "expected_output": '200，{"band": "standard", "grams": 720}',
                    "failure": "非正整数重量预期400；其他方法或路径预期404；均未执行。",
                    "evidence_id": "synthetic-parcel-source-review",
                }],
                "runtime_evidence": [],
            },
            "form_rule_evidence": "synthetic-internal-form-not-official-rule",
        }
        self.options = {"selection": "all", "screenshots": [], "sensitive_literals": []}

    def authorize(self, stage, request, output, *, build=False):
        raw = core.canonical_bytes(request)
        request_name = stage + ".request.json"
        (self.root / request_name).write_bytes(raw)
        now = datetime.now(timezone.utc)
        permission = {
            "purpose": "synthetic_parcel_workflow", "recipient": "local_tool",
            "decision": "allow", "authority_evidence": "synthetic-local-test-permission",
            "valid_from": (now - timedelta(hours=1)).isoformat(),
            "valid_until": (now + timedelta(hours=1)).isoformat(),
        }
        authorization = {
            "kind": "software_local_authorization", "authorized_root": str(self.root),
            "context": {"sensitivity": "synthetic", "purpose": permission["purpose"],
                        "environment": {}, "permissions": [
                            {**permission, "action": action} for action in ("local_read", "local_write")]},
            "request": {"path": request_name, "sha256": core.sha256_bytes(raw)},
            "files": [{"path": "parcel_api.py", "sha256": core.sha256_bytes(
                (self.root / "parcel_api.py").read_bytes())}],
            "output": output,
        }
        authorization_raw = core.canonical_bytes(authorization)
        authorization_name = stage + ".authorization.json"
        (self.root / authorization_name).write_bytes(authorization_raw)
        return ["build-software" if build else "prepare-software", "--root", str(self.root),
                "--authorization", authorization_name, "--authorization-sha256",
                core.sha256_bytes(authorization_raw)]

    def invoke(self, stage, args, expected):
        started = time.perf_counter()
        process = subprocess.run([sys.executable, "-B", "-m", "tools", *args], cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        output_allowed = process.stdout in {"", "result_written\n", "software_documents_partial\n"}
        error_allowed = process.stderr in {"", "contract_rejected\n"}
        self.observation["cli_interactions"].append({
            "stage": stage, "command": args[0], "verify": "--verify" in args,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "returncode": process.returncode,
            "stdout": process.stdout.strip() if output_allowed else "unexpected_output_redacted",
            "stderr": process.stderr.strip() if error_allowed else "unexpected_output_redacted",
            "stdout_sha256": core.sha256_bytes(process.stdout.encode("utf-8")),
            "stderr_sha256": core.sha256_bytes(process.stderr.encode("utf-8")),
        })
        # 失败断言也不能把可能泄漏的原始stdout/stderr插进测试日志。
        combined = process.stdout + process.stderr
        self.assertFalse(any(value in combined for value in (
            SECRET_SENTINEL, str(self.root), "synthetic-parcel-bands", "/v2/parcels/classify")),
            "CLI leaked material or a private path; raw output intentionally omitted")
        self.assertTrue(output_allowed and error_allowed, "Unexpected CLI text; raw output omitted")
        self.assertEqual(process.returncode, expected)
        expected_out = "result_written\n" if expected == 0 else "software_documents_partial\n" if expected == 4 else ""
        self.assertTrue(process.stdout == expected_out, "Unexpected CLI stdout status")
        self.assertTrue(process.stderr == ("contract_rejected\n" if expected == 2 else ""),
                        "Unexpected CLI stderr status")

    def read_json(self, path):
        return json.loads((self.root / path).read_text(encoding="utf-8"))

    def prepare(self, stage, request):
        output = stage + ".json"
        self.invoke(stage, self.authorize(stage, request, output), 0)
        envelope = self.read_json(output)
        self.assertEqual(envelope["status"], "partial")
        self.assertEqual(envelope["professional_review"], "not_performed")
        self.assertEqual(envelope["official_status"], "not_asserted")
        self.assertEqual(envelope["external_action"], "not_performed")
        self.assertEqual(envelope["output_scope"], "internal_only_not_for_submission")
        return envelope["artifacts"]

    def package_hashes(self):
        target = self.root / "parcel-package"
        return {path.relative_to(target).as_posix(): core.sha256_bytes(path.read_bytes())
                for path in target.rglob("*") if path.is_file()}

    def test_independent_api_cli_chain_preserves_unknown_and_rejects_stale_evidence(self):
        declared = self.prepare("01-declarations", self.request)
        self.assertEqual(declared["scope"]["ownership"], "undetermined")
        self.assertEqual(declared["manual"]["verification"], "static_only")
        self.assertEqual(declared["manual"]["screenshots"], [])
        declared_rows = {row["field"]: row for row in declared["worksheet"]["rows"]}
        self.assertEqual(declared_rows["published_date"]["status"], "unknown")
        self.assertTrue(all(declared_rows[field]["status"] == "declared"
                            for field in SYNTHETIC_OPERATOR_CHOICES))
        self.assertTrue(all(not row["applied"] for row in declared_rows.values()))
        self.observation["coverage"].append("declarations_and_evidence_do_not_auto_confirm")

        candidates = []
        for field, value in SYNTHETIC_OPERATOR_CHOICES.items():
            source = ({"evidence_id": value["evidence_id"], "locator": "scope_input.metadata." + field}
                      if isinstance(value, dict) else
                      {"path": "parcel_api.py", "sha256": core.sha256_bytes(SOURCE.encode("utf-8")),
                       "locator": "L1-L3"})
            candidates.append({"field": field, "value": copy.deepcopy(value),
                               "status": "candidate", "sources": [source]})
        candidates.append({"field": "published_date", "value": None, "status": "unknown", "sources": []})
        candidate_request = {**self.request, "field_candidates": candidates}
        pending = self.prepare("02-candidates", candidate_request)
        self.assertTrue(all(not row["applied"] for row in pending["worksheet"]["rows"]))
        self.assertEqual(pending["form"], declared["form"])
        self.assertTrue(all(row["sources"] for row in pending["worksheet"]["rows"]
                            if row["field"] != "published_date"))
        self.observation["coverage"].append("file_hash_and_evidence_sources_remain_candidates")

        confirmations = []
        for row in pending["worksheet"]["rows"]:
            if row["field"] not in SYNTHETIC_OPERATOR_CHOICES:
                continue
            self.assertEqual(row["value"], SYNTHETIC_OPERATOR_CHOICES[row["field"]])
            confirmations.append({
                "candidate_digest": row["candidate_digest"],
                "input_binding": pending["worksheet"]["input_binding"], "status": "confirmed",
                "actor": "synthetic-parcel-operator", "role": "synthetic_fact_provider_not_professional",
                "evidence_id": "synthetic-explicit-field-choices-v1",
            })
        confirmed_request = {**candidate_request, "confirmations": confirmations}
        confirmed = self.prepare("03-explicit-synthetic-choices", confirmed_request)
        rows = {row["field"]: row for row in confirmed["worksheet"]["rows"]}
        self.assertEqual(len(confirmations), 5)
        for field in SYNTHETIC_OPERATOR_CHOICES:
            self.assertEqual(rows[field]["status"], "confirmed")
            self.assertTrue(rows[field]["applied"])
        self.assertEqual(rows["published_date"]["status"], "unknown")
        self.assertFalse(rows["published_date"]["applied"])
        self.assertIsNone(confirmed["form"]["published_date"])
        for name in ("scope", "rights", "source", "manual"):
            self.assertEqual(confirmed[name], pending[name])
        self.assertEqual(confirmed["scope"]["ownership"], "undetermined")
        self.assertEqual(confirmed["manual"]["verification"], "static_only")
        self.observation["coverage"].append("explicit_synthetic_choices_only_confirm_known_form_fields")

        build_request = {**confirmed_request, "delivery": self.options}
        build_args = self.authorize("04-build", build_request, "parcel-package", build=True)
        self.invoke("04-build", build_args, 4)
        manifest = self.read_json("parcel-package/manifest.json")
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(manifest["pdf"], "not_generated")
        self.assertEqual(manifest["physical_review"], {})
        self.assertTrue({"pdf_not_generated", "physical_layout_not_checked", "runtime_not_verified",
                         "field_confirmation_pending", "published_date_unknown"} <= set(manifest["issues"]))
        for key in ("visual_review", "professional_review", "identity_verification", "external_action"):
            self.assertEqual(manifest[key], "not_performed")
        self.assertEqual(manifest["official_status"], "not_asserted")
        self.assertEqual(manifest["output_scope"], "internal_only_not_for_submission")
        self.assertEqual(self.read_json("parcel-package/internal/preparation.json"), confirmed)
        mapping = self.read_json("parcel-package/internal/source-map.json")
        self.assertEqual(mapping["source"]["source_lines"], len(SOURCE.splitlines()))
        self.assertEqual(confirmed["source"]["selected_source_lines"], len(SOURCE.splitlines()))
        for kind in ("source", "manual", "worksheet"):
            docx = self.root / "parcel-package" / "body" / (kind + ".docx")
            with zipfile.ZipFile(docx) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn("[Content_Types].xml", archive.namelist())
                document = ET.fromstring(archive.read("word/document.xml"))
                text = "".join(document.itertext())
                header = ET.fromstring(archive.read("word/header1.xml"))
                self.assertIn("合成包裹分档接口 2.4", "".join(header.itertext()))
                if kind == "manual":
                    self.assertIn("/v2/parcels/classify", text)
                    self.assertIn("不是已执行结果", text)
            self.assertTrue(docx.with_suffix(".txt").is_file())
        self.assertFalse(list((self.root / "parcel-package").rglob("*.pdf")))
        self.observation["delivery"] = {key: manifest[key] for key in (
            "status", "pdf", "issues", "professional_review", "official_status", "output_scope")}
        original_package = self.package_hashes()
        self.invoke("05-verify-original", build_args + ["--verify"], 4)
        self.assertEqual(self.package_hashes(), original_package)
        self.observation["coverage"].append("real_docx_build_and_cli_verify_remain_partial_without_pdf")

        changed_request = copy.deepcopy(confirmed_request)
        changed_request["scope_input"]["metadata"]["completed_date"]["value"] = "2026-06-05"
        changed_request["previous_preparation"] = confirmed
        changed = self.prepare("06-changed-date-stale-confirmations", changed_request)
        self.assertNotEqual(changed["worksheet"]["input_binding"], confirmed["worksheet"]["input_binding"])
        for row in changed["worksheet"]["rows"]:
            self.assertFalse(row["applied"])
            if row["field"] in SYNTHETIC_OPERATOR_CHOICES:
                self.assertEqual(row["reason"], "field_confirmation_stale")
        self.assertEqual(changed["form"]["completed_date"]["value"], "2026-06-05")
        self.assertEqual(changed["supersedes"], confirmed["binding"])
        self.assertIn(confirmed["binding"], changed["invalidated"])
        self.assertNotEqual(changed["source"]["binding"], confirmed["source"]["binding"])
        self.assertEqual(build_binding(changed), build_binding(confirmed))
        self.assertEqual(build_binding(changed), core.digest([
            {"file_id": "parcel_source", "sha256": core.sha256_bytes(SOURCE.encode("utf-8"))}]))
        self.assertNotIn("screenshots", {row["artifact"] for row in changed["changes"]})
        self.observation["coverage"].append("date_change_invalidates_confirmation_not_source_byte_build_binding")
        stale_args = self.authorize("07-verify-stale-package", {**changed_request, "delivery": self.options},
                                    "parcel-package", build=True)
        self.invoke("07-verify-stale-package", stale_args + ["--verify"], 2)
        self.assertEqual(self.package_hashes(), original_package)
        self.observation["coverage"].append("old_package_rejected_for_changed_facts_without_rewriting_history")

        secret_request = copy.deepcopy(build_request)
        secret_request["manual_input"]["facts"][0]["text"] += SECRET_SENTINEL
        secret_request["delivery"]["sensitive_literals"] = [SECRET_SENTINEL]
        secret_args = self.authorize("08-known-secret", secret_request, "secret-rejected-package", build=True)
        self.invoke("08-known-secret", secret_args, 2)
        self.assertFalse((self.root / "secret-rejected-package").exists())
        self.observation["coverage"].append("known_literal_rejected_before_output_and_absent_from_cli_logs")

        self.invoke("09-original-package-still-verifiable", build_args + ["--verify"], 4)
        self.assertEqual(self.package_hashes(), original_package)
        self.assertEqual((self.root / "parcel_api.py").read_bytes(), SOURCE.encode("utf-8"))
        (self.root / "parcel_api.py").write_bytes((SOURCE + "# 合成后续改动\n").encode("utf-8"))
        self.invoke("10-changed-source-old-authorization", build_args + ["--verify"], 2)
        self.assertEqual(self.package_hashes(), original_package)
        self.observation["coverage"].append("source_byte_change_rejects_old_authorization")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="仅将本轮观测写入获准的固定记录文件")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    previous_runs = []
    if args.record and REPORT.exists():
        previous = json.loads(REPORT.read_text(encoding="utf-8"))
        previous_runs = previous.pop("previous_runs", []) + [previous]
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SoftwareWorkflowTests)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    if args.record:
        record = {"kind": "synthetic_independent_cli_workflow_observation",
                  "command": "python -B -m evals.test_software_workflow --record -v",
                  "tests_run": result.testsRun, "failures": len(result.failures),
                  "errors": len(result.errors), "skipped": len(result.skipped),
                  "outcome": "passed" if result.wasSuccessful() else "failed",
                  "observation": SoftwareWorkflowTests.observation,
                  "previous_runs": previous_runs}
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        with REPORT.open("w" if previous_runs else "x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    sys.exit(0 if result.wasSuccessful() else 1)
