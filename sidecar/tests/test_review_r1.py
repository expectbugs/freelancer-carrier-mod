"""Regression tests for review round 1 (state/reports/P0-SIDECAR-r1.md; NOTES.md "Review r1").

One section per finding: the stopped-tick lifecycle (pause, deferred and late acks, PTT cancel),
abort on a send timeout, per-process command ids, the play-port guards and welcome.ptt_vk, the
brain off the event loop plus the CONVENTIONS §13 sandbox data, voice_smoke --require-cuda (all
libraries mocked), and the critical_hull cap in the fake DLL's policy model.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from conftest import REPO_DIR, SCRIPTS_DIR, SIDECAR_DIR, run, running_app
from flcopilot import protocol
from flcopilot import server as server_mod
from flcopilot.audio.capture import Mic
from flcopilot.brain import (BRAIN_CLI_FLAGS, BRAIN_CWD, BRAIN_ENV_ALLOWLIST, FakeBrain, brain_command, brain_env,
                             check_init_message)
from flcopilot.profiles import ProfileError, check_port

RUN_SH = SIDECAR_DIR / "run.sh"
FAKEGAME = SIDECAR_DIR / "tools" / "fakegame.py"
#: server.stop() warnings that mean a stuck peer delayed the shutdown.
STUCK_WARNINGS = ("session did not finish in time", "listener did not close in time")


async def until(pred, timeout: float = 2.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


def established_on(port: int) -> list[str]:
    """Remote addresses of ESTABLISHED IPv4 sockets whose local port is ``port`` (server side)."""
    out = []
    with open("/proc/net/tcp", encoding="ascii") as fh:
        next(fh)
        for line in fh:
            parts = line.split()
            if len(parts) > 3 and parts[3] == "01" and int(parts[1].split(":")[1], 16) == port:
                out.append(parts[2])
    return out


def hello_line(seq: int = 1) -> bytes:
    return json.dumps({"v": 1, "t": "hello", "seq": seq, "gt": 0, "dll": "raw/0.1", "game": "raw"},
                      separators=(",", ":")).encode() + b"\n"


async def raw_client(port: int, rcvbuf: int = 4096) -> socket.socket:
    """A peer that sends hello and then never reads (small receive buffer)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    s.setblocking(False)
    loop = asyncio.get_running_loop()
    await loop.sock_connect(s, ("127.0.0.1", port))
    await loop.sock_sendall(s, hello_line())
    return s


# ---- MAJOR: stopped game tick (ipc.md §4.7) ---------------------------------------------------
def test_pause_suspends_ack_timeouts_and_keeps_the_heartbeat(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 0.8, "server.heartbeat_s": 0.05}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            sess = await app.server.wait_for_session()
            await until(lambda: sess.tick == "running", what="tick running")  # the timer gets armed
            fut = await sess.send_command("act", do="use_bots")
            cmd = await g.expect({"t": "act"})
            # The tick stops: ev.pause{on:true}, then the one paused snapshot.
            await g.send("ev.pause", on=True)
            await g.send("state", rate="paused", ship={"hull": 0.8, "shield": 0.4, "mode": "free"})
            await until(lambda: sess.tick == "stopped", what="tick stopped")
            pings_before = len(g.pings)
            await g.expect_silence(1.3)  # longer than the ack timeout; the sidecar's pings get auto-pongs
            assert not fut.done() and app.server.stats.ack_timeouts == 0
            assert len(g.pings) - pings_before >= 5  # the sidecar kept its heartbeat through the pause
            await g.send("ping", n=99)  # and keeps answering ours
            assert (await g.expect({"t": "pong"}))["n"] == 99
            # A command sent while paused is not timed either (the DLL queues it, §4.7.3).
            fut2 = await sess.send_command("say", speaker="copilot", text="Holding.", prio=2, subtitle=True)
            cmd2 = await g.expect({"t": "say"})
            await g.expect_silence(1.0)
            assert not fut2.done() and app.server.stats.ack_timeouts == 0
            # Resume: the deferred acks arrive once the tick has applied the commands.
            await g.send("ev.pause", on=False)
            await g.ack(cmd)
            await g.ack(cmd2, applied={"shown": True})
            a1, a2 = await asyncio.wait_for(asyncio.gather(fut, fut2), 2.0)
            assert a1["id"] == cmd["id"] and a1["ok"] is True and a2["id"] == cmd2["id"]
            st = app.server.stats
            assert st.ack_timeouts == 0 and st.late_acks == 0 and st.ping_timeouts == 0
            assert sess.reconciled == [] and sess.pending == {} and sess.tick == "running" and not sess.closing
            await g.close()
    run(body())


def test_resume_rearms_the_ack_timer_in_full(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 0.6}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            sess = await app.server.wait_for_session()
            await until(lambda: sess.tick == "running", what="tick running")
            fut = await sess.send_command("act", do="use_batts")
            await g.expect({"t": "act"})
            await g.send("ev.pause", on=True)
            await until(lambda: sess.tick == "stopped", what="tick stopped")
            await g.expect_silence(1.0)
            await g.send("ev.pause", on=False)
            await until(lambda: sess.tick == "running", what="tick running")
            t_resume = time.monotonic()
            assert await asyncio.wait_for(fut, 3.0) is None  # no ack after the resume: overdue again
            assert time.monotonic() - t_resume >= 0.5  # a full new timeout, not the remainder
            assert app.server.stats.ack_timeouts == 1
            await g.close()
    run(body())


def test_late_ack_is_reconciled_and_session_end_resolves_the_rest(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 0.2}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            sess = await app.server.wait_for_session()
            await until(lambda: sess.tick == "running", what="tick running")
            seen_sync: list = []
            seen_async: list = []

            async def on_late_async(ack):
                seen_async.append(ack)

            fut1 = await sess.send_command("policy.set", on_late=seen_sync.append, scope="player", bots_reserve=7)
            fut2 = await sess.send_command("act", on_late=on_late_async, do="use_bots")
            c1 = await g.expect({"t": "policy.set"})
            c2 = await g.expect({"t": "act"})
            assert await asyncio.wait_for(fut1, 2.0) is None  # overdue: reported as None ...
            assert await asyncio.wait_for(fut2, 2.0) is None
            assert app.server.stats.ack_timeouts == 2
            assert sess.pending[c1["id"]].late and sess.pending[c2["id"]].late  # ... but still pending
            with patch.object(server_mod.log, "warning", wraps=server_mod.log.warning) as warn:
                await g.ack(c1)  # the fake DLL computes the full clamped policy
                await g.ack(c2)
                await until(lambda: len(sess.reconciled) == 2, what="two reconciled acks")
            assert not any("unknown id" in str(c.args[0]) for c in warn.call_args_list)
            assert app.server.stats.late_acks == 2
            assert [a["id"] for a in sess.reconciled] == [c1["id"], c2["id"]]
            assert seen_sync == [sess.reconciled[0]] and seen_sync[0]["applied"]["bots_reserve"] == 7
            assert [a["id"] for a in seen_async] == [c2["id"]]
            assert sess.pending == {}
            # A late command that never gets its ack, and a fresh one: both end with the session.
            fut3 = await sess.send_command("say", speaker="copilot", text="One.")
            await g.expect({"t": "say"})
            assert await asyncio.wait_for(fut3, 2.0) is None and sess.pending[next(iter(sess.pending))].late
            fut4 = await sess.send_command("say", speaker="copilot", text="Two.")
            await g.expect({"t": "say"})
            await g.close()
            await asyncio.wait_for(sess.done.wait(), 2.0)
            assert await asyncio.wait_for(fut4, 1.0) is None
            assert sess.pending == {} and app.server.stats.late_acks == 2
    run(body())


class CancelMic(Mic):
    name = "cancel-recording"

    def __init__(self):
        self.events: list[str] = []

    def open(self):
        self.events.append("open")

    def close(self):
        self.events.append("close")

    def ptt_down(self):
        self.events.append("down")

    async def ptt_up(self):
        self.events.append("up")
        return None

    def cancel(self):
        self.events.append("cancel")

    def reset(self):
        self.events.append("reset")


def test_ptt_cancel_discards_the_utterance_for_every_reason(fakegame):
    async def body():
        async with running_app() as (app, port):
            mic = CancelMic()
            app.profile.mic = mic
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await until(lambda: "open" in mic.events, what="mic open")
            assert mic.events == ["reset", "open"]  # no recording state survives into a new session
            for reason in protocol.PTT_CANCEL_REASONS:
                await g.ptt(True)
                await g.ptt(False, reason=reason)
            await g.expect_silence(0.4)  # no policy.set, no say
            assert app.pipeline.cancelled == len(protocol.PTT_CANCEL_REASONS)
            assert app.profile.transcriber.calls == 0 and app.profile.brain.calls == []
            assert mic.events.count("cancel") == len(protocol.PTT_CANCEL_REASONS) and "up" not in mic.events
            # A reason on a press is invalid and dropped.
            await g.send("ptt", down=True, reason="pause")
            await g.send("ping", n=1)
            await g.expect({"t": "pong"})
            assert app.server.stats.invalid == 1 and mic.events.count("down") == len(protocol.PTT_CANCEL_REASONS)
            # The next normal press is handled as usual.
            await g.ptt(True)
            await g.ptt(False)
            await g.expect({"t": "policy.set"}, timeout=3)
            await g.ack()
            await g.expect({"t": "say"})
            await g.ack()
            await until(lambda: app.pipeline.utterances == 1, what="utterance handled")
            # Disconnect with the key held: the session end cancels the press, then closes the mic.
            await g.ptt(True)
            await g.send("ping", n=2)
            await g.expect({"t": "pong"})
            n = len(mic.events)
            await g.close()
            await until(lambda: "close" in mic.events[n:], what="mic closed")
            assert mic.events[n:] == ["cancel", "close"]
    run(body())


# ---- MINOR: a peer that stops reading is aborted, never left half-open --------------------------
def test_send_timeout_aborts_a_peer_that_never_reads(monkeypatch):
    monkeypatch.setattr(server_mod, "SEND_TIMEOUT_S", 0.2)

    async def body():
        async with running_app() as (app, port):
            s = await raw_client(port)
            try:
                sess = await app.server.wait_for_session()
                assert established_on(port), "the session socket should be visible in /proc/net/tcp"
                with pytest.raises(ConnectionError):
                    for _ in range(200_000):
                        await sess.send_command("say", speaker="copilot", text="x" * 500)
                assert sess.close_reason == "send_timeout"
                assert app.server.stats.send_timeouts == 1
                await asyncio.wait_for(sess.done.wait(), 2.0)
                assert sess.pending == {} and app.server.active is None
                assert established_on(port) == []
                t0 = time.monotonic()
                with patch.object(server_mod.log, "warning", wraps=server_mod.log.warning) as warn:
                    await app.server.stop("shutdown")
                assert time.monotonic() - t0 < 1.0
                assert not any(str(c.args[0]) in STUCK_WARNINGS for c in warn.call_args_list)
            finally:
                s.close()
    run(body())


@pytest.mark.parametrize("via", ["session.close", "server.stop"])
def test_close_aborts_when_the_flush_never_finishes(monkeypatch, via):
    """bye goes into the write buffer (drain does not block), but the peer never reads: neither
    close() nor the server's stop() may wait for the flush forever."""
    monkeypatch.setattr(server_mod, "CLOSE_FLUSH_S", 0.3)

    async def body():
        async with running_app() as (app, port):
            s = await raw_client(port)
            try:
                sess = await app.server.wait_for_session()
                tr = sess.writer.transport
                tr.set_write_buffer_limits(high=64 << 20)  # drain() returns at once; data piles up
                for _ in range(200_000):
                    if tr.get_write_buffer_size() > 0:
                        break
                    await sess.send_command("say", speaker="copilot", text="y" * 500)
                assert tr.get_write_buffer_size() > 0  # the kernel buffers are full
                t0 = time.monotonic()
                if via == "server.stop":
                    with patch.object(server_mod.log, "warning", wraps=server_mod.log.warning) as warn:
                        await app.server.stop("shutdown")
                    texts = [str(c.args[0]) for c in warn.call_args_list]
                    assert "close did not flush in time; aborting" in texts
                    assert not any(t in STUCK_WARNINGS for t in texts)
                else:
                    await sess.close("shutdown", detail="test")
                await asyncio.wait_for(sess.done.wait(), 3.0)
                assert 0.25 <= time.monotonic() - t0 < 2.5
                assert established_on(port) == []
                assert app.server.active is None
            finally:
                s.close()
    run(body())


# ---- MINOR: command ids are unique per process --------------------------------------------------
def test_command_ids_never_repeat_and_stale_acks_resolve_nothing(fakegame):
    async def body():
        async with running_app() as (app, port):
            a = fakegame.FakeGame(port=port, name="game-a")
            await a.connect()
            await a.handshake()
            sa = await app.server.wait_for_session()
            fa = await sa.send_command("act", do="use_bots")
            ca = await a.expect({"t": "act"})
            await a.close()  # the game restarts before acking
            await asyncio.wait_for(sa.done.wait(), 2.0)
            assert await asyncio.wait_for(fa, 1.0) is None  # lost with its session
            b = fakegame.FakeGame(port=port, name="game-b")
            await b.connect()
            await b.handshake()
            sb = await app.server.wait_for_session()
            assert sb is not sa
            fb = await sb.send_command("act", do="use_bots")
            cb = await b.expect({"t": "act"})
            assert cb["id"] != ca["id"] and int(cb["id"][2:]) > int(ca["id"][2:])
            # A stale ack for A's command arriving on B must not resolve B's command.
            await b.send("ack", id=ca["id"], ok=True, applied={"do": "use_bots"})
            await b.send("ping", n=1)
            await b.expect({"t": "pong"})
            assert not fb.done() and cb["id"] in sb.pending
            await b.ack(cb)
            assert (await asyncio.wait_for(fb, 2.0))["id"] == cb["id"]
            await b.close()
            return ca["id"], cb["id"]

    first = run(body())
    second = run(body())  # a new server in the same process continues the counter
    nums = [int(x[2:]) for x in (*first, *second)]
    assert nums == sorted(nums) and len(set(nums)) == 4


# ---- MINOR: the play port 29170 is guarded; welcome.ptt_vk --------------------------------------
@pytest.mark.parametrize("profile,port,allow,env,refused", [
    ("test", 29170, False, {}, True),
    ("test", 29170, True, {}, False),
    ("test", 29170, False, {"FLCOPILOT_ALLOW_PLAY_PORT": "1"}, False),
    ("test", 29170, False, {"FLCOPILOT_ALLOW_PLAY_PORT": "0"}, True),
    ("test", 29171, False, {}, False),
    ("test", 0, False, {}, False),
    ("live", 29170, False, {}, False),
])
def test_check_port(profile, port, allow, env, refused):
    if refused:
        with pytest.raises(ProfileError, match="play port"):
            check_port(profile, port, allow, env=env)
    else:
        check_port(profile, port, allow, env=env)


def launcher_env(tmp_path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FLCOPILOT_")}
    env["FLMOD_SIDECAR_VENV"] = sys.prefix
    env["FLMOD_LOCAL"] = str(tmp_path)
    env.update(extra)
    return env


# These tests must never hold or reach the host's 29170, even if a guard regresses (review r2):
# the in-process ones patch out serving and binding, and the subprocess ones run in a private
# network namespace (its own loopback and its own 29170) and are killed on any ready line.
PLAY_PORT_CASES = [
    ({}, []),                                   # config default port 29170
    ({"FLCOPILOT_PORT": "29170"}, []),          # from the environment
    ({}, ["--port", "29170"]),                  # explicit
]


def isolated(argv: list[str]) -> list[str]:
    """argv run in a new user + network namespace with its own loopback up."""
    return ["unshare", "-rn", "sh", "-c", 'ip link set lo up && exec "$@"', "sh", *map(str, argv)]


@pytest.fixture(scope="module")
def netns():
    try:
        ok = subprocess.run(isolated(["true"]), capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if not ok:
        pytest.skip("needs `unshare -rn` and `ip` (a private network namespace), so that a regressed "
                    "guard can never bind or reach the host's play port; the in-process guard tests still run")
    return isolated


def run_killing_on_ready(argv, env, timeout: float = 30.0):
    """Run argv; kill it the moment it prints the ready line (it bound a port). Returns
    (returncode, stdout, stderr, saw_ready)."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    lines: list[str] = []
    ready = threading.Event()

    def reader():
        for line in proc.stdout:
            lines.append(line)
            if "FLCOPILOT ready" in line:
                ready.set()
                proc.kill()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        rc = proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = proc.wait()
    t.join(5)
    err = proc.stderr.read()
    proc.stderr.close()
    return rc, "".join(lines), err, ready.is_set()


@pytest.mark.parametrize("extra_env,args", PLAY_PORT_CASES)
def test_cli_guard_refuses_before_anything_binds(tmp_path, monkeypatch, extra_env, args):
    from flcopilot import cli
    for k in [k for k in os.environ if k.startswith("FLCOPILOT_")]:
        monkeypatch.delenv(k)
    for k, v in extra_env.items():
        monkeypatch.setenv(k, v)
    with patch("flcopilot.cli.serve", new=AsyncMock(return_value=0)) as serve, \
            patch("asyncio.start_server", side_effect=AssertionError("a socket was bound")) as bind:
        rc = cli.main(["--profile", "test", *args, "--no-local-config", "--log-file", str(tmp_path / "l.log"),
                       "--quiet"])
    assert rc == 2 and not serve.called and not bind.called
    assert "play port" in (tmp_path / "l.log").read_text(encoding="utf-8")


def test_cli_selftest_picks_port_0_before_anything_binds(tmp_path, monkeypatch):
    from flcopilot import cli
    for k in [k for k in os.environ if k.startswith("FLCOPILOT_")]:
        monkeypatch.delenv(k)
    with patch("flcopilot.cli.selftest", new=AsyncMock(return_value=0)) as selftest, \
            patch("asyncio.start_server", side_effect=AssertionError("a socket was bound")):
        rc = cli.main(["--selftest", "--no-local-config", "--log-file", str(tmp_path / "l.log"), "--quiet"])
    assert rc == 0 and selftest.call_args.args[0].get("server.port") == 0


@pytest.mark.parametrize("extra_env,args", PLAY_PORT_CASES)
def test_run_sh_test_profile_refuses_play_port(tmp_path, netns, extra_env, args):
    log = tmp_path / "l.log"
    rc, out, err, saw_ready = run_killing_on_ready(
        netns([RUN_SH, "--profile", "test", *args, "--log-file", log, "--quiet"]),
        launcher_env(tmp_path, **extra_env))
    assert not saw_ready, "the test profile started serving on the play port (inside the private namespace)"
    assert rc == 2, (out, err)
    assert "play port" in log.read_text(encoding="utf-8")


def test_selftest_defaults_to_an_ephemeral_port(tmp_path, netns):
    res = subprocess.run(netns([RUN_SH, "--selftest", "--log-file", tmp_path / "l.log", "--quiet"]),
                         capture_output=True, text=True, timeout=60, env=launcher_env(tmp_path))
    assert res.returncode == 0, (res.stdout, res.stderr)
    port = int(res.stdout.split("port=")[1].split()[0])
    assert port not in (0, protocol.DEFAULT_PORT)


@pytest.mark.parametrize("args,extra_env,needle", [
    ([], {}, "--port is required"),
    (["--port", "29170"], {}, "refusing the play port"),
    ([], {"FLCOPILOT_PORT": "29170"}, "refusing the play port"),
])
def test_fakegame_cli_needs_a_non_play_port(tmp_path, netns, args, extra_env, needle):
    env = launcher_env(tmp_path, **extra_env)
    res = subprocess.run(netns([sys.executable, "-I", FAKEGAME, *args, SCRIPTS_DIR / "handshake.ndjson"]),
                         capture_output=True, text=True, timeout=30, env=env)
    assert res.returncode == 2 and needle in res.stderr, (res.stdout, res.stderr)


def test_fakegame_has_no_default_port(fakegame):
    with pytest.raises(TypeError):
        fakegame.FakeGame()


@pytest.mark.parametrize("ptt_key,vk", [("numpad_period", 110), ("numpad_minus", 109)])
def test_welcome_carries_the_configured_ptt_vk(fakegame, ptt_key, vk):
    async def body():
        async with running_app(**{"audio.ptt_key": ptt_key}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            with patch.object(server_mod.log, "warning", wraps=server_mod.log.warning) as warn:
                welcome = await g.handshake(ptt_vk=110)  # the DLL polls VK 110 (its INI)
                await g.send("ping", n=1)
                await g.expect({"t": "pong"})
            assert welcome["ptt_vk"] == vk
            mismatch = [c for c in warn.call_args_list if "push-to-talk" in str(c.args[0])]
            assert len(mismatch) == (0 if vk == 110 else 1)
            await g.close()
    run(body())


def test_readme_examples_avoid_the_play_port_for_tests():
    text = (SIDECAR_DIR / "README.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "fakegame" in line and "--port" in line:
            assert "--port 29170" not in line, line
    assert "--allow-play-port" in text


# ---- MINOR: the brain never blocks the event loop; §13 sandbox data ----------------------------
class BlockingBrain(FakeBrain):
    """Stays inside respond() until the test releases it (or 3 s pass)."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()

    def respond(self, utterance, state):
        self.entered.set()
        self.release.wait(3.0)
        try:
            return super().respond(utterance, state)
        finally:
            self.returned.set()


def test_slow_brain_does_not_block_pings_or_io(fakegame):
    async def body():
        async with running_app(**{"server.heartbeat_s": 0.05}) as (app, port):
            brain = BlockingBrain()
            app.profile.brain = brain
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.ptt(True)
            await g.ptt(False)
            assert await asyncio.to_thread(brain.entered.wait, 3.0)
            rtts = []
            for n in range(3):
                t0 = time.perf_counter()
                await g.send("ping", n=n)
                assert (await g.expect({"t": "pong"}))["n"] == n
                rtts.append(time.perf_counter() - t0)
            # The loop served the pings while the brain was still inside respond().
            assert not brain.returned.is_set()
            assert max(rtts) < 0.15, rtts
            brain.release.set()
            await g.expect({"t": "policy.set"}, timeout=3)
            await g.ack()
            await g.expect({"t": "say"})
            await g.ack()
            await until(lambda: app.pipeline.utterances == 1, what="utterance handled")
            assert app.server.stats.ping_timeouts == 0
            await g.close()
    run(body())


def test_brain_env_is_an_allowlist():
    environ = {"HOME": "/home/u", "PATH": "/usr/bin", "LANG": "en_US.utf8", "USER": "u",
               "XDG_RUNTIME_DIR": "/run/user/1000", "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli",
               "ANTHROPIC_API_KEY": "dummy", "SSH_AUTH_SOCK": "/tmp/agent", "FLMOD_LOCAL": "/x",
               "LD_LIBRARY_PATH": "/y", "PYTHONPATH": "/z", "DISPLAY": ":0", "EMPTY": ""}
    env = brain_env(environ)
    assert set(env) == {"HOME", "PATH", "LANG", "USER", "XDG_RUNTIME_DIR", "CLAUDE_CODE_DISABLE_AUTO_MEMORY"}
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1" and env["HOME"] == "/home/u"
    assert set(BRAIN_ENV_ALLOWLIST) >= {"HOME", "PATH", "LANG", "USER", "XDG_RUNTIME_DIR"}
    assert brain_env({"PATH": "/usr/bin", "HOME": ""}) == {"PATH": "/usr/bin", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


def test_brain_command_carries_every_section_13_flag():
    argv = brain_command("/usr/bin/claude", system_prompt="You are the copilot.")
    assert argv[0] == "/usr/bin/claude" and tuple(argv[1:1 + len(BRAIN_CLI_FLAGS)]) == BRAIN_CLI_FLAGS

    def value(flag):
        return argv[argv.index(flag) + 1]

    assert value("--tools") == ""
    assert "--strict-mcp-config" in argv and "--mcp-config" not in argv
    assert value("--disallowedTools") == "mcp__*"
    assert value("--setting-sources") == ""
    assert value("--system-prompt") == "You are the copilot."
    for risky in ("--dangerously-skip-permissions", "--allowedTools", "--add-dir", "--continue", "--resume"):
        assert risky not in argv
    assert "--system-prompt" not in brain_command("/usr/bin/claude")


def test_brain_cwd_is_outside_the_repo():
    cwd = Path(BRAIN_CWD)
    assert cwd.is_absolute() and str(cwd) == "/home/user/freelancer/carrier-brain-cwd"
    assert REPO_DIR.resolve() not in (cwd, *cwd.parents)


@pytest.mark.parametrize("msg,problems", [
    ({"type": "system", "subtype": "init", "tools": [], "mcp_servers": []}, []),
    ({"type": "system", "subtype": "init", "tools": ["Bash", "Read"], "mcp_servers": []}, ["2 tool(s)"]),
    ({"type": "system", "subtype": "init", "tools": [], "mcp_servers": [{"name": "x", "status": "connected"}]},
     ["1 MCP server(s)"]),
    ({"type": "system", "subtype": "init"}, ["no tools list", "no mcp_servers list"]),
    ({"type": "assistant"}, ["not a system/init message"]),
    ("garbage", ["not a system/init message"]),
])
def test_check_init_message(msg, problems):
    got = check_init_message(msg)
    assert len(got) == len(problems)
    for needle, text in zip(problems, got):
        assert needle in text


# ---- MINOR: voice_smoke --require-cuda (every library mocked; no GPU, model or audio) ----------
def _segments(text: str):
    def transcribe(*args, **kwargs):
        return iter([SimpleNamespace(start=0.0, end=1.5, text=" " + text)]), SimpleNamespace(language="en",
                                                                                            duration=1.5)
    return transcribe


@pytest.fixture
def smoke_env(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy", reason="sidecar venv test (numpy not installed here)")
    for mod in ("soundfile", "kokoro_onnx", "faster_whisper"):
        pytest.importorskip(mod, reason=f"sidecar venv test ({mod} not installed here)")
    import voice_smoke

    kdir = tmp_path / "models" / "kokoro"
    kdir.mkdir(parents=True)
    (kdir / "kokoro-v1.0.onnx").write_bytes(b"x")
    (kdir / "voices-v1.0.bin").write_bytes(b"x")
    monkeypatch.setenv("FLMOD_MODELS", str(tmp_path / "models"))
    return SimpleNamespace(np=np, mod=voice_smoke, out=tmp_path / "run")


def _run_smoke(env, args, cuda_ok: bool, text: str = "Save nanobots for the cruiser."):
    np = env.np

    def whisper_model(src, device, compute_type, local_files_only):
        assert local_files_only is True
        if device == "cuda" and not cuda_ok:
            raise RuntimeError("CUDA failed with error unknown error")
        return SimpleNamespace(transcribe=_segments(text))

    with patch("kokoro_onnx.Kokoro") as kokoro, \
            patch("faster_whisper.WhisperModel", side_effect=whisper_model) as wm, \
            patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi")):
        kokoro.return_value.create.return_value = (np.zeros(4800, dtype=np.float32), 24000)
        rc = env.mod.main(["--out", str(env.out), "--warm-runs", "1", *args])
    summary = json.loads((env.out / "summary.json").read_text(encoding="utf-8"))
    return rc, summary, wm


def test_voice_smoke_require_cuda_fails_without_cpu_attempt(smoke_env, capsys):
    rc, summary, wm = _run_smoke(smoke_env, ["--require-cuda"], cuda_ok=False)
    assert rc == 1 and summary["result"] == "fail"
    assert wm.call_count == 1 and wm.call_args.kwargs["device"] == "cuda"  # no CPU fallback attempted
    assert summary["note"].startswith("CUDA required") and "CUDA failed" in summary["error"]
    assert "VOICE_SMOKE FAIL(fail)" in capsys.readouterr().out


def test_voice_smoke_reports_cpu_fallback_distinctly(smoke_env, capsys):
    rc, summary, wm = _run_smoke(smoke_env, [], cuda_ok=False)
    assert rc == 0 and summary["result"] == "ok-cpu-fallback"
    assert [c.kwargs["device"] for c in wm.call_args_list] == ["cuda", "cpu"]
    assert summary["stt"]["device"] == "cpu" and summary["stt"]["compute_type"] == "int8"
    assert "CUDA failed" in summary["stt"]["fallback_reason"] and summary["note"].startswith("CPU fallback")
    assert summary["gpu"]["cuda_used"] is False
    assert "VOICE_SMOKE ok-cpu-fallback" in capsys.readouterr().out


def test_voice_smoke_ok_on_cuda(smoke_env, capsys):
    rc, summary, wm = _run_smoke(smoke_env, ["--require-cuda"], cuda_ok=True)
    assert rc == 0 and summary["result"] == "ok" and wm.call_count == 1
    assert summary["stt"]["device"] == "cuda" and summary["stt"]["missing"] == []
    assert "VOICE_SMOKE ok " in capsys.readouterr().out


def test_voice_smoke_wrong_transcript_fails(smoke_env):
    rc, summary, _ = _run_smoke(smoke_env, [], cuda_ok=True, text="Save the robots for the cruiser.")
    assert rc == 1 and summary["result"] == "fail" and summary["stt"]["missing"] == ["nanobots"]


# ---- MINOR: critical_hull never exceeds bots_hull_below (fake DLL model, ipc.md §5) -------------
def test_fakegame_caps_critical_hull_at_bots_hull_below(fakegame):
    g = fakegame.FakeGame(port=1)

    def setp(**fields):
        ok, applied, err = g.apply_policy({"t": "policy.set", "id": "c-1", "scope": "player", **fields})
        assert ok and err is None, err
        return applied

    assert setp(critical_hull=0.95)["critical_hull"] == 0.5                # capped at bots_hull_below 0.5
    assert setp(critical_hull=0.4)["critical_hull"] == 0.4                 # inside the band
    a = setp(bots_hull_below=0.3)                                          # lowering the threshold re-clamps
    assert a["bots_hull_below"] == 0.3 and a["critical_hull"] == 0.3
    a = setp(bots_hull_below=0.1)                                          # below the floor: the floor wins
    assert a["bots_hull_below"] == 0.1 and a["critical_hull"] == 0.25
    assert setp(critical_hull=0.1)["critical_hull"] == 0.25                # never below the floor
    a = setp(bots_hull_below=0.9, critical_hull=0.95)                      # both at once
    assert a["bots_hull_below"] == 0.9 and a["critical_hull"] == 0.9
    a = setp(bots_hull_below=1.5, critical_hull=1.5)                       # both clamped to 0.95
    assert a["bots_hull_below"] == 0.95 and a["critical_hull"] == 0.95
    assert g.policy["carrier"]["critical_hull"] == 0.25                    # scopes are independent


def test_fakegame_ptt_cancel_validation(fakegame, tmp_path):
    g = fakegame.FakeGame(port=1)
    for down, reason in ((True, "pause"), (False, "bogus")):
        with pytest.raises(ValueError):
            run(g.ptt(down, reason=reason))
    assert fakegame.PTT_CANCEL_REASONS == protocol.PTT_CANCEL_REASONS
    script = tmp_path / "s.ndjson"
    script.write_text('{"ptt": "tap", "reason": "pause"}\n', encoding="utf-8")

    async def body():
        async with running_app() as (app, port):
            with pytest.raises(ValueError, match="only with ptt cancel"):
                await fakegame.run_script_file(script, port)
    run(body())
