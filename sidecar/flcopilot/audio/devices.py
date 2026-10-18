"""Microphone discovery: resolve the PipeWire/Pulse capture source by a name substring.

The substring (``audio.mic_match``) comes only from the gitignored local overlay. The public
config has none, so by default voice input is disabled. The resolved device name is written
only to the local log, never to a committed file.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from .. import logsetup

log = logsetup.get("audio")

PACTL_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class Source:
    index: int
    name: str
    driver: str = ""
    spec: str = ""
    state: str = ""

    @property
    def is_monitor(self) -> bool:
        return self.name.endswith(".monitor")


@dataclass(frozen=True)
class Discovery:
    status: str  # resolved | not_found | not_configured | error
    source: Source | None = None
    detail: str = ""
    candidates: int = 0


def parse_short_sources(text: str) -> list[Source]:
    """Parse ``pactl list short sources``: ``index<TAB>name<TAB>driver<TAB>spec<TAB>state``."""
    out: list[Source] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            parts = line.split()
        try:
            index = int(parts[0])
        except (ValueError, IndexError):
            continue
        name = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            continue
        out.append(Source(index=index, name=name,
                          driver=parts[2].strip() if len(parts) > 2 else "",
                          spec=parts[3].strip() if len(parts) > 3 else "",
                          state=parts[4].strip() if len(parts) > 4 else ""))
    return out


def list_sources() -> list[Source]:
    """Capture sources from ``pactl`` (PipeWire's pulse server). Raises OSError/RuntimeError."""
    exe = shutil.which("pactl")
    if exe is None:
        raise RuntimeError("pactl not found")
    res = subprocess.run([exe, "list", "short", "sources"], capture_output=True, text=True,
                         timeout=PACTL_TIMEOUT_S, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"pactl exited {res.returncode}: {res.stderr.strip()[:200]}")
    return parse_short_sources(res.stdout)


def resolve_source(mic_match: str, sources: list[Source]) -> tuple[Source | None, int]:
    """First non-monitor source whose name contains ``mic_match`` (case-insensitive)."""
    needle = mic_match.strip().lower()
    hits = [s for s in sources if not s.is_monitor and needle in s.name.lower()]
    return (hits[0] if hits else None), len(hits)


def discover(mic_match: str) -> Discovery:
    if not mic_match or not mic_match.strip():
        log.info("mic: not configured (audio.mic_match is empty); voice input disabled")
        return Discovery("not_configured")
    try:
        sources = list_sources()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        log.warning("mic: discovery failed; voice input disabled", extra={"kv": {"err": str(exc)[:200]}})
        return Discovery("error", detail=str(exc)[:200])
    src, n = resolve_source(mic_match, sources)
    if src is None:
        log.warning("mic: not found; voice input disabled", extra={"kv": {"sources": len(sources)}})
        return Discovery("not_found", candidates=0)
    # The name goes to the local (gitignored) log only.
    log.info("mic: resolved", extra={"kv": {"index": src.index, "name": src.name, "matches": n}})
    return Discovery("resolved", source=src, candidates=n)
