"""SE-01表式迁移正反例；转换不代替真实来源、确认和阶段审查。"""

import copy
import json
from pathlib import Path
import unittest

from tools import standards, standards_contract as migration
from tools.core import ContractError, canonical_bytes
from evals.test_standards_closed_loop import final_ready_payload


HASH = "a" * 64
LOCATOR = "synthetic:consultation-table:1"


def legacy_table():
    return {
        "header": {"standard_name": "合成标准", "draft_version": "v1",
                   "version_date": "2026-11-13", "total_received": 1,
                   "compiled_by": "合成汇总人", "reviewed_by": ""},
        "items": [{"seq": 7, "clause_id": "C-1", "text": "请记录校验结果。",
                   "origin": {"organization": "合成提出单位", "representative_scope": "仅代表本单位",
                              "participant_id": "P-1"},
                   "classification": "technical", "outcome": "accepted",
                   "reason": "统一要求型措辞", "proposed_text": "应记录校验结果。"}],
        "summary": {"total": 1, "accepted": 1, "partially_accepted": 0, "rejected": 0,
                    "pending": 0, "by_classification": {
                        key: int(key == "technical") for key in migration.CLASSIFICATIONS}},
    }


def imported(table=None, **kwargs):
    return migration.import_v1_disposition(
        legacy_table() if table is None else table,
        source_sha256=kwargs.get("source_sha256", HASH),
        source_locator=kwargs.get("source_locator", LOCATOR))


class ImportDispositionTests(unittest.TestCase):
    def test_import_preserves_original_and_stable_ids_without_aliasing(self):
        table = legacy_table()
        before = copy.deepcopy(table)
        result = imported(table)
        candidate = result["candidate"]
        self.assertEqual(1, result["source"]["contract_version"])
        self.assertEqual(2, result["target"]["contract_version"])
        self.assertEqual("dyz/standards/comment-disposition/v1", result["source"]["schema_id"])
        self.assertEqual("dyz/standards/comment-disposition/v2", result["target"]["schema_id"])
        self.assertEqual(before, candidate["migration_source"]["table"])
        cid = candidate["comments"][0]["id"]
        self.assertEqual(cid, candidate["comment_outcomes"][0]["comment_id"])
        self.assertEqual(cid, imported(table)["candidate"]["comments"][0]["id"])
        self.assertEqual(cid, imported(table, source_sha256=HASH.upper())["candidate"]["comments"][0]["id"])
        self.assertNotEqual(cid, imported(table, source_sha256="b" * 64)["candidate"]["comments"][0]["id"])
        table["items"].append({**copy.deepcopy(table["items"][0]), "seq": 8})
        reordered = imported({**table, "items": list(reversed(table["items"]))})
        self.assertEqual(cid, reordered["candidate"]["comments"][1]["id"])
        candidate["migration_source"]["table"]["items"][0]["text"] = "修改副本"
        candidate["comments"][0]["provenance"]["origin"]["organization"] = "修改副本"
        self.assertEqual(before["items"][0], table["items"][0])
        self.assertEqual(before["items"][0]["origin"], result["candidate"]["migration_source"]["table"]["items"][0]["origin"])

    def test_locator_partitions_same_source_and_sequence(self):
        first = imported(source_locator="/document/tables/0")["candidate"]["comments"][0]
        second = imported(source_locator="/document/tables/1")["candidate"]["comments"][0]
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["source"], second["source"])

    def test_missing_declared_statistics_are_reported_per_field(self):
        for summary in ({}, {"by_classification": {}}):
            with self.subTest(summary=summary):
                table = legacy_table()
                table["summary"] = summary
                result = imported(table)
                paths = {issue["source_path"] for issue in result["issues"]}
                for field in ("total", *migration.OUTCOMES):
                    self.assertIn("/summary/" + field, paths)
                for field in migration.CLASSIFICATIONS:
                    self.assertIn("/summary/by_classification/" + field, paths)

    def test_missing_evidence_is_explicit_and_not_a_ready_payload(self):
        result = imported()
        candidate = result["candidate"]
        row = candidate["comment_outcomes"][0]
        self.assertEqual("needs_review", result["status"])
        self.assertEqual("proposed", row["decision_status"])
        self.assertEqual("undetermined", row["major_change"])
        self.assertNotIn("confirmation", row)
        self.assertNotIn("collection_status", candidate)
        self.assertNotIn("operation", row["changes"][0])
        self.assertEqual({key: "unknown" for key in migration.IMPACT_FIELDS}, row["impact"])
        targets = {issue["target_path"] for issue in result["issues"]}
        for path in ("/project_id", "/adaptation/organization", "/adaptation/standard_type",
                     "/adaptation/domain", "/adaptation/stage", "/collection_status",
                     "/comment_outcomes/0/decision_status", "/comment_outcomes/0/changes/0/operation"):
            self.assertIn(path, targets)
        self.assertEqual("not_performed", result["professional_review"])
        self.assertEqual("not_asserted", result["organization_approval"])
        with self.assertRaisesRegex(ContractError, "missing:project_id"):
            standards.closed_loop(candidate)

    def test_every_source_leaf_has_a_preservation_mapping(self):
        table = legacy_table()
        table["decisions"] = [{"decision": "经研究同意", "extension": ["原文", {"a/b~c": 3}]}]
        result = imported(table)
        paths = {entry["source_path"] for entry in result["mapping"]}
        self.assertTrue({"/header/version_date", "/items/0/origin/representative_scope",
                         "/items/0/proposed_text", "/summary/accepted",
                         "/decisions/0/extension/1/a~1b~0c"} <= paths)
        self.assertEqual(table["decisions"], result["candidate"]["decisions"])
        self.assertEqual(table, result["candidate"]["migration_source"]["table"])

    def test_free_decision_is_not_guessed_and_full_document_is_not_a_clause(self):
        table = legacy_table()
        row = table["items"][0]
        row.pop("outcome")
        row.update(decision="采纳并批准发布", clause_id="全文")
        row["origin"].pop("participant_id")
        result = imported(table)
        comment = result["candidate"]["comments"][0]
        outcome = result["candidate"]["comment_outcomes"][0]
        self.assertEqual("document", comment["scope"])
        self.assertNotIn("clause_id", comment)
        self.assertNotIn("participant_id", comment)
        self.assertNotIn("outcome", outcome)
        self.assertNotIn("changes", outcome)
        self.assertEqual(row["origin"], comment["provenance"]["origin"])
        self.assertIn("outcome_missing", {issue["code"] for issue in result["issues"]})
        self.assertEqual(1, result["summary_comparison"]["derived"]["unmapped_outcomes"])

    def test_pending_string_preserves_only_question_and_reports_each_gap(self):
        table = legacy_table()
        row = table["items"][0]
        row.pop("proposed_text")
        row.update(outcome="pending", unresolved_item="补充原始记录", owner="外层姓名不能冒充责任确认")
        result = imported(table)
        pending = result["candidate"]["comment_outcomes"][0]["unresolved_item"]
        self.assertEqual({"question": "补充原始记录"}, pending)
        paths = {issue["target_path"] for issue in result["issues"]}
        for field in ("owner", "blocks", "recovery"):
            self.assertIn("/comment_outcomes/0/unresolved_item/" + field, paths)

    def test_partial_acceptance_and_document_proposal_do_not_invent_details(self):
        table = legacy_table()
        table["items"][0].update(outcome="partially_accepted", clause_id="全文")
        result = imported(table)
        row = result["candidate"]["comment_outcomes"][0]
        self.assertNotIn("clause_id", row["changes"][0])
        self.assertEqual(table["items"][0]["proposed_text"], row["changes"][0]["proposed_text"])
        paths = {issue["target_path"] for issue in result["issues"]}
        for field in ("accepted_part", "rejected_part", "rejected_reason", "reason_source"):
            self.assertNotIn(field, row)
            self.assertIn("/comment_outcomes/0/" + field, paths)
        self.assertIn("/comment_outcomes/0/changes/0/clause_id", paths)

    def test_supplied_confirmation_and_unknown_impacts_are_not_rewritten(self):
        table = legacy_table()
        table["items"][0].update(decision_status="confirmed", decision_version="decision-1",
                                  confirmation={"actor": "真实记录里的姓名"},
                                  impact={"verification": False, "references": "undetermined"})
        result = imported(table)
        row = result["candidate"]["comment_outcomes"][0]
        self.assertEqual("confirmed", row["decision_status"])
        self.assertEqual({"actor": "真实记录里的姓名"}, row["confirmation"])
        self.assertIs(False, row["impact"]["verification"])
        self.assertEqual("undetermined", row["impact"]["references"])
        self.assertEqual("unknown", row["impact"]["compilation_note"])
        paths = {issue["target_path"] for issue in result["issues"]}
        self.assertIn("/comment_outcomes/0/confirmation/authority_evidence", paths)
        self.assertIn("/comment_outcomes/0/confirmation/source", paths)

    def test_legacy_confirmed_rows_remain_unbound_with_explicit_gap(self):
        table = legacy_table()
        table["items"][0].update(decision_status="confirmed", decision_version="decision-v1", operation="replace",
                                  major_change="no", impact={key: False for key in migration.IMPACT_FIELDS},
                                  confirmation={"actor": "synthetic-reviewer", "authority_evidence": "synthetic:authority",
                                                "source": "synthetic:decision", "version": "decision-v1",
                                                "baseline_version": "v1"})
        result = imported(table)
        row = result["candidate"]["comment_outcomes"][0]
        self.assertEqual(table["items"][0]["confirmation"], row["confirmation"])
        self.assertNotIn("content_binding", row["confirmation"])
        self.assertIn({"code": "comment_decision_content_binding_unbound", "source_path": "/items/0/confirmation/content_binding",
                       "target_path": "/comment_outcomes/0/confirmation/content_binding", "record_id": row["comment_id"]},
                      result["issues"])
        self.assertEqual(table, result["candidate"]["migration_source"]["table"])

    def test_declared_statistics_remain_original_and_mismatches_are_located(self):
        table = legacy_table()
        table["summary"].update(total=99, accepted=98, clauses_touched=3, substantive_changes=2)
        table["summary"]["by_classification"]["technical"] = 80
        table["header"]["total_received"] = 9
        result = imported(table)
        comparison = result["summary_comparison"]
        self.assertEqual(table["summary"], comparison["declared"])
        self.assertEqual(1, comparison["derived"]["total"])
        self.assertEqual(1, comparison["derived"]["accepted"])
        paths = {issue["source_path"] for issue in result["issues"]}
        for path in ("/summary/total", "/summary/accepted", "/summary/by_classification/technical",
                     "/header/total_received", "/summary/clauses_touched", "/summary/substantive_changes"):
            self.assertIn(path, paths)

    def test_invalid_versions_shapes_hashes_and_duplicate_sequences_are_rejected(self):
        for value in (0, 2, 3, True, 1.0, "1", None):
            with self.subTest(version=value):
                table = legacy_table()
                table["contract_version"] = value
                with self.assertRaises(ContractError):
                    imported(table)
        for value in ("dyz/standards/comment-disposition/v2", "unknown", 1):
            table = legacy_table()
            table["$id"] = value
            with self.assertRaises(ContractError):
                imported(table)
        for value in ("", "a" * 63, "g" * 64, 42, " a" + "a" * 63):
            with self.assertRaisesRegex(ContractError, "source_sha256"):
                imported(source_sha256=value)
        for value in ("", "  ", None, 1):
            with self.assertRaisesRegex(ContractError, "source_locator"):
                imported(source_locator=value)
        for key, value in (("header", []), ("items", {}), ("items", []), ("summary", [])):
            table = legacy_table()
            table[key] = value
            with self.assertRaises(ContractError):
                imported(table)
        for field, value in (("seq", True), ("seq", 0), ("origin", []), ("text", 12),
                             ("impact", []), ("outcome", "同意"), ("operation", "upsert"),
                             ("unresolved_item", 12)):
            table = legacy_table()
            table["items"][0][field] = value
            with self.assertRaises(ContractError):
                imported(table)
        table = legacy_table()
        table["items"].append(copy.deepcopy(table["items"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate.*seq"):
            imported(table)

    def test_candidate_can_reach_real_v2_consumers_after_explicit_completion(self):
        table = legacy_table()
        table["items"][0].update(operation="replace", major_change="no",
                                  impact={key: False for key in migration.IMPACT_FIELDS})
        result = imported(table)
        candidate = result["candidate"]
        complete = final_ready_payload()
        for field in ("project_id", "adaptation", "clauses", "baseline_clauses", "compilation_note",
                      "verification_matrix", "baseline_version", "sensitivity", "delivery_stage"):
            candidate[field] = copy.deepcopy(complete[field])
        candidate["version"] = complete["version"]
        before = copy.deepcopy(candidate)
        for capability in ("STD-09", "STD-11"):
            out = standards.run(capability, candidate)
            self.assertEqual(candidate["comments"], out["artifacts"]["comments"])
            self.assertEqual(candidate["comment_outcomes"], out["artifacts"]["comment_outcomes"])
            codes = {issue["code"] for issue in out["issues"]}
            self.assertIn("comment_decision_unconfirmed", codes)
            self.assertIn("comment_collection_incomplete", codes)
            self.assertFalse(out["artifacts"]["outcome_tally"]["closed"])
            self.assertEqual("not_performed", out["professional_review"])
        self.assertEqual(before, candidate)


class ExportDispositionTests(unittest.TestCase):
    def payload(self):
        result = imported()
        data = final_ready_payload()
        data["migration_source"] = copy.deepcopy(result["candidate"]["migration_source"])
        data["comments"][0]["provenance"] = copy.deepcopy(result["candidate"]["comments"][0]["provenance"])
        return data

    def test_projection_reports_each_unrepresentable_leaf_and_preserves_input(self):
        data = self.payload()
        data["comment_realizations"] = [{"comment_id": "COM-1", "status": "verified",
                                           "document_hash": "c" * 64}]
        data["extension"] = {"a/b~c": ["原始扩展"]}
        before = copy.deepcopy(data)
        out = migration.export_v1_disposition(data)
        self.assertEqual(before, data)
        self.assertEqual("partial", out["status"])
        self.assertEqual("not_performed", out["schema_validation"])
        self.assertEqual(2, out["source"]["contract_version"])
        self.assertEqual(1, out["target"]["contract_version"])
        item = out["table"]["items"][0]
        self.assertEqual(data["comments"][0]["text"], item["text"])
        self.assertEqual(data["comments"][0]["provenance"]["origin"], item["origin"])
        self.assertEqual(data["comment_outcomes"][0]["changes"][0]["proposed_text"], item["proposed_text"])
        losses = {loss["path"]: loss for loss in out["losses"]}
        for path in ("/comment_outcomes/0/decision_status", "/comment_outcomes/0/confirmation/authority_evidence",
                     "/comment_outcomes/0/changes/0/operation", "/comments/0/source", "/comments/0/id",
                     "/comment_realizations/0/status", "/comment_realizations/0/document_hash",
                     "/migration_source/sha256", "/extension/a~1b~0c/0"):
            self.assertIn(path, losses)
            self.assertTrue(losses[path]["reason"])
            self.assertIn("value", losses[path])
        out["table"]["items"][0]["origin"]["organization"] = "副本改动"
        self.assertEqual(before, data)

    def test_new_confirmation_and_reference_leaves_have_specific_export_losses(self):
        data = self.payload()
        data = migration.confirm_comment(data, "COM-1", data["comment_outcomes"][0]["confirmation"])
        data["external_references"] = [{"id": "R-1", "identifier": "SYN-1", "edition": "2024",
                                          "title": "合成引用", "source": "synthetic:reference"}]
        data["reference_bindings"] = [{"clause_id": "C-1", "reference": "SYN-1-2024",
                                       "kind": "external", "target_id": "R-1"}]
        before = copy.deepcopy(data)
        out = migration.export_v1_disposition(data)
        self.assertEqual("partial", out["status"])
        losses = {row["path"]: row for row in out["losses"]}
        for prefix, reason in (("/comment_outcomes/0/confirmation/content_binding/", "v1_cannot_represent_comment_content_binding"),
                               ("/comment_outcomes/0/confirmation_history/", "v1_cannot_represent_confirmation_history"),
                               ("/external_references/", "v1_cannot_represent_reference_identity_or_binding"),
                               ("/reference_bindings/", "v1_cannot_represent_reference_identity_or_binding")):
            matches = [row for path, row in losses.items() if path.startswith(prefix)]
            self.assertTrue(matches, prefix)
            self.assertTrue(all(row["reason"] == reason for row in matches))
        self.assertNotIn("confirmation", out["table"]["items"][0])
        self.assertEqual(before, data)

    def test_multiple_targets_and_add_delete_rows_are_not_squeezed_into_v1(self):
        for kind in ("multiple", "add", "delete", "different-target"):
            data = self.payload()
            changes = data["comment_outcomes"][0]["changes"]
            if kind == "multiple":
                changes.append({"operation": "replace", "clause_id": "C-2", "proposed_text": "第二目标"})
            elif kind == "different-target":
                changes[0]["clause_id"] = "C-2"
            else:
                changes[0]["operation"] = kind
                if kind == "delete":
                    changes[0].pop("proposed_text")
            with self.subTest(kind=kind):
                out = migration.export_v1_disposition(data)
                self.assertEqual("refused", out["status"])
                self.assertEqual([], out["table"]["items"])
                self.assertEqual(["COM-1"], out["rejected_record_ids"])
                self.assertTrue(any(loss["path"].startswith("/comment_outcomes/0/changes/") for loss in out["losses"]))

    def test_document_scope_is_explicitly_reencoded_not_silently_dropped(self):
        data = self.payload()
        data["comments"][0].pop("clause_id")
        data["comments"][0]["scope"] = "document"
        row = data["comment_outcomes"][0]
        row.pop("changes")
        row.update(no_change=True, no_change_scope="document", reason_source="synthetic:unchanged")
        out = migration.export_v1_disposition(data)
        self.assertEqual("全文", out["table"]["items"][0]["clause_id"])
        self.assertTrue(any(entry["source_path"] == "/comments/0/scope" and
                            entry["action"] == "document_scope_label" for entry in out["mapping"]))
        self.assertIn("/comment_outcomes/0/no_change_scope", {loss["path"] for loss in out["losses"]})

    def test_pending_metadata_and_partial_acceptance_details_are_reported(self):
        for outcome in ("pending", "partially_accepted"):
            data = self.payload()
            row = data["comment_outcomes"][0]
            row.update(outcome=outcome, accepted_part="措辞", rejected_part="试验",
                       rejected_reason="范围外", reason_source="synthetic:scope")
            if outcome == "pending":
                row.pop("changes")
                row["unresolved_item"] = {"id": "O-1", "question": "核验资料", "owner": "组A",
                                           "blocks": "submission", "recovery": "取得原件",
                                           "source_refs": ["synthetic:source"]}
            out = migration.export_v1_disposition(data)
            self.assertEqual(1, len(out["table"]["items"]))
            paths = {loss["path"] for loss in out["losses"]}
            for field in ("accepted_part", "rejected_part", "rejected_reason"):
                self.assertIn("/comment_outcomes/0/" + field, paths)
            if outcome == "pending":
                self.assertIn("/comment_outcomes/0/unresolved_item/id", paths)
                self.assertIn("/comment_outcomes/0/unresolved_item/source_refs/0", paths)
                self.assertEqual({"question", "owner", "blocks", "recovery"},
                                 set(out["table"]["items"][0]["unresolved_item"]))

    def test_unknown_impact_is_not_false_and_unknown_dates_are_not_borrowed(self):
        data = self.payload()
        data["comment_outcomes"][0]["impact"]["verification"] = "unknown"
        out = migration.export_v1_disposition(data)
        self.assertNotIn("verification", out["table"]["items"][0]["impact"])
        self.assertNotIn("version_date", out["table"]["header"])
        paths = {loss["path"] for loss in out["losses"]}
        self.assertIn("/comment_outcomes/0/impact/verification", paths)
        self.assertIn("/migration_source/table/header/version_date", paths)
        self.assertIn("/header/version_date", {issue["target_path"] for issue in out["issues"]})

    def test_missing_origin_or_pending_responsibility_refuses_record(self):
        for mutate in (lambda p: p["comments"][0].pop("provenance"),
                       lambda p: p["comments"][0]["provenance"]["origin"].pop("representative_scope"),
                       lambda p: p["comment_outcomes"][0].update(
                           changes=[], outcome="pending", unresolved_item={"question": "待补"})):
            data = self.payload()
            mutate(data)
            out = migration.export_v1_disposition(data)
            self.assertEqual("refused", out["status"])
            self.assertEqual([], out["table"]["items"])

    def test_zero_comments_do_not_fabricate_a_row_or_claim_v1_valid(self):
        data = final_ready_payload()
        data.update(comments=[], comment_outcomes=[], collection_evidence=["synthetic:zero"])
        out = migration.export_v1_disposition(data)
        self.assertEqual([], out["table"]["items"])
        self.assertEqual(0, out["table"]["summary"]["total"])
        self.assertEqual("refused", out["status"])
        self.assertEqual("not_performed", out["schema_validation"])
        self.assertIn("v1_min_items_unsatisfied", {issue["code"] for issue in out["issues"]})

    def test_mixed_safe_unsafe_rows_export_only_safe_projection_with_partial_status(self):
        data = self.payload()
        data["comments"].append({**copy.deepcopy(data["comments"][0]), "id": "COM-2"})
        row = copy.deepcopy(data["comment_outcomes"][0])
        row.update(comment_id="COM-2", changes=[{"operation": "add", "clause_id": "C-2", "proposed_text": "新增"}])
        data["comment_outcomes"].append(row)
        out = migration.export_v1_disposition(data)
        self.assertEqual("partial", out["status"])
        self.assertEqual(1, len(out["table"]["items"]))
        self.assertEqual(["COM-2"], out["rejected_record_ids"])
        self.assertEqual(1, out["table"]["summary"]["total"])
        self.assertEqual("exported_rows_only", out["summary_scope"])

    def test_export_rejects_unknown_versions_bad_shapes_and_duplicates(self):
        for version in (None, 1, 3, True, 2.0, "2"):
            data = self.payload()
            data["contract_version"] = version
            with self.assertRaises(ContractError):
                migration.export_v1_disposition(data)
        for field, value in (("comments", {}), ("comment_outcomes", "bad")):
            data = self.payload()
            data[field] = value
            with self.assertRaises(ContractError):
                migration.export_v1_disposition(data)
        for field in ("comments", "comment_outcomes"):
            data = self.payload()
            data[field].append(copy.deepcopy(data[field][0]))
            with self.assertRaises(ContractError):
                migration.export_v1_disposition(data)

    def test_export_malformed_impact_and_conflicting_no_change_scopes_are_not_projected(self):
        for value in (0, 1, "false", [], {}):
            data = self.payload()
            data["comment_outcomes"][0]["impact"]["verification"] = value
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    migration.export_v1_disposition(data)
        data = self.payload()
        data["comments"][0].pop("clause_id")
        data["comments"][0]["scope"] = "document"
        row = data["comment_outcomes"][0]
        row.pop("changes")
        row.update(no_change=True, no_change_targets=["全文"], no_change_scope="document",
                   reason_source="synthetic:reason")
        out = migration.export_v1_disposition(data)
        self.assertEqual("refused", out["status"])
        self.assertEqual([], out["table"]["items"])

    def test_export_never_emits_fields_outside_frozen_v1_schema(self):
        schema = json.loads((Path(__file__).resolve().parents[1] /
                            "skills/dyz-standards/resources/lifecycle/comment-disposition.schema.json").read_text(encoding="utf-8"))
        result = migration.export_v1_disposition(self.payload())
        table = result["table"]
        self.assertTrue(set(table) <= set(schema["properties"]))
        for key in ("header", "summary"):
            self.assertTrue(set(table[key]) <= set(schema["$defs"][key]["properties"]))
        for row in table["items"]:
            self.assertTrue(set(row) <= set(schema["$defs"]["item"]["properties"]))
            self.assertTrue(set(row["origin"]) <= set(schema["$defs"]["origin"]["properties"]))
        self.assertEqual(result, json.loads(canonical_bytes(result)))


if __name__ == "__main__":
    unittest.main()
