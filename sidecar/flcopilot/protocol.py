"""IPC protocol v1 between the game DLL and the copilot sidecar.

This module is the machine-readable twin of ``docs/spec/ipc.md``. The two must agree;
``tests/test_protocol.py`` cross-checks the message catalog against the spec.

Stdlib only: the server core must import without numpy or audio libraries.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 1
SUPPORTED_VERSIONS = (1,)

#: Loopback only. Never 0.0.0.0, never "localhost" (it can resolve to ::1).
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 29170

#: Max bytes in one line, including the terminating "\n".
MAX_LINE_BYTES = 65536

HEARTBEAT_S = 2.0
MISSED_PONGS_LIMIT = 3

# Directions
G2S = "game->sidecar"
S2G = "sidecar->game"
BOTH = "both"

# Kinds
CONTROL = "control"
STATE = "state"
EVENT = "event"
COMMAND = "command"
ACK = "ack"

# Enumerations shared across messages
CARRIER_STATES = (
    "Stopped", "DockedTravel", "EscortTravel", "Away", "AmbushWaiting", "UnderAttack", "Destroyed",
)
SHIP_CLASSES = (
    "fighter", "freighter", "gunboat", "cruiser", "battleship", "carrier", "transport", "station", "other",
)
SHIP_MODES = ("free", "cruise", "lane", "docked", "dead", "menu")
RATE_TIERS = ("combat", "calm", "docked", "paused")
POLICY_SCOPES = ("player", "carrier")
RELEASE_RESERVE_WHEN = ("never", "capital_hostile_present", "target_is_capital")
ACT_DO = ("use_bots", "use_batts")
WING_FORMATIONS = ("tight", "loose", "line", "escort_carrier")
WING_ORDERS = ("follow", "engage", "hold", "retreat", "guard_carrier", "regroup")
WING_STATES = ("follow", "engage", "retreat", "guard", "docked")
WING_WHAT = ("down", "damaged", "retreating", "rejoined")
BYE_REASONS = ("version", "replaced", "shutdown", "timeout", "protocol")
PTT_CANCEL_REASONS = ("focus_lost", "pause", "menu", "chat", "disconnect")
ACK_ERRORS = (
    "unknown_type", "unknown_field", "bad_value", "rate_limited", "unsupported", "not_now", "internal",
)
FEATURES = ("stt", "tts", "llm", "grammar")

# Clamp bounds the DLL enforces (W2-REFLEX). Documented here so both sides agree.
CLAMP_BELOW_MIN = 0.05
CLAMP_BELOW_MAX = 0.95
CRITICAL_HULL_FLOOR_DEFAULT = 0.25  # the DLL also caps critical_hull at bots_hull_below (ipc.md §5)
RATE_LIMIT_COMMANDS_PER_S = 10
RATE_LIMIT_POLICY_PER_S = 2

PTT_KEYS = {"numpad_period": 110, "numpad_minus": 109}

COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")
SPEAKER_RE = re.compile(r"^(copilot|wing:[A-Za-z0-9_-]{1,32})$")
ACTOR_RE = re.compile(r"^(player|wing:[A-Za-z0-9_-]{1,32}|carrier:[A-Za-z0-9_-]{1,32}|other)$")
FOCUS_RE = re.compile(r"^(player_target|nearest_hostile|capital|id:[0-9]{1,10})$")


class ProtocolError(ValueError):
    """A line or message violates protocol v1. ``code`` is a short machine-readable reason."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class F:
    """One field. ``type`` is int | num | bool | str | obj | list | any."""

    type: str
    required: bool = False
    nullable: bool = False
    enum: tuple | None = None
    min: float | None = None
    max: float | None = None
    maxlen: int | None = None
    pattern: re.Pattern | None = None
    schema: dict | None = None  # for obj
    items: "F | None" = None    # for list
    max_items: int | None = None
    doc: str = ""


@dataclass(frozen=True)
class Msg:
    direction: str
    kind: str
    fields: dict = field(default_factory=dict)
    #: Unknown fields fail validation (commands that must never be half-applied).
    strict: bool = False
    #: Reserved for a later wave; the DLL may answer ``unsupported`` until then.
    reserved_for: str = ""
    doc: str = ""


def _frac(required=False, doc=""):
    return F("num", required=required, min=0.0, max=1.0, doc=doc)


def _count(required=False, doc=""):
    return F("int", required=required, min=0, doc=doc)


def _name(required=False, nullable=False, doc=""):
    return F("str", required=required, nullable=nullable, maxlen=128, doc=doc)


POLICY_FIELDS = {
    "auto_bots": F("bool", doc="reflex may use nanobots"),
    "bots_hull_below": F("num", doc="use nanobots below this hull fraction; DLL clamps to [0.05, 0.95]"),
    "bots_reserve": F("int", doc="nanobots kept back; DLL clamps to [0, max stock]"),
    "critical_hull": F("num", doc="hard floor; DLL clamps to [floor, 0.95]; may be raised, never lowered below the INI floor"),
    "release_reserve_when": F("str", enum=RELEASE_RESERVE_WHEN, doc="when the reserve may be spent"),
    "auto_batts": F("bool", doc="reflex may use shield batteries"),
    "batts_shield_below": F("num", doc="use batteries below this shield fraction; DLL clamps to [0.05, 0.95]"),
    "batts_reserve": F("int", doc="batteries kept back; DLL clamps to [0, max stock]"),
}
POLICY_SCHEMA = POLICY_FIELDS  # an object whose every field is optional

SHIP_SCHEMA = {
    "hull": _frac(True), "shield": _frac(True), "shield_up": F("bool"),
    "bots": _count(), "batts": _count(), "bots_max": _count(), "batts_max": _count(),
    "speed": F("num", min=0.0), "mode": F("str", enum=SHIP_MODES, required=True),
    "system": _name(nullable=True), "base": _name(nullable=True), "near": _name(nullable=True),
}
TARGET_SCHEMA = {
    "obj": F("int", required=True, min=0, doc="space object id (same name as ev.target.obj)"),
    "name": _name(), "faction": _name(nullable=True),
    "cls": F("str", enum=SHIP_CLASSES), "hull": _frac(), "shield": _frac(),
    "dist": F("num", min=0.0), "hostile": F("bool"),
}
THREAT_SCHEMA = {
    "hostiles": _count(True), "capital_hostile": F("bool"), "incoming_missiles": F("int", min=0, nullable=True),
}
WING_ENTRY_SCHEMA = {
    "id": _name(True), "name": _name(), "hull": _frac(), "shield": _frac(),
    "state": F("str", enum=WING_STATES), "dist": F("num", min=0.0),
}
CARRIER_ENTRY_SCHEMA = {
    "id": _name(True), "name": _name(), "state": F("str", enum=CARRIER_STATES, required=True),
    "hull": _frac(), "bots": _count(), "eta_s": F("num", min=0.0, nullable=True), "system": _name(nullable=True),
}
UI_SCHEMA = {
    "paused": F("bool"), "menu_open": F("bool"), "focused": F("bool"), "chat_typing": F("bool"),
}

MESSAGES: dict[str, Msg] = {
    # ---- control -------------------------------------------------------------------------
    "hello": Msg(G2S, CONTROL, {
        "dll": _name(True, doc="DLL version"),
        "game": _name(True, doc="game build string"),
        "char": _name(nullable=True, doc="character name; null at the main menu"),
        "save": _name(nullable=True, doc="save file id; null if none loaded"),
        "policy": F("obj", schema={"player": F("obj", schema=POLICY_SCHEMA),
                                   "carrier": F("obj", schema=POLICY_SCHEMA)},
                    doc="the DLL's current (applied) policy per scope"),
        "features": F("list", items=_name(), max_items=32, doc="DLL capabilities, e.g. reflex, wing, carrier"),
        "ptt_vk": F("int", min=1, max=255, doc="virtual-key code the DLL polls for push-to-talk"),
    }, doc="first message of every connection"),
    "welcome": Msg(S2G, CONTROL, {
        "sidecar": _name(True, doc="sidecar version"),
        "features": F("list", required=True, items=F("str", enum=FEATURES), max_items=16),
        "heartbeat_ms": F("int", min=10, max=60000),
        "profile": F("str", enum=("live", "test")),
        "ptt_vk": F("int", min=1, max=255, doc="the VK the sidecar's ptt_key maps to (the DLL logs a mismatch)"),
    }, doc="reply to a hello with a supported version"),
    "bye": Msg(BOTH, CONTROL, {
        "reason": F("str", required=True, enum=BYE_REASONS),
        "detail": F("str", maxlen=256),
        "supported": F("list", items=F("int", min=1), max_items=8),
    }, doc="the sender closes the connection right after this"),
    "ping": Msg(BOTH, CONTROL, {"n": F("int", min=0)}),
    "pong": Msg(BOTH, CONTROL, {"n": F("int", min=0)}),
    # ---- game -> sidecar: state ----------------------------------------------------------
    "state": Msg(G2S, STATE, {
        "rate": F("str", enum=RATE_TIERS, required=True),
        "ship": F("obj", schema=SHIP_SCHEMA, nullable=True),
        "target": F("obj", schema=TARGET_SCHEMA, nullable=True),
        "threat": F("obj", schema=THREAT_SCHEMA),
        "wing": F("list", items=F("obj", schema=WING_ENTRY_SCHEMA), max_items=64),
        "carriers": F("list", items=F("obj", schema=CARRIER_ENTRY_SCHEMA), max_items=64),
        "ui": F("obj", schema=UI_SCHEMA),
    }, doc="coalesced full snapshot"),
    # ---- game -> sidecar: events ---------------------------------------------------------
    "ev.hull": Msg(G2S, EVENT, {
        "band": F("int", required=True, enum=(75, 50, 25, 10)),
        "dir": F("str", required=True, enum=("down", "up")),
        "hull": _frac(),
    }),
    "ev.shield": Msg(G2S, EVENT, {"state": F("str", required=True, enum=("down", "up"))}),
    "ev.reflex": Msg(G2S, EVENT, {
        "what": F("str", required=True, enum=("bots", "batts")),
        "by": F("str", required=True, enum=("player", "carrier")),
        "carrier": _name(),
        "left": _count(True),
        "hull": _frac(),
    }),
    "ev.low_stock": Msg(G2S, EVENT, {
        "what": F("str", required=True, enum=("bots", "batts")),
        "by": F("str", enum=("player", "carrier")),
        "carrier": _name(),
        "left": _count(True),
    }),
    "ev.target": Msg(G2S, EVENT, {
        "obj": F("int", required=True, nullable=True, min=0, doc="space object id; null = target cleared"),
        "name": _name(), "cls": F("str", enum=SHIP_CLASSES), "faction": _name(nullable=True),
        "hostile": F("bool"),
    }),
    "ev.kill": Msg(G2S, EVENT, {
        "victim": _name(True), "cls": F("str", enum=SHIP_CLASSES), "faction": _name(nullable=True),
        "by": F("str", required=True, pattern=ACTOR_RE),
    }),
    "ev.hostiles": Msg(G2S, EVENT, {
        "count": _count(True), "capital": F("bool", required=True), "faction": _name(nullable=True),
    }),
    "ev.hit": Msg(G2S, EVENT, {"attacker": _name(nullable=True), "dmg": _frac(True)}),
    "ev.dock": Msg(G2S, EVENT, {"base": _name(True)}),
    "ev.undock": Msg(G2S, EVENT, {"base": _name(True)}),
    "ev.system": Msg(G2S, EVENT, {
        "system": _name(True), "from": _name(nullable=True),
        "via": F("str", required=True, enum=("gate", "hole", "load", "other")),
    }),
    "ev.lane": Msg(G2S, EVENT, {"state": F("str", required=True, enum=("enter", "exit", "disrupted"))}),
    "ev.cruise": Msg(G2S, EVENT, {"state": F("str", required=True, enum=("enter", "exit", "disrupted"))}),
    "ev.wing": Msg(G2S, EVENT, {
        "wing": _name(True), "what": F("str", required=True, enum=WING_WHAT),
    }, reserved_for="W4-WINGMEN"),
    "ev.carrier": Msg(G2S, EVENT, {
        "carrier": _name(True),
        "state_from": F("str", required=True, enum=CARRIER_STATES),
        "state_to": F("str", required=True, enum=CARRIER_STATES),
        "detail": F("str", maxlen=256),
    }, reserved_for="W2-CARRIER-GAME"),
    "ev.death": Msg(G2S, EVENT, {"save": _name(nullable=True)}),
    "ev.menu": Msg(G2S, EVENT, {}, doc="returned to the main menu (no ship, no game loaded)"),
    "ev.load": Msg(G2S, EVENT, {"save": _name(True), "char": _name(nullable=True)}),
    "ev.save": Msg(G2S, EVENT, {"save": _name(True)}),
    "ev.pause": Msg(G2S, EVENT, {"on": F("bool", required=True, doc="true = the game tick stopped")}),
    "ptt": Msg(G2S, EVENT, {
        "down": F("bool", required=True),
        "reason": F("str", enum=PTT_CANCEL_REASONS,
                    doc="only with down=false: polling stopped with the key held; the utterance is cancelled"),
    }),
    # ---- game -> sidecar: acks -----------------------------------------------------------
    "ack": Msg(G2S, ACK, {
        "id": F("str", required=True, pattern=COMMAND_ID_RE),
        "ok": F("bool", required=True),
        "applied": F("obj"),
        "err": F("str", enum=ACK_ERRORS),
        "detail": F("str", maxlen=256),
    }),
    # ---- sidecar -> game: commands (all carry "id") --------------------------------------
    "policy.set": Msg(S2G, COMMAND, {
        "scope": F("str", required=True, enum=POLICY_SCOPES),
        "carrier": _name(doc="carrier id for scope=carrier; absent = the default carrier policy"),
        **POLICY_FIELDS,
    }, strict=True),
    "act": Msg(S2G, COMMAND, {
        "do": F("str", required=True, enum=ACT_DO),
        "scope": F("str", enum=POLICY_SCOPES),
        "carrier": _name(),
    }),
    "wing.formation": Msg(S2G, COMMAND, {"form": F("str", required=True, enum=WING_FORMATIONS)},
                          reserved_for="W4-WINGMEN"),
    "wing.focus": Msg(S2G, COMMAND, {"target": F("str", required=True, pattern=FOCUS_RE)},
                      reserved_for="W4-WINGMEN"),
    "wing.order": Msg(S2G, COMMAND, {
        "order": F("str", required=True, enum=WING_ORDERS), "wing": _name(doc='wing id or "all" (default)'),
    }, reserved_for="W4-WINGMEN"),
    "wing.policy": Msg(S2G, COMMAND, {"retreat_hull_below": F("num", required=True)}, strict=True,
                       reserved_for="W4-WINGMEN"),
    "say": Msg(S2G, COMMAND, {
        "speaker": F("str", required=True, pattern=SPEAKER_RE),
        "text": F("str", required=True, maxlen=500),
        "prio": F("int", min=0, max=3),
        "subtitle": F("bool"),
    }),
}

#: Top-level "id" is reserved for command ids (commands and acks); payloads never use it.
ENVELOPE_FIELDS = ("v", "t", "seq", "gt", "id")
COMMAND_TYPES = tuple(t for t, m in MESSAGES.items() if m.kind == COMMAND)
EVENT_TYPES = tuple(t for t, m in MESSAGES.items() if m.kind == EVENT)


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x: Any) -> bool:
    return (isinstance(x, (int, float)) and not isinstance(x, bool)) and x == x and x not in (
        float("inf"), float("-inf"))


def _check_value(path: str, spec: F, value: Any, strict: bool, errors: list[str]) -> None:
    if value is None:
        if not spec.nullable:
            errors.append(f"{path}: null not allowed")
        return
    t = spec.type
    if t == "int" and not _is_int(value):
        errors.append(f"{path}: expected int")
        return
    if t == "num" and not _is_num(value):
        errors.append(f"{path}: expected number")
        return
    if t == "bool" and not isinstance(value, bool):
        errors.append(f"{path}: expected bool")
        return
    if t == "str" and not isinstance(value, str):
        errors.append(f"{path}: expected string")
        return
    if t == "obj" and not isinstance(value, dict):
        errors.append(f"{path}: expected object")
        return
    if t == "list" and not isinstance(value, list):
        errors.append(f"{path}: expected list")
        return
    if spec.enum is not None and value not in spec.enum:
        errors.append(f"{path}: {value!r} not in {list(spec.enum)}")
    if spec.min is not None and t in ("int", "num") and value < spec.min:
        errors.append(f"{path}: {value} < {spec.min}")
    if spec.max is not None and t in ("int", "num") and value > spec.max:
        errors.append(f"{path}: {value} > {spec.max}")
    if spec.maxlen is not None and t == "str" and len(value) > spec.maxlen:
        errors.append(f"{path}: longer than {spec.maxlen}")
    if spec.pattern is not None and t == "str" and not spec.pattern.fullmatch(value):
        errors.append(f"{path}: {value!r} does not match {spec.pattern.pattern}")
    if t == "obj" and spec.schema is not None:
        _check_fields(path, spec.schema, value, strict, errors)
    if t == "list":
        if spec.max_items is not None and len(value) > spec.max_items:
            errors.append(f"{path}: more than {spec.max_items} items")
        if spec.items is not None:
            for i, item in enumerate(value):
                _check_value(f"{path}[{i}]", spec.items, item, strict, errors)


def _check_fields(path: str, schema: dict, obj: dict, strict: bool, errors: list[str],
                  skip: tuple = ()) -> None:
    for name, spec in schema.items():
        if name not in obj:
            if spec.required:
                errors.append(f"{path}.{name}: missing" if path else f"{name}: missing")
            continue
        _check_value(f"{path}.{name}" if path else name, spec, obj[name], strict, errors)
    if strict:
        for name in obj:
            if name not in schema and name not in skip:
                errors.append(f"{path}.{name}: unknown field" if path else f"{name}: unknown field")


def validate_envelope(msg: Any) -> list[str]:
    """Errors in the envelope only (v, t, seq, gt, id). Empty list means valid."""
    if not isinstance(msg, dict):
        return ["message is not a JSON object"]
    errors: list[str] = []
    v = msg.get("v")
    if not _is_int(v):
        errors.append("v: missing or not an int")
    t = msg.get("t")
    if not isinstance(t, str) or not t or len(t) > 64:
        errors.append("t: missing or not a non-empty string")
    seq = msg.get("seq")
    if not _is_int(seq) or seq < 0:
        errors.append("seq: missing or not an int >= 0")
    if "gt" in msg and (not _is_int(msg["gt"]) or msg["gt"] < 0):
        errors.append("gt: not an int >= 0")
    if "id" in msg and (not isinstance(msg["id"], str) or not COMMAND_ID_RE.fullmatch(msg["id"])):
        errors.append("id: not a valid command id")
    return errors


def validate(msg: Any) -> list[str]:
    """Full validation: envelope, then payload for known types.

    Unknown ``t`` values pass (extension rule: the receiver ignores them). Unknown fields
    pass, except in strict messages (``policy.set``, ``wing.policy``).
    """
    errors = validate_envelope(msg)
    if errors:
        return errors
    if msg["v"] not in SUPPORTED_VERSIONS:
        return [f"v: unsupported version {msg['v']}"]
    spec = MESSAGES.get(msg["t"])
    if spec is None:
        return []
    if spec.kind == COMMAND and "id" not in msg:
        errors.append("id: missing (commands carry an id)")
    _check_fields("", spec.fields, msg, spec.strict, errors, skip=ENVELOPE_FIELDS)
    if msg["t"] == "policy.set" and not any(k in msg for k in POLICY_FIELDS):
        errors.append("policy.set: no policy field given")
    if msg["t"] in ("policy.set", "act") and "carrier" in msg and msg.get("scope", "player") != "carrier":
        errors.append("carrier: only allowed with scope=carrier")
    if msg["t"] == "ptt" and "reason" in msg and msg.get("down") is not False:
        errors.append("reason: only allowed with down=false")
    if msg["t"] == "ack":
        if msg.get("ok") is False and "err" not in msg:
            errors.append("err: missing (ok=false acks carry an err code)")
    return errors


def encode(msg: dict) -> bytes:
    """One NDJSON line (UTF-8, compact, "\\n"-terminated). Raises ProtocolError if too long."""
    data = json.dumps(msg, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    if len(data) > MAX_LINE_BYTES:
        raise ProtocolError("oversize", f"{len(data)} bytes > {MAX_LINE_BYTES}")
    return data


def decode(line: bytes) -> dict:
    """Parse one line (with or without its terminator) into a message dict.

    Raises ProtocolError(code) with code in: oversize, utf8, json, not_object, envelope.
    Returns {} for an empty line (callers ignore it).
    """
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError("oversize", f"{len(line)} bytes")
    if line.endswith(b"\n"):
        line = line[:-1]
    if line.endswith(b"\r"):
        line = line[:-1]
    if not line.strip():
        return {}
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("utf8", str(exc)) from None
    try:
        obj = json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float,
                         object_pairs_hook=_no_duplicate_keys)
    except (ValueError, RecursionError) as exc:  # RecursionError: absurdly deep nesting
        raise ProtocolError("json", str(exc)[:200]) from None
    if "\\u" in text and _has_lone_surrogate(obj):
        raise ProtocolError("utf8", "lone surrogate escape")
    if not isinstance(obj, dict):
        raise ProtocolError("not_object", type(obj).__name__)
    env = validate_envelope(obj)
    if env:
        raise ProtocolError("envelope", "; ".join(env))
    return obj


def _reject_constant(name: str):
    raise ValueError(f"non-finite number {name} is not allowed")


def _no_duplicate_keys(pairs: list) -> dict:
    """Duplicate keys are invalid (parsers disagree on which one wins)."""
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key[:40]!r}")
        out[key] = value
    return out


def _finite_float(text: str) -> float:
    val = float(text)
    if val in (float("inf"), float("-inf")):
        raise ValueError(f"number {text[:32]} overflows to infinity")
    return val


def _has_lone_surrogate(obj) -> bool:
    """True if any string holds a lone UTF-16 surrogate (from a \\uD8xx escape): it cannot be
    re-encoded as UTF-8. Iterative, so deep nesting cannot overflow the stack."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            try:
                cur.encode("utf-8")
            except UnicodeEncodeError:
                return True
        elif isinstance(cur, dict):
            stack.extend(cur.keys())
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return False


def ptt_vk(name_or_code: str | int) -> int:
    """Map a ``ptt_key`` config value (name, ``vk:<n>`` or int) to a virtual-key code."""
    if isinstance(name_or_code, int) and not isinstance(name_or_code, bool):
        code = name_or_code
    else:
        s = str(name_or_code).strip().lower()
        if s in PTT_KEYS:
            return PTT_KEYS[s]
        if s.startswith("vk:"):
            s = s[3:]
        try:
            code = int(s, 0)
        except ValueError:
            raise ValueError(f"unknown ptt_key {name_or_code!r}; use one of {sorted(PTT_KEYS)} or vk:<code>") from None
    if not 1 <= code <= 255:
        raise ValueError(f"ptt_key code {code} out of range 1..255")
    return code


def preview(line: bytes, limit: int = 120) -> str:
    """A safe, short printable preview of a raw line for logs."""
    text = line[:limit].decode("utf-8", errors="replace")
    text = text.encode("unicode_escape").decode("ascii")
    return text + ("..." if len(line) > limit else "")
