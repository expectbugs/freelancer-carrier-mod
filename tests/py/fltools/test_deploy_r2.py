"""Review r2 MINORs on the deploy path (synthetic install; no game data needed).

- per-install deploy lock (MINOR 1)
- kill at every filesystem write of deploy / redeploy / undeploy recovers (MINOR 2): an audit
  hook stops the operation right before the n-th write under the install root, like a SIGKILL
- the temp overlay never lands in (or probes) a protected prefix (MINOR 3)
- overlay and state paths cannot leave their root (MINOR 6)
- one-line CLI errors (MINOR 7), symlinked patch target into the play prefix (MINOR 8)
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fltools import patch as flpatch
from fltools.safety import PlayPrefixError
from gen.framework import core

REPO = Path(__file__).resolve().parents[3]
RUN = REPO / "gen" / "run.py"
BIN = REPO / "tools" / "fltools" / "bin"
QUIET = dict(log=lambda m: None)

GEN_A = r'''
def generate(ctx):
    ctx.strings.register("fcm.t.a", "A")
    ctx.write_data("EQUIPMENT/fcm_a.ini", "[Good]\r\nnickname = fcm_a\r\n")
    ctx.write_data("FCM/SUB/fcm_b.ini", "[Good]\r\nnickname = fcm_b\r\n")
    ctx.add_data_file("goods", "equipment\\fcm_a.ini")
    ctx.patch(ctx.data_rel + "/EQUIPMENT/market_synth.ini", "mk",
              [{"op": "add_section", "lines": ["[BaseGood]", "base = fcm_base"]}])
'''
GEN_B = r'''
def generate(ctx):
    ctx.strings.register("fcm.t.b", "B")
    ctx.write_data("EQUIPMENT/fcm_c.ini", "[Good]\r\nnickname = fcm_c\r\n")
    ctx.add_data_file("goods", "equipment\\fcm_c.ini")
    ctx.patch(ctx.data_rel + "/EQUIPMENT/synth_equip.ini", "eq",
              [{"op": "add_section", "lines": ["[Power]", "nickname = fcm_power"]}])
'''


def _build(tmp_path: Path, root: Path, code: str, name: str) -> Path:
    g = tmp_path / f"gen-{name}"
    (g / name).mkdir(parents=True)
    (g / name / "generator.py").write_text(code, encoding="utf-8")
    ov = tmp_path / f"ov-{name}"
    core.build(root, ov, None, gen_dir=g, text_ids=tmp_path / f"ids-{name}.json",
               data_dir=tmp_path / "nd", world=False, **QUIET)
    return ov


# --- audit-hook "kill" ---------------------------------------------------------------------------
class _Killed(BaseException):
    """Raised right before the n-th write: skips every except/cleanup like a SIGKILL would
    (deploy has no finally that writes into the install)."""


_ARM: dict = {"root": None, "n": 0, "at": 0, "events": []}
_WRITE_EVENTS = {"os.rename", "os.remove", "os.mkdir", "os.rmdir", "os.chmod", "os.truncate"}
_WFLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _hook(ev, args):
    a = _ARM
    if a["root"] is None:
        return
    if ev == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
            (mode is None and isinstance(flags, int) and bool(flags & _WFLAGS))
    else:
        write = ev in _WRITE_EVENTS
    if not write or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    p = os.path.abspath(os.fsdecode(args[0]))
    if not (p == a["root"] or p.startswith(a["root"] + os.sep)):
        return
    a["n"] += 1
    a["events"].append(f"{ev} {os.path.relpath(p, a['root'])}")
    if a["n"] == a["at"]:
        a["root"] = None
        raise _Killed()


sys.addaudithook(_hook)     # inert unless armed


def _armed(root: Path, at: int, fn, *args, **kw) -> list[str]:
    """Run ``fn`` with writes under ``root`` counted; stop before write number ``at`` (0 =
    never). Returns the write events seen."""
    _ARM.update(root=os.path.abspath(root), n=0, at=at, events=[])
    try:
        fn(*args, **kw)
    except _Killed:
        pass
    finally:
        _ARM["root"] = None
    return list(_ARM["events"])


# --- MINOR 1: per-install lock ----------------------------------------------------------------
def test_deploy_and_undeploy_wait_for_the_install_lock(synth_install, tmp_path, snap,
                                                       monkeypatch):
    ov = _build(tmp_path, synth_install, GEN_A, "a")
    lock = core.deploy_lock_path(synth_install)
    assert lock.parent == Path(os.environ["FLMOD_LOCKS"]) and lock.name.startswith("deploy-")
    assert core.deploy_lock_path(tmp_path / "synth" / "." / "") == lock   # by realpath
    monkeypatch.setattr(core, "DEPLOY_LOCK_TIMEOUT", 0.3)
    before = snap(synth_install)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)            # another deploy is running
        with pytest.raises(core.GenError, match="timed out waiting"):
            core.deploy(synth_install, ov, **QUIET)
        with pytest.raises(core.GenError, match="timed out waiting"):
            core.undeploy(synth_install, **QUIET)
        assert snap(synth_install) == before
    finally:
        os.close(fd)
    core.deploy(synth_install, ov, **QUIET)
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before


def test_concurrent_deploys_serialise(synth_install, tmp_path, snap):
    """Two deploys of different overlays start while the lock is held, then race for it: both
    succeed one after the other, and the install carries exactly the last one's content."""
    before = snap(synth_install)
    ova = _build(tmp_path, synth_install, GEN_A, "a")
    ovb = _build(tmp_path, synth_install, GEN_B, "b")
    lock = core.deploy_lock_path(synth_install)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        procs = [subprocess.Popen([sys.executable, "-I", str(RUN), "deploy", "--install",
                                   str(synth_install), "--overlay", str(ov)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for ov in (ova, ovb)]
        time.sleep(1.0)
        assert all(p.poll() is None for p in procs), "a deploy did not wait for the lock"
        assert snap(synth_install) == before
    finally:
        os.close(fd)
    outs = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    st = json.loads((synth_install / core.DEPLOY_STATE).read_text())
    files_a = set(json.loads((ova / "MANIFEST.json").read_text())["files"])
    files_b = set(json.loads((ovb / "MANIFEST.json").read_text())["files"])
    assert set(st["files"]) in (files_a, files_b) and st["status"] == "complete"
    other = files_b if set(st["files"]) == files_a else files_a
    for rel in other - set(st["files"]):
        assert not (synth_install / rel).exists(), f"unrecorded leftover {rel}"
    core.undeploy(synth_install, **QUIET)
    assert snap(synth_install) == before


# --- MINOR 2: kill at every write ------------------------------------------------------------------
@pytest.fixture
def km(synth_install, tmp_path, snap):
    """Templates for the kill matrix: pristine, deployed with A, and the clean results."""
    ova = _build(tmp_path, synth_install, GEN_A, "a")
    ovb = _build(tmp_path, synth_install, GEN_B, "b")
    t = tmp_path / "templates"
    pristine = t / "pristine"
    shutil.copytree(synth_install, pristine, symlinks=True)
    dep_a = t / "dep_a"
    shutil.copytree(pristine, dep_a, symlinks=True)
    core.deploy(dep_a, ova, **QUIET)
    ref_ab = t / "ref_ab"                        # clean redeploy A -> B
    shutil.copytree(dep_a, ref_ab, symlinks=True)
    core.deploy(ref_ab, ovb, **QUIET)
    return {"ova": ova, "ovb": ovb, "pristine": pristine, "dep_a": dep_a, "ref_ab": ref_ab,
            "work": tmp_path / "work", "snap": snap}


def _matrix(km, start: str, op, expected_after_rerun: str) -> list[str]:
    """For every write k of ``op`` on a copy of template ``start``: stop before write k, then
    (A) undeploy must give the pristine tree, and (B) re-running ``op`` must give the clean
    result, after which undeploy again gives the pristine tree. Returns failures."""
    snap, work = km["snap"], km["work"]
    pristine = snap(km["pristine"])
    clean = snap(km[expected_after_rerun])

    def fresh(name):
        d = work / name
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(km[start], d, symlinks=True)
        return d

    probe = fresh("probe")
    events = _armed(probe, 0, op, probe)
    assert events, "no write events counted"
    bad = []
    for k in range(1, len(events) + 1):
        a = fresh(f"a{k}")
        _armed(a, k, op, a)
        core.undeploy(a, **QUIET)
        if snap(a) != pristine:
            bad.append(f"A k={k} [{events[k - 1]}]")
        b = fresh(f"b{k}")
        _armed(b, k, op, b)
        op(b)
        if snap(b) != clean:
            bad.append(f"B-rerun k={k} [{events[k - 1]}]")
        core.undeploy(b, **QUIET)
        if snap(b) != pristine:
            bad.append(f"B-undeploy k={k} [{events[k - 1]}]")
        shutil.rmtree(a)
        shutil.rmtree(b)
    return bad


def test_kill_matrix_first_deploy(km):
    assert _matrix(km, "pristine", lambda r: core.deploy(r, km["ova"], **QUIET), "dep_a") == []


def test_kill_matrix_redeploy(km):
    assert _matrix(km, "dep_a", lambda r: core.deploy(r, km["ovb"], **QUIET), "ref_ab") == []


def test_kill_matrix_undeploy(km):
    assert _matrix(km, "dep_a", lambda r: core.undeploy(r, **QUIET), "pristine") == []


def test_undeploy_deletes_the_state_last(km):
    """Order check (the reviewer's k=20-23 window): the deploy state is the last write."""
    d = km["work"] / "order"
    shutil.copytree(km["dep_a"], d, symlinks=True)
    events = _armed(d, 0, core.undeploy, d, **QUIET)
    assert events[-1] == f"os.remove {core.DEPLOY_STATE}", events
    assert any(e.startswith("os.rmdir ") for e in events)


# --- MINOR 3: temp dir ---------------------------------------------------------------------------
def test_temp_overlay_never_touches_a_protected_tmpdir(synth_install, tmp_path, monkeypatch,
                                                       make_synth, snap):
    prefix = tmp_path / "prefix"
    (prefix / "drive_c" / "tmp").mkdir(parents=True)
    monkeypatch.setenv("FLMOD_PLAY_PREFIX", str(prefix))
    before = snap(prefix)
    for var in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TMPDIR", str(prefix / "drive_c" / "tmp"))
    kw = dict(only=["example_strings"], text_ids=tmp_path / "i.json", data_dir=tmp_path / "nd")

    def go():
        with pytest.raises(core.GenError, match="play prefix"):
            core.deploy(synth_install, **kw, **QUIET)
    events = _armed(prefix, 0, go)
    assert events == [] and snap(prefix) == before       # not even a probe file
    # a normal TMPDIR works and leaves no fcm-overlay-* behind
    ok_tmp = tmp_path / "oktmp"
    ok_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(ok_tmp))
    core.deploy(synth_install, **kw, **QUIET)
    assert list(ok_tmp.iterdir()) == []


# --- MINOR 6: path containment -----------------------------------------------------------------
@pytest.mark.parametrize("call", [
    "ctx.write_file('EXE/../../fcm_escaped.txt', 'x')",
    "ctx.write_file('/tmp/fcm_escaped.txt', 'x')",
    "ctx.write_file('C:/fcm_escaped.txt', 'x')",
    "ctx.write_data('../../fcm_escaped.txt', 'x')",
    "ctx.patch('../EXE/freelancer.ini', 'b', [{'op': 'append', 'section': 'Data', 'lines': ['x']}])",
])
def test_build_refuses_escaping_paths(synth_install, tmp_path, call):
    g = tmp_path / "g"
    (g / "esc").mkdir(parents=True)
    (g / "esc" / "generator.py").write_text(f"def generate(ctx):\n    {call}\n", encoding="utf-8")
    with pytest.raises(core.GenError, match=r"'\.\.'|absolute"):
        core.build(synth_install, tmp_path / "ov", None, gen_dir=g, text_ids=tmp_path / "i.json",
                   data_dir=tmp_path / "nd", world=False, **QUIET)
    assert not list(tmp_path.rglob("fcm_escaped.txt"))
    assert not Path("/tmp/fcm_escaped.txt").exists()


def _retarget(ov: Path, old: str, new: str) -> None:
    """Rename a manifest file entry (and move the file) like a tampered overlay would."""
    man = json.loads((ov / "MANIFEST.json").read_text())
    man["files"][new] = man["files"].pop(old)
    dst = ov / "files" / new
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ov / "files" / old), dst)
    (ov / "MANIFEST.json").write_text(json.dumps(man))


def test_deploy_refuses_escaping_overlay_and_state(synth_install, tmp_path, snap):
    box = tmp_path / "box"                 # the install's parent: escapes would land here
    box.mkdir()
    inst = box / "inst"
    shutil.move(str(synth_install), inst)
    before_box = snap(box)
    ov = _build(tmp_path, inst, GEN_A, "a")
    _retarget(ov, "DATA/EQUIPMENT/fcm_a.ini", "EXE/../../fcm_escaped.txt")
    with pytest.raises(core.GenError, match=r"'\.\.'"):
        core.deploy(inst, ov, **QUIET)
    ov2 = _build(tmp_path, inst, GEN_B, "b")
    pj = ov2 / "patches.json"
    units = json.loads(pj.read_text())
    units["units"][0]["file"] = "../inst/" + units["units"][0]["file"]
    pj.write_text(json.dumps(units))
    man = json.loads((ov2 / "MANIFEST.json").read_text())
    man.pop("patches_sha256")
    (ov2 / "MANIFEST.json").write_text(json.dumps(man))
    with pytest.raises(core.GenError, match=r"'\.\.'"):
        core.deploy(inst, ov2, **QUIET)
    (inst / core.DEPLOY_STATE).write_text(json.dumps(
        {"version": 2, "status": "complete", "files": {"../escaped.txt": {"sha256": "0"}}}))
    with pytest.raises(core.GenError, match="corrupt"):
        core.undeploy(inst, **QUIET)
    (inst / core.DEPLOY_STATE).unlink()
    assert snap(box) == before_box


def test_deploy_refuses_a_directory_symlinked_outside(synth_install, tmp_path, snap):
    outside = tmp_path / "outside"
    outside.mkdir()
    ov = _build(tmp_path, synth_install, GEN_A, "a")
    (synth_install / "DATA" / "FCM").symlink_to(outside, target_is_directory=True)
    before, before_out = snap(synth_install), snap(outside)
    with pytest.raises(core.GenError, match="outside the install root"):
        core.deploy(synth_install, ov, **QUIET)
    assert snap(synth_install) == before and snap(outside) == before_out


# --- MINOR 8: symlinked patch target into the play prefix -----------------------------------
def test_symlinked_patch_target_is_refused_before_any_write(synth_install, tmp_path,
                                                             monkeypatch, snap):
    ov = _build(tmp_path, synth_install, GEN_A, "a")
    prefix = tmp_path / "prefix"
    (prefix / "EXE").mkdir(parents=True)
    real = synth_install / "EXE" / "freelancer.ini"
    shutil.move(str(real), prefix / "EXE" / "freelancer.ini")
    real.symlink_to(prefix / "EXE" / "freelancer.ini")
    monkeypatch.setenv("FLMOD_PLAY_PREFIX", str(prefix))
    before, before_p = snap(synth_install), snap(prefix)
    with pytest.raises(core.GenError, match="play prefix"):
        core.deploy(synth_install, ov, **QUIET)
    assert snap(synth_install) == before and snap(prefix) == before_p   # no state, no DLL
    with pytest.raises(PlayPrefixError, match="play prefix"):
        flpatch.patch_file(synth_install, "EXE/freelancer.ini",
                           [{"id": "x.y", "ops": [{"op": "append", "section": "Data",
                                                   "lines": ["x = y"]}]}], **QUIET)
    assert snap(synth_install) == before and snap(prefix) == before_p


# --- MINOR 7: one-line errors ---------------------------------------------------------------------
def _one_line(r: subprocess.CompletedProcess, needle: str) -> None:
    lines = r.stderr.strip().splitlines()
    assert r.returncode != 0 and len(lines) == 1 and lines[0].startswith("ERROR"), r.stderr
    assert needle in lines[0] and "Traceback" not in r.stderr, r.stderr


def test_more_one_line_errors(synth_install, tmp_path):
    pytest.importorskip("yaml", reason="PyYAML not installed")
    data = tmp_path / "data" / "x"
    data.mkdir(parents=True)
    (data / "strings.yaml").write_text("strings: {a: [unclosed\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", str(RUN), "build", "--install", str(synth_install),
                        "--out", str(tmp_path / "ov"), "--only", "example_strings", "--no-world",
                        "--text-ids", str(tmp_path / "i.json"), "--data-dir",
                        str(tmp_path / "data")], capture_output=True, text=True)
    _one_line(r, "invalid YAML")
    ov = tmp_path / "ovx"
    (ov / "files").mkdir(parents=True)
    (ov / "patches.json").write_text('{"version": 1, "units": []}')
    (ov / "MANIFEST.json").write_text('{"schema": "fcm.overlay.v1", "files": ["a"]}')
    r = subprocess.run([sys.executable, "-I", str(RUN), "deploy", "--install", str(synth_install),
                        "--overlay", str(ov)], capture_output=True, text=True)
    _one_line(r, "'files' must map")


def test_cli_play_prefix_refusals_are_one_line(tmp_path, snap):
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    env = dict(os.environ, FLMOD_PLAY_PREFIX=str(prefix))
    before = snap(prefix)
    spec = tmp_path / "spec.json"
    spec.write_text('{"strings": {"1": "x"}}')
    r = subprocess.run([sys.executable, "-I", str(BIN / "flresdll"), str(spec),
                        str(prefix / "x.dll")], capture_output=True, text=True, env=env)
    _one_line(r, "play prefix")
    r = subprocess.run([sys.executable, "-I", str(BIN / "flworldexport"), "--install",
                        str(tmp_path / "none"), "--out", str(prefix / "w.json")],
                       capture_output=True, text=True, env=env)
    _one_line(r, "play prefix")
    assert snap(prefix) == before
