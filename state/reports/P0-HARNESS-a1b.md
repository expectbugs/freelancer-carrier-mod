I've finished attempt 1 as **PARTIAL**. Everything is implemented and the self test passes, but two acceptance checks can't run yet:

- **Track A save loading** is blocked on P0-TRACK-A: any save file at all crashes the HDE + FLUF install.
- **The post-campaign gate check** has no way to target the gate yet.

The GPU stayed healthy all session (`Recovery Action: None` after every run, no new driver errors in the kernel log since the reboot).

**1. Fix report**

There's no review yet, so this covers the resume-brief items.

| Item | What changed | Test / evidence | State |
|---|---|---|---|
| Track A boot on DXVK | vdesk mode: menu reached. x11 mode: menu reached, but FLUF fills the whole screen and ignores `windowsize` | `…-063851-…-boot-A-dxvk-vdesk`, `…-063920-…-x11` | DONE |
| Track A crash (`dacom.dll+0x5e6c`) | Narrowed: **any `.fl` save file**, even the game's own `newplayer.fl`, crashes A about 2 s after the menu. FLUF core with no modules is enough; the same install without FLUF.dll is fine. Handed to P0-TRACK-A (NOTES N7) | 15 runs, `…-n7-*` | DONE (triage) |
| Concurrency on DXVK | 1–4 lanes all PASS, ~194–199 fps each. Set `LANES=4`, and `LANES_SW=2` for the software renderer | NOTES N11, `conc-BBBB4fix-*` | DONE |
| Spew allow-lists | Added `spew_allow_{A,B}_{dxvk,wined3d-sw}.txt`; A covers boot to menu only, because of the crash above | `baseline/README.md` | DONE |
| D106 citations | Moved out of `flhash.py` and `gen_fixture.py` into NOTES N12 | check_public tree clean | DONE |
| vdesk input gate | Gate accepts exactly `lane<N> - Wine Desktop` owned by the lane's explorer.exe | `…-071015-lane3-vdesk-input-gate-A` | DONE |
| lvl1_rich_fp9 fixture | Loads docked at Ew04_01_Base with 5M credits | selftest `b_fp9` | DONE (rank 1 is set in the save; there's no in-game readback) |
| Post-campaign validity | Fixture loads and no story script starts (the story control drops straight into a cutscene) | NOTES N15 | PARTIAL: gate and bar checks not verified |
| README, selftest.sh | Written | selftest PASS | DONE |
| Leftover lanes 6/7/8 | Deleted; `test_lanes.sh` now cleans up after itself | — | DONE |

**2. Standard block**

```
PACKAGE: P0-HARNESS   ATTEMPT: 1   RESULT: PARTIAL
BRANCH: wp/P0-HARNESS @ 181ebcc (tree clean)
```

**SUMMARY:** All requirements are implemented. `harness/selftest.sh` gives PASS: 6 steps pass and 2 are BLOCKED (the Track A save load and the gate check). The session found and fixed a real bug in concurrent runs (below); every concurrency result in this report was re-run after the fix.

**FILES:** `harness/` only. New: `selftest.sh`, `README.md`, `fixtures/selftest/*.yaml`, `baseline/spew_allow_*_*.txt`. Changed: `lane.sh`, `config.sh`, `lib/common.sh`, `lib/runner.py`, `lib/xinput.py`, `baseline.sh`, `verdict.py`, tests, `NOTES.md` (N3, N5, N7, N10–N16).

**TESTS:**
- Selftest — PASS (6 PASS, 2 BLOCKED) — `local/testruns/20261018-073121-selftest/summary.md`
- `test_guards.sh` — PASS 61/61, including the success case (VERIFIED)
- `test_lanes.sh` — PASS 20/20, including the `--perf` checks (VERIFIED)
- `test_display_awake.sh` — PASS 14/14 (VERIFIED)
- pytest — PASS 126; devbridge doctest — PASS 23/23 (VERIFIED)
- `baseline.sh verify A` / `verify B` — PASS 23 / 15, play prefix unchanged (VERIFIED)
- Window identification — 5/5 two-lane runs with distinct windows, each at its slot — `p0-harness-evidence/window_id_2lane_runs.txt`, NOTES N16 (VERIFIED)
- Track A fixture load — SKIP, DEFERRED(P0-TRACK-A), NOTES N7
- Gate check — SKIP; needs a devbridge `target` verb (W1-SPAWN), NOTES N15
- check_public `--tree` — exit 0 (VERIFIED)
- check_public `--commits=main..HEAD` — FAIL only on intermediate commit a5bafe5, the old citations; tip is clean, so squash-merge per D106

**DECISIONS:**
- `LANES=4` on DXVK. `LANES_SW=2` on the software renderer; acquire picks the lane count by renderer. Don't mix software and DXVK lanes.
- `lane.sh acquire --renderer` records `LANE_RENDERER`, which the runner uses by default.
- Never combine `xdotool search --pid` with `--name`; check the pid per window.
- No automatic fallback from a failed devbridge load to menu clicks.
- A start-up stall where the game is still using at least 25% of a core counts as slow start-up, not a hang. The runner now records CPU time per second.
- Crash text logged after a hang is detected is attributed to the hang dump, so the verdict is HANG, not CRASH.
- A runner exception or failed step can never produce PASS.

**ENGINE FACTS LEARNED:**
- `xdotool search --pid P --name N` ORs the two conditions: two different pids each returned both games' windows. VERIFIED, `p0-harness-evidence/xdotool_search_pid_probe.txt`.
- On Track A the frame function at 0x5B2890 already starts with a jump, so the selftest DLL can't hook it there. VERIFIED, `…-064006-…-E1` devbridge log.
- Any save file plus FLUF core crashes A at the menu. VERIFIED, NOTES N7.
- With the selftest DLL, the game's frame rate is ~198 fps even with `DXVK_FRAME_RATE=60` set. VERIFIED. I don't know why the limiter doesn't apply (UNVERIFIED).
- `T` selects nothing because the contact list is empty under its default filter. VERIFIED, `…-071622-…/shots/target.png`.
- In space, after the cursor-reckoning moves the pointer ended outside the game window, so the gate refused the click on the gate. VERIFIED.
- The post-campaign fixture's "last objective" key shows "DOCK WITH PLANET TOLEDO", an objective from mission 12. VERIFIED; whether it's actually active is UNVERIFIED.

**OPEN QUESTIONS / BLOCKERS:**
- P0-TRACK-A owns the crash in NOTES N7. Leading suspect is FLUF's patch to how saves are read (UNVERIFIED).
- The gate and bar checks need a devbridge `target` or `dock` verb; then run `selftest.sh --with-gate`.
- If the M12 objective turns out to be live, the fallbacks in the spec apply (MissionNum 41, then the open-SP trigger effects).
- No orchestrator-file patches needed: the guard gap I reported last time (`notepad`, `winefile`, `winemine`) is already fixed in `tools/bin`.

**KNOWN ISSUES:**
- Under heavy mixed load (two software-renderer instances plus 3–4 DXVK games, load average 15–18), 3 games stalled before the menu, right after ReShade's shader compiler loaded. A fourth crashed after loading because Vulkan pipeline creation failed. None of this happened on a quiet host; cause UNVERIFIED (NOTES N14).
- `winedbg --minidump` against a hung game crashed it and produced no dump (seen once).
- In x11 mode Track A covers the whole screen, so A must use vdesk mode.

Everything is in `harness/` on the branch; start with `README.md`, and the full experiment record is in `NOTES.md`.
