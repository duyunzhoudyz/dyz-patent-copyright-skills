"""只读发布范围与候选结构检查；不安装、联网、写Git或认证专业能力。"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
# 从显式源码根导入；不采用当前工作目录或调用者的PYTHONPATH副本。
sys.path.insert(0, str(ROOT))
from tools import __version__  # noqa: E402
from tools import bundle  # noqa: E402
from tools.cli import catalog  # noqa: E402

REQUIRED_FACTS = ("license_holder", "repository_url", "commercial_contact", "security_contact")
FORBIDDEN_PREFIXES = (".references/", "private/", "outputs/", "tmp/", ".breezell/", "evals/workflows/")
COMPARISON_REPORTS = frozenset({
    "竞品对比/README.md",
    "竞品对比/标准/标准技能深度对比与提升方案-20261113.md",
    "竞品对比/标准/标准技能优化后复对比与下一轮提升方案-20261114.md",
})
RELEASE_FILES = frozenset({
    "release.json", "RELEASE.md", "CHANGELOG.md", "CONTRIBUTING.md",
    "CONTRIBUTOR-LICENSE.md", "SECURITY.md",
})


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _git_paths(*args):
    result = subprocess.run(["git", "ls-files", *args, "-z"], cwd=ROOT,
                            capture_output=True, check=True, timeout=30)
    return {item for item in result.stdout.decode("utf-8").split("\0") if item}


def _forbidden(name):
    parts = PurePosixPath(name).parts
    return (name.startswith(FORBIDDEN_PREFIXES)
            or (name.startswith("竞品对比/") and name not in COMPARISON_REPORTS)
            or ".git" in parts or "__pycache__" in parts
            or any(part == ".env" or part.startswith(".env.") for part in parts)
            or name.endswith((".pyc", ".pyo", ".pem", ".key")))


def inspect_release(*, publication=False):
    errors, warnings = [], []
    facts_missing = []
    try:
        metadata = json.loads((ROOT / "release.json").read_text(encoding="utf-8"),
                              object_pairs_hook=_object)
        if not isinstance(metadata, dict):
            raise ValueError("metadata_object_required")
        if metadata.get("version") != __version__:
            errors.append("version_mismatch")
        match = re.fullmatch(r"(\d+\.\d+\.\d+)a(\d+)", __version__)
        if not match or metadata.get("proposed_tag") != f"v{match[1]}-alpha.{match[2]}":
            errors.append("proposed_tag_mismatch")
        expected = {
            "publication_status": "unpublished_candidate",
            "license": "PolyForm-Noncommercial-1.0.0",
            "contributions": "accepted_subject_to_explicit_contributor_license",
            "supported_platforms": ["Windows"], "supported_python": ["3.11"],
            "capability_support": "synthetic_helper_only",
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            errors.append("release_scope_mismatch")
        for key in REQUIRED_FACTS:
            value = metadata.get(key)
            if value is None or value == "":
                facts_missing.append(key)
            elif (not isinstance(value, str) or not value.strip()
                  or re.search(r"待填写|待确认|TODO|PLACEHOLDER|example\.(?:com|org|net)", value, re.I)):
                errors.append("release_fact_invalid:" + key)
        repository = metadata.get("repository_url")
        if isinstance(repository, str) and repository:
            parsed = urlsplit(repository)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or not parsed.path.strip("/") or parsed.query or parsed.fragment):
                errors.append("repository_url_invalid")
    except (OSError, ValueError, TypeError) as exc:
        errors.append("release_metadata_invalid:" + type(exc).__name__)

    if facts_missing:
        warnings.append("publication_facts_missing:" + ",".join(facts_missing))
        if publication:
            errors.append("publication_facts_incomplete")
    if sys.version_info[:2] != (3, 11):
        errors.append("python_311_required")

    candidates = set()
    try:
        tracked = _git_paths("--cached")
        untracked = _git_paths("--others", "--exclude-standard")
        candidates = tracked | untracked
        forbidden = sorted(name for name in candidates if _forbidden(name))
        if forbidden:
            errors.extend("source_scope_forbidden:" + name for name in forbidden)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        errors.append("git_source_scope_unavailable")

    missing_source = sorted(name for name in candidates if not (ROOT / name).is_file())
    errors.extend("source_member_missing:" + name for name in missing_source)
    required_source = RELEASE_FILES | {
        "LICENSE", "COMMERCIAL-LICENSE.md", "THIRD-PARTY-NOTICES.md",
        ".github/workflows/ci.yml", ".github/PULL_REQUEST_TEMPLATE.md",
    }
    errors.extend("release_source_missing:" + name for name in sorted(required_source - candidates))

    inventory = bundle.BUNDLE_FILES
    errors.extend("bundle_source_not_in_git_scope:" + name
                  for name in sorted(set(inventory) - candidates))
    if len(inventory) != len(set(inventory)):
        errors.append("bundle_duplicate")
    for name in inventory:
        if _forbidden(name) or name.startswith("evals/"):
            errors.append("bundle_scope_forbidden:" + name)
        path = ROOT / name
        try:
            info = bundle._checked_path(path, missing_leaf=True)
            if not path.is_file() or info is None:
                errors.append("bundle_member_missing:" + name)
        except (OSError, bundle.BundleError):
            errors.append("bundle_member_invalid:" + name)
    errors.extend("release_bundle_missing:" + name for name in sorted(RELEASE_FILES - set(inventory)))

    compiled = 0
    for name in sorted(candidates):
        if not name.endswith(".py") or _forbidden(name):
            continue
        try:
            compile((ROOT / name).read_bytes(), str(ROOT / name), "exec")
            compiled += 1
        except (OSError, SyntaxError, ValueError):
            errors.append("python_source_invalid:" + name)
    for name in inventory:
        if not name.startswith("tools/") or not name.endswith(".py") or not (ROOT / name).is_file():
            continue
        try:
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            deps = []
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                deps = (["tools/" + node.module.replace(".", "/") + ".py"] if node.module else
                        ["tools/" + item.name + ".py" for item in node.names])
            elif isinstance(node, ast.ImportFrom) and node.module == "tools":
                deps = ["tools/" + item.name + ".py" for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tools."):
                deps = [node.module.replace(".", "/") + ".py"]
            elif isinstance(node, ast.Import):
                deps = [item.name.replace(".", "/") + ".py" for item in node.names
                        if item.name.startswith("tools.")]
            errors.extend("bundle_dependency_missing:" + dep for dep in deps if dep not in inventory)

    metadata_count = 0
    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8-sig")
        match = re.match(r"---\r?\nname: ([^\r\n]+)\r?\ndescription: ([^\r\n]+)\r?\n---", text)
        if not match or match[1] != path.parent.name or not match[2].strip():
            errors.append("skill_metadata_invalid:" + path.parent.name)
        metadata_count += 1
    if metadata_count != 6:
        errors.append("six_skill_entries_required")
    rows = catalog()
    if (len(rows) != 83 or len({row["capability"] for row in rows}) != 83
            or any(row["support"] != "synthetic_helper_only" or row["availability"] != "available"
                   for row in rows)):
        errors.append("catalog_scope_changed")
    return {"status": "rejected" if errors else "candidate_checks_passed",
            "version": __version__, "python": ".".join(map(str, sys.version_info[:3])),
            "publication_check": publication, "publication_performed": False,
            "source_candidates": len(candidates), "bundle_source_files": len(inventory),
            "compiled_files": compiled, "skill_entries": metadata_count,
            "catalog_entries": len(rows), "missing_publication_facts": facts_missing,
            "errors": sorted(set(errors)), "warnings": warnings,
            "identity_license_secret_scan_professional_checks": "not_performed",
            "model_host_office_and_full_regression": "not_performed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", action="store_true", help="公开前要求真实发布元数据齐备")
    args = parser.parse_args(argv)
    report = inspect_release(publication=args.publication)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
