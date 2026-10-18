"""Command line: ``python -m flcopilot`` (normally through ``sidecar/run.sh``)."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import signal
import socket
import sys
import time

from . import __version__, config, logsetup, protocol
from .profiles import PROFILES, ProfileError

log = logsetup.get("main")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="flcopilot", description="Copilot sidecar for the Freelancer Carrier Mod.")
    ap.add_argument("--profile", choices=PROFILES, help="live (default for play) or test (harness/lanes/CI)")
    ap.add_argument("--port", type=int, help="listen port on 127.0.0.1 (default: FLCOPILOT_PORT, then config)")
    ap.add_argument("--config", help="public TOML config (default: sidecar/config/flcopilot.toml)")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--local-config", help="local YAML overlay (default: $FLMOD_LOCAL/sidecar.local.yaml)")
    grp.add_argument("--no-local-config", action="store_true", help="ignore the local overlay")
    ap.add_argument("--log-file", help="JSON log file (default from config)")
    ap.add_argument("--log-level", help="DEBUG|INFO|WARNING|ERROR")
    ap.add_argument("--quiet", action="store_true", help="no human log on stderr")
    ap.add_argument("--heartbeat-s", type=float, help="ping interval (tests)")
    ap.add_argument("--mic-file", help="test profile: WAV used as the microphone")
    ap.add_argument("--null-wav-dir", help="test profile: write null-sink audio here as WAVs")
    ap.add_argument("--selftest", action="store_true",
                    help="start the server (test profile), run the fake client handshake, shut down")
    ap.add_argument("--discover-mic", action="store_true", help="resolve mic_match to a capture source and exit")
    ap.add_argument("--print-config", action="store_true", help="print the effective config and exit")
    ap.add_argument("--version", action="version", version=f"flcopilot {__version__} (protocol v{protocol.PROTOCOL_VERSION})")
    return ap.parse_args(argv)


def _load_cfg(args) -> config.Config:
    overrides = {
        "server.port": args.port,
        "server.heartbeat_s": args.heartbeat_s,
        "log.file": args.log_file,
        "log.level": args.log_level,
        "profile.default": args.profile,
    }
    local = False if args.no_local_config else (args.local_config or None)
    return config.load(args.config, local_path=local, overrides=overrides)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cfg = _load_cfg(args)
    except config.ConfigError as exc:
        print(f"flcopilot: config error: {exc}", file=sys.stderr)
        return 2
    log_path = config.resolve_log_file(cfg)
    logsetup.setup(log_path, level=cfg.get("log.level"), stderr=not args.quiet,
                   max_bytes=int(cfg.get("log.max_bytes")), backups=int(cfg.get("log.backups")))
    log.info("flcopilot starting", extra={"kv": {"version": __version__, "pid": os.getpid(),
                                                 "sources": cfg.sources, "log": str(log_path)}})
    for w in cfg.warnings:
        log.warning(w)
    try:
        if args.print_config:
            data = cfg.as_dict()
            if data["audio"].get("mic_match"):
                data["audio"]["mic_match"] = "<set in local overlay>"
            print(json.dumps(data, indent=2, sort_keys=True))
            return 0
        if args.discover_mic:
            return discover_mic(cfg)
        if args.selftest:
            return asyncio.run(selftest(cfg, log_path))
        profile = cfg.get("profile.default")
        return asyncio.run(serve(cfg, profile, args.mic_file, args.null_wav_dir))
    except ProfileError as exc:
        log.error(f"profile error: {exc}")
        return 2
    finally:
        logsetup.shutdown()


def discover_mic(cfg) -> int:
    from .audio import devices

    d = devices.discover(str(cfg.get("audio.mic_match") or ""))
    if d.status == "resolved":
        print(f"mic: resolved index={d.source.index} name={d.source.name} matches={d.candidates}")
        return 0
    print(f"mic: {d.status.replace('_', ' ')}" + (f" ({d.detail})" if d.detail else ""))
    return 1


async def serve(cfg, profile_name: str, mic_file=None, null_wav_dir=None) -> int:
    from .app import build_app

    app = build_app(cfg, profile_name, mic_file=mic_file, null_wav_dir=null_wav_dir)
    try:
        port = await app.server.start()
    except OSError as exc:
        log.error("cannot listen", extra={"kv": {"port": cfg.get("server.port"), "err": str(exc)}})
        return 3
    print(f"FLCOPILOT ready host={protocol.LOOPBACK_HOST} port={port} profile={app.profile.name} pid={os.getpid()}",
          flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    log.info("signal received; shutting down")
    await app.server.stop("shutdown")
    log.info("shutdown clean")
    return 0


def _load_fakegame():
    path = config.SIDECAR_DIR / "tools" / "fakegame.py"
    spec = importlib.util.spec_from_file_location("flcopilot_fakegame", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


async def selftest(cfg, log_path) -> int:
    """Server up (test profile) -> fake client handshake script -> clean shutdown seen by a client."""
    from .app import build_app
    from .server import listening_addresses

    fg = _load_fakegame()
    checks: dict[str, object] = {}
    app = build_app(cfg, "test")
    t0 = time.perf_counter()
    port = await app.server.start()
    addrs = listening_addresses(port)
    checks["listen"] = [f"{fam}:{ip}" for fam, ip in addrs]
    checks["loopback_only"] = bool(addrs) and all(ip == protocol.LOOPBACK_HOST for _, ip in addrs)
    script = config.SIDECAR_DIR / "tests" / "scripts" / "handshake.ndjson"
    try:
        await fg.run_script_file(script, port)
        checks["handshake_script"] = "pass"
    except Exception as exc:
        checks["handshake_script"] = f"FAIL {exc}"
    # A client that stays connected must see bye{shutdown} and then EOF.
    game = fg.FakeGame(port=port)
    try:
        await game.connect()
        await game.handshake()
        stop_task = asyncio.ensure_future(app.server.stop("shutdown"))
        seen = await game.expect_closed(timeout=3.0)
        await stop_task
        byes = [m for m in seen if m.get("t") == "bye"]
        checks["shutdown_bye"] = byes[0].get("reason") if byes else "missing"
    except Exception as exc:
        checks["shutdown_bye"] = f"FAIL {exc}"
        await app.server.stop("shutdown")
    # After shutdown the port must be closed.
    try:
        with socket.create_connection((protocol.LOOPBACK_HOST, port), timeout=0.5):
            checks["port_closed_after"] = False
    except OSError:
        checks["port_closed_after"] = True
    checks["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    ok = (checks["loopback_only"] is True and checks["handshake_script"] == "pass"
          and checks["shutdown_bye"] == "shutdown" and checks["port_closed_after"] is True)
    log.info("selftest " + ("ok" if ok else "FAILED"), extra={"kv": {"port": port, **checks}})
    print(f"SELFTEST {'ok' if ok else 'FAIL'} port={port} " + " ".join(f"{k}={v}" for k, v in checks.items())
          + f" log={log_path}", flush=True)
    return 0 if ok else 1
