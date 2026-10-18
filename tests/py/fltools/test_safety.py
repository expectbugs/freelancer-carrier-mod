"""Play-prefix guard on every write path (review r1 MAJOR 3).

Every writer in fltools / gen is pointed at a FAKE play prefix (``$FLMOD_PLAY_PREFIX`` set to a
temp dir; the variable can only add protection) and must refuse before writing anything; the
fake tree must be byte-identical afterwards. The real play prefix is only ever touched through
``os.path.realpath`` (metadata), never opened.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fltools import ini, patch, resdll, safety, utf, validate, worldexport
from fltools.install import Install
from fltools.safety import PLAY_PREFIX, PlayPrefixError, refuse_play_prefix
from gen.framework import core
from gen.framework.strings import StringsRegistry

REPO = Path(__file__).resolve().parents[3]
RUN = REPO / "gen" / "run.py"
QUIET = dict(log=lambda m: None)
UNITS = [{"file": "EXE/freelancer.ini", "id": "t.res", "version": 1,
          "ops": [{"op": "append", "section": "Resources", "lines": ["DLL = fcm_text.dll"]}]}]


@pytest.fixture
def fake(tmp_path, monkeypatch, make_synth, snap):
    """A fake play prefix holding a synthetic install; asserts it is unchanged at teardown."""
    prefix = tmp_path / "prefix"
    inst = make_synth(prefix / "drive_c" / "Games" / "HDE")
    monkeypatch.setenv("FLMOD_PLAY_PREFIX", str(prefix))
    before = snap(prefix)
    yield {"prefix": prefix, "inst": inst}
    assert snap(prefix) == before, "a writer modified the (fake) play prefix"


def test_refuse_is_pure_and_keeps_the_hardcoded_prefix(tmp_path, monkeypatch):
    real = Path(PLAY_PREFIX) / "drive_c" / "x.ini"
    for env in (None, str(tmp_path / "elsewhere")):     # unset, or pointing elsewhere
        if env is None:
            monkeypatch.delenv("FLMOD_PLAY_PREFIX", raising=False)
        else:
            monkeypatch.setenv("FLMOD_PLAY_PREFIX", env)
        with pytest.raises(PlayPrefixError):
            refuse_play_prefix(real)
        with pytest.raises(PlayPrefixError):
            refuse_play_prefix(PLAY_PREFIX)
        with pytest.raises(PlayPrefixError):
            refuse_play_prefix(f"{PLAY_PREFIX}/../prefix/drive_c")
        # siblings are not inside it (whole path components)
        for ok in ("/home/user/freelancer/prefix-lane1/x", "/home/user/freelancer/prefix2/x",
                   "/home/user/freelancer/prefix-carrier/drive_c"):
            assert refuse_play_prefix(ok) == Path(os.path.realpath(ok))
    assert Path(PLAY_PREFIX) in safety.protected_roots()


def test_dotdot_and_symlink_into_fake_prefix_are_refused(fake, tmp_path):
    p = fake["prefix"]
    with pytest.raises(PlayPrefixError):
        refuse_play_prefix(tmp_path / "a" / ".." / "prefix" / "z.ini")
    link = tmp_path / "innocent"
    link.symlink_to(p / "drive_c")
    doc = ini.loads(b"[A]\r\nk = v\r\n")
    with pytest.raises(PlayPrefixError):
        doc.dump(link / "Games" / "HDE" / "EXE" / "new.ini")
    with pytest.raises(core.GenError, match="play prefix"):
        core.deploy(link / "Games" / "HDE", gen_dir=tmp_path / "nogen",
                    text_ids=tmp_path / "i.json", data_dir=tmp_path / "nd", **QUIET)


def test_fltools_writers_refuse(fake, tmp_path):
    p, inst = fake["prefix"], fake["inst"]
    fini = inst / "EXE" / "freelancer.ini"
    # ini
    doc = ini.load(fini)
    doc.section("Resources").add("DLL", "x.dll")
    with pytest.raises(PlayPrefixError):
        doc.dump()                                  # its own path
    with pytest.raises(PlayPrefixError):
        ini.loads(b"[A]\r\n").dump(p / "new.ini")
    # patch
    with pytest.raises(PlayPrefixError):
        patch.patch_file(inst, "EXE/freelancer.ini", UNITS, log=lambda m: None)
    with pytest.raises(PlayPrefixError):
        patch.unpatch_file(inst, "EXE/freelancer.ini", log=lambda m: None)
    with pytest.raises(PlayPrefixError):
        patch.unpatch_file(inst, "EXE/freelancer.ini", ["t.res"], log=lambda m: None)
    with pytest.raises(PlayPrefixError):
        patch.apply_overlay_patches(inst, UNITS, log=lambda m: None)
    with pytest.raises(PlayPrefixError):
        patch.plan_overlay_patches(inst, UNITS, log=lambda m: None)
    with pytest.raises(PlayPrefixError):
        patch.PatchState(p / "st.json").save()
    with pytest.raises(PlayPrefixError):
        patch._write_atomic(fini, b"x")
    spec = tmp_path / "units.json"
    spec.write_text(json.dumps(UNITS))
    assert patch.main(["apply", "--root", str(inst), str(spec)]) == 1
    assert patch.main(["unpatch", "--root", str(inst)]) == 1
    # resdll, utf, worldexport
    with pytest.raises(PlayPrefixError):
        resdll.write_dll(inst / "EXE" / "fcm_text.dll", {1: "x"})
    u = utf.UtfFile(utf.Node("\\", children=[utf.Node("Exporter Version", data=b"t\0")]))
    with pytest.raises(PlayPrefixError):
        u.dump(p / "m.cmp")
    with pytest.raises(PlayPrefixError):
        worldexport.write({"schema": "x"}, p / "world.json")
    # validate CLI outputs (refused before the install is even read)
    for flag in ("--json", "--write-baseline"):
        assert validate.main(["--install", str(tmp_path / "none"), flag,
                              str(p / "out.txt")]) == 2


def test_gen_writers_refuse(fake, tmp_path, synth_install):
    p, inst = fake["prefix"], fake["inst"]
    kw = dict(data_dir=tmp_path / "nd", world=False, **QUIET)
    with pytest.raises(core.GenError, match="play prefix"):          # out dir
        core.build(synth_install, p / "ov", ["example_strings"], text_ids=tmp_path / "i.json", **kw)
    with pytest.raises(core.GenError, match="play prefix"):          # text-id map
        core.build(synth_install, tmp_path / "ov", ["example_strings"], text_ids=p / "i.json", **kw)
    with pytest.raises(core.GenError, match="play prefix"):          # lock file
        with core._flock(p / "x.lock", timeout=0.1):
            pass
    ctx = core.Context(Install(synth_install), p / "ov", StringsRegistry(None, 8), 8, **QUIET)
    with pytest.raises(core.GenError, match="play prefix"):
        ctx.write_file("DATA/fcm_x.ini", "x")
    reg = StringsRegistry(p / "ids.json", 8)
    reg.register("fcm.k", "v")
    with pytest.raises(PlayPrefixError):
        reg.save()
    with pytest.raises(core.GenError, match="play prefix"):
        core._save_state(inst, {"files": {}})
    with pytest.raises(core.GenError, match="play prefix"):
        core._copy_atomic(synth_install / "EXE" / "freelancer.ini", inst / "EXE" / "y.ini")
    with pytest.raises(core.GenError, match="play prefix"):
        core.deploy(inst, only=["example_strings"], text_ids=tmp_path / "i.json", **kw)
    ov = tmp_path / "ov-ok"
    core.build(synth_install, ov, ["example_strings"], text_ids=tmp_path / "i.json", **kw)
    with pytest.raises(core.GenError, match="play prefix"):
        core.deploy(inst, ov, **QUIET)
    with pytest.raises(core.GenError, match="play prefix"):
        core.undeploy(inst, **QUIET)


def _run(*args, env=None):
    return subprocess.run([sys.executable, "-I", str(RUN), *map(str, args)], capture_output=True,
                          text=True, env=env)


def test_run_py_refuses_in_one_line(fake, tmp_path, synth_install):
    env = dict(os.environ, FLMOD_PLAY_PREFIX=str(fake["prefix"]))
    p, inst = fake["prefix"], fake["inst"]
    for args in (["build", "--install", synth_install, "--out", p / "ov", "--only",
                  "example_strings", "--text-ids", tmp_path / "i.json", "--no-world"],
                 ["build", "--install", synth_install, "--out", tmp_path / "ov", "--only",
                  "example_strings", "--text-ids", p / "i.json", "--no-world"],
                 ["deploy", "--install", inst, "--only", "example_strings"],
                 ["undeploy", "--install", inst],
                 ["validate", "--install", synth_install, "--json", p / "v.json"]):
        r = _run(*args, env=env)
        lines = r.stderr.strip().splitlines()
        assert r.returncode == 1 and len(lines) == 1 and "play prefix" in lines[0], \
            (args, r.stdout, r.stderr)


def test_hde_fixture_is_a_read_only_view_outside_the_play_prefix(hde):
    real = Path(os.path.realpath(PLAY_PREFIX))
    view = Path(os.path.realpath(hde))
    assert view != real and real not in view.parents
    fini = hde / "EXE" / "freelancer.ini"
    assert fini.is_file() and not os.access(fini, os.W_OK)
    assert not os.access(hde / "EXE", os.W_OK)
    with pytest.raises(PermissionError):
        (hde / "EXE" / "probe.tmp").write_bytes(b"x")
    with pytest.raises(PermissionError):
        fini.open("ab").close()
