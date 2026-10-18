"""Tests for toolchain/prefix_clone.sh (sourced by load_proof.sh and ehprobe.sh; review r3 N2, D110).

flmod_prefix_in_use scans /proc for processes whose cwd is inside a prefix or whose WINEPREFIX names it. The tests
start harmless `sleep` processes with WINEPREFIX spelled in every equivalent way and check they are seen. Only temp
dirs are used; no Wine runs. Run: $FLMOD_VENV/bin/python -I -m pytest toolchain/tests -q
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "prefix_clone.sh"


def bash(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'. "{LIB}"\n{script}', "bash", *args],
                          capture_output=True, text=True, timeout=60)


def in_use(prefix: str) -> subprocess.CompletedProcess:
    return bash('flmod_prefix_in_use "$1"', prefix)


@pytest.fixture
def pfx(tmp_path: Path) -> Path:
    p = tmp_path / "pfx"
    (p / "drive_c" / "x").mkdir(parents=True)
    (tmp_path / "pfx2" / "drive_c").mkdir(parents=True)
    return p


def spawn(env_prefix: str | None = None, cwd: Path | None = None) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if k != "WINEPREFIX"}
    if env_prefix is not None:
        env["WINEPREFIX"] = env_prefix
    proc = subprocess.Popen(["sleep", "30"], env=env, cwd=cwd)
    time.sleep(0.2)
    return proc


def check_seen(prefix: Path, env_prefix: str | None = None, cwd: Path | None = None, arg: str | None = None) -> str:
    proc = spawn(env_prefix, cwd)
    try:
        r = in_use(arg or str(prefix))
    finally:
        proc.kill()
        proc.wait()
    assert r.returncode == 0, f"not detected: WINEPREFIX={env_prefix!r} cwd={cwd} arg={arg!r}\n{r.stdout}{r.stderr}"
    assert f"pid {proc.pid} " in r.stdout
    return r.stdout


def test_idle_prefix(pfx):
    assert in_use(str(pfx)).returncode == 1


@pytest.mark.parametrize("spelling", ["{p}", "{p}/", "{d}//pfx", "{d}/./pfx", "{p}/drive_c/..", "{d}/pfx2/../pfx"])
def test_wineprefix_spellings_are_detected(pfx, spelling):
    check_seen(pfx, env_prefix=spelling.format(p=pfx, d=pfx.parent))


@pytest.mark.parametrize("arg", ["{d}//pfx", "{d}/./pfx/", "{p}/drive_c/.."])
def test_prefix_argument_spellings_are_normalised(pfx, arg):
    check_seen(pfx, env_prefix=str(pfx), arg=arg.format(p=pfx, d=pfx.parent))


def test_cwd_inside_prefix_is_detected(pfx):
    check_seen(pfx, cwd=pfx / "drive_c" / "x")


def test_sibling_prefix_with_common_name_is_not_a_user(pfx):
    proc = spawn(env_prefix=str(pfx.parent / "pfx2"), cwd=pfx.parent / "pfx2" / "drive_c")
    try:
        r = in_use(str(pfx))
    finally:
        proc.kill()
        proc.wait()
    assert f"pid {proc.pid} " not in r.stdout


def source_check(root: Path, name: str) -> subprocess.CompletedProcess:
    # Point the library at a temp root (the variable is read at call time); never the real /home/user/freelancer.
    return bash('FLMOD_FL_ROOT="$1"; flmod_check_clone_source "$2"', str(root), name)


def test_baseline_without_baseline_json_is_refused(tmp_path):
    (tmp_path / "prefix-dev-base-T" / "drive_c").mkdir(parents=True)
    r = source_check(tmp_path, "prefix-dev-base-T")
    assert r.returncode == 77
    assert "no BASELINE.json" in r.stderr


def test_finished_baseline_is_accepted(tmp_path):
    base = tmp_path / "prefix-dev-base-T"
    (base / "drive_c").mkdir(parents=True)
    (base / "BASELINE.json").write_text('{"track": "B"}\n')
    r = source_check(tmp_path, "prefix-dev-base-T")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(base)


def test_baseline_in_use_is_refused(tmp_path):
    base = tmp_path / "prefix-dev-base-T"
    (base / "drive_c").mkdir(parents=True)
    (base / "BASELINE.json").write_text("{}\n")
    proc = spawn(env_prefix=f"{tmp_path}//prefix-dev-base-T/drive_c/..")
    try:
        r = source_check(tmp_path, "prefix-dev-base-T")
    finally:
        proc.kill()
        proc.wait()
    assert r.returncode == 3
    assert "in use" in r.stderr


@pytest.mark.parametrize("bad", ["../prefix-dev-base-T", "prefix-dev-base-T/../x", "/abs/path", "lane-1", ""])
def test_bad_from_values(tmp_path, bad):
    assert source_check(tmp_path, bad).returncode == 2
