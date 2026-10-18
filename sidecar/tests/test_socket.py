"""Socket-level tests over a real loopback connection on an ephemeral port.

The six required by the spec: handshake, ping timeout, malformed line, oversize line,
version mismatch, reconnect replacing the old connection. Plus the edges around them.
"""
from __future__ import annotations

import asyncio
import json
import socket

import pytest

from conftest import run, running_app
from flcopilot import __version__, protocol
from flcopilot.protocol import ProtocolError
from flcopilot.server import listening_addresses


# ---- 1. handshake -----------------------------------------------------------------------
def test_handshake(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            hello = await g.hello(char="Test Pilot", save="HARNESS_x")
            w = await g.expect({"t": "welcome"})
            assert w["v"] == 1 and w["seq"] == 1
            assert w["sidecar"] == __version__
            assert set(w["features"]) <= set(protocol.FEATURES)
            assert w["heartbeat_ms"] == 2000
            assert w["profile"] == "test"
            assert "gt" not in w  # the sidecar omits game time
            sess = await app.server.wait_for_session()
            assert sess.hello["char"] == "Test Pilot" and sess.hello["seq"] == hello["seq"]
            assert app.server.stats.sessions == 1
            await g.close()
    run(body())


# ---- 2. ping timeout --------------------------------------------------------------------
def test_ping_timeout_closes_session(fakegame):
    async def body():
        async with running_app(**{"server.heartbeat_s": 0.05}) as (app, port):
            g = fakegame.FakeGame(port=port, auto_pong=False)
            await g.connect()
            await g.handshake()
            seen = await g.expect_closed(timeout=2.0)
            assert seen[-1]["t"] == "bye" and seen[-1]["reason"] == "timeout"
            assert len(g.pings) == 3  # exactly missed_pongs pings went unanswered
            assert app.server.stats.ping_timeouts == 1
            assert app.server.active is None
    run(body())


def test_answered_pings_keep_session_alive(fakegame):
    async def body():
        async with running_app(**{"server.heartbeat_s": 0.05}) as (app, port):
            g = fakegame.FakeGame(port=port, auto_pong=True)
            await g.connect()
            await g.handshake()
            await g.expect_silence(0.6)  # ~12 pings, all answered automatically
            assert len(g.pings) >= 5
            assert app.server.stats.ping_timeouts == 0
            assert app.server.active is not None
            await g.close()
    run(body())


# ---- 3. malformed lines -----------------------------------------------------------------
def test_malformed_lines_rejected_connection_kept(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.send_raw(b"this is not json\n")
            await g.send_raw(b"[1, 2, 3]\n")
            await g.send_raw(b'{"t": "ping"}\n')                      # envelope: no v, no seq
            await g.send_raw(b"\xff\xfe\xfd\n")                        # not UTF-8
            await g.send_raw(b'{"v":1,"t":"ping","seq":1,"n":NaN}\n')  # non-finite number
            await g.send_raw(b"\n")                                    # empty line: ignored silently
            await g.send("ev.hull", band=33, dir="down")               # valid envelope, bad payload
            await g.send("ping", n=42)
            pong = await g.expect({"t": "pong"})
            assert pong["n"] == 42
            st = app.server.stats
            assert st.malformed == 5
            assert st.invalid == 1
            assert app.server.active is not None and not app.server.active.closing
            await g.close()
    run(body())


def test_crlf_line_endings_tolerated(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.send_raw(b'{"v":1,"t":"ping","seq":2,"gt":0,"n":5}\r\n')
            assert (await g.expect({"t": "pong"}))["n"] == 5
            await g.close()
    run(body())


# ---- 4. oversize lines ------------------------------------------------------------------
def _ping_line(n: int, total: int | None = None) -> bytes:
    msg = {"v": 1, "t": "ping", "seq": 2, "gt": 0, "n": n}
    line = json.dumps(msg, separators=(",", ":")).encode()
    if total is not None:  # pad with an extra field to hit an exact size incl. "\n"
        pad = total - len(line) - len(b',"pad":""') - 1
        msg["pad"] = "x" * pad
        line = json.dumps(msg, separators=(",", ":")).encode()
        assert len(line) + 1 == total
    return line + b"\n"


def test_oversize_lines_skipped_connection_kept(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            # (a) exactly the limit (65536 bytes incl. "\n") is accepted.
            await g.send_raw(_ping_line(1, total=protocol.MAX_LINE_BYTES))
            assert (await g.expect({"t": "pong"}))["n"] == 1
            # (b) one byte over is rejected.
            await g.send_raw(_ping_line(2, total=protocol.MAX_LINE_BYTES + 1))
            # (c) 70 KB arriving in one burst, newline included.
            await g.send_raw(b"y" * 70_000 + b"\n")
            # (d) 300 KB with no newline for a while, then a tail that is itself a valid ping:
            #     the tail belongs to the oversize line and must NOT be parsed as a message.
            await g.send_raw(b"z" * 300_000)
            await asyncio.sleep(0.1)
            await g.send_raw(b'{"v":1,"t":"ping","seq":3,"gt":0,"n":666}\n')
            # The connection still works, and the next pong is ours, not 2 or 666.
            await g.send("ping", n=3)
            assert (await g.expect({"t": "pong"}))["n"] == 3
            await g.expect_silence(0.2)
            assert app.server.stats.oversize == 3
            assert app.server.active is not None and not app.server.active.closing
            await g.close()
    run(body())


# ---- 5. version mismatch ----------------------------------------------------------------
def test_version_mismatch_gets_bye_and_close(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.hello(v=2)
            seen = await g.expect_closed()
            assert [m["t"] for m in seen] == ["bye"]
            assert seen[0]["reason"] == "version" and seen[0]["supported"] == [1]
            assert app.server.stats.version_mismatch == 1
            assert app.server.active is None
    run(body())


# ---- 6. reconnect replaces the old connection -------------------------------------------
def test_new_connection_replaces_old(fakegame):
    async def body():
        async with running_app() as (app, port):
            a = fakegame.FakeGame(port=port, name="game-a")
            await a.connect()
            await a.handshake()
            first = await app.server.wait_for_session()
            b = fakegame.FakeGame(port=port, name="game-b")
            await b.connect()
            await b.handshake()
            seen = await a.expect_closed()
            assert seen and seen[-1]["t"] == "bye" and seen[-1]["reason"] == "replaced"
            await b.send("ping", n=9)
            assert (await b.expect({"t": "pong"}))["n"] == 9
            assert app.server.active is not first
            assert app.server.active.hello["dll"].startswith("game-b")
            assert app.server.stats.replaced == 1
            assert first.close_reason == "replaced"
            await b.close()
    run(body())


def test_connection_without_hello_does_not_replace_active(fakegame):
    async def body():
        async with running_app() as (app, port):
            a = fakegame.FakeGame(port=port)
            await a.connect()
            await a.handshake()
            stray = fakegame.FakeGame(port=port)
            await stray.connect()  # never says hello
            await asyncio.sleep(0.1)
            await a.send("ping", n=1)
            assert (await a.expect({"t": "pong"}))["n"] == 1
            assert app.server.stats.replaced == 0
            await stray.close()
            await a.close()
    run(body())


# ---- edges ------------------------------------------------------------------------------
def test_handshake_timeout(fakegame):
    async def body():
        async with running_app(**{"server.handshake_timeout_s": 0.2}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            seen = await g.expect_closed(timeout=2.0)
            assert seen[-1]["t"] == "bye" and seen[-1]["reason"] == "protocol"
            assert app.server.stats.handshake_timeouts == 1
    run(body())


def test_before_hello_only_ping_is_answered(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.send("ev.dock", base="test_base")
            await g.send("ping", n=4)
            assert (await g.expect({"t": "pong"}))["n"] == 4
            assert app.server.stats.before_hello == 2
            await g.handshake()
            await g.close()
    run(body())


def test_invalid_hello_rejected(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.send({"t": "hello", "game": "x"})  # no dll
            seen = await g.expect_closed()
            assert seen[-1]["t"] == "bye" and seen[-1]["reason"] == "protocol"
    run(body())


def test_unknown_type_ignored_connection_kept(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.send("ev.from_the_future", whatever=1)
            await g.send("ev.dock", base="test_base", new_optional_field=True)  # new fields are fine
            await g.send("ping", n=8)
            assert (await g.expect({"t": "pong"}))["n"] == 8
            assert app.server.stats.unknown_type == 1
            assert app.server.stats.invalid == 0
            await g.close()
    run(body())


def test_sidecar_only_type_from_game_ignored(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.send("policy.set", id="c-1", scope="player", auto_bots=False)
            await g.send("ping", n=1)
            assert (await g.expect({"t": "pong"}))["n"] == 1
            assert app.server.stats.wrong_direction == 1
            await g.close()
    run(body())


def test_registry_dispatch_and_failing_handler(fakegame):
    async def body():
        async with running_app() as (app, port):
            got = []
            app.registry.register_handler("ev.kill", lambda s, m: got.append(("exact", m["victim"])))
            app.registry.register_handler("ev.*", lambda s, m: got.append(("prefix", m["t"])))

            async def boom(s, m):
                raise RuntimeError("handler bug")
            app.registry.register_handler("ev.kill", boom)
            app.registry.register_handler("ev.experimental", lambda s, m: got.append(("new", m["t"])))
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            await g.send("ev.kill", victim="Test Rogue", cls="fighter", by="player")
            await g.send("ev.experimental", x=1)  # unknown to v1 but a later wave registered it
            await g.send("ping", n=1)
            assert (await g.expect({"t": "pong"}))["n"] == 1
            assert ("exact", "Test Rogue") in got and ("prefix", "ev.kill") in got
            assert ("new", "ev.experimental") in got
            await g.close()
    run(body())


def test_command_ack_roundtrip_and_timeout(fakegame):
    async def body():
        async with running_app(**{"server.ack_timeout_s": 0.3}) as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            sess = await app.server.wait_for_session()
            fut = await sess.send_command("act", do="use_bots")
            cmd = await g.expect({"t": "act", "do": "use_bots", "id": "$str"})
            await g.ack(cmd, ok=False, err="not_now", detail="docked")
            ack = await asyncio.wait_for(fut, 1.0)
            assert ack["ok"] is False and ack["err"] == "not_now"
            fut2 = await sess.send_command("act", do="use_batts")
            await g.expect({"t": "act", "do": "use_batts"})
            assert await asyncio.wait_for(fut2, 2.0) is None  # never acked -> timeout -> None
            assert app.server.stats.ack_timeouts == 1
            with pytest.raises(ProtocolError):
                await sess.send_command("policy.set", scope="player", bogus=1)  # strict: unknown field
            with pytest.raises(ProtocolError):
                await sess.send_command("policy.set", scope="player")  # no policy field at all
            with pytest.raises(ProtocolError):
                await sess.send_command("ping")  # not a command
            await g.close()
    run(body())


def test_peer_bye_closes_session(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            sess = await app.server.wait_for_session()
            await g.send("bye", reason="shutdown")
            await asyncio.wait_for(sess.done.wait(), 2.0)
            assert sess.close_reason == "peer:shutdown"
            await g.close()
    run(body())


def test_server_stop_sends_shutdown_bye(fakegame):
    async def body():
        async with running_app() as (app, port):
            g = fakegame.FakeGame(port=port)
            await g.connect()
            await g.handshake()
            stop = asyncio.ensure_future(app.server.stop("shutdown"))
            seen = await g.expect_closed()
            await stop
            assert seen[-1] == {**seen[-1], "t": "bye", "reason": "shutdown"}
    run(body())


# ---- bind address -----------------------------------------------------------------------
def test_binds_loopback_ipv4_only():
    async def body():
        async with running_app() as (app, port):
            names = [s.getsockname() for s in app.server._server.sockets]
            assert names == [("127.0.0.1", port)]
            listens = listening_addresses(port)
            assert listens == [("ipv4", "127.0.0.1")], listens
            # Not reachable over IPv6 loopback.
            with pytest.raises(OSError):
                with socket.create_connection(("::1", port), timeout=0.5):
                    pass
            # Not reachable on any non-loopback address of this host.
            others = set()
            try:
                for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                    if not info[4][0].startswith("127."):
                        others.add(info[4][0])
            except OSError:
                pass
            for ip in others:
                with pytest.raises(OSError):
                    with socket.create_connection((ip, port), timeout=0.5):
                        pass
    run(body())


def test_configured_port_is_used():
    # Find a free port, then ask for it explicitly (lanes use 29170 + N the same way).
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]

    async def body():
        async with running_app(**{"server.port": free}) as (app, port):
            assert port == free
    run(body())
