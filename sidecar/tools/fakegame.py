#!/usr/bin/env python3
"""Fake game client for the copilot sidecar, protocol v1 (docs/spec/ipc.md).

It plays the game DLL's side: it connects to 127.0.0.1, sends ``hello``, replays an NDJSON
script, asserts on the sidecar's replies and acks its commands. It is stdlib-only and does
not import ``flcopilot``, so it is an independent second implementation of the protocol.

Usage:
    fakegame.py [--port N] [--no-hello] [--timeout S] [-v] script.ndjson [script2.ndjson ...]

``--port`` defaults to $FLCOPILOT_PORT, then 29170. Exit code 0 = every script passed.

Script format: one JSON object per line. Blank lines and lines starting with ``#`` or ``//``
are ignored. Directives:

    {"options": {"hello": false}}             first line only: don't send hello on connect
    {"send": {"t": "...", ...}}               send a message; v/seq/gt are filled in if absent
    {"send": {...}, "raw": true}              send the object exactly as written
    {"send_raw": "text", "repeat": 1, "newline": true}   send raw bytes (text * repeat)
    {"hello": {...overrides}}                 send hello (with field overrides, e.g. {"v": 2})
    {"expect": {pattern}, "timeout": 2, "skip": false}  next message must match the pattern
                                              (pings are answered and skipped automatically;
                                              "skip": true skips non-matching messages)
    {"expect_closed": true, "timeout": 2}     the sidecar must close the connection
    {"expect_silence": 0.5}                   no message other than ping for 0.5 s
    {"ack": {"ok": true, "applied": {...}, "err": "...", "detail": "..."}}
                                              ack the most recent command (default applied =
                                              an echo of the command's fields)
    {"ptt": "down" | "up"}  or  {"ptt": "tap", "hold_ms": 200}
    {"sleep": 0.1}
    {"auto_pong": false}                      stop answering the sidecar's pings
    {"disconnect": true}
    {"connect": true, "hello": true}          (re)connect, then send hello unless "hello": false
    {"comment": "..."}

Pattern values: literals compare equal (bool is not int); objects match as subsets; lists
match element-wise. Special strings: "$any", "$int", "$num", "$str", "$bool", "$list",
"$obj", "$null", "$absent" (key must be missing). Special objects: {"$range": [lo, hi]},
{"$re": "regex"} (full match), {"$contains": "text"}.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

HOST = "127.0.0.1"
DEFAULT_PORT = 29170
PROTOCOL_VERSION = 1

DEFAULT_POLICY = {
    "auto_bots": True, "bots_hull_below": 0.5, "bots_reserve": 0, "critical_hull": 0.25,
    "release_reserve_when": "never", "auto_batts": True, "batts_shield_below": 0.25, "batts_reserve": 0,
}


class ExpectationFailed(AssertionError):
    pass


_ABSENT = object()


def match(pattern, value, path: str = "$") -> str | None:
    """None if ``value`` matches ``pattern``, else a description of the first mismatch."""
    if isinstance(pattern, str) and pattern.startswith("$") and pattern in _TYPE_CHECKS:
        if pattern == "$absent":
            return None if value is _ABSENT else f"{path}: expected absent, got {value!r}"
        if value is _ABSENT:
            return f"{path}: missing"
        return None if _TYPE_CHECKS[pattern](value) else f"{path}: expected {pattern}, got {value!r}"
    if value is _ABSENT:
        return f"{path}: missing"
    if isinstance(pattern, dict) and len(pattern) == 1 and next(iter(pattern)) in ("$range", "$re", "$contains"):
        op, arg = next(iter(pattern.items()))
        if op == "$range":
            ok = _is_num(value) and arg[0] <= value <= arg[1]
            return None if ok else f"{path}: {value!r} not in range {arg}"
        if op == "$re":
            ok = isinstance(value, str) and re.fullmatch(arg, value) is not None
            return None if ok else f"{path}: {value!r} does not match /{arg}/"
        ok = isinstance(value, str) and arg in value
        return None if ok else f"{path}: {value!r} does not contain {arg!r}"
    if isinstance(pattern, dict):
        if not isinstance(value, dict):
            return f"{path}: expected object, got {value!r}"
        for k, p in pattern.items():
            err = match(p, value.get(k, _ABSENT), f"{path}.{k}")
            if err:
                return err
        return None
    if isinstance(pattern, list):
        if not isinstance(value, list) or len(value) != len(pattern):
            return f"{path}: expected list of {len(pattern)}, got {value!r}"
        for i, (p, v) in enumerate(zip(pattern, value)):
            err = match(p, v, f"{path}[{i}]")
            if err:
                return err
        return None
    if isinstance(pattern, bool) or isinstance(value, bool):
        return None if (type(pattern) is type(value) and pattern == value) else f"{path}: expected {pattern!r}, got {value!r}"
    return None if pattern == value else f"{path}: expected {pattern!r}, got {value!r}"


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_TYPE_CHECKS = {
    "$any": lambda v: True,
    "$int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "$num": _is_num,
    "$str": lambda v: isinstance(v, str),
    "$bool": lambda v: isinstance(v, bool),
    "$list": lambda v: isinstance(v, list),
    "$obj": lambda v: isinstance(v, dict),
    "$null": lambda v: v is None,
    "$absent": lambda v: False,
}


class FakeGame:
    """The DLL side of protocol v1, for tests."""

    def __init__(self, port: int = DEFAULT_PORT, host: str = HOST, auto_pong: bool = True,
                 verbose: bool = False, name: str = "fakegame"):
        if host != HOST:
            raise ValueError("fakegame only talks to 127.0.0.1")
        self.host = host
        self.port = port
        self.auto_pong = auto_pong
        self.verbose = verbose
        self.name = name
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.seq = 0
        self.t0 = time.monotonic()
        self.received: list[dict] = []
        self.pings: list[dict] = []
        self.last_command: dict | None = None
        self.connections = 0

    # ---- connection --------------------------------------------------------------------
    async def connect(self, timeout: float = 2.0) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, limit=1 << 20), timeout)
        self.seq = 0
        self.connections += 1
        self._log(f"connected to {self.host}:{self.port}")

    async def close(self) -> None:
        if self.writer is not None:
            try:
                self.writer.close()
                await asyncio.wait_for(self.writer.wait_closed(), 1.0)
            except Exception:
                pass
        self.reader = self.writer = None

    @property
    def connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()

    # ---- sending -----------------------------------------------------------------------
    def gt(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    async def send(self, msg: dict | str, raw: bool = False, **fields) -> dict:
        if isinstance(msg, str):
            msg = {"t": msg, **fields}
        else:
            msg = {**msg, **fields}
        if not raw:
            self.seq += 1
            msg = {"v": PROTOCOL_VERSION, "seq": self.seq, "gt": self.gt(), **msg}
        await self.send_raw(json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n")
        self._log(f"-> {msg}")
        return msg

    async def send_raw(self, data: bytes) -> None:
        if self.writer is None:
            raise ConnectionError("not connected")
        self.writer.write(data)
        await self.writer.drain()

    async def hello(self, **overrides) -> dict:
        msg = {"t": "hello", "dll": f"{self.name}/0.1.0", "game": "fakegame", "char": "Test Pilot",
               "save": "HARNESS_fake", "policy": {"player": dict(DEFAULT_POLICY)},
               "features": ["reflex"], "ptt_vk": 110}
        msg.update(overrides)
        return await self.send(msg)

    async def handshake(self, timeout: float = 2.0, **overrides) -> dict:
        await self.hello(**overrides)
        return await self.expect({"t": "welcome", "v": PROTOCOL_VERSION}, timeout=timeout)

    async def ptt(self, down: bool) -> dict:
        return await self.send("ptt", down=bool(down))

    async def ack(self, cmd: dict | None = None, ok: bool = True, applied=_ABSENT, err: str | None = None,
                  detail: str | None = None) -> dict:
        cmd = cmd or self.last_command
        if cmd is None:
            raise ExpectationFailed("ack: no command received yet")
        fields: dict = {"id": cmd["id"], "ok": bool(ok)}
        if ok:
            fields["applied"] = ({k: v for k, v in cmd.items() if k not in ("v", "t", "seq", "id", "gt")}
                                 if applied is _ABSENT else applied)
        else:
            fields["err"] = err or "bad_value"
        if detail:
            fields["detail"] = detail
        return await self.send("ack", **fields)

    # ---- receiving ---------------------------------------------------------------------
    async def recv(self, timeout: float = 2.0, include_pings: bool = False) -> dict | None:
        """Next message (None at EOF). Pings are answered (if auto_pong) and skipped."""
        if self.reader is None:
            raise ConnectionError("not connected")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError("no message")
            line = await asyncio.wait_for(self.reader.readline(), remaining)
            if not line:
                return None
            msg = json.loads(line.decode("utf-8"))
            self.received.append(msg)
            self._log(f"<- {msg}")
            if msg.get("t") == "ping":
                self.pings.append(msg)
                if self.auto_pong:
                    await self.send("pong", **({"n": msg["n"]} if "n" in msg else {}))
                if not include_pings:
                    continue
            if "id" in msg and msg.get("t") not in ("ack",):
                self.last_command = msg
            return msg

    async def expect(self, pattern: dict, timeout: float = 2.0, skip: bool = False) -> dict:
        deadline = time.monotonic() + timeout
        include_pings = isinstance(pattern, dict) and pattern.get("t") == "ping"
        while True:
            remaining = deadline - time.monotonic()
            try:
                msg = await self.recv(max(remaining, 0.001), include_pings=include_pings)
            except asyncio.TimeoutError:
                raise ExpectationFailed(f"timeout after {timeout}s waiting for {pattern}") from None
            if msg is None:
                raise ExpectationFailed(f"connection closed while waiting for {pattern}")
            err = match(pattern, msg)
            if err is None:
                return msg
            if not skip:
                raise ExpectationFailed(f"unexpected message {msg}: {err}")

    async def expect_closed(self, timeout: float = 2.0) -> list[dict]:
        """Read until EOF; returns the messages seen on the way."""
        seen = []
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            try:
                msg = await self.recv(max(remaining, 0.001))
            except asyncio.TimeoutError:
                raise ExpectationFailed(f"connection still open after {timeout}s") from None
            except (ConnectionError, OSError):
                msg = None
            if msg is None:
                await self.close()
                return seen
            seen.append(msg)

    async def expect_silence(self, duration: float) -> None:
        try:
            msg = await self.recv(duration)
        except asyncio.TimeoutError:
            return
        if msg is None:
            raise ExpectationFailed("connection closed during expected silence")
        raise ExpectationFailed(f"expected silence, got {msg}")

    def _log(self, text: str) -> None:
        if self.verbose:
            print(f"[fakegame] {text}", file=sys.stderr)


# ---- scripts ------------------------------------------------------------------------------
def load_script(path: str | os.PathLike) -> list[dict]:
    steps = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        try:
            step = json.loads(s)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n}: bad JSON: {exc}") from None
        if not isinstance(step, dict):
            raise ValueError(f"{path}:{n}: each line must be a JSON object")
        step["_line"] = n
        steps.append(step)
    return steps


async def run_steps(game: FakeGame, steps: list[dict], default_timeout: float = 2.0) -> None:
    options = {}
    if steps and "options" in steps[0]:
        options = steps[0]["options"]
        steps = steps[1:]
    if not game.connected:
        await game.connect()
        if options.get("hello", True):
            await game.hello()
    for step in steps:
        where = f"line {step.get('_line', '?')}"
        timeout = float(step.get("timeout", default_timeout))
        try:
            if "comment" in step and len([k for k in step if k != "_line"]) == 1:
                continue
            if "send" in step:
                await game.send(step["send"], raw=bool(step.get("raw")))
            elif "send_raw" in step:
                data = str(step["send_raw"]) * int(step.get("repeat", 1))
                payload = data.encode("utf-8") + (b"\n" if step.get("newline", True) else b"")
                await game.send_raw(payload)
            elif "hello" in step and "connect" not in step:
                await game.hello(**(step["hello"] or {}))
            elif "expect" in step:
                await game.expect(step["expect"], timeout=timeout, skip=bool(step.get("skip")))
            elif "expect_closed" in step:
                await game.expect_closed(timeout=timeout)
            elif "expect_silence" in step:
                await game.expect_silence(float(step["expect_silence"]))
            elif "ack" in step:
                a = step["ack"] or {}
                await game.ack(ok=a.get("ok", True), applied=a.get("applied", _ABSENT),
                               err=a.get("err"), detail=a.get("detail"))
            elif "ptt" in step:
                mode = step["ptt"]
                if mode == "tap":
                    await game.ptt(True)
                    await asyncio.sleep(float(step.get("hold_ms", 200)) / 1000.0)
                    await game.ptt(False)
                elif mode in ("down", "up"):
                    await game.ptt(mode == "down")
                else:
                    raise ValueError(f"ptt must be down|up|tap, got {mode!r}")
            elif "sleep" in step:
                await asyncio.sleep(float(step["sleep"]))
            elif "auto_pong" in step:
                game.auto_pong = bool(step["auto_pong"])
            elif "disconnect" in step:
                await game.close()
            elif "connect" in step:
                await game.close()
                await game.connect()
                if step.get("hello", True):
                    await game.hello()
            else:
                raise ValueError(f"unknown directive {sorted(k for k in step if k != '_line')}")
        except ExpectationFailed as exc:
            raise ExpectationFailed(f"{where}: {exc}") from None


async def run_script_file(path: str | os.PathLike, port: int, verbose: bool = False,
                          timeout: float = 2.0, hello: bool = True) -> FakeGame:
    steps = load_script(path)
    if not hello and not (steps and "options" in steps[0]):
        steps.insert(0, {"options": {"hello": False}})
    game = FakeGame(port=port, verbose=verbose)
    try:
        await run_steps(game, steps, default_timeout=timeout)
    finally:
        await game.close()
    return game


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fake game client for the copilot sidecar (protocol v1).")
    ap.add_argument("scripts", nargs="+", help="NDJSON script files")
    ap.add_argument("--port", type=int, default=int(os.environ.get("FLCOPILOT_PORT") or DEFAULT_PORT))
    ap.add_argument("--no-hello", action="store_true", help="do not send hello on connect")
    ap.add_argument("--timeout", type=float, default=2.0, help="default expect timeout (s)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    failed = 0
    for script in args.scripts:
        try:
            asyncio.run(run_script_file(script, args.port, verbose=args.verbose, timeout=args.timeout,
                                        hello=not args.no_hello))
            print(f"PASS {script}")
        except (ExpectationFailed, ConnectionError, OSError, ValueError, asyncio.TimeoutError) as exc:
            failed += 1
            print(f"FAIL {script}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
