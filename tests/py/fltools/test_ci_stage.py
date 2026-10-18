"""harness/ci.d/30-pytest.sh follows the drop-in protocol (PASS 0 / FAIL 1 / SKIP 77) and runs
one pytest process per root, so roots with clashing conftest modules both work."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
STAGE = REPO / "harness" / "ci.d" / "30-pytest.sh"
VENV = Path(os.environ.get("FLMOD_VENV", "/home/user/freelancer/carrier-mod/.venv"))
needs_venv = pytest.mark.skipif(not (VENV / "bin" / "python").exists(), reason="shared venv missing")


def _run(repo: Path, rundir: Path, venv: Path = VENV, sidecar_venv: Path | None = None):
    env = dict(os.environ, CI_REPO_ROOT=str(repo), CI_RUNDIR=str(rundir), CI_MODE="quick",
               CI_LANES="1", FLMOD_VENV=str(venv),
               FLMOD_SIDECAR_VENV=str(sidecar_venv or repo / "no-sidecar-venv"))
    return subprocess.run(["bash", str(STAGE)], capture_output=True, text=True, env=env)


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_stage_is_executable():
    assert os.access(STAGE, os.X_OK)


def test_skip_without_test_dirs(tmp_path):
    r = _run(tmp_path / "repo", tmp_path / "run")
    assert r.returncode == 77 and "CI pytest: SKIP" in r.stdout


def test_skip_without_venv(tmp_path):
    (tmp_path / "repo" / "tests" / "py").mkdir(parents=True)
    r = _run(tmp_path / "repo", tmp_path / "run", venv=tmp_path / "novenv")
    assert r.returncode == 77 and "SKIP" in r.stdout


@needs_venv
def test_roots_with_clashing_conftests_run_separately(tmp_path):
    """Both roots export different names from a module called ``conftest`` and import them with
    ``from conftest import ...`` (the P0-SIDECAR pattern). One combined pytest process fails
    to collect this; one process per root passes. Each root also has its own pytest config."""
    repo = tmp_path / "repo"
    _w(repo / "tests" / "py" / "pkg" / "conftest.py", "PY_ONLY = 1\n")
    _w(repo / "tests" / "py" / "pkg" / "test_a.py",
       "from conftest import PY_ONLY\n\ndef test_a():\n    assert PY_ONLY == 1\n")
    _w(repo / "sidecar" / "pyproject.toml",
       "[tool.pytest.ini_options]\ntestpaths = ['tests']\npythonpath = ['src']\n")
    _w(repo / "sidecar" / "src" / "scmod.py", "VALUE = 7\n")
    _w(repo / "sidecar" / "tests" / "conftest.py", "SIDECAR_ONLY = 2\n")
    _w(repo / "sidecar" / "tests" / "test_b.py",
       "from conftest import SIDECAR_ONLY\nimport scmod\n\n"
       "def test_b():\n    assert SIDECAR_ONLY == 2 and scmod.VALUE == 7\n")
    _w(repo / "gen" / "tests" / "test_c.py", "def test_c():\n    assert True\n")
    run = tmp_path / "run"
    r = _run(repo, run)
    assert r.returncode == 0 and "CI pytest: PASS" in r.stdout, r.stdout
    for root in ("tests-py", "sidecar", "gen-tests"):
        assert root in r.stdout
        log = run / "30-pytest" / f"{root}.log"
        assert log.is_file() and "1 passed" in log.read_text()
    assert not (run / "30-pytest.log").exists()     # ci.sh owns that file


@needs_venv
def test_fail_and_partial_skip(tmp_path):
    repo = tmp_path / "repo"
    _w(repo / "gen" / "tests" / "test_ok.py", "def test_ok():\n    assert True\n")
    r = _run(repo, tmp_path / "run1")
    assert r.returncode == 0 and "PASS" in r.stdout and "tests-py: absent" in r.stdout, r.stdout
    _w(repo / "gen" / "tests" / "test_bad.py", "def test_bad():\n    assert False\n")
    r = _run(repo, tmp_path / "run2")
    assert r.returncode == 1 and "CI pytest: FAIL" in r.stdout, r.stdout
    assert "test_bad" in r.stdout
