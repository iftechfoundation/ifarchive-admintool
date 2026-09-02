#!/usr/bin/env python3
"""Extract release number and serial from Blorb, Z-code, Glulx, ADRIFT, or TADS.

Accepts bare Z-code (.z3–.z8, etc.), Inform Glulx (.ulx), TADS 2/3
(.gam / .t3), ADRIFT .taf (3.7–5), and Blorb wrappers containing those
formats.

Serial number is a YYMMDD date. Bare ADRIFT .taf files have no release
number (only serial from CompileDate / LastUpdated). TADS stories without
GameInfo use the image header compile timestamp as serial only.

For Blorbs, the first source that yields a result wins, in this order:

  1. iFiction <zcode> release/serial
  2. iFiction <glulx> release/serial
  3. iFiction <tads2> / <tads3> version + releasedate→serial
  4. iFiction <releases>/<attached>/<release>
     (version → release; releasedate → YYMMDD serial)
  5. ZCOD Exec chunk header
  6. Inform GLUL Exec Info block
  7. ADRI Exec: CompileDate (v3/v4) or LastUpdated (v5) → serial
  8. TAD2 / TAD3 Exec: GameInfo Version + ReleaseDate, else header timestamp

Empty or unusable higher sources are skipped. Fails only when no source
yields a release or serial.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime
from pathlib import Path


class ExtractError(Exception):
    """Could not extract release/serial from this file."""


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u16le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _is_blorb(data: bytes) -> bool:
    return len(data) >= 12 and data[0:4] == b"FORM" and data[8:12] == b"IFRS"


def _iter_blorb_chunks(data: bytes):
    """Yield (chunk_id, data_start, chunk_len) for each top-level Blorb chunk.

    Ignores the top-level FORM length. ADRIFT 5's Blorb generator writes a
    FORM length that is too short (often only covering the game chunk), so
    later chunks such as IFmd lie past the declared FORM end. See:
    https://eblong.com/zarf/blorb/Blorb-Spec.html#adrift-5-compatibility-issues
    """
    if not _is_blorb(data):
        raise ExtractError("not a Blorb (FORM/IFRS) file")

    i = 12
    while i + 8 <= len(data):
        chunk_id = data[i : i + 4]
        chunk_len = _u32(data, i + 4)
        data_start = i + 8
        data_end = data_start + chunk_len
        if data_end > len(data):
            raise ExtractError(
                f"truncated Blorb chunk {chunk_id!r} at offset {i}"
            )
        yield chunk_id, data_start, chunk_len
        i = data_end + (chunk_len & 1)  # word-align


def _blorb_chunk_payload(data: bytes, chunk_id: bytes) -> bytes | None:
    for cid, start, length in _iter_blorb_chunks(data):
        if cid == chunk_id:
            return data[start : start + length]
    return None


def _blorb_exec(data: bytes) -> tuple[bytes, bytes]:
    """Return (chunk_type, payload) for Exec #0 from an IFRS Blorb."""
    ridx_data = _blorb_chunk_payload(data, b"RIdx")
    if ridx_data is None or len(ridx_data) < 4:
        raise ExtractError("Blorb has no RIdx resource index")

    nresources = _u32(ridx_data, 0)
    entries = ridx_data[4:]
    if len(entries) < nresources * 12:
        raise ExtractError("truncated Blorb RIdx")

    exec_offset = None
    for n in range(nresources):
        usage = entries[n * 12 : n * 12 + 4]
        number = _u32(entries, n * 12 + 4)
        start = _u32(entries, n * 12 + 8)
        if usage == b"Exec" and number == 0:
            exec_offset = start
            break
    if exec_offset is None:
        raise ExtractError("Blorb has no Exec #0 resource")

    if exec_offset + 8 > len(data):
        raise ExtractError("Blorb Exec chunk offset out of range")
    chunk_type = data[exec_offset : exec_offset + 4]
    story_len = _u32(data, exec_offset + 4)
    story_start = exec_offset + 8
    if story_start + story_len > len(data):
        raise ExtractError("truncated Blorb Exec chunk")
    return chunk_type, data[story_start : story_start + story_len]


def _from_zcode(story: bytes) -> tuple[int | None, str | None]:
    if len(story) < 0x18:
        raise ExtractError("file too short for a Z-code header")
    version = story[0]
    if not (1 <= version <= 8):
        raise ExtractError(f"not a Z-code story file (version byte {version})")
    release = _u16(story, 0x02)
    serial = story[0x12:0x18].decode("ascii", errors="replace")
    return release, serial


def _from_inform_glulx(story: bytes) -> tuple[int | None, str | None]:
    if len(story) < 0x3C:
        raise ExtractError("file too short for an Inform Glulx Info block")
    if story[0:4] != b"Glul":
        raise ExtractError("not a Glulx story file")
    if story[36:40] != b"Info":
        raise ExtractError(
            "Glulx story has no Inform Info block (no release/serial)"
        )
    release = _u16(story, 0x34)
    serial = story[0x36:0x3C].decode("ascii", errors="replace")
    return release, serial


# --- iFiction (Blorb IFmd) -------------------------------------------------


def _local_tag(tag: str) -> str:
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def _child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local_tag(child.tag) == name:
            return child
    return None


def _child_text(parent: ET.Element, name: str) -> str | None:
    child = _child(parent, name)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _parse_ifmd(ifmd: bytes) -> ET.Element:
    try:
        root = ET.fromstring(ifmd)
    except ET.ParseError as exc:
        raise ExtractError(f"invalid IFmd XML: {exc}") from exc
    if _local_tag(root.tag) != "ifindex":
        raise ExtractError("IFmd root is not <ifindex>")
    story = _child(root, "story")
    if story is None:
        raise ExtractError("IFmd has no <story>")
    return story


def _parse_release_int(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def _serial_from_releasedate(text: str) -> str | None:
    """Convert iFiction releasedate (YYYY-MM-DD) to YYMMDD serial."""
    stamp = text.strip()
    try:
        dt = datetime.strptime(stamp[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return _serial_yymmdd(dt)


def _from_format_section(
    story: ET.Element, section: str
) -> tuple[int | None, str | None] | None:
    """Release/serial from <zcode> / <glulx>, or None if absent/empty."""
    el = _child(story, section)
    if el is None:
        return None
    release = _parse_release_int(_child_text(el, "release"))
    serial = _child_text(el, "serial")
    if release is None and serial is None:
        return None
    return release, serial


def _from_tads_ifiction_section(
    story: ET.Element, section: str
) -> tuple[int | None, str | None] | None:
    """Version + releasedate from <tads2> / <tads3>, or None if absent/empty."""
    el = _child(story, section)
    if el is None:
        return None
    release = _parse_tads_version(_child_text(el, "version"))
    releasedate = _child_text(el, "releasedate")
    serial = _serial_from_releasedate(releasedate) if releasedate else None
    if release is None and serial is None:
        return None
    return release, serial


def _from_attached_release(
    story: ET.Element,
) -> tuple[int | None, str | None] | None:
    """First <releases>/<attached>/<release>: version + releasedate→serial."""
    releases = _child(story, "releases")
    if releases is None:
        return None
    attached = _child(releases, "attached")
    if attached is None:
        return None
    release_el = _child(attached, "release")
    if release_el is None:
        return None
    release = _parse_release_int(_child_text(release_el, "version"))
    releasedate = _child_text(release_el, "releasedate")
    serial = _serial_from_releasedate(releasedate) if releasedate else None
    if release is None and serial is None:
        return None
    return release, serial


# --- TADS 2 / 3 (GameInfo.txt) ---------------------------------------------

_T3_SIG = b"T3-image\r\n\x1a"
_T2_SIG = b"TADS2 bin\n\r\x1a"


def _parse_tads_version(text: str | None) -> int | None:
    """GameInfo Version may be '6' or '1.0'; return an int release if possible."""
    if text is None:
        return None
    text = text.strip()
    n = _parse_release_int(text)
    if n is not None:
        return n
    match = re.match(r"(\d+)", text)
    return int(match.group(1)) if match else None


def _is_tads3(data: bytes) -> bool:
    return data.startswith(_T3_SIG)


def _is_tads2(data: bytes) -> bool:
    return data.startswith(_T2_SIG)


def _t3_find_resource(data: bytes, name: str) -> bytes | None:
    """Find a named resource in a T3 image MRES block (Spatterlight/babel)."""
    if not _is_tads3(data):
        return None
    # Header: 11 sig + 2 format ver + 32 reserved + 24 timestamp
    p = 11 + 2 + 32 + 24
    name_b = name.encode("ascii")
    end = len(data)
    while p + 10 <= end:
        block_type = data[p : p + 4]
        siz = _u32le(data, p + 4)
        block_base = p + 10
        if block_type == b"EOF ":
            return None
        if block_type == b"MRES":
            if block_base + 2 > end:
                return None
            entry_cnt = _u16le(data, block_base)
            q = block_base + 2
            for _ in range(entry_cnt):
                if q + 9 > end:
                    return None
                entry_ofs = _u32le(data, q)
                entry_siz = _u32le(data, q + 4)
                entry_name_len = data[q + 8]
                q += 9
                if q + entry_name_len > end:
                    return None
                raw_name = data[q : q + entry_name_len]
                q += entry_name_len
                decoded = bytes(b ^ 0xFF for b in raw_name)
                if decoded.lower() == name_b.lower():
                    start = block_base + entry_ofs
                    if start + entry_siz > end:
                        return None
                    return data[start : start + entry_siz]
            p = block_base + siz
            continue
        p = block_base + siz
    return None


def _t2_find_resource(data: bytes, name: str) -> bytes | None:
    """Find a named resource in a TADS 2 HTMLRES section."""
    if not _is_tads2(data):
        return None
    # Header: 13 sig + 7 version + 2 flags + 26 timestamp
    p = 13 + 7 + 2 + 26
    name_b = name.encode("ascii")
    end = len(data)
    while p < end:
        if p + 1 > end:
            return None
        type_len = data[p]
        if p + 1 + type_len + 4 > end:
            return None
        type_name = data[p + 1 : p + 1 + type_len]
        endofs = _u32le(data, p + 1 + type_len)
        if type_name == b"$EOF":
            return None
        if type_name == b"HTMLRES":
            idx = p + 1 + type_len + 4
            if idx + 8 > end:
                return None
            entry_cnt = _u32le(data, idx)
            q = idx + 8
            found_ofs = found_siz = None
            for _ in range(entry_cnt):
                if q + 10 > end:
                    return None
                res_ofs = _u32le(data, q)
                res_siz = _u32le(data, q + 4)
                name_len = _u16le(data, q + 8)
                q += 10
                if q + name_len > end:
                    return None
                entry_name = data[q : q + name_len]
                q += name_len
                if entry_name.lower() == name_b.lower():
                    found_ofs, found_siz = res_ofs, res_siz
            if found_ofs is not None and found_siz is not None:
                # Resource data starts after the index (at q).
                start = q + found_ofs
                if start + found_siz > end:
                    return None
                return data[start : start + found_siz]
        if endofs <= p or endofs > end:
            return None
        p = endofs
    return None


def _parse_gameinfo(text: str) -> dict[str, str]:
    """Parse GameInfo.txt name: value pairs (continuation lines supported)."""
    values: dict[str, str] = {}
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        if not name or any(ch.isspace() for ch in name):
            continue
        parts = [rest.lstrip()]
        while i < len(lines) and lines[i][:1].isspace() and lines[i].strip():
            parts.append(lines[i].strip())
            i += 1
        values[name] = " ".join(p for p in parts if p)
    return values


def _from_gameinfo_text(text: str) -> tuple[int | None, str | None] | None:
    values = _parse_gameinfo(text)
    release = _parse_tads_version(values.get("Version"))
    releasedate = values.get("ReleaseDate")
    serial = _serial_from_releasedate(releasedate) if releasedate else None
    if release is None and serial is None:
        return None
    return release, serial


def _tads_header_timestamp_serial(data: bytes) -> str | None:
    """YYMMDD from the TADS 2/3 image header compile timestamp."""
    if _is_tads2(data):
        # After sig (13) + version (7) + flags (2).
        raw = data[22 : 22 + 26]
    elif _is_tads3(data):
        # After sig (11) + format ver (2) + reserved (32).
        raw = data[45 : 45 + 24]
    else:
        return None
    stamp = raw.split(b"\0", 1)[0].decode("ascii", errors="replace").strip()
    if not stamp:
        return None
    try:
        dt = datetime.strptime(stamp, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
    return _serial_yymmdd(dt)


def _from_tads(data: bytes) -> tuple[int | None, str | None]:
    """GameInfo Version/ReleaseDate, else header compile timestamp (serial only)."""
    if _is_tads3(data):
        raw = _t3_find_resource(data, "GameInfo.txt")
    elif _is_tads2(data):
        raw = _t2_find_resource(data, "GameInfo.txt")
    else:
        raise ExtractError("not a TADS 2/3 story file")

    if raw is not None:
        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        got = _from_gameinfo_text(text)
        if got is not None:
            return got

    serial = _tads_header_timestamp_serial(data)
    if serial is not None:
        return None, serial
    raise ExtractError(
        "TADS story has no GameInfo Version/ReleaseDate or header timestamp"
    )


# --- ADRIFT .taf -----------------------------------------------------------

# 12-byte magic prefixes (ADRIFT 5 / detection helpers). Scarier taf2xml.py.
_V5_MAGIC = bytes([60, 66, 63, 201, 106, 135, 194, 207, 146, 69, 62, 97])

# 14-byte signatures for ADRIFT 3.7–4.0 (Scarier taftool.py).
_SIG_400 = bytes.fromhex("3c423fc96a87c2cf93453e6139fa")
_SIG_390 = bytes.fromhex("3c423fc96a87c2cf9445376139fa")
_SIG_380 = bytes.fromhex("3c423fc96a87c2cf9445366139fa")
_SIG_370 = bytes.fromhex("3c423fc96a87c2cf9445396139fa")
_VERSION_BY_SIG = {
    _SIG_400: "4.00",
    _SIG_390: "3.90",
    _SIG_380: "3.80",
    _SIG_370: "3.70",
}

_OBFUSCATION_KEY = bytes(
    [
        41, 236, 221, 117, 23, 189, 44, 187, 161, 96, 4, 147, 90, 91, 172, 159, 244, 50, 249, 140,
        190, 244, 82, 111, 170, 217, 13, 207, 25, 177, 18, 4, 3, 221, 160, 209, 253, 69, 131, 37,
        132, 244, 21, 4, 39, 87, 56, 203, 119, 139, 231, 180, 190, 13, 213, 53, 153, 109, 202, 62,
        175, 93, 161, 239, 77, 0, 143, 124, 186, 219, 161, 175, 175, 212, 7, 202, 223, 77, 72, 83,
        160, 66, 88, 142, 202, 93, 70, 246, 8, 107, 55, 144, 122, 68, 117, 39, 83, 37, 183, 39,
        199, 188, 16, 155, 233, 55, 5, 234, 6, 11, 86, 76, 36, 118, 158, 109, 5, 19, 36, 239, 185,
        153, 115, 79, 164, 17, 52, 106, 94, 224, 118, 185, 150, 33, 139, 228, 49, 188, 164, 146, 88,
        91, 240, 253, 21, 234, 107, 3, 166, 7, 33, 63, 0, 199, 109, 46, 72, 193, 246, 216, 3, 154,
        139, 37, 148, 156, 182, 3, 235, 185, 60, 73, 111, 145, 151, 94, 169, 118, 57, 186, 165, 48,
        195, 86, 190, 55, 184, 206, 180, 93, 155, 111, 197, 203, 143, 189, 208, 202, 105, 121, 51,
        104, 24, 237, 203, 216, 208, 111, 48, 15, 132, 210, 136, 60, 51, 211, 215, 52, 102, 92, 227,
        232, 79, 142, 29, 204, 131, 163, 2, 217, 141, 223, 12, 192, 134, 61, 23, 214, 139, 230, 102,
        73, 158, 165, 216, 201, 231, 137, 152, 187, 230, 155, 99, 12, 149, 75, 25, 138, 207, 254, 85,
        44, 108, 86, 129, 165, 197, 200, 182, 245, 187, 1, 169, 128, 245, 153, 74, 170, 181, 83, 229,
        250, 11, 70, 243, 242, 123, 0, 42, 58, 35, 141, 6, 140, 145, 58, 221, 71, 35, 51, 4, 30, 210,
        162, 0, 229, 241, 227, 22, 252, 1, 110, 212, 123, 24, 90, 32, 37, 99, 142, 42, 196, 158, 123,
        209, 45, 250, 28, 238, 187, 188, 3, 134, 130, 79, 199, 39, 105, 70, 14, 0, 151, 234, 46, 56,
        181, 185, 138, 115, 54, 25, 183, 227, 149, 9, 63, 128, 87, 208, 210, 234, 213, 244, 91, 63,
        254, 232, 81, 44, 81, 51, 183, 222, 85, 142, 146, 218, 112, 66, 28, 116, 111, 168, 184, 161,
        4, 31, 241, 121, 15, 70, 208, 152, 116, 35, 43, 163, 142, 238, 58, 204, 103, 94, 34, 2, 97,
        217, 142, 6, 119, 100, 16, 20, 179, 94, 122, 44, 59, 185, 58, 223, 247, 216, 28, 11, 99, 31,
        105, 49, 98, 238, 75, 129, 8, 80, 12, 17, 134, 181, 63, 43, 145, 234, 2, 170, 54, 188, 228,
        22, 168, 255, 103, 213, 180, 91, 213, 143, 65, 23, 159, 66, 111, 92, 164, 136, 25, 143, 11, 99,
        81, 105, 165, 133, 121, 14, 77, 12, 213, 114, 213, 166, 58, 83, 136, 99, 135, 118, 205, 173,
        123, 124, 207, 111, 22, 253, 188, 52, 70, 122, 145, 167, 176, 129, 196, 63, 89, 225, 91, 165,
        13, 200, 185, 207, 65, 248, 8, 27, 211, 64, 1, 162, 193, 94, 231, 213, 153, 53, 111, 124, 81,
        25, 198, 91, 224, 45, 246, 184, 142, 73, 9, 165, 26, 39, 159, 178, 194, 0, 45, 29, 245, 161,
        97, 5, 120, 238, 229, 81, 153, 239, 165, 35, 114, 223, 83, 244, 1, 94, 238, 20, 2, 79, 140,
        137, 54, 91, 136, 153, 190, 53, 18, 153, 8, 81, 135, 176, 184, 193, 226, 242, 72, 164, 30, 159,
        164, 230, 51, 58, 212, 171, 176, 100, 17, 25, 27, 165, 20, 215, 206, 29, 102, 75, 147, 100, 221,
        11, 27, 32, 88, 162, 59, 64, 123, 252, 203, 93, 48, 237, 229, 80, 40, 77, 197, 18, 132, 173,
        136, 238, 54, 225, 156, 225, 242, 197, 140, 252, 17, 185, 193, 153, 202, 19, 226, 49, 112, 111,
        232, 20, 78, 190, 117, 38, 242, 125, 244, 24, 134, 128, 224, 47, 130, 45, 234, 119, 6, 90, 78,
        182, 112, 206, 76, 118, 43, 75, 134, 20, 107, 147, 162, 20, 197, 116, 160, 119, 107, 117, 238,
        116, 208, 115, 118, 144, 217, 146, 22, 156, 41, 107, 43, 21, 33, 50, 163, 127, 114, 254, 251,
        166, 247, 223, 173, 242, 222, 203, 106, 14, 141, 114, 11, 145, 107, 217, 229, 253, 88, 187, 156,
        153, 53, 233, 235, 255, 104, 141, 243, 146, 209, 33, 5, 109, 122, 72, 125, 240, 198, 131, 178,
        14, 40, 8, 15, 182, 95, 153, 169, 71, 77, 166, 38, 182, 97, 97, 113, 13, 244, 173, 138, 80, 215,
        215, 61, 107, 108, 157, 22, 35, 91, 244, 55, 213, 8, 142, 113, 44, 217, 52, 159, 206, 228, 171,
        68, 42, 250, 78, 11, 24, 215, 112, 252, 24, 249, 97, 54, 80, 202, 164, 74, 194, 131, 133, 235,
        88, 110, 81, 173, 211, 240, 68, 51, 191, 13, 187, 108, 44, 147, 18, 113, 30, 146, 253, 76, 235,
        247, 30, 219, 167, 88, 32, 97, 53, 234, 221, 75, 94, 192, 236, 188, 169, 160, 56, 40, 146, 60,
        61, 10, 62, 245, 10, 189, 184, 50, 43, 47, 133, 57, 0, 97, 80, 117, 6, 122, 207, 226, 253, 212,
        48, 112, 14, 108, 166, 86, 199, 125, 89, 213, 185, 174, 186, 20, 157, 178, 78, 99, 169, 2, 191,
        173, 197, 36, 191, 139, 107, 52, 154, 190, 88, 175, 63, 105, 218, 206, 230, 157, 22, 98, 107,
        174, 214, 175, 127, 81, 166, 60, 215, 84, 44, 107, 57, 251, 21, 130, 170, 233, 172, 27, 234,
        147, 227, 155, 125, 10, 111, 80, 57, 207, 203, 176, 77, 71, 151, 16, 215, 22, 165, 110, 228,
        47, 92, 69, 145, 236, 118, 68, 84, 88, 35, 252, 241, 250, 119, 215, 203, 59, 50, 117, 225, 86,
        2, 8, 137, 124, 30, 242, 99, 4, 171, 148, 68, 61, 55, 186, 55, 157, 9, 144, 147, 43, 252, 225,
        171, 206, 190, 83, 207, 191, 68, 155, 227, 47, 140, 142, 45, 84, 188, 20,
    ]
)

# ADRIFT 3/4 CompileDate looks like "05 Jun 2004".
_COMPILE_DATE_RE = re.compile(
    r"^\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}$"
)


def _vb6_prng_stream(n: int) -> bytes:
    """First n values of the VB6 PRNG after Rnd(-1); Randomize 1976."""
    s = 0x00A09E86
    out = bytearray()
    for _ in range(n):
        s = (s * 0x43FD43FD + 0x00C39EC3) & 0x00FFFFFF
        out.append((255 * s) // 0x1000000)
    return bytes(out)


def _deobfuscate_inplace(data: bytearray) -> None:
    for i, byte in enumerate(data):
        data[i] = byte ^ _OBFUSCATION_KEY[i % len(_OBFUSCATION_KEY)]


def _serial_yymmdd(dt: datetime) -> str:
    return dt.strftime("%y%m%d")


def _parse_compile_date(text: str) -> str:
    """Convert ADRIFT 3/4 CompileDate ('05 Jun 2004') to YYMMDD serial."""
    try:
        dt = datetime.strptime(text.strip(), "%d %b %Y")
    except ValueError as exc:
        raise ExtractError(f"unrecognized CompileDate {text!r}") from exc
    return _serial_yymmdd(dt)


def _parse_last_updated(text: str) -> str:
    """Convert ADRIFT 5 LastUpdated ('2013-09-21 23:09:03') to YYMMDD serial."""
    stamp = text.strip()
    try:
        dt = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(stamp[:10], "%Y-%m-%d")
        except ValueError as exc:
            raise ExtractError(f"unrecognized LastUpdated {text!r}") from exc
    return _serial_yymmdd(dt)


def _is_adrift_taf(data: bytes) -> bool:
    if len(data) >= 12 and data[:12] == _V5_MAGIC:
        return True
    if len(data) >= 14 and data[:14] in _VERSION_BY_SIG:
        return True
    return False


def _unpack_adrift34_plain(data: bytes) -> bytes:
    """Decrypt/decompress ADRIFT 3.7–4.0 body to CR-LF field lines (taftool)."""
    if len(data) < 14:
        raise ExtractError("not an ADRIFT 3.7–4.0 taf (short file)")
    version = _VERSION_BY_SIG.get(data[:14])
    if version is None:
        raise ExtractError("not an ADRIFT 3.7–4.0 taf (unknown signature)")
    if version == "4.00":
        try:
            plain = zlib.decompress(data[22:])
        except zlib.error as exc:
            raise ExtractError(f"ADRIFT 4.0 decompression failed: {exc}") from exc
        return plain
    keystream = _vb6_prng_stream(len(data))
    return bytes(data[i] ^ keystream[i] for i in range(14, len(data)))


def _compile_date_from_plain(plain: bytes) -> str:
    """Find CompileDate near the end of an unpacked ADRIFT 3/4 body."""
    text = plain.decode("latin-1")
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    lines = text.split("\r\n")
    for line in reversed(lines):
        if _COMPILE_DATE_RE.match(line.strip()):
            return line.strip()
    raise ExtractError("ADRIFT 3/4 taf has no CompileDate field")


def _adrift5_xml(data: bytes) -> str:
    """Decompress ADRIFT 5 .taf to XML (logic from taf2xml.py)."""
    if len(data) < 12 or data[:12] != _V5_MAGIC:
        raise ExtractError("not an ADRIFT 5 taf")

    babel_extra = 0
    obfuscate = True
    comp_start = 12

    if len(data) >= 24:
        size_chunk = data[12:16].decode("utf-8", errors="replace")
        check_chunk = data[16:24].decode("utf-8", errors="replace")
        if (
            size_chunk == "0000"
            or check_chunk.startswith("<ifindex")
            or check_chunk.startswith("<?xml")
        ):
            try:
                babel_len = int(size_chunk.strip(), 16)
            except ValueError as exc:
                raise ExtractError("invalid ADRIFT 5 babel size field") from exc
            babel_extra = babel_len + 4
            comp_start = 16 + babel_len
        else:
            comp_start = 12
            obfuscate = False

    comp_len = len(data) - 26 - babel_extra
    if comp_len <= 0 or comp_start + comp_len > len(data):
        raise ExtractError("invalid ADRIFT 5 taf")

    compressed = bytearray(data[comp_start : comp_start + comp_len])
    if obfuscate:
        _deobfuscate_inplace(compressed)

    try:
        xml_bytes = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise ExtractError(f"ADRIFT 5 decompression failed: {exc}") from exc

    return xml_bytes.decode("utf-8", errors="replace")


def _last_updated_from_xml(xml: str) -> str:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ExtractError(f"invalid ADRIFT 5 XML: {exc}") from exc

    if root.tag != "Adventure":
        raise ExtractError(f"ADRIFT 5 XML root is <{root.tag}>, expected <Adventure>")
    value = root.findtext("LastUpdated")
    if value:
        return value.strip()
    raise ExtractError("ADRIFT 5 taf has no Adventure LastUpdated")


def _from_taf(data: bytes) -> tuple[int | None, str | None]:
    """Serial (YYMMDD) from an ADRIFT 3.7–5 .taf; no release number."""
    if len(data) >= 12 and data[:12] == _V5_MAGIC:
        serial = _parse_last_updated(_last_updated_from_xml(_adrift5_xml(data)))
        return None, serial
    if len(data) >= 14 and data[:14] in _VERSION_BY_SIG:
        plain = _unpack_adrift34_plain(data)
        serial = _parse_compile_date(_compile_date_from_plain(plain))
        return None, serial
    raise ExtractError("not an ADRIFT 3.7–5 taf")


def _from_blorb(data: bytes) -> tuple[int | None, str | None]:
    chunk_type, exec_payload = _blorb_exec(data)

    ifmd = _blorb_chunk_payload(data, b"IFmd")
    if ifmd is not None:
        try:
            story = _parse_ifmd(ifmd)
        except ExtractError:
            story = None
        if story is not None:
            for section in ("zcode", "glulx"):
                got = _from_format_section(story, section)
                if got is not None:
                    return got
            for section in ("tads2", "tads3"):
                got = _from_tads_ifiction_section(story, section)
                if got is not None:
                    return got
            got = _from_attached_release(story)
            if got is not None:
                return got

    try:
        if chunk_type == b"ZCOD":
            return _from_zcode(exec_payload)
        if chunk_type == b"GLUL":
            return _from_inform_glulx(exec_payload)
        if chunk_type == b"ADRI" and _is_adrift_taf(exec_payload):
            return _from_taf(exec_payload)
        if chunk_type in (b"TAD2", b"TAD3"):
            return _from_tads(exec_payload)
    except ExtractError:
        pass

    raise ExtractError(
        "no release or serial found in Blorb iFiction or Exec chunk"
    )


def release_and_serial(path: Path) -> tuple[int | None, str | None]:
    data = path.read_bytes()
    if _is_blorb(data):
        return _from_blorb(data)
    if _is_adrift_taf(data):
        return _from_taf(data)
    if _is_tads3(data) or _is_tads2(data):
        return _from_tads(data)
    if data.startswith(b"Glul"):
        return _from_inform_glulx(data)
    if data and 1 <= data[0] <= 8:
        return _from_zcode(data)
    raise ExtractError(
        "unsupported file type "
        "(need Z-code, Inform Glulx, TADS, ADRIFT .taf, "
        "or Blorb with ZCOD / GLUL / ADRI / TAD2 / TAD3)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print release number and/or serial from a Z-code, Inform Glulx, "
            "TADS, or ADRIFT story file, or a Blorb containing those formats."
        )
    )
    parser.add_argument(
        "path",
        type=Path,
        help="story file (.z*, .ulx, .t3, .gam, .taf, .blorb, .gblorb, …)",
    )
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"error: not a file: {args.path}", file=sys.stderr)
        return 1

    try:
        release, serial = release_and_serial(args.path)
    except ExtractError as exc:
        print(f"error: {args.path}: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {args.path}: {exc}", file=sys.stderr)
        return 1

    if release is not None:
        print(f"release: {release}")
    if serial is not None:
        print(f"serial: {serial}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
