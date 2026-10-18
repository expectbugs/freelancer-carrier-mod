# Resume: P0-HARNESS (attempt 1, continued; no review yet)

Read `state/briefs/P0-HARNESS.md` (your brief), then `state/briefs/RESUME-2026-10-18.md` (common resume rules, which win), then this file.

- **Start point:** `git checkout wp/P0-HARNESS`; expect HEAD `a5bafe5`.
- **Read first:** the RESUME POINT at the top of `harness/NOTES.md`, then the attempt-1 PARTIAL report `state/reports/P0-HARNESS-a1.md`, then D103–D106 in `state/DECISIONS.md`.
- **Goal of this session:** finish attempt 1 to RESULT: DONE (every REQ in `docs/plan/packages/P0-HARNESS.md` with acceptance evidence). A reviewer audits it next.
- **Do first, now that DXVK works again:**
  1. Track A boot on DXVK (x11 and vdesk display modes).
  2. Triage the Track A `dacom.dll` stricmp crash (dacom.dll+0x5e6c, NOTES N7) with the ten-hypotheses rule. If the crash is a Track A profile problem that P0-TRACK-A should own, document the evidence and the reproduction and say so; don't sink the whole session into it.
  3. Concurrency on DXVK: 2 lanes, then 3–4. Make the safe maximum a harness setting (`LANES`), record the measured limit and any failure, and watch the GPU (common file).
- **Then:** spew allow-lists per track and renderer; **D106:** move the decomp citations out of `harness/fixtures/flhash.py` and `harness/fixtures/gen_fixture.py` into `harness/NOTES.md`; Track A fixture validity; the `lvl1_rich_fp9` fixture; the vdesk input gate; README; `selftest.sh`; check_public.
- **Leftovers:** `prefix-lane-6/7/8` are leftovers from attempt 1 and may be deleted (only after `WINEPREFIX=<it> wineserver -k`; check no process uses them).
- **Siblings running in parallel:** P0-TOOLCHAIN also launches the game (its own `prefix-dev-toolchain-*` clones, not lanes). Both of you share the X display, so always hold `lane.sh acquire --input` for any focus or synthetic input, and never touch windows whose PID isn't your lane's.
- **Orchestrator-owned files** (`tools/env.sh`, `tools/bin/`, `tools/display-awake.sh`, `tools/watchdog.sh`): propose changes in your report, with the patch, rather than editing them.
