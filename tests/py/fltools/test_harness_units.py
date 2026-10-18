"""D107: the reserved ``harness.*`` unit namespace survives gen deploy / redeploy / undeploy.

The harness adds its dacom.ini ``[Libraries]`` block as an fltools.patch unit on the shared
patch state; the generator overlay must never strip, re-order or rewrite it, and only an
explicit harness unpatch removes it. Both units append to the same section, so their regions
land at the same line and the unit order decides the bytes (the strictest case).
Synthetic install only (no game data).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fltools import patch as flpatch
from gen.framework import core

QUIET = dict(log=lambda m: None)
DACOM = "[DACOM]\r\nIgnoreDACOMEnv = true\r\n\r\n[Libraries]\r\nsynth_a.dll\r\nsynth_b.dll\r\n"
GEN = r'''
def generate(ctx):
    ctx.write_data("EQUIPMENT/fcm_a.ini", "[Good]\r\nnickname = fcm_a\r\n")
    ctx.patch("EXE/dacom.ini", "libs",
              [{"op": "append", "section": "Libraries", "lines": ["fcm_gen.dll"]}])
'''
HARNESS = {"id": "harness.dacom", "version": 1,
           "ops": [{"op": "append", "section": "Libraries", "lines": ["harness_devbridge.dll"]}]}
H_REGION = (b"; >>> carrier-mod harness.dacom v1\r\nharness_devbridge.dll\r\n"
            b"; <<< carrier-mod harness.dacom\r\n")
G_REGION = b"; >>> carrier-mod gen.libs v1\r\nfcm_gen.dll\r\n; <<< carrier-mod gen.libs\r\n"


@pytest.fixture
def setup(synth_install, tmp_path):
    root = synth_install
    (root / "EXE" / "dacom.ini").write_bytes(DACOM.encode("latin-1"))
    g = tmp_path / "genroot"
    (g / "gen").mkdir(parents=True)
    (g / "gen" / "generator.py").write_text(GEN, encoding="utf-8")
    ov = tmp_path / "ov"
    core.build(root, ov, None, gen_dir=g, text_ids=tmp_path / "ids.json",
               data_dir=tmp_path / "nd", world=False, **QUIET)
    return root, ov, root / "EXE" / "dacom.ini"


def harness_add(root):
    return flpatch.patch_file(root, "EXE/dacom.ini", [HARNESS], **QUIET)


def harness_remove(root):
    return flpatch.unpatch_file(root, "EXE/dacom.ini", ["harness.dacom"], **QUIET)


def _state_units(root) -> dict[str, list[str]]:
    st = json.loads((root / flpatch.STATE_NAME).read_text())
    return {k: [u["id"] for u in v["units"]] for k, v in st["files"].items()}


def test_gen_first_then_harness(setup, snap):
    root, ov, dacom = setup
    pristine, before = dacom.read_bytes(), snap(root)
    core.deploy(root, ov, **QUIET)
    assert G_REGION in dacom.read_bytes()
    harness_add(root)
    both = dacom.read_bytes()
    assert both.index(G_REGION) < both.index(H_REGION)          # appended after gen's region
    tree = snap(root)
    core.deploy(root, ov, **QUIET)                               # gen redeploy
    assert snap(root) == tree                                     # unit survives, byte-exact
    core.undeploy(root, **QUIET)                                  # gen undeploy
    assert dacom.read_bytes() == pristine.replace(b"synth_b.dll\r\n",
                                                  b"synth_b.dll\r\n" + H_REGION)
    assert G_REGION not in dacom.read_bytes()
    assert not (root / "DATA" / "EQUIPMENT" / "fcm_a.ini").exists()
    assert not (root / core.DEPLOY_STATE).exists()
    assert _state_units(root) == {"exe/dacom.ini": ["harness.dacom"]}
    assert harness_remove(root) is True                           # explicit harness undeploy
    assert dacom.read_bytes() == pristine
    assert snap(root) == before                 # whole install byte-identical (no state file)


def test_harness_first_then_gen(setup, snap):
    root, ov, dacom = setup
    pristine, before = dacom.read_bytes(), snap(root)
    harness_add(root)
    h_only, tree_h = dacom.read_bytes(), snap(root)
    core.deploy(root, ov, **QUIET)
    both = dacom.read_bytes()
    assert both.index(H_REGION) < both.index(G_REGION)          # harness stays where it was
    assert _state_units(root) == {"exe/dacom.ini": ["harness.dacom", "gen.libs"]}
    tree = snap(root)
    core.deploy(root, ov, **QUIET)
    assert snap(root) == tree
    core.undeploy(root, **QUIET)
    assert dacom.read_bytes() == h_only and snap(root) == tree_h  # back to "harness only"
    harness_remove(root)
    assert dacom.read_bytes() == pristine and snap(root) == before


def test_harness_unpatch_keeps_gen_regions(setup):
    root, ov, dacom = setup
    core.deploy(root, ov, **QUIET)
    gen_only = dacom.read_bytes()
    harness_add(root)
    harness_remove(root)
    assert dacom.read_bytes() == gen_only
    core.undeploy(root, **QUIET)
    assert not (root / flpatch.STATE_NAME).exists()               # nothing left recorded


def test_gen_may_not_use_the_reserved_namespace(setup, tmp_path):
    root, _ov, dacom = setup
    with pytest.raises(flpatch.PatchError, match="reserved"):
        flpatch.plan_overlay_patches(root, [dict(HARNESS, file="EXE/dacom.ini")], **QUIET)
    g = tmp_path / "g2"
    (g / "harness").mkdir(parents=True)
    (g / "harness" / "generator.py").write_text(
        "def generate(ctx):\n    ctx.patch('EXE/dacom.ini', 'x', [{'op': 'append', "
        "'section': 'Libraries', 'lines': ['x.dll']}])\n", encoding="utf-8")
    with pytest.raises(core.GenError, match="reserved"):
        core.build(root, tmp_path / "ov2", None, gen_dir=g, text_ids=tmp_path / "i2.json",
                   data_dir=tmp_path / "nd", world=False, **QUIET)
    assert dacom.read_bytes() == DACOM.encode("latin-1")


def test_merge_keeps_preserved_units_in_order():
    U = lambda i: {"id": i, "version": 1, "ops": []}             # noqa: E731
    ids = lambda us: [u["id"] for u in us]                        # noqa: E731
    old = [U("g1"), U("harness.a"), U("g2"), U("harness.b")]
    m = flpatch._merge_preserved
    assert ids(m(old, [U("g1"), U("g2")])) == ids(old)                       # unchanged
    assert ids(m(old, [U("g2")])) == ["harness.a", "g2", "harness.b"]        # anchor gone
    assert ids(m(old, [])) == ["harness.a", "harness.b"]                     # undeploy
    assert ids(m(old, [U("g1"), U("g2"), U("g3")])) == \
        ["g1", "harness.a", "g2", "harness.b", "g3"]                         # new gen unit
    assert ids(m([U("g1")], [U("g2")])) == ["g2"]                            # nothing preserved
