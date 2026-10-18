"""Transactional deploy (review r1 MAJOR 2, MINORs m4/m5/m6) on a synthetic install.

No game data needed: ``synth_install`` is a tiny placeholder tree (conftest). Every failure
case checks that nothing was written (files AND directories), and every interruption case checks
that ``undeploy`` restores the original tree byte for byte and that a re-deploy then succeeds.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fltools import patch as flpatch
from gen.framework import core

REPO = Path(__file__).resolve().parents[3]
RUN = REPO / "gen" / "run.py"
QUIET = dict(log=lambda m: None)

# Two new files (one in a new directory), a string (-> EXE/fcm_text.dll) and units on two
# install files (EXE/freelancer.ini twice, DATA/EQUIPMENT/market_synth.ini once).
MULTI = r'''
def generate(ctx):
    ctx.strings.register("fcm.t.name", "T")
    ctx.write_data("EQUIPMENT/fcm_a.ini", "[Good]\r\nnickname = fcm_a\r\n")
    ctx.write_data("FCM/SUB/fcm_b.ini", "[Good]\r\nnickname = fcm_b\r\n")
    ctx.add_data_file("goods", "equipment\\fcm_a.ini")
    ctx.patch(ctx.data_rel + "/EQUIPMENT/market_synth.ini", "mk",
              [{"op": "add_section", "lines": ["[BaseGood]", "base = fcm_base"]}])
'''
BAD_UNIT = MULTI + r'''
    ctx.patch("EXE/freelancer.ini", "bad",
              [{"op": "append", "section": "NoSuchSection", "lines": ["x = 1"]}])
'''


def _gen_dir(tmp_path: Path, code: str, name: str = "multi") -> Path:
    g = tmp_path / f"gen-{name}"
    (g / name).mkdir(parents=True)
    (g / name / "generator.py").write_text(code, encoding="utf-8")
    return g


def _kw(tmp_path: Path, gen_dir: Path) -> dict:
    return dict(gen_dir=gen_dir, text_ids=tmp_path / "ids.json", data_dir=tmp_path / "nodata",
                world=False)


def _build(tmp_path: Path, root: Path, code: str = MULTI, name: str = "ov") -> Path:
    ov = tmp_path / name
    core.build(root, ov, None, **_kw(tmp_path, _gen_dir(tmp_path, code, name)), **QUIET)
    return ov


def _fail_on_call(n: int, real):
    """Wrap ``real`` so that its n-th call raises OSError (simulated disk error / kill)."""
    calls = {"n": 0}

    def wrapper(*a, **k):
        calls["n"] += 1
        if calls["n"] == n:
            raise OSError(28, "No space left on device (simulated)")
        return real(*a, **k)
    return wrapper


def test_clean_deploy_undeploy_restores_dirs_too(synth_install, tmp_path, snap):
    before = snap(synth_install)
    ov = _build(tmp_path, synth_install)
    res = core.deploy(synth_install, ov, **QUIET)
    assert sorted(res["patched"]) == ["DATA/EQUIPMENT/market_synth.ini", "EXE/freelancer.ini"]
    st = json.loads((synth_install / core.DEPLOY_STATE).read_text())
    assert st["status"] == "complete" and st["dirs"] == ["DATA/FCM", "DATA/FCM/SUB"]
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before            # files AND directories


def test_failing_unit_writes_nothing(synth_install, tmp_path, snap):
    before = snap(synth_install)
    g = _gen_dir(tmp_path, BAD_UNIT)
    with pytest.raises(core.GenError, match="NoSuchSection"):
        core.deploy(synth_install, **_kw(tmp_path, g), **QUIET)
    assert snap(synth_install) == before
    # the same through a pre-built overlay
    ov = tmp_path / "ov-bad"
    core.build(synth_install, ov, None, **_kw(tmp_path, g), **QUIET)
    with pytest.raises(core.GenError, match="NoSuchSection"):
        core.deploy(synth_install, ov, **QUIET)
    assert snap(synth_install) == before


@pytest.mark.parametrize("state_name", [flpatch.STATE_NAME, core.DEPLOY_STATE])
@pytest.mark.parametrize("prebuilt", [False, True], ids=["build", "overlay"])
def test_corrupt_state_json_writes_nothing(synth_install, tmp_path, snap, state_name, prebuilt):
    ov = _build(tmp_path, synth_install) if prebuilt else None
    (synth_install / state_name).write_text('{"files": {"half', encoding="utf-8")
    before = snap(synth_install)
    kw = {} if prebuilt else _kw(tmp_path, _gen_dir(tmp_path, MULTI, "g2"))
    with pytest.raises(core.GenError, match="corrupt"):
        core.deploy(synth_install, ov, **kw, **QUIET)
    with pytest.raises(core.GenError, match="corrupt"):
        core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before


def test_tampered_overlay_is_refused(synth_install, tmp_path, snap):
    before = snap(synth_install)
    ov = _build(tmp_path, synth_install)
    pj = ov / "patches.json"
    pj.write_bytes(pj.read_bytes().replace(b"fcm_base", b"fcm_base_x"))
    with pytest.raises(core.GenError, match="patches.json does not match"):
        core.deploy(synth_install, ov, **QUIET)
    ov2 = _build(tmp_path, synth_install, name="ov2")
    (ov2 / "files" / "DATA" / "EQUIPMENT" / "fcm_a.ini").write_bytes(b"changed")
    with pytest.raises(core.GenError, match="does not match its manifest"):
        core.deploy(synth_install, ov2, **QUIET)
    assert snap(synth_install) == before


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_interrupted_copy_recovers(synth_install, tmp_path, snap, monkeypatch, fail_at):
    """A copy fails mid-deploy: the in-progress state lists every file, undeploy restores the
    original tree, and a later deploy succeeds."""
    before = snap(synth_install)
    ov = _build(tmp_path, synth_install)
    monkeypatch.setattr(core, "_copy_atomic", _fail_on_call(fail_at, core._copy_atomic))
    with pytest.raises(core.GenError, match="simulated"):
        core.deploy(synth_install, ov, **QUIET)
    st = json.loads((synth_install / core.DEPLOY_STATE).read_text())
    assert st["status"] == "in_progress"
    assert sorted(st["files"]) == ["DATA/EQUIPMENT/fcm_a.ini", "DATA/FCM/SUB/fcm_b.ini",
                                   f"EXE/{core.RESOURCE_DLL}"]
    monkeypatch.undo()
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before
    core.deploy(synth_install, ov, **QUIET)
    deployed = snap(synth_install)
    assert f"EXE/{core.RESOURCE_DLL}" in deployed
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before


def test_interrupted_copy_then_redeploy_directly(synth_install, tmp_path, snap, monkeypatch):
    """No undeploy in between: a re-deploy over the half-deployed tree completes, and equals a
    clean deploy."""
    before = snap(synth_install)
    ov = _build(tmp_path, synth_install)
    core.deploy(synth_install, ov, **QUIET)
    clean = snap(synth_install)
    core.undeploy(synth_install, **QUIET)
    monkeypatch.setattr(core, "_copy_atomic", _fail_on_call(2, core._copy_atomic))
    with pytest.raises(core.GenError):
        core.deploy(synth_install, ov, **QUIET)
    monkeypatch.undo()
    core.deploy(synth_install, ov, **QUIET)
    assert snap(synth_install) == clean
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before


@pytest.mark.parametrize("fail_at", [1, 2])
def test_interrupted_patch_recovers(synth_install, tmp_path, snap, monkeypatch, fail_at):
    """The n-th patched-file write fails (after the copies): the patch state still covers every
    file on disk, undeploy restores the original tree, a re-deploy succeeds."""
    before = snap(synth_install)
    ov = _build(tmp_path, synth_install)
    monkeypatch.setattr(flpatch, "_write_atomic", _fail_on_call(fail_at, flpatch._write_atomic))
    with pytest.raises(core.GenError, match="simulated"):
        core.deploy(synth_install, ov, **QUIET)
    monkeypatch.undo()
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before
    core.deploy(synth_install, ov, **QUIET)
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before


def test_undeploy_removes_interrupted_temp_files(synth_install, tmp_path, snap, monkeypatch):
    """A copy that dies half-way leaves ``<file>.carrier-mod.tmp``; undeploy removes it."""
    before = snap(synth_install)
    ov = _build(tmp_path, synth_install)

    def half_copy(src, dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.with_name(dst.name + core.TMP_SUFFIX).write_bytes(Path(src).read_bytes()[:3])
        raise OSError(5, "I/O error (simulated)")
    monkeypatch.setattr(core, "_copy_atomic", half_copy)
    with pytest.raises(core.GenError):
        core.deploy(synth_install, ov, **QUIET)
    assert (synth_install / "DATA" / "EQUIPMENT" / ("fcm_a.ini" + core.TMP_SUFFIX)).exists()
    monkeypatch.undo()
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before


def test_overlay_ids_index_mismatch_is_refused(synth_install, tmp_path, snap, make_synth):
    """m4: an overlay built for index 8 onto an install with an extra resource DLL."""
    ov = _build(tmp_path, synth_install)
    other = make_synth(tmp_path / "other")
    fini = other / "EXE" / "freelancer.ini"
    fini.write_bytes(fini.read_bytes().replace(b"DLL = synth_res7.dll\r\n",
                                               b"DLL = synth_res7.dll\r\nDLL = another_mod.dll\r\n"))
    before = snap(other)
    with pytest.raises(core.GenError, match="index 9, expected 8"):
        core.deploy(other, ov, **QUIET)
    assert snap(other) == before


def test_text_ids_lock_is_taken_and_times_out(synth_install, tmp_path, monkeypatch):
    """m5: the text-id map's read-modify-write runs under an exclusive flock."""
    ids = tmp_path / "ids.json"
    lock = core._text_ids_lock(ids)
    assert lock == tmp_path / "ids.json.lock"
    monkeypatch.setattr(core, "TEXT_IDS_LOCK_TIMEOUT", 0.3)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)                  # someone else holds the map
        with pytest.raises(core.GenError, match="timed out waiting"):
            core.build(synth_install, tmp_path / "ov", ["example_strings"], text_ids=ids,
                       data_dir=tmp_path / "nd", world=False, **QUIET)
        assert not ids.exists()
    finally:
        os.close(fd)
    core.build(synth_install, tmp_path / "ov", ["example_strings"], text_ids=ids,
               data_dir=tmp_path / "nd", world=False, **QUIET)
    assert json.loads(ids.read_text())["ids"]


def test_default_text_ids_lock_lives_in_flmod_locks(monkeypatch, tmp_path):
    monkeypatch.setenv("FLMOD_LOCKS", str(tmp_path / "locks"))
    assert core._text_ids_lock(core.LOCAL / "gen" / "text_ids.json") == \
        tmp_path / "locks" / "text_ids.lock"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(RUN), *map(str, args)],
                          capture_output=True, text=True)


def _one_line_error(r: subprocess.CompletedProcess, needle: str) -> None:
    assert r.returncode == 1, r.stdout + r.stderr
    lines = r.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("ERROR:") and needle in lines[0], r.stderr
    assert "Traceback" not in r.stderr


def test_run_py_reports_corrupt_inputs_in_one_line(synth_install, tmp_path, snap):
    """m6: corrupt JSON and bad paths end in one ERROR line, never a traceback."""
    bad_ids = tmp_path / "ids.json"
    bad_ids.write_text("{not json", encoding="utf-8")
    common = ["--only", "example_strings", "--data-dir", tmp_path / "nd"]
    _one_line_error(_run("build", "--install", synth_install, "--out", tmp_path / "ov",
                         "--text-ids", bad_ids, "--no-world", *common), "text id map")
    _one_line_error(_run("build", "--install", tmp_path / "nope", "--out", tmp_path / "ov",
                         "--text-ids", tmp_path / "ok.json", "--no-world", *common),
                    "cannot read install")
    (synth_install / flpatch.STATE_NAME).write_text("[1,", encoding="utf-8")
    before = snap(synth_install)
    _one_line_error(_run("deploy", "--install", synth_install, "--text-ids", tmp_path / "ok.json",
                         *common), "corrupt")
    _one_line_error(_run("undeploy", "--install", synth_install), "corrupt")
    assert snap(synth_install) == before
    (tmp_path / "ovx").mkdir()
    (tmp_path / "ovx" / "MANIFEST.json").write_text("{", encoding="utf-8")
    _one_line_error(_run("deploy", "--install", synth_install, "--overlay", tmp_path / "ovx"),
                    "overlay manifest")
