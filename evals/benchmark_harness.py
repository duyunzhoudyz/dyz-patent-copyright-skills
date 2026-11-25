"""Phase F1/F2: 未见任务评测集防泄漏与盲测对照框架（仅开发评测仓，不入运行包）。

本模块只使用 Python 标准库，用于：
1. 严格区分开发回归集（dev_regression）与未见任务集（held_out_unseen），拒绝原文或提示词 SHA-256 泄漏；
2. 按案例随机分配盲测标签（System-A / System-B ...）并生成密封解盲映射；
3. 按“硬阻断缺陷”优先于“实用效率指标”的结构化规则评估输出，禁止将未测量费用伪装为 0；
4. 提供离线夹具回放自检（--dry-run），不触发联网或付费模型调用，也不宣称真实市场领先。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
from pathlib import Path
import random
import re
import secrets
import sys
from typing import Any
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import core

SCHEMA_VERSION = "dyz-benchmark-harness/1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_RESPONSE_SHA256 = hashlib.sha256(b"").hexdigest()
_MAX_COUNT_METRIC = 1_000_000_000
_PLACEHOLDER = re.compile(r"(?:unknown|tbd|todo|placeholder|pending|none|null|n/?a|redacted|未提供|待补|未知)(?:[-_ ].*)?", re.I)
_RATING_RESULT_KEYS = (
    "completed", "hard_blocker_codes", "hard_blocker_count", "rework_items", "clarification_rounds", "outcome",
)

VALID_SPLITS = frozenset({"dev_regression", "held_out_unseen"})
VALID_DOMAINS = frozenset({"patent", "software", "standards", "procedure", "rendering", "cross_domain"})
VALID_COST_BASES = frozenset({"measured_api_receipt", "local_hardware_no_api_fee", "not_measured"})
VALID_BENCHMARK_MODES = frozenset({"offline_fixture_replay", "live_blind_human_rated"})

HARD_BLOCKER_CODES = frozenset({
    "unmarked_fabrication",
    "fake_quote",
    "unknown_as_supported",
    "condition_direction_reversal",
    "unauthorized_disclosure",
    "stale_review_reuse",
})


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _clean_text(value: Any, *, allow_multiline: bool = False) -> bool:
    return isinstance(value, str) and bool(value.strip()) and all(
        (allow_multiline and ch in "\n\r\t") or unicodedata.category(ch) not in {"Cc", "Cf", "Cs"}
        for ch in value
    )


def _is_nonneg_int(value: Any) -> bool:
    return type(value) is int and 0 <= value <= _MAX_COUNT_METRIC


def _is_nonneg_number(value: Any) -> bool:
    return (type(value) is int and 0 <= value <= sys.float_info.max
            or type(value) is float and value >= 0 and math.isfinite(value))


def validate_case_pack(
    manifest: dict[str, Any],
    *,
    known_dev_sha256s: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """校验评测案例集结构与未见集防泄漏边界。"""
    errors: list[str] = []
    leakage_hits: list[dict[str, str]] = []
    if not isinstance(manifest, dict):
        return {
            "schema": SCHEMA_VERSION,
            "status": "rejected",
            "errors": ["manifest_object_required"],
            "leakage_hits": [],
            "counts": {"total": 0, "dev_regression": 0, "held_out_unseen": 0},
        }
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        return {
            "schema": SCHEMA_VERSION,
            "status": "rejected",
            "errors": ["cases_list_required"],
            "leakage_hits": [],
            "counts": {"total": 0, "dev_regression": 0, "held_out_unseen": 0},
        }

    seen_ids: set[str] = set()
    dev_hashes = {digest.lower() for digest in known_dev_sha256s if isinstance(digest, str)}
    unseen_cases: list[dict[str, Any]] = []
    split_counts = {"dev_regression": 0, "held_out_unseen": 0}

    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"case_object_required:{idx}")
            continue
        cid = case.get("case_id")
        split = case.get("split")
        domain = case.get("domain")
        prompt_sha = case.get("prompt_sha256")
        source_sha = case.get("source_sha256")
        if not isinstance(cid, str) or not cid.strip():
            errors.append(f"case_id_invalid:{idx}")
            continue
        if cid in seen_ids:
            errors.append(f"case_id_duplicate:{cid}")
        seen_ids.add(cid)
        if not isinstance(split, str) or split not in VALID_SPLITS:
            errors.append(f"split_invalid:{cid}")
            continue
        if not isinstance(domain, str) or domain not in VALID_DOMAINS:
            errors.append(f"domain_invalid:{cid}")
        if not _is_sha256(prompt_sha):
            errors.append(f"prompt_sha256_invalid:{cid}")
        if not _is_sha256(source_sha):
            errors.append(f"source_sha256_invalid:{cid}")

        split_counts[split] += 1
        if split == "dev_regression":
            if _is_sha256(prompt_sha):
                dev_hashes.add(prompt_sha)
            if _is_sha256(source_sha):
                dev_hashes.add(source_sha)
        else:
            unseen_cases.append(case)

    seen_unseen: set[str] = set()
    for case in unseen_cases:
        cid = case["case_id"]
        for field in ("prompt_sha256", "source_sha256"):
            digest = case.get(field)
            if not _is_sha256(digest):
                continue
            if digest in dev_hashes:
                leakage_hits.append({"case_id": cid, "field": field, "sha256": digest})
                errors.append(f"benchmark_unseen_leakage_detected:{cid}:{field}")
            if digest in seen_unseen:
                errors.append(f"benchmark_unseen_hash_duplicate:{cid}:{field}")
            seen_unseen.add(digest)

    return {
        "schema": SCHEMA_VERSION,
        "status": "valid" if not errors else "rejected",
        "errors": errors,
        "leakage_hits": leakage_hits,
        "counts": {
            "total": len(cases),
            "dev_regression": split_counts["dev_regression"],
            "held_out_unseen": split_counts["held_out_unseen"],
        },
        "pack_id": manifest.get("pack_id", ""),
    }


def require_valid_case_pack(
    manifest: dict[str, Any],
    *,
    known_dev_sha256s: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    report = validate_case_pack(manifest, known_dev_sha256s=known_dev_sha256s)
    if report["status"] != "valid":
        raise core.ContractError(report["errors"][0])
    return report


def assign_blind_labels(
    case_ids: list[str],
    system_ids: list[str],
    *,
    seed: str | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """返回单独可公开的盲评单和保密映射。复现实验须使用私有高熵 seed。"""
    core.require(isinstance(case_ids, list) and len(case_ids) > 0, "case_ids_required")
    core.require(isinstance(system_ids, list) and len(system_ids) >= 2, "at_least_two_systems_required")
    core.require(all(isinstance(key, str) and key.strip() for key in (*case_ids, *system_ids)), "blinding_ids_invalid")
    core.require(len(set(case_ids)) == len(case_ids), "duplicate_case_ids")
    core.require(len(set(system_ids)) == len(system_ids), "duplicate_system_ids")
    if seed is None:
        seed = secrets.token_hex(32)
    core.require(isinstance(seed, str) and len(seed.strip()) >= 32, "blinding_seed_required")
    core.require(len(system_ids) <= 26, "too_many_systems_for_letter_labels")

    seed_bytes = seed.encode("utf-8")
    case_ids, system_ids = sorted(case_ids), sorted(system_ids)
    commitment = core.digest(["blinding-commitment-v2", seed, case_ids, system_ids])
    rng = random.Random(int.from_bytes(hmac.new(seed_bytes, b"blinding-prng-v1", "sha256").digest(), "big"))
    labels = [f"System-{chr(ord('A') + i)}" for i in range(len(system_ids))]

    blind_assignments: dict[str, list[dict[str, str]]] = {}
    sealed_reveal_key: dict[str, dict[str, str]] = {}
    for cid in case_ids:
        ordered = list(system_ids)
        rng.shuffle(ordered)
        case_list = []
        reveal = {}
        for label, sys_id in zip(labels, ordered):
            case_list.append({"blind_label": label, "case_id": cid})
            reveal[label] = sys_id
        blind_assignments[cid] = case_list
        sealed_reveal_key[cid] = reveal

    return {
        "schema": SCHEMA_VERSION,
        "blinding_protocol": "per_case_randomized_blind_labels",
        "seed_commitment_sha256": commitment,
        "blind_assignments": blind_assignments,
    }, sealed_reveal_key


def evaluate_submission(submission: dict[str, Any]) -> dict[str, Any]:
    """对单条盲测输出按硬阻断优先原则计分并校验费用口径诚实性。"""
    core.require(isinstance(submission, dict), "submission_object_required")
    core.require_fields(
        submission,
        ("case_id", "blind_label", "completed", "clarification_rounds", "rework_items", "elapsed_seconds", "cost_basis"),
    )
    case_id = submission["case_id"]
    blind_label = submission["blind_label"]
    completed = submission["completed"]
    clarification_rounds = submission["clarification_rounds"]
    rework_items = submission["rework_items"]
    elapsed_seconds = submission["elapsed_seconds"]
    cost_basis = submission["cost_basis"]
    cost_usd = submission.get("cost_usd")
    tokens_in = submission.get("tokens_in")
    tokens_out = submission.get("tokens_out")

    response = submission.get("blind_response")
    response_sha256 = None
    if response is not None:
        core.require(_clean_text(response, allow_multiline=True), "blind_response_text_required")
        response_sha256 = core.sha256_bytes(response.encode("utf-8"))
    core.require(isinstance(case_id, str) and bool(case_id.strip()), "case_id_required")
    core.require(isinstance(blind_label, str) and bool(blind_label.strip()), "blind_label_required")
    core.require(type(completed) is bool, "completed_bool_required")
    core.require(_is_nonneg_int(clarification_rounds), "clarification_rounds_nonneg_int_required")
    core.require(_is_nonneg_int(rework_items), "rework_items_nonneg_int_required")
    core.require(_is_nonneg_number(elapsed_seconds), "elapsed_seconds_nonneg_number_required")
    core.require(isinstance(cost_basis, str) and cost_basis in VALID_COST_BASES, "cost_basis_invalid")

    if cost_basis == "not_measured":
        # 严格禁止把未测量费用记成 0 或 0.0
        core.require(cost_usd is None, "benchmark_unknown_cost_disguised_as_zero")
    elif cost_basis == "measured_api_receipt":
        core.require(_is_nonneg_number(cost_usd), "measured_cost_usd_required")
        core.require(_is_nonneg_int(tokens_in) and _is_nonneg_int(tokens_out), "measured_tokens_required")
    elif cost_basis == "local_hardware_no_api_fee":
        core.require(cost_usd is None or (_is_nonneg_number(cost_usd) and cost_usd == 0), "local_hardware_cost_invalid")

    raw_blockers = submission.get("blockers", [])
    core.require(isinstance(raw_blockers, list), "blockers_list_required")
    validated_blockers = []
    for item in raw_blockers:
        core.require(isinstance(item, dict) and isinstance(item.get("code"), str)
                     and item["code"] in HARD_BLOCKER_CODES, "hard_blocker_code_invalid")
        core.require(isinstance(item.get("detail"), str) and bool(item["detail"].strip()), "hard_blocker_detail_required")
        validated_blockers.append({
            "code": item["code"],
            "detail": item["detail"],
            "source_ref": str(item.get("source_ref", "")),
        })

    blocker_codes = sorted({b["code"] for b in validated_blockers})
    outcome = _submission_outcome(completed, len(validated_blockers))

    return {
        "schema": SCHEMA_VERSION,
        "case_id": case_id,
        "blind_label": blind_label,
        "blind_response_sha256": response_sha256,
        "completed": completed,
        "outcome": outcome,
        "hard_blocker_count": len(validated_blockers),
        "hard_blocker_codes": blocker_codes,
        "blockers": validated_blockers,
        "clarification_rounds": clarification_rounds,
        "rework_items": rework_items,
        "elapsed_seconds": float(elapsed_seconds),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": float(cost_usd) if _is_nonneg_number(cost_usd) else None,
        "cost_basis": cost_basis,
    }


def _submission_outcome(completed: bool, blocker_count: int) -> str:
    if blocker_count:
        return "blocked_by_hard_defect"
    return "completed_no_hard_blockers" if completed else "incomplete"


def _rank_key(ev: dict[str, Any]) -> tuple[int, int, int, int]:
    if ev["hard_blocker_count"]:
        return (-ev["hard_blocker_count"], 0, 0, 0)
    return (0, int(ev["completed"]), -ev["rework_items"], -ev["clarification_rounds"])


def _rating_matches(rating: Any, evaluation: dict) -> bool:
    if (not isinstance(rating, dict) or rating.keys() != {"assessment", *_RATING_RESULT_KEYS}
            or not _clean_text(rating["assessment"], allow_multiline=True)):
        return False
    blockers = evaluation.get("blockers")
    if (type(evaluation.get("completed")) is not bool or not isinstance(blockers, list)
            or not all(isinstance(item, dict) and isinstance(item.get("code"), str)
                       and item["code"] in HARD_BLOCKER_CODES for item in blockers)
            or not all(_is_nonneg_int(evaluation.get(key)) for key in
                       ("hard_blocker_count", "rework_items", "clarification_rounds"))):
        return False
    return (
        evaluation["hard_blocker_count"] == len(blockers)
        and evaluation.get("hard_blocker_codes") == sorted({item["code"] for item in blockers})
        and evaluation.get("outcome") == _submission_outcome(evaluation["completed"], len(blockers))
        and all(type(rating[key]) is type(evaluation[key]) and rating[key] == evaluation[key]
                for key in _RATING_RESULT_KEYS)
    )


def _verify_scorecard(case_id: str, evaluations: dict[str, dict], evidence: dict) -> bool:
    responses = {row["blind_label"]: row.get("blind_response_sha256") for row in evaluations.values()}
    if not all(_is_sha256(value) and value != _EMPTY_RESPONSE_SHA256 for value in responses.values()):
        return False
    response_digest = core.digest(responses)
    payload = evidence.get("scorecard_payload")
    if not isinstance(payload, dict) or evidence.get("blind_response_sha256") != response_digest:
        return False
    if payload.get("case_id") != case_id or payload.get("blind_response_sha256") != response_digest:
        return False
    if any(payload.get(field) != evidence[field] for field in ("reviewer_id", "reviewed_at")):
        return False
    ratings = payload.get("ratings")
    if not isinstance(ratings, dict) or ratings.keys() != responses.keys():
        return False
    if not all(_rating_matches(ratings[row["blind_label"]], row) for row in evaluations.values()):
        return False
    try:
        return core.digest(payload) == evidence["independent_scorecard_ref"]
    except (core.ContractError, RecursionError):
        return False


def aggregate_blind_comparison(
    evaluations: list[dict[str, Any]],
    sealed_reveal_key: dict[str, dict[str, str]],
    *,
    benchmark_mode: str = "offline_fixture_replay",
    human_review_evidence: dict[str, dict[str, Any]] | None = None,
    seed: str | None = None,
    seed_commitment_sha256: str | None = None,
) -> dict[str, Any]:
    """真人聚合使用私有 seed 和盲评前公开的承诺回验解盲映射及原评分单。"""
    core.require(isinstance(benchmark_mode, str) and benchmark_mode in VALID_BENCHMARK_MODES, "benchmark_mode_invalid")
    core.require(isinstance(evaluations, list) and bool(evaluations), "evaluations_required")
    live = benchmark_mode == "live_blind_human_rated"
    report = {
        "schema": SCHEMA_VERSION,
        "benchmark_mode": benchmark_mode,
        "human_blind_review": "reveal_mismatch_not_verified" if live else "not_performed",
        "human_blind_review_evidence": {},
        "live_comparison_valid": False,
        "claims_live_market_leadership": False,
        "system_summaries": {},
        "paired_comparisons": [],
    }
    if live:
        if (not _clean_text(seed) or not _is_sha256(seed_commitment_sha256)
                or not isinstance(sealed_reveal_key, dict) or not sealed_reveal_key):
            return report
        first_mapping = next(iter(sealed_reveal_key.values()))
        if not isinstance(first_mapping, dict) or not all(
            _clean_text(value) for value in (*sealed_reveal_key, *first_mapping.values())
        ):
            return report
        try:
            public_sheet, expected_reveal = assign_blind_labels(list(sealed_reveal_key), list(first_mapping.values()), seed=seed)
        except core.ContractError:
            return report
        if (not hmac.compare_digest(public_sheet["seed_commitment_sha256"], seed_commitment_sha256)
                or expected_reveal != sealed_reveal_key):
            return report
    core.require(isinstance(sealed_reveal_key, dict) and bool(sealed_reveal_key), "sealed_reveal_key_required")
    expected_systems = None
    for cid, labels in sealed_reveal_key.items():
        core.require(_clean_text(cid) and isinstance(labels, dict) and len(labels) >= 2
                     and all(_clean_text(label) and _clean_text(system) for label, system in labels.items()),
                     "reveal_key_invalid")
        systems = set(labels.values())
        core.require(len(systems) == len(labels) and (expected_systems is None or systems == expected_systems),
                     "reveal_key_inconsistent_systems")
        expected_systems = systems

    by_system: dict[str, list[dict[str, Any]]] = {}
    by_case: dict[str, dict[str, dict[str, Any]]] = {}
    for ev in evaluations:
        cid = ev["case_id"]
        label = ev["blind_label"]
        core.require(cid in sealed_reveal_key and label in sealed_reveal_key[cid], "reveal_key_missing_entry")
        sys_id = sealed_reveal_key[cid][label]
        core.require(all(_is_nonneg_int(ev.get(field)) for field in
                         ("clarification_rounds", "rework_items", "hard_blocker_count")), "benchmark_metric_out_of_range")
        core.require(_is_nonneg_number(ev.get("elapsed_seconds")), "benchmark_metric_out_of_range")
        cost_usd = ev.get("cost_usd")
        if cost_usd is not None or ev.get("cost_basis") == "measured_api_receipt":
            core.require(_is_nonneg_number(cost_usd), "benchmark_metric_out_of_range")
        core.require(sys_id not in by_case.setdefault(cid, {}), "duplicate_system_evaluation_for_case")
        by_case[cid][sys_id] = ev
        by_system.setdefault(sys_id, []).append(ev)
    core.require(by_case.keys() == sealed_reveal_key.keys() and all(rows.keys() == expected_systems for rows in by_case.values()),
                 "benchmark_incomplete_case_coverage")
    if live:
        reported_evidence = report["human_blind_review_evidence"]
        core.require(isinstance(human_review_evidence, dict) and human_review_evidence.keys() == by_case.keys(),
                     "human_blind_review_evidence_required")
        scorecards = set()
        seen_blind_responses: dict[str, str] = {}
        verified_cases = 0
        for case_id, evidence in human_review_evidence.items():
            core.require(isinstance(evidence, dict) and all(_clean_text(evidence.get(key))
                         for key in ("reviewer_id", "reviewed_at", "independent_scorecard_ref"))
                         and not _PLACEHOLDER.fullmatch(unicodedata.normalize("NFKC", evidence["reviewer_id"]).strip()),
                         "human_blind_review_evidence_required")
            try:
                core.parse_time(evidence["reviewed_at"])
            except OverflowError:
                raise core.ContractError("invalid_timestamp") from None
            scorecard = evidence["independent_scorecard_ref"].strip()
            core.require(scorecard not in scorecards, "human_blind_review_scorecard_reused")
            scorecards.add(scorecard)
            for row in by_case[case_id].values():
                response_sha256 = row.get("blind_response_sha256")
                if _is_sha256(response_sha256):
                    core.require(seen_blind_responses.setdefault(response_sha256, case_id) == case_id,
                                 "human_blind_review_blind_response_reused")
            verified = _verify_scorecard(case_id, by_case[case_id], evidence)
            verified_cases += verified
            reported_evidence[case_id] = {key: evidence[key] for key in
                                          ("reviewer_id", "reviewed_at", "independent_scorecard_ref")}
            if verified:
                reported_evidence[case_id]["blind_response_sha256"] = evidence["blind_response_sha256"]
        if verified_cases != len(by_case):
            report["human_blind_review"] = "evidence_asserted_not_verified"
            return report
        report["human_blind_review"] = "performed"
        report["live_comparison_valid"] = True

    system_summaries: dict[str, dict[str, Any]] = {}
    for sys_id, rows in sorted(by_system.items()):
        total = len(rows)
        completed = sum(1 for r in rows if r["completed"])
        zero_blocker = sum(1 for r in rows if r["hard_blocker_count"] == 0)
        clean_completed = sum(1 for r in rows if r["outcome"] == "completed_no_hard_blockers")
        blocker_breakdown: dict[str, int] = {}
        for r in rows:
            for b in r["blockers"]:
                blocker_breakdown[b["code"]] = blocker_breakdown.get(b["code"], 0) + 1
        measured_costs = [r["cost_usd"] for r in rows if r["cost_basis"] == "measured_api_receipt" and r["cost_usd"] is not None]
        unmeasured_cases = sum(1 for r in rows if r["cost_basis"] == "not_measured")
        try:
            total_cost = round(math.fsum(measured_costs), 6) if measured_costs else None
        except (ValueError, OverflowError):
            raise core.ContractError("benchmark_cost_total_out_of_range") from None
        try:
            avg_clarification_rounds = round(sum(r["clarification_rounds"] for r in rows) / total, 3)
            avg_rework_items = round(sum(r["rework_items"] for r in rows) / total, 3)
            avg_elapsed_seconds = round(math.fsum(r["elapsed_seconds"] / total for r in rows), 3)
        except OverflowError:
            raise core.ContractError("benchmark_metric_out_of_range") from None
        system_summaries[sys_id] = {
            "total_cases": total,
            "completed_cases": completed,
            "completion_rate": round(completed / total, 4),
            "zero_blocker_cases": zero_blocker,
            "zero_blocker_rate": round(zero_blocker / total, 4),
            "clean_completed_cases": clean_completed,
            "clean_completed_rate": round(clean_completed / total, 4),
            "hard_blocker_total": sum(r["hard_blocker_count"] for r in rows),
            "blocker_breakdown": blocker_breakdown,
            "avg_clarification_rounds": avg_clarification_rounds,
            "avg_rework_items": avg_rework_items,
            "avg_elapsed_seconds": avg_elapsed_seconds,
            "cost_summary": {
                "measured_cases": len(measured_costs),
                "measured_total_usd": total_cost,
                "local_hardware_cases": sum(1 for r in rows if r["cost_basis"] == "local_hardware_no_api_fee"),
                "unmeasured_cases": unmeasured_cases,
            },
        }

    system_ids = sorted(by_system)
    paired_comparisons: list[dict[str, Any]] = []
    for i, sys_a in enumerate(system_ids):
        for sys_b in system_ids[i + 1:]:
            wins_a = wins_b = ties = both_blocked = fewer_blockers_a = fewer_blockers_b = 0
            for case_map in by_case.values():
                first, second = case_map[sys_a], case_map[sys_b]
                ka, kb = _rank_key(first), _rank_key(second)
                if first["hard_blocker_count"] and second["hard_blocker_count"]:
                    both_blocked += 1
                    fewer_blockers_a += ka > kb
                    fewer_blockers_b += kb > ka
                elif ka > kb:
                    wins_a += 1
                elif kb > ka:
                    wins_b += 1
                else:
                    ties += 1
            paired_comparisons.append({
                "system_a": sys_a,
                "system_b": sys_b,
                "shared_cases": len(by_case),
                "both_blocked": both_blocked,
                "both_blocked_fewer_on_a": fewer_blockers_a,
                "both_blocked_fewer_on_b": fewer_blockers_b,
                "wins_a": wins_a,
                "wins_b": wins_b,
                "ties": ties,
            })

    report["system_summaries"] = system_summaries
    report["paired_comparisons"] = paired_comparisons
    return report


def run_fixture_dry_run() -> dict[str, Any]:
    """零联网、零付费模型调用的合成夹具端到端协议自检。"""
    def _h(label: str) -> str:
        return hashlib.sha256(label.encode("utf-8")).hexdigest()

    pack = {
        "pack_id": "synthetic-dry-run-20261124",
        "cases": [
            {"case_id": "DEV-01", "split": "dev_regression", "domain": "patent",
             "prompt_sha256": _h("dev-prompt-1"), "source_sha256": _h("dev-src-1")},
            {"case_id": "UNSEEN-PAT-01", "split": "held_out_unseen", "domain": "patent",
             "prompt_sha256": _h("unseen-pat-prompt-1"), "source_sha256": _h("unseen-pat-src-1")},
            {"case_id": "UNSEEN-STD-01", "split": "held_out_unseen", "domain": "standards",
             "prompt_sha256": _h("unseen-std-prompt-1"), "source_sha256": _h("unseen-std-src-1")},
        ],
    }
    pack_audit = require_valid_case_pack(pack)
    unseen_ids = [c["case_id"] for c in pack["cases"] if c["split"] == "held_out_unseen"]
    blinding, reveal = assign_blind_labels(unseen_ids, ["dyz_candidate", "baseline_generic"],
                                          seed=_h("fixed-synthetic-fixture-seed"))

    def _label_for(cid: str, sys_id: str) -> str:
        for lbl, sid in reveal[cid].items():
            if sid == sys_id:
                return lbl
        raise AssertionError("missing reveal entry")

    submissions = [
        {
            "case_id": "UNSEEN-PAT-01",
            "blind_label": _label_for("UNSEEN-PAT-01", "dyz_candidate"),
            "completed": True,
            "clarification_rounds": 1,
            "rework_items": 0,
            "elapsed_seconds": 12.5,
            "cost_basis": "not_measured",
            "cost_usd": None,
            "blockers": [],
        },
        {
            "case_id": "UNSEEN-PAT-01",
            "blind_label": _label_for("UNSEEN-PAT-01", "baseline_generic"),
            "completed": True,
            "clarification_rounds": 0,
            "rework_items": 2,
            "elapsed_seconds": 8.0,
            "cost_basis": "not_measured",
            "cost_usd": None,
            "blockers": [
                {"code": "condition_direction_reversal", "detail": "synthetic fixture: turned only-if into once", "source_ref": "claim-1"}
            ],
        },
        {
            "case_id": "UNSEEN-STD-01",
            "blind_label": _label_for("UNSEEN-STD-01", "dyz_candidate"),
            "completed": True,
            "clarification_rounds": 1,
            "rework_items": 1,
            "elapsed_seconds": 15.0,
            "cost_basis": "not_measured",
            "cost_usd": None,
            "blockers": [],
        },
        {
            "case_id": "UNSEEN-STD-01",
            "blind_label": _label_for("UNSEEN-STD-01", "baseline_generic"),
            "completed": True,
            "clarification_rounds": 0,
            "rework_items": 1,
            "elapsed_seconds": 9.5,
            "cost_basis": "not_measured",
            "cost_usd": None,
            "blockers": [
                {"code": "unmarked_fabrication", "detail": "synthetic fixture: invented standard clause reference", "source_ref": "clause-4.2"}
            ],
        },
    ]
    evals = [evaluate_submission(sub) for sub in submissions]
    summary = aggregate_blind_comparison(evals, reveal, benchmark_mode="offline_fixture_replay")
    return {
        "schema": SCHEMA_VERSION,
        "status": "dry_run_passed",
        "pack_audit": pack_audit,
        "blinding_protocol": blinding["blinding_protocol"],
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="未见任务与盲测对照协议校验工具（离线、无付费调用）")
    parser.add_argument("--dry-run", action="store_true", help="运行合成夹具协议自检并输出 JSON")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps(run_fixture_dry_run(), ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
