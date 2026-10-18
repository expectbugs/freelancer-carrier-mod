# G0a: Gate, platform track choice (orchestrator procedure)

- **Type:** gate (run by the orchestrator; no implementation agent)
- **Depends on:** P0-TRACK-A and P0-TRACK-B both `MERGED` or `DEGRADED`. Their reviewers have re-run items 2, 3, 7, 8 and 9 on each track.
- **Unblocks:** S-BASE, S-NPC, S-UI, S-LOADOUT, S-PERF.

## Inputs

- `spikes/track_a/RESULTS.md`, `spikes/track_b/RESULTS.md` (13-item tables with evidence paths under `$FLMOD_TESTRUNS`)
- `spikes/track_b/PATCHES.md`; `spikes/track_{a,b}/LOST_FEATURES.md` (item 13)
- The saved reports and reviews `state/reports/P0-TRACK-{A,B}-a<n>.md` / `-r<n>.md` (CONVENTIONS §10)
- `docs/plan/BUILD_PLAN.md` §4 (decision rule) and §8 (fallbacks)

## Procedure

1. **Verify the evidence exists.** For every item marked PASS, open its `verdict.json` and check `verdict == PASS`. Check the HARNESS lines the item names are present. Delegate this to a small checker agent if the files are many.
   - An item without evidence counts as **FAIL**.
   - **Item 12** is compared on identical evidence: both tracks ran the shared scenario `harness/scenarios/bakeoff_vmstat.yaml`. Read `va_largest_free_mb` from each `verdict.json`; PASS means ≥ 300.
   - **Item 13** has no game run. Its evidence is `LOST_FEATURES.md`: PASS if complete, with every removed DLL's features listed and classified (Track B: "none", with the dacom/freelancer.ini diff). What Track A loses is weighed in step 3's justification text, not in the score.
2. **Score.** Each item counts 1, except items **3, 7, 8 and 9**, which count **2** (BUILD_PLAN §4). PARTIAL counts half.
   - Total possible: 9 items × 1 + 4 items × 2 = 17. Items 1–13 apply to both tracks, with Track B's item 13 being "no HDE feature lost".
3. **Decide** (BUILD_PLAN §4, verbatim rule):
   - If **both pass** every item, choose **B**: it keeps HDE whole and removes the moving dependency.
   - If **only one passes**, choose that one.
   - If **neither passes fully**, choose the higher weighted score. **Tie → B.**
   - The failing items of the chosen track become follow-up tasks: add them to ARCH-0's addendum and to W1-PLATFORM's scope.
4. **Hard veto.** A track whose item 1 (boot) or item 2 (load a save) fails can't be chosen unless the other track fails them too. If both fail them, **HALT** (AUTONOMY §4: the game can't boot with the mod) after one `FIX-*` attempt per track.
5. **Address space on Track A.** If A is chosen, record the mitigation baseline A now uses (LAA flag, stripped FLUF, or stable 2.0). Re-run `harness/baseline.sh verify A`.
6. **Record:**
   - `state/gates/G0a.md`: both tables, the scores, the rule applied, the decision, and follow-up items.
   - `state/DECISIONS.md`: a "Platform track = A|B" entry with reasons.
   - `state/BUILD_STATE.md`: set the `**Track (G0a):**` field in the status list to `A` or `B`. **Never insert lines above line 1 or rewrite it**, except to change the status (CONVENTIONS §10).
7. **Lane config.** Set the harness default track: `harness/config/default_track` (one line, `A` or `B`; the orchestrator writes it directly and commits). Keep both baselines until G0b, in case a spike needs to cross-check.
8. **Notify** (push notification): `G0a passed: track <X> (A <score>/17, B <score>/17)`.
9. Start the S-* spikes in parallel (BUILD_PLAN §5), using `spike_platform_<x>` as their base library.

## Pass criteria

- A decision is recorded with the full evidence tables for both tracks (BUILD_PLAN §7).
- The decision follows the rule mechanically. Any deviation needs a DECISIONS entry citing the "never changes after G0a unless…" clause.

## After G0a

The track never changes, unless a later package proves the chosen track cannot deliver a must-have. Then: log a decision, re-run that bake-off item on the other track, and switch only the platform layer (BUILD_PLAN §4).
