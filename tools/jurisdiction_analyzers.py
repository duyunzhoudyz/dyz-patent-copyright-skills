"""Phase E1 & E2: US / EP 法域本地启发式与结构化规则分析器（纯 Python 标准库）。

显式报告 checks_run 与 checks_skipped，保留 legal_conclusion="not_determined" 与
professional_review="not_performed"；绝不将启发式检查冒充为官方审查或法律意见。
"""
from __future__ import annotations

import re

from tools.core import digest, require, require_fields

VERSION = "1.0"
US_RELATIVE_TERMS = (
    "substantially", "about", "approximately", "essentially",
    "relatively", "effectively", "adapted to", "configured as needed",
)
US_112F_CUES = ("means for", "step for")
US_101_ABSTRACT_CUES = (
    "scoring", "evaluating", "classifying", "organizing", "managing business",
    "financial transaction", "mental process",
)
EP_TWO_PART_MARKER = re.compile(r"(?i)\bcharacteri[sz]ed\s+in\s+that\b")
_CLAIM_TERM_STOP = (
    r"a|an|the|said|and|or|of|for|to|by|from|with|in|on|as|is|are|was|were|be|has|have|"
    r"comprises|comprising|includes|including|consists|consisting|configured|adapted|arranged|"
    r"coupled|connected|wherein|where|which|that|when|while|using|based|further|"
    r"opens|closes|moves|returns|receives|sends|detects|updates|emits|drives|measures"
)
_CLAIM_TERM = rf"([a-z][a-z0-9-]*(?:\s+(?!(?:{_CLAIM_TERM_STOP})\b)[a-z][a-z0-9-]*){{0,2}})"
_INTRODUCED_TERM = re.compile(rf"\b(?:at least one|one or more|a plurality of|an?)\s+{_CLAIM_TERM}", re.I)
_DEFINITE_REF = re.compile(rf"\b(?:the|said)\s+{_CLAIM_TERM}", re.I)
_ORDINALS = frozenset("first second third fourth fifth sixth seventh eighth ninth tenth".split())
_NON_TERM_REFS = {"claim", "method", "system", "apparatus", "device", "step", "following", "present", "same"}
MAX_EP_BRANCHES = 64


def _claim_rows(claims: list[dict], prefix: str) -> list[tuple[int, dict, list[int]]]:
    require(isinstance(claims, list) and bool(claims), f"{prefix}_claims_required")
    rows = []
    seen = set()
    for row in claims:
        require(isinstance(row, dict), f"{prefix}_claim_object_required")
        require_fields(row, ("id", "text"))
        cid = row["id"]
        require(type(cid) is int and cid >= 1, f"{prefix}_claim_id_invalid")
        require(cid not in seen, f"{prefix}_claim_id_duplicate")
        require(isinstance(row["text"], str), f"{prefix}_claim_text_invalid")
        parents = row.get("parent_ids", [])
        require(isinstance(parents, list) and all(type(pid) is int for pid in parents),
                f"{prefix}_parent_ids_invalid")
        require(len(parents) == len(set(parents)), f"{prefix}_parent_id_duplicate")
        rows.append((cid, row, sorted(parents)))
        seen.add(cid)
    return sorted(rows, key=lambda item: item[0])


def _feature_set(values: object, code: str) -> set[str]:
    require(isinstance(values, list) and all(isinstance(v, str) and v.strip() for v in values), code)
    return set(values)


def _antecedents(text: str, inherited: set[str]) -> tuple[set[str], list[str]]:
    introduced = iter(_INTRODUCED_TERM.finditer(text))
    next_term = next(introduced, None)
    known = set(inherited)
    missing = set()
    for ref in _DEFINITE_REF.finditer(text):
        while next_term is not None and next_term.start() < ref.start():
            known.add(next_term[1])
            next_term = next(introduced, None)
        phrase = ref[1]
        words = phrase.split()
        if words[0] in _NON_TERM_REFS or phrase in _ORDINALS:
            continue
        if not any(" ".join(words[:end]) in known for end in range(len(words), 0, -1)):
            missing.add(phrase)
    if next_term is not None:
        known.add(next_term[1])
        known.update(match[1] for match in introduced)
    return known, sorted(missing)


def analyze_us_claims(
    claims: list[dict],
    *,
    mpep_rule_version: str = "MPEP-reference-index-2026-not-professionally-verified",
) -> dict:
    """US 英文权项结构/前置基础/112(b)/112(e)/112(f)/101 启发式分析器。"""
    require(isinstance(mpep_rule_version, str) and bool(mpep_rule_version.strip()), "us_rule_version_invalid")
    known_terms_by_id: dict[int, set[str]] = {}
    multiple_dependent_lineages: set[int] = set()
    issues: list[dict] = []
    warnings: list[dict] = []
    claim_reports = []

    for cid, row, parents in _claim_rows(claims, "us"):
        parent_terms = []
        multiple_dependent_bases = []
        for pid in parents:
            if pid not in known_terms_by_id:
                issues.append({"code": "us_claim_parent_missing_or_forward", "claim_id": cid, "parent_id": pid})
                parent_terms.append(set())
                continue
            parent_terms.append(known_terms_by_id[pid])
            if pid in multiple_dependent_lineages:
                multiple_dependent_bases.append(pid)
        if len(parents) > 1 or multiple_dependent_bases:
            multiple_dependent_lineages.add(cid)
        if len(parents) > 1:
            for pid in multiple_dependent_bases:
                issues.append({
                    "code": "us_112e_multiple_dependent_on_multiple_dependent",
                    "claim_id": cid,
                    "parent_id": pid,
                })

        low = " ".join(row["text"].lower().split())
        ancestor_terms = set.intersection(*parent_terms) if parent_terms else set()
        known_terms, missing_antecedents = _antecedents(low, ancestor_terms)
        if missing_antecedents:
            issues.append({
                "code": "us_112b_missing_antecedent_basis",
                "claim_id": cid,
                "terms": missing_antecedents,
            })

        found_rel = [term for term in US_RELATIVE_TERMS if re.search(rf"\b{re.escape(term)}\b", low)]
        if found_rel:
            warnings.append({"code": "us_112b_relative_term_needs_spec_anchor", "claim_id": cid, "terms": found_rel})

        found_112f = [cue for cue in US_112F_CUES if re.search(rf"\b{re.escape(cue)}\b", low)]
        if found_112f:
            warnings.append({"code": "us_112f_functional_claiming_verify_structure", "claim_id": cid, "cues": found_112f})

        found_101 = [cue for cue in US_101_ABSTRACT_CUES if re.search(rf"\b{re.escape(cue)}\b", low)]
        if found_101:
            warnings.append({
                "code": "us_101_alice_mayo_eligibility_review_required",
                "claim_id": cid,
                "cues": found_101,
            })

        known_terms_by_id[cid] = known_terms
        claim_reports.append({
            "claim_id": cid,
            "kind": "dependent" if parents else "independent",
            "parent_ids": parents,
            "missing_antecedents": missing_antecedents,
            "relative_terms": found_rel,
            "flags_112f": found_112f,
            "flags_101": found_101,
        })

    if list(known_terms_by_id) != list(range(1, len(known_terms_by_id) + 1)):
        issues.append({"code": "us_claim_numbering_gap"})

    return {
        "schema": "dyz-us-claim-analysis-v1",
        "version": VERSION,
        "jurisdiction": "US",
        "rule_source_version": mpep_rule_version,
        "status": "blocked" if issues else "needs_review",
        "input_hash": digest(claims),
        "claims": claim_reports,
        "issues": issues,
        "warnings": warnings,
        "checks_run": [
            "claim_numbering_and_parent_chain",
            "35_usc_112e_multiple_dependent_chain",
            "35_usc_112b_dependency_chain_antecedent_basis_heuristic",
            "35_usc_112b_relative_term_scan",
            "35_usc_112f_means_step_flag",
            "35_usc_101_abstract_cue_flag",
        ],
        "checks_skipped": [
            {"check": "35_usc_112a_full_written_description_and_enablement", "reason": "requires_full_spec_and_professional_judgment"},
            {"check": "35_usc_102_103_prior_art_examination", "reason": "no_prior_art_examination_executed_here"},
        ],
        "legal_conclusion": "not_determined",
        "professional_review": "not_performed",
    }


def _ep_branch_issue(features, embodiments):
    matched = False
    split_details = []
    for emb in embodiments:
        if not features <= emb["features"]:
            continue
        matched = True
        splits = []
        for group in emb["coupled_groups"]:
            taken = features & group
            if taken and taken != group:
                splits.append({"embodiment_id": emb["id"], "taken": sorted(taken), "omitted": sorted(group - taken)})
        if not splits:
            return None
        split_details.extend(splits)
    if matched:
        return {"code": "ep_art123_2_intermediate_generalisation", "details": split_details}
    return {"code": "ep_art123_2_ungrounded_or_mixed_embodiment_features", "feature_ids": sorted(features)}


def analyze_ep_claims(
    claims: list[dict],
    *,
    original_embodiments: list[dict] | None = None,
    epc_rule_version: str = "EPC-Guidelines-2026-static-not-professionally-verified",
) -> dict:
    """EP 英文权项分析器：Rule 43(1) 两段式（含合理例外）、Art. 123(2) 中间概括与 PSA 结构检查。"""
    require(isinstance(epc_rule_version, str) and bool(epc_rule_version.strip()), "ep_rule_version_invalid")
    require(original_embodiments is None or isinstance(original_embodiments, list), "ep_embodiments_list_required")
    embodiments = original_embodiments if original_embodiments is not None else []
    emb_feature_sets = []
    for emb in embodiments:
        require(isinstance(emb, dict) and isinstance(emb.get("id"), str) and bool(emb["id"].strip()),
                "ep_embodiment_invalid")
        groups = emb.get("functionally_linked_groups", [])
        require(isinstance(groups, list), "ep_embodiment_coupled_groups_invalid")
        emb_feature_sets.append({
            "id": emb["id"],
            "features": _feature_set(emb.get("features"), "ep_embodiment_features_invalid"),
            "coupled_groups": [_feature_set(group, "ep_embodiment_coupled_group_invalid") for group in groups],
        })

    issues: list[dict] = []
    warnings: list[dict] = []
    claim_reports = []
    effective_features: dict[int, list[frozenset[str]]] = {}
    for cid, row, parents in _claim_rows(claims, "ep"):
        is_indep = not parents
        has_two_part = bool(EP_TWO_PART_MARKER.search(row["text"]))
        exception_reason = row.get("two_part_not_appropriate_reason", "")
        require(isinstance(exception_reason, str), "ep_two_part_exception_invalid")
        two_part_exception = exception_reason.strip()

        # EPO Guidelines F-IV, 2.3: two-part form "wherever appropriate" — NOT mandatory without exception!
        if is_indep and not has_two_part and not two_part_exception:
            warnings.append({
                "code": "ep_rule43_1_two_part_or_exception_reason_needed",
                "claim_id": cid,
                "reason": "Rule 43(1) applies wherever appropriate; either use two-part form or document why one-part is appropriate.",
            })

        claim_feats = frozenset(_feature_set(row.get("feature_ids", []), "ep_claim_feature_ids_invalid"))
        # 空列表是无效继承；空特征集是存在但缺证的分支。
        branches = {claim_feats: None} if not parents else {}
        invalid_chain = False
        over_budget = False
        for pid in parents:
            if pid not in effective_features:
                issues.append({"code": "ep_claim_parent_missing_or_forward", "claim_id": cid, "parent_id": pid})
            parent_branches = effective_features.get(pid, [])
            invalid_chain |= not parent_branches
            for inherited in parent_branches:
                branches[claim_feats | inherited if claim_feats and inherited else frozenset()] = None
                if len(branches) > MAX_EP_BRANCHES:
                    over_budget = True
                    break
            if over_budget:
                issues.append({"code": "ep_claim_branch_budget_exceeded", "claim_id": cid})
                break
        effective_features[cid] = [] if invalid_chain or over_budget else list(branches)

        if over_budget:
            art123_status = "not_checked_branch_budget_exceeded"
        elif invalid_chain:
            art123_status = "not_checked_invalid_parent_chain"
        elif not any(branches):
            art123_status = "not_checked_no_feature_ids"
        elif not emb_feature_sets:
            art123_status = "not_checked_no_embodiments"
        else:
            branch_issues = []
            for branch in branches:
                issue = _ep_branch_issue(branch, emb_feature_sets) if branch else None
                if issue is not None:
                    branch_issues.append({"claim_id": cid, **issue})
            if branch_issues:
                issues.extend(branch_issues)
                art123_status = "blocked"
            elif frozenset() in branches:
                art123_status = "not_checked_no_feature_ids"
            else:
                art123_status = "checked_finite_feature_set"

        claim_reports.append({
            "claim_id": cid,
            "parent_ids": parents,
            "independent": is_indep,
            "two_part_form": has_two_part,
            "two_part_exception_recorded": bool(two_part_exception),
            "art123_2_check": art123_status,
        })

    if list(effective_features) != list(range(1, len(effective_features) + 1)):
        issues.append({"code": "ep_claim_numbering_gap"})

    return {
        "schema": "dyz-ep-claim-analysis-v1",
        "version": VERSION,
        "jurisdiction": "EP",
        "rule_source_version": epc_rule_version,
        "status": "blocked" if issues else "needs_review",
        "input_hash": digest({"claims": claims, "embodiments": embodiments}),
        "claims": claim_reports,
        "issues": issues,
        "warnings": warnings,
        "checks_run": [
            "ep_rule43_1_two_part_with_appropriate_exception",
            "ep_art123_2_finite_embodiment_and_intermediate_generalisation",
        ],
        "checks_skipped": [
            {"check": "ep_art56_problem_solution_substantive_obviousness", "reason": "requires_prior_art_and_european_patent_attorney"},
            {"check": "ep_art83_sufficiency_of_disclosure", "reason": "requires_full_description_and_skilled_person_assessment"},
        ],
        "legal_conclusion": "not_determined",
        "professional_review": "not_performed",
    }
