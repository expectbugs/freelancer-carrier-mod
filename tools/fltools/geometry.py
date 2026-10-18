"""Zone and object geometry conventions, and the reference route-exposure algorithm.

Conventions (VERIFIED, R3 §3.4: empirical patrol-path continuity test on 2,172 joints, and
Librelancer ``Zone.cs::ContainsPoint``):

- ``rotate = (rx, ry, rz)`` in degrees; ``world = Rz(rz) @ Ry(ry) @ Rx(rx) @ local``
  (column vectors).
- SPHERE ``size = r``; ELLIPSOID ``size = (a, b, c)`` semi-axes; BOX ``size = (x, y, z)`` full
  extents; CYLINDER (and RING, treated the same here) ``size = (radius, length)`` along local +Y,
  centred on ``pos``.

:func:`exposure` is a port of ``R3-data/tools/route_exposure.py`` onto ``world.json`` data, kept
numerically identical so W1-WORLD can golden-test its own implementation against it.
"""
from __future__ import annotations

import math

__all__ = ["rot", "mv", "mtv", "contains", "cylinder_endpoints", "exposure",
           "COMBAT_PREFIXES", "HOSTILE_THRESHOLD"]

COMBAT_PREFIXES = ("patrolp_", "area_assault", "area_defend", "area_scout", "area_bh_",
                   "area_gunboats", "area_nomads", "patrolp_gunboats")
HOSTILE_THRESHOLD = -0.6   # Librelancer Faction.cs; UNVERIFIED against the exe (R3 §8)


def _R(axis: str, deg: float):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    if axis == "y":
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def _mm(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def rot(rx: float, ry: float, rz: float):
    """3x3 rotation for an FL ``rotate = rx, ry, rz`` (degrees)."""
    return _mm(_mm(_R("z", rz), _R("y", ry)), _R("x", rx))


def mv(M, v):
    return [sum(M[i][k] * v[k] for k in range(3)) for i in range(3)]


def mtv(M, v):
    """``transpose(M) @ v`` (world -> local for a rotation)."""
    return [sum(M[k][i] * v[k] for k in range(3)) for i in range(3)]


def _vec3(v, fill=0.0):
    v = list(v or [])
    return (v + [fill] * 3)[:3]


def contains(zone: dict, p) -> bool:
    """Is world point ``p`` inside ``zone`` (``shape``, ``pos``, ``rotate``, ``size``)?"""
    pos = _vec3(zone.get("pos"))
    d = [p[i] - pos[i] for i in range(3)]
    shape = (zone.get("shape") or "").upper()
    sz = list(zone.get("size") or [0.0])
    if shape == "SPHERE":
        return math.dist(p, pos) <= sz[0]
    M = rot(*_vec3(zone.get("rotate")))
    loc = mtv(M, d)
    if shape == "ELLIPSOID":
        a, b, c = (sz + sz[-1:] * 3)[:3]
        return (loc[0] / a) ** 2 + (loc[1] / b) ** 2 + (loc[2] / c) ** 2 <= 1.0
    if shape == "BOX":
        return all(abs(loc[i]) <= sz[i] / 2 for i in range(min(3, len(sz))))
    if shape in ("CYLINDER", "RING"):
        r, length = sz[0], (sz[1] if len(sz) > 1 else 0.0)
        return abs(loc[1]) <= length / 2 and (loc[0] ** 2 + loc[2] ** 2) <= r * r
    return False


def cylinder_endpoints(zone: dict):
    """World endpoints of a CYLINDER zone's axis: ``pos -/+ R @ (0, length/2, 0)``."""
    sz = list(zone.get("size") or [0.0, 0.0])
    half = mv(rot(*_vec3(zone.get("rotate"))), [0, (sz[1] if len(sz) > 1 else 0.0) / 2, 0])
    p = _vec3(zone.get("pos"))
    return [p[i] - half[i] for i in range(3)], [p[i] + half[i] for i in range(3)]


def exposure(world: dict, system: str, a, b, rep: dict | None = None, step: float = 500.0,
             hostile_threshold: float = HOSTILE_THRESHOLD) -> dict:
    """Per-faction exposure along the straight leg ``a -> b`` (metres) in ``system``.

    exposure = sum over zones/encounters of (metres inside zone) * density * chance * weight,
    counting only combat encounters of factions with ``rep <= hostile_threshold``. ``rep``
    defaults to ``world["player_start_reps"]``. Same sampling as the R3 reference: ``n =
    max(1, L // step)`` segments, ``n + 1`` sample points, each worth ``L / n`` metres.
    """
    zones = [z for z in world.get("zones", {}).get(_sys_key(world, system), []) if z["encounters"]]
    rep = rep if rep is not None else world.get("player_start_reps", {})
    L = math.dist(a, b)
    n = max(1, int(L // step))
    pts = [[a[i] + (b[i] - a[i]) * k / n for i in range(3)] for k in range(n + 1)]
    seg = L / n
    out: dict[str, dict] = {}
    for z in zones:
        inside = sum(1 for p in pts if contains(z, p)) * seg
        if inside <= 0:
            continue
        dens = float(z.get("density") or 0)
        for e in z["encounters"]:
            if not e["encounter"].lower().startswith(COMBAT_PREFIXES):
                continue
            for f, w in e["factions"]:
                r = rep.get(f, 0.0)
                if r > hostile_threshold:
                    continue
                k = out.setdefault(f, {"metres_inside": 0.0, "weighted": 0.0, "max_level": 0,
                                       "zones": set()})
                k["metres_inside"] += inside
                k["weighted"] += inside * dens * (e.get("chance") or 0) * w
                k["max_level"] = max(k["max_level"], e.get("level") or 0)
                k["zones"].add(z["nickname"])
    for f in out:
        out[f]["zones"] = sorted(out[f]["zones"])
    return out


def _sys_key(world: dict, system: str) -> str:
    zs = world.get("zones", {})
    if system in zs:
        return system
    for k in zs:
        if k.lower() == system.lower():
            return k
    return system
