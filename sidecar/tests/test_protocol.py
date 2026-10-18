"""Protocol v1: the code catalog matches docs/spec/ipc.md; framing and validation rules."""
from __future__ import annotations

import json
import re

import pytest

from conftest import REPO_DIR
from flcopilot import protocol
from flcopilot.protocol import ProtocolError, decode, encode, validate

SPEC = REPO_DIR / "docs" / "spec" / "ipc.md"

POLICY = {"auto_bots": True, "bots_hull_below": 0.5, "bots_reserve": 0, "critical_hull": 0.25,
          "release_reserve_when": "never", "auto_batts": True, "batts_shield_below": 0.25, "batts_reserve": 0}

#: One valid example per message type (payload only; the envelope is added below).
SAMPLES = {
    "hello": {"dll": "0.1.0", "game": "FLHD", "char": None, "save": None, "policy": {"player": POLICY},
              "features": ["reflex"], "ptt_vk": 110},
    "welcome": {"sidecar": "0.1.0", "features": ["stt", "tts"], "heartbeat_ms": 2000, "profile": "live"},
    "bye": {"reason": "version", "supported": [1], "detail": "x"},
    "ping": {"n": 1},
    "pong": {"n": 1},
    "state": {"rate": "combat",
              "ship": {"hull": 0.8, "shield": 0.0, "shield_up": False, "bots": 3, "batts": 2, "mode": "free",
                       "system": "test_system", "base": None, "near": None, "speed": 80.5},
              "target": {"id": 7, "name": "Bandit", "faction": None, "cls": "gunboat", "hull": 1.0,
                         "shield": 0.5, "dist": 900.0, "hostile": True},
              "threat": {"hostiles": 2, "capital_hostile": True, "incoming_missiles": None},
              "wing": [{"id": "w1", "name": "Wing One", "hull": 1.0, "state": "follow", "dist": 50}],
              "carriers": [{"id": "c1", "state": "EscortTravel", "hull": 0.9, "bots": 40, "eta_s": None}],
              "ui": {"paused": False, "menu_open": False, "focused": True, "chat_typing": False}},
    "ev.hull": {"band": 25, "dir": "down", "hull": 0.24},
    "ev.shield": {"state": "down"},
    "ev.reflex": {"what": "bots", "by": "carrier", "carrier": "c1", "left": 12, "hull": 0.4},
    "ev.low_stock": {"what": "batts", "left": 1},
    "ev.target": {"obj": None},
    "ev.kill": {"victim": "Bandit", "cls": "fighter", "faction": "test_faction", "by": "wing:w1"},
    "ev.hostiles": {"count": 0, "capital": False, "faction": None},
    "ev.hit": {"attacker": None, "dmg": 0.12},
    "ev.dock": {"base": "test_base"},
    "ev.undock": {"base": "test_base"},
    "ev.system": {"system": "test_system", "from": None, "via": "gate"},
    "ev.lane": {"state": "disrupted"},
    "ev.cruise": {"state": "enter"},
    "ev.wing": {"wing": "w1", "what": "down"},
    "ev.carrier": {"carrier": "c1", "state_from": "Away", "state_to": "AmbushWaiting", "detail": "ambush"},
    "ev.death": {"save": None},
    "ev.load": {"save": "slot1", "char": "Test Pilot"},
    "ev.save": {"save": "slot1"},
    "ev.pause": {"paused": True},
    "ptt": {"down": True},
    "ack": {"id": "c-1", "ok": True, "applied": dict(POLICY)},
    "policy.set": {"id": "c-2", "scope": "carrier", "carrier": "c1", "bots_reserve": 5,
                   "release_reserve_when": "capital_hostile_present"},
    "act": {"id": "c-3", "do": "use_batts"},
    "wing.formation": {"id": "c-4", "form": "escort_carrier"},
    "wing.focus": {"id": "c-5", "target": "id:40213"},
    "wing.order": {"id": "c-6", "order": "guard_carrier", "wing": "all"},
    "wing.policy": {"id": "c-7", "retreat_hull_below": 0.3},
    "say": {"id": "c-8", "speaker": "wing:w1", "text": "On your six.", "prio": 0, "subtitle": True},
}


def env(t: str, **payload) -> dict:
    msg = {"v": 1, "t": t, "seq": 1, **payload}
    if protocol.MESSAGES.get(t) and protocol.MESSAGES[t].direction != protocol.S2G:
        msg["gt"] = 1000
    return msg


def spec_types() -> set[str]:
    text = SPEC.read_text(encoding="utf-8")
    return set(re.findall(r"^#### `([a-z][a-z0-9_.]*)`\s*$", text, flags=re.MULTILINE))


def test_spec_and_code_list_the_same_types():
    assert spec_types() == set(protocol.MESSAGES)


def test_every_type_has_a_valid_sample():
    assert set(SAMPLES) == set(protocol.MESSAGES)
    for t, payload in SAMPLES.items():
        assert validate(env(t, **payload)) == [], t


def test_top_level_id_is_reserved_for_command_ids():
    for t, m in protocol.MESSAGES.items():
        if m.kind != protocol.ACK:
            assert "id" not in m.fields, t


def test_spec_names_required_constants():
    text = SPEC.read_text(encoding="utf-8")
    for needle in ("127.0.0.1", "29170", "65 536", "VK_DECIMAL = 110", "0.05", "0.95",
                   "10 commands per second", "2 policy changes per second", "3 consecutive pings"):
        assert needle in text, needle
    assert protocol.MAX_LINE_BYTES == 65536 and protocol.DEFAULT_PORT == 29170
    assert protocol.LOOPBACK_HOST == "127.0.0.1"
    assert (protocol.CLAMP_BELOW_MIN, protocol.CLAMP_BELOW_MAX) == (0.05, 0.95)
    assert (protocol.RATE_LIMIT_COMMANDS_PER_S, protocol.RATE_LIMIT_POLICY_PER_S) == (10, 2)
    assert protocol.HEARTBEAT_S == 2.0 and protocol.MISSED_PONGS_LIMIT == 3


def test_carrier_states_match_conventions():
    conv = (REPO_DIR / "docs" / "plan" / "CONVENTIONS.md").read_text(encoding="utf-8")
    line = next(l for l in conv.splitlines() if l.startswith("**States:**"))
    names = re.findall(r"([A-Z][A-Za-z]+)", line.split(":", 1)[1])
    assert tuple(names) == protocol.CARRIER_STATES


@pytest.mark.parametrize("t,payload,needle", [
    ("policy.set", {"id": "c-1", "scope": "player", "bogus": 1}, "unknown field"),
    ("policy.set", {"id": "c-1", "scope": "player"}, "no policy field"),
    ("policy.set", {"scope": "player", "auto_bots": True}, "id: missing"),
    ("policy.set", {"id": "c-1", "scope": "fleet", "auto_bots": True}, "scope"),
    ("policy.set", {"id": "c-1", "scope": "player", "release_reserve_when": "hull_critical"}, "release_reserve_when"),
    ("policy.set", {"id": "c-1", "scope": "player", "bots_reserve": 1.5}, "expected int"),
    ("ev.hull", {"band": 33, "dir": "down"}, "band"),
    ("ev.hull", {"band": 25, "dir": "down", "hull": 1.5}, "hull"),
    ("ev.hit", {"dmg": 12}, "dmg"),
    ("ev.target", {"name": "x"}, "obj: missing"),
    ("ev.kill", {"victim": "x", "by": "enemy"}, "by"),
    ("ptt", {"down": 1}, "expected bool"),
    ("ptt", {}, "down: missing"),
    ("ack", {"id": "c-1", "ok": False}, "err: missing"),
    ("ack", {"id": "c-1", "ok": False, "err": "nope"}, "err"),
    ("ack", {"id": "bad id with spaces", "ok": True}, "id"),
    ("say", {"id": "c-1", "speaker": "narrator", "text": "x"}, "speaker"),
    ("say", {"id": "c-1", "speaker": "copilot", "text": "x" * 501}, "longer than"),
    ("say", {"id": "c-1", "speaker": "copilot", "text": "x", "prio": 4}, "prio"),
    ("state", {"ship": None}, "rate: missing"),
    ("state", {"rate": "calm", "ship": {"hull": 0.5, "shield": 0.5}}, "mode: missing"),
    ("state", {"rate": "calm", "carriers": [{"id": "c1", "state": "Sleeping"}]}, "state"),
    ("hello", {"game": "x"}, "dll: missing"),
    ("wing.focus", {"id": "c-1", "target": "id:abc"}, "target"),
    ("wing.policy", {"id": "c-1", "retreat_hull_below": 0.3, "extra": 1}, "unknown field"),
])
def test_invalid_payloads(t, payload, needle):
    errors = validate(env(t, **payload))
    assert errors, (t, payload)
    assert any(needle in e for e in errors), errors


def test_unknown_fields_ok_outside_strict_commands():
    assert validate(env("ev.dock", base="x", future_field={"a": 1})) == []
    assert validate(env("act", id="c-1", do="use_bots", future_field=1)) == []


def test_unknown_type_passes_validation():
    assert validate(env("ev.something_new", x=1)) == []


def test_unsupported_version():
    assert validate({"v": 2, "t": "ping", "seq": 1}) == ["v: unsupported version 2"]


def test_envelope_errors():
    assert protocol.validate_envelope([]) == ["message is not a JSON object"]
    errs = protocol.validate_envelope({"v": "1", "t": "", "seq": -1, "gt": 1.5, "id": ""})
    assert len(errs) == 5
    assert protocol.validate_envelope({"v": True, "t": "x", "seq": 0}) == ["v: missing or not an int"]


def test_encode_decode_roundtrip():
    msg = {"v": 1, "t": "say", "seq": 3, "id": "c-1", "speaker": "copilot", "text": "Ünïcode ok\nnewline", "subtitle": True}
    line = encode(msg)
    assert line.endswith(b"\n") and line.count(b"\n") == 1  # the newline in text is escaped
    assert decode(line) == msg
    assert decode(line.rstrip(b"\n") + b"\r\n") == msg
    assert decode(b"   \n") == {}


@pytest.mark.parametrize("raw,code", [
    (b"nope\n", "json"),
    (b"[1]\n", "not_object"),
    (b"\xff\n", "utf8"),
    (b'{"v":1,"t":"ping","seq":1,"n":NaN}\n', "json"),
    (b'{"v":1,"t":"ping","seq":1,"n":Infinity}\n', "json"),
    (b'{"t":"ping"}\n', "envelope"),
    (b"x" * (protocol.MAX_LINE_BYTES + 1), "oversize"),
])
def test_decode_errors(raw, code):
    with pytest.raises(ProtocolError) as exc:
        decode(raw)
    assert exc.value.code == code


def test_encode_refuses_oversize_and_nan():
    with pytest.raises(ProtocolError):
        encode({"v": 1, "t": "say", "seq": 1, "text": "x" * protocol.MAX_LINE_BYTES})
    with pytest.raises(ValueError):
        encode({"v": 1, "t": "x", "seq": 1, "n": float("nan")})


def test_encoded_line_at_exact_limit():
    base = {"v": 1, "t": "x", "seq": 1, "pad": ""}
    overhead = len(encode(base))
    msg = dict(base, pad="p" * (protocol.MAX_LINE_BYTES - overhead))
    assert len(encode(msg)) == protocol.MAX_LINE_BYTES


@pytest.mark.parametrize("value,vk", [("numpad_period", 110), ("numpad_minus", 109), ("vk:5", 5),
                                      ("0x6E", 110), (110, 110), ("NUMPAD_PERIOD", 110)])
def test_ptt_vk(value, vk):
    assert protocol.ptt_vk(value) == vk


@pytest.mark.parametrize("value", ["banana", "vk:0", 256, "vk:999"])
def test_ptt_vk_rejects(value):
    with pytest.raises(ValueError):
        protocol.ptt_vk(value)


def test_preview_is_safe():
    p = protocol.preview(b"\x00\x1b[31mred\xff" + b"a" * 500)
    assert "\x1b" not in p and p.endswith("...") and len(p) < 200
    json.dumps(p)
