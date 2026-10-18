```
REVIEW: P0-SIDECAR ROUND 1   VERDICT: CHANGES_REQUIRED
COVERAGE:
REQ-P0-SIDECAR-1 (layout): covered. Pinned pyproject; the venv at $FLMOD_SIDECAR_VENV is built from /usr/bin/python3.13 (pyvenv.cfg) and its pip freeze matches requirements.lock; run.sh finds the venv; the TOML has no device names; overlay, models and logs are where the spec says; test_config/test_cli cover it.
REQ-P0-SIDECAR-2 (transport): covered. 127.0.0.1/AF_INET only, FLCOPILOT_PORT and config honoured, newest hello replaces the old session. Tests: test_binds_loopback_ipv4_only, test_env_port_is_honored, test_new_connection_replaces_old.
REQ-P0-SIDECAR-3 (protocol v1): partial. ipc.md and protocol.py agree, and every type, clamp and extension rule is there, but the pause/focus lifecycle is missing (MAJOR below).
REQ-P0-SIDECAR-4 (server): covered. readuntil in place of readline is a justified deviation (D1). Registry, 10 MB JSON log rotation (rotation also seen in my fuzz logs), and profiles with the null sink are in place.
REQ-P0-SIDECAR-5 (fakegame): covered. 3 required scripts plus version_mismatch; stdlib only; strict envelope checks; the fake DLL clamps policy.
REQ-P0-SIDECAR-6 (voice env): covered. The GPU path rests on the author's evidence. The offline and CPU paths reproduced.
REQ-P0-SIDECAR-7 (audio devices): covered. Mic discovery works; capture plumbing is tested with mocks; capture_enabled=false.
REQ-P0-SIDECAR-8 (PTT): covered. Config key and hello.ptt_vk are in place; where the key is really set is a MINOR below.
REQ-P0-SIDECAR-9 (safety): covered. Loopback only; AST import checks; mocks patch at sounddevice.*; no aria imports (grep and test_safety).

REPRODUCED (run dir $FLMOD_TESTRUNS/20261018T052823Z-review-P0-SIDECAR-r1):
- pytest, sidecar venv: reproduced. 253 passed, 11 runs out of 11, 0 failures (pytest-sidecar-venv-1.txt, pytest-x10-summary.txt).
- pytest, shared $FLMOD_VENV: reproduced. 235 passed, 11 skipped with reasons (pytest-shared-venv.txt).
- run.sh --selftest: reproduced on port 29179 (selftest/stdout.txt): loopback_only=True, handshake_script=pass, shutdown_bye=shutdown, port_closed_after=True.
- ss, listeners while serving: reproduced on 29179 (ss/ss.txt). Only 127.0.0.1:29179 TCP; no IPv6 or UDP listener; SIGTERM exit 0; no listener afterwards.
- Primary scenario: there is no in-game scenario. The package has no game runs, and harness/ is on neither main nor the branch. The stand-in is the policy round trip (ptt → policy.set → ack with full clamped policy → say → null sink), via test_script_policy_roundtrip and test_serve_until_sigterm: reproduced.
- voice_smoke on GPU: not reproduced — GPU faulted (D103). The author's GPU evidence is consistent: 044011Z and 061200Z both show cuda/float16, this PID holding 2336 MiB, stt_ms 117/121, transcript "Save nanobots for the cruiser.".
- voice_smoke offline / CPU: reproduced. Under unshare -rn (only lo), the CPU int8 fallback with its reason recorded produced the correct transcript: stt_ms 8850, tts_first_audio_ms 392; the hf-cache variant gave 8942/382.
- Mic discovery: reproduced. resolved index=63 matches=1. The name appears in none of the 5 commit trees or messages (mic/).
- check_public (P0-REPO checker): reproduced. --commits=main..wp/P0-SIDECAR OK, 5 commits; --tree OK, 149 files.
- "33 regression tests fail on pre-fix code": reproduced. 33 failed and 2 passed against the 23d9f6b sources; 35 passed on cf21a75 (prefix-regressions.txt).
- NDJSON fuzz (fuzz/, fuzz*-stdout.txt): reproduced. Inputs were malformed, binary, invalid UTF-8/CESU, lone surrogates, NaN/1e400, 5000-digit ints, nesting depth 500–30000, 64 KiB±1, 1/10/30 MB lines, partial lines plus disconnect, RST mid-line, slowloris before and after hello, 50 rapid reconnects with hello, 50 connect/close, 50 idle connections, and a ptt flood. No crash, no loop hang, 0 handler exceptions, canary round trip under 1 ms throughout. Pre-hello slowloris was closed at 5.0 s; post-hello at 4 s (1 s heartbeat). My 3 "FAIL" lines were errors in my harness: duplicate-key last-wins turned a line into a bye, and a hello from another connection replaced the victim. A focused rerun was clean, except the leak below.

FINDINGS (ordered by severity):
[MAJOR] docs/spec/ipc.md §4.2, §7.2 ptt, §7.3, §9 "Timing", §11
  Problem: what the DLL does when the game tick stops (F1 pause, unfocused/alt-tab pause, loading screens) is not specified.
  - Commands "apply on the next game tick", but the sidecar counts an ack later than 5 s as lost. server.py:351-352 throws a late ack away, so the sidecar's world model diverges from a policy the DLL applied after unpause.
  - Nothing says that ping/pong and hello/bye must stay on the worker thread. Routed through the tick, a pause longer than 8 s causes a timeout and reconnect churn.
  - The DLL polls PTT only while the window is in the foreground, so alt-tab with the key held never sends ptt{down:false}.
  - "0.1 Hz while paused" has no producer if the game thread is suspended.
  Required change:
  - State that the worker answers ping/pong and the handshake independently of the tick.
  - Define commands during a stopped tick: either an immediate err:"not_now", or a deferred ack that the sidecar still reconciles from `applied`. Make server.py match whichever is chosen.
  - Require ptt{down:false} (or a cancel) whenever polling stops with the key down (focus loss, chat, pause, menu, disconnect).
  - Say who sends `state`, if anyone, while paused.
[MINOR] sidecar/flcopilot/server.py:204-210, 509-513
  Problem: after a send timeout to a peer that never reads, `writer.close()` waits to flush forever. The socket stays ESTABLISHED (3.3 MB Send-Q) after the session ends and after server.stop(), which logs "listener did not close in time"; close_reason is logged as "eof" (fuzz3-stdout.txt).
  Required change: call `transport.abort()` when drain or wait_closed times out, and record the reason as send_timeout.
[MINOR] sidecar/flcopilot/server.py:87
  Problem: command ids restart at c-1 on each connection, so a stale ack from connection A can resolve a different pending command on connection B.
  Required change: use a per-process id counter, or specify that the DLL drops unapplied commands and their acks on disconnect.
[MINOR] sidecar/flcopilot/cli.py:137-139, sidecar/tools/fakegame.py:517, sidecar/README.md (fakegame example)
  Problem: the test-profile --selftest and fakegame both default to the play port 29170, and the author's selftest and ss evidence ran the test profile on 29170. Once the DLL exists:
  - a test sidecar on 29170 can feed FakeBrain policy.set into Adam's real game, and the DLL keeps the last applied policy;
  - fakegame's hello replaces the real session, and the DLL then backs off 30 s.
  Required change: selftest binds port 0 unless --port is given; fakegame requires --port or FLCOPILOT_PORT; the test profile refuses 29170 unless forced; the README example uses 29171.
[MINOR] sidecar/flcopilot/pipeline.py:87, brain.py:257
  Problem: `Brain.respond` is synchronous and runs on the event loop. A W4 CLI brain behind the same interface would block pings and all I/O for seconds. The CONVENTIONS §13 sandbox, which the brief asks to anticipate, is not recorded:
  - flags --tools "", --strict-mcp-config, --disallowedTools 'mcp__*', --setting-sources "";
  - an environment allowlist and cwd /home/user/freelancer/carrier-brain-cwd;
  - a check that the init message shows zero tools.
  Required change: make respond async or call it with asyncio.to_thread, and add the sandbox constants or docs for W4.
[MINOR] sidecar/flcopilot/audio/capture.py:268, 285-288; pipeline.py:47-49
  Problem: after a lost release, `_recording` stays set. The next ptt_down is treated as a duplicate; once the 30 s cap is reached, new speech is dropped and the stale clip is transcribed. The shared mic's recording state also survives a session replacement. This is behind capture_enabled=false in P0.
  Required change: discard or finalize at the cap, and reset recording state on session start.
[MINOR] sidecar/tools/voice_smoke.py:166-169
  Problem: with --device cuda, a CPU fallback still prints "VOICE_SMOKE ok" and exits 0, so a broken CUDA setup passes the gate.
  Required change: add --require-cuda, or report a distinct ok-fallback result or exit code.
[MINOR] docs/spec/ipc.md §5, §9
  Problem: critical_hull may be raised to 0.95. One command then lets the hard floor override auto_bots:false and every reserve, which defeats "save bots for the cruiser" (D-11.1 intent).
  Required change: cap critical_hull at bots_hull_below, or document that this is intended.
[MINOR] docs/spec/ipc.md §6 (hello.ptt_vk), config
  Problem: Adam's ptt_key in local/sidecar.local.yaml only triggers a mismatch warning. The DLL's value wins and nothing carries the key to the DLL.
  Required change: name the single source of truth (for example, deploy writes the DLL INI and the keymap patch from ptt_key), or add welcome.ptt_vk.
[MINOR] docs/spec/ipc.md
  Problem: smaller gaps that W2 will hit:
  - duplicate JSON keys are undefined (Python takes the last one; yyjson-style parsers take the first);
  - `state.target.id` and `ev.target.obj` name the same thing differently;
  - nothing on SP⇄MP or returning to the menu;
  - no rule for re-hello versus ev.load.
  Required change: specify each.
[MINOR] Evidence hygiene ($FLMOD_TESTRUNS)
  Problem: the dirs …060000Z-sidecar-pytest-x20, …061000Z-sidecar-selftest, …061100Z-sidecar-ss and …061200Z-voice-smoke-netns were created at 05:20–05:22Z (mtimes) but are named 06:00–06:12Z, and …0445Z-voice-smoke-netns breaks the stamp format. CONVENTIONS §5 requires the real UTC stamp. Their contents agree with my reruns.
  Required change: use real stamps.

NOTES:
- GPU: my first 3 voice_smoke runs, a ctranslate2 device-count probe and one raw cuCtxCreate probe happened before your D103 note. Every context creation failed (CUDA_ERROR_UNKNOWN / NV_ERR_RESET_REQUIRED) and nothing ran on the GPU. I ran no GPU work after the note.
- The fault is in dmesg at 05:27:54Z: Xid 51 from an Xwayland process (pid 1376925, now exited), then Xid 154 "recovery action PF FLR". That is before my first command at 05:28:23Z.
- N/A for this package, which has no DLL code: engine-safety items (main-thread game calls, spawn/destroy deferral, st6, null checks) and the nickname hash scan. ipc.md §11 does carry the worker-thread, no-DllMain-init and apply-on-main-thread rules for W2.
- Ownership and contracts: the branch touches only sidecar/ and docs/spec/ipc.md. No frozen contracts exist yet. Carrier states match CONVENTIONS §9 exactly. There is no leftover refs/original from the filter-branch rewrite.
```
