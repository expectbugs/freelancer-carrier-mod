# W4-BRAIN: The copilot and crew LLM brain (Claude CLI on Adam's subscription)

- **Type:** impl
- **Wave:** 4 (sub-wave 4a, CONVENTIONS §8)
- **Depends on:** ARCH-3 (plus merged W1-SIDECAR and W2-REFLEX)
- **Unblocks:** M3-PLAYTEST

## Goal

The crew gets a mind. Spoken or typed free-form orders that the deterministic grammar can't parse go to Claude, which turns them into validated policy and wing commands ("save bots for the cruiser", "keep two on the carrier and the rest with me"). Claude also gives the copilot and each wingman a personality, with timely banter and memory across sessions.

Claude never sits in the reflex loop. When it is slow or unavailable, the game and the grammar path work exactly as before.

## Requirements

- **REQ-W4-BRAIN-1 (D-11.2).** The LLM runs through **Claude Code CLI on Adam's subscription**: `/home/user/.local/bin/claude`, model **`claude-opus-5-5`**, **`--effort low`**. No API keys and no Anthropic SDK calls.
- **REQ-W4-BRAIN-2 (D-11.2, AUTONOMY §2, CONVENTIONS §13).** Hard isolation (the brain sandbox). Every CLI session is started with:
  - no tools: `--tools ""`, **plus** `--disallowedTools 'mcp__*'`;
  - no MCP or connectors: `--strict-mcp-config` with no `--mcp-config`;
  - no settings or hooks discovery: `--setting-sources ""` (or `--restricted`, whichever the installed CLI verifies);
  - `--no-session-persistence`;
  - **cwd = `/home/user/freelancer/carrier-brain-cwd`**: an empty directory **outside the repo**, so no project `CLAUDE.md` is discovered. Create it if missing; refuse to start if it isn't empty.
  - the environment is an **allowlist**: `HOME`, `PATH`, `LANG`, `USER`, `XDG_RUNTIME_DIR`, plus only the variables the CLI needs for subscription auth (verify), and `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`. Everything else is dropped (no denylist scrub; R6 §1.5, §5.1).

  At each session start, parse the stream-json `system/init` message and **assert the tool list and MCP server list are empty**; refuse to use the session otherwise. Verify every flag against `claude --help` of the installed version (2.1.302) before relying on it; record the facts.

  The only outbound traffic allowed is the CLI's own connection to Anthropic. No other network.
- **REQ-W4-BRAIN-3.** Persistent session pattern.
  - Keep warm stream-json sessions: `--print --input-format stream-json --output-format stream-json --verbose`.
  - **Recycle** after N requests or M KB of context (start from rt-zomboid's values: 150 requests / 500 KB).
  - One session per active speaker role, or one session with per-turn speaker context. Choose by measured latency and quality; record the decision.
  - The pattern comes from `/home/user/rt-zomboid/daemon/claude_session.py`. **Read-only reference:** reimplement in `sidecar/brain/`, never import or copy aria or rt-zomboid modules wholesale.
- **REQ-W4-BRAIN-4.** Structured output.
  - Every LLM turn returns JSON matching `{"say": str|null (≤30 words), "speaker": "copilot"|"wing:<id>", "commands": [ … only ops from ipc.md v2 … ], "remember": str|null}` (R6 §5.4 step 2).
  - Use the CLI's JSON-schema option if available (`--json-schema`; verify). Else validate it in the sidecar, with one repair retry.
  - The sidecar re-validates against the schema, then the DLL validates and clamps again.
- **REQ-W4-BRAIN-5.** Routing.
  - The W1-SIDECAR grammar fast path handles known intents first, with no LLM.
  - The brain handles only non-matching utterances, banter and conversation.
  - Every LLM request carries the snapshot `seq` and game state.
  - **Staleness guard:** discard results older than 8 s, or produced after `mode`/`system` changed (R6 §5.4 step 3). A late answer is worse than none.
- **REQ-W4-BRAIN-6.** Banter scheduler.
  - Event-driven: kill, near-death survived, system entered, dock, carrier events, ambush, wing losses, escalation news.
  - A global cooldown of ≥ 45 s between unsolicited lines.
  - Nothing unsolicited while hostiles are present unless priority ≥ 2.
  - Suppressed while paused, unfocused (configurable), or while push-to-talk is held.
  - Optional pre-generation of likely lines on undock, so they play instantly.
- **REQ-W4-BRAIN-7.** Personas.
  - `sidecar/personas.yaml`: the copilot plus templates for crew and hired pilots, generated from the pilot's faction, skill tier and name (from roster snapshots).
  - Lore-consistent, original names (no campaign NPCs). Short lines.
  - Each persona maps to a Kokoro voice and speed (W1-SIDECAR TTS), so distinct pilots get distinct voices.
- **REQ-W4-BRAIN-8.** Memory (R6 §6) in a sidecar-owned SQLite DB. The path is configurable: the default in dev and lanes is `$FLMOD_LOCAL/sidecar-data/copilot.db`; `prefix-carrier` uses the path W5-SHIP sets, outside the repo and the Wine prefix. Tests always use a temp file.
  - Store turns, events, memories (with salience), and affinity per crew member.
  - Context per call: persona + top-K memories + last N turns + a state digest.
  - Session summaries on dock/undock and every ~20 min.
  - **Save-lineage semantics** (decision, recorded): every memory is tagged with the save identity and mod game time. When a save older than the memory is loaded, memories "after" it are marked `unlived`: excluded from prompts, kept in the DB. Loading forward again re-enables them.
  - Deaths and reloads are *not* turned into meta-jokes by default; a persona flag can allow it.
- **REQ-W4-BRAIN-9.** Degradation.
  - CLI missing, a quota/limit error, a timeout (default 12 s), or a malformed reply means: fall back to the grammar plus canned lines, mark the brain `degraded`, and retry with backoff (1, 2, 5, then 15 min).
  - Never block the IPC loop. Never crash the sidecar.
  - Emit `ipc` status `brain=ok|degraded` so the DLL can show a subtle indicator.
- **REQ-W4-BRAIN-10.** Safety.
  - Never `import` aria, aria2 or G2CC modules.
  - No phone push.
  - Strip any `<!--ACTION::` or other markup from LLM text before TTS (R6 §1.4).
  - Never put file paths, secrets or environment details in prompts.
- **REQ-W4-BRAIN-11.** Instrumentation: per-request latency (time to first token, total), recycle events and degradation events, logged to `$FLMOD_LOCAL/sidecar-logs/` (configurable; never committed) and exposed via `ipc.status`.
- **REQ-W4-BRAIN-12** (CONVENTIONS §4, `brain.*`): devbridge verbs `brain.context` (print the latest `brain.context` IPC payload the DLL sent) and `brain.say <speaker> <text>` (inject a line for subtitle and TTS tests). They are implemented in a thin DLL-side adapter `src/game/brain/`, owned here, on top of W2-REFLEX's IPC client service. ARCH-3 records this path in OWNERSHIP.md.
- **REQ-W4-BRAIN-13** (CONVENTIONS §13): **test profile.** Under `--profile test` the brain uses a **fake LLM** (a deterministic responder that replays recorded stream-json) and the sidecar uses a null audio sink. Lanes, soaks and milestones always run the test profile; only M3's single live-brain smoke step uses the real CLI.

## Context pack (read before writing code)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §4, §8, §13)
- `docs/plan/DESIGN.md` §11
- `docs/plan/AUTONOMY.md` §2
- `docs/plan/TESTING.md` §M3 step 7, §Metrics (copilot latency)
- `state/ENGINE_FACTS.md`
- `docs/spec/ipc.md` (v2), `docs/spec/wave4-contracts.md`
- Merged `sidecar/` (W1-SIDECAR, P0-SIDECAR): grammar, TTS, STT, playback, memory store skeleton
- `local/research/R6-copilot-sidecar.md`: §0, §1.4 (safety), §1.5 (CLI patterns), §3, §5, §6, §7
- Reference (read-only): `/home/user/rt-zomboid/daemon/claude_session.py`, `memory_store.py`; `/home/user/aria/aria_api.py` (`_run_opus_cli`). Patterns only.
- `claude --help` output of the installed CLI

## Ownership

- **Owns:** `sidecar/brain/`, `sidecar/personas.yaml`, `sidecar/tests/brain/`, `src/game/brain/` (thin devbridge adapter only)
- **Reads:** the rest of `sidecar/`, docs, contracts
- **Must not touch:** the rest of the DLL side (`src/` except `src/game/brain/`), the grammar and TTS internals (propose changes via report), and other projects

## Contract

- **Consumes:** IPC events and snapshots (ipc.md v2), the grammar fallthrough hook, the TTS speak API, and memory store primitives.
- **Provides:** brain service, schema-validated command emission, banter, persona registry.

## Tasks

1. Verify the CLI flags; write `sidecar/brain/CLI_FACTS.md` (VERIFIED with command output).
2. Session manager: spawn, the init assertion, request/response over stream-json, recycle, timeouts, backoff.
3. Prompt assembly (persona, memory, state digest) and schema validation.
4. Router integration with the grammar fast path; staleness guard.
5. Banter scheduler and personas.
6. Memory with save lineage.
7. Tests: unit tests with a **fake CLI** (a stub executable that replays recorded stream-json), plus one real smoke test.

## Acceptance (all automated)

- **pytest** (mock `subprocess.Popen` at its defining module, `subprocess.Popen`):
  - `test_init_asserts_no_tools_no_mcp`
  - `test_schema_validation_and_repair`
  - `test_staleness_discard`
  - `test_recycle_after_limits`
  - `test_degrade_and_backoff`
  - `test_banter_cooldown_and_combat_suppression`
  - `test_memory_save_lineage`
  - `test_markup_stripped_before_tts`
  - `test_router_grammar_first`
- **Fake-game NDJSON replay:** recorded sessions for "save bots for the cruiser", "two on the carrier, rest with me", and an unknown request. Commands emitted are valid and clamped.
- **Real smoke** (one run, tagged `smoke-real-llm`, run in M3): the real CLI with `claude-opus-5-5` at low effort.
  - The init tool list is empty.
  - One free-form order produces valid commands.
  - One banter line is ≤ 30 words.
  - Latency is recorded.
  - It doesn't fail the build if a usage limit prevents it: mark SKIP with the reason and retry later in M3.
- **Metrics:** free-form reply to first audio ≤ 6 s target (TESTING §Metrics). If it's missed, record and keep (tunable: Haiku option documented in BUILD_REPORT as an Adam tunable; default stays Opus 5.5 low per D-11.2).

## Engine facts to rely on / verify

- Not engine-related. CLI facts go in `sidecar/brain/CLI_FACTS.md`; summarize them for `ENGINE_FACTS.md` under "Toolchain/CLI".

## Pitfalls

- `--bare` doesn't work with subscription OAuth (R6 §5.1); don't use it.
- `--strict-mcp-config` exclusion of claude.ai connectors was UNVERIFIED (R6 risk 6). The init assertion is the guard.
- Prompt caching doesn't apply via the CLI the same way as the API. Keep the prompt prefix stable anyway.

## Fallbacks and degrade path

1. If persistent stream-json sessions misbehave, use one-shot `--print` per request (slower).
2. If the CLI is unusable entirely, ship the brain disabled (grammar + canned lines + scripted banter), documented as DEGRADED.

## Report

Standard. Include the latency table and the CLI_FACTS summary.

## Gate-time addendum

(orchestrator)
