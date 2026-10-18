"""Audio output sinks.

- :class:`NullSink` (test profile): never touches an audio device. It counts what it was
  given and can optionally write WAV files for inspection.
- :class:`DeviceSink` (live profile): plays on the default PipeWire sink through
  ``sounddevice``. ``sounddevice`` is imported lazily, on the first play, so building a
  live profile opens nothing.

``pcm`` is a sequence of float32 samples in [-1, 1], mono.
"""
from __future__ import annotations

import struct
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .. import logsetup

log = logsetup.get("audio")


class AudioSink:
    name = "abstract"

    def play(self, pcm: Sequence[float], sample_rate: int, label: str = "") -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


@dataclass
class NullSink(AudioSink):
    """Discards audio. No device is ever opened."""

    wav_dir: Path | None = None
    name: str = "null"
    plays: int = 0
    samples: int = 0
    history: list = field(default_factory=list)

    def play(self, pcm: Sequence[float], sample_rate: int, label: str = "") -> None:
        n = len(pcm)
        self.plays += 1
        self.samples += n
        self.history.append({"label": label, "samples": n, "rate": sample_rate})
        path = None
        if self.wav_dir is not None:
            self.wav_dir.mkdir(parents=True, exist_ok=True)
            path = self.wav_dir / f"null-sink-{self.plays:04d}.wav"
            write_wav16(path, pcm, sample_rate)
        log.info("null sink: audio discarded", extra={"kv": {
            "label": label, "samples": n, "rate": sample_rate, **({"wav": str(path)} if path else {})}})


class DeviceSink(AudioSink):
    """Plays through ``sounddevice.OutputStream`` on the configured output device."""

    name = "device"

    def __init__(self, device: str | int | None = "default"):
        self.device = None if device in ("", "default", None) else device

    def play(self, pcm: Sequence[float], sample_rate: int, label: str = "") -> None:
        import numpy as np
        import sounddevice

        data = np.asarray(pcm, dtype=np.float32).reshape(-1, 1)
        with sounddevice.OutputStream(samplerate=sample_rate, channels=1, dtype="float32",
                                      device=self.device) as stream:
            stream.write(data)
        log.info("played", extra={"kv": {"label": label, "samples": len(data), "rate": sample_rate}})


def write_wav16(path: Path, pcm: Sequence[float], sample_rate: int) -> None:
    """Write mono PCM16 WAV with the stdlib (no numpy needed)."""
    frames = bytearray()
    for x in pcm:
        v = max(-1.0, min(1.0, float(x)))
        frames += struct.pack("<h", int(v * 32767.0))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(bytes(frames))
