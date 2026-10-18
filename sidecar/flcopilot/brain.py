"""The LLM hook. P0 ships only the deterministic fake responder for the test profile.

The real brain (Claude Code CLI, no tools, no MCP, empty cwd; CONVENTIONS §13) arrives in
W4-BRAIN and implements the same :class:`Brain` interface. ``respond`` is synchronous and the
voice pipeline always calls it through ``asyncio.to_thread``, so a slow brain never blocks the
event loop (pings, acks, other messages).

The CONVENTIONS §13 sandbox is fixed here as data for W4-BRAIN: the CLI flags, the working
directory, the environment allowlist, and the check of the stream-json init message (zero tools,
zero MCP servers). Nothing in this module starts a process or opens a network connection.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# ---- CONVENTIONS §13 brain sandbox (for W4-BRAIN) -------------------------------------------
#: Empty directory outside the repo, so no project CLAUDE.md or settings are picked up.
BRAIN_CWD = "/home/user/freelancer/carrier-brain-cwd"
BRAIN_MODEL = "claude-opus-5-5"  # DESIGN D-11.2
BRAIN_EFFORT = "low"
#: Flags verified present in `claude --help` (2026-10-18). `--tools ""` disables every built-in
#: tool; `--strict-mcp-config` without `--mcp-config` loads no MCP server; `--disallowedTools
#: mcp__*` is belt and braces for connectors; `--setting-sources ""` ignores user/project settings.
BRAIN_CLI_FLAGS = (
    "--print", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
    "--model", BRAIN_MODEL, "--effort", BRAIN_EFFORT,
    "--tools", "",
    "--strict-mcp-config",
    "--disallowedTools", "mcp__*",
    "--setting-sources", "",
    "--no-session-persistence",
)
#: The only environment passed to the CLI. Subscription auth lives under $HOME/.claude.
BRAIN_ENV_ALLOWLIST = ("HOME", "PATH", "LANG", "USER", "XDG_RUNTIME_DIR", "CLAUDE_CONFIG_DIR")
BRAIN_ENV_FORCED = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


def brain_env(environ: dict | None = None) -> dict:
    """The allowlisted environment for the brain CLI (everything else, e.g. CLAUDECODE, is dropped)."""
    environ = os.environ if environ is None else environ
    env = {k: environ[k] for k in BRAIN_ENV_ALLOWLIST if environ.get(k)}
    env.update(BRAIN_ENV_FORCED)
    return env


def brain_command(cli_path: str, system_prompt: str | None = None) -> list[str]:
    """argv for the sandboxed brain CLI. W4-BRAIN runs it with cwd=BRAIN_CWD, env=brain_env()."""
    argv = [cli_path, *BRAIN_CLI_FLAGS]
    if system_prompt:
        argv += ["--system-prompt", system_prompt]
    return argv


def check_init_message(msg: dict) -> list[str]:
    """Problems with the CLI's stream-json ``system/init`` message: the sandbox requires zero
    tools and zero MCP servers (CONVENTIONS §13 first-run test). Empty list = sandbox holds.
    The field names follow the CLI's stream-json init message; W4-BRAIN's first live run confirms them."""
    problems = []
    if not isinstance(msg, dict) or msg.get("type") != "system" or msg.get("subtype") != "init":
        return ["not a system/init message"]
    tools = msg.get("tools")
    if not isinstance(tools, list):
        problems.append("init message has no tools list")
    elif tools:
        problems.append(f"{len(tools)} tool(s) available: {sorted(map(str, tools))[:10]}")
    servers = msg.get("mcp_servers")
    if not isinstance(servers, list):
        problems.append("init message has no mcp_servers list")
    elif servers:
        problems.append(f"{len(servers)} MCP server(s) configured")
    return problems


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
