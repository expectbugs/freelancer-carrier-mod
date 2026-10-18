"""Voice pipeline lifecycle: the mic follows the active session, also across replacement."""
from __future__ import annotations

import asyncio

from conftest import run, running_app
from flcopilot.audio.capture import Mic
from flcopilot.voice.stt import FakeTranscriber


class RecordingMic(Mic):
    name = "recording"

    def __init__(self):
        self.events: list[str] = []
        self.is_open = False

    def open(self):
        self.events.append("open")
        self.is_open = True

    def close(self):
        self.events.append("close")
        self.is_open = False

    def ptt_down(self):
        self.events.append("down")

    async def ptt_up(self):
        self.events.append("up")
        return None


def test_mic_open_while_connected_and_closed_after(fakegame):
    async def body():
        async with running_app() as (app, port):
            mic = app.profile.mic = RecordingMic()
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            assert mic.is_open
            sess = await app.server.wait_for_session()
            await g.close()
            await asyncio.wait_for(sess.done.wait(), 2.0)
            assert not mic.is_open and mic.events == ["open", "close"]
    run(body())


def test_replacement_keeps_mic_open_for_new_session(fakegame):
    async def body():
        async with running_app() as (app, port):
            mic = app.profile.mic = RecordingMic()
            a = fakegame.FakeGame(port=port)
            await a.connect()
            await a.handshake()
            first = await app.server.wait_for_session()
            b = fakegame.FakeGame(port=port)
            await b.connect()
            await b.handshake()
            await a.expect_closed()
            await asyncio.wait_for(first.done.wait(), 2.0)
            assert mic.is_open, mic.events  # the replaced session's end must not close B's mic
            # And B's push-to-talk still works end to end.
            await b.ptt(True)
            await b.ptt(False)
            await b.expect({"t": "policy.set"}, timeout=3)
            await b.ack()
            await b.expect({"t": "say"})
            await b.ack()
            assert "down" in mic.events and "up" in mic.events
            await b.close()
    run(body())


def test_ptt_up_without_brain_or_transcriber_is_harmless(fakegame):
    async def body():
        async with running_app() as (app, port):
            app.profile.transcriber = None
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.ptt(True)
            await g.ptt(False)
            await g.expect_silence(0.3)  # nothing is sent
            app.profile.transcriber = FakeTranscriber("x")
            app.profile.brain = None
            await g.ptt(True)
            await g.ptt(False)
            await g.expect_silence(0.3)
            await g.close()
    run(body())


def test_disconnect_mid_utterance_cancels_cleanly(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 5.0}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            sess = await app.server.wait_for_session()
            await g.ptt(True)
            await g.ptt(False)
            await g.expect({"t": "policy.set"}, timeout=3)
            await g.close()  # never acks; the utterance task is waiting on the ack
            await asyncio.wait_for(sess.done.wait(), 2.0)
            await asyncio.sleep(0.05)
            assert not app.pipeline._tasks  # cancelled with its session, nothing leaked
    run(body())
