"""Regression tests for the defects found in the P0-SIDECAR self-review (NOTES.md B-5)."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from conftest import make_cfg, run, running_app
from flcopilot import config, protocol
from flcopilot.protocol import ProtocolError, decode, validate


# ---- 1, 2: lines that used to drop the connection ---------------------------------------
@pytest.mark.parametrize("raw", [
    b"[" * 20000 + b"]" * 20000 + b"\n",                      # RecursionError inside json.loads
    b'{"v":1,"t":"ping","seq":5,"gt":0,"n":1e400}\n',          # overflows to inf
    b'{"v":1,"t":"ping","seq":5,"gt":0,"n":"\\ud800"}\n',      # lone surrogate: cannot be re-encoded
    b'{"v":1,"t":"ping","seq":5,"gt":0,"n":{"x":[1,"a"]}}\n',  # wrong type, would be echoed
])
@pytest.mark.parametrize("before_hello", [True, False])
def test_hostile_lines_never_drop_the_connection(fakegame, raw, before_hello):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            if not before_hello:
                await g.handshake()
            await g.send_raw(raw)
            await g.send("ping", n=1)
            pong = await g.expect({"t": "pong"})
            assert pong["n"] == 1  # the hostile ping got no pong; the connection survived
            st = app.server.stats
            assert st.malformed + st.invalid == 1 and st.handler_errors == 0
            if before_hello:
                await g.handshake()
            await g.close()
    run(body())


def test_decode_rejects_overflow_surrogates_and_deep_nesting():
    for raw, code in ((b'{"v":1,"t":"x","seq":1,"a":1e400}', "json"),
                      (b'{"v":1,"t":"x","seq":1,"a":-1e999}', "json"),
                      (b'{"v":1,"t":"x","seq":1,"a":"\\udfff"}', "utf8"),
                      (b"[" * 25000 + b"]" * 25000, "json")):
        with pytest.raises(ProtocolError) as exc:
            decode(raw)
        assert exc.value.code == code
    # A proper surrogate pair is fine, and so is a deep-but-parseable array of the wrong type.
    assert decode(b'{"v":1,"t":"x","seq":1,"a":"\\ud83d\\ude00"}')["a"] == "\U0001F600"
    with pytest.raises(ProtocolError) as exc:
        decode(b"[" * 500 + b"]" * 500)
    assert exc.value.code == "not_object"


def test_handler_exception_is_contained(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.send("ping", n=1)  # the state sent after welcome is handled before the patch
            await g.expect({"t": "pong"})
            with patch("flcopilot.protocol.validate", side_effect=RuntimeError("bug")):
                await g.send("ev.dock", base="x")
                await asyncio.sleep(0.05)
            await g.send("ping", n=2)
            assert (await g.expect({"t": "pong"}))["n"] == 2
            assert app.server.stats.handler_errors == 1
            await g.close()
    run(body())


# ---- 5: patterns must match the whole value ---------------------------------------------
@pytest.mark.parametrize("t,payload", [
    ("say", {"id": "c-1", "speaker": "copilot\n", "text": "x"}),
    ("wing.focus", {"id": "c-1", "target": "id:5\n"}),
    ("ack", {"id": "c-1\n", "ok": True}),
    ("ev.kill", {"victim": "x", "by": "player\n"}),
])
def test_trailing_newline_does_not_match_patterns(t, payload):
    msg = {"v": 1, "t": t, "seq": 1, **payload}
    assert validate(msg), msg


# ---- spec deltas found in review ---------------------------------------------------------
def test_wing_policy_needs_its_field_and_carrier_needs_carrier_scope():
    assert validate({"v": 1, "t": "wing.policy", "seq": 1, "id": "c-1"})
    assert validate({"v": 1, "t": "policy.set", "seq": 1, "id": "c-1", "scope": "player", "carrier": "c1",
                     "auto_bots": True})
    assert validate({"v": 1, "t": "act", "seq": 1, "id": "c-1", "do": "use_bots", "carrier": "c1"})
    assert not validate({"v": 1, "t": "act", "seq": 1, "id": "c-1", "do": "use_bots", "scope": "carrier",
                         "carrier": "c1"})


# ---- 6: welcome.heartbeat_ms stays inside its schema --------------------------------------
@pytest.mark.parametrize("hb", [0.01, 0.05, 2.0, 60.0])
def test_welcome_heartbeat_in_schema(fakegame, hb):
    async def body():
        async with running_app(**{"server.heartbeat_s": hb}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            w = await g.handshake()
            assert validate(w) == []
            await g.close()
    run(body())


@pytest.mark.parametrize("hb", [0.001, 61, 120])
def test_heartbeat_out_of_range_rejected(hb):
    with pytest.raises(config.ConfigError, match="heartbeat_s"):
        make_cfg(**{"server.heartbeat_s": hb})


# ---- 7: welcome before the session becomes active ------------------------------------------
def test_new_session_is_active_only_after_welcome(fakegame):
    async def body():
        async with running_app() as (app, port):
            a = fakegame.FakeGame(port=port)
            await a.connect()
            await a.handshake()
            seen_active = []
            orig = app.server._activate

            def spy(sess):
                seen_active.append(sess.seq_out)  # welcome is seq 1, so it was already sent
                orig(sess)
            app.server._activate = spy
            b = fakegame.FakeGame(port=port)
            await b.connect()
            await b.handshake()
            assert seen_active == [1]
            await a.expect_closed()
            await b.close()
    run(body())


# ---- 3, 4: push-to-talk edge cases in the capture -----------------------------------------
def _np():
    return pytest.importorskip("numpy", reason="sidecar venv test (numpy not installed here)")


def _blocks(value: float, n: int, block: int = 320):
    np = _np()
    for _ in range(n):
        yield np.full(block, value, dtype=np.float32)


def test_repress_during_tail_keeps_both_utterances():
    np = _np()
    from flcopilot.audio.capture import PttCapture
    cap = PttCapture(preroll_ms=0, tail_ms=150)

    async def body():
        cap.ptt_down()
        for b in _blocks(1.0, 10):
            cap.feed(b)
        first = asyncio.ensure_future(cap.ptt_up())
        await asyncio.sleep(0)
        for b in _blocks(1.0, 2):                 # 40 ms of tail, then pressed again
            cap.feed(b)
        cap.ptt_down()
        for b in _blocks(2.0, 10):
            cap.feed(b)
        second = asyncio.ensure_future(cap.ptt_up())
        await asyncio.sleep(0)
        for b in _blocks(0.0, 10):
            cap.feed(b)
        return await asyncio.wait_for(first, 1), await asyncio.wait_for(second, 1)

    c1, c2 = run(body())
    assert c1 is not None and set(np.unique(c1)) == {1.0}            # tail cut short, no speech of #2
    assert c2 is not None and 2.0 in set(np.unique(c2))               # the second utterance survived
    assert len(c2) >= 10 * 320


def test_duplicate_release_does_not_steal_the_next_clip():
    np = _np()
    from flcopilot.audio.capture import PttCapture
    cap = PttCapture(preroll_ms=0, tail_ms=150, tail_grace_s=0.05)

    async def body():
        cap.ptt_down()
        for b in _blocks(3.0, 5):
            cap.feed(b)
        first = asyncio.ensure_future(cap.ptt_up())
        dup = asyncio.ensure_future(cap.ptt_up())   # a repeated ptt{down:false}
        await asyncio.sleep(0)
        for b in _blocks(3.0, 10):
            cap.feed(b)
        c1, d = await asyncio.wait_for(first, 1), await asyncio.wait_for(dup, 1)
        cap.ptt_down()
        for b in _blocks(4.0, 5):
            cap.feed(b)
        nxt = asyncio.ensure_future(cap.ptt_up())
        await asyncio.sleep(0)
        for b in _blocks(4.0, 10):
            cap.feed(b)
        return c1, d, await asyncio.wait_for(nxt, 1)

    c1, dup, nxt = run(body())
    assert dup is None
    assert set(np.unique(c1)) == {3.0}
    assert nxt is not None and set(np.unique(nxt)) == {4.0}


def test_pipeline_skips_none_clip_for_real_transcribers(fakegame):
    class StrictTranscriber:
        name = "strict"
        calls = 0

        def transcribe(self, clip, sample_rate=16000):
            StrictTranscriber.calls += 1
            raise AssertionError("must not be called without audio")

    async def body():
        async with running_app() as (app, port):
            app.profile.transcriber = StrictTranscriber()
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.ptt(True)
            await g.ptt(False)
            await g.expect_silence(0.3)
            await g.close()
    run(body())
    assert StrictTranscriber.calls == 0


def test_whisper_engine_empty_clip_short_circuits(tmp_path):
    np = _np()
    from flcopilot.voice.stt import WhisperEngine
    eng = WhisperEngine(tmp_path)
    assert eng.transcribe(None).text == "" and eng.transcribe(np.zeros(0)).text == ""
    assert eng._model is None  # no model was loaded for nothing


# ---- 8: no half-open stream when start() fails --------------------------------------------
def test_stream_closed_when_start_fails():
    pytest.importorskip("sounddevice", reason="sidecar venv test (sounddevice not installed here)")
    from flcopilot.audio.capture import PttCapture
    with patch("sounddevice.InputStream") as in_stream:
        in_stream.return_value.start.side_effect = RuntimeError("device busy")
        cap = PttCapture()
        with pytest.raises(RuntimeError):
            cap.open()
        in_stream.return_value.close.assert_called_once()
        assert not cap.is_open


# ---- 9: fakegame no longer passes vacuously ------------------------------------------------
@pytest.mark.parametrize("line,match", [
    ('{"expect": {"t": "welcome"}, "timout": 3}', "unknown key"),
    ('{"expect": {"t": "welcome"}, "skip": "false"}', "true or false"),
    ('{"disconnect": false}', "must be true"),
    ('{"expect_closed": false}', "must be true"),
    ('{"send": {"t": "ping"}, "ptt": "down"}', "several directives"),
])
def test_fakegame_rejects_bad_steps(fakegame, tmp_path, line, match):
    script = tmp_path / "s.ndjson"
    script.write_text(line + "\n", encoding="utf-8")

    async def body():
        async with running_app() as (app, port):
            with pytest.raises(ValueError, match=match):
                await fakegame.run_script_file(script, port)
    run(body())


def test_fakegame_envelope_checks(fakegame):
    g = fakegame.FakeGame(port=1)
    g._check_envelope({"v": 1, "t": "welcome", "seq": 1}, 30)
    for bad in ({"v": 1, "t": "pong", "seq": 3},                    # seq gap
                {"v": 1, "t": "say", "seq": 4},                     # command without id
                {"v": 1, "t": "pong", "seq": 5, "gt": 7},           # sidecar must not send gt
                {"v": 2, "t": "pong", "seq": 6}):
        with pytest.raises(fakegame.ExpectationFailed):
            g._check_envelope(bad, 30)
    lax = fakegame.FakeGame(port=1, strict=False)
    lax._check_envelope({"v": 1, "t": "pong", "seq": 9}, 30)
    assert len(lax.violations) == 1


def test_fakegame_policy_model_clamps_like_the_dll(fakegame):
    g = fakegame.FakeGame(port=1, max_stock=10)
    ok, applied, err = g.apply_policy({"t": "policy.set", "id": "c-1", "scope": "player", "bots_hull_below": 0.01,
                                       "critical_hull": 0.1, "bots_reserve": 50, "batts_shield_below": 2})
    assert ok and err is None
    assert applied["bots_hull_below"] == 0.05 and applied["critical_hull"] == 0.25
    assert applied["bots_reserve"] == 10 and applied["batts_shield_below"] == 0.95
    assert g.apply_policy({"t": "policy.set", "id": "c-2", "scope": "player", "x": 1})[2] == "unknown_field"
    assert g.apply_policy({"t": "policy.set", "id": "c-3", "scope": "player", "auto_bots": 1})[2] == "bad_value"
    assert g.apply_policy({"t": "policy.set", "id": "c-4", "scope": "player", "carrier": "c1",
                           "auto_bots": True})[2] == "bad_value"
    assert g.policy["player"]["bots_reserve"] == 10  # failed commands changed nothing
    assert protocol.CRITICAL_HULL_FLOOR_DEFAULT == fakegame.CRITICAL_HULL_FLOOR
