"""Push-to-talk capture.

Design (R6 §4.2): a 16 kHz mono ``sounddevice.InputStream`` stays open while a game is
connected and feeds a 300 ms pre-roll ring. ``ptt down`` starts accumulating (seeded with the
pre-roll, so the first syllable is not clipped); ``ptt up`` keeps accumulating for a 150 ms
tail, then hands the clip to speech-to-text.

P0 ships this plumbing behind ``audio.capture_enabled`` (off) and tests it with a mocked
``sounddevice.InputStream``; W1-SIDECAR exercises the live mic.

Mics: :class:`PttCapture` (device), :class:`FileMic` (``--mic-file``, test profile),
:class:`NullMic` (no input).
"""
from __future__ import annotations

import asyncio
import collections
import os
import threading
import time
from pathlib import Path

from .. import logsetup

log = logsetup.get("audio")


class Mic:
    name = "abstract"

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def ptt_down(self) -> None:
        pass

    async def ptt_up(self):
        return None


class NullMic(Mic):
    """No microphone: every utterance is empty."""

    name = "null"


class FileMic(Mic):
    """Replays a WAV file as the utterance on every push-to-talk release (test profile)."""

    name = "file"

    def __init__(self, path: str | os.PathLike, sample_rate: int = 16000):
        import numpy as np
        import soundfile

        from .dsp import resample, to_mono

        self.path = Path(path)
        data, rate = soundfile.read(str(self.path), dtype="float32", always_2d=False)
        self.clip = resample(to_mono(np.asarray(data)), int(rate), sample_rate)
        self.sample_rate = sample_rate
        self.uses = 0

    async def ptt_up(self):
        self.uses += 1
        return self.clip.copy()


class PttCapture(Mic):
    name = "device"

    def __init__(self, sample_rate: int = 16000, preroll_ms: int = 300, tail_ms: int = 150,
                 device: str | int | None = None, source_name: str | None = None,
                 tail_grace_s: float = 0.5, max_utterance_s: float = 30.0, block_ms: int = 20):
        self.sample_rate = sample_rate
        self.preroll_samples = sample_rate * preroll_ms // 1000
        self.tail_samples = sample_rate * tail_ms // 1000
        self.tail_s = tail_ms / 1000.0
        self.tail_grace_s = tail_grace_s
        self.max_samples = int(sample_rate * max_utterance_s)
        self.block = max(1, sample_rate * block_ms // 1000)
        self.device = device
        self.source_name = source_name
        self._lock = threading.Lock()
        self._ring: collections.deque = collections.deque()
        self._ring_len = 0
        self._chunks: list = []
        self._rec_len = 0
        self._recording = False
        self._tail_left: int | None = None
        self._fut: tuple[asyncio.AbstractEventLoop, asyncio.Future] | None = None
        self._stream = None
        self.down_at: float | None = None
        self.overflows = 0

    # ---- stream ------------------------------------------------------------------------
    def open(self) -> None:
        if self._stream is not None:
            return
        import sounddevice

        device = self.device
        if self.source_name:
            # PortAudio has no PipeWire source picker; the pulse ALSA device honors PULSE_SOURCE.
            # UNVERIFIED with this PortAudio build until W1-SIDECAR's live test.
            os.environ["PULSE_SOURCE"] = self.source_name
            if device in (None, "", "default"):
                device = "pulse"
        stream = sounddevice.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32",
                                         blocksize=self.block, device=device, callback=self._callback)
        try:
            stream.start()
        except Exception:
            stream.close()  # never leak a half-open PortAudio stream
            raise
        self._stream = stream
        log.info("capture stream open", extra={"kv": {"rate": self.sample_rate, "device": str(device)}})

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
            log.info("capture stream closed")
        with self._lock:
            self._ring.clear()
            self._ring_len = 0
            self._finalize_locked()

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status) -> None:  # PortAudio thread
        if status:
            self.overflows += 1
        self.feed(indata[:, 0])

    # ---- buffer ------------------------------------------------------------------------
    def feed(self, samples) -> None:
        """Append mono float32 samples (from the stream callback, or a test)."""
        block = samples.copy()
        n = len(block)
        with self._lock:
            if self._recording:
                if self._rec_len < self.max_samples:
                    self._chunks.append(block)
                    self._rec_len += n
                if self._tail_left is not None:
                    self._tail_left -= n
                    if self._tail_left <= 0:
                        self._finalize_locked()
                return
            self._ring.append(block)
            self._ring_len += n
            while self._ring and self._ring_len - len(self._ring[0]) >= self.preroll_samples:
                self._ring_len -= len(self._ring.popleft())
            if self._ring and self._ring_len > self.preroll_samples:
                extra = self._ring_len - self.preroll_samples
                self._ring[0] = self._ring[0][extra:]
                self._ring_len -= extra

    def ptt_down(self) -> None:
        with self._lock:
            if self._recording and self._tail_left is None:
                return  # already held (duplicate down)
            if self._recording:
                # Pressed again during the previous release's tail: cut that tail short and hand
                # its clip over now, so the new utterance starts its own recording.
                self._finalize_locked()
            self._recording = True
            self._chunks = list(self._ring)
            self._rec_len = self._ring_len
            self._ring.clear()
            self._ring_len = 0
            self._tail_left = None
            self.down_at = time.monotonic()

    async def ptt_up(self):
        """The clip (pre-roll + speech + tail) as float32, or None if PTT was not down."""
        loop = asyncio.get_running_loop()
        with self._lock:
            if not self._recording or self._fut is not None:
                return None  # not held, or a duplicate release while the tail is pending
            fut = loop.create_future()
            self._fut = (loop, fut)
            self._tail_left = self.tail_samples
            if self.tail_samples <= 0:
                self._finalize_locked()
        # asyncio.wait (unlike wait_for) never cancels fut, so a result set concurrently is not lost.
        await asyncio.wait({fut}, timeout=self.tail_s + self.tail_grace_s)
        if fut.done():
            return fut.result()
        with self._lock:
            mine = self._fut is not None and self._fut[1] is fut
            if mine:
                # The stream stopped delivering (device gone): hand over what we have.
                clip = self._take_locked()
                self._fut = None
        if mine:
            log.warning("capture tail timed out; using partial clip")
            return clip
        return await fut  # finalized just now by the callback thread; the result is in flight

    def _take_locked(self):
        import numpy as np

        clip = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)
        self._chunks = []
        self._rec_len = 0
        self._recording = False
        self._tail_left = None
        return clip

    def _finalize_locked(self) -> None:
        if not self._recording and self._fut is None:
            return
        clip = self._take_locked()
        if self._fut is not None:
            loop, fut = self._fut
            self._fut = None
            loop.call_soon_threadsafe(_set_result, fut, clip)


def _set_result(fut: asyncio.Future, value) -> None:
    if not fut.done():
        fut.set_result(value)
