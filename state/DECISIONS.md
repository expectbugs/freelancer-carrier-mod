# Decision log

Append-only. Format:

```
## D<nnn> — <date> — <short title>
- Context:
- Options:
- Choice:
- Why:
- Decided by:
```

Decided by is one of Adam, orchestrator, or a package ID. Every sudo command is logged here too.

## D001 — 2026-10-17 — Platform: head-to-head bake-off
- **Context:** FLUF refuses to coexist with six HDE DLLs, is beta and moves fast, and is AGPL. The design doc names FLUF.
- **Choice:** Phase 0 runs Track A (FLUF) against Track B (our own thin hook DLL, HDE intact), using the BUILD_PLAN §4 checklist. If both pass, choose B.
- **Decided by:** Adam

## D002 — 2026-10-17 — Separate modded prefixes
- **Choice:** Adam's play prefix is never modified. The mod runs in `prefix-dev*`, `prefix-lane*` and `prefix-carrier`.
- **Decided by:** Adam

## D003 — 2026-10-17 — Copilot LLM
- **Choice:** Claude Code CLI on Adam's subscription, model `claude-opus-5-5`, effort `low`, with no tools, MCP or connectors. Cost is not a concern.
- **Decided by:** Adam

## D004 — 2026-10-17 — Carrier purchase UI
- **Choice:** A custom Carrier Yard panel. Upgrades can be bought at purchase or retrofitted later, and per-planet catalogs differ.
- **Decided by:** Adam

## D005 — 2026-10-17 — No level gating
- **Choice:** Carriers are buyable whenever the yard is reachable. Every market level requirement is removed; reputation requirements stay.
- **Decided by:** Adam

## D006 — 2026-10-17 — Loss drops everything
- **Choice:** Everything aboard drops as bundled crates when the carrier dies.
- **Decided by:** Adam

## D007 — 2026-10-17 — Classes and prices
- **Choice:** Tier base prices are 3M / 8M / 20M. There are multiple classes per tier (Trade Carrier, Dreadnought, balanced ones and more), with operating costs from munition and nanobot resupply.
- **Decided by:** Adam

## D008 — 2026-10-17 — Yards and looks
- **Choice:**
  - Core yards: Norfolk, Southampton, Yokohama and Oder, each with its house look.
  - Border/Edge yards: Freistadt, Kurile, Cadiz and Freeport 9.
  - Nomad yard: Gammu, in the Osiris look.
- **Decided by:** Adam

## D009 — 2026-10-17 — Cargo value and ambush odds
- **Choice:** Cargo value raises ambush odds, with the multiplier capped at ×1.5.
- **Decided by:** Adam

## D010 — 2026-10-17 — Wingmen
- **Choice:**
  - 2 crew wingmen per carrier (3 at Nomad tier), replaced after a cooldown.
  - Plus unlimited hires from bars, across skill and ship tiers, with a fee and a small daily wage, and permanent death.
  - Docking bays cap how many ships launch from a carrier; followers are uncapped.
- **Decided by:** Adam

## D011 — 2026-10-17 — Nomad boss
- **Choice:**
  - It can appear anywhere in Ew06, and seeks the player out if they fight Nomads there.
  - The group is a battleship, 2 gunboats and 8 fighters.
  - It respawns after 4 in-game days; the Gammu unlock happens once.
- **Decided by:** Adam

## D012 — 2026-10-17 — Escalation designed during the build
- **Choice:** A dedicated design agent at Wave 4 designs a player-alterable faction-influence system and writes `docs/design/ESCALATION.md` for Adam to review later. The build implements it without waiting for him.
- **Decided by:** Adam

## D013 — 2026-10-17 — Autonomy grants
- **Choice:**
  - Sudo is granted; display `:0` may be used and the screensaver paused.
  - Push notifications at milestones and blockers.
  - A watchdog supervisor; degrade and continue when a package is stuck.
  - The GitHub repo `expectbugs/freelancer-carrier-mod` is **public**.
- **Decided by:** Adam

## D014 — 2026-10-17 — Voice input
- **Choice:**
  - The mic is the Bigscreen Beyond headset.
  - Push-to-talk is numpad period (VK 110) by default. Numpad minus is bound to the hidden `USER_ZOOM_IN`; it is a config option that unbinds that.
- **Decided by:** Adam, with the orchestrator setting the default

## D015 — 2026-10-17 — Fleet, retrofit, bays, wages, hardpoints, boss respawn, gating scope
- **Choice:**
  - Fleets are allowed.
  - Retrofit requires the carrier within 10 km of the yard.
  - Docking bays cap launches; followers are uncapped.
  - Hired wingmen cost a fee plus a small daily wage.
  - Adding hardpoints to existing models is allowed.
  - The Nomad boss respawns; the unlock happens once.
  - Level gating is removed for all equipment.
- **Decided by:** Adam (accepted the orchestrator's defaults)

## D100 — 2026-10-17 — display-awake.sh: borrow the XFCE session bus
- **Context:** Under tmux the orchestrator's shell had no `DBUS_SESSION_BUS_ADDRESS`, so `xfce4-screensaver-command --inhibit` failed ("Screensaver is not running") and the slideshow screensaver was active on `:0`.
- **Options:** (a) rely on `xset` only; (b) read the bus address of the running `xfce4-screensaver` from `/proc/<pid>/environ` (read-only) when unset, and un-blank with `-d` on start.
- **Choice:** (b). Verified: `xfce4-screensaver-command -q` → inactive, inhibited by `flbuild`. Screen lock is disabled in xfconf (`/lock/enabled false`).
- **Why:** an active screensaver window would cover lane windows for screenshots and synthetic input.
- **Decided by:** orchestrator

## D101 — 2026-10-18 — Git hooks path is absolute (main checkout)
- **Context:** P0-REPO review r1 F4: the shared repo config holds `core.hooksPath=/home/user/freelancer/carrier-mod/.githooks` (absolute). Worktrees branched before P0-REPO merges have no `.githooks/` or checker of their own.
- **Options:** relative `.githooks` (each worktree uses its own copy; pre-merge worktrees run no hook) vs absolute main-checkout path (every worktree runs main's hooks).
- **Choice:** absolute. Hooks locate the checker relative to their own real path, so they use main's checker everywhere.
- **Why:** the public-safety gate must apply to every agent commit, including sibling worktrees created before the hooks existed.
- **Decided by:** orchestrator

## D102 — 2026-10-18 — Public checker scope widened (P0-REPO review r1)
- **Choice:** content sniffing for game binaries regardless of extension; YAML/JSON forms of FL data detected by FL-distinctive keys (not generic `nickname`/`faction`, so our authored YAML passes); decomp marker matched loosely in all code; a gitignored local fingerprint index of `$FLMOD_REFS` rejects copies of other mods' content (escape: `check_public: derived-from <repo> <SPDX>` header → warning); `--tree` skips only `.claude/worktrees/` (CONVENTIONS §5 amended). Infra literals added to the local blocklist.
- **Why:** the reviewer showed 94% of real HDE INI files and 99% of decomp files passed the literal spec rules.
- **Decided by:** orchestrator

## D103 — 2026-10-18 — GPU fault: no gamescope; OpenGL (wined3d) lane fallback until Adam resets the GPU
- **Context:** P0-HARNESS reported every Vulkan device creation failing since 05:28Z. Orchestrator VERIFIED in `/var/log/kern.log` (world-readable): `00:28:03 NVRM: Xid 51, pid=1376925, name=Xwayland, BAD_TSG encountered on runlist 0, error code 5`, then `Xid 154, GPU recovery action changed from 0x0 (None) to 0x1 (PF FLR)`; since then `GspRmAlloc failed … NV_ERR_RESET_REQUIRED` for class 0xc56f (Ampere GPFIFO channel) several times a minute. `nvidia-smi -q`: "GPU Recovery Action: Reset". `vulkaninfo`: vkCreateDevice ERROR_INITIALIZATION_FAILED. OpenGL works: `glxgears` 208 FPS on the RTX 3090 (direct rendering). No lavapipe ICD installed. The Xwayland was gamescope's (P0-HARNESS headless-lane evaluation); two Track A runs had just crashed (dacom.dll+0x5e6c) and the runner `wineserver -k`'d the lane while gamescope was presenting.
- **Hypotheses for the fault (ten-explanations rule):** (1) killing a lane mid-present left gamescope's Xwayland submitting on a torn-down TSG; (2) gamescope `vulkan_remake_swapchain` after DXVK device loss hit a driver bug; (3) NVIDIA open kernel module 615.71.09 bug with nested Xwayland + DRI3/explicit sync; (4) channel/TSG leak after ~40 rapid gamescope launches; (5) concurrent CUDA contexts (sidecar Whisper smoke, Frigate ffmpeg/onnx) plus Vulkan on the same runlist; (6) GSP firmware fault triggered by an invalid submission from the crashed game's DXVK; (7) a gamescope + NVIDIA known instability unrelated to our crash; (8) Xwayland and the main X server both driving modeset on one GPU; (9) thermal/power transient (GPU at 61 °C, unlikely); (10) latent hardware fault (prior Xid 31/109 from Steam/VR in June–July show the GPU has faulted before under other compositors). Most consistent with all data: (1)/(2)/(7) — the fault process was gamescope's Xwayland seconds after a lane kill. No experiment is safe to run without a reset.
- **Options:** (a) reboot or `nvidia-smi -r` (needs X stopped) — not pre-authorized (AUTONOMY §1/§2: no service changes; it would kill Adam's desktop and Frigate's GPU work); (b) halt — not a halt condition (AUTONOMY §4); (c) continue host-side work, and run lanes on Wine's OpenGL d3d8/d3d9 (wined3d) until Adam resets; re-run every DXVK-dependent acceptance item afterwards.
- **Choice:** (c). gamescope is banned on this host for the build. The harness gets a renderer switch (DXVK when a Vulkan device can be created, otherwise wined3d) and every run records which renderer it used. Gate evidence gathered on wined3d is marked provisional for rendering-chain items (overlay hook through dxwrapper→ReShade→DXVK, FPS, VA headroom) until re-run on DXVK.
- **Decided by:** orchestrator. Adam notified (`state/NOTIFICATIONS.md`) to reboot when convenient.

## D104 — 2026-10-18 — Adam's report: misclicks into Steam; workspace switch as a GPU-fault trigger
- **Context:** Adam (present at the terminal, 00:45) reported agents occasionally clicking his Steam window. About 00:25 he closed the Steam window (client still in the tray) and switched XFCE to an empty virtual desktop (Ctrl-Alt-Right). He suggested the switch may have caused the GPU fault.
- **Assessment:** the timing fits. Two Track A crashes at 00:27:25/00:27:44, gamescope's `vulkan_remake_swapchain` assert, then Xid 51 from gamescope's Xwayland at 00:28:03. A workspace switch unmaps the windows on the old desktop, which can force swapchain rebuilds and D3D device loss. This joins the D103 hypotheses as (11), and is the leading trigger candidate; the faulting process was still gamescope's Xwayland. The GPU state itself is real and persists (vkCreateDevice still failing at 00:44:50).
- **Choice:** P0-HARNESS must verify the active window PID, the pointer target and `_NET_WM_DESKTOP` before every synthetic input, and refuse otherwise. Never switch desktops or move windows. Lanes run on the current desktop (desktop 2).
- **Decided by:** orchestrator, after Adam's report.

## D105 — 2026-10-18 — Lane renderer while the GPU is faulted: wined3d on Mesa llvmpipe (amends D103)
- **Context:** P0-HARNESS VERIFIED that hardware wined3d (`d3d8=b;d3d9=b`) also fails on the faulted GPU: GL_OUT_OF_MEMORY and GLXBadContextState, with 18 NVRM GPFIFO RESET_REQUIRED lines per launch. So new hardware GL contexts are broken too, not only Vulkan.
- **Choice:** `FLMOD_RENDERER=auto|dxvk|wined3d|wined3d-sw`. `auto` means dxvk when a Vulkan device can be created, otherwise `wined3d-sw` (`__GLX_VENDOR_LIBRARY_NAME=mesa LIBGL_ALWAYS_SOFTWARE=1`), which touches no NVIDIA channel (0 NVRM lines). VERIFIED: Track B boots, loads HARNESS_new_story, launches to space at 68.7 fps average and quits clean (run 20261018-055223-lane1-loadrep-HARNESS_new_story-B-1). `LANES=2` until the GPU is reset. gamescope has been removed from the harness. Every synthetic input passes the PID/desktop/geometry gate (commit 9c6649a on wp/P0-HARNESS).
- **Input trace:** the likely Steam misclick was an unguarded click at 05:06:48Z (run …050637-lane1-load-HARNESS_new_story-B), before the gate existed.
- **Decided by:** orchestrator, on P0-HARNESS evidence. A reboot or reset still needs Adam (options offered 00:5x).

## D106 — 2026-10-18 — Branch history that fails check_public: squash-merge; decomp citations move out of code
- **Context:** P0-REPO fix round 1 tightened the decomp rule: it now matches the reference repo's name loosely in every code file outside docs/. Its sibling scan (`--commits=main..wp/*`) finds:
  - wp/P0-REPO's own early commits (95db516, 257ef54), whose old checker spelled the name literally;
  - code comments in wp/P0-DATATOOLS (`tools/fltools/hash.py`, `ini.py`) and wp/P0-HARNESS (`harness/fixtures/flhash.py`, `gen_fixture.py`) citing the decompilation as a reference.

  The pre-push hook checks every commit being pushed, and AUTONOMY forbids rewriting main.
- **Options:**
  - (a) narrow the rule to allow citations in code;
  - (b) packages move citations out of code;
  - (c) packages rewrite their own branches;
  - (d) the orchestrator squash-merges any branch whose intermediate history fails `--commits`.
- **Choice:** (b) + (d).
  - Code comments say "see NOTES.md §x" instead. Citations of reference sources live in the package's NOTES.md or docs. The rule stays strict, so copied decomp headers are still caught.
  - Merges stay `--no-ff` by default (BUILD_PLAN §5). When `check_public --commits=main..wp/<ID>` fails only on intermediate commits and the tip is clean, the orchestrator uses `git merge --squash` + a commit named `merge <ID>: <title> (squashed: intermediate history failed check_public)`.
  - The wp branch stays local for reference (never pushed).
  - This is not a rewrite of main.
- **Why:** keeps the strongest leak gate without blocking the first push, and needs no history rewriting on main.
- **Decided by:** orchestrator

## D107 — 2026-10-18 — dacom.ini marker clash: harness writes its block as an fltools.patch unit
- **Context:** P0-DATATOOLS f1 open question. `harness/lib/deploy.py` (P0-HARNESS) writes its own `[Libraries]` block into `EXE/dacom.ini`; `gen` deploy (fltools.patch, P0-DATATOOLS) manages marker regions in the same file. Two independent writers to one file can strip or duplicate each other's blocks. Reading `patch.py`: `plan_overlay_patches` makes the install carry exactly gen's units, so a gen redeploy would strip any foreign unit.
- **Options:** (a) two separate marker schemes and hope they never interleave; (b) one shared patch state: the harness writes a `harness.*` patch unit via `fltools.patch.patch_file`, and overlay planning preserves `harness.*` units; (c) the harness stops editing dacom.ini (not possible for Track B, which loads our DLL through `[Libraries]`).
- **Choice:** (b). P0-DATATOOLS adds the `harness.*` preservation (with tests) now, before its round-2 review. The harness switches `deploy.py` to the patch unit after both packages are merged (P0-HARNESS fix round, or W1-HARNESS if HARNESS has already merged).
- **Why:** one writer of record per file; reversible undeploy stays exact.
- **Decided by:** orchestrator

## D108 — 2026-10-18 — Public checker: authored-data escape for R5, word-bounded blocklist entries, api_key in assignment form
- **Context:** P0-REPO review r2. R5 (bulk FL data) blocks our own authored data that legitimately uses FL-native key names (`fcm.world.v1` world.json fixtures with `ids_name`/`dock_with`; NPC definitions with `ship_archetype`/`state_graph`/`npc_class`; carrier YAML with `hit_pts`/`nanobot_limit`). D102 assumed our YAML would avoid such keys, but our own schemas use them. Also: the 6-character tailnet-host blocklist entry is a substring of ordinary words; `api_key` inside any identifier (e.g. a test name) is flagged as a credential.
- **Options (R5):** rename every key in our schemas away from FL names (fights the data model and the generators); loosen R5 globally (reopens the r1 leak); a reviewable per-file escape header.
- **Choice:**
  - R5 escape: a file whose first 5 lines contain `check_public: authored-data <reason>` gets R5 reported as a WARNING instead of a violation, only under `data/`, `tests/`, `harness/`, `gen/`, `docs/spec/` and `src/**/tests/`. It never overrides R1, R2, R4 or R7. CONVENTIONS §12 is amended after the P0-REPO merge to require the header (with a one-line reason) on authored files that use FL-native keys in bulk, and reviewers check the reason.
  - Blocklist entries prefixed `w:` match as whole words (case-insensitive, word boundaries; also in paths and in UTF-8/UTF-16LE binary content). The short tailnet-host entry becomes a `w:` entry.
  - The `api_key` credential marker matches assignment/value form only (`api_key = …`, `"api_key": …`, `api_key: …`, `API_KEY=…`), not any identifier containing it. Real secret shapes are still matched everywhere.
- **Why:** keeps the strong r1 gate on pasted game data while letting honest packages commit their own schemas; every escape is visible in review and in `git grep`.
- **Decided by:** orchestrator

## D109 — 2026-10-18 — P0-HARNESS: two blocked acceptance items carried to their owners
- **Context:** P0-HARNESS attempt 1 ended PARTIAL with every REQ implemented. Two checks cannot run inside the package: (1) loading any `.fl` save on Track A crashes ~2 s after the menu (FLUF core alone reproduces it; the same install without FLUF.dll is fine; NOTES N7); (2) the post-campaign fixture's gate and bar checks need a devbridge `target`/`dock` verb, which W1-SPAWN/W1-CORE own (NOTES N15).
- **Options:** keep HARNESS open until both resolve (blocks P0-TRACK-A/B, which need the harness); degrade; or review and merge HARNESS with the two items formally carried.
- **Choice:** carry them. (1) belongs to P0-TRACK-A, whose spike scope is exactly "make Track A boot and load a save" (§4 items 1–2); its brief includes NOTES N7 as the starting point. (2) becomes an acceptance item for W1-HARNESS (fixture owner from Wave 1) once W1-SPAWN's `target` verb lands; until then the post-campaign fixture is marked "loads, no story script; gate/bar UNVERIFIED". The reviewer judges everything else on its merits.
- **Why:** both items are genuinely outside the package's owned paths; holding HARNESS would stall the whole bake-off.
- **Decided by:** orchestrator

## D110 — 2026-10-18 — EH probe as a standing acceptance check; play_prefix_busy normalises WINEPREFIX
- **Context:** P0-TOOLCHAIN f2/r3. Wine's builtin vcruntime140 kills the process on one C++ EH pattern unless `-mstackrealign` is set; the probe (`toolchain/ehprobe.sh`) is the only runtime proof, and CI can't run Wine. The r3 reviewer also found that prefix-in-use checks compared raw `WINEPREFIX` strings, so `//`, `/./` and `x/..` spellings hid a user.
- **Choice:**
  - `toolchain/ehprobe.sh --crt both` is part of the acceptance of P0-TRACK-A, P0-TRACK-B and W1-PLATFORM, and is re-run by any package or reviewer whose change touches `toolchain/`, `cmake/` or compile/link flags. Stage 10's static `check_flags.py` is the CI-side guard.
  - `tools/play_prefix_busy.sh` (orchestrator-owned) now normalises each process's `WINEPREFIX` with `realpath -m` before comparing (tested: 4 alternate spellings detected as busy; a dev prefix is not). `toolchain/prefix_clone.sh` gets the same fix (P0-TOOLCHAIN polish N2).
- **Why:** the EH failure mode is silent until a hook throws in game; a probe in every platform acceptance keeps it caught. Safety checks on the play prefix must match the guards' own path semantics.
- **Decided by:** orchestrator
