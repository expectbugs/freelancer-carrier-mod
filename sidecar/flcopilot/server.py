"""NDJSON-over-TCP server for protocol v1 (docs/spec/ipc.md).

- Binds 127.0.0.1 only. One active session: the newest connection that completes the
  handshake replaces the previous one (game restart), which gets ``bye{reason:"replaced"}``.
- Lines are read with ``StreamReader.readuntil`` and a 64 KiB limit. A malformed line is
  logged and dropped; an oversize line is skipped up to its newline. Neither drops the
  connection.
- Heartbeat: ``ping`` every ``heartbeat_s``; after ``missed_pongs`` unanswered pings the
  session is closed with ``bye{reason:"timeout"}``.
- Everything else goes through the :class:`~flcopilot.registry.HandlerRegistry`.
"""
from __future__ import annotations

import asyncio
import itertools
import os
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from . import __version__, logsetup, protocol
from .protocol import ProtocolError
from .registry import HandlerRegistry

log = logsetup.get("server")

MAX_PENDING_CONNECTIONS = 4
SEND_TIMEOUT_S = 2.0


@dataclass
class Stats:
    connections: int = 0
    sessions: int = 0
    lines_in: int = 0
    lines_out: int = 0
    malformed: int = 0
    oversize: int = 0
    invalid: int = 0
    unknown_type: int = 0
    wrong_direction: int = 0
    before_hello: int = 0
    version_mismatch: int = 0
    ping_timeouts: int = 0
    handshake_timeouts: int = 0
    replaced: int = 0
    refused: int = 0
    acks: int = 0
    ack_timeouts: int = 0
    by_type: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class Session:
    """One TCP connection from a game DLL."""

    def __init__(self, server: "SidecarServer", reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, sid: int):
        self.server = server
        self.reader = reader
        self.writer = writer
        self.sid = sid
        peer = writer.get_extra_info("peername")
        self.peer = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) else str(peer)
        self.hello: dict | None = None
        self.last_state: dict | None = None
        self.handshaken = False
        self.started = False  # session_start hooks ran
        self.closing = False
        self._close_started = False
        self._bg: set[asyncio.Task] = set()
        self.close_reason: str | None = None
        self.seq_out = 0
        self.last_seq_in: int | None = None
        self.misses = 0
        self._ping_n = 0
        self._discarding = False
        self._unknown_seen: set[str] = set()
        self._send_lock = asyncio.Lock()
        self._heartbeat: asyncio.Task | None = None
        self._handshake_timer: asyncio.TimerHandle | None = None
        self._cmd_ids = itertools.count(1)
        self.pending: dict[str, tuple[str, asyncio.Future, asyncio.TimerHandle]] = {}
        self.done = asyncio.Event()
        self.data: dict[str, Any] = {}  # scratch space for features (keyed by feature name)

    # ---- sending -----------------------------------------------------------------------
    async def send(self, t: str, **fields: Any) -> dict:
        """Send one message (the envelope is added here). Returns the message sent."""
        async with self._send_lock:
            if self.closing and t != "bye":
                raise ConnectionError("session closing")
            self.seq_out += 1
            msg = {"v": protocol.PROTOCOL_VERSION, "t": t, "seq": self.seq_out, **fields}
            data = protocol.encode(msg)
            self.writer.write(data)
            await asyncio.wait_for(self.writer.drain(), SEND_TIMEOUT_S)
            self.server.stats.lines_out += 1
        lvl = 10 if t in ("ping", "pong") else 20
        log.log(lvl, "sent", extra={"kv": {"sid": self.sid, "t": t, "seq": msg["seq"],
                                           **({"id": fields["id"]} if "id" in fields else {})}})
        return msg

    async def send_command(self, t: str, **fields: Any) -> asyncio.Future:
        """Send a command with a fresh id. The returned future resolves to the ack dict,
        or to ``None`` on ack timeout or disconnect. Invalid commands raise ProtocolError
        (that is a sidecar bug, never sent)."""
        spec = protocol.MESSAGES.get(t)
        if spec is None or spec.kind != protocol.COMMAND:
            raise ProtocolError("not_a_command", t)
        cid = f"c-{next(self._cmd_ids)}"
        probe = {"v": protocol.PROTOCOL_VERSION, "t": t, "seq": 0, "id": cid, **fields}
        errors = protocol.validate(probe)
        if errors:
            raise ProtocolError("invalid_command", "; ".join(errors))
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        timer = loop.call_later(self.server.ack_timeout_s, self._ack_timeout, cid)
        self.pending[cid] = (t, fut, timer)
        try:
            await self.send(t, id=cid, **fields)
        except Exception:
            self._resolve(cid, None)
            raise
        return fut

    def _resolve(self, cid: str, ack: dict | None) -> None:
        entry = self.pending.pop(cid, None)
        if entry is None:
            return
        _, fut, timer = entry
        timer.cancel()
        if not fut.done():
            fut.set_result(ack)

    def _ack_timeout(self, cid: str) -> None:
        if cid in self.pending:
            self.server.stats.ack_timeouts += 1
            log.warning("ack timeout", extra={"kv": {"sid": self.sid, "id": cid, "t": self.pending[cid][0]}})
            self._resolve(cid, None)

    # ---- lifecycle ---------------------------------------------------------------------
    async def close(self, reason: str | None = None, detail: str = "", send_bye: bool = True,
                    **extra: Any) -> None:
        if self._close_started or self.closing:
            return
        self._close_started = True
        if send_bye and reason:
            fields: dict[str, Any] = {"reason": reason}
            if detail:
                fields["detail"] = detail[:256]
            fields.update(extra)
            try:
                await self.send("bye", **fields)
            except Exception as exc:  # peer may already be gone
                log.debug("bye not sent", extra={"kv": {"sid": self.sid, "err": repr(exc)}})
        self.closing = True
        self.close_reason = self.close_reason or reason or "closed"
        log.info("closing session", extra={"kv": {"sid": self.sid, "reason": self.close_reason,
                                                  **({"detail": detail} if detail else {})}})
        if self._handshake_timer:
            self._handshake_timer.cancel()
        if self._heartbeat and self._heartbeat is not asyncio.current_task():
            self._heartbeat.cancel()
        try:
            self.writer.close()
        except Exception:
            pass

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._handshake_timer = loop.call_later(self.server.handshake_timeout_s, self._on_handshake_timeout)
        try:
            while not self.closing:
                line = await self._read_line()
                if line is None:
                    break
                await self._handle_line(line)
        except (ConnectionError, asyncio.IncompleteReadError, OSError) as exc:
            log.info("connection lost", extra={"kv": {"sid": self.sid, "err": repr(exc)}})
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if not self.closing:
            self.closing = True
            self.close_reason = self.close_reason or "eof"
        if self._handshake_timer:
            self._handshake_timer.cancel()
        if self._heartbeat and self._heartbeat is not asyncio.current_task():
            self._heartbeat.cancel()
        for cid in list(self.pending):
            self._resolve(cid, None)
        try:
            self.writer.close()
            await asyncio.wait_for(self.writer.wait_closed(), 1.0)
        except Exception:
            pass
        if self.started:
            await self.server.registry.session_ended(self)
        self.server._session_finished(self)
        log.info("session ended", extra={"kv": {"sid": self.sid, "reason": self.close_reason}})
        self.done.set()

    def _on_handshake_timeout(self) -> None:
        if not self.handshaken and not self.closing:
            self.server.stats.handshake_timeouts += 1
            log.warning("no hello before timeout", extra={"kv": {"sid": self.sid}})
            task = asyncio.ensure_future(self.close("protocol", detail="no hello before timeout"))
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)

    async def _heartbeat_loop(self) -> None:
        interval = self.server.heartbeat_s
        limit = self.server.missed_pongs
        try:
            while not self.closing:
                await asyncio.sleep(interval)
                if self.closing:
                    return
                if self.misses >= limit:
                    self.server.stats.ping_timeouts += 1
                    log.warning("ping timeout", extra={"kv": {"sid": self.sid, "missed": self.misses}})
                    self.close_reason = "timeout"
                    await self.close("timeout", detail=f"{self.misses} pings unanswered")
                    return
                self.misses += 1
                self._ping_n += 1
                await self.send("ping", n=self._ping_n)
        except asyncio.CancelledError:
            pass
        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            log.info("heartbeat stopped", extra={"kv": {"sid": self.sid, "err": repr(exc)}})
            await self.close(None, send_bye=False)

    # ---- receiving ---------------------------------------------------------------------
    async def _read_line(self) -> bytes | None:
        """Next complete line, or None at EOF. Oversize lines are skipped whole."""
        while True:
            try:
                chunk = await self.reader.readuntil(b"\n")
            except asyncio.IncompleteReadError as exc:
                if exc.partial and not self._discarding:
                    log.warning("partial line at EOF dropped",
                                extra={"kv": {"sid": self.sid, "bytes": len(exc.partial)}})
                return None
            except asyncio.LimitOverrunError as exc:
                # The data stays in the buffer (readuntil contract): drop what was scanned and
                # keep discarding until this line's newline arrives.
                await self.reader.readexactly(exc.consumed)
                if not self._discarding:
                    self.server.stats.oversize += 1
                    log.warning("oversize line rejected", extra={"kv": {
                        "sid": self.sid, "limit": protocol.MAX_LINE_BYTES}})
                self._discarding = True
                continue
            if self._discarding:
                self._discarding = False  # this was the tail (up to the newline) of the oversize line
                continue
            return chunk

    async def _handle_line(self, line: bytes) -> None:
        stats = self.server.stats
        stats.lines_in += 1
        try:
            msg = protocol.decode(line)
        except ProtocolError as exc:
            stats.malformed += 1
            log.warning("malformed line rejected", extra={"kv": {
                "sid": self.sid, "code": exc.code, "detail": exc.detail[:160], "line": protocol.preview(line)}})
            return
        if not msg:
            return
        t = msg["t"]
        stats.by_type[t] = stats.by_type.get(t, 0) + 1
        log.log(20 if t in ("hello", "bye") else 10, "recv", extra={"kv": {"sid": self.sid, "t": t, "seq": msg["seq"]}})
        seq = msg["seq"]
        if self.last_seq_in is not None and seq != self.last_seq_in + 1:
            log.debug("seq gap", extra={"kv": {"sid": self.sid, "expected": self.last_seq_in + 1, "got": seq}})
        self.last_seq_in = seq

        if t == "hello":
            await self._on_hello(msg)
            return
        if not self.handshaken:
            stats.before_hello += 1
            if t == "ping":
                await self.send("pong", **({"n": msg["n"]} if "n" in msg else {}))
            else:
                log.info("ignored before hello", extra={"kv": {"sid": self.sid, "t": t}})
            return
        if msg["v"] not in protocol.SUPPORTED_VERSIONS:
            stats.invalid += 1
            log.warning("unsupported version on message; dropped", extra={"kv": {"sid": self.sid, "t": t, "v": msg["v"]}})
            return
        spec = protocol.MESSAGES.get(t)
        registry = self.server.registry
        if spec is None:
            stats.unknown_type += 1
            if registry.has_specific_handler(t):
                await registry.dispatch(self, msg)
                return
            first = t not in self._unknown_seen
            self._unknown_seen.add(t)
            log.log(30 if first else 10, "unknown message type ignored", extra={"kv": {"sid": self.sid, "t": t}})
            return
        if spec.direction == protocol.S2G:
            stats.wrong_direction += 1
            log.warning("sidecar-only message from game ignored", extra={"kv": {"sid": self.sid, "t": t}})
            return
        errors = protocol.validate(msg)
        if errors:
            stats.invalid += 1
            log.warning("invalid message dropped", extra={"kv": {"sid": self.sid, "t": t, "errors": errors[:5]}})
            return

        if t == "ping":
            await self.send("pong", **({"n": msg["n"]} if "n" in msg else {}))
        elif t == "pong":
            self.misses = 0
        elif t == "bye":
            log.info("peer said bye", extra={"kv": {"sid": self.sid, "reason": msg.get("reason")}})
            self.close_reason = f"peer:{msg.get('reason')}"
            await self.close(None, send_bye=False)
        elif t == "ack":
            stats.acks += 1
            cid = msg["id"]
            if cid in self.pending:
                log.info("ack", extra={"kv": {"sid": self.sid, "id": cid, "ok": msg["ok"],
                                              **({"err": msg["err"]} if "err" in msg else {})}})
                self._resolve(cid, msg)
            else:
                log.warning("ack for unknown or expired id", extra={"kv": {"sid": self.sid, "id": cid}})
        elif t == "state":
            self.last_state = msg
        await registry.dispatch(self, msg)

    async def _on_hello(self, msg: dict) -> None:
        v = msg.get("v")
        if v not in protocol.SUPPORTED_VERSIONS:
            self.server.stats.version_mismatch += 1
            log.warning("protocol version mismatch", extra={"kv": {"sid": self.sid, "peer_v": v}})
            self.close_reason = "version"
            await self.close("version", detail=f"sidecar speaks v{protocol.PROTOCOL_VERSION}, got v{v}",
                             supported=list(protocol.SUPPORTED_VERSIONS))
            return
        errors = protocol.validate(msg)
        if errors:
            self.server.stats.invalid += 1
            log.warning("invalid hello", extra={"kv": {"sid": self.sid, "errors": errors[:5]}})
            self.close_reason = "protocol"
            await self.close("protocol", detail="invalid hello: " + "; ".join(errors)[:200])
            return
        first = not self.handshaken
        self.hello = msg
        self.handshaken = True
        if self._handshake_timer:
            self._handshake_timer.cancel()
        if first:
            await self.server._activate(self)
            if self.closing:
                return
        log.info("hello", extra={"kv": {"sid": self.sid, "dll": msg.get("dll"), "game": msg.get("game"),
                                        "repeat": not first}})
        await self.send("welcome", sidecar=__version__, features=list(self.server.features),
                        heartbeat_ms=int(self.server.heartbeat_s * 1000), profile=self.server.profile_name)
        ptt = msg.get("ptt_vk")
        if ptt is not None and self.server.ptt_vk is not None and ptt != self.server.ptt_vk:
            log.warning("DLL polls a different push-to-talk key than configured",
                        extra={"kv": {"sid": self.sid, "dll_vk": ptt, "config_vk": self.server.ptt_vk}})
        if first:
            self._heartbeat = asyncio.ensure_future(self._heartbeat_loop())
            self.started = True
            await self.server.registry.session_started(self)
        await self.server.registry.dispatch(self, msg)


class SidecarServer:
    def __init__(self, registry: HandlerRegistry | None = None, port: int = protocol.DEFAULT_PORT,
                 heartbeat_s: float = protocol.HEARTBEAT_S, missed_pongs: int = protocol.MISSED_PONGS_LIMIT,
                 handshake_timeout_s: float = 5.0, ack_timeout_s: float = 5.0,
                 features: tuple | list = (), profile_name: str = "live", ptt_vk: int | None = None):
        self.registry = registry or HandlerRegistry()
        self.requested_port = port
        self.heartbeat_s = heartbeat_s
        self.missed_pongs = missed_pongs
        self.handshake_timeout_s = handshake_timeout_s
        self.ack_timeout_s = ack_timeout_s
        self.features = tuple(features)
        self.profile_name = profile_name
        self.ptt_vk = ptt_vk
        self.stats = Stats()
        self.active: Session | None = None
        self.sessions: set[Session] = set()
        self._server: asyncio.base_events.Server | None = None
        self._sids = itertools.count(1)
        self.port: int | None = None
        self.session_changed = asyncio.Event()

    @classmethod
    def from_config(cls, cfg, registry: HandlerRegistry | None = None, features=(), profile_name="live"):
        return cls(registry=registry, port=cfg.get("server.port"), heartbeat_s=float(cfg.get("server.heartbeat_s")),
                   missed_pongs=int(cfg.get("server.missed_pongs")),
                   handshake_timeout_s=float(cfg.get("server.handshake_timeout_s")),
                   ack_timeout_s=float(cfg.get("server.ack_timeout_s")),
                   features=features, profile_name=profile_name,
                   ptt_vk=protocol.ptt_vk(cfg.get("audio.ptt_key")))

    async def start(self) -> int:
        self._server = await asyncio.start_server(
            self._on_client, host=protocol.LOOPBACK_HOST, port=self.requested_port,
            limit=protocol.MAX_LINE_BYTES - 1, family=socket.AF_INET)
        addrs = [s.getsockname() for s in self._server.sockets]
        bad = [a for a in addrs if a[0] != protocol.LOOPBACK_HOST]
        if bad or not addrs:
            self._server.close()
            raise RuntimeError(f"refusing to listen on non-loopback addresses {bad}")
        self.port = addrs[0][1]
        log.info("listening", extra={"kv": {"host": protocol.LOOPBACK_HOST, "port": self.port,
                                            "profile": self.profile_name, "features": list(self.features),
                                            "pid": os.getpid()}})
        return self.port

    async def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.stats.connections += 1
        pending = [s for s in self.sessions if not s.handshaken and not s.closing]
        if len(pending) >= MAX_PENDING_CONNECTIONS:
            self.stats.refused += 1
            log.warning("too many connections without hello; refusing")
            writer.close()
            return
        # Belt and braces: the listener is loopback-only, so the peer must be too.
        peer = writer.get_extra_info("peername")
        if not (isinstance(peer, tuple) and str(peer[0]).startswith("127.")):
            self.stats.refused += 1
            log.error("non-loopback peer refused", extra={"kv": {"peer": str(peer)}})
            writer.close()
            return
        sess = Session(self, reader, writer, next(self._sids))
        self.sessions.add(sess)
        log.info("connection", extra={"kv": {"sid": sess.sid, "peer": sess.peer}})
        await sess.run()

    async def _activate(self, sess: Session) -> None:
        old = self.active
        self.active = sess
        self.stats.sessions += 1
        self.session_changed.set()
        if old is not None and old is not sess and not old.closing:
            self.stats.replaced += 1
            log.info("new session replaces the old one", extra={"kv": {"old": old.sid, "new": sess.sid}})
            old.close_reason = "replaced"
            await old.close("replaced", detail=f"replaced by session {sess.sid}")

    def _session_finished(self, sess: Session) -> None:
        self.sessions.discard(sess)
        if self.active is sess:
            self.active = None
            self.session_changed.set()

    async def wait_for_session(self, timeout: float = 5.0) -> Session:
        deadline = time.monotonic() + timeout
        while self.active is None or not self.active.handshaken:
            self.session_changed.clear()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError("no session")
            try:
                await asyncio.wait_for(self.session_changed.wait(), remaining)
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError("no session") from None
        return self.active

    async def stop(self, reason: str = "shutdown") -> None:
        if self._server is not None:
            self._server.close()
        for sess in list(self.sessions):
            await sess.close(reason if sess.handshaken else None, detail="sidecar stopping",
                             send_bye=sess.handshaken)
        for sess in list(self.sessions):
            try:
                await asyncio.wait_for(sess.done.wait(), 2.0)
            except asyncio.TimeoutError:
                log.warning("session did not finish in time", extra={"kv": {"sid": sess.sid}})
        if self._server is not None:
            try:
                await asyncio.wait_for(self._server.wait_closed(), 2.0)
            except asyncio.TimeoutError:
                log.warning("listener did not close in time")
            self._server = None
        log.info("stopped", extra={"kv": {"reason": reason, "stats": self.stats.as_dict()}})


def listening_addresses(port: int) -> list[tuple[str, str]]:
    """(family, ip) of every TCP LISTEN socket on ``port`` in this network namespace (/proc/net)."""
    out: list[tuple[str, str]] = []
    for fam, path in (("ipv4", "/proc/net/tcp"), ("ipv6", "/proc/net/tcp6")):
        try:
            with open(path, encoding="ascii") as fh:
                next(fh)
                for line in fh:
                    parts = line.split()
                    if len(parts) < 4 or parts[3] != "0A":
                        continue
                    addr, _, hexport = parts[1].partition(":")
                    if int(hexport, 16) != port:
                        continue
                    if fam == "ipv4":
                        ip = socket.inet_ntop(socket.AF_INET, struct.pack("<I", int(addr, 16)))
                    else:
                        words = [int(addr[i:i + 8], 16) for i in range(0, 32, 8)]
                        ip = socket.inet_ntop(socket.AF_INET6, struct.pack("<4I", *words))
                    out.append((fam, ip))
        except FileNotFoundError:
            continue
    return out
