"""Runtime profiles (CONVENTIONS §13).

- ``live`` (default for play): device audio output, the real mic when capture is enabled and
  ``mic_match`` resolves. In P0 it has no speech-to-text, TTS or brain yet (W1-SIDECAR and
  W4-BRAIN add them), so it advertises no features.
- ``test`` (mandatory for harness, lanes, soaks, CI): a null audio sink (no device is ever
  opened), ``--mic-file`` or no mic, a fake transcriber, fake TTS and the deterministic fake
  brain. Nothing touches audio hardware, the GPU, a model or the network.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import logsetup
from .audio.capture import Mic, NullMic
from .audio.sinks import AudioSink, DeviceSink, NullSink
from .brain import Brain, FakeBrain
from .voice.stt import FakeTranscriber
from .voice.tts import FakeTTS

log = logsetup.get("profile")

PROFILES = ("live", "test")


class ProfileError(RuntimeError):
    pass


@dataclass
class Profile:
    name: str
    sink: AudioSink
    mic: Mic
    transcriber: Any = None
    brain: Brain | None = None
    tts: Any = None
    features: tuple = ()
    voice: str = "am_michael"
    speed: float = 1.0
    mic_discovery: Any = None
    notes: list = field(default_factory=list)


def guard_live(env: dict | None = None) -> None:
    """Refuse the live profile under pytest or when the harness demands the test profile."""
    env = os.environ if env is None else env
    if env.get("PYTEST_CURRENT_TEST"):
        raise ProfileError("live profile refused under pytest; use --profile test")
    if env.get("FLCOPILOT_FORCE_TEST_PROFILE", "") not in ("", "0"):
        raise ProfileError("FLCOPILOT_FORCE_TEST_PROFILE is set; use --profile test")


def build_profile(name: str, cfg, mic_file: str | os.PathLike | None = None,
                  null_wav_dir: str | os.PathLike | None = None, env: dict | None = None) -> Profile:
    if name not in PROFILES:
        raise ProfileError(f"unknown profile {name!r}; use one of {PROFILES}")
    voice = str(cfg.get("tts.voice"))
    speed = float(cfg.get("tts.speed"))
    if name == "test":
        mic: Mic = NullMic()
        if mic_file:
            from .audio.capture import FileMic
            mic = FileMic(mic_file, sample_rate=int(cfg.get("audio.sample_rate")))
        prof = Profile(
            name="test",
            sink=NullSink(wav_dir=Path(null_wav_dir) if null_wav_dir else None),
            mic=mic,
            transcriber=FakeTranscriber(str(cfg.get("test.fake_transcript"))),
            brain=FakeBrain(default_reserve=int(cfg.get("test.fake_bots_reserve"))),
            tts=FakeTTS(),
            features=("stt", "tts", "llm"),
            voice=voice, speed=speed,
        )
        log.info("profile test: null sink, fake transcriber, fake TTS, fake brain",
                 extra={"kv": {"mic": prof.mic.name}})
        return prof

    guard_live(env)
    if mic_file:
        raise ProfileError("--mic-file requires --profile test")
    from .audio import devices

    discovery = devices.discover(str(cfg.get("audio.mic_match") or ""))
    mic = NullMic()
    notes = []
    if cfg.get("audio.capture_enabled"):
        if discovery.status == "resolved":
            from .audio.capture import PttCapture
            mic = PttCapture(sample_rate=int(cfg.get("audio.sample_rate")),
                             preroll_ms=int(cfg.get("audio.preroll_ms")),
                             tail_ms=int(cfg.get("audio.tail_ms")),
                             source_name=discovery.source.name)
        else:
            notes.append("capture enabled but no mic resolved; voice input disabled")
    else:
        notes.append("capture disabled (audio.capture_enabled = false)")
    prof = Profile(name="live", sink=DeviceSink(cfg.get("audio.output_device")), mic=mic,
                   features=(), voice=voice, speed=speed, mic_discovery=discovery, notes=notes)
    log.info("profile live (P0: no STT/TTS/brain yet)", extra={"kv": {"mic": mic.name, "notes": notes}})
    return prof
