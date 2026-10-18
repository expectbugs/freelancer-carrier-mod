# <ID>: <Title>

- **Type:** impl | spike | arch | design | test
- **Wave:** …
- **Depends on:** … → **Unblocks:** …

## Goal

One paragraph: what exists when this is done, and why it matters to the player.

## Requirements

Numbered `REQ-<ID>-n`, each citing `DESIGN.md` `D-x.y` or a BUILD_PLAN section. Quote the design text where it matters, so the agent never needs to interpret a paraphrase.

## Context pack (read before writing code)

Absolute paths plus the sections to read. Always include:

- `CLAUDE.md`, `docs/plan/DESIGN.md` (the relevant §), `docs/plan/TESTING.md` (the relevant §), `state/ENGINE_FACTS.md`
- the frozen contracts it consumes or provides
- the research sections with the exact facts it relies on (`local/research/R*.md` §…)
- reference code to study (`/home/user/freelancer/refs/...` with file paths). Study it; don't copy AGPL or unlicensed code verbatim unless the license allows and it is attributed.

## Ownership

- **Owns** (may create or modify): …
- **Reads** (read-only): …
- **Must not touch:** everything else, including frozen `src/contracts/` (propose changes in the report instead).

## Contract

- **Consumes:** interfaces and events used.
- **Provides:** interfaces, events, data files, CLI tools.
- ARCH packages fill in the exact headers; this section names them.

## Tasks

An ordered list. Each task is small enough to verify on its own.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:** named test cases and what they assert.
- **Build checks:** `harness/ci.sh` subset, import check, data validator.
- **In-game scenarios:** `harness/scenarios/<name>.yaml`. Give the steps (fixture save, devbridge commands), the expected `HARNESS` lines, the screenshots to capture, and any vision-check rubric.
- **Metrics:** targets from TESTING.md, where applicable.
- **Negative tests:** failure injection, bad inputs, save/load at awkward moments.

## Engine facts to rely on / verify

Bullets referencing `ENGINE_FACTS.md` IDs, or research facts still UNVERIFIED that this package must confirm.

## Pitfalls

Known crash causes and gotchas relevant here (from R4 §A1, R2, R5).

## Fallbacks and degrade path

Pre-decided alternatives, in order. What "degraded" looks like if all fail.

## Report (the agent's final message)

Summary; files changed; tests run with results (VERIFIED, with paths to logs and screenshots); decisions taken; facts learned (for `ENGINE_FACTS.md`); open questions; known issues; branch name and final commit SHA.

## Gate-time addendum

The orchestrator fills this in when writing the brief: chosen track, base plan, contract paths, engine-fact IDs, lane assignment, attempt number, prior-attempt notes.
