```
PACKAGE: P0-HARNESS   ATTEMPT: 1   RESULT: PARTIAL (stopped at the orchestrator's checkpoint for the GPU-reset reboot)
BRANCH: wp/P0-HARNESS @ a5bafe5 (worktree clean; no lanes held, no game or background processes)
```

**SUMMARY:** Most of the harness is built and the core loop works in game. On Track B a run boots, loads a fixture through the devbridge, launches into space and quits cleanly with verdict PASS. That was shown on both DXVK and the software renderer.

- The GPU faulted at 05:28Z: kernel log Xid 51 from gamescope's Xwayland, after which new Vulkan and GL channels are refused until a reset.
- Since then, game runs use Wine's builtin d3d8/d3d9 on Mesa llvmpipe, which doesn't touch the GPU.
- gamescope is banned (D103), so headless lanes are **NOT VIABLE** (REQ-9).

**FILES:** everything is under `harness/`. Full status is in the RESUME POINT section at the top of `harness/NOTES.md`.

**TESTS:**
| Test | Result | Evidence |
|---|---|---|
| `test_guards.sh` | PASS 57/57; the success case was skipped because no prefix existed yet | run in session |
| `test_lanes.sh` | PASS 18/18, run once | `local/testruns/p0-harness-evidence/test_lanes.txt` |
| `test_display_awake.sh` | PASS 14/14; the live inhibitor was untouched | `p0-harness-evidence/test_display_awake.txt` |
| verdict/triage unit tests | PASS 37 | — |
| fixture generator tests | PASS 49 | — |
| devbridge doctest | PASS 23 cases | — |
| devbridge client pytest | PASS 36 | — |
| `baseline.sh verify A` / `verify B` | PASS / PASS | — |
| devbridge in game on B (DXVK) | PASS, all 9 commands acked, clean quit | `…-050441-lane1-devbridge-smoke-B` |
| B: load new_story, launch to space | PASS on DXVK | `…-052136-…` |
| B: same, software renderer | PASS, 68.7 fps in space | `…-055223-…` |
| Track A plain boots | 10/10 PASS | `p0-harness-evidence/boot_rep_A_x10.txt` |
| A with selftest DLL + `--save-file` fixture | CRASH 3/3 | `…-052402-…-A` |
| Spew allow-lists, concurrency, A fixture validity, selftest.sh | not run (blocked by the GPU fault, then the checkpoint) | — |

**DECISIONS:**
- Track A lanes run with `-w`: FLUF rewrites the keep-running-unfocused bytes at 0x1B264C at startup otherwise, so our file patch is skipped on A.
- `baseline.sh fluf-init` answers FLUF's first-run "No ship classes" dialog through the input gate.
- Each lane is identified by `_NET_WM_PID`. Track A gets a per-lane Wine virtual desktop because FLUF forces the game to the desktop size.
- Renderer is `auto|dxvk|wined3d|wined3d-sw`, recorded in every `verdict.json`. Spew allow-lists are kept per track and per renderer.
- `LANES=2` while the GPU is degraded.
- Lanes export `FLCOPILOT_FORCE_TEST_PROFILE=1`.
- Hang minidumps are capped at 30 s.

**ENGINE FACTS LEARNED (all VERIFIED):**
- The game window carries `_NET_WM_PID` = the lane's Freelancer.exe pid.
- `LoadGame` at 0x5B2C70 works from the main menu (devbridge log of the B load runs).
- Fixture file name rule `%x.fl` of CreateID(description) works.
- Under Wine WoW64 the non-LAA Freelancer.exe gets a 4 GB address space (`va_max=0xFFFEFFFF`).
- FLUF sizes the game to the desktop and ignores PerfOptions.
- FLUF's log is in `My Games/Freelancer/fluf.log`.
- FLSpew is truncated each launch; on Track A every line gets two timestamp prefixes.
- Synthetic keys reach the game: F1 pauses and the state verb shows `paused=1`. Mouse clicks are unreliable because the game draws its own cursor from relative motion, about 1.034× the pointer's movement, and it moves the X pointer itself.

**OPEN QUESTIONS / BLOCKERS:**
- The GPU needs a reset; the reboot is pending.
- The input-to-Steam incident is traced in NOTES.md N9. The most likely cause is an unguarded click at 05:06:48Z while Steam was stacked over the game's tile. Every input step now goes through a strict gate that refuses and logs rather than guessing.
- Proposed patch for `tools/bin`: add guard symlinks for `notepad`, `winefile` and `winemine`, which are on PATH unguarded.

**KNOWN ISSUES:**
- Track A crashes at the main menu in dacom's exported `stricmp`, called with the same garbage pointer every time. Ten hypotheses are in NOTES.md N7; the triage re-run on DXVK is the first job after the reboot.
- The new virtual-desktop launch path in `run.sh` is untested, and the input gate doesn't accept the virtual desktop window yet.
- An orphaned screenshot process froze X for about 11 minutes (04:42–04:53Z). That is fixed: every capture now has a hard kill timeout.
