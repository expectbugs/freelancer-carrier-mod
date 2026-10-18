# S-PERF: Spike: scale, the "army" ceiling, enemy clamp, follower jumps, leaks

- **Type:** spike
- **Wave:** Phase 0 (after G0a)
- **Depends on:** G0a, P0-DATATOOLS → **Unblocks:** G0b, W1-SPAWN (stagger rules), W4-WINGMEN, W4-HIRING (scale warning, D-11.9), W3-AMBUSH (lineup sizes).

## Goal

Adam wants no cap on fleets or hired wingmen ("if I want to hire an army I should be able to", D-1.6, D-11.5). The engine has limits. Measure where performance and stability degrade, so the mod can:

- warn at a measured threshold (D-11.9) instead of capping;
- stagger spawns;
- despawn idle followers safely.

Also determine whether the engine's "max enemies attacking the player" clamp limits large battles. And check that repeated spawning doesn't leak memory in a 32-bit process.

## Requirements

- **REQ-S-PERF-1:** Build `s_perf.dll` on `spike_platform_<track>`. Measure in-process with devbridge verbs:
  - `perf <seconds>`: frame-time stats from the tick (avg FPS, 1% low, max frame ms);
  - `vmstat`: address-space free and largest free block;
  - `count_objects`: our spawned objects alive, and all ships in the system.

  Also sample, from Linux, the wine process RSS and CPU (`ps -o rss,pcpu`) every 5 s. GPU use is optional (`nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv`).
  - **Every measurement in E1–E6 runs under `lane.sh acquire --perf`**, the exclusive perf lock (CONVENTIONS §7), so no other game instance loads the GPU or CPU. If the lock waits on other spikes, wait; don't measure without it.
  - E7 deliberately measures concurrency, so it runs its own lanes, but still under the perf lock (it holds all lanes itself).
  - Key names follow CONVENTIONS §4: `va_free_mb`, `va_largest_free_mb`, `fps_avg`, `fps_p1`.
- **REQ-S-PERF-2:** Report results as tables in `FINDINGS.md`, plus a recommendation block:
  - the warning threshold N for D-11.9;
  - the safe spawn rate (ships per second);
  - the follower despawn/respawn policy;
  - whether to patch the enemy clamp.

## Experiments

### E1: Follower scaling

Spawn N friendly fighters following the player (`DirectiveFollowOp{player, maxDistance}` after `DirectiveCancelOp`; R2 §4.4), for N = 10, 25, 50, 100, 200. Use mixed archetypes from wingman-like NPCs (e.g. `li_n_li_elite_d6`-class fighters, fc_lr/fc_ou elites). The scene is Li01 near Manhattan; the player is idle.

For each N, measure over 60 s: FPS avg / 1% low, frame max, `vmstat`, process RSS.

Also record behaviour: are followers in formation, stuck, or colliding? (Screenshot plus vision rubric: "ships are visibly following in a loose group".)

### E2: Combat scaling

For each N in {10, 25, 50, 100}: N friendlies versus N hostiles (e.g. `fc_ou_grp` d10), started by rep attitudes (`SetAttitude` −1; R2 fact 11).

Measure FPS and stability for 3 minutes, and count the ships actually firing.

Watch for the known crash: "NPC destroyed right after spawn while scripted" (Freelancer.exe 0x14661b, SP-only; R4 §0.1 #4). Spawn staggered at 2, 5, 10 and 20 ships per second, and record which rates are clean.

### E3: Enemy clamp

The default is `Act_PlayerEnemyClamp = 2, 2` (common.dll 0x18C754 / 0x18C758). A patch at common.dll 0x08E86A disables it (R4 §A1.3, KB `limit-breaking/npcs.md`; values are as the KB describes them).

1. With 12 hostiles targeting the player, count simultaneous attackers on the player, both vanilla and patched (lane-only byte patch, byte-verified).
2. Also check whether the clamp limits NPC-versus-NPC fights. It shouldn't.

Recommend patch or no patch for ambush intensity, and record it as a design input.

### E4: Followers across jumps

1. With N = 10, 25 and 50 followers, the player jumps through `Li01_to_Li02`.
2. Policy under test: despawn followers on `OnSystemSwitchOut`, then respawn them near the arrival gate on `OnJumpInComplete`, staggered. R2 fact 8: vanilla followers try to dock or jump with their leader; Discovery's drones self-destruct on jump.
3. Measure the jump-in frame spike, time to all respawned, and any crash.
4. Also try letting the engine carry followers through (followers inherit the dock event via `FollowFollowers`, R2 fact 8), and record what happens to API NPCs.

### E5: Capital battle

House-war preview: 2 battleships + 4 cruisers + 20 fighters per side (Liberty vs Rheinland navies, using unused NPC defs such as `li_n_dreadnought_d25` and `rh_n_battleship_d25`; R3 §8), with the player present.

Measure FPS and crash. Then destroy every capital in turn; capital deaths are a crash hotspot (R4 §0.1 #5).

### E6: Spawn/despawn leak check

Run 1,000 cycles of spawning 10 ships and despawning them (Vanish), measuring `vmstat` and RSS every 100 cycles.

**Pass:** the largest free block and RSS are stable within 5%. Otherwise, find the leak: FLHook master notes that spawned CObjects leak unless released (R2 §1.5), and Track A has `ResourceManager` lifetimes.

### E7: Lane concurrency

With 3 lanes running E1 at N = 25 at once, measure the FPS impact per lane. This sets the harness lane count for later waves.

## Context pack

- `docs/plan/CONVENTIONS.md` §4, §7 (authoritative)

- `docs/plan/DESIGN.md` §1 (D-1.6), §11 (D-11.5, D-11.6, D-11.9)
- `docs/plan/TESTING.md` §Metrics, §Soak
- `$FLMOD_RESEARCH/R2-engine-api.md` §0 facts 2, 8, 11; §4.4 (wingmen recipe); §1.5 (leaks)
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md` §A1.1–A1.4 (limits, crash offsets)
- `$FLMOD_RESEARCH/R3-game-data.md` §8 (factions, capital NPC defs)

## Ownership

- **Owns:** `spikes/s_perf/`.
- **Must not touch:** `spikes/track_*`, `harness/`, `docs/plan/`, `state/`.

## Contract

- **Provides:**
  - `FINDINGS.md` with performance tables;
  - the recommended warning threshold, spawn stagger rate, jump policy and clamp decision;
  - lane-count advice;
  - proposed `EF-PERF-*` facts.

## Tasks

E1 → E2 → E3 → E4 → E5 → E6 → E7.

## Acceptance

All tables are filled with measured numbers. Reviewers re-run E1 at N = 50 and E4 at N = 25, and compare against the reported numbers within 15%.

## Engine facts to rely on / verify

- **Verify:**
  - safe spawn rates;
  - follower behaviour across jumps;
  - the clamp effect;
  - leaks;
  - the per-instance cost in this Wine + DXVK setup.

## Pitfalls

- Measure at a fixed resolution (1280×720) and DXVK frame cap (`DXVK_FRAME_RATE=60`); otherwise FPS numbers mean nothing.
- Keep the player invincible during tests (`SetInvincible`), or deaths will end runs early.
- Clean up every spawned object between experiments.

## Fallbacks and degrade path

- **The engine crashes below N = 25:** recommend a "squadron" abstraction. Ships beyond the stable count stay docked or travel on paper and rotate in as others die. This is still uncapped in the roster, per D-1.6. Record it as a design decision proposal for W4.

## Report

AGENT_BRIEF_TEMPLATE format plus the `FINDINGS.md` tables and recommendations.

## Gate-time addendum

(Orchestrator: track, lane(s), attempt, commit trailer.)
