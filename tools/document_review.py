"""CORE-07：合成或显式研究示例的只读DOCX回查；不接受修订、不运行域、不认证专业结论。"""
from __future__ import annotations

import argparse
import io
import json
import posixpath
import re
import zipfile
import zlib
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from tools.core import ContractError, require, sha256_bytes, safe_path, write_new_json


VERSION = "1.4"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
MAX_PACKAGE_BYTES = 16_000_000
MAX_TOTAL_BYTES = 64_000_000
MAX_PART_BYTES = 16_000_000
MAX_XML_BYTES = 8_000_000
MAX_XML_NODES = 100_000
MAX_XML_DEPTH = 128
MAX_MEMBERS = 1024
MAX_TEXT_CHARS = 2_000_000
MAX_BOOKMARKS = 2048
MAX_SPAN_CHARS = 8_000_000
MAX_BLOCKS = 10_000
MAX_NOTICES = 10_000
MAX_DRAWINGS = 2048
MAX_IMAGE_REFERENCES = 4096
MAX_INVENTORY_ITEMS = 4096
MAX_INVENTORY_NODES = 200_000
PROPERTIES = {"pPr", "rPr", "tblPr", "trPr", "tcPr", "tblGrid", "sectPr"}
REVISIONS = {"ins", "del", "moveFrom", "moveTo"}
HIDDEN = {"vanish", "webHidden", "specVanish"}


def _w(name):
    return "{" + W + "}" + name


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _xml(raw):
    require(len(raw) <= MAX_XML_BYTES, "docx_xml_size_limit")
    # NUL removal also detects declarations encoded as UTF-16/32; no DTD is needed here.
    require(re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw.replace(b"\0", b""), re.I) is None,
            "docx_dtd_or_entity_forbidden")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, LookupError) as exc:
        raise ContractError("docx_xml_invalid") from exc
    pending, count = [(root, 1)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        require(count <= MAX_XML_NODES and depth <= MAX_XML_DEPTH, "docx_xml_structure_limit")
        pending.extend((child, depth + 1) for child in node)
    return root


def _member_name(name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name
            and all(ord(char) >= 32 and ord(char) != 127 for char in name)
            and not name.startswith("/") and "%" not in name,
            "docx_member_path_unsupported")
    pieces = name.rstrip("/").split("/")
    require(all(piece not in {"", ".", ".."} for piece in pieces), "docx_member_path_unsafe")


def _target(source, value):
    require(isinstance(value, str) and bool(value), "docx_relationship_target_invalid")
    value = unquote(value)
    require("\\" not in value and ":" not in value
            and all(ord(char) >= 32 and ord(char) != 127 for char in value),
            "docx_relationship_target_unsafe")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ContractError("docx_relationship_target_invalid") from exc
    require(not parsed.scheme and not parsed.netloc and not parsed.query and not parsed.fragment,
            "docx_relationship_target_unsupported")
    resolved = posixpath.normpath(value.lstrip("/") if value.startswith("/") else
                                 posixpath.join(posixpath.dirname(source), value))
    _member_name(resolved)
    return resolved


def _package(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_PACKAGE_BYTES, "docx_package_size_limit")
    parts = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            require(0 < len(members) <= MAX_MEMBERS, "docx_member_count_limit")
            require(len({m.filename for m in members}) == len(members), "docx_duplicate_member")
            require(len({m.filename.casefold() for m in members}) == len(members), "docx_member_case_ambiguous")
            require(sum(m.file_size for m in members) <= MAX_TOTAL_BYTES, "docx_total_size_limit")
            for member in members:
                _member_name(member.filename)
                require(not member.flag_bits & 1, "docx_encrypted_member_unsupported")
                require(member.file_size <= MAX_PART_BYTES, "docx_part_size_limit")
                if member.is_dir():
                    continue
                with archive.open(member) as stream:
                    content = stream.read(MAX_PART_BYTES + 1)
                require(len(content) <= MAX_PART_BYTES, "docx_part_size_limit")
                parts[member.filename] = content
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ContractError("docx_package_invalid") from exc
    require("[Content_Types].xml" in parts and "_rels/.rels" in parts, "docx_opc_parts_missing")
    parsed = {name: _xml(content) for name, content in parts.items()
              if name.lower().endswith((".xml", ".rels"))}
    types = parsed["[Content_Types].xml"]
    require(types.tag == "{" + CT + "}Types", "docx_content_types_namespace_unsupported")
    relationships = []
    for name, tree in parsed.items():
        if not name.endswith(".rels"):
            continue
        require(tree.tag == "{" + REL + "}Relationships", "docx_relationship_namespace_unsupported")
        if name == "_rels/.rels":
            source = ""
        else:
            directory, filename = posixpath.split(name)
            require(posixpath.basename(directory) == "_rels", "docx_relationship_location_invalid")
            source = posixpath.join(posixpath.dirname(directory), filename[:-5])
        seen = set()
        for node in tree:
            require(node.tag == "{" + REL + "}Relationship", "docx_relationship_element_unsupported")
            rid, kind, target = node.get("Id"), node.get("Type"), node.get("Target")
            mode = node.get("TargetMode", "Internal")
            require(rid and rid not in seen and kind and target and mode in {"Internal", "External"},
                    "docx_relationship_invalid")
            seen.add(rid)
            relationships.append({"source": source, "id": rid, "type": kind, "target": target,
                                  "mode": mode, "part": _target(source, target) if mode == "Internal" else None})
    mains = [item for item in relationships if item["source"] == "" and
             item["type"].endswith("/officeDocument")]
    require(len(mains) == 1, "docx_main_relationship_ambiguous")
    main = mains[0]
    require(main["type"] == R + "/officeDocument" and main["mode"] == "Internal",
            "docx_main_relationship_unsupported")
    require(main["part"] in parsed, "docx_main_part_missing")
    overrides = [node for node in types if node.tag == "{" + CT + "}Override" and
                 node.get("PartName") == "/" + main["part"]]
    require(len(overrides) == 1 and overrides[0].get("ContentType") ==
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
            "docx_main_content_type_unsupported")
    return parts, parsed, relationships, main["part"]


def _children(node, path):
    counts = {}
    for child in node:
        local = _local(child.tag)
        counts[local] = counts.get(local, 0) + 1
        yield child, path + "/" + local + "[" + str(counts[local]) + "]"


def _fragment(node):
    return "".join(item.text or "" for item in node.iter()
                   if item.tag in {_w("t"), _w("delText"), _w("instrText")})


class _BodyReader:
    def __init__(self):
        self.chunks, self.length = [], 0
        self.blocks, self.bookmarks, self.notices, self.fragments = [], [], [], []
        self.links, self.active, self.ids = [], {}, {}
        self.block = None
        self.fields = []
        self.drawings, self.image_reference_count = [], 0

    def notice(self, code, locator, **extra):
        require(len(self.notices) < MAX_NOTICES, "docx_notice_limit")
        item = {"code": code, "locator": locator, **extra}
        self.notices.append(item)
        if self.block is not None:
            self.block["issues"].add(code)
        for records in self.active.values():
            for record in records:
                record["issues"].add(code)

    def touch(self):
        if self.block is not None:
            for records in self.active.values():
                for record in records:
                    record["blocks"].add(self.block["index"])

    def emit(self, value):
        self.length += len(value)
        require(self.length <= MAX_TEXT_CHARS, "docx_text_size_limit")
        self.chunks.append(value)
        self.touch()

    def bookmark(self, node, locator):
        bid = node.get(_w("id"), "")
        if re.fullmatch(r"-?\d{1,20}", bid) is None:
            self.notice("bookmark_id_invalid", locator)
            return
        bid = str(int(bid))
        if node.tag == _w("bookmarkEnd"):
            records = self.active.pop(bid, [])
            if not records:
                self.notice("bookmark_end_unmatched", locator, bookmark_id=bid)
                for record in self.ids.get(bid, []):
                    record["issues"].add("bookmark_end_duplicated")
            for record in records:
                record.update(end=self.length, end_locator=locator)
            return
        name = node.get(_w("name"), "")
        require(len(self.bookmarks) < MAX_BOOKMARKS, "docx_bookmark_count_limit")
        record = {"name": name, "numeric_id": bid, "start": self.length, "end": None,
                  "locator": locator, "end_locator": None, "blocks": set(), "issues": set()}
        if not name or len(name) > 256 or any(ord(char) < 32 for char in name):
            record["issues"].add("bookmark_name_invalid")
            self.notice("bookmark_name_invalid", locator)
        if bid in self.ids:
            record["issues"].add("bookmark_id_duplicated")
            for previous in self.ids[bid]:
                previous["issues"].add("bookmark_id_duplicated")
            self.notice("bookmark_id_duplicated", locator, bookmark_id=bid)
        self.ids.setdefault(bid, []).append(record)
        self.active.setdefault(bid, []).append(record)
        self.bookmarks.append(record)
        self.touch()
        if node.get(_w("colFirst")) is not None or node.get(_w("colLast")) is not None:
            self.notice("bookmark_column_scope_not_interpreted", locator)

    def properties(self, node, locator):
        for item in node.iter():
            local = _local(item.tag)
            if item.tag == _w(local) and local in HIDDEN:
                value = item.get(_w("val"), "true").lower()
                if value not in {"false", "0", "off"}:
                    self.notice("direct_hidden_property", locator, property=local, value=value)
            elif item.tag == _w("numPr"):
                self.notice("automatic_numbering_not_resolved", locator)
            elif item.tag == _w("gridSpan") or item.tag == _w("vMerge"):
                self.notice("table_merge_not_interpreted", locator, property=local)
            elif local.endswith("Change") and item.tag == _w(local):
                self.notice("property_revision_not_resolved", locator, property=local)

    def drawing(self, node, locator):
        # Retain the original unresolved status: binding bytes is not rendering a drawing.
        require(len(self.drawings) < MAX_DRAWINGS, "docx_drawing_count_limit")
        self.notice("markup_not_interpreted", locator, element="drawing")
        self.fragments.append({"kind": "unread_drawing", "locator": locator, "text": _fragment(node)})
        record = {"locator": locator, "block_index": self.block["index"] if self.block else None,
                  "literal_offset": self.length, "context": "unresolved_field" if self.fields else "main_body",
                  "serialized_xml_sha256": sha256_bytes(ET.tostring(node, encoding="utf-8")),
                  "containers": [], "doc_properties": [], "references": []}
        for child in node:
            if child.tag in {"{" + WP + "}inline", "{" + WP + "}anchor"}:
                record["containers"].append({"kind": _local(child.tag), "attributes": dict(child.attrib),
                    "extent_attributes": [dict(e.attrib) for e in child if e.tag == "{" + WP + "}extent"]})
        pending = [(node, locator)]
        while pending:
            item, path = pending.pop()
            if item.tag == "{" + WP + "}docPr":
                record["doc_properties"].append({"id": item.get("id"), "name": item.get("name"),
                                                 "attributes": dict(item.attrib)})
            elif item.tag == "{" + A + "}blip":
                modes = [(mode, item.get("{" + R + "}" + mode)) for mode in ("embed", "link")
                         if "{" + R + "}" + mode in item.attrib]
                for mode, rid in modes or [("unspecified", None)]:
                    self.image_reference_count += 1
                    require(self.image_reference_count <= MAX_IMAGE_REFERENCES, "docx_image_reference_count_limit")
                    record["references"].append({"locator": path, "mode": mode, "relationship_id": rid})
            pending.extend(reversed(list(_children(item, path))))
        self.drawings.append(record)

    def walk(self, node, locator):
        local = _local(node.tag)
        if node.tag != _w(local):
            self.notice("foreign_markup_not_interpreted", locator, tag=node.tag)
            return
        if local in PROPERTIES:
            self.properties(node, locator)
        elif local in {"bookmarkStart", "bookmarkEnd"}:
            self.bookmark(node, locator)
        elif local == "drawing":
            self.drawing(node, locator)
        elif local in REVISIONS or local == "fldSimple":
            self.notice("revision_not_resolved" if local in REVISIONS else "field_not_resolved", locator)
            self.fragments.append({"kind": local, "locator": locator, "text": _fragment(node),
                                   "instruction": node.get(_w("instr"))})
        elif local == "fldChar":
            self.notice("field_not_resolved", locator)
            mode = node.get(_w("fldCharType"))
            if mode == "begin":
                self.fields.append("instruction")
            elif mode == "separate" and self.fields:
                self.fields[-1] = "cached_result"
            elif mode == "end" and self.fields:
                self.fields.pop()
            else:
                self.notice("field_marker_unmatched", locator)
        elif local in {"t", "instrText", "delText"}:
            if self.fields or local != "t":
                self.notice("field_not_resolved" if self.fields or local == "instrText" else
                            "deleted_text_outside_revision", locator)
                self.fragments.append({"kind": self.fields[-1] if self.fields else local,
                                       "locator": locator, "text": node.text or ""})
            else:
                self.emit(node.text or "")
        elif local in {"tab", "br", "cr"}:
            if self.fields:
                self.notice("field_not_resolved", locator)
            else:
                self.emit("\t" if local == "tab" else "\n")
        elif local in {"p", "r", "hyperlink"}:
            if local == "hyperlink":
                self.links.append({"locator": locator, "anchor": node.get(_w("anchor")),
                                   "relationship_id": node.get("{" + R + "}id")})
            for child, child_path in _children(node, locator):
                self.walk(child, child_path)
        elif local == "proofErr":
            pass
        else:
            self.notice("markup_not_interpreted", locator, element=local)
            self.fragments.append({"kind": "unread_" + local, "locator": locator, "text": _fragment(node)})

    def table(self, table, locator):
        rows = [child for child in table if child.tag == _w("tr")]
        widths = []
        for child, path in _children(table, locator):
            if child.tag in {_w("tblPr"), _w("tblGrid")}:
                self.walk(child, path)
            elif child.tag != _w("tr"):
                self.notice("table_child_not_interpreted", path, element=_local(child.tag))
        for row_index, row in enumerate(rows, 1):
            row_path = locator + "/tr[" + str(row_index) + "]"
            cells = [child for child in row if child.tag == _w("tc")]
            widths.append(len(cells))
            for child, path in _children(row, row_path):
                if child.tag == _w("trPr"):
                    self.walk(child, path)
                elif child.tag != _w("tc"):
                    self.notice("table_row_child_not_interpreted", path, element=_local(child.tag))
            for cell_index, cell in enumerate(cells, 1):
                cell_path = row_path + "/tc[" + str(cell_index) + "]"
                start, paragraphs = self.length, 0
                for child, path in _children(cell, cell_path):
                    if child.tag == _w("p"):
                        if paragraphs:
                            self.emit("\n")
                        paragraphs += 1
                        self.walk(child, path)
                    elif child.tag == _w("tcPr"):
                        self.walk(child, path)
                    else:
                        self.notice("table_cell_child_not_interpreted", path, element=_local(child.tag))
                self.block["cells"].append({"row": row_index, "cell": cell_index, "locator": cell_path,
                                             "start": start, "end": self.length})
                if cell_index < len(cells):
                    self.emit("\t")
            if row_index < len(rows):
                self.emit("\n")
        if not widths or 0 in widths or len(set(widths)) != 1:
            self.notice("table_grid_not_rectangular", locator)

    def read(self, tree):
        require(tree.tag == _w("document"), "docx_document_namespace_unsupported")
        bodies = tree.findall(_w("body"))
        require(len(bodies) == 1, "docx_body_missing_or_ambiguous")
        for child in tree:
            if child is not bodies[0]:
                self.notice("document_child_not_interpreted", "document/" + _local(child.tag))
        for node, locator in _children(bodies[0], "body"):
            if node.tag not in {_w("p"), _w("tbl")}:
                self.walk(node, locator)
                continue
            require(len(self.blocks) < MAX_BLOCKS, "docx_block_count_limit")
            block = {"index": len(self.blocks) + 1, "kind": "table" if node.tag == _w("tbl") else "paragraph",
                     "locator": locator, "start": self.length, "issues": set(), "cells": []}
            self.blocks.append(block)
            self.block = block
            self.touch()
            if block["kind"] == "table":
                self.table(node, locator)
            else:
                self.walk(node, locator)
            block["end"] = self.length
            self.block = None
            self.emit("\n")
        if self.fields:
            self.notice("field_unclosed", "body")
        for records in self.active.values():
            for record in records:
                record["issues"].add("bookmark_unclosed")
                self.notices.append({"code": "bookmark_unclosed", "locator": record["locator"]})
        names = {}
        for record in self.bookmarks:
            names.setdefault(record["name"], []).append(record)
        for name, records in names.items():
            if len(records) > 1:
                self.notices.append({"code": "bookmark_name_duplicated", "locator": "body", "name": name})
                for record in records:
                    record["issues"].add("bookmark_name_duplicated")
        text = "".join(self.chunks)
        require(sum((item["end"] if item["end"] is not None else len(text)) - item["start"]
                    for item in self.bookmarks) <= MAX_SPAN_CHARS,
                "docx_bookmark_span_limit")
        for block in self.blocks:
            block["text"] = text[block["start"]:block["end"]]
            block["issues"] = sorted(block["issues"])
            for cell in block["cells"]:
                cell["text"] = text[cell["start"]:cell["end"]]
        for record in self.bookmarks:
            column_scope = "bookmark_column_scope_not_interpreted" in record["issues"]
            record["text"] = (text[record["start"]:record["end"]]
                              if record["end"] is not None and not column_scope else None)
            record["text_state"] = "not_interpreted" if column_scope else "incomplete" if record["issues"] else "literal_span"
            record["issues"] = sorted(record["issues"])
            record["blocks"] = sorted(record["blocks"])
            record["identity_state"] = "unresolved" if record["issues"] else "paired_unique_name"
        for link in self.links:
            anchor = link["anchor"]
            link["anchor_state"] = ("not_applicable" if anchor is None else
                "located_in_main_body" if anchor in names and len(names[anchor]) == 1 and
                names[anchor][0]["identity_state"] == "paired_unique_name" else "not_verified_in_main_body")
        return {"blocks": self.blocks, "bookmarks": self.bookmarks, "notices": self.notices,
                "unresolved_fragments": self.fragments, "hyperlinks": self.links,
                "drawings": self.drawings,
                "literal_text_sha256": sha256_bytes(text.encode("utf-8"))}


def _content_inventory(trees, part_metadata):
    """枚举已解析XML中的指定标记；不摘录内容、不计算继承或可见性。"""
    categories = {name: "revision_marker" for name in REVISIONS}
    categories.update({name: "hidden_property" for name in HIDDEN})
    categories.update({name: "comment_marker" for name in
                       ("comment", "commentRangeStart", "commentRangeEnd", "commentReference")})
    findings, scanned, visited = [], [], 0
    for part, tree in sorted(trees.items()):
        scanned.append(part)
        # 遍历全部已解析部件及被正文读取器跳过的子树；定位不表示它会显示或生效。
        pending = [iter(((tree, _local(tree.tag) + "[1]"),))]
        while pending:
            item = next(pending[-1], None)
            if item is None:
                pending.pop()
                continue
            node, locator = item
            visited += 1
            require(visited <= MAX_INVENTORY_NODES, "docx_inventory_scan_limit")
            local = _local(node.tag)
            if node.tag == _w(local) and local in categories:
                require(len(findings) < MAX_INVENTORY_ITEMS, "docx_inventory_count_limit")
                finding = {"category": categories[local], "element": local,
                           "namespace": W, "part": part,
                           "part_sha256": part_metadata[part]["sha256"], "locator": locator}
                if local in HIDDEN:
                    value = node.get(_w("val"))
                    # 任意属性值不进入报告；只保留已知开关词，缺省和未知分别列出。
                    finding["declared_value"] = ("omitted" if value is None else value
                        if value in {"true", "false", "1", "0", "on", "off"} else "unrecognized")
                    finding["effective_visibility"] = "not_evaluated"
                findings.append(finding)
            pending.append(iter(_children(node, locator)))
    return {"state": "enumerated_markers_only", "scanned_parts": scanned,
            "scanned_nodes": visited, "findings": findings,
            "scope": "selected_transitional_wordprocessingml_markers_in_parsed_xml_only",
            "hidden_content_clearance": "not_assessed",
            "limitations": ["marker_presence_does_not_prove_display_or_effect",
                            "style_inheritance_and_revision_acceptance_not_evaluated",
                            "unrecognized_xml_and_binary_payloads_not_interpreted",
                            "no_content_or_personal_metadata_extracted",
                            "empty_findings_do_not_prove_no_hidden_content"]}


def _inspect(raw):
    parts, trees, relationships, main = _package(raw)
    data = _BodyReader().read(trees[main])
    data.update(sha256=sha256_bytes(raw), bytes=len(raw), main_part=main,
                parts=[{"path": name, "sha256": sha256_bytes(content), "bytes": len(content)}
                       for name, content in sorted(parts.items())],
                relationships=relationships, unread_parts=[])
    for relationship in relationships:
        if relationship["mode"] == "External":
            data["notices"].append({"code": "external_relationship_not_followed", "locator": relationship["source"],
                                    "relationship_id": relationship["id"]})
        elif relationship["part"] not in parts:
            data["notices"].append({"code": "relationship_part_missing", "locator": relationship["source"],
                                    "relationship_id": relationship["id"]})
    main_relationships = {item["id"]: item for item in relationships if item["source"] == main}
    part_metadata = {item["path"]: item for item in data["parts"]}
    for drawing in data["drawings"]:
        drawing["source_part"] = main
        for ref in drawing["references"]:
            relationship = main_relationships.get(ref["relationship_id"])
            if ref["mode"] == "unspecified":
                state = "image_reference_missing"
            elif relationship is None:
                state = "relationship_missing"
            elif relationship["type"] != R + "/image":
                state = "relationship_type_mismatch"
            else:
                ref.update(target=relationship["target"], relationship_mode=relationship["mode"],
                           part=relationship["part"])
                if ref["mode"] == "link":
                    state = "linked_reference_not_followed"
                elif relationship["mode"] != "Internal":
                    state = "external_reference_not_followed"
                elif relationship["part"] not in part_metadata:
                    state = "image_part_missing"
                else:
                    state = "embedded_part_bound"
                    part = part_metadata[relationship["part"]]
                    ref.update(sha256=part["sha256"], bytes=part["bytes"])
            ref["state"] = state
            if state != "embedded_part_bound":
                require(len(data["notices"]) < MAX_NOTICES, "docx_notice_limit")
                data["notices"].append({"code": "drawing_" + state, "locator": ref["locator"],
                                        "relationship_id": ref["relationship_id"]})
    data["drawing_scope"] = "encountered_main_body_drawings_only_not_skipped_revisions_or_other_parts"
    for link in data["hyperlinks"]:
        rid = link["relationship_id"]
        if rid is not None and link["anchor"] is not None:
            link["anchor_state"] = "relationship_target_anchor_not_verified"
        if link["anchor_state"] not in {"located_in_main_body", "not_applicable"}:
            data["notices"].append({"code": "hyperlink_anchor_not_verified", "locator": link["locator"]})
        if rid is not None and (rid not in main_relationships or main_relationships[rid]["type"] != R + "/hyperlink"):
            data["notices"].append({"code": "hyperlink_relationship_not_verified", "locator": link["locator"],
                                    "relationship_id": rid})
    metadata = {"[Content_Types].xml", main}
    metadata.update(name for name in parts if name.endswith(".rels"))
    styles = {item["part"] for item in relationships if item["source"] == main and
              item["type"] == R + "/styles" and item["mode"] == "Internal"}
    for name in sorted(set(parts) - metadata):
        if name in styles and name in trees:
            data["unread_parts"].append({"path": name, "scope": "style_inheritance_not_resolved"})
            if any(node.tag in {_w(tag) for tag in HIDDEN} for node in trees[name].iter()):
                data["notices"].append({"code": "style_hidden_toggle_not_resolved", "locator": name})
            if any(node.tag == _w("numPr") for node in trees[name].iter()):
                data["notices"].append({"code": "style_numbering_not_resolved", "locator": name})
        else:
            data["unread_parts"].append({"path": name, "scope": "not_interpreted"})
            data["notices"].append({"code": "part_not_interpreted", "locator": name})
    data["content_inventory"] = _content_inventory(trees, part_metadata)
    data["readback_state"] = "partial" if data["notices"] else "complete_supported_subset"
    return data


def _literal_change(before, after):
    prefix = 0
    while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(before), len(after)) - prefix and before[-suffix - 1] == after[-suffix - 1]:
        suffix += 1
    def span(value):
        end = len(value) - suffix
        changed = value[prefix:end]
        return {"start": prefix, "end": end, "text": changed[:2048], "truncated": len(changed) > 2048,
                "sha256": sha256_bytes(changed.encode("utf-8"))}
    return {"before": span(before), "after": span(after), "meaning": "literal_span_only"}


def _coverage(source, records):
    """用实际字符区间核覆盖；一个书签接触某段不等于覆盖整段。"""
    spans = sorted((record["start"], record["end"]) for record in records)
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    named_blocks = {index for record in records for index in record["blocks"]}
    gaps, unverified, first = [], [], 0
    for block in source["blocks"]:
        start, end = block["start"], block["end"]
        while first < len(merged) and merged[first][1] <= start:
            first += 1
        cursor = start
        segments = []
        for interval in range(first, len(merged)):
            left, right = merged[interval]
            if left >= end:
                break
            if left > cursor:
                segments.append((cursor, min(left, end)))
            cursor = max(cursor, min(right, end))
        if cursor < end:
            segments.append((cursor, end))
        if segments or (start == end and block["index"] not in named_blocks):
            unverified.append(block["index"])
        for left, right in segments:
            text = block["text"][left - start:right - start]
            gaps.append({"block": block["index"], "locator": block["locator"], "start": left, "end": right,
                         "text": text[:2048], "truncated": len(text) > 2048,
                         "sha256": sha256_bytes(text.encode("utf-8"))})
    return unverified, gaps


def _compare(before, after):
    left, right = {}, {}
    for source, target in ((before, left), (after, right)):
        for record in source["bookmarks"]:
            target.setdefault(record["name"], []).append(record)
    paired, unresolved = [], []
    for name in sorted(set(left) | set(right)):
        old, new = left.get(name, []), right.get(name, [])
        if (len(old) != 1 or len(new) != 1 or old[0]["identity_state"] != "paired_unique_name" or
                new[0]["identity_state"] != "paired_unique_name"):
            unresolved.append({"name": name, "baseline_occurrences": len(old), "current_occurrences": len(new),
                               "state": "identity_not_verified", "baseline_issues": [r["issues"] for r in old],
                               "current_issues": [r["issues"] for r in new]})
            continue
        old, new = old[0], new[0]
        equal = old["text"] == new["text"]
        paired.append({"name": name, "text_equal": equal, "baseline_blocks": old["blocks"],
                       "current_blocks": new["blocks"], "block_positions_changed": old["blocks"] != new["blocks"],
                       "baseline_locator": old["locator"], "current_locator": new["locator"],
                       "literal_change": None if equal else _literal_change(old["text"], new["text"])})
    part_left = {item["path"]: item for item in before["parts"]}
    part_right = {item["path"]: item for item in after["parts"]}
    changed_parts = [{"path": path, "baseline_sha256": part_left.get(path, {}).get("sha256"),
                      "current_sha256": part_right.get(path, {}).get("sha256")}
                     for path in sorted(set(part_left) | set(part_right))
                     if part_left.get(path, {}).get("sha256") != part_right.get(path, {}).get("sha256")]
    names = [item["name"] for item in paired]
    uncovered, current_gaps = _coverage(after, [right[name][0] for name in names])
    baseline_uncovered, baseline_gaps = _coverage(before, [left[name][0] for name in names])
    partial = (unresolved or uncovered or baseline_uncovered or before["readback_state"] == "partial" or
               after["readback_state"] == "partial")
    return {"state": "partial" if partial else "complete_supported_subset",
            "matching_basis": "unique_paired_bookmark_name_not_visible_number_or_numeric_id",
            "paired_bookmarks": paired, "unresolved_bookmarks": unresolved,
            "current_blocks_without_verified_identity": uncovered,
            "baseline_blocks_without_verified_identity": baseline_uncovered, "changed_parts": changed_parts,
            "current_unanchored_text_ranges": current_gaps, "baseline_unanchored_text_ranges": baseline_gaps,
            "range_offsets": "zero_based_unicode_characters_in_each_main_literal_stream",
            "package_bytes_equal": before["sha256"] == after["sha256"],
            "main_literal_stream_equal": before["literal_text_sha256"] == after["literal_text_sha256"],
            **_compare_drawings(before["drawings"], after["drawings"]),
            "semantic_equivalence": "not_assessed", "format_equivalence": "not_assessed",
            "prior_review_reuse": "requires_separate_current_version_review"}


def _compare_drawings(before, after):
    """Only pair unique caller labels; IDs, positions and identical media are not identity proof."""
    def grouped(rows):
        result = {}
        for row in rows:
            properties = row["doc_properties"]
            name = (properties[0]["name"] if len(properties) == 1 and len(row["containers"]) == 1
                    and row["context"] == "main_body" else None)
            result.setdefault(name or None, []).append(row)
        return result

    def media_sequence(row):
        refs = row["references"]
        return ([r["sha256"] for r in refs] if refs and
                all(r["state"] == "embedded_part_bound" for r in refs) else None)

    left, right = grouped(before), grouped(after)
    paired, unresolved = [], []
    for name in sorted(set(left) | set(right), key=lambda value: value or ""):
        old, new = left.get(name, []), right.get(name, [])
        if name is None or len(old) != 1 or len(new) != 1:
            unresolved.append({"name": name, "baseline_occurrences": len(old), "current_occurrences": len(new),
                               "state": "unique_drawing_label_not_paired",
                               "baseline_locators": [r["locator"] for r in old],
                               "current_locators": [r["locator"] for r in new]})
            continue
        old, new = old[0], new[0]
        old_media, new_media = media_sequence(old), media_sequence(new)
        paired.append({"name": name, "identity": "caller_label_only_not_certified",
                       "baseline_locator": old["locator"], "current_locator": new["locator"],
                       "baseline_block": old["block_index"], "current_block": new["block_index"],
                       "block_positions_changed": old["block_index"] != new["block_index"],
                       "embedded_bytes_equal": old_media == new_media if old_media is not None and new_media is not None else None,
                       "serialized_drawing_markup_equal": old["serialized_xml_sha256"] == new["serialized_xml_sha256"],
                       "visual_equivalence": "not_assessed"})
    return {"drawing_matching_basis": "unique_docPr_name_caller_label_not_numeric_id_relationship_id_position_or_hash",
            "paired_drawings": paired, "unresolved_drawings": unresolved}


def review_docx(current: bytes, baseline: bytes | None = None) -> dict:
    """只核调用者提供的字节；不读路径/网络、不开Office、不证明来源或提交身份。"""
    after = _inspect(current)
    before = _inspect(baseline) if baseline is not None else None
    return {"tool": "tools.document_review", "tool_version": VERSION, "capability": "CORE-07",
            "status": "needs_review", "current": after, "baseline": before,
            "comparison": _compare(before, after) if before is not None else {"state": "not_requested"},
            "scope": "main_body_literal_text_paragraphs_rectangular_tables_bookmark_spans_and_drawing_byte_bindings",
            "visual_review": "not_performed", "professional_review": "not_performed",
            "official_status": "not_asserted", "external_action": "not_performed",
            "limitations": ["caller_supplied_baseline_authenticity_not_verified", "style_inheritance_not_resolved",
                            "automatic_numbering_not_resolved", "tracked_changes_not_accepted_or_rejected",
                            "fields_not_executed_or_refreshed", "unread_parts_not_cleared",
                            "drawing_bytes_and_labels_do_not_prove_visual_or_source_identity",
                            "image_bytes_not_decoded_or_mime_validated",
                            "no_legal_or_natural_language_equivalence_verdict"]}


def _review_summary(report):
    """返回有界定位索引；完整证据仍由CLI单独落盘，省略项绝不算已审。"""
    groups = []
    for side in ("current", "baseline"):
        source = report[side]
        if source is None:
            continue
        for key in ("notices", "unread_parts", "unresolved_fragments"):
            groups.append((f"/{side}/{key}", source[key], None))
        groups.append((f"/{side}/content_inventory/findings", source["content_inventory"]["findings"], None))
    comparison = report["comparison"]
    if comparison["state"] != "not_requested":
        groups.extend([
            ("/comparison/paired_bookmarks", comparison["paired_bookmarks"],
             lambda row: not row["text_equal"] or row["block_positions_changed"]),
            ("/comparison/paired_drawings", comparison["paired_drawings"],
             lambda row: row["embedded_bytes_equal"] is not True or
             not row["serialized_drawing_markup_equal"] or row["block_positions_changed"]),
        ])
        for key in ("unresolved_bookmarks", "unresolved_drawings", "changed_parts",
                    "current_unanchored_text_ranges", "baseline_unanchored_text_ranges"):
            groups.append((f"/comparison/{key}", comparison[key], None))

    summary = {
        "scope": "bounded_navigation_only_not_full_read_or_clearance",
        "current_sha256": report["current"]["sha256"],
        "baseline_sha256": report["baseline"]["sha256"] if report["baseline"] else None,
        "readback_state": report["current"]["readback_state"],
        "baseline_readback_state": report["baseline"]["readback_state"] if report["baseline"] else None,
        "comparison_state": comparison["state"],
        "hidden_content_clearance": "not_assessed",
        "professional_review": report["professional_review"],
        "visual_review": report["visual_review"],
        "external_action": report["external_action"],
        "main_literal_stream_equal": comparison.get("main_literal_stream_equal"),
        "limits": {"items": 32, "item_json_bytes": 24000, "excerpt_characters": 240},
        "groups": [], "items": [],
    }
    used = 0
    # 只摘取定位与变化事实；批注／修订正文、作者等仍留在获准的完整报告。
    fields = ("code", "scope", "name", "state", "path", "part", "part_sha256", "locator",
              "category", "element", "declared_value", "effective_visibility", "block", "start", "end",
              "baseline_locator", "current_locator", "baseline_sha256", "current_sha256",
              "text_equal", "block_positions_changed", "embedded_bytes_equal", "serialized_drawing_markup_equal")
    for pointer, rows, predicate in groups:
        total = shown = 0
        for index, row in enumerate(rows):
            if predicate is not None and not predicate(row):
                continue
            total += 1
            item = {"report_pointer": f"{pointer}/{index}",
                    **{key: row[key] for key in fields if key in row}}
            change = row.get("literal_change")
            if change:
                item["literal_change"] = {
                    side: {**span, "text": span["text"][:240],
                           "truncated": span["truncated"] or len(span["text"]) > 240}
                    for side, span in change.items() if side in {"before", "after"}}
            if pointer.endswith("unanchored_text_ranges"):
                item.update(text=row["text"][:240], sha256=row["sha256"],
                            truncated=row["truncated"] or len(row["text"]) > 240)
            size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            if len(summary["items"]) < 32 and used + size <= 24000:
                summary["items"].append(item)
                used += size
                shown += 1
        summary["groups"].append({"report_pointer": pointer, "total": total,
                                  "shown": shown, "omitted": total - shown})
    summary["omitted_items"] = sum(group["omitted"] for group in summary["groups"])
    summary["coverage"] = "partial_index" if summary["omitted_items"] else "listed_findings_only"
    return summary


def _read_file(root, relative, expected):
    path = safe_path(root, relative)
    require(path.is_file() and path.suffix.lower() == ".docx", "docx_file_required")
    with path.open("rb") as stream:
        raw = stream.read(MAX_PACKAGE_BYTES + 1)
    require(len(raw) <= MAX_PACKAGE_BYTES, "docx_package_size_limit")
    if expected is not None:
        require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, "docx_expected_hash_invalid")
        require(sha256_bytes(raw) == expected, "docx_input_hash_changed")
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    declarations = parser.add_mutually_exclusive_group()
    declarations.add_argument("--synthetic", action="store_true")
    declarations.add_argument("--research-example", action="store_true", help="调用者声明为原创研究/合成示例；不证明来源或权利")
    parser.add_argument("--root", default=".")
    parser.add_argument("--input", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--baseline-sha256")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", action="store_true", help="stdout附有界差异／异常索引；完整JSON仍写output")
    args = parser.parse_args(argv)
    try:
        require(args.synthetic or args.research_example, "synthetic_only")
        require(args.baseline is not None or args.baseline_sha256 is None, "docx_baseline_required")
        current = _read_file(args.root, args.input, args.expected_sha256)
        baseline = _read_file(args.root, args.baseline, args.baseline_sha256) if args.baseline else None
        report = review_docx(current, baseline)
        report["mode"] = "research_example" if args.research_example else "synthetic"
        report["material_classification"] = "caller_declaration_not_verified"
        report["input_paths"] = {"current": args.input, "baseline": args.baseline}
        require(Path(args.output).suffix.lower() == ".json", "docx_report_json_required")
        target = write_new_json(args.root, args.output, report)
        result = {"status": report["status"], "output": args.output,
                  "sha256": sha256_bytes(target.read_bytes()), "current_sha256": report["current"]["sha256"],
                  "readback_state": report["current"]["readback_state"],
                  "comparison_state": report["comparison"]["state"]}
        if args.summary:
            result["review_summary"] = _review_summary(report)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ContractError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, ContractError) else "io_error"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
