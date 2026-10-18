"""Logging: structured JSON lines to a rotating file, plus a human line on stderr.

The file log is one JSON object per line: ``{"ts", "lvl", "sub", "msg", ...fields}``.
stderr uses the project log format ``[carrier] <subsystem>: <message> k=v ...``.
Loggers are named ``sidecar.<subsystem>`` (for example ``sidecar.server``).

Pass structured fields with ``log.info("msg", extra={"kv": {...}})``.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

ROOT = "sidecar"
ROTATE_BYTES = 10 * 1024 * 1024
ROTATE_BACKUPS = 5

_installed: list[logging.Handler] = []


def get(sub: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{sub}")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
        out = {
            "ts": f"{ts}.{int(record.msecs):03d}Z",
            "lvl": record.levelname,
            "sub": record.name,
            "msg": record.getMessage(),
        }
        kv = getattr(record, "kv", None)
        if isinstance(kv, dict):
            for k, v in kv.items():
                if k not in out:
                    out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = f"[carrier] {record.name}: {record.getMessage()}"
        kv = getattr(record, "kv", None)
        if isinstance(kv, dict) and kv:
            line += " " + " ".join(f"{k}={_kv(v)}" for k, v in kv.items())
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _kv(v) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return f'"{s}"' if (" " in s or s == "") else s


def setup(log_file: str | os.PathLike | None, level: str = "INFO", stderr: bool = True,
          max_bytes: int = ROTATE_BYTES, backups: int = ROTATE_BACKUPS) -> Path | None:
    """Install handlers on the ``sidecar`` logger. Idempotent (replaces earlier handlers)."""
    root = logging.getLogger(ROOT)
    for h in _installed:
        root.removeHandler(h)
        h.close()
    _installed.clear()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.propagate = False
    path = None
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups,
                                                  encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
        _installed.append(fh)
    if stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(HumanFormatter())
        root.addHandler(sh)
        _installed.append(sh)
    return path


def shutdown() -> None:
    root = logging.getLogger(ROOT)
    for h in _installed:
        try:
            h.flush()
        finally:
            root.removeHandler(h)
            h.close()
    _installed.clear()
    root.propagate = True
