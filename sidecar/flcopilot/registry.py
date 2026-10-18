"""Handler registry: later waves extend the sidecar by registering handlers, not by editing the server.

    registry.register_handler("ev.kill", on_kill)        # exact type
    registry.register_handler("ev.*", on_any_event)      # prefix wildcard
    registry.register_handler("*", on_anything)          # every message
    registry.on_session_start(fn) / on_session_end(fn)   # connection lifecycle

A handler is ``fn(session, msg)``; it may be a plain function or a coroutine function.
Handlers for one message run in registration order (exact, then wildcards). A handler that
raises is logged and does not affect the connection or the other handlers. Handlers run
inline on the connection's read loop, so long work (STT, LLM) must spawn its own task.
"""
from __future__ import annotations

import inspect
from collections import defaultdict
from typing import Any, Callable

from . import logsetup

log = logsetup.get("registry")

Handler = Callable[[Any, dict], Any]


class HandlerRegistry:
    def __init__(self) -> None:
        self._exact: dict[str, list[Handler]] = defaultdict(list)
        self._prefix: list[tuple[str, Handler]] = []
        self._all: list[Handler] = []
        self._start: list[Callable[[Any], Any]] = []
        self._end: list[Callable[[Any], Any]] = []

    def register_handler(self, t: str, fn: Handler) -> Handler:
        if not isinstance(t, str) or not t:
            raise ValueError("message type must be a non-empty string")
        if not callable(fn):
            raise TypeError("handler must be callable")
        if t == "*":
            self._all.append(fn)
        elif t.endswith(".*"):
            self._prefix.append((t[:-1], fn))  # keep the trailing "."
        elif "*" in t:
            raise ValueError(f"unsupported wildcard {t!r}; use 'prefix.*' or '*'")
        else:
            self._exact[t].append(fn)
        return fn

    def handler(self, t: str) -> Callable[[Handler], Handler]:
        """Decorator form of :meth:`register_handler`."""
        def deco(fn: Handler) -> Handler:
            return self.register_handler(t, fn)
        return deco

    def on_session_start(self, fn: Callable[[Any], Any]) -> None:
        self._start.append(fn)

    def on_session_end(self, fn: Callable[[Any], Any]) -> None:
        self._end.append(fn)

    def handlers_for(self, t: str) -> list[Handler]:
        out = list(self._exact.get(t, ()))
        out += [fn for prefix, fn in self._prefix if t.startswith(prefix)]
        out += self._all
        return out

    def has_handler(self, t: str) -> bool:
        return bool(self.handlers_for(t))

    def has_specific_handler(self, t: str) -> bool:
        """An exact or prefix handler (not just a ``*`` catch-all) is registered for ``t``."""
        return bool(self._exact.get(t)) or any(t.startswith(p) for p, _ in self._prefix)

    async def dispatch(self, session: Any, msg: dict) -> int:
        """Run every handler for ``msg["t"]``. Returns how many ran."""
        handlers = self.handlers_for(msg.get("t", ""))
        for fn in handlers:
            await _call(fn, session, msg)
        return len(handlers)

    async def session_started(self, session: Any) -> None:
        for fn in self._start:
            await _call(fn, session)

    async def session_ended(self, session: Any) -> None:
        for fn in self._end:
            await _call(fn, session)


async def _call(fn: Callable, *args: Any) -> None:
    try:
        res = fn(*args)
        if inspect.isawaitable(res):
            await res
    except Exception:  # a broken handler must never kill the connection
        log.exception("handler failed", extra={"kv": {"handler": getattr(fn, "__qualname__", repr(fn))}})
