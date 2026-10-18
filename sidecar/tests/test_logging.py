"""Structured JSON log with rotation, and the human stderr format."""
from __future__ import annotations

import json
import logging

from flcopilot import logsetup


def test_json_lines_and_rotation(tmp_path):
    path = tmp_path / "logs" / "sidecar.log"
    try:
        logsetup.setup(path, level="INFO", stderr=False, max_bytes=2000, backups=2)
        log = logsetup.get("test")
        for i in range(100):
            log.info("event", extra={"kv": {"i": i, "text": "ünïcode"}})
        log.debug("hidden at INFO")
    finally:
        logsetup.shutdown()
    files = sorted(p.name for p in path.parent.iterdir())
    assert files == ["sidecar.log", "sidecar.log.1", "sidecar.log.2"]  # rotated, capped at 2 backups
    for p in path.parent.iterdir():
        assert p.stat().st_size <= 2000 + 200
        for line in p.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            assert rec["lvl"] == "INFO" and rec["sub"] == "sidecar.test" and rec["msg"] == "event"
            assert rec["text"] == "ünïcode" and rec["ts"].endswith("Z")
    assert logging.getLogger("sidecar").propagate is True  # restored for other tests


def test_default_rotation_is_10_mib():
    assert logsetup.ROTATE_BYTES == 10 * 1024 * 1024


def test_human_format():
    rec = logging.LogRecord("sidecar.server", logging.INFO, __file__, 1, "listening", None, None)
    rec.kv = {"port": 29170, "note": "two words"}
    assert logsetup.HumanFormatter().format(rec) == '[carrier] sidecar.server: listening port=29170 note="two words"'


def test_exception_is_logged_as_field(tmp_path):
    path = tmp_path / "x.log"
    try:
        logsetup.setup(path, stderr=False)
        try:
            raise ValueError("boom")
        except ValueError:
            logsetup.get("t").exception("failed")
    finally:
        logsetup.shutdown()
    rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["lvl"] == "ERROR" and "ValueError: boom" in rec["exc"]
