"""gen_fixture.py + flhash.py tests (REQ-P0-HARNESS-16).

Every spec in harness/fixtures/specs/ is rendered from the dev baseline install (read-only) into tmp_path.
Expected values that come from game data are read from the install at test time, never hard-coded here.
"""
import math
import os
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIXTURES = os.path.join(HARNESS, "fixtures")
sys.path.insert(0, FIXTURES)

import flhash  # noqa: E402
import gen_fixture as gf  # noqa: E402

INSTALL = os.environ.get("FLMOD_FIXTURE_INSTALL",
                         "/home/user/freelancer/prefix-dev-base-B/drive_c/Games/Freelancer HD Edition")
TSTAMP = (31284881, 3414609264)
SPECS = [os.path.splitext(os.path.basename(p))[0] for p in gf.list_specs()]
REQUIRED_SPECS = {"HARNESS_new_story", "HARNESS_endgame_eagle", "HARNESS_endgame_eagle_space",
                  "HARNESS_endgame_crete", "HARNESS_lvl1_rich_fp9", "HARNESS_ew06_space"}

needs_install = pytest.mark.skipif(not os.path.isdir(INSTALL), reason="dev baseline install not present: " + INSTALL)


# ---------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def inst():
    return gf.Install(INSTALL)


def render(tmp_path, spec, rule="hash"):
    out = tmp_path / "SinglePlayer"
    out.mkdir(exist_ok=True)
    res = gf.generate(INSTALL, spec, str(out), rule, TSTAMP)
    return res


def player_section(path):
    return next(s for s in gf.parse_ini(path) if s.lname == "player")


def section(path, lname):
    return [s for s in gf.parse_ini(path) if s.lname == lname]


def run_main(argv, capsys):
    rc = gf.main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def write_spec(tmp_path, name, body):
    p = tmp_path / ("%s.yaml" % name)
    p.write_text("name: %s\n%s" % (name, body), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------------------------------------------
# hashes
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("nick,value", [
    ("Li01_to_Li02", 2830511361),
    ("Ew06_01_Base", 3094908802),
    ("Li02", 2745692751),
    ("ew0601_monkey_003_m", 2318074572),
    ("Br05", 2945937410),
])
def test_create_id_golden(nick, value):
    assert flhash.create_id(nick) == value
    assert flhash.create_id(nick.upper()) == value   # CreateID lower-cases first


def test_make_id_and_location_id():
    assert flhash.make_id("li_n_grp") == 8778          # R3 §10 port value (consistency check)
    assert flhash.make_id("LI_N_GRP") == 8778
    assert flhash.create_id("li_n_grp") != flhash.make_id("li_n_grp")
    base = flhash.create_id("Li01_01_Base")
    assert flhash.make_location_id("Li01_01_Base", "Bar") == flhash.create_id("%X_Bar" % base)
    assert flhash.make_location_id(base, "bar") == flhash.make_location_id("li01_01_base", "Bar")


def test_wide_hex_roundtrip_and_name_rule():
    assert gf.wide_to_hex("HARNESS_x") == "".join("%04x" % ord(c) for c in "HARNESS_x")
    assert gf.hex_to_wide(gf.wide_to_hex("HARNESS_endgame_eagle")) == "HARNESS_endgame_eagle"
    assert gf.hex_to_wide("Trent") == "Trent"           # non-hex falls back to plain text, like HexToWide
    assert gf.save_file_name("HARNESS_endgame_eagle") == "%x.fl" % flhash.create_id("harness_endgame_eagle")


# ---------------------------------------------------------------------------------------------------------------
# every spec renders and has the required shape
# ---------------------------------------------------------------------------------------------------------------

def test_required_specs_present():
    assert REQUIRED_SPECS <= set(SPECS)


@needs_install
@pytest.mark.parametrize("name", SPECS)
def test_spec_renders(tmp_path, inst, name):
    spec = gf.load_spec(name)
    (path, info, _), = render(tmp_path, name)
    assert os.path.basename(path) == gf.save_file_name(name)
    data = open(path, "rb").read()
    # CRLF everywhere, nothing else.
    assert data.endswith(b"\r\n")
    assert data.count(b"\n") == data.count(b"\r\n") and data.count(b"\r") == data.count(b"\r\n")
    p = player_section(path)
    # description / name: lower-case hex of UTF-16BE.
    assert p.get("description") == name.encode("utf-16-be").hex()
    assert gf.hex_to_wide(p.get("name")) == spec.get("player_name", "HARNESS")
    for key in ("description", "tstamp", "name", "rank", "money", "system", "ship_archetype"):
        assert p.get(key) is not None, key
    assert p.get("tstamp") == "%u,%u" % TSTAMP
    assert p.get("system").lower() == spec["system"].lower()
    if spec.get("base"):
        assert p.get("base").lower() == spec["base"].lower()
        assert p.get("pos") is None and p.get("rotate") is None
        start, rooms = inst.base_rooms(p.get("base"))
        assert int(p.get("location")) == flhash.make_location_id(p.get("base"), start)
    else:
        assert p.get("base") is None and p.get("location") is None
        assert p.get("pos") is not None and p.get("rotate") is not None
    # validated content
    assert p.get("ship_archetype").lower() in inst.ships
    for v in p.values("equip") + p.values("cargo"):
        assert gf.csv(v)[0].lower() in inst.equipment
    for v in p.values("house"):
        assert gf.csv(v)[1].lower() in inst.factions
    secs = gf.parse_ini(path)
    names = [s.lname for s in secs]
    assert names.count("player") == 1 and names.count("storyinfo") == 1 and "mplayer" in names
    assert names.count("group") == len([s for s in gf.parse_ini(inst.initial_world_path) if s.lname == "group"])
    story = section(path, "storyinfo")[0]
    gates = [v for s in secs for v in s.values("locked_gate")]
    tmpl = gf.parse_ini(inst.template_path)
    if spec.get("post_campaign"):
        assert story.get("mission") == "Mission_13" and story.get("missionnum") == "42"
        assert gates == []
        assert section(path, "locked_gates")[0].values("npc_locked_gate")
        assert not set(names) & gf.MISSION_SECTIONS
    else:
        t_story = next(s for s in tmpl if s.lname == "storyinfo")
        assert story.get("mission") == t_story.get("mission")
        t_gates = [v for s in tmpl for v in s.values("locked_gate")]
        iw_gates = [v for s in gf.parse_ini(inst.initial_world_path) for v in s.values("locked_gate")]
        assert len(gates) == len(t_gates) + len(iw_gates)


@needs_install
def test_name_rule_both_and_determinism(tmp_path):
    res = render(tmp_path, "HARNESS_endgame_eagle", "both")
    files = sorted(os.path.basename(p) for p, _, _ in res)
    assert files == sorted([gf.save_file_name("HARNESS_endgame_eagle"), "HARNESS_endgame_eagle.fl"])
    a, b = (open(p, "rb").read() for p, _, _ in res)
    assert a == b
    again = render(tmp_path, "HARNESS_endgame_eagle", "hash")   # overwrite of our own fixture is allowed
    assert open(again[0][0], "rb").read() == a
    assert not os.path.exists(os.path.join(os.path.dirname(res[0][0]), "Restart.fl"))


# ---------------------------------------------------------------------------------------------------------------
# fixture semantics, checked against install data
# ---------------------------------------------------------------------------------------------------------------

@needs_install
def test_endgame_eagle_loadout(tmp_path, inst):
    (path, info, _), = render(tmp_path, "HARNESS_endgame_eagle")
    p = player_section(path)
    ship = inst.ships[p.get("ship_archetype").lower()]
    assert ship.nickname.lower() == "ge_fighter6"
    assert int(p.get("money")) == 60000000
    equip = [gf.csv(v) for v in p.values("equip")]
    by_hp = {e[1].lower(): e[0].lower() for e in equip if e[1]}
    # Nomad guns on every gun hardpoint that takes one; 01/02 wherever a class-10 Nomad gun fits.
    nomad = {n: inst.equipment[n] for n in ("special_nomad_gun01", "special_nomad_gun02", "special_nomad_gun03")}
    gun_hps = [hp for hp in ship.hp_order if any(t.startswith("hp_gun_special_") for t in ship.types_by_hp[hp.lower()])]
    assert gun_hps
    for hp in gun_hps:
        fits = [n for n, it in nomad.items() if it.hp_type in ship.types_by_hp[hp.lower()]]
        assert by_hp.get(hp.lower()) in fits, hp
        if {"special_nomad_gun01", "special_nomad_gun02"} & set(fits):
            assert by_hp[hp.lower()] in ("special_nomad_gun01", "special_nomad_gun02")
    assert {"special_nomad_gun01", "special_nomad_gun02"} <= set(by_hp.values())
    # The best class-10 shield that fits the shield hardpoint.
    shp = [hp for hp in ship.hp_order if any("shield" in t for t in ship.types_by_hp[hp.lower()])][0]
    allowed = ship.types_by_hp[shp.lower()]
    cands = [it for it in inst.equipment.values() if it.section == "shieldgenerator" and it.hp_type in allowed
             and it.hp_type.endswith("_special_10")]
    best = max(cands, key=lambda it: it.max_capacity)
    assert by_hp[shp.lower()] == best.nickname.lower()
    # Exactly one engine and one power plant, internal.
    internal = [inst.equipment[e[0].lower()].section for e in equip if not e[1]]
    assert internal.count("engine") == 1 and internal.count("power") == 1
    # Max bots and batteries (the ship's limits).
    cargo = {gf.csv(v)[0].lower(): int(gf.csv(v)[1]) for v in p.values("cargo")}
    assert cargo["ge_s_repair_01"] == ship.nanobot_limit > 0
    assert cargo["ge_s_battery_01"] == ship.shield_battery_limit > 0
    # Broadly friendly; Nomads and the possessed navies stay hostile.
    reps = {gf.csv(v)[1].lower(): float(gf.csv(v)[0]) for v in p.values("house")}
    hostile = {"fc_n_grp", "fc_ln_grp", "fc_kn_grp", "fc_rn_grp"}
    assert all(v >= 0.65 for k, v in reps.items() if k not in hostile)
    assert all(reps[k] < -0.6 for k in hostile)
    assert int(p.get("rank")) == 38


@needs_install
def test_post_campaign_applies_m13_reps(tmp_path, inst):
    (path, _, _), = render(tmp_path, "HARNESS_lvl1_rich_fp9")
    p = player_section(path)
    reps = {gf.csv(v)[1].lower(): float(gf.csv(v)[0]) for v in p.values("house")}
    owner_obj = [o for o in inst.system("Ew04")["objects"].values() if o.base == "ew04_01_base" and o.reputation]
    owner = owner_obj[0].reputation.lower()
    for g, v in inst.m13_reps():
        if g.lower() != owner:
            assert reps[g.lower()] == pytest.approx(v), g
    assert reps[owner] >= 0.6
    assert int(p.get("rank")) == 1 and int(p.get("money")) == 5000000
    assert p.get("base") == "Ew04_01_Base"


@needs_install
@pytest.mark.parametrize("name,near", [("HARNESS_endgame_eagle_space", "li01_01"),
                                       ("HARNESS_ew06_space", "ew06_to_hi02_hole")])
def test_space_positions_are_safe(tmp_path, inst, name, near):
    (path, info, _), = render(tmp_path, name)
    p = player_section(path)
    pos = gf.vec3(p.get("pos"), "pos")
    sysd = inst.system(p.get("system"))
    obj = sysd["objects"][near]
    spec = gf.load_spec(name)
    d = math.dist(pos, obj.pos)
    assert d > obj.atmosphere_range
    assert d < obj.atmosphere_range + 10000 + spec["pos"]["standoff"]    # still "near"
    for z in sysd["zones"]:
        if z.damage > 0 and z.shape == "sphere":
            assert math.dist(z.pos, pos) > z.size[0], z.nickname
    if name == "HARNESS_ew06_space":
        reps = {gf.csv(v)[1].lower(): float(gf.csv(v)[0]) for v in p.values("house")}
        assert reps["fc_n_grp"] <= -0.6


@needs_install
def test_new_story_keeps_template_story(tmp_path, inst):
    (path, _, _), = render(tmp_path, "HARNESS_new_story")
    p = player_section(path)
    t = next(s for s in gf.parse_ini(inst.template_path) if s.lname == "player")
    assert p.get("ship_archetype") == t.get("ship_archetype")
    assert int(p.get("rank")) == 1
    assert p.get("system") == "Li01" and p.get("base") == "Li01_01_Base"


@needs_install
def test_overrides_room_and_mission_num(tmp_path):
    spec = write_spec(tmp_path, "HARNESS_tmp_bar",
                      "extends: HARNESS_endgame_eagle\nroom: Bar\nmission_num: 41\n")
    (path, _, _), = gf.generate(INSTALL, spec, str(tmp_path / "o"), "plain", TSTAMP)
    assert os.path.basename(path) == "HARNESS_tmp_bar.fl"
    p = player_section(path)
    assert int(p.get("location")) == flhash.make_location_id("Li01_01_Base", "Bar")
    assert section(path, "storyinfo")[0].get("missionnum") == "41"
    assert p.get("ship_archetype") == "ge_fighter6"          # inherited from the parent spec


# ---------------------------------------------------------------------------------------------------------------
# validation errors: generator errors (exit 2), never a written file
# ---------------------------------------------------------------------------------------------------------------

BASE = "post_campaign: true\nsystem: Li01\nbase: Li01_01_Base\n"
EAGLE = ("ship:\n  archetype: ge_fighter6\n  base_loadout: package\n")


@needs_install
@pytest.mark.parametrize("body,needle", [
    (BASE + "ship: {archetype: no_such_ship}\n", "ship archetype"),
    (BASE + EAGLE + "cargo:\n  - {item: no_such_good, count: 1}\n", "unknown item"),
    (BASE + EAGLE + "  equip:\n    - {item: no_such_gun, hp: HpWeapon01}\n", "unknown item"),
    (BASE + EAGLE + "  equip:\n    - {item: special_nomad_gun01, hp: HpWeapon99}\n", "does not fit"),
    (BASE + EAGLE + "  equip:\n    - {item: special_nomad_gun01, hp: HpShield01}\n", "does not fit"),
    (BASE + EAGLE + "  equip:\n    - {item: ge_s_repair_01, hp: HpWeapon01}\n", "cargo, not mountable"),
    (BASE + EAGLE + "  equip:\n    - {item: special_nomad_gun01}\n", "needs a hardpoint"),
    (BASE + EAGLE + "cargo:\n  - {item: ge_s_repair_01, count: 100000}\n", "nanobot_limit"),
    ("post_campaign: true\nsystem: Li01\nbase: No_Such_Base\n", "unknown base"),
    ("post_campaign: true\nsystem: Li01\nbase: Ew04_01_Base\n", "is in system"),
    ("post_campaign: true\nsystem: No_Such_System\nbase: Li01_01_Base\n", "unknown system"),
    ("post_campaign: true\nbase: Li01_01_Base\n", "system: required"),
    ("post_campaign: true\nsystem: Li01\n", "exactly one of base"),
    (BASE + "room: No_Such_Room\n", "is not a [Room]"),
    (BASE + "reps: {no_such_grp: 0.5}\n", "unknown faction"),
    (BASE + "reps_default_min: 0.6\nreps_default_except: [no_such_grp]\n", "unknown faction"),
    (BASE + "reps: {li_n_grp: 3}\n", "out of -1..1"),
    ("post_campaign: true\nsystem: Li01\npos: {near: Li01_01, offset: [0, 0, 100]}\n", "inside"),
    ("post_campaign: true\nsystem: Li01\npos: {near: No_Such_Object, standoff: 100}\n", "no [Object]"),
    ("system: Li01\nbase: Li01_01_Base\n", "exactly one of post_campaign"),
    (BASE + "colour: blue\n", "unknown key"),
])
def test_validation_errors(tmp_path, capsys, body, needle):
    spec = write_spec(tmp_path, "HARNESS_bad", body)
    out = tmp_path / "out"
    rc, so, se = run_main(["--install", INSTALL, "--spec", spec, "--out", str(out), "--tstamp", "1,2"], capsys)
    assert rc == 2, se
    assert needle in se, se
    assert not list(out.glob("*.fl"))


@needs_install
def test_spec_name_must_match_file(tmp_path, capsys):
    p = tmp_path / "HARNESS_other.yaml"
    p.write_text("name: HARNESS_bad\n" + BASE, encoding="utf-8")
    rc, _, se = run_main(["--install", INSTALL, "--spec", str(p), "--out", str(tmp_path / "o")], capsys)
    assert rc == 2 and "file stem" in se


# ---------------------------------------------------------------------------------------------------------------
# path safety
# ---------------------------------------------------------------------------------------------------------------

@needs_install
def test_refuses_my_games(tmp_path, capsys):
    out = tmp_path / "Documents" / "My Games" / "Freelancer" / "Accts" / "SinglePlayer"
    rc, _, se = run_main(["--install", INSTALL, "--spec", "HARNESS_endgame_eagle", "--out", str(out)], capsys)
    assert rc == 3 and "My Games" in se
    assert not out.exists()


@needs_install
def test_refuses_play_prefix(tmp_path, capsys, monkeypatch):
    fake_play = tmp_path / "prefix"
    monkeypatch.setenv("FLMOD_PLAY_PREFIX", str(fake_play))
    out = fake_play / "drive_c" / "saves"
    rc, _, se = run_main(["--install", INSTALL, "--spec", "HARNESS_endgame_eagle", "--out", str(out)], capsys)
    assert rc == 3 and "play prefix" in se
    assert not out.exists()
    rc, _, se = run_main(["--install", str(fake_play), "--spec", "HARNESS_endgame_eagle",
                          "--out", str(tmp_path / "o")], capsys)
    assert rc == 3 and "play prefix" in se


@needs_install
def test_refuses_foreign_save(tmp_path, capsys):
    out = tmp_path / "SinglePlayer"
    out.mkdir()
    victim = out / gf.save_file_name("HARNESS_endgame_eagle")
    original = b"[Player]\r\ndescription = %s\r\n" % gf.wide_to_hex("A real save").encode()
    victim.write_bytes(original)
    rc, _, se = run_main(["--install", INSTALL, "--spec", "HARNESS_endgame_eagle", "--out", str(out)], capsys)
    assert rc == 3 and "not overwriting" in se
    assert victim.read_bytes() == original
    assert gf.existing_description(str(victim)) == "A real save"


def test_never_restart_fl(tmp_path):
    with pytest.raises(gf.RefusedPath):
        gf.write_fixture(str(tmp_path), "Restart.fl", "x\r\n", "HARNESS_x")


# ---------------------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------------------

def test_cli_list(capsys):
    rc, so, _ = run_main(["--list"], capsys)
    assert rc == 0
    for n in REQUIRED_SPECS:
        assert n in so


@needs_install
def test_cli_subprocess_isolated(tmp_path):
    out = tmp_path / "SinglePlayer"
    r = subprocess.run([sys.executable, "-I", os.path.join(FIXTURES, "gen_fixture.py"), "--install", INSTALL,
                        "--spec", "HARNESS_endgame_eagle", "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    line = r.stdout.strip().splitlines()[0]
    assert line.startswith("fixture=HARNESS_endgame_eagle file=")
    assert "description=HARNESS_endgame_eagle system=Li01 base=Li01_01_Base" in line
    assert (out / gf.save_file_name("HARNESS_endgame_eagle")).exists()
