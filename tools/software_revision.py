"""软件稿件的纯内存导入与块级差异；不读取路径、不认证身份或来源。

Markdown只接受可无损保留文本的块子集，图片只返回待上层逐项授权读取的
相对PNG引用。DOCX只接受明确支持的正文结构，不承诺原版式；拒绝不支持的
对象而非跳过。confirmed仅保留有证据引用的输入声明，不等于人工签核。
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import io
import posixpath
import re
import struct
import zipfile
import zlib
from collections import Counter
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from tools.core import ContractError, digest, require

MAX_INPUT_BYTES = 10_000_000
MAX_MEMBER_BYTES = 8_000_000
MAX_EXPANDED_BYTES = 40_000_000
MAX_MEMBERS = 256
MAX_XML_NODES = 200_000
KINDS = {"heading1", "heading2", "paragraph", "code", "list", "table", "image"}
STATUSES = {"needs_review", "needs_evidence", "confirmed", "draft", "blocked",
            "unknown", "invalidated", "not_applicable"}
IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_.:-]{0,127}"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
NS = {"w": W, "r": R, "wp": WP, "a": A, "pic": PIC}
ANCHOR = re.compile(r"^\s*<!--\s*(block:" + IDENTIFIER + r"(?:\s+[^<>]+)?)\s*-->\s*$")
IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^\n()]*)\)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\n]*)$")
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*)$")
LIST = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+")
HTML = re.compile(r"<\s*(?:/?[A-Za-z][A-Za-z0-9-]*(?:\s|/?>)|!|\?)")


def _text(value: object) -> str:
    require(isinstance(value, str) and "\x00" not in value,
            "revision_text_required")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise ContractError("revision_invalid_unicode") from exc
    require(size <= MAX_INPUT_BYTES, "revision_input_size")
    return value


class _Blocks:
    def __init__(self, format_name: str):
        self.format = format_name
        self.blocks: list[dict] = []
        self.images: list[dict] = []
        self.identities: set[str] = set()
        self.occurrences: Counter = Counter()

    def add(self, kind: str, text: str, source: dict, anchor: dict | None = None,
            **extra) -> dict:
        anchor = anchor or {}
        content = {"kind": kind, "text": text, **extra}
        fingerprint = digest(content)[:24]
        self.occurrences[fingerprint] += 1
        identity = anchor.get("id", f"blk-{fingerprint}-{self.occurrences[fingerprint]}")
        require(identity not in self.identities, "revision_duplicate_block_id")
        self.identities.add(identity)
        evidence = list(anchor.get("evidence_ids", []))
        status = anchor.get("status", "needs_review")
        if status == "confirmed" and not evidence:
            status = "needs_review"
        block = {"id": identity, **content, "evidence_ids": evidence,
                 "status": status, "source": {"format": self.format, **source}}
        if anchor.get("operation_id"):
            block["operation_id"] = anchor["operation_id"]
        self.blocks.append(block)
        return block

    def image(self, row: dict) -> None:
        if not any(item["image_id"] == row["image_id"] for item in self.images):
            self.images.append(row)

    def result(self, **metadata) -> dict:
        require(bool(self.blocks), "revision_document_empty")
        title = next((b["text"] for b in self.blocks if b["kind"] == "heading1"), None)
        return {"blocks": self.blocks, "images": self.images,
                "metadata": {"format": self.format, "title": title,
                             "layout_preserved": False,
                             "identity_verification": "not_performed", **metadata}}


def _anchor(line: str) -> dict:
    match = ANCHOR.fullmatch(line)
    require(match is not None, "revision_markdown_comment_unsupported")
    fields = {}
    for entry in match[1].split():
        require(":" in entry, "revision_anchor_invalid")
        key, value = entry.split(":", 1)
        require(key in {"block", "evidence", "status", "operation"}
                and key not in fields and bool(value), "revision_anchor_invalid")
        fields[key] = value
    require(re.fullmatch(IDENTIFIER, fields.get("block", "")) is not None,
            "revision_anchor_invalid")
    evidence = fields.get("evidence", "").split(",") if "evidence" in fields else []
    require(all(re.fullmatch(IDENTIFIER, item) for item in evidence)
            and len(set(evidence)) == len(evidence), "revision_anchor_evidence_invalid")
    status = fields.get("status", "needs_review")
    require(status in STATUSES, "revision_anchor_status_invalid")
    operation = fields.get("operation")
    require(operation is None or re.fullmatch(IDENTIFIER, operation) is not None,
            "revision_anchor_operation_invalid")
    return {"id": fields["block"], "evidence_ids": evidence, "status": status,
            **({"operation_id": operation} if operation else {})}


def _relative_png(value: str) -> str:
    # 编码后的父目录、协议及Windows路径同样不能成为上层的读文件指令。
    require(isinstance(value, str) and bool(value), "revision_png_reference_invalid")
    decoded = unquote(value)
    require(decoded == value and not any(char.isspace() for char in value)
            and not any(char in value for char in "\\:\x00?#<>\"'")
            and not value.startswith("/")
            and all(part not in {"", ".", ".."} for part in value.split("/"))
            and value.lower().endswith(".png"), "revision_png_reference_unsafe")
    return value


def _markdown_inline(builder: _Blocks, kind: str, text: str, source: dict,
                     anchor: dict | None) -> None:
    require(HTML.search(text) is None and "<!--" not in text,
            "revision_markdown_html_unsupported")
    matches = list(IMAGE.finditer(text))
    remainder = IMAGE.sub("", text)
    require("![" not in remainder, "revision_markdown_image_unsupported")
    if not matches:
        builder.add(kind, text, source, anchor)
        return
    require(kind == "paragraph", "revision_markdown_image_context_unsupported")
    cursor = 0
    used_anchor = False
    for match in matches:
        prefix = text[cursor:match.start()]
        if prefix:
            builder.add(kind, prefix, source, anchor if not used_anchor else
                        {k: v for k, v in (anchor or {}).items() if k != "id"})
            used_anchor = True
        reference = _relative_png(match[2])
        image_id = "img-" + hashlib.sha256(reference.encode("utf-8")).hexdigest()
        builder.image({"image_id": image_id, "path": reference,
                       "reference_path": reference, "png": None,
                       "content_status": "awaiting_authorized_read"})
        builder.add("image", match[1], source, anchor if not used_anchor else
                    {k: v for k, v in (anchor or {}).items() if k != "id"},
                    image_id=image_id, reference_path=reference)
        used_anchor = True
        cursor = match.end()
    if cursor < len(text):
        builder.add(kind, text[cursor:], source,
                    {k: v for k, v in (anchor or {}).items() if k != "id"})


def _table_cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [cell.replace("\\|", "|").strip()
            for cell in re.split(r"(?<!\\)\|", line)]


def _table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return len(cells) > 1 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def parse_markdown(text: str) -> dict:
    """解析H1/H2、段落、连续列表、围栏代码、管道表格与段内相对PNG。

    返回的Markdown图片png为None，只是待授权引用；本函数不尝试读盘。
    块ID由显式注释或内容哈希及同文出现次数产生，重排保持内容ID稳定。
    其他Markdown行内标记作为原文本保留，HTML和含糊的图片语法拒绝。
    """
    text = _text(text)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    builder = _Blocks("markdown")
    pending = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if "<!--" in line:
            require(pending is None, "revision_anchor_without_block")
            pending = _anchor(line)
            index += 1
            continue
        start = index
        fence = FENCE.fullmatch(line)
        heading = HEADING.fullmatch(line)
        kind = "paragraph"
        extra = {}
        if fence:
            kind = "code"
            marker, language = fence.groups()
            require("`" not in language if marker[0] == "`" else True,
                    "revision_markdown_fence_invalid")
            index += 1
            contents = []
            closing = re.compile(r"^ {0,3}" + re.escape(marker[0])
                                 + "{" + str(len(marker)) + r",}\s*$")
            while index < len(lines) and not closing.fullmatch(lines[index]):
                contents.append(lines[index])
                index += 1
            require(index < len(lines), "revision_markdown_fence_unclosed")
            index += 1
            value = "\n".join(contents)
            extra = {"language": language.strip()}
        elif heading:
            require(len(heading[1]) <= 2, "revision_markdown_heading_unsupported")
            kind = "heading" + str(len(heading[1]))
            value = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2])
            index += 1
        elif index + 1 < len(lines) and _table_separator(lines[index + 1]):
            kind = "table"
            rows = [_table_cells(line)]
            require(len(rows[0]) == len(_table_cells(lines[index + 1])),
                    "revision_markdown_table_width")
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                row = _table_cells(lines[index])
                require(len(row) == len(rows[0]), "revision_markdown_table_width")
                rows.append(row)
                index += 1
            value = "\n".join("\t".join(row) for row in rows)
            extra = {"cells": rows}
        elif LIST.match(line):
            kind = "list"
            contents = [line]
            index += 1
            while index < len(lines) and lines[index].strip():
                following = lines[index]
                if LIST.match(following) or following.startswith(("  ", "\t")):
                    contents.append(following)
                    index += 1
                else:
                    break
            value = "\n".join(contents)
        else:
            contents = [line]
            index += 1
            while index < len(lines) and lines[index].strip():
                following = lines[index]
                if ("<!--" in following or FENCE.fullmatch(following)
                        or HEADING.fullmatch(following) or LIST.match(following)
                        or (index + 1 < len(lines)
                            and _table_separator(lines[index + 1]))):
                    break
                contents.append(following)
                index += 1
            value = "\n".join(contents)
        source = {"line_start": start + 1, "line_end": index}
        if kind == "code":
            builder.add(kind, value, source, pending, **extra)
        else:
            require(HTML.search(value) is None and "<!--" not in value,
                    "revision_markdown_html_unsupported")
            if extra:
                require("![" not in value, "revision_markdown_image_context_unsupported")
                builder.add(kind, value, source, pending, **extra)
            else:
                _markdown_inline(builder, kind, value, source, pending)
        pending = None
    require(pending is None, "revision_anchor_without_block")
    return builder.result()


def _xml(raw: bytes) -> ET.Element:
    try:
        text = raw.decode("utf-8-sig")
        require("<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(),
                "revision_docx_xml_dtd")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("revision_docx_xml_invalid") from exc
    count = 0
    stack = [(root, 0)]
    while stack:
        element, depth = stack.pop()
        count += 1
        require(count <= MAX_XML_NODES and depth <= 64, "revision_docx_xml_limit")
        stack.extend((child, depth + 1) for child in element)
    return root


def _member_path(name: str) -> None:
    require(bool(name) and not name.startswith("/") and "\\" not in name
            and ":" not in name and "\x00" not in name
            and unquote(name) == name
            and all(p not in {"", ".", ".."} for p in name.rstrip("/").split("/")),
            "revision_docx_member_path")


def _package(raw: bytes) -> dict[str, bytes]:
    require(isinstance(raw, bytes), "revision_docx_bytes_required")
    require(0 < len(raw) <= MAX_INPUT_BYTES, "revision_input_size")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            members = package.infolist()
            names = [entry.filename for entry in members]
            require(0 < len(members) <= MAX_MEMBERS
                    and len({n.casefold() for n in names}) == len(names),
                    "revision_docx_members")
            require(sum(entry.file_size for entry in members) <= MAX_EXPANDED_BYTES,
                    "revision_docx_expansion_limit")
            result = {}
            for entry in members:
                _member_path(entry.filename)
                lower = entry.filename.lower()
                require(not any(token in lower for token in
                                ("vbaproject", "activex", "embeddings/", ".bin")),
                        "revision_docx_active_content")
                require(not entry.flag_bits & 1
                        and entry.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                        and entry.file_size <= MAX_MEMBER_BYTES
                        and (entry.external_attr >> 16) & 0o170000 != 0o120000,
                        "revision_docx_member_unsupported")
                if not entry.is_dir():
                    result[entry.filename] = package.read(entry)
            return result
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError,
            NotImplementedError, zlib.error, EOFError) as exc:
        raise ContractError("revision_docx_package_invalid") from exc


def _relationships(parts: dict[str, bytes]) -> dict[str, dict[str, dict]]:
    output = {}
    for name, raw in parts.items():
        if not name.endswith(".rels"):
            continue
        root = _xml(raw)
        require(root.tag == "{" + REL + "}Relationships", "revision_docx_relationships")
        rows = {}
        base = "" if name == "_rels/.rels" else posixpath.dirname(
            posixpath.dirname(name))
        for node in root:
            require(node.tag == "{" + REL + "}Relationship"
                    and set(node.attrib) <= {"Id", "Type", "Target", "TargetMode"},
                    "revision_docx_relationships")
            require(node.get("TargetMode", "Internal") == "Internal",
                    "revision_docx_external_relationship")
            identity, target = node.get("Id"), node.get("Target", "")
            require(bool(identity) and identity not in rows, "revision_docx_relationships")
            _member_path(target)
            resolved = posixpath.join(base, target)
            require(resolved in parts, "revision_docx_relationship_target_missing")
            rows[identity] = {"type": node.get("Type", ""), "target": resolved}
        output[name] = rows
    return output


def _children(node: ET.Element, namespace: str, allowed: set[str]) -> None:
    require(not node.text or not node.text.strip(), "revision_docx_unexpected_text")
    for child in node:
        require(child.tag.startswith("{" + namespace + "}")
                and child.tag.split("}", 1)[1] in allowed,
                "revision_docx_body_object_unsupported")
        require(not child.tail or not child.tail.strip(), "revision_docx_unexpected_text")


P_PROPERTIES = {"pStyle", "numPr", "keepNext", "keepLines", "pageBreakBefore",
                "spacing", "ind", "jc", "outlineLvl", "tabs", "widowControl",
                "contextualSpacing", "bidi", "rPr", "sectPr", "pBdr", "shd",
                "textAlignment", "snapToGrid", "suppressLineNumbers"}
R_PROPERTIES = {"rStyle", "rFonts", "b", "bCs", "i", "iCs", "u", "strike",
                "dstrike", "color", "sz", "szCs", "lang", "spacing", "kern",
                "position", "vertAlign", "highlight", "shd", "rtl", "cs",
                "noProof", "snapToGrid", "caps", "smallCaps", "emboss",
                "imprint", "outline", "shadow", "fitText"}
FORBIDDEN = {"txbxContent", "textbox", "anchor", "object", "oleObject", "OLEObject",
             "pict", "altChunk", "ins", "del", "moveFrom", "moveTo", "delText",
             "pPrChange", "rPrChange", "sectPrChange", "tblPrChange", "trPrChange",
             "tcPrChange", "cellIns", "cellDel", "cellMerge", "sdt", "contentPart"}


def _validate_word_tree(root: ET.Element) -> None:
    """属性只能携带已知格式项，不能在忽略的格式容器内藏入正文对象。"""
    containers = {
        "document": {"body"}, "body": {"p", "tbl", "sectPr"},
        "hdr": {"p"}, "ftr": {"p"},
        "p": {"pPr", "r", "bookmarkStart", "bookmarkEnd", "proofErr", "fldSimple"},
        "r": {"rPr", "t", "tab", "br", "cr", "drawing", "lastRenderedPageBreak",
              "noBreakHyphen", "softHyphen", "fldChar", "instrText"},
        "fldSimple": {"r"}, "pPr": P_PROPERTIES, "rPr": R_PROPERTIES,
        "numPr": {"ilvl", "numId"}, "tabs": {"tab"},
        "pBdr": {"top", "left", "bottom", "right", "between", "bar"},
        "sectPr": {"headerReference", "footerReference", "pgSz", "pgMar", "cols",
                   "docGrid", "type", "titlePg", "pgNumType", "bidi", "rtlGutter",
                   "paperSrc", "vAlign"},
        "cols": {"col"}, "tbl": {"tblPr", "tblGrid", "tr"},
        "tblPr": {"tblStyle", "tblW", "jc", "tblInd", "tblBorders", "shd",
                  "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription"},
        "tblBorders": {"top", "left", "bottom", "right", "insideH", "insideV",
                       "start", "end"},
        "tblCellMar": {"top", "left", "bottom", "right", "start", "end"},
        "tblGrid": {"gridCol"}, "tr": {"trPr", "tc"},
        "trPr": {"cantSplit", "tblHeader", "trHeight", "jc", "hidden"},
        "tc": {"tcPr", "p"},
        "tcPr": {"tcW", "gridSpan", "vMerge", "tcBorders", "shd", "noWrap",
                 "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark"},
        "tcBorders": {"top", "left", "bottom", "right", "insideH", "insideV",
                      "start", "end", "tl2br", "tr2bl"},
        "tcMar": {"top", "left", "bottom", "right", "start", "end"},
    }
    leaves = set().union(*containers.values()) - containers.keys() - {"drawing"}
    for node in root.iter():
        if node.tag == "{" + W + "}drawing":
            continue
        if not node.tag.startswith("{" + W + "}"):
            # DrawingML在图像解析器逐项校验，其他命名空间不在正文子集中。
            require(node.tag.startswith(tuple("{" + ns + "}" for ns in (WP, A, PIC))),
                    "revision_docx_body_object_unsupported")
            continue
        local = node.tag.split("}", 1)[1]
        require(local in containers or local in leaves,
                "revision_docx_body_object_unsupported")
        if local in {"t", "instrText"}:
            require(not list(node), "revision_docx_body_object_unsupported")
        else:
            _children(node, W, containers.get(local, set()))
        if local == "hidden":
            require(node.get("{" + W + "}val") in {"0", "false", "off"},
                    "revision_docx_hidden_content")


def _properties(node: ET.Element) -> None:
    local = node.tag.split("}")[-1]
    if local == "pPr":
        _children(node, W, P_PROPERTIES)
    elif local == "rPr":
        _children(node, W, R_PROPERTIES)
    for child in node:
        name = child.tag.split("}")[-1]
        if name == "numPr":
            _children(child, W, {"ilvl", "numId"})
            require(all(re.fullmatch(r"\d+", e.get("{" + W + "}val", ""))
                        for e in child), "revision_docx_numbering_invalid")
        if name == "rPr":
            _properties(child)
        if name == "sectPr":
            _section(child)


def _section(node: ET.Element) -> None:
    _children(node, W, {"headerReference", "footerReference", "pgSz", "pgMar",
                        "cols", "docGrid", "type", "titlePg", "pgNumType",
                        "bidi", "rtlGutter", "paperSrc", "vAlign"})


def _styles(parts: dict[str, bytes]) -> dict[str, str]:
    if "word/styles.xml" not in parts:
        return {}
    root = _xml(parts["word/styles.xml"])
    require(root.tag == "{" + W + "}styles", "revision_docx_styles_invalid")
    definitions = {}
    for style in root.findall("w:style", NS):
        identity = style.get("{" + W + "}styleId")
        require(identity and identity not in definitions, "revision_docx_styles_invalid")
        for properties in style.findall("w:pPr", NS) + style.findall("w:rPr", NS):
            _properties(properties)
        name = style.find("w:name", NS)
        based = style.find("w:basedOn", NS)
        outline = style.find("w:pPr/w:outlineLvl", NS)
        definitions[identity] = {
            "name": name.get("{" + W + "}val", "") if name is not None else "",
            "based": based.get("{" + W + "}val") if based is not None else None,
            "outline": outline.get("{" + W + "}val") if outline is not None else None,
        }
    output = {}
    for identity in definitions:
        current, seen, kind = identity, set(), "paragraph"
        while current in definitions:
            require(current not in seen, "revision_docx_style_cycle")
            seen.add(current)
            row = definitions[current]
            names = {current.lower().replace(" ", ""), row["name"].lower().replace(" ", "")}
            if names & {"heading1", "标题1"} or row["outline"] == "0":
                kind = "heading1"
                break
            if names & {"heading2", "标题2"} or row["outline"] == "1":
                kind = "heading2"
                break
            if names & {"code", "sourcecode"}:
                kind = "code"
                break
            require(not any(re.fullmatch(r"heading[3-9]", n) for n in names)
                    and row["outline"] in {None, "9"},
                    "revision_docx_heading_unsupported")
            current = row["based"]
        output[identity] = kind
    return output


def _png(raw: bytes) -> tuple[int, int]:
    require(33 <= len(raw) <= MAX_MEMBER_BYTES and raw[:16] ==
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "revision_docx_png_invalid")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", raw[16:29])
    require(0 < width <= 20000 and 0 < height <= 20000
            and width * height <= 40_000_000
            and depth in {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
                          4: {8, 16}, 6: {8, 16}}.get(color, set())
            and compression == filtering == 0 and interlace in {0, 1},
            "revision_docx_png_invalid")
    offset, has_data = 8, False
    while offset + 12 <= len(raw):
        size = struct.unpack(">I", raw[offset:offset + 4])[0]
        end = offset + size + 12
        require(end <= len(raw), "revision_docx_png_invalid")
        tag = raw[offset + 4:offset + 8]
        require(struct.unpack(">I", raw[end - 4:end])[0] ==
                zlib.crc32(raw[offset + 4:end - 4]), "revision_docx_png_invalid")
        require(tag != b"IHDR" or offset == 8, "revision_docx_png_invalid")
        if tag == b"IDAT" and size:
            has_data = True
        if tag == b"IEND":
            require(size == 0 and has_data and end == len(raw), "revision_docx_png_invalid")
            return width, height
        offset = end
    raise ContractError("revision_docx_png_invalid")


def _drawing(node: ET.Element, builder: _Blocks, parts: dict, rels: dict) -> dict:
    _children(node, WP, {"inline"})
    require(len(node) == 1, "revision_docx_inline_image_required")
    allowed = {
        WP: {"inline", "extent", "effectExtent", "docPr", "cNvGraphicFramePr"},
        A: {"graphic", "graphicData", "graphicFrameLocks", "picLocks", "blip",
            "stretch", "fillRect", "srcRect", "xfrm", "off", "ext", "prstGeom",
            "avLst", "ln", "noFill", "solidFill", "srgbClr"},
        PIC: {"pic", "nvPicPr", "cNvPr", "cNvPicPr", "blipFill", "spPr"},
    }
    for child in node.iter():
        if child is node:
            continue
        require(child.tag.startswith("{") and "}" in child.tag,
                "revision_docx_drawing_unsupported")
        namespace, local = child.tag[1:].split("}", 1)
        require(local in allowed.get(namespace, set()),
                "revision_docx_drawing_unsupported")
        require(not child.text or not child.text.strip(), "revision_docx_drawing_unsupported")
        if child.tag == "{" + A + "}graphicData":
            require(child.get("uri") == PIC, "revision_docx_drawing_unsupported")
    blips = node.findall(".//a:blip", NS)
    require(len(blips) == 1 and set(blips[0].attrib) <= {"{" + R + "}embed", "cstate"},
            "revision_docx_inline_image_required")
    relation = rels.get(blips[0].get("{" + R + "}embed"))
    require(relation is not None and relation["type"] == R + "/image"
            and relation["target"].lower().endswith(".png"),
            "revision_docx_png_relationship_required")
    raw = parts[relation["target"]]
    width, height = _png(raw)
    sha = hashlib.sha256(raw).hexdigest()
    image_id = "img-" + sha
    builder.image({"image_id": image_id, "sha256": sha, "png": raw,
                   "width": width, "height": height,
                   "source_part": relation["target"]})
    properties = node.find(".//wp:docPr", NS)
    text = properties.get("descr", properties.get("title", "")) if properties is not None else ""
    return {"image_id": image_id, "text": text}


def _bookmark(node: ET.Element) -> dict | None:
    for bookmark in node.findall(".//w:bookmarkStart", NS):
        name = bookmark.get("{" + W + "}name", "")
        if not name.startswith("_") and re.fullmatch(IDENTIFIER, name):
            return {"id": name}
    return None


def _paragraph(node: ET.Element, styles: dict, builder: _Blocks, parts: dict,
               rels: dict, source: dict, *, auxiliary: bool = False) -> list[dict]:
    _children(node, W, {"pPr", "r", "bookmarkStart", "bookmarkEnd", "proofErr", "fldSimple"}
              if auxiliary else {"pPr", "r", "bookmarkStart", "bookmarkEnd", "proofErr"})
    properties = node.find("w:pPr", NS)
    kind, extra = "paragraph", {}
    if properties is not None:
        _properties(properties)
        style = properties.find("w:pStyle", NS)
        identity = style.get("{" + W + "}val", "") if style is not None else ""
        kind = styles.get(identity, {"Heading1": "heading1", "Heading2": "heading2",
                                     "Code": "code"}.get(identity, "paragraph"))
        outline = properties.find("w:outlineLvl", NS)
        if outline is not None:
            value = outline.get("{" + W + "}val")
            require(value in {"0", "1", "9"}, "revision_docx_heading_unsupported")
            if value in {"0", "1"}:
                kind = "heading" + str(int(value) + 1)
        numbering = properties.find("w:numPr", NS)
        if numbering is not None:
            kind = "list"
            extra = {"numbering_id": numbering.find("w:numId", NS).get("{" + W + "}val")
                     if numbering.find("w:numId", NS) is not None else None,
                     "list_level": numbering.find("w:ilvl", NS).get("{" + W + "}val", "0")
                     if numbering.find("w:ilvl", NS) is not None else "0"}
    events, text, field = [], [], None
    field_instruction = []
    for child in node:
        if child.tag == "{" + W + "}fldSimple":
            require(auxiliary and child.get("{" + W + "}instr", "").strip() == "PAGE",
                    "revision_docx_field_unsupported")
            require(all(item.tag in {"{" + W + "}" + tag for tag in
                                     {"fldSimple", "r", "rPr", "t", "tab", "br", "cr"}
                                     | R_PROPERTIES}
                        for item in child.iter()), "revision_docx_field_unsupported")
            continue
        if child.tag != "{" + W + "}r":
            continue
        _children(child, W, {"rPr", "t", "tab", "br", "cr", "drawing",
                             "lastRenderedPageBreak", "noBreakHyphen", "softHyphen",
                             "fldChar", "instrText"} if auxiliary else
                  {"rPr", "t", "tab", "br", "cr", "drawing", "lastRenderedPageBreak",
                   "noBreakHyphen", "softHyphen"})
        for item in child:
            local = item.tag.split("}")[-1]
            if local == "rPr":
                _properties(item)
            elif local == "fldChar":
                field_type = item.get("{" + W + "}fldCharType")
                if field_type == "begin":
                    require(field is None, "revision_docx_field_unsupported")
                    field, field_instruction = "instruction", []
                elif field_type == "separate":
                    require(field == "instruction" and "".join(field_instruction).strip() == "PAGE",
                            "revision_docx_field_unsupported")
                    field = "cache"
                elif field_type == "end":
                    require(field == "cache", "revision_docx_field_unsupported")
                    field = None
                else:
                    raise ContractError("revision_docx_field_unsupported")
            elif local == "instrText":
                require(field == "instruction", "revision_docx_field_unsupported")
                field_instruction.append(item.text or "")
            elif field is not None:
                require(local in {"t", "tab", "br", "cr"}, "revision_docx_field_unsupported")
            elif local == "drawing":
                require(not auxiliary, "revision_docx_auxiliary_image_unsupported")
                if text:
                    events.append({"kind": kind, "text": "".join(text), **extra})
                    text = []
                events.append({"kind": "image", **_drawing(item, builder, parts, rels)})
            elif local == "t":
                require(not list(item), "revision_docx_body_object_unsupported")
                text.append(item.text or "")
            elif local in {"tab", "br", "cr", "noBreakHyphen", "softHyphen"}:
                text.append({"tab": "\t", "br": "\n", "cr": "\n",
                             "noBreakHyphen": "\u2011", "softHyphen": "\u00ad"}[local])
    require(field is None, "revision_docx_field_unsupported")
    if text or not events:
        events.append({"kind": kind, "text": "".join(text), **extra})
    if auxiliary:
        return events
    anchor = _bookmark(node)
    for index, event in enumerate(events):
        # 普通空段落仅承载Word间距；代码段的空白属于原文内容。
        if event["kind"] == "paragraph" and not event["text"].strip():
            continue
        builder.add(event["kind"], event["text"], source,
                    anchor if index == 0 else None,
                    **{k: v for k, v in event.items() if k not in {"kind", "text"}})
    return events


def _table(node: ET.Element, styles: dict, builder: _Blocks, parts: dict,
           rels: dict, source: dict) -> None:
    _children(node, W, {"tblPr", "tblGrid", "tr"})
    rows = []
    for row_index, row in enumerate(node.findall("w:tr", NS), 1):
        _children(row, W, {"trPr", "tc"})
        cells = []
        for cell_index, cell in enumerate(row.findall("w:tc", NS), 1):
            _children(cell, W, {"tcPr", "p"})
            values = []
            for paragraph in cell.findall("w:p", NS):
                temporary = _Blocks("docx")
                _paragraph(paragraph, styles, temporary, parts, rels,
                           {**source, "row": row_index, "cell": cell_index})
                require(not temporary.images, "revision_docx_table_image_unsupported")
                values.extend(block["text"] for block in temporary.blocks)
            cells.append("\n".join(values))
        require(bool(cells), "revision_docx_table_invalid")
        rows.append(cells)
    require(bool(rows), "revision_docx_table_invalid")
    builder.add("table", "\n".join("\t".join(row) for row in rows), source,
                _bookmark(node), cells=rows)


def parse_docx(raw: bytes) -> dict:
    """读取受支持的DOCX正文及行内PNG，全部操作在内存完成。

    不导入批注、脚注、文本框、浮动图、链接、修订、公式、图表或嵌入对象；
    遇到这些结构拒绝整稿。页眉/页脚文本保留在metadata，PAGE域忽略。
    书签仅作为ID，不作为来源证明；所有DOCX块初始为needs_review。
    """
    parts = _package(raw)
    require({"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= parts.keys(),
            "revision_docx_main_part_required")
    allowed = re.compile(
        r"(?:\[Content_Types\]\.xml|_rels/\.rels|docProps/(?:core|app|custom)\.xml|"
        r"word/(?:document|styles|numbering|settings|webSettings|fontTable)\.xml|"
        r"word/(?:header|footer)\d+\.xml|word/theme/theme\d+\.xml|"
        r"word/media/[^/]+\.png|word/_rels/(?:document|header\d+|footer\d+)\.xml\.rels)")
    roots = {}
    for name, content in parts.items():
        require(allowed.fullmatch(name) is not None, "revision_docx_part_unsupported")
        if name.endswith((".xml", ".rels")):
            root = _xml(content)
            roots[name] = root
            for node in root.iter():
                local = node.tag.split("}")[-1]
                require(local not in FORBIDDEN and not local.endswith("Change")
                        and local not in {"vanish", "webHidden", "specVanish"},
                        "revision_docx_body_object_unsupported")
            require(not any("macroenabled" in value.lower()
                            or "vba" in value.lower() or "oleobject" in value.lower()
                            for element in root.iter() for value in element.attrib.values()),
                    "revision_docx_active_content")
    relations = _relationships(parts)
    root_links = relations.get("_rels/.rels", {})
    require(sum(row["type"] == R + "/officeDocument"
                and row["target"] == "word/document.xml" for row in root_links.values()) == 1,
            "revision_docx_main_relationship_required")
    rels = relations.get("word/_rels/document.xml.rels", {})
    allowed_types = {R + "/" + kind for kind in
                     ("styles", "numbering", "settings", "webSettings", "fontTable",
                      "theme", "header", "footer", "image", "officeDocument",
                      "extended-properties", "custom-properties")}
    allowed_types.add("http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties")
    require(all(row["type"] in allowed_types
                for collection in relations.values() for row in collection.values()),
            "revision_docx_relationship_unsupported")
    document = roots["word/document.xml"]
    require(document.tag == "{" + W + "}document", "revision_docx_document_invalid")
    _validate_word_tree(document)
    _children(document, W, {"body"})
    require(len(document) == 1, "revision_docx_document_invalid")
    body = document[0]
    _children(body, W, {"p", "tbl", "sectPr"})
    styles, builder = _styles(parts), _Blocks("docx")
    for index, node in enumerate(body, 1):
        source = {"part": "word/document.xml", "body_index": index}
        if node.tag == "{" + W + "}p":
            _paragraph(node, styles, builder, parts, rels, source)
        elif node.tag == "{" + W + "}tbl":
            _table(node, styles, builder, parts, rels, source)
        else:
            _section(node)
    auxiliary = {}
    for name, root in roots.items():
        if not re.fullmatch(r"word/(header|footer)\d+\.xml", name):
            continue
        require(root.tag in {"{" + W + "}hdr", "{" + W + "}ftr"},
                "revision_docx_auxiliary_invalid")
        _validate_word_tree(root)
        _children(root, W, {"p"})
        texts = []
        for node in root:
            events = _paragraph(node, styles, builder, parts, rels, {"part": name},
                                auxiliary=True)
            texts.extend(event["text"] for event in events if event["text"])
        auxiliary[name] = "\n".join(texts)
    return builder.result(auxiliary_text=auxiliary)


def _validate_blocks(blocks: list) -> None:
    require(isinstance(blocks, list), "revision_blocks_required")
    identities = set()
    for block in blocks:
        require(isinstance(block, dict)
                and {"id", "kind", "text", "evidence_ids", "status"} <= block.keys(),
                "revision_block_invalid")
        require(isinstance(block["id"], str) and bool(block["id"])
                and block["id"] not in identities, "revision_duplicate_block_id")
        identities.add(block["id"])
        require(isinstance(block["kind"], str) and block["kind"] in KINDS
                and isinstance(block["text"], str)
                and isinstance(block["status"], str) and block["status"] in STATUSES
                and isinstance(block["evidence_ids"], list)
                and all(isinstance(value, str) and bool(value)
                        for value in block["evidence_ids"]), "revision_block_invalid")
        if block["kind"] == "image":
            require(isinstance(block.get("image_id"), str) and bool(block["image_id"]),
                    "revision_image_id_required")


def diff_blocks(previous: list, current: list) -> dict:
    """比较快照，不修改输入；名称/版本等metadata由调用方另行比较。

    先按ID匹配；未锚定的改写再按同种块的相对顺序作启发式配对，显式记录
    matching，不能将启发式关联当作原作者确认。增删不会单独制造重排。
    """
    _validate_blocks(previous)
    _validate_blocks(current)
    old = {block["id"]: (i, block) for i, block in enumerate(previous)}
    new = {block["id"]: (i, block) for i, block in enumerate(current)}
    pairs = [(old[key][0], new[key][0], "id") for key in old.keys() & new.keys()]
    unmatched_old = [(i, b) for i, b in enumerate(previous) if b["id"] not in new]
    unmatched_new = [(i, b) for i, b in enumerate(current) if b["id"] not in old]
    # 仅自动生成的ID可启发式续接；删除一个显式锚点再新增另一锚点不伪称改写。
    eligible_old = [(i, b) for i, b in unmatched_old if b["id"].startswith("blk-")]
    eligible_new = [(i, b) for i, b in unmatched_new if b["id"].startswith("blk-")]
    matcher = difflib.SequenceMatcher(None,
                                     [b["kind"] for _, b in eligible_old],
                                     [b["kind"] for _, b in eligible_new], autojunk=False)
    for match in matcher.get_matching_blocks():
        for offset in range(match.size):
            pairs.append((eligible_old[match.a + offset][0],
                          eligible_new[match.b + offset][0], "kind_order_heuristic"))
    pairs.sort()
    paired_old, paired_new = {a for a, _, _ in pairs}, {b for _, b, _ in pairs}
    added = [copy.deepcopy(b) for i, b in enumerate(current) if i not in paired_new]
    removed = [copy.deepcopy(b) for i, b in enumerate(previous) if i not in paired_old]
    changes = {name: [] for name in ("rewritten", "reordered", "images_changed",
                                     "evidence_changed", "source_changed",
                                     "status_changed", "operation_changed")}
    ranks = {index: rank for rank, index in enumerate(sorted(b for _, b, _ in pairs))}
    for old_rank, (a, b, matching) in enumerate(pairs):
        before, after = previous[a], current[b]
        binding = {"before_id": before["id"], "after_id": after["id"],
                   "matching": matching}
        for key, fields in (
                ("rewritten", ("kind", "text", "cells", "language", "list_level", "numbering_id")),
                ("images_changed", ("image_id", "sha256", "reference_path")),
                ("evidence_changed", ("evidence_ids",)),
                ("source_changed", ("source",)),
                ("status_changed", ("status",)),
                ("operation_changed", ("operation_id",))):
            if any(before.get(field) != after.get(field) for field in fields):
                changes[key].append({**binding,
                                     "before": {f: copy.deepcopy(before.get(f)) for f in fields},
                                     "after": {f: copy.deepcopy(after.get(f)) for f in fields}})
        if old_rank != ranks[b]:
            changes["reordered"].append({**binding, "before_index": a, "after_index": b})
    changed = bool(added or removed or any(changes.values()))
    return {"changed": changed, "added": added, "removed": removed, **changes,
            "matches": [{"before_id": previous[a]["id"], "after_id": current[b]["id"],
                         "matching": matching} for a, b, matching in pairs],
            "metadata_comparison": "caller_responsibility"}
