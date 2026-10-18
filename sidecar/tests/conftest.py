"""Shared fixtures. Every server in these tests binds an ephemeral port on 127.0.0.1 and runs the
test profile: null audio sink, fake transcriber, fake TTS, fake brain. No audio device, GPU,
model or network is touched."""
from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

import pytest

SIDECAR_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SIDECAR_DIR.parent
SCRIPTS_DIR = SIDECAR_DIR / "tests" / "scripts"

for p in (SIDECAR_DIR, SIDECAR_DIR / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from flcopilot import config  # noqa: E402
from flcopilot.app import build_app  # noqa: E402


def make_cfg(**overrides):
    """Effective config with the public TOML, no local overlay, port 0 (ephemeral)."""
    ov = {"server.port": 0, "log.file": ""}
    ov.update(overrides)
    return config.load(None, local_path=False, env={}, overrides=ov)


@contextlib.asynccontextmanager
async def running_app(profile: str = "test", mic_file=None, **overrides):
    cfg = make_cfg(**overrides)
    app = build_app(cfg, profile, mic_file=mic_file)
    port = await app.server.start()
    try:
        yield app, port
    finally:
        await app.server.stop("shutdown")


def run(coro, timeout: float = 20.0):
    """Run a coroutine on a fresh loop with an overall timeout (no pytest-asyncio needed)."""
    async def guarded():
        return await asyncio.wait_for(coro, timeout)
    return asyncio.run(guarded())


@pytest.fixture
def fakegame():
    import fakegame as fg
    return fg
