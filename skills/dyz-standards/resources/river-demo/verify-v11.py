"""Original synthetic River1.1 development checks; no service, persistence or approval.

Reuses model.py for frozen single inputs and for actual-state sequential calls.
Only prints JSON. Optional corpus is still a developer-owned synthetic fixture.
Repository LICENSE applies; no third-party standard text or implementation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def raw_input(item):
    return bytes.fromhex(item["body_hex"]) if "body_hex" in item else item["body_text"].encode("utf-8")


def execute(path):
    base = Path(__file__).resolve().parent
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if corpus["receiver_version"] != "1.1" or corpus["count"] != len(corpus["vectors"]):
        raise ValueError("v11_corpus_identity_invalid")
    for name in ("model.py", "requirements.json"):
        if hashlib.sha256((base / name).read_bytes()).hexdigest() != corpus["source_bindings"][name]:
            raise ValueError("source_binding_changed")
    ids = [item["id"] for item in corpus["vectors"]]
    if len(ids) != len(set(ids)) or any(x["receiver_version"] != "1.1" for x in corpus["vectors"]):
        raise ValueError("v11_vectors_invalid")
    if any(not check["vector_ids"] or not set(check["vector_ids"]).issubset(ids) for check in corpus["checks"]):
        raise ValueError("v11_check_targets_invalid")
    start = time.monotonic()
    process = subprocess.run([sys.executable, "-E", "-s", "-S", str(base / "model.py"), str(path)],
                             capture_output=True, text=True, encoding="utf-8")
    if process.returncode not in (0, 1):
        raise ValueError("single_input_runner_failed")
    singles = json.loads(process.stdout)
    if [item["id"] for item in singles["results"]] != ids:
        raise ValueError("single_input_results_incomplete")
    spec = importlib.util.spec_from_file_location("river_v11_checked_model", base / "model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sequences = []
    for scenario in corpus["sequences"]:
        state = copy.deepcopy(scenario["initial_state"])
        original_initial = copy.deepcopy(scenario["initial_state"])
        steps = []
        for number, item in enumerate(scenario["steps"], 1):
            raw = raw_input(item)
            before = copy.deepcopy(state)
            actual = module.receive(raw, "1.1", state)
            unchanged = before == state
            passed = actual == item["expected"] and unchanged
            steps.append({"step": number, "actual_input_state": before,
                          "input_bytes": len(raw), "input_sha256": hashlib.sha256(raw).hexdigest(),
                          "expected": item["expected"], "actual": actual,
                          "caller_state_unchanged": unchanged, "status": "passed" if passed else "failed"})
            # Carry the actual returned state, even after a mismatch; never reset from expected.
            state = actual["state"]
        unchanged = scenario["initial_state"] == original_initial
        sequences.append({"id": scenario["id"], "requirements": scenario["requirements"],
                          "steps": steps, "initial_fixture_unchanged": unchanged,
                          "status": "passed" if unchanged and all(x["status"] == "passed" for x in steps) else "failed"})
    passed_ids = {x["id"] for x in singles["results"] if x["status"] == "passed"}
    checks = [{**c, "status": "observed_as_expected" if set(c["vector_ids"]).issubset(passed_ids) else "failed"}
              for c in corpus["checks"]]
    failed_sequences = sum(s["status"] != "passed" for s in sequences)
    sources = []
    for source in [Path(__file__), base / "model.py", base / "requirements.json", path]:
        sources.append({"name": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "bytes": source.stat().st_size})
    singles.pop("sources")
    return {"kind": "author_finite_v11_vectors_and_actual_state_sequences", "sources": sources,
            "single_inputs": singles, "checks": checks, "sequences": sequences,
            "summary": {"vectors": len(ids), "vectors_passed": singles["passed"], "vectors_failed": singles["failed"],
                        "check_groups": len(checks), "scenario_count": len(sequences),
                        "scenarios_passed": len(sequences)-failed_sequences, "scenarios_failed": failed_sequences,
                        "sequence_steps": sum(len(s["steps"]) for s in sequences), "skipped": 0},
            "wall_seconds": round(time.monotonic()-start, 6),
            "status": "passed_finite_development_checks" if singles["failed"] == failed_sequences == 0 else "failed",
            "limits": corpus["unverified"] + ["Check groups are author-selected finite observations, not exhaustive coverage, held-out or professional acceptance."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", nargs="?", type=Path, default=Path(__file__).resolve().with_name("v11-boundary-vectors.json"))
    args = parser.parse_args()
    try:
        report = execute(args.corpus.resolve())
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed_finite_development_checks" else 1


if __name__ == "__main__":
    raise SystemExit(main())
