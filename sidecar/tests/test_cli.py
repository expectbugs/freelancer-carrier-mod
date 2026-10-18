"""The launcher and CLI as real processes: run.sh --selftest, serve + SIGTERM, guards."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time

import pytest

from conftest import SCRIPTS_DIR, SIDECAR_DIR, run
from flcopilot.server import listening_addresses

RUN_SH = SIDECAR_DIR / "run.sh"


def launcher_env(tmp_path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FLCOPILOT_")}
    env["FLMOD_SIDECAR_VENV"] = sys.prefix  # the venv running these tests
    env["FLMOD_LOCAL"] = str(tmp_path)      # logs and overlay lookups stay in tmp
    env.update(extra)
    return env


def test_run_sh_selftest(tmp_path):
    log = tmp_path / "selftest.log"
    res = subprocess.run([str(RUN_SH), "--selftest", "--port", "0", "--log-file", str(log), "--quiet"],
                         capture_output=True, text=True, timeout=60, env=launcher_env(tmp_path))
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert "SELFTEST ok" in res.stdout
    assert "loopback_only=True" in res.stdout and "shutdown_bye=shutdown" in res.stdout
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    msgs = [r["msg"] for r in lines]
    assert "listening" in msgs and "hello" in msgs and "selftest ok" in msgs
    assert all({"ts", "lvl", "sub", "msg"} <= set(r) for r in lines)


def test_run_sh_environment(tmp_path):
    """run.sh puts the venv's CUDA-12 libs first on LD_LIBRARY_PATH, forces offline HF, and
    isolates sys.path (no user site, no cwd/script dir, PYTHONPATH = the sidecar dir)."""
    env = launcher_env(tmp_path, LD_LIBRARY_PATH="/opt/elsewhere")
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    res = subprocess.run([str(RUN_SH), "--tool", "env_probe"], capture_output=True, text=True, timeout=30,
                         env=env, cwd=str(tmp_path))
    assert res.returncode == 0, res.stderr
    probe = json.loads(res.stdout)
    assert probe["dbus_session_bus_address"] == "disabled:"  # no D-Bus autolaunch via X11 (NOTES B-2)
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/example-bus"
    res = subprocess.run([str(RUN_SH), "--tool", "env_probe"], capture_output=True, text=True, timeout=30, env=env)
    assert json.loads(res.stdout)["dbus_session_bus_address"] == "unix:path=/run/example-bus"  # a real one is kept
    assert probe["prefix"] == sys.prefix
    assert probe["hf_hub_offline"] == "1"
    assert probe["no_user_site"] and probe["safe_path"]
    assert probe["pythonpath"] == str(SIDECAR_DIR)
    assert probe["sys_path0"] == str(SIDECAR_DIR)
    site = [d for d in sys.path if d.endswith("site-packages")]
    if any(os.path.isdir(os.path.join(d, "nvidia", "cublas", "lib")) for d in site):
        ld = probe["ld_library_path"]
        assert ld[0].endswith("nvidia/cublas/lib") and ld[1].endswith("nvidia/cudnn/lib")
        assert ld[-1] == "/opt/elsewhere"


def test_serve_until_sigterm(tmp_path, fakegame):
    log = tmp_path / "serve.log"
    proc = subprocess.Popen([str(RUN_SH), "--profile", "test", "--port", "0", "--log-file", str(log), "--quiet"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=launcher_env(tmp_path))
    try:
        line = proc.stdout.readline()
        m = re.match(r"FLCOPILOT ready host=127\.0\.0\.1 port=(\d+) profile=test pid=(\d+)", line)
        assert m, line
        port = int(m.group(1))
        assert listening_addresses(port) == [("ipv4", "127.0.0.1")]
        run(fakegame.run_script_file(SCRIPTS_DIR / "handshake.ndjson", port))
        run(fakegame.run_script_file(SCRIPTS_DIR / "policy_roundtrip.ndjson", port))
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    msgs = [json.loads(x)["msg"] for x in log.read_text(encoding="utf-8").splitlines()]
    assert "shutdown clean" in msgs and "utterance handled" in msgs
    assert listening_addresses(port) == []


def test_env_port_is_honored(tmp_path):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    proc = subprocess.Popen([str(RUN_SH), "--profile", "test", "--log-file", str(tmp_path / "l.log"), "--quiet"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=launcher_env(tmp_path, FLCOPILOT_PORT=str(free)))
    try:
        line = proc.stdout.readline()
        assert f"port={free} " in line, line
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)


def test_live_profile_refused_under_pytest(tmp_path):
    # PYTEST_CURRENT_TEST is inherited by the child, so the live guard must refuse.
    res = subprocess.run([str(RUN_SH), "--profile", "live", "--port", "0", "--log-file", str(tmp_path / "l.log"),
                          "--quiet"], capture_output=True, text=True, timeout=30, env=launcher_env(tmp_path))
    assert res.returncode == 2
    assert "pytest" in (tmp_path / "l.log").read_text(encoding="utf-8")


def test_port_in_use_fails_cleanly(tmp_path):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        res = subprocess.run([str(RUN_SH), "--profile", "test", "--port", str(busy), "--log-file",
                              str(tmp_path / "l.log"), "--quiet"], capture_output=True, text=True, timeout=30,
                             env=launcher_env(tmp_path))
    assert res.returncode == 3


def test_print_config_masks_mic(tmp_path):
    ov = tmp_path / "ov.yaml"
    ov.write_text('mic_match: "Example_Headset"\n', encoding="utf-8")
    res = subprocess.run([str(RUN_SH), "--print-config", "--local-config", str(ov), "--quiet",
                          "--log-file", str(tmp_path / "l.log")],
                         capture_output=True, text=True, timeout=30, env=launcher_env(tmp_path))
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["audio"]["mic_match"] == "<set in local overlay>"
    assert "Example_Headset" not in res.stdout


def test_bad_config_exit_code(tmp_path):
    res = subprocess.run([str(RUN_SH), "--port", "99999", "--quiet"], capture_output=True, text=True, timeout=30,
                         env=launcher_env(tmp_path))
    assert res.returncode == 2 and "config error" in res.stderr


def test_run_sh_without_venv(tmp_path):
    env = launcher_env(tmp_path)
    env["FLMOD_SIDECAR_VENV"] = str(tmp_path / "no-venv")
    res = subprocess.run([str(RUN_SH), "--version"], capture_output=True, text=True, timeout=30, env=env)
    assert res.returncode == 2 and "venv not found" in res.stderr


def test_run_sh_rejects_unknown_tool(tmp_path):
    res = subprocess.run([str(RUN_SH), "--tool", "../../etc/passwd"], capture_output=True, text=True, timeout=30,
                         env=launcher_env(tmp_path))
    assert res.returncode == 2


@pytest.mark.parametrize("flag", ["--version"])
def test_version(tmp_path, flag):
    res = subprocess.run([str(RUN_SH), flag], capture_output=True, text=True, timeout=30, env=launcher_env(tmp_path))
    assert res.returncode == 0 and "protocol v1" in res.stdout
    time.sleep(0)
