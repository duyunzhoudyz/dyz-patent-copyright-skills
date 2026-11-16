"""显式调用已安装LibreOffice另存三份合成DOCX；非默认测试，不代表手动Word或视觉验收。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from tools.core import canonical_bytes, require, safe_path, sha256_bytes
from tools.document_review import review_docx


def run(root, *, cases, output, office_tool, synthetic, business=None):
    require(synthetic, "synthetic_only")
    case_bytes = safe_path(root, cases).read_bytes()
    inputs = json.loads(case_bytes)
    require(inputs.get("scope") == "three_business_author_constructed_synthetic_docx_engineering_controls",
            "synthetic_case_manifest_required")
    binary = Path(office_tool)
    require(binary.is_absolute() and binary.is_file() and binary.name in {"soffice.com", "soffice.exe"},
            "explicit_installed_office_tool_required")
    target = safe_path(root, output, must_exist=False)
    require(target.parent.is_dir() and not target.exists(), "new_output_directory_required")
    target.mkdir()
    report = {"scope": "actual_libreoffice_import_save_of_programmatically_edited_synthetic_docx",
              "case_manifest": cases, "case_manifest_sha256": sha256_bytes(case_bytes), "office_tool": str(binary),
              "office_tool_sha256": sha256_bytes(binary.read_bytes()), "tool_version": "1.0", "cases": [],
              "source": "evals/maturity_docx_office_roundtrip.py",
              "source_sha256": sha256_bytes((root / "evals/maturity_docx_office_roundtrip.py").read_bytes()),
              "selected_business": business, "manual_word_ui": "not_executed", "visual_review": "not_performed", "professional_review": "not_performed"}
    for case in inputs["cases"]:
        if business is not None and case["business"] != business:
            continue
        control = next(item for item in case["controls"] if item["variant"] == "edited")
        source = safe_path(root, control["docx"])
        source_raw = source.read_bytes()
        original = safe_path(root, case["original_docx"]).read_bytes()
        require(sha256_bytes(source_raw) == control["sha256"] and sha256_bytes(original) == case["original_sha256"],
                "synthetic_case_bytes_changed")
        preflight = review_docx(source_raw)
        require(preflight["current"]["readback_state"] == "complete_supported_subset", "office_input_not_preflighted")
        folder = target / case["business"]
        folder.mkdir()
        profile = folder / "office-profile"
        saved = folder / "saved"
        saved.mkdir()
        command = [str(binary), "-env:UserInstallation=" + profile.as_uri(), "--headless", "--nologo", "--nodefault",
                   "--norestore", "--convert-to", "docx:Office Open XML Text", "--outdir", str(saved), str(source)]
        started = time.perf_counter()
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        actual = saved / source.name
        entry = {"business": case["business"], "command": command, "exit_code": process.returncode,
                 "elapsed_seconds": round(time.perf_counter() - started, 3), "stdout": process.stdout, "stderr": process.stderr,
                 "input": control["docx"], "input_sha256": sha256_bytes(source_raw), "output_exists": actual.is_file(),
                 "profile_path": profile.relative_to(root).as_posix(), "profile_cleanup": "pending_process_check"}
        report["cases"].append(entry)
        if process.returncode == 0 and actual.is_file():
            raw = actual.read_bytes()
            entry.update(output=actual.relative_to(root).as_posix(), output_sha256=sha256_bytes(raw))
            for label, baseline in (("edited_input", source_raw), ("original", original)):
                observed = review_docx(raw, baseline)
                destination = folder / ("readback-vs-" + label + ".json")
                with destination.open("xb") as stream:
                    stream.write(canonical_bytes(observed) + b"\n")
                entry[label] = {"report": destination.relative_to(root).as_posix(), "sha256": sha256_bytes(destination.read_bytes()),
                                "comparison_state": observed["comparison"]["state"],
                                "changed_bookmarks": [item["name"] for item in observed["comparison"]["paired_bookmarks"] if not item["text_equal"]],
                                "unresolved_bookmarks": [item["name"] for item in observed["comparison"]["unresolved_bookmarks"]],
                                "literal_stream_equal": observed["comparison"]["main_literal_stream_equal"],
                                "notice_codes": sorted({item["code"] for item in observed["current"]["notices"]})}
        require(source.read_bytes() == source_raw, "office_source_was_overwritten")
        with (target / ("execution-" + str(len(report["cases"])) + ".json")).open("xb") as stream:
            stream.write(canonical_bytes(report) + b"\n")
    with (target / "execution.json").open("xb") as stream:
        stream.write(canonical_bytes(report) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--office-tool", required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--business", choices=("patent", "software", "standard"))
    args = parser.parse_args()
    result = run(Path(args.root).resolve(strict=True), cases=args.cases, output=args.output,
                 office_tool=args.office_tool, synthetic=args.synthetic, business=args.business)
    print(json.dumps({"cases": len(result["cases"]), "saved": sum(item["output_exists"] for item in result["cases"]),
                      "professional_review": result["professional_review"]}, ensure_ascii=False))
