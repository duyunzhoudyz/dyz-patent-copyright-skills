"""软件候选材料的 PDF 物理页检查，不授予读取、处理或外发权限。

只供已完成授权、指纹核验及生成的调用方传入本系统 PDF。这里不扫描项目，
不读取原始源码，也不把文本提取结果当成图片、空白行或专业规则的证明。
坐标单位为 PDF point，左上角为原点；报告不含材料正文、路径或工具错误原文。
"""

from __future__ import annotations

import math
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET


_A4 = (595.276, 841.890)
_MARGIN = 56.7  # 与软件 DOCX 的 20 mm 正文边距配对。
_SIZE_TOLERANCE = 1.0
_BOUNDS_TOLERANCE = 0.75
_CODE_PITCH = 12.0
_PITCH_TOLERANCE = 0.75
_MAX_XML_BYTES = 64 * 1024 * 1024
_BLOCK_KINDS = {"code", "paragraph", "heading1", "heading2", "image"}
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _normalized(value: str) -> str:
    # 提取器会在 CJK 字符或字体切换处插入空白；不折叠标点、Unicode 或重复字。
    return "".join(value.split())


def _issue(report: dict, code: str, page: int | None = None,
           *, domain: str = "layout", **details) -> None:
    issue = {"code": code, "domain": domain}
    if page is not None:
        issue["physical_page"] = page
    issue.update(details)
    report["issues"].append(issue)
    if code in {"min_lines_unmet", "image_min_lines_exception_unconfirmed"}:
        report["rule_issues"].append(dict(issue))


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _box(element: ET.Element) -> list[float]:
    values = [float(element.attrib[key]) for key in ("xMin", "yMin", "xMax", "yMax")]
    if (not all(math.isfinite(value) for value in values)
            or values[0] >= values[2] or values[1] >= values[3]):
        raise ValueError("invalid_bbox")
    return values


def _inside(box: list[float], bounds: list[float]) -> bool:
    return (box[0] >= bounds[0] - _BOUNDS_TOLERANCE
            and box[1] >= bounds[1] - _BOUNDS_TOLERANCE
            and box[2] <= bounds[2] + _BOUNDS_TOLERANCE
            and box[3] <= bounds[3] + _BOUNDS_TOLERANCE)


def _union(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes)]


def _valid_plan(pages: list, kind: str, title: str, version: str) -> bool:
    if (not isinstance(kind, str) or kind not in {"source", "manual", "worksheet"}
            or not isinstance(title, str) or not _normalized(title)
            or not isinstance(version, str) or not _normalized(version)
            or not isinstance(pages, list) or not pages):
        return False
    seen = set()
    for page in pages:
        if not isinstance(page, list) or not page:
            return False
        for block in page:
            if (not isinstance(block, dict)
                    or not isinstance(block.get("id"), str)
                    or not _SAFE_ID.fullmatch(block["id"])
                    or block["id"] in seen
                    or not isinstance(block.get("kind"), str)
                    or block["kind"] not in _BLOCK_KINDS
                    or not isinstance(block.get("text", ""), str)):
                return False
            seen.add(block["id"])
            if kind == "source" and block["kind"] != "code":
                return False
            if block["kind"] == "code" and any(
                    char in block.get("text", "") for char in "\n\r\v\f\x85\u2028\u2029"):
                return False
    return True


def _extract(pdf: Path, tool: str, report: dict) -> ET.Element | None:
    try:
        executable = Path(tool)
        if (not executable.is_absolute()
                or executable.name.lower() not in {"pdftotext", "pdftotext.exe"}
                or not executable.is_file()):
            _issue(report, "pdf_text_tool_unavailable", domain="extraction")
            return None
        if (not isinstance(pdf, Path) or not pdf.is_absolute()
                or pdf.suffix.lower() != ".pdf" or not pdf.is_file()):
            _issue(report, "invalid_pdf_input", domain="extraction")
            return None
        with pdf.open("rb") as source:
            if source.read(5) != b"%PDF-":
                _issue(report, "invalid_pdf_input", domain="extraction")
                return None
        with tempfile.TemporaryDirectory(prefix="dyz-software-bbox-") as directory:
            output = Path(directory) / "layout.xml"
            process = subprocess.run(
                [str(executable), "-bbox-layout", "-enc", "UTF-8", str(pdf), str(output)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, shell=False, timeout=60, check=False,
            )
            if process.returncode != 0:
                _issue(report, "pdf_text_tool_failed", domain="extraction")
                return None
            if not output.is_file():
                _issue(report, "pdf_text_output_missing", domain="extraction")
                return None
            if output.stat().st_size > _MAX_XML_BYTES:
                _issue(report, "pdf_text_output_too_large", domain="extraction")
                return None
            with output.open("rb") as stream:
                raw = stream.read(_MAX_XML_BYTES + 1)
            if len(raw) > _MAX_XML_BYTES:
                _issue(report, "pdf_text_output_too_large", domain="extraction")
                return None
    except subprocess.TimeoutExpired:
        _issue(report, "pdf_text_tool_timeout", domain="extraction")
        return None
    except (OSError, ValueError, TypeError):
        _issue(report, "pdf_text_io_error", domain="extraction")
        return None
    try:
        text = raw.decode("utf-8")
        # pdftotext 的标准外部 XHTML DOCTYPE 不联网；拒绝内部实体扩展。
        if re.search(r"<!ENTITY\b|<!DOCTYPE[^>]*\[", text, re.IGNORECASE):
            raise ValueError("unsafe_xml")
        document = ET.fromstring(text)
        if _tag(document) != "html":
            raise ValueError("unexpected_xml_root")
        return document
    except (UnicodeError, ET.ParseError, ValueError):
        _issue(report, "invalid_pdf_text_xml", domain="extraction")
        return None


def _read_rows(element: ET.Element, number: int, width: float, height: float,
               report: dict) -> list[dict]:
    lines = []
    mapped_words = set()
    for node in element.iter():
        if _tag(node) != "line":
            continue
        try:
            bounds = _box(node)
            words = [word for word in node if _tag(word) == "word"]
            if not words:
                raise ValueError("line_without_words")
            word_boxes = [_box(word) for word in words]
            if not all(_inside(box, bounds) for box in word_boxes):
                raise ValueError("word_outside_line")
            if not _inside(bounds, [0.0, 0.0, width, height]):
                _issue(report, "bbox_out_of_page", number)
            if any(word_boxes[i][0] < word_boxes[i - 1][0] - _BOUNDS_TOLERANCE
                   for i in range(1, len(word_boxes))):
                _issue(report, "word_reading_order_invalid", number, domain="content")
            text = " ".join("".join(word.itertext()) for word in words)
            mapped_words.update(id(word) for word in words)
            if _normalized(text):
                lines.append({"text": text, "bbox": bounds})
        except (KeyError, ValueError, OverflowError):
            _issue(report, "invalid_bbox", number, domain="extraction")
    all_words = {id(word) for word in element.iter() if _tag(word) == "word"}
    if all_words != mapped_words:
        _issue(report, "unmapped_pdf_text", number, domain="extraction")

    # 独立 flow 可能拆开同一行；按实际坐标合并横向片段，不以 XML 块数量计行。
    rows = []
    for item in sorted(lines, key=lambda line: (line["bbox"][1], line["bbox"][0])):
        box = item["bbox"]
        if rows:
            previous = rows[-1]
            old = previous["bbox"]
            centers = abs((box[1] + box[3] - old[1] - old[3]) / 2)
            if centers <= min(box[3] - box[1], old[3] - old[1]) * 0.25:
                previous["parts"].append(item)
                previous["bbox"] = _union([old, box])
                continue
        rows.append({"parts": [item], "bbox": box})
    for row in rows:
        row["text"] = " ".join(part["text"] for part in sorted(
            row.pop("parts"), key=lambda item: item["bbox"][0]))
    return rows


def _locators(blocks: list[dict], rows: list[dict], *, matched: bool,
              kind: str) -> tuple[list[dict], list[dict]]:
    expected = []
    offset = 0
    for index, block in enumerate(blocks, 1):
        count = len(_normalized(block.get("text", "")))
        expected.append({"block_id": block["id"], "block_index": index,
                         "display_row": index if kind == "source" else None,
                         "kind": block["kind"], "start": offset, "end": offset + count,
                         "physical_lines": [], "bbox": None,
                         "status": "matched" if matched else "unresolved"})
        offset += count
    result = []
    offset = 0
    for line_number, row in enumerate(rows, 1):
        count = len(_normalized(row["text"]))
        finish = offset + count
        sources = []
        if matched:
            for block in expected:
                start, end = max(offset, block["start"]), min(finish, block["end"])
                if start >= end:
                    continue
                sources.append({"block_id": block["block_id"],
                                "block_index": block["block_index"],
                                "display_row": block["display_row"],
                                "text_start": start - block["start"],
                                "text_end": end - block["start"]})
                block["physical_lines"].append(line_number)
                boxes = [block["bbox"], row["bbox"]] if block["bbox"] else [row["bbox"]]
                block["bbox"] = _union(boxes)
        result.append({"physical_line": line_number, "bbox": row["bbox"],
                       "sources": sources,
                       "mapping_status": "matched" if matched else "unresolved"})
        offset = finish
    for block in expected:
        if block["kind"] == "image":
            block["status"] = "image_visual_unverified"
            # 图注坐标不能伪装成图片框；真实图片仍须独立视觉检查。
            block["caption_bbox"], block["bbox"] = block["bbox"], None
        elif block["start"] == block["end"]:
            block["status"] = "blank_not_extractable"
        del block["start"], block["end"]
    return result, expected


def _inspect_page(element: ET.Element, blocks: list[dict], number: int,
                  page_count: int, kind: str, title: str, version: str,
                  report: dict) -> dict:
    page = {"physical_page": number, "candidate_page": number if blocks else None,
            "content_status": "not_checked", "layout_status": "blocked",
            "rows": [], "blocks": [], "nonblank_physical_lines": 0,
            "image_rendering": "not_verified" if any(
                block["kind"] == "image" for block in blocks) else "not_applicable",
            "visual_review": "not_performed",
            "unobservable_blank_rows": sum(not _normalized(b.get("text", ""))
                                           and b["kind"] == "code" for b in blocks)}
    try:
        width, height = float(element.attrib["width"]), float(element.attrib["height"])
        if not all(math.isfinite(x) and x > 0 for x in (width, height)):
            raise ValueError("invalid_page_size")
    except (ValueError, KeyError, OverflowError):
        _issue(report, "invalid_page_size", number, domain="extraction")
        return page
    page["width_pt"], page["height_pt"] = width, height
    if (abs(width - _A4[0]) > _SIZE_TOLERANCE
            or abs(height - _A4[1]) > _SIZE_TOLERANCE):
        _issue(report, "page_size_not_a4", number)
    rows = _read_rows(element, number, width, height, report)
    header = [row for row in rows if row["bbox"][3] <= _MARGIN]
    footer = [row for row in rows if row["bbox"][1] >= height - _MARGIN]
    header_ok = _normalized("".join(row["text"] for row in header)) == _normalized(
        title + " " + version)
    footer_ok = _normalized("".join(row["text"] for row in footer)) == str(number)
    page["header_status"] = "checked" if header_ok else "blocked"
    page["footer_status"] = "checked" if footer_ok else "blocked"
    page["header_bbox"] = _union([row["bbox"] for row in header])
    page["footer_bbox"] = _union([row["bbox"] for row in footer])
    excluded = set()
    if header_ok:
        excluded.update(id(row) for row in header)
    else:
        _issue(report, "header_mismatch", number)
    if footer_ok:
        excluded.update(id(row) for row in footer)
    else:
        _issue(report, "footer_mismatch", number)
    # 仅精确匹配且位于保留区域的整段页眉／页脚可移除，其他文字进入正文比对。
    body = [row for row in rows if id(row) not in excluded]
    actual = _normalized("".join(row["text"] for row in body))
    expected = _normalized("".join(block.get("text", "") for block in blocks))
    matched = actual == expected
    page["content_status"] = "checked" if matched else "blocked"
    if not matched:
        _issue(report, "body_text_mismatch", number, domain="content")
    elif not actual:
        _issue(report, "empty_body", number)
    bounds = [_MARGIN, _MARGIN, width - _MARGIN, height - _MARGIN]
    for line_number, row in enumerate(body, 1):
        if not _inside(row["bbox"], bounds):
            _issue(report, "body_out_of_bounds", number, physical_line=line_number)
        if line_number > 1 and row["bbox"][1] < body[line_number - 2]["bbox"][3] - 0.75:
            _issue(report, "body_rows_overlap", number, physical_line=line_number)
    public_rows, locations = _locators(blocks, body, matched=matched, kind=kind)
    page.update(rows=public_rows, blocks=locations, nonblank_physical_lines=len(body))

    if kind == "source":
        nonblank = [(index, block) for index, block in enumerate(blocks)
                    if _normalized(block.get("text", ""))]
        page["expected_nonblank_display_rows"] = len(nonblank)
        page["expected_line_pitch_pt"] = _CODE_PITCH
        pitch = {"status": "not_measured", "checked_pairs": 0, "unmeasured_pairs": 0,
                 "basis": "equal_height_glyph_box_tops", "baseline_verified": False}
        page["line_pitch_check"] = pitch
        if len(body) != len(nonblank):
            _issue(report, "code_line_count_mismatch", number,
                   expected=len(nonblank), actual=len(body))
        for line_number, row in enumerate(body, 1):
            if row["bbox"][3] - row["bbox"][1] > _CODE_PITCH + _PITCH_TOLERANCE:
                _issue(report, "code_glyph_height_exceeds_pitch", number,
                       physical_line=line_number)
        if matched and len(body) == len(nonblank):
            for index, (row, (_, block)) in enumerate(zip(body, nonblank), 1):
                if _normalized(row["text"]) != _normalized(block.get("text", "")):
                    _issue(report, "code_row_text_mismatch", number,
                           physical_line=index, block_id=block["id"])
            for index in range(1, len(body)):
                previous_box, current_box = body[index - 1]["bbox"], body[index]["bbox"]
                # bbox是字形框而非基线；中英文字体度量变化不能按框顶差误判行距。
                # 只比较等高字形框，跨度量的间距明确保留未测，边界/重叠照常检查。
                if abs((current_box[3] - current_box[1]) - (previous_box[3] - previous_box[1])) > 0.25:
                    pitch["unmeasured_pairs"] += 1
                    continue
                pitch["checked_pairs"] += 1
                expected_gap = (nonblank[index][0] - nonblank[index - 1][0]) * _CODE_PITCH
                actual_gap = current_box[1] - previous_box[1]
                if abs(actual_gap - expected_gap) > _PITCH_TOLERANCE:
                    _issue(report, "code_line_pitch_mismatch", number,
                           physical_line=index + 1, expected_pt=expected_gap,
                           actual_pt=round(actual_gap, 4))
            pitch["status"] = ("partial_font_metrics" if pitch["unmeasured_pairs"] else
                               "checked_glyph_spacing" if pitch["checked_pairs"] else "not_measured")
            if any(issue["code"] == "code_line_pitch_mismatch" and issue.get("physical_page") == number
                   for issue in report["issues"]):
                pitch["status"] = "blocked"

    images = any(block["kind"] == "image" for block in blocks)
    minimum = {"source": 50, "manual": 30}.get(kind)
    page["minimum_nonblank_lines"] = minimum if number < page_count else None
    if minimum and number < page_count and len(body) < minimum:
        _issue(report, "min_lines_unmet", number, required=minimum, actual=len(body))
        if images:
            _issue(report, "image_min_lines_exception_unconfirmed", number)
    issues = [issue for issue in report["issues"] if issue.get("physical_page") == number]
    if any(issue["domain"] == "extraction" for issue in issues):
        page["content_status"] = "blocked"
    page["layout_status"] = "blocked" if any(
        issue["domain"] != "content" for issue in issues) else "checked"
    return page


def inspect_pdf(pdf: Path, pages: list[list[dict]], *, kind: str, title: str,
                version: str, pdf_text_tool: str) -> dict:
    """核对已获准生成的 PDF 与候选逻辑页，返回不含正文的确定性报告。

    ``pages`` 是非空页列表；每块使用 ``id/kind/text``，source 每块为单个 code
    展示行，允许空白行。manual/worksheet 可用 paragraph/heading1/heading2/image。
    图片的 ``text`` 是可选图注；图片像素与真实 PDF 图框不由文本提取器认证。

    ``pdf`` 与 ``pdf_text_tool`` 必须为绝对路径；工具名限定 pdftotext[.exe]，
    无 shell、无联网，60 秒超时。调用方负责 PDF 来源、授权、TOCTOU 隔离和指纹。
    checked 只表示文本几何及候选分页规则检查完成，不是全部成品通过；图片页的
    image_rendering 恒为 not_verified，visual_review 恒为 not_performed。
    非末页 50/30 非空物理行是本链采用的检查条件，不用空白行凑数，也不推定图片例外。
    """
    report = {
        "kind": "software_pdf_layout_report", "status": "blocked",
        "check_scope": "pdf_text_geometry_and_candidate_pagination",
        "image_rendering": "not_applicable", "visual_review": "not_performed",
        "expected_page_count": len(pages) if isinstance(pages, list) else None,
        "actual_page_count": None, "page_count_status": "not_checked",
        "content_fidelity": {"status": "not_checked", "normalization": "whitespace_only"},
        "layout_compliance": {"status": "not_checked"},
        "text_geometry": {"status": "not_checked"},
        "image_fidelity": {"status": "not_applicable"},
        "physical_pages": [], "issues": [], "rule_issues": [],
        "limitations": ["blank_rows_not_observable", "text_bbox_not_pixel_appearance",
                        "image_pixels_and_bounds_not_observable", "mixed_font_baselines_not_observable"],
        "official_status": "not_asserted",
    }
    if not _valid_plan(pages, kind, title, version):
        _issue(report, "invalid_page_plan", domain="input")
        return report
    if any(block["kind"] == "image" for page in pages for block in page):
        report["image_fidelity"]["status"] = "not_checked"
        report["image_rendering"] = "not_verified"
    root = _extract(pdf, pdf_text_tool, report)
    if root is None:
        return report
    physical = [element for element in root.iter() if _tag(element) == "page"]
    report["actual_page_count"] = len(physical)
    if not physical:
        _issue(report, "pdf_has_no_physical_pages", domain="extraction")
        return report
    if len(physical) != len(pages):
        report["page_count_status"] = "blocked"
        _issue(report, "physical_page_count_mismatch", domain="content_and_layout",
               expected=len(pages), actual=len(physical))
    else:
        report["page_count_status"] = "checked"
    for number, page in enumerate(physical, 1):
        blocks = pages[number - 1] if number <= len(pages) else []
        report["physical_pages"].append(_inspect_page(
            page, blocks, number, len(physical), kind, title, version, report))
    content_failed = any(issue["domain"] in {"content", "content_and_layout", "extraction"}
                         for issue in report["issues"])
    layout_failed = any(issue["domain"] != "content" for issue in report["issues"])
    report["content_fidelity"]["status"] = "blocked" if content_failed else "checked"
    report["layout_compliance"]["status"] = "blocked" if layout_failed else "checked"
    geometry_failed = any(issue not in report["rule_issues"] for issue in report["issues"])
    report["text_geometry"]["status"] = "blocked" if geometry_failed else "checked"
    if not report["issues"]:
        report["status"] = "checked"
    return report
