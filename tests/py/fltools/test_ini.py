"""fltools.ini: lossless round trip, lookups, editing, path resolver, BINI."""
from __future__ import annotations

import os
import shutil

import pytest

from fltools import bini, ini

SYNTH = (
    b"; preamble comment (ignored by the game)\r\n"
    b"\r\n"
    b"[Ship]\r\n"
    b"nickname = fcm_a\r\n"
    b"Hit_Pts = 100 ; inline comment\r\n"
    b"hp_type = hp_gun, HpWeapon01 , HpWeapon02\r\n"
    b"hp_type = hp_turret, HpTurret01\r\n"
    b"bare_key\r\n"
    b"empty =\r\n"
    b"\r\n"
    b"[ship]\r\n"
    b"NICKNAME = fcm_b\r\n"
    b"name = caf\xe9 \x85 \xa0x\xa0\r\n"
    b"[;Disabled]\r\n"
    b"nickname = fcm_hidden\r\n"
    b"[Other]\n"
    b"k = v\n"
    b"lone\rcr = 1\n\r"
    b"last = no newline"
)


def test_roundtrip_synthetic_bytes():
    doc = ini.loads(SYNTH)
    assert doc.to_bytes() == SYNTH


@pytest.mark.parametrize("data", [b"", b"\r\n", b"[A]", b"[A]\r\nk=v", b"x\n\n\r\r\n\n\r",
                                  b"[A]\nk = 1\r\nj = 2\rq = 3\n\rz = 4",
                                  bytes(range(256)) * 3])
def test_roundtrip_edge_cases(data):
    assert ini.loads(data).to_bytes() == data


def test_sections_and_case_insensitive_lookup():
    doc = ini.loads(SYNTH)
    ships = doc.sections("SHIP")
    assert [s.nickname for s in ships] == ["fcm_a", "fcm_b"]
    a = ships[0]
    assert a.get("hit_pts") == "100"
    assert a.getv("HP_TYPE") == ["hp_gun", "HpWeapon01", "HpWeapon02"]
    assert a.getallv("hp_type")[1] == ["hp_turret", "HpTurret01"]
    assert a.getall("hp_type") == ["hp_gun, HpWeapon01 , HpWeapon02", "hp_turret, HpTurret01"]
    assert a.has("bare_key") and a.get("bare_key") == "" and a.getv("bare_key") == []
    assert a.get("empty") == "" and a.get1("empty") is None
    assert a.get("missing", "dflt") == "dflt"
    assert doc.section("ship", nickname="FCM_B").nickname == "fcm_b"
    # latin-1 bytes, NBSP and NEL are data, not blanks or line breaks
    assert ships[1].get("name") == "caf\xe9 \x85 \xa0x\xa0"
    # disabled sections are kept but skipped
    assert doc.sections("Disabled") == []
    assert doc.sections(";Disabled", include_disabled=True)[0].nickname == "fcm_hidden"
    other = doc.section("Other")
    assert other.get("k") == "v"
    # a lone CR ends a line, as in the game's reader: "lone" is a bare key, "cr = 1" a key
    assert other.has("lone") and other.get("cr") == "1"


def test_editing_keeps_untouched_bytes():
    doc = ini.loads(SYNTH)
    a = doc.section("Ship")
    a.set("hit_pts", 250)
    a.add("fcm_new", ["x", 1, 2.5])
    a.set("hp_type", "hp_gun, HpWeapon09", index=1)
    out = doc.to_bytes()
    assert b"Hit_Pts = 250 ; inline comment\r\n" in out
    assert b"fcm_new = x, 1, 2.5\r\n" in out
    assert b"hp_type = hp_gun, HpWeapon09\r\n" in out
    # everything after the first section is byte-identical
    tail = SYNTH[SYNTH.index(b"[ship]"):]
    assert out.endswith(tail)
    # the new key went after the last entry, before the trailing blank line
    assert out.index(b"fcm_new") < out.index(b"[ship]")
    assert ini.loads(out).section("Ship").get("fcm_new") == "x, 1, 2.5"
    with pytest.raises(IndexError):
        a.set("hp_type", "x", index=5)
    assert a.remove("hp_type") == 2 and not a.has("hp_type")


def test_add_section_and_eol():
    doc = ini.loads(b"[A]\r\nk = v")
    doc.add_section("Good", [("nickname", "fcm_g"), ("price", 10)])
    assert doc.to_bytes() == b"[A]\r\nk = v\r\n[Good]\r\nnickname = fcm_g\r\nprice = 10\r\n"
    lf = ini.loads(b"[A]\nk = v\n")
    lf.add_section("B")
    assert lf.to_bytes() == b"[A]\nk = v\n[B]\n"


def test_format_and_split():
    assert ini.format_value(3.0) == "3" and ini.format_value(0.25) == "0.25"
    assert ini.format_value([1, "a", True]) == "1, a, true"
    assert ini.split_params(" a ,\tb\t, c d ") == ["a", "b", "c d"]
    assert ini.split_params("") == []


def test_ci_resolver(tmp_path):
    (tmp_path / "DATA" / "Universe" / "SYSTEMS").mkdir(parents=True)
    f = tmp_path / "DATA" / "Universe" / "SYSTEMS" / "Li01.INI"
    f.write_text("[x]")
    r = ini.CIResolver()
    assert r.resolve(tmp_path, r"data\UNIVERSE\systems\li01.ini") == f
    assert r.resolve(tmp_path / "DATA", r"..\data\universe\systems\LI01.ini") == f
    assert r.resolve(tmp_path, "data/nope.ini") is None


def test_bini_decode_roundtrip(tmp_path):
    secs = [("Ship", [("nickname", ["fcm_b"]), ("hit_pts", [1000]), ("mass", [2.5]),
                      ("flag", [True]), ("multi", ["a", 1, 0.1])]),
            ("Empty", [])]
    raw = bini.encode(secs)
    got = bini.decode(raw)
    assert got[0][1][0] == ("nickname", ["fcm_b"])
    assert got[0][1][2][1][0] == pytest.approx(2.5)
    doc = ini.loads(raw)
    assert doc.source_format == "bini"
    assert doc.section("ship").get("multi") == "a, 1, 0.1"
    assert doc.section("ship").get("flag") == "true"
    with pytest.raises(ValueError, match="BINI"):
        doc.dump(tmp_path / "x.ini")


def test_every_hde_data_ini_roundtrips(hde, tmp_path):
    """REQ-2 acceptance: every INI under the install's DATA, copied to tmp, round-trips 100%
    byte-identical through load -> dump."""
    src_root = ini.ci_path(hde, "DATA")
    copied = tmp_path / "DATA"
    rels = []
    for p in ini.iter_ini_files(src_root):
        rel = os.path.relpath(p, src_root)
        d = copied / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, d)
        rels.append(rel)
    assert len(rels) > 1000, "expected the full HDE DATA tree"
    out_root = tmp_path / "out"
    bad = []
    n_sections = 0
    for rel in rels:
        doc = ini.load(copied / rel)
        assert doc.source_format == "text", f"{rel} is BINI (HDE should have none)"
        n_sections += len(doc.all_sections)
        o = out_root / rel
        o.parent.mkdir(parents=True, exist_ok=True)
        doc.dump(o)
        if o.read_bytes() != (copied / rel).read_bytes():
            bad.append(rel)
    assert bad == [], f"{len(bad)} files differ, e.g. {bad[:5]}"
    assert n_sections > 10000
