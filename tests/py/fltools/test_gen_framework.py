"""gen/framework + gen/run.py: deterministic builds, strings registry, deploy/undeploy."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fltools import ini, peres
from fltools.install import Install
from gen.framework import core
from gen.framework.strings import StringsError, StringsRegistry

REPO = Path(__file__).resolve().parents[3]
RUN = REPO / "gen" / "run.py"
EXAMPLE = ["example_strings"]
QUIET = dict(log=lambda m: None)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file()}


def test_cli_example_build_is_deterministic(hde, tmp_path):
    """Acceptance: two runs of gen/run.py on the example generator -> identical MANIFEST sha256
    (and identical bytes for every output file)."""
    outs = []
    for i in (1, 2):
        out = tmp_path / f"ov{i}"
        cmd = [sys.executable, "-I", str(RUN), "build", "--install", str(hde), "--out", str(out),
               "--only", "example_strings", "--text-ids", str(tmp_path / f"ids{i}.json"),
               "--data-dir", str(tmp_path / "nodata")]
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        outs.append(out)
    assert _sha(outs[0] / "MANIFEST.json") == _sha(outs[1] / "MANIFEST.json")
    assert _snapshot(outs[0]) == _snapshot(outs[1])
    man = json.loads((outs[0] / "MANIFEST.json").read_text())
    assert man["ids_index"] == 8 and man["resource_dll"].endswith(core.RESOURCE_DLL)
    assert man["patched_files"] == [{"file": "EXE/freelancer.ini", "units": ["fcm.resources"]}]
    assert man["files"][man["resource_dll"]]["sha256"] == _sha(outs[0] / "files" /
                                                                man["resource_dll"])
    # the combined view resolves our IDS through the patched [Resources] list
    ids = peres.IdsResolver.from_install(Install(hde, outs[0]))
    assert ids.names[-1] == core.RESOURCE_DLL
    assert ids.name(man["text_ids"]["fcm.example.name"]) == "Carrier Mod Test String"
    assert "mod's resource DLL is loaded" in ids.infocard(man["text_ids"]["fcm.example.infocard"])
    # world.json was exported from install + overlay
    w = json.loads((outs[0] / "world.json").read_text(encoding="utf-8"))
    assert w["schema"] == "fcm.world.v1" and len(w["systems"]) > 50


def test_cli_validate_overlay(hde, tmp_path):
    out = tmp_path / "ov"
    core.build(hde, out, EXAMPLE, text_ids=tmp_path / "ids.json", data_dir=tmp_path / "x",
               world=False, **QUIET)
    r = subprocess.run([sys.executable, "-I", str(RUN), "validate", "--install", str(hde),
                        "--overlay", str(out), "--json", str(tmp_path / "v.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    v = json.loads((tmp_path / "v.json").read_text())
    assert v["validate"]["ERROR"] == 0 and v["hashscan"]["createid_collisions"] == []


def test_strings_registry(tmp_path):
    pytest.importorskip("yaml", reason="PyYAML not installed")
    data = tmp_path / "data" / "core"
    data.mkdir(parents=True)
    (data / "strings.yaml").write_text(
        "strings:\n  carrier.b: Bee\n  carrier.a: Ay\n"
        "infocards:\n  carrier.info: |\n    Para one.\n\n    Para two & more.\n"
        "entries:\n  carrier.pinned: {kind: name, text: Pinned, id: 500}\n", encoding="utf-8")
    ids = tmp_path / "text_ids.json"
    r = StringsRegistry(ids, 8)
    r.load_yaml_tree(tmp_path / "data")
    assert r.ids("carrier.a") == 8 * 65536 + 1        # sorted keys first
    assert r.ids("carrier.b") == 8 * 65536 + 2
    assert r.ids("carrier.pinned") == 8 * 65536 + 500
    code = r.register("code.x", "X")
    s, c = r.tables()
    assert s[1] == "Ay" and "Para two &amp; more." in c[r.mapping["carrier.info"]]
    r.save()
    # a new run with an extra key keeps every old id, retired keys stay reserved
    (data / "strings.yaml").write_text(
        "strings:\n  carrier.0new: New\n  carrier.b: Bee\n", encoding="utf-8")
    r2 = StringsRegistry(ids, 8)
    r2.load_yaml_tree(tmp_path / "data")
    assert r2.ids("carrier.b") == 8 * 65536 + 2
    assert r2.ids("carrier.0new") == 8 * 65536 + 501   # above the highest id ever used
    assert r2.register("code.x", "X") == code
    with pytest.raises(StringsError):
        r2.register("code.x", "different text")
    with pytest.raises(StringsError):
        r2.register("clash", "x", id=2)
    with pytest.raises(StringsError):
        r2.register("bad.card", kind="infocard", rdl="<NOT/>")


def _with_build_kw(tmp_path):
    return dict(only=EXAMPLE, text_ids=tmp_path / "ids.json", data_dir=tmp_path / "nodata",
                world=False)


def test_deploy_redeploy_undeploy_byte_identical(mini_install, tmp_path):
    before = _snapshot(mini_install)
    res = core.deploy(mini_install, **_with_build_kw(tmp_path), **QUIET)
    dll = ini.ci_path(mini_install, f"EXE/{core.RESOURCE_DLL}")
    assert dll is not None and res["patched"] == ["EXE/freelancer.ini"]
    fini = ini.load(ini.ci_path(mini_install, "EXE/freelancer.ini"))
    assert fini.section("Resources").getall("DLL")[-1] == core.RESOURCE_DLL
    assert peres.ResourceDll(dll).strings
    deployed = _snapshot(mini_install)
    res2 = core.deploy(mini_install, **_with_build_kw(tmp_path), **QUIET)
    assert res2["patched"] == [] and _snapshot(mini_install) == deployed      # idempotent
    core.undeploy(mini_install, **QUIET)
    assert _snapshot(mini_install) == before                                  # reversible


def test_deploy_refuses_foreign_file(mini_install, tmp_path):
    kw = _with_build_kw(tmp_path)
    ov = tmp_path / "ov"
    core.build(mini_install, ov, kw.pop("only"), **kw, **QUIET)
    foreign = mini_install / "EXE" / core.RESOURCE_DLL
    foreign.write_bytes(b"someone else's file")
    with pytest.raises(Exception, match="not ours"):           # deploy layer
        core.deploy(mini_install, ov, **QUIET)
    with pytest.raises(core.GenError, match="exists in the install"):   # build layer
        core.deploy(mini_install, **_with_build_kw(tmp_path), **QUIET)
    assert foreign.read_bytes() == b"someone else's file"
    assert not (mini_install / core.DEPLOY_STATE).exists()


def test_deploy_refuses_play_prefix(tmp_path, monkeypatch):
    fake_play = tmp_path / "prefix"
    inst = fake_play / "drive_c" / "Games" / "HDE"
    (inst / "EXE").mkdir(parents=True)
    monkeypatch.setenv("FLMOD_PLAY_PREFIX", str(fake_play))   # can only ADD protection
    with pytest.raises(core.GenError, match="play prefix"):
        core.deploy(inst, **_with_build_kw(tmp_path), **QUIET)
    with pytest.raises(core.GenError, match="play prefix"):
        core.undeploy(inst, **QUIET)
    assert list((inst / "EXE").iterdir()) == []


def test_check_target_real_play_prefix_is_refused():
    """Pure check (no I/O beyond realpath): the real play install is always refused."""
    with pytest.raises(core.GenError):
        core._check_target(Path("/home/user/freelancer/prefix/drive_c/Games/Freelancer HD Edition"))


PLUGIN = '''
ORDER = {order}
def generate(ctx):
    ids = ctx.strings.register("{key}", "{text}")
    ctx.write_data("EQUIPMENT/fcm_{name}.ini", "[Good]\\r\\nnickname = fcm_{name}\\r\\nids_name = %d\\r\\n" % ids)
    ctx.add_data_file("goods", "equipment\\\\fcm_{name}.ini")
'''


def test_plugin_discovery_and_build(hde, tmp_path):
    g = tmp_path / "gen"
    for d, order, key in (("alpha", 10, "a.k"), ("plugins/zeta", 5, "z.k"), ("framework", 1, "f")):
        (g / d).mkdir(parents=True)
        name = d.split("/")[-1]
        (g / d / "generator.py").write_text(PLUGIN.format(order=order, key=key, text=name,
                                                          name=name))
    gens = core.discover(g)
    assert [x.name for x in gens] == ["plugins.zeta", "alpha"]      # ORDER, framework skipped
    out = tmp_path / "ov"
    man = core.build(hde, out, None, text_ids=tmp_path / "ids.json", data_dir=tmp_path / "nd",
                     world=False, gen_dir=g, **QUIET)
    assert sorted(man["files"]) == ["DATA/EQUIPMENT/fcm_alpha.ini", "DATA/EQUIPMENT/fcm_zeta.ini",
                                    f"EXE/{core.RESOURCE_DLL}"]
    units = json.loads((out / "patches.json").read_text())["units"]
    assert [u["id"] for u in units][:2] == ["plugins.zeta.data.goods.equipment_fcm_zeta.ini",
                                            "alpha.data.goods.equipment_fcm_alpha.ini"]
    comb = Install(hde, out)
    assert comb.data_files("goods")[-2:] == ["equipment\\fcm_zeta.ini", "equipment\\fcm_alpha.ini"]
    good = comb.data_ini("equipment/fcm_zeta.ini").section("Good")
    assert peres.IdsResolver.from_install(comb).name(int(good.get("ids_name"))) == "zeta"
    # refuses to write over an install file, and to clear a non-overlay directory
    bad = tmp_path / "gen2" / "bad"
    bad.mkdir(parents=True)
    (bad / "generator.py").write_text("def generate(ctx):\n    ctx.write_file('EXE/freelancer.ini', 'x')\n")
    with pytest.raises(core.GenError, match="exists in the install"):
        core.build(hde, tmp_path / "ov2", None, text_ids=tmp_path / "i2.json",
                   data_dir=tmp_path / "nd", world=False, gen_dir=tmp_path / "gen2", **QUIET)
    notov = tmp_path / "precious"
    notov.mkdir()
    (notov / "keep.txt").write_text("x")
    with pytest.raises(core.GenError, match="not an overlay"):
        core.build(hde, notov, EXAMPLE, text_ids=tmp_path / "i3.json", data_dir=tmp_path / "nd",
                   world=False, **QUIET)
    assert (notov / "keep.txt").exists()


def test_build_from_deployed_install_equals_pristine_build(mini_install, tmp_path):
    """Building from an install that was already deployed gives the same overlay bytes."""
    kw = dict(text_ids=tmp_path / "ids.json", data_dir=tmp_path / "nd", world=False, **QUIET)
    core.build(mini_install, tmp_path / "a", EXAMPLE, **kw)
    core.deploy(mini_install, tmp_path / "a", **QUIET)
    core.build(mini_install, tmp_path / "b", EXAMPLE, **kw)
    assert _snapshot(tmp_path / "a") == _snapshot(tmp_path / "b")
