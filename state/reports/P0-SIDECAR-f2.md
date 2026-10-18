All 5 review-r2 MINORs are closed and committed. New HEAD is `wp/P0-SIDECAR @ 824564a` (code at dec1f45; 824564a only updates NOTES.md).

Run dirs are under `$FLMOD_TESTRUNS`.

| # | Change | Tests | Evidence | Status |
|---|---|---|---|---|
| 1 ipc.md (a)–(f) | **(a)** After `welcome` the DLL reports the tick: a `state` if running; `ev.pause{on:true}` + paused `state` if stopped; plus `ev.menu` at the menu. `server.py:112` now starts each session with the tick `unknown` and ack timers off. The first `state`/`ev.pause`/`ev.menu` sets it, with a 5 s fallback to running. **(b)** The game tick is the simulation step. One stopped flag covers every reason, so overlapping reasons give one edge. Edges come from a hook that also runs while stopped, with a 1 s stall watchdog. The menu is a stopped tick; commands there get an immediate `not_now`. **(c)** Queued commands never cross a save load, new game, respawn or menu: they are acked `not_now` with `detail:"load"`. **(d)** Acks go out in command order; only the worker's immediate `ok:false` acks may overtake. **(e)** When the outbox is full: drop the oldest `state`, then the oldest droppable event, then hit a hard cap that closes the connection. Acks and control lines are never dropped. **(f)** `seq`/`n`/`obj` are uint32, `gt` is int64, the rest int32. Out-of-range values are rejected by the server; any integer beyond int64 makes the line malformed. | `test_review_r2.py`: 6 tick tests, 3 integer-width tests | x5, CI-like | DONE |
| 2 PTT per session | The pipeline tracks the pressed state for the session that owns the mic. It ignores unmatched releases and cancels, repeated presses, and `ptt` from other sessions. `ev.pause{on:true}`, `ev.menu` and `ev.load` cancel a held press. | 6 pipeline tests in `test_review_r2.py` | x5 | DONE |
| 3 unknown-type log flood | WARNING for the first 64 distinct unknown types per connection, then one cap notice, then DEBUG | `test_unknown_type_warnings_are_capped` (164 distinct types → 65 WARNINGs) | x5 | DONE |
| 4 play-port test | In-process guard tests patch out serving and binding. Subprocess tests run in a private network namespace (`unshare -rn`) and are killed on any ready line; they skip with a reason if `unshare` isn't available. | `test_cli_guard_*`, `test_cli_selftest_picks_port_0_*`, the 3 run.sh refusal cases, the netns selftest, the 3 fakegame CLI cases | `20261018T074428Z-sidecar-r2-guard-off-proof`: with every guard disabled in a temp copy, 13 tests fail, and a host-side poller saw 0 sockets on 29170 (1050 samples over 9.4 s) | DONE |
| 5 `critical_hull` doc | Now reads [floor, min(bots_hull_below, 0.95)], floor wins | `test_critical_hull_doc_names_the_cap` | — | DONE |

**Fail-before check:** on the reviewed code (75da0e4) with the new fakegame, 30 of the new tests fail and 10 pass. The 10 are in-range accept cases plus "resume does not cancel a press" (`20261018T074506Z-sidecar-r2-prefix-regressions`).

**Knock-on changes:**
- fakegame `handshake()` now sends a running `state` after `welcome` (`state=False` or a dict to vary it), and the scripts do the same.
- `test_handler_exception_is_contained` now pings first so that state line can't race its patch.

**Verification on dec1f45:**
- **Sidecar venv ×5:** 351 passed each run (`20261018T074534Z-sidecar-pytest-x5`).
- **Shared venv:** 326 passed, 15 skipped (missing numpy/sounddevice/kokoro).
- **CI-like run** (fresh `git archive` copy, `env -i`, `CUDA_VISIBLE_DEVICES=""`): sidecar venv 349 passed / 2 skipped (no local overlay); shared venv 324 passed / 17 skipped; both exit 0 (`20261018T074739Z-sidecar-ci-like`).
- **Selftest + ss:** selftest ok on ephemeral port 37897. `--profile test` with no port exits 2 with no ready line (host run; the guard refuses before binding). While serving on 34613, only `127.0.0.1:34613` listens (no UDP, no IPv6); SIGTERM exits 0 (`20261018T074824Z-sidecar-selftest-ss`).
- **check_public (snapshot):** `--tree` OK (152 files); `--commits=main..HEAD` OK (11 commits).

**NOTES.md:** decisions D27–D35, the cross-package note that W2-REFLEX (DLL side) and W1-DATA deploy integration own writing `ptt_vk` from `ptt_key`, and an updated RESUME POINT (nothing pending).

**Scratchpad:** writing `ci_like.sh` in the shared session scratchpad overwrote an existing file of that name, possibly another agent's. Nothing in the repo depends on it.
