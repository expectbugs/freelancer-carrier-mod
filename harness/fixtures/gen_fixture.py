#!/usr/bin/env python3
"""Fixture save generator (CONVENTIONS §6, TESTING §Fixtures, REQ-P0-HARNESS-16).

    gen_fixture.py --install <HDE dir> --spec <yaml path | fixture name> --out <savedir>
                   [--name-rule hash|plain|both] [--tstamp now|HI,LO]
    gen_fixture.py --install <HDE dir> --all --out <savedir>
    gen_fixture.py --list

Renders a committed YAML spec (nicknames + our own numbers only) into a plain-text CRLF `.fl` save. Everything that
comes from the game (template, loadouts, positions, rep tables, hardpoints) is read from the given install at
generation time and is never committed. Every nickname is validated against that install's DATA: an invalid fixture
is a generator error (exit 2), never a game crash. Path refusals exit 3. See README.md for the spec format.
"""
import argparse
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import flhash  # noqa: E402

try:
    import yaml  # noqa: E402
except ImportError:  # pragma: no cover
    sys.stderr.write("gen_fixture: ERROR: pyyaml is required ($FLMOD_VENV/bin/python -I)\n")
    sys.exit(1)

SPEC_DIR = os.path.join(HERE, "specs")
CRLF = "\r\n"
NAME_RE = re.compile(r"^HARNESS_[A-Za-z0-9_]{1,56}$")
CLASS_RE = re.compile(r"_special_(\d+)$")

# Design values for `post_campaign: true` (TESTING §Fixtures; R3 §7). MissionNum 42 = mission_end per Librelancer's
# storyline table; free-play validity in HDE is UNVERIFIED until W1-HARNESS loads the fixture in game.
POST_CAMPAIGN_MISSION = "Mission_13"
POST_CAMPAIGN_MISSION_NUM = 42
M13_FILE = "MISSIONS/M13/m13.ini"        # Content.dll StoryLauncher's hard-coded Mission_13 script (R3 §7)
M13_REP_TRIGGER = "enter_bar"             # the trigger that re-sets the player's reps at the end of the campaign
MISSION_SECTIONS = {"missionstate", "triggersave", "mission01asave", "mission01bsave", "bstorymissiondone",
                    "nnobjective", "randommission"}

# [Player] keys the generator writes itself; any other template key is carried over unchanged.
MANAGED_PLAYER_KEYS = {"description", "descrip_strid", "tstamp", "name", "rank", "money", "num_kills",
                       "num_misn_successes", "num_misn_failures", "system", "base", "last_base", "pos", "rotate",
                       "location", "ship_archetype", "hull_status", "collision_group", "equip", "cargo",
                       "base_equip", "base_cargo", "house", "rep_group", "visit", "wg", "starting_ring"}
TOP_KEYS = {"name", "extends", "summary", "post_campaign", "story_mode", "mission", "mission_num", "player_name",
            "rank", "money", "system", "base", "room", "pos", "rotate", "ship", "cargo", "reps",
            "reps_default_min", "reps_default_except", "reps_owner_min", "visit"}
SHIP_KEYS = {"archetype", "base_loadout", "shield", "guns", "turrets", "equip"}

# Equipment classes (INI section names, lower-case).
INTERNAL_SECTIONS = {"engine", "power", "scanner", "tractor", "armor", "cargopod", "internalfx"}
COSMETIC_SECTIONS = {"light", "attachedfx"}           # mounted on model hardpoints shiparch doesn't list
CARGO_ONLY_SECTIONS = {"munition", "commodity", "repairkit", "shieldbattery", "countermeasure", "mine",
                       "lootcrate", "explosion", "motor"}
# Classes whose hardpoint type is implied by the class (the data carries no hp_type for them).
IMPLIED_HP_TYPE = {"countermeasuredropper": "hp_countermeasure_dropper", "minedropper": "hp_mine_dropper",
                   "thruster": "hp_thruster"}


class FixtureError(Exception):
    """Spec or validation error(s): exit 2."""

    def __init__(self, errors):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


class RefusedPath(Exception):
    """A safety refusal (play prefix, My Games, ~/.wine, foreign save): exit 3."""


# --------------------------------------------------------------------------------------------------------------------
# Paths and INI reading
# --------------------------------------------------------------------------------------------------------------------

def ci_path(root, rel):
    """Resolve `rel` (\\ or / separated) under `root` case-insensitively (FL data is mixed-case). None if missing."""
    if root is None:
        return None
    cur = root
    for part in re.split(r"[\\/]+", rel.strip()):
        if part in ("", "."):
            continue
        if part == "..":
            cur = os.path.dirname(cur)
            continue
        cand = os.path.join(cur, part)
        if os.path.exists(cand):
            cur = cand
            continue
        try:
            names = os.listdir(cur)
        except OSError:
            return None
        hits = sorted(n for n in names if n.lower() == part.lower())
        if not hits:
            return None
        cur = os.path.join(cur, hits[0])
    return cur


def read_text(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"BINI":
        raise FixtureError("%s: binary (BINI) INI is not supported" % path)
    if data[:4] in (b"FLS1", b"FLSG"):
        raise FixtureError("%s: encrypted save/template (%s) is not supported" % (path, data[:4].decode()))
    return data.decode("latin-1")


def strip_comment(line):
    i = line.find(";")
    return line if i < 0 else line[:i]


class Section:
    __slots__ = ("name", "lname", "entries", "src")

    def __init__(self, name, src):
        self.name = name
        self.lname = name.lower()
        self.entries = []          # (key_lower, key, value)
        self.src = src

    def values(self, key):
        return [v for k, _, v in self.entries if k == key]

    def get(self, key, default=None):
        for k, _, v in self.entries:
            if k == key:
                return v
        return default


def parse_ini(path):
    """FL text INI: [Section] headers, `key = value`, `;` comments, repeated sections and keys, case-insensitive."""
    sections, cur = [], None
    for raw in read_text(path).splitlines():
        line = strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("["):
            end = line.find("]")
            cur = Section((line[1:end] if end > 0 else line[1:]).strip(), path)
            sections.append(cur)
            continue
        if cur is None:
            continue
        key, _, value = line.partition("=")
        cur.entries.append((key.strip().lower(), key.strip(), value.strip()))
    return sections


def csv(value):
    return [p.strip() for p in value.split(",")]


def to_float(text, what):
    try:
        return float(text)
    except (TypeError, ValueError):
        raise FixtureError("%s: not a number: %r" % (what, text))


def vec3(text, what):
    parts = csv(text)
    if len(parts) < 3:
        raise FixtureError("%s: expected x, y, z: %r" % (what, text))
    return tuple(to_float(p, what) for p in parts[:3])


# --------------------------------------------------------------------------------------------------------------------
# Install data (read lazily, at generation time)
# --------------------------------------------------------------------------------------------------------------------

class Item:
    __slots__ = ("nickname", "section", "hp_type", "max_capacity", "volume", "src")


class Ship:
    __slots__ = ("nickname", "hp_by_type", "types_by_hp", "hp_canon", "hp_order", "nanobot_limit",
                 "shield_battery_limit", "hold_size", "src")


class Obj:
    __slots__ = ("nickname", "pos", "atmosphere_range", "base", "reputation")


class Zone:
    __slots__ = ("nickname", "shape", "size", "pos", "damage")


class Install:
    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.exe_dir = ci_path(self.root, "EXE")
        if self.exe_dir is None:
            raise FixtureError("install %s: no EXE directory" % self.root)
        fl_ini = ci_path(self.exe_dir, "freelancer.ini")
        if fl_ini is None:
            raise FixtureError("install %s: no EXE/freelancer.ini" % self.root)
        secs = parse_ini(fl_ini)
        fl = next((s for s in secs if s.lname == "freelancer"), None)
        self.data_dir = ci_path(self.exe_dir, fl.get("data path", r"..\data") if fl else r"..\data")
        if self.data_dir is None:
            raise FixtureError("install %s: DATA directory not found" % self.root)
        self.initial_world_rel = fl.get("initial_world", "initialworld.ini") if fl else "initialworld.ini"
        self.data_files = {}
        for s in secs:
            if s.lname == "data":
                for k, _, v in s.entries:
                    self.data_files.setdefault(k, []).append(v)
        self.template_path = ci_path(self.exe_dir, "newplayer.fl")
        if self.template_path is None:
            raise FixtureError("install %s: no EXE/newplayer.fl template" % self.root)
        self._cache = {}

    def data_path(self, rel):
        p = ci_path(self.data_dir, rel)
        if p is None:
            raise FixtureError("install: missing DATA file %s" % rel)
        return p

    def _data_list(self, key):
        rels = self.data_files.get(key, [])
        if not rels:
            raise FixtureError("install: freelancer.ini [Data] has no '%s =' entries" % key)
        return [self.data_path(r) for r in rels]

    def cached(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    # -- equipment ------------------------------------------------------------------------------------------------
    @property
    def equipment(self):
        return self.cached("equipment", self._load_equipment)

    def _load_equipment(self):
        items = {}
        for path in self._data_list("equipment"):
            for s in parse_ini(path):
                nick = s.get("nickname")
                if not nick:
                    continue
                it = Item()
                it.nickname, it.section, it.src = nick, s.lname, path
                hp = s.get("hp_gun_type") if s.lname == "gun" else None
                if hp is None and s.lname == "shieldgenerator":
                    hp = s.get("hp_type")
                if hp is None:
                    hp = IMPLIED_HP_TYPE.get(s.lname)
                it.hp_type = hp.lower() if hp else None
                cap = s.get("max_capacity")
                it.max_capacity = to_float(cap, "%s max_capacity" % nick) if cap else 0.0
                vol = s.get("volume")
                it.volume = to_float(vol, "%s volume" % nick) if vol else 0.0
                items.setdefault(nick.lower(), it)
        return items

    # -- ships ----------------------------------------------------------------------------------------------------
    @property
    def ships(self):
        return self.cached("ships", self._load_ships)

    def _load_ships(self):
        ships = {}
        for path in self._data_list("ships"):
            for s in parse_ini(path):
                nick = s.get("nickname")
                if s.lname != "ship" or not nick:
                    continue
                sh = Ship()
                sh.nickname, sh.src = nick, path
                sh.hp_by_type, sh.types_by_hp, sh.hp_canon, sh.hp_order = {}, {}, {}, []
                for v in s.values("hp_type"):
                    parts = [p for p in csv(v) if p]
                    if not parts:
                        continue
                    t = parts[0].lower()
                    for hp in parts[1:]:
                        sh.hp_by_type.setdefault(t, []).append(hp)
                        sh.types_by_hp.setdefault(hp.lower(), set()).add(t)
                        if hp.lower() not in sh.hp_canon:
                            sh.hp_canon[hp.lower()] = hp
                            sh.hp_order.append(hp)
                sh.nanobot_limit = int(to_float(s.get("nanobot_limit", "0"), nick + " nanobot_limit"))
                sh.shield_battery_limit = int(to_float(s.get("shield_battery_limit", "0"),
                                                       nick + " shield_battery_limit"))
                sh.hold_size = to_float(s.get("hold_size", "0"), nick + " hold_size")
                ships.setdefault(nick.lower(), sh)
        return ships

    # -- goods: ship packages -------------------------------------------------------------------------------------
    @property
    def packages(self):
        """ship lower -> list of (package nickname, [(item, hp-or-'', count)]) incl. the hull good's addons."""
        return self.cached("packages", self._load_packages)

    def _load_packages(self):
        hulls, pkgs = {}, {}
        for path in self._data_list("goods"):
            for s in parse_ini(path):
                cat = (s.get("category") or "").lower()
                nick = s.get("nickname")
                if s.lname != "good" or not nick:
                    continue
                if cat == "shiphull" and s.get("ship"):
                    hulls[nick.lower()] = (s.get("ship").lower(), self._addons(s))
                elif cat == "ship" and s.get("hull"):
                    pkgs.setdefault(s.get("hull").lower(), []).append((nick, self._addons(s)))
        out = {}
        for hull, (ship, hull_addons) in hulls.items():
            for pkg_nick, addons in pkgs.get(hull, []):
                out.setdefault(ship, []).append((pkg_nick, hull_addons + addons))
        return out

    @staticmethod
    def _addons(section):
        res = []
        for v in section.values("addon"):
            p = csv(v)
            hp = p[1] if len(p) > 1 else ""
            hp = "" if hp.lower() == "internal" else hp
            count = int(to_float(p[2], "addon count")) if len(p) > 2 and p[2] else 1
            res.append((p[0], hp, count))
        return res

    def loadout(self, nick):
        def load():
            res = {}
            for path in self._data_list("loadouts"):
                for s in parse_ini(path):
                    n = s.get("nickname")
                    if s.lname == "loadout" and n:
                        res.setdefault(n.lower(), s)
            return res
        return self.cached("loadouts", load).get(nick.lower())

    # -- universe -------------------------------------------------------------------------------------------------
    @property
    def universe(self):
        return self.cached("universe", self._load_universe)

    def _load_universe(self):
        rels = self.data_files.get("universe") or [r"universe\universe.ini"]
        path = self.data_path(rels[0])
        systems, bases = {}, {}
        for s in parse_ini(path):
            nick = s.get("nickname")
            if not nick:
                continue
            if s.lname == "system":
                systems.setdefault(nick.lower(), {"nickname": nick, "file": s.get("file")})
            elif s.lname == "base":
                bases.setdefault(nick.lower(), {"nickname": nick, "system": s.get("system"), "file": s.get("file")})
        return {"path": path, "dir": os.path.dirname(path), "systems": systems, "bases": bases}

    def _universe_file(self, rel):
        # System files are relative to UNIVERSE/, base files to DATA/; accept either.
        return ci_path(self.universe["dir"], rel) or ci_path(self.data_dir, rel)

    def system(self, nick):
        return self.cached("system:" + nick.lower(), lambda: self._load_system(nick))

    def _load_system(self, nick):
        info = self.universe["systems"][nick.lower()]
        path = self._universe_file(info["file"] or "")
        if path is None:
            raise FixtureError("system %s: file %s not found" % (info["nickname"], info["file"]))
        objects, zones = {}, []
        for s in parse_ini(path):
            n = s.get("nickname")
            if not n:
                continue
            if s.lname == "object":
                o = Obj()
                o.nickname = n
                o.pos = vec3(s.get("pos", "0, 0, 0"), "%s pos" % n)
                ar = s.get("atmosphere_range")
                o.atmosphere_range = to_float(ar, "%s atmosphere_range" % n) if ar else 0.0
                o.base = (s.get("base") or "").lower() or None
                o.reputation = s.get("reputation")
                objects.setdefault(n.lower(), o)
            elif s.lname == "zone":
                z = Zone()
                z.nickname, z.shape = n, (s.get("shape") or "sphere").lower()
                z.size = tuple(to_float(p, "%s size" % n) for p in csv(s.get("size", "0")) if p)
                z.pos = vec3(s.get("pos", "0, 0, 0"), "%s pos" % n)
                dmg = s.get("damage")
                z.damage = to_float(dmg, "%s damage" % n) if dmg else 0.0
                zones.append(z)
        return {"nickname": info["nickname"], "path": path, "objects": objects, "zones": zones}

    def base_rooms(self, nick):
        def load():
            info = self.universe["bases"][nick.lower()]
            path = self._universe_file(info["file"] or "")
            if path is None:
                raise FixtureError("base %s: file %s not found" % (info["nickname"], info["file"]))
            start, rooms = None, {}
            for s in parse_ini(path):
                if s.lname == "baseinfo":
                    start = s.get("start_room")
                elif s.lname == "room" and s.get("nickname"):
                    rooms.setdefault(s.get("nickname").lower(), s.get("nickname"))
            return start, rooms
        return self.cached("rooms:" + nick.lower(), load)

    # -- factions, initial world, M13 -----------------------------------------------------------------------------
    @property
    def initial_world_path(self):
        return self.data_path(self.initial_world_rel)

    @property
    def factions(self):
        def load():
            return {s.get("nickname").lower(): s.get("nickname") for s in parse_ini(self.initial_world_path)
                    if s.lname == "group" and s.get("nickname")}
        return self.cached("factions", load)

    def m13_reps(self):
        """[(group, value)] from the Act_SetRep lines of M13's enter_bar trigger, in file order."""
        def load():
            path = self.data_path(M13_FILE)
            trig = [s for s in parse_ini(path) if s.lname == "trigger"
                    and (s.get("nickname") or "").lower() == M13_REP_TRIGGER]
            if not trig:
                raise FixtureError("%s: no [Trigger] nickname = %s" % (path, M13_REP_TRIGGER))
            reps = []
            for v in trig[0].values("act_setrep"):
                p = csv(v)
                if len(p) < 3 or p[0].lower() != "player":
                    continue
                reps.append((p[1], to_float(p[2], "%s Act_SetRep %s" % (M13_REP_TRIGGER, p[1]))))
            if not reps:
                raise FixtureError("%s: trigger %s has no Act_SetRep = Player, ... lines" % (path, M13_REP_TRIGGER))
            return reps
        return self.cached("m13", load)


# --------------------------------------------------------------------------------------------------------------------
# Raw template (.fl) handling
# --------------------------------------------------------------------------------------------------------------------

class RawSection:
    __slots__ = ("header", "lname", "lines")

    def __init__(self, header, lname):
        self.header, self.lname, self.lines = header, lname, []


def parse_raw(text):
    """Split an .fl/.ini text into sections keeping every line verbatim (line endings removed)."""
    out = [RawSection(None, None)]
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            end = s.find("]")
            out.append(RawSection(line, (s[1:end] if end > 0 else s[1:]).strip().lower()))
        else:
            out[-1].lines.append(line)
    return out


def raw_kv(line):
    s = strip_comment(line).strip()
    if not s or "=" not in s:
        return None, None
    k, _, v = s.partition("=")
    return k.strip().lower(), v.strip()


# --------------------------------------------------------------------------------------------------------------------
# Specs
# --------------------------------------------------------------------------------------------------------------------

def spec_path_for(arg):
    if os.path.isfile(arg):
        return os.path.realpath(arg)
    name = arg if arg.startswith("HARNESS_") else "HARNESS_" + arg
    path = os.path.join(SPEC_DIR, name + ".yaml")
    if not os.path.isfile(path):
        raise FixtureError("no spec file %r and no fixture named %s in %s" % (arg, name, SPEC_DIR))
    return path


def load_spec(arg, _seen=None):
    """Load a spec; `extends: <fixture name>` is a shallow merge (this spec's top-level keys replace the parent's)."""
    path = spec_path_for(arg)
    seen = _seen or []
    if path in seen:
        raise FixtureError("spec extends cycle: %s" % " -> ".join(seen + [path]))
    with open(path, "r", encoding="utf-8") as f:
        try:
            spec = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise FixtureError("%s: YAML error: %s" % (path, e))
    if not isinstance(spec, dict):
        raise FixtureError("%s: spec must be a mapping" % path)
    unknown = sorted(set(spec) - TOP_KEYS)
    if unknown:
        raise FixtureError("%s: unknown key(s): %s" % (path, ", ".join(unknown)))
    stem = os.path.splitext(os.path.basename(path))[0]
    if spec.get("name") != stem:
        raise FixtureError("%s: name must equal the file stem %r (got %r)" % (path, stem, spec.get("name")))
    if spec.get("extends"):
        parent = load_spec(spec["extends"], seen + [path])
        merged = {k: v for k, v in parent.items() if k not in ("name", "extends", "summary", "_path")}
        merged.update(spec)
        spec = merged
    spec["_path"] = path
    return spec


def list_specs():
    if not os.path.isdir(SPEC_DIR):
        return []
    return sorted(os.path.join(SPEC_DIR, n) for n in os.listdir(SPEC_DIR) if n.endswith(".yaml"))


# --------------------------------------------------------------------------------------------------------------------
# Encoding helpers (VERIFIED against reference sources, see harness/NOTES.md N12)
# --------------------------------------------------------------------------------------------------------------------

def wide_to_hex(text):
    """Common.dll WideToHex: "%04x" per UTF-16 code unit (= lower-case hex of UTF-16BE)."""
    return text.encode("utf-16-be").hex()


def hex_to_wide(text):
    """Common.dll HexToWide: all-hex -> 4 digits per code unit; otherwise the plain (multibyte) text."""
    t = text.strip()
    if t and all(c in "0123456789abcdefABCDEF" for c in t):
        return "".join(chr(int(t[i:i + 4], 16)) for i in range(0, len(t) - len(t) % 4, 4))
    return t


def save_file_name(description):
    """adoxa console fl_name(): sprintf("%x.fl", CreateIDW(desc)); CreateIDW = wcstombs + CreateID (lower-cases)."""
    return "%x.fl" % flhash.create_id(description.encode("ascii"))


def filetime_now():
    """FILETIME of local time, as FL's writer does (GetLocalTime -> SystemTimeToFileTime): (high, low)."""
    now = time.time()
    local = now + time.localtime(now).tm_gmtoff
    ft = int((local + 11644473600) * 10_000_000)
    return (ft >> 32) & 0xFFFFFFFF, ft & 0xFFFFFFFF


def fmt_num(v):
    return ("%d" % round(v)) if abs(v - round(v)) < 1e-6 else ("%.2f" % v)


def fmt_rep(v):
    return "%g" % v


# --------------------------------------------------------------------------------------------------------------------
# Fixture builder
# --------------------------------------------------------------------------------------------------------------------

class Builder:
    def __init__(self, inst, spec):
        self.inst, self.spec = inst, spec
        self.errors, self.warnings = [], []
        self.where = os.path.basename(spec.get("_path", "?"))
        self.notes = {}   # what the generator resolved from the install (shield, package, owner, near); for tests/logs

    def err(self, msg):
        self.errors.append("%s: %s" % (self.where, msg))

    def warn(self, msg):
        self.warnings.append("%s: %s" % (self.where, msg))

    # -- small resolvers ------------------------------------------------------------------------------------------
    def faction(self, nick, what):
        canon = self.inst.factions.get(str(nick).lower())
        if canon is None:
            self.err("%s: unknown faction %r (not a [Group] in %s)" % (what, nick, self.inst.initial_world_rel))
        return canon

    def item(self, nick, what):
        it = self.inst.equipment.get(str(nick).lower())
        if it is None:
            self.err("%s: unknown item %r (not in the [Data] equipment INIs)" % (what, nick))
        return it

    # -- main -----------------------------------------------------------------------------------------------------
    def build(self, tstamp):
        spec, inst = self.spec, self.inst
        desc = spec["name"]
        if not NAME_RE.match(desc):
            raise FixtureError("%s: name %r must match %s" % (self.where, desc, NAME_RE.pattern))
        post, story = bool(spec.get("post_campaign")), bool(spec.get("story_mode"))
        if post == story:
            raise FixtureError("%s: set exactly one of post_campaign: true / story_mode: true" % self.where)

        tmpl = parse_raw(read_text(inst.template_path))
        player = next((s for s in tmpl if s.lname == "player"), None)
        if player is None:
            raise FixtureError("%s: template has no [Player] section" % inst.template_path)

        # Template [Player]: carry-over lines, house table, ship, money/rank.
        carry, houses, t_equip, t_cargo, t = [], [], [], [], {}
        for line in player.lines:
            k, v = raw_kv(line)
            if k is None:
                continue
            if k == "house":
                p = csv(v)
                houses.append((p[1] if len(p) > 1 else "", to_float(p[0], "template house")))
            elif k == "equip":
                p = csv(v)
                t_equip.append((p[0], p[1] if len(p) > 1 else ""))
            elif k == "cargo":
                p = csv(v)
                t_cargo.append((p[0], int(to_float(p[1], "template cargo count")) if len(p) > 1 and p[1] else 1))
            elif k in MANAGED_PLAYER_KEYS:
                t.setdefault(k, v)
            else:
                carry.append(strip_comment(line).strip())

        rank = self.int_field("rank", t.get("rank", "0"), 0, 1000)
        money = self.int_field("money", t.get("money", "0"), 0, 2 ** 31 - 1)
        player_name = str(spec.get("player_name", "HARNESS"))
        self.mission_num = self.int_field("mission_num", POST_CAMPAIGN_MISSION_NUM, 0, 1000)

        reps = self.resolve_reps(houses, post)
        where_lines, where_info = self.resolve_location()
        ship, equip, cargo = self.resolve_ship(t.get("ship_archetype"), t_equip, t_cargo)
        visits = self.resolve_visits()
        if self.errors:
            raise FixtureError(self.errors)

        hi, lo = tstamp
        out = ["[Player]",
               "description = %s" % wide_to_hex(desc),
               "tstamp = %u,%u" % (hi, lo),
               "name = %s" % wide_to_hex(player_name),
               "rank = %d" % rank]
        out += ["house = %s, %s" % (fmt_rep(v), g) for g, v in reps]
        out += ["money = %d" % money, "num_kills = 0", "num_misn_successes = 0", "num_misn_failures = 0", ""]
        out += carry_head(carry) + [""]
        out += where_lines
        out += ["ship_archetype = %s" % ship.nickname]
        out += ["equip = %s, %s, 1" % (i, hp) for i, hp in equip]
        out += ["cargo = %s, %d, , , 0" % (i, n) for i, n in cargo]
        out += ["visit = %u, %d" % (h, f) for h, f in visits]
        out += carry_tail(carry) + [""]

        for sec in tmpl:
            if sec is player or sec.header is None:
                continue
            if post and sec.lname in MISSION_SECTIONS:
                continue
            out.append(sec.header.strip())
            if sec.lname == "storyinfo":
                out += self.story_lines(sec.lines, post)
            elif sec.lname == "mplayer" and post:
                out += [ln for ln in sec.lines if raw_kv(ln)[0] != "locked_gate"]
            else:
                out += sec.lines
        if not any(s.lname == "storyinfo" for s in tmpl):
            out += ["[StoryInfo]"] + self.story_lines([], post)

        # Append the initial world exactly as the game builds Restart.fl (NewPlayer.fl + initialworld.ini),
        # minus the player gate locks when post-campaign (every one is unlocked by the story / HDE Open SP).
        for sec in parse_raw(read_text(inst.initial_world_path)):
            if sec.header is not None:
                out.append(sec.header.strip())
            for ln in sec.lines:
                if post and sec.lname == "locked_gates" and raw_kv(ln)[0] == "locked_gate":
                    continue
                out.append(ln.rstrip())
        text = CRLF.join(out).rstrip("\r\n") + CRLF
        info = dict(where_info, fixture=desc, description=desc, ship=ship.nickname, notes=dict(self.notes))
        return text, info

    def int_field(self, key, default, lo, hi):
        v = self.spec.get(key, default)
        try:
            n = int(v)
        except (TypeError, ValueError):
            self.err("%s: not an integer: %r" % (key, v))
            return lo
        if not lo <= n <= hi:
            self.err("%s: %d out of range %d..%d" % (key, n, lo, hi))
        return n

    def story_lines(self, lines, post):
        if not post:
            return list(lines)
        mission = str(self.spec.get("mission", POST_CAMPAIGN_MISSION))
        new = {"mission": "Mission = %s" % mission, "missionnum": "MissionNum = %d" % self.mission_num}
        res, seen = [], set()
        for ln in lines:
            k = raw_kv(ln)[0]
            if k in new:
                seen.add(k)
                ln = new[k]
            res.append(ln)
        missing = [new[k] for k in ("mission", "missionnum") if k not in seen]
        return missing + res

    # -- reputations ----------------------------------------------------------------------------------------------
    def resolve_reps(self, houses, post):
        spec = self.spec
        table, order = {}, []

        def put(group, value, what):
            canon = self.faction(group, what)
            if canon is None:
                return
            if not -1.0 <= float(value) <= 1.0:
                self.err("%s: rep %r for %s out of -1..1" % (what, value, canon))
            if canon.lower() not in table:
                order.append(canon.lower())
            table[canon.lower()] = [canon, float(value)]

        for g, v in houses:
            put(g, v, "template house")
        if post:
            for g, v in self.inst.m13_reps():
                put(g, v, "%s %s Act_SetRep" % (M13_FILE, M13_REP_TRIGGER))
        floor = spec.get("reps_default_min")
        if floor is not None:
            floor = to_float(floor, "reps_default_min")
            keep = {(self.faction(g, "reps_default_except") or "").lower()
                    for g in spec.get("reps_default_except") or []}
            for key in order:
                if key not in keep and table[key][1] < floor:
                    table[key][1] = floor
        for entry in spec.get("reps_owner_min", []) or []:
            if not isinstance(entry, dict) or "base" not in entry or "min" not in entry:
                self.err("reps_owner_min entries are {base: <base>, min: <rep>}: %r" % (entry,))
                continue
            owner = self.base_owner(entry["base"])
            if owner:
                cur = table.get(owner.lower(), [owner, -1.0])[1]
                put(owner, max(cur, to_float(entry["min"], "reps_owner_min")), "reps_owner_min %s" % entry["base"])
        explicit = spec.get("reps") or {}
        if not isinstance(explicit, dict):
            self.err("reps: expected a mapping {<faction>: <rep>}")
            explicit = {}
        for g, v in explicit.items():
            put(g, to_float(v, "reps %s" % g), "reps")
        return [(table[k][0], table[k][1]) for k in order]

    def base_owner(self, base):
        b = self.inst.universe["bases"].get(str(base).lower())
        if b is None:
            self.err("reps_owner_min: unknown base %r" % base)
            return None
        if b["system"] is None or b["system"].lower() not in self.inst.universe["systems"]:
            self.err("base %s: unknown system %r" % (b["nickname"], b["system"]))
            return None
        objs = [o for o in self.inst.system(b["system"])["objects"].values()
                if o.base == b["nickname"].lower() and o.reputation]
        if not objs:
            self.err("base %s: no object with base = %s and a reputation in %s" % (base, base, b["system"]))
            return None
        owner = self.faction(objs[0].reputation, "base %s owner" % b["nickname"])
        if owner:
            self.notes["owner"] = "%s=%s" % (b["nickname"], owner)
        return owner

    # -- system / base / position ---------------------------------------------------------------------------------
    def resolve_location(self):
        spec, uni = self.spec, self.inst.universe
        sysname = spec.get("system")
        if not sysname:
            self.err("system: required (never rely on newplayer.fl's FP7 start)")
            return [], {}
        sysinfo = uni["systems"].get(str(sysname).lower())
        if sysinfo is None:
            self.err("system: unknown system %r (not in universe.ini)" % sysname)
            return [], {}
        system = sysinfo["nickname"]
        has_base, has_pos = spec.get("base") is not None, spec.get("pos") is not None
        if has_base == has_pos:
            self.err("set exactly one of base: (docked) or pos: (in space)")
            return [], {}
        lines = ["system = %s" % system]
        if has_base:
            b = uni["bases"].get(str(spec["base"]).lower())
            if b is None:
                self.err("base: unknown base %r (not in universe.ini)" % spec["base"])
                return [], {}
            if (b["system"] or "").lower() != system.lower():
                self.err("base %s is in system %s, not %s" % (b["nickname"], b["system"], system))
                return [], {}
            lines.append("base = %s" % b["nickname"])
            room = spec.get("room", "start_room")
            if room is not None and str(room).lower() != "none":
                start, rooms = self.inst.base_rooms(b["nickname"])
                want = start if str(room).lower() == "start_room" else str(room)
                if not want or want.lower() not in rooms:
                    self.err("room: %r is not a [Room] of %s (rooms: %s)" % (want, b["nickname"],
                                                                             ", ".join(sorted(rooms.values()))))
                else:
                    lines.append("location = %u" % flhash.make_location_id(b["nickname"], rooms[want.lower()]))
            return lines, {"system": system, "base": b["nickname"]}
        pos = self.resolve_pos(system, spec["pos"])
        if pos is None:
            return [], {}
        rot = spec.get("rotate", [0, 0, 0])
        if not (isinstance(rot, list) and len(rot) == 3 and all(isinstance(x, (int, float)) for x in rot)):
            self.err("rotate: expected [x, y, z] degrees, got %r" % (rot,))
            rot = [0, 0, 0]
        lines += ["pos = %s" % ", ".join(fmt_num(c) for c in pos),
                  "rotate = %s" % ", ".join(fmt_num(float(c)) for c in rot)]
        return lines, {"system": system, "pos": ",".join(fmt_num(c) for c in pos)}

    def resolve_pos(self, system, p):
        if not isinstance(p, dict) or "near" not in p:
            self.err("pos: expected {near: <object>, standoff: <m>, direction: [x,y,z]} or {near:, offset: [x,y,z]}")
            return None
        sysd = self.inst.system(system)
        obj = sysd["objects"].get(str(p["near"]).lower())
        if obj is None:
            self.err("pos.near: no [Object] %r in %s" % (p["near"], sysd["path"]))
            return None
        zones = [z for z in sysd["zones"] if z.damage > 0]
        if "offset" in p:
            off = self.vec(p["offset"], "pos.offset")
            if off is None:
                return None
            pos = tuple(a + b for a, b in zip(obj.pos, off))
        elif "standoff" in p:
            d = self.vec(p.get("direction", [0, 0, 1]), "pos.direction")
            if d is None:
                return None
            n = math.sqrt(sum(c * c for c in d))
            if n == 0:
                self.err("pos.direction must not be zero")
                return None
            clear = obj.atmosphere_range
            for z in zones:
                if z.shape == "sphere" and z.size:
                    dist = math.dist(z.pos, obj.pos)
                    if dist < z.size[0]:
                        clear = max(clear, dist + z.size[0])
            r = clear + to_float(p["standoff"], "pos.standoff")
            pos = tuple(a + c / n * r for a, c in zip(obj.pos, d))
        else:
            self.err("pos: needs offset: or standoff:")
            return None
        # Safety: never inside an atmosphere or a damage zone (conservative bounding sphere for non-spheres).
        for o in sysd["objects"].values():
            if o.atmosphere_range and math.dist(o.pos, pos) < o.atmosphere_range:
                self.err("pos is inside the atmosphere of %s" % o.nickname)
        for z in zones:
            if not z.size:
                continue
            bound = z.size[0] if z.shape == "sphere" else math.sqrt(sum(s * s for s in z.size))
            if math.dist(z.pos, pos) < bound:
                self.err("pos is inside damage zone %s (%s%s)" % (z.nickname, z.shape,
                                                                  "" if z.shape == "sphere" else ", bounding sphere"))
        self.notes["near"] = obj.nickname
        return pos

    def vec(self, v, what):
        if isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
            return tuple(float(x) for x in v)
        self.err("%s: expected [x, y, z] numbers, got %r" % (what, v))
        return None

    # -- ship, equipment, cargo -----------------------------------------------------------------------------------
    def resolve_ship(self, t_ship, t_equip, t_cargo):
        spec_ship = self.spec.get("ship", "template")
        if isinstance(spec_ship, str):
            spec_ship = {"archetype": spec_ship}
        if not isinstance(spec_ship, dict):
            self.err("ship: expected a mapping or 'template'")
            spec_ship = {"archetype": "template"}
        unknown = sorted(set(spec_ship) - SHIP_KEYS)
        if unknown:
            self.err("ship: unknown key(s): %s" % ", ".join(unknown))
        arch = str(spec_ship.get("archetype", "template"))
        from_template = arch.lower() == "template"
        if from_template:
            arch = t_ship or ""
        ship = self.inst.ships.get(arch.lower())
        if ship is None:
            raise FixtureError(self.errors + ["%s: ship archetype %r not in the [Data] ships INIs (shiparch)"
                                              % (self.where, arch)])
        base_lo = str(spec_ship.get("base_loadout", "template" if from_template else "package"))
        equip, cargo, trusted_hps = [], [], set()
        pkgs = self.inst.packages.get(ship.nickname.lower(), [])
        for _, addons in pkgs[:1]:
            trusted_hps |= {hp.lower() for _, hp, _ in addons if hp}
        if base_lo == "template":
            if not from_template:
                self.err("ship.base_loadout: template needs ship.archetype: template")
            equip = [[i, hp] for i, hp in t_equip]
            cargo = [[i, n] for i, n in t_cargo]
            trusted_hps |= {hp.lower() for _, hp in t_equip if hp}
        elif base_lo == "package":
            if not pkgs:
                self.err("ship %s: no ship package in the goods INIs; use base_loadout: none or loadout:<nick>"
                         % ship.nickname)
            else:
                self.notes["package"] = pkgs[0][0]
                for i, hp, n in pkgs[0][1]:
                    it = self.inst.equipment.get(i.lower())
                    if it is not None and it.section in CARGO_ONLY_SECTIONS and not hp:
                        cargo.append([i, n])
                    else:
                        equip.append([i, hp])
        elif base_lo.lower().startswith("loadout:"):
            lo = self.inst.loadout(base_lo.split(":", 1)[1].strip())
            if lo is None:
                self.err("ship.base_loadout: no [Loadout] %r" % base_lo)
            else:
                for v in lo.values("equip"):
                    p = csv(v)
                    equip.append([p[0], p[1] if len(p) > 1 else ""])
                    if len(p) > 1 and p[1]:
                        trusted_hps.add(p[1].lower())
                for v in lo.values("cargo"):
                    p = csv(v)
                    cargo.append([p[0], int(to_float(p[1], "loadout cargo")) if len(p) > 1 and p[1] else 1])
        elif base_lo != "none":
            self.err("ship.base_loadout: %r (expected package | template | none | loadout:<nickname>)" % base_lo)

        for e in spec_ship.get("equip", []) or []:
            if not isinstance(e, dict) or "item" not in e:
                self.err("ship.equip entries are {item: <nick>, hp: <hardpoint>}: %r" % (e,))
                continue
            self.mount(equip, str(e["item"]), str(e.get("hp") or ""))
        if spec_ship.get("shield") is not None:
            self.fit_shield(ship, equip, spec_ship["shield"])
        for key, kind in (("guns", "hp_gun_special_"), ("turrets", "hp_turret_special_")):
            if spec_ship.get(key) is not None:
                self.fit_guns(ship, equip, spec_ship[key], key, kind)

        for c in self.spec.get("cargo", []) or []:
            if not isinstance(c, dict) or "item" not in c:
                self.err("cargo entries are {item: <nick>, count: <n|max>}: %r" % (c,))
                continue
            it = self.item(c["item"], "cargo")
            if it is None:
                continue
            count = c.get("count", 1)
            if count == "max":
                count = {"repairkit": ship.nanobot_limit, "shieldbattery": ship.shield_battery_limit}.get(it.section)
                if count is None:
                    self.err("cargo %s: count: max is only defined for nanobots/batteries" % it.nickname)
                    continue
            elif not isinstance(count, int) or isinstance(count, bool):
                self.err("cargo %s: count must be an integer or max, got %r" % (it.nickname, count))
                continue
            cargo = [x for x in cargo if x[0].lower() != it.nickname.lower()] + [[it.nickname, int(count)]]

        return ship, self.validate_equip(ship, equip, trusted_hps), self.validate_cargo(ship, cargo)

    def mount(self, equip, item, hp):
        it = self.item(item, "ship.equip")
        if it is None:
            return
        def same_slot(e):
            if hp:
                return e[1].lower() == hp.lower()
            other = self.inst.equipment.get(e[0].lower())
            return not e[1] and other is not None and other.section == it.section  # an internal of the same class

        equip[:] = [e for e in equip if not same_slot(e)]
        equip.append([it.nickname, hp])

    def shield_hps(self, ship):
        return [hp for hp in ship.hp_order if any("shield" in t for t in ship.types_by_hp[hp.lower()])]

    def fit_shield(self, ship, equip, want):
        hps = self.shield_hps(ship)
        if not hps:
            self.err("ship.shield: %s has no shield hardpoint" % ship.nickname)
            return
        cls = None
        if isinstance(want, dict) and "best_class" in want:
            cls = int(want["best_class"])
        elif isinstance(want, str) and want.lower().startswith("best_class_"):
            cls = int(want.rsplit("_", 1)[1])
        if cls is None:
            self.mount(equip, str(want), hps[0])
            return
        allowed = ship.types_by_hp[hps[0].lower()]
        cands = [it for it in self.inst.equipment.values() if it.section == "shieldgenerator" and it.hp_type
                 in allowed and CLASS_RE.search(it.hp_type) and int(CLASS_RE.search(it.hp_type).group(1)) == cls]
        if not cands:
            self.err("ship.shield: no class-%d shield fits %s %s" % (cls, ship.nickname, hps[0]))
            return
        best = sorted(cands, key=lambda it: (-it.max_capacity, it.nickname.lower()))[0]
        self.notes["shield"] = best.nickname
        self.mount(equip, best.nickname, hps[0])

    def fit_guns(self, ship, equip, want, key, kind):
        if not isinstance(want, dict) or not isinstance(want.get("prefer"), list):
            self.err("ship.%s: expected {prefer: [<gun>, ...], fill: all_gun_hardpoints | [<hp>, ...]}" % key)
            return
        guns = []
        for g in want["prefer"]:
            it = self.item(g, "ship.%s.prefer" % key)
            if it is None:
                continue
            if it.section != "gun" or not it.hp_type:
                self.err("ship.%s.prefer: %s has no hp_gun_type (not player-mountable)" % (key, it.nickname))
                continue
            guns.append(it)
        fill = want.get("fill", "all_%s_hardpoints" % key[:-1])
        if not isinstance(fill, list) and fill != "all_%s_hardpoints" % key[:-1]:
            self.err("ship.%s.fill: %r (expected all_%s_hardpoints or a list of hardpoints)" % (key, fill, key[:-1]))
            return
        if isinstance(fill, list):
            hps = []
            for hp in fill:
                if str(hp).lower() not in ship.hp_canon:
                    self.err("ship.%s.fill: %s has no hardpoint %r" % (key, ship.nickname, hp))
                else:
                    hps.append(ship.hp_canon[str(hp).lower()])
        else:
            hps = [hp for hp in ship.hp_order if any(t.startswith(kind) for t in ship.types_by_hp[hp.lower()])]
        rr = {}
        for hp in hps:
            ok = [g for g in guns if g.hp_type in ship.types_by_hp[hp.lower()]]
            if not ok:
                self.warn("ship.%s: no preferred gun fits %s %s; left as is" % (key, ship.nickname, hp))
                continue
            top = max(int(CLASS_RE.search(g.hp_type).group(1)) if CLASS_RE.search(g.hp_type) else 0 for g in ok)
            best = tuple(g for g in ok if (int(CLASS_RE.search(g.hp_type).group(1))
                                           if CLASS_RE.search(g.hp_type) else 0) == top)
            pick = best[rr.get(best, 0) % len(best)]
            rr[best] = rr.get(best, 0) + 1
            self.mount(equip, pick.nickname, hp)

    def validate_equip(self, ship, equip, trusted_hps):
        out, used, counts = [], set(), {}
        for item, hp in equip:
            it = self.item(item, "equip")
            if it is None:
                continue
            if it.section in CARGO_ONLY_SECTIONS:
                self.err("equip %s: a %s is cargo, not mountable" % (it.nickname, it.section))
                continue
            if not hp:
                if it.section not in INTERNAL_SECTIONS:
                    self.err("equip %s (%s): needs a hardpoint" % (it.nickname, it.section))
                    continue
                counts[it.section] = counts.get(it.section, 0) + 1
                out.append((0, 0, it.nickname, ""))
                continue
            if it.section in INTERNAL_SECTIONS:
                self.err("equip %s (%s) is internal; it must not name a hardpoint (%s)" % (it.nickname, it.section,
                                                                                            hp))
                continue
            canon = ship.hp_canon.get(hp.lower(), hp)
            if hp.lower() in used:
                self.err("equip: hardpoint %s used twice" % canon)
                continue
            if it.hp_type:
                allowed = ship.hp_by_type.get(it.hp_type, [])
                if hp.lower() not in {h.lower() for h in allowed}:
                    self.err("equip %s (%s) does not fit %s %s; that type fits: %s" % (
                        it.nickname, it.hp_type, ship.nickname, hp, ", ".join(allowed) or "no hardpoint"))
                    continue
            elif it.section in COSMETIC_SECTIONS:
                if hp.lower() not in trusted_hps:
                    self.err("equip %s: hardpoint %s is not used by %s's own package/template/loadout"
                             % (it.nickname, hp, ship.nickname))
                    continue
            else:
                self.err("equip %s (%s): no hardpoint type; cannot mount on %s" % (it.nickname, it.section, hp))
                continue
            used.add(hp.lower())
            order = ship.hp_order.index(canon) if canon in ship.hp_order else len(ship.hp_order)
            out.append((1 if it.hp_type else 2, order, it.nickname, canon))
        for sec in ("engine", "power"):
            if counts.get(sec, 0) != 1:
                self.err("loadout must have exactly one %s (has %d)" % (sec, counts.get(sec, 0)))
        for sec in ("scanner", "tractor"):
            if counts.get(sec, 0) == 0:
                self.warn("loadout has no %s" % sec)
        return [(n, hp) for _, _, n, hp in sorted(out, key=lambda x: (x[0], x[1]))]

    def validate_cargo(self, ship, cargo):
        out, bots, bats, vol = [], 0, 0, 0.0
        for item, count in cargo:
            it = self.item(item, "cargo")
            if it is None:
                continue
            if int(count) < 1:
                self.err("cargo %s: count must be >= 1" % it.nickname)
                continue
            bots += count if it.section == "repairkit" else 0
            bats += count if it.section == "shieldbattery" else 0
            vol += it.volume * count
            out.append((it.nickname, int(count)))
        if bots > ship.nanobot_limit:
            self.err("cargo: %d nanobots exceed %s nanobot_limit %d" % (bots, ship.nickname, ship.nanobot_limit))
        if bats > ship.shield_battery_limit:
            self.err("cargo: %d batteries exceed %s shield_battery_limit %d" % (bats, ship.nickname,
                                                                                 ship.shield_battery_limit))
        if vol > ship.hold_size:
            self.err("cargo: volume %g exceeds %s hold_size %g" % (vol, ship.nickname, ship.hold_size))
        return out

    def resolve_visits(self):
        out = []
        uni = self.inst.universe
        for v in self.spec.get("visit", []) or []:
            if not isinstance(v, dict) or "nick" not in v:
                self.err("visit entries are {nick: <system|base>, flags: <n>}: %r" % (v,))
                continue
            nick = str(v["nick"])
            canon = (uni["systems"].get(nick.lower()) or uni["bases"].get(nick.lower()) or {}).get("nickname")
            if canon is None:
                self.err("visit: unknown system/base %r" % nick)
                continue
            out.append((flhash.create_id(canon), int(v.get("flags", 1))))
        return out


def carry_head(carry):
    return [c for c in carry if raw_kv(c)[0] not in ("log", "interface")]


def carry_tail(carry):
    return [c for c in carry if raw_kv(c)[0] in ("log", "interface")]


# --------------------------------------------------------------------------------------------------------------------
# Output safety and writing
# --------------------------------------------------------------------------------------------------------------------

def _under(path, root):
    root = os.path.realpath(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def check_path(path, what):
    real = os.path.realpath(path)
    play = os.environ.get("FLMOD_PLAY_PREFIX", "/home/user/freelancer/prefix")
    if _under(real, play):
        raise RefusedPath("%s %s is inside the play prefix %s" % (what, real, play))
    if _under(real, os.path.join(os.path.expanduser("~"), ".wine")):
        raise RefusedPath("%s %s is inside ~/.wine" % (what, real))
    if what == "--out" and any(p.lower() == "my games" for p in real.split(os.sep)):
        raise RefusedPath("--out %s is under a 'My Games' folder (lane saves only)" % real)
    return real


def existing_description(path):
    try:
        for s in parse_ini(path):
            if s.lname == "player":
                d = s.get("description")
                return hex_to_wide(d) if d is not None else None
    except (OSError, FixtureError):
        return None
    return None


def write_fixture(out_dir, file_name, text, desc):
    if file_name.lower() == "restart.fl":
        raise RefusedPath("refusing to write Restart.fl")
    path = os.path.join(out_dir, file_name)
    if os.path.exists(path):
        old = existing_description(path)
        if old != desc:
            raise RefusedPath("%s exists and is not fixture %s (description %r); not overwriting" % (path, desc, old))
    tmp = path + ".tmp-gen"
    with open(tmp, "w", encoding="latin-1", newline="") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def file_names(desc, rule):
    names = {"hash": [save_file_name(desc)], "plain": [desc + ".fl"],
             "both": [save_file_name(desc), desc + ".fl"]}
    return names[rule]


def generate(install, spec_arg, out_dir, name_rule="hash", tstamp=None, inst=None):
    """Library entry point (same safety checks as the CLI): returns [(path, info, warnings)]."""
    check_path(install, "--install")
    out_dir = check_path(out_dir, "--out")
    inst = inst or Install(install)
    spec = load_spec(spec_arg)
    b = Builder(inst, spec)
    text, info = b.build(tstamp or filetime_now())
    os.makedirs(out_dir, exist_ok=True)
    res = []
    for name in file_names(spec["name"], name_rule):
        res.append((write_fixture(out_dir, name, text, spec["name"]), info, b.warnings))
    return res


def parse_tstamp(arg):
    if arg in (None, "now"):
        return None
    m = re.match(r"^\s*(\d+)\s*,\s*(\d+)\s*$", arg)
    if not m:
        raise FixtureError("--tstamp: expected now or HI,LO")
    return int(m.group(1)), int(m.group(2))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--install", help="HDE install dir of the lane (read-only)")
    ap.add_argument("--spec", help="spec YAML path or fixture name (HARNESS_<name> or <name>)")
    ap.add_argument("--all", action="store_true", help="generate every spec in specs/")
    ap.add_argument("--out", help="the lane's save dir (<HDE>/SAVE/Accts/SinglePlayer)")
    ap.add_argument("--name-rule", choices=("hash", "plain", "both"), default="hash")
    ap.add_argument("--tstamp", default="now", help="now (default) or HI,LO FILETIME halves")
    ap.add_argument("--list", action="store_true", help="list the available fixture specs")
    a = ap.parse_args(argv)
    try:
        if a.list:
            for p in list_specs():
                s = load_spec(p)
                print("%-34s %s%s" % (s["name"], os.path.relpath(p, HERE),
                                      ("  extends=" + s["extends"]) if s.get("extends") else ""))
            return 0
        if not a.install or not a.out or not (a.spec or a.all):
            ap.error("--install, --out and --spec (or --all) are required")
        check_path(a.install, "--install")
        out_dir = check_path(a.out, "--out")
        inst = Install(a.install)
        ts = parse_tstamp(a.tstamp)
        for spec_arg in (list_specs() if a.all else [a.spec]):
            for path, info, warns in generate(a.install, spec_arg, out_dir, a.name_rule, ts, inst):
                for w in warns:
                    sys.stderr.write("gen_fixture: WARNING: %s\n" % w)
                where = ("base=%s" % info["base"]) if "base" in info else ("pos=%s" % info["pos"])
                print("fixture=%s file=%s description=%s system=%s %s" % (info["fixture"], path,
                                                                         info["description"], info["system"], where))
        return 0
    except FixtureError as e:
        for msg in e.errors:
            sys.stderr.write("gen_fixture: ERROR: %s\n" % msg)
        return 2
    except (ValueError, TypeError) as e:   # a malformed spec value that slipped past the typed checks
        sys.stderr.write("gen_fixture: ERROR: invalid spec value: %s\n" % e)
        return 2
    except RefusedPath as e:
        sys.stderr.write("gen_fixture: REFUSED: %s\n" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
