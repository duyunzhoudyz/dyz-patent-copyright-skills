"""Phase E3: 专利策略与争议分轨确定性工具（no-go/缩权复评、FTO 四轨矩阵、STD-08/SEP 交接包）。

严禁以单一总分替代专业分析，严禁将“未观察到特征”升级为“不侵权”，严禁把标准采纳等同于专利性或必要性。
"""
from __future__ import annotations

from tools.core import digest, parse_time, require, require_fields

VERSION = "1.0"
DETECTABILITY = frozenset({"observable_external", "internal_unobservable", "partial_observable", "unknown"})
FTO_STATES = frozenset({
    "observed_present",
    "observed_absent_with_evidence",
    "not_observed_unknown",
    "equivalents_pending_legal_review",
})


def _require_strings(row, keys, code):
    require(all(isinstance(row.get(key), str) and row[key].strip() for key in keys), code)


def evaluate_no_go_and_narrowing(payload: dict) -> dict:
    """缩权或对抗检索后的保护价值、绕开与可检测性复评；支持明确输出 no-go 结论。"""
    require(isinstance(payload, dict), "strategy_payload_required")
    require_fields(payload, ("project_id", "narrowed_claim_summary", "detectability", "design_around_paths"))
    _require_strings(payload, ("project_id", "narrowed_claim_summary"), "strategy_identifier_invalid")
    detect = payload["detectability"]
    require(isinstance(detect, str) and detect in DETECTABILITY, "strategy_detectability_invalid")
    design_arounds = payload["design_around_paths"]
    require(isinstance(design_arounds, list), "strategy_design_arounds_list_required")
    for path in design_arounds:
        require(isinstance(path, dict), "strategy_design_around_object_required")
        effort = path.get("effort")
        require(isinstance(effort, str) and effort in {"low", "medium", "high"}, "strategy_design_around_effort_invalid")
        if "id" in path:
            _require_strings(path, ("id",), "strategy_design_around_id_invalid")
    alignment = payload.get("commercial_alignment")
    if "commercial_alignment" in payload:
        require(isinstance(alignment, str) and alignment in {"strong", "moderate", "weak", "unknown"},
                "strategy_commercial_alignment_invalid")
    blocked_prior_art = payload.get("prior_art_blocking_unresolved", False)
    require(type(blocked_prior_art) is bool, "strategy_prior_art_flag_invalid")

    low_effort = sum(path["effort"] == "low" for path in design_arounds)
    reasons = []
    if detect == "internal_unobservable":
        reasons.append("enforcement_detectability_internal_unobservable")
    elif detect == "unknown":
        reasons.append("enforcement_detectability_unknown")
    if low_effort:
        reasons.append("low_effort_design_around_exists")
    if alignment == "weak":
        reasons.append("commercial_alignment_weak")
    if blocked_prior_art:
        reasons.append("prior_art_blocking_unresolved")
        recommendation = "no_go_pending_prior_art_resolution"
    elif detect == "internal_unobservable" and low_effort:
        recommendation = "no_go_recommend_internal_archive_or_trade_secret"
    elif reasons:
        recommendation = "reassess_narrowing_before_filing"
    else:
        recommendation = "proceed_as_internal_candidate_pending_professional_review"

    return {
        "schema": "dyz-patent-no-go-reassessment-v1",
        "version": VERSION,
        "project_id": payload["project_id"],
        "input_hash": digest(payload),
        "detectability": detect,
        "design_around_count": len(design_arounds),
        "low_effort_design_around_count": low_effort,
        "risk_factors": sorted(set(reasons)),
        "working_recommendation": recommendation,
        "single_composite_score": "intentionally_omitted",
        "professional_review": "not_performed",
        "business_decision": "requires_authorized_owner",
    }


def build_fto_four_track_matrix(payload: dict) -> dict:
    """FTO 四轨矩阵：强制区分已观察存在、有证不存在、未观察未知与等同待审。"""
    require(isinstance(payload, dict), "fto_payload_required")
    require_fields(payload, ("product_id", "jurisdiction", "as_of", "patents"))
    _require_strings(payload, ("product_id", "jurisdiction"), "fto_identifier_invalid")
    parse_time(payload["as_of"])
    patents = payload["patents"]
    require(isinstance(patents, list) and bool(patents), "fto_patents_required")

    rows = []
    blocking_unknowns = []
    for pat in patents:
        require(isinstance(pat, dict), "fto_patent_object_required")
        require_fields(pat, ("patent_id", "legal_status", "elements"))
        _require_strings(pat, ("patent_id",), "fto_patent_id_invalid")
        legal_status = pat["legal_status"]
        require(isinstance(legal_status, str) and legal_status in {"in_force", "pending", "expired", "revoked", "unknown"},
                "fto_legal_status_invalid")
        elements = pat["elements"]
        require(isinstance(elements, list) and bool(elements), "fto_elements_required")

        counts = {state: 0 for state in sorted(FTO_STATES)}
        for el in elements:
            require(isinstance(el, dict), "fto_element_object_required")
            require_fields(el, ("element_id", "state"))
            _require_strings(el, ("element_id",), "fto_element_id_invalid")
            state = el["state"]
            require(isinstance(state, str) and state in FTO_STATES, "fto_element_state_invalid")
            if state in {"observed_present", "observed_absent_with_evidence"}:
                evidence_id = el.get("evidence_id")
                require(isinstance(evidence_id, str) and bool(evidence_id.strip()),
                        "fto_observed_state_requires_evidence")
            counts[state] += 1

        if legal_status == "unknown":
            blocking_unknowns.append(f"{pat['patent_id']}:legal_status_unknown")
        if counts["not_observed_unknown"] > 0:
            blocking_unknowns.append(f"{pat['patent_id']}:unobserved_elements_{counts['not_observed_unknown']}")

        if legal_status in {"expired", "revoked"}:
            working_state = "inactive_status_reported_pending_verification"
        elif counts["observed_absent_with_evidence"] > 0 and counts["not_observed_unknown"] == 0 and counts["equivalents_pending_legal_review"] == 0:
            working_state = "literal_absence_evidenced_equivalents_and_legal_review_still_required"
        elif counts["observed_present"] == len(elements):
            working_state = "high_risk_all_elements_observed_present"
        else:
            working_state = "incomplete_or_pending_legal_and_technical_verification"

        rows.append({
            "patent_id": pat["patent_id"],
            "legal_status": legal_status,
            "element_counts": counts,
            "working_state": working_state,
            "non_infringement_certified": False,
        })

    return {
        "schema": "dyz-fto-four-track-matrix-v1",
        "version": VERSION,
        "product_id": payload["product_id"],
        "jurisdiction": payload["jurisdiction"],
        "as_of": payload["as_of"],
        "input_hash": digest(payload),
        "patents": rows,
        "unresolved_unknowns": sorted(set(blocking_unknowns)),
        "fto_clearance_granted": False,
        "professional_review": "not_performed",
    }


def build_sep_handoff_pack(payload: dict) -> dict:
    """STD-08 跨子系统交接：公开前专利支持（PROC-01/02）与 SEP 必要性/政策（RIGHTS-07）双轨分立。"""
    require(isinstance(payload, dict), "sep_payload_required")
    require_fields(payload, ("standard_id", "standard_version", "organization_policy", "clause_links"))
    _require_strings(payload, ("standard_id", "standard_version", "organization_policy"), "sep_identifier_invalid")
    links = payload["clause_links"]
    require(isinstance(links, list) and bool(links), "sep_clause_links_required")

    pre_disclosure_items = []
    essentiality_items = []
    issues = []
    for row in links:
        require(isinstance(row, dict), "sep_link_object_required")
        require_fields(row, ("clause_id", "normative", "related_patent_ids", "filing_support_verified", "technical_alternatives"))
        _require_strings(row, ("clause_id",), "sep_clause_id_invalid")
        require(type(row["normative"]) is bool and type(row["filing_support_verified"]) is bool, "sep_boolean_required")
        if not row["filing_support_verified"]:
            issues.append(f"pre_disclosure_patent_support_unverified:{row['clause_id']}")
        pre_disclosure_items.append({
            "clause_id": row["clause_id"],
            "handoff_target": ["PROC-01", "PROC-02", "ANALYSIS-05", "REVIEW-02"],
            "filing_support_verified": row["filing_support_verified"],
            "public_standard_release_cleared": False,
        })
        patent_ids = row["related_patent_ids"]
        alts = row["technical_alternatives"]
        require(isinstance(patent_ids, list) and all(isinstance(p, str) and p.strip() for p in patent_ids),
                "sep_related_patent_ids_invalid")
        require(isinstance(alts, list), "sep_alternatives_list_required")
        require(all(isinstance(alt, str) and alt.strip() for alt in alts), "sep_alternative_invalid")
        essentiality_items.append({
            "clause_id": row["clause_id"],
            "normative": row["normative"],
            "handoff_target": ["RIGHTS-07", "RIGHTS-03", "RIGHTS-06"],
            "related_patent_ids": list(patent_ids),
            "known_technical_alternatives": alts,
            "essentiality_status": "not_essential_alternative_identified_pending_review" if alts else "candidate_requires_independent_essentiality_review",
            "standard_adoption_proves_patentability": False,
            "essentiality_certified": False,
        })

    return {
        "schema": "dyz-sep-dual-handoff-v1",
        "version": VERSION,
        "standard_id": payload["standard_id"],
        "standard_version": payload["standard_version"],
        "organization_policy": payload["organization_policy"],
        "input_hash": digest(payload),
        "pre_disclosure_protection_track": pre_disclosure_items,
        "essentiality_and_policy_track": essentiality_items,
        "issues": sorted(set(issues)),
        "policy_disclosure_submitted": False,
        "professional_review": "not_performed",
    }
