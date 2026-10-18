"""fltools.hashscan on stock HDE and on overlays with forced collisions."""
from __future__ import annotations

import itertools
import json
import os
import random
import re
import string

import pytest

from fltools import hashscan
from fltools.hash import create_id, faction_id
from fltools.install import Install


def _r4_numbers(research):
    """R4 §A1.3 states the baseline in prose; read it at test time (not hard-coded)."""
    txt = (research / "R4-lore-and-testloop.md").read_text(encoding="utf-8")
    m = re.search(r"([\d,]+) unique nicknames, 0 CreateID collisions; (\d+) factions, 0 FLFacHash",
                  txt)
    if not m:
        pytest.skip("R4 baseline sentence not found")
    return int(m.group(1).replace(",", "")), int(m.group(2))


def test_stock_hde(install, research):
    r4_nicks, r4_factions = _r4_numbers(research)
    r = hashscan.scan(install)
    assert r.createid_collisions == [] and r.faction_collisions == []
    assert r.legacy_regex_count == r4_nicks            # R4's method reproduces R4's number
    assert len(r.factions) == r4_factions
    # The engine reads full values: the only difference from R4's regex count are nicknames
    # containing blanks, which the regex truncated (explained in hashscan's docstring).
    extra = [n for n in r.nicknames if " " in n or "\t" in n]
    truncated = {re.split(r"[\s;,]", n, maxsplit=1)[0] for n in extra}
    assert len(r.nicknames) == r4_nicks + len(extra) - len(truncated - set(r.nicknames))
    assert not r.new_nicknames


def _collide(prefix: str, fn, bits: int):
    """Birthday search with seeded random suffixes (CRC hashes are linear, so sequential
    names collide far less often than random ones)."""
    rng = random.Random(1234)
    seen = {}
    for i in itertools.count():
        n = prefix + "".join(rng.choice(string.ascii_lowercase) for _ in range(10))
        h = fn(n)
        if h in seen and seen[h] != n:
            return seen[h], n
        seen[h] = n
        assert i < 1 << (bits // 2 + 6), "no collision found"


def test_overlay_collisions_are_reported(install, tmp_path):
    a, b = _collide("fcm_hc_", create_id, 30)
    fa, fb = _collide("fcm_fh_", faction_id, 16)
    assert create_id(a) == create_id(b) and faction_id(fa) == faction_id(fb)
    data = os.path.relpath(install.data_dir, install.root)
    ov = tmp_path / "ov"
    f = ov / "files" / data / "EQUIPMENT" / "fcm_hash_test.ini"
    f.parent.mkdir(parents=True)
    f.write_text(f"[Good]\r\nnickname = {a}\r\n\r\n[Good]\r\nnickname = {b.upper()}\r\n",
                 encoding="latin-1")
    groups = install.data_files("groups")[0]
    units = [{"file": f"{data}/{groups}".replace("\\", "/"), "id": "t.groups", "version": 1,
              "ops": [{"op": "add_section", "lines": ["[Group]", f"nickname = {fa}"]},
                      {"op": "add_section", "lines": ["[Group]", f"nickname = {fb}"]}]}]
    (ov / "patches.json").write_text(json.dumps({"units": units}))
    r = hashscan.scan(Install(install.root, ov))
    assert [sorted(c) for c in r.createid_collisions] == [sorted([a, b])]
    assert [sorted(c) for c in r.faction_collisions] == [sorted([fa, fb])]
    assert {a, b} <= r.new_nicknames
    assert hashscan.main(["--install", str(install.root), "--overlay", str(ov)]) == 1
