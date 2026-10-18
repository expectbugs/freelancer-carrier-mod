"""fltools.utf: byte-exact round trip on real capital-ship models, hardpoint add."""
from __future__ import annotations

import math
import shutil
import struct

import pytest

from fltools import utf
from fltools.ini import ci_path

SHIPS = ("rh_battleship", "li_dreadnought", "or_osiris")  # nicknames; models found via shiparch


@pytest.fixture(scope="module")
def ship_models(install):
    """``{ship nickname: model path}`` from shiparch ``DA_archetype`` (read at test time)."""
    out = {}
    for rel in install.data_files("ships"):
        doc = install.data_ini(rel)
        for s in doc.sections("Ship"):
            if s.nickname and s.nickname.lower() in SHIPS:
                out[s.nickname.lower()] = install.data_path(s.get1("DA_archetype"))
    assert set(out) == set(SHIPS)
    return out


def _tree(u):
    return [(p, n.name, n.data) for p, n in u.root.walk()]


def _synthetic() -> utf.UtfFile:
    hp = utf.Node("HpTest01", children=[utf.Node("Orientation", data=struct.pack("<9f", *utf.IDENTITY)),
                                        utf.Node("Position", data=struct.pack("<3f", 1, 2, 3))])
    root = utf.Node("\\", children=[
        utf.Node("Hardpoints", children=[utf.Node("Fixed", children=[hp])]),
        utf.Node("Exporter Version", data=b"fltools test\0"),
    ])
    return utf.UtfFile(root)


def test_synthetic_write_read():
    u = _synthetic()
    b = u.dumps()
    assert b[:4] == b"UTF "
    u2 = utf.loads(b)
    assert _tree(u2) == _tree(u)
    assert u2.dumps() == b                     # preserve layout of an unmodified tree
    hps = utf.list_hardpoints(u2)
    assert [(h.name, h.kind, h.position) for h in hps] == [("HpTest01", "fixed", (1.0, 2.0, 3.0))]
    utf.add_hardpoint(u2, None, "HpTest02", "revolute", (4, 5, 6), axis=(0, 0, 1), min=-1, max=2)
    u3 = utf.loads(u2.dumps())
    rev = [h for h in utf.list_hardpoints(u3) if h.name == "HpTest02"][0]
    assert rev.axis == (0.0, 0.0, 1.0) and rev.min == -1.0 and rev.max == 2.0
    with pytest.raises(utf.UtfError):
        utf.add_hardpoint(u3, None, "hptest01", "fixed", (0, 0, 0))
    with pytest.raises(utf.UtfError):
        utf.loads(b"NOPE" + b"\0" * 60)


@pytest.mark.parametrize("ship", SHIPS)
def test_capital_model_roundtrip_and_add(ship, ship_models, tmp_path):
    src = ship_models[ship]
    work = tmp_path / src.name
    shutil.copyfile(src, work)           # never touch the install
    orig = work.read_bytes()
    u = utf.load(work)
    assert u.dumps() == orig, "unmodified tree must round-trip byte-identically"
    compact = utf.loads(u.dumps("compact"))
    assert _tree(compact) == _tree(u)

    before = utf.list_hardpoints(u)
    assert before and all(len(h.orientation) == 9 for h in before)
    revs = [h for h in before if h.kind == "revolute"]
    assert revs and all(h.axis is not None and h.min is not None and h.max is not None
                        for h in revs)
    utf.add_hardpoint(u, "Root", "HpFcmTest01", "fixed", (1.5, -2.0, 30.25),
                      orientation=((0, 0, 1), (0, 1, 0), (-1, 0, 0)))
    utf.add_hardpoint(u, None, "HpFcmTest02", "revolute", (0, 10, 0), axis=(0, 1, 0),
                      min=-math.pi / 2, max=math.pi / 2)
    u.dump(work)
    out = work.read_bytes()
    # preserve layout: every original data byte is still there, in place
    h0 = struct.unpack_from("<4s13I", orig, 0)
    h1 = struct.unpack_from("<4s13I", out, 0)
    assert out[h1[9]:h1[9] + len(orig) - h0[9]] == orig[h0[9]:]
    r = utf.load(work)
    after = {h.name: h for h in utf.list_hardpoints(r)}
    assert len(after) == len(before) + 2
    a = after["HpFcmTest01"]
    assert a.part.lower() == "root" and a.kind == "fixed"
    assert a.position == (1.5, -2.0, 30.25)
    assert a.orientation == (0.0, 0.0, 1.0, 0.0, 1.0, 0.0, -1.0, 0.0, 0.0)
    b = after["HpFcmTest02"]
    assert b.kind == "revolute" and b.axis == (0.0, 1.0, 0.0)
    assert b.min == pytest.approx(-math.pi / 2) and b.max == pytest.approx(math.pi / 2)
    for h in before:                       # existing hardpoints unchanged
        assert after[h.name].position == h.position and after[h.name].part == h.part
    assert utf.load(work).dumps() == out   # the edited file round-trips too


def test_model_path_case_insensitive(hde):
    assert ci_path(hde, r"data\ships\liberty\li_dreadnought\LI_DREADNOUGHT.CMP") is not None
