"""fltools.patch: idempotent, reversible marker-block patches."""
from __future__ import annotations

import json
import shutil

import pytest

from fltools import ini, patch
from fltools.patch import PatchError, PatchState, apply_units, strip

BASE = (
    "[Freelancer]\r\n"
    "data path = ..\\data\r\n"
    "\r\n"
    "[Resources]\r\n"
    "DLL = InfoCards.dll ; text\r\n"
    "DLL = Controls.dll\r\n"
    "\r\n"
    "[Data]\r\n"
    "equipment = equipment\\a.ini\r\n"
    "equipment = equipment\\b.ini\r\n"
    "goods = equipment\\goods.ini\r\n"
    "\r\n"
    "[BaseGood]\r\n"
    "base = Li01_01_Base\r\n"
    "marketgood = gun_a, 3, -1, 1, 1, 0, 1\r\n"
    "marketgood = gun_b, 0, -1, 1, 1, 0, 1\r\n"
    "marketgood = gun_c, 12, 0.2, 1, 1, 0, 1\r\n"
    "\r\n"
    "[BaseGood]\r\n"
    "base = Li01_02_Base\r\n"
    "marketgood = gun_a, 5, -1, 1, 1, 0, 1\r\n"
    "; comment line\r\n"
    "marketgood = gun_d, 7, -1, 1, 1, 0, 1"          # no final newline
)


def U(uid, ops, version=1, file="EXE/freelancer.ini"):
    return {"file": file, "id": uid, "version": version, "ops": ops}


def test_append_and_strip_roundtrip():
    out = apply_units(BASE, [U("res", [{"op": "append", "section": "Resources",
                                         "lines": ["DLL = fcm_text.dll"]}]),
                             U("data", [{"op": "append", "section": "Data",
                                         "lines": ["equipment = equipment\\fcm_equip.ini"]}])])
    doc = ini.loads(out)
    assert doc.section("Resources").getall("DLL")[-1] == "fcm_text.dll"
    assert doc.section("Data").getall("equipment") == ["equipment\\a.ini", "equipment\\b.ini",
                                                        "equipment\\fcm_equip.ini"]
    assert "; >>> carrier-mod res v1\r\nDLL = fcm_text.dll\r\n; <<< carrier-mod res\r\n" in out
    assert strip(out)[0] == BASE
    assert sorted(strip(out)[1]) == ["data", "res"]


def test_append_after_same_key_keeps_load_order():
    out = apply_units(BASE, [U("eq", [{"op": "append", "section": "Data", "after_key": "equipment",
                                        "lines": ["equipment = equipment\\fcm_equip.ini"]}]),
                             U("new", [{"op": "append", "section": "Data", "after_key": "ships",
                                        "lines": ["ships = ships\\fcm_ships.ini"]}])])
    keys = [(e.key, e.params) for e in ini.loads(out).section("Data").entries()]
    assert keys == [("equipment", "equipment\\a.ini"), ("equipment", "equipment\\b.ini"),
                    ("equipment", "equipment\\fcm_equip.ini"), ("goods", "equipment\\goods.ini"),
                    ("ships", "ships\\fcm_ships.ini")]          # no 'ships' yet: end of section
    assert strip(out)[0] == BASE


def test_set_field_all_occurrences_like_d21():
    """D-2.1 shape: set every marketgood level (field 1) to 0 in every [BaseGood]."""
    unit = U("levels", [{"op": "set", "section": "BaseGood", "match": "*", "nth": "all",
                         "key": "marketgood", "field": 1, "value": "0", "occurrence": "all"}])
    out = apply_units(BASE, [unit])
    doc = ini.loads(out)
    lv = [e.values[1] for s in doc.sections("BaseGood") for e in s.entries("marketgood")]
    assert lv == ["0"] * 5
    # unchanged lines (gun_b already 0) are not wrapped; each run of consecutive replaced
    # lines is one region (gun_a | gun_c | gun_a | gun_d: the comment line splits the last two)
    ids = [r for r, _v in patch.region_ids(out)]
    assert ids == ["levels#1", "levels#2", "levels#3", "levels#4"]
    assert patch.DISABLED + "marketgood = gun_a, 3, -1, 1, 1, 0, 1" in out
    assert strip(out)[0] == BASE          # includes restoring the missing final newline


def test_set_by_nickname_match_and_comment_out_where():
    out = apply_units(BASE, [
        U("price", [{"op": "set", "section": "BaseGood", "match": {"base": "li01_02_base"},
                     "key": "marketgood", "value": "gun_a, 1, -1, 1, 1, 0, 1"}]),
        U("off", [{"op": "comment_out", "section": "Resources", "key": "DLL",
                   "where": {"field": 0, "value": "controls.dll"}, "occurrence": "all"}]),
    ])
    doc = ini.loads(out)
    assert doc.sections("BaseGood")[1].getall("marketgood")[0] == "gun_a, 1, -1, 1, 1, 0, 1"
    assert doc.sections("BaseGood")[0].getall("marketgood")[0].startswith("gun_a, 3")
    assert doc.section("Resources").getall("DLL") == ["InfoCards.dll"]
    assert strip(out)[0] == BASE


def test_add_section_eof_and_after():
    out = apply_units(BASE, [
        U("s1", [{"op": "add_section", "lines": ["[Good]", "nickname = fcm_x", "price = 1"]}]),
        U("s2", [{"op": "add_section", "after": {"section": "Data"},
                  "lines": ["[Good]", "nickname = fcm_y"]}]),
    ])
    doc = ini.loads(out)
    assert [s.nickname for s in doc.sections("Good")] == ["fcm_y", "fcm_x"]
    assert out.endswith("; <<< carrier-mod s1\r\n")
    assert strip(out)[0] == BASE


def test_add_missing_key():
    out = apply_units(BASE, [U("k", [{"op": "set", "section": "Freelancer", "key": "fcm_flag",
                                      "value": "1"}])])
    assert ini.loads(out).section("Freelancer").get("fcm_flag") == "1"
    assert strip(out)[0] == BASE


def test_errors():
    with pytest.raises(PatchError):
        apply_units(BASE, [U("x", [{"op": "append", "section": "NoSuch", "lines": ["a = 1"]}])])
    with pytest.raises(PatchError, match="two ops replace"):
        apply_units(BASE, [U("a", [{"op": "comment_out", "section": "Resources", "key": "DLL"}]),
                           U("b", [{"op": "comment_out", "section": "Resources", "key": "DLL"}])])
    with pytest.raises(PatchError):
        apply_units(BASE, [U("bad id!", [{"op": "append", "section": "Data", "lines": ["x"]}])])
    with pytest.raises(PatchError):
        apply_units(BASE, [U("a", [{"op": "frobnicate"}])])
    with pytest.raises(PatchError, match="pristine"):
        apply_units(apply_units(BASE, [U("a", [{"op": "append", "section": "Data",
                                                "lines": ["x = 1"]}])]), [])
    with pytest.raises(PatchError):
        strip("; >>> carrier-mod a v1\r\nx\r\n")


def _file(tmp_path, text=BASE):
    root = tmp_path / "inst"
    (root / "EXE").mkdir(parents=True)
    (root / "EXE" / "freelancer.ini").write_bytes(text.encode("latin-1"))
    return root


def test_patch_file_idempotent_and_reversible(tmp_path):
    root = _file(tmp_path)
    f = root / "EXE" / "freelancer.ini"
    units = [U("res", [{"op": "append", "section": "Resources", "lines": ["DLL = fcm_text.dll"]}])]
    assert patch.patch_file(root, "EXE/freelancer.ini", units, log=lambda m: None) is True
    once = f.read_bytes()
    assert patch.patch_file(root, "exe\\FREELANCER.INI", units, log=lambda m: None) is False
    assert f.read_bytes() == once
    st = json.loads((root / patch.STATE_NAME).read_text())
    rec = st["files"]["exe/freelancer.ini"]
    assert rec["original_sha256"] == patch.sha256(BASE.encode("latin-1"))
    assert rec["patched_sha256"] == patch.sha256(once)
    # version bump replaces the region
    units2 = [dict(units[0], version=2, ops=[{"op": "append", "section": "Resources",
                                               "lines": ["DLL = fcm_text2.dll"]}])]
    patch.patch_file(root, "EXE/freelancer.ini", units2, log=lambda m: None)
    txt = f.read_text("latin-1")
    assert "res v2" in txt and "fcm_text.dll\r" not in txt and txt.count("carrier-mod res") == 2
    assert patch.unpatch_file(root, "EXE/freelancer.ini", log=lambda m: None) is True
    assert f.read_bytes() == BASE.encode("latin-1")


def test_refuses_unexpected_change_and_force_rebaselines(tmp_path):
    root = _file(tmp_path)
    f = root / "EXE" / "freelancer.ini"
    units = [U("res", [{"op": "append", "section": "Resources", "lines": ["DLL = fcm.dll"]}])]
    patch.patch_file(root, "EXE/freelancer.ini", units, log=lambda m: None)
    # someone else edits the file outside our regions (e.g. an installer re-run)
    f.write_bytes(f.read_bytes().replace(b"Controls.dll", b"Controls2.dll"))
    with pytest.raises(PatchError, match="changed"):
        patch.patch_file(root, "EXE/freelancer.ini", units, log=lambda m: None)
    logs = []
    patch.patch_file(root, "EXE/freelancer.ini", units, force=True, log=logs.append)
    assert any("re-baselined" in m for m in logs)
    st = json.loads((root / patch.STATE_NAME).read_text())
    assert any("re-baselined exe/freelancer.ini" in line.lower() for line in st["log"])
    assert b"Controls2.dll" in f.read_bytes() and b"fcm.dll" in f.read_bytes()


def test_unpatch_one_unit_keeps_others(tmp_path):
    root = _file(tmp_path)
    f = root / "EXE" / "freelancer.ini"
    patch.patch_file(root, "EXE/freelancer.ini", [
        U("a", [{"op": "append", "section": "Data", "lines": ["goods = fcm_a.ini"]}]),
        U("b", [{"op": "append", "section": "Data", "lines": ["goods = fcm_b.ini"]}])],
        log=lambda m: None)
    patch.unpatch_file(root, "EXE/freelancer.ini", ["a"], log=lambda m: None)
    t = f.read_text("latin-1")
    assert "fcm_a.ini" not in t and "fcm_b.ini" in t
    patch.unpatch_file(root, "EXE/freelancer.ini", None, log=lambda m: None)
    assert f.read_bytes() == BASE.encode("latin-1")


def test_commit_saves_state_before_patching_and_after_restoring(tmp_path, monkeypatch):
    """A kill between the file write and the state save must never leave regions the saved
    state does not know about: when a file gains regions its record is on disk before the
    write; when it is restored the record goes only after the write."""
    root = _file(tmp_path)
    st_path = root / patch.STATE_NAME
    seen = []
    real = patch._write_atomic

    def spy(path, data):
        on_disk = json.loads(st_path.read_text())["files"] if st_path.exists() else {}
        seen.append((b"; >>> carrier-mod" in data, "exe/freelancer.ini" in on_disk))
        real(path, data)
    monkeypatch.setattr(patch, "_write_atomic", spy)
    units = [U("res", [{"op": "append", "section": "Resources", "lines": ["DLL = fcm.dll"]}])]
    patch.apply_overlay_patches(root, units, log=lambda m: None)
    patch.apply_overlay_patches(root, [], log=lambda m: None)
    assert seen == [(True, True),     # patching: record already saved
                    (False, True)]    # restoring: record still saved while writing
    assert not st_path.exists()          # nothing recorded any more: the state file goes too
    assert (root / "EXE" / "freelancer.ini").read_bytes() == BASE.encode("latin-1")


REAL_TARGETS = ["EXE/freelancer.ini", "EXE/dacom.ini", "DATA/EQUIPMENT/market_ships.ini",
                "DATA/MISSIONS/npcships.ini", "DATA/UNIVERSE/universe.ini",
                "DATA/MISSIONS/mbases.ini", "DATA/SOLAR/solararch.ini", "DATA/SHIPS/shiparch.ini",
                "DATA/SHIPS/loadouts.ini", "DATA/EQUIPMENT/market_misc.ini",
                "DATA/EQUIPMENT/market_commodities.ini"]


def test_real_hde_files_apply_unapply_byte_identical(hde, tmp_path):
    """Temp copies of real HDE files: patch (incl. the D-2.1 level reset on market_ships.ini),
    re-apply (no change), unpatch -> byte-identical."""
    root = tmp_path / "hde"
    rels = []
    for rel in REAL_TARGETS:
        p = ini.ci_path(hde, rel)
        assert p is not None, rel
        d = root / p.relative_to(hde)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, d)
        rels.append(str(p.relative_to(hde)))
    originals = {r: (root / r).read_bytes() for r in rels}
    ship = ini.load(root / rels[7]).sections("Ship")[0].nickname        # picked at test time
    loadout = ini.load(root / rels[8]).sections("Loadout")[0].nickname
    units = [
        U("fcm.res", [{"op": "append", "section": "Resources", "lines": ["DLL = fcm_text.dll"]}],
          file=rels[0]),
        U("fcm.data", [{"op": "append", "section": "Data",
                        "lines": ["equipment = equipment\\fcm_equip.ini"]}], file=rels[0]),
        U("fcm.libs", [{"op": "append", "section": "Libraries", "lines": ["fcm_carrier.dll"]}],
          file=rels[1]),
        U("fcm.levels", [{"op": "set", "section": "BaseGood", "match": "*", "nth": "all",
                          "key": "marketgood", "field": 1, "value": "0", "occurrence": "all"}],
          file=rels[2]),
        U("fcm.npc", [{"op": "add_section", "lines": ["[NPCShipArch]", "nickname = fcm_test_npc"]}],
          file=rels[3]),
        U("fcm.base", [{"op": "add_section", "lines": ["[Base]", "nickname = fcm_test_base"]}],
          file=rels[4]),
        U("fcm.mbase", [{"op": "add_section", "lines": ["[MBase]", "nickname = fcm_test_base"]}],
          file=rels[5]),
        U("fcm.solar", [{"op": "add_section", "lines": ["[Solar]", "nickname = fcm_test_solar"]}],
          file=rels[6]),
        U("fcm.ship", [{"op": "set", "section": "Ship", "match": {"nickname": ship.upper()},
                        "key": "hit_pts", "value": "123456"}], file=rels[7]),
        U("fcm.lo", [{"op": "append", "section": "Loadout", "match": {"nickname": loadout},
                      "lines": ["equip = fcm_test_equip"]}], file=rels[8]),
        U("fcm.levels", [{"op": "set", "section": "BaseGood", "match": "*", "nth": "all",
                          "key": "marketgood", "field": 1, "value": "0", "occurrence": "all"}],
          file=rels[9]),
        U("fcm.levels", [{"op": "set", "section": "BaseGood", "match": "*", "nth": "all",
                          "key": "marketgood", "field": 1, "value": "0", "occurrence": "all"}],
          file=rels[10]),
        U("fcm.spdlls", [{"op": "append", "section": "Initial SP DLLs",
                          "lines": ["DLL = fcm_test.dll, Test, NORMAL"]}], file=rels[0]),
    ]
    noop = {r for r in rels      # e.g. a market whose levels are all 0 already: nothing to wrap
            if apply_units(originals[r].decode("latin-1"), [u for u in units if u["file"] == r])
            == originals[r].decode("latin-1")}
    changed = patch.apply_overlay_patches(root, units, log=lambda m: None)
    assert sorted(changed) == sorted(set(rels) - noop)
    assert len(noop) <= 1
    for r in (rels[2], rels[9], rels[10]):
        mk = ini.load(root / r)
        levels = {e.values[1] for s in mk.sections("BaseGood") for e in s.entries("marketgood")}
        assert levels == {"0"}, r
    assert ini.load(root / rels[7]).section("Ship", nickname=ship).get("hit_pts") == "123456"
    assert ini.load(root / rels[8]).section("Loadout", nickname=loadout).getall("equip")[-1] \
        == "fcm_test_equip"
    assert ini.load(root / rels[0]).section("Initial SP DLLs").getall("DLL")[-1] \
        .startswith("fcm_test.dll")
    assert ini.load(root / rels[0]).section("Resources").getall("DLL")[-1] == "fcm_text.dll"
    assert ini.load(root / rels[1]).section("Libraries").entries()[-1].key == "fcm_carrier.dll"
    patched = {r: (root / r).read_bytes() for r in rels}
    assert patch.apply_overlay_patches(root, units, log=lambda m: None) == []
    assert {r: (root / r).read_bytes() for r in rels} == patched
    patch.apply_overlay_patches(root, [], log=lambda m: None)
    assert {r: (root / r).read_bytes() for r in rels} == originals
    assert PatchState(root / patch.STATE_NAME).data["files"] == {}


def test_cli(tmp_path, capsys):
    root = _file(tmp_path)
    spec = tmp_path / "units.json"
    spec.write_text(json.dumps({"units": [U("res", [{"op": "append", "section": "Resources",
                                                      "lines": ["DLL = fcm.dll"]}])]}))
    assert patch.main(["apply", "--root", str(root), str(spec)]) == 0
    assert patch.main(["status", "--root", str(root)]) == 0
    assert "exe/freelancer.ini" in capsys.readouterr().out
    assert patch.main(["unpatch", "--root", str(root)]) == 0
    assert (root / "EXE" / "freelancer.ini").read_bytes() == BASE.encode("latin-1")
