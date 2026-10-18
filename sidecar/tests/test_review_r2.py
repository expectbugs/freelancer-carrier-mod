"""Regression tests for review round 2 (state/reports/P0-SIDECAR-r2.md; NOTES.md "Review r2 polish").

The tick is unknown until the DLL reports it after welcome (ipc.md §4.1, §4.7), integer widths
(§3), push-to-talk tracked per session (§7.2), the unknown-type log cap (§10.1), and the
critical_hull doc. The play-port test hardening lives with the original tests in test_review_r1.py.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from conftest import make_cfg, run, running_app
from flcopilot import protocol
from flcopilot import server as server_mod
from flcopilot.audio.capture import Mic
from flcopilot.pipeline import VoicePipeline
from flcopilot.profiles import build_profile
from flcopilot.protocol import ProtocolError, decode, validate


async def until(pred, timeout: float = 2.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


# ---- (a) the tick is unknown until the DLL reports it after welcome ------------------------------
def test_reconnect_while_paused_keeps_ack_timers_suspended(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 0.3}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake(state=False)
            sess = await app.server.wait_for_session()
            assert sess.tick == "unknown" and sess.paused
            # The sidecar sends at once; the DLL reports the stopped tick right after welcome.
            fut = await sess.send_command("act", do="use_bots")
            cmd = await g.expect({"t": "act"})
            await g.send("ev.pause", on=True)
            await g.send("state", rate="paused", ship={"hull": 0.8, "shield": 0.4, "mode": "free"})
            await until(lambda: sess.tick == "stopped", what="tick stopped")
            await g.expect_silence(0.8)  # well past the 0.3 s ack timeout
            assert not fut.done() and app.server.stats.ack_timeouts == 0
            await g.send("ev.pause", on=False)
            await g.ack(cmd)  # the deferred ack, after the queued command was applied
            assert (await asyncio.wait_for(fut, 2.0))["ok"] is True
            assert app.server.stats.ack_timeouts == 0 and sess.tick == "running"
            await g.close()
    run(body())


def test_reconnect_at_the_main_menu_gets_not_now(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 0.3}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake(state=False)
            sess = await app.server.wait_for_session()
            await g.send("ev.pause", on=True)
            await g.send("ev.menu")
            await g.send("state", rate="paused", ship=None)
            await until(lambda: sess.tick == "stopped", what="tick stopped")
            fut = await sess.send_command("policy.set", scope="player", bots_reserve=3)
            cmd = await g.expect({"t": "policy.set"})
            await g.expect_silence(0.5)
            assert not fut.done()
            await g.ack(cmd, ok=False, err="not_now", detail="main menu")  # the worker's immediate answer
            ack = await asyncio.wait_for(fut, 2.0)
            assert ack["ok"] is False and ack["err"] == "not_now" and app.server.stats.ack_timeouts == 0
            await g.close()
    run(body())


def test_ev_menu_alone_stops_the_tick(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()  # running
            sess = await app.server.wait_for_session()
            await until(lambda: sess.tick == "running", what="tick running")
            await g.send("ev.menu")
            await until(lambda: sess.tick == "stopped", what="tick stopped by ev.menu")
            await g.close()
    run(body())


@pytest.mark.parametrize("rate,tick", [("calm", "running"), ("combat", "running"), ("docked", "running"),
                                       ("paused", "stopped")])
def test_first_state_sets_the_tick(fakegame, rate, tick):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake(state={"rate": rate})
            sess = await app.server.wait_for_session()
            await until(lambda: sess.tick == tick, what=f"tick {tick}")
            await g.send("state", rate="calm")  # a later state never changes the tick: only edges do
            await g.send("ping", n=1)
            await g.expect({"t": "pong"})
            assert sess.tick == tick
            await g.close()
    run(body())


def test_running_tick_times_commands_out(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 0.3}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()  # sends a running state
            sess = await app.server.wait_for_session()
            await until(lambda: sess.tick == "running", what="tick running")
            fut = await sess.send_command("act", do="use_bots")
            await g.expect({"t": "act"})
            assert await asyncio.wait_for(fut, 2.0) is None and app.server.stats.ack_timeouts == 1
            await g.close()
    run(body())


def test_no_report_after_welcome_assumes_running(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 0.3, "server.handshake_timeout_s": 0.4}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            with patch.object(server_mod.log, "warning", wraps=server_mod.log.warning) as warn:
                await g.handshake(state=False)
                sess = await app.server.wait_for_session()
                fut = await sess.send_command("act", do="use_bots")
                await g.expect({"t": "act"})
                t0 = time.monotonic()
                assert await asyncio.wait_for(fut, 3.0) is None  # 0.4 s unknown, then a full 0.3 s timeout
                assert time.monotonic() - t0 >= 0.5
            assert sess.tick == "running"
            assert any("assuming the game tick runs" in str(c.args[0]) for c in warn.call_args_list)
            await g.close()
    run(body())


# ---- (f) integer widths ---------------------------------------------------------------------
def _env(t, **payload):
    return {"v": 1, "t": t, "seq": 1, "gt": 0, **payload}


@pytest.mark.parametrize("msg,ok", [
    ({"v": 1, "t": "ping", "seq": 2 ** 32 - 1}, True),
    ({"v": 1, "t": "ping", "seq": 2 ** 32}, False),
    ({"v": 1, "t": "ping", "seq": 1, "gt": 2 ** 53 - 1}, True),
    ({"v": 1, "t": "ping", "seq": 1, "gt": 2 ** 53}, False),
    (_env("ping", n=2 ** 32 - 1), True),
    (_env("ping", n=2 ** 32), False),
    (_env("ev.target", obj=2 ** 32 - 1), True),
    (_env("ev.target", obj=2 ** 32), False),
    (_env("state", rate="calm", target={"obj": 2 ** 32}), False),
    (_env("ev.reflex", what="bots", by="player", left=2 ** 31 - 1), True),
    (_env("ev.reflex", what="bots", by="player", left=2 ** 31), False),
    (_env("ev.hostiles", count=-1, capital=False), False),
    (_env("policy.set", id="c-1", scope="player", bots_reserve=-5), True),        # the DLL clamps to 0
    (_env("policy.set", id="c-1", scope="player", bots_reserve=2 ** 31), False),  # outside int32
    (_env("policy.set", id="c-1", scope="player", bots_reserve=-(2 ** 31) - 1), False),
])
def test_integer_widths(msg, ok):
    assert (validate(msg) == []) is ok, validate(msg)


@pytest.mark.parametrize("raw,ok", [
    (b'{"v":1,"t":"x","seq":1,"extra":9223372036854775807}', True),
    (b'{"v":1,"t":"x","seq":1,"extra":-9223372036854775808}', True),
    (b'{"v":1,"t":"x","seq":1,"extra":9223372036854775808}', False),
    (b'{"v":1,"t":"x","seq":1,"extra":[1,2,-9223372036854775809]}', False),
    (b'{"v":1,"t":"ping","seq":' + b"9" * 4000 + b"}", False),
])
def test_integers_outside_int64_are_malformed(raw, ok):
    if ok:
        assert decode(raw)["seq"] == 1
    else:
        with pytest.raises(ProtocolError) as exc:
            decode(raw)
        assert exc.value.code == "json" and "int64" in exc.value.detail


def test_server_drops_out_of_range_integers(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.send_raw(b'{"v":1,"t":"ping","seq":' + b"4" * 4000 + b',"gt":0,"n":5}\n')  # 4000-digit seq
            await g.send_raw(b'{"v":1,"t":"ping","seq":3,"gt":0,"n":4294967296}\n')        # n beyond uint32
            await g.send("ev.target", obj=2 ** 32)
            await g.send("ping", n=7)
            assert (await g.expect({"t": "pong"}))["n"] == 7  # neither bad ping was answered
            st = app.server.stats
            assert st.malformed == 1 and st.invalid == 2 and st.handler_errors == 0
            await g.close()
    run(body())


# ---- push-to-talk tracked per session (ipc.md §7.2) ------------------------------------------
class EdgeMic(Mic):
    name = "edges"

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


async def _session(app, fakegame, port):
    mic = EdgeMic()
    app.profile.mic = mic
    g = fakegame.FakeGame(port=port)
    await g.connect()
    await g.handshake()
    await until(lambda: "open" in mic.events, what="mic open")
    return g, mic


async def _sync(g, n: int = 1):
    await g.send("ping", n=n)  # everything sent before is handled once the pong is back
    await g.expect({"t": "pong"})


def test_unmatched_release_and_cancel_are_ignored(fakegame):
    async def body():
        async with running_app() as (app, port):
            g, mic = await _session(app, fakegame, port)
            await g.ptt(False)                          # release without a press
            await g.ptt(False, reason="focus_lost")     # cancel without a press
            await g.expect_silence(0.4)                 # no utterance, no policy.set, no say
            p = app.pipeline
            assert p.ignored_ptt == 2 and p.cancelled == 0 and p.utterances == 0
            assert app.profile.transcriber.calls == 0 and "up" not in mic.events and "cancel" not in mic.events
            await g.close()
    run(body())


def test_repeated_press_is_ignored_and_one_utterance_follows(fakegame):
    async def body():
        async with running_app() as (app, port):
            g, mic = await _session(app, fakegame, port)
            await g.ptt(True)
            await g.ptt(True)  # key repeat: ignored
            await g.ptt(False)
            await g.expect({"t": "policy.set"}, timeout=3)
            await g.ack()
            await g.expect({"t": "say"})
            await g.ack()
            await until(lambda: app.pipeline.utterances == 1, what="utterance")
            assert mic.events.count("down") == 1 and app.pipeline.ignored_ptt == 1
            await g.close()
    run(body())


def test_cancel_after_release_does_not_discard_the_utterance(fakegame):
    async def body():
        async with running_app() as (app, port):
            g, mic = await _session(app, fakegame, port)
            await g.ptt(True)
            await g.ptt(False)
            await g.ptt(False, reason="focus_lost")  # arrives during the tail: not down any more
            await g.expect({"t": "policy.set"}, timeout=3)
            await g.ack()
            await g.expect({"t": "say"})
            await g.ack()
            await until(lambda: app.pipeline.utterances == 1, what="utterance")
            assert app.pipeline.cancelled == 0 and "cancel" not in mic.events and app.pipeline.ignored_ptt == 1
            await g.close()
    run(body())


@pytest.mark.parametrize("edge", [{"t": "ev.pause", "on": True}, {"t": "ev.menu"},
                                  {"t": "ev.load", "save": "slot2", "char": "Test Pilot"}])
def test_tick_edges_cancel_a_held_press(fakegame, edge):
    async def body():
        async with running_app() as (app, port):
            g, mic = await _session(app, fakegame, port)
            await g.ptt(True)
            await g.send(edge)
            await _sync(g)
            assert app.pipeline.cancelled == 1 and mic.events[-1] == "cancel"
            await g.ptt(False)  # the late release is unmatched now
            await g.expect_silence(0.3)
            assert app.pipeline.utterances == 0 and app.pipeline.ignored_ptt == 1
            # Without a held press the edge changes nothing.
            await g.send(edge)
            await _sync(g, 2)
            assert app.pipeline.cancelled == 1
            await g.close()
    run(body())


def test_resume_does_not_cancel_a_press(fakegame):
    async def body():
        async with running_app() as (app, port):
            g, mic = await _session(app, fakegame, port)
            await g.ptt(True)
            await g.send("ev.pause", on=False)
            await _sync(g)
            assert app.pipeline.cancelled == 0 and "cancel" not in mic.events
            await g.close()
    run(body())


def test_ptt_from_a_session_that_does_not_own_the_mic_is_ignored():
    async def body():
        prof = build_profile("test", make_cfg())
        mic = EdgeMic()
        prof.mic = mic
        pipe = VoicePipeline(prof)
        old, new = SimpleNamespace(sid=1, last_state=None), SimpleNamespace(sid=2, last_state=None)
        pipe.on_session_start(old)
        pipe.on_session_start(new)  # the newer session replaced the old one and owns the mic
        pipe.on_ptt(old, {"t": "ptt", "down": True})
        pipe.on_ptt(old, {"t": "ptt", "down": False})
        pipe.on_tick_edge(old, {"t": "ev.menu"})
        assert "down" not in mic.events and "cancel" not in mic.events and pipe.ignored_ptt == 2
        assert not pipe._tasks
        pipe.on_ptt(new, {"t": "ptt", "down": True})
        assert mic.events[-1] == "down" and pipe._pressed
        pipe.on_session_end(old)  # the old session's end leaves the new press alone
        assert mic.events[-1] == "down" and pipe._pressed
    run(body())


# ---- unknown-type warnings are capped per connection (ipc.md §10.1) ---------------------------
def test_unknown_type_warnings_are_capped(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            with patch.object(server_mod.log, "warning", wraps=server_mod.log.warning) as warn:
                for i in range(server_mod.UNKNOWN_TYPES_LOGGED + 100):  # 164 distinct new types
                    await g.send(f"ev.future_{i}")
                for _ in range(50):                                   # repeats of a known-unknown one
                    await g.send("ev.future_0")
                for _ in range(50):                                   # repeats of one past the cap
                    await g.send("ev.future_150")
                await _sync(g)
            texts = [str(c.args[0]) for c in warn.call_args_list]
            assert texts.count("unknown message type ignored") == server_mod.UNKNOWN_TYPES_LOGGED
            assert sum("log cap reached" in t for t in texts) == 1
            assert len(texts) == server_mod.UNKNOWN_TYPES_LOGGED + 1
            assert app.server.stats.unknown_type == server_mod.UNKNOWN_TYPES_LOGGED + 200
            assert app.server.active is not None and not app.server.active.closing
            await g.close()
    run(body())


# ---- critical_hull doc matches the spec (ipc.md §5) --------------------------------------------
def test_critical_hull_doc_names_the_cap():
    doc = protocol.POLICY_FIELDS["critical_hull"].doc
    assert "min(bots_hull_below, 0.95)" in doc and "[floor, 0.95]" not in doc
