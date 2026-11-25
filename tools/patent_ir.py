"""Phase B1: 专利起草前结构化事实-权项中间表示 (Claim-Fact IR) 预检与骨架投影。

在模型生成大段自然语言正文之前，先对原文引文、条件方向、未知边界隔离、从属项增量限定及
同一方案组合做确定性预检，避免先生成再在终稿门禁反复返工。本模块不替代自然语言审阅、
专利门禁终稿核对或人类专业签核。
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from tools.core import ContractError, canonical_bytes, digest, require, require_fields, sha256_bytes
from tools.fidelity import _check_nesting

VERSION = "1.1"
MAX_IR_BYTES = 2_000_000
FACT_STATES = frozenset({"explicit", "inferred", "unknown", "proposal", "conflicting"})
DIRECTIONS = frozenset({"none", "necessary", "sufficient", "biconditional"})

_CN_TIMING = (r"(?<![同及实定延耗超])时(?![钟间刻序])(?=\s*[，,]|[\u4e00-\u9fff])"
              r"|(?<=[\w)）])(?<![然最随之])后(?=\s*[，,]|立即|即|自动|触发|执行|关闭|开启)"
              r"|在[^,，。；;]{1,80}条件下")
_CN_CUE = re.compile(
    rf"(?P<biconditional>当且仅当|充要条件)|(?P<necessary>只有|仅在|仅当|唯有|除非|若非|必要条件)"
    rf"|(?P<timing>{_CN_TIMING})|(?P<end>才|方可|方才)"
)
_CN_NECESSARY_LINK = re.compile(r"\s*(?:[,，]\s*[^，,。；;]{0,24}?)?(?:才|方可|方才)")
_CN_THEN = re.compile(r"(?<![否规原法准细])则(?=[\w])")
_CN_NECESSARY_END = re.compile(r"(?<!刚)才(?=[\u4e00-\u9fff])|方可|方才")
_SUFFICIENT_CUE = re.compile(
    r"一旦|只要|如果|假如|每当|充分条件|若(?!干|非)(?=[\w\s])|即可"
    r"|\b(?:when|whenever|after|upon|if)\b"
    r"|(?<!at )\bonce\b(?! (?:per|every|each|daily|weekly|monthly|yearly|a (?:second|minute|hour|day|week|month|year))\b)"
    r"|\bsufficient (?:condition|for)\b"
)
_EN_BINDER = re.compile(
    r"(?P<ambiguous>\b(?:not only (?:if|when|after|upon)|not if|provided that|in case|otherwise|until)\b)"
    r"|(?P<biconditional>\b(?:if and only if|iff)\b)"
    r"|(?P<necessary>\b(?:only (?:if|when|after|upon)|necessary condition|unless)\b)"
)
_EN_NON_CONDITION = re.compile(r"\b(?:based upon|even if|if any(?=\s*(?:[,);:\u2013\u2014-]|$)))\b")
_CONDITION_SPLIT = re.compile(r"[。；;！？!?]|\.(?=\s|$)")


def _norm_match(value: str) -> str:
    if not value.isascii():
        value = "".join(ch for ch in value if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", value).strip().casefold()


def _text_direction(text: str) -> str:
    """有限线索检查，不把同一中文条件内的“时、才”另计为充分条件。"""
    directions = set()
    for clause in _CONDITION_SPLIT.split(text):
        clause_directions = {binder.lastgroup for binder in _EN_BINDER.finditer(clause)}
        clause = _EN_NON_CONDITION.sub(" ", _EN_BINDER.sub(" ", clause))
        bound_timing = False
        for cue in _CN_CUE.finditer(clause):
            kind = cue.lastgroup
            if kind in {"necessary", "biconditional"}:
                clause_directions.add(kind)
                bound_timing = True
            else:
                if kind == "timing" and not bound_timing and not _CN_NECESSARY_LINK.match(clause, cue.end()):
                    clause_directions.add("sufficient")
                bound_timing = False
        if _CN_NECESSARY_END.search(clause) and "biconditional" not in clause_directions:
            clause_directions.add("necessary")
        if _CN_THEN.search(clause) or _SUFFICIENT_CUE.search(clause):
            clause_directions.add("sufficient")
        directions.update(clause_directions)
    return next(iter(directions)) if len(directions) == 1 else ("ambiguous" if directions else "none")


def _nonempty_str(value: Any, code: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), code)
    return value.strip()


def _check_quote(citation: dict, documents: dict[str, dict]) -> dict:
    require(isinstance(citation, dict), "ir_citation_required")
    require_fields(citation, ("document_id", "start", "end", "quote"))
    doc_id = citation["document_id"]
    require(isinstance(doc_id, str) and doc_id in documents, "ir_citation_document_unknown")
    text = documents[doc_id]["text"]
    start, end = citation["start"], citation["end"]
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(text),
            "ir_citation_offsets_invalid")
    require(isinstance(citation["quote"], str) and text[start:end] == citation["quote"],
            "ir_citation_quote_mismatch")
    return {
        "document_id": doc_id,
        "version": documents[doc_id]["version"],
        "start": start,
        "end": end,
        "quote": citation["quote"],
    }


def validate_ir(payload: dict) -> dict:
    """确定性预检 Claim-Fact IR；发现未知泄漏、条件反向、无据从属或跨方案组合即阻断。"""
    require(isinstance(payload, dict), "ir_payload_object_required")
    _check_nesting(payload, "ir_payload_nesting_exceeded", max_bytes=MAX_IR_BYTES,
                   budget_code="ir_payload_budget_exceeded")
    require(len(canonical_bytes(payload)) <= MAX_IR_BYTES, "ir_payload_budget_exceeded")
    require_fields(payload, ("project_id", "documents", "facts", "claims"))
    project_id = _nonempty_str(payload["project_id"], "ir_project_id_required")

    raw_docs = payload["documents"]
    require(isinstance(raw_docs, list) and bool(raw_docs), "ir_documents_required")
    documents: dict[str, dict] = {}
    for doc in raw_docs:
        require(isinstance(doc, dict), "ir_document_object_required")
        require_fields(doc, ("id", "version", "role", "text", "sha256"))
        doc_id = _nonempty_str(doc["id"], "ir_document_id_required")
        _nonempty_str(doc["version"], "ir_document_version_required")
        require(isinstance(doc["text"], str) and bool(doc["text"]), "ir_document_text_required")
        require(isinstance(doc["sha256"], str), "ir_document_hash_mismatch")
        require(doc_id not in documents, "ir_document_duplicate")
        require(isinstance(doc["role"], str) and doc["role"] in {"original", "disclosure", "paper", "code", "prior_art"},
                "ir_document_role_invalid")
        require(doc["sha256"] == sha256_bytes(doc["text"].encode("utf-8")), "ir_document_hash_mismatch")
        documents[doc_id] = doc

    raw_unknowns = payload.get("unknown_boundaries", [])
    require(isinstance(raw_unknowns, list), "ir_unknown_boundaries_list_required")
    unknown_boundaries = []
    seen_unknown_ids: set[str] = set()
    for item in raw_unknowns:
        require(isinstance(item, dict), "ir_unknown_boundary_object_required")
        require_fields(item, ("id", "description", "forbidden_terms"))
        uid = _nonempty_str(item["id"], "ir_unknown_id_required")
        require(uid not in seen_unknown_ids, "ir_unknown_boundary_duplicate")
        seen_unknown_ids.add(uid)
        terms = item["forbidden_terms"]
        require(isinstance(terms, list) and bool(terms) and all(isinstance(t, str) and t.strip() for t in terms),
                "ir_unknown_forbidden_terms_required")
        unknown_boundaries.append({
            "id": uid,
            "description": _nonempty_str(item["description"], "ir_unknown_description_required"),
            "forbidden_terms": [t.strip() for t in terms],
            "citation": _check_quote(item["citation"], documents) if item.get("citation") is not None else None,
        })

    raw_facts = payload["facts"]
    require(isinstance(raw_facts, list) and bool(raw_facts), "ir_facts_required")
    facts: dict[str, dict] = {}
    issues: list[dict] = []
    any_scoped_fact = False
    for fact in raw_facts:
        require(isinstance(fact, dict), "ir_fact_object_required")
        require_fields(fact, ("id", "state", "statement", "citation"))
        fid = _nonempty_str(fact["id"], "ir_fact_id_required")
        require(fid not in facts, "ir_fact_duplicate")
        state = fact["state"]
        require(isinstance(state, str) and state in FACT_STATES, "ir_fact_state_invalid")
        direction = fact.get("condition_direction", "none")
        require(isinstance(direction, str) and direction in DIRECTIONS, "ir_fact_direction_invalid")
        raw_scopes = fact.get("embodiment_scopes", [])
        require(
            isinstance(raw_scopes, list) and all(isinstance(s, str) and bool(s.strip()) for s in raw_scopes),
            "ir_fact_embodiment_scopes_invalid",
        )
        scopes = [s.strip() for s in raw_scopes]
        if scopes:
            any_scoped_fact = True
        cited = _check_quote(fact["citation"], documents)
        statement = _nonempty_str(fact["statement"], "ir_fact_statement_required")
        source_direction = _text_direction(_norm_match(cited["quote"]))
        if source_direction != direction:
            issues.append({
                "code": "ir_fact_condition_direction_source_mismatch",
                "severity": "blocking",
                "fact_id": fid,
                "declared_direction": direction,
                "source_direction": source_direction,
            })
        if state == "explicit" and documents[cited["document_id"]]["role"] == "prior_art":
            issues.append({
                "code": "ir_explicit_fact_from_prior_art",
                "severity": "blocking",
                "fact_id": fid,
                "document_id": cited["document_id"],
            })
        if state != "unknown":
            norm_stmt = _norm_match(statement)
            statement_direction = _text_direction(norm_stmt)
            if statement_direction not in {"none", direction}:
                issues.append({
                    "code": "ir_fact_condition_direction_statement_mismatch",
                    "severity": "blocking",
                    "fact_id": fid,
                    "declared_direction": direction,
                    "observed_direction": statement_direction,
                })
            for ub in unknown_boundaries:
                for term in ub["forbidden_terms"]:
                    if _norm_match(term) in norm_stmt:
                        issues.append({
                            "code": "ir_unknown_boundary_leaked_in_fact",
                            "severity": "blocking",
                            "fact_id": fid,
                            "unknown_boundary_id": ub["id"],
                            "matched_term": term,
                        })
        facts[fid] = {
            "id": fid,
            "state": state,
            "statement": statement,
            "condition_direction": direction,
            "embodiment_scopes": scopes,
            "citation": cited,
        }

    raw_claims = payload["claims"]
    require(isinstance(raw_claims, list) and bool(raw_claims), "ir_claims_required")
    normalized_claims: list[dict] = []
    seen_claim_ids: set[int] = set()
    for row in raw_claims:
        require(isinstance(row, dict), "ir_claim_object_required")
        require_fields(row, ("id", "kind", "features"))
        cid = row["id"]
        require(type(cid) is int and cid >= 1, "ir_claim_id_invalid")
        require(cid not in seen_claim_ids, "ir_claim_duplicate")
        seen_claim_ids.add(cid)
        normalized_claims.append(row)
    normalized_claims.sort(key=lambda r: r["id"])

    claims_by_id: dict[int, dict] = {}
    checked_claims: list[dict] = []
    for row in normalized_claims:
        cid = row["id"]
        kind = row["kind"]
        require(isinstance(kind, str) and kind in {"independent", "dependent"}, "ir_claim_kind_invalid")
        parent_id = row.get("parent_claim_id")
        if kind == "independent":
            require(parent_id is None, "ir_independent_cannot_have_parent")
        else:
            require(type(parent_id) is int and parent_id in claims_by_id and parent_id < cid,
                    "ir_dependent_parent_invalid")

        features = row["features"]
        require(isinstance(features, list) and bool(features), "ir_claim_features_required")
        used_fact_ids: list[str] = []
        scope_sets: list[set[str]] = []
        for idx, feat in enumerate(features, start=1):
            require(isinstance(feat, dict), "ir_feature_object_required")
            require_fields(feat, ("text", "fact_ids"))
            ftext = _nonempty_str(feat["text"], "ir_feature_text_required")
            fids = feat["fact_ids"]
            require(isinstance(fids, list) and bool(fids) and all(isinstance(x, str) for x in fids),
                    "ir_feature_fact_ids_required")
            fdir = feat.get("condition_direction", "none")
            require(isinstance(fdir, str) and fdir in DIRECTIONS, "ir_feature_direction_invalid")

            norm_ftext = _norm_match(ftext)
            for ub in unknown_boundaries:
                for term in ub["forbidden_terms"]:
                    if _norm_match(term) in norm_ftext:
                        issues.append({
                            "code": "ir_unknown_boundary_leaked",
                            "severity": "blocking",
                            "claim_id": cid,
                            "feature_index": idx,
                            "unknown_boundary_id": ub["id"],
                            "matched_term": term,
                        })

            # 同特征内多个 fact_ids 必须取实施例作用域交集（绝不能取并集绕过跨实施例检查）
            has_directional_fact = False
            fact_scope_sets: list[set[str]] = []
            for raw_fid in fids:
                fid = raw_fid.strip()
                if fid not in facts:
                    issues.append({
                        "code": "ir_feature_fact_unknown",
                        "severity": "blocking",
                        "claim_id": cid,
                        "feature_index": idx,
                        "fact_id": fid,
                    })
                    continue
                fact = facts[fid]
                used_fact_ids.append(fid)
                if fact["embodiment_scopes"]:
                    fact_scope_sets.append(set(fact["embodiment_scopes"]))
                elif any_scoped_fact:
                    issues.append({
                        "code": "ir_fact_embodiment_scope_missing",
                        "severity": "review",
                        "claim_id": cid,
                        "feature_index": idx,
                        "fact_id": fid,
                    })
                if fact["state"] in {"unknown", "proposal", "conflicting"}:
                    issues.append({
                        "code": f"ir_{fact['state']}_fact_in_claim",
                        "severity": "blocking",
                        "claim_id": cid,
                        "feature_index": idx,
                        "fact_id": fid,
                    })
                elif fact["state"] == "inferred":
                    issues.append({
                        "code": "ir_inferred_fact_requires_review",
                        "severity": "review",
                        "claim_id": cid,
                        "feature_index": idx,
                        "fact_id": fid,
                    })
                has_directional_fact |= fact["condition_direction"] != "none"
                if fact["condition_direction"] != "none" and fact["condition_direction"] != fdir:
                    issues.append({
                        "code": "ir_condition_direction_mismatch",
                        "severity": "blocking",
                        "claim_id": cid,
                        "feature_index": idx,
                        "fact_id": fid,
                        "source_direction": fact["condition_direction"],
                        "claim_direction": fdir,
                    })
            if fdir != "none" and not has_directional_fact:
                issues.append({
                    "code": "ir_condition_direction_mismatch",
                    "severity": "blocking",
                    "claim_id": cid,
                    "feature_index": idx,
                    "source_direction": "none",
                    "claim_direction": fdir,
                })
            observed_direction = _text_direction(norm_ftext)
            if observed_direction != fdir:
                code = {
                    "necessary": "ir_condition_direction_weakened_in_text",
                    "biconditional": "ir_condition_direction_weakened_in_text",
                    "sufficient": "ir_condition_direction_narrowed_in_text",
                    "none": "ir_condition_direction_unsupported_in_text",
                }[fdir]
                issues.append({
                    "code": code,
                    "severity": "blocking",
                    "claim_id": cid,
                    "feature_index": idx,
                    "claim_direction": fdir,
                    "observed_direction": observed_direction,
                })

            if len(fact_scope_sets) > 1 and not set.intersection(*fact_scope_sets):
                issues.append({
                    "code": "ir_cross_embodiment_combination",
                    "severity": "blocking",
                    "claim_id": cid,
                    "feature_index": idx,
                })
            if fact_scope_sets:
                scope_sets.append(set.intersection(*fact_scope_sets))

        inherited_fact_ids: list[str] = []
        inherited_scopes: list[set[str]] = []
        if parent_id is not None:
            parent_record = claims_by_id[parent_id]
            inherited_fact_ids = list(parent_record["all_fact_ids"])
            inherited_scopes = list(parent_record["scope_sets"])
            new_explicit = [
                fid for fid in used_fact_ids
                if fid in facts and facts[fid]["state"] == "explicit" and fid not in set(inherited_fact_ids)
            ]
            if not new_explicit:
                issues.append({
                    "code": "ir_dependent_claim_no_grounded_addition",
                    "severity": "blocking",
                    "claim_id": cid,
                    "parent_claim_id": parent_id,
                })

        combined_scopes = inherited_scopes + scope_sets
        if len(combined_scopes) > 1 and not set.intersection(*combined_scopes):
            issues.append({
                "code": "ir_cross_embodiment_combination",
                "severity": "blocking",
                "claim_id": cid,
            })

        claim_entry = {
            "id": cid,
            "kind": kind,
            "parent_claim_id": parent_id,
            "feature_count": len(features),
            "own_fact_ids": used_fact_ids,
            "all_fact_ids": inherited_fact_ids + used_fact_ids,
            "scope_sets": combined_scopes,
            "features": copy.deepcopy(features),
        }
        claims_by_id[cid] = claim_entry
        checked_claims.append({
            "id": cid,
            "kind": kind,
            "parent_claim_id": parent_id,
            "feature_count": len(features),
            "own_fact_ids": used_fact_ids,
            "all_fact_ids": claim_entry["all_fact_ids"],
            "common_embodiment_scopes": sorted(set.intersection(*combined_scopes)) if combined_scopes else [],
        })

    if sorted(claims_by_id) != list(range(1, len(claims_by_id) + 1)):
        issues.append({"code": "ir_claim_numbering_nonsequential", "severity": "blocking"})

    blocking = [i for i in issues if i.get("severity") == "blocking"]
    status = "blocked" if blocking else ("needs_review" if issues else "checked")
    return {
        "schema": "dyz-patent-claim-fact-ir-v1",
        "version": VERSION,
        "project_id": project_id,
        "status": status,
        "input_hash": digest(payload),
        "document_bindings": [
            {"id": d["id"], "version": d["version"], "role": d["role"], "sha256": d["sha256"]}
            for d in raw_docs
        ],
        "fact_summary": {
            "total": len(facts),
            "by_state": {state: sum(1 for f in facts.values() if f["state"] == state) for state in sorted(FACT_STATES)},
        },
        "unknown_boundaries": unknown_boundaries,
        "claims": checked_claims,
        "issues": issues,
        "blocking_issue_count": len(blocking),
        "ready_for_prose_drafting": not blocking,
        "natural_language_verified": False,
        "professional_review": "not_performed",
    }


def project_draft_skeleton(payload: dict, ir_report: dict | None = None) -> dict:
    """仅对与当前输入精确哈希绑定且预检未阻断的 IR 投影起草骨架与防编造红线清单。"""
    report = validate_ir(payload)
    if ir_report is not None:
        require(isinstance(ir_report, dict) and ir_report.get("schema") == "dyz-patent-claim-fact-ir-v1",
                "ir_report_invalid")
        require(ir_report.get("input_hash") == report["input_hash"], "ir_report_stale_or_mismatched")
        require(ir_report.get("ready_for_prose_drafting") is True, "ir_not_ready_for_drafting")
    require(report["ready_for_prose_drafting"], "ir_not_ready_for_drafting")

    facts = {f["id"].strip(): f for f in payload["facts"]}
    ordered_claims = sorted(payload["claims"], key=lambda c: c["id"])
    heading = "IR 有待核事项" if report["status"] == "needs_review" else "IR 预检通过"
    lines = [
        f"# 内部起草骨架（{heading} · 待专业审阅）",
        f"- 项目：{report['project_id']}",
        f"- IR 绑定哈希：`{report['input_hash']}`",
        "",
        "## 禁止补写的未知边界（严禁写入正文或权项）",
    ]
    if report["unknown_boundaries"]:
        for ub in report["unknown_boundaries"]:
            lines.append(f"- [{ub['id']}] {ub['description']}（禁用补写词：{', '.join(ub['forbidden_terms'])}）")
    else:
        lines.append("- （未声明独立未知边界；原文未记载内容一律不得补写）")

    lines.append("")
    lines.append("## 权项逐特征依据映射")
    trace_map = []
    for claim in ordered_claims:
        prefix = f"独立权利要求 {claim['id']}" if claim["kind"] == "independent" else (
            f"从属权利要求 {claim['id']}（引用权利要求 {claim['parent_claim_id']}）"
        )
        lines.append(f"### {prefix}")
        for idx, feat in enumerate(claim["features"], start=1):
            norm_fids = [fid.strip() for fid in feat["fact_ids"]]
            cites = [facts[fid]["citation"]["quote"] for fid in norm_fids if fid in facts]
            direction = feat.get("condition_direction", "none")
            lines.append(f"- 特征 {claim['id']}.{idx}（方向={direction}）：{feat['text']}")
            lines.append(f"  - 原文依据：{'; '.join(cites)}")
            trace_map.append({
                "claim_id": claim["id"],
                "feature_index": idx,
                "fact_ids": norm_fids,
                "condition_direction": direction,
                "quotes": cites,
            })

    if report["issues"]:
        lines.extend(("", "## 起草前待核事项"))
        lines.extend(f"- `{issue['code']}`：权项 {issue['claim_id']}，特征 {issue['feature_index']}，事实 `{issue['fact_id']}`"
                     for issue in report["issues"])
    markdown = "\n".join(lines) + "\n"
    return {
        "schema": "dyz-patent-draft-skeleton-v1",
        "project_id": report["project_id"],
        "ir_input_hash": report["input_hash"],
        "ir_status": report["status"],
        "review_issues": report["issues"],
        "skeleton_markdown": markdown,
        "skeleton_sha256": sha256_bytes(markdown.encode("utf-8")),
        "trace_map": trace_map,
        "professional_review": "not_performed",
    }
