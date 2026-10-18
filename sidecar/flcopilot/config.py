"""Configuration: public TOML defaults, then the gitignored local YAML overlay, then env, then CLI.

Precedence (later wins):
  1. ``sidecar/config/flcopilot.toml`` (committed; no secrets, no device names)
  2. the local overlay, ``$FLMOD_LOCAL/sidecar.local.yaml`` (gitignored; holds ``mic_match``, ``ptt_key``)
  3. env ``FLCOPILOT_PORT`` (the harness sets 29170 + N per lane)
  4. CLI flags (``--port`` etc.)

String values may use ``${VAR}``; a value whose variables cannot all be resolved counts as unset.
"""
from __future__ import annotations

import copy
import os
import re
import tomllib
from pathlib import Path
from typing import Any

from . import protocol

SIDECAR_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SIDECAR_DIR / "config" / "flcopilot.toml"

#: Flat keys allowed in the local overlay, mapped to their section.
LOCAL_ALIASES = {
    "mic_match": ("audio", "mic_match"),
    "ptt_key": ("audio", "ptt_key"),
}

#: Built-in defaults; the TOML file normally repeats them. Unknown TOML keys are reported.
BUILTIN: dict[str, dict[str, Any]] = {
    "server": {
        "port": protocol.DEFAULT_PORT,
        "heartbeat_s": protocol.HEARTBEAT_S,
        "missed_pongs": protocol.MISSED_PONGS_LIMIT,
        "handshake_timeout_s": 5.0,
        "ack_timeout_s": 5.0,
    },
    "log": {
        "file": "${FLMOD_LOCAL}/sidecar-logs/sidecar.log",
        "level": "INFO",
        "max_bytes": 10 * 1024 * 1024,
        "backups": 5,
    },
    "profile": {"default": "live"},
    "audio": {
        "mic_match": "",
        "ptt_key": "numpad_period",
        "capture_enabled": False,
        "sample_rate": 16000,
        "preroll_ms": 300,
        "tail_ms": 150,
        "output_device": "default",
    },
    "stt": {
        "model_path": "${FLMOD_MODELS}/whisper/faster-whisper-large-v3-turbo",
        "model_name": "large-v3-turbo",
        "device": "cuda",
        "compute_type": "float16",
        "language": "en",
        "beam_size": 1,
    },
    "tts": {
        "model_dir": "${FLMOD_MODELS}/kokoro",
        "voice": "am_michael",
        "speed": 1.0,
    },
    "test": {
        "fake_transcript": "save nanobots for the cruiser",
        "fake_bots_reserve": 5,
    },
}

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    pass


def expand(value: str, env: dict | None = None) -> str:
    """Expand ``${VAR}``. Returns "" if any variable is unset or empty."""
    env = os.environ if env is None else env
    missing = False

    def sub(m: re.Match) -> str:
        nonlocal missing
        val = env.get(m.group(1), "")
        if not val:
            missing = True
        return val

    out = _VAR_RE.sub(sub, value)
    out = os.path.expanduser(out)
    return "" if missing else out


class Config:
    """A two-level mapping ``section -> key -> value`` plus load notes."""

    def __init__(self, data: dict, sources: list[str], warnings: list[str]):
        self.data = data
        self.sources = sources
        self.warnings = warnings

    def get(self, dotted: str, default: Any = None) -> Any:
        section, _, key = dotted.partition(".")
        return self.data.get(section, {}).get(key, default)

    def set(self, dotted: str, value: Any) -> None:
        section, _, key = dotted.partition(".")
        self.data.setdefault(section, {})[key] = value

    def path(self, dotted: str) -> Path | None:
        raw = self.get(dotted) or ""
        s = expand(str(raw))
        return Path(s) if s else None

    def as_dict(self) -> dict:
        return copy.deepcopy(self.data)


def _merge(base: dict, over: dict, origin: str, warnings: list[str], aliases: dict | None = None) -> None:
    for key, val in over.items():
        if aliases and key in aliases and not isinstance(val, dict):
            section, sub = aliases[key]
            base.setdefault(section, {})[sub] = val
            continue
        if key not in base:
            warnings.append(f"{origin}: unknown section {key!r} ignored")
            continue
        if not isinstance(val, dict):
            warnings.append(f"{origin}: {key!r} must be a table/mapping; ignored")
            continue
        for sub, subval in val.items():
            if sub not in base[key]:
                warnings.append(f"{origin}: unknown key {key}.{sub} ignored")
                continue
            base[key][sub] = subval


def default_local_overlay() -> Path | None:
    explicit = os.environ.get("FLCOPILOT_LOCAL_CONFIG", "")
    if explicit:
        return Path(explicit)
    local = os.environ.get("FLMOD_LOCAL", "")
    return Path(local) / "sidecar.local.yaml" if local else None


def load(config_path: str | os.PathLike | None = None,
         local_path: str | os.PathLike | None | bool = None,
         env: dict | None = None,
         overrides: dict | None = None) -> Config:
    """Load and validate the effective config.

    ``local_path``: a path, ``None`` for the default overlay, or ``False`` for no overlay.
    ``overrides``: dotted keys from the CLI, applied last.
    """
    env = os.environ if env is None else env
    data = copy.deepcopy(BUILTIN)
    sources: list[str] = ["builtin"]
    warnings: list[str] = []

    cpath = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if cpath.exists():
        with open(cpath, "rb") as fh:
            try:
                toml = tomllib.load(fh)
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"{cpath}: {exc}") from None
        _merge(data, toml, str(cpath.name), warnings)
        sources.append(str(cpath))
    elif config_path:
        raise ConfigError(f"config file not found: {cpath}")

    if local_path is not False:
        lpath = Path(local_path) if local_path else default_local_overlay()
        if lpath is not None and lpath.exists():
            try:
                import yaml  # pyyaml; only needed for the overlay
            except ImportError:
                warnings.append(f"{lpath}: pyyaml not installed; local overlay skipped")
            else:
                with open(lpath, encoding="utf-8") as fh:
                    try:
                        overlay = yaml.safe_load(fh) or {}
                    except yaml.YAMLError as exc:
                        raise ConfigError(f"{lpath}: {exc}") from None
                if not isinstance(overlay, dict):
                    raise ConfigError(f"{lpath}: top level must be a mapping")
                _merge(data, overlay, "local overlay", warnings, aliases=LOCAL_ALIASES)
                # Only the file name: the overlay path itself is not secret, but its values may be.
                sources.append("local overlay")
        elif local_path:
            warnings.append(f"local overlay {lpath} not found; using public defaults")

    env_port = env.get("FLCOPILOT_PORT", "")
    if env_port:
        try:
            data["server"]["port"] = int(env_port)
        except ValueError:
            raise ConfigError(f"FLCOPILOT_PORT={env_port!r} is not an integer") from None
        sources.append("env FLCOPILOT_PORT")

    if overrides:
        for dotted, val in overrides.items():
            if val is None:
                continue
            section, _, key = dotted.partition(".")
            if section not in data or key not in data[section]:
                raise ConfigError(f"unknown override {dotted}")
            data[section][key] = val
        sources.append("cli")

    cfg = Config(data, sources, warnings)
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    port = cfg.get("server.port")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ConfigError(f"server.port must be an int 0..65535 (0 = ephemeral, tests only), got {port!r}")
    for key in ("server.heartbeat_s", "server.handshake_timeout_s", "server.ack_timeout_s"):
        val = cfg.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
            raise ConfigError(f"{key} must be a positive number, got {val!r}")
    mp = cfg.get("server.missed_pongs")
    if not isinstance(mp, int) or isinstance(mp, bool) or mp < 1:
        raise ConfigError(f"server.missed_pongs must be an int >= 1, got {mp!r}")
    if cfg.get("profile.default") not in ("live", "test"):
        raise ConfigError(f"profile.default must be live|test, got {cfg.get('profile.default')!r}")
    try:
        protocol.ptt_vk(cfg.get("audio.ptt_key"))
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    if not isinstance(cfg.get("audio.mic_match"), str):
        raise ConfigError("audio.mic_match must be a string")
    for key in ("audio.sample_rate", "audio.preroll_ms", "audio.tail_ms"):
        val = cfg.get(key)
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise ConfigError(f"{key} must be an int >= 0, got {val!r}")
    level = str(cfg.get("log.level")).upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ConfigError(f"log.level must be DEBUG|INFO|WARNING|ERROR, got {cfg.get('log.level')!r}")


def resolve_log_file(cfg: Config) -> Path:
    """The configured log file, or an XDG state fallback when ``${FLMOD_LOCAL}`` is unset."""
    p = cfg.path("log.file")
    if p:
        return p
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(state) / "flcopilot" / "sidecar.log"
