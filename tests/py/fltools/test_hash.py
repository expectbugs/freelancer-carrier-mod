"""fltools.hash: CreateID goldens, faction id, location id."""
from __future__ import annotations

import re

import pytest

from fltools.hash import create_id, faction_id, location_id

# Algorithm outputs VERIFIED against hashes the game wrote into newplayer.fl (R3 §10).
CREATE_ID_GOLDENS = {
    "Li01_to_Li02": 2830511361,
    "Ew06_01_Base": 3094908802,
    "Li02": 2745692751,
    "ew0601_monkey_003_m": 2318074572,
    "Br05": 2945937410,
}


@pytest.mark.parametrize("name,value", sorted(CREATE_ID_GOLDENS.items()))
def test_create_id_goldens(name, value):
    assert create_id(name) == value
    assert create_id(name.upper()) == value  # case-insensitive


def test_create_id_shape():
    for n in ("a", "fcm_salvage_pod", "x" * 300, ""):
        h = create_id(n)
        assert h & 0x80000000 and 0 <= h <= 0xFFFFFFFF


def test_create_id_against_game_written_hashes(hde):
    """Every ``locked_gate = <hash> ; <nickname>`` comment pair in the install's newplayer.fl
    (written by the game's own tools) matches our CreateID."""
    from fltools.ini import ci_path
    txt = ci_path(hde, "EXE/newplayer.fl").read_bytes().decode("latin-1")
    pairs = re.findall(r"locked_gate\s*=\s*(\d+)\s*;\s*(\S+)", txt)
    assert len(pairs) >= 10
    assert [n for h, n in pairs if create_id(n) != int(h)] == []


def _crc16_ccitt_bitwise(data: bytes, init: int = 0xFFFF) -> int:
    """Re-derivation of MakeId's update rule ``crc = table[(crc ^ b) & 0xff] ^ (crc >> 8)``
    (MSB-first 0x1021 table), computing each table entry on the fly instead of using the
    module's precomputed table."""
    def table_entry(i: int) -> int:
        x = i << 8
        for _ in range(8):
            x = ((x << 1) ^ 0x1021) if x & 0x8000 else (x << 1)
            x &= 0xFFFF
        return x
    crc = init
    for b in data:
        crc = table_entry((crc ^ b) & 0xFF) ^ (crc >> 8)
    return crc


@pytest.mark.parametrize("name", ["li_n_grp", "fc_or_grp", "fcm_test_faction", "x", ""])
def test_faction_id(name):
    """UNVERIFIED against a game-produced value (none found in saves or reference code);
    this checks the port against an independent re-derivation of Librelancer's FLFacHash /
    MakeId (sources: tools/fltools/NOTES.md §6), its 16-bit range and case-insensitivity."""
    v = faction_id(name)
    assert 0 <= v <= 0xFFFF
    assert v == faction_id(name.upper())
    assert v == _crc16_ccitt_bitwise(name.lower().encode("latin-1"))


def test_faction_id_algorithm_output_golden():
    # algorithm output (R3 §10: "li_n_grp -> 8778, computed by the port"); UNVERIFIED in game
    assert faction_id("li_n_grp") == 8778
    assert faction_id("li_n_grp") != create_id("li_n_grp")


def test_location_id():
    assert location_id("Li01_01_Base", "Bar") == create_id("%X_Bar" % create_id("Li01_01_Base"))
    assert location_id(create_id("li01_01_base"), "Bar") == location_id("Li01_01_Base", "Bar")
