"""Phase D tests: multi-stack software discovery, 3-batch intake, PNG metadata stripping,
standards v3 profile, declarative external template mapper, 6-dim review & circularity,
terminology standard specimen, and CLI help subcommand.
"""
import copy
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from tools import documents, media_prep, software_discovery, software_intake, standard_review, template_mapper
from tools import omml, standard_pdf
from tools.core import ContractError, sha256_bytes

ROOT = Path(__file__).resolve().parents[1]


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _make_png(*, extra_chunk: tuple[bytes, bytes] | None = None) -> bytes:
    chunk = _png_chunk

    parts = [
        b"\x89PNG\r\n\x1a\n",
        chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)),
    ]
    if extra_chunk is not None:
        parts.append(chunk(extra_chunk[0], extra_chunk[1]))
    raw_scanlines = b"".join(b"\x00" + b"\x11\x22\x33" * 4 for _ in range(4))
    parts.append(chunk(b"IDAT", zlib.compress(raw_scanlines)))
    parts.append(chunk(b"IEND", b""))
    return b"".join(parts)


def _update_zip(raw, *, replacements=None, additional=None):
    replacements = replacements or {}
    target = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as reader, zipfile.ZipFile(target, "w") as writer:
        for info in reader.infolist():
            writer.writestr(info, replacements[info.filename] if info.filename in replacements else reader.read(info))
        for name, value in (additional or {}).items():
            writer.writestr(name, value)
    return target.getvalue()


def _valid_context() -> dict:
    return {
        "sensitivity": "synthetic",
        "purpose": "software_internal_preparation",
        "now": "2026-11-24T00:00:00+00:00",
        "environment": {
            "assessment_evidence": "local_unit_test_fixture",
            "data_paths": [
                {"id": pid, "mode": "local" if pid != "telemetry" else "disabled",
                 "verified": True, "evidence": f"unit-test-{pid}-verified"}
                for pid in ("host_model", "index", "telemetry", "tools", "logs", "subprocess")
            ],
        },
        "permissions": [
            {
                "action": act,
                "purpose": "software_internal_preparation",
                "recipient": "local_tool",
                "decision": "allow",
                "authority_evidence": "unit-test-auth",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "valid_until": "2028-01-01T00:00:00+00:00",
            }
            for act in ("local_read", "local_write", "local_process")
        ],
    }


class MultiStackDiscoveryAndMediaTests(unittest.TestCase):
    def test_multistack_and_english_readme_discovery_hits_many_fields_without_auto_confirm(self):
        with tempfile.TemporaryDirectory(prefix="dyz-disc-") as folder:
            root = Path(folder)
            (root / "Cargo.toml").write_text(
                '[package]\nname = "harbor-cli"\nversion = "2.4.1"\n'
                'description = "Deterministic telemetry collector"\nedition = "2021"\n'
                '[dependencies]\nserde = "1.0"\ntokio = "1.0"\n',
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "# Harbor CLI\n"
                "- Version: 2.4.1\n"
                "- Purpose: Deterministic edge log archival\n"
                "- Domain: Industrial telemetry\n"
                "- Platform: Linux / Windows x86_64\n"
                "- OS: Ubuntu 22.04\n"
                "- Technical Features: Zero-copy framing and checksum verification\n",
                encoding="utf-8",
            )
            (root / "src").mkdir()
            (root / "src/main.rs").write_text("fn main() {}\n", encoding="utf-8")

            files = [
                {"id": "f1", "path": "Cargo.toml"},
                {"id": "f2", "path": "README.md"},
                {"id": "f3", "path": "src/main.rs"},
            ]
            result = software_discovery.discover({
                "context": _valid_context(),
                "authorized_root": str(root),
                "files": files,
                "material_permissions": [{"paths": [f["path"] for f in files], "decision": "allow", "evidence_id": "EV-P"}],
            })
            found_fields = {row["field"] for row in result["field_candidates"] if row["status"] != "unknown"}
            self.assertGreaterEqual(len(found_fields), 9, found_fields)
            self.assertIn("version", found_fields)
            self.assertIn("programming_language", found_fields)
            self.assertIn("development_tools", found_fields)
            self.assertIn("development_purpose", found_fields)
            self.assertIn("application_domain", found_fields)
            self.assertIn("technical_features", found_fields)
            # Dates MUST remain unknown (never fabricated!)
            for date_field in ("completed_date", "published_date"):
                row = next(r for r in result["field_candidates"] if r["field"] == date_field)
                self.assertEqual("unknown", row["status"])

    def test_go_mod_and_pom_xml_discovery(self):
        with tempfile.TemporaryDirectory(prefix="dyz-disc-go-") as folder:
            root = Path(folder)
            (root / "go.mod").write_text("module example.invalid/netprobe\n\ngo 1.22\n\nrequire (\n\tgithub.com/pkg/errors v0.9.1\n)\n", encoding="utf-8")
            (root / "pom.xml").write_text(
                "<project><artifactId>billing-core</artifactId><version>3.1.0</version>"
                "<description>Invoice ledger</description><properties><java.version>21</java.version></properties></project>",
                encoding="utf-8",
            )
            files = [{"id": "g", "path": "go.mod"}, {"id": "p", "path": "pom.xml"}]
            res = software_discovery.discover({
                "context": _valid_context(),
                "authorized_root": str(root),
                "files": files,
                "material_permissions": [{"paths": ["go.mod", "pom.xml"], "decision": "allow", "evidence_id": "EV"}],
            })
            values = [str(r["value"]) for r in res["field_candidates"] if r["status"] != "unknown"]
            joined = " ".join(values)
            self.assertIn("Go 1.22", joined)
            self.assertIn("Java 21", joined)
            self.assertIn("3.1.0", joined)

    def test_png_ancillary_strip_and_capture_manifest(self):
        noisy = _make_png(extra_chunk=(b"tEXt", b"Software\x00BrowserCapture"))
        clean_info = media_prep.strip_png_ancillary_chunks(noisy)
        self.assertEqual(["tEXt"], clean_info["stripped_chunks"])
        self.assertNotEqual(clean_info["original_sha256"], clean_info["clean_sha256"])
        # Re-stripping clean PNG is idempotent with zero stripped chunks
        again = media_prep.strip_png_ancillary_chunks(clean_info["clean_png"])
        self.assertEqual([], again["stripped_chunks"])

        # APNG MUST be rejected
        apng = _make_png(extra_chunk=(b"acTL", struct.pack(">II", 2, 0)))
        with self.assertRaisesRegex(ContractError, "media_animated_png_unsupported"):
            media_prep.strip_png_ancillary_chunks(apng)

        with tempfile.TemporaryDirectory(prefix="dyz-cap-") as folder:
            root = Path(folder)
            (root / "shot.png").write_bytes(noisy)
            report = media_prep.validate_capture_manifest(root, {
                "schema": "dyz-screenshot-capture-manifest-v1",
                "tool": "playwright-optional-external",
                "software_version": "1.0",
                "captures": [{
                    "id": "cap1", "operation_id": "op1", "path": "shot.png",
                    "sha256": sha256_bytes(noisy),
                    "captured_at": "2026-11-24T10:00:00+00:00",
                    "visible_state": "main window sorted list",
                    "permission_decision": "allow", "authority_evidence": "EV-CAP",
                }],
            })
            self.assertEqual("checked_needs_visual_review", report["status"])
            self.assertTrue(report["captures"][0]["needs_metadata_strip"])

    def test_discovery_rejects_unsafe_config_and_avoids_false_version_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = {
                "README.md": "# Synthetic app\nRequires Python version 3.11.\n",
                "go.mod": "module example.invalid/collector // module note\ngo 1.24 // toolchain note\n",
                "requirements.txt": "sample==1.2\nhttps://fixture-user:fixture-pass@example.invalid/sample.whl\n",
            }
            for name, text in sources.items():
                (root / name).write_text(text, encoding="utf-8")
            files = [{"path": name} for name in (*sources, "pom.xml")]
            payload = {"context": _valid_context(), "authorized_root": str(root), "files": files,
                       "material_permissions": [{"paths": [row["path"] for row in files],
                                                 "decision": "allow", "evidence_id": "EV"}]}
            for pom in ('<!DOCTYPE project><project><version>9.9</version></project>',
                        "<project><version>9.9</version>" + "<d>" * 70 + "</d>" * 70 + "</project>"):
                with self.subTest(pom=pom[:20]):
                    (root / "pom.xml").write_text(pom, encoding="utf-8")
                    result = software_discovery.discover(payload)
                    version = next(row for row in result["field_candidates"] if row["field"] == "version")
                    self.assertEqual("unknown", version["status"])
                    values = json.dumps(result["field_candidates"])
                    self.assertIn("collector", values)
                    self.assertIn("Go 1.24", values)
                    self.assertNotIn("toolchain note", values)
                    self.assertNotIn("fixture-pass", values)
                    self.assertTrue(any(row.get("reason") == "configuration_unreadable" for row in result["facts"]))

    def test_discovery_rejects_denied_hardlink_before_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "declined.py").write_text("pass\n", encoding="utf-8")
            os.link(root / "declined.py", root / "alias.py")
            with patch.object(Path, "open", side_effect=AssertionError("unapproved read")):
                with self.assertRaisesRegex(ContractError, "material_permission_not_proven"):
                    software_discovery.discover({
                        "context": _valid_context(), "authorized_root": str(root),
                        "files": [{"path": "alias.py", "local_permission": {"decision": "allow", "evidence_id": "EV"}}],
                        "material_permissions": [{"paths": ["declined.py"], "decision": "deny"}],
                    })

    def test_png_structure_rejects_invalid_chunk_order_and_lengths(self):
        raw = _make_png()
        header, end = raw[8:33], raw[-12:]
        for image, code in (
            (raw[:8] + _png_chunk(b"tEXt", b"note") + raw[8:], "media_png_ihdr_invalid"),
            (raw[:33] + header + raw[33:], "media_png_ihdr_invalid"),
            (raw[:33] + _png_chunk(b"IDAT", b"") + end, "media_png_idat_empty"),
            (raw[:-12] + _png_chunk(b"IEND", b"fixture"), "media_png_iend_invalid"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(ContractError, code):
                media_prep.strip_png_ancillary_chunks(image)

    def test_capture_manifest_rejects_bad_fields_size_and_alias_before_read(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside_folder:
            root = Path(folder)
            outside = Path(outside_folder)
            png = _make_png()
            (root / "shot.png").write_bytes(png)
            (outside / "secret.png").write_bytes(png)
            (root / "folder.png").mkdir()
            row = {"id": "cap1", "operation_id": "op1", "path": "shot.png", "sha256": sha256_bytes(png),
                   "captured_at": "2026-11-24T10:00:00+00:00", "visible_state": "Fixture",
                   "permission_decision": "allow", "authority_evidence": "EV"}
            manifest = {"schema": "dyz-screenshot-capture-manifest-v1", "tool": "fixture", "software_version": "1"}
            cases = [([dict(row, authority_evidence=" ")], "empty:authority_evidence"),
                     ([dict(row, source={})], "capture_record_text_invalid"),
                     ([dict(row, redaction_evidence=" ")], "capture_record_text_invalid"),
                     ([dict(row, path="folder.png")], "capture_file_required"),
                     ([row, dict(row, id="cap2", path="shot.png")], "capture_duplicate_path")]
            with patch.object(os, "open", side_effect=AssertionError("unexpected read")):
                for captures, code in cases:
                    with self.subTest(code=code), self.assertRaisesRegex(ContractError, code):
                        media_prep.validate_capture_manifest(root, dict(manifest, captures=captures))
                with patch.object(media_prep, "MAX_PNG_BYTES", len(png) - 1):
                    with self.assertRaisesRegex(ContractError, "capture_png_size_invalid"):
                        media_prep.validate_capture_manifest(root, dict(manifest, captures=[row]))
                # Hardlink escaping outside root and intra-root hardlink MUST be rejected before os.open!
                os.link(outside / "secret.png", root / "escaped.png")
                with self.assertRaisesRegex(ContractError, "capture_file_required"):
                    media_prep.validate_capture_manifest(
                        root, dict(manifest, captures=[dict(row, path="escaped.png")]),
                    )
                (root / "escaped.png").unlink()
                os.link(root / "shot.png", root / "alias.png")
                with self.assertRaisesRegex(ContractError, "capture_file_required"):
                    media_prep.validate_capture_manifest(
                        root, dict(manifest, captures=[dict(row, path="alias.png")]),
                    )
                (root / "alias.png").unlink()

            # TOCTOU: st_nlink changes to 2 between pre-check and open MUST raise capture_file_changed!
            real_fstat = os.fstat

            def mutated_fstat(fd):
                st = real_fstat(fd)
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev, 2, st.st_uid, st.st_gid,
                                       st.st_size, st.st_atime, st.st_mtime, st.st_ctime))

            with patch.object(os, "fstat", side_effect=mutated_fstat):
                with self.assertRaisesRegex(ContractError, "capture_file_changed"):
                    media_prep.validate_capture_manifest(root, dict(manifest, captures=[row]))

    def test_png_ihdr_validation_and_idat_decoding_and_adam7(self):
        from tools import software_delivery

        def build_raw_png(ihdr_args, idat_payload, *, extra_chunks=()):
            chunks = [b"\x89PNG\r\n\x1a\n", _png_chunk(b"IHDR", struct.pack(">IIBBBBB", *ihdr_args))]
            chunks.extend(extra_chunks)
            chunks.append(_png_chunk(b"IDAT", idat_payload))
            chunks.append(_png_chunk(b"IEND", b""))
            return b"".join(chunks)

        valid_4x4 = zlib.compress(b"".join(b"\x00" + b"\x11\x22\x33" * 4 for _ in range(4)))
        # Invalid IHDR fields rejected by BOTH media_prep and software_delivery._png
        for label, ihdr_args, media_code, delivery_code in (
            ("bad_color_depth_rgb4", (4, 4, 4, 2, 0, 0, 0), "media_png_ihdr_invalid", "screenshot_png_header"),
            ("bad_color_type_7", (4, 4, 8, 7, 0, 0, 0), "media_png_ihdr_invalid", "screenshot_png_header"),
            ("bad_compression", (4, 4, 8, 2, 1, 0, 0), "media_png_ihdr_invalid", "screenshot_png_header"),
            ("bad_filter_method", (4, 4, 8, 2, 0, 1, 0), "media_png_ihdr_invalid", "screenshot_png_header"),
            ("bad_interlace", (4, 4, 8, 2, 0, 0, 2), "media_png_ihdr_invalid", "screenshot_png_header"),
            ("decompressed_bomb_ihdr", (5000, 5000, 16, 6, 0, 0, 0), "media_png_dimensions_exceeded", "screenshot_png_dimensions"),
        ):
            bad_png = build_raw_png(ihdr_args, valid_4x4)
            with self.subTest(ihdr=label):
                with self.assertRaisesRegex(ContractError, media_code):
                    media_prep.strip_png_ancillary_chunks(bad_png)
                with self.assertRaisesRegex(ContractError, delivery_code):
                    software_delivery._png(bad_png)

        # Undecodable / mismatched / bomb IDAT rejected by media_prep.strip_png_ancillary_chunks
        for label, idat_bytes, code in (
            ("not_zlib", b"not-a-zlib-stream", "media_png_idat_corrupt"),
            ("truncated_zlib", valid_4x4[:-4], "media_png_idat_corrupt"),
            ("trailing_garbage", valid_4x4 + b"EXTRA", "media_png_idat_corrupt"),
            ("too_short_pixels", zlib.compress(b"\x00" * 10), "media_png_idat_size_mismatch"),
            ("too_long_pixels", zlib.compress(b"\x00" * 200), "media_png_idat_size_mismatch"),
            ("png_bomb_small_dim", zlib.compress(b"\x00" * (1024 * 1024)), "media_png_idat_size_mismatch"),
            ("bad_filter_byte", zlib.compress(b"".join(b"\x09" + b"\x11\x22\x33" * 4 for _ in range(4))), "media_png_idat_corrupt"),
        ):
            bad_png = build_raw_png((4, 4, 8, 2, 0, 0, 0), idat_bytes)
            with self.subTest(idat=label):
                with self.assertRaisesRegex(ContractError, code):
                    media_prep.strip_png_ancillary_chunks(bad_png)

        # Indexed color_type=3 without PLTE MUST fail; with valid PLTE MUST pass
        idx_scanlines = zlib.compress(b"".join(b"\x00" + b"\x00\x01\x00\x01" for _ in range(4)))
        with self.assertRaisesRegex(ContractError, "media_png_plte_invalid"):
            media_prep.strip_png_ancillary_chunks(build_raw_png((4, 4, 8, 3, 0, 0, 0), idx_scanlines))
        valid_idx = build_raw_png((4, 4, 8, 3, 0, 0, 0), idx_scanlines,
                                  extra_chunks=[_png_chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")])
        self.assertEqual(4, media_prep.strip_png_ancillary_chunks(valid_idx)["width"])

        # Valid Adam7 interlaced 5x5 RGB 8-bit PNG MUST pass (exact pass byte count)
        adam7_passes = media_prep._png_scanline_layout(5, 5, 8, 2, 1)
        adam7_raw = b"".join(b"\x00" + b"\x22" * (stride - 1) for pass_h, stride in adam7_passes for _ in range(pass_h))
        adam7_png = build_raw_png((5, 5, 8, 2, 0, 0, 1), zlib.compress(adam7_raw))
        res_adam7 = media_prep.strip_png_ancillary_chunks(adam7_png)
        self.assertEqual((5, 5), (res_adam7["width"], res_adam7["height"]))


class StandardsV3TemplateMapperAndSixDimTests(unittest.TestCase):
    def test_standards_v3_profile_supports_omml_and_roundtrips(self):
        profile = documents.document_profile("dyz-standard-internal-v3")
        self.assertEqual("dyz-standard-internal-v3", profile["profile_id"])
        self.assertIn("formula", profile["supported_objects"])
        blocks = [
            {"id": "Title", "kind": "title", "text": "合成标准草案 v3"},
            {"id": "H1", "kind": "heading1", "text": "1 范围"},
            {"id": "P1", "kind": "paragraph", "text": "本文件规定了测试要求。"},
            {"id": "F1", "kind": "formula", "text": r"R = \frac{U}{I}"},
        ]
        raw = documents.make_docx(blocks, [], profile="dyz-standard-internal-v3")
        checked = documents.inspect_generated_docx(raw, blocks, [], profile="dyz-standard-internal-v3")
        self.assertTrue(checked["source_text_equal"])
        self.assertEqual("PAGE", checked["page_numbering"]["instruction"])

    def test_standard_pdf_validates_and_reads_only_supported_omml(self):
        formula = {"id": "Calc", "kind": "formula", "text": "R=U/I"}
        raw = documents.make_docx([formula], [], profile="dyz-standard-internal-v3")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        math_tag = "{" + omml.M + "}oMath"
        math = next(document.iter(math_tag))
        state = standard_pdf._document_state(raw)
        self.assertEqual("R=U/I", state["bookmarks"]["Calc"]["text"])
        self.assertEqual([], state["unsupported_objects"])
        header = state["visible_parts"]["word/header1.xml"].rstrip("\n")
        self.assertTrue(standard_pdf._ordered_pdf_evidence(state, [f"{header}\nR=U/I\n1\n"])["matched"])
        self.assertFalse(standard_pdf._ordered_pdf_evidence(state, [f"{header}\nR = U/I\n1\n"])["matched"])

        math.tag = "{" + omml.M + "}oMathPara"
        inline = ET.Element(math_tag)
        for child in list(math):
            math.remove(child)
            inline.append(child)
        math.append(inline)
        wrapped = _update_zip(raw, replacements={"word/document.xml": ET.tostring(document)})
        wrapped_state = standard_pdf._document_state(wrapped)
        self.assertEqual("R=U/I", wrapped_state["bookmarks"]["Calc"]["text"])
        self.assertEqual([], wrapped_state["unsupported_objects"])

        ET.SubElement(inline, "{" + template_mapper.W + "}ins")
        unsupported = _update_zip(raw, replacements={"word/document.xml": ET.tostring(document)})
        rejected = standard_pdf._document_state(unsupported)
        self.assertEqual([{"part": "word/document.xml", "kind": "oMathPara"}], rejected["unsupported_objects"])
        self.assertEqual("", rejected["bookmarks"]["Calc"]["text"])

    def test_template_mapper_audits_rejects_macros_and_maps_cleanly(self):
        # Build a clean synthetic template DOCX using existing make_docx
        tpl_bytes = documents.make_docx(
            [{"id": "Intro", "kind": "heading1", "text": "模板占位"}], [], profile="dyz-standard-internal-v2"
        )
        audit = template_mapper.audit_template(tpl_bytes)
        self.assertEqual("audited_ready_for_declarative_mapping", audit["status"])
        self.assertIn("Heading1", audit["styles"])

        # Inject a fake VBA macro part -> MUST be rejected!
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf, "w") as zout:
            for item in zin.infolist():
                zout.writestr(item, zin.read(item.filename))
            zout.writestr("word/vbaProject.bin", b"FAKEVBA")
        bad_audit = template_mapper.audit_template(buf.getvalue())
        self.assertEqual("rejected", bad_audit["status"])
        self.assertIn("template_macros_or_ole_forbidden", bad_audit["blocked_reasons"])

        # Inject uppercase .RELS external link + inline OLEObject -> MUST BOTH be rejected!
        buf2 = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf2, "w") as zout:
            for item in zin.infolist():
                raw_part = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    raw_part = raw_part.replace(
                        b"</w:body>",
                        b"<w:p><w:r><w:object><o:OLEObject xmlns:o='urn:schemas-microsoft-com:office:office'/></w:object></w:r></w:p></w:body>",
                    )
                zout.writestr(item, raw_part)
            zout.writestr(
                "word/_rels/settings.xml.RELS",
                b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                b'<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                b'Target="https://evil.invalid" TargetMode="external"/></Relationships>',
            )
        bad_audit2 = template_mapper.audit_template(buf2.getvalue())
        self.assertEqual("rejected", bad_audit2["status"])
        self.assertIn("template_external_links_forbidden", bad_audit2["blocked_reasons"])
        self.assertIn("template_unsupported_inline_objects_forbidden", bad_audit2["blocked_reasons"])

        # UTF-16 DTD / forged Zip size / external Target without TargetMode / malicious header XML MUST be rejected!
        buf_dtd = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_dtd, "w") as zout:
            for item in zin.infolist():
                raw_part = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    raw_part = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE foo [<!ENTITY x "y">]>'
                                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>').encode("utf-16")
                zout.writestr(item, raw_part)
        with self.assertRaisesRegex(ContractError, "template_dtd_forbidden"):
            template_mapper.audit_template(buf_dtd.getvalue())

        buf_hdr = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_hdr, "w") as zout:
            for item in zin.infolist():
                zout.writestr(item, zin.read(item.filename))
            zout.writestr(
                "word/my_custom_header.xml",
                b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b'<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                b'<w:r><w:instrText>INCLUDEPICTURE "https://evil.invalid/a.png"</w:instrText></w:r>'
                b'<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:hdr>',
            )
        hdr_audit = template_mapper.audit_template(buf_hdr.getvalue())
        self.assertEqual("rejected", hdr_audit["status"])
        self.assertIn("template_unsupported_inline_objects_forbidden", hdr_audit["blocked_reasons"])

        # Round-2 P0/P1 regressions: uppercase word/STYLES.XML DTD, vanish in styles, fldData smuggling,
        # child-tag instrText smuggling, ms-msdt: & //UNC external rel targets, and UTF-16 mc:Ignorable!
        buf_styles_dtd = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_styles_dtd, "w") as zout:
            for item in zin.infolist():
                if item.filename == "word/styles.xml":
                    zout.writestr("word/STYLES.XML", b'<?xml version="1.0"?><!DOCTYPE s [<!ENTITY x "y">]><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
                else:
                    zout.writestr(item, zin.read(item.filename))
        with self.assertRaisesRegex(ContractError, "template_dtd_forbidden"):
            template_mapper.audit_template(buf_styles_dtd.getvalue())

        buf_fld_smug = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_fld_smug, "w") as zout:
            for item in zin.infolist():
                if item.filename == "word/header1.xml":
                    continue
                zout.writestr(item, zin.read(item.filename))
            zout.writestr(
                "word/header1.xml",
                b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b'<w:p><w:r><w:fldChar w:fldCharType="begin"><w:fldData>UEsDBBQ=</w:fldData></w:fldChar></w:r>'
                b'<w:r><w:instrText>PAGE</w:instrText></w:r>'
                b'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                b'<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:hdr>',
            )
        self.assertEqual("rejected", template_mapper.audit_template(buf_fld_smug.getvalue())["status"])

        buf_msdt = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_msdt, "w") as zout:
            for item in zin.infolist():
                zout.writestr(item, zin.read(item.filename))
            zout.writestr(
                "word/_rels/footer1.xml.rels",
                b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                b'<Relationship Id="rId99" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                b'Target="ms-msdt:/id PCWDiagnostic"/></Relationships>',
            )
        self.assertIn("template_external_links_forbidden", template_mapper.audit_template(buf_msdt.getvalue())["blocked_reasons"])

        # Round-3 P1-1: non-.xml OPC part declared as XML ContentType + .vml/.svg MUST be audited/blocked!
        buf_dat_xml = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_dat_xml, "w") as zout:
            for item in zin.infolist():
                raw_part = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    raw_part = raw_part.replace(
                        b"</Types>",
                        b'<Override PartName="/word/header1.dat" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/></Types>',
                    )
                zout.writestr(item, raw_part)
            zout.writestr(
                "word/header1.dat",
                b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "1">]><w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
            )
        with self.assertRaisesRegex(ContractError, "template_dtd_forbidden"):
            template_mapper.audit_template(buf_dat_xml.getvalue())

        # Round-4 P1-2/3: misplaced .rels smuggling & percent-encoded Override MUST be rejected!
        buf_rels_smug = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_rels_smug, "w") as zout:
            for item in zin.infolist():
                raw_part = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    raw_part = raw_part.replace(
                        b"</Types>",
                        b'<Override PartName="/word/header1.rels" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/></Types>',
                    )
                zout.writestr(item, raw_part)
            zout.writestr(
                "word/header1.rels",
                b'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>x</w:t></w:r></w:p></w:hdr>',
            )
        self.assertEqual("rejected", template_mapper.audit_template(buf_rels_smug.getvalue())["status"])

        buf_pct = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_pct, "w") as zout:
            for item in zin.infolist():
                raw_part = zin.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    raw_part = raw_part.replace(
                        b"</Types>",
                        b'<Override PartName="/word/header%201.dat" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/></Types>',
                    )
                zout.writestr(item, raw_part)
            zout.writestr(
                "word/header 1.dat",
                b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "1">]><w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
            )
        with self.assertRaisesRegex(ContractError, "template_dtd_forbidden"):
            template_mapper.audit_template(buf_pct.getvalue())

        # Namespace declarations referenced by mc:Ignorable MUST survive apply_template_mapping intact (even for UTF-16)!
        buf_mc = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(tpl_bytes), "r") as zin, zipfile.ZipFile(buf_mc, "w") as zout:
            for item in zin.infolist():
                raw_part = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    txt = raw_part.decode("utf-8").replace(
                        'encoding="UTF-8"', 'encoding="UTF-16"', 1,
                    ).replace(
                        "encoding='UTF-8'", "encoding='UTF-16'", 1,
                    ).replace(
                        'encoding="utf-8"', 'encoding="UTF-16"', 1,
                    ).replace(
                        "encoding='utf-8'", "encoding='UTF-16'", 1,
                    ).replace(
                        "<w:document ",
                        '<w:document xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" mc:Ignorable="w14" ',
                        1,
                    )
                    raw_part = txt.encode("utf-16")
                zout.writestr(item, raw_part)
        with tempfile.TemporaryDirectory(prefix="dyz-tpl-mc-") as mc_folder:
            mc_root = Path(mc_folder)
            (mc_root / "mc.docx").write_bytes(buf_mc.getvalue())
            template_mapper.apply_template_mapping(
                mc_root,
                template_path="mc.docx",
                output_path="mc-out.docx",
                mapping_spec={
                    "profile_id": "mc-test",
                    "license_and_origin_declaration": {"origin": "syn", "license_basis": "syn", "user_confirmed_rights": "syn"},
                    "style_map": {"body": "Normal"},
                },
                sections=[{"id": "S1", "role": "body", "text": "保命名空间测试"}],
            )
            with zipfile.ZipFile(mc_root / "mc-out.docx", "r") as zchk:
                out_xml = zchk.read("word/document.xml").decode("utf-8")
                self.assertIn("xmlns:w14=", out_xml)
                self.assertIn("mc:Ignorable=", out_xml)

        with tempfile.TemporaryDirectory(prefix="dyz-tpl-") as folder:
            root = Path(folder)
            (root / "org-tpl.docx").write_bytes(tpl_bytes)
            report = template_mapper.apply_template_mapping(
                root,
                template_path="org-tpl.docx",
                output_path="mapped.docx",
                mapping_spec={
                    "profile_id": "user-org-tpl-1",
                    "license_and_origin_declaration": {
                        "origin": "synthetic_local_test_template",
                        "license_basis": "original_synthetic_fixture",
                        "user_confirmed_rights": "local_test_only",
                    },
                    "style_map": {"heading1": "Heading1", "body": "Normal"},
                },
                sections=[
                    {"id": "S1", "role": "heading1", "text": "1 术语与定义"},
                    {"id": "S2", "role": "body", "text": "数据帧是由帧头与负载组成的单元。"},
                ],
            )
            self.assertTrue(report["template_unchanged"])
            self.assertEqual(2, report["mapped_count"])
            self.assertTrue((root / "mapped.docx").is_file())

    def test_template_rejects_deep_xml_relationship_aliases_and_unsupported_parts(self):
        template = documents.make_docx([{"id": "Intro", "kind": "heading1", "text": "Fixture"}], [],
                                       profile="dyz-standard-internal-v2")
        with zipfile.ZipFile(io.BytesIO(template)) as archive:
            doc = archive.read("word/document.xml")
            cts = archive.read("[Content_Types].xml")
        for tag in ("pict", "sdt", "control", "commentRangeStart", "commentReference", "ins", "del",
                    "moveFrom", "moveTo", "delText", "rPrChange", "pPrChange", "sectPrChange",
                    "cellIns", "cellDel", "cellMerge", "customXml", "subDoc", "contentPart"):
            with self.subTest(tag=tag):
                bad_doc = doc.replace(b"</w:body>", f"<w:{tag}/></w:body>".encode())
                audit = template_mapper.audit_template(_update_zip(template, replacements={"word/document.xml": bad_doc}))
                self.assertIn(tag.lower(), audit["unsupported_inline_objects"])
                self.assertEqual("rejected", audit["status"])
        txbody_doc = doc.replace(b"</w:body>", b'<a:txBody xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/></w:body>')
        txbody_audit = template_mapper.audit_template(_update_zip(template, replacements={"word/document.xml": txbody_doc}))
        self.assertIn("txbody", txbody_audit["unsupported_inline_objects"])
        self.assertEqual("rejected", txbody_audit["status"])
        # Non-XML extension with forged XML ContentType (both valid XML and JS payload) MUST be blocked into unsupported_attachments!
        for js_label, js_body in (("xml_body", b"<root/>"), ("js_body", b"alert(1)")):
            with self.subTest(forged_js=js_label):
                evil_ct = b'<Override PartName="/word/evil.js" ContentType="application/xml"/>'
                smuggled = _update_zip(
                    template,
                    replacements={"[Content_Types].xml": cts.replace(b"</Types>", evil_ct + b"</Types>")},
                    additional={"word/evil.js": js_body},
                )
                smug_audit = template_mapper.audit_template(smuggled)
                self.assertEqual("rejected", smug_audit["status"])
                self.assertIn("template_attachment_unsupported", smug_audit["blocked_reasons"])
                self.assertIn("word/evil.js", smug_audit["unsupported_attachments"])
        alternate = doc.replace(b"</w:body>", b'<mc:AlternateContent xmlns:mc="urn:synthetic-mc"/></w:body>')
        self.assertIn("alternatecontent", template_mapper.audit_template(_update_zip(
            template, replacements={"word/document.xml": alternate}))["unsupported_inline_objects"])
        nesting = b"<w:p>" * 150 + b"</w:p>" * 150
        deep_doc = doc.replace(b"</w:body>", nesting + b"</w:body>")
        with self.assertRaisesRegex(ContractError, "template_xml_limits_exceeded"):
            template_mapper.audit_template(_update_zip(template, replacements={"word/document.xml": deep_doc}))
        with patch.object(template_mapper, "MAX_XML_NODES", 3):
            with self.assertRaisesRegex(ContractError, "template_xml_limits_exceeded"):
                template_mapper.audit_template(template)
        alias = "word/relationship.data"
        relation_ct = (f'<Override PartName="/{alias}" ContentType="{template_mapper.REL_CONTENT_TYPE}"/>').encode()
        rel = (f'<Relationships xmlns="{template_mapper.REL}"><Relationship Id="R1" Type="hyperlink" '
               'Target="https://example.invalid/" TargetMode="External"/></Relationships>').encode()
        changed = _update_zip(template, replacements={"[Content_Types].xml": cts.replace(b"</Types>", relation_ct + b"</Types>")},
                              additional={alias: rel, "word/media/extra.txt": b"fixture"})
        report = template_mapper.audit_template(changed)
        self.assertEqual("rejected", report["status"])
        self.assertEqual(alias, report["external_links"][0]["part"])
        self.assertEqual(["word/media/extra.txt"], report["unsupported_attachments"])

        # Standalone customXml parts (item1.xml, itemProps1.xml, rels, case/encoding variants,
        # customXmlProperties+xml ContentType, customXml rel, and renamed datastoreItem) MUST be rejected
        # and NEVER passed through apply_template_mapping!
        cxml_cases = [
            ("item1_part", {}, {"customXml/item1.xml": b"<customData><secret>x</secret></customData>"}),
            ("itemProps_and_ct", {
                "[Content_Types].xml": cts.replace(
                    b"</Types>",
                    b'<Override PartName="/customXml/itemProps1.xml" '
                    b'ContentType="application/vnd.openxmlformats-officedocument.customXmlProperties+xml"/></Types>',
                ),
            }, {
                "customXml/itemProps1.xml": b'<ds:datastoreItem xmlns:ds="http://schemas.openxmlformats.org/officeDocument/2006/customXml" ds:itemID="{1111}"/>',
            }),
            ("uppercase_and_rels", {}, {
                "CustomXML/ITEM1.XML": b"<root/>",
                "customXml/_rels/item1.xml.rels": (
                    f'<Relationships xmlns="{template_mapper.REL}">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps" '
                    'Target="itemProps1.xml"/></Relationships>'
                ).encode(),
            }),
            ("ct_only_renamed_part", {
                "[Content_Types].xml": cts.replace(
                    b"</Types>",
                    b'<Override PartName="/word/data1.xml" '
                    b'ContentType="application/vnd.openxmlformats-officedocument.customXmlProperties+xml"/></Types>',
                ),
            }, {"word/data1.xml": b"<root/>"}),
            ("rel_only_customxml_type", {}, {
                "word/_rels/settings.xml.rels": (
                    f'<Relationships xmlns="{template_mapper.REL}">'
                    '<Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" '
                    'Target="data1.xml"/></Relationships>'
                ).encode(),
                "word/data1.xml": b"<root/>",
            }),
            ("renamed_datastore_ns", {}, {
                "word/hiddenStore.xml": b'<ds:datastoreItem xmlns:ds="http://schemas.openxmlformats.org/officeDocument/2006/customXml"/>',
            }),
        ]
        with tempfile.TemporaryDirectory(prefix="dyz-cxml-") as cxml_folder:
            cxml_root = Path(cxml_folder)
            valid_spec = {
                "profile_id": "cxml-test",
                "license_and_origin_declaration": {
                    "origin": "原创自有模板",
                    "license_basis": "已取得完整使用与再分发许可",
                    "user_confirmed_rights": "原创自有模板，已取得完整使用与再分发许可",
                },
                "style_map": {"body": "Normal"},
            }
            for label, repl, add in cxml_cases:
                with self.subTest(custom_xml=label):
                    bad_tpl = _update_zip(template, replacements=repl, additional=add)
                    cxml_audit = template_mapper.audit_template(bad_tpl)
                    self.assertEqual("rejected", cxml_audit["status"])
                    self.assertIn("template_custom_xml_parts_forbidden", cxml_audit["blocked_reasons"])
                    self.assertTrue(cxml_audit["forbidden_custom_xml_parts"])
                    tpl_file = cxml_root / f"{label}.docx"
                    tpl_file.write_bytes(bad_tpl)
                    with self.assertRaisesRegex(ContractError, "template_custom_xml_parts_forbidden"):
                        template_mapper.apply_template_mapping(
                            cxml_root, template_path=tpl_file.name, output_path=f"{label}-out.docx",
                            mapping_spec=valid_spec, sections=[{"id": "S1", "role": "body", "text": "x"}],
                        )
                    self.assertFalse((cxml_root / f"{label}-out.docx").exists())

    def test_template_mapping_rejects_aliases_placeholders_and_case_collisions(self):
        template = documents.make_docx([{"id": "Intro", "kind": "heading1", "text": "Fixture"}], [],
                                       profile="dyz-standard-internal-v2")
        decl = {"origin": "fixture", "license_basis": "original test fixture", "user_confirmed_rights": "EV"}
        spec = {"profile_id": "fixture", "license_and_origin_declaration": decl, "style_map": {"body": "Normal"}}
        sections = [{"id": "Section", "role": "body", "text": "Mapped"}]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "template.docx").write_bytes(template)
            os.link(root / "template.docx", root / "alias.docx")
            with self.assertRaisesRegex(ContractError, "template_file_or_link_invalid"):
                template_mapper.apply_template_mapping(root, template_path="alias.docx", output_path="out.docx",
                                                       mapping_spec=spec, sections=sections)
            (root / "alias.docx").unlink()
            (root / "real").mkdir()
            (root / "real/template.docx").write_bytes(template)
            try:
                (root / "linked").symlink_to(root / "real", target_is_directory=True)
            except OSError:
                if sys.platform != "win32":
                    raise
                subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "linked"), str(root / "real")],
                               check=True, capture_output=True, timeout=10)
            with self.assertRaisesRegex(ContractError, "template_path_invalid"):
                template_mapper.apply_template_mapping(root, template_path="linked/template.docx", output_path="out.docx",
                                                       mapping_spec=spec, sections=sections)
            for idx, value in enumerate((
                " Unknown ", "\u0301", "u\u0301nknown", "p\u0301ending", "t\u0301bd", "未\u0301知", "待\u0301定",
                "u\u20ddnknown", "u n k n o w n", "未 知", "(unknown)", "【（ U N K N O W N ）】！", "( n / a )",
            )):
                with self.subTest(placeholder=value):
                    bad_spec = dict(spec, license_and_origin_declaration=dict(decl, license_basis=value))
                    output = f"placeholder-{idx}.docx"
                    with self.assertRaisesRegex(ContractError, "template_license_declaration_required"):
                        template_mapper.apply_template_mapping(root, template_path="template.docx", output_path=output,
                                                               mapping_spec=bad_spec, sections=sections)
                    self.assertFalse((root / output).exists())
            for field, denied_text in (
                ("user_confirmed_rights", "无权使用"),
                ("user_confirmed_rights", "无权分发"),
                ("user_confirmed_rights", "不享有使用权"),
                ("user_confirmed_rights", "未获授权"),
                ("user_confirmed_rights", "未获许可"),
                ("license_basis", "无使用许可"),
                ("license_basis", "禁止使用"),
                ("license_basis", "禁止商用"),
                ("license_basis", "不得用于商业项目"),
                ("license_basis", "仅限参考"),
                ("license_basis", "内部保密"),
                ("origin", "版权归第三方未取得许可"),
                ("license_basis", "未经许可"),
                ("license_basis", "未经授权"),
                ("license_basis", "保留所有权利"),
                ("license_basis", "no license"),
                ("license_basis", "no_license"),
                ("license_basis", "no rights"),
                ("license_basis", "no permission"),
                ("license_basis", "without permission"),
                ("license_basis", "without authorization"),
                ("license_basis", "without license"),
                ("origin", "third-party template without permission"),
                ("license_basis", "not licensed"),
                ("user_confirmed_rights", "not authorized"),
                ("user_confirmed_rights", "unauthorized"),
                ("user_confirmed_rights", "not permitted"),
                ("user_confirmed_rights", "do not use"),
                ("user_confirmed_rights", "do not redistribute"),
                ("license_basis", "All rights reserved"),
                ("origin", "proprietary"),
                ("origin", "confidential"),
                ("user_confirmed_rights", "prohibited"),
                ("user_confirmed_rights", "forbidden"),
                ("user_confirmed_rights", "false"),
                ("user_confirmed_rights", "否"),
                # Round-4 P1 Grok Chinese negative license vocabulary MUST all be rejected
                ("license_basis", "不予授权"),
                ("license_basis", "不予许可"),
                ("user_confirmed_rights", "未予授权"),
                ("user_confirmed_rights", "未予许可"),
                ("origin", "没有版权"),
                ("origin", "无版权"),
                ("license_basis", "暂不授权"),
                ("user_confirmed_rights", "拒绝提供授权"),
                ("user_confirmed_rights", "拒绝提供许可"),
                # Positive clearance phrases paired with real denial or double negation MUST STILL be rejected
                ("user_confirmed_rights", "本模板不含未授权第三方材料，但暂不授权"),
                ("license_basis", "原创自有模板，无第三方版权限制，但无权使用"),
                ("license_basis", "原创自有模板，无第三方版权限制，但拒绝提供许可"),
                ("origin", "并非不含未授权第三方材料"),
                ("origin", "版权归第三方，无版权"),
                ("license_basis", "All rights reserved; written permission required for reuse"),
                ("license_basis", "All rights reserved. Prior written authorization is required."),
                ("user_confirmed_rights", "No third-party copyright restrictions, but no license"),
                ("user_confirmed_rights", "Free of unauthorized third-party materials; unauthorized for reuse"),
                ("user_confirmed_rights", "not free of unauthorized third-party materials"),
                # Zero-width Cf, invisible Mn/Lo fillers, control Cc, fullwidth NFKC, punctuation, and spaced-letter evasion MUST be blocked
                ("user_confirmed_rights", "未\u200b经\u200d授\ufeff权"),
                ("user_confirmed_rights", "不\u200b予\u200c授\u200d权"),
                ("license_basis", "未\u2060予\u00ad许\ufeff可"),
                ("origin", "没\u034f有\ufe0f版\u3164权"),
                ("origin", "无\u200b版\ufe0f权"),
                ("license_basis", "暂\u200b不\u034f授\u200d权"),
                ("user_confirmed_rights", "拒\u200b绝\ufeff提\u2060供\u200d授\u200c权"),
                ("user_confirmed_rights", "未\u0301经\u0301授\u0301权"),
                ("user_confirmed_rights", "u\u0301nauthorized"),
                ("user_confirmed_rights", "not\u200b authorized"),
                ("user_confirmed_rights", "not\u034f authorized"),
                ("user_confirmed_rights", "un\ufe0fauthorized"),
                ("user_confirmed_rights", "no\u3164 license"),
                ("user_confirmed_rights", "un\u00adauthorized"),
                ("origin", "原创\u200b模板"),
                ("origin", "original\x07template"),
                ("license_basis", "未 经 授 权"),
                ("license_basis", "不 予 授 权"),
                ("license_basis", "无·权·分·发"),
                ("license_basis", "无·版·权"),
                ("license_basis", "未,予,授,权"),
                ("license_basis", "暂-不-授-权"),
                ("license_basis", "拒·绝·提·供·许·可"),
                ("license_basis", "ｎｏｔ　ａｕｔｈｏｒｉｚｅｄ"),
                ("license_basis", "not.authorized"),
                ("license_basis", "not—authorized"),
                ("license_basis", "un-authorized"),
                ("license_basis", "do_not_redistribute"),
                ("origin", "p.r.o.p.r.i.e.t.a.r.y"),
                ("user_confirmed_rights", "u n a u t h o r i z e d"),
                ("user_confirmed_rights", "u_n_a_u_t_h_o_r_i_z_e_d"),
                ("user_confirmed_rights", "n\to\t\tl\ti\tc\te\tn\ts\te"),
                ("origin", "We do not own the copyright for this template"),
                ("license_basis", "No valid written commercial authorization"),
                ("user_confirmed_rights", "Not entitled to use the template"),
                ("user_confirmed_rights", "I have not obtained the required authorization"),
                ("user_confirmed_rights", "We have never received permission to reuse the template"),
                ("origin", "本单位并非该模板的权利人"),
                ("license_basis", "尚未取得相关权利人对本模板的再分发许可"),
                ("license_basis", "仍需取得模板权利人的书面授权"),
                ("license_basis", "All rights reserved. Use only with written permission."),
                ("user_confirmed_rights", "u\u20ddnauthorized"),
            ):
                with self.subTest(denied_field=field, denied_text=denied_text):
                    denied_spec = dict(spec, license_and_origin_declaration=dict(decl, **{field: denied_text}))
                    with self.assertRaisesRegex(ContractError, "template_license_denied_or_unconfirmed"):
                        template_mapper.apply_template_mapping(root, template_path="template.docx", output_path="out.docx",
                                                               mapping_spec=denied_spec, sections=sections)
                    self.assertFalse((root / "out.docx").exists())
            for ambiguous, error in (
                ({**spec, "rights": {"decision": "deny"}}, "template_mapping_spec_invalid"),
                ({**spec, "license_and_origin_declaration": {**decl, "reuse": {"allowed": False}}},
                 "template_license_declaration_required"),
                ({**spec, "license_and_origin_declaration": {**decl, "user_confirmed_rights": False}},
                 "template_license_declaration_required"),
            ):
                with self.subTest(ambiguous=ambiguous), self.assertRaisesRegex(ContractError, error):
                    template_mapper.apply_template_mapping(root, template_path="template.docx", output_path="out.docx",
                                                           mapping_spec=ambiguous, sections=sections)
                self.assertFalse((root / "out.docx").exists())
            # Legitimate positive Chinese/English declarations (including third-party clearance phrasing) and All-Rights-Reserved WITH explicit written grant MUST pass
            for idx, positive_decl in enumerate((
                {
                    "origin": "原创自有模板",
                    "license_basis": "原创自有模板，已取得完整使用与再分发许可",
                    "user_confirmed_rights": "已确认原创归属及完整使用与再分发授权（EV-POS-ZH）",
                },
                {
                    "origin": "原创自有模板，无第三方版权限制，允许完整使用与再分发",
                    "license_basis": "本模板不含未授权第三方材料，完全自有授权使用",
                    "user_confirmed_rights": "不存在未经授权的第三方素材，自有原创可完整使用与分发（EV-POS-CLEAR-1）",
                },
                {
                    "origin": "自有原创模板，无版权纠纷及第三方权利限制，非保密文件",
                    "license_basis": "本模板不含第三方保密资料及未许可组件，由本团队原创编写并授权使用",
                    "user_confirmed_rights": "无侵权风险，已确认完整内部及交付使用授权（EV-POS-CLEAR-2）",
                },
                {
                    "origin": "Original self-authored template",
                    "license_basis": "Original self-authored template with full license for use and redistribution",
                    "user_confirmed_rights": "Confirmed full license for local mapping and redistribution (EV-POS-EN)",
                },
                {
                    "origin": "Original self-authored template, no third-party copyright restrictions, full license to use and redistribute",
                    "license_basis": "Contains no unauthorized third-party content; non-confidential, non-proprietary original template",
                    "user_confirmed_rights": "Free of unauthorized third-party materials; no license restrictions (EV-POS-EN-CLEAR)",
                },
                {
                    "origin": "Partner template (All rights reserved; explicit written authorization granted, EV-AUTH-1)",
                    "license_basis": "Written authorization granted for mapping and submission",
                    "user_confirmed_rights": "Confirmed via EV-AUTH-1",
                },
                {
                    "origin": "合作方模板（保留所有权利，已取得权利人明确书面授权，EV-AUTH-2）",
                    "license_basis": "已取得明确书面许可",
                    "user_confirmed_rights": "EV-AUTH-2 已核验",
                },
                {
                    "origin": "合作方模板（保留所有权利）",
                    "license_basis": "已取得权利人明确书面授权（EV-AUTH-3）",
                    "user_confirmed_rights": "已核验书面授权范围（EV-AUTH-3）",
                },
            )):
                with self.subTest(positive_decl=idx):
                    pos_spec = dict(spec, license_and_origin_declaration=positive_decl)
                    pos_res = template_mapper.apply_template_mapping(
                        root, template_path="template.docx", output_path=f"pos-out-{idx}.docx",
                        mapping_spec=pos_spec, sections=sections,
                    )
                    self.assertEqual("mapped_needs_visual_and_professional_review", pos_res["status"])
                    self.assertTrue((root / f"pos-out-{idx}.docx").is_file())
            with self.assertRaisesRegex(ContractError, "template_bookmark_name_collision"):
                template_mapper.apply_template_mapping(root, template_path="template.docx", output_path="out.docx",
                                                       mapping_spec=spec, sections=[dict(sections[0], id="INTRO")])
            self.assertFalse((root / "out.docx").exists())

            def map_template(index):
                return template_mapper.apply_template_mapping(root, template_path="template.docx",
                    output_path=f"mapped-{index}.docx", mapping_spec=spec, sections=sections)

            with patch.object(ET, "register_namespace", side_effect=AssertionError("global namespace mutation")):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first, second = pool.map(map_template, (1, 2))
            self.assertEqual(decl, first["license_and_origin_declaration"])
            self.assertEqual(first["output_sha256"], second["output_sha256"])
            with zipfile.ZipFile(root / "mapped-1.docx") as archive:
                self.assertEqual({(1980, 1, 1, 0, 0, 0)}, {info.date_time for info in archive.infolist()})
                self.assertEqual({0}, {info.create_system for info in archive.infolist()})
                self.assertEqual({0}, {info.external_attr for info in archive.infolist()})
                self.assertEqual({0}, {info.flag_bits for info in archive.infolist()})

    def test_six_dimension_review_circular_definitions_and_terminology_specimen(self):
        specimen_path = ROOT / "skills/dyz-standards/resources/terminology-example/terminology-standard.json"
        specimen = json.loads(specimen_path.read_text(encoding="utf-8"))
        # Specimen itself must have ZERO circular definitions!
        self.assertEqual([], standard_review.detect_circular_definitions(specimen["terms"]))
        assessment = standard_review.assess(specimen)
        self.assertEqual([], assessment["issues"])
        verification = [row for row in assessment["limitation_checks"] if row["limitation_type"] == "verification_link"]
        self.assertEqual([("C-01", [], "unknown"), ("C-02", ["M-01"], "supports")],
                         [(row["target_id"], row["source_value"], row["judgment"]) for row in verification])

        # Circular definition probe MUST catch A -> B -> A and self-reference C -> C
        circular = standard_review.detect_circular_definitions([
            {"id": "T1", "term": "甲单元", "definition": "由乙单元组成的模块。"},
            {"id": "T2", "term": "乙单元", "definition": "属于甲单元的子部件。"},
            {"id": "T3", "term": "丙参数", "definition": "丙参数的标称值。"},
        ])
        codes = [c["code"] for c in circular]
        self.assertIn("review_term_circular_definition", codes)
        self.assertIn("review_term_self_circular_definition", codes)

        six = standard_review.project_six_dimension_report(
            {"input_hash": "0" * 64, "issues": [{"code": "review_strength_conflict", "record_id": "C-02"}],
             "pending_reviews": [{"code": "source_evidence_not_verified", "record_id": "C-01"}]},
            payload={"terms": [{"id": "T1", "term": "甲", "definition": "甲自身"}]},
        )
        self.assertEqual("blocked", six["status"])
        self.assertEqual(1, six["dimension_counts"]["2_modality_strength"])
        self.assertEqual(1, six["dimension_counts"]["3_cross_references"])
        self.assertEqual(1, six["dimension_counts"]["4_terminology_and_circularity"])
        self.assertEqual("P0_blocking", six["priority_table"][0]["priority"])

    def test_term_cycles_cover_long_chains_aliases_and_real_boundaries(self):
        count = 1_200
        rows = [{"id": f"T{i}", "term": f"term{i}", "definition": f"Uses term{(i + 1) % count}."}
                for i in range(count)]
        [finding] = standard_review.detect_circular_definitions(rows)
        self.assertEqual("review_term_circular_definition", finding["code"])
        self.assertEqual(count, len(finding["terms"]))
        self.assertEqual(finding["cycle"][0], finding["cycle"][-1])
        self.assertEqual(count + 1, len(finding["cycle"]))
        self.assertEqual([], standard_review.detect_circular_definitions([
            {"term": "帧", "definition": "由帧头标识。"}, {"term": "帧头", "definition": "前置区域。"},
            {"term": "rate", "definition": "Used to generate output."},
        ]))
        alias_findings = standard_review.detect_circular_definitions([
            {"id": "A", "term": "帧", "aliases": ["数据帧"], "definition": "由帧头标识。"},
            {"id": "B", "term": "帧头", "definition": "数据帧的前置区域。"},
            {"id": "C", "term": "帧", "admitted": ["传输单元"], "definition": "传输单元。"},
        ])
        self.assertEqual({"review_duplicate_term_name", "review_term_circular_definition",
                          "review_term_self_circular_definition"}, {row["code"] for row in alias_findings})

    def test_six_dim_report_preserves_blocked_and_uses_exact_rule_codes(self):
        report = standard_review.project_six_dimension_report({"status": "blocked", "pending_reviews": [
            {"code": "review_unit_conflict"}, {"code": "review_duplicate_clause_id"},
            {"code": "review_clauses_not_provided"}, {"code": "unknown_source_narrative"},
        ]})
        self.assertEqual("blocked", report["status"])
        self.assertEqual(2, report["dimension_counts"]["1_structure"])
        self.assertEqual(1, report["dimension_counts"]["2_modality_strength"])
        self.assertEqual(0, report["dimension_counts"]["3_cross_references"])
        self.assertEqual(1, report["dimension_counts"]["6_clarity_and_ambiguity"])

    def test_cli_help_subcommand(self):
        proc = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-m", "tools", "help", "list"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("list", proc.stdout)

    def test_software_intake_collect_batch_with_markdown_manual(self):
        from argparse import Namespace
        from tools import cli

        with tempfile.TemporaryDirectory(prefix="dyz-batch-intake-") as folder:
            root = Path(folder)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "harbor-batch"\nversion = "1.4.0"\n'
                'description = "Batch intake demo"\nrequires-python = ">=3.11"\n',
                encoding="utf-8",
            )
            (root / "app.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
            (root / "manual.md").write_text(
                "# 操作说明\n\n## 功能概览\n\n运行 `app.py` 执行本地检查。\n",
                encoding="utf-8",
            )
            files = [
                {"id": "f1", "path": "pyproject.toml", "component_id": "main", "kind": "source", "include": True},
                {"id": "f2", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
            ]
            base_batch = {
                "context_and_permissions": _valid_context(),
                "files_and_rights": {
                    "scope": {
                        "metadata": {
                            "software_id": "harbor-batch",
                            "name": "Harbor Batch",
                            "version": "1.4.0",
                            "completed_date": None,
                            "published_date": None,
                            "runtime_environment": None,
                        },
                        "components": [{
                            "id": "main",
                            "kind": "standalone",
                            "version": "1.4.0",
                            "origin": "own",
                            "origin_evidence": "EV-ORIG",
                            "claim": ["local batch runner"],
                            "exclusions": [],
                            "subjects": [{"subject_id": "Synthetic Holder", "basis": "original", "evidence_id": "EV-SUBJ"}],
                            "original_right_holder": "Synthetic Holder",
                        }],
                    },
                    "rights": [{
                        "component_id": "main",
                        "requested_decision": "claim",
                        "evidence_ids": ["EV-RIGHTS"],
                        "permissions": {"local_process": "allow", "deposit": "allow", "public": "deny", "cloud": "deny"},
                    }],
                    "files": files,
                    "material_permissions": [
                        {"paths": ["pyproject.toml", "app.py", "manual.md"], "decision": "allow", "evidence_id": "EV-MAT"}
                    ],
                    "manual_mode": "CLI",
                },
            }
            # 1) Blind confirmation without plan_batch digests MUST be rejected!
            blind = dict(base_batch, field_confirmation={"confirm_eligible": True, "actor": "a", "role": "r", "evidence_id": "e"})
            with self.assertRaisesRegex(ContractError, "blind_batch_confirmation_forbidden"):
                software_intake.collect_batch(root, "blind-out", batch_input=blind, manual_markdown_path="manual.md")

            # 2) Explicit plan_batch -> review -> collect_batch -> real cli._prepare_software MUST succeed with ZERO stale confirmations!
            planned = software_intake.plan_batch(root, batch_input=base_batch, manual_markdown_path="manual.md")
            self.assertEqual("needs_confirm", planned["status"])
            self.assertTrue(planned["eligible_candidates"])

            confirmed_batch = dict(base_batch, field_confirmation={
                "group_binding": planned["group_binding"],
                "summary_digest": planned["summary_digest"],
                "input_binding": planned["input_binding"],
                "candidate_digests": planned["eligible_candidates"],
                "actor": "reviewer-1",
                "role": "technical_owner",
                "evidence_id": "EV-CONF",
            })
            res = software_intake.collect_batch(
                root, "intake-out", batch_input=confirmed_batch, manual_markdown_path="manual.md",
            )
            self.assertEqual("collected_batch", res["status"])
            self.assertEqual(3, res["batches_consumed"])
            self.assertTrue(res["manual_blocks_imported"])
            self.assertGreaterEqual(res["confirmed_candidates"], 1)

            # End-to-end consumption by real cli._prepare_software (build-software DOCX pipeline)!
            built = cli._prepare_software(
                Namespace(
                    root=str(root),
                    authorization=res["authorization"],
                    authorization_sha256=res["authorization_sha256"],
                    verify=False, pdf_tool=None, pdf_text_tool=None,
                ),
                document_output=True,
            )
            self.assertIn(built["status"], {"built_needs_review", "partial", "needs_review"})
            prep_file = root / "intake-out/materials/internal/preparation.json"
            self.assertTrue(prep_file.is_file())
            prep_data = json.loads(prep_file.read_text(encoding="utf-8"))
            worksheet_rows = prep_data["worksheet"]["rows"]
            stale_rows = [r for r in worksheet_rows if r.get("reason") == "field_confirmation_stale"]
            self.assertEqual([], stale_rows)
            confirmed_rows = [r for r in worksheet_rows if r.get("status") == "confirmed"]
            self.assertEqual(res["confirmed_candidates"], len(confirmed_rows))

            # 3) Deny-beats-allow on manual.md (exact, ./, and OS case variants), unpermitted screenshot, and string sensitive_literals MUST all fail closed!
            deny_batch = json.loads(json.dumps(base_batch))
            deny_batch["files_and_rights"]["material_permissions"].append(
                {"paths": ["manual.md"], "decision": "deny", "evidence_id": "EV-DENY"}
            )
            with self.assertRaisesRegex(ContractError, "manual_markdown_permission_required"):
                software_intake.plan_batch(root, batch_input=deny_batch, manual_markdown_path="manual.md")
            if sys.platform in {"win32", "darwin"}:
                case_deny_batch = json.loads(json.dumps(base_batch))
                case_deny_batch["files_and_rights"]["material_permissions"].append(
                    {"paths": ["MANUAL.MD"], "decision": "deny", "evidence_id": "EV-DENY"}
                )
                with self.assertRaisesRegex(ContractError, "manual_markdown_permission_required"):
                    software_intake.plan_batch(root, batch_input=case_deny_batch, manual_markdown_path="manual.md")

            dot_deny_batch = json.loads(json.dumps(base_batch))
            dot_deny_batch["files_and_rights"]["material_permissions"].append(
                {"paths": ["./manual.md"], "decision": "deny", "evidence_id": "EV-DENY"}
            )
            with self.assertRaises(ContractError):
                software_intake.plan_batch(root, batch_input=dot_deny_batch, manual_markdown_path="manual.md")

            str_secret_batch = json.loads(json.dumps(base_batch))
            str_secret_batch["files_and_rights"]["sensitive_literals"] = "NOT_A_LIST"
            with self.assertRaisesRegex(ContractError, "invalid_sensitive_literals"):
                software_intake.plan_batch(root, batch_input=str_secret_batch)

            (root / "secret-shot.png").write_bytes(_make_png())
            unperm_shot_batch = json.loads(json.dumps(base_batch))
            unperm_shot_batch["files_and_rights"]["delivery"] = {
                "selection": "all",
                "screenshots": [{"path": "secret-shot.png"}],
            }
            with self.assertRaisesRegex(ContractError, "screenshot_permission_required"):
                software_intake.collect_batch(root, "unperm-shot-out", batch_input=unperm_shot_batch)

            # Non-boolean inventory_complete (e.g. string "false") MUST NOT coerce to True!
            for bad_inv in ("false", "true", 1, 0, None):
                with self.subTest(inventory_complete=bad_inv):
                    bad_inv_batch = copy.deepcopy(base_batch)
                    bad_inv_batch["files_and_rights"]["inventory_complete"] = bad_inv
                    with self.assertRaisesRegex(ContractError, "inventory_complete_bool_required"):
                        software_intake.plan_batch(root, batch_input=bad_inv_batch)
                    with self.assertRaisesRegex(ContractError, "inventory_complete_bool_required"):
                        software_intake.collect_batch(root, "bad-inv-out", batch_input=bad_inv_batch)
            self.assertFalse((root / "bad-inv-out").exists())

            # Filtered inventory cannot reach the delivery chain with a complete-source declaration.
            (root / "unreadable.py").write_bytes(b"\xff\xfe\x80")
            (root / ".env").write_text("fixture\n", encoding="utf-8")
            filtered = copy.deepcopy(base_batch)
            filtered_far = filtered["files_and_rights"]
            filtered_far.update(inventory_complete=True, material_permissions=[])
            filtered_far["files"] += [{"path": "unreadable.py"}, {"path": ".env"}]
            self.assertFalse(software_intake.plan_batch(root, batch_input=filtered)["inventory_complete"])
            result = software_intake.collect_batch(root, "filtered-out", batch_input=filtered)
            self.assertFalse(result["inventory_complete"])
            request = json.loads((root / "filtered-out/request.json").read_text(encoding="utf-8"))
            self.assertFalse(request["inventory_complete"])
            built = cli._prepare_software(Namespace(root=str(root), authorization=result["authorization"],
                authorization_sha256=result["authorization_sha256"], verify=False, pdf_tool=None, pdf_text_tool=None),
                document_output=True)
            self.assertIn("source_coverage_incomplete", built["issues"])

            # Non-"source" kind variants on excluded/unreadable files in plan_batch / collect_batch MUST ALSO downgrade inventory_complete!
            (root / "bad_secret.py").write_text("SECRET = 'BATCH_SECRET_TOKEN'\n", encoding="utf-8")
            (root / "bad_bin.c").write_bytes(b"int f(){\x00return 1;}\n")
            clean_complete = copy.deepcopy(base_batch)
            clean_complete["files_and_rights"]["inventory_complete"] = True
            self.assertTrue(software_intake.plan_batch(root, batch_input=clean_complete)["inventory_complete"])
            for idx, (extra_file, extra_secrets) in enumerate((
                ({"id": "fx", "path": "unreadable.py", "component_id": "main", "kind": "other", "include": False}, []),
                ({"id": "fx", "path": "unreadable.py", "component_id": "main", "kind": "SOURCE", "include": True}, []),
                ({"id": "fx", "path": "unreadable.py", "component_id": "main", "kind": "program", "include": True}, []),
                ({"id": "fx", "path": "bad_bin.c", "component_id": "main", "kind": "code", "include": True}, []),
                ({"id": "fx", "path": "bad_secret.py", "component_id": "main", "kind": "other", "include": False}, ["BATCH_SECRET_TOKEN"]),
                ({"id": "fx", "path": "unreadable.py", "component_id": "main", "kind": None, "include": False}, []),
            )):
                with self.subTest(batch_non_source_excluded=idx, kind=extra_file["kind"]):
                    bcase = copy.deepcopy(base_batch)
                    bfar = bcase["files_and_rights"]
                    bfar["inventory_complete"] = True
                    bfar["sensitive_literals"] = list(extra_secrets)
                    bfar["files"].append(extra_file)
                    bfar["material_permissions"][0]["paths"].append(extra_file["path"])
                    bplan = software_intake.plan_batch(root, batch_input=bcase)
                    self.assertFalse(bplan["inventory_complete"])
                    self.assertEqual(extra_file["path"], bplan["excluded_sources"][0]["path"])
                    bres = software_intake.collect_batch(root, f"filtered-nonsrc-{idx}", batch_input=bcase)
                    self.assertFalse(bres["inventory_complete"])
                    self.assertEqual(extra_file["path"], bres["excluded_sources"][0]["path"])
                    breq = json.loads((root / f"filtered-nonsrc-{idx}/request.json").read_text(encoding="utf-8"))
                    self.assertFalse(breq["inventory_complete"])

            # A decoded Markdown cell and request metadata are scanned before any output is written.
            sensitive = copy.deepcopy(base_batch)
            sensitive["files_and_rights"]["sensitive_literals"] = ["sample|marker"]
            (root / "manual.md").write_text("| a | sample\\|marker |\n| --- | --- |\n| ordinary | data |\n", encoding="utf-8")
            for call in (lambda: software_intake.plan_batch(root, batch_input=sensitive, manual_markdown_path="manual.md"),
                         lambda: software_intake.collect_batch(root, "sensitive-out", batch_input=sensitive,
                                                               manual_markdown_path="manual.md")):
                with self.assertRaisesRegex(ContractError, "sensitive_literal_in_manual"):
                    call()
            self.assertFalse((root / "sensitive-out").exists())
            sensitive["files_and_rights"]["scope"]["metadata"]["name"] = "sample|marker"
            with self.assertRaisesRegex(ContractError, "intake_sensitive_request"):
                software_intake.plan_batch(root, batch_input=sensitive)
            for call in (lambda: software_intake.plan_batch(root / "missing", batch_input=base_batch),
                         lambda: software_intake.collect_batch(root / "missing", "out", batch_input=base_batch)):
                with self.assertRaisesRegex(ContractError, "^intake_io_failed$"):
                    call()

            # GUI runtime evidence and the exact source build are carried through build-software.
            gui = copy.deepcopy(base_batch)
            far = gui["files_and_rights"]
            far["manual_mode"] = "GUI"
            far["manual_input"] = {"operations": [{"id": "open", "input": "Open the fixture",
                "expected_output": "Main window", "failure": "Window missing", "evidence_id": "EV-OP"}]}
            (root / "manual.md").write_text("# 手册\n\n<!-- block:Open operation:open -->\n打开合成界面。\n", encoding="utf-8")
            shot = {"id": "shot1", "path": "secret-shot.png", "version": "1.4.0", "operation_id": "open",
                    "capture_evidence": "EV-CAP", "local_use_evidence": "EV-USE", "visible_state": "Fixture window"}
            far["material_permissions"][0]["paths"].append(shot["path"])
            far["delivery"] = {"selection": "all", "screenshots": [shot]}
            second_png = root / "second.png"
            second_png.write_bytes(_make_png())
            far["material_permissions"][0]["paths"].append(second_png.name)
            bad_gui = copy.deepcopy(gui)
            bad_gui["files_and_rights"]["delivery"]["screenshots"].append({"path": second_png.name})
            original_open = Path.open

            def deny_png_read(path, *args, **kwargs):
                if path.suffix == ".png":
                    raise AssertionError("PNG read before all screenshot metadata was validated")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", deny_png_read):
                with self.assertRaisesRegex(ContractError, "missing:id"):
                    software_intake.collect_batch(root, "invalid-shot-out", batch_input=bad_gui, manual_markdown_path="manual.md")
                for key, value, code in (("version", "1.3.0", "screenshot_version_mismatch"),
                                         ("operation_id", "absent", "screenshot_operation_mismatch"),
                                         ("capture_evidence", 123, "screenshot_evidence_required"),
                                         ("build_binding", "0" * 64, "screenshot_build_changed")):
                    with self.subTest(key=key):
                        bad = copy.deepcopy(gui)
                        bad["files_and_rights"]["delivery"]["screenshots"][0][key] = value
                        with self.assertRaisesRegex(ContractError, code):
                            software_intake.collect_batch(root, "invalid-shot-out", batch_input=bad, manual_markdown_path="manual.md")
                wrong_mode = copy.deepcopy(gui)
                wrong_mode["files_and_rights"]["manual_mode"] = "CLI"
                with self.assertRaisesRegex(ContractError, "screenshots_require_gui"):
                    software_intake.collect_batch(root, "invalid-shot-out", batch_input=wrong_mode, manual_markdown_path="manual.md")
                conflict_mode = copy.deepcopy(gui)
                conflict_mode["files_and_rights"]["manual_mode"] = "CLI"
                conflict_mode["files_and_rights"]["manual_input"]["mode"] = "GUI"
                with self.assertRaisesRegex(ContractError, "manual_mode_mismatch"):
                    software_intake.collect_batch(root, "invalid-shot-out", batch_input=conflict_mode, manual_markdown_path="manual.md")
                invalid_mode = copy.deepcopy(gui)
                invalid_mode["files_and_rights"]["manual_mode"] = "UNKNOWN_MODE"
                with self.assertRaisesRegex(ContractError, "manual_mode_invalid"):
                    software_intake.collect_batch(root, "invalid-shot-out", batch_input=invalid_mode, manual_markdown_path="manual.md")
            self.assertFalse((root / "invalid-shot-out").exists())
            # Omitting far["manual_mode"] when manual_input["mode"] == "GUI" MUST succeed without redundant conflict!
            gui_no_top_mode = copy.deepcopy(gui)
            gui_no_top_mode["files_and_rights"].pop("manual_mode")
            gui_no_top_mode["files_and_rights"]["manual_input"]["mode"] = "GUI"
            gui_no_top_res = software_intake.collect_batch(
                root, "gui-mode-from-manual-out", batch_input=gui_no_top_mode, manual_markdown_path="manual.md",
            )
            self.assertEqual("collected_batch", gui_no_top_res["status"])
            gui_result = software_intake.collect_batch(root, "gui-out", batch_input=gui, manual_markdown_path="manual.md")
            cli._prepare_software(Namespace(root=str(root), authorization=gui_result["authorization"],
                authorization_sha256=gui_result["authorization_sha256"], verify=False, pdf_tool=None, pdf_text_tool=None),
                document_output=True)
            maps = json.loads((root / "gui-out/materials/internal/source-map.json").read_text(encoding="utf-8"))
            [mapped] = maps["screenshots"]
            self.assertEqual("shot1", mapped["id"])
            self.assertEqual("open", mapped["operation_id"])
            request = json.loads((root / "gui-out/request.json").read_text(encoding="utf-8"))
            self.assertEqual(mapped["build_binding"], request["delivery"]["screenshots"][0]["build_binding"])
            self.assertEqual([{"id": "shot1", "version": "1.4.0", "kind": "screenshot", "evidence_id": "EV-CAP"}],
                             request["manual_input"]["runtime_evidence"])

    def test_batch_intake_explicit_exclusions_and_single_file_open_failure_preserve_security_guards(self):
        from argparse import Namespace
        from tools import cli

        with tempfile.TemporaryDirectory(prefix="dyz-batch-r4-") as folder, \
                tempfile.TemporaryDirectory(prefix="dyz-batch-r4-outside-") as outside_folder:
            root = Path(folder)
            outside = Path(outside_folder)
            (root / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
            (root / "extra.py").write_text("def extra():\n    return 2\n", encoding="utf-8")
            (root / "locked.py").write_text("def locked():\n    return 3\n", encoding="utf-8")
            (root / "vendor").mkdir()
            (root / "vendor/lib.py").write_text("LIB = True\n", encoding="utf-8")
            (outside / "secret.py").write_text("OUTSIDE_SECRET = 1\n", encoding="utf-8")

            def make_batch(file_entries, *, perm_paths=None, extra_far=None):
                paths = perm_paths if perm_paths is not None else [f["path"] for f in file_entries]
                far = {
                    "scope": {
                        "metadata": {
                            "software_id": "r4-demo",
                            "name": "R4 Demo",
                            "version": "1.0.0",
                            "completed_date": None,
                            "published_date": None,
                            "runtime_environment": None,
                        },
                        "components": [{
                            "id": "main",
                            "kind": "standalone",
                            "version": "1.0.0",
                            "origin": "own",
                            "origin_evidence": "EV-O",
                            "claim": ["core logic"],
                            "exclusions": [],
                            "subjects": [{"subject_id": "Synthetic Holder", "basis": "original", "evidence_id": "EV-S"}],
                            "original_right_holder": "Synthetic Holder",
                        }],
                    },
                    "rights": [{
                        "component_id": "main",
                        "requested_decision": "claim",
                        "evidence_ids": ["EV-R"],
                        "permissions": {"local_process": "allow", "deposit": "allow", "public": "deny", "cloud": "deny"},
                    }],
                    "files": file_entries,
                    "material_permissions": [{"paths": paths, "decision": "allow", "evidence_id": "EV-M"}],
                    "inventory_complete": True,
                }
                if extra_far:
                    far.update(extra_far)
                return {"context_and_permissions": _valid_context(), "files_and_rights": far}

            # 1) Empty explicit exclusion lists MUST NOT falsely downgrade inventory_complete
            clean = make_batch(
                [{"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True}],
                extra_far={"excluded_files": [], "excluded_directories": [], "exclude_patterns": []},
            )
            clean_plan = software_intake.plan_batch(root, batch_input=clean)
            self.assertTrue(clean_plan["inventory_complete"])
            self.assertNotIn("excluded_sources", clean_plan)

            # 2) Any explicit exclusion (include=False, exclusion_reason, excluded_files, excluded_directories,
            #    exclude_patterns, excluded_sources) MUST downgrade inventory_complete to False!
            explicit_cases = [
                (
                    "include_false",
                    [
                        {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                        {"id": "f2", "path": "extra.py", "component_id": "main", "kind": "source", "include": False},
                    ],
                    {},
                    "extra.py",
                ),
                (
                    "entry_exclusion_reason",
                    [
                        {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                        {"id": "f2", "path": "extra.py", "component_id": "main", "kind": "source", "include": True, "exclusion_reason": "out_of_scope"},
                    ],
                    {},
                    "extra.py",
                ),
                (
                    "excluded_files_in_list",
                    [
                        {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                        {"id": "f2", "path": "extra.py", "component_id": "main", "kind": "source", "include": True},
                    ],
                    {"excluded_files": ["extra.py"]},
                    "extra.py",
                ),
                (
                    "excluded_files_unlisted",
                    [{"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True}],
                    {"excluded_files": ["vendor/lib.py"]},
                    "vendor/lib.py",
                ),
                (
                    "excluded_directories",
                    [
                        {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                        {"id": "f2", "path": "vendor/lib.py", "component_id": "main", "kind": "source", "include": True},
                    ],
                    {"excluded_directories": ["vendor"]},
                    "vendor/lib.py",
                ),
                (
                    "exclude_patterns_matching",
                    [
                        {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                        {"id": "f2", "path": "extra.py", "component_id": "main", "kind": "source", "include": True},
                    ],
                    {"exclude_patterns": ["extra.*"]},
                    "extra.py",
                ),
                (
                    "exclude_patterns_nonempty_unmatched",
                    [{"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True}],
                    {"exclude_patterns": ["*.generated.py"]},
                    None,
                ),
                (
                    "excluded_sources_declared",
                    [{"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                     {"id": "f2", "path": "vendor/lib.py", "component_id": "main", "kind": "source", "include": True}],
                    {"excluded_sources": [{"path": "vendor/lib.py", "reason": "third_party_vendor"}]},
                    "vendor/lib.py",
                ),
            ]
            original_open = Path.open
            for idx, (label, entries, extra_far, expected_path) in enumerate(explicit_cases):
                with self.subTest(explicit_exclusion=label):
                    batch = make_batch(entries, extra_far=extra_far)
                    def forbid_excluded_open(path, *args, **kwargs):
                        if expected_path and path == root / expected_path:
                            self.fail(f"excluded path opened: {expected_path}")
                        return original_open(path, *args, **kwargs)

                    with patch.object(Path, "open", forbid_excluded_open):
                        plan = software_intake.plan_batch(root, batch_input=batch)
                        collected = software_intake.collect_batch(root, f"explicit-{idx}", batch_input=batch)
                    self.assertFalse(plan["inventory_complete"])
                    if expected_path is not None:
                        self.assertIn(expected_path, [row["path"] for row in plan["excluded_sources"]])
                    self.assertFalse(collected["inventory_complete"])
                    req = json.loads((root / f"explicit-{idx}/request.json").read_text(encoding="utf-8"))
                    self.assertFalse(req["inventory_complete"])
                    self.assertEqual(["app.py"], [row["path"] for row in req["files"]])
                    auth = json.loads((root / f"explicit-{idx}/authorization.json").read_text(encoding="utf-8"))
                    self.assertEqual(["app.py"], [row["path"] for row in auth["files"]])

            (root / "manual.md").write_text("# Excluded manual", encoding="utf-8")
            (root / "shot.png").write_bytes(b"excluded screenshot")
            excluded_artifacts = make_batch(clean["files_and_rights"]["files"], extra_far={
                "excluded_sources": [{"path": "manual.md"}, {"path": "shot.png"}],
                "delivery": {"screenshots": [{"path": "shot.png"}]},
            })

            def forbid_artifact_open(path, *args, **kwargs):
                if path.name in {"manual.md", "shot.png"}:
                    self.fail(f"excluded artifact opened: {path.name}")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", forbid_artifact_open):
                filtered = software_intake.collect_batch(root, "excluded-artifacts", batch_input=excluded_artifacts,
                                                         manual_markdown_path="manual.md")
            self.assertFalse(filtered["inventory_complete"])
            self.assertFalse(filtered["manual_blocks_imported"])
            self.assertEqual({"manual.md", "shot.png"}, {row["path"] for row in filtered["excluded_sources"]})
            auth = json.loads((root / filtered["authorization"]).read_text(encoding="utf-8"))
            self.assertEqual(["app.py"], [row["path"] for row in auth["files"]])

            # 3) Single-file ordinary open() PermissionError/OSError MUST NOT abort the batch;
            #    instead it records excluded_sources and downgrades inventory_complete=False.
            orig_open = Path.open
            two_files = [
                {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                {"id": "f2", "path": "locked.py", "component_id": "main", "kind": "source", "include": True},
            ]
            batch_two = make_batch(two_files)

            def flaky_open(path, *args, **kwargs):
                if path.name == "locked.py":
                    raise PermissionError("simulated OS lock on locked.py")
                return orig_open(path, *args, **kwargs)

            with patch.object(Path, "open", flaky_open):
                planned = software_intake.plan_batch(root, batch_input=batch_two)
                self.assertFalse(planned["inventory_complete"])
                self.assertEqual(
                    [{"id": "f2", "path": "locked.py", "read_status": "not_read", "exclusion_reason": "unreadable"}],
                    planned["excluded_sources"],
                )
                collected = software_intake.collect_batch(root, "open-err-out", batch_input=batch_two)
                self.assertFalse(collected["inventory_complete"])
                self.assertEqual(planned["excluded_sources"], collected["excluded_sources"])

            auth_data = json.loads((root / "open-err-out/authorization.json").read_text(encoding="utf-8"))
            req_data = json.loads((root / "open-err-out/request.json").read_text(encoding="utf-8"))
            self.assertFalse(req_data["inventory_complete"])
            self.assertEqual(["app.py"], [row["path"] for row in req_data["files"]])
            self.assertEqual(planned["excluded_sources"], auth_data["excluded_sources"])
            built = cli._prepare_software(
                Namespace(root=str(root), authorization=collected["authorization"],
                          authorization_sha256=collected["authorization_sha256"],
                          verify=False, pdf_tool=None, pdf_text_tool=None),
                document_output=True,
            )
            self.assertIn("source_coverage_incomplete", built["issues"])

            for failing_open in (2, 3):
                # 探测后的发现读取或确认组回读只失败一次，不能靠重新探读定位。
                locked_opens = 0

                def fail_one_open(path, *args, **kwargs):
                    nonlocal locked_opens
                    if path.name == "locked.py":
                        locked_opens += 1
                        if locked_opens == failing_open:
                            raise OSError("one-time file read failure")
                    return orig_open(path, *args, **kwargs)

                with self.subTest(failing_open=failing_open), patch.object(Path, "open", fail_one_open):
                    failed_once = software_intake.collect_batch(root, f"once-{failing_open}", batch_input=batch_two)
                self.assertEqual(failing_open, locked_opens)
                self.assertFalse(failed_once["inventory_complete"])
                self.assertEqual(planned["excluded_sources"], failed_once["excluded_sources"])
                auth = json.loads((root / failed_once["authorization"]).read_text(encoding="utf-8"))
                self.assertEqual(["app.py"], [row["path"] for row in auth["files"]])

            # All files unreadable on open() MUST still fail closed with no_readable_source_files
            def fail_all_open(path, *args, **kwargs):
                if path.suffix == ".py":
                    raise PermissionError("all locked")
                return orig_open(path, *args, **kwargs)

            with patch.object(Path, "open", fail_all_open):
                with self.assertRaisesRegex(ContractError, "no_readable_source_files"):
                    software_intake.collect_batch(root, "all-locked-out", batch_input=batch_two)
            self.assertFalse((root / "all-locked-out").exists())

            # 4) Security violations (path traversal, outside/intra hardlink, symlink/junction, denied file)
            #    MUST STILL raise ContractError immediately and NEVER be swallowed as exclusions!
            traversal_batch = make_batch(
                [
                    {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                    {"id": "f2", "path": "../outside.py", "component_id": "main", "kind": "source", "include": True},
                ],
                perm_paths=["app.py"],
            )
            with self.assertRaisesRegex(ContractError, "unsafe_path"):
                software_intake.plan_batch(root, batch_input=traversal_batch)

            excluded_traversal = make_batch(
                [{"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True}],
                extra_far={"excluded_files": ["../outside.py"]},
            )
            with self.assertRaisesRegex(ContractError, "unsafe_path"):
                software_intake.plan_batch(root, batch_input=excluded_traversal)

            os.link(outside / "secret.py", root / "escaped_hl.py")
            hl_batch = make_batch([
                {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                {"id": "f2", "path": "escaped_hl.py", "component_id": "main", "kind": "source", "include": True},
            ])
            with self.assertRaisesRegex(ContractError, "source_file_or_link_invalid"):
                software_intake.collect_batch(root, "hl-escape-out", batch_input=hl_batch)
            self.assertFalse((root / "hl-escape-out").exists())
            (root / "escaped_hl.py").unlink()

            os.link(root / "app.py", root / "alias_hl.py")
            intra_hl_batch = make_batch([
                {"id": "f1", "path": "alias_hl.py", "component_id": "main", "kind": "source", "include": True},
            ])
            with self.assertRaisesRegex(ContractError, "source_file_or_link_invalid"):
                software_intake.plan_batch(root, batch_input=intra_hl_batch)
            (root / "alias_hl.py").unlink()

            (root / "real_dir").mkdir()
            (root / "real_dir/mod.py").write_text("M = 1\n", encoding="utf-8")
            try:
                (root / "linked_dir").symlink_to(root / "real_dir", target_is_directory=True)
            except OSError:
                if sys.platform != "win32":
                    raise
                subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "linked_dir"), str(root / "real_dir")],
                               check=True, capture_output=True, timeout=10)
            link_batch = make_batch([
                {"id": "f1", "path": "app.py", "component_id": "main", "kind": "source", "include": True},
                {"id": "f2", "path": "linked_dir/mod.py", "component_id": "main", "kind": "source", "include": True},
            ])
            with self.assertRaisesRegex(ContractError, "source_file_or_link_invalid"):
                software_intake.collect_batch(root, "link-out", batch_input=link_batch)
            self.assertFalse((root / "link-out").exists())

            denied_locked = make_batch(two_files)
            denied_locked["files_and_rights"]["material_permissions"].append(
                {"paths": ["locked.py"], "decision": "deny", "evidence_id": "EV-DENY"}
            )
            with patch.object(Path, "open", flaky_open):
                with self.assertRaisesRegex(ContractError, "material_permission_not_proven"):
                    software_intake.collect_batch(root, "denied-locked-out", batch_input=denied_locked)
            self.assertFalse((root / "denied-locked-out").exists())


if __name__ == "__main__":
    unittest.main()
