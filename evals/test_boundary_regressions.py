"""独立审阅发现的共享信任边界回归；只使用临时合成数据。"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.cli import main
from tools.core import ContractError, VersionLedger, strict_json_loads

REPO = Path(__file__).resolve().parents[1]


class BoundaryRegressions(unittest.TestCase):
    def invoke(self, root, payload):
        source = Path(root, "input.json")
        source.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "tools", "run", "CORE-04", "--synthetic",
             "--root", str(root), "--input", "input.json", "--output", "out.json"],
            cwd=REPO, text=True, capture_output=True, check=False,
        )

    def test_cli_rejects_payload_root_outside_authorized_root_before_journal(self):
        with tempfile.TemporaryDirectory() as authorized, tempfile.TemporaryDirectory() as other:
            answer = self.invoke(authorized, {"root": other, "journal": "outside.sqlite",
                                             "operation": "status", "arguments": {"release_id": "none"}})
            self.assertFalse(Path(other, "outside.sqlite").exists())
            self.assertEqual(answer.returncode, 2)

    def test_cli_rejects_duplicate_keys_before_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = ('{"sensitivity":"confidential","sensitivity":"synthetic",'
                       '"root":' + json.dumps(directory) + ',"journal":"duplicate.sqlite",'
                       '"operation":"status","arguments":{"release_id":"none"}}')
            answer = self.invoke(directory, payload)
            self.assertFalse(Path(directory, "duplicate.sqlite").exists())
            self.assertEqual(answer.returncode, 2)

    def test_cli_rejects_nonfinite_json_before_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = ('{"root":' + json.dumps(directory) + ',"journal":"nan.sqlite",'
                       '"operation":"status","arguments":{"release_id":"none"},"unused":NaN}')
            answer = self.invoke(directory, payload)
            self.assertFalse(Path(directory, "nan.sqlite").exists())
            self.assertEqual(answer.returncode, 2)

    def ledger(self):
        ledger = VersionLedger()
        ledger.put("scope", {"version": "one"})
        ledger.put("source", {"version": "one"}, dependencies=["scope"])
        ledger.add_review("r", ["source"], reviewer={"actor_id": "synthetic-reviewer",
                          "actor_type": "machine", "authority_evidence": "synthetic"},
                          kind="machine", decision="accepted")
        return ledger

    def restore(self, state):
        return VersionLedger(state["records"], state["reviews"])

    def test_restored_payload_hash_mismatch_rejected(self):
        state = self.ledger().export()
        state["records"]["scope"][0]["payload"]["version"] = "two"
        with self.assertRaises(ContractError):
            self.restore(state)

    def test_restored_missing_dependency_rejected(self):
        state = self.ledger().export()
        del state["records"]["scope"]
        with self.assertRaises(ContractError):
            self.restore(state)

    def test_restored_forged_current_review_rejected(self):
        ledger = self.ledger()
        ledger.put("scope", {"version": "two"})
        state = ledger.export()
        state["reviews"][0]["status"] = "recorded"
        with self.assertRaises(ContractError):
            self.restore(state)

    def test_valid_stale_history_remains_loadable(self):
        ledger = self.ledger()
        ledger.put("scope", {"version": "two"})
        restored = self.restore(ledger.export())
        self.assertFalse(restored.is_current("source"))
        self.assertEqual(restored.reviews[0]["status"], "invalidated")
        self.assertEqual(len(restored.records["scope"]), 2)

    def test_history_version_and_old_hash_checked(self):
        ledger = self.ledger()
        ledger.put("scope", {"version": "two"})
        state = ledger.export()
        for field, value in (("version", 99), ("hash", "0" * 64)):
            changed = copy.deepcopy(state)
            changed["records"]["scope"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.restore(changed)

    def test_cli_rejects_software_authorized_root_outside(self):
        with tempfile.TemporaryDirectory() as authorized, tempfile.TemporaryDirectory() as other:
            source = Path(authorized, "input.json")
            source.write_text(json.dumps({"authorized_root": other}), encoding="utf-8")
            with patch("tools.cli.dispatch", return_value={"status": "checked"}) as dispatch:
                code = main(["run", "SW-02", "--synthetic", "--root", authorized,
                             "--input", "input.json", "--output", "out.json"])
            self.assertEqual(code, 2)
            dispatch.assert_not_called()
            self.assertFalse(Path(authorized, "out.json").exists())

    def test_cli_accepts_relative_nested_root_without_enlargement(self):
        with tempfile.TemporaryDirectory() as authorized:
            Path(authorized, "nested").mkdir()
            Path(authorized, "input.json").write_text('{"root":"nested"}', encoding="utf-8")
            with patch("tools.cli.dispatch", return_value={"status": "checked"}) as dispatch:
                code = main(["run", "CORE-04", "--synthetic", "--root", authorized,
                             "--input", "input.json", "--output", "out.json"])
            self.assertEqual(code, 0)
            self.assertEqual(dispatch.call_args.args[1]["root"], str(Path(authorized, "nested").resolve()))

    def test_nested_duplicate_and_exponent_overflow_rejected(self):
        for text in ('{"context":{"sensitivity":"public","sensitivity":"synthetic"}}',
                     '{"number":1e999}', '{"value":Infinity}', '{"value":-Infinity}'):
            with self.subTest(text=text), self.assertRaises(ContractError):
                strict_json_loads(text)

    def test_json_null_payload_roundtrip_is_preserved(self):
        ledger = VersionLedger()
        ledger.put("nullable", None)
        restored = self.restore(ledger.export())
        self.assertTrue(restored.is_current("nullable"))
        self.assertIsNone(restored.records["nullable"][0]["payload"])

    def test_direct_dispatch_rejects_nonfinite_before_journal(self):
        from tools.cli import dispatch
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContractError):
                dispatch("CORE-04", {"root": directory, "journal": "nan.sqlite",
                         "operation": "status", "arguments": {"release_id": "none"},
                         "unused": float("nan")}, synthetic=True)
            self.assertFalse(Path(directory, "nan.sqlite").exists())

    def test_empty_wrong_type_ledger_is_not_silently_reset(self):
        for records, reviews in (([], None), (None, {}), ("", None)):
            with self.subTest(records=records, reviews=reviews), self.assertRaises(ContractError):
                VersionLedger(records, reviews)


if __name__ == "__main__":
    unittest.main()
