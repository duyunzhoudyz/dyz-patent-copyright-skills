"""PROC-05实际候选与既有有限关系复核；不证明自然语言或法律支持。"""
import copy
import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import zipfile

from evals.test_fidelity import citation, document
from evals.test_procedure import base, ev
from tools.core import ContractError, sha256_bytes
from tools.procedure import run


def delivery_example():
    original = document("O", "original", "采用光学接口。", "O1")
    candidate = document("D", "candidate", "光学接口", "C2")
    response = document("R", "candidate", "本轮仅整理给定局部文字，其余意见待核。", "R2")
    review = {
        "documents": [original, candidate, response],
        "atoms": [{"id": "optical", "meaning": "采用光学接口", "scope": "本题局部接口限定"},
                  {"id": "pump", "meaning": "接口信号后自动启泵", "scope": "本题局部接口动作关系"}],
        "facts": [{"id": "F", "state": "explicit", "citation": citation(original), "formula": "optical"}],
        "assertions": [{"id": "A", "citation": citation(candidate), "formula": "optical",
                        "basis_fact_ids": ["F"], "proof_scope": "original_support", "mode": "asserted"}],
        "regions": [{"id": "D-body", "citation": citation(candidate), "kind": "technical", "assertion_ids": ["A"]},
                    {"id": "R-scope", "citation": citation(response), "kind": "context", "assertion_ids": [],
                     "reason": "答复范围，不是新增技术断言；分类仍由调用者负责"}],
        "parameter_requests": [], "parameter_assessments": [],
    }
    payload = base()
    payload.update(
        notice=ev(id="N", version="N2", kind="synthetic", complete=True,
                  served_at="2026-10-30T00:00:00Z", due_at="2026-12-01T00:00:00Z",
                  opinions=[{"id": "I", "text": "合成局部文字意见"}]),
        current_claims=ev(version="C1"), original_application=ev(version="O1"),
        responses=[ev(opinion_id="I", text=response["text"])], amendments=[], citations=[], disclosure_targets=[],
        replacement_required=True,
        replacement_candidates=[ev(id="K", version="C2", text=candidate["text"], coverage="partial",
                                   boundary="只含获给局部文字，未取得其余权项上下文，不是完整权项")],
        fidelity=review,
        fidelity_bindings={"response:I": citation(response), "replacement:K": citation(candidate)},
    )
    return payload


def replace_candidate(payload, text, formula):
    doc = document("D", "candidate", text, "C2")
    payload["replacement_candidates"][0]["text"] = text
    payload["fidelity"]["documents"][1] = doc
    payload["fidelity"]["assertions"][0].update(citation=citation(doc), formula=formula)
    payload["fidelity"]["regions"][0]["citation"] = citation(doc)
    payload["fidelity_bindings"]["replacement:K"] = citation(doc)


class ProcedureOutputQualityTests(unittest.TestCase):
    def test_without_fidelity_actual_response_and_replacement_are_scanned(self):
        for field in ("responses", "replacement_candidates"):
            with self.subTest(field=field):
                p = delivery_example()
                del p["fidelity"], p["fidelity_bindings"]
                p[field][0]["text"] += "[待确认：技术负责人补证]"
                out = run("PROC-05", p)
                self.assertEqual("blocked", out["status"])
                self.assertEqual("blocked", out["artifacts"]["text_quality"]["status"])
                self.assertEqual("not_performed", out["artifacts"]["fidelity"]["status"])
                self.assertIn("技术负责人补证", out["artifacts"][field][0]["text"])

    def test_resolved_record_does_not_clear_residual_candidate_text(self):
        p = delivery_example()
        text = "光学接口[待确认：技术负责人补证]"
        replace_candidate(p, text, "optical")
        p["fidelity"]["placeholder_resolutions"] = [{
            "id": "replacement:K#" + str(text.index("[")),
            "resolution_source": "C2", "reviewer": "合成技术负责人"}]
        out = run("PROC-05", p)
        self.assertEqual("blocked", out["status"])
        self.assertEqual("checked", out["artifacts"]["fidelity"]["status"])
        self.assertEqual("blocked", out["artifacts"]["text_quality"]["status"])

    def test_clean_partial_draft_keeps_review_boundaries(self):
        out = run("PROC-05", delivery_example())
        self.assertEqual("checked", out["artifacts"]["text_quality"]["status"])
        self.assertEqual("draft", out["artifacts"]["response_status"])
        self.assertEqual("not_performed", out["professional_review"])


class ProcedureFinalTextGateTests(unittest.TestCase):
    def final_case(self, candidate):
        payload = delivery_example()
        original = "只有许可成立，才允许发布。"
        payload["delivery_stage"] = "final"
        payload["final_text_sources"] = [document("GateOriginal", "original", original)]
        payload["responses"][0]["text"] = original
        payload["replacement_candidates"][0]["text"] = candidate
        del payload["fidelity"], payload["fidelity_bindings"]
        return payload

    def test_oa_final_checks_actual_response_and_replacement(self):
        result = run("PROC-05", self.final_case("只有许可成立，才允许发布。"))
        self.assertEqual("checked", result["artifacts"]["final_text_gate"]["status"])

    def test_oa_wrong_replacement_is_not_returned_as_final(self):
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            run("PROC-05", self.final_case("一旦许可成立，就允许发布。"))

    def test_oa_wrong_response_is_not_hidden_by_correct_replacement(self):
        payload = self.final_case("只有许可成立，才允许发布。")
        payload["responses"][0]["text"] = "一旦许可成立，就允许发布。"
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            run("PROC-05", payload)

    def test_oa_uses_the_same_frozen_fulltext_gate_for_both_artifacts(self):
        from evals.test_patent_gate_fulltext import load_case, variants
        for key in ("cn", "mechanical"):
            raw, fixture = load_case(key)
            text = raw.decode("utf-8")
            payload = self.final_case(text)
            payload["final_text_sources"] = fixture["documents"]
            payload["responses"][0]["text"] = text
            result = run("PROC-05", payload)
            self.assertEqual("checked", result["artifacts"]["final_text_gate"]["status"])
            self.assertEqual(text, result["artifacts"]["responses"][0]["text"])
            for name, body in variants(key, text):
                for field in ("responses", "replacement_candidates"):
                    with self.subTest(case=key, variant=name, field=field):
                        changed = copy.deepcopy(payload)
                        changed[field][0]["text"] = body.decode("utf-8")
                        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
                            run("PROC-05", changed)


class ProcedureDeliveryTests(unittest.TestCase):
    def test_retained_unsupported_relation_is_checked_even_without_new_amendments(self):
        value = delivery_example()
        replace_candidate(value, "光学接口收到信号后自动启泵。", {"all": ["optical", "pump"]})
        out = run("PROC-05", value)
        self.assertEqual("blocked", out["status"])
        assertion = out["artifacts"]["fidelity"]["assertions"][0]
        self.assertEqual("undetermined", assertion["relation"])
        self.assertFalse(assertion["countermodel"]["pump"])

    def test_actual_candidate_cannot_borrow_an_unrelated_good_review(self):
        value = delivery_example()
        value["replacement_candidates"][0]["text"] = "光学接口收到信号后自动启泵。"
        out = run("PROC-05", value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("artifact_text_not_in_fidelity", {x["code"] for x in out["artifacts"]["fidelity"]["issues"]})

    def test_required_candidate_missing_is_not_satisfied_by_a_deletion_plan(self):
        value = delivery_example()
        value["responses"][0]["text"] = "删除新增部分，其余旧文不变。"
        value["replacement_candidates"] = []
        del value["fidelity"], value["fidelity_bindings"]
        out = run("PROC-05", value)
        self.assertEqual("needs_evidence", out["status"])
        self.assertIn("replacement_candidate_missing", out["issues"])
        self.assertEqual("missing", out["artifacts"]["replacement_status"])

    def test_supported_partial_candidate_is_materialized_without_professional_upgrade(self):
        out = run("PROC-05", delivery_example())
        self.assertEqual("needs_review", out["status"])
        self.assertEqual("光学接口", out["artifacts"]["replacement_candidates"][0]["text"])
        self.assertEqual("supplied_partial", out["artifacts"]["replacement_status"])
        self.assertEqual("checked", out["artifacts"]["fidelity"]["status"])
        self.assertFalse(out["artifacts"]["fidelity"]["natural_language_verified"])
        self.assertEqual("not_determined", out["artifacts"]["legal_conclusion"])
        self.assertEqual("not_performed", out["professional_review"])

    def test_supported_paraphrase_is_not_rejected_for_different_source_wording(self):
        value = delivery_example()
        replace_candidate(value, "该结构使用光学接口。", "optical")
        self.assertEqual("checked", run("PROC-05", value)["artifacts"]["fidelity"]["status"])

    def test_valid_retained_necessary_condition_and_its_equivalent_rewrite_are_accepted(self):
        value = delivery_example()
        rule = {"implies": ["pump", "optical"]}
        original = document("O", "original", "只有采用光学接口时才允许启泵。", "O1")
        value["fidelity"]["documents"][0] = original
        value["fidelity"]["facts"][0]["citation"] = citation(original)
        value["fidelity"]["facts"][0]["formula"] = rule
        replace_candidate(value, "启泵必须采用光学接口。", copy.deepcopy(rule))
        value["fidelity"]["assertions"][0]["comparison"] = "equivalent"
        self.assertEqual("checked", run("PROC-05", value)["artifacts"]["fidelity"]["status"])
        replace_candidate(value, "未采用光学接口时不得启泵。", {"implies": [{"not": "optical"}, {"not": "pump"}]})
        self.assertEqual("checked", run("PROC-05", value)["artifacts"]["fidelity"]["status"])

    def test_dropping_a_valid_retained_condition_is_rejected(self):
        value = delivery_example()
        original = document("O", "original", "只有采用光学接口时才允许启泵。", "O1")
        value["fidelity"]["documents"][0] = original
        value["fidelity"]["facts"][0]["citation"] = citation(original)
        value["fidelity"]["facts"][0]["formula"] = {"implies": ["pump", "optical"]}
        replace_candidate(value, "启泵。", "pump")
        self.assertEqual("blocked", run("PROC-05", value)["status"])

    def test_candidate_version_must_match_actual_bound_document(self):
        value = delivery_example()
        value["replacement_candidates"][0]["version"] = "C3"
        out = run("PROC-05", value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("replacement_version_mismatch", {x["code"] for x in out["artifacts"]["fidelity"]["issues"]})

    def test_original_basis_cannot_borrow_another_original_version(self):
        value = delivery_example()
        value["original_application"]["version"] = "O2"
        out = run("PROC-05", value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("replacement_original_version_mismatch", {x["code"] for x in out["artifacts"]["fidelity"]["issues"]})

    def test_product_consistency_cannot_replace_original_support_in_replacement_body(self):
        value = delivery_example()
        value["fidelity"]["documents"][0]["role"] = "product"
        value["fidelity"]["assertions"][0]["proof_scope"] = "technical_consistency"
        out = run("PROC-05", value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("replacement_original_support_required", {x["code"] for x in out["artifacts"]["fidelity"]["issues"]})

    def test_context_only_candidate_cannot_borrow_an_assertion_from_the_response(self):
        value = delivery_example()
        review = value["fidelity"]
        review["assertions"][0]["citation"] = citation(review["documents"][2])
        review["regions"][0].update(kind="context", assertion_ids=[], reason="调用者标成上下文")
        review["regions"][1].update(kind="technical", assertion_ids=["A"])
        out = run("PROC-05", value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("replacement_assertions_missing", {x["code"] for x in out["artifacts"]["fidelity"]["issues"]})

    def test_every_actual_response_and_replacement_requires_a_binding(self):
        value = delivery_example()
        del value["fidelity_bindings"]["response:I"]
        with self.assertRaisesRegex(ContractError, "artifact_binding_members_mismatch"):
            run("PROC-05", value)

    def test_binding_to_original_instead_of_candidate_is_rejected(self):
        value = delivery_example()
        value["fidelity_bindings"]["replacement:K"] = citation(value["fidelity"]["documents"][0])
        with self.assertRaisesRegex(ContractError, "artifact_candidate_required"):
            run("PROC-05", value)

    def test_partial_candidate_requires_an_explicit_boundary(self):
        value = delivery_example()
        value["replacement_candidates"][0]["boundary"] = " "
        with self.assertRaisesRegex(ContractError, "replacement_boundary_required"):
            run("PROC-05", value)

    def test_blank_candidate_and_blank_response_are_contract_errors(self):
        for target, code in [("replacement_candidates", "replacement_text_required"), ("responses", "empty:text")]:
            with self.subTest(target=target):
                value = delivery_example()
                value[target][0]["text"] = " "
                with self.assertRaisesRegex(ContractError, code):
                    run("PROC-05", value)

    def test_nontext_response_is_not_accepted_as_an_answer(self):
        value = delivery_example()
        value["responses"][0]["text"] = ["not a text body"]
        with self.assertRaisesRegex(ContractError, "response_text_required"):
            run("PROC-05", value)

    def test_complete_candidate_remains_a_complete_deliverable(self):
        value = delivery_example()
        value["replacement_candidates"][0]["coverage"] = "complete"
        del value["replacement_candidates"][0]["boundary"]
        out = run("PROC-05", value)
        self.assertEqual("supplied_complete", out["artifacts"]["replacement_status"])
        self.assertEqual("checked", out["artifacts"]["fidelity"]["status"])
        self.assertEqual("caller_declared_not_verified", out["artifacts"]["replacement_coverage"])

    def test_bad_requirement_and_coverage_types_are_contract_errors(self):
        for flag in [None, 1, "true", []]:
            with self.subTest(flag=flag):
                value = delivery_example()
                value["replacement_required"] = flag
                with self.assertRaisesRegex(ContractError, "replacement_required_boolean_required"):
                    run("PROC-05", value)
        value = delivery_example()
        value["replacement_candidates"][0]["coverage"] = []
        with self.assertRaisesRegex(ContractError, "replacement_coverage_unknown"):
            run("PROC-05", value)

    def test_replacement_assertion_cannot_borrow_a_larger_candidate_region(self):
        value = delivery_example()
        actual = value["replacement_candidates"][0]["text"]
        larger = document("D", "candidate", actual + "及其他限定", "C2")
        value["fidelity"]["documents"][1] = larger
        value["fidelity"]["assertions"][0]["citation"] = citation(larger)
        value["fidelity"]["regions"][0]["citation"] = citation(larger)
        value["fidelity_bindings"]["replacement:K"] = citation(larger, 0, len(actual))
        out = run("PROC-05", value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("replacement_assertion_crosses_boundary", {x["code"] for x in out["artifacts"]["fidelity"]["issues"]})

    def test_unknown_original_fact_is_not_promoted_to_support(self):
        value = delivery_example()
        value["fidelity"]["facts"][0]["state"] = "unknown"
        out = run("PROC-05", value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("basis_not_explicit", {x["code"] for x in out["artifacts"]["fidelity"]["issues"]})

    def test_bindings_without_a_review_cannot_claim_performed_checks(self):
        value = delivery_example()
        del value["fidelity"]
        with self.assertRaisesRegex(ContractError, "fidelity_payload_required"):
            run("PROC-05", value)

    def test_legacy_calls_remain_explicitly_unchecked(self):
        value = delivery_example()
        for key in ["replacement_required", "replacement_candidates", "fidelity", "fidelity_bindings"]:
            del value[key]
        out = run("PROC-05", value)
        self.assertEqual("needs_review", out["status"])
        self.assertEqual("not_declared", out["artifacts"]["replacement_status"])
        self.assertEqual("not_performed", out["artifacts"]["fidelity"]["status"])

    def test_changed_version_keeps_old_review_invalidated_even_when_new_check_blocks(self):
        value = delivery_example()
        old = run("PROC-05", value)["artifacts"]["input_digest"]
        value["previous_input_digest"] = old
        replace_candidate(value, "光学接口收到信号后自动启泵。", {"all": ["optical", "pump"]})
        out = run("PROC-05", value)
        self.assertEqual("invalidated", out["status"])
        self.assertEqual("blocked", out["artifacts"]["recomputed_status"])
        self.assertEqual("not_granted", out["artifacts"]["review_reuse"])

    def test_actual_api_candidate_reaches_docx_and_changed_text_cannot_borrow_it(self):
        from tools import documents
        payload = delivery_example()
        out = run("PROC-05", payload)
        scope = out["artifacts"]["responses"][0]["text"]
        candidate = out["artifacts"]["replacement_candidates"][0]["text"]
        with tempfile.TemporaryDirectory(prefix="dyz-procedure-delivery-") as temporary:
            root = Path(temporary)
            raw = (scope + "\n" + candidate).encode("utf-8")
            (root / "draft.md").write_bytes(raw)
            spec = {"sensitivity": "synthetic", "document_id": "ProcedureLocalCandidate", "version": "C2", "business": "patent",
                "sources": [{"id": "Draft", "path": "draft.md", "sha256": sha256_bytes(raw)}],
                "blocks": [{"id": "Scope", "source_id": "Draft", "kind": "paragraph", "audience": "body", "start_line": 1, "end_line": 1},
                           {"id": "Candidate", "source_id": "Draft", "kind": "paragraph", "audience": "body", "start_line": 2, "end_line": 2}],
                "fidelity": {"payload": payload["fidelity"], "blocks": {
                    "Scope": payload["fidelity_bindings"]["response:I"],
                    "Candidate": payload["fidelity_bindings"]["replacement:K"]}}}
            built = documents.build(root, spec, "pack", synthetic=True)
            self.assertEqual("checked", built["fidelity"]["status"])
            self.assertEqual("checked", documents.verify(root, spec, "pack", synthetic=True)["fidelity"]["status"])
            with zipfile.ZipFile(root / "pack/body/document.docx") as archive:
                xml = ET.fromstring(archive.read("word/document.xml"))
            text = "".join(node.text or "" for node in xml.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
            self.assertIn(scope, text)
            self.assertIn(candidate, text)
            changed = (scope + "\n光学接口收到信号后自动启泵。").encode("utf-8")
            (root / "draft.md").write_bytes(changed)
            spec["sources"][0]["sha256"] = sha256_bytes(changed)
            with self.assertRaisesRegex(ContractError, "document_fidelity_blocked"):
                documents.build(root, spec, "changed-pack", synthetic=True)
            self.assertFalse((root / "changed-pack").exists())


if __name__ == "__main__":
    unittest.main()
