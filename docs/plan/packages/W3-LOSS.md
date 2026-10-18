# W3-LOSS: Carrier destruction, salvage drop, cleanup

- **Type:** impl
- **Wave:** 3 (sub-wave 3a, CONVENTIONS §8)
- **Depends on:** ARCH-2
- **Unblocks:** M2-PLAYTEST; W4-WINGMEN (crew loss, hangar)

## Goal

A carrier is hard to kill but killable, and losing it is permanent. When it dies:

- it explodes convincingly **without crashing the game** (capital deaths are a known crash hotspot);
- **everything aboard** drops as a small number of bundled salvage crates the player can recover;
- crew are lost, hangar ships were already launched, all state is cleaned up;
- the player can buy another at full price.

## Requirements

- **REQ-W3-LOSS-1** (D-8.3, verbatim): "Permanent loss: a destroyed carrier is gone. Buy another at full price."
  - On carrier death in **any** live state (solar or ship form; ARCH-2 loss event via `OnServerSolarDestroy` / `OnServerShipDestroy` or the S-NPC-proven damage/destroy hook):
    1. the model goes to Destroyed. Per CONVENTIONS §9, a death outside a formal fight (Stopped or EscortTravel) passes `HullZero` → UnderAttack → Destroyed in one tick, so this package always handles `UnderAttack → Destroyed`;
    2. the record is removed after cleanup;
    3. no resurrection paths exist (save/load must not restore it, because the next save writes it gone).
  - A reload of an **earlier** save naturally has the carrier. That is the player's choice, and fine.
- **REQ-…-2** (D-8.4; Adam: "All drops, using bundled crates to avoid lag or issues with amount"):
  - Everything aboard drops: hold contents, stored or removed upgrades, nanobot and munition stocks, and anything else in the carrier inventory.
  - Use **at most 6 crates** per death (the vanilla `drop_loot` caps about 6 records; R2 fact 9).
  - Because one vanilla loot object holds one good type, implement **salvage pods**:
    - a mod-defined lootable equipment good `fcm_salvage_pod` (data via W1-DATA, or a `FIX` if missing);
    - each pod carries a manifest of goods and counts stored in the per-save JSON, keyed by the pod object id or a pod serial;
    - **when the player tractors a pod** (`TractorObjects` / `ReqAddItem` hook), remove the pod item and add the manifest contents to the player's cargo, up to the player's hold;
    - overflow stays in a remaining pod at the player's position, which the player can come back for, or optionally transfers into another of the player's carriers in the same system within 10 km (config, default on);
    - distribute the manifest across ≤ 6 pods by value (highest-value goods first, so partial recovery recovers the most value).
  - If the inventory has ≤ 6 distinct goods, plain vanilla crates (`lootcrate_*` archetypes, count = full stack) may be used instead of pods.
- **REQ-…-3:** **suppress vanilla drops.** Suppress the vanilla automatic drop for carrier objects (`OnServerShipDropAllCargo` or the equivalent), so nothing duplicates. API-spawned NPCs drop their lootable cargo unfiltered (R2 fact 9), which would duplicate the manifest.
- **REQ-…-4:** **loot lifetime.** Vanilla loot unseen beyond 2,500 m vanishes after 60 s (`LOOT_UNSEEN_RADIUS`/`LOOT_UNSEEN_LIFE_TIME`; R4 §A1.3).
  - Salvage pods must persist until collected: re-spawn them from the manifest when the player is in the system and within 10 km of the wreck site, if the engine removed them.
  - Wreck-site records persist in JSON until emptied (cap 20 sites; the oldest are dropped with a log line).
- **REQ-…-5** (D-8.5): "Hired wingmen docked in its hangar auto-launch when an ambush starts" (W3-AMBUSH emits `HangarScramble`). On death, assert that the hangar is empty, with a log warning if not; in that case launch them at the death point.
  - **Crew wingmen die with their carrier.** Emit `CrewLost(carrier)` for W4-WINGMEN; this package marks the crew roster entries dead.
- **REQ-…-6:** **crash-safe destruction.** Capital death and fuse effects are a crash hotspot (R4 pitfall 5; common.dll 0x5da50 / 0x5e010 fuse/explosion errors; Nomad Legacy "crash after death of battleship").
  - Never use `destroy_root` fuses on a solar that has a base.
  - Use the destruction method S-NPC proved stable:
    - `Destroy(Fuse)` with a vanilla capital explosion (`explosion_rh_battleship` family);
    - or `SetRelativeHealth(0)` with a known-good fuse;
    - or `Destroy(Vanish)` plus a spawned explosion effect.
  - Release the base binding **before** the solar dies.
  - **Never `ForceLand` a docked player** (CONVENTIONS / W2-CARRIER-GAME REQ-7). If the player is docked at that carrier's base when its hull reaches 0 (it shouldn't be possible: W3-AMBUSH's aboard hold makes the carrier invulnerable until launch):
    1. **defer the destruction**: set the carrier invincible at 1 % hull and show the alert "Carrier critical: abandon ship";
    2. destroy it only after the player's launch-complete, once they are ≥ 2 km away.
- **REQ-…-7:** **cleanup ordering.**
  1. Release the base binding and the registry entries (W2-CARRIER-GAME).
  2. Encounter outcome (loss) → the ambush instance is resolved.
  3. The model record is removed.
  4. JSON is updated on the next save.
  5. Notifications: NN/popup "Carrier <name> destroyed" plus a neural-net log entry.

  Reflex policies and the IPC carrier entries are cleared.
- **REQ-…-8:** devbridge (CONVENTIONS §4, `loss.*`):
  - `loss.kill <carrier>` (test: hull to 0 by the chosen method);
  - `loss.sites`;
  - `loss.pods`;
  - `loss.collect <pod>` (test tractor helper).

  Events: `ev=loss.destroyed carrier=… pods=N value=…`, `ev=loss.salvage pod=… collected=… goods=…`, `ev=loss.deferred carrier=… reason=player_docked`.

## Context pack (read before writing code)

- `CLAUDE.md`, `CONVENTIONS.md` (all; §4, §8, §9)
- `DESIGN.md` §8, §10.5, §11.4–11.5
- `TESTING.md` §Scenarios, §CrashTriage, §SaveCompat, §M2
- `state/ENGINE_FACTS.md`: S-NPC (loot bundling via `Server.MineAsteroid` / `CreateLoot`, capital death behavior, destroy hooks)
- Contracts (ARCH-2): loss, carrier forms, encounter outcome, inventory, base binding, notifications
- `local/research/R2-engine-api.md` §0 fact 9, §1.4 (destroy and fuse), §7 (loot), §9 (`OnServerShipDropAllCargo`, `OnServerSolarDestroy`)
- `local/research/R4-lore-and-testloop.md` §A1.1 (crash offsets: fuses and explosions), §A1.3 (loot lifetime), §A1.4 item 4
- Reference: `/home/user/freelancer/refs/FLHook-4.0-locked/plugins/loot_tables/LootTables.cpp` (~95, `MineAsteroid`), `…/cargo_drop/CargoDrop.cpp` 123–186, `/home/user/freelancer/refs/DiscoveryFLHook/Plugins/Public/base_plugin/CoreModule.cpp` 250–256, 399 (`LightFuse`)

## Ownership

- **Owns:** `src/game/loss/`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/game/loss/scenarios/`, `src/game/loss/tests/`
- **Reads:** `src/contracts/`, `src/logic/*`, `src/game/*`, `data/`
- **Must not touch:** everything else; the salvage-pod good definition is W1-DATA's (file a `FIX` if missing)

## Contract

- **Consumes (ARCH-2):** loss event and payload, inventory, encounter outcomes, base binding release, spawn service (loot), tractor/add-item events, notifications.
- **Provides:** the loss service, the salvage-pod manifest store (persistence section `salvage`), events `CarrierDestroyed` and `CrewLost`, devbridge commands.

## Tasks

1. The destruction sequence with crash-safe ordering.
2. Manifest building, the pod-distribution algorithm, and the pod spawn (`MineAsteroid` / `CreateLoot`).
3. Pickup conversion (tractor hook), overflow handling, wreck-site persistence and re-spawn.
4. Vanilla-drop suppression for carriers.
5. Cleanup, notifications, crew loss events.
6. Scenarios.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:**
  - the distribution algorithm (≤ 6 pods, highest-value first, conservation of goods: Σ manifests == inventory);
  - the overflow logic;
  - the site cap.
- **In-game scenarios:**

  | Scenario | Steps and expected result |
  |---|---|
  | `loss_destroy_drops_all` | Carrier with 25 distinct goods plus stocks; player nearby; `loss.kill <id>`. **Expect** explosion; **[vision]** "an explosion or debris where the capital ship was"; ≤ 6 pods spawned; collect them all (playbot tractor or devbridge tractor helper) → the player's cargo plus overflow pods together equal the original inventory exactly (HARNESS manifest diff empty); no crash; no new spew errors. |
  | `loss_no_duplicates` | **Expect** no vanilla loot crates other than our pods spawned at the death (object scan within 3 km). |
  | `loss_pods_persist` | Leave the system before collecting; save, reload, return. **Expect** the pods present at the site. |
  | `loss_stopped_carrier_killed` | A **Stopped** carrier (no ambush) attacked to death by spawned hostiles. **Expect** `ev=carrier.state … UnderAttack` then `… Destroyed` in one tick, and then the same drops and cleanup. |
  | `loss_cleanup` | After death: `carrier.list` lacks it; the yard fleet count decreased; docking at its former base is impossible; the base binding is released; buying a new carrier works. |
  | `loss_crash_soak` | 20 carrier deaths across classes and looks in one session. **Expect** zero crashes (the core crash-hotspot test). |
  | `loss_crew_event` | `CrewLost` emitted with the crew ids. |

- **Negative tests:**
  - death while the player is docked: it must be prevented. Prove the **deferred-destruction** path: `ev=loss.deferred`, no destruction, no ForceLand; destruction happens after launch at ≥ 2 km.
  - a pod tractored with a full hold;
  - save/load between the death and the pod spawn tick.

## Engine facts to rely on / verify

- S-NPC: loot bundling (`MineAsteroid` count semantics), a stable capital destruction method, destroy-hook firing for solars and ships.

## Pitfalls

- Never destroy within the same tick as spawn (`Freelancer.exe 0x14661b`, single player only).
- `drop_loot` health scaling may damage dropped equipment. Our pods carry manifests, so health is irrelevant.
- A pod's object id is not stable across save/load. Key manifests by our own serial stored in a pod-site record.

## Fallbacks and degrade path

1. If custom pod goods can't carry manifests reliably, spawn ≤ 6 plain crates with the 6 highest-value goods, and move the remainder into an "insurance claim" credited at 50 % value at the next yard visit. Log a decision; it deviates from "All drops".
2. **Degraded:** everything aboard is lost on death, with the reason logged in `DEGRADED.md`.

## Report (the agent's final message)

Per the template, including the destruction method used and the crash-soak results.

## Gate-time addendum

Contracts, S-NPC loot and death facts, salvage-pod data status, lanes, attempt and prior notes.
