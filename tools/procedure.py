"""专利程序、争议和组合的确定性辅助；不提交、不联网、不签核。

输入是已获准的结构化事实，而非命令、路径或待执行工具调用。
支持、法律状态与规则审阅均为调用者提供的证据主张，不由工具认证。
"""

from __future__ import annotations

import calendar
import copy
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from tools.core import (
    ContractError, digest, parse_time, require, require_fields, result, select_rules,
)

CAPABILITIES = (
    *(f"PROC-{n:02d}" for n in range(1, 10)),
    *(f"RIGHTS-{n:02d}" for n in range(1, 8)),
    "SEARCH-07", "SEARCH-08", "LIFE-02",
)


def _items(data: dict, key: str, *, identity: str | None = "id") -> list[dict]:
    require(key in data and isinstance(data[key], list), f"list_required:{key}")
    rows = data[key]
    require(all(isinstance(row, dict) for row in rows), f"objects_required:{key}")
    if identity:
        for row in rows:
            require_fields(row, (identity,))
            require(isinstance(row[identity], str), f"string_id_required:{key}")
        require(len({row[identity] for row in rows}) == len(rows),
                f"duplicate_id:{key}")
    return rows


def _strings(value, name: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    ), f"strings_required:{name}")
    require(len(set(value)) == len(value), f"duplicate_value:{name}")
    require(not nonempty or bool(value), f"nonempty_required:{name}")
    return value


class _Context:
    def __init__(self, capability: str, payload: dict):
        require_fields(payload, ("adaptation", "as_of", "evidence"))
        require_fields(payload["adaptation"],
                       ("jurisdiction", "right_type", "domain", "stage"))
        self.capability = capability
        self.p = payload
        self.now = parse_time(payload["as_of"])
        self.evidence = _items(payload, "evidence")
        self.ids = {row["id"] for row in self.evidence}
        for row in self.evidence:
            require_fields(row, ("version", "source", "locator", "kind"))
            require(row["kind"] in {"synthetic", "public", "authorized"},
                    "evidence_kind_unknown")
        self._validate_references(payload)
        self.binding = digest({k: v for k, v in payload.items()
                               if k != "previous_input_digest"})

    def _validate_references(self, value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "evidence_ids" or key.endswith("_evidence_ids"):
                    refs = _strings(child, key)
                    require(set(refs) <= self.ids, "evidence_reference_missing")
                elif key.endswith("_at") and child is not None:
                    parse_time(child)
                else:
                    self._validate_references(child)
        elif isinstance(value, list):
            for child in value:
                self._validate_references(child)

    def refs(self, record: dict, key: str = "evidence_ids") -> bool:
        return bool(record.get(key))

    def finish(self, artifacts: dict, issues: list[str] | None = None,
               *, status: str | None = None) -> dict:
        issues = sorted(set(issues or []))
        status = status or ("needs_evidence" if issues else "needs_review")
        artifacts.update(input_digest=self.binding,
                         legal_conclusion="not_determined",
                         evidence_authenticity="not_verified")
        previous = self.p.get("previous_input_digest")
        if previous is not None:
            require(isinstance(previous, str) and bool(re.fullmatch(
                r"[0-9a-f]{64}", previous)), "invalid_previous_digest")
            artifacts["previous_input_digest"] = previous
            artifacts["review_reuse"] = "not_granted"
            if previous != self.binding:
                artifacts["recomputed_status"] = status
                status = "invalidated"
                issues.append("input_version_changed_re_review_required")
        return result(self.capability, status=status, artifacts=artifacts,
                      issues=issues, evidence=self.evidence,
                      adaptation=self.p["adaptation"],
                      checks=["structured_facts_only", "AC-" + self.capability])


def _timeline(c: _Context) -> dict:
    p = c.p
    contents = _items(p, "contents")
    content_ids = {row["id"] for row in contents}
    require(bool(content_ids), "contents_required")
    targets = _strings(p.get("target_regions"), "target_regions", nonempty=True)
    events, issues, potential = [], [], []
    for event in _items(p, "events"):
        require_fields(event, ("kind", "content_ids", "access", "location"))
        require(set(_strings(event["content_ids"], "content_ids", nonempty=True))
                <= content_ids, "event_content_missing")
        require(event["access"] in {"public", "confidential", "unknown"},
                "unknown_access_state")
        if not event.get("occurred_at") or not c.refs(event):
            issues.append("event_date_or_source_unknown")
        # 公开分支、演示和销售等事件不依赖产品上线或主分支合并状态。
        effective_access = event["access"]
        if effective_access == "confidential" and not event.get(
                "confidentiality_evidence_ids"):
            effective_access = "unknown"
            issues.append("confidentiality_unproven")
        if effective_access in {"public", "unknown"}:
            potential.append(event["id"])
        if effective_access == "unknown":
            issues.append("disclosure_access_unknown")
        events.append({**event, "effective_access": effective_access})
    if not events:
        issues.append("disclosure_history_not_supplied")
    events.sort(key=lambda row: (not bool(row.get("occurred_at")),
        parse_time(row["occurred_at"]) if row.get("occurred_at") else c.now,
        row["id"]))
    conditions = _items(p, "conditions", identity=None)
    required = {"confidentiality", "foreign_filing", "first_filing"}
    checks = []
    for region in targets:
        for kind in sorted(required):
            supplied = [r for r in conditions
                        if r.get("jurisdiction") == region and r.get("kind") == kind]
            state = "unknown"
            if len(supplied) == 1 and c.refs(supplied[0]):
                state = supplied[0].get("state", "unknown")
                require(state in {"confirmed", "unknown", "not_applicable"},
                        "condition_state_unknown")
                if state == "not_applicable" and not supplied[0].get("reason"):
                    state = "unknown"
            if state == "unknown":
                issues.append("regional_disclosure_conditions_unresolved")
            checks.append({"jurisdiction": region, "kind": kind, "state": state})
    return c.finish({"timeline": events, "potential_disclosures": potential,
                     "regional_checks": checks, "public_release_opinion": "defer",
                     "handoff": ["PROC-02", "ANALYSIS-05", "REVIEW-02", "CORE-04"]},
                    issues)


def _support(c: _Context) -> dict:
    p = c.p
    apps = _items(p, "applications")
    app_by_id = {a["id"]: a for a in apps}
    targets = _strings(p.get("target_regions"), "target_regions", nonempty=True)
    issues, matrix, edges = [], [], []
    for app in apps:
        require_fields(app, ("jurisdiction", "version", "submitted"))
        require(type(app["submitted"]) is bool, "submitted_boolean_required")
        parent = app.get("parent_id")
        if parent:
            require(parent in app_by_id, "parent_application_missing")
            edges.append([parent, app["id"]])
        seen, cursor = set(), app
        while cursor.get("parent_id"):
            require(cursor["id"] not in seen, "application_cycle")
            seen.add(cursor["id"])
            require(cursor["parent_id"] in app_by_id, "parent_application_missing")
            cursor = app_by_id[cursor["parent_id"]]
    content_rows = _items(p, "contents")
    require(bool(content_rows), "contents_required")
    for content in content_rows:
        require_fields(content, ("kind",))
        mappings = _items(content, "mappings", identity=None)
        mapped_ids = []
        for mapping in mappings:
            require_fields(mapping, ("application_id", "support"))
            require(mapping["application_id"] in app_by_id,
                    "support_application_missing")
            require(mapping["support"] in {"confirmed", "new", "unknown"},
                    "support_state_unknown")
            mapped_ids.append(mapping["application_id"])
        require(len(set(mapped_ids)) == len(mapped_ids), "duplicate_support_mapping")
        for region in targets:
            candidates, recorded = [], []
            for mapping in mappings:
                app = app_by_id[mapping["application_id"]]
                if app["jurisdiction"] != region:
                    continue
                recorded.append(mapping)
                if (mapping["support"] != "confirmed" or not c.refs(mapping)
                        or not mapping.get("locator") or not app["submitted"]
                        or not app.get("filing_at") or not c.refs(app)):
                    continue
                # 优先权日期只接受逐内容证据，不从同族或申请级字段继承。
                priority = app.get("priority_at") if (
                    mapping.get("priority_supported") is True
                    and c.refs(mapping, "priority_evidence_ids")) else None
                candidates.append({"application_id": app["id"],
                    "application_version": app["version"],
                    "filing_at": app["filing_at"], "priority_at": priority,
                    "claimed_priority_at": app.get("priority_at"),
                    "locator": mapping["locator"],
                    "evidence_ids": mapping["evidence_ids"],
                    "date_status": "caller_supported_candidate_not_legal_finding"})
            state = "supported_candidate" if candidates else (
                "new" if recorded and all(m["support"] == "new" for m in recorded)
                else "unknown")
            if state != "supported_candidate":
                issues.append("content_support_or_date_unresolved")
            matrix.append({"content_id": content["id"], "kind": content["kind"],
                           "jurisdiction": region, "state": state,
                           "mappings": recorded, "date_candidates": candidates})
    artifacts = {"support_matrix": matrix, "applications": apps,
                 "effective_date_decision": "requires_professional_review"}
    if c.capability == "PROC-07":
        conditions = _items(p, "route_conditions", identity=None)
        artifacts.update(edges=edges, route_conditions=conditions,
                         route_decision="undetermined")
        if not conditions or any(not c.refs(r) or r.get("state") != "confirmed"
                                 for r in conditions):
            issues.append("subsequent_route_conditions_unresolved")
    return c.finish(artifacts, issues)


def _entry(c: _Context) -> dict:
    rows, issues = [], []
    rules = _items(c.p, "rules", identity=None)
    for route in _items(c.p, "routes"):
        require_fields(route, ("jurisdiction", "rule_id", "materials", "language"))
        _strings(route["materials"], "materials")
        adaptation = {**c.p["adaptation"], "jurisdiction": route["jurisdiction"]}
        selected = select_rules(rules, adaptation, as_of=c.p["as_of"])
        matching = [r for r in selected["artifacts"]["selected"]
                    if r["rule_id"] == route["rule_id"]]
        due, arithmetic, rule_version = None, None, None
        if len(matching) != 1 or not route.get("anchor_at") or not c.refs(route):
            issues.append("entry_rule_or_anchor_unverified")
        else:
            rule = matching[0]
            interval = rule.get("interval")
            require_fields(interval, ("unit", "value"))
            require(type(interval["value"]) is int and 0 <= interval["value"] <= 1200,
                    "invalid_rule_interval")
            require(interval["unit"] in {"days", "months"}, "interval_unit_unsupported")
            # 保留给定偏移量作日历运算；不猜时区、节假日或法定例外。
            start = datetime.fromisoformat(route["anchor_at"].replace("Z", "+00:00"))
            try:
                if interval["unit"] == "days":
                    calculated = start + timedelta(days=interval["value"])
                else:
                    index = start.year * 12 + start.month - 1 + interval["value"]
                    year, month = divmod(index, 12)
                    month += 1
                    calculated = start.replace(year=year, month=month, day=min(
                        start.day, calendar.monthrange(year, month)[1]))
            except (ValueError, OverflowError) as exc:
                raise ContractError("date_out_of_range") from exc
            arithmetic = calculated.isoformat()
            due, rule_version = arithmetic, rule["version"]
            adjustment = route.get("adjustment")
            if adjustment is not None:
                require_fields(adjustment, ("due_at", "reason"))
                if not c.refs(adjustment):
                    due = None
                    issues.append("date_adjustment_evidence_missing")
                else:
                    due = adjustment["due_at"]
        for key in ("representative", "fee_basis"):
            if route.get(key) in (None, "unknown", "pending"):
                issues.append("entry_qualification_or_fee_unresolved")
        rows.append({**route, "candidate_due_at": due, "arithmetic_due_at": arithmetic,
                     "rule_version": rule_version, "deadline_verified": False,
                     "calendar_policy": "fixed_offset_month_end_clamp_explicit_adjustments",
                     "human_review": "required"})
    return c.finish({"routes": rows}, issues)


def _citation_tasks(c: _Context) -> list[dict]:
    tasks = []
    for citation in _items(c.p, "citations"):
        require_fields(citation, ("origin_jurisdiction",))
        targets = _items(c.p, "disclosure_targets", identity=None)
        if not targets:
            tasks.append({"citation_id": citation["id"],
                          "origin_jurisdiction": citation["origin_jurisdiction"],
                          "jurisdiction": None, "owner": None,
                          "status": "target_scope_unknown", "due_at": None,
                          "submission": "not_performed", "receipt": None})
        for target in targets:
            require_fields(target, ("jurisdiction", "owner"))
            status = "applicability_unknown"
            if not c.refs(citation):
                status = "citation_source_unknown"
            elif target.get("applicable") is True and target.get("rule_evidence_ids"):
                status = "prepare_disclosure_review"
            elif (target.get("applicable") is False and target.get("reason")
                  and target.get("rule_evidence_ids")):
                status = "not_applicable"
            tasks.append({"citation_id": citation["id"],
                          "origin_jurisdiction": citation["origin_jurisdiction"],
                          "jurisdiction": target["jurisdiction"],
                          "owner": target["owner"], "status": status,
                          "due_at": target.get("due_at"),
                          "rule_evidence_ids": target.get("rule_evidence_ids", []),
                          "submission": "not_performed", "receipt": None})
    return tasks


def _filing(c: _Context) -> dict:
    p = c.p
    files = _items(p, "files")
    required = _strings(p.get("required_files"), "required_files", nonempty=True)
    for file in files:
        require(isinstance(file.get("sha256"), str) and bool(re.fullmatch(
            r"[0-9a-f]{64}", file["sha256"])), "invalid_file_hash")
    manifest = digest(sorted(files, key=lambda f: f["id"]))
    missing = sorted(set(required) - {f["id"] for f in files})
    transmission = p.get("transmission")
    require_fields(transmission, ("state",))
    state = transmission["state"]
    require(state in {"not_attempted", "transport_success", "unknown", "failed"},
            "transmission_state_unknown")
    issues = ["missing_submission_files"] if missing else []
    receipt = p.get("receipt")
    filing_fact = "unverified"
    if receipt is not None:
        require_fields(receipt, ("manifest_digest", "application_id", "filing_at"))
        if receipt["manifest_digest"] != manifest:
            issues.append("receipt_manifest_mismatch")
        elif c.refs(receipt) and not missing:
            filing_fact = "recorded_claim_requires_official_verification"
        else:
            issues.append("receipt_evidence_missing")
    else:
        issues.append("official_receipt_missing")
    tasks = _citation_tasks(c)
    if any(t["status"] != "not_applicable" for t in tasks):
        issues.append("citation_disclosure_review_required")
    return c.finish({"files": files, "manifest_digest": manifest,
                     "missing_files": missing, "transmission_state": state,
                     "receipt": receipt, "filing_fact": filing_fact,
                     "retry_allowed": False, "citation_tasks": tasks,
                     "next_action": "verify_outcome_before_any_new_attempt" if state == "unknown"
                     else "professional_submission_review"}, issues,
                    status="failed" if state == "failed" else (
                        "unknown" if state == "unknown" else None))


def _replacement_fidelity(c: _Context, responses: list[dict], candidates: list[dict]) -> dict:
    """核实际答复和候选；文本到命题的解释仍由调用者负责。"""
    p = c.p
    if "fidelity" not in p:
        require("fidelity_bindings" not in p, "fidelity_payload_required")
        return {"status": "not_performed", "natural_language_verified": False,
                "professional_review": "not_performed"}
    from .fidelity import audit_bound_text
    texts = {"response:" + row["opinion_id"]: row["text"] for row in responses}
    texts.update({"replacement:" + row["id"]: row["text"] for row in candidates})
    report = audit_bound_text(p["fidelity"], texts, p.get("fidelity_bindings"))
    documents = {row["id"]: row for row in p["fidelity"]["documents"]}
    facts = {row["id"]: row for row in p["fidelity"]["facts"]}
    original_version = (p.get("original_application") or {}).get("version")

    def block(code, candidate_id, **details):
        report["issues"].append({"code": code, "candidate_id": candidate_id,
                                 "severity": "blocking", **details})
        report["status"] = "blocked"

    for candidate in candidates:
        identity = candidate["id"]
        cite = p["fidelity_bindings"]["replacement:" + identity]
        if documents[cite["document_id"]]["version"] != candidate["version"]:
            block("replacement_version_mismatch", identity)
        assertions = [row for row in report["assertions"]
                      if row["citation"]["document_id"] == cite["document_id"]
                      and row["citation"]["start"] < cite["end"]
                      and cite["start"] < row["citation"]["end"]]
        if not assertions:
            block("replacement_assertions_missing", identity)
        for assertion in assertions:
            location = assertion["citation"]
            if not (cite["start"] <= location["start"] < location["end"] <= cite["end"]):
                block("replacement_assertion_crosses_boundary", identity,
                      assertion_id=assertion["assertion_id"])
            if assertion["proof_scope"] != "original_support" or assertion["mode"] != "asserted":
                block("replacement_original_support_required", identity,
                      assertion_id=assertion["assertion_id"])
            for fact_id in assertion["accepted_basis_fact_ids"]:
                source = documents[facts[fact_id]["citation"]["document_id"]]
                if source["role"] != "original" or source["version"] != original_version:
                    block("replacement_original_version_mismatch", identity, fact_id=fact_id)
    return report


def _office_action(c: _Context) -> dict:
    p = c.p
    notice = p.get("notice")
    require_fields(notice, ("id", "version", "kind", "complete", "opinions"))
    require(notice["kind"] in {"synthetic", "official"}, "notice_kind_unknown")
    require(type(notice["complete"]) is bool, "notice_complete_boolean_required")
    opinions = _items(notice, "opinions")
    ids = {r["id"] for r in opinions}
    require(bool(ids), "notice_opinions_required")
    responses = _items(p, "responses", identity="opinion_id")
    for row in responses:
        require_fields(row, ("text",))
        require(isinstance(row["text"], str) and bool(row["text"].strip()),
                "response_text_required")
        require(row["opinion_id"] in ids, "response_opinion_missing")
    answered = {r["opinion_id"] for r in responses if c.refs(r)}
    missing = sorted(ids - answered)
    issues = ["opinion_responses_incomplete"] if missing else []
    if not c.refs(notice):
        issues.append("notice_source_missing")
    if not notice["complete"]:
        issues.append("notice_incomplete")
    for key in ("served_at", "due_at"):
        if not notice.get(key):
            issues.append(f"notice_{key}_unknown")
    for key in ("current_claims", "original_application"):
        record = p.get(key)
        if record is None:
            issues.append(f"{key}_missing")
        else:
            require_fields(record, ("version",))
            if not c.refs(record):
                issues.append(f"{key}_source_missing")
    unsupported = []
    amendments = _items(p, "amendments")
    for amendment in amendments:
        require_fields(amendment, ("before", "after", "support"))
        require(amendment["support"] in {"confirmed", "new", "unknown"},
                "amendment_support_unknown")
        if (amendment["support"] != "confirmed" or not amendment.get("locator")
                or not c.refs(amendment) or not p.get("original_application")
                or amendment.get("original_version") != p["original_application"]["version"]):
            unsupported.append(amendment["id"])
    if unsupported:
        issues.append("amendment_support_unresolved")
    if "replacement_required" in p:
        require(type(p["replacement_required"]) is bool, "replacement_required_boolean_required")
    candidates = _items(p, "replacement_candidates") if "replacement_candidates" in p else []
    for candidate in candidates:
        require(isinstance(candidate["id"], str) and bool(candidate["id"].strip()),
                "replacement_id_required")
        require(isinstance(candidate.get("version"), str) and bool(candidate["version"].strip()),
                "replacement_version_required")
        require(isinstance(candidate.get("text"), str) and bool(candidate["text"].strip()),
                "replacement_text_required")
        require(candidate.get("coverage") in ("partial", "complete"), "replacement_coverage_unknown")
        if candidate["coverage"] == "partial":
            require(isinstance(candidate.get("boundary"), str) and bool(candidate["boundary"].strip()),
                    "replacement_boundary_required")
        if not c.refs(candidate):
            issues.append("replacement_candidate_source_missing")
    if candidates:
        replacement_status = ("supplied_partial" if any(row["coverage"] == "partial" for row in candidates)
                              else "supplied_complete")
    elif p.get("replacement_required") is True:
        replacement_status = "missing"
        issues.append("replacement_candidate_missing")
    else:
        replacement_status = "not_requested" if p.get("replacement_required") is False else "not_declared"
    fidelity = _replacement_fidelity(c, responses, candidates)
    issues.extend("fidelity:" + row["code"] for row in fidelity.get("issues", []))
    from .fidelity import audit_text_quality
    texts = {"response:" + row["opinion_id"]: row["text"] for row in responses}
    texts.update({"replacement:" + row["id"]: row["text"] for row in candidates})
    quality = (audit_text_quality(texts, business="patent", stage="draft") if texts else
               {"status": "not_performed", "issues": [], "reason": "no_deliverable_text",
                "semantic_fidelity": "not_performed", "professional_review": "not_performed"})
    issues.extend("text_quality:" + row["code"] for row in quality["issues"])
    require(p.get("delivery_stage", "draft") in {"draft", "final"}, "patent_delivery_stage_invalid")
    final_text_gate = {"status": "not_performed", "delivery_allowed": False,
                       "reason": "internal_draft_only"}
    if p.get("delivery_stage") == "final" or "final_text_sources" in p:
        from .patent_gate import require_final_text
        sources = p.get("final_text_sources")
        if sources is None:
            sources = [row for row in p.get("fidelity", {}).get("documents", [])
                       if row.get("role") == "original"]
        final_text_gate = require_final_text(texts, sources)
    tasks = _citation_tasks(c)
    if any(task["status"] != "not_applicable" for task in tasks):
        issues.append("citation_disclosure_review_required")
    return c.finish({"notice_id": notice["id"], "notice_version": notice["version"],
                     "notice_kind": notice["kind"], "opinions": opinions,
                     "current_claims": p.get("current_claims"),
                     "original_application": p.get("original_application"),
                     "responses": responses, "unanswered_opinions": missing,
                     "amendments": amendments, "unsupported_amendments": unsupported,
                     "replacement_candidates": candidates, "replacement_status": replacement_status,
                     "replacement_coverage": "caller_declared_not_verified", "fidelity": fidelity,
                     "text_quality": quality, "final_text_gate": final_text_gate,
                     "citation_tasks": tasks, "response_status": "draft"}, issues,
                    status="blocked" if "blocked" in (fidelity["status"], quality["status"]) else None)


def _correction(c: _Context) -> dict:
    agenda = _items(c.p, "agenda")
    minutes = _items(c.p, "minutes")
    defects = _items(c.p, "defects")
    confirmed, unconfirmed, tasks, issues = [], [], [], []
    if not agenda and not minutes and not defects:
        issues.append("correction_or_communication_facts_missing")
    for minute in minutes:
        require_fields(minute, ("text",))
        if minute.get("participant_confirmed") is True and c.refs(minute):
            confirmed.append(minute)
        else:
            unconfirmed.append(minute)
            issues.append("minutes_not_participant_confirmed")
    actions = {"missing_document": "verify_missing_document_remedy",
               "incorrect_field": "verify_form_correction_route",
               "restriction": "review_election_and_support",
               "submission_error": "verify_official_submission_record"}
    for defect in defects:
        require(defect.get("kind") in actions, "defect_kind_unsupported")
        tasks.append({**defect, "action": actions[defect["kind"]],
                      "status": "needs_review", "executed": False})
        if not c.refs(defect):
            issues.append("defect_evidence_missing")
    return c.finish({"agenda": agenda, "confirmed_minutes": confirmed,
                     "unconfirmed_minutes": unconfirmed, "repair_tasks": tasks}, issues)


def _remedies(c: _Context) -> dict:
    events = _items(c.p, "events")
    decisions = _items(c.p, "decisions")
    paths, issues = [], []
    if not events:
        issues.append("procedural_events_missing")
    for event in events:
        require_fields(event, ("kind",))
        if not event.get("occurred_at") or not c.refs(event):
            issues.append("procedural_event_evidence_missing")
    for remedy in _items(c.p, "remedies"):
        require_fields(remedy, ("jurisdiction", "rule_id", "eligibility"))
        require(remedy["eligibility"] in {"unknown", "candidate", "not_applicable"},
                "remedy_eligibility_unknown")
        effective = remedy["eligibility"]
        if not c.refs(remedy) or not remedy.get("rule_evidence_ids"):
            effective = "unknown"
        if effective == "not_applicable" and not remedy.get("reason"):
            effective = "unknown"
        if effective == "unknown" or not remedy.get("due_at"):
            issues.append("remedy_applicability_or_deadline_unknown")
        paths.append({**remedy, "eligibility": effective, "request_status": "not_filed"})
    if not paths:
        issues.append("remedy_paths_require_professional_identification")
    return c.finish({"events": events, "decisions": decisions,
                     "remedy_paths": paths, "rights_outcome": "undetermined"}, issues)


def _grant(c: _Context) -> dict:
    p = c.p
    for key in ("official", "approved"):
        require_fields(p.get(key), ("version", "sections"))
        require(isinstance(p[key]["sections"], dict), "section_map_required")
        require(all(isinstance(k, str) and isinstance(v, str)
                    for k, v in p[key]["sections"].items()), "section_text_required")
    official, approved = p["official"]["sections"], p["approved"]["sections"]
    diffs = [{"section_id": key, "official": official.get(key),
              "approved": approved.get(key)}
             for key in sorted(official.keys() | approved.keys())
             if official.get(key) != approved.get(key)]
    issues = []
    if not official or not approved:
        issues.append("text_sections_missing")
    if not c.refs(p["official"]) or not c.refs(p["approved"]):
        issues.append("text_source_missing")
    routes = _items(p, "routes")
    for route in routes:
        require_fields(route, ("jurisdiction",))
    return c.finish({"official_version": p["official"]["version"],
                     "approved_version": p["approved"]["version"],
                     "differences": diffs, "routes": routes,
                     "correction_status": "needs_review" if diffs else "no_text_difference",
                     "effect_or_registration": "not_asserted"}, issues)


def _claim_matrix(c: _Context) -> tuple[dict, list[str]]:
    p = c.p
    require_fields(p.get("product"), ("id", "version"))
    claims = _items(p, "claims")
    require(bool(claims), "claims_required")
    observations = _items(p, "observations", identity=None)
    keys, rows, issues, unknown = set(), [], [], []
    for claim in claims:
        require_fields(claim, ("version", "jurisdiction", "text_kind", "legal_status"))
        require(claim["text_kind"] == "claims", "full_claims_required")
        require(claim["legal_status"] in {"active", "expired", "pending", "unknown"},
                "claim_status_unknown")
        elements = _items(claim, "elements")
        require(bool(elements), "claim_elements_required")
        if not c.refs(claim) or not claim.get("status_at"):
            issues.append("claim_source_or_status_date_missing")
        for element in elements:
            require_fields(element, ("text",))
            keys.add((claim["id"], element["id"]))
            found = [o for o in observations if o.get("claim_id") == claim["id"]
                     and o.get("element_id") == element["id"]]
            require(len(found) <= 1, "duplicate_element_observation")
            obs = found[0] if found else {}
            if obs:
                require(obs.get("state") in {"present", "absent", "unobserved", "unknown"},
                        "observation_state_unknown")
                require_fields(obs, ("claim_version", "source_kind"))
            usable = (obs.get("claim_version") == claim["version"]
                      and obs.get("product_version") == p["product"]["version"]
                      and obs.get("source_kind") == "technical" and c.refs(obs)
                      and bool(obs.get("locator")))
            state = obs.get("state", "unknown") if usable else "unknown"
            if state in {"unknown", "unobserved"}:
                unknown.append(f"{claim['id']}:{element['id']}")
                issues.append("product_element_evidence_unknown")
            rows.append({"claim_id": claim["id"], "claim_version": claim["version"],
                         "jurisdiction": claim["jurisdiction"],
                         "element_id": element["id"], "text": element["text"],
                         "state": state, "reported_state": obs.get("state", "unknown"),
                         "observation": obs, "equivalence": "requires_professional_review"})
    for obs in observations:
        require((obs.get("claim_id"), obs.get("element_id")) in keys,
                "observation_claim_element_missing")
    return {"product": p["product"], "claims": claims, "matrix": rows,
            "unknown_elements": unknown, "infringement": "undetermined"}, issues


def _rights_matrix(c: _Context) -> dict:
    artifacts, issues = _claim_matrix(c)
    if c.capability == "RIGHTS-03":
        territories = _strings(c.p.get("territories"), "territories", nonempty=True)
        activities = _strings(c.p.get("activities"), "activities", nonempty=True)
        search = c.p.get("search")
        require_fields(search, ("status", "coverage"))
        require(search["status"] in {"complete", "partial", "failed", "unknown"},
                "search_status_unknown")
        _strings(search["coverage"], "coverage")
        if search["status"] != "complete" or not search["coverage"] or not c.refs(search):
            issues.append("fto_search_coverage_incomplete")
        statuses = []
        for claim in artifacts["claims"]:
            in_region = claim["jurisdiction"] in territories
            if claim["legal_status"] == "unknown" or not claim.get("status_at"):
                issues.append("fto_legal_status_unknown")
            elif parse_time(claim["status_at"]) != c.now:
                issues.append("fto_status_snapshot_requires_refresh")
            statuses.append({"claim_id": claim["id"], "jurisdiction": claim["jurisdiction"],
                             "in_scope": in_region, "legal_status": claim["legal_status"],
                             "status_at": claim.get("status_at")})
        artifacts.update(fto="undetermined", territories=territories,
                         activities=activities, as_of=c.p["as_of"],
                         search=search, status_scope=statuses,
                         own_patents_do_not_clear_fto=True)
    elif c.capability == "RIGHTS-05":
        require_fields(c.p, ("previous_product_version", "search_product_version"))
        changes = _items(c.p, "changes")
        screened = _strings(c.p.get("screened_claim_ids"), "screened_claim_ids")
        ids = {claim["id"] for claim in artifacts["claims"]}
        require(set(screened) <= ids, "screened_claim_missing")
        evidenced = {claim_id for claim_id in screened if all(
            row["state"] not in {"unknown", "unobserved"}
            for row in artifacts["matrix"] if row["claim_id"] == claim_id)}
        remaining = sorted(ids - evidenced)
        search_required = c.p["search_product_version"] != c.p["product"]["version"]
        if remaining or search_required:
            issues.append("redesign_rescreen_required")
        for change in changes:
            require_fields(change, ("description", "functional_impact"))
            if not c.refs(change):
                issues.append("independent_design_evidence_missing")
        artifacts.update(changes=changes, remaining_claims=remaining,
                         search_required=search_required, safe_design=False,
                         validation_plan=[{"change_id": row["id"],
                             "action": "validate_function_and_rescreen_all_claims"}
                             for row in changes])
    return c.finish(artifacts, issues)


def _purpose_search(c: _Context) -> dict:
    p = c.p
    purpose = p.get("purpose")
    require(purpose in {"invalidity", "fto"}, "search_purpose_required")
    if c.capability == "RIGHTS-04":
        require(purpose == "invalidity", "invalidity_purpose_required")
    territories = _strings(p.get("territories"), "territories", nonempty=True)
    critical = parse_time(p["critical_at"]) if p.get("critical_at") else None
    documents = _items(p, "documents")
    candidates, issues = [], []
    if not documents:
        issues.append("candidate_set_empty_coverage_unverified")
    for doc in documents:
        require_fields(doc, ("jurisdiction", "legal_status"))
        require(doc["legal_status"] in {"active", "expired", "pending", "unknown"},
                "document_status_unknown")
        if purpose == "invalidity":
            if not critical or not doc.get("public_at") or not c.refs(doc):
                selection, reason = "lead_only", "publication_or_critical_date_unproven"
                issues.append(reason)
            elif parse_time(doc["public_at"]) > critical:
                selection, reason = "special_date_review", "later_publication_prior_filing_rules_unchecked"
                issues.append(reason)
            else:
                selection, reason = "candidate", "publication_precedes_key_date_status_not_filter"
        elif doc["jurisdiction"] not in territories:
            selection, reason = "outside_territory", "other_family_members_not_cleared"
        elif not c.refs(doc) or not doc.get("status_at") or doc["legal_status"] == "unknown":
            selection, reason = "needs_status", "legal_status_unproven"
            issues.append(reason)
        elif parse_time(doc["status_at"]) != c.now:
            selection, reason = "needs_status", "status_snapshot_requires_refresh"
            issues.append(reason)
        elif doc["legal_status"] == "expired":
            selection, reason = "not_current_target", "recorded_expired_at_snapshot_only"
        else:
            selection, reason = "candidate", "claim_scope_and_status_review_needed"
        candidates.append({**doc, "selection": selection, "reason": reason})
    artifacts = {"purpose": purpose, "critical_at": p.get("critical_at"),
                 "territories": territories, "candidates": candidates,
                 "global_clearance": False}
    if c.capability == "RIGHTS-04":
        grounds = _items(p, "grounds")
        ids = {d["id"] for d in documents}
        for ground in grounds:
            require_fields(ground, ("claim_id", "reason", "burden", "document_ids"))
            require(set(_strings(ground["document_ids"], "document_ids", nonempty=True))
                    <= ids, "ground_document_missing")
        artifacts.update(grounds=grounds, invalidity="undetermined",
                         procedure=c.p["adaptation"], burden_review="required")
    return c.finish(artifacts, issues)


def _license(c: _Context) -> dict:
    p = c.p
    require_fields(p.get("request"), ("products", "territories", "actions"))
    license_record = p.get("license")
    require_fields(license_record, ("id", "state", "products", "territories", "actions"))
    require(license_record["state"] in {"draft", "promised", "executed", "unknown"},
            "license_state_unknown")
    gaps = {}
    for key in ("products", "territories", "actions"):
        wanted = _strings(p["request"][key], key, nonempty=True)
        covered = _strings(license_record[key], key)
        gaps[key] = sorted(set(wanted) - set(covered))
    diligence = []
    if not c.refs(license_record, "authority_evidence_ids"):
        diligence.append("signing_authority_unknown")
    if not c.refs(license_record, "chain_evidence_ids"):
        diligence.append("rights_chain_unknown")
    if license_record.get("encumbrances") in (None, "unknown"):
        diligence.append("encumbrances_unknown")
    if license_record["state"] != "executed" or not c.refs(license_record):
        diligence.append("executed_license_not_evidenced")
    if not license_record.get("valid_from") or not license_record.get("valid_until"):
        diligence.append("license_interval_unknown")
    elif not (parse_time(license_record["valid_from"]) <= c.now
              < parse_time(license_record["valid_until"])):
        diligence.append("license_outside_interval")
    issues = diligence + (["license_scope_gap"] if any(gaps.values()) else [])
    return c.finish({"scope_gaps": gaps, "due_diligence": diligence,
                     "license_record": license_record, "permission": "undetermined",
                     "signature": "not_performed", "valuation": "not_performed"}, issues)


def _sep(c: _Context) -> dict:
    p = c.p
    declarations = _items(p, "declarations")
    require_fields(p.get("standard"), ("id", "version", "clauses"))
    clauses = _strings(p["standard"]["clauses"], "clauses", nonempty=True)
    claims = _items(p, "claims")
    require(bool(claims), "claims_required")
    claim_by_id = {r["id"]: r for r in claims}
    mappings = _items(p, "mappings", identity=None)
    issues, missing = [], []
    for mapping in mappings:
        require(mapping.get("claim_id") in claim_by_id, "mapping_claim_missing")
        claim = claim_by_id[mapping["claim_id"]]
        require(mapping.get("element_id") in {e["id"] for e in _items(claim, "elements")},
                "mapping_element_missing")
        require(mapping.get("clause_id") in clauses, "mapping_clause_missing")
    for declaration in declarations:
        require(declaration.get("claim_id") in claim_by_id, "declaration_claim_missing")
        if not c.refs(declaration):
            issues.append("declaration_source_missing")
    for claim in claims:
        require_fields(claim, ("version",))
        for element in _items(claim, "elements"):
            matching = [m for m in mappings if m.get("claim_id") == claim["id"]
                        and m.get("element_id") == element["id"]
                        and m.get("claim_version") == claim["version"]
                        and m.get("standard_version") == p["standard"]["version"]
                        and m.get("clause_id") in clauses and c.refs(m)
                        and m.get("locator")]
            if not matching:
                missing.append({"claim_id": claim["id"], "element_id": element["id"]})
    if missing:
        issues.append("essentiality_mapping_incomplete")
    conflicts = _strings(p.get("policy_conflicts"), "policy_conflicts")
    if conflicts:
        issues.append("policy_or_competition_conflict_requires_professional_review")
    return c.finish({"declarations": declarations, "standard": p["standard"],
                     "mappings": mappings, "missing_mappings": missing,
                     "policy_conflicts": conflicts, "essentiality": "undetermined",
                     "alternative_implementations": "not_excluded",
                     "license": "not_established", "fto": "not_established",
                     "frand_commitment": "not_signed", "handoff": "STD-08"}, issues)


def _landscape(c: _Context) -> dict:
    p = c.p
    require(p.get("counting") in {"document", "family"}, "counting_basis_required")
    require_fields(p.get("window"), ("start", "end"))
    start, end = parse_time(p["window"]["start"]), parse_time(p["window"]["end"])
    require(start <= end, "invalid_time_window")
    docs = _items(p, "documents")
    coverage = _items(p, "coverage", identity=None)
    issues, included, unknown_dates, groups = [], [], [], {}
    for doc in docs:
        require_fields(doc, ("category", "effect"))
        require(all(isinstance(doc[k], str) for k in ("category", "effect")),
                "landscape_labels_must_be_strings")
        if not doc.get("public_at") or not c.refs(doc):
            unknown_dates.append(doc["id"])
            issues.append("landscape_date_or_source_unknown")
            continue
        if not start <= parse_time(doc["public_at"]) <= end:
            continue
        included.append(doc["id"])
        key = ("document", doc["id"])
        if p["counting"] == "family":
            if doc.get("family_id"):
                require(isinstance(doc["family_id"], str), "family_id_string_required")
                key = ("family", doc["family_id"])
            else:
                issues.append("family_unknown_counted_separately")
        groups.setdefault(key, []).append(doc)
    cells = {}
    for members in groups.values():
        # 每个计数实体在每个技术-功效格仅计一次；跨格总和可超过实体数。
        for category, effect in {(d["category"], d["effect"]) for d in members}:
            cells[(category, effect)] = cells.get((category, effect), 0) + 1
    if not coverage or any(row.get("status") != "complete" for row in coverage):
        issues.append("source_coverage_incomplete")
    return c.finish({"counting": p["counting"], "window": p["window"],
                     "total": len(groups), "included_document_ids": included,
                     "unknown_date_ids": unknown_dates, "coverage": coverage,
                     "matrix": [{"category": key[0], "effect": key[1], "count": value}
                                for key, value in sorted(cells.items())],
                     "cell_totals_may_overlap": True,
                     "white_space_is_patentability": False,
                     "monitoring": "snapshot_only_no_scheduler"}, issues,
                    status="partial" if issues else "checked")


def _budget(c: _Context) -> dict:
    totals, expired, rows, issues = {}, [], [], []
    quotes = _items(c.p, "quotes")
    if not quotes:
        issues.append("budget_quotes_missing")
    for quote in quotes:
        require_fields(quote, ("family_id", "amount", "currency", "decision"))
        require(quote["decision"] in {"maintain", "abandon_proposed", "undecided"},
                "budget_decision_unknown")
        require(isinstance(quote["currency"], str) and bool(re.fullmatch(
            r"[A-Z]{3}", quote["currency"])), "currency_code_required")
        require(isinstance(quote["amount"], (str, int, float))
                and not isinstance(quote["amount"], bool), "amount_required")
        try:
            amount = Decimal(str(quote["amount"]))
        except InvalidOperation as exc:
            raise ContractError("invalid_amount") from exc
        require(amount.is_finite() and amount >= 0, "invalid_amount")
        state = "unknown"
        if quote.get("valid_from") and quote.get("valid_until") and c.refs(quote):
            begin, end = parse_time(quote["valid_from"]), parse_time(quote["valid_until"])
            require(begin < end, "invalid_quote_interval")
            state = "expired" if c.now >= end else ("future" if c.now < begin else "current")
        if state == "expired":
            expired.append(quote["id"])
        if state != "current":
            issues.append("quote_requires_update_or_confirmation")
        else:
            currency = quote["currency"]
            totals[currency] = totals.get(currency, Decimal(0)) + amount
        rows.append({**quote, "quote_state": state, "decision_execution": "not_performed"})
    return c.finish({"quotes": rows, "expired_quote_ids": expired,
                     "current_totals": {key: format(value, "f")
                                        for key, value in sorted(totals.items())},
                     "currency_conversion": "not_performed", "payment_authorized": False,
                     "abandonment_authorized": False}, issues)


_HANDLERS = {
    "PROC-01": _timeline, "PROC-02": _support, "PROC-03": _entry,
    "PROC-04": _filing, "PROC-05": _office_action, "PROC-06": _correction,
    "PROC-07": _support, "PROC-08": _remedies, "PROC-09": _grant,
    "RIGHTS-01": _rights_matrix, "RIGHTS-02": _rights_matrix,
    "RIGHTS-03": _rights_matrix, "RIGHTS-04": _purpose_search,
    "RIGHTS-05": _rights_matrix, "RIGHTS-06": _license, "RIGHTS-07": _sep,
    "SEARCH-07": _purpose_search, "SEARCH-08": _landscape, "LIFE-02": _budget,
}


def run(capability: str, payload: dict) -> dict:
    """返回共享信封；结构错误抛 ContractError，事实未知保留在结果中。

    不验证证据真实性、不认证调用者身份；敏感资料进入本函数前由共享
    预检确认宿主数据路径与权限。previous_input_digest变化使旧审核失效，
    同时保留本次重算产物和其原始状态。函数不读写文件或执行外部动作。
    """
    require(isinstance(capability, str) and capability in _HANDLERS,
            "unsupported_procedure_capability")
    require(isinstance(payload, dict), "object_required")
    p = copy.deepcopy(payload)
    c = _Context(capability, p)
    applicability = p.get("applicability")
    if applicability is not None:
        require_fields(applicability, ("state", "reason"))
        require(applicability["state"] == "not_applicable", "applicability_state_unknown")
        require(c.refs(applicability), "applicability_evidence_required")
        return c.finish({"applicability": applicability}, status="not_applicable")
    return _HANDLERS[capability](c)
