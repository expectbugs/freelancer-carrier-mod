# W3-AMBUSH: Ambushes (rare and earned)

- **Type:** impl
- **Wave:** 3 (sub-wave 3b, CONVENTIONS §8)
- **Depends on:** W3-ESCORT, W3-LOSS (merged), ARCH-2
- **Unblocks:** M2-PLAYTEST, W4-WINGMEN (hangar auto-launch hook), W4-ESCALATION (influence-weighted odds later)

## Goal

Travelling carriers can be ambushed, but only where an enemy really patrols in strength and can pull a capital ship out of cruise. The odds come from the game's own patrol data, weighted by the player's reputation and cargo value. What happens depends on where the player is:

| Player is | What happens |
|---|---|
| Aboard | Alert and forced stop |
| Escorting | A real fight on the spot |
| Away | A distress call. The fight waits, frozen, until the player arrives |

The result: "a base ship is a golden target, but only for enemies strong enough to stop one."

## Requirements

- **REQ-W3-AMBUSH-1** (D-9.1, verbatim): "Only where the route crosses areas an enemy patrols in real strength, and only if that enemy has interdiction strong enough to pull a capital ship out of cruise."
  - For each route leg, compute per hostile faction f: **E_f**, exposure. This is metres inside combat-encounter zones × density × encounter chance × faction weight, as in `R3-data/tools/route_exposure.py`, ported in W1-WORLD. It excludes trade-lane BOX zones (D-9.4).
  - **I_f**, interdiction capability: the fraction of level-matched NPC ships of f carrying a cruise disruptor (`frac_spawnable_ships_with_CD`), or a gunboat/capital presence factor. Data comes from the deploy-time generated equivalent of `R3-data/system_combat_presence.json` (`cd_weighted`, `gunboat_presence`, `max_level`).
  - If I_f = 0, then f contributes **0**.
- **REQ-…-2** (D-9.2): **reputation weighting.** H_f from the player's reputation with f (the game's ±0.6 thresholds):

  | Reputation with f | H_f |
  |---|---|
  | ≤ −0.6 (hostile) | 1.0 |
  | between −0.6 and +0.6 (neutral) | 0.25 (tunable) |
  | ≥ +0.6 (friendly) | **0**: "friendly space is safe passage" |

  The player's escort wingmen don't change odds.
- **REQ-…-3** (D-9.3): **cargo multiplier.** C = 1 + 0.5 × min(1, V / V_ref), **capped at 1.5**, where V is the value of everything aboard the carrier (hold + stocks) at base prices, and V_ref comes from data (default 10,000,000 cr).
- **REQ-…-4:** **odds formula.** Hazard rate λ_leg = k × Σ_f (E_f × I_f × H_f) × C × (1 − dampener) × class_factor.
  - P(ambush during a leg segment of duration Δt) = 1 − exp(−λ × Δt).
  - k, class_factor and the dampener values are tuning data, **tuned so frequencies fall in the TESTING.md §Metrics bands**, the single source, encoded in `harness/metrics_targets.yaml`:

    | Space | Ambushes per hour of carrier travel (hostile rep, no cargo) |
    |---|---|
    | Liberty core (Li01–Li05) | ≤ 0.1 |
    | Bretonia/Kusari/Rheinland interiors | 0.1–0.3 |
    | Border Worlds | 0.3–0.6 |
    | Edge/Hispania | 0.8–1.5 |

    Friendly rep (≥ +0.6) to every patrolling faction ⇒ the odds factor is ≤ 0.25 (REQ-2 makes it 0). Never restate different numbers. If the table in TESTING changes, it wins.
  - Tuned values live in **`data/tuning/ambush.yaml`**, owned by this package and layered over W1-CARRIER-DESIGN's defaults (BUILD_PLAN §6 conventions).
  - Provide a host **Monte Carlo** that reports these frequencies from the real data, used to tune k.
- **REQ-…-5:** **rolls.**
  - Evaluated for every carrier in DockedTravel, EscortTravel or Away, on simulated time, every 10 s of game time per carrier.
  - Use the carrier's deterministic RNG (W2-CARRIER-LOGIC).
  - **One at a time per carrier** (D-9.7): no rolls while `ambush_pending`.
- **REQ-…-6** (D-9.8): **lineup.** Request a lineup from the W2-ENCOUNTER generator for the winning faction (chosen proportional to E×I×H) at that zone's level. Scale it by carrier tier and class (data):
  - include gunboats where the faction fields them;
  - for house navies, use the unused d22/d25 capitals (`li_n_cruiser_d22`, `li_n_dreadnought_d25`, `br_n_destroyer_d22`, `br_n_battleship_d25`, `ku_n_destroyer_d22`, `ku_n_battleship_d25`, `rh_n_cruiser_d22`, `rh_n_battleship_d25`) only for high-strength cases.

  The lineup must be able to threaten the carrier. Balance targets are in TESTING §Metrics: a tier-matched carrier with full nanobots and no player help wins **≥ 70 %** in the host balance sim, and a carrier two tiers below loses most (≤ 30 % wins).
- **REQ-…-7** (D-9.5, aboard): "Alert, forced stop, the carrier appears with attackers nearby, you launch and fight."
  - The carrier model transitions DockedTravel → UnderAttack: snap position, spawn the solar via form-swap, unblock launch.
  - Show an alert: popup/NN message plus a docked-UI banner.
  - Attackers spawn 4–7 km away (placement solver).
  - **Never forced (D-1.5):** the fight does not start while the player is still docked. Until the player launches, attackers hold position, and the carrier and attackers are mutually non-hostile or invulnerable (attitude neutral + `SetInvincible`). On launch-complete, attitudes turn hostile and the fight begins.
  - **Save/reload while docked during the alert** (ARCH-2 REQ-1c): the instance is saved frozen. On load, W2-CARRIER-GAME's restore spawns the carrier solar **first**, then calls this package's `RestoreHeldFight(carrier)`, which thaws the attackers in hold mode (keep distance, carrier invulnerable). Only after that is launch allowed.
  - Never ForceLand or relocate the docked player in this path.
- **REQ-…-8** (D-9.5, escorting): "A real fight on the spot." The carrier is in ship form; attackers spawn around it (5–8 km, ahead along its path) and the fight starts immediately. The carrier's reflex nanobots are active (W2-REFLEX).
- **REQ-…-9** (D-9.5–9.6, away): "A distress call. The carrier and the fight pause indefinitely, even for days." The carrier goes to AmbushWaiting at its current position, and a **frozen** encounter instance is created (lineup, carrier condition, location). Distress UX:
  - a Neural Net message (a vanilla NN voice id, if a suitable one exists, plus text via the text service);
  - a persistent **waypoint** set with `pub::Player::ReturnBestPath` (or the waypoint helper);
  - a neural-net log entry;
  - a toast.
- **REQ-…-10** (D-9.6): "The fight spawns when you drop out of cruise within a set distance, giving a few seconds of 'there it is, under fire'."
  - When the player is in the system, within **8 km** (config) of the frozen instance, and **not in cruise** (cruise-state event), then:
    1. thaw the attackers and spawn the carrier (solar form);
    2. attackers engage the carrier immediately;
    3. the player sees it under fire.
  - If the player leaves again, refreeze (`UnderAttack → AmbushWaiting`, W2-CARRIER-LOGIC implied edge).
- **REQ-…-11:** **outcomes.**
  - Win (all attackers destroyed or fled) → `Won` → Stopped; the carrier stays at its position, docking allowed again.
  - Carrier destroyed → `Lost` → W3-LOSS takes over.
  - Player killed → the instance freezes, as abandonment.
- **REQ-…-12** (D-8.5): **hangar auto-launch.** At ambush start, emit `HangarScramble(carrier)` for W4-WINGMEN (no-op until W4 merges).
- **REQ-…-13:** **checkpoint save** (crash-hotspot mitigation, R4 pitfall 5). Before spawning an aboard or escort ambush, write an autosave to slot "Carrier ambush" via `pub::Save`, if S-BASE/W1-CORE proved in-space saving safe. Config default on.
- **REQ-…-14:** devbridge (CONVENTIONS §4, `ambush.*`):
  - `ambush.odds <carrier>`: per-leg breakdown
  - `ambush.force <carrier> [faction]`: immediate roll success; refused with a reason while one is pending
  - `ambush.simulate <hours> [seed]`: in-game Monte Carlo on live data, deterministic for a seed
  - `ambush.state`

  Events: `ev=ambush.rolled carrier= faction= p=`, `ev=ambush.alert carrier=`, `ev=ambush.distress carrier= system=`, `ev=ambush.arrived carrier=`, plus the encounter events `ev=enc.spawn` / `ev=enc.resolved`.

## Context pack (read before writing code)

- `CLAUDE.md`, `CONVENTIONS.md` (all; §4, §8, §9, §10)
- `DESIGN.md` §1.4–1.5, §7.11, §8.5, §9, §10
- `TESTING.md` §Metrics (ambush frequency bands, survival targets), §M2, §Scenarios, §Vision
- `state/ENGINE_FACTS.md`: S-NPC (freeze/thaw, cruise state detection, SetInvincible, attitude), S-UI (NN messages, waypoints, popups)
- Contracts (ARCH-2): ambush, carrier forms, encounter, carrier model, world exposure, reflex, notifications
- `local/research/R3-game-data.md` §3.3–3.4 (route-exposure algorithm, geometry convention world = Rz·Ry·Rx·local), §8 (CD carriers by faction and level; Liberty zones ≤ d4)
- `local/research/R3-data/system_combat_presence.json`, `zone_encounters_flat.tsv`, `tools/route_exposure.py`
- `local/research/R5-sp-architecture.md` §5 (`SendNNMessage`, `PopUpDialog`, `ReturnBestPath`, `MarkObj`, `FmtStr` IDS constraint)
- `local/research/R2-engine-api.md` §6 (cruise disruptor event, `toggle_cruise`), §4.4

## Ownership

- **Owns:** `src/logic/ambush/`, `src/game/ambush/`
- **Also owns:** `data/tuning/ambush.yaml`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/logic/ambush/tests/`, `src/game/ambush/scenarios/`
- **Reads:** `src/contracts/`, `src/logic/*`, `src/game/*` (consumers only), `data/`
- **Must not touch:** everything else

## Contract

- **Consumes (ARCH-2):** ambush odds inputs, encounter lineup + freeze/thaw + outcome hooks, carrier model commands + RNG, carrier form-swap, world exposure, reputation and cargo-value queries, notifications/waypoints, platform cruise and launch events.
- **Provides:**
  - the ambush service;
  - `HangarScramble` event;
  - devbridge commands;
  - the Monte Carlo tool (host binary `ambush_mc`).

## Tasks

1. Odds model (engine-free) and the Monte Carlo over real data (deploy-time `$FLMOD_LOCAL/gen/` tables; never committed). Tune k and the class factors against the bands in `data/tuning/ambush.yaml`.
2. Roll scheduler on simulated time.
3. Three outcome paths (aboard, escort, away) with the never-forced hold for aboard.
4. Distress UX.
5. Arrival trigger (8 km, out of cruise) and refreeze.
6. Outcomes and the checkpoint save.
7. Scenarios.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:**
  - odds are 0 when I_f = 0;
  - friendly rep gives 0;
  - the cargo multiplier is capped at 1.5;
  - determinism for the same seed;
  - `ambush_pending` blocks;
  - Monte Carlo frequencies per region within the bands (report a table: region × rep class → ambushes/hour).
- **In-game scenarios:**

  | Scenario | Steps and expected result |
  |---|---|
  | `ambush_aboard_forced_stop` | Aboard in DockedTravel through Bw-space, `ambush.force <id>`. **Expect** `ev=carrier.state … state=UnderAttack`, alert shown (**[vision]** "an alert or warning message is visible in the base UI"), attackers spawned but **no carrier damage while docked for 60 s**; launch → within 10 s attackers engage (HARNESS damage events); win via `enc.resolve <id> win` (and once by real combat) → `state=Stopped`, docking allowed. |
  | `ambush_aboard_save_reload_held` | During the aboard alert (still docked), `save HARNESS_amb_held`, quit, relaunch, load. **Expect** the solar exists before any launch; the attackers are present in hold mode; zero carrier damage while docked; launch → the fight starts. |
  | `ambush_escort_on_the_spot` | EscortTravel with the player nearby, `ambush.force <id>`. **Expect** attackers within 8 km engage immediately; the carrier's reflex nanobots fire when its hull drops below its threshold. |
  | `ambush_away_distress_waits` | Carrier Away in another system, `ambush.force <id>`. **Expect** `state=AmbushWaiting`, NN message + waypoint (**[vision]** "a waypoint marker or nav path is shown"); `time.skip` 3 in-game days (5400 s) → still waiting with the carrier hull unchanged; save/load → still waiting; fly there, drop cruise at 7 km → spawn; **[vision]** "a capital ship under fire with enemy fighters nearby". |
  | `ambush_leave_refreeze` | During a thawed away fight, jump out. **Expect** `AmbushWaiting`; return → resumes with the remaining attackers and the carrier hull preserved. |
  | `ambush_friendly_space_zero` | Route Li01→Li04 with Liberty-friendly rep, `ambush.simulate 50`. **Expect** 0 ambushes. |
  | `ambush_natural_high_exposure` | `HARNESS_hostile_frontier`, docked travel forced along a high-exposure Border route, natural rolls only, `time.skip` over ≥ 3 expected-ambush intervals. **Expect ≥ 1 natural** `ev=ambush.rolled` (qualitative check only; no rate comparison in game). |
  | `ambush_one_per_carrier` | With AmbushWaiting active, force again → rejected. |

- **Metrics** (TESTING §Metrics):
  - **Frequency bands** are checked in the **host** Monte Carlo (≥ 10,000 simulated hours per region class, seeded), compared against the analytic expectation Σ(λ·Δt) within 3σ.
  - **In-game:** `ambush.simulate <h> <seed>` must reproduce the host result **exactly** for the same seed and data (determinism check), plus the qualitative natural-ambush scenario above. No in-game statistical rate comparison: about 2 expected events make that unreachable.
  - **Aboard-alert hold:** zero damage before launch.
- **Negative tests:**
  - carrier destroyed while the player is docked aboard (must be impossible: the hold-until-launch rule plus `SetInvincible` while docked);
  - F1 pause during an alert;
  - ambush rolled during an arrival reload (Plan B).

## Engine facts to rely on / verify

- S-NPC: freeze/thaw fidelity, `SetInvincible` on the solar and attackers, attitude switching, cruise-state detection.
- R2 fact 1: frozen systems.
- R4: capital death hotspot (checkpoint save).

## Pitfalls

- `FmtStr` needs IDS. Distress text uses the text service.
- `ReturnBestPath` packet sizing (R5 §5): use the helper.
- Don't roll ambushes for carriers in systems where the player currently is, if the carrier is Stopped. Only travelling carriers roll.

## Fallbacks and degrade path

1. If the never-forced hold can't keep attackers passive, despawn the attackers until launch and spawn them at launch-complete (freeze-until-launch).
2. If waypoints fail, show the NN message plus a map-marker toast with system and sector text.
3. **Degraded:** away ambushes disabled (`ambush.away = false`), so only live ambushes happen.

## Report (the agent's final message)

Per the template, plus the Monte Carlo table and the tuned values.

## Gate-time addendum

Contracts, ENGINE_FACTS ids, the TESTING §Metrics bands in force, lanes, attempt and prior notes.
