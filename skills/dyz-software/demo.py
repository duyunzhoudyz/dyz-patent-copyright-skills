"""完整软件材料合成演示；只写临时目录，退出时删除，无外部调用。"""

import copy
import json
import tempfile
from pathlib import Path

from tools.software import run


CONTEXT = {
    "environment": {}, "sensitivity": "synthetic", "purpose": "synthetic_demo",
    "now": "2026-10-31T10:00:00Z",
    "permissions": [{"action": "local_read", "purpose": "synthetic_demo",
                     "recipient": "local_tool", "decision": "allow",
                     "authority_evidence": "synthetic-consent",
                     "valid_from": "2026-01-01T00:00:00Z",
                     "valid_until": "2027-01-01T00:00:00Z"}],
}
SCOPE_INPUT = {
    "metadata": {
        "software_id": "demo", "name": "合成计数器", "version": "1.0",
        "runtime_environment": {"description": "Python 3.11 CLI", "evidence_id": "synthetic-env"},
        "completed_date": {"value": "2026-10-01", "evidence_id": "synthetic-date"},
        "published_date": {"value": "2026-10-02", "evidence_id": "synthetic-publication"},
    },
    "components": [{"id": "cli", "kind": "standalone", "version": "1.0", "origin": "own",
                    "claim": ["本版命令表达"], "exclusions": ["Python运行时"],
                    "subjects": [{"subject_id": "demo-owner", "basis": "合成合同",
                                  "evidence_id": "synthetic-contract"}]}],
}


def execute_demo() -> dict:
    """返回SW-01..08及两个SW-08分支的实际合成工件。"""
    outputs = {}

    def call(capability, **payload):
        output = run(capability, {"context": CONTEXT, **payload})
        outputs[capability] = output
        return output["artifacts"]

    scope = call("SW-01", **SCOPE_INPUT)
    rights = call("SW-07", scope=scope, rights=[{
        "component_id": "cli", "requested_decision": "claim",
        "evidence_ids": ["synthetic-contract"],
        "permissions": {"local_process": "allow", "deposit": "allow",
                        "public": "unknown", "cloud": "deny"},
    }])
    with tempfile.TemporaryDirectory(prefix="dyz-software-synthetic-") as directory:
        Path(directory, "counter.py").write_text(
            "def count(items):\n    return len(items)\nprint(count([1, 2]))\n",
            encoding="utf-8",
        )
        material = call("SW-02", scope=scope, rights_decisions=rights,
                        authorized_root=directory, inventory_complete=True,
                        files=[{"id": "f1", "path": "counter.py", "component_id": "cli",
                                "kind": "source", "include": True}],
                        pagination={"lines_per_page": 3, "wrap_columns": 12,
                                    "selection": "all", "basis": "合成分页，不是法律规则"})
        assert material["total_source_lines"] == 3
        assert material["selected_source_lines"] == 3
        call("SW-03", material=material, redactions=[], sensitive_literals=["count"])
        manual = call("SW-04", scope=scope, mode="CLI",
                      facts=[{"id": "f1", "text": "计算给定列表长度", "evidence_id": "synthetic-code"}],
                      operations=[{"id": "count", "input": "python counter.py",
                                   "expected_output": "2", "failure": "参数不合法时错误退出",
                                   "evidence_id": "synthetic-code"}], runtime_evidence=[])
        form = {**scope["metadata"], "total_source_lines": 3, "selected_source_lines": 3}
        call("SW-05", scope=scope, material=material, manual=manual, form=form,
             form_rule_evidence="synthetic-form-rule")
        changed = copy.deepcopy(SCOPE_INPUT)
        changed["metadata"]["version"] = "1.1"
        after = run("SW-01", {"context": CONTEXT, **changed})["artifacts"]
        call("SW-06", before=scope, after=after,
             event={"id": "correction1", "type": "correction", "evidence_id": "synthetic-notice",
                    "source_status": "synthetic"},
             notice_items=[{"id": "n1", "evidence_id": "synthetic-notice", "locator": "page1"}],
             responses=[{"notice_id": "n1", "basis_evidence": "synthetic-change",
                         "replacement_locator": "metadata.version"}],
             prior_reviews=[{"id": "r1", "binding": scope["binding"], "status": "recorded"}])
        call("SW-08", scope=scope, branch="adaptation", targets=[{
            "jurisdiction": "SYNTHETIC-REGION", "route": "registration",
            "requirements": [{"id": "deposit", "source_locator": "synthetic-rule:1",
                              "evidence_id": "synthetic-source"}],
        }])
        outputs["SW-08-adaptation"] = outputs.pop("SW-08")
        call("SW-08", scope=scope, branch="dispute", pairs=[{
            "id": "pair1", "classification": "expression",
            "left": {"version": "1.0", "text": "return len(items)",
                     "evidence_id": "synthetic-left", "locator": "counter.py:2"},
            "right": {"version": "other", "text": "return len(values)",
                      "evidence_id": "synthetic-right", "locator": "other.py:3"},
            "access_evidence": None, "origin_evidence": None,
        }])
    return outputs


if __name__ == "__main__":
    report = execute_demo()
    print(json.dumps({key: {"status": value["status"], "kind": value["artifacts"]["kind"],
                            "issues": [issue["code"] for issue in value["issues"]],
                            "external_action": value["external_action"]}
                      for key, value in report.items()}, ensure_ascii=False, indent=2))
