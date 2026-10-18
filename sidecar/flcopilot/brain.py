"""The LLM hook. P0 ships only the deterministic fake responder for the test profile.

The real brain (Claude Code CLI, no tools, no MCP, empty cwd; CONVENTIONS §13) arrives in
W4-BRAIN and implements the same :class:`Brain` interface. Nothing here starts a process
or opens a network connection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Command:
    t: str
    fields: dict


@dataclass
class BrainReply:
    say: str | None = None
    speaker: str = "copilot"
    commands: list[Command] = field(default_factory=list)


class Brain:
    name = "abstract"

    def respond(self, utterance: str, state: dict | None) -> BrainReply:
        raise NotImplementedError


def _ship(state: dict | None) -> dict:
    if isinstance(state, dict) and isinstance(state.get("ship"), dict):
        return state["ship"]
    return {}


class FakeBrain(Brain):
    """Deterministic responder: same utterance + same snapshot -> same reply. No LLM."""

    name = "fake"

    def __init__(self, default_reserve: int = 5):
        self.default_reserve = default_reserve
        self.calls: list[str] = []

    def respond(self, utterance: str, state: dict | None) -> BrainReply:
        self.calls.append(utterance)
        text = re.sub(r"[^a-z ]", " ", (utterance or "").lower())
        words = set(text.split())
        bots = bool(words & {"nanobots", "nanobot", "bots", "bot"}) or "nano bots" in text
        if bots and words & {"save", "keep", "hold", "reserve"}:
            ship = _ship(state)
            n = ship.get("bots")
            reserve = n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else self.default_reserve
            return BrainReply(
                say=f"Copy. Holding {reserve} nanobots for the capital ship.",
                commands=[Command("policy.set", {"scope": "player", "bots_reserve": reserve,
                                                 "release_reserve_when": "capital_hostile_present"})])
        if bots and words & {"use", "heal", "fire"}:
            return BrainReply(say="Using nanobots.", commands=[Command("act", {"do": "use_bots"})])
        return BrainReply(say="Say again?")
