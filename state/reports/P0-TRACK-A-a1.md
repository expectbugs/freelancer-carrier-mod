```
PACKAGE: P0-TRACK-A   ATTEMPT: 1   RESULT: PARTIAL (paused by orchestrator)
BRANCH: wp/P0-TRACK-A @ 855b285 (tree clean, check_public --tree OK)
```

**SUMMARY:** The item 2 hard-veto blocker is fixed. The N7 / EF-008 crash came from two patches writing the same server.dll bytes: FLUF core's restart-file patch at +0x6900F, then flplusplus' `always_regenerate_restart_file` patch at +0x69012, which corrupted FLUF's `lea`. Seven checklist items pass, six are partial or not run. I hold no lanes or locks, no game is running, and GPU Recovery Action is None.

How I found the crash cause (VERIFIED): an in-process crash probe in `spike_a` logged the real caller and the rewritten bytes, and the arithmetic reproduces all three garbage pointers. Setting the flplusplus option to `false` fixes it, and FLUF still regenerates Restart.fl itself.

**FILES:**
- `spikes/track_a/`: platform lib (`platform/*.cpp`), `include/spike_platform.hpp` (byte-identical to Track B's) plus the `spike_platform_a.hpp` extensions, `module/spike_a.cpp`
- Scripts: `deploy_a.sh`, `scenario_a.py`, `bootloop_a.sh`
- `scenarios/a01–a10`, `a12_*`; `NOTES.md`, `RESULTS.md`, `LOST_FEATURES.md`
- `harness/scenarios/bakeoff_vmstat.yaml` (committed here first; Track B copies it)

**TESTS** (all under `/home/user/freelancer/carrier-mod/local/testruns/`):

| # | Result | Evidence |
|---|---|---|
| 1 | PASS | `20261018-102342-lane1-a01_boot` |
| 2 | PASS | `20261018-102741-lane1-a02_load` |
| 3 | PASS | `20261018-102837-lane1-a03_hooks` |
| 4 | PARTIAL | game time advances docked and in space; F1 freeze not shown (`20261018-105102-lane1-a04_tick`) |
| 5 | PARTIAL | overlay renders, my vision check says yes (`…-101708-…-a-explore4/shots/overlay2.png`); click not run |
| 6 | PARTIAL | button renders at Manhattan; clicks not run |
| 7 | PARTIAL | block/unblock via devbridge works (`…-101518-…-a-explore3`); real-click part not run |
| 8 | PASS | `20261018-103005-lane1-a08_undock`: spawn 3.1 m from target |
| 9 | PASS | `…-103055/103118/103135-…-a09_save_load-r1..r3`, same n after restart |
| 10 | NOT RUN | — |
| 11 | NOT RUN | — |
| 12 | PASS | as shipped 1643 MB (`…-103216-…-bakeoff_vmstat`); true 2 GB space 352 MB (`…-103557-…`); LAA-flag and stripped variants not run |
| 13 | PASS | `LOST_FEATURES.md`: 15 replaced, 24 lost, 7 unknown, 1 conflict |

ehprobe `--crt both`, the FLUF import check and the catch-funclet scan are NOT RUN.

**DECISIONS:**
- The Track A profile needs `always_regenerate_restart_file = false`; lanes apply it through `deploy_a.sh`.
- Load hook = entry detour of `IServerImpl::CharacterSelect`. FLUF fires no module event for it in single player.
- Save hook = entry detour of `PlayerData::save`.
- The undock override acts only inside the player's own PlayerLaunch and uses the dock's `launch_pos()`.
- NavBar clicks are caught through the button class's Execute vtable slot. A per-instance vtable copy crashed on launch.
- Events use the CONVENTIONS seed names, with `hook=<spec name>`.

**ENGINE FACTS LEARNED** (VERIFIED, evidence in NOTES A1–A4):
- FLUF core and flplusplus patch the same restart-file bytes and crash together (A1).
- HDE's `HudFacility.dll` re-patches 0x59E1B8, 0x55BB26 and 0x59DC09, so FLUF's vanilla-UI events never fire (A3).
- FLUF passes an uninitialised transform to `OnServerShipUndock`, for NPC launches too (A4).
- This Proton build forces large-address-aware (`va_max` 0xFFFEFFFF) unless `WINE_LARGE_ADDRESS_AWARE=0`.
- A docking ring's launch path overrides the spawn point after the first frame (A4).

**OPEN QUESTIONS / BLOCKERS:**
- Start-up stall before the menu (A5): 6 on a long-lived lane prefix, 0 of 8 on a fresh clone. Leading hypothesis is state accumulating in the prefix (UNVERIFIED).
- XTEST F1/Escape pass the input gate but never reach the game on vdesk lanes (A6, 10 hypotheses).
- One `quit_no_exit` on the first boot of a fresh prefix (A7).
- Proposals for other owners: `baseline.sh` should apply the A1 setting; `RUN_WINEDEBUG` can't be overridden from the environment; `@click` has no `--warp` option.

**KNOWN ISSUES:** A `[CockpitCamera] znear` warning shows up in every space run. Track A's spew allow-list only covers the menu.

**RESUME POINT** (top of `spikes/track_a/NOTES.md`), next steps in order:
1. A6: try the same keys on a Track B x11 lane, then trace with `+key,+dinput`. Fallback evidence for item 4: the engine's own pause (`SetPaused` 0x42D6F0).
2. Run the input scenarios a05, a06 and a07 and judge their screenshots.
3. Item 11: three runs without `spike_a`, build an A allow-list, check every item run against it.
4. The two remaining item 12 variants.
5. The a10 soak on a fresh lane.
6. Toolchain items.
7. Final RESULTS.md and report.

Run `scenario_a.py` without `--lane` so each scenario gets a fresh lane.
