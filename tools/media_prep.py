"""Phase D1: 软著截图与媒体预处理辅助（纯 Python 标准库）。

提供：
1. PNG 附加元数据块剥离（仅保留 IHDR/PLTE/tRNS/IDAT/IEND 并重算 CRC-32），解决 macOS/Windows/浏览器
   截图携带 eXIf/tEXt/iTXt/pHYs 等块而被严格静态 PNG 门禁拒绝的问题，同时绑定原图与干净副本 SHA-256；
2. 可选外部格式转码（JPEG/WebP → PNG）与可选 Playwright 浏览器截图采集清单的契约校验，
   不在默认测试中启动浏览器或安装外部依赖。
"""
from __future__ import annotations

import os
import re
import stat
import struct
import zlib
from pathlib import Path, PureWindowsPath

from tools import bundle, core, software_delivery
from tools.core import ContractError, parse_time, require, require_fields, sha256_bytes

PNG_SIG = b"\x89PNG\r\n\x1a\n"
SAFE_PNG_CHUNKS = frozenset({b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"})
MAX_PNG_BYTES = 20_000_000
MAX_PNG_DECOMPRESSED_BYTES = 64_000_000
PNG_BIT_DEPTHS = {
    0: frozenset({1, 2, 4, 8, 16}),
    2: frozenset({8, 16}),
    3: frozenset({1, 2, 4, 8}),
    4: frozenset({8, 16}),
    6: frozenset({8, 16}),
}
PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_ADAM7_PASSES = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)


def _png_scanline_layout(width: int, height: int, bit_depth: int, color_type: int, interlace: int) -> list[tuple[int, int]]:
    """返回每个 pass 的 (pass_height, scanline_bytes_incl_filter)。"""
    bpp_bits = PNG_CHANNELS[color_type] * bit_depth
    if interlace == 0:
        return [(height, 1 + (width * bpp_bits + 7) // 8)]
    passes: list[tuple[int, int]] = []
    for x0, y0, dx, dy in _ADAM7_PASSES:
        pass_w = (width - x0 + dx - 1) // dx if width > x0 else 0
        pass_h = (height - y0 + dy - 1) // dy if height > y0 else 0
        if pass_w > 0 and pass_h > 0:
            passes.append((pass_h, 1 + (pass_w * bpp_bits + 7) // 8))
    return passes


def _verify_png_idat(idat_bytes: bytes, width: int, height: int,
                     bit_depth: int, color_type: int, interlace: int) -> None:
    """有限内存真实解压 IDAT 并核对解压总字节数与各扫描行滤波字节。"""
    passes = _png_scanline_layout(width, height, bit_depth, color_type, interlace)
    expected_bytes = sum(pass_h * stride for pass_h, stride in passes)
    require(0 < expected_bytes <= MAX_PNG_DECOMPRESSED_BYTES, "media_png_dimensions_exceeded")
    decomp = zlib.decompressobj()
    try:
        raw_pixels = decomp.decompress(idat_bytes, expected_bytes + 1)
        require(not decomp.unconsumed_tail, "media_png_idat_size_mismatch")
        remaining = expected_bytes + 1 - len(raw_pixels)
        if remaining > 0:
            raw_pixels += decomp.flush(remaining)
    except zlib.error:
        raise ContractError("media_png_idat_corrupt") from None
    require(decomp.eof and not decomp.unused_data, "media_png_idat_corrupt")
    require(len(raw_pixels) == expected_bytes, "media_png_idat_size_mismatch")
    pos = 0
    for pass_h, stride in passes:
        for _ in range(pass_h):
            require(raw_pixels[pos] <= 4, "media_png_idat_corrupt")
            pos += stride


def strip_png_ancillary_chunks(raw: bytes) -> dict:
    """剥离 PNG 中 tEXt/iTXt/eXIf/pHYs 等非像素附加块，输出符合严格静态 PNG 门禁的字节。"""
    require(isinstance(raw, bytes) and 33 <= len(raw) <= MAX_PNG_BYTES and raw.startswith(PNG_SIG),
            "media_png_signature_invalid")
    offset = 8
    kept = [PNG_SIG]
    stripped_chunks: list[str] = []
    width = height = bit_depth = color_type = interlace = None
    saw_plte = False
    saw_idat = False
    idat_ended = False
    idat_parts: list[bytes] = []
    saw_iend = False

    while offset < len(raw):
        require(offset + 12 <= len(raw), "media_png_truncated")
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        chunk_type = raw[offset + 4:offset + 8]
        data_end = offset + 8 + length
        require(data_end + 4 <= len(raw), "media_png_truncated")
        data = raw[offset + 8:data_end]
        crc_actual = struct.unpack(">I", raw[data_end:data_end + 4])[0]
        crc_expected = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        require(crc_actual == crc_expected, "media_png_crc_mismatch")

        require(re.fullmatch(rb"[A-Za-z]{4}", chunk_type) is not None, "media_png_chunk_type_invalid")
        require(offset != 8 or chunk_type == b"IHDR", "media_png_ihdr_invalid")
        if chunk_type == b"acTL":
            raise ContractError("media_animated_png_unsupported")
        if chunk_type == b"IHDR":
            require(offset == 8 and length == 13, "media_png_ihdr_invalid")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", data,
            )
            require(0 < width <= 10000 and 0 < height <= 10000 and width * height <= 40_000_000,
                    "media_png_dimensions_exceeded")
            require(bit_depth in PNG_BIT_DEPTHS.get(color_type, frozenset())
                    and compression == 0 and filtering == 0 and interlace in {0, 1},
                    "media_png_ihdr_invalid")
        if chunk_type == b"PLTE":
            require(not saw_plte and not saw_idat and 3 <= length <= 768 and length % 3 == 0,
                    "media_png_plte_invalid")
            saw_plte = True
        if chunk_type == b"IDAT":
            require(length > 0, "media_png_idat_empty")
            require(not idat_ended, "media_png_idat_corrupt")
            saw_idat = True
            idat_parts.append(data)
        elif saw_idat:
            idat_ended = True
        if chunk_type == b"IEND":
            require(length == 0, "media_png_iend_invalid")
            saw_iend = True

        if chunk_type in SAFE_PNG_CHUNKS:
            kept.append(raw[offset:data_end + 4])
        else:
            require(bool(chunk_type[0] & 32), "media_png_critical_chunk_unsupported")
            stripped_chunks.append(chunk_type.decode("ascii"))
        offset = data_end + 4
        if saw_iend:
            require(offset == len(raw), "media_png_trailing_bytes")
            break

    require(width is not None and saw_idat and saw_iend, "media_png_incomplete")
    if color_type == 3:
        require(saw_plte, "media_png_plte_invalid")
    _verify_png_idat(b"".join(idat_parts), width, height, bit_depth, color_type, interlace)
    clean = b"".join(kept)
    software_delivery._png(clean)
    return {
        "clean_png": clean,
        "original_sha256": sha256_bytes(raw),
        "clean_sha256": sha256_bytes(clean),
        "width": width,
        "height": height,
        "stripped_chunks": stripped_chunks,
        "visual_review": "not_performed",
    }


def validate_capture_manifest(root: str | Path, manifest: dict) -> dict:
    """校验可选浏览器/GUI 自动截图采集清单，确保每张截图绑定版本、权限、场景与真实 PNG 字节。"""
    require(isinstance(manifest, dict), "capture_manifest_object_required")
    require_fields(manifest, ("schema", "tool", "software_version", "captures"))
    require(manifest["schema"] == "dyz-screenshot-capture-manifest-v1", "capture_manifest_schema_invalid")
    require(all(isinstance(manifest[key], str) and manifest[key].strip()
                for key in ("tool", "software_version")), "capture_origin_invalid")
    captures = manifest["captures"]
    require(isinstance(captures, list) and bool(captures), "capture_records_required")

    verified, checked = [], []
    seen_ids, seen_paths, seen_identities = set(), set(), set()
    try:
        base = bundle._absolute(root)
        require(stat.S_ISDIR(core.checked_path(base).st_mode), "capture_root_required")
    except (OSError, bundle.BundleError):
        raise ContractError("capture_path_invalid") from None
    for row in captures:
        require(isinstance(row, dict), "capture_record_object_required")
        require_fields(row, ("id", "operation_id", "path", "sha256", "captured_at", "visible_state",
                             "permission_decision", "authority_evidence"))
        text_fields = ("id", "operation_id", "path", "sha256", "captured_at", "visible_state", "authority_evidence")
        optional_fields = ("source", "capture_evidence", "local_use_evidence", "redaction_evidence", "redaction_status")
        require(all(isinstance(row[key], str) and row[key].strip()
                    for key in (*text_fields, *(k for k in optional_fields if k in row))),
                "capture_record_text_invalid")
        require(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None, "capture_png_hash_invalid")
        require(row["id"] not in seen_ids, "capture_duplicate_id")
        seen_ids.add(row["id"])
        require(row["permission_decision"] == "allow", "capture_permission_not_allowed")
        parse_time(row["captured_at"])
        relative = row["path"]
        parts = relative.replace("\\", "/").split("/")
        require(not PureWindowsPath(relative).drive and not any(c in relative for c in ":\x00")
                and all(p not in {"", ".", ".."} and p == p.rstrip(" .") for p in parts),
                "capture_path_invalid")
        file_path = base.joinpath(*parts)
        try:
            info = core.checked_path(file_path)
        except (OSError, bundle.BundleError):
            raise ContractError("capture_path_invalid") from None
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "capture_file_required")
        require(0 < info.st_size <= MAX_PNG_BYTES, "capture_png_size_invalid")
        identity = (info.st_dev, info.st_ino)
        require(file_path not in seen_paths and identity not in seen_identities, "capture_duplicate_path")
        seen_paths.add(file_path)
        seen_identities.add(identity)
        checked.append((row, file_path, info))
    for row, file_path, info in checked:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            with os.fdopen(os.open(file_path, flags), "rb") as stream:
                opened = os.fstat(stream.fileno())
                require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1
                        and os.path.samestat(info, opened), "capture_file_changed")
                raw = stream.read(MAX_PNG_BYTES + 1)
        except OSError:
            raise ContractError("capture_read_failed") from None
        require(len(raw) <= MAX_PNG_BYTES, "capture_png_size_invalid")
        require(sha256_bytes(raw) == row["sha256"], "capture_png_hash_mismatch")
        stripped = strip_png_ancillary_chunks(raw)
        verified.append({
            "id": row["id"],
            "operation_id": row["operation_id"],
            "path": row["path"],
            "original_sha256": stripped["original_sha256"],
            "clean_sha256": stripped["clean_sha256"],
            "width": stripped["width"],
            "height": stripped["height"],
            "stripped_chunks": stripped["stripped_chunks"],
            "needs_metadata_strip": bool(stripped["stripped_chunks"]),
            "visible_state": row["visible_state"],
        })
    return {
        "status": "checked_needs_visual_review",
        "software_version": manifest["software_version"],
        "tool": manifest["tool"],
        "capture_count": len(verified),
        "captures": verified,
        "visual_review": "not_performed",
        "browser_executed_by_verifier": False,
    }
