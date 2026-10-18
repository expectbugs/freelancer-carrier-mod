# Harness (P0-HARNESS)

The build tests itself in the real game: disposable per-test Wine prefixes ("lanes") cloned from two dev baselines,
a deploy step, a run driver that launches Freelancer, drives it through the file-based devbridge, collects
evidence and decides a verdict, plus fixture saves, crash triage and screenshots.

Working notes, hypotheses and every experiment behind the decisions below are in [`NOTES.md`](NOTES.md) (sections
`N<n>`). Evidence lives under `$FLMOD_TESTRUNS` (never in the repo).

## Safety rules (built in)

- Every script starts with `source /home/user/freelancer/carrier-mod/tools/env.sh`, so `wine`, `wineserver` and
  `winedbg` are the orchestrator's guards (`tools/bin`). They refuse any prefix except `prefix-dev*`,
  `prefix-lane*` and `prefix-carrier*`. `harness/tests/test_guards.sh` is their regression test.
- The harness only ever deletes, patches or kills inside its own prefixes (`prefix-dev-base-A|B`,
  `prefix-lane-<N>`; `lib/common.sh assert_owned_prefix`). It kills with `WINEPREFIX=<lane> wineserver -k` only.
- The play prefix is a clone source only, and only while `tools/play_prefix_busy.sh` says it is idle.
- Synthetic input only through `lib/xinput.py`, only while holding the input lock (checked from the holder's open
  fd and `/proc/locks`), and only after its gate passes: the target window is the lane's (`_NET_WM_PID` *and* the
  X server's X-Resource creator pid), on the current workspace, active after activation, pointer inside and
  uncovered. A refusal sends nothing (NOTES.md N9, N18; `tests/test_input_gate.sh`).
- Renderer classes never mix: no DXVK/GPU lane runs while a `wined3d-sw` lane does, and vice versa (lane.sh waits).
- `baseline-<T>.lock`: baseline.sh holds it exclusively while creating or tweaking a baseline; lane.sh and
  deploy.sh hold it shared while cloning from it.

### Lock order

Every harness process takes the locks it needs in one global order, and never waits for an earlier lock while it
holds a later one (`lib/common.sh`; review r2 found `fluf-init` taking baseline-A before input.lock, the reverse of
a `--track A --input` lane):

1. `lane-<N>.lock` → 2. `perf.gate` / `perf.lock` → 3. `render.gate` / `render-<class>.lock` → 4. `input.lock`
→ 5. `baseline-<T>.lock`

| Who | Locks, in order |
|---|---|
| `lane.sh acquire` | the holder takes 1-4 (4 only with `--input`); then the prefix clone takes 5 shared |
| `deploy.sh` | runs inside a held lane (1-4); its rsync refresh takes 5 shared |
| `baseline.sh create` | 5 exclusive |
| `baseline.sh fluf-init` | 4 (`with_input_lock`, for FLUF's first-run dialog), then 5 exclusive; its `xinput.py --prefix` call finds the input lock on its ancestor and does not take it again |

`tests/test_lanes.sh` §13 replays the reviewer's inversion (fluf-init's locks via `baseline.sh fluf-init-lock-probe`
against a `--track A --input` lane, both orders): both sides complete, nobody times out.
- Graceful exit first (devbridge `quit` or a window close), then the scoped `wineserver -k`. After a crash or
  kill, check `nvidia-smi -q | grep 'Recovery Action'` (GPU fault watch, D103).

## Commands

| Command | Purpose |
|---|---|
| `baseline.sh create\|verify A\|B` | Build or re-check `/home/user/freelancer/prefix-dev-base-<T>` (reflink clone of the play prefix + byte-verified tweaks, `BASELINE.json`). `baseline.sh fluf-init` answers FLUF's first-run dialog on A. |
| `lane.sh acquire [--track A\|B] [--input] [--perf] [--lane N] [--display x11\|vdesk] [--renderer R]` | Exclusive lane: flock under `$FLMOD_LOCKS`, prefix recreated from the baseline, `export` lines on stdout (`LANE`, `WINEPREFIX`, `HDE`, `FL_SAVEDIR`, `FL_DEVBRIDGE_DIR`, `LANE_X/Y`, `FLCOPILOT_PORT`, `LANE_TRACK`, `LANE_DISPLAY`, `LANE_RENDERER`, `LANE_TOKEN`, …). Use `eval "$(harness/lane.sh acquire …)"`. |
| `lane.sh release <token>` / `status` / `reap` / `env <N>` | Release (scoped `wineserver -k`), list, free stale locks (only lanes whose lock reap can take itself; status files only of dead or expired acquisitions), re-print a held lane's env. The lock lease is `--ttl` seconds (default `LOCK_TTL_S` = 4 h): give long soaks a longer `--ttl`; a run aborts (`lane_lost`, FAIL) when its holder disappears. |
| `deploy.sh --lane N [--artifacts D] [--dacom-lib X.dll …] [--fluf-module X.dll …] [--overlay D] [--fixture <name\|spec.yaml> …]` | Refresh the lane's HDE dir from its baseline (under the shared baseline lock), copy DLLs, list them in dacom.ini `[Libraries]` through the fltools patch unit `harness.dacom` (D107; `gen/run.py deploy` keeps `harness.*` units), overlay new files, run `gen/run.py deploy`, fail if the pipeline lost a listed DLL, render fixtures, write `DEPLOY_MANIFEST.json`. The run's verdict then checks every listed DLL really loaded (`dll_not_loaded`). |
| `run.sh --lane N [--save P] [--cmds F] [--expect RX …] [--launch-in-space] [--hold-s S] [--renderer R] [--name X]` | Launch, find and place the window, wait for the menu, load, feed commands, check expectations, screenshot, quit, verdict. Prints `rundir=…` and `verdict=…`; exit 0 iff PASS (2 = environment ERROR, nothing launched). Full option list: `run.sh --help`; `--dump-before-quit` captures a backtrace/minidump of a live game (debugging; it kills the game, N18). |
| `shot.sh <wid> <out.png>` | Screenshot of the window itself (exit 0 = proof of rendering); if that is uniform, a root crop only when nothing is stacked above the window (exit 2 = evidence, never proof); exit 1 = failed/covered/uniform. Writes `<out>_small.png`. |
| `verdict.py <rundir>` | `verdict.json` (below). Exit code = verdict class. |
| `triage.py <rundir>` / `triage.py --lookup <module> <hex>` | Fault module + RVA from `+loaddll`/`+seh`, Starport crash-offsets lookup, last spew/devbridge lines. |
| `devbridge.py --lane N send <verb> …` / `wait-ready` / `run-file` / `tail` | Devbridge client (library and CLI), wire protocol in `devbridge/PROTOCOL.md`. |
| `fixtures/gen_fixture.py --install <HDE> --spec <name\|yaml> --out <savedir>` | Fixture saves (`fixtures/README.md`). |
| `lib/spew_allow.py build\|check` | FLSpew allow-lists (`baseline/README.md`). |
| `lib/xinput.py --lane N key\|type\|console\|click\|check …` | The only synthetic-input path (gated). |
| `selftest.sh [--renderer R] [--only s,…] [--skip s,…] [--strict-a]` | End-to-end self test (below). |

Configuration is in `config.sh` (lane count, slots, renderer, timeouts); environment variables of the same name
override it.

### `--cmds` files

One devbridge command per line (`<verb> [args]`; a leading `!` means "failure expected"; a leading
`[timeout_s=N]` gives a long command its budget and is not sent; `perf <s>` gets s+30 automatically), `#` comments,
plus runner-side steps:

| Step | Meaning |
|---|---|
| `@sleep <s>` | keep monitoring for `s` seconds |
| `@shot <name>` | screenshot of the lane window |
| `@key <keysym>` | one gated XTEST key (lane acquired with `--input`) |
| `@console <text>` | adoxa console chat command (Return, text, Return), gated |
| `@click <x> <y>` | gated click at a window point (FL cursor dead reckoning; unreliable in space, NOTES.md N5/N15) |
| `@wait_state <k>=<v>[,<v>…] [timeout_s]` | poll devbridge `state` until key `k` has one of the values |

A failed step ends the list and fails the run (`run.json steps`, verdict signature `step_failed`).

## Run directory and verdict

`$FLMOD_TESTRUNS/<UTC YYYYmmdd-HHMMSS>-lane<N>-<name>/`:

| File | Contents |
|---|---|
| `run.json` | everything the runner observed: args, env, renderer, display, game pid, `window_id`/`window_method`/`window_placed`/`window_changes`, ready/loaded markers, `cmds`, `steps`, `expects`, `shots`, `hang`, `x_stalls`, `dialogs`, quit/exit data, `runner_error` |
| `verdict.json` | `{"verdict": "PASS\|FAIL\|CRASH\|HANG\|NO_WINDOW\|EXITED_EARLY\|TIMEOUT\|ERROR", "reasons": […], "signatures": [{kind, detail}], "fault": {"module", "rva", "addr", "offset_lookup"}, "new_spew_errors": […], "first_chance_exceptions": n, "cmds": {sent, acked, failed}, "expects": {total, matched}, "ready", "clean_quit", "renderer", "display", "run"}`; precedence CRASH > HANG > NO_WINDOW > EXITED_EARLY > TIMEOUT > FAIL > PASS. `ERROR` is written by the runner alone when its environment check refuses to launch (no game ran; `{"verdict", "reasons", "run"}` only). Rules worth knowing: a nonzero game exit code after quit/close is CRASH; a quit that doesn't end the process is HANG; a silent heartbeat-capable devbridge is HANG even when idle; the spew check fails closed; a partial run.json or `ready=false` is FAIL (NOTES.md N18). |
| `wine.log` | `WINEDEBUG=fixme-all,+seh,+loaddll` output; `crash_lines.txt` = its crash lines |
| `FLSpew.txt`, `fluf.log` (A), `devbridge_log.txt` | copies taken at the end |
| `shots/*.png` (+ `_small`) | screenshots (`loaded`, `launched`, `final`, dialogs, hang, `@shot`s) |
| `liveness.tsv`, `windows.txt`, `runner.log` | per-second liveness (`ms alive spew_bytes devbridge_bytes pending cpu_ticks phase wine_bytes hb`), window search/placement log, runner log |
| `backtrace_<tag>.txt`, `<tag>.mdmp`, `winedbg_*_<tag>.txt`, `dumps/` | text backtrace (all threads) and minidump attempt on a hang or start-up timeout, with the failure reasons in run.json (NOTES.md N6/N14/N18), new `*.dmp` files |

## Decisions and measured facts

| Topic | Result | Evidence |
|---|---|---|
| Window identification (REQ-8) | **x11 lanes:** the game window's `_NET_WM_PID` is the lane's Freelancer.exe pid, checked **per window** (`xdotool search --pid P --name N` ORs the criteria and returns every lane's window, NOTES.md N13). **vdesk lanes:** the window titled `lane<N> - Wine Desktop` owned by the lane's explorer.exe. The runner re-validates the window every 2 s and records whether it reached its slot. | N13; `conc-BBBB4fix-*` (4 distinct windows, each at its slot) |
| Display mode | Track B: `x11` (the game window on `:0`, moved to the lane slot). Track A: `vdesk` (FLUF sizes the game to the desktop: in `x11` it covers the whole 3744x2106 screen and ignores `windowsize`). | N2; `…-063920-lane1-boot-A-dxvk-x11` |
| Headless (REQ-9) | **NOT VIABLE**: gamescope worked but faulted the GPU; banned (D103). All lanes on `:0`. | N3, N8 |
| Renderer | `auto` = DXVK when `vulkaninfo --summary` succeeds, else `wined3d-sw` (Mesa llvmpipe). Recorded in `run.json`/`verdict.json`. | N10, D105 |
| Lane count | `LANES=4` (the 2x2 slot grid): 3 rounds of 4 mixed lanes (B space, 2× B docked, A menu) at once, 12/12 PASS at 60.0 fps each (fps_p1 ≥ 59.0), GPU ≤ 48 %. `LANES_SW=2` on `wined3d-sw` (2 instances: 41 fps each). Renderer classes never mix (enforced). | N11, N17 |
| Frame cap | `DXVK_CONFIG="d3d9.presentInterval = 0; d3d9.maxFrameRate = 60"`: Proton 11's DXVK v3.1.1 has no `DXVK_FRAME_RATE` env var (absent from its d3d9.dll); the config key caps presents at 60 (`fps_avg=60.0 fps_p1=59.7`). Override with `RUN_DXVK_CONFIG` for uncapped perf work. | N17 |
| Fixture file name | `%x.fl` of CreateID(description) works for devbridge `load` (B). | `…-050441-…`, every B fixture run |
| FLUF log path | `<prefix>/drive_c/users/steamuser/Documents/My Games/Freelancer/fluf.log` (FLUF resolves it before flplusplus' detour). | NOTES.md RESUME table |
| Track A keep-running patch | skipped in the baseline (FLUF rewrites 0x1B264C at start-up); A lanes launch with `-w`. | `BASELINE.json` (A) |
| Track A saves | **Any `.fl` in the A save folder crashes HDE + FLUF ~2 s after the menu** (`dacom.dll+0x5e6c`); FLUF core alone is enough, the profile without FLUF is fine. Track A fixture loading is blocked on P0-TRACK-A. | N7 |
| Post-campaign fixtures | see `fixtures/README.md` and NOTES.md N15 | N15 |

## Self test

`selftest.sh` runs the host suites and then the in-game steps `b_smoke`, `b_eagle`, `b_fp9` (both with the rank read
in game), `b_longcmd` (`perf 75`, D111 keep-alives), `b_gate` (BLOCKED unless `--with-gate`, N15), `a_boot`,
`a_eagle` (BLOCKED unless `--strict-a`, NOTES.md N7) and `concurrent`, each on its own lane, each requiring a clean
quit, and
writes `$FLMOD_TESTRUNS/<stamp>-selftest/summary.md`. It needs the selftest devbridge DLL
(`devbridge/selftest_dll/build.sh`, built automatically) because Track B has no other devbridge yet. Exit 0 iff no
step failed.

## Ownership

`harness/` is P0-HARNESS's in Phase 0 (except `ci.sh` and `ci.d/README.md`, P0-REPO's). W1-HARNESS takes over the
fixture generator and scenarios in Wave 1; W1-CORE promotes the devbridge core without changing the wire format.
