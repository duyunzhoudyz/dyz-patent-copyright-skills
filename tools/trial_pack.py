"""Phase F3: 专业人员试审包生成器与连续三案升级门控（纯标准库）。

用于把特定“(法域/组织, 领域, 任务)”组合的脱敏产物、原文哈希、历史缺陷及具体法律/技术争议点
装配为可供外部独立专业人员（专利代理师、版权律师、标准委专家）审阅的固定试审包；
并按“同一组合连续 3 个不同案例均由独立具备资质专家实质审阅、零未解决重大/阻断缺陷、且哈希未过期”
的门槛评估是否具备升级建议资格。

本模块永不自动修改 tools/cli.py 中 83 项能力的 synthetic_helper_only 等级，也不替人类专家签核。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
import stat
from typing import Any
import unicodedata

from tools import bundle, core

SCHEMA_VERSION = "dyz-expert-trial-pack/1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_MATERIAL_SHA256 = core.sha256_bytes(b"")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_REVIEW_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
_PLACEHOLDER = re.compile(r"(?:unknown|tbd|todo|placeholder|pending|none|null|n/?a|redacted|未提供|待补|未知)(?:[-_ ].*)?", re.I)
_INVISIBLE_FILLERS = frozenset("\u115f\u1160\u2800\u3164\uffa0")
_SUBSTANTIVE_JUDGMENT = "substantive_legal_or_technical_opinion"
MAX_TRIAL_FILE_BYTES = 16_000_000
MAX_TRIAL_TOTAL_BYTES = 32_000_000
MAX_TRIAL_ARTIFACTS = 128

ALLOWED_EXPERT_ROLES = frozenset({
    "patent_attorney",
    "copyright_counsel",
    "standardization_tc_expert",
})

ALLOWED_VERDICTS = frozenset({
    "approved_with_no_major_defects",
    "revisions_required",
    "rejected",
})

RECOMMENDED_DISPUTE_CATEGORIES = {
    "patent_attorney": (
        "claim_scope_and_support",
        "technical_problem_and_effect",
        "office_action_or_amendment_basis",
    ),
    "copyright_counsel": (
        "authorship_and_rights_chain",
        "source_deposit_and_version_consistency",
        "manual_and_screenshot_traceability",
    ),
    "standardization_tc_expert": (
        "scope_and_normative_strength",
        "clause_verifiability_and_references",
        "comment_disposition_and_ip_handoff",
    ),
}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _clean_text(value: Any, *, allow_multiline: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    has_visible_text = False
    for ch in value:
        category = unicodedata.category(ch)
        if ((ch in _INVISIBLE_FILLERS or category in {"Cc", "Cf", "Cs", "Zl", "Zp"}
             or ch in "\u034f\u17b4\u17b5\u180b\u180c\u180d\u180f"
             or "\ufe00" <= ch <= "\ufe0f" or "\U000e0100" <= ch <= "\U000e01ef")
                and not (allow_multiline and ch in "\n\r\t")):
            return False
        if category[0] not in "CMZ":
            has_visible_text = True
    return has_visible_text


def _opaque_id(value: Any) -> bool:
    return isinstance(value, str) and _OPAQUE_ID.fullmatch(value) is not None


def _question_key(question: str) -> str:
    normalized = unicodedata.normalize("NFKD", question).casefold()
    visible = "".join(ch for ch in normalized if unicodedata.category(ch) not in {"Mn", "Me", "Cf"})
    return " ".join(visible.split())


def _material_fingerprint(hashes) -> str:
    return core.digest(sorted(set(hashes)))


def _redaction_receipt_digest(receipt, evidence_id, case_id, combination_id, text_hashes, artifact_hashes) -> str:
    error = "unredacted_free_text_blocked"
    core.require(isinstance(receipt, dict) and receipt.get("receipt_id") == evidence_id
                 and receipt.get("approved") is True and _opaque_id(receipt.get("redactor_id"))
                 and not _PLACEHOLDER.fullmatch(receipt["redactor_id"])
                 and receipt.get("case_id") == case_id and receipt.get("combination_id") == combination_id
                 and receipt.get("artifact_hashes") == artifact_hashes
                 and receipt.get("field_hashes") == text_hashes, error)
    redacted_at = receipt.get("redacted_at")
    core.require(isinstance(redacted_at, str) and _REVIEW_TIME.fullmatch(redacted_at), error)
    try:
        core.parse_time(redacted_at)
    except (core.ContractError, OverflowError):
        raise core.ContractError(error) from None
    return core.digest({key: receipt[key] for key in
                        ("receipt_id", "approved", "redactor_id", "redacted_at", "case_id", "combination_id",
                         "field_hashes", "artifact_hashes")})


def _registered_pack_matches(pack, record) -> bool:
    if (not isinstance(pack, dict) or pack.get("schema") != SCHEMA_VERSION
            or pack.get("status") != "ready_for_independent_expert_review"
            or not _opaque_id(pack.get("author_id")) or _PLACEHOLDER.fullmatch(pack["author_id"])):
        return False
    if any(pack.get(key) != record.get(key) for key in
           ("pack_sha256", "case_id", "combination_id", "expert_role", "author_id", "material_fingerprint_sha256")):
        return False
    if not _is_sha256(pack.get("redaction_receipt_sha256")) or pack.get("deidentification_confirmed") is not True:
        return False
    if not _is_sha256(pack.get("source_material_sha256")) or pack["source_material_sha256"] == _EMPTY_MATERIAL_SHA256:
        return False
    if "source_material_sha256" in record and record["source_material_sha256"] != pack.get("source_material_sha256"):
        return False
    artifacts = pack.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False
    hashes = {}
    artifact_ids = set()
    for item in artifacts:
        if (not isinstance(item, dict) or not _opaque_id(item.get("id"))
                or item.get("path") != f"artifacts/{item['id']}" or not _is_sha256(item.get("sha256"))
                or item["sha256"] == _EMPTY_MATERIAL_SHA256 or type(item.get("bytes")) is not int or item["bytes"] <= 0):
            return False
        hashes[item["path"]] = item["sha256"]
        artifact_ids.add(item["id"])
    if (len(hashes) != len(artifacts) or hashes != record.get("artifact_hashes")
            or _material_fingerprint(hashes.values()) != pack.get("material_fingerprint_sha256")):
        return False
    questions = pack.get("dispute_questions")
    if not isinstance(questions, list) or not 2 <= len(questions) <= MAX_TRIAL_ARTIFACTS:
        return False
    for question in questions:
        if (not isinstance(question, dict) or not _opaque_id(question.get("id"))
                or not _opaque_id(question.get("category")) or not isinstance(question.get("artifact_ref"), str)
                or question["artifact_ref"] not in artifact_ids or question.get("expected_judgment_type") != _SUBSTANTIVE_JUDGMENT
                or not _clean_text(question.get("question"), allow_multiline=True) or len(question["question"]) > 4000):
            return False
    if (len({question["id"].casefold() for question in questions}) != len(questions)
            or len({_question_key(question["question"]) for question in questions}) != len(questions)):
        return False
    history = pack.get("defect_history")
    if not isinstance(history, list) or len(history) > MAX_TRIAL_ARTIFACTS:
        return False
    defect_ids = set()
    for item in history:
        if (not isinstance(item, dict) or not _opaque_id(item.get("defect_id"))
                or not _clean_text(item.get("summary"), allow_multiline=True) or len(item["summary"]) > 4000):
            return False
        defect_id = item["defect_id"].casefold()
        if defect_id in defect_ids:
            return False
        defect_ids.add(defect_id)
    try:
        return core.digest({key: value for key, value in pack.items() if key != "pack_sha256"}) == pack["pack_sha256"]
    except (core.ContractError, RecursionError):
        return False


def _read_trial_artifact(target: Path, limit: int, seen_files: set[tuple[int, int]]) -> bytes:
    try:
        expected = core.checked_path(target)
        core.require(expected is not None and stat.S_ISREG(expected.st_mode), "trial_artifact_file_required")
        identity = (expected.st_dev, expected.st_ino)
        core.require(identity not in seen_files, "trial_artifact_duplicate")
        core.require(expected.st_nlink == 1, "trial_artifact_link_rejected")
        core.require(expected.st_size > 0, "trial_artifact_empty")
        core.require(expected.st_size <= limit, "trial_artifact_byte_limit")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(target, flags), "rb") as stream:
            actual = os.fstat(stream.fileno())
            core.require(stat.S_ISREG(actual.st_mode) and actual.st_nlink == 1
                         and os.path.samestat(expected, actual) and expected.st_size == actual.st_size
                         and expected.st_mtime_ns == actual.st_mtime_ns, "trial_artifact_changed")
            raw = stream.read(limit + 1)
            final = os.fstat(stream.fileno())
            core.require(len(raw) <= limit, "trial_artifact_byte_limit")
            core.require(final.st_size == len(raw) == actual.st_size and final.st_mtime_ns == actual.st_mtime_ns,
                         "trial_artifact_changed")
        seen_files.add(identity)
        return raw
    except (OSError, bundle.BundleError):
        raise core.ContractError("trial_artifact_path_rejected") from None


def build_expert_trial_pack(
    root: str | Path,
    *,
    combination_id: str,
    case_id: str,
    expert_role: str,
    author_id: str,
    artifacts: list[dict[str, Any]],
    dispute_questions: list[dict[str, Any]],
    defect_history: list[dict[str, Any]] | None = None,
    deidentification_confirmed: bool = False,
    deidentification_evidence: str = "",
    redaction_receipt: dict[str, Any] | None = None,
    source_material_sha256: str | None = None,
) -> dict[str, Any]:
    """构造可登记的逐案试审清单，绑定作者不透明标识。原路径和脱敏回执正文留在调用方。"""
    core.require(_opaque_id(combination_id), "combination_id_required")
    core.require(isinstance(expert_role, str) and expert_role in ALLOWED_EXPERT_ROLES, "expert_role_invalid")
    core.require(_opaque_id(case_id) and _opaque_id(author_id) and not _PLACEHOLDER.fullmatch(author_id),
                 "identifier_not_canonical")
    core.require(_is_sha256(source_material_sha256) and source_material_sha256 != _EMPTY_MATERIAL_SHA256,
                 "source_material_sha256_invalid")
    core.require(deidentification_confirmed is True and _opaque_id(deidentification_evidence)
                 and not _PLACEHOLDER.fullmatch(deidentification_evidence), "trial_pack_deidentification_required")
    core.require(isinstance(artifacts, list) and 0 < len(artifacts) <= MAX_TRIAL_ARTIFACTS, "trial_artifacts_required")
    core.require(isinstance(dispute_questions, list) and 2 <= len(dispute_questions) <= MAX_TRIAL_ARTIFACTS,
                 "specific_dispute_questions_required")
    core.require(defect_history is None or isinstance(defect_history, list) and len(defect_history) <= MAX_TRIAL_ARTIFACTS,
                 "defect_history_invalid")

    try:
        base = bundle._absolute(root)
        root_info = core.checked_path(base)
        core.require(root_info is not None and stat.S_ISDIR(root_info.st_mode), "trial_pack_root_required")
    except (OSError, bundle.BundleError):
        raise core.ContractError("trial_pack_root_required") from None

    bound_artifacts: list[dict[str, Any]] = []
    artifact_ids: set[str] = set()
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    seen_files: set[tuple[int, int]] = set()
    total_bytes = 0
    for item in artifacts:
        core.require(isinstance(item, dict), "trial_artifact_object_required")
        aid = item.get("id")
        rel = item.get("path")
        role = item.get("role")
        core.require(_opaque_id(aid) and aid.casefold() not in seen_ids, "trial_artifact_id_invalid")
        core.require(_clean_text(rel) and _opaque_id(role), "trial_artifact_path_and_role_required")
        parts = rel.replace("\\", "/").split("/")
        core.require(":" not in rel and "\x00" not in rel and all(p not in {"", ".", ".."} for p in parts),
                     "trial_artifact_path_rejected")
        target = base.joinpath(*parts)
        core.require(target not in seen_paths, "trial_artifact_duplicate")
        raw = _read_trial_artifact(target, min(MAX_TRIAL_FILE_BYTES, MAX_TRIAL_TOTAL_BYTES - total_bytes), seen_files)
        total_bytes += len(raw)
        seen_paths.add(target)
        seen_ids.add(aid.casefold())
        digest = core.sha256_bytes(raw)
        declared_sha = item.get("sha256")
        if declared_sha is not None:
            core.require(_is_sha256(declared_sha) and declared_sha == digest, "trial_artifact_sha256_mismatch")
        artifact_ids.add(aid)
        bound_artifacts.append({
            "id": aid,
            "path": f"artifacts/{aid}",
            "role": role,
            "bytes": len(raw),
            "sha256": digest,
        })

    text_hashes: dict[str, str] = {}
    validated_questions: list[dict[str, Any]] = []
    seen_qids: set[str] = set()
    seen_questions: set[str] = set()
    for q in dispute_questions:
        core.require(isinstance(q, dict), "dispute_question_object_required")
        qid = q.get("id")
        category = q.get("category")
        question = q.get("question")
        artifact_ref = q.get("artifact_ref")
        judgment_type = q.get("expected_judgment_type", _SUBSTANTIVE_JUDGMENT)
        core.require(_opaque_id(qid) and qid.casefold() not in seen_qids, "dispute_question_id_invalid")
        core.require(_opaque_id(category) and _clean_text(question, allow_multiline=True) and len(question) <= 4000,
                     "dispute_question_content_required")
        question_key = _question_key(question)
        core.require(question_key not in seen_questions, "duplicate_dispute_question")
        core.require(isinstance(artifact_ref, str) and artifact_ref in artifact_ids, "dispute_question_artifact_ref_unknown")
        # 拒绝仅用 1-5 打分代替具体法律/技术争议点审阅
        core.require(judgment_type == _SUBSTANTIVE_JUDGMENT,
                     "numeric_only_scorecard_rejected")
        seen_qids.add(qid.casefold())
        seen_questions.add(question_key)
        text_hashes[f"dispute_questions.{qid}.question"] = core.digest(question)
        validated_questions.append({
            "id": qid,
            "category": category,
            "artifact_ref": artifact_ref,
            "question": question,
            "expected_judgment_type": judgment_type,
        })

    normalized_history: list[dict[str, Any]] = []
    seen_defect_ids: set[str] = set()
    for rec in defect_history or []:
        core.require(isinstance(rec, dict) and _opaque_id(rec.get("defect_id"))
                     and _clean_text(rec.get("summary"), allow_multiline=True)
                     and len(rec["summary"]) <= 4000, "defect_history_entry_invalid")
        defect_id = rec["defect_id"]
        core.require(defect_id.casefold() not in seen_defect_ids, "defect_history_entry_invalid")
        seen_defect_ids.add(defect_id.casefold())
        text_hashes[f"defect_history.{defect_id}.summary"] = core.digest(rec["summary"])
        severity = rec.get("severity", "unspecified")
        status = rec.get("status", "open")
        core.require(_opaque_id(severity) and _opaque_id(status), "defect_history_entry_invalid")
        normalized_history.append({
            "defect_id": defect_id,
            "severity": severity,
            "summary": rec["summary"],
            "status": status,
        })

    body_for_hash = {
        "schema": SCHEMA_VERSION,
        "combination_id": combination_id,
        "case_id": case_id,
        "expert_role": expert_role,
        "author_id": author_id,
        "deidentification_confirmed": True,
        "redaction_receipt_sha256": _redaction_receipt_digest(
            redaction_receipt, deidentification_evidence, case_id, combination_id, text_hashes,
            {item["path"]: item["sha256"] for item in bound_artifacts},
        ),
        "material_fingerprint_sha256": _material_fingerprint(item["sha256"] for item in bound_artifacts),
        "source_material_sha256": source_material_sha256,
        "artifacts": bound_artifacts,
        "dispute_questions": validated_questions,
        "defect_history": normalized_history,
        "status": "ready_for_independent_expert_review",
        "recommended_dispute_categories": list(RECOMMENDED_DISPUTE_CATEGORIES[expert_role]),
        "review_status": "pending_external_expert",
        "catalog_support_unchanged": "synthetic_helper_only",
        "external_dispatch": "not_performed",
    }
    return {**body_for_hash, "pack_sha256": core.digest(body_for_hash)}


def evaluate_combination_upgrade(
    combination_id: str,
    trial_records: list[dict[str, Any]],
    *,
    current_artifact_hashes: dict[str, str] | dict[str, dict[str, str]] | None = None,
    registered_packs: dict[str, dict[str, Any]] | None = None,
    expected_expert_role: str | None = None,
    min_consecutive: int = 3,
) -> dict[str, Any]:
    """以独立登记的完整试审清单回验逐案记录。登记键可为 case_id 或 pack_sha256。"""
    core.require(_opaque_id(combination_id), "combination_id_required")
    core.require(isinstance(trial_records, list), "trial_records_list_required")
    core.require(type(min_consecutive) is int and min_consecutive >= 3, "min_consecutive_at_least_three_required")

    def normalize(value):
        return value.casefold() if _opaque_id(value) else ""

    def valid_hashes(value):
        return isinstance(value, dict) and bool(value) and all(_clean_text(path) and _is_sha256(digest)
                                                               for path, digest in value.items())

    blocking_reasons = []
    registry = registered_packs if isinstance(registered_packs, dict) else {}
    if not registry:
        blocking_reasons.append("trial_pack_not_verified")
    flat_hashes = valid_hashes(current_artifact_hashes)
    by_case = {}
    if not flat_hashes and isinstance(current_artifact_hashes, dict) and current_artifact_hashes:
        by_case = {normalize(case): hashes for case, hashes in current_artifact_hashes.items()}
        if len(by_case) != len(current_artifact_hashes) or "" in by_case or not all(map(valid_hashes, by_case.values())):
            by_case = {}
    if not flat_hashes and not by_case:
        blocking_reasons.append("current_artifact_hashes_required")
    if not isinstance(expected_expert_role, str) or expected_expert_role not in ALLOWED_EXPERT_ROLES:
        blocking_reasons.append("expected_expert_role_required")

    seen_cases: set[str] = set()
    seen_packs: set[str] = set()
    seen_material_hashes: set[str] = set()
    last_reviewed = None
    record_audits: list[dict[str, Any]] = []
    trailing_start = 0

    for idx, row in enumerate(trial_records):
        reasons = []
        rec = row if isinstance(row, dict) else {}
        if not isinstance(row, dict):
            reasons.append("record_object_required")
        cid = normalize(rec.get("case_id"))
        same_combination = rec.get("combination_id") == combination_id
        if not same_combination:
            reasons.append("combination_id_mismatch")
        if any(rec.get(key) is not None and not _opaque_id(rec[key]) for key in ("case_id", "reviewer_id", "author_id")):
            reasons.append("identifier_not_canonical")
            if same_combination:
                blocking_reasons.append("identifier_not_canonical")
        if not cid:
            reasons.append("case_id_missing")
        elif cid in seen_cases:
            reasons.append(f"duplicate_case_id:{cid}")
            blocking_reasons.append(reasons[-1])
        elif same_combination:
            seen_cases.add(cid)

        if rec.get("expert_role") != expected_expert_role:
            reasons.append("expert_role_mismatch")
            if same_combination:
                blocking_reasons.append("expert_role_mismatch")
        reviewer_id = normalize(rec.get("reviewer_id"))
        author_id = normalize(rec.get("author_id"))
        if (not reviewer_id or not author_id or _PLACEHOLDER.fullmatch(reviewer_id)
                or _PLACEHOLDER.fullmatch(author_id)):
            reasons.append("reviewer_or_author_missing")
        qualification = rec.get("reviewer_qualification_evidence")
        if not _clean_text(qualification) or _PLACEHOLDER.fullmatch(unicodedata.normalize("NFKC", qualification).strip()):
            reasons.append("reviewer_qualification_evidence_missing")
        pack_hash = rec.get("pack_sha256")
        if not _is_sha256(pack_hash):
            reasons.append("pack_sha256_invalid")
        elif pack_hash in seen_packs:
            reasons.append("duplicate_pack_sha256")
            blocking_reasons.append("duplicate_pack_sha256")
        elif same_combination:
            seen_packs.add(pack_hash)

        reviewed_at = rec.get("reviewed_at")
        try:
            core.require(isinstance(reviewed_at, str) and _REVIEW_TIME.fullmatch(reviewed_at), "reviewed_at_invalid")
            stamp = core.parse_time(reviewed_at)
        except (core.ContractError, OverflowError):
            reasons.append("reviewed_at_invalid")
        else:
            if same_combination:
                if last_reviewed is not None and stamp <= last_reviewed:
                    reasons.append("reviewed_at_not_strictly_increasing")
                else:
                    last_reviewed = stamp

        art_hashes = rec.get("artifact_hashes")
        current = current_artifact_hashes if flat_hashes else by_case.get(cid)
        if not valid_hashes(art_hashes):
            reasons.append("artifact_hashes_missing_or_invalid")
        fingerprint = rec.get("material_fingerprint_sha256")
        pack = registry.get(pack_hash) if _is_sha256(pack_hash) else None
        case_pack = registry.get(rec.get("case_id")) if cid else None
        if pack is None:
            pack = case_pack
        if (not _is_sha256(fingerprint) or not valid_hashes(art_hashes)
                or case_pack is not None and case_pack != pack or not _registered_pack_matches(pack, rec)):
            reasons.append("trial_pack_not_verified")
            if same_combination:
                blocking_reasons.append("trial_pack_not_verified")
        elif same_combination:
            if reviewer_id == normalize(pack["author_id"]):
                reasons.append("self_review_forbidden")
            material_hashes = {pack["source_material_sha256"], *art_hashes.values()}
            if not seen_material_hashes.isdisjoint(material_hashes):
                reasons.append("duplicate_underlying_material")
                blocking_reasons.append("duplicate_underlying_material")
            seen_material_hashes.update(material_hashes)
        if current is None:
            reasons.append("current_artifact_hashes_missing_for_case")
        elif valid_hashes(art_hashes):
            if art_hashes.keys() != current.keys():
                reasons.append("artifact_hash_coverage_mismatch")
            for path in art_hashes.keys() & current.keys():
                if art_hashes[path] != current[path]:
                    reasons.append(f"stale_artifact_hash:{path}")

        findings = rec.get("substantive_findings")
        if not isinstance(findings, list) or not findings or not all(_clean_text(x, allow_multiline=True) for x in findings):
            reasons.append("substantive_findings_required")

        blocking = rec.get("unresolved_blocking_defects")
        major = rec.get("unresolved_major_defects")
        if not isinstance(blocking, list) or not isinstance(major, list):
            reasons.append("defect_lists_required")
        else:
            if blocking:
                reasons.append(f"unresolved_blocking_defects:{len(blocking)}")
            if major:
                reasons.append(f"unresolved_major_defects:{len(major)}")

        verdict = rec.get("verdict")
        if not isinstance(verdict, str) or verdict not in ALLOWED_VERDICTS:
            reasons.append("verdict_invalid")
        elif verdict != "approved_with_no_major_defects":
            reasons.append(f"verdict_not_approved:{verdict}")

        if reasons:
            trailing_start = idx + 1
        record_audits.append({"index": idx, "case_id": cid or None, "valid_pass": not reasons, "reasons": sorted(reasons)})

    trailing_consecutive = len(trial_records) - trailing_start
    eligible = trailing_consecutive >= min_consecutive and not blocking_reasons
    historical_record_issues = [audit for audit in record_audits if not audit["valid_pass"]]
    if trailing_consecutive < min_consecutive:
        blocking_reasons.extend(reason for audit in historical_record_issues for reason in audit["reasons"])
        blocking_reasons.append(f"insufficient_consecutive_valid_cases:{trailing_consecutive}/{min_consecutive}")

    return {
        "schema": SCHEMA_VERSION,
        "combination_id": combination_id,
        "evaluated_records": len(trial_records),
        "trailing_consecutive_valid": trailing_consecutive,
        "min_consecutive_required": min_consecutive,
        "eligible_for_upgrade": eligible,
        "recommended_support_level": (
            "professionally_reviewed_limited_combination" if eligible else "synthetic_helper_only"
        ),
        "requires_explicit_maintainer_release_action": True,
        "catalog_mutated": False,
        "blocking_reasons": sorted(set(blocking_reasons)),
        "historical_record_issues": historical_record_issues,
        "record_audits": record_audits,
    }
