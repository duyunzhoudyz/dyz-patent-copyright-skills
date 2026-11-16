"""单来源记载不能借用别的材料；组合分析及真实文件消费者另核。"""
import json
import tempfile
from pathlib import Path
import unittest

from evals.test_fidelity import citation, document
from tools import documents, fidelity
from tools.core import ContractError, sha256_bytes


def attribution_case():
    product = document("P", "product", "本设计进行温度采样。")
    reference = document("R", "source", "资料甲描述环形缓存。", version="2")
    candidate = document("C", "candidate", "资料甲记载温度采样。")
    return {
        "documents": [product, reference, candidate],
        "atoms": [
            {"id": "sampling", "meaning": "待比较设计的温度采样特征", "scope": "本次给定技术集合"},
            {"id": "buffer", "meaning": "待比较设计的环形缓存特征", "scope": "本次给定技术集合"},
        ],
        "facts": [
            {"id": "F-P", "state": "explicit", "citation": citation(product), "formula": "sampling"},
            {"id": "F-R", "state": "explicit", "citation": citation(reference), "formula": "buffer"},
        ],
        "assertions": [{"id": "A", "citation": citation(candidate), "formula": "sampling",
                        "basis_fact_ids": ["F-P"], "proof_scope": "technical_consistency",
                        "mode": "asserted", "attributed_document_id": "R"}],
        "regions": [{"id": "T", "citation": citation(candidate), "kind": "technical",
                     "assertion_ids": ["A"]}],
        "parameter_requests": [], "parameter_assessments": [],
    }


def set_candidate(value, text):
    value["documents"][2] = document("C", "candidate", text)
    value["assertions"][0]["citation"] = citation(value["documents"][2])
    value["regions"][0]["citation"] = citation(value["documents"][2])


def supported_case():
    value = attribution_case()
    set_candidate(value, "资料甲描述环形缓存。")
    value["assertions"][0].update(formula="buffer", basis_fact_ids=["F-R"])
    return value


class FidelityAttributionTests(unittest.TestCase):
    def codes(self, output):
        return {row["code"] for row in output["issues"]}

    def test_product_truth_does_not_establish_reference_disclosure(self):
        out = fidelity.audit(attribution_case())
        self.assertEqual("blocked", out["status"])
        self.assertIn("basis_attribution_mismatch", self.codes(out))
        self.assertEqual([], out["assertions"][0]["accepted_basis_fact_ids"])

    def test_same_document_role_does_not_merge_source_identity(self):
        value = attribution_case()
        value["documents"][0]["role"] = "source"
        self.assertIn("basis_attribution_mismatch", self.codes(fidelity.audit(value)))

    def test_explicit_single_source_is_accepted_and_target_is_reported(self):
        out = fidelity.audit(supported_case())
        self.assertEqual("checked", out["status"])
        self.assertEqual("R", out["assertions"][0]["attributed_document_id"])
        self.assertEqual(["F-R"], out["assertions"][0]["accepted_basis_fact_ids"])
        self.assertFalse(out["natural_language_verified"])
        self.assertEqual("not_performed", out["professional_review"])

    def test_matching_identity_does_not_fill_an_unstated_detail(self):
        value = attribution_case()
        value["assertions"][0]["basis_fact_ids"] = ["F-R"]
        out = fidelity.audit(value)
        self.assertEqual("blocked", out["status"])
        self.assertIn("assertion_not_entailed", self.codes(out))
        self.assertNotIn("basis_attribution_mismatch", self.codes(out))
        self.assertFalse(out["assertions"][0]["countermodel"]["sampling"])

    def test_mixed_basis_is_flagged_even_when_target_already_entails(self):
        value = supported_case()
        value["assertions"][0]["basis_fact_ids"].append("F-P")
        out = fidelity.audit(value)
        self.assertEqual("blocked", out["status"])
        self.assertEqual("entailed", out["assertions"][0]["relation"])
        self.assertEqual(["F-R"], out["assertions"][0]["accepted_basis_fact_ids"])
        self.assertIn("basis_attribution_mismatch", self.codes(out))

    def test_unattributed_synthesis_can_use_both_sources(self):
        value = attribution_case()
        set_candidate(value, "本设计进行温度采样；资料甲描述环形缓存。")
        assertion = value["assertions"][0]
        del assertion["attributed_document_id"]
        assertion.update(formula={"all": ["sampling", "buffer"]}, basis_fact_ids=["F-P", "F-R"])
        out = fidelity.audit(value)
        self.assertEqual("checked", out["status"])
        self.assertEqual(["F-P", "F-R"], out["assertions"][0]["accepted_basis_fact_ids"])

    def test_internal_open_question_remains_review_instead_of_a_supported_fact(self):
        value = attribution_case()
        value["documents"][2]["role"] = "internal"
        value["assertions"][0]["mode"] = "open_question"
        out = fidelity.audit(value)
        self.assertEqual("needs_review", out["status"])
        self.assertTrue(all(row["severity"] == "review" for row in out["issues"]))
        self.assertIn("basis_attribution_mismatch", self.codes(out))

    def test_invalid_or_unknown_target_is_not_silently_ignored(self):
        for target in (None, [], "", "missing"):
            with self.subTest(target=target):
                value = supported_case()
                value["assertions"][0]["attributed_document_id"] = target
                with self.assertRaises(ContractError):
                    fidelity.audit(value)

    def test_candidate_or_internal_target_is_not_a_source(self):
        for target in ("C", "I"):
            with self.subTest(target=target):
                value = supported_case()
                value["documents"].append(document("I", "internal", "内部推论。"))
                value["assertions"][0]["attributed_document_id"] = target
                with self.assertRaisesRegex(ContractError, "attributed_document_role_invalid"):
                    fidelity.audit(value)

    def test_attribution_does_not_bypass_original_application_role(self):
        value = supported_case()
        value["assertions"][0]["proof_scope"] = "original_support"
        self.assertIn("basis_not_original", self.codes(fidelity.audit(value)))

    def document_spec(self, root, value):
        candidate = value["documents"][2]
        raw = candidate["text"].encode("utf-8")
        (root / "body.md").write_bytes(raw)
        return {"sensitivity": "synthetic", "document_id": "AttributionDraft", "version": "1",
                "business": "patent", "sources": [{"id": "C", "path": "body.md", "sha256": sha256_bytes(raw)}],
                "blocks": [{"id": "B", "source_id": "C", "kind": "paragraph", "audience": "body",
                            "start_line": 1, "end_line": 1}],
                "fidelity": {"payload": value, "blocks": {"B": citation(candidate)}}}

    def test_real_document_build_rejects_attribution_before_creating_output(self):
        with tempfile.TemporaryDirectory(prefix="dyz-attribution-") as temp:
            root = Path(temp)
            spec = self.document_spec(root, attribution_case())
            with self.assertRaisesRegex(ContractError, "document_fidelity_blocked"):
                documents.build(root, spec, "pack", synthetic=True)
            self.assertFalse((root / "pack").exists())

    def test_correct_attribution_survives_build_and_actual_docx_recheck(self):
        with tempfile.TemporaryDirectory(prefix="dyz-attribution-") as temp:
            root = Path(temp)
            spec = self.document_spec(root, supported_case())
            built = documents.build(root, spec, "pack", synthetic=True)
            checked = documents.verify(root, spec, "pack", synthetic=True)
            self.assertEqual("checked", built["fidelity"]["status"])
            self.assertEqual(built["fidelity"], checked["fidelity"])
            report = json.loads((root / "pack/internal/fidelity-review.json").read_text(encoding="utf-8"))
            self.assertEqual("R", report["assertions"][0]["attributed_document_id"])


if __name__ == "__main__":
    unittest.main()
