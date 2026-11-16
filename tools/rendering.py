"""CORE-07/FIG-05/REVIEW-07：纯字节预览和版本绑定，不执行浏览器或外发。

只支持明确的被动SVG、Markdown子集和UTF-8文本。证据校验不是身份认证、
视觉事实证明或专业签核；浏览器执行及肉眼检查必须由调用者另行完成。
"""
from __future__ import annotations

import math
import re
import string
import unicodedata
import xml.etree.ElementTree as ET
from html import escape, unescape
from html.entities import html5
from pathlib import Path, PurePosixPath, PureWindowsPath

from .core import ContractError, parse_time, require, safe_path, sha256_bytes

RENDERER = "dyz-safe-html"
RENDERER_VERSION = "1.1"
PAGE_LINES = 40
MAX_SOURCE_BYTES = 2_000_000
CHECKS = ["content_preservation", "document_overflow", "svg_bounds",
          "text_overflow", "pagination", "visual_crop"]
SVG_NS = "http://www.w3.org/2000/svg"
SVG_TAGS = {"svg", "g", "defs", "marker", "path", "rect", "circle", "ellipse",
            "line", "polyline", "polygon", "text", "tspan", "title", "desc"}
SVG_ATTRS = {"id", "viewBox", "width", "height", "x", "y", "x1", "x2", "y1", "y2",
             "cx", "cy", "r", "rx", "ry", "d", "points", "fill", "stroke",
             "stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin",
             "font-size", "font-family", "font-weight", "text-anchor", "dx", "dy",
             "marker-end", "marker-start", "marker-mid", "markerWidth", "markerHeight",
             "refX", "refY", "orient", "markerUnits", "preserveAspectRatio"}
STYLE = """
* { box-sizing: border-box; }
body { margin: 0; color: #17202a; background: #eef1f4;
  font: 16px/1.65 Arial, 'Microsoft YaHei', sans-serif; }
header, main { max-width: 960px; margin: 20px auto; padding: 24px;
  background: white; overflow-wrap: anywhere; }
h1, h2, h3, h4, h5, h6 { line-height: 1.4; break-after: avoid; }
p { margin: 12px 0; } table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td { border: 1px solid #99a3ad; padding: 8px; vertical-align: top; }
thead { display: table-header-group; } tr { break-inside: avoid; }
pre, code { font-family: Consolas, 'Microsoft YaHei', monospace; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; tab-size: 4; }
.source-page { border-top: 1px solid #99a3ad; margin-top: 24px; padding-top: 12px; }
.source-line { display: block; min-height: 1.65em; white-space: pre-wrap; overflow-wrap: anywhere; }
.line-number { color: #586575; display: inline-block; width: 5ch; user-select: none; }
svg { display: block; width: 100%; height: auto; overflow: hidden; }
.binding { font-size: 12px; } .issues { border: 2px solid #a62c23; padding: 12px; }
@page { size: A4; margin: 16mm; }
@media print { body { background: white; font-size: 11pt; }
  header, main { margin: 0; max-width: none; padding: 0; }
  header { padding-bottom: 12mm; } .source-page { break-before: page; border: 0; }
  .source-page:first-child { break-before: auto; } }
"""


def _name(name: str) -> str:
    require(isinstance(name, str) and bool(name), "source_name_required")
    require(not PureWindowsPath(name).drive and not name.startswith(("/", "\\"))
            and "\\" not in name and ":" not in name
            and all(p not in {"", ".", ".."} for p in name.split("/"))
            and not any(unicodedata.category(c).startswith("C") for c in name),
            "unsafe_source_name")
    return PurePosixPath(name).suffix.lower()


def _hash(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def preview_scope(name: str, *, width: int = 1280, height: int = 900) -> dict:
    """当前范围只针对指定屏幕视口；不继承为打印或官方版式通过。"""
    _name(name)
    require(type(width) is int and type(height) is int and width >= 320 and height >= 200,
            "invalid_viewport")
    return {"source_name": name, "checks": CHECKS.copy(), "media": "screen",
            "viewport": {"width": width, "height": height}}


def _svg(text: str) -> str:
    # 白名单比删除危险节点更保守：任何未知元素/属性使整图拒绝，不静默改变技术图。
    require(not re.search(r"<!|<\?", text), "svg_declaration_not_supported")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ContractError("invalid_svg") from exc
    require(root.tag in {"svg", "{" + SVG_NS + "}svg"}, "invalid_svg_root")
    bounds = root.get("viewBox", "").replace(",", " ").split()
    try:
        numbers = [float(x) for x in bounds]
    except ValueError as exc:
        raise ContractError("invalid_svg_viewbox") from exc
    require(len(numbers) == 4 and all(math.isfinite(x) for x in numbers)
            and min(numbers[2:]) > 0, "invalid_svg_viewbox")
    ids, references = set(), []
    for node in root.iter():
        tag = node.tag
        if tag.startswith("{" + SVG_NS + "}"):
            tag = tag[len(SVG_NS) + 2:]
        require(tag in SVG_TAGS and (tag != "svg" or node is root),
                "svg_element_not_supported")
        node.tag = tag
        for key, value in node.attrib.items():
            require(key in SVG_ATTRS, "svg_attribute_not_supported")
            require(not re.search(r"[\\<>]|(?i:https?:|data:|file:|javascript:|@import)", value),
                    "svg_external_or_active_value")
            if key == "id":
                require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value) is not None
                        and value not in ids, "svg_invalid_or_duplicate_id")
                ids.add(value)
            if "url" in value.lower() or key.startswith("marker-"):
                match = re.fullmatch(r"url\(#([A-Za-z][A-Za-z0-9_-]*)\)", value)
                require(match is not None and key in {"marker-start", "marker-mid", "marker-end"},
                        "svg_reference_not_supported")
                references.append(match[1])
        if tag not in {"text", "tspan", "title", "desc"}:
            require(not (node.text or "").strip(), "svg_unrendered_text")
        require(not (node.tail or "").strip() or tag == "tspan", "svg_unrendered_tail")
    require(set(references).issubset(ids), "svg_reference_missing")
    # 所有文本/属性由XML序列化器转义；不直接拼接不可信原始SVG。
    root.set("xmlns", SVG_NS)
    return ET.tostring(root, encoding="unicode")


def _source_pages(lines: list[str], *, start: int = 1) -> str:
    pages = []
    for offset in range(0, max(1, len(lines)), PAGE_LINES):
        chunk = lines[offset:offset + PAGE_LINES]
        rows = "".join(f'<span class="source-line" data-line="{start + offset + i}">'
                       f'<span class="line-number">{start + offset + i}</span>'
                       f'<span class="source-text">{escape(line)}</span></span>'
                       for i, line in enumerate(chunk))
        pages.append(f'<section class="source-page" data-page="{offset // PAGE_LINES + 1}">'
                     f'<h2>源码／文本逻辑页 {offset // PAGE_LINES + 1}</h2><pre>{rows}</pre></section>')
    return "".join(pages)


def _inline(text: str, issues: list[str]) -> str:
    # 转义与字符引用只生成文本，不将解码结果重新解析为HTML、链接或Markdown。
    token = re.compile(r"\\([" + re.escape(string.punctuation) + r"])|`([^`\n]+)`|"
                       r"&((?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);)")
    result, i = [], 0
    while i < len(text):
        match = token.match(text, i)
        if match:
            escaped, code, entity = match.groups()
            if escaped is not None:
                result.append(escape(escaped))
            elif code is not None:
                result.append("<code>" + escape(code) + "</code>")
            else:
                literal = match[0]
                if entity.startswith("#"):
                    number = entity[1:-1]
                    base = 16 if number[:1].lower() == "x" else 10
                    digits = number[1:] if base == 16 else number
                    # 在HTML的替换/删除规则之前检查数值，防止控制字符引用绕过源检查。
                    significant = digits.lstrip("0") or "0"
                    value = int(significant, base) if len(significant) <= 7 else 0x110000
                    require(value > 0x10ffff or unicodedata.category(chr(value)) not in {"Cc", "Cf"},
                            "hidden_control_character")
                    literal = unescape(f"&#{value};")
                elif entity in html5:
                    literal = unescape(literal)
                require(not any(unicodedata.category(c) in {"Cc", "Cf"} for c in literal),
                        "hidden_control_character")
                result.append(escape(literal))
            i = match.end()
            continue
        char = text[i]
        intraword = (char == "_" and i > 0 and i + 1 < len(text)
                     and text[i - 1].isalnum() and text[i + 1].isalnum())
        if char in "[]<>*~`\\" or (char == "_" and not intraword):
            issues.append("markdown_inline_not_supported")
        result.append(escape(char))
        i += 1
    if text.endswith("  "):
        issues.append("markdown_inline_not_supported")
    return "".join(result)


def _markdown(text: str) -> tuple[str, list[str]]:
    lines, parts, issues = text.splitlines(), [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if re.fullmatch(r"```[A-Za-z0-9_-]*", line):
            end = i + 1
            while end < len(lines) and lines[end] != "```":
                end += 1
            if end == len(lines):
                issues.append("markdown_unclosed_fence")
            parts.append(_source_pages(lines[i + 1:end], start=i + 2))
            i = end + 1
            continue
        heading = re.fullmatch(r"(#{1,6}) (.+)", line)
        if heading:
            level = len(heading[1])
            parts.append(f"<h{level}>" + _inline(heading[2], issues) + f"</h{level}>")
            i += 1
            continue
        if line.startswith("|") and line.endswith("|") and i + 1 < len(lines):
            cells = [c.strip() for c in line[1:-1].split("|")]
            divider = [c.strip() for c in lines[i + 1].strip().strip("|").split("|")]
            if len(divider) == len(cells) and all(re.fullmatch(r"-{3,}", c) for c in divider):
                rows = [cells]
                i += 2
                while i < len(lines) and lines[i].startswith("|") and lines[i].endswith("|"):
                    row = [c.strip() for c in lines[i][1:-1].split("|")]
                    if len(row) != len(cells):
                        issues.append("markdown_table_column_mismatch")
                    rows.append(row)
                    i += 1
                parts.append("<table><thead><tr>" + "".join(
                    "<th>" + _inline(c, issues) + "</th>" for c in rows[0]) + "</tr></thead><tbody>" +
                    "".join("<tr>" + "".join("<td>" + _inline(c, issues) + "</td>" for c in row) +
                            "</tr>" for row in rows[1:]) + "</tbody></table>")
                continue
        item = re.fullmatch(r"(- |\d+\. )(.+)", line)
        if item:
            ordered = item[1] != "- "
            tag = "ol" if ordered else "ul"
            number = f' start="{int(item[1][:-2])}"' if ordered else ""
            parts.append(f"<{tag}{number}><li>" + _inline(item[2], issues) + f"</li></{tag}>")
        else:
            if re.match(r"\s|[>|#]|[-=]{3,}$|~~~", line):
                issues.append("markdown_block_not_supported")
            parts.append("<p>" + _inline(line, issues) + "</p>")
        i += 1
    return "".join(parts), sorted(set(issues))


def render_preview(name: str, content: bytes, manifest_hash: str) -> dict:
    """从显式UTF-8字节产生HTML，不读文件/网络、不执行材料中的命令。

    结构非法抛ContractError；不支持Markdown保留可见文字并返回blocked。
    preview_created仅表示HTML生成，绝不代表浏览器或专业审核已通过。
    """
    suffix = _name(name)
    require(suffix in {".svg", ".md", ".txt"}, "render_format_not_supported")
    require(type(content) is bytes and len(content) <= MAX_SOURCE_BYTES, "source_bytes_invalid")
    require(_hash(manifest_hash), "manifest_hash_required")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("invalid_utf8") from exc
    require(not any(unicodedata.category(c) in {"Cc", "Cf"} and c not in "\n\r\t"
                    for c in text), "hidden_control_character")
    issues = []
    if suffix == ".svg":
        body = _svg(text)
    elif suffix == ".md":
        body, issues = _markdown(text)
    else:
        body = _source_pages(text.splitlines())
    source_hash = sha256_bytes(content)
    notice = ("<aside class=\"issues\">未支持结构：" + escape(", ".join(issues)) + "</aside>") if issues else ""
    html = ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            "style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; "
            "base-uri 'none'; form-action 'none'; object-src 'none'\">"
            f"<title>{escape(name)}</title><style>{STYLE}</style></head><body>"
            f"<header><h1>{escape(name)}</h1><p>本地候选预览 · 非专业签核／非正式格式</p>"
            f'<p class="binding">源 SHA-256：{source_hash}<br>包：{manifest_hash}<br>'
            f"渲染器：{RENDERER} {RENDERER_VERSION}</p>{notice}</header>"
            f"<main>{body}</main></body></html>")
    return {"source_name": name, "source_sha256": source_hash, "manifest_hash": manifest_hash,
            "renderer": RENDERER, "renderer_version": RENDERER_VERSION, "html": html,
            "rendered_artifact_hash": sha256_bytes(html.encode("utf-8")), "issues": issues,
            "status": "blocked" if issues else "preview_created",
            "rendering": "not_executed", "professional_review": "not_performed"}


def write_preview(root: str | Path, relative: str, preview: dict) -> Path:
    """只在显式获准根内新建HTML；拒绝覆盖任何现有文件，不隐式建目录。"""
    require(_name(relative) == ".html", "html_output_required")
    content = preview["html"].encode("utf-8")
    require(sha256_bytes(content) == preview.get("rendered_artifact_hash"), "preview_hash_mismatch")
    target = safe_path(root, relative, must_exist=False)
    require(target.parent.is_dir(), "parent_directory_missing")
    with target.open("xb") as stream:
        stream.write(content)
    return target


def validate_rendering_evidence(record: dict, *, name: str, content: bytes,
                                manifest_hash: str, artifact: bytes,
                                evidence_artifacts: dict[str, bytes],
                                required_scope: dict, now: str) -> dict:
    """校验当前源/包/渲染器/HTML/证据字节及范围；不读取record内的路径。

    返回status=consistent或blocked和issues。consistent只表示提供的观察记录
    与字节一致；调用者仍负责证据来源、身份认证、专业审批和外发门禁。
    """
    issues = []

    def check(condition, code):
        if not condition:
            issues.append(code)

    require(isinstance(record, dict) and isinstance(required_scope, dict)
            and isinstance(evidence_artifacts, dict) and type(artifact) is bytes,
            "rendering_validation_arguments_invalid")
    instant = parse_time(now)
    preview = render_preview(name, content, manifest_hash)
    check(not preview["issues"], "preview_has_unsupported_content")
    for field in ("source_name", "source_sha256", "manifest_hash", "renderer", "renderer_version",
                  "rendered_artifact_hash"):
        check(record.get(field) == preview[field], field + "_mismatch")
    check(sha256_bytes(artifact) == preview["rendered_artifact_hash"], "html_bytes_mismatch")
    check(record.get("status") == "passed", "rendering_not_passed")
    check(record.get("scope") == required_scope, "rendering_scope_mismatch")
    viewport = required_scope.get("viewport", {})
    check(isinstance(viewport, dict) and required_scope.get("source_name") == name
          and required_scope.get("checks") == CHECKS and required_scope.get("media") == "screen"
          and type(viewport.get("width")) is int and viewport.get("width", 0) >= 320
          and type(viewport.get("height")) is int and viewport.get("height", 0) >= 200,
          "required_scope_invalid")
    reviewer = record.get("reviewer", {})
    check(isinstance(reviewer, dict) and isinstance(reviewer.get("id"), str)
          and bool(reviewer.get("id", "").strip())
          and reviewer.get("kind") in ("human", "agent", "synthetic"), "reviewer_missing")
    try:
        check(parse_time(record.get("checked_at")) <= instant, "rendering_time_in_future")
    except ContractError:
        check(False, "rendering_time_invalid")
    evidence = record.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
    check(evidence.get("executed") is True, "rendering_not_executed")
    browser = evidence.get("browser", {})
    check(isinstance(browser, dict) and all(isinstance(browser.get(k), str)
          and browser[k].strip() for k in ("name", "version")), "browser_version_missing")
    for key in ("dom", "visual"):
        observation = evidence.get(key, {})
        check(isinstance(observation, dict) and observation.get("status") == "passed"
              and observation.get("issues") == [] and observation.get("scope") == required_scope
              and isinstance(observation.get("notes"), str) and bool(observation["notes"].strip()),
              key + "_review_incomplete")
    entries = evidence.get("artifacts", [])
    check(isinstance(entries, list) and bool(entries), "rendering_artifact_missing")
    seen, screenshot = set(), False
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                check(False, "rendering_artifact_invalid")
                continue
            key = entry.get("id")
            if not isinstance(key, str) or not key or key in seen:
                check(False, "rendering_artifact_id_invalid")
                continue
            seen.add(key)
            raw = evidence_artifacts.get(key)
            valid = type(raw) is bytes and len(raw) > 0
            check(valid and sha256_bytes(raw) == entry.get("sha256"), "evidence_bytes_mismatch")
            kind = entry.get("kind")
            check(kind in ("screenshot_png", "print_pdf"), "evidence_kind_not_supported")
            if kind == "screenshot_png":
                screenshot = True
                check(valid and raw.startswith(b"\x89PNG\r\n\x1a\n"), "evidence_not_png")
            if kind == "print_pdf":
                check(valid and raw.startswith(b"%PDF-"), "evidence_not_pdf")
    check(screenshot, "screen_screenshot_required")
    check(seen == set(evidence_artifacts), "evidence_inventory_mismatch")
    return {"status": "blocked" if issues else "consistent", "issues": sorted(set(issues)),
            "identity_verification": "not_performed", "professional_review": "not_performed",
            "evidence_authenticity": "not_established_by_hash", "external_action": "not_performed"}
