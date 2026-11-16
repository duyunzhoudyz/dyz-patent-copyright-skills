"""Original synthetic River protocol model; not a product or conformance service.

Run with Python 3.11 standard library. Reads local frozen requirements/vectors,
prints a JSON report, never starts a server or writes any file. The state in this
report is an in-memory test oracle, not a wire acknowledgement or durable store.
Repository LICENSE applies; no third-party standard implementation is included.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import re
import sys


class InvalidJSON(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidJSON("duplicate member")
        result[key] = value
    return result


def reject_number(token):
    raise InvalidJSON("only integer number tokens allowed")


def receive(raw: bytes, receiver_version: str, state: dict) -> dict:
    """Validate one batch, returning a separate state; no persistence/concurrency.

    Preconditions: receiver_version is 1.0 or 1.1; state contains only previously
    accepted synthetic batches. Caller-owned raw bytes and state are not mutated.
    """
    if receiver_version not in {"1.0", "1.1"}:
        raise ValueError("unsupported receiver configuration")

    def reject(reason):
        return {"status": "rejected", "reason": reason, "state": copy.deepcopy(state)}

    if not 1 <= len(raw) <= 1024:
        return reject("size")
    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            return reject("encoding")
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return reject("encoding")
    try:
        data = json.loads(text, object_pairs_hook=unique_object,
                          parse_float=reject_number, parse_constant=reject_number)
    except (ValueError, RecursionError):
        return reject("json")
    if not isinstance(data, dict) or set(data) != {"version", "batch", "records"}:
        return reject("shape")
    if data["version"] != receiver_version:
        return reject("version")
    batch = data["batch"]
    if not isinstance(batch, str) or re.fullmatch(r"[A-Z][A-Z0-9-]{0,15}", batch) is None:
        return reject("batch")
    rows = data["records"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4:
        return reject("records")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"seq", "value"}:
            return reject("field")
        seq, value = row["seq"], row["value"]
        if type(seq) is not int:
            return reject("field")
        if receiver_version == "1.1" and not 1 <= seq <= 999:
            return reject("field")
        if value is None and receiver_version == "1.1":
            continue
        if type(value) is not int or not 0 <= value <= 1000:
            return reject("field")
    if receiver_version == "1.0":
        if [row["seq"] for row in rows] != list(range(1, len(rows) + 1)):
            return reject("order")
    elif any(rows[i - 1]["seq"] >= rows[i]["seq"] for i in range(1, len(rows))):
        return reject("order")
    if batch in state:
        return reject("replay")
    new_state = copy.deepcopy(state)
    new_state[batch] = copy.deepcopy(rows)
    return {"status": "accepted", "reason": "accepted", "state": new_state}


def source_record(path):
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw)}


def main():
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vectors", nargs="?", type=Path, default=base / "vectors.json")
    args = parser.parse_args()
    requirements_path = base / "requirements.json"
    requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
    corpus = json.loads(args.vectors.read_text(encoding="utf-8"))
    results = []
    for vector in corpus["vectors"]:
        if vector["receiver_version"] not in requirements["versions"]:
            raise ValueError("vector receiver configuration not in given requirements")
        raw = (bytes.fromhex(vector["body_hex"]) if "body_hex" in vector
               else vector["body_text"].encode("utf-8"))
        original_state = copy.deepcopy(vector["initial_state"])
        actual = receive(raw, vector["receiver_version"], vector["initial_state"])
        unchanged = original_state == vector["initial_state"]
        passed = actual == vector["expected"] and unchanged
        results.append({"id": vector["id"], "receiver_version": vector["receiver_version"],
                        "requirements": vector["requirements"],
                        "input_bytes": len(raw), "input_sha256": hashlib.sha256(raw).hexdigest(),
                        "caller_state_unchanged": unchanged, "expected": vector["expected"],
                        "actual": actual, "status": "passed" if passed else "failed"})
    failed = sum(row["status"] == "failed" for row in results)
    report = {"fixture_id": "deepening-standards-d3", "kind": "finite_model_fixed_vector_run",
              "environment": {"python": sys.version, "executable": sys.executable,
                              "platform": platform.platform()},
              "sources": [source_record(Path(__file__)), source_record(requirements_path),
                          source_record(args.vectors)],
              "count": len(results), "passed": len(results) - failed, "failed": failed,
              "skipped": 0, "results": results,
              "limits": ["One in-memory serial model and fixed synthetic vectors only.",
                         "No real product interoperability, performance, durable transaction, professional or organization approval."]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
