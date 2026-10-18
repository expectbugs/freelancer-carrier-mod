"""fltools.validate on stock HDE and on a synthetic broken overlay (install read-only)."""
from __future__ import annotations

import json
import os

import pytest

from fltools import validate
from fltools.install import Install


def test_stock_hde_has_zero_errors(install):
    rep = validate.validate(install)
    assert rep.errors == [], "\n".join(f.render() for f in rep.errors[:20])
    assert rep.count("WARNING") == 0, "new vanilla warnings: refresh the baseline"
    assert rep.exit_code == 0
    assert rep.stats["hardpoints_checked"] > 10000      # loadout hardpoints exist on models
    assert rep.stats["ids_checked"] > 10000


def test_baseline_is_exact(install):
    """Every baseline entry is still produced (no stale entries) and nothing else is."""
    raw = validate.validate(install, baseline=set())
    got = {f.key for f in raw.findings if f.severity in ("ERROR", "WARNING")}
    assert got == validate.load_baseline()


def _first(install, key, section, n=1):
    out = []
    for rel in install.data_files(key):
        for s in install.data_ini(rel).sections(section):
            if s.nickname:
                out.append(s.nickname)
                if len(out) == n:
                    return out
    return out


def _rel(install, p) -> str:
    return os.path.relpath(p, install.root).replace(os.sep, "/")


def _overlay(tmp_path, files: dict[str, str], units: list[dict]):
    ov = tmp_path / "overlay"
    ov.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = ov / "files" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.replace("\n", "\r\n").encode("latin-1"))
    (ov / "patches.json").write_text(json.dumps({"version": 1, "units": units}))
    (ov / "MANIFEST.json").write_text(json.dumps({"schema": "fcm.overlay.v1", "files": {}}))
    return ov


@pytest.fixture(scope="module")
def broken(install, tmp_path_factory):
    """One overlay with each deliberate break of the acceptance list (plus encounter rules)."""
    I = install
    tmp = tmp_path_factory.mktemp("broken")
    power = _first(I, "equipment", "Power")[0]
    engine = _first(I, "equipment", "Engine")[0]
    ship = _first(I, "ships", "Ship")[0]
    vanilla_loadout, vanilla_loadout2 = _first(I, "loadouts", "Loadout", 2)
    system = I.data_ini(I.data_files("universe")[0]).sections("system")[0]
    sysnick = system.nickname
    sys_rel = _rel(I, I.data_path("universe/" + system.get1("file")))
    pilot = I.data_ini(r"missions\pilots_population.ini").sections("Pilot")[0].nickname
    any_base = I.data_ini(I.data_files("universe")[0]).sections("Base")[0]
    room_file = I.data_ini(any_base.get1("file")).sections("Room")[0].get1("file")
    shipclass = I.data_ini(r"missions\shipclasses.ini").sections("ShipClass")[0].nickname
    fp = I.data_ini(r"missions\faction_prop.ini").sections("FactionProps")[0]
    faction = fp.get1("affiliation")
    form_class = fp.getallv("formation")[0][0]
    assert vanilla_loadout.swapcase() != vanilla_loadout
    assert vanilla_loadout2.lower() != vanilla_loadout.lower()
    # a faction with no [BaseFaction] on any base of the first system (for E006)
    uni = I.data_ini(I.data_files("universe")[0])
    bases_here = {b.nickname.lower() for b in uni.sections("Base")
                  if (b.get1("system") or "").lower() == sysnick.lower()}
    facs_here, cur = set(), None
    for sec in I.data_ini(r"missions\mbases.ini").sections():
        if sec.lname == "mbase":
            cur = (sec.nickname or "").lower()
        elif sec.lname == "basefaction" and cur in bases_here:
            facs_here.add((sec.get1("faction") or "").lower())
    groups = [g.nickname for rel in I.data_files("groups")
              for g in I.data_ini(rel).sections("Group") if g.nickname]
    fac2 = next(g for g in groups if g.lower() not in facs_here)
    # a (system, faction) pair stock HDE already has as a baselined E006 finding (our baseline
    # text, read at test time): an overlay zone of the same pair must still be an ERROR
    e006 = sorted(k for k in validate.load_baseline() if k.startswith("e006|"))[0]
    b_sys, b_fac = e006.split("|")[2].split(":")
    b_sec = next(x for x in uni.sections("system") if x.nickname.lower() == b_sys)
    b_sys_rel = _rel(I, I.data_path("universe/" + b_sec.get1("file")))

    data = os.path.relpath(I.data_dir, I.root)
    files = {
        f"{data}/SHIPS/fcm_test_loadouts.ini": "\n".join([
            "[Loadout]", "nickname = fcm_test_lo_badequip",
            "equip = fcm_no_such_equipment, HpWeapon01", "",
            "[Loadout]", "nickname = fcm_test_lo_noengine", f"equip = {power}", "",
            "[Loadout]", "nickname = fcm_test_lo_ok", f"equip = {engine}", f"equip = {power}", "",
            "[Loadout]", f"nickname = {vanilla_loadout.swapcase()}", f"equip = {engine}", "",
            "[Loadout]", f"nickname = {vanilla_loadout2}", f"equip = {engine}", "",      # D002
            "[Loadout]", "nickname = fcm_test_lo_badhp", f"archetype = {ship}",          # H001
            f"equip = {engine}", f"equip = {power}, HpFcmNoSuchHardpoint", "",
            "[Loadout]", "nickname = test_lo_noprefix", f"equip = {engine}", ""]),     # C001
        f"{data}/UNIVERSE/fcm_test_base.ini": "\n".join([
            "[BaseInfo]", "nickname = fcm_test_base", "start_room = Deck", "",
            "[Room]", "nickname = Deck", f"file = {room_file}", ""]),
        f"{data}/MISSIONS/ENCOUNTERS/fcm_test_enc.ini": "\n".join([
            "[EncounterFormation]", f"ship_by_class = 1, 18, {shipclass}",
            f"formation_by_class = {form_class}", "behavior = wander", "",
            "[Creation]", "permutation = 0, 1", "permutation = 3, 1", ""]),
        f"{data}/MISSIONS/ENCOUNTERS/fcm_test_enc2.ini": "\n".join([           # E003 x2
            "[EncounterFormation]", f"ship_by_class = 1, 2, {shipclass}",
            "formation_by_class = fcm_no_such_class", "formation = fcm_no_such_formation",
            "behavior = wander", "", "[Creation]", "permutation = 0, 1", ""]),
        f"{data}/MISSIONS/ENCOUNTERS/fcm_test_enc3.ini": "\n".join([           # clean
            "[EncounterFormation]", f"ship_by_class = 1, 2, {shipclass}", "behavior = wander",
            "", "[Creation]", "permutation = 0, 1", ""]),
    }
    units = [
        {"file": "EXE/freelancer.ini", "id": "t.data", "version": 1, "ops": [
            {"op": "append", "section": "Data",
             "lines": ["loadouts = ships\\fcm_test_loadouts.ini"]}]},
        {"file": f"{data}/MISSIONS/npcships.ini", "id": "t.npc", "version": 1, "ops": [
            {"op": "add_section", "lines": [
                "[NPCShipArch]", "nickname = fcm_test_npc", f"loadout = fcm_test_lo_noengine",
                "level = d1", f"ship_archetype = {ship}", f"pilot = {pilot}",
                "state_graph = FIGHTER", "npc_class = unlawful, d1"]},
            {"op": "add_section", "lines": [
                "[NPCShipArch]", "nickname = fcm_test_npc_ok", "loadout = fcm_test_lo_ok",
                "level = d1", f"ship_archetype = {ship}", f"pilot = {pilot}",
                "state_graph = FIGHTER", "npc_class = unlawful, d1"]},
            {"op": "add_section", "lines": [                                       # C001
                "[NPCShipArch]", "nickname = test_npc_noprefix", "loadout = fcm_test_lo_ok",
                "level = d1", f"ship_archetype = {ship}", f"pilot = {pilot}",
                "state_graph = FIGHTER", "npc_class = unlawful, d1"]}]},
        {"file": _rel(I, I.data_path(I.data_files("universe")[0])), "id": "t.base",
         "version": 1, "ops": [{"op": "add_section", "lines": [
             "[Base]", "nickname = fcm_test_base", f"system = {sysnick}",
             f"strid_name = {0x7F0001}", "file = universe\\fcm_test_base.ini"]}]},
        {"file": f"{data}/MISSIONS/mbases.ini", "id": "t.mbase", "version": 1, "ops": [
            {"op": "add_section", "lines": ["[MBase]", "nickname = fcm_test_base",
                                            f"local_faction = {faction}", "diff = 1"]}]},
        {"file": sys_rel, "id": "t.enc", "version": 1, "ops": [
            {"op": "add_section", "lines": [
                "[EncounterParameters]", "nickname = fcm_test_enc",
                "filename = missions\\encounters\\fcm_test_enc.ini"]},
            {"op": "add_section", "lines": [
                "[zone]", "nickname = fcm_test_zone", "pos = 0, 0, 0", "shape = SPHERE",
                "size = 1000", "density = 1", "encounter = fcm_test_enc, 1, 0.1",
                f"faction = {faction}, 1"]},
            {"op": "add_section", "lines": [
                "[EncounterParameters]", "nickname = fcm_test_enc2",
                "filename = missions\\encounters\\fcm_test_enc2.ini"]},
            {"op": "add_section", "lines": [                                        # E006
                "[zone]", "nickname = fcm_test_zone2", "pos = 0, 0, 0", "shape = SPHERE",
                "size = 1000", "path_label = fcm_test_path, 1", "density = 1",
                "encounter = fcm_test_enc2, 1, 0.1", f"faction = {fac2}, 1"]}]},
        {"file": b_sys_rel, "id": "t.enc3", "version": 1, "ops": [
            {"op": "add_section", "lines": [
                "[EncounterParameters]", "nickname = fcm_test_enc3",
                "filename = missions\\encounters\\fcm_test_enc3.ini"]},
            {"op": "add_section", "lines": [
                "[zone]", "nickname = fcm_test_zone3", "pos = 0, 0, 0", "shape = SPHERE",
                "size = 1000", "path_label = fcm_test_path3, 1", "density = 1",
                "encounter = fcm_test_enc3, 1, 0.1", f"faction = {b_fac}, 1"]}]},
    ]
    ov = _overlay(tmp, files, units)
    rep = validate.validate(Install(I.root, ov))
    return {"rep": rep, "vanilla_loadout": vanilla_loadout, "vanilla_loadout2": vanilla_loadout2,
            "sysnick": sysnick, "fac2": fac2, "b_pair": f"{b_sys}:{b_fac}"}


def _errors(rep):
    return {(f.code, f.subject.lower()) for f in rep.errors}


def test_broken_overlay_reports_each_break(broken):
    rep = broken["rep"]
    errs = _errors(rep)
    assert ("L001", "fcm_test_lo_badequip:fcm_no_such_equipment") in errs   # missing equipment
    assert ("N002", "fcm_test_npc") in errs                                  # NPC without engine
    assert ("B005", "fcm_test_base") in errs                                 # base without dock
    assert any(c == "I001" and s.startswith("fcm_test_base:strid_name") for c, s in errs)
    assert ("D001", broken["vanilla_loadout"].lower()) in errs               # case-only dup
    assert rep.exit_code == 1
    for f in rep.errors:
        assert f.overlay, f"unexpected non-overlay error: {f.render()}"


def test_broken_overlay_encounter_rules(broken):
    errs = _errors(broken["rep"])
    assert ("E001", "fcm_test_enc#0") in errs                  # 18 ships in a formation
    assert ("E002", "fcm_test_enc:3, 1") in errs               # permutation past formations


def test_broken_overlay_no_collateral(broken):
    """The valid parts of the overlay raise nothing; the base has its MBase, rooms and file."""
    subjects = {f.subject.lower() for f in broken["rep"].findings
                if f.severity in ("ERROR", "WARNING")}
    assert not any(s.startswith(("fcm_test_lo_ok", "fcm_test_npc_ok")) for s in subjects)
    codes_for_base = {f.code for f in broken["rep"].errors if f.subject.lower() == "fcm_test_base"}
    assert codes_for_base == {"B005"}


def test_cli_exit_codes(hde, capsys):
    assert validate.main(["--install", str(hde), "--show", "ERROR"]) == 0
    assert "ERROR=0" in capsys.readouterr().out


def test_overlay_warnings_become_errors(broken):
    """m3: D002, H001 and E006 are ERRORs when the finding involves overlay content."""
    errs = _errors(broken["rep"])
    assert ("D002", broken["vanilla_loadout2"].lower()) in errs           # same-case redefinition
    assert ("H001", "fcm_test_lo_badhp:hpfcmnosuchhardpoint") in errs      # missing hardpoint
    assert ("E006", f"{broken['sysnick']}:{broken['fac2']}".lower()) in errs
    # a vanilla (baselined) system/faction pair hit by an overlay zone is not swallowed
    assert ("E006", broken["b_pair"]) in errs
    assert not [f for f in broken["rep"].findings
                if f.severity == "BASELINE" and f.subject.lower() == broken["b_pair"]]


def test_encounter_formation_rules(broken):
    """E003, both forms: a formation name missing from formations.ini, and a faction without
    a formation for the encounter's formation_by_class (an overlay zone makes it overlay)."""
    errs = _errors(broken["rep"])
    assert ("E003", "fcm_test_enc2:fcm_no_such_formation") in errs
    assert ("E003", f"{broken['fac2']}:fcm_no_such_class".lower()) in errs
    e003 = [f for f in broken["rep"].errors if f.code == "E003"]
    assert e003 and all(f.overlay for f in e003)


def test_mod_prefix_rule(broken):
    """C001: new overlay nicknames need fcm_; rooms and re-definitions are not 'new'."""
    c001 = {f.subject.lower(): f for f in broken["rep"].findings if f.code == "C001"}
    assert set(c001) == {"test_lo_noprefix", "test_npc_noprefix"}, sorted(c001)
    assert all(f.severity == "ERROR" for f in c001.values())
    assert c001["test_npc_noprefix"].file == "missions/npcships.ini"
    assert c001["test_lo_noprefix"].file.lower() == "ships/fcm_test_loadouts.ini"


def test_patch_unit_provenance(install, tmp_path):
    """r2 MINOR 4: every section a unit adds is overlay (by region), C001 newness is judged per
    namespace, and units touching a vanilla nickname key are C002 errors. Names are picked at
    test time from the install."""
    I = install
    goods_rel = I.data_files("goods")[0]
    good1, good2 = [s.nickname for s in I.data_ini(goods_rel).sections("Good")[:2]]
    eq_rel = I.data_files("equipment")[0]
    equip_nicks = {s.nickname.lower() for r in I.data_files("equipment")
                   for s in I.data_ini(r).sections() if s.nickname}
    ship = next(s.nickname for r in I.data_files("ships") for s in I.data_ini(r).sections("Ship")
                if s.nickname and s.nickname.lower() not in equip_nicks)
    units = [
        {"file": _rel(I, I.data_path(goods_rel)), "id": "t.dup", "version": 1, "ops": [
            {"op": "add_section", "lines": ["[Good]", f"nickname = {good1}"]}]},
        {"file": _rel(I, I.data_path(eq_rel)), "id": "t.xns", "version": 1, "ops": [
            {"op": "add_section", "lines": ["[Engine]", f"nickname = {ship}"]}]},
        {"file": _rel(I, I.data_path(goods_rel)), "id": "t.ren", "version": 1, "ops": [
            {"op": "set", "section": "Good", "match": {"nickname": good2}, "key": "nickname",
             "value": "fcm_renamed_good"}]},
    ]
    rep = validate.validate(Install(I.root, _overlay(tmp_path, {}, units)))
    errs = {(f.code, f.subject.lower()): f for f in rep.errors}
    assert ("D002", good1.lower()) in errs and errs[("D002", good1.lower())].overlay  # same file
    assert ("C001", ship.lower()) in errs        # new [Engine] named like a vanilla [Ship]
    assert ("C002", good2.lower()) in errs       # rename of a shipped nickname
    assert rep.exit_code == 1


def _path_encounters(I, sys_doc, faction):
    """Encounters used by path zones of ``faction`` in a system doc."""
    out = []
    for z in sys_doc.sections("zone"):
        if not z.getv("path_label"):
            continue
        cur = None
        for e in z.entries():
            if e.lkey == "encounter":
                cur = e.values[0]
            elif e.lkey == "faction" and cur and e.values[0].lower() == faction:
                out.append(cur)
    return out


def test_vanilla_encounter_reused_in_a_new_zone_flags_nothing_else(install, tmp_path):
    """r2b: a unit that declares a vanilla encounter ([EncounterParameters] is a reference
    section) in the first system for a new, valid fcm_ zone adds 0 ERROR/WARNING findings. In
    particular, the baselined E006 pairs of vanilla zones elsewhere that use the same encounter
    stay BASELINE. Everything is picked at test time from the install and our baseline."""
    I = install
    uni = I.data_ini(I.data_files("universe")[0])
    systems = {s.nickname.lower(): s for s in uni.sections("system")}
    first = uni.sections("system")[0]
    sysnick = first.nickname.lower()
    bases_here = {b.nickname.lower() for b in uni.sections("Base")
                  if (b.get1("system") or "").lower() == sysnick}
    facs_here, cur = set(), None
    for sec in I.data_ini(r"missions\mbases.ini").sections():
        if sec.lname == "mbase":
            cur = (sec.nickname or "").lower()
        elif sec.lname == "basefaction" and cur in bases_here:
            facs_here.add((sec.get1("faction") or "").lower())
    forms: dict[str, set[str]] = {}
    for fp in I.data_ini(r"missions\faction_prop.ini").sections("FactionProps"):
        forms[(fp.get1("affiliation") or "").lower()] = {v[0].lower() for v in
                                                        fp.getallv("formation") if v}
    pick = None
    for key in sorted(k for k in validate.load_baseline() if k.startswith("e006|")):
        b_sys, b_fac = key.split("|")[2].split(":")
        sdoc = I.data_ini("universe/" + systems[b_sys].get1("file"))
        params = {(p.get1("nickname") or "").lower(): p.get1("filename")
                  for p in sdoc.sections("EncounterParameters")}
        for enc in _path_encounters(I, sdoc, b_fac):
            efile = params.get(enc.lower())
            edoc = I.data_ini(efile) if efile else None
            if edoc is None:
                continue
            classes = {(f.get1("formation_by_class") or "").lower()
                       for f in edoc.sections("EncounterFormation")} - {""}
            ok = [f for f in sorted(facs_here) if classes <= forms.get(f, set())]
            if ok:
                pick = (key, enc, efile, ok[0])
                break
        if pick:
            break
    if pick is None:
        pytest.skip("no baselined E006 encounter usable in a valid zone of the first system")
    key, enc, efile, fac = pick
    sys_rel = _rel(I, I.data_path("universe/" + first.get1("file")))
    units = [{"file": sys_rel, "id": "t.reuse", "version": 1, "ops": [
        {"op": "add_section", "lines": ["[EncounterParameters]", f"nickname = {enc}",
                                        f"filename = {efile}"]},
        {"op": "add_section", "lines": [
            "[zone]", "nickname = fcm_zone_reuse_probe", "pos = 0, 0, 0", "shape = SPHERE",
            "size = 5000", "path_label = fcm_reuse_path, 1", "density = 1",
            f"encounter = {enc}, 1, 0.5", f"faction = {fac}, 1"]}]}]
    v = validate.Validator(Install(I.root, _overlay(tmp_path, {}, units)))
    rep = v.run()
    assert [f.render() for f in rep.findings if f.severity in ("ERROR", "WARNING")] == []
    assert any(f.key == key and f.severity == "BASELINE" for f in rep.findings)
    # each half of the fix on its own:
    assert "fcm_zone_reuse_probe" in v._overlay_nicks          # the new zone is overlay ...
    assert enc.lower() not in v._overlay_nicks                 # ... the referenced encounter not
    v._overlay_nicks.add(enc.lower())                          # even if it were, a vanilla
    b_sys = key.split("|")[2].split(":")[0]                    # zone row stays vanilla
    b_rel = "universe/" + systems[b_sys].get1("file")
    assert not v._row_is_overlay("vanilla_zone", enc, b_rel, efile)
    assert v._row_is_overlay("fcm_zone_reuse_probe", enc, b_rel, efile)
