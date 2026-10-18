# S-BASE: Spike: dockable runtime carrier base, base binding (Plan A vs B), save/load, purchase

- **Type:** spike
- **Wave:** Phase 0 (after G0a)
- **Depends on:** G0a, P0-DATATOOLS → **Unblocks:** G0b, then ARCH-0, W1-DATA (carrier base data), W2-CARRIER-GAME, W2-YARD.

## Goal

Answer, with in-game evidence on the chosen track, every engine question the carrier's "Stopped / docked" behaviour depends on:

- Can we spawn a battleship-model object at runtime that the player can see and dock with, in single player?
- Can we make the player undock beside it?
- Can **one** pre-declared base follow the carrier from system to system (Plan A)? Or do we need per-system proxy bases with an "arrival" reload (Plan B)?
- Do saves and loads made while aboard restore safely?
- Can a custom panel take the player's money?

Results feed `state/ENGINE_FACTS.md`, and G0b chooses Plan A or B.

## Requirements

- **REQ-S-BASE-1:** Build `s_base.dll` (a spike module/DLL) on top of `spike_platform_<track>`. The chosen track is in `harness/config/default_track` and the gate addendum. Add devbridge verbs for each experiment.
  - Spike data the experiments need comes from a spike-local generator (`spikes/s_base/gen/`) using P0-DATATOOLS. It is applied to lanes only and never committed as game data.
- **REQ-S-BASE-2:** Run the experiments below. Each one is an automated scenario in `spikes/s_base/scenarios/`. Record a result in `spikes/s_base/FINDINGS.md` with this schema per experiment:
  - `ID`, hypothesis, method, observation, verdict (`CONFIRMED`/`REFUTED`/`PARTIAL`), evidence paths, and the `ENGINE_FACTS` text to add.
  - Also an `EF-` fact id, which the orchestrator assigns on merge; use `EF-BASE-<n>` placeholders.
- **REQ-S-BASE-3: SolarInfo.** Use FLSDK `SolarInfo` (`FLCoreServer.h:831-848`; R2 §1.3, VERIFIED field table):
  - `flag=4`; `archId` must be valid or the game crashes;
  - `systemId`; `pos`/`orientation`; `loadoutId`;
  - `costume` (`benchmark_male_head/body`); `voiceId` (`atc_leg_m01`);
  - `dockWith` at offset 0x7c: an existing universe base id; the solar is then dockable to that base;
  - `hitPointsLeft` (then `SetRelativeHealth(id,1)`);
  - `nickName[64]`: must be **unique and non-empty**, else CreateSolar returns −4;
  - `mission` (0/1).
  - Reputation: `pub::Reputation::Alloc(rep, scannerFmtStr, nameFmtStr)` + `SetAffiliation`.
  - Validate the archetype, loadout and base ids before every spawn (R2 §1.5, R4 §0.1 #4).

## Experiments

Each experiment lists the hypothesis, the method, the pass condition, the evidence and the fallback.

### E1: Runtime solar visible in SP (3 spawn paths)

- **Hypothesis:** a solar created at runtime appears on the SP client with its loadout and is targetable.
- **Risk:** MP spawners suppress vanilla's CREATESOLAR packet (server.dll+0x2A62A `0x74→0xEB`) and resend their own. FLUF's builder resends only `if (IsMPServer())`, with the comment `// TODO: Figure out how this behaves in SP!` (R2 fact 4; R1 §2.6, VERIFIED code, runtime UNVERIFIED).
- **Method:** from `HARNESS_endgame_eagle_space`, spawn archetype `o_osiris` 3 km ahead of the player. `o_osiris` is a STATION with docking spheres, 100,000 hp, loadout `or_osiris`, berth/moor spheres (R3 §4.3, VERIFIED). Use each path:
  - (a) raw `pub::SpaceObj::CreateSolar` with **no** packet patch;
  - (b) Track A: `ResourceManager::CreateSolarSimple(SolarSpawnStruct&, module)`, which sends `Send_FLPACKET_SERVER_CREATESOLAR` to every FLUF client in the system, including SP client 1 (R1 §2.6). Track B: raw CreateSolar plus a manual CREATESOLAR packet only if (a) fails;
  - (c) Track A only: the FLUF `SpaceObjectBuilder` `.AsSolar()`.

  Repeat with archetype `l_dreadnought` (STATION, li_dreadnought.cmp, docking spheres; R3 §4.3).
- **Pass:**
  - **visible:** a screenshot plus vision check, with the rubric "a large capital ship is clearly visible ahead";
  - **loadout present:** turrets visible on the model; devbridge reports `pub::SpaceObj::GetHealth` and the loadout id;
  - **targetable:** client target selection by devbridge `target <id>`, or the scanner list;
  - **survives** jumping away and back (despawn not expected; R2 fact 2).
- **Evidence:** screenshots per path, HARNESS lines, FLSpew diff.
- **Fallback** (BUILD_PLAN §8): raw CreateSolar without FLUF's patch. Else a hidden pre-placed carrier object per system (generated `[Object]` with `visit=128`) moved by respawn.

### E2: Dockable runtime solar

- **Hypothesis:** the E1 solar with `dockWith = CreateID("Li01_15_Base")` lets the player dock and enter that base's rooms. `Li01_15_Base` is the Osiris base declared for system Li01: `li_06` bar, li_05 deck, Deck2; no static object (R3 §4.4, VERIFIED).
- **Method:** fly the player close (devbridge `goto_near <id> 800`, implemented as a same-system relocate of the player ship per R2 §3; for player ships also send `FLPACKET_SERVER_LAUNCH`). Then `dock <id>`: `pub::SpaceObj::DockRequest(ship, id)` / the client dock key.
- **Known glitch:** "spawned solars are not dockable". FLHook 4.0 re-applies `SetRelativeHealth(id, 1.0f)` every 5 s (R2 §1.5). Test with and without the re-apply.
- **Pass:** `ev=base_enter base=li01_15_base`; a screenshot of the Osiris interior (vision: "a ship interior deck or bar is shown"); no crash.
- **Evidence:** a scenario log plus a screenshot.
- **Fallback:** intercept the dock (`OnDockRequest`) and `pub::Player::ForceLand(1, base)` or `pub::SpaceObj::InstantDock(ship, base solar, port)`. The `InstantDock` port isn't range-checked: use port 0/1 only (R2 fact 15).

### E3: Undock placement

- **Hypothesis:** `SetUndockOverride` places the player at the carrier position + up × 500 + forward × 1500 when undocking from `Li01_15_Base`.
- **Pass:** the player is within 50 m of the target position (devbridge `state` pos); no crash; no collision spin.
- **Watch:** server.dll **0x14990** (no valid undock point) and **0xab670** (warp to a base whose solar isn't in space) are known crash offsets (R4 §0.1 #1).

### E4: Plan A, re-point one base to another system

- **Hypothesis:** at runtime, mutating the shared `Universe::IBase` record for `Li01_15_Base` (`systemId`, `spaceObjId`; FLSDK `include/FLCore/Common/Universe/IBase.hpp`; R5 §4.1/§4.2) makes the base "live" in another system, because common.dll is shared by the SP client and server.
- **Method:**
  1. Player docked at `Li01_15_Base` (via E2) in Li01.
  2. Spawn the carrier solar in **Li02** (same `dockWith`).
  3. Set `IBase.systemId = Li02` and `spaceObjId = <new solar id>`. Get the `IBase*` via `Universe::get_base(baseId)`.
  4. Launch.
  5. Also: undocked in Li02 → dock at the Li02 solar → BaseEnter → launch again.
- **Pass:**
  - after launch the player is in **Li02** next to the solar (`state system=li02`);
  - the nav map and current-information panel show the right system (screenshot);
  - no crash at server **0x14990/0xab670**, common **0x4fe6c** (client/server base mismatch) or Freelancer.exe **0x13d55a** (dock to a solar the client doesn't have; R4 §0.1 #1);
  - repeated 10× across 3 systems.
- **Evidence:** the scenario log, screenshots, crash triage (if any).
- **Fallback:** E5 (Plan B) and E6.

### E5: Plan B, per-system proxy base plus arrival reload

- **Method:**
  1. The spike generator creates two proxy bases (`fcm_spk_li01_carrier_base`, `fcm_spk_li02_carrier_base`; all new nicknames use the `fcm_` prefix, CONVENTIONS §2), each with:
     - a `[Base]` in `universe.ini` with `system = Li01` / `Li02`, `file =` a copied Osiris base ini;
     - rooms copied from `Li01_15_Base`'s files;
     - an `[MBase]` in `mbases.ini`.

     All are generated from the lane's install; nothing committed.
  2. Docked at the Li01 proxy, simulate arrival in Li02:
     1. `save HARNESS_arrival`;
     2. edit the `.fl` `[Player] system = Li02`, `base = fcm_spk_li02_carrier_base` (and `location` → the Li02 room hash via `location_id`);
     3. spawn the Li02 solar on load **before** launch is possible;
     4. `load`.
- **Pass:** the player is docked at the Li02 proxy; launch places them next to the Li02 solar; total transition time (reported in ms) under 15 s; no crash.
- **Evidence:** timings, screenshots, the save diff (in the run dir only).

### E6: Cross-system move on undock (alternative for A)

- **Hypothesis:** FLUF's SP "Move System" recipe can relocate the player into the carrier's system right after launch: patch server.dll+0xF600 (the SystemSwitchOutComplete routine) with target system, pos and orientation, and set `*(SystemId*)0x67977C = target` (R2 fact 5; `refs/FLUF/FLUF/Source/Common/Commands/Admin/AdminSystem.cpp:52-124`, VERIFIED code; the same bytes as Discovery HyperJump and '88 Flak SwitchSys).
- **Method:** docked at a Li01 base, launch, then trigger the move to Li02 at the carrier position.
- **Pass:** the player ends up in Li02 at the position; no crash; the client shows the correct system.
- **Evidence:** log plus screenshot.

### E7: Fleet scale: at least 8 carriers sharing base records (D-3.1)

- **Requirement:** DESIGN D-3.1 requires a fleet cap of **at least 8**, as high as the base mechanism allows. This experiment measures the real cap.
- **Method, Plan A** (one active "docked" carrier at a time):
  - spawn **8 carrier solars** spread over at least 4 systems, all `dockWith` the same base record (or one record per look, if looks need different interiors);
  - dock at each in turn and verify the re-point happens **in the dock-request hook, before the dock completes**;
  - cycle through all 8 twice, then try 16 and 32 to find any limit.
- **Method, Plan B:**
  - 8 carriers including **2 of the same look in the same system**, sharing one proxy base; the mod tracks which one you are "in" (Discovery POB pattern, R2 §2.1);
  - dock and undock at each of the two same-system carriers alternately 5×;
  - then the full 8.
- **Pass:**
  - each dock enters the base;
  - each undock places the player at the **correct** carrier (within 50 m of that carrier's position + offset);
  - no crash or object-count errors in FLSpew.
- **Report** the measured practical cap (largest count tested without errors) as an EF fact. The Yard panel later shows that cap (D-3.1).

### E8: Save and load while aboard

- **Method:** docked at the carrier base: `save HARNESS_aboard`, quit, then `load HARNESS_aboard` with **no** solar spawned yet. Observe whether loading crashes (it shouldn't: the base is static) and whether launch crashes without a solar (expected, R4 §A1.4 #2). Then repeat with our `OnSaveLoaded` handler spawning the solar and re-pointing (Plan A) before launch is unblocked.
- **Pass:** load never crashes. Launch is blocked until the solar exists, then works. Under Plan A the `IBase.systemId` reset-on-load is detected and re-applied.
- **Evidence:** logs; a `<save>.carrier.json` round trip via the platform hooks.
- **Never call `ForceLand` (or any relocation) on a player who is docked**: that's the known crash class (R2 fact 6; review #29). Moving a docked player between bases is done only by the E5 route (rewrite `base=` in the save and reload), or by making the target base's solar exist before launch.

### E9: Purchase from a custom panel

- **Method:** devbridge `buy_test <credits>` (stands in for the Yard panel button):
  - `pub::Player::AdjustCash(1, -X)` (or FLUF `ClientId::AdjustCash`);
  - verify with `pub::Player::InspectCash`;
  - `save` / `load` → the amount persists;
  - insufficient funds → refused without change.
- **Pass:** the cash changes exactly; the change is persisted; the refusal path works; the HUD credit display updates (screenshot).

### E10: Docking denial and permission

- **Method:** `deny_dock <carrier solar> 1` → try to dock → refused with feedback (NN message), and the player isn't stuck in a docking state. `deny_dock … 0` → docking works. Also deny docking at a ship-type NPC (escort-mode carrier) to confirm DESIGN D-7.6 can be enforced on both representations.
- **Pass:** both states behave; no stuck state.

### E11: Dockable NPC ship (one object for both forms)

- **Hypothesis:** `ShipInfo` offset 0xac (`DockingBaseId`; R2 §1.2, VERIFIED-decomp) set to a base id makes a **ship** dockable, if its shiparch has docking spheres. No prior art (R2 §2.6 option B).
- **Method:** spawn `li_dreadnought` as an NPC ship with `DockingBaseId = Li01_15_Base` and try to dock, both stationary and moving.
- **Pass/refute:** record the result. If it works, ARCH-0 may unify Stopped and Escort.

### E12: Carrier base display name and infocard per carrier

- **Method:** rename at runtime (D-3.2). Override the base name and infocard IDS shown on dock and in the target info with "CV *Player Name*".
  - Track A: `InfocardManager::OverrideInfocard(ids, wstring, isName)` (R1 §4).
  - Track B: hook the IDS lookup `GetIdsName` 0x4347E0 (R5 §1.2; adoxa console `GetString` FUNC 0x4347e0, VERIFIED source), or use FLSharp's `dynamic_solar_infocards` via `DATA/UNIVERSE/missioncreatedsolars.ini` (R3 §1.3, VERIFIED option in FLSharp.ini; B only).
- **Pass:** the custom name appears in the base screen and the target view (screenshots).

## Context pack

- `docs/plan/DESIGN.md` §3, §5, §7 (esp. D-7.2, D-7.3, D-7.6, D-7.11, D-7.12), §14 (D-14.2: every save names a base that exists)
- `docs/plan/CONVENTIONS.md` §1, §2 (`fcm_` prefix), §4–§7 (authoritative)
- `docs/plan/BUILD_PLAN.md` §8 (fallbacks); `docs/plan/TESTING.md` §Scenarios, §Vision, §SaveCompat, §CrashTriage
- `$FLMOD_RESEARCH/R2-engine-api.md` §0 (facts 3–6, 15), §1.3–1.5, §2 (all prior art), §3 (moving things)
- `$FLMOD_RESEARCH/R5-sp-architecture.md` §3 (saves), §4 (docking, launch)
- `$FLMOD_RESEARCH/R3-game-data.md` §4.3–4.4 (solars, bases, Osiris family, `[MsnSolar]` example), §1.3 (FLSharp dynamic infocards)
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md` §0.1 #1, #2, §A1.4
- `refs`:
  - `FLHook-4.0-locked/plugins/solar_control/SolarControl.cpp` (spawn recipe :261-357; health re-apply :613-625)
  - `DiscoveryFLHook/Plugins/Public/{base_plugin,mobiledocking_plugin}`
  - `FLHook-88Flak/FLHook/trunk/src/source/HkCbIServerImpl.cpp` (:240-420, :1702-1830, :2689-2785)
  - `FLUF/FLUF/Source/Server/ResourceManager.cpp`
  - `FLUF/FLUF/Source/Common/Commands/Admin/AdminSystem.cpp`
  - `Freelancer-Decomp/src/Server/*` (`server_pub.cpp` CreateSolar/ForceLand/InstantDock)

## Ownership

- **Owns:** `spikes/s_base/`.
- **Must not touch:** `spikes/track_*` (extend via your own sources; request platform changes in your report), `harness/`, `docs/plan/`, `state/`.

## Contract

- **Provides:** `FINDINGS.md` with proposed ENGINE_FACTS entries; a recommendation of **Plan A or B** with evidence; the exact recipes (code snippets in our own words) that worked.
- **Consumes:** `spike_platform_<track>`, the harness, fltools.

## Tasks

Run E1 → E2 → E3 → E4 → E5 → E6 → E7 → E8 → E9 → E10 → E11 → E12. E4 to E7 depend on E1 and E2 passing; if E1 or E2 fail, go straight to their fallbacks.

## Acceptance

Every experiment has a verdict and evidence. Plan A or B is recommended, with a justification table. The measured fleet cap from E7 is reported, and it must be at least 8 or the experiment is FAILED. Reviewers re-run E2, E4 (or E5), E7 and E8.

## Engine facts to rely on / verify

**Verify (UNVERIFIED today):**

- SP client visibility of runtime solars;
- `dockWith` dockability in SP;
- IBase re-pointing;
- Move System in SP;
- load-time IBase reset;
- `DockingBaseId` on ships.

**Rely on (VERIFIED):**

- bases are static, with a fixed `system=`;
- launch needs the base's solar in space;
- the crash offsets above;
- the SolarInfo layout;
- saves are plain text.

## Pitfalls

- Duplicate or empty solar nickname → duplicate object or a −4 return. Use unique, deterministic nicknames, e.g. `fcm_crr_<carrierId>_<n>`.
- `ForceLand` only works for a player in space, and relocating a docked player is a crash path. Never do either from a docked state.
- Never destroy a dockable base solar while the player is docked (behaviour UNVERIFIED; Discovery force-launches occupants).
- Defer spawns triggered inside BaseEnter or dock callbacks by one tick.
- Never `destroy_root` a dockable base's fuse (R4 §A1.4 #4).

## Fallbacks and degrade path

As listed per experiment, plus BUILD_PLAN §8. If both Plan A and Plan B fail, report BLOCKED with evidence. The orchestrator then reconsiders: e.g. the static Osiris-family pattern, with one `[Base]` per system per look as pre-placed hidden objects.

## Report

AGENT_BRIEF_TEMPLATE format plus a summary of `FINDINGS.md` and the Plan A/B recommendation.

## Gate-time addendum

(Orchestrator: track, lane(s), attempt, commit trailer.)
