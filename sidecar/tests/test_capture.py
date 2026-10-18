"""Push-to-talk capture with a mocked sounddevice.InputStream (no real audio)."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

np = pytest.importorskip("numpy")

from conftest import run  # noqa: E402
from flcopilot.audio.capture import PttCapture  # noqa: E402
from flcopilot.audio.dsp import resample, to_mono  # noqa: E402

RATE = 16000
BLOCK = 320  # 20 ms


def ramp_blocks(start: int, n_blocks: int):
    """Blocks whose sample values are their global sample index (so positions are traceable)."""
    for b in range(n_blocks):
        lo = start + b * BLOCK
        yield np.arange(lo, lo + BLOCK, dtype=np.float32)


def test_open_creates_16k_mono_stream_and_close_stops_it(monkeypatch):
    monkeypatch.setenv("PULSE_SOURCE", "placeholder")  # so teardown restores the original state
    with patch("sounddevice.InputStream") as in_stream:
        cap = PttCapture(source_name="alsa_input.example-source")
        cap.open()
        kwargs = in_stream.call_args.kwargs
        assert kwargs["samplerate"] == 16000 and kwargs["channels"] == 1 and kwargs["dtype"] == "float32"
        assert kwargs["device"] == "pulse" and callable(kwargs["callback"])
        import os
        assert os.environ["PULSE_SOURCE"] == "alsa_input.example-source"
        in_stream.return_value.start.assert_called_once()
        cap.open()  # idempotent
        assert in_stream.call_count == 1
        cap.close()
        in_stream.return_value.stop.assert_called_once()
        in_stream.return_value.close.assert_called_once()
        assert not cap.is_open


def test_preroll_speech_and_tail():
    cap = PttCapture(preroll_ms=300, tail_ms=150)

    async def body():
        idx = 0
        for blk in ramp_blocks(idx, 50):          # 1 s before PTT: only the last 300 ms survive
            cap.feed(blk)
        idx += 50 * BLOCK
        cap.ptt_down()
        for blk in ramp_blocks(idx, 25):          # 500 ms of speech
            cap.feed(blk)
        idx += 25 * BLOCK
        up = asyncio.ensure_future(cap.ptt_up())
        await asyncio.sleep(0)
        for blk in ramp_blocks(idx, 20):          # the stream keeps running after release
            cap.feed(blk)
            await asyncio.sleep(0)
        return await asyncio.wait_for(up, 1.0)

    clip = run(body())
    preroll = 300 * RATE // 1000                  # 4800
    tail_blocks = -(-150 * RATE // 1000 // BLOCK)  # ceil(2400 / 320) = 8 blocks
    assert len(clip) == preroll + 25 * BLOCK + tail_blocks * BLOCK
    first_speech = 50 * BLOCK
    assert clip[0] == first_speech - preroll       # the pre-roll is exactly the last 300 ms
    assert np.all(np.diff(clip) == 1)              # contiguous, nothing dropped or duplicated


def test_ptt_up_without_down_returns_none():
    cap = PttCapture()
    assert run(cap.ptt_up()) is None


def test_tail_timeout_returns_partial_clip():
    cap = PttCapture(tail_ms=150, tail_grace_s=0.05)

    async def body():
        cap.ptt_down()
        for blk in ramp_blocks(0, 5):
            cap.feed(blk)
        return await cap.ptt_up()                 # no more samples arrive: stream died

    clip = run(body())
    assert len(clip) == 5 * BLOCK


def test_callback_path_and_status_counting():
    with patch("sounddevice.InputStream") as in_stream:
        cap = PttCapture()
        cap.open()
        cb = in_stream.call_args.kwargs["callback"]

        async def body():
            cap.ptt_down()
            cb(np.ones((BLOCK, 1), dtype=np.float32), BLOCK, None, None)
            cb(np.ones((BLOCK, 1), dtype=np.float32), BLOCK, None, "input overflow")
            up = asyncio.ensure_future(cap.ptt_up())
            await asyncio.sleep(0)
            for _ in range(10):
                cb(np.zeros((BLOCK, 1), dtype=np.float32), BLOCK, None, None)
            return await asyncio.wait_for(up, 1.0)

        clip = run(body())
        assert clip[:2 * BLOCK].sum() == 2 * BLOCK
        assert cap.overflows == 1
        cap.close()


def test_max_utterance_caps_memory():
    cap = PttCapture(max_utterance_s=0.1, tail_ms=0)  # 1600 samples max

    async def body():
        cap.ptt_down()
        for blk in ramp_blocks(0, 50):
            cap.feed(blk)
        return await cap.ptt_up()

    clip = run(body())
    assert len(clip) <= 1600 + BLOCK


def test_close_while_recording_discards():
    cap = PttCapture()
    cap.ptt_down()
    cap.feed(np.zeros(BLOCK, dtype=np.float32))
    cap.close()
    assert run(cap.ptt_up()) is None


def test_resample_and_mono():
    x = np.arange(48000, dtype=np.float32)
    y = resample(x, 48000, 16000)
    assert len(y) == 16000 and y.dtype == np.float32
    assert resample(x, 16000, 16000) is not None and len(resample(x, 16000, 16000)) == 48000
    assert len(resample(np.zeros(0, dtype=np.float32), 48000, 16000)) == 0
    st = np.stack([np.ones(10), np.zeros(10)], axis=1)
    assert np.allclose(to_mono(st), 0.5)
