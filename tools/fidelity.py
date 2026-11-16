"""WP-01/05：已形式化关系的有限反例与实际稿件覆盖检查。

不抽取自然语言，不认证原始申请、技术事实、参数修改合法性或专业签核。
只处理调用者已授权提供的内联文本；没有文件读取、网络或执行入口。
"""
from __future__ import annotations

import itertools
import re

from .core import ContractError, digest, canonical_bytes, require, require_fields, sha256_bytes, strict_json_loads

MAX_ATOMS = 16
MAX_RECORDS = 256
MAX_INPUT_BYTES = 4_000_000
MAX_LOGIC_WORK = 2_000_000
FACT_STATES = {"explicit", "inferred", "unknown", "proposal", "conflicting"}
DOCUMENT_ROLES = {"original", "source", "product", "candidate", "internal"}
PARAMETER_ASPECTS = ("technical_feasibility", "implementation_coverage", "original_amendment_support")
SUPPORT_CONSIDERATIONS = ("parameter_domain", "function_and_effect", "combination", "individualization")


def _text(value, code):
    require(isinstance(value, str) and bool(value.strip()), code)
    return value


def _rows(payload, key):
    require_fields(payload, (key,))
    value = payload[key]
    require(isinstance(value, list) and len(value) <= MAX_RECORDS
            and all(isinstance(item, dict) for item in value), key + "_records_required")
    return value


def _index(rows, kind, key="id"):
    result = {}
    for row in rows:
        identity = _text(row.get(key), kind + "_id_required")
        require(identity not in result, "duplicate_" + kind)
        result[identity] = row
    return result


def _ids(value, code):
    require(isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value), code)
    require(len(set(value)) == len(value), "duplicate_" + code)
    return value


def _cite(value, documents):
    require_fields(value, ("document_id", "start", "end", "quote"))
    identity = value["document_id"]
    require(isinstance(identity, str) and identity in documents, "citation_document_unknown")
    document = documents[identity]
    start, end = value["start"], value["end"]
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(document["text"]),
            "citation_offsets_required")
    require(isinstance(value["quote"], str) and document["text"][start:end] == value["quote"],
            "citation_quote_mismatch")
    return document


def _formula(expr, atoms, depth=0, budget=None):
    budget = [0] if budget is None else budget
    budget[0] += 1
    require(depth <= 16 and budget[0] <= 256, "formula_budget_exceeded")
    if type(expr) is bool:
        return set(), 1
    if isinstance(expr, str):
        require(expr in atoms, "formula_atom_unknown")
        return {expr}, 1
    require(isinstance(expr, dict) and len(expr) == 1, "formula_object_required")
    operator, args = next(iter(expr.items()))
    require(operator in {"all", "any", "not", "implies"}, "formula_operator_unknown")
    if operator == "not":
        children = [args]
    else:
        require(isinstance(args, list) and bool(args), "formula_arguments_required")
        require(operator != "implies" or len(args) == 2, "implication_pair_required")
        children = args
    variables, size = set(), 1
    for child in children:
        used, nodes = _formula(child, atoms, depth + 1, budget)
        variables.update(used)
        size += nodes
    return variables, size


def _evaluate(expr, world):
    if type(expr) is bool:
        return expr
    if isinstance(expr, str):
        return world[expr]
    operator, args = next(iter(expr.items()))
    if operator == "not":
        return not _evaluate(args, world)
    if operator == "all":
        return all(_evaluate(x, world) for x in args)
    if operator == "any":
        return any(_evaluate(x, world) for x in args)
    return not _evaluate(args[0], world) or _evaluate(args[1], world)


def _compare(premises, query, atoms, remaining):
    variables, size = _formula(query, atoms)
    for premise in premises:
        used, count = _formula(premise, atoms)
        variables.update(used)
        size += count
    ordered = sorted(variables)
    work = (2 ** len(ordered)) * size
    require(work <= remaining[0], "logic_budget_exceeded")
    remaining[0] -= work
    valid = true = 0
    counter = witness = reverse = None
    antecedent_possible = False
    implication = isinstance(query, dict) and "implies" in query
    for values in itertools.product((False, True), repeat=len(ordered)):
        world = dict(zip(ordered, values))
        supported = all(_evaluate(p, world) for p in premises)
        proposed = _evaluate(query, world)
        if proposed and not supported and reverse is None:
            reverse = world
        if not supported:
            continue
        valid += 1
        if proposed:
            true += 1
            if witness is None:
                witness = world
        elif counter is None:
            counter = world
        if implication and _evaluate(query["implies"][0], world):
            antecedent_possible = True
    relation = ("inconsistent" if not valid else "entailed" if true == valid else
                "contradicted" if not true else "undetermined")
    return {"relation": relation, "admissible_assignments": valid, "supporting_assignment": witness,
            "countermodel": counter, "reverse_countermodel": reverse,
            "equivalent": bool(valid) and true == valid and reverse is None,
            "vacuous": implication and bool(valid) and not antecedent_possible,
            "variables": ordered, "work_units": work}


def _coverage(documents, regions, assertions, issues):
    result, spans = [], {key: [] for key, doc in documents.items() if doc["role"] == "candidate"}
    for region in regions:
        document = _cite(region.get("citation"), documents)
        require(document["role"] in {"candidate", "internal"}, "region_document_role_invalid")
        require(region.get("kind") in {"technical", "context"}, "region_kind_unknown")
        refs = _ids(region.get("assertion_ids", []), "region_assertion_ids_required")
        for ref in refs:
            require(ref in assertions, "region_assertion_unknown")
            a, r = assertions[ref]["citation"], region["citation"]
            if a["document_id"] != r["document_id"] or not (r["start"] <= a["start"] < a["end"] <= r["end"]):
                issues.append({"code": "assertion_outside_region", "region_id": region["id"],
                               "assertion_id": ref, "severity": "blocking"})
        if region["kind"] == "technical" and not refs:
            issues.append({"code": "technical_region_unchecked", "region_id": region["id"], "severity": "blocking"})
        if region["kind"] == "context":
            _text(region.get("reason"), "context_region_reason_required")
        if document["id"] in spans:
            spans[document["id"]].append((region["citation"]["start"], region["citation"]["end"]))
        result.append({"region_id": region["id"], "citation": region["citation"],
                       "kind": region["kind"], "assertion_ids": refs,
                       "classification": "caller_classification_not_verified"})
    for identity, intervals in spans.items():
        text, cursor = documents[identity]["text"], 0
        for start, end in sorted(intervals) + [(len(documents[identity]["text"]), len(documents[identity]["text"]))]:
            if start > cursor and text[cursor:start].strip():
                issues.append({"code": "candidate_region_unmapped", "document_id": identity,
                               "start": cursor, "end": start, "severity": "blocking"})
            cursor = max(cursor, end)
    return result


def _parameters(requests, assessments, documents, issues):
    _index(assessments, "parameter_assessment", "request_id")
    known = _index(requests, "parameter_request")
    by_request = {row["request_id"]: row for row in assessments}
    for row in requests:
        _text(row.get("symbol"), "parameter_symbol_required")
        _cite(row.get("citation"), documents)
    for identity in by_request:
        require(identity in known, "parameter_request_unknown")
    results = []
    for identity, request in known.items():
        assessment = by_request.get(identity)
        if assessment is None:
            issues.append({"code": "parameter_assessment_missing", "request_id": identity, "severity": "blocking"})
            continue
        recorded = {}
        for aspect in PARAMETER_ASPECTS:
            value = assessment.get(aspect)
            if not isinstance(value, dict):
                issues.append({"code": "parameter_aspect_missing", "request_id": identity,
                               "aspect": aspect, "severity": "blocking"})
                continue
            require(value.get("status") in {"candidate_supported", "candidate_not_supported", "conditional", "unknown"},
                    "parameter_assessment_status_unknown")
            reasoning = _cite(value.get("reasoning"), documents)
            require(reasoning["role"] in {"internal", "candidate"}, "parameter_reasoning_role_invalid")
            conditions = _ids(value.get("conditions", []), "parameter_conditions_required")
            if value["status"] in {"conditional", "unknown"} and not conditions:
                issues.append({"code": "parameter_conditions_missing", "request_id": identity,
                               "aspect": aspect, "severity": "blocking"})
            if aspect == "original_amendment_support":
                considerations = value.get("considerations", {})
                if not isinstance(considerations, dict) or any(key not in considerations for key in SUPPORT_CONSIDERATIONS):
                    issues.append({"code": "parameter_support_context_missing", "request_id": identity, "severity": "blocking"})
                else:
                    for key in SUPPORT_CONSIDERATIONS:
                        _cite(considerations[key], documents)
                originals = value.get("original_citations", [])
                require(isinstance(originals, list), "parameter_original_citations_required")
                if not originals:
                    issues.append({"code": "parameter_original_source_missing", "request_id": identity,
                                   "severity": "review" if value["status"] == "unknown" else "blocking"})
                for cite in originals:
                    if _cite(cite, documents)["role"] != "original":
                        issues.append({"code": "parameter_original_source_required", "request_id": identity, "severity": "blocking"})
            recorded[aspect] = value
        results.append({"request_id": identity, "symbol": request["symbol"], "recorded_aspects": recorded,
                        "professional_support": "not_verified", "assessment_quality": "not_automatically_determined"})
    return results


def audit(payload: dict) -> dict:
    """反例只属于有限、由调用者解释的模型；checked不证明自然语言或专业支持。"""
    require(isinstance(payload, dict), "fidelity_object_required")
    try:
        encoded = canonical_bytes(payload)
    except RecursionError as exc:
        raise ContractError("fidelity_input_nesting_exceeded") from exc
    except ContractError as exc:
        if isinstance(exc.__cause__, UnicodeError):
            raise ContractError("fidelity_text_encoding_invalid") from exc
        raise
    except UnicodeError as exc:
        raise ContractError("fidelity_text_encoding_invalid") from exc
    require(len(encoded) <= MAX_INPUT_BYTES, "fidelity_input_budget_exceeded")
    documents = _index(_rows(payload, "documents"), "document")
    for document in documents.values():
        require(document.get("role") in DOCUMENT_ROLES, "document_role_unknown")
        _text(document.get("version"), "document_version_required")
        text = _text(document.get("text"), "document_text_required")
        require(document.get("sha256") == sha256_bytes(text.encode("utf-8")), "document_hash_mismatch")
    atoms = _index(_rows(payload, "atoms"), "atom")
    require(len(atoms) <= MAX_ATOMS, "atom_budget_exceeded")
    for atom in atoms.values():
        _text(atom.get("meaning"), "atom_meaning_required")
        _text(atom.get("scope"), "atom_scope_required")
    facts = _index(_rows(payload, "facts"), "fact")
    for fact in facts.values():
        document = _cite(fact.get("citation"), documents)
        require(fact.get("state") in FACT_STATES, "fact_state_unknown")
        require(fact["state"] != "explicit" or document["role"] in {"original", "source", "product"},
                "explicit_fact_source_role_required")
        _formula(fact.get("formula"), atoms)
    assertions = _index(_rows(payload, "assertions"), "assertion")
    regions = _rows(payload, "regions")
    _index(regions, "region")
    issues, checked, remaining = [], [], [MAX_LOGIC_WORK]
    # 同一已声明模型内的相反事实不能通过只选其中一条依据而被隐藏。
    for scope in sorted({row.get("proof_scope", "") for row in assertions.values()}):
        eligible = [fact["formula"] for fact in facts.values() if fact["state"] == "explicit" and
                    (scope != "original_support" or documents[fact["citation"]["document_id"]]["role"] == "original")]
        if eligible and _compare(eligible, True, atoms, remaining)["relation"] == "inconsistent":
            issues.append({"code": "explicit_facts_inconsistent", "proof_scope": scope, "severity": "blocking"})
    for identity, assertion in assertions.items():
        document = _cite(assertion.get("citation"), documents)
        require(document["role"] in {"candidate", "internal"}, "assertion_document_role_invalid")
        require(assertion.get("proof_scope") in {"original_support", "technical_consistency"}, "proof_scope_required")
        mode = assertion.get("mode", "asserted")
        require(mode in {"asserted", "proposal", "open_question"}, "assertion_mode_unknown")
        comparison = assertion.get("comparison", "entails")
        require(comparison in {"entails", "equivalent"}, "comparison_unknown")
        _formula(assertion.get("formula"), atoms)
        attributed = None
        if "attributed_document_id" in assertion:
            attributed = _text(assertion["attributed_document_id"], "attributed_document_id_required")
            require(attributed in documents, "attributed_document_unknown")
            require(documents[attributed]["role"] in {"original", "source", "product"},
                    "attributed_document_role_invalid")
        premises, accepted = [], []
        for ref in _ids(assertion.get("basis_fact_ids"), "basis_fact_ids_required"):
            require(ref in facts, "basis_fact_unknown")
            fact = facts[ref]
            # 某文献的记载不能由另一材料中的真命题充作依据；组合分析不声明单一归属。
            if attributed is not None and fact["citation"]["document_id"] != attributed:
                issues.append({"code": "basis_attribution_mismatch", "assertion_id": identity,
                               "fact_id": ref, "expected_document_id": attributed,
                               "actual_document_id": fact["citation"]["document_id"],
                               "severity": "blocking" if mode == "asserted" else "review"})
                continue
            if fact["state"] != "explicit":
                issues.append({"code": "basis_not_explicit", "assertion_id": identity, "fact_id": ref,
                               "severity": "blocking" if mode == "asserted" else "review"})
                continue
            if assertion["proof_scope"] == "original_support" and documents[fact["citation"]["document_id"]]["role"] != "original":
                issues.append({"code": "basis_not_original", "assertion_id": identity, "fact_id": ref, "severity": "blocking"})
                continue
            premises.append(fact["formula"])
            accepted.append(ref)
        if mode == "asserted" and assertion["proof_scope"] == "original_support" and not accepted:
            issues.append({"code": "original_basis_missing", "assertion_id": identity, "severity": "blocking"})
        if mode == "asserted" and attributed is not None and not accepted:
            issues.append({"code": "attributed_basis_missing", "assertion_id": identity, "severity": "blocking"})
        result = _compare(premises, assertion["formula"], atoms, remaining)
        if mode == "asserted":
            code = {"inconsistent": "inconsistent_basis", "contradicted": "assertion_contradicted",
                    "undetermined": "assertion_not_entailed"}.get(result["relation"])
            if code:
                issues.append({"code": code, "assertion_id": identity, "severity": "blocking"})
            if comparison == "equivalent" and not result["equivalent"]:
                issues.append({"code": "assertion_not_equivalent", "assertion_id": identity, "severity": "blocking"})
            if result["vacuous"]:
                issues.append({"code": "vacuous_assertion", "assertion_id": identity, "severity": "blocking"})
        if mode == "proposal" and document["role"] == "candidate":
            issues.append({"code": "proposal_in_candidate", "assertion_id": identity, "severity": "blocking"})
        checked.append({"assertion_id": identity, "citation": assertion["citation"], "mode": mode,
                        "proof_scope": assertion["proof_scope"], "accepted_basis_fact_ids": accepted, **result})
        if attributed is not None:
            checked[-1]["attributed_document_id"] = attributed
    coverage = _coverage(documents, regions, assertions, issues)
    region_assertions = {ref for region in regions if region["kind"] == "technical"
                         for ref in region.get("assertion_ids", [])}
    for identity, assertion in assertions.items():
        if documents[assertion["citation"]["document_id"]]["role"] == "candidate" and identity not in region_assertions:
            issues.append({"code": "candidate_assertion_region_missing", "assertion_id": identity, "severity": "blocking"})
    parameters = _parameters(_rows(payload, "parameter_requests"), _rows(payload, "parameter_assessments"), documents, issues)
    has_candidate = any(doc["role"] == "candidate" for doc in documents.values())
    if has_candidate and not any(documents[a["citation"]["document_id"]]["role"] == "candidate" and
                                 a.get("mode", "asserted") == "asserted" for a in assertions.values()):
        issues.append({"code": "candidate_technical_assertions_missing", "severity": "review"})
    status = ("blocked" if any(x["severity"] == "blocking" for x in issues) else "needs_review" if
              issues or not has_candidate or any(a["mode"] != "asserted" for a in checked) else "checked")
    return {"status": status, "input_hash": digest(payload), "issues": issues, "assertions": checked,
            "coverage": coverage, "parameter_assessments": parameters,
            "documents": [{k: row[k] for k in ("id", "version", "role", "sha256")} for row in documents.values()],
            "logic_work_units": MAX_LOGIC_WORK - remaining[0],
            "scope": "finite_caller_formalization_and_supplied_text_only",
            "natural_language_verified": False, "professional_review": "not_performed",
            "official_status": "not_asserted", "external_action": "not_performed"}


def scan_placeholders(texts: dict[str, str], documents: dict, bindings: dict, resolved: list) -> dict:
    """AF-01：候选交付文本里残留的待确认标记。

    只扫已绑定交付文本的原文，不推断标记是否已被消解；消解须由调用者提供
    带依据与责任人的记录。标记是作者自留的缺口信号，不是证据。
    此函数保留旧记录兼容性；正式成件必须另调audit_text_quality，残留标记
    无论有无旧消解记录都阻塞正式交付，不能以本函数checked代替成件检查。
    """
    require(isinstance(resolved, list) and all(isinstance(row, dict) for row in resolved),
            "placeholder_resolutions_list_required")
    cleared = {}
    for row in resolved:
        identity = _text(row.get("id"), "placeholder_resolution_id_required")
        require(identity not in cleared, "duplicate_placeholder_resolution")
        _text(row.get("resolution_source"), "placeholder_resolution_source_required")
        _text(row.get("reviewer"), "placeholder_resolution_reviewer_required")
        cleared[identity] = row
    hits, issues = [], []
    for block_id, cite in bindings.items():
        document = documents[cite["document_id"]]
        require(document["role"] in PLACEHOLDER_ROLES, "placeholder_document_role_invalid")
        text = texts[block_id]
        for match in PLACEHOLDER_PATTERN.finditer(text):
            identity = block_id + "#" + str(match.start())
            record = cleared.get(identity)
            severity = "review" if document["role"] == "internal" else "blocking"
            if record is None:
                code = ("unresolved_placeholder_in_internal" if severity == "review"
                        else "unresolved_placeholder_in_candidate")
                issues.append({"code": code, "block_id": block_id, "offset": match.start(),
                               "marker": match.group(0)[:200],
                               "question": match.group(1).strip()[:500], "severity": severity})
            elif record["resolution_source"] != document["version"]:
                issues.append({"code": "placeholder_resolution_unproven", "block_id": block_id,
                               "offset": match.start(), "resolution_id": identity,
                               "severity": severity})
            else:
                hits.append({"block_id": block_id, "offset": match.start(), "resolution_id": identity,
                             "resolution_source": record["resolution_source"], "reviewer": record["reviewer"]})
    status = ("blocked" if any(row["severity"] == "blocking" for row in issues) else
              "needs_review" if issues else "checked")
    return {"status": status, "issues": issues, "resolved": hits,
            "scope": "supplied_artifact_text_only_not_semantic_completion",
            "resolutions_authenticated": "not_performed"}


def check_phrasing(texts: dict[str, str], scope: str) -> dict:
    """AF-05：本范围内禁用措辞。只报命中与建议，不判断句子在上下文里是否已带限定。

    命中为 review 级：调用者须回改措辞或显式带范围限定后重交，不能用工具禁用词表
    代替专业审阅。
    """
    require(scope in OVERCLAIM_PHRASES, "overclaim_scope_unknown")
    hits = []
    for block_id, text in texts.items():
        _text(text, "phrasing_text_required")
        for phrase, advice in OVERCLAIM_PHRASES[scope]:
            start = text.find(phrase)
            while start != -1:
                hits.append({"code": "phrasing_overclaim", "block_id": block_id,
                             "offset": start, "phrase": phrase, "advice": advice, "severity": "review"})
                start = text.find(phrase, start + len(phrase))
    return {"status": "needs_review" if hits else "checked", "scope": scope,
            "issues": hits, "natural_language_verified": False}


def audit_text_quality(texts: dict[str, str], *, business="standard", stage="draft", coverage=None) -> dict:
    """AF-01/05实际文本质量：独立于语义映射，不接受消解记录豁免残留标记。

    stage只约束消费者能否输出内部草稿，不降低问题等级。原文、引用和否定
    均原样保留；措辞命中只是带上下文的人工待审提示，不自动改结论。
    """
    require(isinstance(business, str) and business in {"standard", "patent", "software"},
            "document_business_invalid")
    require(isinstance(stage, str) and stage in {"draft", "final"}, "document_delivery_stage_invalid")
    require(isinstance(texts, dict) and all(isinstance(k, str) and isinstance(v, str)
            for k, v in texts.items()), "quality_texts_required")
    require(len(canonical_bytes(texts)) <= MAX_INPUT_BYTES, "quality_text_budget_exceeded")
    scope = {"standard": "standard_review", "patent": "patent_draft", "software": "software_copyright"}[business]
    issues = []
    meaningful = {key: text for key, text in texts.items() if text.strip()}
    for block_id, text in meaningful.items():
        for match in PLACEHOLDER_PATTERN.finditer(text):
            issues.append({"code": "placeholder_remaining_in_artifact", "block_id": block_id,
                "offset": match.start(), "end": match.end(), "marker": match.group(0),
                "question": match.group(1).strip(), "severity": "blocking",
                "context": text[max(0, match.start() - 80):match.end() + 80],
                "text_sha256": sha256_bytes(text.encode("utf-8"))})
    for check_scope in (scope, "verification"):
        for hit in check_phrasing(meaningful, check_scope)["issues"]:
            text = meaningful[hit["block_id"]]
            end = hit["offset"] + len(hit["phrase"])
            issues.append({**hit, "end": end, "scope": check_scope,
                "context": text[max(0, hit["offset"] - 80):end + 80],
                "text_sha256": sha256_bytes(text.encode("utf-8")),
                "handling": "context_review_not_automatic_rewrite"})
    if coverage is None:
        coverage = {"state": "complete_supported_subset", "scope": "supplied_text_only",
                    "unsupported_objects": []}
    require(isinstance(coverage, dict) and coverage.get("state") in {"complete_supported_subset", "partial"}
            and isinstance(coverage.get("unsupported_objects"), list), "quality_coverage_invalid")
    coverage = {**coverage, "text_blocks": len(meaningful)}
    if not meaningful:
        coverage["state"] = "partial"
        issues.append({"code": "quality_text_coverage_empty", "severity": "review"})
    if coverage["unsupported_objects"]:
        coverage["state"] = "partial"
    if coverage["state"] == "partial":
        issues.append({"code": "quality_coverage_partial", "severity": "review"})
    status = "blocked" if any(row["severity"] == "blocking" for row in issues) else "needs_review" if issues else "checked"
    return {"contract_version": "1", "status": status, "stage": stage,
        "input_hash": digest({"texts": texts, "business": business, "stage": stage, "coverage": coverage}),
        "issues": issues, "coverage": coverage, "semantic_fidelity": "not_performed",
        "natural_language_verified": False, "professional_review": "not_performed",
        "official_status": "not_asserted", "external_action": "not_performed",
        "residual_marker_policy": "no_resolution_record_exemption"}


def audit_bound_text(payload: dict, texts: dict[str, str], bindings: dict) -> dict:
    """把当前消费者实际使用的每段文字绑定到受核候选；不采信另一份示范稿。"""
    require(isinstance(texts, dict) and bool(texts), "artifact_texts_required")
    require(isinstance(bindings, dict) and set(bindings) == set(texts), "artifact_binding_members_mismatch")
    report = audit(payload)
    documents = {row["id"]: row for row in payload["documents"]}
    bound = []
    for identity, text in texts.items():
        _text(text, "artifact_text_required")
        cite = bindings[identity]
        document = _cite(cite, documents)
        require(document["role"] == "candidate", "artifact_candidate_required")
        if cite["quote"] != text:
            report["issues"].append({"code": "artifact_text_not_in_fidelity", "artifact_id": identity,
                                     "severity": "blocking"})
            report["status"] = "blocked"
        bound.append({"artifact_id": identity, "text_sha256": sha256_bytes(text.encode("utf-8")),
                      "citation": cite})
    placeholders = scan_placeholders(texts, documents, bindings, payload.get("placeholder_resolutions", []))
    report["artifact_bindings"] = bound
    report["placeholders"] = placeholders
    # 待确认标记是作者自留的缺口信号：正式交付文本里残留就不算可交付。
    if placeholders["issues"]:
        report["issues"].extend(placeholders["issues"])
        report["status"] = "blocked" if placeholders["status"] == "blocked" else (
            "needs_review" if report["status"] == "checked" else report["status"])
    return report


READING_STATES = {"known", "unknown", "not_checked", "unavailable", "not_applicable"}
READING_MEDIA = {"pdf": "PDF", "xml": "XML", "text": "文本", "docx": "Word", "image": "图像"}
READING_UNITS = {"physical_page": "页", "numbered_paragraph": "段", "line": "行",
                 "logical_figure": "幅逻辑图", "drawing_object": "个绘图对象", "image": "幅图像", "paragraph_block": "个段落块"}
READING_OPERATIONS = {"visual_review": "目视", "text_read": "文字阅读", "machine_extracted": "机器提取", "rendered": "渲染"}

# AF-01：待确认标记。允许半角/全角方括号与圆括号，中英文变体各自成组。
PLACEHOLDER_PATTERN = re.compile(
    r"[\[【（(]\s*(?:"
    r"TO\s*CONFIRM|to\s*confirm|TODO[-_\s]*确认|todo[-_\s]*确认"
    r"|待确认|待核实|待补充确认|待补证"
    r")\s*[:：]?([^\]】）)]*)[\]】）)]",
    re.IGNORECASE,
)
PLACEHOLDER_ROLES = {"candidate", "internal"}

# AF-05：按范围划分的禁用措辞。命中不等于错误，但不能无条件使用；须带范围限定语。
OVERCLAIM_PHRASES = {
    "standard_review": (
        ("全文符合", "只可就实际审阅的条款范围说明，例如“在本次文本审稿范围内未发现问题”"),
        ("完全符合", "只可就实际审稿范围说明，不覆盖未审条款"),
        ("不存在该标准", "只可写本次检索未命中；网络失败、权限不足与零命中须分列"),
        ("未见任何公开", "只可就本次检索范围与来源说明，不推及全部公开"),
        ("已通过审查", "审查结论属组织程序；文本工具只能说明结构检查结果"),
    ),
    "verification": (
        ("验证通过", "须指明是计划、执行、结果、符合性还是认证中的哪一层"),
        ("试验合格", "试验结果须带方法、样本、条件与判定依据"),
        ("实测无误", "须给出实际执行记录与覆盖范围"),
    ),
    "patent_draft": (
        ("保证授权", "可专利性由审查机构判断，草稿不作授权保证"),
        ("全球保护", "逐地区申请与保护范围分别核验，不作全球概括"),
    ),
    "software_copyright": (
        ("权属无争议", "权属须由实际材料与专业判断确认"),
        ("已确认原创", "原创性判断须留人工复核记录"),
    ),
}


def _reading_label(value):
    _text(value, "reading_label_required")
    require(len(value) <= 128 and all(ord(c) >= 32 for c in value), "reading_label_invalid")
    return value


def _reading_subject(value):
    require(isinstance(value, dict) and set(value) == {"document_id", "version"}, "reading_subject_required")
    return (_reading_label(value["document_id"]), None if value["version"] is None else _reading_label(value["version"]))


def _reading_ranges(value, total, *, limit=MAX_RECORDS):
    require(isinstance(value, list) and len(value) <= limit, "reading_ranges_required")
    intervals = []
    for pair in value:
        require(isinstance(pair, list) and len(pair) == 2 and all(type(n) is int for n in pair), "reading_range_pair_required")
        start, end = pair
        require(1 <= start <= end <= 1_000_000 and (total is None or end <= total), "reading_range_bounds")
        intervals.append((start, end))
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def audit_reading_scope(payload: dict, *, texts=None, bindings=None) -> dict:
    """Project bounded counts from cited JSON records, not from free prose.

    Citations bind ledger bytes; they do not authenticate the observation or
    the human extraction that produced the ledger. Actual scope blocks must
    equal these projections. Unclassified prose remains outside this check.
    """
    require(isinstance(payload, dict), "reading_scope_object_required")
    try:
        encoded = canonical_bytes(payload)
    except (RecursionError, UnicodeError) as exc:
        raise ContractError("reading_scope_encoding_or_nesting") from exc
    require(len(encoded) <= MAX_INPUT_BYTES, "reading_scope_input_budget")
    documents = _index(_rows(payload, "documents"), "document")
    for doc in documents.values():
        require(doc.get("role") in {"original", "source"}, "reading_evidence_source_role")
        _reading_label(doc.get("version"))
        text = _text(doc.get("text"), "document_text_required")
        require(doc.get("sha256") == sha256_bytes(text.encode("utf-8")), "document_hash_mismatch")
    supplied = _index(_rows(payload, "readings"), "reading")
    statements = _index(_rows(payload, "statements"), "reading_statement")
    require(bool(supplied) and bool(statements), "reading_scope_records_required")
    readings = {}
    fields = {"subject", "medium", "unit", "operation", "origin", "event_id", "state", "total", "ranges"}
    for identity, row in supplied.items():
        _cite(row.get("citation"), documents)
        try:
            value = strict_json_loads(row["citation"]["quote"])
        except (ValueError, RecursionError) as exc:
            raise ContractError("reading_record_json_required") from exc
        require(isinstance(value, dict) and fields <= set(value) <= fields | {"reason"}, "reading_record_fields")
        subject = _reading_subject(value["subject"])
        require(isinstance(value["medium"], str) and value["medium"] in READING_MEDIA
                and isinstance(value["unit"], str) and value["unit"] in READING_UNITS, "reading_medium_or_unit_unknown")
        require(isinstance(value["operation"], str) and value["operation"] in READING_OPERATIONS
                and isinstance(value["origin"], str) and value["origin"] in {"direct", "reported"}, "reading_operation_or_origin_unknown")
        _reading_label(value["event_id"])
        require(isinstance(value["state"], str) and value["state"] in READING_STATES, "reading_state_unknown")
        total = value["total"]
        require(total is None or type(total) is int and 1 <= total <= 1_000_000, "reading_total_invalid")
        ranges = _reading_ranges(value["ranges"], total)
        if value["state"] != "known":
            require(not ranges, "reading_unknown_has_ranges")
            _reading_label(value.get("reason"))
        readings[identity] = {**value, "id": identity, "ranges": ranges, "citation": dict(row["citation"]),
            "subject": {"document_id": subject[0], "version": subject[1]},
            "covered": sum(end - start + 1 for start, end in ranges) if value["state"] == "known" else None}
    issues, projected, projection_chars, range_work = [], [], 0, 0
    for identity, statement in statements.items():
        require(isinstance(statement.get("kind"), str) and statement["kind"] in {"single", "aggregate"}, "reading_statement_kind")
        refs = _ids(statement.get("reading_ids"), "reading_ids_required")
        require(bool(refs) and all(ref in readings for ref in refs), "reading_basis_unknown")
        rows = [readings[ref] for ref in refs]
        contexts = {(r["medium"], r["unit"], r["operation"], r["origin"], r["event_id"]) for r in rows}
        groups = {}
        for row in rows:
            groups.setdefault(_reading_subject(row["subject"]), []).append(row)
        subjects = sorted(groups, key=lambda pair: (pair[0], pair[1] or ""))
        row_issues = []
        if len(contexts) != 1:
            row_issues.append("reading_context_mismatch")
        if statement["kind"] == "single" and len(subjects) != 1:
            row_issues.append("reading_single_subject_required")
        if statement["kind"] == "aggregate" and len(subjects) < 2:
            row_issues.append("reading_aggregate_subjects_required")
        counts, totals = [], []
        for subject in subjects:
            group = groups[subject]
            known_totals = {r["total"] for r in group if r["total"] is not None}
            if len(known_totals) > 1:
                row_issues.append("reading_total_conflict")
            total = next(iter(known_totals)) if len(known_totals) == 1 and all(r["total"] is not None for r in group) else None
            intervals = [pair for r in group for pair in r["ranges"]]
            range_work += len(intervals)
            require(range_work <= MAX_LOGIC_WORK, "reading_scope_work_budget")
            union = _reading_ranges(intervals, None, limit=MAX_RECORDS ** 2)
            if known_totals and any(end > min(known_totals) for _, end in union):
                row_issues.append("reading_range_total_conflict")
            counts.append(sum(end - start + 1 for start, end in union) if all(r["state"] == "known" for r in group) else None)
            totals.append(total)
        covered = sum(counts) if all(n is not None for n in counts) and len(contexts) == 1 else None
        total = sum(totals) if all(n is not None for n in totals) and len(contexts) == 1 else None
        if {"reading_total_conflict", "reading_range_total_conflict"}.intersection(row_issues):
            covered = total = None
        expected = statement.get("expected")
        if expected is not None:
            require(isinstance(expected, dict) and set(expected) == {"subjects", "covered", "total"}, "reading_expected_fields")
            require(isinstance(expected["subjects"], list), "reading_expected_subjects")
            wanted = [_reading_subject(row) for row in expected["subjects"]]
            require(len(wanted) == len(set(wanted)), "reading_expected_subject_duplicate")
            for name in ["covered", "total"]:
                require(expected[name] is None or type(expected[name]) is int and expected[name] >= 0, "reading_expected_count")
            if set(wanted) != set(subjects):
                row_issues.append("reading_subject_mismatch")
            if (expected["covered"], expected["total"]) != (covered, total):
                row_issues.append("reading_count_mismatch")
        projection = None
        invalid_group = {"reading_context_mismatch", "reading_total_conflict", "reading_range_total_conflict",
                         "reading_single_subject_required", "reading_aggregate_subjects_required"}.intersection(row_issues)
        known = not invalid_group and covered is not None and total is not None and all(subject[1] is not None for subject in subjects)
        if not invalid_group:
            medium, unit, operation, origin, event = next(iter(contexts))
            names = "＋".join(name + "（" + (version or "版本未知") + "）" for name, version in subjects)
            prefix = ("直接记录" if origin == "direct" else "转述记录") + "〔" + event + "〕：" + names + READING_MEDIA[medium] + READING_OPERATIONS[operation]
            if covered is not None:
                projection = prefix + ("合计覆盖" if statement["kind"] == "aggregate" else "覆盖") + str(covered) + "/" + (str(total) if total is not None else "?") + READING_UNITS[unit]
                projection += "（仅所列版本）。" if statement["kind"] == "aggregate" else "。"
            else:
                labels = {"unknown": "未知", "not_checked": "未检查", "unavailable": "未取得", "not_applicable": "声明不适用"}
                states = sorted({labels[r["state"]] + "：" + r["reason"] for r in rows if r["state"] != "known"})
                projection = prefix + "范围未确定（" + "；".join(states) + "）；已覆盖数不作零或全部认定。"
            if not known:
                projection += "范围或版本仍待核，不能据此认定全文已审。"
            projection_chars += len(projection)
            require(len(projection) <= 32_000 and projection_chars <= 200_000, "reading_projection_budget")
        issues.extend({"code": code, "statement_id": identity, "severity": "blocking"} for code in dict.fromkeys(row_issues))
        projected.append({"id": identity, "kind": statement["kind"], "reading_ids": refs,
            "subjects": [{"document_id": name, "version": version} for name, version in subjects],
            "covered": covered, "total": total, "state": "known" if known else "needs_review", "projection": projection})
    bound = []
    if texts is not None or bindings is not None:
        require(isinstance(texts, dict) and isinstance(bindings, dict) and set(texts) == set(bindings), "reading_binding_members")
        lookup = {row["id"]: row for row in projected}
        used = set()
        for block, ref in bindings.items():
            require(isinstance(ref, str) and ref in lookup and isinstance(texts[block], str), "reading_binding_unknown")
            used.add(ref)
            if texts[block] != lookup[ref]["projection"]:
                issues.append({"code": "reading_projection_mismatch", "block_id": block, "statement_id": ref, "severity": "blocking"})
            bound.append({"block_id": block, "statement_id": ref, "actual_text_sha256": sha256_bytes(texts[block].encode("utf-8"))})
        for identity in statements.keys() - used:
            issues.append({"code": "reading_statement_unbound", "statement_id": identity, "severity": "blocking"})
    status = "blocked" if issues else "needs_review" if any(row["state"] != "known" for row in projected) else "checked"
    return {"status": status, "contract_version": "1", "input_hash": digest(payload), "issues": issues,
        "readings": list(readings.values()), "statements": projected, "artifact_bindings": bound,
        "scope": "cited_structured_reading_records_and_selected_literal_projections_only",
        "natural_language_verified": False, "evidence_authentication": "not_performed", "professional_review": "not_performed",
        "unclassified_prose": "not_assessed", "official_status": "not_asserted", "external_action": "not_performed"}
