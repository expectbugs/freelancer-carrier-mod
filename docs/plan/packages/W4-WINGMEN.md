# W4-WINGMEN: Crew and hired wingmen in space

- **Type:** impl
- **Wave:** 4 (sub-wave 4a, CONVENTIONS §8)
- **Depends on:** ARCH-3
- **Unblocks:** W4-HIRING (4b), M3-PLAYTEST

## Goal

The player flies with a wing:

- 2 crew wingmen per carrier (3 at Nomad tier);
- hired pilots from the roster (W4-HIRING).

The game's own AI flies and fights. Our code spawns them, keeps them in formation, points them at targets, pulls them back, launches and recovers them from carrier bays, and carries them through docks and jumps. It also escorts a travelling carrier and freezes them with an away carrier's ambush. Orders come from hotkeys, the roster panel, devbridge and the sidecar.

## Requirements

- **REQ-W4-WINGMEN-1 (D-11.4).** Crew complement and replacement.
  - Each carrier has crew wingmen: Nomad tier 3, else 2; class overrides come from `docs/design/CARRIERS.md` (e.g. Command Carrier extras).
  - A destroyed crew wingman is replaced **at its carrier after 1 in-game day**. Faster on Command Carriers, per the CARRIERS.md value.
  - Replacement is a roster state change; the ship respawns on the next launch from that carrier.
- **REQ-W4-WINGMEN-2 (D-11.6).** Docking bays cap launches.
  - A carrier launches and recovers at most `bays` wingmen.
  - Ships following the player that launched from a normal base, or joined in space, are **not capped**.
  - Roster assignments: `follow_player`, `guard_carrier(<id>)`, `stay_docked(<id>)`.
- **REQ-W4-WINGMEN-3 (D-11.7).** Orders.
  - `formation(tight|loose|line|escort)`, `focus(<target>)` (player's target, nearest hostile, capital, specific id), `engage_free`, `hold`, `retreat`, `regroup`, `guard_carrier`.
  - Implemented per R2 §4.4:
    - follow: `DirectiveCancelOp` + `DirectiveFollowOp{player, maxDistance, offset}`;
    - attack: `pub::Reputation::SetAttitude(npcRep, targetRep, -1)` both ways, cleared with 0.0, plus `submit_forced_target` if S-NPC proved it;
    - recall/retreat: `DirectiveGotoOp{gotoType 0, target player, range, goToCruise}`.
  - Formation offsets are computed by us (per-slot offsets in follow ops).
- **REQ-W4-WINGMEN-4.** Reputation and IFF.
  - Each wingman gets its own allocated rep (`pub::Reputation::Alloc`), affiliated with a mod-defined player-wing group, or an existing neutral group per ENGINE_FACTS.
  - It mirrors the player's attitudes: it shoots whoever the player is hostile to and is attacked by them. No friendly fire against the player's other wingmen or carriers.
  - Re-sync on reputation changes.
- **REQ-W4-WINGMEN-5.** Lifecycle across docks, jumps and saves.
  - **Docking:** wingmen following the player dock with the player (despawn at the base; they "land" too). Assigned-to-carrier wingmen recover into its bays.
  - **Launch:** they respawn beside the player, or launch from carrier bays.
  - **Jumps:** despawn on SystemSwitchOut; respawn near the player on JumpInComplete in formation, unless ENGINE_FACTS proves native follow-through jumps are reliable.
  - **Save/load:** roster and in-space state are persisted (hull %, ammo/bots state if tracked). On load, in-space wingmen respawn at their saved offsets.
  - Follow R2 §4.4 step 6.
- **REQ-W4-WINGMEN-6 (D-11.8).** Escort duty.
  - Wingmen assigned `guard_carrier(X)`:
    - **X live (escort travel):** they fly with it in a protective formation and engage threats to it.
    - **X Away:** they travel on paper with it.
    - **X AmbushWaiting:** they freeze with it in the encounter's frozen state and spawn beside the carrier, fighting, when the player arrives (W2-ENCOUNTER thaw).
- **REQ-W4-WINGMEN-7 (D-8.5).** Hangar auto-launch.
  - When any ambush or encounter targets a carrier, all hired wingmen docked in its hangar launch immediately (up to bays; the rest launch in waves as slots free) and defend it.
  - Hired pilots are never inside a carrier when it dies. Crew wingmen die with it.
- **REQ-W4-WINGMEN-8.** Permadeath. A destroyed **hired** wingman is permanently dead (roster status `dead`, recorded with time, place and killer faction). Crew wingmen follow the REQ-1 replacement rule.
- **REQ-W4-WINGMEN-9 (D-11.9, D-1.6).** Army scale.
  - No cap.
  - Spawn in staggered batches (≤ 4 per tick) to avoid frame spikes.
  - When the follower count exceeds the S-PERF warn threshold (ENGINE_FACTS), show the warning toast once per session.
  - When the player is more than 10 km from idle followers (e.g. they're holding a position), despawn them to paper and respawn on approach, unless they are in combat.
- **REQ-W4-WINGMEN-10.** In-space wing panel and hotkeys.
  - Roster quick panel (W1-UI kit): list, health and status, order buttons.
  - Hotkeys for formation cycle, attack-my-target, regroup and retreat, rebindable where the platform allows. They must not conflict with vanilla binds; check `DATA/INTERFACE/keymap.ini`.
- **REQ-W4-WINGMEN-11.** IPC. Emit `wing[]` snapshot fields and `ev.wing` events (ipc.md v2). Execute `wing.*` commands from the sidecar after clamping and validation.
- **REQ-W4-WINGMEN-12.** Devbridge `wing.*` commands per `docs/spec/devbridge.md` and CONVENTIONS §4: `wing.list`, `wing.order <who> <order>`, `wing.kill <id>`, `wing.state <id>`, and the test-only `wing.add_test kind=crew|hired skill=<t> ship=<arch> [carrier=<id>] [status=docked|following]`.
  - `wing.add_test` injects roster entries without the hiring UI, because W4-HIRING (sub-wave 4b) is built after this package.
  - Events: `ev=wing.spawned|engage|damaged|down|rejoined|quit|replaced id=…`.

## Context pack (read before writing code)

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (all; §4, §7 `--perf` lock, §8, §13)
- `docs/plan/DESIGN.md` §8.5, §11
- `docs/plan/TESTING.md` §Devbridge, §M3, §Metrics (army-scale), §SaveCompat
- `state/ENGINE_FACTS.md` (S-NPC, S-PERF)
- Contracts: `src/contracts/wingmen.hpp`, `spawn.hpp`, `ai.hpp`, `encounter.hpp`, `carrier.hpp`, `platform.hpp`, `ui_kit.hpp`, `ipc.hpp`; `docs/spec/wave4-contracts.md`, `docs/spec/ipc.md`
- `docs/design/CARRIERS.md` (bays, crew counts, Command Carrier bonuses)
- `local/research/R2-engine-api.md`: §1 (spawning, ShipInfo), §4 (AI ops, personalities), §4.4 (wingmen recipe), §6 (combat helpers)
- Reference code (study, don't copy; Discovery is unlicensed): `/home/user/freelancer/refs/DiscoveryFLHook/Plugins/Public/dronebays/` (`Utility.cpp`, `UserCommands.cpp`, `Main.cpp`, `Timers.cpp`) and `/home/user/freelancer/refs/FLHook-4.0-locked/plugins/npc_control/NPCControl.cpp`
- The lane install's `DATA/MISSIONS/pilots_population.ini` personalities (read at runtime or deploy; reference by nickname only, CONVENTIONS §12): `pilot_military_*`, `pilot_bh_*`, `pilot_pirate_*`, `pilot_lrogue_*`, … with `_easy|_med|_hard|_ace`

## Ownership

- **Owns:** `src/logic/wingmen/`, `src/game/wingmen/`, `harness/scenarios/wingmen/`, `tests/host/wingmen/`
- **Reads:** all contracts, merged code, data
- **Must not touch:** `src/game/ui/hiring/` and `src/logic/hiring/` (W4-HIRING), sidecar (W4-BRAIN), contracts

## Contract

- **Consumes:** spawn, AI helpers, encounter (freeze/thaw, auto-launch hook), carrier (bays, state), inventory (none directly), UI kit, IPC, persistence.
- **Provides:** `wingmen.hpp` implementation; events `wing.*`; devbridge `wing.*`; IPC handlers.

## Tasks

1. Engine-free model in `src/logic/wingmen/`: roster state machine, order state, formation slot math, bay accounting, replacement timers. Host tests first.
2. Game adapter: spawn/despawn via the spawn service, with validated NPC defs (pilot personality from tier, faction-appropriate `npcships.ini` arch and loadout). Rep allocation and attitude sync.
3. Orders → AI directives. Formation offsets. Target focus via rep attitudes.
4. Dock, launch, jump and save/load lifecycle.
5. Escort duty and away-freeze integration with W2-ENCOUNTER; hangar auto-launch hook.
6. Army-scale staggering, the warning, and the distance-based paper mode.
7. Wing panel and hotkeys; IPC and devbridge.
8. Scenarios and evidence.

## Acceptance (all automated)

- **Host tests:**
  - `wing_roster_transitions` (all statuses)
  - `wing_bays_cap` (launch capped, followers uncapped)
  - `wing_crew_replacement_timer` (1 day; Command Carrier faster)
  - `wing_formation_slots` (no overlapping slots up to 200)
  - `wing_permadeath_persist`
- **In-game scenarios** (`harness/scenarios/wingmen/`):
  - `wing_follow_and_formation` (input lane: formation hotkey → vision rubric `wing_formation` shows ships in the expected shape)
  - `wing_attack_my_target`: target a spawned hostile, send the order, then `ev=wing.engage` and the target is destroyed within 3 min
  - `wing_retreat_regroup`
  - `wing_through_gate`: jump; wingmen re-appear within 10 s in formation
  - `wing_dock_launch`: dock, launch; count preserved
  - `wing_bays_launch_cap`
  - `wing_escort_carrier_live`
  - `wing_escort_carrier_away_freeze`: away ambush with guards; arrive; guards spawn and fight
  - `wing_hangar_autolaunch`: `wing.add_test kind=hired status=docked carrier=<id>` ×3, then `ambush.force <id>` (`ev=` HangarScramble path from W3-AMBUSH); all launch; `loss.kill <id>`; hires survive
  - `wing_save_load_in_space`
  - `wing_permadeath`: kill a hire; reload; still dead
- **Metrics** (TESTING §Metrics army-scale row / `harness/metrics_targets.yaml`; measured under `harness/lane.sh acquire --perf`):
  - Army curve re-run at 10/25/50/100/200 (`wing_army_scale`): fps_avg, fps_p1 and `va_free_mb` recorded; the warning shown at the warn threshold; no cap applied.
  - Staggered spawning keeps the frame-rate floor until the measured warn threshold.
- **Negative:**
  - wingman spawn with an invalid arch (forced via devbridge) ⇒ a validation error, no spawn, no crash;
  - player death with wingmen out;
  - F1 pause with 50 wingmen out;
  - load a save from before wingmen existed.

## Engine facts to rely on / verify

- **Verify:** whether NPCs with `DirectiveFollowOp` follow the player through gates natively (R2 fact 8; UNVERIFIED for API NPCs).
- **Verify:** that `submit_forced_target` works (R2 §4.1: no usage example). Otherwise use rep-attitude only.
- **Rely on:** `Act_PlayerEnemyClamp` limits *enemies attacking the player*, not friendlies (R4 §A1.3). Note in the report whether it limits fights.

## Pitfalls

- Destroying a just-spawned NPC can crash in SP (Freelancer.exe 0x14661b): never despawn in the same tick as spawn; defer.
- Every NPC needs a loadout with an engine (server.dll 0x2247f).
- Large formations at gates (common 0x06C00D = 200f).
- Followers trying to dock with the player's dock target (R2 fact 8): intended for base docking, but block it for the carrier-bay case and recover them ourselves.

## Fallbacks and degrade path

1. If follow-through-jump is flaky, always use despawn/respawn.
2. If attitude-based focus fails for some factions, use `submit_forced_target`; else "engage free" only (degraded: focus unsupported for that faction).
3. If high counts crash, keep no cap but force paper mode beyond the measured stable count (log the decision; never refuse hires).

## Report

Standard. Include the army-scale table and the warn-threshold value used.

## Gate-time addendum

(orchestrator)
