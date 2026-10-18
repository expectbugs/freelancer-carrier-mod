"""Speech-to-text.

:class:`WhisperEngine` is adapted from the owner's prior voice-assistant code (copied, not
imported; that code read a secret config at import time, this one takes arguments). Changes:
offline-only loading (``local_files_only=True``, ``HF_HUB_OFFLINE=1``), a local model path,
push-to-talk decoding options (R6 §4.1) and a CPU ``int8`` fallback with a recorded reason.

:class:`FakeTranscriber` is the test-profile stand-in: deterministic text, no model.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import logsetup

log = logsetup.get("stt")

#: Game vocabulary for decoding bias (R6 §4.1). System and base names get appended at runtime.
GAME_VOCAB = (
    "nanobots", "shield batteries", "cruiser", "gunboat", "battleship", "carrier", "formation",
    "wingmen", "Liberty", "Bretonia", "Rheinland", "Kusari", "Rogues", "Outcasts", "Corsairs",
    "Xenos", "Nomads", "Order", "trade lane", "jump gate", "jump hole",
)


def initial_prompt(extra: tuple | list = ()) -> str:
    words = ", ".join((*GAME_VOCAB, *extra))
    return f"Freelancer copilot orders. Vocabulary: {words}."


def hotwords(extra: tuple | list = ()) -> str:
    return " ".join((*GAME_VOCAB, *extra))


@dataclass
class TranscriptResult:
    text: str
    segments: list = field(default_factory=list)
    language: str = ""
    duration: float = 0.0
    processing_time: float = 0.0
    device: str = ""
    compute_type: str = ""


class FakeTranscriber:
    """Deterministic test-profile transcriber: returns the configured text for any clip."""

    name = "fake"
    accepts_empty = True  # answers even without audio (NullMic), so the test profile is deterministic

    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        self.last_clip_len: int | None = None

    def transcribe(self, clip, sample_rate: int = 16000) -> TranscriptResult:
        self.calls += 1
        self.last_clip_len = None if clip is None else len(clip)
        return TranscriptResult(text=self.text, device="fake")


class WhisperEngine:
    """faster-whisper with lazy loading and a lock around the GPU."""

    name = "whisper"

    def __init__(self, model_path: str | os.PathLike | None, model_name: str = "large-v3-turbo",
                 device: str = "cuda", compute_type: str = "float16", language: str = "en",
                 beam_size: int = 1, cpu_fallback: bool = True):
        self.model_path = Path(model_path) if model_path else None
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.cpu_fallback = cpu_fallback
        self.fallback_reason = ""
        self.load_ms: float | None = None
        self._model = None
        self._lock = threading.Lock()

    def _source(self) -> str:
        if self.model_path and (self.model_path / "model.bin").exists():
            return str(self.model_path)
        return self.model_name  # resolved from the HF cache, offline

    def load(self) -> None:
        with self._lock:
            self._ensure_model()

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from faster_whisper import WhisperModel

        src = self._source()
        t0 = time.perf_counter()
        try:
            self._model = WhisperModel(src, device=self.device, compute_type=self.compute_type,
                                       local_files_only=True)
        except Exception as exc:  # CUDA libs missing, no GPU, out of memory
            if not self.cpu_fallback or self.device == "cpu":
                raise
            self.fallback_reason = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("whisper on %s failed; falling back to cpu int8", self.device,
                        extra={"kv": {"reason": self.fallback_reason}})
            self.device, self.compute_type = "cpu", "int8"
            self._model = WhisperModel(src, device="cpu", compute_type="int8", local_files_only=True)
        self.load_ms = (time.perf_counter() - t0) * 1000.0
        log.info("whisper loaded", extra={"kv": {"model": Path(src).name, "device": self.device,
                                                 "compute_type": self.compute_type,
                                                 "load_ms": round(self.load_ms, 1)}})

    def transcribe(self, clip, sample_rate: int = 16000, extra_vocab: tuple | list = ()) -> TranscriptResult:
        """Transcribe a float32 mono clip (resampled to 16 kHz if needed)."""
        import numpy as np

        from ..audio.dsp import resample

        if clip is None or len(clip) == 0:
            return TranscriptResult(text="", device=self.device, compute_type=self.compute_type)
        pcm = np.asarray(clip, dtype=np.float32)
        if sample_rate != 16000:
            pcm = resample(pcm, sample_rate, 16000)
        with self._lock:
            self._ensure_model()
            t0 = time.perf_counter()
            segments_iter, info = self._model.transcribe(
                pcm,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=False,
                without_timestamps=True,
                condition_on_previous_text=False,
                initial_prompt=initial_prompt(extra_vocab),
                hotwords=hotwords(extra_vocab),
            )
            segments = []
            parts = []
            for seg in segments_iter:
                segments.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
                parts.append(seg.text.strip())
            elapsed = time.perf_counter() - t0
        return TranscriptResult(text=" ".join(parts).strip(), segments=segments, language=info.language,
                                duration=round(info.duration, 3), processing_time=round(elapsed, 4),
                                device=self.device, compute_type=self.compute_type)
