"""The harness's shell test suites, run from pytest so CI stage 30 (harness/ci.d/30-pytest.sh, D113) covers them.

Each suite skips cleanly, with the reason, when what it needs is not there:
- test_guards.sh          Wine (the guarded wine-proton install and tools/bin/_wineguard)
- test_display_awake*.sh  an X display in the CALLER's environment ($DISPLAY) plus xset / xfce4-screensaver-command
- test_input_gate.sh      $DISPLAY, python-xlib, the dev baseline B (lane clone), a free input.lock, and >= 1 lane
- test_lanes.sh           the dev baseline B and >= 3 lanes (it uses lanes 6-8 at once)
Lane budget: $HARNESS_LANE_TESTS, else $CI_LANES (ci.sh --lanes N), else 0: lane suites are opt-in, so a plain
`pytest harness/tests` or an `env -i` run never takes a lane. The suites themselves source tools/env.sh, so the gate
here looks at the environment pytest was started with (an `env -i` run has no DISPLAY and no lane budget).
A suite may also exit 77 itself ("SKIP <reason>"), e.g. when input.lock is held by another agent.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
WINE = Path("/usr/lib/wine-proton-11.0.1/bin/wine")
GUARD = REPO / "tools" / "bin" / "_wineguard"
BASELINE_B = Path("/home/user/freelancer/prefix-dev-base-B/BASELINE.json")


def lane_budget() -> int:
    for k in ("HARNESS_LANE_TESTS", "CI_LANES"):
        v = os.environ.get(k, "")
        if v.strip().isdigit():
            return int(v)
    return 0


def have_x() -> str | None:
    if not os.environ.get("DISPLAY"):
        return "no DISPLAY in the environment (headless CI / env -i)"
    if not shutil.which("xdotool") or not shutil.which("xset"):
        return "xdotool/xset not installed"
    return None


def have_wine() -> str | None:
    if not WINE.exists() or not GUARD.exists():
        return f"Wine not available ({WINE} / {GUARD})"
    return None


def need_lanes(n: int) -> str | None:
    if lane_budget() < n:
        return (f"needs {n} lane(s); lane tests are opt-in (HARNESS_LANE_TESTS={n} or harness/ci.sh --lanes {n}), "
                f"budget now {lane_budget()}")
    if not BASELINE_B.exists():
        return f"dev baseline B not present ({BASELINE_B.parent})"
    return None


def have_xlib() -> str | None:
    try:
        import Xlib  # noqa: F401
    except ImportError:
        return "python-xlib not installed"
    return None


def run_suite(name: str, timeout: float) -> None:
    r = subprocess.run(["bash", str(TESTS / name)], capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    if r.returncode == 77:
        pytest.skip(next((l for l in out.splitlines() if l.startswith("SKIP")), f"{name} skipped itself"))
    fails = [l for l in out.splitlines() if l.startswith("FAIL")]
    assert r.returncode == 0, f"{name} rc={r.returncode}; " + "; ".join(fails[:10]) + "\n" + out[-3000:]


def skip_if(reason: str | None) -> None:
    if reason:
        pytest.skip(reason)


def test_guards():
    skip_if(have_wine())
    run_suite("test_guards.sh", 600)


@pytest.mark.parametrize("suite", ["test_display_awake.sh", "test_display_awake_interrupt.sh"])
def test_display_awake(suite):
    skip_if(have_x())
    skip_if(None if shutil.which("xfce4-screensaver-command") else "xfce4-screensaver-command not installed")
    run_suite(suite, 300)


def test_input_gate():
    skip_if(have_x() or have_xlib() or need_lanes(1) or have_wine())
    run_suite("test_input_gate.sh", 600)


def test_lanes():
    skip_if(need_lanes(3) or have_wine())
    run_suite("test_lanes.sh", 1800)
