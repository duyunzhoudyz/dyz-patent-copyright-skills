"""SP-04：原创内部有限核稿；只定位差异和待审，不改文、不签核。

assess是数据评估入口。actual_texts须由消费者回读最终文件后以稳定条款ID
提供原条款文字，不拼入条件/例外等结构核对块。未传实际文字时只核输入，
明确保留实物未核。actual_blocks按来源binding提供非条款完整书签与唯一字段范围。
source_verification只接受本进程verify_reports的原对象。
规则资产是内部工程子集，不承诺任意自然语言、组织符合性或真实试验。
"""
from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from tools.core import canonical_bytes, digest, require, sha256_bytes, strict_json_loads
from tools import standard_sources

VERSION = "1.0"
MAX_RECORDS = 10_000
MAX_TEXT = 1_000_000
RULES_PATH = Path(__file__).resolve().parents[1] / "skills/dyz-standards/resources/lifecycle/review-rules.v1.json"
IMPLEMENTATIONS = {"reference_integrity", "term_consistency", "quantity_unit", "condition_direction",
                   "exception", "strength", "verification_link"}


def _rules():
    raw = RULES_PATH.read_bytes()
    value = strict_json_loads(raw.decode("utf-8"))
    require(value.get("schema") == "dyz-standard-finite-review-rules-v1"
            and value.get("scope") == "internal", "standard_review_rules_unsupported")
    rows = value.get("rules")
    require(isinstance(rows, list) and bool(rows), "standard_review_rules_required")
    require({row.get("implementation") for row in rows} == IMPLEMENTATIONS,
            "standard_review_rule_implementation_mismatch")
    for row in rows:
        require(all(row.get(key) for key in ("id", "version", "scope", "basis", "rights",
                    "objects", "deterministic_conditions", "pending_conditions", "uncovered")),
                "standard_review_rule_metadata_required")
    return value, sha256_bytes(raw)


_RULE_ASSET, _RULES_HASH = _rules()


def _records(payload, name):
    rows = payload.get(name, [])
    require(isinstance(rows, list) and len(rows) <= MAX_RECORDS, "review_records_required:" + name)
    require(all(isinstance(row, dict) for row in rows), "review_record_object_required:" + name)
    return rows


def _text(value):
    require(isinstance(value, str) and len(value) <= MAX_TEXT, "review_text_required")
    return value


def _sha(text):
    return sha256_bytes(text.encode("utf-8"))


def _span(text, start=0, end=None):
    end = len(text) if end is None else end
    return {"start": start, "end": end, "quote": text[start:end],
            "context_start": max(0, start - 60), "context_end": min(len(text), end + 60),
            "context": text[max(0, start - 60):min(len(text), end + 60)]}


def _find_span(text, quote):
    start = text.find(quote)
    return _span(text, start, start + len(quote)) if start >= 0 and quote else _span(text)


def _sentences(text, grammar):
    return [match.group() for match in re.finditer("[^" + re.escape(grammar["sentence_separators"]) + "]+", text)
            if match.group().strip()]


def _unsupported(text, grammar):
    stripped = text.strip()
    reasons = [word for word in grammar["unsupported_markers"] if word in stripped]
    reasons.extend(word for word in grammar["explanatory_prefixes"]
                   if stripped.startswith(word + "：") or stripped.startswith(word + ":"))
    # 此处只接受字面主语；不对说明性否定或转述中的单字模态作专业判断。
    if any(word in stripped for word in ("不是", "不等于", "不能认为", "不代表", "非必要", "不要求")):
        reasons.append("explanatory_negation")
    if re.search(r"\d\s*(?:±|～|~|至|≤|≥|<|>)|[±≤≥]", stripped):
        reasons.append("complex_quantity")
    return sorted(set(reasons))


def _modals(text, grammar):
    masked = list(text)
    for word in grammar["nonmodal_words"]:
        for match in re.finditer(re.escape(word), text):
            masked[match.start():match.end()] = " " * len(word)
    clean = "".join(masked)
    tokens = grammar["modal_tokens"]
    expression = "|".join(re.escape(word) for word in sorted(tokens, key=len, reverse=True))
    return [{"token": match.group(), "strength": tokens[match.group()],
             "start": match.start(), "end": match.end()} for match in re.finditer(expression, clean)]


def _quantities(text, grammar):
    units = "|".join(re.escape(unit) for unit in sorted(grammar["units"], key=len, reverse=True))
    expression = r"(?<![\d.\w])([+-]?\d+(?:\.\d+)?)\s*(" + units + r")(?![A-Za-z])"
    # 中文字符不属于数值左边界，单独排除ASCII技术标识中的数字。
    expression = expression.replace(r"(?<![\d.\w])", r"(?<![A-Za-z0-9_.])")
    return [{"value": match.group(1), "unit": match.group(2), "start": match.start(), "end": match.end(),
             "quote": match.group()} for match in re.finditer(expression, text)]


def _exceptions(text):
    values = []
    for match in re.finditer(r"(?:^|[。；;，,\n])\s*(?:但)?([^。；;，,\n]{1,60}?)除外", text):
        value = match.group(1).strip()
        if value:
            values.append({"value": value, "start": match.start(1), "end": match.end(1)})
    for match in re.finditer(r"(?:^|[。；;\n])\s*除([^。；;，,\n]{1,60}?)外[，,]", text):
        values.append({"value": match.group(1).strip(), "start": match.start(1), "end": match.end(1)})
    return values


def _without_exception(text):
    text = re.sub(r"(?:^|[。；;，,\n])\s*(?:但)?[^。；;，,\n]{1,60}?除外[。；;]?", "", text)
    text = re.sub(r"^\s*除[^。；;，,\n]{1,60}?外[，,]", "", text)
    return text.strip(" 。；;，,\n")


def _quantity_context(text, grammar):
    parts, cursor = [], 0
    for quantity in _quantities(text, grammar):
        parts.extend((text[cursor:quantity["start"]], "<quantity>"))
        cursor = quantity["end"]
    return "".join(parts + [text[cursor:]]).strip(" 。；;\n")


def _polarity(modal):
    return "negative" if modal["token"] in {"不应", "不得", "不宜"} else "positive"


def _condition(text, grammar):
    body = _without_exception(text)
    sentences = _sentences(body, grammar)
    if len(sentences) != 1 or _unsupported(body, grammar):
        return None
    body = body.strip(" 。；;\n")
    patterns = (("necessary", r"^(?:仅在|只有)(.+?)时[，,]?(.+)$"),
                ("sufficient", r"^(?:当|在)?(.+?)时[，,]?(.+)$"),
                ("sufficient", r"^如果(.+?)[，,]?则(.+)$"))
    for direction, pattern in patterns:
        matched = re.fullmatch(pattern, body)
        if matched:
            condition, action = (part.strip() for part in matched.groups())
            if not condition or not action or re.search(r"(?:仅在|只有|如果|则|时)", condition):
                return None
            modals = _modals(action, grammar)
            if len(modals) != 1 or modals[0]["start"] == 0:
                return None
            return {"direction": direction, "condition": condition, "action": action}
    return None


def _simple_clause(text, grammar):
    body = _without_exception(text)
    modals = _modals(body, grammar)
    return (len(_sentences(body, grammar)) == 1 and not _unsupported(body, grammar)
            and len(modals) <= 1 and (not modals or modals[0]["start"] > 0)
            and not re.search(r"(?:仅在|只有|如果|若|则|当|时|除外)", body))


def _source_location(text, citation=None):
    location = _span(text)
    if citation:
        location.update(citation_ids=citation["citation_ids"],
                        segments=[copy.deepcopy(part) for row in citation["citations"]
                                  for part in row.get("segments", [row])])
    return location


def _target_bindings(payload, identity):
    bindings = [r for r in payload.get("source_bindings", [])
                if r.get("target_type") == "clause" and r.get("target_id") == identity]
    wanted = {row.get("report_id") for row in bindings}
    reports = [r for r in payload.get("source_reports", []) if r.get("report_id") in wanted]
    return bindings, reports


def _source_declarations(payload, traces, issues, pending):
    reports = _records(payload, "source_reports")
    bindings = _records(payload, "source_bindings")
    report_checks, binding_checks, report_ids, binding_ids = [], [], set(), set()
    for row in reports:
        rid = row.get("report_id")
        require(isinstance(rid, str) and bool(rid.strip()), "source_report_id_required")
        if rid in report_ids:
            issues.append({"code": "source_report_id_duplicated", "record_id": rid})
        report_ids.add(rid)
        require(isinstance(row.get("path"), str) and bool(row["path"].strip()), "source_report_path_required")
        require(isinstance(row.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
                "source_report_sha256_required")
        require(isinstance(row.get("source"), (str, dict)) and bool(row["source"]), "source_report_identity_required")
        actual = [trace for trace in traces if trace["report_id"] == rid]
        report_checks.append({"report_id": rid, "path": row["path"], "expected_sha256": row["sha256"],
            "state": "read_and_checked" if actual else "not_read",
            "original_verification": "see_source_trace" if actual else "not_verified"})
        if not actual:
            pending.append({"code": "source_report_not_read", "record_id": rid,
                            "reason": "纯数据调用只读取来源描述；报告、原件和当前权限尚未核验。"})
    for row in bindings:
        bid = row.get("binding_id")
        require(isinstance(bid, str) and bool(bid.strip()), "source_binding_id_required")
        if bid in binding_ids:
            issues.append({"code": "source_binding_id_duplicated", "record_id": bid})
        binding_ids.add(bid)
        for key in ("target_type", "target_id", "report_id", "proposition", "version"):
            require(isinstance(row.get(key), str) and bool(row[key].strip()), "source_binding_text_required:" + key)
        citation_ids = row.get("citation_ids")
        require(isinstance(citation_ids, list) and bool(citation_ids)
                and all(isinstance(cid, str) and cid.strip() for cid in citation_ids)
                and len(citation_ids) == len(set(citation_ids)), "source_citation_ids_required")
        problems = []
        if row["report_id"] not in report_ids:
            problems.append("source_report_missing")
        if standard_sources.binding_target(payload, row["target_type"], row["target_id"]) is None:
            problems.append("source_target_missing_or_ambiguous")
        if row["version"] != payload.get("version"):
            problems.append("source_target_version_mismatch")
        for code in problems:
            issues.append({"code": code, "record_id": bid, "target_id": row["target_id"]})
        actual = next((trace for trace in traces if trace["binding_id"] == bid), None)
        binding_checks.append({"binding_id": bid, "target_type": row["target_type"],
            "target_id": row["target_id"], "report_id": row["report_id"],
            "state": actual["state"] if actual else "not_verified", "problems": problems,
            "proposition_support": "not_verified", "version": row["version"]})
    return report_checks, binding_checks


def _range_matches(value, text):
    if not isinstance(value, dict):
        return False
    start, end, quote = value.get("start"), value.get("end"), value.get("quote")
    return (type(start) is int and type(end) is int and 0 <= start < end <= len(text)
            and isinstance(quote, str) and text[start:end] == quote)


def _review_records(payload, checks, actual_texts, rules_hash, pending):
    """保留调用者审阅及其失效原因，不把具名字段当成身份认证或签名。"""
    rows, result = _records(payload, "limitation_reviews"), []
    dimensions = {"object_action", "condition_direction", "quantity_unit", "exception", "strength",
                  "verification_link", "term_usage", "term_consistency"}
    reviewer_types = {"machine_deterministic", "author_engineering_review", "model_self_review",
                      "human_professional", "independent_professional", "professional_review"}
    seen = set()
    for index, row in enumerate(rows, 1):
        rid = row.get("id", row.get("review_id", "limitation-review-" + str(index)))
        require(isinstance(rid, str) and bool(rid.strip()), "limitation_review_id_required")
        target = row.get("target_id", row.get("target"))
        kind = row.get("target_type", "clause")
        if isinstance(target, dict):
            kind = target.get("type", target.get("target_type", kind))
            target = target.get("id", target.get("target_id"))
        dimension = row.get("limitation_type")
        require(target is None or isinstance(target, str), "limitation_review_target_required")
        require(kind is None or isinstance(kind, str), "limitation_review_target_type_required")
        require(dimension is None or isinstance(dimension, str), "limitation_review_dimension_required")
        require(row.get("reviewer_type") is None or isinstance(row["reviewer_type"], str),
                "limitation_review_reviewer_type_required")
        require(row.get("judgment") is None or isinstance(row["judgment"], str),
                "limitation_review_judgment_required")
        problems, missing, stale = [], [], []
        if rid in seen:
            problems.append("limitation_review_id_duplicated")
        seen.add(rid)
        clauses = [clause for clause in payload.get("clauses", []) if clause.get("id") == target]
        if kind != "clause" or len(clauses) != 1:
            problems.append("limitation_review_target_unresolved")
        if dimension not in dimensions:
            problems.append("limitation_review_dimension_unsupported")
        required = ("source_range", "actual_range", "source_sha256", "actual_sha256", "judgment",
                    "reason", "reviewer_type", "evidence", "rules_hash", "dependency_hash")
        missing.extend(key for key in required if row.get(key) is None or row.get(key) == "" or row.get(key) == [])
        if row.get("reviewer_type") not in reviewer_types:
            missing.append("reviewer_type")
        if row.get("reviewer_type") not in {"machine_deterministic", None} and not row.get("reviewer_id"):
            missing.append("reviewer_id")
        if row.get("judgment") not in {"supports", "conflicts", "unknown", "not_applicable"}:
            missing.append("judgment")
        if not isinstance(row.get("reason"), str) or not row.get("reason", "").strip():
            missing.append("reason")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, (str, dict)) and item for item in evidence):
            missing.append("evidence")
        for key in ("source_sha256", "actual_sha256", "rules_hash", "dependency_hash"):
            if not isinstance(row.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                missing.append(key)
        if missing:
            problems.append("limitation_review_incomplete")
        binding_id = row.get("binding_id")
        matches = [check for check in checks if kind == "clause" and check["target_type"] == kind
                   and check["target_id"] == target and check["limitation_type"] == dimension
                   and check.get("binding_id") == binding_id]
        current = matches[0] if matches else None
        actual = (actual_texts or {}).get(target) if isinstance(target, str) else None
        if current and not missing:
            for key in ("dependency_hash", "source_sha256", "actual_sha256"):
                if row[key] != current[key]:
                    stale.append(key)
            if row["rules_hash"] != rules_hash:
                stale.append("rules_hash")
            if actual is None:
                problems.append("limitation_review_actual_text_not_verified")
            elif not _range_matches(row["actual_range"], actual):
                stale.append("actual_range")
            source = ("".join(part["quote"] for part in current["source_range"].get("segments", []))
                      if binding_id else clauses[0]["text"] if len(clauses) == 1 else "")
            if not _range_matches(row["source_range"], source):
                stale.append("source_range")
            if binding_id and row["source_range"].get("citation_ids") != current["source_range"].get("citation_ids"):
                stale.append("citation_ids")
            if stale:
                problems.append("limitation_review_range_stale" if any(key.endswith("range") for key in stale)
                                else "limitation_review_stale")
        elif not current:
            problems.append("limitation_review_current_evidence_unavailable")
        problems = list(dict.fromkeys(problems))
        status = "stale" if stale else "needs_review" if problems else "bound_record_unverified"
        result.append({"review_id": rid, "target_type": kind, "target_id": target,
            "limitation_type": dimension, "status": status, "problems": problems,
            "missing_fields": sorted(set(missing)), "stale_fields": stale,
            "record_sha256": digest(row), "reviewer_identity": "not_authenticated",
            "declared_judgment": row.get("judgment"), "professional_approval": "not_inferred"})
        for code in problems:
            pending.append({"code": code, "record_id": rid, "target_type": kind,
                "target_id": target, "limitation_type": dimension,
                "missing_fields": sorted(set(missing)), "stale_fields": stale,
                "reason": "调用者逐限制记录未完成当前目标、原文范围、实际文字、规则及身份/证据核对。"})
    return result


def _review_emitters(base, text, candidate, rules, issues, pending, checks, *,
                     actual_text=None, field_start=0):
    """字段比较的范围仍指向完整书签；条款沿用零偏移原文范围。"""
    full_text = candidate if actual_text is None else actual_text

    def actual_range(quote=None):
        local = _find_span(candidate, quote) if quote is not None else _span(candidate)
        return _span(full_text, field_start + local["start"], field_start + local["end"])

    def add_pending(code, reason, *, limitation_type=None, source_text=text, citation=None):
        row = {**base, "code": code, "reason": reason, "actual_range": actual_range(),
               "source_range": _source_location(source_text, citation)}
        if limitation_type:
            row["limitation_type"] = limitation_type
            row["rule_id"] = rules.get(limitation_type, rules["term_consistency"])
        if citation:
            row["binding_id"] = citation["binding_id"]
        pending.append(row)

    def record(kind, judgment, source_value, actual_value, reason, *, source_text=text,
               source_quote=None, actual_quote=None, citation=None, code=None):
        source_range = (_find_span(source_text, source_quote) if source_quote is not None
                        else _source_location(source_text, citation))
        if citation:
            source_range.update(citation_ids=citation["citation_ids"],
                                segments=_source_location(source_text, citation)["segments"])
        row = {**base, "limitation_type": kind, "rule_id": rules[kind],
               "source_sha256": _sha(source_text), "source_range": source_range,
               "actual_range": actual_range(actual_quote), "source_value": source_value,
               "actual_value": actual_value, "judgment": judgment, "reason": reason}
        if citation:
            row.update(binding_id=citation["binding_id"], report_id=citation["report_id"],
                       report_sha256=citation["report_sha256"], original_sha256=citation["original_sha256"])
        checks.append(row)
        if judgment == "conflicts":
            issues.append({**row, "code": code or "review_" + kind + "_conflict"})
        elif judgment == "unknown":
            add_pending(code or "review_" + kind + "_needs_review", reason,
                        limitation_type=kind, source_text=source_text, citation=citation)
        return row

    return record, add_pending


def _compare(source_text, candidate, grammar, clause, record, add_pending, checks, *,
             citation=None, structured=False):
    source_text = _text(source_text)
    source_unsupported = _unsupported(source_text, grammar)
    actual_unsupported = _unsupported(candidate, grammar)
    unclear = bool(source_unsupported or actual_unsupported)
    source_condition, actual_condition = _condition(source_text, grammar), _condition(candidate, grammar)
    if structured and source_condition and clause.get("conditions"):
        declared_conditions = clause["conditions"]
        require(isinstance(declared_conditions, list)
                and all(isinstance(value, str) and value for value in declared_conditions),
                "review_conditions_required")
        if declared_conditions != [source_condition["condition"]]:
            add_pending("review_condition_declaration_needs_review",
                "结构条件与可定位条件句不一致；未把结构摘要作为最终文字的语义证明。",
                limitation_type="condition_direction", source_text=source_text, citation=citation)
    if source_condition or actual_condition:
        if source_condition and actual_condition:
            same = (source_condition["condition"] == actual_condition["condition"]
                    and source_condition["action"] == actual_condition["action"])
            judgment = ("supports" if same and source_condition["direction"] == actual_condition["direction"]
                        else "conflicts" if same else "unknown")
            record("condition_direction", judgment, source_condition, actual_condition,
                   "单条件、相同对象动作的必要/充分方向比较。" if same else "条件或动作不同，超出方向核对子集。",
                   source_text=source_text, citation=citation)
        else:
            record("condition_direction", "unknown", source_condition, actual_condition,
                   "一侧没有可完整解析的单条件句，不能推断其必要/充分关系。",
                   source_text=source_text, citation=citation)
    elif re.search(r"(?:仅在|只有|如果|若|则|当|时|条件)", source_text + candidate) or (structured and clause.get("conditions")):
        record("condition_direction", "unknown", clause.get("conditions", []) if structured else source_text,
               candidate, "嵌套、指代或未解析条件保持待审。", source_text=source_text, citation=citation)
    else:
        record("condition_direction", "not_applicable", [], [], "支持子集未出现条件句。",
               source_text=source_text, citation=citation)

    expected = _exceptions(source_text)
    actual_exceptions = _exceptions(candidate)
    declared = clause.get("exceptions", []) if structured else []
    if declared:
        expected = []
        for exception in declared:
            _text(exception)
            expected.append({"value": exception, "start": 0, "end": len(source_text)})
    if unclear and (expected or actual_exceptions or "除外" in source_text + candidate):
        record("exception", "unknown", [r["value"] for r in expected],
               [r["value"] for r in actual_exceptions], "复杂或解释性语境不由字面例外比较决定。",
               source_text=source_text, citation=citation)
    elif expected or actual_exceptions:
        same = [r["value"] for r in expected] == [r["value"] for r in actual_exceptions]
        comparable = (len(expected) <= 1 and len(actual_exceptions) <= 1
                      and (_simple_clause(source_text, grammar) or source_condition is not None)
                      and (_simple_clause(candidate, grammar) or actual_condition is not None))
        if comparable:
            # 已知一个显式例外的遗漏/改变可定位，不把任何缺词都当语义错误。
            value = expected[0]["value"] if len(expected) == 1 else []
            record("exception", "supports" if same else "conflicts", value,
                   actual_exceptions[0]["value"] if len(actual_exceptions) == 1 else [],
                   "显式例外逐字核对；不推断默示例外。", source_text=source_text,
                   source_quote=value if isinstance(value, str) else None, citation=citation)
        else:
            record("exception", "unknown", [r["value"] for r in expected],
                   [r["value"] for r in actual_exceptions], "多个例外或主体不明，需要上下文复核。",
                   source_text=source_text, citation=citation)
    else:
        record("exception", "not_applicable", [], [], "支持子集未出现显式例外。",
               source_text=source_text, citation=citation)

    expected_quantities = _quantities(source_text, grammar)
    if structured and clause.get("quantities"):
        expected_quantities = [{"value": str(row["value"]), "unit": row["unit"],
                                "quote": str(row["value"]) + " " + row["unit"]}
                               for row in clause["quantities"]]
    got_quantities = _quantities(candidate, grammar)
    if expected_quantities or got_quantities:
        simple = (not unclear and len(expected_quantities) == len(got_quantities) == 1
                  and expected_quantities[0]["unit"] in grammar["units"]
                  and _quantity_context(source_text, grammar) == _quantity_context(candidate, grammar))
        if simple:
            before, after = expected_quantities[0], got_quantities[0]
            try:
                left, right = Decimal(before["value"]), Decimal(after["value"])
            except InvalidOperation:
                require(False, "review_numeric_value_required")
            require(left.is_finite() and right.is_finite(), "review_numeric_value_required")
            same_number = left == right
            same_unit = before["unit"] == after["unit"]
            record("quantity_unit", "supports" if same_number and same_unit else "conflicts",
                   {k: before[k] for k in ("value", "unit")}, {k: after[k] for k in ("value", "unit")},
                   "只比较字面数值和单位，不作单位换算或试验充分性判断。",
                   source_text=source_text, source_quote=before["quote"], actual_quote=after["quote"],
                   citation=citation, code="review_quantity_conflict" if not same_number else "review_unit_conflict")
        else:
            record("quantity_unit", "unknown", expected_quantities, got_quantities,
                   "量值未能唯一对应或表达超出支持子集；不能以数量相同视为一致。",
                   source_text=source_text, citation=citation)
    elif re.search(r"\d|±|≤|≥", source_text + candidate):
        record("quantity_unit", "unknown", [], [], "存在未解析数字或单位，保持待审。",
               source_text=source_text, citation=citation)
    else:
        record("quantity_unit", "not_applicable", [], [], "支持子集未出现数值单位表达。",
               source_text=source_text, citation=citation)

    source_modals, got_modals = _modals(source_text, grammar), _modals(candidate, grammar)
    strength = clause.get("strength") if structured else None
    expected_strength = strength if strength is not None else (source_modals[0]["strength"] if len(source_modals) == 1 else None)
    body_simple = ((_simple_clause(source_text, grammar) or source_condition is not None)
                   and (_simple_clause(candidate, grammar) or actual_condition is not None))
    if unclear or len(source_modals) > 1 or len(got_modals) > 1 or not body_simple:
        record("strength", "unknown", source_modals, got_modals,
               "引用、限定否定、说明或多个模态词须连同上下文人工复核。",
               source_text=source_text, citation=citation)
    elif expected_strength == "statement" and not got_modals:
        record("strength", "supports", source_modals, got_modals,
               "描述性文本未出现独立强度词；未将完整词中的单字当模态词。",
               source_text=source_text, citation=citation)
    elif len(got_modals) == 1 and expected_strength:
        same = got_modals[0]["strength"] == expected_strength
        if len(source_modals) == 1:
            same = same and _polarity(source_modals[0]) == _polarity(got_modals[0])
        record("strength", "supports" if same else "conflicts", source_modals,
               got_modals, "独立强度词和显式强度声明/固定原文比较。",
               source_text=source_text, citation=citation)
    elif expected_strength and expected_strength != "statement" and not got_modals:
        record("strength", "unknown", expected_strength, [], "没有可定位独立强度词，不能确定为要求或许可。",
               source_text=source_text, citation=citation)
    else:
        record("strength", "not_applicable", source_modals, got_modals, "未出现可比较强度表达。",
               source_text=source_text, citation=citation)

    if source_text == candidate and body_simple and not unclear:
        record("term_consistency", "supports", source_text, candidate,
               "相同字面对象/动作文本；不推断文字之外的技术事实。", source_text=source_text, citation=citation)
        checks[-1]["limitation_type"] = "object_action"
    else:
        record("term_consistency", "unknown", source_text, candidate,
               "文字差异或复杂句不能由字面匹配证明对象/动作相同。", source_text=source_text, citation=citation)
        checks[-1]["limitation_type"] = "object_action"


def _actual_blocks(payload, value):
    require(value is None or isinstance(value, dict) and len(value) <= MAX_RECORDS,
            "actual_blocks_map_required")
    result = {}
    for bid, rows in (value or {}).items():
        require(isinstance(bid, str) and bool(bid.strip()), "actual_block_binding_id_required")
        bindings = [row for row in payload.get("source_bindings", []) if row.get("binding_id") == bid]
        require(len(bindings) == 1 and bindings[0].get("target_type") != "clause",
                "actual_block_binding_unresolved")
        binding = bindings[0]
        require(isinstance(rows, list) and len(rows) <= MAX_RECORDS, "actual_blocks_list_required")
        result[bid] = []
        for row in rows:
            require(isinstance(row, dict), "actual_block_object_required")
            for key in ("target_type", "target_id", "document_role", "bookmark"):
                require(isinstance(row.get(key), str) and bool(row[key].strip()) and len(row[key]) <= MAX_TEXT,
                        "actual_block_text_required:" + key)
            require(row["target_type"] == binding["target_type"] and row["target_id"] == binding["target_id"],
                    "actual_block_binding_identity_mismatch")
            text = _text(row.get("text"))
            start, end = row.get("start"), row.get("end")
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(text),
                    "actual_block_range_required")
            # 自报verified/status等字段既不参与范围核验，也不作为来源核验凭据。
            result[bid].append({key: row[key] for key in
                ("target_type", "target_id", "document_role", "bookmark", "text", "start", "end")})
    return result


def _nonclause_fields(kind, target):
    if target is None:
        return []
    if kind == "comment":
        return [("comment.text", target["comment"].get("text"))]
    if kind == "comment_reason":
        return [("comment_outcomes/" + str(index) + "/reason", row.get("reason"))
                for index, row in enumerate(target["outcomes"])]
    if kind in {"verification", "verification_basis"}:
        row = target["verification"]
        key = "reason" if kind == "verification_basis" and "reason" in row else "method"
        return [("verification." + key, row.get(key))]
    if kind in {"compilation_note", "note_section"}:
        return [("compilation_note.body", target.get("body"))]
    return []


def _review_nonclauses(payload, blocks, traces, rules_hash, grammar, rules, issues, pending, checks):
    results = []
    for binding in _records(payload, "source_bindings"):
        kind, identity, bid = binding["target_type"], binding["target_id"], binding["binding_id"]
        if kind == "clause":
            continue
        target = standard_sources.binding_target(payload, kind, identity)
        evidence = next((row for row in traces if row["binding_id"] == bid
                         and row["target_type"] == kind and row["target_id"] == identity), None)
        reports = [row for row in payload.get("source_reports", []) if row["report_id"] == binding["report_id"]]
        locations = copy.deepcopy(blocks.get(bid, []))
        dependency = digest({"binding": binding, "target": target, "reports": reports,
            "verified_source": evidence, "actual_blocks": locations, "rules_hash": rules_hash,
            "version": payload.get("version")})
        base = {"binding_id": bid, "target_type": kind, "target_id": identity, "record_id": identity,
            "target_hash": digest(target), "dependency_hash": dependency, "rules_hash": rules_hash,
            "reviewer_type": "machine_deterministic", "evidence": [], "affected_verification_ids": []}
        if evidence:
            base.update(report_id=evidence["report_id"], report_sha256=evidence["report_sha256"],
                        original_sha256=evidence["original_sha256"],
                        source_dependency_hash=evidence["dependency_hash"])
        start_issues, start_pending, start_checks = len(issues), len(pending), len(checks)
        fields = _nonclause_fields(kind, target)
        expected = [(path, value) for path, value in fields
                    if isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT]
        missing_fields = [path for path, value in fields if (path, value) not in expected]
        if not fields or missing_fields:
            pending.append({**base, "code": "review_nonclause_field_unavailable",
                "field_paths": missing_fields, "actual_evidence": "not_provided",
                "reason": "业务字段缺失、非纯文本或目标类型尚未支持；不能以其他字段代替。"})
        # 同一目标的不同业务记录可有相同字面字段，仍按各实际书签分别比较。
        covered, valid, seen_locations = set(), [], set()
        for location in locations:
            text, start, end = location["text"], location["start"], location["end"]
            candidate = text[start:end]
            matches = [path for path, value in expected if value == candidate]
            location.update(text_sha256=_sha(text), field_sha256=_sha(candidate), field_paths=matches)
            key = (location["document_role"], location["bookmark"], start, end)
            if key in seen_locations:
                code = "actual_final_block_duplicated"
            elif not matches:
                code = "actual_final_block_field_unresolved"
            elif text.find(candidate) != start or text.find(candidate, start + 1) != -1:
                code = "actual_final_field_ambiguous"
            else:
                code = None
            seen_locations.add(key)
            location["field_state"] = "unique_literal_span" if code is None else "needs_review"
            if code:
                pending.append({**base, "code": code, "actual_evidence": "not_provided",
                    "actual_locations": [copy.deepcopy(location)], "actual_range": _span(text, start, end),
                    "reason": "实际书签范围未唯一对应当前绑定的一个业务字段，不能作为字面支持证据。"})
                continue
            covered.add(next((path for path in matches if path not in covered), matches[0]))
            valid.append(location)
        if not locations:
            pending.append({**base, "code": "actual_final_block_not_verified" if blocks is None
                            else "actual_final_block_missing", "actual_evidence": "not_provided",
                "reason": "没有消费者回读的实际最终书签字段，输入文字和自报核验标记不能替代。"})
        for path, _ in expected:
            if path not in covered:
                pending.append({**base, "code": "actual_final_field_missing", "field_path": path,
                    "actual_evidence": "not_provided", "reason": "本绑定的一个最终业务字段缺少唯一实际书签范围。"})
        usable = evidence and evidence["state"] == "verified" and evidence["coverage"] == "complete"
        if not usable:
            pending.append({**base, "code": "source_evidence_not_verified",
                "actual_evidence": "actual_final_bookmark_spans" if valid else "not_provided",
                "reason": "没有当前实际报告与完整原件引文核验；不能进行来源字面支持比较。"})
        source_text = ("".join(part["quote"] for row in evidence["citations"]
                               for part in row.get("segments", [row])) if evidence else "")
        pending.append({**base, "code": "source_proposition_applicability_needs_review",
            "actual_evidence": "actual_final_bookmark_spans" if valid else "not_provided",
            "actual_locations": copy.deepcopy(locations),
            "source_range": _source_location(source_text, evidence) if evidence else
                            {"citation_ids": binding["citation_ids"]},
            "reason": "引文及最终字段可定位不证明来源命题或版次适用；需具名专业复核。"})
        if usable:
            for location in valid:
                candidate = location["text"][location["start"]:location["end"]]
                actual_location = {key: value for key, value in location.items() if key != "text"}
                actual_base = {**base, "actual_evidence": "actual_final_bookmark_spans",
                    "actual_sha256": location["text_sha256"], "actual_location": actual_location}
                record, add_pending = _review_emitters(actual_base, source_text, candidate,
                    rules, issues, pending, checks, actual_text=location["text"], field_start=location["start"])
                _compare(source_text, candidate, grammar, {}, record, add_pending, checks, citation=evidence)
        new_checks = checks[start_checks:]
        incomplete = (not fields or bool(missing_fields) or len(covered) != len(expected)
                      or len(valid) != len(locations))
        finite_status = ("not_performed" if not new_checks else
                         "conflicts" if any(row["judgment"] == "conflicts" for row in new_checks) else
                         "unknown" if incomplete or any(row["judgment"] == "unknown" for row in new_checks) else
                         "checked_finite_subset")
        results.append({**base, "actual_locations": locations,
            "actual_evidence": "actual_final_bookmark_spans" if valid else "not_provided",
            "status": "needs_review", "finite_check_status": finite_status,
            "source_state": evidence["state"] if evidence else "not_verified",
            "proposition_support": "not_verified", "professional_review": "not_performed",
            "actual_blocks_checked": len(valid), "checks": len(new_checks),
            "issues": len(issues) - start_issues, "pending_reviews": len(pending) - start_pending})
    return results


def assess(payload: dict, *, actual_texts=None, source_verification=None, actual_blocks=None) -> dict:
    """有限规则评估；supports仅代表所列字面子集，不是专业批准。

    actual_texts为稳定clause_id到最终DOCX原条款text的映射；不得用准备的摘要
    或附加结构核对块替代。未传时actual_file_verification=not_performed。
    actual_blocks按binding_id提供非条款实际书签列表，每项含target_type、target_id、
    document_role、bookmark、完整text及业务字段的唯一start/end半开范围。
    只比较当前绑定字段与完整已核引文；缺失、多义、复杂语境保持待审。
    source_verification须是当前payload的verify_reports返回原对象；任意JSON
    自报verified会保持待审。读取文件、原件和权限由来源层/交付层负责。
    """
    require(isinstance(payload, dict), "standard_review_payload_required")
    canonical_bytes(payload)
    asset, rules_hash = _RULE_ASSET, _RULES_HASH
    grammar = asset["grammar"]
    rules = {row["implementation"]: row["id"] for row in asset["rules"]}
    clauses = _records(payload, "clauses")
    require(actual_texts is None or isinstance(actual_texts, dict), "actual_texts_map_required")
    if actual_texts is not None:
        require(all(isinstance(key, str) and isinstance(value, str) and len(value) <= MAX_TEXT
                    for key, value in actual_texts.items()), "actual_texts_map_required")
    issues, pending, checks, clause_results = [], [], [], []
    trusted = standard_sources.is_current_verification(payload, source_verification)
    traces = source_verification["source_trace"] if trusted else []
    if trusted:
        issues.extend(copy.deepcopy(source_verification["issues"]))
    elif source_verification is not None:
        pending.append({"code": "source_verification_untrusted_or_stale", "record_id": "",
                        "reviewer_type": "machine_deterministic", "reason": "须在当前权限和输入下重新核实际报告与原件。"})
    report_checks, binding_checks = _source_declarations(payload, traces, issues, pending)
    blocks = _actual_blocks(payload, actual_blocks)
    if not clauses:
        pending.append({"code": "review_clauses_not_provided", "record_id": "",
                        "reason": "没有可评估条款，不将空范围视为完成审阅。"})
    verified_count = 0
    seen_ids, seen_numbers = set(), {}
    for clause in clauses:
        identity = clause.get("id")
        require(isinstance(identity, str) and bool(identity), "review_clause_id_required")
        text = _text(clause.get("text", ""))
        if identity in seen_ids:
            issues.append({"code": "review_duplicate_clause_id", "record_id": identity,
                           "rule_id": rules["reference_integrity"]})
        seen_ids.add(identity)
        display = clause.get("display_number", clause.get("number"))
        if display is not None:
            require(isinstance(display, str), "review_display_number_required")
            if display in seen_numbers:
                issues.append({"code": "review_duplicate_display_number", "record_id": identity,
                               "other_id": seen_numbers[display], "rule_id": rules["reference_integrity"]})
            seen_numbers[display] = identity
        actual = actual_texts.get(identity) if actual_texts is not None else None
        if actual is not None:
            verified_count += 1
        candidate = text if actual is None else actual
        bindings, reports = _target_bindings(payload, identity)
        methods = [row for row in payload.get("verification_matrix", []) if row.get("clause_id") == identity]
        related_traces = [row for row in traces if row["target_type"] == "clause" and row["target_id"] == identity]
        dependency = digest({"clause": clause, "actual_text": actual, "version": payload.get("version"),
            "rules_hash": rules_hash, "source_bindings": bindings, "source_reports": reports,
            "verified_sources": related_traces, "verification": methods,
            "terms": payload.get("terms", [])})
        base = {"target_type": "clause", "target_id": identity, "record_id": identity,
                "target_hash": digest(clause), "dependency_hash": dependency,
                "actual_sha256": _sha(candidate), "actual_evidence": "actual_final_text" if actual is not None else "input_text_only",
                "reviewer_type": "machine_deterministic", "evidence": [], "rules_hash": rules_hash,
                "affected_verification_ids": [row.get("id") for row in methods]}
        start_issues, start_pending, start_checks = len(issues), len(pending), len(checks)

        record, add_pending = _review_emitters(base, text, candidate, rules, issues, pending, checks)

        if actual is None:
            add_pending("actual_final_text_not_verified" if actual_texts is None else "actual_final_text_missing",
                        "尚无本条最终文件原文；这里只核输入文字，不能代替实物回查。")
        usable = [row for row in related_traces if row["state"] == "verified" and row["coverage"] == "complete"]
        if not usable:
            add_pending("source_evidence_not_verified", "没有当前实际报告/原件核验及适用命题证据。")
        for citation in related_traces:
            add_pending("source_proposition_applicability_needs_review",
                        "引文可定位不证明命题或版次适用；需具名专业复核。", citation=citation)

        _compare(text, candidate, grammar, clause, record, add_pending, checks, structured=True)
        for citation in usable:
            quotes = [part["quote"] for row in citation["citations"] for part in row.get("segments", [row])]
            _compare("".join(quotes), candidate, grammar, clause, record, add_pending, checks, citation=citation)
        method_ids = clause.get("method_ids", [])
        found = {row.get("id") for row in methods}
        missing = [key for key in method_ids if key not in found]
        if missing:
            record("verification_link", "conflicts", method_ids, sorted(str(x) for x in found),
                   "声明方法未连接当前条款。", code="review_verification_link_missing")
        elif method_ids:
            record("verification_link", "supports", method_ids, sorted(str(x) for x in found),
                   "只核同一条款的方法记录连接；实际试验和技术适用性未由此证明。")
        else:
            record("verification_link", "unknown", [], [], "未提供本条验证联系。")
        clause_results.append({"clause_id": identity, "dependency_hash": dependency,
            "actual_sha256": _sha(candidate) if actual is not None else None,
            "issues": len(issues) - start_issues, "pending_reviews": len(pending) - start_pending,
            "checks": len(checks) - start_checks})

    nonclause_results = _review_nonclauses(payload, blocks, traces, rules_hash, grammar,
                                          rules, issues, pending, checks)
    terms = _records(payload, "terms")
    by_term = {}
    for term in terms:
        word = term.get("term")
        require(isinstance(word, str) and bool(word.strip()), "review_term_text_required")
        by_term.setdefault(word.strip().casefold(), []).append(term)
    for _key, rows in by_term.items():
        word = rows[0]["term"].strip()
        if len({row.get("definition") for row in rows if isinstance(row.get("definition"), str)}) > 1:
            issues.append({"code": "review_term_definition_conflict", "record_id": rows[0].get("id", word),
                           "term": word, "rule_id": rules["term_consistency"]})
        for row in rows:
            row_word = row["term"].strip()
            if not row.get("definition") or not row.get("source"):
                pending.append({"code": "review_term_declaration_incomplete", "record_id": row.get("id", row_word),
                                "term": row_word, "rule_id": rules["term_consistency"],
                                "reason": "术语声明缺定义或依据，不能推断同一性。"})
            aliases = row.get("aliases", [])
            require(isinstance(aliases, list) and all(isinstance(alias, str) and alias for alias in aliases),
                    "review_term_aliases_required")
            for clause in clauses:
                identity = clause["id"]
                actual = (actual_texts or {}).get(identity)
                if actual is None:
                    continue
                used = [alias for alias in aliases if alias in actual]
                if used:
                    base = next(r for r in checks if r["target_id"] == identity)
                    checks.append({**base, "limitation_type": "term_usage", "rule_id": rules["term_consistency"],
                        "source_sha256": digest(row), "source_range": {"term_id": row.get("id"), "term": row_word},
                        "actual_range": _find_span(actual, used[0]), "source_value": row_word,
                        "actual_value": used, "judgment": "supports", "reason": "只使用显式声明的同一术语别名。"})
    for circ in detect_circular_definitions(terms):
        reason = (f"术语定义存在循环引用：{' -> '.join(circ['cycle'])}。"
                  if "cycle" in circ else "存在重复术语定义记录，需核对术语唯一性与定义一致性。")
        issues.append({**circ, "rule_id": rules["term_consistency"], "reason": reason})
    review_records = _review_records(payload, checks, actual_texts, rules_hash, pending)
    pending = list({digest(row): row for row in pending}.values())
    return {"tool": "tools.standard_review", "tool_version": VERSION,
        "status": "blocked" if issues else "needs_review" if pending else "checked_finite_subset",
        "issues": issues, "pending_reviews": pending, "limitation_checks": checks,
        "rules_hash": rules_hash, "clause_reviews": clause_results, "input_hash": digest(payload),
        "nonclause_final_text_checks": nonclause_results,
        "source_report_checks": report_checks, "source_binding_checks": binding_checks,
        "limitation_review_records": review_records,
        "coverage": {"rule_scope": asset["scope"], "rule_ids": [r["id"] for r in asset["rules"]],
            "clauses_declared": len(clauses), "actual_texts_checked": verified_count,
            "actual_file_verification": "actual_texts_supplied_by_consumer" if actual_texts is not None else
                                        "actual_blocks_supplied_by_consumer" if actual_blocks is not None else "not_performed",
            "nonclause_bindings_declared": len(nonclause_results),
            "actual_blocks_checked": sum(row["actual_blocks_checked"] for row in nonclause_results),
            "source_verification": "actual_reports_checked" if trusted else "not_performed",
            "rule_basis": asset["basis"], "source_trace_rows": len(traces),
            "uncovered": ["arbitrary_natural_language", "professional_technical_correctness",
                          "organization_compliance", "real_experiments", "source_authenticity"],
            "scope": "provided_stable_clause_texts_and_verified_literal_sources_only",
            "nonclause_scope": "provided_unique_business_field_spans_and_verified_complete_citations"},
        "automatic_text_changes": "not_performed", "professional_review": "not_performed",
        "organization_compliance": "not_asserted"}


_TRIE_END = object()
_ASCII_WORD = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def _term_references(text, trie):
    """从左向右取最长术语（大小写不敏感），ASCII 标识首尾须对齐单词边界。"""
    folded = text.casefold()
    start = 0
    while start < len(folded):
        node, end = trie, start
        best = None
        if not (start and folded[start] in _ASCII_WORD and folded[start - 1] in _ASCII_WORD):
            while end < len(folded) and folded[end] in node:
                node = node[folded[end]]
                end += 1
                if _TRIE_END in node and not (end < len(folded) and folded[end - 1] in _ASCII_WORD
                                               and folded[end] in _ASCII_WORD):
                    best = end, node[_TRIE_END]
        if best is None:
            start += 1
        else:
            start, owners = best
            yield from owners


def _strong_components(graph):
    """迭代 Tarjan。每条边只访问一次，定义链长度不受 Python 递归限制。"""
    indices, low, active, on_stack = {}, {}, [], set()

    def push(vertex):
        indices[vertex] = low[vertex] = len(indices)
        active.append(vertex)
        on_stack.add(vertex)
        return vertex, iter(graph[vertex])

    for start in graph:
        if start in indices:
            continue
        frames = [push(start)]
        while frames:
            vertex, edges = frames[-1]
            target = next(edges, None)
            if target is not None:
                if target not in indices:
                    frames.append(push(target))
                elif target in on_stack:
                    low[vertex] = min(low[vertex], indices[target])
                continue
            frames.pop()
            if frames:
                parent = frames[-1][0]
                low[parent] = min(low[parent], low[vertex])
            if low[vertex] == indices[vertex]:
                component = []
                while True:
                    member = active.pop()
                    on_stack.remove(member)
                    component.append(member)
                    if member == vertex:
                        break
                yield component


def _representative_cycle(graph, members, start):
    """为强连通分量取一条真实首尾闭合链，并单列全部受影响术语。"""
    allowed = set(members)
    previous = {start: None}
    queue = [start]
    for vertex in queue:
        for target in graph[vertex]:
            if target == start and vertex != start:
                path = [start, vertex]
                while previous[path[-1]] is not None:
                    path.append(previous[path[-1]])
                return list(reversed(path))
            if target in allowed and target not in previous:
                previous[target] = vertex
                queue.append(target)
    raise AssertionError("strong_component_cycle_missing")


def detect_circular_definitions(terms: list[dict]) -> list[dict]:
    """核对同名术语、别名自引用及任意长度的定义循环（大小写不敏感，报告保留原展示名）。"""
    require(isinstance(terms, list), "review_terms_list_required")
    by_key, display_name, trie, findings = {}, {}, {}, []
    for row in terms:
        if not isinstance(row, dict) or not isinstance(row.get("term"), str) or not row["term"].strip():
            continue
        name = row["term"].strip()
        key = name.casefold()
        by_key.setdefault(key, []).append(row)
        display_name.setdefault(key, name)
        spellings = [name]
        for field in ("aliases", "admitted"):
            if field in row:
                raw_values = row[field]
                require(
                    isinstance(raw_values, list)
                    and all(isinstance(alias, str) and bool(alias.strip()) for alias in raw_values),
                    f"review_term_{field}_required",
                )
                spellings.extend(alias.strip() for alias in raw_values)
        for spelling in spellings:
            node = trie
            for char in spelling.casefold():
                node = node.setdefault(char, {})
            node.setdefault(_TRIE_END, {})[key] = None

    graph = {key: {} for key in by_key}
    for key, rows in by_key.items():
        name = display_name[key]
        if len(rows) > 1:
            findings.append({"code": "review_duplicate_term_name", "term": name,
                             "record_id": rows[0].get("id", name),
                             "record_ids": [row.get("id", row["term"].strip()) for row in rows]})
        for row in rows:
            definition = row.get("definition")
            if not isinstance(definition, str):
                continue
            row_name = row["term"].strip()
            refs = dict.fromkeys(_term_references(definition, trie))
            if key in refs:
                findings.append({"code": "review_term_self_circular_definition", "term": row_name,
                                 "record_id": row.get("id", row_name), "cycle": [row_name, row_name]})
            graph[key].update(refs)

    for component in _strong_components(graph):
        if len(component) > 1:
            members_keys = list(reversed(component))
            start_key = members_keys[0]
            start_name = display_name[start_key]
            cycle_keys = _representative_cycle(graph, members_keys, start_key)
            findings.append({"code": "review_term_circular_definition", "term": start_name,
                             "record_id": by_key[start_key][0].get("id", start_name),
                             "terms": [display_name[k] for k in members_keys],
                             "cycle": [display_name[k] for k in cycle_keys]})
    return findings


_DIMENSION_CODES = {
    "1_structure": {"review_clauses_not_provided", "review_duplicate_clause_id",
                    "review_duplicate_display_number", "review_verification_link_missing",
                    "review_verification_link_needs_review", "review_verification_link_conflict",
                    "review_structure_conflict", "review_heading_conflict", "review_outline_conflict",
                    "actual_final_text_not_verified", "actual_final_text_missing",
                    "actual_final_block_duplicated", "actual_final_block_missing", "actual_final_block_not_verified"},
    "2_modality_strength": {"review_strength_conflict", "review_strength_needs_review", "review_modal_conflict",
                            "review_condition_declaration_needs_review", "review_condition_direction_conflict",
                            "review_condition_direction_needs_review", "review_exception_conflict",
                            "review_exception_needs_review", "review_quantity_conflict", "review_unit_conflict",
                            "review_quantity_unit_conflict", "review_quantity_unit_needs_review"},
    "3_cross_references": {"review_reference_conflict", "review_reference_integrity_conflict",
                           "review_reference_integrity_needs_review", "source_report_id_duplicated",
                           "source_report_not_read", "source_binding_id_duplicated", "source_report_missing",
                           "source_target_missing_or_ambiguous", "source_target_version_mismatch",
                           "source_evidence_not_verified", "source_proposition_applicability_needs_review",
                           "source_verification_untrusted_or_stale", "source_binding_review_stale",
                           "source_citation_coverage_partial", "source_citation_missing",
                           "source_extraction_coverage_partial", "source_format_unsupported",
                           "source_identity_mismatch", "source_original_text_not_verified",
                           "source_record_id_duplicated", "source_report_text_changed",
                           "source_report_text_hash_changed", "source_report_tool_unsupported",
                           "source_report_unreadable"},
    "4_terminology_and_circularity": {"review_term_definition_conflict", "review_term_declaration_incomplete",
                                     "review_term_consistency_conflict", "review_term_consistency_needs_review",
                                     "review_term_circular_definition", "review_term_self_circular_definition",
                                     "review_duplicate_term_name"},
    "5_figures_tables_formulas": {"review_figure_conflict", "review_table_conflict", "review_formula_conflict",
                                  "review_omml_conflict"},
}
_DIMENSION_BY_CODE = {code: dimension for dimension, codes in _DIMENSION_CODES.items() for code in codes}
_DIMENSION_BY_RULE = {
    "reference_integrity": "3_cross_references", "term_consistency": "4_terminology_and_circularity",
    "quantity_unit": "2_modality_strength", "condition_direction": "2_modality_strength",
    "exception": "2_modality_strength", "strength": "2_modality_strength", "verification_link": "1_structure",
}
_DIMENSION_BY_RULE_ID = {row["id"]: _DIMENSION_BY_RULE[row["implementation"]] for row in _RULE_ASSET["rules"]}


def project_six_dimension_report(assessment: dict, *, payload: dict | None = None) -> dict:
    """将有限核稿结果投影为六维度结构化审稿报告及“位置—问题—依据—建议—优先级”摘要表。"""
    dims = {
        "1_structure": [],
        "2_modality_strength": [],
        "3_cross_references": [],
        "4_terminology_and_circularity": [],
        "5_figures_tables_formulas": [],
        "6_clarity_and_ambiguity": [],
    }
    priority_rows = []

    def classify(code, row):
        return _DIMENSION_BY_CODE.get(code, _DIMENSION_BY_RULE_ID.get(row.get("rule_id"), "6_clarity_and_ambiguity"))

    seen_circular = set()
    for issue in assessment.get("issues", []):
        code = issue.get("code", "unknown_issue")
        dim = classify(code, issue)
        loc = issue.get("record_id") or issue.get("target_id") or issue.get("clause_id") or "document"
        if code in {"review_term_circular_definition", "review_term_self_circular_definition",
                    "review_duplicate_term_name"}:
            seen_circular.add((loc, code))
        entry = {
            "location": loc,
            "issue": code,
            "basis": issue.get("rule_id") or "internal_finite_rule",
            "suggestion": issue.get("reason") or "对照原文与受影响条款核实并修订后重跑核稿。",
            "priority": "P0_blocking",
            "dimension": dim,
        }
        dims[dim].append(entry)
        priority_rows.append(entry)

    if payload and isinstance(payload.get("terms"), list):
        for circ in detect_circular_definitions(payload["terms"]):
            if (circ["record_id"], circ["code"]) in seen_circular:
                continue
            entry = {
                "location": circ["record_id"],
                "issue": circ["code"],
                "basis": "terminology_non_circularity_check",
                "suggestion": (f"拆分循环定义链：{' -> '.join(circ['cycle'])}" if "cycle" in circ
                               else "核对重复术语的概念、定义与记录标识。"),
                "priority": "P0_blocking",
                "dimension": "4_terminology_and_circularity",
            }
            dims["4_terminology_and_circularity"].append(entry)
            priority_rows.append(entry)

    for pend in assessment.get("pending_reviews", []):
        code = pend.get("code", "pending_review")
        dim = classify(code, pend)
        entry = {
            "location": pend.get("record_id") or pend.get("target_id") or "document",
            "issue": code,
            "basis": pend.get("rule_id") or "pending_semantic_or_source_review",
            "suggestion": pend.get("reason") or "需由具名技术或标准化人员复核。",
            "priority": "P1_needs_review",
            "dimension": dim,
        }
        dims[dim].append(entry)
        priority_rows.append(entry)

    priority_rows.sort(key=lambda r: (0 if r["priority"] == "P0_blocking" else 1, r["dimension"], str(r["location"])))
    return {
        "schema": "dyz-standard-six-dimension-review-v1",
        "source_assessment_hash": assessment.get("input_hash"),
        "status": ("blocked" if assessment.get("status") == "blocked"
                   or any(r["priority"] == "P0_blocking" for r in priority_rows) else "needs_review"),
        "dimensions": dims,
        "dimension_counts": {k: len(v) for k, v in dims.items()},
        "priority_table": priority_rows,
        "professional_review": "not_performed",
        "organization_compliance": "not_asserted",
    }
