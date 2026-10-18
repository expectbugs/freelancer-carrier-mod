"""Small DSP helpers (numpy).

``resample`` is adapted from the owner's prior voice-assistant code (pure function, copied,
not imported): linear interpolation, good enough for speech-to-text input.
"""
from __future__ import annotations

import numpy as np


def resample(pcm: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Resample mono audio by linear interpolation."""
    if from_rate == to_rate:
        return np.asarray(pcm, dtype=np.float32)
    if len(pcm) == 0:
        return np.zeros(0, dtype=np.float32)
    ratio = to_rate / from_rate
    new_length = int(len(pcm) * ratio)
    return np.interp(
        np.linspace(0, len(pcm) - 1, new_length),
        np.arange(len(pcm)),
        pcm,
    ).astype(np.float32)


def to_mono(frames: np.ndarray) -> np.ndarray:
    """(n,) or (n, channels) float audio to (n,) float32 by averaging channels."""
    a = np.asarray(frames, dtype=np.float32)
    if a.ndim == 1:
        return a
    return a.mean(axis=1).astype(np.float32)
