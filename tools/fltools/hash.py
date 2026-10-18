"""Freelancer identifier hashes.

- :func:`create_id` -- ``CreateID`` (Common.dll), the 30-bit nickname hash used for every
  nickname. Algorithm per Librelancer ``FLHash.cs`` ("Sherlog's FLHash"); further reference
  sources are cited in NOTES.md §6. VERIFIED bit-exact against hashes the game wrote into
  ``newplayer.fl`` / ``Restart.fl`` (R3 §10, R4 §A3.3; goldens in the tests).
- :func:`faction_id` -- ``MakeId`` (Common.dll), the 16-bit CRC-16/CCITT-style hash used for
  reputation groups. Same algorithm in Librelancer ``FLFacHash`` (other sources: see NOTES.md
  §6). UNVERIFIED against a value produced by the game (none found in saves or refs).
- :func:`location_id` -- ``MakeLocationID(base_id, room)`` =
  ``CreateID(sprintf("%X_%s", base_id, room))``.

Lower-casing is ASCII-only (``A``-``Z``), like the game's ``_strlwr``/``AsciiToLower``; text is
encoded latin-1 so each char maps to one byte, matching Librelancer's ``(byte)char`` cast.
Run as a CLI: ``python -I tools/fltools/bin/flhash <nickname>...``.
"""
from __future__ import annotations

import sys

__all__ = ["create_id", "faction_id", "location_id", "main"]


def _make_tables() -> tuple[list[int], list[int]]:
    crc = []
    for i in range(256):
        x = i
        for _ in range(8):
            x = (x >> 1) ^ (0xA001 << 14) if x & 1 else x >> 1
        crc.append(x)
    fac = []
    for i in range(256):
        x = (i << 8) & 0xFFFF
        for _ in range(8):
            x = ((x << 1) ^ 0x1021) & 0xFFFF if x & 0x8000 else (x << 1) & 0xFFFF
        fac.append(x)
    return crc, fac


_CRC_TABLE, _FAC_TABLE = _make_tables()


def _lower_bytes(s: str | bytes) -> bytes:
    b = s if isinstance(s, bytes) else s.encode("latin-1", "replace")
    return b.lower()  # bytes.lower() only maps ASCII A-Z


def create_id(nickname: str | bytes) -> int:
    """``CreateID``: nickname -> u32 (top bit always set, case-insensitive)."""
    h = 0
    t = _CRC_TABLE
    for c in _lower_bytes(nickname):
        h = (h >> 8) ^ t[(h & 0xFF) ^ c]
    h = ((h >> 24) | ((h >> 8) & 0x0000FF00) | ((h << 8) & 0x00FF0000) | (h << 24)) & 0xFFFFFFFF
    return ((h >> 2) | 0x80000000) & 0xFFFFFFFF


def faction_id(nickname: str | bytes) -> int:
    """``MakeId``: faction (reputation group) nickname -> u16."""
    h = 0xFFFF
    t = _FAC_TABLE
    for c in _lower_bytes(nickname):
        h = ((h & 0xFF00) >> 8) ^ t[(h & 0xFF) ^ c]
    return h & 0xFFFF


def location_id(base: str | int, room: str) -> int:
    """``MakeLocationID``: base (nickname or CreateID value) + room name -> u32."""
    base_id = base if isinstance(base, int) else create_id(base)
    return create_id("%X_%s" % (base_id, room))


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="flhash", description="Freelancer CreateID / faction id")
    ap.add_argument("names", nargs="+")
    ap.add_argument("--faction", action="store_true", help="print the 16-bit faction id instead")
    ap.add_argument("--room", help="print MakeLocationID(CreateID(name), ROOM)")
    a = ap.parse_args(argv)
    for n in a.names:
        if a.room:
            v = location_id(n, a.room)
        elif a.faction:
            v = faction_id(n)
        else:
            v = create_id(n)
        print(f"{n}\t{v}\t0x{v:X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
