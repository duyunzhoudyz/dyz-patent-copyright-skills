"""专利AC的合成确定性分支；不构成专业验收。"""
import copy
import json
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from tools.core import ContractError, digest
from tools.patent import CAPABILITIES, run


def envelope(**data):
    return {"sensitivity": "synthetic", "adaptation": {
        "jurisdiction": "unverified", "right_type": "invention",
        "domain": "synthetic-control", "stage": "internal_draft"}, **data}


def document(identifier="D1", **changes):
    return {"id": identifier, "version": "1", "title": "温度控制",
            "kind": "patent", "abstract": "采集温度", "family": "F1",
            "jurisdiction": "CN", "public_at": "2000-01-01",
            "acquired_at": "2026-10-31", "archived_at": "2020-01-01",
            "publication_evidence": "date-evidence",
            "sections": [{"locator": "p1", "text": "采集温度并停止加热。"}],
            "claims": ["采集温度"], "legal_status": "unknown", **changes}


def search_payload(**changes):
    return envelope(query={"groups": [["温度"]]}, sources=[
        {"id": "local", "status": "ok", "local_use": True,
         "documents": [document()]}], **changes)


def claims():
    return [{"id": 1, "category": "method", "depends_on": [],
             "feature_ids": ["f1"], "introduces": ["传感器"], "uses": []},
            {"id": 2, "category": "method", "depends_on": [1],
             "feature_ids": ["f2"], "introduces": ["阈值"], "uses": ["传感器"]}]


def features():
    return [{"id": "f1", "text": "采集温度", "evidence_id": "ev1"},
            {"id": "f2", "text": "停止加热", "evidence_id": "ev2"}]


def support_payload():
    return envelope(features=features(), original={"id": "filed-v1",
        "version": "1", "features": features(), "combinations": [["f1", "f2"]]},
        combinations=[["f1", "f2"]])


def flow_payload():
    return envelope(nodes=[{"id": "s", "label": "开始", "kind": "start"},
        {"id": "d", "label": "温度是否过高", "kind": "decision"},
        {"id": "ok", "label": "继续", "kind": "end"},
        {"id": "fail", "label": "停止加热", "kind": "end"}], edges=[
        {"from": "s", "to": "d", "label": "采集"},
        {"from": "d", "to": "ok", "label": "否", "outcome": "success"},
        {"from": "d", "to": "fail", "label": "是", "outcome": "failure"}])


class PatentOutputQualityTests(unittest.TestCase):
    def draft(self, text):
        return envelope(claims=claims()[:1], features=[{
            "id": "f1", "text": text, "evidence_id": "synthetic-source"}])

    def test_actual_markdown_is_scanned_without_optional_fidelity(self):
        out = run("DRAFT-02", self.draft("采集温度。[待确认：阈值来源]"))
        self.assertEqual("blocked", out["status"])
        self.assertEqual("blocked", out["artifacts"]["text_quality"]["status"])
        self.assertEqual("not_performed", out["artifacts"]["fidelity"]["status"])
        self.assertIn("阈值来源", out["artifacts"]["markdown"])

    def test_clean_draft_does_not_claim_semantic_or_professional_review(self):
        out = run("DRAFT-02", self.draft("采集温度"))
        self.assertEqual("draft", out["status"])
        self.assertEqual("checked", out["artifacts"]["text_quality"]["status"])
        self.assertEqual("not_performed", out["artifacts"]["fidelity"]["status"])
        self.assertEqual("not_performed", out["professional_review"])

    def test_analysis_without_text_reports_not_performed_not_an_empty_pass(self):
        out = run("REVIEW-01", envelope(claims=claims()))
        self.assertEqual("not_performed", out["artifacts"]["text_quality"]["status"])
        self.assertEqual("no_deliverable_text", out["artifacts"]["text_quality"]["reason"])

    def test_actual_generated_svg_is_scanned(self):
        p = flow_payload()
        p["nodes"][1]["label"] = "[待确认：动作条件]"
        out = run("FIG-01", p)
        self.assertEqual("blocked", out["status"])
        self.assertEqual("svg", out["artifacts"]["text_quality"]["issues"][0]["block_id"])

    def test_edit_checks_returned_text_without_automatically_rewriting_it(self):
        text = "阈值[待确认：阈值来源]。"
        out = run("REVIEW-05", envelope(original=text))
        self.assertEqual(text, out["artifacts"]["accepted_text"])
        self.assertEqual("blocked", out["status"])

    def test_matching_resolution_does_not_exempt_actual_residual_marker(self):
        from evals.test_fidelity_placeholders import bound_case
        p = self.draft("采集温度。[待确认：阈值来源]")
        text = run("DRAFT-02", p)["artifacts"]["markdown"]
        review, _, _ = bound_case(text, resolved=[{
            "id": "markdown#" + str(text.index("[")),
            "resolution_source": "1", "reviewer": "合成技术负责人"}])
        p["fidelity"] = review
        out = run("DRAFT-02", p)
        self.assertEqual("blocked", out["status"])
        self.assertEqual("checked", out["artifacts"]["fidelity"]["placeholders"]["status"])
        self.assertEqual("blocked", out["artifacts"]["text_quality"]["status"])
        self.assertEqual("markdown", out["artifacts"]["fidelity"]["artifact_bindings"][0]["artifact_id"])

    def test_binding_mismatch_still_scans_the_actual_wrong_text(self):
        from evals.test_fidelity_placeholders import bound_case
        p = self.draft("采集温度。[待确认：阈值来源]")
        p["fidelity"] = bound_case("另一份正确的示范稿。")[0]
        out = run("DRAFT-02", p)
        self.assertEqual("blocked", out["status"])
        self.assertIn("generated_artifact_not_in_fidelity", codes(out))
        self.assertIn("placeholder_remaining_in_artifact", codes(out))

    def test_phrasing_is_review_only_and_text_is_preserved(self):
        out = run("DRAFT-02", self.draft("本方案验证通过"))
        quality = out["artifacts"]["text_quality"]
        self.assertEqual("needs_review", quality["status"])
        self.assertTrue(all(row["severity"] == "review" for row in quality["issues"]))
        self.assertNotEqual("blocked", out["status"])
        self.assertIn("本方案验证通过", out["artifacts"]["markdown"])


class PatentFinalDeliveryGateTests(unittest.TestCase):
    def final_payload(self, text, source=None):
        from evals.test_fidelity import document
        return envelope(claims=claims()[:1], features=[{
            "id": "f1", "text": text, "evidence_id": "original-1"}],
            delivery_stage="final", final_text_sources=[document(
                "Original", "original", text if source is None else source)])

    def test_final_actual_markdown_is_checked_before_return(self):
        text = "只有记录已写入持久介质，才允许返回成功确认"
        result = run("DRAFT-02", self.final_payload(text))
        gate = result["artifacts"]["final_text_gate"]
        self.assertEqual("checked", gate["status"])
        self.assertEqual("1. 一种method方案，" + text + "。", result["artifacts"]["markdown"])
        self.assertFalse(gate["natural_language_verified"])

    def test_final_reversed_actual_text_raises_instead_of_returning_candidate(self):
        original = "只有记录已写入持久介质，才允许返回成功确认"
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            run("DRAFT-02", self.final_payload(
                "一旦记录已写入持久介质，就允许返回成功确认", original))

    def test_final_without_gate_sources_does_not_return_candidate(self):
        p = self.final_payload("传感器每秒采样")
        del p["final_text_sources"]
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            run("DRAFT-02", p)

    def test_final_generated_claim_keeps_typed_members_and_conditions(self):
        from evals.test_patent_gate_fulltext import load_case
        raw, fixture = load_case("mechanical")
        text = raw.decode("utf-8").split("1. ", 1)[1].split("\n\n## 具体实施方式", 1)[0]
        payload = self.final_payload(text)
        payload["final_text_sources"] = fixture["documents"]
        result = run("DRAFT-02", payload)
        self.assertEqual("checked", result["artifacts"]["final_text_gate"]["status"])
        self.assertIn(text, result["artifacts"]["markdown"])
        changed = self.final_payload(text.replace("两条平行导轨", "三条平行导轨"))
        changed["final_text_sources"] = fixture["documents"]
        with self.assertRaisesRegex(ContractError, "final_text_gate_blocked"):
            run("DRAFT-02", changed)

    def test_draft_has_no_unearned_delivery_permission(self):
        p = self.final_payload("传感器每秒采样")
        del p["delivery_stage"]
        del p["final_text_sources"]
        self.assertFalse(run("DRAFT-02", p)["artifacts"]["final_text_gate"]["delivery_allowed"])


class PatentSupportChainTests(unittest.TestCase):
    def draft_review(self, text, source, atoms, premise, conclusion):
        from evals.test_fidelity import citation, document
        from evals.test_fidelity_placeholders import bound_case
        p = envelope(claims=claims()[:1], features=[
            {"id": "f1", "text": text, "evidence_id": "synthetic-original"}])
        actual = run("DRAFT-02", p)["artifacts"]["markdown"]
        review = bound_case(actual)[0]
        original = document("O", "original", source)
        review["documents"][0] = original
        review["atoms"] = [{"id": key, "meaning": meaning, "scope": "本次合成控制周期"}
                           for key, meaning in atoms.items()]
        review["facts"][0].update(citation=citation(original), formula=premise)
        review["assertions"][0]["formula"] = conclusion
        p["fidelity"] = review
        return p

    def test_unknown_middle_action_is_rejected_in_the_actual_claim(self):
        p = self.draft_review("中间区间保持阀位", "高于上限时关阀；中间区间动作未知。",
            {"high": "高于上限", "close": "关阀", "middle": "中间区间", "hold": "保持阀位"},
            {"implies": ["high", "close"]}, {"implies": ["middle", "hold"]})
        out = run("DRAFT-02", p)
        self.assertEqual("blocked", out["status"])
        self.assertEqual("undetermined", out["artifacts"]["fidelity"]["assertions"][0]["relation"])
        self.assertEqual("markdown", out["artifacts"]["fidelity"]["artifact_bindings"][0]["artifact_id"])

    def test_reset_prerequisite_does_not_invent_waiting_action(self):
        p = self.draft_review("未复位时继续输出", "只有人工复位后才允许恢复；等待动作未知。",
            {"reset": "人工复位", "resume": "恢复", "output": "继续输出"},
            {"implies": ["resume", "reset"]}, {"implies": [{"not": "reset"}, "output"]})
        out = run("DRAFT-02", p)
        self.assertEqual("blocked", out["status"])
        self.assertIn("assertion_not_entailed", codes(out))

    def test_necessary_condition_is_not_a_sufficient_trigger(self):
        p = self.draft_review("检测许可后即启动", "只有取得许可时才允许启动。",
            {"permission": "取得许可", "start": "启动"},
            {"implies": ["start", "permission"]}, {"implies": ["permission", "start"]})
        self.assertEqual("blocked", run("DRAFT-02", p)["status"])
        p["fidelity"]["assertions"][0]["formula"] = {"implies": ["start", "permission"]}
        checked = run("DRAFT-02", p)["artifacts"]["fidelity"]
        # 人为改JSON虽能满足模型，不能被描述为自然语言解释已经正确。
        self.assertEqual("checked", checked["status"])
        self.assertFalse(checked["natural_language_verified"])

    def test_separate_features_do_not_prove_the_added_relation(self):
        p = self.draft_review("传感器经缓存控制阀门", "含传感器和缓存，连接关系未给出。",
            {"sensor": "传感器", "buffer": "缓存", "linked": "传感器经缓存控制阀门"},
            {"all": ["sensor", "buffer"]}, {"all": ["sensor", "buffer", "linked"]})
        self.assertIn("assertion_not_entailed", codes(run("DRAFT-02", p)))

    def test_concrete_parameter_keeps_three_aspects_and_four_considerations(self):
        from evals.test_fidelity import FidelityTests, citation, document
        for missing in ("original_amendment_support", "individualization"):
            with self.subTest(missing=missing):
                p = envelope(claims=claims()[:1], features=[
                    {"id": "f1", "text": "具体容量采用32", "evidence_id": "synthetic-original"}])
                review = FidelityTests().parameter_case()
                candidate = document("D", "candidate", run("DRAFT-02", p)["artifacts"]["markdown"])
                review["documents"][1] = candidate
                review["assertions"][0]["citation"] = citation(candidate)
                review["regions"][0]["citation"] = citation(candidate)
                row = review["parameter_assessments"][0]
                if missing == "original_amendment_support":
                    del row[missing]
                else:
                    del row["original_amendment_support"]["considerations"][missing]
                p["fidelity"] = review
                out = run("DRAFT-02", p)
                self.assertEqual("blocked", out["status"])
                self.assertTrue(any(code.startswith("parameter_") for code in codes(out)))

    def test_missing_candidate_id_is_a_contract_error_not_key_error(self):
        from evals.test_fidelity_placeholders import bound_case
        p = envelope(claims=claims()[:1], features=features()[:1])
        p["fidelity"] = bound_case(run("DRAFT-02", p)["artifacts"]["markdown"])[0]
        del p["fidelity"]["documents"][1]["id"]
        with self.assertRaises(ContractError):
            run("DRAFT-02", p)


class SearchTests(unittest.TestCase):
    def test_ac_search_01_failure_zero_and_pagination(self):
        payload = search_payload(page_size=1, max_pages=1)
        payload["sources"][0]["documents"].append(document("D2"))
        payload["sources"] += [
            {"id": "zero", "status": "ok", "local_use": True, "documents": []},
            {"id": "down", "status": "unavailable"},
            {"id": "denied", "status": "permission_denied"}]
        out = run("SEARCH-01", payload)
        logs = {x["source_id"]: x for x in out["artifacts"]["coverage"]}
        self.assertEqual(logs["zero"]["stop_reason"], "zero_hits")
        self.assertEqual(logs["down"]["stop_reason"], "unavailable")
        self.assertEqual(logs["local"]["stop_reason"], "page_budget")
        self.assertEqual(len(out["artifacts"]["documents"]), 1)
        self.assertEqual(out["status"], "partial")

    def test_unconfigured_timeout_and_budget_are_blocked_report_not_zero_hits(self):
        for state in ("not_configured", "timeout", "budget_exhausted"):
            with self.subTest(state=state):
                p = search_payload()
                p["sources"] = [{"id": "offline-record", "status": state,
                                 "documents": "must-not-be-processed"}]
                result = run("SEARCH-06", p)
                self.assertEqual(result["status"], "blocked")
                artifacts = result["artifacts"]
                self.assertEqual(artifacts["network_requests"], 0)
                self.assertEqual(artifacts["documents"], [])
                self.assertIsNone(artifacts["coverage"][0]["matched"])
                self.assertFalse(artifacts["coverage"][0]["collection_complete"])
                self.assertIn(state, artifacts["report"])
                self.assertNotIn("zero_hits", artifacts["report"])
                self.assertFalse(artifacts["qualified_search_report"])

    def test_search_source_states_are_not_zero_hits(self):
        states = ("unavailable", "permission_denied", "rate_limited", "network_error",
                  "login_failed", "unknown", "not_checked", "not_configured", "timeout",
                  "budget_exhausted")
        for state in states:
            with self.subTest(state=state):
                p = search_payload()
                p["sources"].append({"id": "missing", "status": state, "scope": "fixture-scope",
                                     "documents": "must-not-be-processed"})
                out = run("SEARCH-01", p)
                row = out["artifacts"]["coverage"][1]
                self.assertEqual(row["source_status"], state)
                self.assertEqual(row["stop_reason"], state)
                self.assertEqual(row["scope"], "fixture-scope")
                self.assertIsNone(row["matched"])
                self.assertIsNone(row["omitted_matches"])
                self.assertFalse(row["collection_complete"])
                self.assertEqual(out["status"], "partial")
                self.assertEqual(len(out["artifacts"]["documents"]), 1)
                p["sources"] = p["sources"][1:]
                self.assertEqual(run("SEARCH-01", p)["status"], "blocked")

    def test_search_source_not_applicable_requires_explicit_basis(self):
        source = {"id": "excluded", "status": "not_applicable",
                  "reason": "合成专题不涉及该资料类型", "evidence_id": "scope-v1"}
        out = run("SEARCH-01", envelope(sources=[source]))
        self.assertEqual(out["status"], "not_applicable")
        row = out["artifacts"]["coverage"][0]
        self.assertEqual(row["reason"], source["reason"])
        self.assertEqual(row["evidence_id"], "scope-v1")
        self.assertIsNone(row["matched"])
        p = search_payload()
        p["sources"].append(source)
        self.assertEqual(run("SEARCH-01", p)["status"], "needs_review")
        for key in ("reason", "evidence_id"):
            for value in (None, "", " ", [], True):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ContractError):
                        run("SEARCH-01", envelope(sources=[{**source, key: value}]))

    def test_partial_source_preserves_page_budget_and_unknown_total(self):
        p = search_payload(page_size=1, max_pages=1)
        p["sources"][0].update(status="partial", documents=[document(), document("D2")])
        row = run("SEARCH-01", p)["artifacts"]["coverage"][0]
        self.assertEqual(row["stop_reason"], "source_partial")
        self.assertEqual(row["stop_reasons"], ["source_partial", "page_budget"])
        self.assertEqual(row["matched"], 2)
        self.assertEqual(row["omitted_matches"], 1)
        self.assertFalse(row["collection_complete"])
        p["sources"][0].update(status="ok", documents=[])
        row = run("SEARCH-01", p)["artifacts"]["coverage"][0]
        self.assertEqual(row["stop_reasons"], ["zero_hits"])
        self.assertTrue(row["collection_complete"])
        self.assertEqual(row["omitted_matches"], 0)
        p["sources"][0]["local_use"] = False
        row = run("SEARCH-01", p)["artifacts"]["coverage"][0]
        self.assertEqual(row["source_status"], "ok")
        self.assertEqual(row["stop_reason"], "permission_denied")
        self.assertIsNone(row["matched"])

    def test_search_report_preserves_query_coverage_dates_and_gaps(self):
        p = search_payload(page_size=1, max_pages=1, critical_date="2010-01-01")
        p["sources"][0]["documents"].append(document("D2"))
        p["sources"] += [
            {"id": "npl", "status": "ok", "local_use": True, "documents": [
                document(kind="npl", version="2", public_at=None, sections=[])]},
            {"id": "down", "status": "network_error"},
            {"id": "zero", "status": "ok", "local_use": True, "documents": []}]
        out = run("SEARCH-06", p)
        artifacts = out["artifacts"]
        report = artifacts["report"]
        for token in ("温度", "page_budget", "network_error", "zero_hits", "local", "npl",
                      "2000-01-01", "2026-10-31", "2020-01-01", "2010-01-01",
                      "date-evidence", "unknown", "fulltext_missing", "date_evidence_missing",
                      "coverage_incomplete", "source_unavailable", "p1"):
            self.assertIn(token, report)
        self.assertIn("组间AND、组内OR", report)
        self.assertIn("每页1条，最多1页", report)
        self.assertIn("不构成新颖性、创造性或法律可用性结论", report)
        self.assertFalse(artifacts["qualified_search_report"])
        self.assertEqual(artifacts["network_requests"], 0)
        self.assertEqual([(r["collection_source"], r["document_id"], r["version"])
                          for r in artifacts["date_matrix"]], [("local", "D1", "1"), ("npl", "D1", "2")])
        missing = [i for i in out["issues"] if i["code"] == "date_evidence_missing"]
        self.assertEqual(missing[0]["source_id"], "npl")
        self.assertEqual(missing[0]["version"], "2")
        self.assertEqual(out["status"], "partial")

    def test_search_report_unknown_date_even_when_no_hits(self):
        p = search_payload()
        p["sources"][0]["documents"] = []
        out = run("SEARCH-06", p)
        self.assertIn("critical_date_missing", codes(out))
        self.assertIn("critical_date_missing", out["artifacts"]["report"])
        self.assertIn("zero_hits", out["artifacts"]["report"])
        self.assertEqual(out["status"], "partial")
        p["sources"] = [{"id": "down", "status": "unavailable"}]
        out = run("SEARCH-06", p)
        self.assertEqual(out["status"], "blocked")
        self.assertIn("unavailable", out["artifacts"]["report"])

    def test_search_report_is_safe_text_and_keeps_source_versions(self):
        title = '<script>alert("synthetic")</script>\n## 假标题 | [链接](https://example.invalid)'
        p = search_payload(critical_date="2010-01-01")
        p["sources"][0]["documents"] = [document(title=title)]
        original = copy.deepcopy(p)
        out = run("SEARCH-06", p)
        report = out["artifacts"]["report"]
        self.assertNotIn("<script>", report)
        self.assertNotIn("\n## 假标题", report)
        self.assertNotIn("[链接](https://example.invalid)", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertEqual(out["artifacts"]["documents"][0]["title"], title)
        self.assertEqual(p, original)
        self.assertEqual(out, run("SEARCH-06", p))
        p["previous_input_hash"] = out["artifacts"]["input_hash"]
        p["sources"][0]["documents"][0]["version"] = "2"
        changed = run("SEARCH-06", p)
        self.assertIn("input_changed_re_review", codes(changed))
        self.assertFalse(changed["artifacts"]["review_inherited"])

    def test_ac_search_02_strategy_languages_and_operator(self):
        out = run("SEARCH-02", envelope(concepts=[{"id": "c1", "terms": {
            "zh": ["温度"], "en": ["temperature", "thermal"]}}],
            operators=["NEAR"], applicants=[{"name": "同名主体", "entity_id": "A"}]))
        self.assertEqual(out["artifacts"]["query"]["groups"][0],
                         ["温度", "temperature", "thermal"])
        self.assertIn("unsupported_operator", codes(out))
        self.assertEqual(out["artifacts"]["applicants"][0]["entity_id"], "A")

    def test_ac_search_03_dates_do_not_use_archive_as_publication(self):
        p = search_payload(critical_date="2010-01-01")
        p["sources"][0]["documents"] = [document(kind="npl"),
            document("D2", kind="npl", public_at=None)]
        rows = run("SEARCH-03", p)["artifacts"]["date_matrix"]
        self.assertEqual(rows[0]["chronology"], "published_before")
        self.assertEqual(rows[1]["chronology"], "unknown")
        self.assertEqual(rows[0]["legal_eligibility"], "undetermined")

    def test_ac_search_04_05_family_and_status_preserved(self):
        docs = [document(legal_status="expired", status_source="office",
                         status_as_of="2026-10-31"),
                document("D2", jurisdiction="US", claims=["不同权项"],
                         legal_status="active", status_source="office",
                         status_as_of="2026-10-31"),
                document("D3", sections=[], claims=[])]
        out = run("SEARCH-04", envelope(documents=docs))
        self.assertEqual(len(out["artifacts"]["documents"]), 3)
        self.assertEqual(out["artifacts"]["documents"][1]["claims"], ["不同权项"])
        self.assertIn("fulltext_missing", codes(out))
        states = run("SEARCH-05", envelope(documents=docs))["artifacts"]["snapshots"]
        self.assertEqual([x["status"] for x in states], ["expired", "active", "unknown"])

    def test_ac_search_06_keeps_old_prior_art(self):
        out = run("SEARCH-06", search_payload(critical_date="2020-01-01"))
        self.assertEqual(out["artifacts"]["documents"][0]["public_at"], "2000-01-01")
        self.assertFalse(out["artifacts"]["qualified_search_report"])

    def test_invalid_permission_and_date(self):
        p = search_payload()
        p["sources"][0]["local_use"] = False
        self.assertEqual(run("SEARCH-01", p)["status"], "blocked")
        with self.assertRaises(ContractError):
            run("SEARCH-06", search_payload(critical_date="2026-99-01"))


class AnalysisDraftTests(unittest.TestCase):
    def test_ac_analysis_01_draft_01_conflicting_facts(self):
        p = envelope(title="控制方法", facts=[
            {"id": "a", "subject": "实现", "kind": "means", "text": "设计可实现",
             "evidence_id": "design", "state": "design"},
            {"id": "b", "subject": "实现", "kind": "means", "text": "尚未验证",
             "evidence_id": "interview", "state": "hypothesis"}])
        for cap in ("ANALYSIS-01", "DRAFT-01"):
            out = run(cap, p)
            self.assertIn("fact_conflict", codes(out))
            self.assertEqual(len(out["artifacts"]["facts"]), 2)
            self.assertIn("待确认", out["artifacts"]["markdown"])

    def test_ac_analysis_02_no_combining_or_priority_guess(self):
        p = envelope(features=features(), documents=[document(),
            document("D2", public_at="2027-01-01", filed_at="1999-01-01")],
            critical_date="2020-01-01", mappings=[
                {"feature_id": "f1", "document_id": "D1", "locator": "p1",
                 "quote": "采集温度", "state": "present"}])
        out = run("ANALYSIS-02", p)
        self.assertEqual(len(out["artifacts"]["matrix"]), 4)
        self.assertEqual(out["artifacts"]["per_document"][0]["combination"], "not_established")
        self.assertEqual(out["artifacts"]["date_matrix"][1]["chronology"], "earlier_filed_later_published")
        p["mappings"][0]["quote"] = "伪造引文"
        self.assertIn("quote_not_found", codes(run("ANALYSIS-02", p)))

    def test_ac_analysis_03_framework_steps_and_missing_motivation(self):
        out = run("ANALYSIS-03", envelope(features=features(), documents=[document()],
            framework={"id": "synthetic-framework", "jurisdiction": "test",
                       "steps": ["difference", "motivation"], "rule_evidence": "rule"},
            arguments=[{"step": "difference", "text": "停止条件不同", "evidence_id": "ev"}]))
        self.assertEqual(len(out["artifacts"]["reasoning"]), 2)
        self.assertIn("argument_missing", codes(out))

    def test_ac_analysis_04_labels_are_not_eligibility(self):
        out = run("ANALYSIS-04", envelope(subject="算法", purpose="控温",
            technical_facts=[{"id": "f1", "text": "采集传感器数据"}]))
        self.assertEqual(out["artifacts"]["eligibility"], "undetermined")
        self.assertIn("jurisdiction_rules_unverified", codes(out))

    def test_ac_analysis_05_review_02_range_and_new_combination(self):
        p = support_payload()
        p["original"]["features"][0]["range"] = {"min": 10, "max": 20, "unit": "C"}
        p["features"][0]["range"] = {"min": 0, "max": 100, "unit": "C"}
        p["original"]["combinations"] = []
        for cap in ("ANALYSIS-05", "REVIEW-02"):
            out = run(cap, p)
            self.assertIn("range_changed", codes(out))
            self.assertIn("combination_not_in_original", codes(out))
            self.assertEqual(out["artifacts"]["original_hash"], digest(p["original"]))

    def test_ac_analysis_06_07_08_plans_not_legal_conclusions(self):
        out = run("ANALYSIS-06", envelope(features=features(), documents=[], coverage_complete=False))
        self.assertEqual(out["artifacts"]["candidates"][0]["status"], "needs_search")
        layout = run("ANALYSIS-07", envelope(features=features(), claims=claims(),
            markets=["CN"], alternatives=[{"feature_id": "f2", "text": "停止策略",
                                         "evidence_id": "ev2"}]))
        self.assertEqual(layout["artifacts"]["layers"][1]["parent_ids"], [1])
        route = run("ANALYSIS-08", envelope(options=[
            {"id": "x", "detectable": False, "secrecy_feasible": True},
            {"id": "y", "detectable": True, "secrecy_feasible": False}]))
        self.assertNotEqual(route["artifacts"]["options"][0]["considerations"],
                            route["artifacts"]["options"][1]["considerations"])
        self.assertFalse(route["artifacts"]["disclosure_authorized"])

    def test_ac_draft_02_and_review_01_ancestor_not_sibling(self):
        cs = claims() + [{"id": 3, "category": "method", "depends_on": [1],
                         "feature_ids": ["f2"], "introduces": [], "uses": ["阈值"]}]
        for cap in ("DRAFT-02", "REVIEW-01"):
            out = run(cap, envelope(claims=cs, features=features()))
            self.assertIn("antecedent_missing", codes(out))
            self.assertEqual(out["artifacts"]["claim_checks"][2]["missing_terms"], ["阈值"])
        cs[0]["depends_on"] = [2]
        self.assertIn("dependency_cycle", codes(run("REVIEW-01", envelope(claims=cs))))
        self.assertIn("forward_reference", codes(run("REVIEW-01", envelope(claims=cs))))

    def test_multiple_dependency_requires_each_alternative_antecedent(self):
        cs = claims() + [{"id": 3, "category": "method", "depends_on": [],
                         "introduces": [], "uses": []},
                        {"id": 4, "category": "method", "depends_on": [2, 3],
                         "introduces": [], "uses": ["阈值"]}]
        self.assertIn("antecedent_missing", codes(run("REVIEW-01", envelope(claims=cs))))

    def test_ac_draft_03_04_no_invented_experiment(self):
        p = envelope(title="控温", features=features(), examples=[{
            "id": "E1", "state": "design", "steps": ["采集温度", "停止加热"],
            "evidence_id": "design", "parameters": {"threshold": 20}}],
            background=[{"text": "推测背景", "state": "hypothesis"}])
        spec = run("DRAFT-03", p)
        self.assertNotIn("推测背景", spec["artifacts"]["markdown"])
        examples = run("DRAFT-04", p)
        self.assertIn("可实施设计", examples["artifacts"]["markdown"])
        self.assertNotIn("经测试", examples["artifacts"]["markdown"])

    def test_ac_draft_05_06_missing_structure_and_figures(self):
        abstract = run("DRAFT-05", envelope(title="温控", features=features(),
            figures=[{"id": "图2", "caption": "控制流程"}], figure_refs=["图1"]))
        self.assertIn("figure_reference_missing", codes(abstract))
        self.assertIn("图2", abstract["artifacts"]["markdown"])
        device = run("DRAFT-06", envelope(features=features(), components=[]))
        self.assertEqual(device["status"], "needs_evidence")
        self.assertEqual(device["artifacts"]["components"], [])

    def test_ac_draft_07_fig_04_real_views_and_conflicts(self):
        p = envelope(views=[{"id": "front", "state": "static", "source_hash": "h1",
            "components": [{"id": "part1", "model_dimensions": [1, 2, 3]}]},
            {"id": "side", "state": "static", "source_hash": "h2",
             "components": [{"id": "part1", "model_dimensions": [1, 2, 4]}]}])
        for cap in ("DRAFT-07", "FIG-04"):
            out = run(cap, p)
            self.assertIn("view_geometry_conflict", codes(out))
            self.assertFalse(out["artifacts"]["qualified_views"])

    def test_ac_draft_08_translation_parameter_blocked(self):
        out = run("DRAFT-08", envelope(segments=[{"id": "s", "original": "10 ms",
            "proposed": "20 ms", "support": "p1"}], glossary={"温度": "temperature"}))
        self.assertEqual(out["artifacts"]["segments"][0]["accepted_text"], "10 ms")
        self.assertIn("numbers", out["artifacts"]["segments"][0]["semantic_changes"])


class FigureReviewTests(unittest.TestCase):
    def test_ac_fig_01_deterministic_svg_and_failure_exit(self):
        p = flow_payload()
        first = run("FIG-01", p)
        self.assertEqual(first, run("FIG-01", p))
        root = ET.fromstring(first["artifacts"]["svg"])
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("停止加热", first["artifacts"]["svg"])
        p["edges"].pop()
        self.assertIn("failure_exit_missing", codes(run("FIG-01", p)))

    def test_fig_01_chinese_mixed_and_long_labels_fit_without_text_loss(self):
        labels = [
            "这是用于验证流程图长中文节点标签不会越界的合成测试内容并且所有字符必须完整保留",
            "温度Temperature超过Threshold时记录SensorID并保留条件与例外，不得遗漏",
            "采集温度并验证条件与例外" * 30,
            "WIDE English label with WWW and an_unbroken_identifier_" * 5,
            '保留<&>及"引号"并校验XML转义与完整性' * 4,
        ]
        ns = {"svg": "http://www.w3.org/2000/svg"}
        for label in labels:
            with self.subTest(label=label[:30]):
                p = flow_payload()
                p["nodes"][1]["label"] = label
                out = run("FIG-01", p)
                svg = out["artifacts"]["svg"]
                root = ET.fromstring(svg)
                rects = root.findall("svg:rect", ns)
                texts = root.findall("svg:text", ns)[len(p["edges"]):]
                view_width, view_height = map(float, root.get("viewBox").split()[2:])
                for node, rect in zip(p["nodes"], rects):
                    x, y, width, height = (float(rect.get(k)) for k in
                                           ("x", "y", "width", "height"))
                    lines = [t for t in texts if y < float(t.get("y")) < y + height]
                    self.assertEqual("".join(t.text or "" for t in lines), node["label"])
                    for line in lines:
                        # 14px汉字全宽、14px等宽拉丁字形按0.6em估算；真实边界另由浏览器验证。
                        advance = sum(14 if ord(c) > 127 else 8.4 for c in line.text or "")
                        self.assertLessEqual(float(line.get("x")) + advance, x + width - 15)
                        self.assertEqual(line.get("font-size"), "14")
                        self.assertGreaterEqual(float(line.get("y")) - 14, y)
                        self.assertLessEqual(float(line.get("y")) + 4, y + height)
                    self.assertLessEqual(x + width, view_width)
                    self.assertLessEqual(y + height, view_height)
                paths = root.findall("svg:path", ns)
                positions = {node["id"]: (float(rect.get("y")), float(rect.get("height")))
                             for node, rect in zip(p["nodes"], rects)}
                self.assertEqual(len(paths), len(p["edges"]))
                for i, (edge, path) in enumerate(zip(p["edges"], paths)):
                    sy, sh = positions[edge["from"]]
                    ty, th = positions[edge["to"]]
                    self.assertEqual(path.get("d"),
                        f"M300,{sy + sh / 2} H{340 + i * 28} V{ty + th / 2} H300")
                    self.assertEqual(path.get("marker-end"), "url(#arrow)")
                self.assertEqual(out["artifacts"]["nodes"], p["nodes"])
                self.assertEqual(out["artifacts"]["edges"], p["edges"])
                self.assertEqual(out["issues"], [])
                self.assertEqual(out, run("FIG-01", p))

    def test_svg_escapes_content_no_execution(self):
        p = flow_payload()
        p["nodes"][0]["label"] = "<script>alert(1)</script>"
        out = run("FIG-01", p)
        self.assertNotIn("<script>", out["artifacts"]["svg"])

    def test_ac_fig_02_disconnected_components(self):
        out = run("FIG-02", envelope(components=[{"id": "a"}, {"id": "b"}], connections=[]))
        self.assertIn("disconnected_components", codes(out))
        self.assertEqual(out["artifacts"]["cad_rendering"], "not_performed")

    def test_ac_fig_03_curve_data_and_sequence(self):
        p = envelope(mode="curve", series=[{"id": "measured", "evidence_id": "data1",
            "points": [[0, 0], [1, 2], [2, 1]]}], x_unit="s", y_unit="C")
        out = run("FIG-03", p)
        self.assertEqual(out["artifacts"]["series"], p["series"])
        ET.fromstring(out["artifacts"]["svg"])
        seq = run("FIG-03", envelope(mode="sequence", sequence="A C G T", alphabet="ACGT",
                                    evidence_id="sequence-source"))
        self.assertEqual(seq["artifacts"]["length"], 4)
        with self.assertRaises(ContractError):
            run("FIG-03", envelope(mode="curve", series=[{"id": "a", "points": [[0, float("nan")]]}]))

    def test_ac_fig_05_static_bounds_not_render_success(self):
        out = run("FIG-05", envelope(figures=[{"id": "图1", "svg":
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect x="90" y="10" width="20" height="20"/></svg>'}], figure_refs=["图2"]))
        self.assertIn("geometry_outside_viewbox", codes(out))
        self.assertIn("figure_reference_missing", codes(out))
        self.assertEqual(out["artifacts"]["rendering"], "not_performed")

    def test_ac_review_03_conflicting_units_ranges_directions(self):
        out = run("REVIEW-03", envelope(measurements=[
            {"id": "m1", "quantity": "delay", "value": 10, "unit": "ms", "locator": "p1"},
            {"id": "m2", "quantity": "delay", "value": 10, "unit": "s", "locator": "fig1"}],
            ranges=[{"id": "r", "min": 10, "max": 2}],
            directions=[{"id": "edge", "text_from": "a", "text_to": "b", "figure_from": "b", "figure_to": "a"}]))
        self.assertTrue({"measurement_conflict", "range_inverted", "direction_conflict"} <= set(codes(out)))

    def test_ac_review_04_simulation_counterevidence_kept(self):
        out = run("REVIEW-04", envelope(assertions=[{"id": "a", "text": "全部覆盖",
            "evidence_ids": []}], counterevidence=[{"id": "c", "text": "边界未测"}]))
        self.assertTrue(out["artifacts"]["simulated"])
        self.assertEqual(out["artifacts"]["counterevidence"][0]["id"], "c")
        self.assertIn("assertion_evidence_missing", codes(out))

    def test_ac_review_05_06_protected_semantics_and_cleaning(self):
        for cap in ("REVIEW-05", "REVIEW-06"):
            out = run(cap, envelope(original="若温度超过10，应停止，不含备用模式，可能失败。",
                proposed="温度超过20，宜停止，包含备用模式，必然成功。"))
            self.assertFalse(out["artifacts"]["auto_applied"])
            self.assertTrue({"numbers", "conditions", "negation", "modality"} <=
                            set(out["artifacts"]["semantic_changes"]))
        clean = run("REVIEW-05", envelope(original="值得一提的是，可能失败。"))
        self.assertTrue(clean["artifacts"]["auto_applied"])
        self.assertEqual(clean["artifacts"]["accepted_text"], "可能失败。")
        defensive = run("REVIEW-06", envelope(original="以下为起草说明。不含备用模式，结果未知。"))
        self.assertEqual(defensive["artifacts"]["accepted_text"], "不含备用模式，结果未知。")


def codes(output):
    return [issue["code"] for issue in output["issues"]]


class ContractTests(unittest.TestCase):
    def test_every_capability_has_task_output_and_version_binding(self):
        fact = {"id": "f1", "subject": "方案", "kind": "means", "text": "采集温度",
                "evidence_id": "ev1", "state": "design"}
        example = {"id": "E1", "state": "design", "evidence_id": "ev1",
                   "steps": ["采集温度"]}
        matrix = {"features": features(), "documents": [document()], "critical_date": "2020-01-01"}
        samples = {
            "SEARCH-01": search_payload(),
            "SEARCH-02": envelope(concepts=[{"id": "c1", "terms": {"zh": ["温度"]}}]),
            "SEARCH-03": search_payload(critical_date="2020-01-01"),
            "SEARCH-04": envelope(documents=[document()]),
            "SEARCH-05": envelope(documents=[document()]),
            "SEARCH-06": search_payload(critical_date="2020-01-01"),
            "ANALYSIS-01": envelope(facts=[fact]),
            "ANALYSIS-02": envelope(**matrix),
            "ANALYSIS-03": envelope(**matrix),
            "ANALYSIS-04": envelope(subject="控制", purpose="控温", technical_facts=features()),
            "ANALYSIS-05": support_payload(),
            "ANALYSIS-06": envelope(**matrix),
            "ANALYSIS-07": envelope(claims=claims(), features=features()),
            "ANALYSIS-08": envelope(options=[{"id": "o1", "detectable": True}]),
            "DRAFT-01": envelope(title="合成方案", facts=[fact]),
            "DRAFT-02": envelope(claims=claims(), features=features()),
            "DRAFT-03": envelope(features=features()),
            "DRAFT-04": envelope(examples=[example]),
            "DRAFT-05": envelope(features=features(), figures=[{"id": "图1", "caption": "流程"}]),
            "DRAFT-06": envelope(components=[{"id": "c1", "structure": "传感器",
                                               "evidence_id": "ev1"}]),
            "DRAFT-07": envelope(views=[{"id": "front", "state": "static", "source_hash": "h",
                "components": [{"id": "p1", "model_dimensions": [1, 2, 3]}]}]),
            "DRAFT-08": envelope(segments=[{"id": "s1", "original": "温度", "proposed": "temperature",
                                            "support": "p1"}]),
            "FIG-01": flow_payload(),
            "FIG-02": envelope(components=[{"id": "c1"}, {"id": "c2"}],
                               connections=[{"from": "c1", "to": "c2"}]),
            "FIG-03": envelope(mode="curve", series=[{"id": "s1", "evidence_id": "data",
                                                       "points": [[0, 1], [1, 2]]}]),
            "FIG-04": envelope(views=[{"id": "front", "state": "static", "source_hash": "h",
                                       "components": [{"id": "p1", "model_dimensions": [1, 2, 3]}]}]),
            "FIG-05": envelope(figures=[{"id": "图1", "svg": '<svg viewBox="0 0 100 100"/>'}]),
            "REVIEW-01": envelope(claims=claims()),
            "REVIEW-02": support_payload(),
            "REVIEW-03": envelope(measurements=[{"id": "m", "quantity": "温度", "value": 10,
                                                  "unit": "C", "locator": "p1"}]),
            "REVIEW-04": envelope(assertions=[{"id": "a", "text": "阈值可配置", "evidence_ids": ["ev1"]}]),
            "REVIEW-05": envelope(original="值得一提的是，可能失败。"),
            "REVIEW-06": envelope(original="以下为起草说明。结果未知。"),
        }
        self.assertEqual(set(samples), set(CAPABILITIES))
        for capability, payload in samples.items():
            with self.subTest(capability=capability):
                original = copy.deepcopy(payload)
                out = run(capability, payload)
                self.assertEqual(original, payload)
                self.assertTrue(set(out["artifacts"]) - {
                    "input_hash", "previous_input_hash", "tool_version", "support_level", "review_inherited"})
                self.assertEqual(out["professional_review"], "not_performed")
                payload["previous_input_hash"] = out["artifacts"]["input_hash"]
                self.assertNotIn("input_changed_re_review", codes(run(capability, payload)))
                payload["adaptation"]["stage"] = "revised_internal_draft"
                self.assertIn("input_changed_re_review", codes(run(capability, payload)))

    def test_documented_example_executes_and_resources_exist(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "skills" / "dyz-patent" / "example.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        out = run("DRAFT-02", payload)
        self.assertIn("通过温度传感器采集温度", out["artifacts"]["markdown"])
        self.assertEqual(out["issues"], [])
        self.assertTrue((path.parent / "SKILL.md").is_file())

    def test_local_vertical_chain(self):
        retrieved = run("SEARCH-06", search_payload(critical_date="2020-01-01"))
        matrix = run("ANALYSIS-02", envelope(features=features(),
            documents=retrieved["artifacts"]["documents"], critical_date="2020-01-01"))
        draft = run("DRAFT-02", envelope(features=features(), claims=claims(),
            evidence=matrix["artifacts"]["matrix"]))
        review = run("REVIEW-01", envelope(claims=draft["artifacts"]["claims"]))
        figure = run("FIG-01", flow_payload())
        figure_check = run("FIG-05", envelope(figures=[{
            "id": "图1", "svg": figure["artifacts"]["svg"]}], figure_refs=["图1"]))
        self.assertEqual(review["issues"], [])
        self.assertNotIn("svg_invalid", codes(figure_check))
        self.assertEqual(figure_check["artifacts"]["rendering"], "not_performed")

    def test_malformed_nested_input_raises_contract_errors(self):
        bad_doc = document(abstract=[])
        cases = [
            ("SEARCH-04", envelope(documents=[bad_doc])),
            ("DRAFT-04", envelope(examples=[{"id": "e", "state": "design", "steps": ["步骤"],
                "evidence_id": "ev", "parameters": []}])),
            ("DRAFT-03", envelope(background=[{"state": "confirmed", "evidence_id": "ev"}])),
            ("ANALYSIS-02", envelope(features=features(), documents=[document()],
                mappings=[{"feature_id": [], "document_id": "D1", "state": "present"}])),
            ("REVIEW-03", envelope(measurements=[{"id": "m", "quantity": [], "value": 1,
                                                   "unit": "s", "locator": "p1"}])),
            ("FIG-02", envelope(components=[{"id": "x"}], connections=[{"from": [], "to": "x"}])),
            ("FIG-01", envelope(nodes=[{"id": "x", "kind": "start", "label": "x"}],
                                edges=[{"from": [], "to": "x", "label": "x"}])),
            ("FIG-01", envelope(applicability={"applies": "false"})),
        ]
        for cap, payload in cases:
            with self.subTest(capability=cap):
                with self.assertRaises(ContractError):
                    run(cap, payload)

    def test_all_33_ids_and_explicit_not_applicable(self):
        self.assertEqual(len(CAPABILITIES), 33)
        for cap in CAPABILITIES:
            with self.subTest(cap=cap):
                out = run(cap, envelope(applicability={"applies": False,
                    "reason": "合成案例不适用", "evidence_id": "ev-na"}))
                self.assertEqual(out["status"], "not_applicable")
                self.assertEqual(out["professional_review"], "not_performed")
                self.assertEqual(out["external_action"], "not_performed")

    def test_changed_input_invalidates_binding_not_history(self):
        p = flow_payload()
        first = run("FIG-01", p)
        p["previous_input_hash"] = first["artifacts"]["input_hash"]
        p["nodes"][0]["label"] = "不同开始"
        second = run("FIG-01", p)
        self.assertIn("input_changed_re_review", codes(second))
        self.assertEqual(second["artifacts"]["previous_input_hash"], first["artifacts"]["input_hash"])

    def test_unsupported_invalid_and_sensitive_preflight(self):
        with self.assertRaises(ContractError):
            run("SEARCH-99", envelope())
        with self.assertRaises(ContractError):
            run("FIG-01", envelope(nodes="not-a-list"))
        p = flow_payload()
        p["sensitivity"] = "confidential"
        with self.assertRaises(ContractError):
            run("FIG-01", p)

    def test_no_mutation_and_determinism(self):
        p = support_payload()
        before = copy.deepcopy(p)
        a = run("REVIEW-02", p)
        self.assertEqual(p, before)
        self.assertEqual(a, run("REVIEW-02", p))


if __name__ == "__main__":
    unittest.main()
