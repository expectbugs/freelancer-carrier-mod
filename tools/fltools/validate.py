"""Cross-reference validator over the combined data (install + candidate overlay).

Loads every file named in ``freelancer.ini [Data]``, the files Content.dll hard-codes
(:data:`fltools.install.CONTENT_HARDCODED`), universe/system/base/room files, encounter files
and the models loadouts point at, then checks that every reference resolves and that the known
silent-crash rules hold (R4 §0.1 #3/#4/#6, §A1.4). Output: a list of :class:`Finding`
(severity ERROR | WARNING | INFO) and an exit code (1 when any ERROR remains).

A baseline allow-list (``tools/fltools/baseline_findings.txt``) lists findings that stock HDE
already has. Matching findings are reported with severity BASELINE and do not count, so the
validator stays useful on top of vanilla quirks. Overlay content never matches the baseline:
a finding on a file or nickname the overlay introduced keeps its severity.

Finding codes are stable; the key used by the baseline is ``CODE|file|subject`` (lower case).
See ``tools/fltools/README.md`` for the code table.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import utf as _utf
from .ini import Document, Entry, Section
from .install import CONTENT_HARDCODED, Install
from .peres import IdsResolver

__all__ = ["Finding", "Report", "Validator", "validate", "load_baseline", "BASELINE_PATH", "main"]

BASELINE_PATH = Path(__file__).with_name("baseline_findings.txt")
ERROR, WARNING, INFO, BASELINE = "ERROR", "WARNING", "INFO", "BASELINE"
MAX_JUMPS_PER_SYSTEM = 10        # server.dll 0x1b221 (R4 §A1.3)
MAX_SHIPS_PER_FORMATION = 17     # R4 §A1.3 / §A4.7
# Warnings that become errors when the finding involves overlay files or nicknames: vanilla
# has these quirks (baselined), our own content must not.
OVERLAY_ERRORS = {"D002", "H001", "E006"}
MOD_PREFIX = "fcm_"              # CONVENTIONS §2: every new nickname
PREFIX_EXEMPT_SECTIONS = {"room", "mroom"}   # room names are fixed engine names (Bar, Deck...)
# Sections whose nickname REFERENCES something defined elsewhere (an encounter, a base, a room
# name) instead of defining a new object. A unit that adds one (e.g. a vanilla encounter declared
# in another system for a new fcm_ zone) does not make that nickname overlay content.
REFERENCE_SECTIONS = {"encounterparameters", "room", "mroom", "baseinfo"}
IDS_KEY_RE = re.compile(r"^(ids_[a-z0-9_]+|strid_[a-z0-9_]+|tradelane_space_name|individual_name)$")
SOUND_KEYS = {"snd_effect", "one_shot_sound", "separation_explosion", "character_loop_sound",
              "character_start_sound", "cruise_backfire_sound", "cruise_disrupt_sound",
              "cruise_loop_sound", "cruise_start_sound", "cruise_stop_sound", "engine_kill_sound",
              "rumble_sound", "dry_fire_sound", "use_sound", "shield_collapse_sound",
              "shield_rebuilt_sound", "tractor_complete_snd", "bay_doors_close_snd",
              "bay_doors_open_snd", "close_sound", "open_sound"}


@dataclass
class Finding:
    severity: str
    code: str
    file: str
    subject: str
    message: str
    line: int | None = None
    overlay: bool = False

    @property
    def key(self) -> str:
        return f"{self.code}|{self.file.replace(chr(92), '/')}|{self.subject}".lower()

    def render(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"{self.severity:8} {self.code} {loc} [{self.subject}] {self.message}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0

    def by_code(self, code: str) -> list[Finding]:
        return [f for f in self.findings if f.code == code]

    def to_json(self) -> dict:
        return {"stats": self.stats,
                "counts": {s: self.count(s) for s in (ERROR, WARNING, INFO, BASELINE)},
                "findings": [f.__dict__ | {"key": f.key} for f in self.findings]}


def load_baseline(path: str | os.PathLike | None = None) -> set[str]:
    p = Path(path) if path else BASELINE_PATH
    if not p.is_file():
        return set()
    out = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line.lower())
    return out


def _f0(e: Entry | None) -> str | None:
    if e is None or not e.values or not e.values[0]:
        return None
    return e.values[0]


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        try:
            return int(float(str(v).strip()))
        except (TypeError, ValueError):
            return None


class Validator:
    def __init__(self, install: Install, *, baseline: set[str] | None = None,
                 check_hardpoints: bool = True, check_ids: bool = True,
                 runtime_bases: list[str] | None = None, our_dll_index: int | None = None):
        self.I = install
        self.baseline = baseline if baseline is not None else load_baseline()
        self.do_hardpoints = check_hardpoints
        self.do_ids = check_ids
        m = install.manifest()
        self.runtime_bases = {b.lower() for b in (runtime_bases or []) + m.get("runtime_bases", [])}
        self.our_dll_index = our_dll_index if our_dll_index is not None else m.get("ids_index")
        self.findings: list[Finding] = []
        self.sym: dict[str, dict[str, list[tuple[str, Section]]]] = defaultdict(dict)
        self._lines: dict[int, dict[int, int]] = {}
        self._overlay_rels = {r.lower() for r in install.overlay_files()}
        self._patched = {k for k in install._units_by_file}
        self._overlay_nicks: set[str] = set()
        self._patch_new: list[tuple[str, Section, Document]] = []   # sections units added
        self._overlay_secs: set[int] = set()        # id(Section) added by overlay patch units
        self._sec_ns: dict[int, str] = {}           # id(Section) -> symbol-table namespace
        self._sec_pristine_nicks: dict[int, list[str]] = {}   # vanilla sections of patched files
        self._renames: list[tuple[str, Section, Document, str, object]] = []   # for C002
        self._models: dict[str, set[str] | None] = {}
        self._hp_pairs: set[tuple[str, str]] = set()
        self.stats: dict = {}

    # -- helpers ---------------------------------------------------------------------------
    def _is_overlay_file(self, rel: str) -> bool:
        return self.I.data_rel(rel) in self._overlay_rels

    def add(self, sev: str, code: str, rel: str, subject: str, msg: str,
            entry: Entry | Section | None = None, doc: Document | None = None, *,
            overlay: bool = False) -> None:
        """Record a finding. It is *overlay* (never baselined) when ``overlay`` is set, its file
        is an overlay file, or its subject (or the part before ``:``) is an overlay nickname.
        Overlay findings of :data:`OVERLAY_ERRORS` codes are upgraded to ERROR."""
        line = self._line_of(doc, entry) if doc is not None and entry is not None else None
        sl = subject.lower()
        ov = (overlay or self._is_overlay_file(rel) or sl in self._overlay_nicks
              or sl.split(":", 1)[0] in self._overlay_nicks)
        if ov and sev == WARNING and code in OVERLAY_ERRORS:
            sev = ERROR
        f = Finding(sev, code, rel.replace("\\", "/"), subject, msg, line, ov)
        if not ov and f.key in self.baseline and sev in (ERROR, WARNING):
            f.severity = BASELINE
        self.findings.append(f)

    def _line_of(self, doc: Document, obj) -> int | None:
        m = self._lines.get(id(doc))
        if m is None:
            m = {id(ln): i + 1 for i, ln in enumerate(doc._all_lines())}
            self._lines[id(doc)] = m
        target = obj.header if isinstance(obj, Section) else obj
        return m.get(id(target))

    def doc(self, rel: str) -> Document | None:
        return self.I.data_ini(rel)

    def need_doc(self, rel: str, code: str, what: str, sev: str = ERROR) -> Document | None:
        d = self.doc(rel)
        if d is None:
            self.add(sev, code, rel, rel, f"{what} file is missing")
        return d

    def define(self, ns: str, rel: str, doc: Document, names: tuple[str, ...] | None,
               key: str = "nickname") -> None:
        """Register every section (named in ``names``; None = any) with a ``key`` value."""
        table = self.sym[ns]
        ov = self._is_overlay_file(rel)
        wanted = {n.lower() for n in names} if names else None
        for sec in doc.sections():
            if wanted is not None and sec.lname not in wanted:
                continue
            n = sec.get1(key)
            if not n:
                continue
            table.setdefault(n.lower(), []).append((rel, sec))
            self._sec_ns.setdefault(id(sec), ns)
            if ov:
                self._overlay_nicks.add(n.lower())

    def _scan_patch_regions(self) -> None:
        """Overlay provenance by region, in every file the overlay's units patch.

        - A section whose header lies inside a carrier-mod region was added by a unit: it is
          overlay content, and so is its nickname, even when it repeats a vanilla nickname
          (that is a D001/D002 duplicate, now an overlay finding).
        - In a vanilla section, unit lines that add, replace or disable a ``nickname`` key are
          recorded for C002 (shipped nicknames are never renamed).
        - Each vanilla section's pristine nicknames (lines outside regions, plus the originals
          kept in ``carrier-mod-disabled`` lines) feed C001's per-namespace newness test.
        """
        from . import patch as _patch

        def step(text: str, cur: str | None) -> tuple[str | None, bool]:
            m = _patch._OPEN_RE.match(text)
            if m:
                return m.group(1), True
            if _patch._CLOSE_RE.match(text):
                return None, True
            return cur, False

        for root_rel in sorted(self._patched):
            d = self.I.ini_rel(root_rel)
            if d is None:
                continue
            region = None
            for ln in d.preamble:
                region, _ = step(ln.text, region)
            for sec in d._sections:
                added = region is not None          # header inside a region
                if added and not sec.disabled:
                    self._overlay_secs.add(id(sec))
                    if sec.lname not in REFERENCE_SECTIONS:
                        for e in sec.entries("nickname"):
                            if e.values and e.values[0]:
                                self._overlay_nicks.add(e.values[0].lower())
                    self._patch_new.append((root_rel, sec, d))
                pristine: list[str] = []
                for ln in sec.lines:
                    region, marker = step(ln.text, region)
                    if marker or added:
                        continue
                    if region is None:
                        if ln.is_entry and ln.lkey == "nickname" and ln.values and ln.values[0]:
                            pristine.append(ln.values[0])
                    elif ln.is_entry and ln.lkey == "nickname":
                        self._renames.append((root_rel, sec, d, region, ln))
                    elif ln.text.startswith(_patch.DISABLED):
                        orig = ln.text[len(_patch.DISABLED):]
                        k, _, v = orig.partition("=")
                        if k.split(";", 1)[0].strip(" \t").lower() == "nickname":
                            self._renames.append((root_rel, sec, d, region, ln))
                            val = v.split(";", 1)[0].split(",", 1)[0].strip(" \t")
                            if val:
                                pristine.append(val)
                if not added:
                    self._sec_pristine_nicks[id(sec)] = pristine
                    now = sec.nickname
                    if now and now.lower() not in {x.lower() for x in pristine}:
                        self._overlay_nicks.add(now.lower())       # renamed by a unit

    def has(self, ns: str, nick: str | None) -> bool:
        return bool(nick) and nick.lower() in self.sym[ns]

    def first(self, ns: str, nick: str) -> tuple[str, Section] | None:
        v = self.sym[ns].get(nick.lower())
        return v[0] if v else None

    # -- loading ---------------------------------------------------------------------------
    def load(self) -> None:
        I = self.I
        groups = {
            "equipment": ("equipment", None), "goods": ("goods", ("Good",)),
            "ships": ("ships", ("Ship",)), "solar": ("solars", ("Solar",)),
            "loadouts": ("loadouts", ("Loadout",)), "sounds": ("sounds", ("Sound",)),
            "voices": ("voices", ("Voice",)), "groups": ("factions", ("Group",)),
            "costumes": ("costumes", ("Costume",)), "asteroids": ("asteroids", None),
            "bodyparts": ("bodyparts", None),
            "effects": ("effects", None), "explosions": ("explosions", None),
        }
        self.data_files = I.data_entries()
        for key, rel in self.data_files:
            d = self.need_doc(rel, "F001", f"[Data] {key}")
            if d is None:
                continue
            if key in groups:
                ns, names = groups[key]
                self.define(ns, rel, d, names)
            if key == "fuses":
                self.define("fuses", rel, d, ("fuse",), key="name")
        for rel in CONTENT_HARDCODED:
            sev = WARNING if rel.lower().startswith("universe") else ERROR
            self.need_doc(rel, "F002", "Content.dll hard-coded", sev)
        self.npc_doc = self.doc(r"missions\npcships.ini")
        if self.npc_doc:
            self.define("npcships", r"missions\npcships.ini", self.npc_doc, ("NPCShipArch",))
        for rel in (r"missions\pilots_population.ini", r"missions\pilots_story.ini"):
            d = self.doc(rel)
            if d:
                self.define("pilots", rel, d, ("Pilot",))
        for rel, ns, names in ((r"missions\formations.ini", "formations", ("Formation",)),
                               (r"missions\shipclasses.ini", "shipclasses", ("ShipClass",)),
                               (r"missions\mbases.ini", "mbases", ("MBase",))):
            d = self.doc(rel)
            if d:
                self.define(ns, rel, d, names)
        uni = I.data_files("universe")
        self.universe_rel = uni[0] if uni else r"universe\universe.ini"
        self.universe = self.doc(self.universe_rel)
        if self.universe:
            self.define("systems", self.universe_rel, self.universe, ("system",))
            self.define("bases", self.universe_rel, self.universe, ("Base",))
        self.universe_dir = os.path.dirname(self.universe_rel.replace("\\", "/"))
        self.stats["namespaces"] = {k: len(v) for k, v in sorted(self.sym.items())}
        self._scan_patch_regions()

    # -- checks ----------------------------------------------------------------------------
    def check_duplicates(self) -> None:
        for ns, table in sorted(self.sym.items()):
            if ns in ("effects", "explosions"):
                continue
            for nick, defs in table.items():
                if len(defs) < 2:
                    continue
                spellings = {s.get1("nickname" if ns != "fuses" else "name") for _r, s in defs}
                rel, sec = defs[1]
                if len(spellings) > 1:
                    self.add(ERROR, "D001", rel, nick,
                             f"{ns} nickname defined {len(defs)}x with different case "
                             f"{sorted(spellings)} (nicknames are case-insensitive)", sec,
                             self.doc(rel))
                else:
                    self.add(WARNING, "D002", rel, nick,
                             f"{ns} nickname defined {len(defs)}x "
                             f"(also in {defs[0][0]})", sec, self.doc(rel))

    def _equip_kind(self, nick: str) -> str | None:
        hit = self.first("equipment", nick)
        return hit[1].lname if hit else None

    def check_loadouts(self) -> None:
        for nick, defs in self.sym["loadouts"].items():
            for rel, sec in defs:
                d = self.doc(rel)
                arch = sec.get1("archetype")
                if arch and not (self.has("ships", arch) or self.has("solars", arch)):
                    self.add(WARNING, "L003", rel, nick, f"archetype {arch!r} is not a ship or "
                             "solar", sec.entry("archetype"), d)
                for e in sec.entries("equip"):
                    eq = _f0(e)
                    if eq and not self.has("equipment", eq):
                        self.add(ERROR, "L001", rel, f"{nick}:{eq}",
                                 f"equip {eq!r} is not defined in any [Data] equipment file", e, d)
                for e in sec.entries("cargo"):
                    g = _f0(e)
                    if g and not (self.has("goods", g) or self.has("equipment", g)):
                        self.add(ERROR, "L002", rel, f"{nick}:{g}",
                                 f"cargo {g!r} is not a good or equipment", e, d)

    def check_npcs(self) -> None:
        d = self.npc_doc
        rel = r"missions\npcships.ini"
        if d is None:
            return
        for sec in d.sections("NPCShipArch"):
            nick = sec.nickname or "?"
            lo = sec.get1("loadout")
            if not lo or not self.has("loadouts", lo):
                self.add(ERROR, "N001", rel, nick, f"loadout {lo!r} does not exist",
                         sec.entry("loadout") or sec, d)
            else:
                self._check_engine(lo, rel, nick, sec, d)
            ship = sec.get1("ship_archetype")
            if not ship or not self.has("ships", ship):
                self.add(ERROR, "N003", rel, nick, f"ship_archetype {ship!r} does not exist",
                         sec.entry("ship_archetype") or sec, d)
            pilot = sec.get1("pilot")
            if pilot is None:
                self.add(WARNING, "N004", rel, nick, "no pilot (the game falls back to a "
                         "default personality)", sec, d)
            elif not self.has("pilots", pilot):
                self.add(ERROR, "N004", rel, nick, f"pilot {pilot!r} does not exist",
                         sec.entry("pilot"), d)
            if lo and ship and self.has("loadouts", lo) and self.has("ships", ship):
                self._check_hardpoints_for(lo, ship, "ships", rel, nick, sec, d)
        fp_rel = r"missions\faction_prop.ini"
        fp = self.doc(fp_rel)
        if fp is None:
            return
        for sec in fp.sections("FactionProps"):
            aff = sec.get1("affiliation") or "?"
            if not self.has("factions", aff):
                self.add(ERROR, "N006", fp_rel, aff, "affiliation is not an InitialWorld group",
                         sec.entry("affiliation") or sec, fp)
            for e in sec.entries("npc_ship"):
                n = _f0(e)
                if n and not self.has("npcships", n):
                    self.add(ERROR, "N005", fp_rel, f"{aff}:{n}", f"npc_ship {n!r} is not an "
                             "[NPCShipArch]", e, fp)
            for e in sec.entries("formation"):
                vals = e.values
                if len(vals) >= 2 and vals[1] and not self.has("formations", vals[1]):
                    self.add(ERROR, "N007", fp_rel, f"{aff}:{vals[1]}",
                             f"formation {vals[1]!r} is not in formations.ini", e, fp)
            for e in sec.entries("voice"):
                v = _f0(e)
                if v and not self.has("voices", v):
                    self.add(ERROR, "A002", fp_rel, f"{aff}:{v}", f"voice {v!r} is not defined",
                             e, fp)
            for e in sec.entries("mc_costume"):
                c = _f0(e)
                if c and self.sym["costumes"] and not self.has("costumes", c):
                    self.add(WARNING, "N010", fp_rel, f"{aff}:{c}",
                             f"mc_costume {c!r} is not a [Costume]", e, fp)
            for e in sec.entries("space_costume"):
                for c in e.values:
                    if c and self.sym["bodyparts"] and not self.has("bodyparts", c):
                        self.add(WARNING, "N010", fp_rel, f"{aff}:{c}",
                                 f"space_costume part {c!r} is not in bodyparts", e, fp)

    def check_factions(self) -> None:
        for nick, defs in self.sym["factions"].items():
            for rel, sec in defs:
                d = self.doc(rel)
                for e in sec.entries("rep"):
                    vals = e.values
                    if len(vals) >= 2 and vals[1] and not self.has("factions", vals[1]):
                        self.add(ERROR, "R001", rel, f"{nick}:{vals[1]}",
                                 f"rep target {vals[1]!r} is not a [Group]", e, d)
        mb_rel = r"missions\mbases.ini"
        mb = self.doc(mb_rel)
        for s in mb.sections("GF_NPC") if mb else []:
            a = s.get1("affiliation")
            if a and not self.has("factions", a):
                self.add(ERROR, "R002", mb_rel, f"{s.nickname}:{a}",
                         f"affiliation {a!r} is not a [Group]", s.entry("affiliation"), mb)
        fo_rel = r"missions\formations.ini"
        fo = self.doc(fo_rel)
        for s in fo.sections("Formation") if fo else []:
            n = len(s.entries("pos"))
            if n > MAX_SHIPS_PER_FORMATION:
                self.add(WARNING, "E008", fo_rel, s.nickname or "?",
                         f"{n} pos entries (> {MAX_SHIPS_PER_FORMATION})", s, fo)

    def _check_engine(self, lo: str, rel: str, nick: str, sec: Section, d: Document) -> None:
        lrel, lsec = self.first("loadouts", lo)
        kinds = [self._equip_kind(_f0(e) or "") for e in lsec.entries("equip")]
        if "engine" not in kinds:
            self.add(ERROR, "N002", rel, nick,
                     f"loadout {lo!r} ({lrel}) has no [Engine] equip: spawning it crashes "
                     "server.dll 0x2247f", sec.entry("loadout"), d)

    # -- models / hardpoints -----------------------------------------------------------------
    def _model_hardpoints(self, ns: str, arch: str) -> tuple[str | None, set[str] | None]:
        hit = self.first(ns, arch)
        if hit is None:
            return None, None
        da = hit[1].get1("DA_archetype")
        if not da:
            return None, None
        key = da.lower()
        if key not in self._models:
            p = self.I.data_path(da)
            hps = None
            if p is not None and p.is_file():
                try:
                    hps = {h.name.lower() for h in _utf.list_hardpoints(_utf.load(p))}
                except (_utf.UtfError, OSError, ValueError):
                    hps = None
            self._models[key] = hps
        return da, self._models[key]

    def _check_hardpoints_for(self, lo: str, arch: str, ns: str, rel: str, subject: str,
                              sec: Section, d: Document) -> None:
        if not self.do_hardpoints:
            return
        da, hps = self._model_hardpoints(ns, arch)
        if hps is None:
            return
        lrel, lsec = self.first("loadouts", lo)
        ld = self.doc(lrel)
        self.stats["hardpoint_loadouts_checked"] = self.stats.get("hardpoint_loadouts_checked", 0) + 1
        for e in lsec.entries("equip"):
            vals = e.values
            if len(vals) < 2 or not vals[1]:
                continue
            hp = vals[1]
            self.stats["hardpoints_checked"] = self.stats.get("hardpoints_checked", 0) + 1
            if hp.lower() not in hps:
                self.add(WARNING, "H001", lrel, f"{lo}:{hp}",
                         f"hardpoint {hp!r} is not on {da} (archetype {arch} via {subject})",
                         e, ld)

    def check_model_files(self) -> None:
        for ns in ("ships", "solars"):
            for nick, defs in self.sym[ns].items():
                rel, sec = defs[0]
                da = sec.get1("DA_archetype")
                if da and not self.I.exists_data(da):
                    self.add(ERROR, "M001", rel, nick, f"DA_archetype {da!r} not found",
                             sec.entry("DA_archetype"), self.doc(rel))
        # loadouts naming a ship/solar archetype: hardpoints on that model
        for nick, defs in self.sym["loadouts"].items():
            rel, sec = defs[0]
            arch = sec.get1("archetype")
            if not arch:
                continue
            ns = "ships" if self.has("ships", arch) else "solars" if self.has("solars", arch) \
                else None
            if ns:
                self._check_hardpoints_for(nick, arch, ns, rel, nick, sec, self.doc(rel))

    # -- universe, systems, bases --------------------------------------------------------------
    def check_universe(self) -> None:
        u = self.universe
        if u is None:
            return
        urel = self.universe_rel
        self.system_docs: dict[str, tuple[str, Document]] = {}
        for sec in u.sections("system"):
            nick = sec.nickname or "?"
            f = sec.get1("file")
            if not f:
                self.add(ERROR, "S001", urel, nick, "system has no file", sec, u)
                continue
            rel = (self.universe_dir + "/" + f.replace("\\", "/")) if self.universe_dir else f
            d = self.doc(rel)
            if d is None:
                self.add(ERROR, "S001", urel, nick, f"system file {f!r} not found",
                         sec.entry("file"), u)
                continue
            self.system_docs[nick.lower()] = (rel, d)
        # objects per system (for goto targets and dock solars)
        self.objects: dict[str, dict[str, Section]] = {}
        for sysn, (rel, d) in self.system_docs.items():
            self.objects[sysn] = {s.nickname.lower(): s for s in d.sections("Object") if s.nickname}
        for sec in u.sections("Base"):
            nick = sec.nickname or "?"
            sysn = sec.get1("system")
            if not self.has("systems", sysn):
                self.add(ERROR, "B001", urel, nick, f"system {sysn!r} does not exist",
                         sec.entry("system") or sec, u)
            f = sec.get1("file")
            bd = self.doc(f) if f else None
            if bd is None:
                self.add(ERROR, "B002", urel, nick, f"base file {f!r} not found",
                         sec.entry("file") or sec, u)
            else:
                self._check_base_file(f, bd, nick)
            if not self.has("mbases", nick):
                self.add(ERROR, "B004", urel, nick, "no [MBase] in missions\\mbases.ini", sec, u)

    def _check_base_file(self, rel: str, d: Document, base: str) -> None:
        rooms = {}
        for s in d.sections("Room"):
            rn = s.nickname
            rf = s.get1("file")
            if rn:
                rooms[rn.lower()] = s
            if not rf or self.doc(rf) is None:
                self.add(ERROR, "B003", rel, f"{base}:{rn}", f"room file {rf!r} not found",
                         s.entry("file") or s, d)
        if not rooms:
            self.add(ERROR, "B003", rel, base, "base file has no [Room]", None, None)
        info = d.section("BaseInfo")
        start = info.get1("start_room") if info else None
        if not start or start.lower() not in rooms:
            self.add(ERROR, "B003", rel, base, f"start_room {start!r} is not one of its rooms",
                     (info.entry("start_room") or info) if info else None, d)

    def _mission_created_bases(self) -> set[str]:
        out = set()
        rel = self.universe_dir + "/missioncreatedsolars.ini" if self.universe_dir \
            else "missioncreatedsolars.ini"
        d = self.doc(rel)
        for s in d.sections("MissionCreatedSolar") if d else []:
            b = s.get1("base")
            if b:
                out.add(b.lower())
        return out

    def _dockable_solar(self, arch: str) -> bool:
        hit = self.first("solars", arch)
        return bool(hit and hit[1].has("docking_sphere"))

    def check_systems(self) -> None:
        if not hasattr(self, "system_docs"):
            return
        base_objects: dict[str, list[tuple[str, str]]] = defaultdict(list)
        enc_files: dict[str, tuple[str, str]] = {}   # encounter nick -> (file rel, system)
        self.zone_rows: list[tuple] = []
        for sysn, (rel, d) in self.system_docs.items():
            sysnick = self.first("systems", sysn)[1].nickname
            jumps = 0
            solars = 0
            for s in d.sections("Object"):
                nick = s.nickname or "?"
                arch = s.get1("archetype")
                if arch:
                    solars += 1
                    if not (self.has("solars", arch) or self.has("asteroids", arch)):
                        self.add(ERROR, "S002", rel, nick, f"archetype {arch!r} is not a solar",
                                 s.entry("archetype"), d)
                g = s.getv("goto")
                if g:
                    jumps += 1
                    tsys = g[0] if g else None
                    tobj = g[1] if len(g) > 1 else None
                    if not self.has("systems", tsys):
                        self.add(ERROR, "S003", rel, nick, f"goto system {tsys!r} does not exist",
                                 s.entry("goto"), d)
                    elif tobj and tobj.lower() not in self.objects.get(tsys.lower(), {}):
                        self.add(ERROR, "S003", rel, nick, f"goto object {tobj!r} not in {tsys}",
                                 s.entry("goto"), d)
                lo = s.get1("loadout")
                if lo and not self.has("loadouts", lo):
                    self.add(ERROR, "S004", rel, nick, f"loadout {lo!r} does not exist",
                             s.entry("loadout"), d)
                elif lo and arch and self.has("solars", arch) and \
                        (lo.lower(), arch.lower()) not in self._hp_pairs:
                    self._hp_pairs.add((lo.lower(), arch.lower()))
                    self._check_hardpoints_for(lo, arch, "solars", rel, nick, s, d)
                rep = s.get1("reputation")
                if rep and not self.has("factions", rep):
                    self.add(ERROR, "S005", rel, nick, f"reputation {rep!r} is not a faction",
                             s.entry("reputation"), d)
                for key in ("base", "dock_with"):
                    b = s.get1(key)
                    if b and not self.has("bases", b):
                        self.add(ERROR, "B006", rel, nick, f"{key} {b!r} is not a universe [Base]",
                                 s.entry(key), d)
                for key in ("base", "dock_with"):
                    b = s.get1(key)
                    if b and arch:
                        base_objects[b.lower()].append((sysnick, arch))
                par = s.get1("parent")
                if par and par.lower() not in self.objects[sysn]:
                    self.add(WARNING, "S013", rel, nick, f"parent {par!r} is not an object here",
                             s.entry("parent"), d)
            if jumps > MAX_JUMPS_PER_SYSTEM:
                self.add(ERROR, "S006", rel, sysnick, f"{jumps} jump objects (> "
                         f"{MAX_JUMPS_PER_SYSTEM} crashes server.dll 0x1b221)", None, None)
            if solars == 0:
                self.add(ERROR, "S007", rel, sysnick, "system has no solar objects (crashes "
                         "Freelancer.exe 0xd1744)", None, None)
            declared = {}
            for s in d.sections("EncounterParameters"):
                en, ef = s.get1("nickname"), s.get1("filename")
                if not en:
                    continue
                declared[en.lower()] = ef
                if not ef or self.doc(ef) is None:
                    self.add(ERROR, "S008", rel, f"{sysnick}:{en}",
                             f"encounter file {ef!r} not found", s.entry("filename") or s, d)
                else:
                    enc_files.setdefault(en.lower(), (ef, rel))
            for z in d.sections("zone"):
                self._check_zone(rel, d, sysnick, z, declared)
        self.enc_files = enc_files
        self.base_objects = base_objects
        # dock solars
        mcs = self._mission_created_bases()
        if self.universe is None:
            return
        for sec in self.universe.sections("Base"):
            nick = sec.nickname or "?"
            ln = nick.lower()
            sysn = (sec.get1("system") or "").lower()
            objs = base_objects.get(ln, [])
            dock = [o for o in objs if self._dockable_solar(o[1])]
            if dock:
                wrong = [o for o in dock if o[0].lower() != sysn]
                if wrong and len(wrong) == len(dock):
                    self.add(ERROR, "B007", self.universe_rel, nick,
                             f"dock solar is in {wrong[0][0]}, but [Base] system = "
                             f"{sec.get1('system')} (crash on undock)", sec, self.universe)
                continue
            if ln in mcs:
                self.add(INFO, "B005", self.universe_rel, nick, "dock solar is mission-spawned "
                         "(missioncreatedsolars.ini)", sec, self.universe)
                continue
            if ln in self.runtime_bases:
                self.add(INFO, "B005", self.universe_rel, nick, "dock solar is spawned at "
                         "runtime (declared by the overlay)", sec, self.universe)
                continue
            self.add(ERROR, "B005", self.universe_rel, nick,
                     "no dock solar: no dockable system object has base/dock_with = this base "
                     "(crashes server.dll 0x14990 / 0xab670)", sec, self.universe)

    def _check_zone(self, rel: str, d: Document, sysnick: str, z: Section, declared: dict) -> None:
        zn = z.nickname or "?"
        path = z.getv("path_label")
        cur = None
        for e in z.entries():
            k = e.lkey
            if k == "encounter":
                en = _f0(e)
                cur = en
                if en and en.lower() not in declared:
                    self.add(ERROR, "S008", rel, f"{zn}:{en}", f"encounter {en!r} is not "
                             f"declared in this system's [EncounterParameters]", e, d)
            elif k == "faction":
                f = _f0(e)
                if f and not self.has("factions", f):
                    self.add(ERROR, "S009", rel, f"{zn}:{f}", f"faction {f!r} does not exist",
                             e, d)
                if cur:
                    self.zone_rows.append((sysnick, zn, cur, f, bool(path), rel, e, d))
            elif k == "density_restriction":
                vals = e.values
                if len(vals) >= 2 and self.sym["shipclasses"] and \
                        not self.has("shipclasses", vals[1]):
                    self.add(WARNING, "S010", rel, f"{zn}:{vals[1]}",
                             f"density_restriction class {vals[1]!r} is not a [ShipClass]", e, d)

    # -- encounters --------------------------------------------------------------------------
    def check_encounters(self) -> None:
        if not hasattr(self, "enc_files"):
            return
        npc_words: set[str] = set()
        if self.npc_doc:
            for s in self.npc_doc.sections("NPCShipArch"):
                for v in s.getallv("npc_class"):
                    npc_words.update(x.lower() for x in v)
        for nick, defs in self.sym["ships"].items():
            for _r, s in defs:
                for v in s.getallv("mission_property"):
                    npc_words.update(x.lower() for x in v)
        fac_forms: dict[str, set[str]] = defaultdict(set)
        fp = self.doc(r"missions\faction_prop.ini")
        for s in fp.sections("FactionProps") if fp else []:
            aff = (s.get1("affiliation") or "").lower()
            for v in s.getallv("formation"):
                if v:
                    fac_forms[aff].add(v[0].lower())
        enc_info: dict[str, dict] = {}
        for en, (ef, srel) in sorted(self.enc_files.items()):
            d = self.doc(ef)
            forms = d.sections("EncounterFormation")
            if not forms:
                self.add(ERROR, "E004", ef, en, "no [EncounterFormation] (undefined behaviour)",
                         None, None)
            classes_needed = set()
            patrol = False
            for i, f in enumerate(forms):
                lines = f.entries("ship_by_class") + f.entries("ship_by_npc_arch")
                if not lines:
                    self.add(ERROR, "E004", ef, f"{en}#{i}", "formation has no ship lines", f, d)
                total = 0
                for e in lines:
                    vals = e.values
                    mx = _int(vals[1]) if len(vals) > 1 else 0
                    total += mx or 0
                    if e.lkey == "ship_by_class" and len(vals) > 2:
                        c = vals[2].lower()
                        if not (self.has("shipclasses", c) or c in npc_words):
                            self.add(ERROR, "E005", ef, f"{en}:{vals[2]}",
                                     f"ship class {vals[2]!r} matches no [ShipClass] or npc_class",
                                     e, d)
                    if e.lkey == "ship_by_npc_arch" and len(vals) > 2 and \
                            not self.has("npcships", vals[2]):
                        self.add(ERROR, "E005", ef, f"{en}:{vals[2]}",
                                 f"npc arch {vals[2]!r} is not an [NPCShipArch]", e, d)
                if total > MAX_SHIPS_PER_FORMATION:
                    self.add(ERROR, "E001", ef, f"{en}#{i}", f"{total} ships in one formation "
                             f"(> {MAX_SHIPS_PER_FORMATION} crashes)", f, d)
                fbc = f.get1("formation_by_class")
                if fbc:
                    classes_needed.add(fbc.lower())
                fm = f.get1("formation")
                if fm and not self.has("formations", fm):
                    self.add(ERROR, "E003", ef, f"{en}:{fm}", f"formation {fm!r} is not in "
                             "formations.ini", f.entry("formation"), d)
                if (f.get1("behavior") or "") == "patrol_path":
                    patrol = True
            for s in d.sections("Creation"):
                for e in s.entries("permutation"):
                    idxs = [int(x) for x in re.findall(r"\d+", e.values[0] if e.values else "")]
                    bad = [x for x in idxs if x >= len(forms)]
                    if bad:
                        self.add(ERROR, "E002", ef, f"{en}:{e.params}",
                                 f"permutation uses formation {bad} but the file has "
                                 f"{len(forms)}", e, d)
            enc_info[en] = {"classes": classes_needed, "patrol": patrol, "file": ef}
        # per zone usage: formation_by_class mapped for every faction; patrol only on paths
        seen = set()
        for sysnick, zn, en, fac, has_path, rel, e, d in self.zone_rows:
            info = enc_info.get((en or "").lower())
            if not info or not fac:
                continue
            for c in info["classes"]:
                k = (en.lower(), fac.lower(), c)
                if k in seen:
                    continue
                seen.add(k)
                if c not in fac_forms.get(fac.lower(), set()):
                    self.add(ERROR, "E003", r"missions\faction_prop.ini", f"{fac}:{c}",
                             f"faction has no formation for class {c!r} used by encounter "
                             f"{en} ({sysnick} {zn})", None, None,
                             overlay=self._row_is_overlay(zn, en, rel, info["file"]))
            if info["patrol"] and not has_path:
                self.add(ERROR, "E007", rel, f"{zn}:{en}", "patrol_path encounter in a zone "
                         "without path_label", e, d)
        # patrol/trade path factions need a [BaseFaction] in the system
        base_facs: dict[str, set[str]] = defaultdict(set)
        mb = self.doc(r"missions\mbases.ini")
        if mb and self.universe:
            sys_of_base = {(s.nickname or "").lower(): (s.get1("system") or "").lower()
                           for s in self.universe.sections("Base")}
            cur_base = None
            for s in mb.sections():
                if s.lname == "mbase":
                    cur_base = (s.nickname or "").lower()
                    lf = s.get1("local_faction")
                    if lf and not self.has("factions", lf):
                        self.add(ERROR, "B009", r"missions\mbases.ini", f"{cur_base}:{lf}",
                                 f"local_faction {lf!r} does not exist", s, mb)
                elif s.lname == "basefaction" and cur_base:
                    f = s.get1("faction")
                    if f:
                        if not self.has("factions", f):
                            self.add(ERROR, "B009", r"missions\mbases.ini", f"{cur_base}:{f}",
                                     f"[BaseFaction] faction {f!r} does not exist", s, mb)
                        base_facs[sys_of_base.get(cur_base, "")].add(f.lower())
        # one finding per (system, faction); an overlay zone or encounter makes it overlay (and
        # so an ERROR) even when vanilla zones of the same pair are baselined
        rows_by_pair: dict[tuple[str, str], list[tuple]] = {}
        for row in self.zone_rows:
            sysnick, zn, en, fac, has_path, rel, e, d = row
            if not has_path or not fac:
                continue
            if fac.lower() in base_facs.get(sysnick.lower(), set()):
                continue
            rows_by_pair.setdefault((sysnick.lower(), fac.lower()), []).append(row)
        for rows in rows_by_pair.values():
            ov_rows = [r for r in rows if self._row_is_overlay(
                r[1], r[2], r[5], enc_info.get((r[2] or "").lower(), {}).get("file"))]
            sysnick, zn, en, fac, has_path, rel, e, d = (ov_rows or rows)[0]
            self.add(WARNING, "E006", rel, f"{sysnick}:{fac}",
                     f"path encounters of {fac} (e.g. {zn}) but no base in {sysnick} has a "
                     "[BaseFaction] for it (NPCs need a valid destination)", e, d,
                     overlay=bool(ov_rows))

    def _row_is_overlay(self, zone: str | None, enc: str | None, sys_rel: str | None,
                        enc_rel: str | None) -> bool:
        """A zone row is overlay content when its zone is (an overlay nickname), or its system
        file or encounter file is an overlay file. The encounter NICKNAME does not count: vanilla
        zones elsewhere that use the same vanilla encounter are not the overlay's doing (an
        overlay encounter file can only be reached through overlay content)."""
        del enc
        return bool((zone and zone.lower() in self._overlay_nicks)
                    or (sys_rel and self._is_overlay_file(sys_rel))
                    or (enc_rel and self._is_overlay_file(enc_rel)))

    # -- markets, goods ----------------------------------------------------------------------
    def check_goods_markets(self) -> None:
        for nick, defs in self.sym["goods"].items():
            for rel, sec in defs:
                d = self.doc(rel)
                for key, nss in (("equipment", ("equipment",)), ("ship", ("ships",)),
                                 ("hull", ("goods",))):
                    v = sec.get1(key)
                    if v and not any(self.has(ns, v) for ns in nss):
                        self.add(ERROR, "G001", rel, nick, f"{key} {v!r} does not exist",
                                 sec.entry(key), d)
                for e in sec.entries("addon"):
                    v = _f0(e)
                    if v and not (self.has("goods", v) or self.has("equipment", v)):
                        self.add(ERROR, "G001", rel, f"{nick}:{v}", f"addon {v!r} does not exist",
                                 e, d)
        for rel in self.I.data_files("markets"):
            d = self.doc(rel)
            for s in d.sections("BaseGood") if d else []:
                b = s.get1("base")
                if b and not self.has("bases", b):
                    self.add(ERROR, "G002", rel, b, "[BaseGood] base is not a universe [Base]",
                             s.entry("base"), d)
                for e in s.entries("marketgood"):
                    g = _f0(e)
                    if g and not self.has("goods", g):
                        self.add(ERROR, "G003", rel, f"{b}:{g}", f"marketgood {g!r} is not a "
                                 "[Good]", e, d)

    # -- sounds / voices ---------------------------------------------------------------------
    def check_sounds(self) -> None:
        if not self.sym["sounds"]:
            return
        for key in ("equipment", "ships", "solar", "effects"):
            for rel in self.I.data_files(key):
                d = self.doc(rel)
                for s in d.sections() if d else []:
                    for e in s.entries():
                        if e.lkey in SOUND_KEYS:
                            v = _f0(e)
                            ok = self.has("sounds", v) or (
                                e.lkey == "separation_explosion" and self.has("explosions", v))
                            if v and not ok:
                                self.add(WARNING, "A001", rel, f"{s.nickname}:{v}",
                                         f"{e.key} {v!r} is not a [Sound]", e, d)
        mb = self.doc(r"missions\mbases.ini")
        for s in mb.sections("GF_NPC") if mb and self.sym["voices"] else []:
            v = s.get1("voice")
            if v and not self.has("voices", v):
                self.add(WARNING, "A003", r"missions\mbases.ini", f"{s.nickname}:{v}",
                         f"voice {v!r} is not a [Voice]", s.entry("voice"), mb)

    # -- IDS ---------------------------------------------------------------------------------
    def check_ids(self) -> None:
        if not self.do_ids:
            return
        extra = []
        m = self.I.manifest()
        res = IdsResolver.from_install(self.I)
        self.stats["resource_dlls"] = res.names
        missing_dlls = [n for i, n in enumerate(res.names) if res.dll(i) is None]
        for n in missing_dlls:
            self.add(ERROR, "I003", "EXE/freelancer.ini", n, "resource DLL listed in "
                     "[Resources] is missing", None, None)
        n_checked = 0
        for rel in self.I.iter_data_inis():
            d = self.doc(rel)
            if d is None:
                continue
            for s in d.sections():
                for e in s.entries():
                    if not IDS_KEY_RE.match(e.lkey):
                        continue
                    v = _int(_f0(e))
                    if not v:
                        continue
                    n_checked += 1
                    idx = v >> 16
                    subj = f"{s.nickname or s.name}:{e.key}"   # no game values in keys (§12)
                    if not res.in_range(v):
                        self.add(ERROR, "I001", rel, subj, f"IDS {v} is in DLL index {idx}, but "
                                 f"only {res.count} DLLs are loaded (0..{res.count - 1})", e, d)
                        continue
                    kind = e.lkey
                    want_html = kind.startswith("ids_info") or kind == "strid_desc"
                    got = res.infocard(v) if want_html else res.name(v)
                    if got is None:
                        got_other = res.name(v) if want_html else res.infocard(v)
                        what = "infocard" if want_html else "string"
                        if got_other is not None:
                            self.add(INFO, "I004", rel, subj, f"{e.key} points at a "
                                     f"{'string' if want_html else 'infocard'}, not a {what}, "
                                     f"in {res.names[idx]}", e, d)
                            continue
                        sev = ERROR if (self.our_dll_index is not None
                                        and idx == self.our_dll_index) else WARNING
                        self.add(sev, "I002", rel, subj, f"no {what} {v & 0xFFFF} in "
                                 f"{res.names[idx]} (nor a resource of the other kind)", e, d)
        self.stats["ids_checked"] = n_checked
        del extra, m

    # -- naming ------------------------------------------------------------------------------
    def _ns_of(self, sec: Section) -> str:
        return self._sec_ns.get(id(sec), "section:" + sec.lname)

    def check_prefix(self) -> None:
        """C002: a unit adds, replaces or disables a ``nickname`` key of a vanilla section.
        C001: every nickname the overlay introduces starts with ``fcm_`` (CONVENTIONS §2).
        Candidates are the ``nickname`` values of sections in overlay files and of sections
        patch units add (by region); ``[Room]``/``[MRoom]`` names are exempt. A candidate is
        *new* when no pristine section of the same namespace (symbol table, else section type)
        defines it, case-insensitively; re-definitions are D001/D002's business. The pristine
        sets are only computed when a candidate lacks the prefix, so compliant overlays cost
        nothing."""
        data_pre = self.I.data_rel("")          # "data/": report DATA-relative like the rest

        def report_rel(rel: str) -> str:
            return rel[len(data_pre):] if rel.lower().startswith(data_pre) else rel

        seen_sec: set[int] = set()
        for root_rel, sec, d, region, ln in self._renames:         # C002
            if id(sec) in seen_sec:
                continue
            seen_sec.add(id(sec))
            orig = (self._sec_pristine_nicks.get(id(sec)) or [sec.nickname or sec.name])[0]
            self.add(ERROR, "C002", report_rel(root_rel), orig,
                     f"patch unit region {region!r} adds, replaces or disables the nickname key "
                     f"of a vanilla [{sec.name}] (shipped nicknames are never renamed)", ln, d,
                     overlay=True)

        cands: list[tuple[str, Section, Document, str]] = []
        for rel in sorted(self._overlay_rels):
            if not rel.endswith(".ini"):
                continue
            d = self.I.ini_rel(rel)
            for sec in d.sections() if d else []:
                if sec.lname not in PREFIX_EXEMPT_SECTIONS:
                    cands += [(rel, sec, d, e.values[0]) for e in sec.entries("nickname")
                              if e.values and e.values[0]]
        for rel, sec, d in self._patch_new:
            if sec.lname not in PREFIX_EXEMPT_SECTIONS and sec.nickname:
                cands.append((rel, sec, d, sec.nickname))
        bad = [c for c in cands if not c[3].lower().startswith(MOD_PREFIX)]
        if not bad:
            return
        # pristine nicknames per namespace (a symbol table, else the section type), so a new
        # [Engine] named like a vanilla [Ship] still counts as new
        pristine: dict[str, set[str]] = defaultdict(set)
        for rel in self.I.iter_data_inis():
            if self.I.data_rel(rel) in self._overlay_rels:
                continue
            d = self.doc(rel)
            for sec in d.sections() if d else []:
                if id(sec) in self._overlay_secs:
                    continue
                nicks = self._sec_pristine_nicks.get(id(sec))
                if nicks is None:
                    nicks = [e.values[0] for e in sec.entries("nickname")
                             if e.values and e.values[0]]
                pristine[self._ns_of(sec)].update(n.lower() for n in nicks)
        seen = set()
        for rel, sec, d, nick in bad:
            ns = self._ns_of(sec)
            if nick.lower() in pristine[ns] or (ns, nick.lower()) in seen:
                continue
            seen.add((ns, nick.lower()))
            rel = report_rel(rel)
            self.add(ERROR, "C001", rel, nick, f"new nickname {nick!r} ([{sec.name}]) does not "
                     f"start with {MOD_PREFIX!r} (CONVENTIONS §2)", sec.entry("nickname") or sec,
                     d, overlay=True)

    # -- driver ------------------------------------------------------------------------------
    def run(self) -> Report:
        self.load()
        self.check_duplicates()
        self.check_loadouts()
        self.check_npcs()
        self.check_factions()
        self.check_model_files()
        self.check_universe()
        self.check_systems()
        self.check_encounters()
        self.check_goods_markets()
        self.check_sounds()
        self.check_ids()
        self.check_prefix()
        self.stats["models_parsed"] = sum(1 for v in self._models.values() if v is not None)
        order = {ERROR: 0, WARNING: 1, BASELINE: 2, INFO: 3}
        self.findings.sort(key=lambda f: (order.get(f.severity, 9), f.code, f.file.lower(),
                                          f.subject.lower()))
        return Report(self.findings, self.stats)


def validate(install: Install, **kw) -> Report:
    return Validator(install, **kw).run()


def main(argv: list[str] | None = None) -> int:
    import argparse
    from .install import default_hde_root
    ap = argparse.ArgumentParser(prog="flvalidate", description=__doc__.split("\n")[0])
    ap.add_argument("--install", default=str(default_hde_root()))
    ap.add_argument("--overlay")
    ap.add_argument("--baseline", help="allow-list file (default: tools/fltools/baseline_findings.txt)")
    ap.add_argument("--no-baseline", action="store_true")
    ap.add_argument("--no-hardpoints", action="store_true")
    ap.add_argument("--json", help="write the full report as JSON to this path")
    ap.add_argument("--write-baseline", help="write current WARNING/ERROR keys as a baseline file")
    ap.add_argument("--show", default="ERROR,WARNING", help="severities to print")
    a = ap.parse_args(argv)
    from .safety import PlayPrefixError, refuse_play_prefix
    try:
        for out in (a.json, a.write_baseline):
            if out:
                refuse_play_prefix(out)
    except PlayPrefixError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    base = set() if a.no_baseline else load_baseline(a.baseline)
    rep = validate(Install(a.install, a.overlay), baseline=base,
                   check_hardpoints=not a.no_hardpoints)
    show = {s.strip().upper() for s in a.show.split(",")}
    for f in rep.findings:
        if f.severity in show:
            print(f.render())
    counts = {s: rep.count(s) for s in (ERROR, WARNING, BASELINE, INFO)}
    print("summary:", " ".join(f"{k}={v}" for k, v in counts.items()))
    if a.json:
        Path(a.json).write_text(json.dumps(rep.to_json(), indent=1) + "\n", encoding="utf-8")
    if a.write_baseline:
        keys = sorted({f.key for f in rep.findings if f.severity in (ERROR, WARNING, BASELINE)})
        Path(a.write_baseline).write_text(
            "# fltools.validate baseline: findings stock HDE already has (CODE|file|subject).\n"
            "# Generated by `flvalidate --write-baseline`; review before committing.\n"
            + "\n".join(keys) + "\n", encoding="utf-8")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
