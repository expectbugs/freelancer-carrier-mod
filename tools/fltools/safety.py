"""Write-path guard: nothing in fltools or the generator framework may write inside Adam's play
prefix (CLAUDE.md guardrail 1, AUTONOMY §2).

:func:`refuse_play_prefix` resolves the target with ``os.path.realpath`` (so ``..`` and symlinks
cannot sneak in) and refuses it when it is the play prefix or inside it. The hard-coded
``/home/user/freelancer/prefix`` is always protected; ``$FLMOD_PLAY_PREFIX`` can only ADD a
protected location, never remove the default. Sibling prefixes such as ``prefix-lane1`` are not
inside it (the check compares whole path components).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PLAY_PREFIX = "/home/user/freelancer/prefix"

__all__ = ["PlayPrefixError", "refuse_play_prefix", "protected_roots", "PLAY_PREFIX",
           "UnsafePathError", "contained_rel", "is_within"]


class PlayPrefixError(RuntimeError):
    pass


class UnsafePathError(ValueError):
    pass


_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def contained_rel(rel: str) -> str:
    """Normalise a root-relative path (``\\`` -> ``/``, ``.`` and empty parts dropped) and refuse
    anything that could leave the root: absolute paths, drive letters, ``..`` components."""
    s = str(rel).replace("\\", "/")
    if s.startswith("/") or _DRIVE_RE.match(s):
        raise UnsafePathError(f"absolute path {rel!r} not allowed (paths are root-relative)")
    parts = [p for p in s.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise UnsafePathError(f"'..' in path {rel!r} not allowed")
    if not parts:
        raise UnsafePathError(f"empty path {rel!r}")
    return "/".join(parts)


def is_within(path: str | os.PathLike, root: str | os.PathLike) -> bool:
    """True if ``path`` resolves (symlinks included) to ``root`` or below it."""
    real, base = Path(os.path.realpath(path)), Path(os.path.realpath(root))
    return real == base or base in real.parents


def protected_roots() -> list[Path]:
    roots = [Path(os.path.realpath(PLAY_PREFIX))]
    env = os.environ.get("FLMOD_PLAY_PREFIX")
    if env:
        p = Path(os.path.realpath(env))
        if p not in roots:
            roots.append(p)
    return roots


def refuse_play_prefix(path: str | os.PathLike, what: str = "write") -> Path:
    """Raise :class:`PlayPrefixError` if ``path`` resolves into a protected prefix.
    Returns the resolved path otherwise. No filesystem writes; only ``realpath``."""
    real = Path(os.path.realpath(os.fspath(path)))
    for root in protected_roots():
        if real == root or root in real.parents:
            raise PlayPrefixError(
                f"refusing to {what} {path}: it is inside the play prefix {root}")
    return real
