# Freelancer Carrier & Endgame Mod

A single-player endgame mod for **Freelancer (2003)**, built on **Freelancer: HD Edition**. It adds:

- mobile, player-owned **carriers**: dockable bases you buy at carrier yards, upgrade, crew and take with you;
- **ambushes you earn**, drawn from the game's own patrol and encounter data;
- **AI wingmen and crew**, with an optional **voice copilot**;
- a player-driven **faction-escalation** endgame.

It stays vanilla-faithful: same map, same factions, same campaign. See [`docs/plan/DESIGN.md`](docs/plan/DESIGN.md) for the full design.

## Status

**Under autonomous construction.** The mod is being built by an orchestrated set of AI coding agents, following the plan in [`docs/plan/BUILD_PLAN.md`](docs/plan/BUILD_PLAN.md). Progress is tracked in [`state/BUILD_STATE.md`](state/BUILD_STATE.md). Nothing here is playable yet.

## Requirements

- **You must own Freelancer.** This repository does not include, and will never include, the game.
- **Freelancer: HD Edition v0.7.1**, installed on Windows, or on Linux under Wine.
- To build from source: an MSVC-ABI toolchain (clang-cl + lld-link with the MSVC CRT/Windows SDK, or Visual Studio), CMake and Python 3.11+. Build instructions arrive with the toolchain package.

## No game files

**This repo contains no game files.**

- Every data change (new ships, bases, loadouts, text) is **generated locally from your own install** at deploy time, from the YAML definitions and generators in this repo.
- HD Edition's files are never overwritten wholesale; changes are additive.
- A public-safety check (`tools/check_public.py`) runs on every commit, merge and push, and in GitHub Actions. It rejects game files and extracts (by name and by content), decompiled code, other mods' content, secrets and personal details.

To enable the hooks in a clone:

```bash
git config core.hooksPath .githooks
python3 -I tools/check_public.py --explain   # list the rules
```

## Repository layout

| Path | Contents |
|---|---|
| `docs/plan/` | the build plan, design, testing strategy and per-package specs |
| `src/` | the mod DLL (C++, MSVC ABI) |
| `sidecar/` | the copilot sidecar (Python; loopback only) |
| `data/`, `gen/` | YAML definitions and the generators that turn them into game data |
| `harness/` | the test harness; `harness/ci.sh` is the single CI entry point |
| `tools/` | developer tools, including the public-safety checker |

Paths in the docs such as `/home/user/freelancer/...` are examples from the build machine.

## License

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).

Freelancer is a trademark of its respective owners. This is an unofficial fan project, not affiliated with or endorsed by them.
