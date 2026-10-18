"""Config layering: public TOML < local YAML overlay < FLCOPILOT_PORT < CLI."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from flcopilot import config


def write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_public_defaults():
    cfg = config.load(None, local_path=False, env={})
    assert cfg.get("server.port") == 29170
    assert cfg.get("audio.mic_match") == ""
    assert cfg.get("audio.ptt_key") == "numpad_period"
    assert cfg.get("audio.capture_enabled") is False
    assert cfg.get("profile.default") == "live"
    assert cfg.warnings == []


def test_committed_toml_has_no_device_name_and_matches_builtin():
    data = tomllib.loads(config.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert data["audio"]["mic_match"] == ""
    for section, keys in config.BUILTIN.items():
        assert set(data[section]) == set(keys), section


def test_local_overlay_flat_and_nested(tmp_path):
    ov = write(tmp_path / "local.yaml", 'mic_match: "Example_Headset"\nptt_key: numpad_minus\n'
                                         "audio:\n  capture_enabled: true\nserver:\n  port: 29999\n")
    cfg = config.load(None, local_path=ov, env={})
    assert cfg.get("audio.mic_match") == "Example_Headset"
    assert cfg.get("audio.ptt_key") == "numpad_minus"
    assert cfg.get("audio.capture_enabled") is True
    assert cfg.get("server.port") == 29999
    assert "local overlay" in cfg.sources


def test_env_port_beats_overlay_and_cli_beats_env(tmp_path):
    ov = write(tmp_path / "local.yaml", "server:\n  port: 29999\n")
    cfg = config.load(None, local_path=ov, env={"FLCOPILOT_PORT": "29173"})
    assert cfg.get("server.port") == 29173  # lane 3
    cfg = config.load(None, local_path=ov, env={"FLCOPILOT_PORT": "29173"}, overrides={"server.port": 29180})
    assert cfg.get("server.port") == 29180


def test_default_overlay_location(tmp_path, monkeypatch):
    write(tmp_path / "sidecar.local.yaml", 'mic_match: "Example"\n')
    monkeypatch.setenv("FLMOD_LOCAL", str(tmp_path))
    monkeypatch.delenv("FLCOPILOT_LOCAL_CONFIG", raising=False)
    assert config.default_local_overlay() == tmp_path / "sidecar.local.yaml"
    assert config.load(None, env={}).get("audio.mic_match") == "Example"
    monkeypatch.setenv("FLCOPILOT_LOCAL_CONFIG", str(tmp_path / "other.yaml"))
    assert config.default_local_overlay() == tmp_path / "other.yaml"


def test_unknown_keys_warn(tmp_path):
    ov = write(tmp_path / "local.yaml", "colour: blue\naudio:\n  volume: 11\n")
    cfg = config.load(None, local_path=ov, env={})
    assert any("colour" in w for w in cfg.warnings)
    assert any("audio.volume" in w for w in cfg.warnings)


def test_missing_explicit_overlay_warns(tmp_path):
    cfg = config.load(None, local_path=tmp_path / "nope.yaml", env={})
    assert any("not found" in w for w in cfg.warnings)


@pytest.mark.parametrize("ov,match", [
    ({"server.port": 70000}, "server.port"),
    ({"server.port": "29170"}, "server.port"),
    ({"server.heartbeat_s": 0}, "heartbeat_s"),
    ({"server.missed_pongs": 0}, "missed_pongs"),
    ({"profile.default": "prod"}, "profile"),
    ({"audio.ptt_key": "banana"}, "ptt_key"),
    ({"audio.tail_ms": -1}, "tail_ms"),
    ({"log.level": "LOUD"}, "log.level"),
])
def test_bad_values_rejected(ov, match):
    with pytest.raises(config.ConfigError, match=match):
        config.load(None, local_path=False, env={}, overrides=ov)


def test_bad_env_port():
    with pytest.raises(config.ConfigError, match="FLCOPILOT_PORT"):
        config.load(None, local_path=False, env={"FLCOPILOT_PORT": "lane3"})


def test_unknown_override_rejected():
    with pytest.raises(config.ConfigError, match="unknown override"):
        config.load(None, local_path=False, env={}, overrides={"server.host": "0.0.0.0"})


def test_bad_yaml_and_bad_toml(tmp_path):
    with pytest.raises(config.ConfigError):
        config.load(None, local_path=write(tmp_path / "a.yaml", "mic_match: [unclosed\n"), env={})
    with pytest.raises(config.ConfigError):
        config.load(None, local_path=write(tmp_path / "b.yaml", "- a list\n"), env={})
    with pytest.raises(config.ConfigError):
        config.load(write(tmp_path / "c.toml", "[server\n"), local_path=False, env={})


def test_var_expansion_and_log_fallback(tmp_path, monkeypatch):
    assert config.expand("${A}/x", {"A": "/base"}) == "/base/x"
    assert config.expand("${A}/x", {}) == ""
    monkeypatch.delenv("FLMOD_LOCAL", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    cfg = config.load(None, local_path=False, env={})
    assert config.resolve_log_file(cfg) == tmp_path / "flcopilot" / "sidecar.log"
    monkeypatch.setenv("FLMOD_LOCAL", "/srv/x")
    assert config.resolve_log_file(cfg) == Path("/srv/x/sidecar-logs/sidecar.log")


def test_real_local_overlay_parses_if_present():
    """The orchestrator's gitignored overlay must load. Its values are never printed."""
    path = config.default_local_overlay()
    if path is None or not path.exists():
        pytest.skip("no local overlay on this machine (FLMOD_LOCAL unset or file absent)")
    cfg = config.load(None, local_path=path, env={})
    assert isinstance(cfg.get("audio.mic_match"), str)
    config.validate(cfg)
