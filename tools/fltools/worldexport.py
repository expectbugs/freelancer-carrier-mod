"""Export ``world.json`` (systems, links, objects, hazards, trade lanes, encounter zones,
faction CD capability) from an install, optionally combined with an overlay.

Built at deploy time into ``$FLMOD_LOCAL/gen/`` and never committed (CONVENTIONS §12). The
schema is documented in ``gen/framework/WORLD_JSON.md``. Ported and extended from R3's
``extract_universe.py`` / ``extract_factions.py`` / ``route_exposure.py``; the tests compare the
counts and spot values against R3's JSON extracts at test time.

Output is deterministic: same install bytes -> same JSON bytes (no paths, no timestamps).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

from . import geometry
from .hash import create_id
from .ini import Document, Section
from .install import Install
from .peres import IdsResolver

SCHEMA = "fcm.world.v1"
CD_EQUIPMENT = {"cruise_disruptor01_mark01", "cruise_disruptor01_mark02",
                "nomad_cruise_disruptor01"}

__all__ = ["export", "dumps", "write", "route_exposure_golden", "main", "SCHEMA"]


def _num(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except ValueError:
        try:
            f = float(v)
        except ValueError:
            return None
        return int(f) if f.is_integer() and "e" not in v.lower() and "." not in v else f


def _floats(vals, n: int | None = None, default=None):
    if vals is None:
        return default
    out = []
    for v in vals:
        try:
            out.append(float(v))
        except ValueError:
            out.append(0.0)
    if n is not None:
        out = (out + [0.0] * n)[:n]
    return out


def _expand_systems(spec: str) -> list[str]:
    """Territory.ini ranges: ``Li01-5`` -> Li01..Li05, ``St02c`` -> St02c."""
    out = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        m = re.match(r"^([A-Za-z]+)(\d+)-(\d+)$", part)
        if m:
            pre, a, b = m.group(1), m.group(2), int(m.group(3))
            for i in range(int(a), b + 1):
                out.append(f"{pre}{i:0{len(a)}d}")
        else:
            out.append(part)
    return out


class _Exporter:
    def __init__(self, install: Install):
        self.I = install
        self.ids = IdsResolver.from_install(install)

    def name(self, v) -> str | None:
        n = _num(v)
        if not isinstance(n, int) or n <= 0:
            return None
        return self.ids.name(n)

    # ----------------------------------------------------------------------------------------
    def regions(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        d = self.I.data_ini(r"universe\Territory.ini")
        if d is None:
            return out
        for sec in d.sections(include_disabled=True):
            ln = sec.lname.lstrip(";")
            if ln not in ("houses", "systems"):
                continue
            house_name = None
            fmt = None
            for e in sec.entries():
                k = e.lkey
                if k == "house_id":
                    house_name = self.name(e.value(0))
                elif k == "format":
                    fmt = e.params
                    if ln == "houses":
                        # the houses' format line closes the house list: apply to all
                        for v in out.values():
                            if v.get("_pending"):
                                v["region"] = fmt.replace("%s System, ", "", 1) \
                                    .replace("%s", v["house"] or "").rstrip(".").strip()
                                del v["_pending"]
                elif k == "systems":
                    for s in _expand_systems(e.params):
                        if ln == "houses":
                            out[s.lower()] = {"house": house_name, "_pending": True,
                                              "region": None}
                        else:
                            reg = (fmt or "").replace("%s System, ", "", 1).rstrip(".").strip()
                            out[s.lower()] = {"house": None, "region": reg or None}
        for v in out.values():
            v.pop("_pending", None)
        return out

    def solars(self) -> dict[str, Section]:
        out = {}
        for rel in self.I.data_files("solar"):
            d = self.I.data_ini(rel)
            for s in d.sections("Solar") if d else []:
                if s.nickname:
                    out.setdefault(s.nickname.lower(), s)
        return out

    # ----------------------------------------------------------------------------------------
    def run(self) -> dict:
        I = self.I
        solar = self.solars()
        regions = self.regions()
        uni_rel = I.data_files("universe")[0]
        uni_dir = os.path.dirname(uni_rel.replace("\\", "/"))
        uni = I.data_ini(uni_rel)
        systems: dict[str, dict] = {}
        sys_docs: dict[str, tuple[str, Document]] = {}
        for s in uni.sections("system"):
            nick = s.nickname
            if not nick:
                continue
            f = s.get1("file")
            rel = (uni_dir + "/" + f.replace("\\", "/")) if f else None
            reg = regions.get(nick.lower(), {})
            systems[nick] = {
                "nickname": nick, "name": self.name(s.get1("strid_name")),
                "strid_name": _num(s.get1("strid_name")),
                "ids_info": _num(s.get1("ids_info")),
                "navmap_pos": _floats(s.getv("pos"), 2, [0.0, 0.0]),
                "region": reg.get("region"), "house": reg.get("house"),
                "file": f, "visit": _num(s.get1("visit")),
                "navmapscale": _num(s.get1("NavMapScale")),
            }
            d = I.data_ini(rel) if rel else None
            if d is not None:
                sys_docs[nick] = (rel, d)
            else:
                systems[nick]["missing_file"] = True

        # objects
        objects: dict[str, list[dict]] = {}
        obj_index: dict[tuple[str, str], dict] = {}
        rings: dict[str, dict[str, dict]] = {}
        for sysn, (rel, d) in sys_docs.items():
            lst = []
            rings[sysn] = {}
            for s in d.sections("Object"):
                nick = s.nickname
                if not nick:
                    continue
                arch = s.get1("archetype") or ""
                sa = solar.get(arch.lower())
                stype = sa.get1("type") if sa else None
                radius = _num(sa.get1("solar_radius")) if sa else None
                if radius is None and stype in ("PLANET", "SUN"):
                    m = re.search(r"_(\d+)$", arch)
                    radius = int(m.group(1)) if m else None
                o = {"nickname": nick, "archetype": arch or None, "type": stype,
                     "pos": _floats(s.getv("pos"), 3, [0.0, 0.0, 0.0]),
                     "rotate": _floats(s.getv("rotate"), 3, [0.0, 0.0, 0.0]),
                     "ids_name": _num(s.get1("ids_name")), "name": self.name(s.get1("ids_name")),
                     "base": s.get1("base"), "dock_with": s.get1("dock_with"),
                     "reputation": s.get1("reputation"), "loadout": s.get1("loadout"),
                     "parent": s.get1("parent"), "visit": _num(s.get1("visit")),
                     "ids_info": _num(s.get1("ids_info")),
                     "atmosphere_range": _num(s.get1("atmosphere_range")),
                     "radius": radius, "dockable": bool(sa and sa.has("docking_sphere")),
                     "death_zone_radius": None, "exclusion_radius": None}
                g = s.getv("goto")
                if g:
                    o["goto"] = {"system": g[0], "object": g[1] if len(g) > 1 else None,
                                 "tunnel": g[2] if len(g) > 2 else None}
                if arch.lower() == "trade_lane_ring":
                    o["next_ring"] = s.get1("next_ring")
                    o["prev_ring"] = s.get1("prev_ring")
                    o["tradelane_space_name"] = _num(s.get1("tradelane_space_name"))
                    rings[sysn][nick] = o
                lst.append(o)
                obj_index[(sysn.lower(), nick.lower())] = o
            objects[sysn] = lst

        # zones, hazards
        zones: dict[str, list[dict]] = {}
        hazards: dict[str, list[dict]] = {}
        for sysn, (rel, d) in sys_docs.items():
            zl, hz = self._zones(sysn, d, objects[sysn])
            zones[sysn] = zl
            hazards[sysn] = hz

        links = self._links(sys_docs, objects, obj_index, solar)
        lanes = self._lanes(rings)
        return {
            "schema": SCHEMA,
            "source": self._source(),
            "conventions": {
                "units": "metres; angles in degrees",
                "rotate": "world = Rz(rz) @ Ry(ry) @ Rx(rx) @ local (column vectors)",
                "shapes": {"SPHERE": "size = [r]", "ELLIPSOID": "size = [a, b, c] semi-axes",
                           "BOX": "size = [x, y, z] full extents",
                           "CYLINDER": "size = [radius, length], axis local +Y, centred on pos",
                           "RING": "as CYLINDER (inner radius ignored)"},
                "ids": "global IDS = dll_index * 65536 + local id",
            },
            "systems": systems,
            "links": links,
            "objects": objects,
            "hazards": hazards,
            "trade_lanes": lanes,
            "zones": zones,
            "factions": self._factions(),
            "player_start_reps": self._start_reps(),
        }

    def _source(self) -> dict:
        h = hashlib.sha256()
        for rel in ("EXE/freelancer.ini",):
            b = self.I.read_bytes_rel(rel)
            if b:
                h.update(b)
        uni = self.I.data_files("universe")
        b = self.I.read_bytes_rel(self.I.data_rel(uni[0])) if uni else None
        if b:
            h.update(b)
        return {"freelancer_ini_universe_sha256": h.hexdigest(),
                "resource_dlls": self.ids.names}

    # ----------------------------------------------------------------------------------------
    def _zones(self, sysn: str, d: Document, objs: list[dict]):
        zl: list[dict] = []
        hz: list[dict] = []
        zone_secs = {}
        for s in d.sections("zone"):
            if s.nickname:
                zone_secs[s.nickname.lower()] = s
        # fields + their exclusions
        fields = []
        excl_of: dict[str, list[str]] = {}
        for kind, secname in (("asteroid_field", "Asteroids"), ("nebula", "Nebula")):
            for s in d.sections(secname):
                zn, f = s.get1("zone"), s.get1("file")
                fd = self.I.data_ini(f) if f else None
                excl = []
                for es in fd.sections("Exclusion Zones") if fd else []:
                    for e in es.entries("exclusion"):
                        if e.value(0):
                            excl.append(e.value(0))
                            excl_of.setdefault(e.value(0).lower(), []).append(zn)
                fields.append((kind, zn, f, excl))

        def geom(s: Section) -> dict:
            return {"shape": (s.get1("shape") or "").upper() or None,
                    "pos": _floats(s.getv("pos"), 3, [0.0, 0.0, 0.0]),
                    "rotate": _floats(s.getv("rotate"), 3, [0.0, 0.0, 0.0]),
                    "size": _floats(s.getv("size"), None, [0.0])}

        for kind, zn, f, excl in fields:
            s = zone_secs.get((zn or "").lower())
            h = {"kind": kind, "zone": zn, "file": f, "exclusions": excl}
            if s is not None:
                h.update(geom(s))
                for k in ("damage", "interference", "drag_modifier", "property_flags"):
                    v = _num(s.get1(k))
                    if v is not None:
                        h[k] = v
            else:
                h["missing_zone"] = True
            hz.append(h)

        def near_obj(pos, tol=1.0):
            for o in objs:
                if math.dist(o["pos"], pos) <= tol:
                    return o
            return None

        field_zones = {(zn or "").lower() for _k, zn, _f, _e in fields}
        for s in d.sections("zone"):
            zn = s.nickname
            if not zn:
                continue
            g = geom(s)
            dmg = _num(s.get1("damage"))
            if dmg and dmg > 0 and zn.lower() not in field_zones:
                o = near_obj(g["pos"]) if g["shape"] == "SPHERE" else None
                if o is not None:
                    o["death_zone_radius"] = g["size"][0]
                hz.append({"kind": "death_zone", "zone": zn, **g, "damage": dmg,
                           "object": o["nickname"] if o else None})
            if zn.lower() in excl_of:
                o = near_obj(g["pos"]) if g["shape"] == "SPHERE" else None
                if o is not None:
                    o["exclusion_radius"] = max(o["exclusion_radius"] or 0.0, g["size"][0])
                hz.append({"kind": "exclusion", "zone": zn, **g,
                           "fields": excl_of[zn.lower()],
                           "object": o["nickname"] if o else None})
            elif zn.lower() not in field_zones and not (dmg and dmg > 0):
                eff = {k: _num(s.get1(k)) for k in ("interference", "drag_modifier")
                       if _num(s.get1(k)) is not None}
                if eff:
                    hz.append({"kind": "effect_zone", "zone": zn, **g, **eff})

            # encounter zones
            encs: list[dict] = []
            facs: list[list] = []
            cur = None
            for e in s.entries():
                if e.lkey == "encounter":
                    v = e.values
                    cur = {"encounter": v[0] if v else None,
                           "level": int(float(v[1])) if len(v) > 1 and v[1] else None,
                           "chance": float(v[2]) if len(v) > 2 and v[2] else None,
                           "factions": []}
                    encs.append(cur)
                elif e.lkey == "faction":
                    v = e.values
                    pair = [v[0] if v else None, float(v[1]) if len(v) > 1 and v[1] else 1.0]
                    facs.append(pair)
                    if cur is not None:
                        cur["factions"].append(list(pair))
            path = s.getv("path_label")
            if not encs and not path:
                continue
            zl.append({"nickname": zn, **g, "comment": s.get1("comment"),
                       "ids_name": _num(s.get1("ids_name")),
                       "toughness": _num(s.get1("toughness")),
                       "density": _num(s.get1("density")),
                       "repop_time": _num(s.get1("repop_time")),
                       "max_battle_size": _num(s.get1("max_battle_size")),
                       "relief_time": _num(s.get1("relief_time")),
                       "pop_type": s.getv("pop_type"),
                       "path_label": [path[0], _num(path[1]) if len(path) > 1 else None]
                       if path else None,
                       "usage": s.get1("usage"),
                       "mission_eligible": s.get1("mission_eligible"),
                       "density_restriction": [[_num(v[0]), v[1] if len(v) > 1 else None]
                                               for v in s.getallv("density_restriction")],
                       "attack_ids": _num(s.get1("attack_ids")),
                       "tradelane_attack": _num(s.get1("tradelane_attack")),
                       "property_flags": _num(s.get1("property_flags")),
                       "encounters": encs, "factions": facs})
        for o in objs:
            if o["type"] in ("SUN", "PLANET"):
                hz.append({"kind": o["type"].lower(), "object": o["nickname"], "pos": o["pos"],
                           "radius": o["radius"], "death_zone_radius": o["death_zone_radius"]})
        return zl, hz

    def _locks(self) -> tuple[dict[int, set[str]], set[int]]:
        player: dict[int, set[str]] = {}
        npc: set[int] = set()

        def val(e):
            v = e.value(0)
            n = _num(v)
            return n if isinstance(n, int) else (create_id(v) if v else None)

        for rel in self.I.data_files("groups") or ["initialworld.ini"]:
            d = self.I.data_ini(rel)
            for s in d.sections("locked_gates") if d else []:
                for e in s.entries():
                    h = val(e)
                    if h is None:
                        continue
                    if e.lkey == "locked_gate":
                        player.setdefault(h, set()).add("initialworld")
                    elif e.lkey == "npc_locked_gate":
                        npc.add(h)
        np = self.I.exe_ini("newplayer.fl")
        for s in np.sections() if np else []:
            for e in s.entries("locked_gate"):
                h = val(e)
                if h is not None:
                    player.setdefault(h, set()).add("newplayer")
        return player, npc

    def _links(self, sys_docs, objects, obj_index, solar) -> list[dict]:
        player, npc = self._locks()
        out = []
        for sysn in sys_docs:
            for o in objects[sysn]:
                g = o.get("goto")
                if not g:
                    continue
                arch = (o["archetype"] or "").lower()
                st = (solar[arch].get1("type") if arch in solar else "") or ""
                if arch == "nomad_gate":
                    kind = "nomad_gate"
                elif st == "AIRLOCK_GATE" or "airlock" in arch:
                    kind = "airlock"
                elif st == "JUMP_GATE" or ("gate" in arch and "hole" not in arch):
                    kind = "jumpgate"
                else:
                    kind = "jumphole"
                tgt = obj_index.get(((g["system"] or "").lower(), (g["object"] or "").lower()))
                h = create_id(o["nickname"])
                out.append({"from_system": sysn, "to_system": g["system"],
                            "from_object": o["nickname"], "to_object": g["object"],
                            "tunnel": g["tunnel"], "kind": kind, "archetype": o["archetype"],
                            "from_pos": o["pos"], "to_pos": tgt["pos"] if tgt else None,
                            "reputation": o["reputation"], "name": o["name"],
                            "locked_player": h in player,
                            "lock_sources": sorted(player.get(h, set())),
                            "locked_npc": h in npc})
        return out

    def _lanes(self, rings: dict[str, dict[str, dict]]) -> list[dict]:
        out = []
        for sysn, rs in rings.items():
            seen: set[str] = set()
            for n, r in rs.items():
                if r["prev_ring"] and r["prev_ring"] in rs:
                    continue
                chain = []
                cur = n
                while cur and cur in rs and cur not in seen:
                    seen.add(cur)
                    chain.append(rs[cur])
                    cur = rs[cur]["next_ring"]
                if not chain:
                    continue
                out.append({
                    "system": sysn, "rings": [c["nickname"] for c in chain],
                    "ring_positions": [c["pos"] for c in chain],
                    "start_pos": chain[0]["pos"], "end_pos": chain[-1]["pos"],
                    "start_name": self.name(chain[0]["tradelane_space_name"]),
                    "end_name": self.name(chain[-1]["tradelane_space_name"]),
                    "reputation": chain[0]["reputation"],
                    "length_m": round(sum(math.dist(chain[i]["pos"], chain[i + 1]["pos"])
                                          for i in range(len(chain) - 1)))})
        return out

    def _factions(self) -> dict:
        I = self.I
        loadouts = {}
        for rel in I.data_files("loadouts"):
            d = I.data_ini(rel)
            for s in d.sections("Loadout") if d else []:
                if s.nickname:
                    loadouts.setdefault(s.nickname.lower(), s)
        cd_equip = set(CD_EQUIPMENT)
        for rel in I.data_files("equipment"):
            d = I.data_ini(rel)
            for s in d.sections("CruiseDisruptor") if d else []:
                if s.nickname:
                    cd_equip.add(s.nickname.lower())
        npcs = {}
        nd = I.data_ini(r"missions\npcships.ini")
        for s in nd.sections("NPCShipArch") if nd else []:
            if not s.nickname:
                continue
            lo = loadouts.get((s.get1("loadout") or "").lower())
            cd = bool(lo and any((e.value(0) or "").lower() in cd_equip
                                 for e in lo.entries("equip")))
            classes = [c.lower() for v in s.getallv("npc_class") for c in v]
            levels = sorted({int(c[1:]) for c in classes if re.fullmatch(r"d\d+", c)})
            npcs[s.nickname.lower()] = {"cd": cd, "levels": levels, "classes": classes}
        groups = {}
        for rel in I.data_files("groups"):
            d = I.data_ini(rel)
            for s in d.sections("Group") if d else []:
                if s.nickname:
                    groups.setdefault(s.nickname, s)
        props = {}
        fp = I.data_ini(r"missions\faction_prop.ini")
        for s in fp.sections("FactionProps") if fp else []:
            a = s.get1("affiliation")
            if a and a.lower() not in props:
                props[a.lower()] = s
        out = {}
        for nick, g in groups.items():
            p = props.get(nick.lower())
            ships = [npcs[n.lower()] for n in (p.getall("npc_ship") if p else [])
                     if n.lower() in npcs]
            by_level: dict[str, list[int]] = {}
            for sh in ships:
                for lv in sh["levels"]:
                    t = by_level.setdefault(str(lv), [0, 0])
                    t[0] += 1
                    t[1] += 1 if sh["cd"] else 0
            out[nick] = {
                "name": self.name(g.get1("ids_name")),
                "short_name": self.name(g.get1("ids_short_name")),
                "legality": p.get1("legality") if p else None,
                "n_npc_ships": len(ships),
                "npc_ships_by_level": {k: v[0] for k, v in sorted(by_level.items(),
                                                                  key=lambda kv: int(kv[0]))},
                "cd_fraction_by_level": {k: round(v[1] / v[0], 6) for k, v in
                                         sorted(by_level.items(), key=lambda kv: int(kv[0]))},
            }
        return out

    def _start_reps(self) -> dict:
        out = {}
        np = self.I.exe_ini("newplayer.fl")
        for s in np.sections() if np else []:
            for e in s.entries("house"):
                v = e.values
                if len(v) >= 2:
                    try:
                        out[v[1]] = float(v[0])
                    except ValueError:
                        pass
        return out


def export(install: Install) -> dict:
    return _Exporter(install).run()


def dumps(world: dict) -> str:
    return json.dumps(world, indent=1, ensure_ascii=False) + "\n"


def write(world: dict, path: str | os.PathLike) -> Path:
    from .safety import refuse_play_prefix
    p = Path(path)
    refuse_play_prefix(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(dumps(world), encoding="utf-8")
    os.replace(tmp, p)
    return p


def route_exposure_golden(world: dict, systems=("Li01", "Br01", "Ku01", "Rh01", "Bw10",
                                                "Hi02")) -> list[dict]:
    """Reference exposures for gate-to-gate legs (from world data, not hard-coded) so W1-WORLD
    can golden-test its own implementation (``$FLMOD_GOLDEN/route_exposure/``)."""
    out = []
    for sysn in systems:
        gates = [l for l in world["links"] if l["from_system"].lower() == sysn.lower()]
        gates.sort(key=lambda l: l["from_object"].lower())
        for a, b in zip(gates, gates[1:3]):
            res = geometry.exposure(world, sysn, a["from_pos"], b["from_pos"])
            out.append({"system": sysn, "from": a["from_object"], "to": b["from_object"],
                        "a": a["from_pos"], "b": b["from_pos"], "rep": "player_start_reps",
                        "step": 500.0, "hostile_threshold": geometry.HOSTILE_THRESHOLD,
                        "result": {f: {"metres_inside": v["metres_inside"],
                                       "weighted": v["weighted"], "max_level": v["max_level"],
                                       "zones": v["zones"]}
                                   for f, v in sorted(res.items())}})
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    from .install import default_hde_root
    local = Path(os.environ.get("FLMOD_LOCAL", "/home/user/freelancer/carrier-mod/local"))
    ap = argparse.ArgumentParser(prog="flworldexport", description=__doc__.split("\n")[0])
    ap.add_argument("--install", default=str(default_hde_root()))
    ap.add_argument("--overlay")
    ap.add_argument("--out", default=str(local / "gen" / "world.json"))
    ap.add_argument("--route-exposure-golden", metavar="DIR",
                    help="also write reference exposures to DIR/route_exposure.json")
    a = ap.parse_args(argv)
    from .safety import PlayPrefixError, refuse_play_prefix
    try:
        # refuse the output paths before the (slow) export: a refusal costs nothing
        refuse_play_prefix(a.out)
        if a.route_exposure_golden:
            refuse_play_prefix(Path(a.route_exposure_golden) / "route_exposure.json")
        w = export(Install(a.install, a.overlay))
        p = write(w, a.out)
        print(f"wrote {p}: {len(w['systems'])} systems, {len(w['links'])} links, "
              f"{len(w['trade_lanes'])} lanes, {sum(len(v) for v in w['zones'].values())} zones")
        if a.route_exposure_golden:
            d = Path(a.route_exposure_golden)
            d.mkdir(parents=True, exist_ok=True)
            (d / "route_exposure.json").write_text(
                json.dumps(route_exposure_golden(w), indent=1) + "\n", encoding="utf-8")
            print(f"wrote {d / 'route_exposure.json'}")
    except (PlayPrefixError, OSError, ValueError) as e:
        print(f"ERROR: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
