"""最终专利正文门禁的合成回归：检查真实字符串，不以调用者公式代替正文。"""

import copy
import hashlib
import json
import unittest

from tools.core import ContractError
from tools.patent_gate import audit_final_text, require_final_text


NECESSARY = "只有记录已写入持久介质，才允许返回成功确认。"
SUFFICIENT = "一旦记录已写入持久介质，就允许返回成功确认。"
SAMPLING = "传感器每秒采样。"
STOP = "阀门具有机械止挡。"
SUPPORTED_CLAIMS = (
    "1. 传感器每秒采样。\n"
    "2. 根据权利要求1所述的方案，其特征在于，阀门具有机械止挡。"
)


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def original(identity, text, version="1"):
    return {"id": identity, "version": version, "role": "original", "text": text,
            "sha256": text_hash(text)}


def claim_sources():
    # 明确的同一方案同时支持两个独立已知句，避免将无关共现当成组合。
    return [original("O-combined", "同一方案：" + SAMPLING + STOP)]


class PatentFinalTextGateTests(unittest.TestCase):
    def checked(self, texts, sources):
        report = audit_final_text(texts, sources)
        self.assertIsInstance(report, dict)
        self.assertEqual("checked", report.get("status"), report)
        self.assertEqual([], report.get("issues"), report)
        self.assertIsInstance(report.get("claims"), list)
        self.assertIsInstance(report.get("input_binding"), dict)
        # 正常输入也必须能经过强制门禁；不限定其返回值。
        require_final_text(texts, sources)
        return report

    def blocked(self, texts, sources):
        report = audit_final_text(texts, sources)
        self.assertIsInstance(report, dict)
        self.assertEqual("blocked", report.get("status"), report)
        self.assertIsInstance(report.get("issues"), list)
        self.assertTrue(report["issues"], report)
        for issue in report["issues"]:
            self.assertIsInstance(issue, dict)
            self.assertIsInstance(issue.get("code"), str)
            self.assertTrue(issue["code"])
        self.assertIsInstance(report.get("claims"), list)
        with self.assertRaisesRegex(ContractError, "^final_text_gate_blocked$"):
            require_final_text(texts, sources)
        return report

    def test_exact_necessary_condition_is_supported(self):
        self.checked({"description": NECESSARY}, [original("O", NECESSARY)])

    def test_necessary_condition_cannot_be_replaced_by_sufficient_trigger(self):
        self.blocked({"description": SUFFICIENT}, [original("O", NECESSARY)])

    def test_exact_sufficient_condition_is_supported(self):
        self.checked({"description": SUFFICIENT}, [original("O", SUFFICIENT)])

    def test_sufficient_condition_cannot_be_replaced_by_necessary_gate(self):
        self.blocked({"description": NECESSARY}, [original("O", SUFFICIENT)])

    def test_when_and_then_conditions_preserve_their_direction(self):
        for sentence in (
            "当记录已写入持久介质时，允许返回成功确认。",
            "若记录已写入持久介质，则允许返回成功确认。",
        ):
            with self.subTest(sentence=sentence):
                self.checked({"description": sentence}, [original("O", sentence)])
                self.blocked({"description": NECESSARY}, [original("O", sentence)])

    def test_then_condition_cannot_reverse_its_antecedent_and_consequence(self):
        source = "若记录已写入持久介质，则允许返回成功确认。"
        reversed_text = "若允许返回成功确认，则记录已写入持久介质。"
        self.blocked({"description": reversed_text}, [original("O", source)])

    def test_condition_cannot_be_flattened_into_unconditional_facts(self):
        self.blocked({"description": "记录已写入持久介质。允许返回成功确认。"},
                     [original("O", NECESSARY)])

    def test_all_final_text_sections_are_checked(self):
        sources = [original("O-sampling", SAMPLING), original("O-rule", NECESSARY)]
        texts = {"claims": "1. " + SAMPLING, "description": NECESSARY}
        self.checked(texts, sources)
        texts["description"] = SUFFICIENT
        self.blocked(texts, sources)

    def test_supported_single_parent_addition_is_checked(self):
        report = self.checked({"claims": SUPPORTED_CLAIMS}, claim_sources())
        self.assertEqual(2, len(report["claims"]))

    def test_independent_claim_has_original_support(self):
        self.checked({"claims": "1. " + SAMPLING}, [original("O", SAMPLING)])

    def test_new_dependent_limitation_without_original_support_is_blocked(self):
        self.blocked({"claims": SUPPORTED_CLAIMS}, [original("O", SAMPLING)])

    def test_new_independent_fact_without_original_support_is_blocked(self):
        self.blocked({"claims": "1. 传感器每毫秒采样。"},
                     [original("O", SAMPLING)])

    def test_dependent_claim_repeating_parent_adds_no_limitation(self):
        claims = ("1. 传感器每秒采样。\n"
                  "2. 根据权利要求1所述的方案，其特征在于，传感器每秒采样。")
        self.blocked({"claims": claims}, [original("O", SAMPLING)])

    def test_dependent_claim_repeating_inherited_limitation_is_blocked(self):
        claims = (SUPPORTED_CLAIMS + "\n"
                  "3. 根据权利要求2所述的方案，其特征在于，阀门具有机械止挡。")
        self.blocked({"claims": claims}, claim_sources())

    def test_unknown_parent_is_blocked_despite_supported_child_text(self):
        claims = SUPPORTED_CLAIMS.replace("根据权利要求1", "根据权利要求9")
        self.blocked({"claims": claims}, claim_sources())

    def test_forward_parent_is_blocked_despite_supported_claim_text(self):
        claims = ("1. 根据权利要求2所述的方案，其特征在于，传感器每秒采样。\n"
                  "2. 阀门具有机械止挡。")
        self.blocked({"claims": claims}, claim_sources())

    def test_self_parent_is_blocked(self):
        claims = SUPPORTED_CLAIMS.replace("根据权利要求1", "根据权利要求2")
        self.blocked({"claims": claims}, claim_sources())

    def test_parent_cycle_is_blocked(self):
        claims = ("1. 根据权利要求2所述的方案，其特征在于，传感器每秒采样。\n"
                  "2. 根据权利要求1所述的方案，其特征在于，阀门具有机械止挡。")
        self.blocked({"claims": claims}, claim_sources())

    def test_multiple_parent_references_are_outside_the_supported_subset(self):
        for parents in ("1或2", "1和2", "1、2", "1至2"):
            with self.subTest(parents=parents):
                claims = ("1. 传感器每秒采样。\n"
                          "2. 控制器具有定时器。\n"
                          f"3. 根据权利要求{parents}所述的方案，其特征在于，阀门具有机械止挡。")
                sources = claim_sources() + [original("O-timer", "控制器具有定时器。")]
                self.blocked({"claims": claims}, sources)

    def test_unconnected_facts_in_one_original_do_not_prove_a_new_condition(self):
        for separator in ("", "\n", "\n\n"):
            with self.subTest(separator=repr(separator)):
                source_text = "记录已写入持久介质。" + separator + "允许返回成功确认。"
                self.blocked({"description": SUFFICIENT}, [original("O", source_text)])

    def test_unconnected_facts_in_one_original_do_not_prove_a_new_connection(self):
        source_text = SAMPLING + STOP
        self.blocked({"description": "传感器通过连杆驱动阀门。"},
                     [original("O", source_text)])

    def test_same_paragraph_without_explicit_scope_does_not_prove_a_claim_combination(self):
        self.blocked({"claims": SUPPORTED_CLAIMS},
                     [original("O", SAMPLING + STOP)])

    def test_separate_original_facts_do_not_prove_a_claim_combination(self):
        self.blocked({"claims": SUPPORTED_CLAIMS},
                     [original("O-sampling", SAMPLING), original("O-stop", STOP)])

    def test_disconnected_source_paragraphs_do_not_prove_a_claim_combination(self):
        self.blocked({"claims": SUPPORTED_CLAIMS},
                     [original("O", SAMPLING + "\n\n" + STOP)])

    def test_evidence_outside_source_text_cannot_supply_a_missing_fact(self):
        source = original("O", SAMPLING)
        source.update(quote=STOP, evidence_text=STOP, supported=True)
        self.blocked({"claims": SUPPORTED_CLAIMS}, [source])

    def test_unknown_source_does_not_establish_a_positive_fact(self):
        for unknown in (
            "尚未确认阀门具有机械止挡。",
            "阀门是否具有机械止挡尚未确认。",
            "阀门具有机械止挡的情况尚不明确。",
        ):
            with self.subTest(unknown=unknown):
                sources = [original("O-sampling", SAMPLING), original("O-unknown", unknown)]
                self.blocked({"claims": SUPPORTED_CLAIMS}, sources)

    def test_question_copied_verbatim_is_not_a_known_technical_fact(self):
        question = "是否允许返回成功确认？"
        self.blocked({"description": question}, [original("O", question)])

    def test_changed_source_text_cannot_keep_the_old_hash(self):
        source = original("O", NECESSARY)
        source["text"] = SUFFICIENT
        self.blocked({"description": SUFFICIENT}, [source])

    def test_wrong_original_hash_is_blocked(self):
        source = original("O", NECESSARY)
        source["sha256"] = "0" * 64
        self.blocked({"description": NECESSARY}, [source])

    def test_non_original_document_cannot_supply_original_support(self):
        for role in ("candidate", "product", "internal", "source"):
            with self.subTest(role=role):
                source = original("O", SAMPLING)
                source["role"] = role
                self.blocked({"claims": "1. " + SAMPLING}, [source])

    def test_empty_sources_are_blocked(self):
        self.blocked({"description": NECESSARY}, [])

    def test_empty_original_text_is_blocked(self):
        self.blocked({"description": NECESSARY}, [original("O", "")])

    def test_empty_final_text_is_blocked(self):
        for texts in ({}, {"claims": ""}, {"claims": " \n\t "}):
            with self.subTest(texts=texts):
                self.blocked(texts, [original("O", SAMPLING)])

    def test_valid_section_cannot_hide_an_empty_section(self):
        self.blocked({"claims": "1. " + SAMPLING, "description": ""},
                     [original("O", SAMPLING)])

    def test_formula_and_passed_metadata_cannot_bless_reversed_actual_text(self):
        # 原反例的源文字与反句保持不变，仅篡改旧调用方式中的公式或通过标志。
        for formula in (True, False, {"implies": ["acknowledgement", "stored"]},
                        {"implies": ["stored", "acknowledgement"]}):
            with self.subTest(formula=formula):
                source = original("O", NECESSARY)
                source.update(formula=formula, passed=True, status="checked")
                self.blocked({"description": SUFFICIENT}, [source])

    def test_formula_metadata_cannot_replace_missing_original_fact(self):
        source = original("O", SAMPLING)
        source.update(formula=STOP, passed=True)
        self.blocked({"claims": SUPPORTED_CLAIMS}, [source])

    def test_input_binding_contains_actual_text_and_original_hashes(self):
        texts = {"claims": SUPPORTED_CLAIMS}
        sources = claim_sources()
        report = self.checked(texts, sources)
        encoded = json.dumps(report["input_binding"], sort_keys=True)
        self.assertIn(text_hash(SUPPORTED_CLAIMS), encoded)
        for source in sources:
            self.assertIn(source["sha256"], encoded)
        self.assertEqual(report["input_binding"],
                         audit_final_text(copy.deepcopy(texts), copy.deepcopy(sources))["input_binding"])

    def test_changing_final_bytes_changes_the_input_binding(self):
        source = original("O", SAMPLING)
        first = self.checked({"claims": "1. " + SAMPLING}, [source])
        second_text = "1. " + SAMPLING + "\n"
        second = self.checked({"claims": second_text}, [source])
        self.assertNotEqual(first["input_binding"], second["input_binding"])
        self.assertIn(text_hash(second_text), json.dumps(second["input_binding"]))

    def test_changing_original_version_changes_the_input_binding(self):
        source = original("O", SAMPLING)
        first = self.checked({"claims": "1. " + SAMPLING}, [source])
        revised_source = original("O", SAMPLING, version="2")
        second = self.checked({"claims": "1. " + SAMPLING}, [revised_source])
        self.assertNotEqual(first["input_binding"], second["input_binding"])

    def test_conflicting_original_cannot_supply_only_its_positive_sentence(self):
        self.blocked({"claims": "1. " + SAMPLING},
                     [original("O", SAMPLING + "并非" + SAMPLING)])

    def test_independent_combination_needs_explicit_source_scope(self):
        self.blocked({"claims": "1. " + SAMPLING + STOP},
                     [original("O", SAMPLING + "\n\n" + STOP)])
        self.blocked({"claims": "1. " + SAMPLING + STOP},
                     [original("O", SAMPLING + STOP)])
        self.checked({"claims": "1. " + SAMPLING + STOP}, claim_sources())

    def test_blank_line_cannot_hide_independent_claim_combination(self):
        self.blocked({"claims": "1. " + SAMPLING + "\n\n" + STOP},
                     [original("O", SAMPLING + "\n\n" + STOP)])

    def test_source_dependent_claim_cannot_lose_its_inherited_limitation(self):
        source = ("1. 传感器每秒采样。\n"
                  "2. 根据权利要求1所述的方案，其特征在于，阀门具有机械止挡。")
        self.blocked({"claims": "1. " + STOP}, [original("O", source)])

    def test_heading_only_artifact_cannot_hide_behind_valid_claims(self):
        self.blocked({"claims": "1. " + SAMPLING,
                      "description": "说明书\n技术领域\n背景技术\n发明内容\n具体实施方式"},
                     [original("O", SAMPLING)])

    def test_claim_number_gap_is_blocked_across_artifacts(self):
        self.blocked({"claims-a": "1. " + SAMPLING,
                      "claims-b": "3. 根据权利要求1所述的方案，其特征在于，" + STOP},
                     claim_sources())

    def test_identifier_underscores_are_not_removed_as_decoration(self):
        self.blocked({"description": "控制器读取portab。"},
                     [original("O", "控制器读取porta__b。")])

    def test_original_contact_sentence_keeps_result_before_condition_marker(self):
        sentence = "只有滑块抵靠止挡时两孔才同轴。"
        report = self.checked({"claims": sentence}, [original("O", sentence)])
        self.assertEqual([{"implies": ["两孔同轴", "滑块抵靠止挡"]}],
                         [row["expression"] for row in report["clauses"]])
        self.blocked({"claims": "滑块抵靠止挡时，两孔同轴。"}, [original("O", sentence)])

    def test_equivalent_necessary_wording_does_not_add_a_reverse_fact(self):
        source = "只有滑块抵靠固定止挡时两孔才同轴。"
        for sentence in ("只有所述滑块抵靠所述固定止挡时，两孔才同轴。",
                         "滑块抵靠固定止挡是两孔同轴的必要条件。"):
            with self.subTest(sentence=sentence):
                self.checked({"claims": sentence}, [original("O", source)])
        self.blocked({"claims": "抵靠本身不保证两孔同轴。"}, [original("O", source)])

    def test_named_claim_category_is_a_single_parent_reference(self):
        claims = ("1. 传感器每秒采样。\n"
                  "2. 根据权利要求1所述的通风控制装置，其特征在于，阀门具有机械止挡。")
        report = self.checked({"claims": claims}, claim_sources())
        self.assertEqual([[], [1]], [row["parent_ids"] for row in report["claims"]])

    def test_unknown_statement_does_not_erase_an_unaffected_fact(self):
        source = "传感器每秒采样。阀门在中间区间的动作未给出。"
        self.checked({"claims": "1. 传感器每秒采样。"}, [original("O", source)])
        self.blocked({"claims": "1. 阀门在中间区间保持原位。"}, [original("O", source)])

    def test_later_uncertainty_still_limits_the_preceding_rule(self):
        source = "温度高于H时打开阀门。\n\n上述开阀规则尚未确认。"
        self.blocked({"claims": "温度高于H时打开阀门。"}, [original("O", source)])

    def test_prohibition_and_recovery_do_not_authorize_other_actions(self):
        source = "传感器故障时禁止新开阀命令。故障解除后须收到人工复位确认才能恢复正常判断。"
        self.checked({"claims": source}, [original("O", source)])
        for sentence in ("传感器故障时关闭阀门。", "收到人工复位确认就恢复正常判断。",
                         "故障解除前收到人工复位确认就恢复正常判断。"):
            with self.subTest(sentence=sentence):
                self.blocked({"claims": sentence}, [original("O", source)])

    def test_capability_and_alternative_structures_keep_their_boundaries(self):
        capability = "插销可同时穿过两孔以阻止滑块离开止挡。"
        self.checked({"claims": capability}, [original("O", capability)])
        self.blocked({"claims": "插销同时穿过两孔。"}, [original("O", capability)])
        alternatives = "实施方式一使用弹簧。实施方式二使用磁吸。"
        self.blocked({"claims": "夹具同时使用弹簧和磁吸。"}, [original("O", alternatives)])

    def test_natural_single_structure_supports_its_stated_combination(self):
        source = "原创合成夹具仅有这一种结构：基座具有滑块。滑块具有一个孔。"
        claims = "1. 基座具有滑块。滑块具有一个孔。"
        self.checked({"claims": claims}, [original("O", source)])
        self.blocked({"claims": claims}, [original("O", "基座具有滑块。滑块具有一个孔。")])

    def test_technical_heading_is_not_exempt_context(self):
        self.blocked({"claims": "1. 传感器每秒采样。", "description": "## 故障时阀门自动关闭"},
                     [original("O", SAMPLING)])

    def test_purpose_roles_cannot_be_swapped(self):
        self.blocked({"description": "采样温度用于传感器。"},
                     [original("O", "传感器用于采样温度。")])

    def test_another_scheme_ends_the_preceding_combination(self):
        source = "同一方案：基座具有滑块。另一方案：滑块具有磁铁。"
        self.blocked({"claims": "1. 基座具有滑块。滑块具有磁铁。"}, [original("O", source)])

    def test_membership_keeps_ownership_and_member_roles(self):
        source = "基座具有两条平行导轨和一个固定止挡。"
        self.checked({"description": source}, [original("O", source)])
        for sentence in ("滑块具有两条平行导轨和一个固定止挡。",
                         "基座具有三条平行导轨和一个固定止挡。",
                         "基座具有两条导轨和一个固定止挡。"):
            with self.subTest(sentence=sentence):
                self.blocked({"description": sentence}, [original("O", source)])

    def test_purpose_and_capability_do_not_supply_unconditional_components(self):
        for source, unsupported in (
            ("传感器用于采样温度。", "传感器。采样温度。"),
            ("插销可同时穿过两孔以阻止滑块离开止挡。", "滑块离开止挡。"),
            ("控制器将采样值与阈值比较。", "控制器。采样值。阈值。"),
        ):
            with self.subTest(source=source):
                self.checked({"description": source}, [original("O", source)])
                self.blocked({"description": unsupported}, [original("O", source)])

    def test_coordinated_facts_are_reparsed_without_losing_owner(self):
        source = "同一方案：基座具有两条平行导轨和一个固定止挡；滑块沿导轨移动。"
        sentence = "基座具有两条平行导轨和一个固定止挡，滑块沿导轨移动。"
        report = self.checked({"description": sentence}, [original("O", source)])
        for row in report["clauses"]:
            self.assertEqual(row["quote"], sentence[row["start"]:row["end"]])
        self.blocked({"description": sentence.replace("滑块沿", "插销沿")}, [original("O", source)])

    def test_peer_conjunction_is_covered_without_splitting_compound_conditions(self):
        source = "同一方案：基座具有滑块；滑块具有一个孔。"
        for connector in ("并且", "，并且"):
            sentence = "基座具有滑块" + connector + "滑块具有一个孔。"
            with self.subTest(connector=connector):
                report = self.checked({"description": sentence}, [original("O", source)])
                for row in report["clauses"]:
                    self.assertEqual(row["quote"], sentence[row["start"]:row["end"]])
        self.blocked({"description": "只有许可成立时，记录已写入并且允许发布。"},
                     [original("O", "只有许可成立时，记录已写入并且允许发布。")])

    def test_two_relationships_in_one_sentence_remain_distinct(self):
        sentences = (
            "传感器故障时禁止新开阀命令，故障解除后须收到人工复位确认才能恢复正常判断。",
            "只有滑块抵靠止挡时两孔才同轴，插销可同时穿过两孔以阻止滑块离开止挡。",
        )
        for source in sentences:
            with self.subTest(source=source):
                self.checked({"description": source.replace("，", "。", 1)}, [original("O", source)])
        self.blocked({"description": "基座具有一个孔和一个孔。"},
                     [original("O", "基座具有一个孔。")])

    def test_comparison_operands_and_direction_are_preserved(self):
        source = "控制器将采样值与低阈值L及高阈值H比较，L小于H。"
        self.checked({"description": source}, [original("O", source)])
        for sentence in (source.replace("L小于H", "H小于L"),
                         source.replace("采样值与", "压力值与")):
            with self.subTest(sentence=sentence):
                self.blocked({"description": sentence}, [original("O", source)])

    def test_structural_title_is_bound_to_a_supported_device(self):
        source = "一种夹具包括基座和滑块。"
        self.checked({"description": "# 夹具\n## 独立权利要求\n" + source}, [original("O", source)])
        self.blocked({"description": "# 自动复位夹具\n" + source}, [original("O", source)])
        self.blocked({"description": "# 夹具\n## 独立权利要求"}, [original("O", source)])

    def test_unknown_scope_does_not_erase_single_structure(self):
        source = "原创合成夹具仅有这一种结构：基座具有滑块；滑块具有一个孔。尺寸未给出。"
        self.checked({"claims": "1. 基座具有滑块，滑块具有一个孔。"}, [original("O", source)])
        self.blocked({"claims": "1. 基座具有滑块，滑块具有两个孔。"}, [original("O", source)])

    def test_control_overview_requires_matching_conditions_not_only_actions(self):
        source = ("同一方案：通风控制装置包括温度传感器、控制器和阀门。温度传感器采样温度。"
                  "控制器将采样值与低阈值L及高阈值H比较。L小于H。"
                  "温度高于H时打开阀门。温度低于L时关闭阀门。")
        overview = "通风控制装置以温度采样值与两个阈值的比较结果控制阀门。"
        self.checked({"description": overview}, [original("O", source)])
        for changed in (
            source.replace("温度高于H", "压力高于P").replace("温度低于L", "压力低于Q"),
            source.replace("温度高于H", "温度高于J"),
            source.replace("温度传感器、控制器和阀门", "控制器和阀门"),
        ):
            with self.subTest(source=changed):
                self.blocked({"description": overview}, [original("O", changed)])

    def test_overview_cannot_mix_two_sampling_measurements(self):
        source = ("同一方案：通风控制装置包括控制器和阀门和温度传感器和压力传感器。"
                  "温度传感器采样温度。压力传感器采样压力。"
                  "控制器将采样值与低阈值L及高阈值H比较。"
                  "压力高于H时打开阀门。压力低于L时关闭阀门。")
        self.blocked({"description": "通风控制装置以温度采样值与两个阈值的比较结果控制阀门。"},
                     [original("O", source)])

    def test_inferred_device_member_respects_explicit_negation(self):
        source = "原创合成夹具仅有这一种结构：基座具有滑块。并非夹具包括基座。"
        self.blocked({"description": "夹具包括基座。"}, [original("O", source)])

    def test_projected_membership_cannot_bypass_an_original_negation(self):
        source = "同一方案：基座具有滑块和插销。并非基座具有滑块。"
        self.blocked({"description": "基座具有滑块。"}, [original("O", source)])

    def test_other_scheme_labels_cannot_inherit_an_old_combination(self):
        for label in ("其他方案", "其它方案", "另一实施方式", "实施例二"):
            with self.subTest(label=label):
                source = "同一方案：基座具有滑块。" + label + "：滑块具有磁铁。"
                self.blocked({"claims": "1. 基座具有滑块。滑块具有磁铁。"}, [original("O", source)])

    def test_external_subject_is_not_inferred_as_a_device_member(self):
        source = "原创合成夹具仅有这一种结构：外部机械臂具有夹爪。基座具有滑块。"
        self.blocked({"description": "夹具包括外部机械臂。"}, [original("O", source)])

    def test_standalone_uncertainty_marks_cannot_disappear_from_coverage(self):
        for suffix in ("？？？", ":???", "。？？", "\n？"):
            with self.subTest(suffix=suffix):
                self.blocked({"description": SAMPLING + suffix}, [original("O", SAMPLING)])

    def test_full_coverage_and_actionable_typed_diagnostics(self):
        source = "同一方案：基座具有两条平行导轨和一个固定止挡。"
        text = "权利要求书\n1. 基座具有两条平行导轨和一个固定止挡。"
        report = self.checked({"claims": text}, [original("O", source)])
        spans = [(row["start"], row["end"]) for row in report["coverage_ledger"]]
        self.assertTrue(all(char.isspace() or any(start <= i < end for start, end in spans)
                            for i, char in enumerate(text)))
        for sentence, code in (("基座具有三条平行导轨和一个固定止挡。", "member_quantity_or_property_not_supported"),
                               ("插销用于采样温度。", "purpose_not_supported")):
            with self.subTest(sentence=sentence):
                blocked = self.blocked({"description": sentence}, [original("O", source)])
                self.assertIn(code, [row["code"] for row in blocked["issues"]])

    def test_audit_does_not_mutate_the_final_text_or_originals(self):
        texts, sources = {"claims": SUPPORTED_CLAIMS}, claim_sources()
        before = copy.deepcopy((texts, sources))
        self.checked(texts, sources)
        self.assertEqual(before, (texts, sources))


class PatentFinalTextGateCliTests(unittest.TestCase):
    def test_cli_blocks_bad_body_and_only_copies_verified_body(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path
        from tools.patent_gate import main

        with tempfile.TemporaryDirectory(prefix="patent-gate-cli-") as temporary:
            root = Path(temporary)
            (root / "sources.json").write_text(json.dumps({
                "sensitivity": "synthetic", "documents": claim_sources()}, ensure_ascii=False), encoding="utf-8")
            (root / "body.md").write_text(SUPPORTED_CLAIMS.replace(STOP, "阀门自动复位。"), encoding="utf-8")
            arguments = ["--synthetic", "--root", str(root), "--manuscript", "body.md",
                         "--sources", "sources.json", "--report", "rejected.json", "--deliver", "delivered.md"]
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, main(arguments))
            self.assertFalse((root / "delivered.md").exists())
            rejected = json.loads((root / "rejected.json").read_text(encoding="utf-8"))
            self.assertEqual("blocked", rejected["status"])
            (root / "body.md").write_text(SUPPORTED_CLAIMS, encoding="utf-8")
            arguments[arguments.index("rejected.json")] = "accepted.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(arguments))
            self.assertEqual((root / "body.md").read_bytes(), (root / "delivered.md").read_bytes())

    def test_cli_requires_synthetic_before_any_file_read(self):
        import contextlib
        import io
        from unittest.mock import patch
        from tools.patent_gate import main

        with patch("tools.patent_gate.safe_path", side_effect=AssertionError("no read allowed")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, main(["--manuscript", "missing.md", "--sources", "missing.json",
                                          "--report", "report.json"]))


if __name__ == "__main__":
    unittest.main()
