"""有限关系模型与实际稿件绑定的行为回归；不作专业法律判断。"""
import copy
import hashlib
import unittest

from tools import fidelity
from tools.core import ContractError


def document(identity, role, text, version="1"):
    return {"id": identity, "role": role, "version": version, "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def citation(doc, start=0, end=None):
    end = len(doc["text"]) if end is None else end
    return {"document_id": doc["id"], "start": start, "end": end,
            "quote": doc["text"][start:end]}


def example():
    source = document("O", "original", "只有许可成立时，系统才允许发布。")
    draft = document("D", "candidate", "系统发布时须已取得许可。")
    formula = {"implies": ["release", "permission"]}
    return {"documents": [source, draft],
            "atoms": [{"id": "release", "meaning": "发生发布", "scope": "当前发布事件"},
                      {"id": "permission", "meaning": "许可成立", "scope": "当前发布事件"}],
            "facts": [{"id": "F1", "state": "explicit", "citation": citation(source),
                       "formula": formula}],
            "assertions": [{"id": "A1", "citation": citation(draft),
                            "formula": copy.deepcopy(formula), "basis_fact_ids": ["F1"],
                            "proof_scope": "original_support", "mode": "asserted"}],
            "regions": [{"id": "R1", "citation": citation(draft), "kind": "technical",
                         "assertion_ids": ["A1"]}],
            "parameter_requests": [], "parameter_assessments": []}


class FidelityTests(unittest.TestCase):
    def codes(self, output):
        return {issue["code"] for issue in output["issues"]}

    def test_preserved_necessary_condition_is_entailed(self):
        out = fidelity.audit(example())
        self.assertEqual("checked", out["status"])
        self.assertEqual("entailed", out["assertions"][0]["relation"])
        self.assertFalse(out["natural_language_verified"])
        self.assertEqual("not_performed", out["professional_review"])

    def test_unknown_reverse_is_not_sufficient_trigger(self):
        value = example()
        value["assertions"][0]["formula"] = {"implies": ["permission", "release"]}
        out = fidelity.audit(value)
        self.assertEqual("blocked", out["status"])
        row = out["assertions"][0]
        self.assertEqual("undetermined", row["relation"])
        self.assertEqual({"permission": True, "release": False}, row["countermodel"])

    def test_logically_equivalent_contrapositive_is_accepted(self):
        value = example()
        value["assertions"][0]["formula"] = {"implies": [
            {"not": "permission"}, {"not": "release"}]}
        self.assertEqual("checked", fidelity.audit(value)["status"])

    def test_negation_cannot_be_relaxed_to_only_one_implementation_path(self):
        value = example()
        value["atoms"].append({"id": "path", "meaning": "使用路径甲", "scope": "当前发布事件"})
        value["facts"][0]["formula"] = {"implies": ["permission", {"not": "release"}]}
        value["assertions"][0]["formula"] = {"implies": [
            "permission", {"not": {"all": ["release", "path"]}}]}
        # 放宽后的断言虽被原文蕴含，原限制反向不成立；等价改写应另外查两向。
        value["assertions"][0]["comparison"] = "equivalent"
        out = fidelity.audit(value)
        self.assertIn("assertion_not_equivalent", self.codes(out))

    def test_unstated_mid_interval_hold_remains_unknown(self):
        value = example()
        value["atoms"] = [{"id": x, "meaning": x, "scope": "一次阀门控制"}
                          for x in ["high", "release", "middle", "hold"]]
        value["facts"][0]["formula"] = {"implies": ["high", "release"]}
        value["assertions"][0]["formula"] = {"implies": ["middle", "hold"]}
        out = fidelity.audit(value)
        self.assertEqual("undetermined", out["assertions"][0]["relation"])
        self.assertFalse(out["assertions"][0]["countermodel"]["hold"])

    def test_manual_reset_gate_does_not_imply_physical_hold(self):
        value = example()
        value["atoms"] = [{"id": x, "meaning": x, "scope": "恢复等待期"}
                          for x in ["reset", "resume", "hold"]]
        value["facts"][0]["formula"] = {"implies": ["resume", "reset"]}
        value["assertions"][0]["formula"] = {"implies": [{"not": "reset"}, "hold"]}
        out = fidelity.audit(value)
        self.assertEqual("undetermined", out["assertions"][0]["relation"])

    def test_unknown_is_not_false_or_a_premise(self):
        value = example()
        value["facts"][0]["state"] = "unknown"
        out = fidelity.audit(value)
        self.assertEqual("undetermined", out["assertions"][0]["relation"])
        self.assertIn("basis_not_explicit", self.codes(out))

    def test_inferred_and_proposed_facts_cannot_self_certify_support(self):
        for state in ["inferred", "proposal", "conflicting"]:
            with self.subTest(state=state):
                value = example()
                value["facts"][0]["state"] = state
                self.assertIn("basis_not_explicit", self.codes(fidelity.audit(value)))

    def test_product_confirmation_does_not_become_original_disclosure(self):
        value = example()
        value["documents"][0]["role"] = "product"
        self.assertIn("basis_not_original", self.codes(fidelity.audit(value)))

    def test_product_can_be_used_for_bounded_technical_consistency(self):
        value = example()
        value["documents"][0]["role"] = "product"
        value["assertions"][0]["proof_scope"] = "technical_consistency"
        self.assertEqual("checked", fidelity.audit(value)["status"])

    def test_inconsistent_basis_is_not_vacuous_proof(self):
        value = example()
        value["facts"][0]["formula"] = {"all": ["release", {"not": "release"}]}
        out = fidelity.audit(value)
        self.assertIn("inconsistent_basis", self.codes(out))
        self.assertEqual("inconsistent", out["assertions"][0]["relation"])

    def test_conflicting_explicit_facts_cannot_be_hidden_by_basis_selection(self):
        value = example()
        value["facts"] += [{"id": "F2", "state": "explicit", "citation": value["facts"][0]["citation"],
                             "formula": "release"},
                            {"id": "F3", "state": "explicit", "citation": value["facts"][0]["citation"],
                             "formula": {"not": "permission"}}]
        self.assertIn("explicit_facts_inconsistent", self.codes(fidelity.audit(value)))

    def test_a_different_time_scope_is_not_implicitly_equated(self):
        value = example()
        value["atoms"].append({"id": "later_permission", "meaning": "许可成立", "scope": "下一个发布事件"})
        value["assertions"][0]["formula"] = {"implies": ["release", "later_permission"]}
        self.assertEqual("undetermined", fidelity.audit(value)["assertions"][0]["relation"])

    def test_unreachable_antecedent_is_flagged(self):
        value = example()
        value["facts"][0]["formula"] = {"not": "release"}
        self.assertIn("vacuous_assertion", self.codes(fidelity.audit(value)))

    def test_opposite_assertion_is_contradicted(self):
        value = example()
        value["facts"][0]["formula"] = "permission"
        value["assertions"][0]["formula"] = {"not": "permission"}
        self.assertEqual("contradicted", fidelity.audit(value)["assertions"][0]["relation"])

    def test_document_bytes_and_citation_offsets_are_bound(self):
        for edit, code in [(lambda p: p["documents"][0].update(sha256="0" * 64), "document_hash_mismatch"),
                           (lambda p: p["facts"][0]["citation"].update(quote="伪造引文"), "citation_quote_mismatch"),
                           (lambda p: p["facts"][0]["citation"].update(start=True), "citation_offsets_required")]:
            with self.subTest(code=code):
                value = example(); edit(value)
                with self.assertRaisesRegex(ContractError, code): fidelity.audit(value)

    def test_duplicate_or_unknown_identifiers_are_rejected(self):
        value = example(); value["atoms"].append(copy.deepcopy(value["atoms"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate_atom"): fidelity.audit(value)
        value = example(); value["assertions"][0]["basis_fact_ids"] = ["missing"]
        with self.assertRaisesRegex(ContractError, "basis_fact_unknown"): fidelity.audit(value)

    def test_unknown_operator_and_bounded_formula_are_rejected(self):
        for formula in [{"execute": "anything"}, {"implies": ["release"]}, {"all": []}, "missing"]:
            with self.subTest(formula=formula):
                value = example(); value["facts"][0]["formula"] = formula
                with self.assertRaises(ContractError): fidelity.audit(value)
        value = example()
        for i in range(20): value["atoms"].append({"id": f"v{i}", "meaning": "x", "scope": "x"})
        with self.assertRaisesRegex(ContractError, "atom_budget_exceeded"): fidelity.audit(value)

    def test_invalid_text_encoding_and_excessive_nesting_are_contract_errors(self):
        value = example();value["documents"][0]["text"] = "\ud800"
        with self.assertRaisesRegex(ContractError, "fidelity_text_encoding_invalid"):fidelity.audit(value)
        value = example();expr = "release"
        for _ in range(1200):expr = {"not": expr}
        value["facts"][0]["formula"] = expr
        with self.assertRaisesRegex(ContractError, "fidelity_input_nesting_exceeded"):fidelity.audit(value)

    def test_unmapped_actual_paragraph_is_detected(self):
        value = example()
        value["documents"][1] = document("D", "candidate", value["documents"][1]["text"] + "另有自动重启。")
        self.assertIn("candidate_region_unmapped", self.codes(fidelity.audit(value)))

    def test_technical_region_requires_a_bound_assertion(self):
        value = example(); value["regions"][0]["assertion_ids"] = []
        self.assertIn("technical_region_unchecked", self.codes(fidelity.audit(value)))

    def test_context_labels_cannot_hide_unlinked_candidate_assertions(self):
        value = example();value["regions"][0].update(kind="context", assertion_ids=[], reason="标题")
        self.assertIn("candidate_assertion_region_missing", self.codes(fidelity.audit(value)))

    def test_tautology_without_original_basis_is_not_original_support(self):
        value = example();value["facts"] = [];value["assertions"][0]["basis_fact_ids"] = []
        value["assertions"][0]["formula"] = {"implies": ["release", "release"]}
        self.assertIn("original_basis_missing", self.codes(fidelity.audit(value)))

    def test_assertion_cannot_point_outside_its_region(self):
        value = example(); value["regions"][0]["citation"] = citation(value["documents"][1], 0, 2)
        self.assertIn("assertion_outside_region", self.codes(fidelity.audit(value)))

    def test_internal_proposal_is_distinguished_from_supported_candidate(self):
        value = example(); value["assertions"][0]["mode"] = "proposal"
        self.assertIn("proposal_in_candidate", self.codes(fidelity.audit(value)))
        value["documents"][1]["role"] = "internal"
        self.assertEqual("needs_review", fidelity.audit(value)["status"])

    def parameter_case(self):
        value = example()
        value["documents"][0] = document("O", "original", value["documents"][0]["text"] +
                                         "容量参数C是正整数；4仅为一个配置示例。")
        request = document("Q", "source", "请评估将参数C具体化为12的修改。")
        internal = document("N", "internal", "可实现性尚无运行数据。实现覆盖须核其他条件。修改支持须核原始参数域、作用效果、组合及具体值的确定依据；若均可由原文确定再考虑该路线，否则保留参数稿。")
        value["documents"] += [request, internal]
        value["parameter_requests"] = [{"id": "P1", "symbol": "C", "citation": citation(request)}]
        reasoning = citation(internal)
        aspect = {"status": "conditional", "reasoning": reasoning, "conditions": ["取得当前原文及技术依据"]}
        support = copy.deepcopy(aspect)
        support["original_citations"] = [citation(value["documents"][0])]
        support["considerations"] = {key: reasoning for key in
            ["parameter_domain", "function_and_effect", "combination", "individualization"]}
        value["parameter_assessments"] = [{"request_id": "P1", "technical_feasibility": copy.deepcopy(aspect),
            "implementation_coverage": copy.deepcopy(aspect), "original_amendment_support": support}]
        return value

    def test_parameter_request_cannot_omit_amendment_support_assessment(self):
        value = self.parameter_case()
        del value["parameter_assessments"][0]["original_amendment_support"]
        self.assertIn("parameter_aspect_missing", self.codes(fidelity.audit(value)))

    def test_parameter_coverage_is_not_amendment_support(self):
        value = self.parameter_case()
        value["parameter_assessments"][0]["original_amendment_support"] = copy.deepcopy(
            value["parameter_assessments"][0]["implementation_coverage"])
        self.assertIn("parameter_support_context_missing", self.codes(fidelity.audit(value)))

    def test_conditional_parameter_analysis_can_be_recorded_without_certification(self):
        out = fidelity.audit(self.parameter_case())
        self.assertEqual("checked", out["status"])
        self.assertEqual("not_verified", out["parameter_assessments"][0]["professional_support"])

    def test_parameter_positive_claim_does_not_certify_legal_support(self):
        value = self.parameter_case()
        value["parameter_assessments"][0]["original_amendment_support"]["status"] = "candidate_supported"
        out = fidelity.audit(value)
        self.assertEqual("not_verified", out["parameter_assessments"][0]["professional_support"])

    def test_product_quote_cannot_replace_original_parameter_evidence(self):
        value = self.parameter_case()
        value["documents"][0]["role"] = "product"
        self.assertIn("parameter_original_source_required", self.codes(fidelity.audit(value)))

    def test_parameter_omitted_request_and_duplicate_assessment_are_visible(self):
        value = self.parameter_case(); value["parameter_assessments"] = []
        self.assertIn("parameter_assessment_missing", self.codes(fidelity.audit(value)))
        value = self.parameter_case();value["parameter_assessments"] *= 2
        with self.assertRaisesRegex(ContractError, "duplicate_parameter_assessment"):fidelity.audit(value)

    def test_existing_patent_consumer_propagates_fidelity_failure(self):
        from tools.patent import run
        value = example();value["assertions"][0]["formula"] = {"implies": ["permission", "release"]}
        payload = {"sensitivity": "synthetic", "adaptation": {"jurisdiction": "unverified",
            "right_type": "invention", "domain": "synthetic", "stage": "draft"},
            "features": [{"id": "F", "text": "已给特征"}],
            "original": {"id": "O", "version": "1", "features": [{"id": "F", "text": "已给特征"}]},
            "fidelity": value}
        out = run("REVIEW-02", payload)
        self.assertEqual("blocked", out["status"])
        self.assertIn("fidelity", out["artifacts"])
        self.assertEqual("not_performed", out["professional_review"])

    def test_generated_markdown_cannot_be_replaced_by_an_unrelated_good_candidate(self):
        from tools.patent import run
        payload = {"sensitivity": "synthetic", "adaptation": {"jurisdiction": "unverified",
            "right_type": "invention", "domain": "synthetic", "stage": "draft"},
            "features": [{"id": "F", "text": "实际生成的另一段技术限定", "evidence_id": "O"}],
            "claims": [{"id": 1, "category": "method", "depends_on": [], "feature_ids": ["F"]}],
            "fidelity": example()}
        out = run("DRAFT-02", payload)
        self.assertEqual("blocked", out["status"])
        self.assertIn("generated_artifact_not_in_fidelity", {x["code"] for x in out["issues"]})


if __name__ == "__main__":
    unittest.main()
