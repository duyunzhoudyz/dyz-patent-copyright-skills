"""只读发布范围与候选结构检查；不安装、联网、写Git或认证专业能力。"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path, PurePosixPath
import re
import stat
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
_RELEASE_FACT_PLACEHOLDER = re.compile(
    r"待填写|待确认|未填写|待补|占位|TODO|PLACEHOLDER|example\.(?:com|org|net)"
    r"|\b(?:tbd|none|null|unknown|n/a|测试)\b",
    re.I,
)
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
CI_CHECKOUT_PIN = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
CI_SETUP_PYTHON_PIN = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
PLATFORM_TO_RUNNER = {
    "Windows": "windows-latest",
    "Linux": "ubuntu-latest",
    "macOS": "macos-latest",
}
EXPECTED_VERIFIED_PLATFORMS = ["Windows", "Linux", "macOS"]
EXPECTED_VERIFIED_PYTHON = ["3.11", "3.12", "3.13", "3.14"]
EXPECTED_TARGET_CI_PLATFORMS = ["Windows", "Linux", "macOS"]
EXPECTED_TARGET_CI_PYTHON = ["3.11", "3.12", "3.13", "3.14"]


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _strip_yaml_quotes(value):
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


class _CiSyntax(Exception):
    """工作流子集里无法安全判断的结构；调用方整文件拒绝。"""


_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_BLOCK_HEADER = re.compile(r"^[|>](?:[+-][1-9]?|[1-9][+-]?)?$")
_SHA_REF = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
_GITHUB_EXPR = re.compile(r"\$\{\{.*?\}\}")
_QUOTED_KEY = re.compile(r"""^(['"]).*?\1\s*:""")
_EMPTY_FLOW = re.compile(r"\{\s*\}")


def _cut_comment(line):
    """丢掉引号外的 #。引号内的 # 留给标量。"""
    out = []
    index = 0
    quote = None
    while index < len(line):
        char = line[index]
        if quote == "'":
            out.append(char)
            if char == "'":
                if index + 1 < len(line) and line[index + 1] == "'":
                    out.append("'")
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if quote == '"':
            out.append(char)
            if char == "\\" and index + 1 < len(line):
                out.append(line[index + 1])
                index += 2
                continue
            if char == '"':
                quote = None
            index += 1
            continue
        if char in "'\"":
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "#" and (index == 0 or line[index - 1] in " \t"):
            break
        out.append(char)
        index += 1
    if quote is not None:
        raise _CiSyntax()
    return "".join(out).rstrip()


def _bare_syntax(content):
    """去掉引号和 GitHub 表达式，只留下能判断流式/锚点的骨架。"""
    out = []
    index = 0
    quote = None
    while index < len(content):
        char = content[index]
        if quote == "'":
            if char == "'" and index + 1 < len(content) and content[index + 1] == "'":
                index += 2
                continue
            if char == "'":
                quote = None
            index += 1
            continue
        if quote == '"':
            if char == "\\" and index + 1 < len(content):
                index += 2
                continue
            if char == '"':
                quote = None
            index += 1
            continue
        if char in "'\"":
            quote = char
            index += 1
            continue
        out.append(char)
        index += 1
    return _GITHUB_EXPR.sub(" ", "".join(out))


def _reject_structure(content):
    stripped = content.strip()
    # 唯一允许的流式写法是 job 最小权限 permissions: {}。
    if re.fullmatch(r"(?:-\s+)?permissions:\s*\{\s*\}", stripped):
        return
    body = stripped[2:].strip() if stripped.startswith("- ") else stripped
    if _QUOTED_KEY.match(body):
        raise _CiSyntax()
    bare = _bare_syntax(stripped)
    if ("<<" in bare or re.search(r"(?:^|[\s:{])&[A-Za-z_]", bare)
            or re.search(r"(?:^|[\s:{])\*[A-Za-z_]", bare)):
        raise _CiSyntax()
    if any(char in bare for char in "{}[]"):
        raise _CiSyntax()


def _split_entry(content):
    sequence = content.startswith("- ")
    body = content[2:].strip() if sequence else content
    key, separator, rest = body.partition(":")
    if separator == "":
        return sequence, None, body
    key = key.strip()
    if not _PLAIN_KEY.fullmatch(key):
        raise _CiSyntax()
    return sequence, key, rest.strip()


def _value_scalar(content):
    _sequence, key, rest = _split_entry(content)
    if key is None:
        return None
    return rest or None


def _structural_events(text):
    """结构化行。|/> 块标量的缩进正文整段跳过，避免 run 脚本里的 uses 被当成步骤。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    events = []
    block_floor = None
    for raw in text.splitlines():
        if block_floor is not None:
            if not raw.strip():
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent > block_floor:
                continue
            block_floor = None
        cleaned = _cut_comment(raw)
        if not cleaned.strip():
            continue
        indent_text = cleaned[:len(cleaned) - len(cleaned.lstrip(" \t"))]
        if "\t" in indent_text:
            raise _CiSyntax()
        indent = len(indent_text)
        content = cleaned.strip()
        _reject_structure(content)
        events.append((indent, content))
        scalar = _value_scalar(content)
        if scalar is not None and _BLOCK_HEADER.fullmatch(scalar):
            # 序列首键的块标量以键列封口；用 '-' 列会把同一步的 uses/with 吃进正文。
            if content.startswith("- "):
                block_floor = indent + (len(content) - len(content[1:].lstrip(" ")))
            else:
                block_floor = indent
    return events


def _mapping(events):
    nodes = {}
    if not events:
        return nodes
    base = events[0][0]
    index = 0
    while index < len(events):
        indent, content = events[index]
        if indent != base:
            raise _CiSyntax()
        sequence, key, rest = _split_entry(content)
        if sequence or key is None or key in nodes:
            raise _CiSyntax()
        index += 1
        child = []
        while index < len(events) and events[index][0] > base:
            child.append(events[index])
            index += 1
        if rest and child:
            raise _CiSyntax()
        nodes[key] = (rest or None, child)
    return nodes


def _sequence(events):
    if not events:
        return []
    items = []
    base = events[0][0]
    current = None
    for indent, content in events:
        if indent == base and content.startswith("- "):
            if current is not None:
                items.append(current)
            rest = content[1:].lstrip(" ")
            key_indent = indent + (len(content) - len(rest))
            current = [(key_indent, rest)] if rest else []
        elif current is not None and indent > base:
            current.append((indent, content))
        else:
            raise _CiSyntax()
    if current is not None:
        items.append(current)
    return items


def _plain(mapping, key):
    node = mapping.get(key)
    if node is None:
        return None
    scalar, child = node
    if child or not scalar:
        return None
    return _strip_yaml_quotes(scalar)


def _scalar_list(events):
    if not events:
        raise _CiSyntax()
    base = events[0][0]
    values = []
    for indent, content in events:
        if indent != base or not content.startswith("- "):
            raise _CiSyntax()
        raw = content[2:].strip()
        if not raw or ":" in _bare_syntax(raw):
            raise _CiSyntax()
        values.append(_strip_yaml_quotes(raw))
    return values


def _pair_rows(events):
    rows = []
    for item in _sequence(events):
        mapping = _mapping(item)
        rows.append((_plain(mapping, "os"), _plain(mapping, "python-version")))
    return rows


def _exclude_rows(events):
    """exclude 条目只接受 os / python-version。空条目或未知键无法安全解释。"""
    rows = []
    allowed = {"os", "python-version"}
    for item in _sequence(events):
        mapping = _mapping(item)
        if not mapping or set(mapping) - allowed:
            raise _CiSyntax()
        row = []
        for key in ("os", "python-version"):
            if key not in mapping:
                row.append(None)
                continue
            value = _plain(mapping, key)
            if value is None:
                raise _CiSyntax()
            row.append(value)
        rows.append(tuple(row))
    return rows


def _excluded_pair(pair, excluded):
    os_name, py_name = pair
    return any(
        (ex_os is None or os_name == ex_os) and (ex_py is None or py_name == ex_py)
        for ex_os, ex_py in excluded
    )


def _matrix_pairs(node):
    scalar, child = node
    if scalar is not None:
        raise _CiSyntax()
    mapping = _mapping(child)
    pairs = []
    has_axis = "os" in mapping or "python-version" in mapping
    if has_axis:
        if "os" not in mapping or "python-version" not in mapping:
            return [("", "")]
        os_scalar, os_child = mapping["os"]
        py_scalar, py_child = mapping["python-version"]
        if os_scalar is not None or py_scalar is not None:
            raise _CiSyntax()
        for item_os in _scalar_list(os_child):
            for item_py in _scalar_list(py_child):
                pairs.append((item_os, item_py))
    excluded = []
    if "exclude" in mapping:
        ex_scalar, ex_child = mapping["exclude"]
        if ex_scalar is not None:
            raise _CiSyntax()
        excluded = _exclude_rows(ex_child)
    # exclude 只裁笛卡尔积。include 在其后合并，可把刚排除的组合加回。
    pairs = [pair for pair in pairs if not _excluded_pair(pair, excluded)]
    if "include" in mapping:
        inc_scalar, inc_child = mapping["include"]
        if inc_scalar is not None:
            raise _CiSyntax()
        pairs.extend(_pair_rows(inc_child))
    if not has_axis and "include" not in mapping:
        return []
    return pairs


def _job_matrix_pairs(job_node):
    scalar, body = job_node
    if scalar is not None:
        return None
    mapping = _mapping(body)
    if "strategy" not in mapping:
        return None
    strategy_scalar, strategy_body = mapping["strategy"]
    if strategy_scalar is not None:
        return None
    strategy = _mapping(strategy_body)
    if "matrix" not in strategy:
        return None
    return _matrix_pairs(strategy["matrix"])


def _parse_ci_matrix_include(lines):
    """返回各 job 矩阵展开后的 (os, python-version)；语法无效时返回空。"""
    try:
        top = _mapping(_structural_events("\n".join(lines)))
        jobs = top.get("jobs")
        if jobs is None or jobs[0] is not None:
            return []
        pairs = []
        for node in _mapping(jobs[1]).values():
            found = _job_matrix_pairs(node)
            if found:
                pairs.extend(found)
        return pairs
    except _CiSyntax:
        return []


def _permissions_ok(node, *, required):
    scalar, child = node
    if scalar is not None:
        return (not required) and not child and _EMPTY_FLOW.fullmatch(scalar) is not None
    mapping = _mapping(child)
    if not mapping:
        return not required
    return set(mapping) == {"contents"} and _plain(mapping, "contents") == "read"


def _concurrency_ok(node):
    scalar, child = node
    if scalar is not None:
        return False
    mapping = _mapping(child)
    group = _plain(mapping, "group")
    return bool(group and group.strip()) and _plain(mapping, "cancel-in-progress") == "true"


def _action_kind(ref):
    """仓库名大小写不敏感。只把 checkout / setup-python 归入强制钉扎。"""
    ref_lower = ref.lower()
    if ref_lower == "actions/checkout" or ref_lower.startswith("actions/checkout@"):
        return "checkout"
    if ref_lower == "actions/setup-python" or ref_lower.startswith("actions/setup-python@"):
        return "setup"
    return "other"


def _exact_pin(ref, pin):
    repo, separator, sha = ref.partition("@")
    expected_repo, _, expected_sha = pin.partition("@")
    return separator == "@" and repo.lower() == expected_repo and sha == expected_sha


def _collect_use(ref, checkout, setup, other):
    kind = _action_kind(ref)
    if kind == "checkout":
        checkout.append(ref)
    elif kind == "setup":
        setup.append(ref)
    else:
        other.append(ref)


def _collect_steps(node, checkout, setup, other, errors):
    scalar, body = node
    if scalar is not None:
        raise _CiSyntax()
    for item in _sequence(body):
        mapping = _mapping(item)
        if "uses" not in mapping:
            continue
        ref = _plain(mapping, "uses")
        if not ref:
            errors.append("ci_action_unpinned")
            continue
        _collect_use(ref, checkout, setup, other)
        if _action_kind(ref) != "checkout":
            continue
        if not _exact_pin(ref, CI_CHECKOUT_PIN):
            errors.append("ci_checkout_sha_mismatch")
        persist = None
        with_node = mapping.get("with")
        if with_node is not None and with_node[0] is None:
            persist = _plain(_mapping(with_node[1]), "persist-credentials")
        if persist != "false":
            errors.append("ci_permissions_mismatch")


def _matrix_from_strategy(node):
    scalar, body = node
    if scalar is not None:
        raise _CiSyntax()
    mapping = _mapping(body)
    if "matrix" not in mapping:
        return None
    return _matrix_pairs(mapping["matrix"])


def _matrix_expression(value, field):
    match = re.fullmatch(r"\$\{\{\s*matrix\.(os|python-version)\s*\}\}", value or "")
    return match is not None and match[1] == field


def _matrix_binding_ok(mapping):
    """有矩阵的作业必须真正读 matrix.os 与 matrix.python-version。"""
    if not _matrix_expression(_plain(mapping, "runs-on"), "os"):
        return False
    steps = mapping.get("steps")
    if steps is None or steps[0] is not None:
        return False
    bound = False
    for item in _sequence(steps[1]):
        step = _mapping(item)
        ref = _plain(step, "uses")
        if not ref or _action_kind(ref) != "setup":
            continue
        bound = True
        version = None
        with_node = step.get("with")
        if with_node is not None and with_node[0] is None:
            version = _plain(_mapping(with_node[1]), "python-version")
        if not _matrix_expression(version, "python-version"):
            return False
    return bound


def _audit_workflow(text, *, target_platforms, target_python):
    errors = []
    top = _mapping(_structural_events(text))
    permissions = top.get("permissions")
    if permissions is None or not _permissions_ok(permissions, required=True):
        errors.append("ci_permissions_mismatch")
    concurrency = top.get("concurrency")
    if concurrency is None or not _concurrency_ok(concurrency):
        errors.append("ci_concurrency_missing")

    checkout, setup, other = [], [], []
    matrices = []
    jobs_node = top.get("jobs")
    job_map = {}
    if jobs_node is not None and jobs_node[0] is not None:
        errors.append("ci_permissions_mismatch")
    elif jobs_node is not None:
        job_map = _mapping(jobs_node[1])
    for job in job_map.values():
        job_scalar, job_body = job
        if job_scalar is not None:
            errors.append("ci_permissions_mismatch")
            continue
        mapping = _mapping(job_body)
        if "permissions" in mapping and not _permissions_ok(mapping["permissions"], required=False):
            errors.append("ci_permissions_mismatch")
        if "uses" in mapping:
            # job 级 uses 没有步骤 with，不能冒充 checkout / setup-python。
            errors.append("ci_action_unpinned")
        if "steps" in mapping:
            _collect_steps(mapping["steps"], checkout, setup, other, errors)
        if "strategy" in mapping:
            found = _matrix_from_strategy(mapping["strategy"])
            if found is not None:
                matrices.append(found)
                if not _matrix_binding_ok(mapping):
                    errors.append("ci_matrix_binding_invalid")

    if not checkout or any(not _exact_pin(ref, CI_CHECKOUT_PIN) for ref in checkout):
        errors.append("ci_checkout_sha_mismatch")
    if not setup or any(not _exact_pin(ref, CI_SETUP_PYTHON_PIN) for ref in setup):
        errors.append("ci_setup_python_sha_mismatch")
    uses_refs = [*checkout, *setup, *other]
    if not uses_refs or any(_SHA_REF.fullmatch(ref) is None for ref in uses_refs):
        errors.append("ci_action_unpinned")

    platforms = target_platforms if isinstance(target_platforms, list) else EXPECTED_TARGET_CI_PLATFORMS
    pythons = target_python if isinstance(target_python, list) else EXPECTED_TARGET_CI_PYTHON
    if (not platforms or not pythons
            or any(not isinstance(item, str) or item not in PLATFORM_TO_RUNNER for item in platforms)
            or any(not isinstance(item, str) or not item.strip() for item in pythons)):
        errors.append("ci_matrix_mismatch")
    else:
        expected_pairs = {(PLATFORM_TO_RUNNER[item], version) for item in platforms for version in pythons}
        if not matrices or any(
                len(pairs) != len(expected_pairs)
                or any(not os_name or not py_ver for os_name, py_ver in pairs)
                or set(pairs) != expected_pairs
                for pairs in matrices):
            errors.append("ci_matrix_mismatch")
    return list(dict.fromkeys(errors))


def _readable_workflow(path):
    try:
        info = path.lstat()
    except OSError:
        return None
    reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISREG(info.st_mode):
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def check_ci_workflow(ci_path, *, target_platforms=None, target_python=None):
    """核对单个 workflow 的权限、并发、步骤 SHA、checkout 凭证和矩阵。"""
    if not ci_path.is_file():
        return ["ci_workflow_missing"]
    text = _readable_workflow(ci_path)
    if text is None:
        return ["ci_workflow_unreadable"]
    try:
        return _audit_workflow(text, target_platforms=target_platforms, target_python=target_python)
    except _CiSyntax:
        return ["ci_workflow_syntax_rejected"]


def _workflow_paths():
    directory = ROOT / ".github" / "workflows"
    try:
        if not directory.is_dir():
            return []
        entries = list(directory.iterdir())
    except OSError:
        return None
    paths = [path for path in entries if path.suffix.lower() in {".yml", ".yaml"} and path.is_file()]
    return sorted(paths, key=lambda path: path.name.lower())


def _check_workflows(*, target_platforms, target_python):
    """逐个检查 workflows 下全部 yml/yaml，不只看 ci.yml。"""
    paths = _workflow_paths()
    if paths is None:
        return ["ci_workflow_unreadable"]
    errors = []
    if not any(path.name == "ci.yml" for path in paths):
        errors.append("ci_workflow_missing")
    for path in paths:
        errors.extend(check_ci_workflow(
            path, target_platforms=target_platforms, target_python=target_python))
    return errors


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
    metadata = None
    publication_status = None
    try:
        metadata = json.loads((ROOT / "release.json").read_text(encoding="utf-8"),
                              object_pairs_hook=_object)
        if not isinstance(metadata, dict):
            raise ValueError("metadata_object_required")
        if metadata.get("version") != __version__:
            errors.append("version_mismatch")
        match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+)(?:a([0-9]+))?", __version__)
        expected_tag = None
        if match:
            suffix = f"-alpha.{match[2]}" if match[2] is not None else ""
            expected_tag = f"v{match[1]}{suffix}"
        if expected_tag is None or metadata.get("proposed_tag") != expected_tag:
            errors.append("proposed_tag_mismatch")
        publication_status = metadata.get("publication_status")
        if publication_status == "published_release" and match and match[2] is not None:
            errors.append("published_alpha_not_allowed")
        expected = {
            "license": "PolyForm-Noncommercial-1.0.0",
            "contributions": "accepted_subject_to_explicit_contributor_license",
            "verified_platforms": EXPECTED_VERIFIED_PLATFORMS,
            "verified_python": EXPECTED_VERIFIED_PYTHON,
            "target_ci_platforms": EXPECTED_TARGET_CI_PLATFORMS,
            "target_ci_python": EXPECTED_TARGET_CI_PYTHON,
            "supported_platforms": EXPECTED_VERIFIED_PLATFORMS,
            "supported_python": EXPECTED_VERIFIED_PYTHON,
            "capability_support": "synthetic_helper_only",
        }
        if (publication_status not in ("unpublished_candidate", "published_release")
                or any(metadata.get(key) != value for key, value in expected.items())):
            errors.append("release_scope_mismatch")
        vp = metadata.get("verified_platforms")
        vpy = metadata.get("verified_python")
        tp = metadata.get("target_ci_platforms")
        tpy = metadata.get("target_ci_python")
        sp = metadata.get("supported_platforms")
        spy = metadata.get("supported_python")
        if (not all(isinstance(item, list) for item in (vp, vpy, tp, tpy, sp, spy))
                or sp != vp or spy != vpy
                or not set(vp).issubset(set(tp))
                or not set(vpy).issubset(set(tpy))):
            errors.append("release_platform_subset_mismatch")
        note = metadata.get("platform_verification_note")
        if (not isinstance(note, str) or not note.strip()
                or re.search(r"待填写|待确认|TODO|PLACEHOLDER", note, re.I)):
            errors.append("release_platform_note_invalid")
        for key in REQUIRED_FACTS:
            value = metadata.get(key)
            if value is None or value == "":
                facts_missing.append(key)
            elif (not isinstance(value, str) or not value.strip()
                  or _RELEASE_FACT_PLACEHOLDER.search(value)):
                errors.append("release_fact_invalid:" + key)
        repository = metadata.get("repository_url")
        if isinstance(repository, str) and repository:
            parsed = urlsplit(repository)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or not parsed.path.strip("/") or parsed.query or parsed.fragment):
                errors.append("repository_url_invalid")
    except (OSError, ValueError, TypeError) as exc:
        errors.append("release_metadata_invalid:" + type(exc).__name__)

    target_platforms = metadata.get("target_ci_platforms") if isinstance(metadata, dict) else None
    target_python = metadata.get("target_ci_python") if isinstance(metadata, dict) else None
    errors.extend(_check_workflows(target_platforms=target_platforms, target_python=target_python))

    if facts_missing:
        warnings.append("publication_facts_missing:" + ",".join(facts_missing))
        if publication or publication_status == "published_release":
            errors.append("publication_facts_incomplete")
    if not ((3, 11) <= sys.version_info[:2] <= (3, 14)):
        errors.append("python_311_to_314_required")

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
            if isinstance(node, ast.ImportFrom) and node.level >= 1:
                parents = PurePosixPath(name).parents
                if node.level >= len(parents):
                    errors.append("python_source_invalid:" + name)
                    continue
                pkg = parents[node.level - 1].as_posix()
                prefix = "" if pkg == "." else pkg + "/"
                if node.module:
                    mod_path = prefix + node.module.replace(".", "/")
                    deps.append(mod_path + ".py")
                    # Add intermediate parent __init__.py requirements
                    parts = mod_path.split("/")
                    for i in range(2, len(parts)):
                        deps.append("/".join(parts[:i]) + "/__init__.py")
                    # If target is a package, check imported submodule names that exist on disk or aren't symbols
                    if (mod_path + "/__init__.py") in inventory:
                        for item in node.names:
                            if item.name == "*":
                                continue
                            sub_py = f"{mod_path}/{item.name}.py"
                            sub_pkg = f"{mod_path}/{item.name}/__init__.py"
                            if (ROOT / sub_py).is_file() or (ROOT / sub_pkg).is_file():
                                deps.append(sub_py)
                else:
                    deps = [prefix + item.name + ".py" for item in node.names if item.name != "*"]
            elif isinstance(node, ast.ImportFrom) and node.module == "tools":
                deps = [
                    "tools/" + item.name + ".py"
                    for item in node.names
                    if item.name != "*" and not item.name.startswith("__")
                ]
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tools."):
                mod_path = node.module.replace(".", "/")
                deps.append(mod_path + ".py")
                parts = mod_path.split("/")
                for i in range(2, len(parts)):
                    deps.append("/".join(parts[:i]) + "/__init__.py")
                if (mod_path + "/__init__.py") in inventory:
                    for item in node.names:
                        if item.name == "*":
                            continue
                        sub_py = f"{mod_path}/{item.name}.py"
                        sub_pkg = f"{mod_path}/{item.name}/__init__.py"
                        if (ROOT / sub_py).is_file() or (ROOT / sub_pkg).is_file():
                            deps.append(sub_py)
            elif isinstance(node, ast.Import):
                for item in node.names:
                    if item.name.startswith("tools."):
                        mod_path = item.name.replace(".", "/")
                        deps.append(mod_path + ".py")
                        parts = mod_path.split("/")
                        for i in range(2, len(parts)):
                            deps.append("/".join(parts[:i]) + "/__init__.py")
            errors.extend(
                "bundle_dependency_missing:" + dep
                for dep in deps
                if dep not in inventory and (dep[:-3] + "/__init__.py" if dep.endswith(".py") else dep) not in inventory
            )

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
