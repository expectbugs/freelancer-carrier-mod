"""fltools.worldexport golden-tested against R3's independent extracts (read at test time)."""
from __future__ import annotations

import collections
import subprocess
import sys

import pytest

from fltools import geometry, worldexport

R3_KIND = {"nomad_gate(hypergate)": "nomad_gate"}


def test_counts_match_r3(world, r3json, r3):
    graph = r3json("system_graph.json")
    assert len(world["systems"]) == len(graph)
    assert sorted(world["systems"]) == sorted(graph)
    r3_links = [l for v in graph.values() for l in v["links"]]
    assert len(world["links"]) == len(r3_links)
    assert collections.Counter(l["kind"] for l in world["links"]) == \
        collections.Counter(R3_KIND.get(l["kind"], l["kind"]) for l in r3_links)
    assert len(world["trade_lanes"]) == len(r3json("trade_lanes.json"))
    zones = [z for v in world["zones"].values() for z in v]
    assert len(zones) == len(r3json("zones_encounters.json"))
    rows = sum(len(e["factions"]) for z in zones for e in z["encounters"])
    with open(r3 / "zone_encounters_flat.tsv", encoding="utf-8") as fh:
        assert rows == sum(1 for _ in fh) - 1          # minus header


def test_links_match_r3_and_are_symmetric(world, r3json):
    graph = r3json("system_graph.json")
    r3 = {(s, l["via"], l["to"], l["to_object"], tuple(l["pos"])) for s, v in graph.items()
          for l in v["links"]}
    mine = {(l["from_system"], l["from_object"], l["to_system"], l["to_object"],
             tuple(l["from_pos"])) for l in world["links"]}
    assert mine == r3
    by_obj = {(l["from_system"].lower(), l["from_object"].lower()): l for l in world["links"]}
    for l in world["links"]:
        back = by_obj[(l["to_system"].lower(), l["to_object"].lower())]
        assert back["to_object"].lower() == l["from_object"].lower()
        assert back["from_pos"] == l["to_pos"]


def test_spot_values(world, r3json, install):
    graph = r3json("system_graph.json")
    # Hi02_to_Ew06_hole position, as R3 extracted it
    r3_hole = [l for l in graph["Hi02"]["links"] if l["via"] == "Hi02_to_Ew06_hole"][0]
    mine = [l for l in world["links"] if l["from_object"] == "Hi02_to_Ew06_hole"][0]
    assert mine["from_pos"] == r3_hole["pos"] and mine["kind"] == "jumphole"
    # the Li01 lane starting at ring Li01_Trade_Lane_Ring_16 (spec Task 6 spot value): names and
    # length as R3 extracted them (selected by nickname; no display strings in the repo, §12)
    r3_lanes = r3json("trade_lanes.json")
    ref = [t for t in r3_lanes if t["system"] == "Li01"
           and t["rings"][0].lower() == "li01_trade_lane_ring_16"][0]
    got = [t for t in world["trade_lanes"] if t["rings"] == ref["rings"]][0]
    assert (got["start_name"], got["end_name"], got["length_m"]) == \
        (ref["start_name"], ref["end_name"], ref["length_m"])
    # every lane identical in rings, positions and length. R3 resolved a missing
    # tradelane_space_name as IDS 0 (a placeholder string); we report None there.
    from fltools.peres import IdsResolver
    ids0 = IdsResolver.from_install(install).name(0)
    key = lambda t: (t["system"], tuple(t["rings"]))
    r3m = {key(t): t for t in r3_lanes}
    for t in world["trade_lanes"]:
        r = r3m[key(t)]
        assert t["ring_positions"] == r["ring_positions"] and t["length_m"] == r["length_m"]
        for mine_n, ref_n in ((t["start_name"], r["start_name"]), (t["end_name"], r["end_name"])):
            assert mine_n == ref_n or (mine_n is None and ref_n == ids0)


def test_zone_geometry_and_encounters_match_r3(world, r3json):
    ref = {(z["system"], z["zone"]): z for z in r3json("zones_encounters.json")}
    n = 0
    for sysn, zl in world["zones"].items():
        for z in zl:
            r = ref[(sysn, z["nickname"])]
            assert (z["shape"] or None) == ((r["shape"] or "").upper() or None)
            assert z["pos"] == r["pos"] and z["rotate"] == r["rotate"] and z["size"] == r["size"]
            assert z["encounters"] == r["encounters"]
            assert (z["density"] if z["density"] is None else str(z["density"])) == r["density"]
            assert (z["path_label"][0] if z["path_label"] else None) == \
                (r["path_label"][0] if r["path_label"] else None)
            n += 1
    assert n == len(ref)


def test_systems_and_objects(world, r3json):
    sysf = r3json("systems_full.json")["systems"]
    for nick, s in world["systems"].items():
        r = sysf[nick.lower()]
        assert s["name"] == r["name"] and s["navmap_pos"] == r["navmap_pos"]
    no_region = [n for n, s in world["systems"].items() if not s["region"]]
    assert len(no_region) <= 1, no_region            # Territory.ini covers all but the intro
    houses = {s["house"] for s in world["systems"].values() if s["house"]}
    assert len(houses) == 4
    for nick, objs in world["objects"].items():
        r_objs = {o["nickname"]: o for o in sysf[nick.lower()].get("objects", [])}
        for o in objs:
            if o["nickname"] in r_objs:
                ro = r_objs[o["nickname"]]
                assert o["pos"] == ro["pos"] and o["type"] == ro["solar_type"]
                assert o["base"] == ro["base"] and o["reputation"] == ro["reputation"]


def test_hazards_and_cd(world, r3json):
    kinds = collections.Counter(h["kind"] for v in world["hazards"].values() for h in v)
    for k in ("sun", "planet", "death_zone", "asteroid_field", "nebula", "exclusion"):
        assert kinds[k] > 0, k
    assert kinds["sun"] == sum(1 for v in world["objects"].values() for o in v
                               if o["type"] == "SUN")
    # death zones centred on planets/suns are attached to them
    attached = [h for v in world["hazards"].values() for h in v
                if h["kind"] == "death_zone" and h["object"]]
    assert len(attached) > 50
    # CD capability agrees with R3's join (faction -> npc ships with a cruise disruptor)
    fac = r3json("factions.json")["faction_capabilities"]
    for f, v in fac.items():
        if f in world["factions"]:
            mine = world["factions"][f]
            cd_any = any(x > 0 for x in mine["cd_fraction_by_level"].values())
            assert cd_any == bool(v["cd_ships"]), f


def test_deterministic(install, world):
    assert worldexport.dumps(worldexport.export(install)) == worldexport.dumps(world)


def _r3_exposure(r3, system, a, b):
    tool = r3 / "tools" / "route_exposure.py"
    if not tool.is_file():
        pytest.skip("R3 route_exposure.py not available")
    out = subprocess.run([sys.executable, "-I", str(tool), system, ",".join(map(str, a)),
                          ",".join(map(str, b))], capture_output=True, text=True, check=True,
                         cwd=str(r3 / "tools")).stdout
    res = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 6 and p[3] == "maxlvl":
            res[p[0]] = (int(p[1]), int(p[2]), int(p[4]), int(p[5]))
    return res


def test_route_exposure_parity_with_r3_reference(world, r3):
    """Our port on world.json == R3's reference script on its own extracts, for gate-to-gate
    legs picked from the data (including the R3 §3.4 Li01 example leg's gates)."""
    legs = worldexport.route_exposure_golden(world, systems=("Li01", "Br01", "Ku04"))
    assert legs
    nonzero = 0
    for leg in legs:
        ref = _r3_exposure(r3, leg["system"], leg["a"], leg["b"])
        mine = {f: (round(v["metres_inside"]), round(v["weighted"]), v["max_level"],
                    len(v["zones"])) for f, v in leg["result"].items()}
        assert mine == ref, leg["system"] + " " + leg["from"] + "->" + leg["to"]
        nonzero += bool(mine)
    assert nonzero > 0


def test_geometry_contains_conventions():
    z = {"shape": "CYLINDER", "pos": [0, 0, 0], "rotate": [0, 0, 90], "size": [10, 100]}
    a, b = geometry.cylinder_endpoints(z)          # +Y axis rotated 90 deg about Z -> -X
    assert a[0] == pytest.approx(50) and b[0] == pytest.approx(-50)
    assert geometry.contains(z, [40, 0, 0]) and not geometry.contains(z, [0, 40, 0])
    box = {"shape": "BOX", "pos": [0, 0, 0], "rotate": [0, 0, 0], "size": [10, 20, 30]}
    assert geometry.contains(box, [4.9, 9.9, 14.9]) and not geometry.contains(box, [5.1, 0, 0])
    assert geometry.contains({"shape": "SPHERE", "pos": [1, 1, 1], "size": [2]}, [2, 2, 2])
