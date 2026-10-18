"""The fake game client and its NDJSON scripts, against a real test-profile server."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from conftest import SCRIPTS_DIR, SIDECAR_DIR, run, running_app


def test_script_handshake(fakegame):
    async def body():
        async with running_app() as (app, port):
            game = await fakegame.run_script_file(SCRIPTS_DIR / "handshake.ndjson", port)
            assert [m["t"] for m in game.received] == ["welcome", "pong"]
            assert app.server.stats.sessions == 1
    run(body())


def test_script_policy_roundtrip(fakegame):
    async def body():
        async with running_app() as (app, port):
            game = await fakegame.run_script_file(SCRIPTS_DIR / "policy_roundtrip.ndjson", port)
            types = [m["t"] for m in game.received]
            assert types == ["welcome", "policy.set", "say"]
            pipe = app.pipeline
            assert pipe.utterances == 1
            assert pipe.last_timing["acks"] == 2 and pipe.last_timing["acks_ok"] == 2
            assert app.profile.transcriber.calls == 1
            assert app.profile.brain.calls == ["save nanobots for the cruiser"]
            assert app.profile.sink.plays == 1  # the spoken line went to the null sink
            assert app.server.stats.acks == 2 and app.server.stats.ack_timeouts == 0
            acks = [m for m in game.sent if m["t"] == "ack"]
            assert acks[0]["ok"] is True
            assert acks[0]["applied"] == {**fakegame.DEFAULT_POLICY, "bots_reserve": 7,
                                          "release_reserve_when": "capital_hostile_present"}
            assert game.violations == []
    run(body())


def test_script_reconnect(fakegame):
    async def body():
        async with running_app() as (app, port):
            game = await fakegame.run_script_file(SCRIPTS_DIR / "reconnect.ndjson", port)
            assert game.connections == 2
            assert [m["t"] for m in game.received] == ["welcome", "pong", "welcome", "pong"]
            assert app.server.stats.sessions == 2 and app.server.stats.replaced == 0
    run(body())


def test_script_version_mismatch(fakegame):
    async def body():
        async with running_app() as (app, port):
            game = await fakegame.run_script_file(SCRIPTS_DIR / "version_mismatch.ndjson", port)
            assert [m["t"] for m in game.received] == ["bye"]
            assert app.server.stats.version_mismatch == 1
    run(body())


def test_ptt_tap_without_snapshot_uses_default_reserve(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.ptt(True)
            await g.ptt(False)
            cmd = await g.expect({"t": "policy.set"}, timeout=3)
            assert cmd["bots_reserve"] == 5  # test.fake_bots_reserve
            await g.ack()
            await g.expect({"t": "say"})
            await g.ack()
            await g.close()
    run(body())


def test_failing_expectation_reports_line(fakegame, tmp_path):
    script = tmp_path / "bad.ndjson"
    script.write_text('{"expect": {"t": "welcome", "profile": "live"}}\n', encoding="utf-8")

    async def body():
        async with running_app() as (app, port):
            with pytest.raises(fakegame.ExpectationFailed, match="line 1"):
                await fakegame.run_script_file(script, port)
    run(body())


def test_unknown_directive_rejected(fakegame, tmp_path):
    script = tmp_path / "bad.ndjson"
    script.write_text('{"teleport": true}\n', encoding="utf-8")

    async def body():
        async with running_app() as (app, port):
            with pytest.raises(ValueError, match="unknown directive"):
                await fakegame.run_script_file(script, port)
    run(body())


def test_fakegame_cli(tmp_path):
    """The command-line entry point, as later packages and the harness use it."""
    async def body():
        async with running_app() as (app, port):
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", str(SIDECAR_DIR / "tools" / "fakegame.py"), "--port", str(port),
                str(SCRIPTS_DIR / "handshake.ndjson"), str(SCRIPTS_DIR / "reconnect.ndjson"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "FLCOPILOT_PORT": "1"})
            out, err = await proc.communicate()
            assert proc.returncode == 0, (out, err)
            text = out.decode()
            assert text.count("PASS ") == 2
    run(body())


def test_fakegame_has_no_flcopilot_dependency():
    src = (SIDECAR_DIR / "tools" / "fakegame.py").read_text(encoding="utf-8")
    assert "import flcopilot" not in src and "from flcopilot" not in src


@pytest.mark.parametrize("pattern,value,ok", [
    ({"t": "welcome"}, {"t": "welcome", "v": 1}, True),
    ({"t": "welcome"}, {"t": "bye"}, False),
    ({"n": "$int"}, {"n": 3}, True),
    ({"n": "$int"}, {"n": True}, False),
    ({"ok": True}, {"ok": 1}, False),
    ({"x": "$absent"}, {}, True),
    ({"x": "$absent"}, {"x": None}, False),
    ({"x": {"$range": [0.05, 0.95]}}, {"x": 0.5}, True),
    ({"x": {"$range": [0.05, 0.95]}}, {"x": 0.99}, False),
    ({"id": {"$re": "c-[0-9]+"}}, {"id": "c-12"}, True),
    ({"id": {"$re": "c-[0-9]+"}}, {"id": "x-12"}, False),
    ({"text": {"$contains": "bots"}}, {"text": "use nanobots"}, True),
    ({"l": [1, "$str"]}, {"l": [1, "a"]}, True),
    ({"l": [1]}, {"l": [1, 2]}, False),
    ({"o": {"a": 1}}, {"o": {"a": 1, "b": 2}}, True),
])
def test_match(fakegame, pattern, value, ok):
    assert (fakegame.match(pattern, value) is None) is ok
