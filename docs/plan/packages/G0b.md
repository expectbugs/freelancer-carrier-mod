# G0b: Gate, engine facts complete, Plan A/B chosen (orchestrator procedure)

- **Type:** gate (run by the orchestrator; no implementation agent)
- **Depends on:** S-BASE, S-NPC, S-UI, S-LOADOUT and S-PERF, all `MERGED` or `DEGRADED`, with reviewer re-runs done.
- **Unblocks:** ARCH-0, then Wave 1.

## Inputs

- `spikes/s_base/FINDINGS.md`, `spikes/s_npc/FINDINGS.md`, `spikes/s_ui/FINDINGS.md` (with the UI capability matrix), `spikes/s_loadout/FINDINGS.md`, `spikes/s_perf/FINDINGS.md`
- The saved reports and reviews `state/reports/S-*-a<n>.md` / `-r<n>.md` (CONVENTIONS §10)
- `docs/plan/BUILD_PLAN.md` §7 (G0b criteria), §8 (fallbacks); `docs/plan/DESIGN.md`

## Procedure

1. **Completeness check.** Every experiment in every S-* spec (S-BASE E1–E12, S-NPC E1–E13, S-UI E1–E13, S-LOADOUT E1–E7, S-PERF E1–E7) has:
   - a verdict: CONFIRMED / REFUTED / PARTIAL / "not possible + fallback chosen";
   - an evidence path that exists.

   For gaps, re-brief the spike agent (same package, next attempt) with only the missing experiments. Optional experiments (S-UI E13, S-NPC E12, E13) may be marked "skipped" with a reason.
2. **Write `state/ENGINE_FACTS.md`.** Assign final ids (`EF-BASE-1…`, `EF-NPC-1…`, `EF-UI-…`, `EF-LOAD-…`, `EF-PERF-…`). One entry per fact: statement, track, status (VERIFIED-in-game / REFUTED / PARTIAL), evidence path, consequences. Also carry over research facts that the spikes **re-verified**. Mark everything else as still UNVERIFIED: research-only, never tested in game. These facts override research from now on (AGENT_BRIEF read order item 4).
3. **Choose the base plan** (S-BASE recommendation):

   | Plan | Choose when | Record |
   |---|---|---|
   | **A** (re-point one base) | E4, E7 and E8 CONFIRMED | — |
   | **B** (per-system proxy + arrival reload) | E4 refuted and E5 CONFIRMED | Transition timing |
   | **A + E6** (Move-System on undock) | Hybrid only if E6 CONFIRMED and E4 PARTIAL | Exact limits |
   | Neither | E4, E5 and E6 all REFUTED | Apply BUILD_PLAN §8 / S-BASE fallbacks; record the static-pattern decision |
   | **Otherwise** (any other combination) | Mixed results | In order:<br>1. E5 CONFIRMED → **B**.<br>2. Else E4 CONFIRMED, with E7 or E8 PARTIAL → **A**, recording the exact limits as EF facts and FIX packages for W2-CARRIER-GAME.<br>3. Else E6 CONFIRMED → **A + E6**.<br>4. Else the "Neither" row.<br>Always record the reasoning. |

   Write the choice to the `**Base plan (S-BASE / G0b):**` field of the ledger's status list (never above line 1; CONVENTIONS §10) and to `state/DECISIONS.md`.
   - Also record the **measured fleet cap** from S-BASE E7, which must be at least 8 (D-3.1). If it's below 8, the D-3.1 requirement is degraded: write it to `state/DEGRADED.md` with the evidence.
4. **Settle the design-affecting outcomes.** Record each as a `state/DECISIONS.md` entry. Each is an input to ARCH-0 and to later briefs:
   - **Upgrade strategy** (S-LOADOUT): runtime loadouts / pre-generated / per-slot packages; hardpoint addition yes/no; shields yes/no; munition enforcement method.
   - **Escort movement** (S-NPC E2–E5): engine AI goto, or our kinematic steering; the gate recipe.
   - **Nanobot mechanism** (S-NPC E8) for the player and the carrier.
   - **Loot recipe** (S-NPC E10).
   - **UI channels** (S-UI matrix): native button yes/no; panel tech; infocard override; popups; sounds; PTT key method; rebindable keys.
   - **Scale numbers** (S-PERF): warning threshold, spawn stagger, follower jump policy, enemy-clamp patch yes/no, lane count for later waves.
   - **Voice output path:** if S-UI E7 failed, reflex voice lines need the sidecar. Update W2-REFLEX scope accordingly.
5. **Degrade check.** For any DESIGN requirement now known to be impossible, write the degraded form into `state/DEGRADED.md` with the D-id, reason, evidence and shipped alternative, and notify. Examples: capital shields impossible → D-5.3 shield upgrade dropped; munition enforcement impossible → D-8.6 uses the per-minute cost model.
6. **Archive baselines.** If the unused track's baseline isn't needed by any finding, keep it but note in `state/BUILD_STATE.md` that it is reference only. Disk is cheap; deleting it gains nothing.
7. **Gate report.** Write `state/gates/G0b.md`: the completeness table, the decisions list, the facts count, the degraded list.
8. **Notify:** `G0b passed: plan <A|B>, <N> engine facts, <k> degraded`.
9. Brief ARCH-0, with the decisions above in its gate addendum.

## Pass criteria (BUILD_PLAN §7)

- Every spike question is answered as VERIFIED-in-game, or explicitly "not possible" with the fallback chosen.
- Plan A/B is chosen.
- `ENGINE_FACTS.md` is updated with evidence paths.
