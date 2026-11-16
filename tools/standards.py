"""技术标准确定性辅助工具（STD-01..12），仅处理调用者提供的获准JSON。

不联网、不读取文件、不执行试验、不产生签核、表决或外发。所有专业
规则由调用方提供并保留来源；机器比较不升级为符合性、认证或组织批准。
"""

from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation

from tools.standards_contract import contract_version, evaluate
from tools.core import (
    ContractError, canonical_bytes, digest, record_deadline, require,
    require_fields, result,
)

CAPABILITIES = [f"STD-{number:02d}" for number in range(1, 13)]
TOOL_VERSION = "1.0"
SEMANTIC_FIELDS = (
    "text", "strength", "kind", "conditions", "exceptions", "quantities",
    "method_ids", "references", "source", "implementation", "features",
)


def _text(value, code: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), code)
    return value


def _strings(value, code: str) -> list[str]:
    require(isinstance(value, list), code)
    for item in value:
        _text(item, code)
    return value


def _records(value, fields: tuple = ("id",), *, unique: bool = True) -> list[dict]:
    require(isinstance(value, list), "records_list_required")
    seen = set()
    for item in value:
        require_fields(item, fields)
        for field in fields:
            _text(item[field], f"string_required:{field}")
        if unique and "id" in fields:
            require(item["id"] not in seen, "duplicate_record_id")
            seen.add(item["id"])
    return value


def _number(value) -> Decimal:
    require(isinstance(value, (int, float, str)) and not isinstance(value, bool),
            "numeric_value_required")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ContractError("invalid_numeric_value") from exc
    require(number.is_finite(), "finite_numeric_value_required")
    return number


def _issue(code: str, record_id: str = "", **details) -> dict:
    return {"code": code, "record_id": record_id, **details}


def _clauses(value) -> list[dict]:
    clauses = _records(value, ("id", "text", "strength", "kind", "source"))
    for clause in clauses:
        require(clause["strength"] in {"requirement", "recommendation", "permission", "statement"},
                "unknown_requirement_strength")
        require(clause["kind"] in {"normative", "informative"}, "unknown_clause_kind")
        for field in ("conditions", "exceptions"):
            require(field in clause, f"missing:{field}")
            _strings(clause[field], f"list_required:{field}")
        for field in ("method_ids", "references", "features"):
            _strings(clause.get(field, []), f"list_required:{field}")
        for quantity in _records(clause.get("quantities", []), ("id", "unit", "source")):
            require("value" in quantity, "missing:quantity_value")
            _number(quantity["value"])
            if "tolerance" in quantity:
                require(_number(quantity["tolerance"]) >= 0, "negative_tolerance")
    return clauses


def _changes(before: list[dict], after: list[dict]) -> list[dict]:
    old, new = {c["id"]: c for c in before}, {c["id"]: c for c in after}
    changes = []
    for key in sorted(old.keys() | new.keys()):
        if key not in old or key not in new:
            changes.append({"clause_id": key, "kind": "added" if key in new else "removed",
                            "fields": [], "review": "required"})
        else:
            fields = [field for field in SEMANTIC_FIELDS if old[key].get(field) != new[key].get(field)]
            if fields:
                changes.append({"clause_id": key, "kind": "modified", "fields": fields,
                                "review": "required"})
    return changes


def _effect_layers(payload: dict, clauses: list[dict]) -> dict:
    nature = payload.get("standard_nature", {})
    require(isinstance(nature, dict), "standard_nature_object_required")
    obligations = _records(payload.get("incorporations", []), ("id", "kind", "scope", "source"))
    for obligation in obligations:
        require(obligation["kind"] in {"law", "regulation", "contract", "procurement"},
                "unknown_incorporation_kind")
    return {
        "clause_strengths": [{"clause_id": c["id"], "strength": c["strength"]} for c in clauses],
        "standard_nature": nature if nature.get("source") else {"value": "unknown"},
        "external_obligations": obligations,
        "universal_legal_obligation": "not_inferred",
    }


def _catalog(payload: dict) -> tuple[dict, list]:
    entries = _records(payload.get("catalog", []), ("id", "number", "edition", "status", "source"))
    nodes, edges, issues = [], [], []
    versions = set()
    for entry in entries:
        key = (entry["number"], entry["edition"])
        require(key not in versions, "duplicate_catalog_version")
        versions.add(key)
        require(entry["status"] in {"current_reported", "withdrawn", "replaced", "draft", "unknown"},
                "unknown_catalog_status")
        access = entry.get("access", {})
        require(isinstance(access, dict), "access_object_required")
        fulltext = access.get("fulltext", "not_acquired")
        require(fulltext in {"authorized", "restricted", "not_acquired", "unknown"}, "invalid_fulltext_access")
        if fulltext == "authorized":
            require(bool(access.get("authority_evidence")), "fulltext_authority_required")
        nodes.append({field: entry[field] for field in ("id", "number", "edition", "status", "source")})
        nodes[-1].update({"access": access, "fulltext": fulltext,
                          "redistribution": access.get("redistribution", "unknown")})
        for relation in ("replaces", "references"):
            for target in _strings(entry.get(relation, []), "catalog_relations_list_required"):
                edges.append({"from": entry["id"], "to": target, "relation": relation})
        if fulltext != "authorized":
            issues.append(_issue("fulltext_not_authorized", entry["id"], access=fulltext))
    known = {node["id"] for node in nodes}
    issues.extend(_issue("unresolved_catalog_reference", edge["from"], target=edge["to"])
                  for edge in edges if edge["to"] not in known)
    logs = _records(payload.get("search_log", []), ("id", "source", "query", "status"))
    for log in logs:
        require(log["status"] in {"complete", "zero_hits", "network_error", "permission_denied", "partial"},
                "unknown_search_status")
        if log["status"] not in {"complete", "zero_hits"}:
            issues.append(_issue("search_incomplete", log["id"], state=log["status"]))
    if not entries and not any(log["status"] == "zero_hits" for log in logs):
        issues.append(_issue("catalog_not_provided"))
    return {"nodes": nodes, "edges": edges, "search_log": logs,
            "coverage": "provided_records_only", "existence_from_missing_fulltext": "not_inferred"}, issues


def _proposal(payload: dict) -> tuple[dict, list]:
    needs = _records(payload.get("needs", []), ("id", "objective", "source"))
    existing = _records(payload.get("existing_scopes", []), ("id", "source"))
    features = set()
    for scope in existing:
        features.update(_strings(scope.get("features", []), "scope_features_required"))
    gaps, issues = [], []
    for need in needs:
        requested = set(_strings(need.get("features", []), "need_features_required"))
        gaps.append({"need_id": need["id"], "objective": need["objective"],
                     "covered_features": sorted(requested & features),
                     "new_features": sorted(requested - features), "source": need["source"],
                     "candidate": "new_or_revised_scope" if requested - features else "coordination_review"})
        if not requested:
            issues.append(_issue("need_scope_missing", need["id"]))
    route = payload.get("route", {})
    require(isinstance(route, dict), "route_object_required")
    if not route.get("source") or not route.get("procedure"):
        issues.append(_issue("route_requires_organization_rule"))
    if not payload.get("maturity_evidence"):
        issues.append(_issue("technical_maturity_unknown"))
    if not needs:
        issues.append(_issue("needs_missing"))
    return {"scope_difference": gaps, "route_candidate": route,
            "maturity_evidence": payload.get("maturity_evidence", []),
            "resources": payload.get("resources", []), "effects": _effect_layers(payload, []),
            "proposal_markdown": "# 立项候选论证\n\n" + "\n".join(
                f"- {g['need_id']}：{g['objective']}；新增特征：{', '.join(g['new_features']) or '无（待协调）'}"
                for g in gaps), "project_approval": "not_asserted"}, issues


def _stakeholders(payload: dict) -> tuple[dict, list]:
    statements = _records(payload.get("statements", []), ("id", "text", "category", "source", "participant_id"))
    participants = _records(payload.get("participants", []), ("id", "group"))
    people = {person["id"]: person for person in participants}
    issues, groups = [], {}
    for statement in statements:
        require(statement["category"] in {"fact", "opinion", "hypothesis"}, "unknown_statement_category")
        groups.setdefault((statement["category"], statement["text"]), []).append(statement["id"])
        person = people.get(statement["participant_id"], {})
        if not person.get("authority_evidence"):
            issues.append(_issue("representative_authority_unproven", statement["id"]))
        if statement["category"] == "fact" and not statement.get("evidence_id"):
            issues.append(_issue("fact_requires_evidence", statement["id"]))
    expected = set(_strings(payload.get("required_groups", []), "required_groups_list_required"))
    missing = sorted(expected - {person["group"] for person in participants})
    issues.extend(_issue("stakeholder_group_missing", group) for group in missing)
    conflicts = [person["id"] for person in participants if person.get("conflict_of_interest")]
    issues.extend(_issue("conflict_of_interest_review", person) for person in conflicts)
    disputes = _records(payload.get("disputes", []), ("id", "source"))
    issues.extend(_issue("unresolved_dispute", d["id"]) for d in disputes
                  if d.get("status") != "resolved_with_evidence" or not d.get("resolution_evidence"))
    return {"statements": statements, "participants": participants,
            "duplicate_groups": [{"category": category, "statement_ids": ids}
                                 for (category, _), ids in groups.items() if len(ids) > 1],
            "missing_groups": missing, "conflicts": conflicts, "disputes": disputes,
            "consensus": "not_inferred"}, issues


def _structure(payload: dict) -> tuple[dict, list]:
    clauses = _clauses(payload.get("clauses", []))
    terms = _records(payload.get("terms", []), ("id", "term", "definition", "source"))
    sections = _records(payload.get("sections", []), ("id", "title", "kind"))
    issues, glossary = [], {}
    for section in sections:
        require(section["kind"] in {"normative", "informative"}, "unknown_section_kind")
    for term in terms:
        glossary.setdefault(term["term"], []).append(term)
    for word, records in glossary.items():
        if len({item["definition"] for item in records}) > 1:
            issues.append(_issue("conflicting_term_definitions", records[0]["id"], term=word))
    issues.extend(_issue("informative_requirement", c["id"]) for c in clauses
                  if c["kind"] == "informative" and c["strength"] == "requirement")
    if not sections:
        issues.append(_issue("organization_structure_not_supplied"))
    return {"sections": sections, "terms": terms, "clauses": clauses,
            "effects": _effect_layers(payload, clauses)}, issues


def _draft(payload: dict) -> tuple[dict, list]:
    clauses = _clauses(payload.get("clauses", []))
    previous = _clauses(payload.get("previous_clauses", []))
    issues, paragraphs = [], ["# 技术标准工作草案", ""]
    for index, clause in enumerate(clauses, 1):
        paragraphs.extend([f"## {index} {clause['id']}", clause["text"],
                           f"性质：{clause['kind']}；强度：{clause['strength']}",
                           "适用条件：" + ("；".join(clause["conditions"]) or "无附加条件（输入声明）"),
                           "例外：" + ("；".join(clause["exceptions"]) or "无（输入声明）")])
        for quantity in clause.get("quantities", []):
            paragraphs.append(f"量值 {quantity['id']}：{quantity['value']} {quantity['unit']}；"
                              f"容差：{quantity.get('tolerance', '未指定')}；依据：{quantity['source']}")
        paragraphs.extend(["来源：" + clause["source"], ""])
        if clause["strength"] == "requirement" and not clause.get("method_ids"):
            issues.append(_issue("verification_method_missing", clause["id"]))
        if clause.get("implementation") and not clause.get("implementation_basis"):
            issues.append(_issue("exclusive_implementation_needs_review", clause["id"]))
    if not clauses:
        issues.append(_issue("clauses_missing"))
    changes = _changes(previous, clauses) if "previous_clauses" in payload else []
    return {"clauses": clauses, "draft_markdown": "\n".join(paragraphs), "semantic_changes": changes,
            "invalidated_reviews": [{"clause_id": c["clause_id"],
                                     "kinds": ["content", "verification", "disclosure"]} for c in changes],
            "automatic_semantic_edit": False}, issues


def _verification(payload: dict) -> tuple[dict, list]:
    clauses = _clauses(payload.get("clauses", []))
    methods = _records(payload.get("methods", []), ("id", "clause_id", "kind", "source"))
    measurements = _records(payload.get("results", []), ("id", "method_id", "evidence_id", "execution_evidence"))
    known_clauses, known_methods = {c["id"] for c in clauses}, {m["id"] for m in methods}
    require(all(m["clause_id"] in known_clauses for m in methods), "method_clause_missing")
    require(all(r["method_id"] in known_methods for r in measurements), "result_method_missing")
    issues, matrix = [], []
    for clause in clauses:
        candidates = [m for m in methods if m["clause_id"] == clause["id"]]
        linked_ids = {m["id"] for m in candidates}
        for method_id in clause.get("method_ids", []):
            if method_id not in linked_ids:
                issues.append(_issue("declared_verification_method_missing", clause["id"], method_id=method_id))
        if not candidates:
            issues.append(_issue("verification_method_missing", clause["id"]))
        for method in candidates:
            require(method["kind"] in {"measurement", "inspection", "document_review", "interoperability"},
                    "unknown_verification_kind")
            blockers = []
            aspects = method.get("methodology", {})
            require(isinstance(aspects, dict), "methodology_object_required")
            required = method.get("required_aspects", [])
            _strings(required, "required_aspects_list_required")
            if method["kind"] == "measurement":
                required = sorted(set(required) | {"sampling", "environment", "equipment", "calibration",
                                                  "uncertainty", "repeatability", "reproducibility", "boundary_rule"})
            if method["kind"] == "interoperability":
                required = sorted(set(required) | {"coverage", "negative_cases", "abnormal_cases"})
            for aspect in required:
                detail = aspects.get(aspect, {})
                require(isinstance(detail, dict), "methodology_detail_object_required")
                if not ((detail.get("status") == "provided" and detail.get("evidence")) or
                        (detail.get("status") == "not_applicable" and detail.get("reason"))):
                    blockers.append(aspect)
            observed = [r for r in measurements if r["method_id"] == method["id"]]
            comparisons = []
            rule = method.get("decision_rule", {})
            require(isinstance(rule, dict), "decision_rule_object_required")
            for observation in observed:
                comparison = "not_evaluated"
                if method["kind"] == "measurement" and rule.get("source") and not blockers:
                    require(rule.get("operator") in {"le", "ge"}, "unsupported_decision_operator")
                    require(rule.get("uncertainty_policy") in {"interval", "ignore_by_rule"},
                            "uncertainty_policy_required")
                    if observation.get("unit") != rule.get("unit") or not rule.get("unit"):
                        blockers.append("unit_mismatch")
                    elif rule["uncertainty_policy"] == "interval" and "uncertainty" not in observation:
                        blockers.append("result_uncertainty_missing")
                    else:
                        value, limit = _number(observation.get("value")), _number(rule.get("limit"))
                        uncertainty = _number(observation.get("uncertainty", 0)) if rule["uncertainty_policy"] == "interval" else Decimal(0)
                        require(uncertainty >= 0, "negative_uncertainty")
                        low, high = value - uncertainty, value + uncertainty
                        if rule["operator"] == "le":
                            comparison = "within_rule" if high <= limit else "outside_rule" if low > limit else "indeterminate"
                        else:
                            comparison = "within_rule" if low >= limit else "outside_rule" if high < limit else "indeterminate"
                elif not rule.get("source"):
                    blockers.append("decision_rule_source_missing")
                comparisons.append({"result_id": observation["id"], "machine_comparison": comparison,
                                    "evidence_id": observation["evidence_id"]})
            if method["kind"] == "measurement" and not rule.get("source"):
                blockers.append("decision_rule_source_missing")
            issues.extend(_issue("methodology_incomplete", method["id"], aspect=b) for b in sorted(set(blockers)))
            if not observed:
                issues.append(_issue("execution_not_provided", method["id"]))
            matrix.append({"clause_id": clause["id"], "method_id": method["id"],
                           "kind": method["kind"], "source": method["source"],
                           "conditions": method.get("conditions", []), "methodology": aspects,
                           "plan": "provided", "execution": "record_provided_unverified" if observed else "not_provided",
                           "results": observed, "comparisons": comparisons,
                           "conformity": "not_determined", "certification": "not_performed",
                           "blockers": sorted(set(blockers))})
    return {"matrix": matrix, "performed_experiments": False}, issues


def _references(payload: dict) -> tuple[dict, list]:
    references = _records(payload.get("references", []), ("id", "number", "edition", "source"))
    updates = _records(payload.get("updates", []), ("id", "reference_id", "edition", "source"))
    usages = _records(payload.get("usages", []), ("id", "reference_id", "clause_id"))
    known = {r["id"]: r for r in references}
    require(all(u["reference_id"] in known for u in usages + updates), "reference_target_missing")
    impacts, issues = [], []
    for update in updates:
        ref = known[update["reference_id"]]
        if ref["edition"] == update["edition"]:
            continue
        for use in usages:
            if use["reference_id"] != ref["id"]:
                continue
            impacts.append({"reference_id": ref["id"], "clause_id": use["clause_id"],
                            "retained_edition": ref["edition"], "candidate_edition": update["edition"],
                            "dated": ref.get("dated", "unknown"),
                            "products": use.get("products", []), "conclusions": use.get("conclusions", []),
                            "review": "required", "automatic_upgrade": False})
    for ref in references:
        if not isinstance(ref.get("dated"), bool) or not ref.get("citation_rule_source"):
            issues.append(_issue("citation_rule_unknown", ref["id"]))
    conflicts = _records(payload.get("conflicts", []), ("id", "source", "description"))
    issues.extend(_issue("coordination_conflict", c["id"]) for c in conflicts)
    return {"references": references, "impacts": impacts, "conflicts": conflicts,
            "effects": _effect_layers(payload, [])}, issues


def _ip_handoff(payload: dict) -> tuple[dict, list]:
    contents = _records(payload.get("contents", []), ("id", "clause_id", "source"))
    mappings = _records(payload.get("support_mappings", []), ("id", "content_id", "jurisdiction", "status"))
    declarations = _records(payload.get("declarations", []), ("id", "source"))
    require(all(m["content_id"] in {c["id"] for c in contents} for m in mappings), "support_content_missing")
    issues, unresolved, protection = [], [], []
    if not contents:
        issues.append(_issue("disclosure_contents_missing"))
    for content in contents:
        targets = _strings(content.get("jurisdictions", []), "jurisdictions_list_required")
        if content.get("protection_required") is False:
            valid_na = bool(content.get("not_applicable_reason") and content.get("public_evidence"))
            protection.append({"content_id": content["id"], "status": "not_applicable" if valid_na else "unknown",
                               "reason": content.get("not_applicable_reason", "")})
            if not valid_na:
                unresolved.append(content["id"])
            continue
        if not targets:
            unresolved.append(content["id"])
        for jurisdiction in targets:
            matches = [m for m in mappings if m["content_id"] == content["id"] and m["jurisdiction"] == jurisdiction]
            # 申请号或自行声称supported不能替代实际原文、日期及专业审阅证据。
            fields = ("application_document_hash", "locator", "date_evidence", "review_evidence", "reviewer_authority")
            supported = len(matches) == 1 and matches[0]["status"] == "supported" and all(matches[0].get(k) for k in fields)
            protection.append({"content_id": content["id"], "jurisdiction": jurisdiction,
                               "status": "review_record_supplied" if supported else "needs_review", "mappings": matches})
            if not supported:
                unresolved.append(content["id"])
    for declaration in declarations:
        if not declaration.get("signer_authority_evidence"):
            issues.append(_issue("declaration_signer_authority_unproven", declaration["id"]))
    conflicts = _records(payload.get("policy_conflicts", []), ("id", "source", "description"))
    competition = _records(payload.get("competition_concerns", []), ("id", "source", "description"))
    if conflicts or competition:
        issues.append(_issue("ip_policy_professional_review_required"))
    issues.extend(_issue("disclosure_support_missing", key) for key in sorted(set(unresolved)))
    return {
        "protection_handoff": {"targets": ["PROC-01", "PROC-02", "ANALYSIS-05", "REVIEW-02"],
                               "contents": contents, "support": protection, "unresolved": sorted(set(unresolved)),
                               "public_route": "blocked" if unresolved or not contents else "requires_core_disclosure_approval"},
        "rights_handoff": {"targets": ["RIGHTS-07", "RIGHTS-03", "RIGHTS-06"],
                           "declarations": declarations, "policy_conflicts": conflicts,
                           "competition_concerns": competition, "necessity": "not_determined",
                           "fto": "not_determined", "license_granted": "not_inferred"},
        "disclosure_executor": "CORE-04/06/07", "release_id": payload.get("release_id"),
        "package_hash": payload.get("package_hash"), "external_action": "not_performed",
    }, issues


COMMENT_OUTCOMES = {"accepted", "partially_accepted", "rejected", "pending"}
COMMENT_CLASSIFICATIONS = {"technical", "editorial", "procedural", "ip", "insufficient_evidence"}
# 编制说明 11 节固定顺序；与 resources/lifecycle/compilation-note.schema.json 的 sectionId 一致。
COMPILATION_NOTE_SECTIONS = (
    "note-01-work-overview", "note-02-background-purpose", "note-03-principles-basis",
    "note-04-technical-content-basis", "note-05-comparison", "note-06-legal-standard-relation",
    "note-07-major-divergence", "note-08-nature-and-implementation",
    "note-09-comment-disposition", "note-10-verification", "note-11-open-items",
)


def _ballot(payload: dict) -> tuple[dict, list]:
    """旧数值统计与资格/同版审查共用；只检查记录，不认定组织程序有效。"""
    participants = _records(copy.deepcopy(payload.get("participants", [])), ("id",))
    votes = _records(copy.deepcopy(payload.get("votes", [])), ("id", "participant_id", "choice", "evidence_id"))
    require(len({v["participant_id"] for v in votes}) == len(votes), "duplicate_participant_vote")
    people = {p["id"]: p for p in participants}
    issues, valid_votes = [], []

    def eligibility_status(participant):
        if participant.get("eligible") is False:
            return "invalid"
        evidence = participant.get("authority_evidence")
        return ("valid" if participant.get("eligible") is True
                and isinstance(evidence, str) and evidence.strip() else "unknown")

    def review_status(states):
        if "invalid" in states:
            return "invalid"
        return "unknown" if not states or "unknown" in states else "valid"

    vote_checks, bound_votes = [], []
    for vote in votes:
        require(vote["choice"] in {"yes", "no", "abstain"}, "invalid_vote_choice")
        participant = people.get(vote["participant_id"], {})
        # 旧数值口径仅筛显式资格和truthy依据，保留兼容；不补推同版。
        legacy_eligible = participant.get("eligible") is True and bool(participant.get("authority_evidence"))
        if legacy_eligible:
            valid_votes.append(vote)
        else:
            issues.append(_issue("vote_authority_unproven", vote["id"]))
        eligibility = eligibility_status(participant)
        if eligibility == "invalid":
            issues.append(_issue("vote_ineligible", vote["id"]))
        elif eligibility == "unknown" and legacy_eligible:
            issues.append(_issue("vote_authority_unproven", vote["id"]))
        version = vote.get("version")
        require(version is None or isinstance(version, str), "vote_version_string_required")
        same_version = ("unknown" if not version or not version.strip() else
                        "valid" if version == payload["version"] else "invalid")
        if same_version != "valid":
            issues.append(_issue("vote_version_unproven" if same_version == "unknown"
                                 else "vote_version_mismatch", vote["id"]))
        state = review_status([eligibility, same_version])
        vote_checks.append({"vote_id": vote["id"], "participant_id": vote["participant_id"],
                            "version": version, "eligibility_status": eligibility,
                            "same_version_status": same_version, "status": state})
        if state == "valid":
            bound_votes.append(vote)
    rule = payload.get("ballot_rule", {})
    require(isinstance(rule, dict), "ballot_rule_object_required")
    counts = {choice: sum(v["choice"] == choice for v in valid_votes) for choice in ("yes", "no", "abstain")}
    assessment = "unknown"
    if rule.get("source") and all(k in rule for k in ("min_votes", "min_yes_fraction", "denominator")):
        require(rule["denominator"] in {"cast", "non_abstaining", "eligible"}, "invalid_ballot_denominator")
        require(type(rule["min_votes"]) is int and rule["min_votes"] > 0, "invalid_quorum")
        fraction = _number(rule["min_yes_fraction"])
        require(0 < fraction <= 1, "invalid_ballot_fraction")
        denominator = (len(valid_votes) if rule["denominator"] == "cast" else
                       counts["yes"] + counts["no"] if rule["denominator"] == "non_abstaining" else
                       sum(p.get("eligible") is True and bool(p.get("authority_evidence")) for p in participants))
        met = len(valid_votes) >= rule["min_votes"] and denominator > 0 and Decimal(counts["yes"]) / denominator >= fraction
        assessment = "numeric_conditions_met" if met else "numeric_conditions_not_met"
    else:
        issues.append(_issue("organization_ballot_rule_missing"))
    eligibility = review_status([check["eligibility_status"] for check in vote_checks])
    same_version = review_status([check["same_version_status"] for check in vote_checks])
    denominator_eligibility = "not_applicable"
    if rule.get("denominator") == "eligible":
        # 未投票者的未知资格同样影响eligible分母；明确不具资格者仅排除于分母。
        unknown_people = [p["id"] for p in participants if eligibility_status(p) == "unknown"]
        denominator_eligibility = "unknown" if unknown_people else "valid"
        issues.extend(_issue("ballot_denominator_eligibility_unproven", pid) for pid in unknown_people)
    governance_status = review_status([eligibility, same_version, denominator_eligibility])
    if governance_status == "valid":
        governance_status = {"numeric_conditions_met": "internal_checks_met",
                             "numeric_conditions_not_met": "internal_checks_not_met"}.get(assessment, "unknown")
    # valid仅表示提交记录的内部一致性，不认证人员或证据真实性，也不修复原程序。
    ballot_governance = {
        "status": governance_status, "scope": "internal_records_only", "version": payload["version"],
        "eligibility_status": eligibility, "same_version_status": same_version,
        "denominator_eligibility_status": denominator_eligibility, "vote_checks": vote_checks,
        "qualified_same_version_vote_counts": {
            choice: sum(v["choice"] == choice for v in bound_votes) for choice in ("yes", "no", "abstain")},
    }
    return {"participants": participants, "votes": votes, "valid_vote_counts": counts,
            "ballot_rule": copy.deepcopy(rule), "ballot_assessment": assessment,
            "ballot_governance": ballot_governance}, issues


def _governance(payload: dict) -> tuple[dict, list]:
    comments = _records(payload.get("comments", []), ("id", "clause_id", "text", "source", "participant_id"))
    participants = _records(payload.get("participants", []), ("id",))
    decisions = _records(payload.get("decisions", []), ("id", "comment_id", "decision", "reason", "source"))
    # 同一意见可多人提出：comment_id 去重仍是硬要求，但允许一意见多处置行的“来源拆分”需显式声明
    # 聚合行；否则 duplicate_comment_decision。
    outcomes = _records(payload.get("comment_outcomes", []), ("comment_id", "outcome"))
    known_comments, people = {c["id"] for c in comments}, {p["id"]: p for p in participants}
    require(all(d["comment_id"] in known_comments for d in decisions), "decision_comment_missing")
    require(len({d["comment_id"] for d in decisions}) == len(decisions), "duplicate_comment_decision")
    issues, groups, dispositions = [], {}, []
    for comment in comments:
        groups.setdefault((comment["clause_id"], comment["text"]), []).append(comment["id"])
        decision = next((d for d in decisions if d["comment_id"] == comment["id"]), None)
        dispositions.append({"comment": comment, "decision": decision, "minority_retained": bool(comment.get("minority"))})
        if decision is None:
            issues.append(_issue("comment_disposition_missing", comment["id"]))
        elif not decision.get("reviewer_authority"):
            issues.append(_issue("decision_authority_unproven", decision["id"]))
        if not people.get(comment["participant_id"], {}).get("authority_evidence"):
            issues.append(_issue("representative_authority_unproven", comment["id"]))
    # AF-04：意见处理结果受控词表。旧 decision 字段保留为自由文本（历史兼容），
    # 新 comment_outcomes 用枚举校验逐条闭环；两者都缺时才算未处置。
    outcome_rows, tally = {}, {name: 0 for name in COMMENT_OUTCOMES}
    for row in outcomes:
        cid = _text(row["comment_id"], "comment_outcome_comment_required")
        require(cid in known_comments, "comment_outcome_comment_missing")
        require(cid not in outcome_rows, "duplicate_comment_outcome")
        require(row["outcome"] in COMMENT_OUTCOMES, "comment_outcome_unknown")
        outcome_rows[cid] = row
        tally[row["outcome"]] += 1
        for field in ("reason", "proposed_text", "unresolved_item"):
            if field in row and row[field] is not None:
                _text(row[field], f"comment_outcome_{field}_required")
        if row["outcome"] in {"accepted", "partially_accepted"}:
            # 采纳必须有落点：拟改文字或条款引用至少一项。
            require(bool(row.get("proposed_text")) != bool(row.get("clause_id")),
                    "accepted_text_unresolved")
            if row.get("clause_id"):
                _text(row["clause_id"], "comment_outcome_clause_required")
        if row["outcome"] == "rejected":
            # 不采纳必须有理由与依据来源，不能只写“不予采纳”。
            require(row.get("reason"), "rejection_reason_unsourced")
            require(row.get("reason_source"), "rejection_reason_unsourced")
            _text(row["reason_source"], "rejection_reason_unsourced")
        if row["outcome"] == "pending":
            # 挂起必须绑定未决项与责任人。
            require(row.get("unresolved_item"), "pending_item_unowned")
            require(row.get("owner"), "pending_item_unowned")
            _text(row["owner"], "pending_item_unowned")
        if "classification" in row:
            require(row["classification"] in COMMENT_CLASSIFICATIONS,
                    "comment_classification_unknown")
        if "major_change" in row:
            require(row["major_change"] in {"yes", "no", "undetermined"},
                    "comment_major_change_unknown")
    for comment in comments:
        if comment["id"] in outcome_rows:
            continue
        # 受控 outcome 是硬要求：旧 decisions 自由文本只能作为补充信息，
        # 不能充当处置结果，否则四值枚举可被绕过。
        issues.append(_issue("comment_outcome_missing", comment["id"]))
    ballot, ballot_issues = _ballot(payload)
    issues.extend(ballot_issues)
    modifications = _records(payload.get("modifications", []), ("id", "clause_id", "source"))
    major_rule = payload.get("major_change_rule", {})
    require(isinstance(major_rule, dict), "major_change_rule_object_required")
    deadlines = payload.get("deadlines", [])
    require(isinstance(deadlines, list), "deadlines_list_required")
    deadline_checks = []
    for deadline in deadlines:
        require(isinstance(deadline, dict) and deadline.get("business") == "standard",
                "standard_deadline_required")
        deadline_checks.append(record_deadline(deadline))
    rereview = []
    for modification in modifications:
        if modification.get("major") is True:
            rereview.append({"modification_id": modification["id"], "clause_id": modification["clause_id"],
                             "action": "reconsultation_required" if major_rule.get("source") and major_rule.get("reconsultation") is True
                             else "organization_decision_required"})
    appeals = _records(payload.get("appeals", []), ("id", "source", "status"))
    issues.extend(_issue("appeal_pending", a["id"]) for a in appeals if a["status"] != "closed_with_evidence" or not a.get("closure_evidence"))
    return {"dispositions": dispositions,
            "duplicate_groups": [ids for ids in groups.values() if len(ids) > 1],
            "comment_outcomes": [outcome_rows[c["id"]] for c in comments if c["id"] in outcome_rows],
            "outcome_tally": {**tally, "total_ranked": sum(tally.values()),
                              "tally_balanced": sum(tally.values()) == len(outcome_rows)},
            **ballot, "major_change_review": rereview,
            "appeals": appeals, "deadlines": deadlines, "deadline_checks": deadline_checks,
            "deadline_owner": "STD-09/11", "consensus": "not_inferred",
            "organization_approval": "not_asserted"}, issues


def _adoption(payload: dict) -> tuple[dict, list]:
    source = _clauses(payload.get("source_clauses", []))
    target = _clauses(payload.get("target_clauses", []))
    mappings = _records(payload.get("mappings", []), ("id", "source_id", "target_id", "source"))
    old, new = {c["id"]: c for c in source}, {c["id"]: c for c in target}
    require(all(m["source_id"] in old and m["target_id"] in new for m in mappings), "adoption_mapping_target_missing")
    issues, comparisons = [], []
    for mapping in mappings:
        left, right = old[mapping["source_id"]], new[mapping["target_id"]]
        fields = [f for f in SEMANTIC_FIELDS if f != "source" and left.get(f) != right.get(f)]
        technical = [f for f in fields if f != "text"]
        comparisons.append({"mapping_id": mapping["id"], "source_id": left["id"], "target_id": right["id"],
                            "changed_fields": fields, "technical_differences": technical,
                            "translation_review": "required" if "text" in fields else "not_asserted",
                            "source": mapping["source"]})
    mapped_old, mapped_new = {m["source_id"] for m in mappings}, {m["target_id"] for m in mappings}
    unmapped = {"source": sorted(old.keys() - mapped_old), "target": sorted(new.keys() - mapped_new)}
    if any(unmapped.values()):
        issues.append(_issue("unmapped_adoption_clauses"))
    permissions = payload.get("translation_permission", {})
    require(isinstance(permissions, dict), "translation_permission_object_required")
    if permissions.get("decision") != "allow" or not permissions.get("source"):
        issues.append(_issue("translation_permission_unproven"))
    if not payload.get("adoption_rule_source"):
        issues.append(_issue("adoption_rule_missing"))
    return {"comparisons": comparisons, "unmapped": unmapped,
            "bilingual_terms": _records(payload.get("bilingual_terms", []), ("id", "source_term", "target_term", "source")),
            "proposal": payload.get("proposal", {}), "adoption_relationship": "not_determined",
            "translation_is_idt": False, "new_disclosure_review": "required_if_target_disclosed"}, issues


def _candidate(payload: dict) -> tuple[dict, list]:
    clauses = _clauses(payload.get("clauses", []))
    artifacts = _records(payload.get("documents", []), ("id", "role", "hash", "source"))
    matrix = _records(payload.get("verification_matrix", []), ("id", "clause_id", "source"))
    issues, checklist = [], []
    ids = {c["id"] for c in clauses}
    external_references = _strings(payload.get("external_reference_ids", []), "external_reference_ids_list_required")
    require(all(m["clause_id"] in ids for m in matrix), "matrix_clause_missing")
    for clause in clauses:
        mapped = [m for m in matrix if m["clause_id"] == clause["id"]]
        okay = bool(mapped) and all(m.get("review_evidence") and m.get("result_evidence")
                                    and m.get("clause_hash") == digest(clause) for m in mapped)
        checklist.append({"item": "verification_evidence", "clause_id": clause["id"], "state": "record_provided" if okay else "missing"})
        if clause["strength"] == "requirement" and not okay:
            issues.append(_issue("required_verification_missing", clause["id"]))
        for ref in clause.get("references", []):
            if ref not in ids and ref not in external_references:
                issues.append(_issue("unresolved_clause_reference", clause["id"], target=ref))
    roles = {d["role"] for d in artifacts}
    required = _strings(payload.get("required_document_roles", ["draft", "explanatory_note", "comment_dispositions", "verification_evidence"]), "document_roles_list_required")
    for role in required:
        if role not in roles:
            issues.append(_issue("candidate_document_missing", role))
    public_documents = [d for d in artifacts if d["role"] != "internal_risk_report"]
    internal_documents = [d for d in artifacts if d["role"] == "internal_risk_report"]
    reviews = _records(payload.get("reviews", []), ("id", "reviewer", "source"))
    for review in reviews:
        if (review.get("actor_type") != "human" or not review.get("authority_evidence") or
                review.get("content_hash") != digest(clauses) or review.get("decision") != "accepted"):
            issues.append(_issue("independent_review_unproven_or_stale", review["id"]))
    if not reviews:
        issues.append(_issue("independent_review_missing"))
    unresolved = _strings(payload.get("unresolved_items", []), "unresolved_items_list_required")
    issues.extend(_issue("unresolved_candidate_item", item) for item in unresolved)
    # AF-03：编制说明结构校验。清单声明了 explanatory_note 角色（或显式提供了
    # compilation_note）时必须有结构，不能只靠一个文件名充当交代。未声明该角色
    # 且未提供结构时保持历史行为，不额外报错。
    note = payload.get("compilation_note", {})
    note_checks = []
    if note or "explanatory_note" in roles:
        require(isinstance(note, dict), "compilation_note_object_required")
        # 角色文件已声明（roles 为实际上交文件，不是 required 声明）时必须有结构；
        # 仅有必需角色而尚未交文件的情形由 candidate_document_missing 负责。
        if "explanatory_note" in roles:
            require(bool(note), "compilation_note_structure_missing")
        sections = _records(note.get("sections", []), ("id", "heading", "state", "owner"))
        # 注意：_records 自身已挡重复 id（duplicate_record_id）并要求上述四字段齐备；
        # source/question/reason/open_items 为按状态触发的条件字段，不进入必填元组。
        present = [s["id"] for s in sections]
        missing = [name for name in COMPILATION_NOTE_SECTIONS if name not in present]
        if missing:
            require(not (note.get("require_complete") is True),
                                    "compilation_note_section_missing:" + ",".join(missing))
            issues.append(_issue("compilation_note_section_missing", ",".join(missing)))
        for section in sections:
            require(section["state"] in {"explicit", "inferred", "unknown", "not_applicable"},
                    "compilation_note_state_unknown")
            _text(section["owner"], "compilation_note_state_unowned")
            if section["state"] == "unknown" and not section.get("question"):
                issues.append(_issue("compilation_note_state_unowned", section["id"]))
            if section["state"] == "not_applicable" and not section.get("reason"):
                issues.append(_issue("compilation_note_not_applicable_unreasoned", section["id"]))
            if section["state"] == "explicit" and not section.get("source"):
                issues.append(_issue("compilation_note_source_missing", section["id"]))
            if section["id"] == "note-11-open-items":
                for item in section.get("open_items", []) or []:
                    require(isinstance(item, dict), "open_item_object_required")
                    require(all(item.get(k) for k in ("question", "owner", "blocks", "recovery")),
                            "pending_item_unowned")
                    require(item["blocks"] in {"submission", "approval", "publication", "none"},
                            "open_item_blocks_unknown")
            note_checks.append({"id": section["id"], "state": section["state"],
                                "sourced": bool(section.get("source"))})
        # 说明必须跟着正文版本；digest 不匹配即为旧版说明。
        if note.get("clause_digest") and note["clause_digest"] != digest(clauses):
            issues.append(_issue("compilation_note_stale"))
    if not clauses:
        issues.append(_issue("clauses_missing"))
    return {"checklist": checklist, "candidate_documents": public_documents,
            "internal_documents": internal_documents, "content_hash": digest(clauses),
            "candidate_manifest_hash": digest(public_documents), "reviews": reviews,
            "candidate_status": "needs_evidence" if issues else "prepared_for_professional_review",
            "compilation_note": note, "compilation_note_sections": note_checks,
            "organization_records": payload.get("organization_records", []),
            "organization_approval": "not_asserted", "submission": "not_performed",
            "disclosure_executor": "CORE-04/06/07"}, issues


def _revision(payload: dict) -> tuple[dict, list]:
    before = _clauses(payload.get("previous_clauses", []))
    after = _clauses(payload.get("clauses", []))
    changes = _changes(before, after)
    changed_ids = {c["clause_id"] for c in changes}
    usages = _records(payload.get("dependencies", []), ("id", "clause_id", "kind", "source"))
    revision_type = payload.get("revision_type", "unknown")
    require(revision_type in {"correction", "amendment", "revision", "replacement", "withdrawal", "unknown"},
            "unknown_revision_type")
    issues = []
    if not payload.get("classification_rule_source") or revision_type == "unknown":
        issues.append(_issue("revision_classification_requires_rule"))
    transition = payload.get("transition", {})
    require(isinstance(transition, dict), "transition_object_required")
    if not transition.get("source"):
        issues.append(_issue("transition_rule_unknown"))
    impacts = [{**dep, "state": "needs_review", "prior_conclusion_retained": True}
               for dep in usages if dep["clause_id"] in changed_ids]
    new_disclosure = [c["clause_id"] for c in changes
                      if c["kind"] == "added" or any(f in c["fields"] for f in SEMANTIC_FIELDS)]
    return {"revision_type_candidate": revision_type, "classification_rule_source": payload.get("classification_rule_source"),
            "changes": changes, "impacts": impacts, "transition": transition,
            "feedback": _records(payload.get("feedback", []), ("id", "source", "description")),
            "disclosure_reassessment": new_disclosure,
            "review_invalidation": [{"clause_id": key, "reviews": ["content", "verification", "disclosure"]} for key in sorted(changed_ids)],
            "effective_status": "not_asserted", "history_preserved": before}, issues


_HANDLERS = dict(zip(CAPABILITIES, (
    _catalog, _proposal, _stakeholders, _structure, _draft, _verification,
    _references, _ip_handoff, _governance, _adoption, _candidate, _revision,
)))


def closed_loop(payload: dict) -> dict:
    """检查显式v2闭环并派生统计、未决和说明引用，不验证实物或专业正确性。

    第9/10/11节可声明outcome_tally、verification_summary、open_items；
    有矛盾时保留原值并报告，派生真值位于compilation_note_derived。
    本接口不回填comment_outcomes，也不继承任何专业或有权决定结论。
    """
    # v2只共享表决检查；其问题须在说明统计核对之前进入同一派生链。
    ballot, ballot_issues = {}, []
    if "votes" in payload or "ballot_rule" in payload:
        require_fields(payload, ("version",))
        ballot, ballot_issues = _ballot(payload)
        if ballot["ballot_assessment"] == "numeric_conditions_not_met":
            ballot_issues.append(_issue("ballot_numeric_conditions_not_met"))
    artifacts = evaluate(payload, section_ids=COMPILATION_NOTE_SECTIONS,
                         clause_validator=_clauses, semantic_fields=SEMANTIC_FIELDS,
                         initial_issues=ballot_issues)
    # 纯业务入口只比较内存文字；最终DOCX和原件证据由受控成件层另行核验。
    from tools.standard_review import assess
    finite = assess(payload)
    artifacts['finite_review'] = finite
    artifacts['pending_reviews'] = copy.deepcopy(finite['pending_reviews'])
    existing = {digest(issue) for issue in artifacts['issues']}
    artifacts['issues'].extend(copy.deepcopy(issue) for issue in finite['issues']
                               if digest(issue) not in existing)
    artifacts.update(ballot)
    return artifacts


def _closed_candidate(data: dict, artifacts: dict, issues: list) -> None:
    """v2送审保留证据边界；必需角色不由调用者缩小。"""
    documents = _records(data.get("documents", []), ("id", "role", "hash", "source"))
    required = {"draft", "explanatory_note", "comment_dispositions", "verification_evidence", "review_report"}
    required.update(_strings(data.get("required_document_roles", []), "document_roles_list_required"))
    for role in sorted(required - {doc["role"] for doc in documents}):
        issues.append(_issue("candidate_document_missing", role))
    matrix = data.get("verification_matrix", [])
    for clause in data.get("clauses", []):
        if clause.get("strength") == "requirement":
            mapped = [row for row in matrix if row["clause_id"] == clause["id"]]
            if not mapped or not all(row.get("result_evidence") and row.get("review_evidence")
                                     and row.get("clause_hash") == digest(clause) for row in mapped):
                issues.append(_issue("required_verification_missing", clause["id"]))
    reviews = _records(data.get("reviews", []), ("id", "reviewer", "source"))
    if not reviews:
        issues.append(_issue("independent_review_missing"))
    for review in reviews:
        if (review.get("actor_type") != "human" or not review.get("authority_evidence")
                or review.get("content_hash") != artifacts["clause_digest"]
                or review.get("decision") != "accepted"):
            issues.append(_issue("independent_review_unproven_or_stale", review["id"]))
    artifacts.update({
        "candidate_documents": [doc for doc in documents if doc["role"] != "internal_risk_report"],
        "internal_documents": [doc for doc in documents if doc["role"] == "internal_risk_report"],
        "content_hash": artifacts["clause_digest"], "reviews": reviews,
        "candidate_status": ("needs_evidence" if issues else "needs_semantic_review"
                             if artifacts.get("pending_reviews") else "prepared_for_professional_review"),
        "disclosure_executor": "CORE-04/06/07",
    })


def run(capability: str, payload: dict) -> dict:
    """返回绑定输入版本的草拟辅助结果；格式错误抛ContractError。

    所有能力需project_id、version及四轴adaptation。不适用需理由；输入
    previous_input_hash可显式标记旧版审核失效，旧签核永不继承。
    调用前必须完成CORE材料权限及宿主数据路径预检；本函数没有文件入口。
    """
    require(isinstance(capability, str) and capability in _HANDLERS, "unsupported_standard_capability")
    selected_version = contract_version(payload)
    require(selected_version == 1 or capability in {"STD-09", "STD-11"},
            "standard_contract_v2_capability_unsupported")
    require_fields(payload, ("project_id", "version", "adaptation"))
    _text(payload["project_id"], "project_id_required")
    _text(payload["version"], "version_required")
    adaptation = payload["adaptation"]
    require_fields(adaptation, ("organization", "standard_type", "domain", "stage"))
    for axis in ("organization", "standard_type", "domain", "stage"):
        _text(adaptation[axis], f"adaptation_required:{axis}")
    canonical_bytes(payload)
    _strings(payload.get("evidence_ids", []), "evidence_ids_list_required")
    if "applicable" in payload:
        require(type(payload["applicable"]) is bool, "applicable_boolean_required")
    if "previous_input_hash" in payload:
        _text(payload["previous_input_hash"], "previous_input_hash_required")
    data = copy.deepcopy(payload)
    if data.get("applicable") is False:
        _text(data.get("not_applicable_reason"), "not_applicable_reason_required")
        artifacts, issues, status = {"reason": data["not_applicable_reason"]}, [], "not_applicable"
    elif selected_version == 2:
        artifacts = closed_loop(data)
        issues = artifacts.pop("issues")
        if capability == "STD-11":
            _closed_candidate(data, artifacts, issues)
        status = "needs_evidence" if issues else "needs_review"
    else:
        artifacts, issues = _HANDLERS[capability](data)
        status = "needs_evidence" if issues else "needs_review"
    artifacts["contract_version"] = selected_version
    artifacts["contract_mode"] = "legacy" if selected_version == 1 else "closed_loop"
    current_hash = digest({k: v for k, v in data.items() if k != "previous_input_hash"})
    changed = bool(data.get("previous_input_hash") and data["previous_input_hash"] != current_hash)
    artifacts["bindings"] = {"project_id": data["project_id"], "version": data["version"],
                              "input_hash": current_hash, "tool_version": TOOL_VERSION,
                              "prior_review": "invalidated" if changed else "not_inherited"}
    return result(capability, status=status, artifacts=artifacts, issues=issues,
                  evidence=data.get("evidence_ids", []), adaptation=adaptation,
                  checks=[f"AC-{capability}:deterministic_assistance", "no_external_action"])
