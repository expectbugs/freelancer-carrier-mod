"""Text-to-speech.

``prepare_for_speech``, ``split_sentences`` and ``ensure_tts_splits`` are adapted from the
owner's prior voice-assistant code (pure functions, copied, not imported). Changes: the
code-block marker is dropped (game lines never carry code), names follow this package.

:class:`KokoroEngine` wraps kokoro-onnx 0.5.0 on CPU with the 509-phoneme guard.
:class:`FakeTTS` is the test-profile stand-in: deterministic silence, no model, no numpy.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Iterator

from .. import logsetup

log = logsetup.get("tts")

SAMPLE_RATE = 24000  # Kokoro native rate

# Per-unit synthesis targets. Kokoro's phoneme batcher truncates past 509 phonemes (~200
# chars worst case), so units stay well below that. The first unit is small for fast first audio.
SENTENCE_FIRST_TARGET_CHARS = 100
SENTENCE_TARGET_CHARS = 250
SENTENCE_HARD_MAX_CHARS = 450


def ensure_tts_splits(text: str, max_chars: int = 200) -> str:
    """Insert a comma at a word boundary in any run of ``max_chars`` without [.,!?;]."""
    pattern = re.compile(r"[^.,!?;]{" + str(max_chars) + r",}")
    while True:
        m = pattern.search(text)
        if not m:
            break
        run = m.group()
        mid = len(run) // 2
        best = None
        for offset in range(mid + 1):
            if mid + offset < len(run) and run[mid + offset] == " ":
                best = mid + offset
                break
            if mid - offset >= 0 and run[mid - offset] == " ":
                best = mid - offset
                break
        if best is None:
            break  # no space in the whole run; cannot split
        insert_pos = m.start() + best
        text = text[:insert_pos] + "," + text[insert_pos:]
    return text


def prepare_for_speech(text: str) -> str:
    """Strip markdown and characters Kokoro vocalizes badly; add pause points."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Parentheses: Kokoro renders them as an audible burst.
    text = re.sub(r"[()]", "", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"(?<![.,!?;:])\n", ", ", text)
    text = re.sub(r"\n", " ", text)
    text = ensure_tts_splits(text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Split prepared text into synthesis units of at most SENTENCE_HARD_MAX_CHARS."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+", text) if p.strip()]
    units: list[str] = []
    cur = ""

    def target() -> int:
        return SENTENCE_FIRST_TARGET_CHARS if not units else SENTENCE_TARGET_CHARS

    for part in parts:
        while len(part) > SENTENCE_HARD_MAX_CHARS:
            cut = part.rfind(" ", 0, SENTENCE_HARD_MAX_CHARS)
            if cut <= 0:
                cut = SENTENCE_HARD_MAX_CHARS
            if cur:
                units.append(cur)
                cur = ""
            units.append(part[:cut].strip())
            part = part[cut:].strip()
        if not part:
            continue
        if cur and len(cur) + 1 + len(part) > target():
            units.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    if cur:
        units.append(cur)
    return units


class FakeTTS:
    """Deterministic test-profile TTS: 50 ms of silence per word at 24 kHz."""

    name = "fake"
    sample_rate = SAMPLE_RATE

    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, text: str, voice: str = "", speed: float = 1.0) -> Iterator[tuple[list, int]]:
        self.calls += 1
        words = max(1, len(text.split()))
        yield [0.0] * (SAMPLE_RATE // 20 * words), SAMPLE_RATE


class KokoroEngine:
    """kokoro-onnx on CPU, loaded once, one ``create()`` per sentence unit."""

    name = "kokoro"
    sample_rate = SAMPLE_RATE

    def __init__(self, model_dir: str | os.PathLike, lang: str = "en-us"):
        self.model_dir = Path(model_dir)
        self.lang = lang
        self.load_ms: float | None = None
        self._kokoro = None
        self._lock = threading.Lock()

    @property
    def model_path(self) -> Path:
        return self.model_dir / "kokoro-v1.0.onnx"

    @property
    def voices_path(self) -> Path:
        return self.model_dir / "voices-v1.0.bin"

    def available(self) -> bool:
        return self.model_path.exists() and self.voices_path.exists()

    def load(self) -> None:
        with self._lock:
            self._ensure()

    def _ensure(self) -> None:
        if self._kokoro is not None:
            return
        import kokoro_onnx

        # kokoro-onnx 0.5.0 allows index 510 into a 510-row style table; clamp to 509.
        kokoro_onnx.MAX_PHONEME_LENGTH = 509
        for p in (self.model_path, self.voices_path):
            if not p.exists():
                raise FileNotFoundError(f"Kokoro model file missing: {p}")
        t0 = time.perf_counter()
        self._kokoro = kokoro_onnx.Kokoro(str(self.model_path), str(self.voices_path))
        self.load_ms = (time.perf_counter() - t0) * 1000.0
        log.info("kokoro loaded", extra={"kv": {"load_ms": round(self.load_ms, 1)}})

    def synthesize(self, text: str, voice: str = "am_michael", speed: float = 1.0) -> Iterator[tuple[object, int]]:
        """Yield (float32 samples, rate) per sentence unit, as soon as each is ready."""
        units = split_sentences(prepare_for_speech(text))
        with self._lock:
            self._ensure()
            for unit in units:
                samples, sr = self._kokoro.create(unit, voice=voice, speed=speed, lang=self.lang)
                if len(samples) == 0:
                    log.warning("tts unit produced no audio", extra={"kv": {"unit": unit[:60]}})
                    continue
                yield samples, sr
