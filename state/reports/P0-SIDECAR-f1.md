Fix round 1 for P0-SIDECAR is finished: all 11 review findings are fixed and tested, the final suite ran 20 times with no failures, and nothing is pending. The GPU stayed healthy throughout ("GPU Recovery Action: None" before and after every GPU run), so there was nothing to log.

## 1. Fix report (review r1)

| Finding | What changed | Tests | Evidence | Status |
|---|---|---|---|---|
| MAJOR: what happens while the game tick is stopped (pause, unfocused, loading) | Protocol spec (`docs/spec/ipc.md`) and server code were already done in the earlier checkpoint. This round added the tests and a fakegame directive for a push-to-talk cancel (`{"ptt":"cancel","reason":…}`), plus a new `ptt_cancel.ndjson` script | `test_pause_suspends_ack_timeouts_and_keeps_the_heartbeat`, `test_resume_rearms_the_ack_timer_in_full`, `test_late_ack_is_reconciled_and_session_end_resolves_the_rest`, `test_ptt_cancel_discards_the_utterance_for_every_reason`, `test_script_ptt_cancel` | x20 run | DONE |
| A peer that stops reading left the socket half-open | Already coded; tested both the send-timeout path and a close that never flushes (via `session.close` and `server.stop`). Each test checks that no ESTABLISHED socket is left in `/proc/net/tcp` | `test_send_timeout_aborts_a_peer_that_never_reads`, `test_close_aborts_when_the_flush_never_finishes[*]` | x20 run | DONE |
| Command ids restarted on each connection | Tested: ids never repeat, and a stale ack from an old connection resolves nothing | `test_command_ids_never_repeat_and_stale_acks_resolve_nothing` | x20 run | DONE |
| Test tools defaulted to the play port 29170 | README examples now use 29171 and explain the guard and `--allow-play-port` | `test_check_port[*]`, `test_run_sh_test_profile_refuses_play_port[*]`, `test_selftest_defaults_to_an_ephemeral_port`, `test_fakegame_cli_needs_a_non_play_port[*]`, `test_readme_examples_avoid_the_play_port_for_tests` | `20261018T064931Z-sidecar-selftest-ss` | DONE |
| Brain blocked the event loop; CONVENTIONS §13 sandbox not recorded | Tested: pings answer in under 0.15 s while the brain is still inside `respond()`; env allowlist, CLI flags, cwd and init-message check are tested | `test_slow_brain_does_not_block_pings_or_io`, `test_brain_*`, `test_check_init_message[*]` | x20 run | DONE |
| Mic recording state survived a lost release or a reconnect | Done earlier; this round also asserts the mic resets before it opens for a new session | `test_capture.py` cap/cancel/reset tests | x20 run | DONE |
| A CPU fallback passed the CUDA gate | Mocked tests, plus real runs (next three rows) | `test_voice_smoke_*` (4) | `20261018T064843Z-…-nogpu-require-cuda` (fail, exit 1, no CPU attempt), `20261018T064850Z-…-nogpu-fallback` (`ok-cpu-fallback`, exit 0) | DONE |
| `critical_hull` could be raised to 0.95 | fakegame now clamps it to [floor, min(`bots_hull_below`, 0.95)], floor wins | `test_fakegame_caps_critical_hull_at_bots_hull_below` | x20 run | DONE |
| No single source of truth for the push-to-talk key | Already in spec and code; now tested (`welcome.ptt_vk` is 110 or 109, mismatch is logged) | `test_welcome_carries_the_configured_ptt_vk[*]` | x20 run | DONE |
| Smaller spec gaps | Done earlier; covered by `test_protocol.py` | existing | x20 run | DONE |
| Run dirs had made-up timestamps | Dirs renamed earlier; all new runs use real UTC stamps | — | — | DONE |

As a check that the new tests bite, I ran them against the reviewed code (cf21a75): 33 failed and 8 passed. The 8 that pass only touch the new fakegame or README, or behaviour that didn't change (`20261018T064950Z-sidecar-r1-prefix-regressions`).

## 2. Standard report

```
PACKAGE: P0-SIDECAR   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-SIDECAR @ 75da0e4   (code/tests final at 8a23e7e; 75da0e4 adds NOTES only)
SUMMARY: Review r1 fix round complete. Every finding has regression tests; the real CUDA
  voice smoke was re-run after the GPU reset.
FILES: sidecar/tests/test_review_r1.py (new), sidecar/tests/scripts/ptt_cancel.ndjson (new),
  sidecar/tests/test_fakegame_scripts.py, sidecar/tools/fakegame.py, sidecar/README.md,
  sidecar/NOTES.md (earlier WIP checkpoint dbc1c9f: ipc.md, server/protocol/pipeline/brain/
  profiles/cli/capture, voice_smoke.py)
TESTS:
  pytest sidecar venv x20 — PASS (306 x 20, 0 failures) — $FLMOD_TESTRUNS/20261018T065455Z-sidecar-pytest-x20  VERIFIED
  pytest shared $FLMOD_VENV — PASS (281 passed, 15 SKIP: numpy/sounddevice/kokoro not installed there)  VERIFIED
  voice_smoke --require-cuda — PASS — 20261018T064806Z-voice-smoke: cuda/float16, transcript
    "Save nanobots for the cruiser.", stt_ms 131.3 (warm 122–143), first 710.5, tts_first_audio_ms 374.0,
    the smoke's process held 2336 MiB on the GPU, driver 615.71.09  VERIFIED
  voice_smoke offline (unshare -rn, only lo) — PASS — 20261018T064822Z-voice-smoke-netns, stt_ms 114.6, tts 358.7  VERIFIED
  CUDA gate, no visible GPU — PASS (fail/exit 1 with --require-cuda; ok-cpu-fallback, stt_ms 7843, without)  VERIFIED
  selftest + ss — PASS — 20261018T064931Z-sidecar-selftest-ss: selftest on ephemeral port 45659; only
    127.0.0.1:<port> listening, no IPv6/UDP; SIGTERM exit 0; --profile test with no port → exit 2  VERIFIED
  check_public --tree — PASS (151 files); --commits=main..HEAD — PASS (9 commits)  VERIFIED
DECISIONS: D15–D26 in sidecar/NOTES.md "Review r1 fix round": deferred acks while paused (chosen
  over an immediate not_now); late-ack reconciliation; the DLL's IPC worker owns the link;
  push-to-talk cancel with a reason; command ids unique per process; abort a stuck peer, never
  half-close; play-port guards; brain runs in a thread with the §13 sandbox kept as data;
  critical_hull ≤ bots_hull_below; ptt_key in the sidecar config is the source of truth (deploy
  writes the DLL INI); voice_smoke results ok/ok-cpu-fallback/fail; smaller spec rules
  (duplicate keys invalid, hello once per connection, ev.menu, single-player only).
ENGINE FACTS LEARNED: none (no game runs in this package).
OPEN QUESTIONS / BLOCKERS: none. Proposal still open: harness/lane.sh should export
  FLCOPILOT_FORCE_TEST_PROFILE=1 together with FLCOPILOT_PORT (D7).
KNOWN ISSUES:
  - The init-message field names (tools, mcp_servers) are UNVERIFIED until W4-BRAIN's first live
    sandbox run; per the brief, P0 never calls the real Claude CLI.
  - An earlier x20 run (20261018T064942Z) had 1 failure in run 6. It was in my new test while
    I was editing it (its check also matched the expected "close did not flush" warning), not
    in the sidecar code. Fixed in 8a23e7e; the final x20 is clean.  VERIFIED (run-6.txt)
  - CPU fallback for speech-to-text stays slow (about 7.8 s per 2 s clip, NOTES B-3); it's for W1-SIDECAR.
```

Run dirs are under `/home/user/freelancer/carrier-mod/local/testruns/`. The fix-round notes and RESUME POINT are in `sidecar/NOTES.md` on the branch.
