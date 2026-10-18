"""BINI (binary INI) decoder/encoder. Optional: HDE ships no BINI files (VERIFIED R4 §A3.1);
this only matters for other mods' data.

Layout (R4 §A3.4; Librelancer ``BinaryIniParser.cs``, flint ``formats/bini.py``):
``"BINI"``, int32 version (1), int32 string-table offset; then sections up to that offset,
each ``u16 name offset, u16 entry count``; each entry ``u16 name offset, u8 value count``,
then values ``u8 type`` + 4 bytes: 1 = int32, 2 = float32, 3 = int32 offset into the
NUL-separated string table. Type 0 (bool, 1 byte) is accepted as Librelancer does.
"""
from __future__ import annotations

import struct

from .ini import Document

__all__ = ["decode", "encode", "to_document", "BiniError"]


class BiniError(ValueError):
    pass


def _fmt_float(f: float) -> str:
    for p in range(1, 10):
        s = "%.*g" % (p, f)
        if struct.pack("<f", float(s)) == struct.pack("<f", f):
            return s
    return repr(f)


def decode(b: bytes) -> list[tuple[str, list[tuple[str, list]]]]:
    if b[:4] != b"BINI":
        raise BiniError("not a BINI file")
    ver, strings_off = struct.unpack_from("<ii", b, 4)
    if ver != 1:
        raise BiniError(f"BINI version {ver} unsupported")
    if not 12 <= strings_off <= len(b):
        raise BiniError("string table offset out of range")
    table = b[strings_off:]

    def s_at(o: int) -> str:
        end = table.find(b"\0", o)
        return table[o:end if end >= 0 else len(table)].decode("latin-1")

    out = []
    o = 12
    while o < strings_off:
        name_off, count = struct.unpack_from("<HH", b, o)
        o += 4
        entries = []
        for _ in range(count):
            key_off, nvals = struct.unpack_from("<HB", b, o)
            o += 3
            vals: list = []
            for _ in range(nvals):
                t = b[o]
                o += 1
                if t == 0:
                    vals.append(bool(b[o]))
                    o += 1
                elif t == 1:
                    vals.append(struct.unpack_from("<i", b, o)[0])
                    o += 4
                elif t == 2:
                    vals.append(struct.unpack_from("<f", b, o)[0])
                    o += 4
                elif t == 3:
                    vals.append(s_at(struct.unpack_from("<i", b, o)[0]))
                    o += 4
                else:
                    raise BiniError(f"unknown value type {t} at 0x{o - 1:x}")
            entries.append((s_at(key_off), vals))
        out.append((s_at(name_off), entries))
    return out


def _render_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return _fmt_float(v)
    return str(v)


def to_text(sections) -> str:
    lines = []
    for name, entries in sections:
        lines.append(f"[{name}]")
        for k, vals in entries:
            lines.append(f"{k} = {', '.join(_render_value(v) for v in vals)}" if vals else k)
        lines.append("")
    return "\r\n".join(lines) + ("\r\n" if lines else "")


def to_document(b: bytes, path=None) -> Document:
    doc = Document.parse(to_text(decode(b)), path=path)
    doc.source_format = "bini"
    return doc


def encode(sections) -> bytes:
    """Encode ``[(section, [(key, [values])])]``; str/int/float values (bool -> type 0)."""
    table = bytearray()
    index: dict[str, int] = {}

    def s_off(s: str) -> int:
        if s not in index:
            index[s] = len(table)
            table.extend(s.encode("latin-1") + b"\0")
        return index[s]

    body = bytearray()
    for name, entries in sections:
        body += struct.pack("<HH", s_off(name), len(entries))
        for k, vals in entries:
            body += struct.pack("<HB", s_off(k), len(vals))
            for v in vals:
                if isinstance(v, bool):
                    body += bytes([0, 1 if v else 0])
                elif isinstance(v, int):
                    body += b"\x01" + struct.pack("<i", v)
                elif isinstance(v, float):
                    body += b"\x02" + struct.pack("<f", v)
                else:
                    body += b"\x03" + struct.pack("<i", s_off(str(v)))
    return b"BINI" + struct.pack("<ii", 1, 12 + len(body)) + bytes(body) + bytes(table)
