"""三业务DOCX编辑变体；作者工程对照，不是模型写作、人工Word操作或专业验收。"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

from tools.core import ContractError, canonical_bytes, require, safe_path, sha256_bytes
from tools.documents import build, verify, resolve_document, inspect_generated_docx


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CASES = (
    ("patent", "skills/dyz-rendering/resources/fidelity-document-example.json", "P010",
     (("P010", "均有效且", "任一有效且"),)),
    ("software", "skills/dyz-software/resources/harbor-delivery-v1.2/manual-input.json", "manual_7",
     (("manual_7", "最多1000条记录", "最多1001条记录"),)),
    ("standard", "skills/dyz-standards/resources/river-delivery/standard-input.json", "standard_99",
     (("RIV_05", "8 记录 RIV-05", "12 记录 RIV-05"),
      ("standard_121", "原始字节数为0或大于1024", "原始字节数为0或大于2048"))),
)


def _mutate(raw, replacements=(), tracked_bookmark=None):
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        entries = {name: package.read(name) for name in package.namelist()}
    tree = ET.fromstring(entries["word/document.xml"])
    changes = []
    ordered = list(tree.iter())
    for bookmark, old, new in replacements:
        starts = [index for index, node in enumerate(ordered) if node.tag == "{" + W + "}bookmarkStart"
                  and node.get("{" + W + "}name") == bookmark]
        require(len(starts) == 1, "synthetic_edit_bookmark_not_unique")
        start = starts[0]
        bid = ordered[start].get("{" + W + "}id")
        ends = [index for index in range(start + 1, len(ordered)) if ordered[index].tag == "{" + W + "}bookmarkEnd"
                and ordered[index].get("{" + W + "}id") == bid]
        require(len(ends) == 1, "synthetic_edit_end_not_unique")
        nodes = [node for node in ordered[start + 1:ends[0]] if node.tag == "{" + W + "}t" and old in (node.text or "")]
        require(len(nodes) == 1 and nodes[0].text.count(old) == 1, "synthetic_edit_not_unique")
        nodes[0].text = nodes[0].text.replace(old, new)
        changes.append({"bookmark": bookmark, "old": old, "new": new})
    if tracked_bookmark is not None:
        paragraphs = [node for node in tree.iter("{" + W + "}p")
                      if any(child.tag == "{" + W + "}bookmarkStart" and
                             child.get("{" + W + "}name") == tracked_bookmark for child in node)]
        require(len(paragraphs) == 1, "synthetic_tracked_target_not_unique")
        revision = ET.Element("{" + W + "}ins", {"{" + W + "}id": "900", "{" + W + "}author": "SyntheticEngineering"})
        run = ET.SubElement(revision, "{" + W + "}r")
        ET.SubElement(run, "{" + W + "}t").text = "合成修订片段，尚未确认。"
        end = paragraphs[0].find("{" + W + "}bookmarkEnd")
        require(end is not None, "synthetic_tracked_end_missing")
        paragraphs[0].insert(list(paragraphs[0]).index(end), revision)
        changes.append({"tracked_insertion_in_bookmark": tracked_bookmark, "accepted": False})
    entries["word/document.xml"] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in sorted(entries.items()):
            package.writestr(name, data)
    return buffer.getvalue(), changes


def run(root: Path, output: str):
    target = safe_path(root, output, must_exist=False)
    require(target.parent.is_dir() and not target.exists(), "new_output_directory_required")
    target.mkdir()
    summary = {"scope": "three_business_author_constructed_synthetic_docx_engineering_controls",
               "editor_operation": "programmatic_zip_xml_mutation_not_manual_word_ui",
               "professional_review": "not_performed", "independent_model_acceptance": "not_executed", "cases": [],
               "sources": {name: sha256_bytes((root / name).read_bytes()) for name in
                           ("evals/maturity_docx_review_cases.py", "tools/document_review.py", "tools/documents.py")}}
    for business, relative, tracked, replacements in CASES:
        folder = target / business
        folder.mkdir()
        spec_raw = (root / relative).read_bytes()
        spec = json.loads(spec_raw)
        original_relative = (folder / "original").relative_to(root).as_posix()
        build(root, spec, original_relative, synthetic=True)
        verified = verify(root, spec, original_relative, synthetic=True)
        original = folder / "original/body/document.docx"
        original_raw = original.read_bytes()
        blocks, images = resolve_document(root, spec)
        controls = []
        for variant in ("edited", "tracked"):
            edited_raw, changes = _mutate(original_raw, replacements=replacements if variant == "edited" else (),
                                          tracked_bookmark=tracked if variant == "tracked" else None)
            current = folder / (variant + ".docx")
            with current.open("xb") as stream:
                stream.write(edited_raw)
            report_path = folder / (variant + "-readback.json")
            command = [sys.executable, "-X", "utf8", "-m", "tools.document_review", "--synthetic", "--root", str(root),
                       "--input", current.relative_to(root).as_posix(), "--baseline", original.relative_to(root).as_posix(),
                       "--expected-sha256", sha256_bytes(edited_raw), "--baseline-sha256", sha256_bytes(original_raw),
                       "--output", report_path.relative_to(root).as_posix()]
            process = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
            require(process.returncode == 0, "synthetic_review_cli_failed")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            changed_names = [item["name"] for item in report["comparison"]["paired_bookmarks"] if not item["text_equal"]]
            if variant == "edited":
                require(bool(changed_names), "synthetic_edit_not_observed")
            else:
                require(report["comparison"]["state"] == "partial" and
                        any(item["name"] == tracked for item in report["comparison"]["unresolved_bookmarks"]),
                        "synthetic_tracked_change_cleared")
            try:
                inspect_generated_docx(edited_raw, [block for block in blocks if block["audience"] == "body"], images)
            except ContractError as exc:
                strict_check = {"state": "rejected_as_expected", "reason": str(exc)}
            else:
                raise ContractError("generated_strict_check_was_weakened")
            controls.append({"variant": variant, "docx": current.relative_to(root).as_posix(),
                             "sha256": sha256_bytes(edited_raw), "changes": changes,
                             "report": report_path.relative_to(root).as_posix(), "report_sha256": sha256_bytes(report_path.read_bytes()),
                             "comparison_state": report["comparison"]["state"], "changed_bookmarks": changed_names,
                             "unresolved_bookmark_count": len(report["comparison"]["unresolved_bookmarks"]),
                             "command": command, "exit_code": process.returncode, "stdout": process.stdout,
                             "stderr": process.stderr, "original_generator_check": strict_check,
                             "professional_review": report["professional_review"]})
        require(original.read_bytes() == original_raw, "original_docx_mutated")
        summary["cases"].append({"business": business, "input": relative, "input_sha256": sha256_bytes(spec_raw),
                                  "original_docx": original.relative_to(root).as_posix(), "original_sha256": sha256_bytes(original_raw),
                                  "original_generated_verify": verified, "controls": controls})
    with (target / "summary.json").open("xb") as stream:
        stream.write(canonical_bytes(summary) + b"\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    options = parser.parse_args()
    result = run(Path(options.root).resolve(strict=True), options.output)
    print(json.dumps({"case_count": len(result["cases"]), "controls": sum(len(case["controls"]) for case in result["cases"]),
                      "professional_review": result["professional_review"]}, ensure_ascii=False))
