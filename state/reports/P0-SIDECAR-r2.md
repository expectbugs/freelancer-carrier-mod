```
REVIEW: P0-SIDECAR ROUND 2   VERDICT: PASS
R1 FINDINGS:
- MAJOR stopped-tick lifecycle: fixed. ipc.md §4.7, §7.3 and the §11 MUSTs now cover it; server.py has set_paused, Pending.late, on_late and reconciled. Its 5 tests fail on cf21a75 and pass on 75da0e4. A 20,000-toggle pause storm left 0 handler errors and 0 ping timeouts, and the full ack timeout re-armed after resume (0.501 s against a 0.5 s timeout). VERIFIED
- Send timeout left the socket half-open: fixed. A drain timeout now aborts the transport, close() has a 2 s flush timer, and _cleanup aborts as a fallback. The 3 tests fail old and pass new. VERIFIED
- Command ids restarted per connection: fixed. Ids come from a counter shared by the whole process. The test fails old. In my probe a stale ack and a duplicate ack on a new session both resolved nothing (2 "unknown id" warnings). VERIFIED
- Test tools defaulted to the play port: fixed.
  - `--profile test` with no port exits 2.
  - `--selftest` took ephemeral port 44833.
  - fakegame refuses to run without a port, and refuses 29170.
  - The README uses 29171.
  - 13 cases fail old. VERIFIED
- Brain blocked the event loop; §13 sandbox not recorded: fixed. respond() runs in asyncio.to_thread. The sandbox settings (cwd, env allowlist, flags, init-message check) are stored as data in brain.py and match CONVENTIONS §13. 9 tests fail old. VERIFIED
- Mic recording state survived a lost release or reconnect: fixed. The clip is discarded at the 30 s cap, cancel() exists, and the mic is reset on session start. 3 capture tests and the ptt-cancel test fail old. VERIFIED
- CPU fallback passed the CUDA gate: fixed. `--require-cuda` added, and a fallback now reports `ok-cpu-fallback`. 3 tests fail old. My real `--require-cuda` run passed on cuda/float16. VERIFIED
- critical_hull could be raised to 0.95: fixed in the spec (§5, §9) and in the fake DLL. The test fails with the old fakegame. VERIFIED
- No source of truth for the PTT key: fixed. ipc.md §6 names the deploy-time INI write, and welcome.ptt_vk was added. 2 tests fail old. No package is named as owning the INI write (see NOTES). VERIFIED
- Smaller spec gaps: fixed. Duplicate keys are malformed (in code, and confirmed by fuzzing), target.id became obj, ev.menu was added, single-player only, hello once per connection. 7 protocol tests fail old. VERIFIED
- Evidence hygiene: fixed. Run-dir names now match their birth times (for example, 064806Z was created at 06:48:06Z). VERIFIED
  Method: new tests on cf21a75 with the old fakegame gave 46 failed / 93 passed; with the new fakegame, 39 failed / 100 passed; all pass on 75da0e4 (prefix/oldA.txt, prefix/oldB.txt).
COVERAGE:
REQ-P0-SIDECAR-1 (layout): covered
REQ-P0-SIDECAR-2 (transport): covered (127.0.0.1 TCP only; replacement by the newest hello; play-port guard)
REQ-P0-SIDECAR-3 (protocol v1): covered, with the MINOR W2 gaps in finding 1
REQ-P0-SIDECAR-4 (server): covered
REQ-P0-SIDECAR-5 (fakegame): covered (4 scripts plus ptt_cancel; they pass against the real process)
REQ-P0-SIDECAR-6 (voice env): covered (GPU smoke reproduced)
REQ-P0-SIDECAR-7 (audio devices): covered (mocked; capture_enabled=false)
REQ-P0-SIDECAR-8 (PTT): covered; a deviation from §7.2 is in finding 2
REQ-P0-SIDECAR-9 (safety): covered
REPRODUCED (run dir $FLMOD_TESTRUNS/20261018T070235Z-review-P0-SIDECAR-r2):
- pytest, sidecar venv: reproduced. 306 passed in each of 5 serial runs and 12 parallel runs (4 at a time × 3 rounds); 0 flakes (pytest-x5-summary.txt, stress/summary.txt).
- pytest, shared $FLMOD_VENV: reproduced. 281 passed, 15 skipped, each skip with a reason (pytest-shared-venv.txt).
- CI-like run: clean skips. Fresh git-archive copy outside the repo, empty environment, no FLMOD_* variables, CUDA_VISIBLE_DEVICES="".
  - Shared venv: 279 passed, 17 skipped.
  - Sidecar venv: 304 passed, 2 skipped.
  - Both exit 0 (pytest-ci-like-*.txt).
- run.sh --selftest: reproduced. SELFTEST ok port=44833 listen=['ipv4:127.0.0.1'] loopback_only=True handshake_script=pass shutdown_bye=shutdown port_closed_after=True (selftest/).
- ss -ltnup while serving: reproduced. Only 127.0.0.1:34289 TCP is listening; no IPv6, no UDP. The handshake, policy_roundtrip, ptt_cancel and reconnect scripts all PASS against the live process. SIGTERM exits 0 and no listener remains (serve-ss/).
- Re-fuzz, out of process: reproduced. 70 cases, 0 failures, handler_errors=0, no traceback; the canary pong stayed under 8 ms throughout (fuzz-oop/). Cases:
  - malformed, binary, invalid and overlong UTF-8, CESU-8, BOM, NUL, NaN/±Inf, 1e400, lone surrogates;
  - nesting 30k deep, 6000-key objects, a 5000-digit int;
  - lines of 65535, 65536 and 65537 bytes (the tail of an oversize line is never parsed); 1, 10 and 30 MB lines;
  - partial line then FIN or RST, before and after hello;
  - slowloris: closed at 5.02 s before hello (bye protocol) and 4.01 s after hello (bye timeout, heartbeat 1 s);
  - 50 rapid reconnects (49 replaced byes); 50 connect/close; 50 idle (46 refused, 4 closed at the handshake timeout).
- New paths, in process: 12/14 passed (fuzz-inproc/). Covered:
  - pause/resume storms ending paused and ending running;
  - a late command that a pause cycle does not re-arm;
  - stale and duplicate acks after a session ends;
  - an ack racing a replacement; an ack after the peer's bye;
  - PTT cancel during an in-flight utterance; a 1000-press cancel storm.
  The 1 FAIL and 1 OBS are finding 2.
- voice_smoke --require-cuda: reproduced. ok, cuda/float16, transcript "Save nanobots for the cruiser.", stt_ms 123.2, tts_first_audio_ms 395.8, this PID held 2336 MiB. The netns run (interfaces: lo only) was also ok, stt_ms 115.1. GPU Recovery Action was None before, between and after the runs (voice-smoke/).
- check_public (snapshot): --tree OK, 151 files; --commits=main..wp/P0-SIDECAR OK, 9 commits / 192 files.
FINDINGS (ordered by severity):
[MINOR] docs/spec/ipc.md §4.1–4.8, §7.3, §11 — Gaps a C++ author would have to guess at:
  (a) Reconnecting while the tick is stopped or at the main menu. Nothing says the DLL must send ev.pause{on:true} and a paused state (plus a fresh state) right after welcome. server.py:112 starts every session unpaused, so the sidecar times out commands that the DLL is queuing.
  (b) "Game tick" is undefined: the simulation update, or a per-frame hook that also runs in menus? This decides whether menu and F1 commands apply, queue or get not_now. Also unstated: how the stop edge is detected when the game thread may not run, and how overlapping reasons (F1 plus alt-tab) collapse into one edge.
  (c) Commands queued during a loading screen apply after the load, inside a different save, so a stale act or say can fire there.
  (d) Nothing guarantees that acks for applied commands go out in command order. Late-ack reconciliation of the full policy depends on that, and the worker's immediate rate_limited acks can overtake.
  (e) No rule for a full outbox that holds no snapshot to drop.
  (f) No integer width for seq, gt, n, obj or counts; the sidecar accepted a 4000-digit seq.
  Required change: add these rules before ARCH-0 freezes the spec.
[MINOR] sidecar/flcopilot/pipeline.py:59-73 — The pipeline does not track the PTT state per session, against §7.2 ("down:false while not down is ignored"):
  - A bare ptt{down:false} runs a full utterance in the test profile (VERIFIED: policy.set and say were sent).
  - A stray cancel during the 150 ms tail throws away an utterance that was already released (VERIFIED, PttCapture probe).
  - ptt from a replaced session still reaches the shared mic.
  - A held press is not cancelled on ev.pause{on:true}/ev.menu, which is the backstop if the DLL's game thread cannot post the cancel.
  Required change: track the pressed state for the session that owns the mic; ignore unmatched releases, cancels and ptt from other sessions; cancel a held press on pause, menu and load; add tests.
[MINOR] sidecar/flcopilot/server.py:406-409 — Once 64 distinct unknown types have been seen, every later occurrence of a new type logs at WARNING (VERIFIED: 501 WARNING lines for one type on one connection), against §10.1. Required change: once the cap is reached, rate-limit or downgrade those lines; add a test.
[MINOR] sidecar/tests/test_review_r1.py:377-383 — If the play-port guard regresses, this test starts a test-profile sidecar on 127.0.0.1:29170 for up to 30 s (VERIFIED on cf21a75: "FLCOPILOT ready ... port=29170"). Required change: kill the process as soon as the ready line appears, or check the guard before anything binds.
[MINOR] sidecar/flcopilot/protocol.py:133 — The critical_hull doc still says "[floor, 0.95]"; spec §5 says [floor, min(bots_hull_below, 0.95)]. Required change: update the doc.
NOTES:
- Disclosure: running the new tests against cf21a75 made the old run.sh bind 127.0.0.1:29170 (test profile), up to 30 s each, 6 times. No DLL exists yet, so nothing could have connected, and nothing is listening on 2917x now (ss). This went against the orchestrator's "never 29170" note.
- D7: sound, and already implemented on wp/P0-HARNESS: harness/lane.sh:59 exports FLCOPILOT_FORCE_TEST_PROFILE=1 next to FLCOPILOT_PORT, lanes are 1..N, and config.sh:27 sets the base to 29170, so a lane never gets 29170. It fails safe: if the variable leaks, the live sidecar refuses to start (voice is missing); it never sends fake commands into the game. Merge as is.
- Brain sandbox: matches §13. The flag strings are present in the installed CLI 2.1.302 binary; I checked this statically and did not run the CLI. Still UNVERIFIED and left to W4's first-run test:
  - how `--setting-sources ""` is parsed;
  - the init-message field names;
  - whether ~/.claude/CLAUDE.md is still loaded when HOME is passed.
- Cross-package: no package is named as owner of the step that writes the DLL INI `ptt_vk` from `ptt_key` at deploy. P0-REPO's GitHub workflow runs only tests/py, so sidecar/tests are not in CI at all.
- This review made no commits and the worktree is clean at 75da0e4.
```
