# Resume: P0-TOOLCHAIN (attempt 1, review r1 fix round 1, continued)

Read `state/briefs/P0-TOOLCHAIN.md` (your brief), then `state/briefs/RESUME-2026-10-18.md` (common resume rules, which win), then this file.

- **Start point:** `git checkout wp/P0-TOOLCHAIN`; expect HEAD `ad47bb5`.
- **Read first:** the RESUME POINT at the end of `toolchain/NOTES.md` ("Exact next steps" 1–4), then the review `state/reports/P0-TOOLCHAIN-r1.md`.
- **Remaining (per the RESUME POINT):** re-run ci.d stages 20 and 50 under the new protocol plus the stale-binary test; README; PINS.md (FLUF upstream URLs, the `msvc-redist-x86` pin, FLSDK-embedding cross-reference); the final load-proof and EH probe on both tracks; the full acceptance set from an empty `build/`; the fix report.
- **check_public:** the path in your NOTES (`.claude/worktrees/agent-af7c…/tools/check_public.py`) no longer exists. Use `$FLMOD_LOCAL/snapshots/check_public.py`.
- **GPU:** your previous load-proof/EH-probe runs may have used wined3d-sw. Re-run them on DXVK now (`FLMOD_RENDERER=auto`) and say which renderer each run used. Use your own `prefix-dev-toolchain-*` clones as before (reflink from a dev baseline, never from the play prefix while it's busy).
- **Open question for G0a/W1-PLATFORM:** app-local native MSVC runtime for FLUF (Track A). Give your recommendation with evidence (what FLUF's DLLs import, whether Wine's builtin msvcp140/vcruntime140 satisfy them, what an app-local native copy changes). If you can verify it in a run, do.
- **Engine facts:** your RESUME POINT lists facts to report for TRACK-A/B (EH rules (a)/(b), `-mstackrealign`). Put them under ENGINE FACTS LEARNED with evidence paths.
