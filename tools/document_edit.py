"""SE-06／SP-07：同样式文本段落与明确映射表格的受限DOCX新副本修改。

全部计划预检后才写新副本，只替换受支持文本节点的UTF-8字节区间；保留
非目标部件原始字节和样式。域、修订、公式、文本框、混合样式及控制对象
写前拒绝；本生成器v2页眉／PAGE页脚可原样保留，不执行或刷新域。
"""
from __future__ import annotations

import argparse
import copy
import io
import json
from pathlib import Path
import re
import zipfile
from xml.parsers import expat
from xml.sax.saxutils import escape

from tools import document_review as review
from tools.core import ContractError, digest, require, require_fields, sha256_bytes
from tools.standard_sources import (
    authorize_io, load_cli_request, new_output_path, read_bound, scoped_path, write_report,
)

VERSION = "1.1"
W = "{" + review.W + "}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
MAX_OPERATIONS = 256
SAFE_PROPERTIES = {
    "pPr", "rPr", "pStyle", "rStyle", "keepNext", "keepLines", "pageBreakBefore",
    "widowControl", "spacing", "ind", "jc", "outlineLvl", "contextualSpacing",
    "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
    "color", "sz", "szCs", "highlight", "u", "vertAlign", "lang", "kern",
    "shd", "bdr", "position", "snapToGrid", "noProof", "textAlignment",
}


def _tag_end(raw, start):
    quote = None
    for index in range(start, len(raw)):
        char = raw[index]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in (34, 39):
            quote = char
        elif char == 62:
            return index + 1
    raise ContractError("docx_start_tag_invalid")


def _text_spans(raw):
    """Expat字节定位与语义节点配对；空t节点只在明确目标处展开。"""
    try:
        raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ContractError("edit_utf8_xml_required") from exc
    require(b"\x00" not in raw, "edit_utf8_xml_required")
    declaration = re.match(br"\s*<\?xml[^?]+\?>", raw.lstrip(b"\xef\xbb\xbf"))
    if declaration:
        encoding = re.search(br"encoding\s*=\s*['\"]([^'\"]+)", declaration.group(), re.I)
        require(encoding is None or encoding.group(1).lower() in {b"utf-8", b"utf8", b"us-ascii"},
                "edit_utf8_xml_required")
    parser = expat.ParserCreate(namespace_separator="}")
    spans, stack = [], []

    def start(name, _attrs):
        if name == review.W + "}t":
            start_at = parser.CurrentByteIndex
            inner = _tag_end(raw, start_at)
            empty = raw[start_at:inner].rstrip().endswith(b"/>")
            stack.append({"start": start_at if empty else inner,
                          "tag_start": start_at, "tag_end": inner, "empty": empty})

    def end(name):
        if name == review.W + "}t":
            require(bool(stack), "text_range_unresolved")
            span = stack.pop()
            span["end"] = span["tag_end"] if span["empty"] else parser.CurrentByteIndex
            spans.append(span)

    def unsupported(*_args):
        raise ContractError("edit_xml_construct_unsupported")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CommentHandler = unsupported
    parser.ProcessingInstructionHandler = unsupported
    parser.StartCdataSectionHandler = unsupported
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as exc:
        raise ContractError("edit_xml_invalid") from exc
    return spans


def _signature(node):
    if node is None:
        return None
    return [node.tag, sorted(node.attrib.items()), node.text or "",
            [_signature(child) for child in node]]


def _properties(parent, name, allowed=SAFE_PROPERTIES):
    props = parent.findall(W + name)
    require(len(props) <= 1, "edit_duplicate_properties")
    if props:
        require(all(node.tag.startswith(W) and node.tag[len(W):] in allowed
                    for node in props[0].iter()), "edit_format_property_unsupported")
    return _signature(props[0]) if props else None


def _paragraph_record(paragraph, *, allow_empty=False):
    require(all(node.tag in {W + "pPr", W + "r", W + "bookmarkStart", W + "bookmarkEnd"}
                for node in paragraph), "edit_paragraph_object_unsupported")
    context = _properties(paragraph, "pPr")
    runs = paragraph.findall(W + "r")
    require(bool(runs) or allow_empty, "edit_mixed_or_empty_runs_unsupported")
    children = list(paragraph)
    if runs:
        first, last = children.index(runs[0]), children.index(runs[-1])
        require(all(node.tag == W + "r" for node in children[first:last + 1]),
                "edit_runs_not_adjacent")
        for node in paragraph:
            if node.tag == W + "bookmarkStart":
                require(children.index(node) < first, "edit_bookmark_not_whole_paragraph")
            elif node.tag == W + "bookmarkEnd":
                require(children.index(node) > last, "edit_bookmark_not_whole_paragraph")
    records = []
    for run in runs:
        require(all(node.tag in {W + "rPr", W + "t"} for node in run),
                "edit_run_object_unsupported")
        texts = run.findall(W + "t")
        require(len(texts) == 1 and not list(texts[0]), "edit_multiple_text_nodes_unsupported")
        require(set(texts[0].attrib) <= {XML_SPACE}, "edit_text_attribute_unsupported")
        properties = {"run_attributes": sorted(run.attrib.items()),
                      "run_properties": _properties(run, "rPr"),
                      "paragraph_context": context}
        records.append({"node": texts[0], "properties": properties,
                        "properties_sha256": digest(properties)})
    require(len({row["properties_sha256"] for row in records}) <= 1,
            "edit_mixed_run_styles_unsupported")
    return {"node": paragraph, "runs": records,
            "text": "".join(row["node"].text or "" for row in records),
            "paragraph_context_sha256": digest(context)}


def _tables(body, paragraph_records):
    tables = []
    table_props = {"tblPr", "tblW", "tblLayout", "tblStyle", "tblLook", "jc", "tblInd",
                   "tblBorders", "top", "left", "bottom", "right", "insideH", "insideV",
                   "tblCellMar", "tblCellSpacing"}
    cell_props = {"tcPr", "tcW", "gridSpan", "vMerge", "shd", "vAlign", "tcBorders",
                  "tcMar", "top", "left", "bottom", "right", "insideH", "insideV"}
    for table_index, table in enumerate(body.findall(W + "tbl"), 1):
        require(all(node.tag in {W + "tblPr", W + "tblGrid", W + "tr"} for node in table),
                "edit_table_object_unsupported")
        _properties(table, "tblPr", table_props)
        grids = table.findall(W + "tblGrid")
        require(len(grids) == 1 and 1 <= len(grids[0]) <= 6
                and all(node.tag == W + "gridCol" and not list(node) for node in grids[0]),
                "edit_table_grid_unsupported")
        width = len(grids[0])
        rows = table.findall(W + "tr")
        require(1 < len(rows) <= review.MAX_BLOCKS, "edit_table_rows_unsupported")
        aliases, owners, previous = {}, [], {}
        for row_index, row in enumerate(rows, 1):
            require(all(node.tag in {W + "trPr", W + "tc"} for node in row),
                    "edit_table_row_object_unsupported")
            _properties(row, "trPr", {"trPr", "cantSplit", "tblHeader", "trHeight"})
            column, current = 1, {}
            for cell in row.findall(W + "tc"):
                require(all(node.tag in {W + "tcPr", W + "p"} for node in cell),
                        "edit_table_cell_object_unsupported")
                _properties(cell, "tcPr", cell_props)
                require(len(cell.findall(W + "p")) == 1, "edit_cell_paragraphs_unsupported")
                p = paragraph_records[id(cell.find(W + "p"))]
                spans = cell.findall("./" + W + "tcPr/" + W + "gridSpan")
                merges = cell.findall("./" + W + "tcPr/" + W + "vMerge")
                require(len(spans) <= 1 and len(merges) <= 1, "edit_table_merge_ambiguous")
                value = spans[0].get(W + "val", "") if spans else "1"
                require(re.fullmatch(r"[1-6]", value) is not None,
                        "edit_table_grid_span_unsupported")
                span = int(value)
                require(column + span - 1 <= width, "edit_table_grid_mismatch")
                merge = merges[0].get(W + "val", "continue") if merges else None
                require(merge in {None, "restart", "continue"}, "edit_table_vertical_merge_unsupported")
                coordinates = range(column, column + span)
                if merge == "continue":
                    candidates = [previous.get(index) for index in coordinates]
                    owner = candidates[0]
                    require(owner is not None and all(item is owner for item in candidates)
                            and owner["column"] == column and owner["column_span"] == span,
                            "edit_table_merge_owner_ambiguous")
                    require(p["text"] == "" and not list(p["node"].iter(W + "bookmarkStart"))
                            and not list(p["node"].iter(W + "bookmarkEnd")),
                            "edit_nonempty_merge_continuation_unsupported")
                    owner["row_span"] += 1
                else:
                    owner = {"table": table_index, "row": row_index, "column": column,
                             "column_span": span, "row_span": 1, "paragraph_record": p}
                    owners.append(owner)
                for index in coordinates:
                    aliases[(row_index, index)] = owner
                    if merge is not None:
                        current[index] = owner
                column += span
            require(column == width + 1, "edit_table_grid_mismatch")
            previous = current
        tables.append({"table": table_index, "columns": width,
                       "aliases": aliases, "owners": owners})
    return tables


def _simple_structure(parts, trees, relationships, main):
    allowed_parts = {main, "[Content_Types].xml", "_rels/.rels", "word/styles.xml",
                     "word/settings.xml", "word/fontTable.xml", "docProps/core.xml",
                     "docProps/app.xml", "word/_rels/document.xml.rels"}
    page_parts = {name for name in parts if re.fullmatch(r"word/(?:header|footer)1\.xml", name)}
    if page_parts:
        # 只为本生成器已验证的静态页眉与PAGE页脚开窄口；域仍不可作为编辑目标。
        from tools.documents import _standard_header_footer, document_profile
        known = _standard_header_footer(document_profile("dyz-standard-internal-v2"))
        require(page_parts == {"word/header1.xml", "word/footer1.xml"}
                and all(parts["word/" + name + "1.xml"] == value for name, value in known.items()),
                "edit_header_footer_unsupported")
        for name in ("header", "footer"):
            require(sum(row["source"] == main and row["id"] == name
                        and row["type"] == review.R + "/" + name
                        and row["part"] == "word/" + name + "1.xml"
                        for row in relationships) == 1, "edit_header_footer_relationship_invalid")
    allowed_parts.update(page_parts)
    require(set(parts).issubset(allowed_parts), "edit_package_part_unsupported")
    require(all(row["mode"] == "Internal" for row in relationships),
            "edit_external_relationship_unsupported")
    require(all(row["part"] in parts for row in relationships), "edit_relationship_target_missing")
    forbidden = {"ins", "del", "moveFrom", "moveTo", "fldSimple", "fldChar", "instrText",
                 "txbxContent", "drawing", "pict", "object", "sdt", "altChunk", "oMath", "oMathPara",
                 "vanish", "webHidden", "specVanish", "trackRevisions", "commentRangeStart",
                 "commentRangeEnd", "commentReference", "delText", "numPr", "tab", "br", "cr"}
    for name, tree in trees.items():
        if name not in page_parts:
            require(not any(node.tag.rsplit("}", 1)[-1] in forbidden for node in tree.iter()),
                    "edit_complex_or_hidden_content_unsupported")
    tree = trees[main]
    require(tree.tag == W + "document", "edit_word_namespace_unsupported")
    require(len(tree) == 1 and tree[0].tag == W + "body", "edit_body_shape_unsupported")
    body = tree[0]
    require(all(node.tag in {W + "p", W + "tbl", W + "sectPr"} for node in body),
            "edit_body_object_unsupported")
    sections = body.findall(W + "sectPr")
    require(len(sections) <= 1 and (not sections or list(body)[-1] is sections[0]),
            "edit_section_shape_unsupported")
    for section in sections:
        allowed = {W + name for name in ("pgSz", "pgMar", "cols", "docGrid", "pgNumType")}
        if page_parts:
            allowed.update({W + "headerReference", W + "footerReference"})
        require(all(node.tag in allowed and not list(node) for node in section),
                "edit_section_object_unsupported")
        for name in ("header", "footer") if page_parts else ():
            refs = section.findall(W + name + "Reference")
            require(len(refs) == 1 and refs[0].get("{" + review.R + "}id") == name
                    and refs[0].get(W + "type") == "default", "edit_header_footer_reference_invalid")
    paragraphs = list(body.iter(W + "p"))
    require(0 < len(paragraphs) <= review.MAX_BLOCKS, "edit_paragraph_limit")
    records = {id(p): _paragraph_record(p, allow_empty=True) for p in paragraphs}
    direct = [records[id(p)] for p in body.findall(W + "p")]
    for record in direct:
        require(bool(record["runs"]), "edit_mixed_or_empty_runs_unsupported")
    starts, ids, ends = {}, {}, {}
    for paragraph in paragraphs:
        for node in paragraph:
            if node.tag not in {W + "bookmarkStart", W + "bookmarkEnd"}:
                continue
            bid = node.get(W + "id")
            require(isinstance(bid, str) and re.fullmatch(r"\d{1,12}", bid) is not None,
                    "edit_bookmark_id_invalid")
            bid = str(int(bid))
            require(not list(node) and set(node.attrib) <= {W + "id", W + "name"},
                    "edit_bookmark_scope_unsupported")
            if node.tag == W + "bookmarkStart":
                name = node.get(W + "name")
                require(isinstance(name, str) and bool(name), "edit_bookmark_name_required")
                require(name not in starts and bid not in ids, "bookmark_ambiguous")
                starts[name] = {"id": bid, "record": records[id(paragraph)]}
                ids[bid] = name
            else:
                require(bid not in ends and bid in ids, "bookmark_ambiguous")
                ends[bid] = records[id(paragraph)]
    require(set(ends) == set(ids), "edit_bookmark_unpaired_or_spanning")
    bookmarks = {}
    for name, item in starts.items():
        record = item["record"]
        if record in direct:
            require(ends[item["id"]] is record, "edit_bookmark_unpaired_or_spanning")
            bookmarks[name] = direct.index(record) + 1
        else:
            require(ends[item["id"]] not in direct, "edit_bookmark_unpaired_or_spanning")
    return direct, records, bookmarks, _tables(body, records)


def _redistribute(old_runs, new):
    """保留未变化前后缀的run归属；变化区按原run覆盖比例分配，绝不合并run。"""
    old = "".join(old_runs)
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(old), len(new)) - prefix and old[-suffix - 1] == new[-suffix - 1]:
        suffix += 1
    old_end, new_end = len(old) - suffix, len(new) - suffix
    middle = new[prefix:new_end]
    intervals, offset = [], 0
    for text in old_runs:
        intervals.append((offset, offset + len(text)))
        offset += len(text)
    weights = [max(0, min(end, old_end) - max(start, prefix)) for start, end in intervals]
    if not any(weights):
        if not old:
            weights = [1] * len(old_runs)
        else:
            anchor = next((index for index, (start, end) in enumerate(intervals)
                           if start < prefix <= end), 0)
            weights[anchor] = 1
    total, accumulated, cursor, result = sum(weights), 0, 0, []
    for text, (start, _), weight in zip(old_runs, intervals, weights):
        accumulated += weight
        boundary = len(middle) * accumulated // total
        left = max(0, min(len(text), prefix - start))
        right = max(0, min(len(text), old_end - start))
        result.append(text[:left] + middle[cursor:boundary] + text[right:])
        cursor = boundary
    require("".join(result) == new, "edit_run_distribution_mismatch")
    return result


def _replacement(raw, span, text):
    escaped = escape(text).encode("utf-8")
    if span["empty"]:
        tag = raw[span["tag_start"]:span["tag_end"]]
        name = re.match(br"<([^\s/>]+)", tag).group(1)
        return re.sub(br"/\s*>$", b">", tag) + escaped + b"</" + name + b">"
    return escaped


def _locate(operation, main, direct, bookmarks, tables):
    require_fields(operation, ("locator", "new_text", "source_refs"))
    require("old_text" in operation, "missing:old_text")
    allowed = {"type", "part", "locator", "old_text", "old_text_sha256", "new_text", "source_refs", "table_profile"}
    require(set(operation) <= allowed, "edit_operation_fields_unsupported")
    require(operation.get("part", main) == main, "edit_part_unsupported")
    kind = operation.get("type", "replace_paragraph")
    locator = operation["locator"]
    require(isinstance(locator, dict), "unique_locator_required")
    extra = {"type": kind, "part": main}
    if kind == "replace_table_cell":
        require_fields(operation, ("part", "table_profile", "old_text_sha256"))
        require(set(locator) == {"table", "row", "column"}
                and all(type(value) is int and value > 0 for value in locator.values()),
                "edit_table_locator_invalid")
        require(locator["table"] <= len(tables), "edit_table_not_found")
        table = tables[locator["table"] - 1]
        from tools.documents import table_template_profile
        profile = table_template_profile(operation["table_profile"])
        headers = [table["aliases"][(1, column)]["paragraph_record"]["text"]
                   for column in range(1, table["columns"] + 1)]
        require(headers == [column["header"] for column in profile["columns"]]
                and all(table["aliases"][(1, column)]["column_span"] == 1
                        and table["aliases"][(1, column)]["row_span"] == 1
                        for column in range(1, table["columns"] + 1)),
                "edit_table_profile_header_mismatch")
        owner = table["aliases"].get((locator["row"], locator["column"]))
        require(owner is not None and owner["row"] > profile["header_row"], "edit_table_cell_not_found")
        extra.update(canonical_cell={key: owner[key] for key in ("table", "row", "column")},
                     column_span=owner["column_span"], row_span=owner["row_span"],
                     table_profile=profile["profile_id"], table_profile_hash=profile["hash"])
        record = owner["paragraph_record"]
    else:
        require(kind == "replace_paragraph" and "table_profile" not in operation, "edit_operation_type_unsupported")
        if "type" in operation:
            require_fields(operation, ("part", "old_text_sha256"))
        require(len(locator) == 1, "unique_locator_required")
        if "bookmark" in locator:
            name = locator["bookmark"]
            require(isinstance(name, str) and name in bookmarks, "bookmark_not_found")
            index = bookmarks[name]
        elif "paragraph" in locator:
            index = locator["paragraph"]
            require(type(index) is int and 0 < index <= len(direct), "paragraph_not_found")
        else:
            raise ContractError("locator_unsupported")
        record = direct[index - 1]
        extra["paragraph"] = index
    require(bool(record["runs"]), "edit_empty_cell_without_text_run_unsupported")
    return record, extra


def _prepare(raw, payload):
    parts, trees, relationships, main = review._package(raw)
    direct, records, bookmarks, tables = _simple_structure(parts, trees, relationships, main)
    nodes = list(trees[main].iter(W + "t"))
    spans = _text_spans(parts[main])
    require(len(spans) == len(nodes), "edit_text_span_ambiguous")
    positions = {id(node): index for index, node in enumerate(nodes)}
    operations = payload.get("operations")
    require(isinstance(operations, list) and 0 < len(operations) <= MAX_OPERATIONS,
            "edit_operations_required")
    changes, replacements, used = [], [], set()
    expected_text = [node.text or "" for node in nodes]
    for operation in operations:
        record, extra = _locate(operation, main, direct, bookmarks, tables)
        key = id(record["node"])
        require(key not in used, "duplicate_edit_target")
        used.add(key)
        old, new = operation["old_text"], operation["new_text"]
        require(isinstance(old, str) and isinstance(new, str) and bool(new.strip()), "edit_text_required")
        require(len(new) <= review.MAX_TEXT_CHARS and not any(
            ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF or ord(char) in {0xFFFE, 0xFFFF}
            for char in new), "edit_text_control_or_size_unsupported")
        require(isinstance(operation["source_refs"], list) and operation["source_refs"]
                and all(isinstance(item, str) and item.strip() for item in operation["source_refs"]),
                "edit_source_refs_required")
        require(record["text"] == old, "old_text_mismatch")
        old_hash = sha256_bytes(old.encode("utf-8"))
        if "old_text_sha256" in operation:
            require(operation["old_text_sha256"] == old_hash, "old_text_hash_mismatch")
        require(new != old, "edit_no_change")
        new_runs = _redistribute([run["node"].text or "" for run in record["runs"]], new)
        evidence, before_offset, after_offset = [], 0, 0
        for run_index, (run, new_text) in enumerate(zip(record["runs"], new_runs), 1):
            node = run["node"]
            require(new_text == new_text.strip() or node.get(XML_SPACE) == "preserve",
                    "edit_whitespace_preservation_unsupported")
            position = positions[id(node)]
            span = spans[position]
            start, end = span["start"], span["end"]
            old_text = node.text or ""
            if old_text != new_text:
                replacements.append((start, end, _replacement(parts[main], span, new_text)))
            expected_text[position] = new_text
            evidence.append({"run": run_index, "old_text": old_text, "new_text": new_text,
                "old_text_sha256": sha256_bytes(old_text.encode("utf-8")),
                "new_text_sha256": sha256_bytes(new_text.encode("utf-8")),
                "old_character_range": [before_offset, before_offset + len(old_text)],
                "new_character_range": [after_offset, after_offset + len(new_text)],
                "properties_sha256": run["properties_sha256"], "properties_unchanged": True,
                "original_xml_byte_range": [start, end]})
            before_offset += len(old_text)
            after_offset += len(new_text)
        ranges = [item["original_xml_byte_range"] for item in evidence]
        changes.append({**extra, "locator": copy.deepcopy(operation["locator"]),
            "old_text": old, "new_text": new, "old_text_sha256": old_hash,
            "new_text_sha256": sha256_bytes(new.encode("utf-8")),
            "source_refs": list(operation["source_refs"]), "run_evidence": evidence,
            "run_distribution": "unchanged_prefix_suffix_ownership_then_proportional_changed_span",
            "paragraph_context_sha256": record["paragraph_context_sha256"],
            "original_xml_byte_range": [ranges[0][0], ranges[-1][1]], "text_change": "verified"})
    ordered = sorted(replacements)
    require(all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:])),
            "overlapping_edit_ranges")
    updated = parts[main]
    for start, end, value in reversed(ordered):
        updated = updated[:start] + value + updated[end:]
    updated_parts, updated_trees = {**parts, main: updated}, {**trees, main: review._xml(updated)}
    _, actual_records, _, _ = _simple_structure(updated_parts, updated_trees, relationships, main)
    require([node.text or "" for node in updated_trees[main].iter(W + "t")] == expected_text,
            "edit_readback_mismatch")
    old_properties = [[row["properties_sha256"] for row in item["runs"]] for item in records.values()]
    new_properties = [[row["properties_sha256"] for row in item["runs"]] for item in actual_records.values()]
    require(old_properties == new_properties, "edit_style_text_relation_changed")
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(output, "w") as revised:
        revised.comment = original.comment
        for member in original.infolist():
            revised.writestr(copy.copy(member), updated if member.filename == main else original.read(member))
    revised_raw = output.getvalue()
    new_parts, _, _, _ = review._package(revised_raw)
    require(set(parts) == set(new_parts), "edit_parts_changed")
    preserved = []
    for name, value in parts.items():
        if name != main:
            require(value == new_parts[name], "edit_untouched_part_changed")
            preserved.append({"part": name, "sha256": sha256_bytes(value), "unchanged": True})
    return revised_raw, {"changes": changes, "main_part": main, "edited_parts": [main],
        "preserved_parts": preserved, "all_operations_preflight": "passed_before_output_creation",
        "main_part_before_sha256": sha256_bytes(parts[main]),
        "main_part_after_sha256": sha256_bytes(updated),
        "outside_replacement_ranges": "byte_identical",
        "readback": "all_supported_text_nodes_and_per_run_style_relations_verified"}


def edit_copy(root, input_path: str, output_path: str, payload: dict, *,
              synthetic: bool = False, admission: dict | None = None) -> dict:
    """同样式相邻文本run或明确表式单元格替换，原件hash强制绑定。

    旧locator={bookmark|paragraph}计划兼容。新表操作要求type为
    replace_table_cell、part、table_profile、locator={table,row,column}、
    old_text及其UTF-8 SHA-256、new_text和source_refs；坐标均为1基逻辑
    网格，gridSpan／vMerge别名归一到左上承载格，重复承载格写前拒绝。
    每个受支持格只有一个段落；跨run保留前后缀归属并分配实际变化区。
    输出必须是尚不存在的新路径。目录应由调用者独占；不能抵御同权恶意
    进程在最终路径检查与open之间替换整个目录树。
    """
    require_fields(payload, ("expected_sha256", "operations"))
    expected = payload["expected_sha256"]
    mode = authorize_io(root, synthetic=synthetic, admission=admission, payload=payload,
                        inputs={input_path: expected}, outputs=(output_path,))
    require(Path(input_path).suffix.lower() == ".docx"
            and Path(output_path).suffix.lower() == ".docx", "docx_paths_required")
    source = scoped_path(root, input_path)
    target = new_output_path(root, output_path, synthetic=synthetic,
                             admission=admission, payload=payload)
    require(source != target, "original_overwrite_forbidden")
    raw = read_bound(root, input_path, expected, synthetic=synthetic,
                     admission=admission, payload=payload, limit=review.MAX_PACKAGE_BYTES)
    revised, evidence = _prepare(raw, payload)
    # 写入前复核原件和实时授权；预验后换件不得生成基于陈旧原件的副本。
    read_bound(root, input_path, expected, synthetic=synthetic,
               admission=admission, payload=payload, limit=review.MAX_PACKAGE_BYTES)
    target = new_output_path(root, output_path, synthetic=synthetic,
                             admission=admission, payload=payload)
    created = False
    try:
        with target.open("xb") as stream:
            created = True
            stream.write(revised)
    except OSError:
        if created:
            target.unlink(missing_ok=True)
        raise
    return {"tool": "tools.document_edit", "tool_version": VERSION, "mode": mode,
        "status": "needs_review", "input": input_path, "output": output_path,
        "original_sha256": expected, "output_sha256": sha256_bytes(revised),
        "original_unchanged": True, "operation_digest": digest(payload["operations"]),
        "authorization_binding": digest(admission) if admission else None,
        "authorization_authenticity": "caller_responsibility_not_authenticated",
        "authorization_binding_scope": "change_detection_not_signature_or_trusted_anchor",
        **evidence, "standard_semantic_review": "required",
        "semantic_equivalence": "not_assessed", "visual_review": "not_performed",
        "professional_review": "not_performed", "official_status": "not_asserted",
        "external_action": "not_performed", "fields_refreshed": False,
        "material_classification": "caller_declaration_not_verified"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--authorization")
    args = parser.parse_args(argv)
    report = None
    try:
        payload, admission = load_cli_request(args)
        require(Path(args.report).suffix.lower() == ".json", "report_json_required")
        new_output_path(args.root, args.report, synthetic=args.synthetic,
                        admission=admission, payload=payload)
        report = edit_copy(args.root, args.input, args.output, payload,
                           synthetic=args.synthetic, admission=admission)
        report_hash = write_report(args.root, args.report, report, synthetic=args.synthetic,
                                   admission=admission, payload=payload)
        print(json.dumps({"status": report["status"], "output": args.output,
            "sha256": report["output_sha256"], "report": args.report,
            "report_sha256": report_hash}))
        return 0
    except (ContractError, OSError, UnicodeError, TypeError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ContractError) else "input_or_io_error"
        result = {"status": "partial" if report else "error", "error": code}
        if report:
            result.update(output=args.output, sha256=report["output_sha256"],
                          report_state="not_written")
        print(json.dumps(result))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
