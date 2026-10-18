# Decision log

Append-only. Format:

```
## D<nnn> — <date> — <short title>
- Context:
- Options:
- Choice:
- Why:
- Decided by:
```

Decided by is one of Adam, orchestrator, or a package ID. Every sudo command is logged here too.

## D001 — 2026-10-17 — Platform: head-to-head bake-off
- **Context:** FLUF refuses to coexist with six HDE DLLs, is beta and moves fast, and is AGPL. The design doc names FLUF.
- **Choice:** Phase 0 runs Track A (FLUF) against Track B (our own thin hook DLL, HDE intact), using the BUILD_PLAN §4 checklist. If both pass, choose B.
- **Decided by:** Adam

## D002 — 2026-10-17 — Separate modded prefixes
- **Choice:** Adam's play prefix is never modified. The mod runs in `prefix-dev*`, `prefix-lane*` and `prefix-carrier`.
- **Decided by:** Adam

## D003 — 2026-10-17 — Copilot LLM
- **Choice:** Claude Code CLI on Adam's subscription, model `claude-opus-5-5`, effort `low`, with no tools, MCP or connectors. Cost is not a concern.
- **Decided by:** Adam

## D004 — 2026-10-17 — Carrier purchase UI
- **Choice:** A custom Carrier Yard panel. Upgrades can be bought at purchase or retrofitted later, and per-planet catalogs differ.
- **Decided by:** Adam

## D005 — 2026-10-17 — No level gating
- **Choice:** Carriers are buyable whenever the yard is reachable. Every market level requirement is removed; reputation requirements stay.
- **Decided by:** Adam

## D006 — 2026-10-17 — Loss drops everything
- **Choice:** Everything aboard drops as bundled crates when the carrier dies.
- **Decided by:** Adam

## D007 — 2026-10-17 — Classes and prices
- **Choice:** Tier base prices are 3M / 8M / 20M. There are multiple classes per tier (Trade Carrier, Dreadnought, balanced ones and more), with operating costs from munition and nanobot resupply.
- **Decided by:** Adam

## D008 — 2026-10-17 — Yards and looks
- **Choice:**
  - Core yards: Norfolk, Southampton, Yokohama and Oder, each with its house look.
  - Border/Edge yards: Freistadt, Kurile, Cadiz and Freeport 9.
  - Nomad yard: Gammu, in the Osiris look.
- **Decided by:** Adam

## D009 — 2026-10-17 — Cargo value and ambush odds
- **Choice:** Cargo value raises ambush odds, with the multiplier capped at ×1.5.
- **Decided by:** Adam

## D010 — 2026-10-17 — Wingmen
- **Choice:**
  - 2 crew wingmen per carrier (3 at Nomad tier), replaced after a cooldown.
  - Plus unlimited hires from bars, across skill and ship tiers, with a fee and a small daily wage, and permanent death.
  - Docking bays cap how many ships launch from a carrier; followers are uncapped.
- **Decided by:** Adam

## D011 — 2026-10-17 — Nomad boss
- **Choice:**
  - It can appear anywhere in Ew06, and seeks the player out if they fight Nomads there.
  - The group is a battleship, 2 gunboats and 8 fighters.
  - It respawns after 4 in-game days; the Gammu unlock happens once.
- **Decided by:** Adam

## D012 — 2026-10-17 — Escalation designed during the build
- **Choice:** A dedicated design agent at Wave 4 designs a player-alterable faction-influence system and writes `docs/design/ESCALATION.md` for Adam to review later. The build implements it without waiting for him.
- **Decided by:** Adam

## D013 — 2026-10-17 — Autonomy grants
- **Choice:**
  - Sudo is granted; display `:0` may be used and the screensaver paused.
  - Push notifications at milestones and blockers.
  - A watchdog supervisor; degrade and continue when a package is stuck.
  - The GitHub repo `expectbugs/freelancer-carrier-mod` is **public**.
- **Decided by:** Adam

## D014 — 2026-10-17 — Voice input
- **Choice:**
  - The mic is the Bigscreen Beyond headset.
  - Push-to-talk is numpad period (VK 110) by default. Numpad minus is bound to the hidden `USER_ZOOM_IN`; it is a config option that unbinds that.
- **Decided by:** Adam, with the orchestrator setting the default

## D015 — 2026-10-17 — Fleet, retrofit, bays, wages, hardpoints, boss respawn, gating scope
- **Choice:**
  - Fleets are allowed.
  - Retrofit requires the carrier within 10 km of the yard.
  - Docking bays cap launches; followers are uncapped.
  - Hired wingmen cost a fee plus a small daily wage.
  - Adding hardpoints to existing models is allowed.
  - The Nomad boss respawns; the unlock happens once.
  - Level gating is removed for all equipment.
- **Decided by:** Adam (accepted the orchestrator's defaults)

## D100 — 2026-10-17 — display-awake.sh: borrow the XFCE session bus
- **Context:** Under tmux the orchestrator's shell had no `DBUS_SESSION_BUS_ADDRESS`, so `xfce4-screensaver-command --inhibit` failed ("Screensaver is not running") and the slideshow screensaver was active on `:0`.
- **Options:** (a) rely on `xset` only; (b) read the bus address of the running `xfce4-screensaver` from `/proc/<pid>/environ` (read-only) when unset, and un-blank with `-d` on start.
- **Choice:** (b). Verified: `xfce4-screensaver-command -q` → inactive, inhibited by `flbuild`. Screen lock is disabled in xfconf (`/lock/enabled false`).
- **Why:** an active screensaver window would cover lane windows for screenshots and synthetic input.
- **Decided by:** orchestrator

## D101 — 2026-10-18 — Git hooks path is absolute (main checkout)
- **Context:** P0-REPO review r1 F4: the shared repo config holds `core.hooksPath=/home/user/freelancer/carrier-mod/.githooks` (absolute). Worktrees branched before P0-REPO merges have no `.githooks/` or checker of their own.
- **Options:** relative `.githooks` (each worktree uses its own copy; pre-merge worktrees run no hook) vs absolute main-checkout path (every worktree runs main's hooks).
- **Choice:** absolute. Hooks locate the checker relative to their own real path, so they use main's checker everywhere.
- **Why:** the public-safety gate must apply to every agent commit, including sibling worktrees created before the hooks existed.
- **Decided by:** orchestrator

## D102 — 2026-10-18 — Public checker scope widened (P0-REPO review r1)
- **Choice:** content sniffing for game binaries regardless of extension; YAML/JSON forms of FL data detected by FL-distinctive keys (not generic `nickname`/`faction`, so our authored YAML passes); decomp marker matched loosely in all code; a gitignored local fingerprint index of `$FLMOD_REFS` rejects copies of other mods' content (escape: `check_public: derived-from <repo> <SPDX>` header → warning); `--tree` skips only `.claude/worktrees/` (CONVENTIONS §5 amended). Infra literals added to the local blocklist.
- **Why:** the reviewer showed 94% of real HDE INI files and 99% of decomp files passed the literal spec rules.
- **Decided by:** orchestrator
