"""Nickname hash-collision scan (CreateID, 30-bit) and faction-hash scan (MakeId, 16-bit).

Nicknames are collected from every ``nickname =`` key in every active section of every INI under
DATA (install + overlay, overlay patches applied). Nicknames are case-insensitive (the game
lower-cases before hashing), so case-only spellings are one object; distinct lower-case names
whose CreateID is equal are a collision (ERROR). Factions are the ``[Group]`` nicknames of the
``groups`` file(s) in ``[Data]`` (``InitialWorld.ini``); a faction-hash collision is an ERROR
(about a 1/1200 chance per new faction against HDE's 55; R4 §A1.3).

Counting note (VERIFIED on HDE 0.7.1.1): this scan finds 24,900 unique nicknames. R4 reported
24,877 because its regex stopped at the first blank: 26 HDE nicknames contain spaces
(e.g. ``Br03_Com Sat_1``) and collapsed into 3 truncated names. The engine reads the full value
(params run to ``;``, only the ends are trimmed), so 24,900 is the right count;
``legacy_regex_count`` reproduces R4's number for comparison.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

from .hash import create_id, faction_id
from .install import Install

__all__ = ["HashScan", "scan", "main"]

_LEGACY_RX = re.compile(r"^\s*nickname\s*=\s*([^;\s,]+)", re.I | re.M)


@dataclass
class HashScan:
    nicknames: dict[str, set[str]] = field(default_factory=dict)   # lower -> {data-rel files}
    spellings: dict[str, set[str]] = field(default_factory=dict)   # lower -> {spellings}
    factions: list[str] = field(default_factory=list)
    createid_collisions: list[list[str]] = field(default_factory=list)
    faction_collisions: list[list[str]] = field(default_factory=list)
    legacy_regex_count: int = 0
    new_nicknames: set[str] = field(default_factory=set)   # only in overlay files

    @property
    def ok(self) -> bool:
        return not self.createid_collisions and not self.faction_collisions

    def summary(self) -> dict:
        return {
            "unique_nicknames": len(self.nicknames),
            "legacy_regex_count": self.legacy_regex_count,
            "createid_collisions": self.createid_collisions,
            "factions": len(self.factions),
            "faction_collisions": self.faction_collisions,
            "case_variant_groups": sum(1 for v in self.spellings.values() if len(v) > 1),
            "nicknames_with_blanks": sorted(n for n in self.nicknames if " " in n or "\t" in n),
            "overlay_new_nicknames": len(self.new_nicknames),
        }


def scan(install: Install) -> HashScan:
    res = HashScan()
    nick_files: dict[str, set[str]] = defaultdict(set)
    spell: dict[str, set[str]] = defaultdict(set)
    legacy: set[str] = set()
    overlay_rels = {r.lower() for r in install.overlay_files()}
    in_install: set[str] = set()
    for rel in install.iter_data_inis():
        doc = install.data_ini(rel)
        if doc is None:
            continue
        p = install.data_path(rel)
        if p is not None:
            for m in _LEGACY_RX.finditer(p.read_bytes().decode("latin-1")):
                legacy.add(m.group(1).lower())
        from_overlay = install.data_rel(rel) in overlay_rels
        for sec in doc.sections():
            for e in sec.entries("nickname"):
                if not e.values or not e.values[0]:
                    continue
                n = e.values[0]
                ln = n.lower()
                nick_files[ln].add(rel)
                spell[ln].add(n)
                if not from_overlay:
                    in_install.add(ln)
    res.nicknames = dict(nick_files)
    res.spellings = dict(spell)
    res.legacy_regex_count = len(legacy)
    res.new_nicknames = set(nick_files) - in_install

    by_hash: dict[int, list[str]] = defaultdict(list)
    for ln in sorted(nick_files):
        by_hash[create_id(ln)].append(ln)
    res.createid_collisions = [v for v in by_hash.values() if len(v) > 1]

    facs: list[str] = []
    seen = set()
    for rel in install.data_files("groups"):
        doc = install.data_ini(rel)
        for sec in doc.sections("Group") if doc else []:
            n = sec.nickname
            if n and n.lower() not in seen:
                seen.add(n.lower())
                facs.append(n)
    res.factions = facs
    fh: dict[int, list[str]] = defaultdict(list)
    for f in facs:
        fh[faction_id(f)].append(f)
    res.faction_collisions = [v for v in fh.values() if len(v) > 1]
    return res


def main(argv: list[str] | None = None) -> int:
    import argparse
    from .install import default_hde_root
    ap = argparse.ArgumentParser(prog="flhashscan", description=__doc__.split("\n")[0])
    ap.add_argument("--install", default=str(default_hde_root()))
    ap.add_argument("--overlay")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = scan(Install(a.install, a.overlay))
    s = r.summary()
    if a.json:
        print(json.dumps(s, indent=1, sort_keys=True))
    else:
        print(f"unique nicknames: {s['unique_nicknames']} (legacy regex count "
              f"{s['legacy_regex_count']}); CreateID collisions: {len(r.createid_collisions)}")
        for c in r.createid_collisions:
            print("  COLLISION", c, hex(create_id(c[0])))
        print(f"factions: {s['factions']}; faction-hash collisions: {len(r.faction_collisions)}")
        for c in r.faction_collisions:
            print("  COLLISION", c, faction_id(c[0]))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
