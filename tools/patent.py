"""专利核心的本地证据整理、候选稿和确定性检查（WP-05/10）。

只处理调用者显式传入的JSON，不读取文件、不执行材料内指令、不联网。
引用匹配及结构比较不是法律支持、新颖性、创造性或制图合格结论。
"""
from __future__ import annotations

import copy
import difflib
import json
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date
from html import escape

from tools.core import ContractError, digest, preflight, require, require_fields, result

CAPABILITIES = tuple(
    f"{group}-{number:02d}"
    for group, count in (("SEARCH", 6), ("ANALYSIS", 8), ("DRAFT", 8),
                         ("FIG", 5), ("REVIEW", 6))
    for number in range(1, count + 1)
)
TOOL_VERSION = "1.2"


def _records(payload: dict, key: str, *, required: bool = False) -> list[dict]:
    values = payload.get(key, [])
    require(isinstance(values, list), f"list_required:{key}")
    require(all(isinstance(x, dict) for x in values), f"objects_required:{key}")
    require(not required or bool(values), f"records_required:{key}")
    return values


def _strings(value, key: str) -> list[str]:
    require(isinstance(value, list) and all(isinstance(x, str) and x.strip()
                                          for x in value), f"strings_required:{key}")
    return value


def _index(values: list[dict], key: str = "id") -> dict:
    for value in values:
        require_fields(value, (key,))
        require(isinstance(value[key], (str, int)) and not isinstance(value[key], bool),
                f"identifier_required:{key}")
    mapped = {x[key]: x for x in values}
    require(len(mapped) == len(values), f"duplicate_identifier:{key}")
    return mapped


def _issue(issues: list, code: str, **details) -> None:
    issues.append({"code": code, **details})


def _day(value):
    if value is None:
        return None
    require(isinstance(value, str), "date_string_required")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError("invalid_date") from exc


def _number(value) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), "finite_number_required")
    return value


def _documents(payload: dict) -> list[dict]:
    docs = _records(payload, "documents")
    _index(docs)
    for doc in docs:
        require_fields(doc, ("version", "title", "kind"))
        require(isinstance(doc["kind"], str) and doc["kind"] in {"patent", "npl"},
                "document_kind_unknown")
        require(isinstance(doc["title"], str) and isinstance(doc.get("abstract", ""), str),
                "document_text_required")
        for field in ("classes", "applicant_ids", "citations", "claims"):
            _strings(doc.get(field, []), field)
        sections = _records(doc, "sections")
        _index(sections, "locator")
        for section in sections:
            require_fields(section, ("text",))
            require(isinstance(section["text"], str), "section_text_required")
    return docs


def _dates(docs: list[dict], critical, issues: list) -> list[dict]:
    key_day = _day(critical)
    rows = []
    for doc in docs:
        published = _day(doc.get("public_at"))
        filed = _day(doc.get("filed_at"))
        _day(doc.get("acquired_at"))
        _day(doc.get("archived_at"))
        known = published is not None and bool(doc.get("publication_evidence"))
        chronology = "unknown"
        if known and key_day:
            if published < key_day:
                chronology = "published_before"
            elif filed and filed < key_day and published > key_day:
                chronology = "earlier_filed_later_published"
            elif published == key_day:
                chronology = "same_day_requires_review"
            else:
                chronology = "published_after"
        if chronology == "unknown":
            _issue(issues, "date_evidence_missing", document_id=doc["id"],
                   source_id=doc.get("collection_source"), version=doc["version"])
        rows.append({"document_id": doc["id"], "version": doc["version"],
                     "collection_source": doc.get("collection_source"), "public_at": doc.get("public_at"),
                     "filed_at": doc.get("filed_at"), "critical_date": critical,
                     "publication_evidence": doc.get("publication_evidence"),
                     "acquired_at": doc.get("acquired_at"),
                     "archived_at": doc.get("archived_at"), "chronology": chronology,
                     "legal_eligibility": "undetermined"})
    return rows


def _search_report(payload: dict, artifacts: dict, issues: list) -> str:
    """工作稿仅呈现输入证据与本地覆盖，不把调用者记录升级为专业结论。"""
    def text(value):
        if value is None:
            return "unknown"
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        # 来源字段不得插入HTML、链接或新的Markdown段落，原值仍保留在JSON中。
        value = escape(" ⏎ ".join(str(value).splitlines()), quote=False)
        return re.sub(r"([\\`*\[\]|])", r"\\\1", value)

    lines = ["# 本地现有技术检索工作稿", "",
             "范围：仅调用者提供的本地集合；网络请求0次，未查询官方数据库。",
             "本稿不是有资质查新机构报告，不构成新颖性、创造性或法律可用性结论。",
             "来源状态和不适用依据为调用者记录；未检索、失败或零命中均不证明不存在现有技术。",
             "", "## 查询与预算", "",
             "查询组（组间AND、组内OR，字面匹配）：" + text(artifacts["query"].get("groups", [])),
             "分类过滤：" + text(artifacts["query"].get("classes", [])),
             "主体ID过滤：" + text(artifacts["query"].get("applicant_ids", [])),
             f"本地分页预算：每页{payload.get('page_size', 50)}条，最多{payload.get('max_pages', 100)}页。",
             "关键日：" + text(payload.get("critical_date")), "", "## 来源覆盖与分页", "",
             "matched/returned/omitted_matches仅计给定本地集合，不表示远端库总量；collection_complete仅表示本地集合已遍历且来源未声明partial。"]
    for row in artifacts["coverage"]:
        lines += ["", "### 来源 " + text(row["source_id"]),
                  "- 声明状态：" + text(row["source_status"]),
                  "- 范围：" + text(row["scope"]),
                  "- 停止原因：" + text(row["stop_reasons"]),
                  f"- 本地命中/返回/预算未返回：{text(row['matched'])} / {row['returned']} / {text(row['omitted_matches'])}",
                  "- collection_complete：" + str(row["collection_complete"]).lower()]
        if row["stop_reason"] == "not_applicable":
            lines.append("- 不适用陈述与依据：" + text(row["reason"]) + " / " + text(row["evidence_id"]))
        for page in row["pages"]:
            lines.append(f"- 第{page['page']}页：" + text(page["document_ids"]))
        if not row["pages"]:
            lines.append("- 无返回页；原因以上述停止状态为准。")
    lines += ["", "## 返回文献与日期证据", ""]
    for doc, dates in zip(artifacts["documents"], artifacts["date_matrix"]):
        lines += ["### " + text(doc["collection_source"]) + " / " + text(doc["id"]) + " / " + text(doc["version"]),
                  "- 标题：" + text(doc["title"]),
                  "- 类型/法域：" + text(doc["kind"]) + " / " + text(doc.get("jurisdiction")),
                  "- 公开/申请/取得/归档日：" + " / ".join(text(dates[k]) for k in
                      ("public_at", "filed_at", "acquired_at", "archived_at")),
                  "- 公开日期依据：" + text(dates["publication_evidence"]),
                  "- 日期关系/法律可用性：" + text(dates["chronology"]) + " / " + text(dates["legal_eligibility"]),
                  "- 给定正文定位（不代表全文已完整核验）：" + text([s["locator"] for s in doc.get("sections", [])]),
                  "- 抽取状态：" + text(doc.get("extraction_status", "not_checked")), ""]
    if not artifacts["documents"]:
        lines.append("没有返回文献；不推导新颖性或无在先技术结论。")
    lines += ["", "## 覆盖与证据缺口", ""]
    lines.extend("- " + text(issue) for issue in issues)
    if not issues:
        lines.append("本次确定性检查未记录缺口；不代表完成全球检索或专业审阅。")
    lines += ["", "## 交接", "",
              "核实缺口、公开日期与来源后交ANALYSIS-02进行逐特征及组合评价；日期与程序问题交PROC。",
              "专业审阅未执行；正文及问题清单均不得绕过CORE披露审批直接外发。"]
    return "\n".join(lines)


def _search(payload: dict, cap: str):
    issues, docs, coverage = [], [], []
    query = payload.get("query", {})
    require(isinstance(query, dict), "query_object_required")
    groups = query.get("groups", [])
    require(isinstance(groups, list), "query_groups_required")
    for group in groups:
        require(bool(_strings(group, "query_group")), "empty_query_group")
    classes = _strings(query.get("classes", []), "classes")
    applicants = _strings(query.get("applicant_ids", []), "applicant_ids")
    page_size, max_pages = payload.get("page_size", 50), payload.get("max_pages", 100)
    require(type(page_size) is int and page_size > 0 and type(max_pages) is int
            and max_pages > 0, "positive_pagination_required")
    sources = _records(payload, "sources", required=True)
    _index(sources)
    for source in sources:
        require_fields(source, ("status",))
        require(isinstance(source["status"], str) and source["status"] in {
            "ok", "unavailable", "permission_denied", "rate_limited", "partial",
            "network_error", "login_failed", "unknown", "not_checked", "not_applicable",
            "not_configured", "timeout", "budget_exhausted"},
            "source_status_unknown")
        source_info = {"source_id": source["id"], "source_status": source["status"],
                       "scope": source.get("scope", "caller_supplied_local_collection")}
        if source["status"] not in {"ok", "partial"} or source.get("local_use") is not True:
            reason = source["status"] if source["status"] not in {"ok", "partial"} else "permission_denied"
            row = {**source_info, "stop_reason": reason, "stop_reasons": [reason],
                   "pages": [], "matched": None, "returned": 0, "omitted_matches": None,
                   "collection_complete": False}
            if reason == "not_applicable":
                for key in ("reason", "evidence_id"):
                    require(isinstance(source.get(key), str) and bool(source[key].strip()),
                            f"source_not_applicable_basis_required:{key}")
                    row[key] = source[key]
            else:
                _issue(issues, "source_unavailable", source_id=source["id"], reason=reason)
            coverage.append(row)
            continue
        candidates = _documents(source)
        matches = []
        for doc in candidates:
            if cap == "SEARCH-03" and doc["kind"] != "npl":
                continue
            text = "\n".join([doc["title"], doc.get("abstract", "")] +
                             [x["text"] for x in doc.get("sections", [])]).casefold()
            if (all(any(term.casefold() in text for term in group) for group in groups)
                    and (not classes or set(classes).intersection(doc.get("classes", [])))
                    and (not applicants or set(applicants).intersection(doc.get("applicant_ids", [])))):
                matches.append(doc)
        matches.sort(key=lambda doc: (str(doc["id"]), str(doc["version"])))
        selected = matches[:page_size * max_pages]
        pages = [{"page": i // page_size + 1,
                  "document_ids": [x["id"] for x in selected[i:i + page_size]]}
                 for i in range(0, len(selected), page_size)]
        reasons = []
        if source["status"] == "partial":
            reasons.append("source_partial")
        if len(selected) < len(matches):
            reasons.append("page_budget")
        incomplete = bool(reasons)
        if not reasons:
            reasons.append("exhausted_local_collection" if matches else "zero_hits")
        coverage.append({**source_info, "stop_reason": reasons[0], "stop_reasons": reasons,
                         "pages": pages, "matched": len(matches), "returned": len(selected),
                         "omitted_matches": len(matches) - len(selected),
                         "collection_complete": not incomplete})
        if incomplete:
            _issue(issues, "coverage_incomplete", source_id=source["id"], reasons=reasons)
        docs.extend({**doc, "collection_source": source["id"]} for doc in selected)
    artifacts = {"query": query, "documents": docs, "coverage": coverage,
                 "network_requests": 0, "scope": "local_supplied_collections_only"}
    if cap in {"SEARCH-03", "SEARCH-06"}:
        if payload.get("critical_date") is None:
            _issue(issues, "critical_date_missing")
        artifacts["date_matrix"] = _dates(docs, payload.get("critical_date"), issues)
    if cap == "SEARCH-06":
        for doc in docs:
            if not doc.get("sections"):
                _issue(issues, "fulltext_missing", source_id=doc["collection_source"],
                       document_id=doc["id"], version=doc["version"])
            if doc.get("extraction_status") in {"ocr_uncertain", "missing_pages", "partial"}:
                _issue(issues, "extraction_uncertain", source_id=doc["collection_source"],
                       document_id=doc["id"], version=doc["version"])
        artifacts["qualified_search_report"] = False
        artifacts["report"] = _search_report(payload, artifacts, issues)
    status = "partial" if issues else "needs_review"
    if all(x["stop_reason"] == "not_applicable" for x in coverage):
        status = "not_applicable"
    elif all(x["matched"] is None for x in coverage):
        status = "blocked"
    return artifacts, issues, status


def _strategy(payload: dict):
    issues, groups = [], []
    concepts = _records(payload, "concepts", required=True)
    _index(concepts)
    for concept in concepts:
        terms = concept.get("terms")
        require(isinstance(terms, dict) and bool(terms), "language_terms_required")
        merged = []
        for words in terms.values():
            merged.extend(_strings(words, "terms"))
        require(bool(merged), "concept_terms_required")
        groups.append(list(dict.fromkeys(merged)))
    for operator in _strings(payload.get("operators", []), "operators"):
        if operator not in {"AND", "OR"}:
            _issue(issues, "unsupported_operator", operator=operator)
    applicants = _records(payload, "applicants")
    for applicant in applicants:
        require_fields(applicant, ("name",))
        if not applicant.get("entity_id"):
            _issue(issues, "applicant_identity_unresolved", name=applicant["name"])
    query = {"groups": groups, "classes": _strings(payload.get("classes", []), "classes"),
             "applicant_ids": [a["entity_id"] for a in applicants if a.get("entity_id")]}
    return {"query": query, "concepts": concepts, "applicants": applicants,
            "syntax": "local_literal_OR_within_AND_between_groups",
            "external_database_syntax": "not_adapted"}, issues, "needs_review"


def _relations(payload: dict, cap: str):
    docs, issues = _documents(payload), []
    if cap == "SEARCH-05":
        snapshots = []
        for doc in docs:
            known = bool(doc.get("status_source") and doc.get("status_as_of"))
            _day(doc.get("status_as_of"))
            state = doc.get("legal_status", "unknown") if known else "unknown"
            if state == "unknown":
                _issue(issues, "legal_status_unknown", document_id=doc["id"])
            snapshots.append({"document_id": doc["id"], "jurisdiction": doc.get("jurisdiction"),
                              "version": doc["version"], "status": state,
                              "asserted_status": doc.get("legal_status"),
                              "source": doc.get("status_source"), "as_of": doc.get("status_as_of"),
                              "history": doc.get("status_history", [])})
        return {"snapshots": snapshots}, issues, "needs_review"
    families = {}
    edges = []
    for doc in docs:
        if doc.get("family"):
            families.setdefault(doc["family"], []).append(doc["id"])
        if not doc.get("sections"):
            _issue(issues, "fulltext_missing", document_id=doc["id"])
        if doc.get("extraction_status") in {"ocr_uncertain", "missing_pages", "partial"}:
            _issue(issues, "extraction_uncertain", document_id=doc["id"])
        for cited in _strings(doc.get("citations", []), "citations"):
            edges.append({"from": doc["id"], "to": cited, "kind": "citation",
                          "target_available": any(d["id"] == cited for d in docs)})
    return {"documents": docs, "families": families, "edges": edges,
            "family_claims_merged": False}, issues, "needs_review"


def _facts(payload: dict):
    facts = _records(payload, "facts", required=True)
    _index(facts)
    issues, subjects = [], {}
    labels = {"implemented": "已实现（调用者陈述）", "design": "可实施设计（待确认）",
              "hypothesis": "待验证假设", "unknown": "状态未知"}
    lines = [f"# {payload.get('title', '技术交底工作稿')}"]
    for fact in facts:
        require_fields(fact, ("subject", "kind", "text", "evidence_id", "state"))
        require(fact["state"] in labels, "fact_state_unknown")
        subjects.setdefault(fact["subject"], []).append(fact)
        lines.append(f"- [{fact['id']}] {fact['kind']} / {labels[fact['state']]}：{fact['text']}（依据：{fact['evidence_id']}）")
        if fact["state"] in {"hypothesis", "unknown"}:
            _issue(issues, "fact_needs_validation", fact_id=fact["id"])
    for subject, entries in subjects.items():
        if len({e["text"] for e in entries}) > 1:
            _issue(issues, "fact_conflict", subject=subject, fact_ids=[e["id"] for e in entries])
            lines.append(f"\n待确认：{subject} 存在不同陈述，未选择其中一方。")
    return {"facts": facts, "problem_means_effect": {
        kind: [f["id"] for f in facts if f["kind"] == kind]
        for kind in ("problem", "means", "effect", "alternative")},
        "markdown": "\n".join(lines)}, issues, "needs_evidence" if issues else "draft"


def _matrix(payload: dict):
    fs = _records(payload, "features", required=True)
    f_index, docs = _index(fs), _documents(payload)
    d_index, issues = _index(docs), []
    mappings = _records(payload, "mappings")
    pairs = {}
    for mapping in mappings:
        require_fields(mapping, ("feature_id", "document_id", "state"))
        require(isinstance(mapping["feature_id"], (str, int))
                and isinstance(mapping["document_id"], (str, int)), "mapping_identifier_required")
        require(isinstance(mapping["state"], str), "mapping_state_required")
        require(isinstance(mapping.get("locator", ""), str), "mapping_locator_required")
        require(mapping["feature_id"] in f_index and mapping["document_id"] in d_index,
                "mapping_reference_unknown")
        require(mapping["state"] in {"present", "unobserved", "absent", "unknown"},
                "mapping_state_unknown")
        key = (mapping["feature_id"], mapping["document_id"])
        require(key not in pairs, "duplicate_mapping")
        pairs[key] = mapping
    matrix, per_document = [], []
    for doc in docs:
        present = []
        sections = {s["locator"]: s["text"] for s in doc.get("sections", [])}
        for feature in fs:
            require_fields(feature, ("text",))
            mapping = pairs.get((feature["id"], doc["id"]), {})
            state = mapping.get("state", "unknown")
            quote, locator = mapping.get("quote"), mapping.get("locator")
            located = isinstance(quote, str) and bool(quote) and quote in sections.get(locator, "")
            if state in {"present", "absent"} and not located:
                _issue(issues, "quote_not_found", feature_id=feature["id"], document_id=doc["id"])
                state = "unknown"
            if state == "present":
                present.append(feature["id"])
            matrix.append({"feature_id": feature["id"], "document_id": doc["id"],
                           "document_version": doc["version"], "state": state,
                           "locator": locator, "quote": quote, "quote_located": located,
                           "assessment": "caller_assertion_not_professionally_verified"})
        per_document.append({"document_id": doc["id"], "present_features": present,
                             "unresolved_features": [f["id"] for f in fs if f["id"] not in present],
                             "combination": "not_established", "novelty": "undetermined"})
    dates = _dates(docs, payload.get("critical_date"), issues)
    return {"matrix": matrix, "per_document": per_document, "date_matrix": dates}, issues, "needs_review"


def _support(payload: dict):
    proposed = _records(payload, "features", required=True)
    _index(proposed)
    original = payload.get("original")
    require_fields(original, ("id", "version", "features"))
    baseline = _index(_records(original, "features"))
    issues, rows = [], []
    for feature in proposed:
        require_fields(feature, ("text",))
        old = baseline.get(feature["id"])
        changes = []
        if old is None:
            changes.append("new_feature")
        else:
            for field, code in (("text", "feature_text_changed"), ("range", "range_changed"),
                                ("conditions", "conditions_changed")):
                if feature.get(field) != old.get(field):
                    changes.append(code)
        for code in changes:
            _issue(issues, code, feature_id=feature["id"])
        rows.append({"feature_id": feature["id"], "original": old, "proposed": feature,
                     "changes": changes, "support": "requires_professional_assessment"})
    original_combinations = original.get("combinations", [])
    combinations = payload.get("combinations", [])
    require(isinstance(combinations, list) and isinstance(original_combinations, list),
            "combinations_list_required")
    for combination in original_combinations + combinations:
        require(bool(_strings(combination, "combination")), "empty_combination")
    for combo in combinations:
        require(set(combo).issubset({f["id"] for f in proposed}), "combination_feature_unknown")
        if not any(set(combo) == set(old) for old in original_combinations):
            _issue(issues, "combination_not_in_original", feature_ids=combo)
    return {"support_matrix": rows, "original_id": original["id"],
            "original_version": original["version"], "original_hash": digest(original),
            "combinations": combinations, "original_combinations": original_combinations,
            "disclosure_permission": "not_granted"}, issues, "needs_evidence" if issues else "needs_review"


def _claim_check(payload: dict):
    cs = _records(payload, "claims", required=True)
    index, issues = _index(cs), []
    for claim in cs:
        require(type(claim["id"]) is int and claim["id"] > 0, "positive_claim_id_required")
        require_fields(claim, ("category", "depends_on"))
        parents = claim["depends_on"]
        require(isinstance(parents, list) and all(type(x) is int for x in parents),
                "claim_dependencies_required")
        require(len(parents) == len(set(parents)), "duplicate_claim_dependency")
        _strings(claim.get("introduces", []), "introduces")
        _strings(claim.get("uses", []), "uses")
        for parent in parents:
            if parent not in index:
                _issue(issues, "claim_reference_missing", claim_id=claim["id"], parent_id=parent)
            if parent >= claim["id"]:
                _issue(issues, "forward_reference", claim_id=claim["id"], parent_id=parent)
    if sorted(index) != list(range(1, len(cs) + 1)):
        _issue(issues, "claim_numbering_gap")
    # 固定点求每条替代依赖路径均有的术语；兄弟权项不得贡献前置基础。
    terms = {key: set(c.get("introduces", [])) for key, c in index.items()}
    for _ in range(len(cs)):
        updated = {}
        for key, claim in index.items():
            parents = claim["depends_on"]
            inherited = set.intersection(*(terms.get(x, set()) for x in parents)) if parents else set()
            updated[key] = set(claim.get("introduces", [])) | inherited
        if terms == updated:
            break
        terms = updated
    rows = []
    for claim in cs:
        start, seen, stack = claim["id"], set(), list(claim["depends_on"])
        cycle = False
        while stack:
            current = stack.pop()
            if current == start:
                cycle = True
                break
            if current in seen or current not in index:
                continue
            seen.add(current)
            stack.extend(index[current]["depends_on"])
        if cycle:
            _issue(issues, "dependency_cycle", claim_id=start)
        parents = claim["depends_on"]
        inherited = set.intersection(*(terms.get(x, set()) for x in parents)) if parents else set()
        available = inherited | set(claim.get("introduces", []))
        missing = sorted(set(claim.get("uses", [])) - available)
        if missing:
            _issue(issues, "antecedent_missing", claim_id=start, terms=missing)
        for parent in parents:
            if parent in index and index[parent]["category"] != claim["category"]:
                _issue(issues, "claim_category_changed", claim_id=start, parent_id=parent)
        rows.append({"claim_id": start, "ancestors": sorted(seen),
                     "missing_terms": missing, "cycle": cycle})
    return {"claims": cs, "claim_checks": rows}, issues, "needs_review"


def _draft_claims(payload: dict):
    artifacts, issues, _ = _claim_check(payload)
    fs = _index(_records(payload, "features", required=True))
    lines = []
    for claim in artifacts["claims"]:
        phrases = []
        for key in _strings(claim.get("feature_ids", []), "feature_ids"):
            if key not in fs or not fs[key].get("evidence_id"):
                _issue(issues, "claim_feature_support_missing", claim_id=claim["id"], feature_id=key)
            if key in fs:
                require_fields(fs[key], ("text",))
                phrases.append(fs[key]["text"])
        if not phrases:
            _issue(issues, "claim_features_missing", claim_id=claim["id"])
        parents = claim["depends_on"]
        prefix = (f"根据权利要求{'、'.join(map(str, parents))}所述的方案，" if parents else
                  f"一种{claim['category']}方案，")
        lines.append(f"{claim['id']}. {prefix}{'；'.join(phrases)}。")
    artifacts["markdown"] = "\n\n".join(lines)
    artifacts["category_rules"] = "not_verified"
    return artifacts, issues, "draft" if not issues else "needs_evidence"


def _analysis(payload: dict, cap: str):
    issues = []
    if cap == "ANALYSIS-03":
        matrix, issues, _ = _matrix(payload)
        framework = payload.get("framework", {})
        require(isinstance(framework, dict), "framework_object_required")
        steps = _strings(framework.get("steps", []), "framework_steps")
        arguments = _records(payload, "arguments")
        reasoning = []
        if not steps or not framework.get("rule_evidence"):
            _issue(issues, "framework_unverified")
        for step in steps:
            entries = [a for a in arguments if a.get("step") == step]
            if not entries or any(not a.get("evidence_id") for a in entries):
                _issue(issues, "argument_missing", step=step)
            reasoning.append({"step": step, "arguments": entries})
        return {**matrix, "framework": framework, "reasoning": reasoning,
                "counterevidence": payload.get("counterevidence", []),
                "inventive_step": "undetermined"}, issues, "needs_review"
    if cap == "ANALYSIS-04":
        require_fields(payload, ("subject", "purpose"))
        facts = _records(payload, "technical_facts")
        _issue(issues, "jurisdiction_rules_unverified")
        return {"subject": payload["subject"], "purpose": payload["purpose"],
                "technical_facts": facts, "eligibility": "undetermined",
                "questions": [{"fact_id": f.get("id"), "question": "该事实的实现条件、可实施用途和依据是什么？"}
                              for f in facts]}, issues, "needs_review"
    if cap == "ANALYSIS-06":
        matrix, issues, _ = _matrix(payload)
        candidates = []
        for feature in _records(payload, "features", required=True):
            hits = [r["document_id"] for r in matrix["matrix"] if r["feature_id"] == feature["id"]
                    and r["state"] == "present"]
            candidates.append({"feature_id": feature["id"], "text": feature["text"],
                               "mapped_documents": hits,
                               "status": "needs_search" if not payload.get("coverage_complete") else "needs_analysis",
                               "next_checks": ["ANALYSIS-02", "ANALYSIS-03"],
                               "research_task": "核实区别及效果，补充反证与可实施条件"})
        return {**matrix, "candidates": candidates,
                "constraints": payload.get("constraints", [])}, issues, "needs_review"
    if cap == "ANALYSIS-07":
        artifacts, issues, _ = _draft_claims(payload)
        alternatives = _records(payload, "alternatives")
        for alternative in alternatives:
            if not alternative.get("evidence_id"):
                _issue(issues, "alternative_support_missing", feature_id=alternative.get("feature_id"))
        artifacts.update({"layers": [{"claim_id": c["id"], "parent_ids": c["depends_on"],
                                      "feature_ids": c.get("feature_ids", [])}
                                     for c in artifacts["claims"]],
                          "alternatives": alternatives, "markets": payload.get("markets", []),
                          "budget": payload.get("budget"), "unity": "undetermined"})
        return artifacts, issues, "needs_review"
    options = _records(payload, "options", required=True)
    _index(options)
    rows = []
    for option in options:
        considerations = []
        if option.get("detectable") is False:
            considerations.append("侵权取证可行性不足，需验证可观察证据")
        elif option.get("detectable") is True:
            considerations.append("已有可检测性陈述，需确认取证权限与证据")
        else:
            considerations.append("可检测性未知")
        if option.get("secrecy_feasible") is True:
            considerations.append("可评估商业秘密路线及保密控制成本")
        else:
            considerations.append("保密可行性不足或未知，需评估专利路线与公开后果")
        rows.append({**option, "considerations": considerations,
                     "decision": "requires_owner_and_professional_review"})
    return {"options": rows, "disclosure_authorized": False}, issues, "needs_review"


def _examples(payload: dict):
    examples = _records(payload, "examples", required=True)
    _index(examples)
    issues, lines = [], ["# 实施例候选稿"]
    labels = {"implemented": "已实现（待核验）", "design": "可实施设计",
              "hypothesis": "待验证假设"}
    for example in examples:
        require_fields(example, ("state", "evidence_id", "steps"))
        require(example["state"] in labels, "example_state_unknown")
        steps = _strings(example["steps"], "example_steps")
        lines.extend([f"## {example['id']} · {labels[example['state']]}"] +
                     [f"{i}. {step}" for i, step in enumerate(steps, 1)])
        require(isinstance(example.get("parameters", {}), dict), "parameters_object_required")
        for key, value in example.get("parameters", {}).items():
            lines.append(f"- 参数 {key}：{value}（依据：{example['evidence_id']}）")
        if example.get("results"):
            if example["state"] != "implemented" or not example.get("measurement_evidence"):
                _issue(issues, "experimental_results_unverified", example_id=example["id"])
            else:
                lines.append(f"测量记录陈述：{example['results']}（依据：{example['measurement_evidence']}）")
        if example["state"] == "hypothesis":
            _issue(issues, "example_hypothesis", example_id=example["id"])
    return {"examples": examples, "markdown": "\n".join(lines)}, issues, "draft"


def _draft_text(payload: dict, cap: str):
    fs = _records(payload, "features")
    _index(fs)
    issues, lines = [], [f"# {payload.get('title', '专利工作稿')}"]
    for feature in fs:
        require_fields(feature, ("text",))
        if not feature.get("evidence_id"):
            _issue(issues, "feature_evidence_missing", feature_id=feature["id"])
    if cap == "DRAFT-03":
        lines.append("## 技术方案")
        lines.extend(f"- {f['text']}（{f.get('evidence_id', '依据待补')}）" for f in fs)
        lines.append("## 背景材料摘述（不作现有技术承认）")
        background = _records(payload, "background")
        for item in background:
            require_fields(item, ("text",))
            if item.get("state") == "confirmed" and item.get("evidence_id"):
                lines.append(f"- {item['text']}（来源：{item['evidence_id']}）")
            else:
                _issue(issues, "background_unconfirmed")
        return {"markdown": "\n".join(lines), "features": fs,
                "background_review": background}, issues, "draft"
    if cap == "DRAFT-06":
        components = _records(payload, "components")
        if not components:
            _issue(issues, "structure_facts_missing")
        for component in components:
            require_fields(component, ("id", "structure", "evidence_id"))
            lines.append(f"- {component['id']}：{component['structure']}（依据：{component['evidence_id']}）")
        return {"markdown": "\n".join(lines), "components": components,
                "category_eligibility": "undetermined"}, issues, "draft" if components else "needs_evidence"
    figures = _records(payload, "figures")
    figure_ids = _index(figures)
    for ref in _strings(payload.get("figure_refs", []), "figure_refs"):
        if ref not in figure_ids:
            _issue(issues, "figure_reference_missing", figure_id=ref)
    abstract = "；".join(f["text"] for f in fs)
    lines.extend(["## 摘要候选", abstract, "## 附图说明"])
    for fig in figures:
        require_fields(fig, ("caption",))
        lines.append(f"{fig['id']}：{fig['caption']}")
    return {"markdown": "\n".join(lines), "abstract": abstract,
            "character_count": len(abstract), "figures": figures,
            "glossary": payload.get("glossary", {}), "format_rules": "not_verified"}, issues, "draft"


SEMANTIC_PATTERNS = {
    "numbers": r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?",
    "units": r"\b(?:ms|s|mm|cm|kg|mV|V|Hz|MHz|Pa|MPa)\b|毫秒|秒|毫米|厘米|千克|摄氏度|%|℃",
    "conditions": r"若|如果|当|仅当|除非|除了|在.{0,20}条件下|\b(?:if|when|unless|except|only)\b",
    "negation": r"不得|不含|不|无|未|否|排除|\b(?:not|never|without|exclude)\b",
    "modality": r"可能|必然|必须|应当|应|宜|可以|可|至少|至多|大于|小于|未知|\b(?:shall|should|may|must|might|can|unknown)\b",
}
SAFE_REMOVALS = {"REVIEW-05": ("值得一提的是，", "综上所述，"),
                 "REVIEW-06": ("以下为起草说明。",)}


def _edit_diff(original: str, proposed: str) -> dict:
    require(isinstance(original, str) and isinstance(proposed, str), "edit_text_required")
    changed = [kind for kind, pattern in SEMANTIC_PATTERNS.items()
               if re.findall(pattern, original, re.I) != re.findall(pattern, proposed, re.I)]
    return {"original": original, "proposed": proposed, "semantic_changes": changed,
            "diff": list(difflib.unified_diff(original.splitlines(), proposed.splitlines(),
                                              fromfile="original", tofile="proposed", lineterm=""))}


def _edit(payload: dict, cap: str):
    require_fields(payload, ("original",))
    original = payload["original"]
    require(isinstance(original, str), "edit_text_required")
    clean = original
    for phrase in SAFE_REMOVALS[cap]:
        clean = clean.replace(phrase, "")
    proposed = payload.get("proposed", clean)
    artifacts = _edit_diff(original, proposed)
    auto = proposed == clean and not artifacts["semantic_changes"]
    issues = []
    if not auto:
        _issue(issues, "edit_requires_professional_review", changed=artifacts["semantic_changes"])
    artifacts.update({"auto_applied": auto, "accepted_text": proposed if auto else original,
                      "semantic_check_scope": "listed_tokens_and_exact_filler_deletions_only"})
    return artifacts, issues, "draft" if auto else "needs_review"


def _translation(payload: dict):
    segments = _records(payload, "segments", required=True)
    _index(segments)
    issues, rows = [], []
    for segment in segments:
        require_fields(segment, ("original", "proposed"))
        compared = _edit_diff(segment["original"], segment["proposed"])
        if compared["semantic_changes"]:
            _issue(issues, "translation_semantic_change", segment_id=segment["id"],
                   changed=compared["semantic_changes"])
        if not segment.get("support"):
            _issue(issues, "translation_support_missing", segment_id=segment["id"])
        rows.append({"id": segment["id"], **compared,
                     "support": segment.get("support"), "accepted_text": segment["original"],
                     "strategy": segment.get("strategy"), "approval": "not_inherited"})
    return {"segments": rows, "glossary": payload.get("glossary", {}),
            "translation_generation": "caller_supplied_proposal_only"}, issues, "needs_review"


def _svg_header(width, height) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
            '<path d="M0,0 L8,4 L0,8 Z" fill="black"/></marker></defs>')


def _flow(payload: dict):
    nodes = _records(payload, "nodes", required=True)
    index, edges, issues = _index(nodes), _records(payload, "edges"), []
    for node in nodes:
        require_fields(node, ("label", "kind"))
        require(isinstance(node["label"], str), "node_label_required")
        require(node["kind"] in {"start", "action", "decision", "end"}, "node_kind_unknown")
    adjacency = {key: [] for key in index}
    for edge in edges:
        require_fields(edge, ("from", "to", "label"))
        require(isinstance(edge["from"], (str, int)) and isinstance(edge["to"], (str, int)),
                "edge_identifier_required")
        require(edge["from"] in index and edge["to"] in index, "edge_node_unknown")
        adjacency[edge["from"]].append(edge["to"])
    starts = [n["id"] for n in nodes if n["kind"] == "start"]
    ends = {n["id"] for n in nodes if n["kind"] == "end"}
    if len(starts) != 1:
        _issue(issues, "one_start_required")
    def reachable(start):
        seen, stack = set(), [start]
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(adjacency[current])
        return seen
    reached = set().union(*(reachable(x) for x in starts)) if starts else set()
    for node in nodes:
        key = node["id"]
        if key not in reached:
            _issue(issues, "flow_unreachable", node_id=key)
        if not reachable(key).intersection(ends):
            _issue(issues, "flow_no_terminal_path", node_id=key)
        if node["kind"] == "end" and adjacency[key]:
            _issue(issues, "terminal_has_outgoing_edge", node_id=key)
        if node["kind"] == "decision":
            outcomes = {e.get("outcome") for e in edges if e["from"] == key}
            if "failure" not in outcomes:
                _issue(issues, "failure_exit_missing", node_id=key)
            if "success" not in outcomes:
                _issue(issues, "success_exit_missing", node_id=key)
    # 14px等宽字体每半角约0.6em；28列给270px节点两侧留出15px。
    # 宽/全角及宽度不定字符占两列；不裁字、不丢空格，实际字体边界仍须浏览器复验。
    widths = []
    for node in nodes:
        lines, columns = [""], 0
        for char in node["label"]:
            units = (0 if unicodedata.combining(char) else
                     2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1)
            if columns + units > 28:
                lines.append("")
                columns = 0
            lines[-1] += char
            columns += units
        widths.append(lines)
    heights = [max(60, len(lines) * 20 + 20) for lines in widths]
    positions, y = {}, 30
    for node, height in zip(nodes, heights):
        positions[node["id"]] = (y, height)
        y += height + 55
    width = 420 + 28 * len(edges)
    parts = [_svg_header(width, y)]
    for i, edge in enumerate(edges):
        sy, sh = positions[edge["from"]]
        ty, th = positions[edge["to"]]
        lane = 340 + i * 28
        parts.append(f'<path d="M300,{sy + sh / 2} H{lane} V{ty + th / 2} H300" fill="none" stroke="black" marker-end="url(#arrow)"/>')
        parts.append(f'<text x="{lane + 3}" y="{sy + sh / 2 - 5}" font-size="12">{escape(str(edge["label"]))}</text>')
    for node, lines in zip(nodes, widths):
        top, height = positions[node["id"]]
        parts.append(f'<rect x="30" y="{top}" width="270" height="{height}" fill="white" stroke="black"/>')
        for i, line in enumerate(lines):
            parts.append(f'<text x="45" y="{top + 25 + i * 20}" font-family="monospace" font-size="14">{escape(line)}</text>')
    parts.append('</svg>')
    return {"svg": "".join(parts), "nodes": nodes, "edges": edges,
            "rendering": "not_performed", "layout": "deterministic_schematic"}, issues, "draft"


def _connections(payload: dict):
    components = _records(payload, "components", required=True)
    index, connections, issues = _index(components), _records(payload, "connections"), []
    graph = {key: set() for key in index}
    for connection in connections:
        require_fields(connection, ("from", "to"))
        require(isinstance(connection["from"], (str, int)) and isinstance(connection["to"], (str, int)),
                "connection_identifier_required")
        require(connection["from"] in index and connection["to"] in index,
                "connection_component_unknown")
        graph[connection["from"]].add(connection["to"])
        graph[connection["to"]].add(connection["from"])
    groups, remaining = [], set(index)
    while remaining:
        start = min(remaining, key=str)
        reached, stack = set(), [start]
        while stack:
            key = stack.pop()
            if key not in reached:
                reached.add(key)
                stack.extend(graph[key])
        groups.append(sorted(reached, key=str))
        remaining -= reached
    if len(groups) > 1:
        _issue(issues, "disconnected_components", groups=groups)
    return {"components": components, "connections": connections,
            "connected_groups": groups, "cad_rendering": "not_performed",
            "unimplemented": ["CAD_projection", "cross_section", "manufacturability"]}, issues, "needs_review"


def _professional_data(payload: dict):
    require_fields(payload, ("mode",))
    mode, issues = payload["mode"], []
    if mode == "sequence":
        require_fields(payload, ("sequence", "alphabet", "evidence_id"))
        require(isinstance(payload["sequence"], str) and isinstance(payload["alphabet"], str),
                "sequence_text_required")
        sequence = "".join(payload["sequence"].split()).upper()
        alphabet = set(payload["alphabet"].upper())
        invalid = [{"position": i, "symbol": c} for i, c in enumerate(sequence, 1) if c not in alphabet]
        if invalid:
            _issue(issues, "sequence_symbol_invalid", positions=[r["position"] for r in invalid])
        return {"sequence": sequence, "length": len(sequence), "invalid_symbols": invalid,
                "evidence_id": payload["evidence_id"], "ST26_validation": "not_performed"}, issues, "needs_review"
    require(mode == "curve", "professional_mode_not_supported")
    series = _records(payload, "series", required=True)
    _index(series)
    all_points = []
    for item in series:
        points = item.get("points")
        require(isinstance(points, list) and bool(points), "series_points_required")
        for point in points:
            require(isinstance(point, list) and len(point) == 2, "xy_pair_required")
            all_points.append((_number(point[0]), _number(point[1])))
        if not item.get("evidence_id"):
            _issue(issues, "series_source_missing", series_id=item["id"])
    xmin, xmax = min(p[0] for p in all_points), max(p[0] for p in all_points)
    ymin, ymax = min(p[1] for p in all_points), max(p[1] for p in all_points)
    parts = [_svg_header(640, 420), '<path d="M60,30 V360 H600" fill="none" stroke="black"/>']
    for i, item in enumerate(series):
        points = " ".join(f"{60 + 520 * (x - xmin) / (xmax - xmin or 1):.6f},{360 - 300 * (y - ymin) / (ymax - ymin or 1):.6f}"
                          for x, y in item["points"])
        parts.append(f'<polyline points="{points}" fill="none" stroke="black" stroke-dasharray="{i + 1} {i + 1}"/>')
        parts.append(f'<text x="70" y="{45 + 18 * i}" font-size="12">{escape(str(item["id"]))}</text>')
    parts.append(f'<text x="70" y="400">x: {xmin}–{xmax} {escape(str(payload.get("x_unit", "unknown")))}; y: {ymin}–{ymax} {escape(str(payload.get("y_unit", "unknown")))}</text></svg>')
    return {"series": series, "svg": "".join(parts), "rendering": "not_performed",
            "source_verification": "not_performed", "chemical_structure_rendering": "not_implemented"}, issues, "draft"


def _views(payload: dict):
    views = _records(payload, "views", required=True)
    _index(views)
    dimensions, issues, inventory = {}, [], []
    for view in views:
        if not view.get("source_hash"):
            _issue(issues, "view_source_missing", view_id=view["id"])
        components = _records(view, "components")
        _index(components)
        inventory.append({"view_id": view["id"], "state": view.get("state", "unknown"),
                          "source_hash": view.get("source_hash"),
                          "components": [c["id"] for c in components]})
        for component in components:
            dims = component.get("model_dimensions")
            if dims is None:
                _issue(issues, "view_geometry_unknown", view_id=view["id"], component_id=component["id"])
                continue
            require(isinstance(dims, list) and len(dims) == 3, "three_model_dimensions_required")
            require(all(_number(d) > 0 for d in dims), "positive_dimensions_required")
            # 比较模型尺寸而非投影像素；不同GUI状态不能无条件互作反证。
            key = (view.get("state", "unknown"), component["id"])
            if key in dimensions and dimensions[key][0] != dims:
                _issue(issues, "view_geometry_conflict", component_id=component["id"],
                       view_ids=[dimensions[key][1], view["id"]])
            else:
                dimensions[key] = (dims, view["id"])
    return {"views": views, "inventory": inventory, "qualified_views": False,
            "rules": "jurisdiction_specific_unverified", "image_analysis": "not_performed",
            "unimplemented": ["occlusion_check", "dashed_line_rule_check", "physical_object_verification"]}, issues, "needs_review"


def _figure_check(payload: dict):
    figures = _records(payload, "figures", required=True)
    index, issues, records = _index(figures), [], []
    for ref in _strings(payload.get("figure_refs", []), "figure_refs"):
        if ref not in index:
            _issue(issues, "figure_reference_missing", figure_id=ref)
    for fig in figures:
        require_fields(fig, ("svg",))
        svg = fig["svg"]
        require(isinstance(svg, str), "svg_text_required")
        if re.search(r"<!DOCTYPE|<!ENTITY", svg, re.I):
            _issue(issues, "svg_unsafe_declaration", figure_id=fig["id"])
            continue
        try:
            root = ET.fromstring(svg)
        except ET.ParseError:
            _issue(issues, "svg_invalid", figure_id=fig["id"])
            continue
        if root.tag.split("}")[-1] != "svg":
            _issue(issues, "svg_root_invalid", figure_id=fig["id"])
            continue
        try:
            bounds = [float(x) for x in root.attrib.get("viewBox", "").replace(",", " ").split()]
        except ValueError:
            bounds = []
        if len(bounds) != 4 or not all(math.isfinite(x) for x in bounds) or min(bounds[2:]) <= 0:
            _issue(issues, "svg_viewbox_invalid", figure_id=fig["id"])
            continue
        bx, by, width, height = bounds
        for node in root.iter():
            tag = node.tag.split("}")[-1]
            if tag in {"script", "foreignObject", "image", "use"} or any(
                    k.lower().startswith("on") or k.split("}")[-1] == "href" for k in node.attrib):
                _issue(issues, "svg_active_or_external_content", figure_id=fig["id"])
            if tag not in {"rect", "text"}:
                continue
            try:
                x, y = float(node.get("x", "0")), float(node.get("y", "0"))
                w, h = float(node.get("width", "0")), float(node.get("height", "0"))
            except ValueError:
                _issue(issues, "svg_geometry_unparsed", figure_id=fig["id"])
                continue
            if (not all(math.isfinite(n) for n in (x, y, w, h)) or w < 0 or h < 0
                    or x < bx or y < by or x + w > bx + width or y + h > by + height):
                _issue(issues, "geometry_outside_viewbox", figure_id=fig["id"], element=tag)
        records.append({"figure_id": fig["id"], "svg_hash": digest(svg), "xml_parsed": True})
    _issue(issues, "rendering_not_performed")
    return {"static_checks": records, "rendering": "not_performed",
            "unchecked": ["glyph_extents", "path_extents", "transforms", "font_substitution", "export_crop"]}, issues, "needs_review"


def _technical(payload: dict):
    issues, groups = [], {}
    measurements = _records(payload, "measurements")
    for measurement in measurements:
        require_fields(measurement, ("id", "quantity", "value", "unit", "locator"))
        require(all(isinstance(measurement[key], str)
                    for key in ("quantity", "unit", "locator")), "measurement_text_required")
        _number(measurement["value"])
        groups.setdefault(measurement["quantity"], []).append(measurement)
    for quantity, rows in groups.items():
        if len({(r["value"], r["unit"]) for r in rows}) > 1:
            _issue(issues, "measurement_conflict", quantity=quantity,
                   locators=[r["locator"] for r in rows])
    ranges = _records(payload, "ranges")
    for interval in ranges:
        require_fields(interval, ("id", "min", "max"))
        if _number(interval["min"]) > _number(interval["max"]):
            _issue(issues, "range_inverted", range_id=interval["id"])
    directions = _records(payload, "directions")
    for edge in directions:
        require_fields(edge, ("id", "text_from", "text_to", "figure_from", "figure_to"))
        if (edge["text_from"], edge["text_to"]) != (edge["figure_from"], edge["figure_to"]):
            _issue(issues, "direction_conflict", edge_id=edge["id"])
    if not measurements and not ranges and not directions:
        _issue(issues, "technical_records_missing")
    return {"measurements": measurements, "ranges": ranges, "directions": directions,
            "unit_conversion": "not_assumed"}, issues, "needs_review"


def _adversarial(payload: dict):
    assertions = _records(payload, "assertions", required=True)
    _index(assertions)
    issues, challenges = [], []
    for assertion in assertions:
        require_fields(assertion, ("text",))
        refs = _strings(assertion.get("evidence_ids", []), "evidence_ids")
        if not refs:
            _issue(issues, "assertion_evidence_missing", assertion_id=assertion["id"])
        challenges.append({"assertion_id": assertion["id"], "assertion": assertion["text"],
                           "evidence_ids": refs, "questions": [
                               "何种边界条件可使该陈述不成立？", "是否存在不采用该特征的替代实现？",
                               "被诉产品中如何合法观察和证明该特征？"]})
    return {"simulated": True, "challenges": challenges,
            "counterevidence": _records(payload, "counterevidence"),
            "official_opinion": False}, issues, "needs_review"


def run(capability: str, payload: dict) -> dict:
    """执行单项本地任务，返回共享结果信封；无效结构抛ContractError。

    必须显式声明sensitivity及四轴adaptation。合成资料不读取任何外部文件；
    非合成载荷须提供core.preflight所需环境/权限/时点，宿主读取仍由调用者负责。
    previous_input_hash用于提示重审，不继承签核；持久失效由共享VersionLedger维护。
    """
    require(capability in CAPABILITIES, "capability_not_supported")
    require_fields(payload, ("sensitivity", "adaptation"))
    require_fields(payload["adaptation"], ("jurisdiction", "right_type", "domain", "stage"))
    require(all(isinstance(payload["adaptation"][key], str) for key in
                ("jurisdiction", "right_type", "domain", "stage")), "adaptation_text_required")
    require(isinstance(payload["sensitivity"], str), "sensitivity_text_required")
    require(isinstance(payload.get("evidence", []), list), "evidence_list_required")
    require(payload["sensitivity"] in {"synthetic", "public", "confidential", "restricted"},
            "sensitivity_unknown")
    digest(payload)
    require(payload.get("delivery_stage", "draft") in {"draft", "final"}, "patent_delivery_stage_invalid")
    if payload["sensitivity"] != "synthetic":
        require_fields(payload, ("now", "purpose", "permissions", "environment"))
        preflight(payload["environment"], payload["permissions"], sensitivity=payload["sensitivity"],
                  purpose=payload["purpose"], now=payload["now"])
    p = copy.deepcopy(payload)
    applicability = p.get("applicability", {})
    require(isinstance(applicability, dict), "applicability_object_required")
    if "applies" in applicability:
        require(type(applicability["applies"]) is bool, "applicability_boolean_required")
    if applicability.get("applies") is False:
        require_fields(applicability, ("reason", "evidence_id"))
        artifacts, issues, status = {"applicability": applicability}, [], "not_applicable"
    elif capability in {"SEARCH-01", "SEARCH-03", "SEARCH-06"}:
        artifacts, issues, status = _search(p, capability)
    elif capability == "SEARCH-02":
        artifacts, issues, status = _strategy(p)
    elif capability in {"SEARCH-04", "SEARCH-05"}:
        artifacts, issues, status = _relations(p, capability)
    elif capability in {"ANALYSIS-01", "DRAFT-01"}:
        artifacts, issues, status = _facts(p)
    elif capability == "ANALYSIS-02":
        artifacts, issues, status = _matrix(p)
    elif capability in {"ANALYSIS-05", "REVIEW-02"}:
        artifacts, issues, status = _support(p)
    elif capability.startswith("ANALYSIS-"):
        artifacts, issues, status = _analysis(p, capability)
    elif capability == "DRAFT-02":
        artifacts, issues, status = _draft_claims(p)
    elif capability == "DRAFT-04":
        artifacts, issues, status = _examples(p)
    elif capability in {"DRAFT-03", "DRAFT-05", "DRAFT-06"}:
        artifacts, issues, status = _draft_text(p, capability)
    elif capability in {"DRAFT-07", "FIG-04"}:
        artifacts, issues, status = _views(p)
    elif capability == "DRAFT-08":
        artifacts, issues, status = _translation(p)
    elif capability == "FIG-01":
        artifacts, issues, status = _flow(p)
    elif capability == "FIG-02":
        artifacts, issues, status = _connections(p)
    elif capability == "FIG-03":
        artifacts, issues, status = _professional_data(p)
    elif capability == "FIG-05":
        artifacts, issues, status = _figure_check(p)
    elif capability == "REVIEW-01":
        artifacts, issues, status = _claim_check(p)
    elif capability == "REVIEW-03":
        artifacts, issues, status = _technical(p)
    elif capability == "REVIEW-04":
        artifacts, issues, status = _adversarial(p)
    else:
        artifacts, issues, status = _edit(p, capability)
    input_hash = digest({k: v for k, v in p.items() if k != "previous_input_hash"})
    previous = p.get("previous_input_hash")
    if previous and previous != input_hash:
        _issue(issues, "input_changed_re_review", previous_input_hash=previous)
    from .fidelity import audit, audit_bound_text, audit_text_quality
    texts = {field: artifacts[field] for field in ("markdown", "svg", "accepted_text")
             if isinstance(artifacts.get(field), str) and artifacts[field].strip()}
    if capability == "DRAFT-08":
        for segment in artifacts.get("segments", []):
            for field in ("accepted_text", "proposed"):
                if segment[field].strip():
                    texts[f"segment:{segment['id']}:{field}"] = segment[field]
    if "fidelity" in p:
        if texts:
            value = p["fidelity"]
            require_fields(value, ("documents",))
            require(isinstance(value["documents"], list)
                    and all(isinstance(doc, dict) for doc in value["documents"]),
                    "fidelity_documents_required")
            # 旧调用只接受完整候选文本相等；自动生成精确引用，不猜子串/语义位置。
            bindings = {}
            for field, text in texts.items():
                matches = [doc for doc in value["documents"]
                           if doc.get("role") == "candidate" and doc.get("text") == text]
                if matches:
                    require_fields(matches[0], ("id",))
                    bindings[field] = {"document_id": matches[0]["id"], "start": 0,
                                       "end": len(text), "quote": text}
            if len(bindings) == len(texts):
                fidelity_result = audit_bound_text(value, texts, bindings)
            else:
                fidelity_result = audit(value)
                fidelity_result["issues"].extend(
                    {"code": "generated_artifact_not_in_fidelity", "field": field,
                     "severity": "blocking"} for field in texts if field not in bindings)
                fidelity_result["status"] = "blocked"
                fidelity_result["artifact_binding_status"] = "incomplete"
        else:
            fidelity_result = audit(p["fidelity"])
            fidelity_result["artifact_binding_status"] = "not_performed"
    else:
        fidelity_result = {"status": "not_performed", "issues": [],
                           "reason": "fidelity_payload_not_supplied",
                           "natural_language_verified": False,
                           "professional_review": "not_performed"}
    artifacts["fidelity"] = fidelity_result
    # 实物轻量检查不依赖调用者的语义JSON，也不接受旧resolution豁免残留标记。
    quality = (audit_text_quality(texts, business="patent", stage="draft") if texts else
               {"status": "not_performed", "issues": [], "reason": "no_deliverable_text",
                "semantic_fidelity": "not_performed", "professional_review": "not_performed"})
    artifacts["text_quality"] = quality
    if p.get("delivery_stage") == "final" or "final_text_sources" in p:
        from .patent_gate import require_final_text
        sources = p.get("final_text_sources")
        if sources is None:
            sources = [row for row in p.get("fidelity", {}).get("documents", [])
                       if row.get("role") == "original"]
        # 最终出口拒绝无依据或不在受支持语法内的正文，不靠可伪造的公式放行。
        artifacts["final_text_gate"] = require_final_text(texts, sources)
    else:
        artifacts["final_text_gate"] = {"status": "not_performed", "delivery_allowed": False,
                                        "reason": "internal_draft_only"}
    for origin, report in (("fidelity", fidelity_result), ("text_quality", quality)):
        issues.extend({**issue, "origin": origin} for issue in report["issues"])
        if report["status"] == "blocked":
            status = "blocked"
        elif report["status"] == "needs_review" and status in {"checked", "draft"}:
            status = "needs_review"
    artifacts.update({"input_hash": input_hash, "previous_input_hash": previous,
                      "tool_version": TOOL_VERSION, "support_level": "drafting_assistance",
                      "review_inherited": False})
    return result(capability, status=status, artifacts=artifacts, issues=issues,
                  evidence=p.get("evidence", []), adaptation=p["adaptation"],
                  checks=["local_deterministic_transformation", "no_external_action",
                          "professional_rules_not_verified"])
