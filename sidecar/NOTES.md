# sidecar/NOTES.md: build notes for the copilot sidecar

Working notes for packages that touch `sidecar/` (P0-SIDECAR, W1-SIDECAR, W4-BRAIN): decisions,
bugs with their hypothesis lists, measurements and open items. Newest section last. Personal
details (device names, host interfaces) stay in local logs, never here.

## P0-SIDECAR, attempt 1 (2026-10-17)

### Layout

| Path | What |
|---|---|
| `flcopilot/protocol.py` | protocol v1 constants, the message catalog with field schemas, `validate`, `encode`/`decode`. Twin of `docs/spec/ipc.md`. Stdlib only. |
| `flcopilot/server.py` | `SidecarServer` (loopback listener, one active session, stats) and `Session` (framing, handshake, heartbeat, commands/acks) |
| `flcopilot/registry.py` | `HandlerRegistry.register_handler(t, fn)`: exact, `prefix.*`, `*`; session start/end hooks |
| `flcopilot/config.py` | TOML defaults → local YAML overlay → `FLCOPILOT_PORT` → CLI |
| `flcopilot/profiles.py` | `live` / `test`; the live guard |
| `flcopilot/pipeline.py` | PTT → clip → transcript → brain → commands + speech (all fakes in the test profile) |
| `flcopilot/audio/` | `sinks.py` (NullSink, DeviceSink), `devices.py` (pactl discovery), `capture.py` (PttCapture, FileMic, NullMic), `dsp.py` |
| `flcopilot/voice/` | `stt.py` (WhisperEngine, FakeTranscriber), `tts.py` (KokoroEngine, FakeTTS, text prep) |
| `flcopilot/brain.py` | `Brain` interface + `FakeBrain` (deterministic) |
| `tools/fakegame.py` | stdlib-only reference client and NDJSON script runner (does not import flcopilot) |
| `tools/voice_smoke.py` | offline Kokoro → WAV → Whisper smoke with timings and nvidia-smi evidence |
| `tools/env_probe.py` | prints the environment run.sh provides (launcher diagnostics) |

### Decisions (P0-SIDECAR)

- **D1 `readuntil`, not `readline`.** `StreamReader.readline()` clears its buffer on overrun, so the rest of an oversize line that is still arriving is later parsed as a new message (a 300 KB line ending in a valid `ping` would get a `pong`). The server uses `readuntil(b"\n")` with `limit=65535`, which leaves the data in the buffer on `LimitOverrunError`, then discards the whole line explicitly. Test: `test_oversize_lines_skipped_connection_kept` (d).
- **D2 replacement at `hello`, not at connect.** The newest connection that completes the handshake replaces the active one. A stray local connection that never says hello cannot kick the game; at most 4 hello-less connections wait (5 s timeout).
- **D3 top-level `id` is reserved for command ids.** `ev.target.id` → `obj`, `ev.wing.id` → `wing`, `ev.carrier.id` → `carrier` (bug B-1).
- **D4 protocol deltas from R6 §3** (listed in ipc.md §14): `ev.hit.dmg` is a fraction; `release_reserve_when=hull_critical` dropped (the hard floor already covers it); `state.carriers` is a list; `say` is a normal command with an ack; added `bye.supported`, `hello.features`, `hello.ptt_vk`, `ev.load.char`, `ev.system.from`, `welcome.profile`, `welcome.heartbeat_ms`.
- **D5 `critical_hull` semantics.** Commands may raise it; the DLL clamps it to `[critical_hull_floor (INI, 0.25), 0.95]`, so the LLM can never lower the floor. Below it the reflex fires regardless of `auto_bots` and reserves.
- **D6 test profile advertises `stt`, `tts`, `llm`** (all fakes) so lane scenarios exercise the "sidecar has TTS" path; the P0 live profile advertises nothing because nothing real is wired yet.
- **D7 live-profile guard.** `--profile live` refuses to start when `PYTEST_CURRENT_TEST` is set or `FLCOPILOT_FORCE_TEST_PROFILE=1`. Proposal for the orchestrator: `harness/lane.sh` exports `FLCOPILOT_FORCE_TEST_PROFILE=1` with `FLCOPILOT_PORT`.
- **D8 package name.** The package is `flcopilot` (P0 spec), started with `sidecar/run.sh` or `python -m flcopilot`. W1-SIDECAR's spec text `python -m sidecar` should read `python -m flcopilot` (or `sidecar/run.sh`).
- **D9 config format.** Public defaults are TOML (`config/flcopilot.toml`, stdlib `tomllib`); the local overlay stays YAML because the orchestrator already wrote it that way. Flat overlay keys `mic_match`/`ptt_key` map to `[audio]`.
- **D10 models are copies** under `$FLMOD_MODELS` (`kokoro/`, `whisper/faster-whisper-large-v3-turbo/`, reflink copies of the owner's files and of the HF cache snapshot). `stt.model_name = "large-v3-turbo"` remains as an offline fallback to the HF cache; both paths pass the smoke.
- **D11 no D-Bus.** `run.sh` (and the test conftest) set `DBUS_SESSION_BUS_ADDRESS=disabled:` when it is unset (bug B-2). A real session address is kept.
- **D12 privacy of the mic name.** Mic discovery logs the resolved source name only to the local log (`$FLMOD_LOCAL/...`). Reports give the index and match count only, because agent reports are committed under `state/reports/`.
- **D13 transcripts** are logged (INFO) only to the local log. W1-SIDECAR may want a config switch to drop them.
- **D14 sidecar-side command validation.** `Session.send_command` validates against the same schema and raises on an invalid command (it is never sent). The DLL validates again.

### Bugs and surprises (with hypothesis lists)

#### B-1: `ev.target` sample failed validation with "id: not a valid command id"

Observation: the catalog test rejected a valid-looking `ev.target{id: null}`. Hypotheses considered:
1. The envelope validator treats every top-level `id` as a command id (string, pattern), so an int/null object id collides.
2. The sample is wrong (`id` should be required int, not null).
3. `nullable` handling in `_check_value` is broken for required fields.
4. Payload validation runs before the envelope skip list, double-checking `id`.
5. The spec meant `ev.target` to carry a string id.
6. JSON `null` decoding differs (None vs missing) between test and server.
7. `ENVELOPE_FIELDS` should not include `id` at all.
8. The pattern `COMMAND_ID_RE` is too strict.
9. Test helper `env()` injects an `id`.
10. `ev.wing`/`ev.carrier` have the same latent collision but pass only because their ids happen to match the pattern.

Experiment: read `validate_envelope` (checks `id` whenever present) and the error text → 1 confirmed; 10 confirmed by inspection (string ids passed by accident). Fix: D3, plus `test_top_level_id_is_reserved_for_command_ids`.

#### B-2: `import sounddevice` hung (> 40 s) during `setup_venv.sh`'s import check

Observation: the check spawned `dbus-launch --autolaunch …`, which sat in `poll`. Earlier the same import took 0.4 s. A per-import probe (fresh interpreter, 40 s timeout) showed: only `sounddevice` hangs; with `DISPLAY` unset it takes 0.41 s; with `DBUS_SESSION_BUS_ADDRESS=disabled:` it takes 0.40 s. At the same time a plain X11 connect (`python-xlib Display(':0')`) also timed out (15 s and 5 s), while another lane was running Freelancer plus a `winedbg --minidump` of a hang.
Hypotheses:
1. libdbus autolaunch (no session bus address in the agent shell) runs `dbus-launch`, which connects to X `:0`; the X server is not answering new clients, so it blocks. **Fits every observation.**
2. A client holds an X server grab (`XGrabServer`), e.g. a frozen Wine process under `winedbg`, so every new X client stalls.
3. A stale `dbus-launch` holds the autolaunch X selection, and new ones wait on it.
4. PortAudio's JACK backend autostarts `jackdbus` over D-Bus. **Disproven:** `query_hostapis()` lists only ALSA.
5. libpulse reads `PULSE_SERVER` from the X root window and blocks on X. **Disproven** as the blocker: with D-Bus disabled but `DISPLAY` set, the import is fast.
6. PipeWire's pulse server stalled. Unlikely: device listing worked seconds later with D-Bus disabled.
7. X server at its client limit. Unlikely: that refuses quickly, it does not block.
8. Missing `XAUTHORITY` in the agent shell. Unlikely: auth failure is fast.
9. The X server is busy with heavy screenshots from a lane (slow, not dead).
10. An ALSA plugin from the ALSA config (enumerated by PortAudio) uses D-Bus.

Status: 1 VERIFIED as the mechanism (both escape hatches fix it, and X itself was unresponsive). The full test suite passed in 5.3 s while X was still stalled, with the conftest fix in place. By about 05:15Z the same X connect worked again, so the stall was transient. Why X stopped answering (2, 3, 9) is UNVERIFIED and outside this package; reported to the orchestrator. Fix: D11. The sidecar never needs D-Bus; in Adam's desktop session the variable is set and left alone.

#### B-4: a replaced session's end closed the new session's mic (found in review)

Sequence: B's hello replaces A → B's `session_start` opens the mic → A's cleanup runs later and its `session_end` closed the (shared) mic and cancelled every utterance task, including B's. Hypotheses for "mic closed while a game is connected":
1. `on_session_end` is not per-session (it acts on shared state for any ending session). **Confirmed by reading the code.**
2. Session end hooks run before start hooks of the successor (ordering), so close happens first and open second (harmless order).
3. A's cleanup ran twice.
4. `PttCapture.open()` is not idempotent and re-open fails silently.
5. The registry calls end hooks for sessions that never started.
6. A heartbeat timeout on A fires during replacement.
7. `close()` called on the mic by the profile builder.
8. Task cancellation of B's utterance raising into B's read loop.
9. The test's fake mic not recording correctly.
10. Server `_session_finished` clearing `active` for the wrong session.

Experiment: `tests/test_pipeline.py::test_replacement_keeps_mic_open_for_new_session` fails on the old code (verified by swapping the old `pipeline.py` back in) and passes on the fix: the pipeline tracks the session that owns the mic and the session of each utterance task.

#### B-5: self-review findings (independent review agent, 2026-10-18)

An independent read-only review found 9 defects that the suite did not catch. Each now has a regression test in `tests/test_review_regressions.py`. 33 of those tests fail on the pre-fix sources (checked by swapping the committed files back in) and all pass on the fix.

| # | Defect | VERIFIED by | Fix |
|---|---|---|---|
| 1 | A JSON array nested ~20 000 deep (fits in 40 KB) raised `RecursionError` out of `decode` and the read loop, dropping the game's connection | reviewer experiment, then our test | `decode` maps `RecursionError` to `json`; the read loop also contains any exception per line (`handler_errors` stat) |
| 2 | Pre-hello `ping` echoed an unchecked `n`: `1e400` (→ inf) and a lone `\ud800` made encoding the pong raise and dropped the connection; `{"x":…}` was echoed out of schema; `1e400` slipped into untyped fields | reviewer experiment | `decode` rejects overflowing floats and lone surrogates; pre-hello pings are validated |
| 3 | PTT pressed again within the 150 ms tail: the second utterance was lost, and `transcribe(None)` was called | reviewer experiment | `ptt_down` during a tail finalizes the first clip; the pipeline skips `None` clips for real transcribers; `WhisperEngine` short-circuits empty clips |
| 4 | A duplicate `ptt{down:false}` orphaned a future whose timeout stole the next utterance's audio | reviewer experiment | a second release while the tail is pending returns `None`; the timeout path only takes the buffer if the pending future is its own and uses `asyncio.wait` (no cancel) |
| 5 | Regex `$` accepted a trailing newline (`"copilot\n"`, `"c-1\n"`) | reviewer experiment | `fullmatch` everywhere |
| 6 | `welcome.heartbeat_ms` could leave its own schema range | reviewer | schema 10–60000; config bounds `heartbeat_s` to 0.01–60 |
| 7 | A replacing session was "active" before its `welcome`, and the old peer's close could delay it | UNVERIFIED by the reviewer; our test checks the order now | `welcome` first, then activate; the old session is closed in a background task |
| 8 | A failed `InputStream.start()` leaked the stream | UNVERIFIED by the reviewer; our mock test confirms the fix | close on failure; set `_stream` only after start |
| 9 | fakegame could pass vacuously: no checks on sidecar output, `"skip":"false"` was true, typos ignored, `disconnect:false` acted, acks echoed instead of the full policy | reviewer reading | strict envelope checks, step validation, a fake-DLL policy model with the spec's clamps |

Spec fixes from the same review: `wing.policy.retreat_hull_below` is required; `carrier` is only valid with `scope:"carrier"`; patterns match whole values; overflowing numbers and lone surrogates are invalid; whitespace-only lines are ignored. Also: `stats.by_type` and the unknown-type set are now bounded.

Hypotheses for the most serious one (#1, a single line drops the connection), before the experiment:
1. An exception type that `decode` does not catch (`RecursionError`, `MemoryError`, `OverflowError`).
2. An exception in a registry handler that `_call` does not catch (`BaseException` subclasses).
3. An encode failure while replying (non-finite or unencodable values echoed back).
4. `LimitOverrunError` handling consuming the wrong number of bytes.
5. The send drain timeout propagating as `TimeoutError` (an `OSError`), which ends `run()` on purpose.
6. A `KeyError` in `_handle_line` on a message that passes the envelope check but lacks a field read directly.
7. Validation recursing on deep data (the schema walker is bounded by schema depth, not data depth).
8. The surrogate check recursing on deep data (made iterative for this reason).
9. Stats bookkeeping raising (an unhashable `t`; `t` is checked to be a string first).
10. Cancellation from replacement arriving mid-line.

The experiment (the reviewer's script, then our parametrized test over four hostile lines, before and after hello) confirmed 1 and 3. The per-line guard also covers 2, 6 and 9. Hypothesis 5 is intended behaviour: a peer that stops reading is dropped.

#### B-3 (surprise, not a bug): Whisper CPU `int8` fallback is ~8–9 s for a 2 s clip

R6 guessed 1–2 s. Measured 7.8–9.4 s (`20261018T044113Z-voice-smoke-cpu`). Hypotheses:
1. The encoder always processes a padded 30 s window, and large-v3's 32-layer encoder dominates on CPU.
2. Too few threads. **Disproven:** `cpu_threads` 0 / 8 / 16 gave 7849 / 8610 / 7890 ms.
3. CPU contention from game lanes running at the same time.
4. int8 kernels not using the best ISA path (oneDNN/ruy choice) on this CPU.
5. Memory bandwidth on 1.6 GB of weights.
6. P-core/E-core scheduling on this hybrid CPU.
7. First-run JIT/oneDNN primitive creation (but warm runs were just as slow).
8. `initial_prompt` + `hotwords` lengthen decoding (small effect with beam 1).
9. Turbo's 4-layer decoder is not the cost; the encoder is (consistent with 1).
10. Timing includes resampling (no: resampling is done before timing).

Not pursued in P0 (fallback path only). W1-SIDECAR options: a smaller CPU model (`small`/`base`), the parakeet daemon fallback, or voice input off.

#### Observation: Kokoro warm first audio 370–440 ms vs 240 ms cited in R6

Measured for the 5-word phrase in voice `am_michael` while game lanes were running. UNVERIFIED causes: CPU contention, a different voice, onnxruntime thread defaults, or the cited figure being for a shorter first unit. W1-SIDECAR targets ≤ 0.3 s and should measure on an idle host.

### Measurements (VERIFIED, run dirs under `$FLMOD_TESTRUNS`)

| Run | Result |
|---|---|
| `20261018T044011Z-voice-smoke` | pass; transcript "Save nanobots for the cruiser."; stt_ms 117 (warm median of 5), first 649; Whisper load 2.8 s; tts_first_audio_ms 390 (warm), cold 465; Kokoro load 0.9 s; cuda/float16; this PID held 2336 MiB (nvidia-smi compute-apps); VRAM delta 2341 MiB |
| `20261018T044044Z-voice-smoke-netns` | pass inside `unshare -rn` (only `lo`, down): offline proven; stt_ms 124 |
| `20261018T044055Z-voice-smoke-hfcache-netns` | pass, model resolved by name from the HF cache, offline; stt_ms 132 |
| `20261018T044113Z-voice-smoke-cpu` | pass on cpu/int8; stt_ms 9351 (B-3) |
| `20261018T045340Z-sidecar-selftest` | `SELFTEST ok port=29170 … loopback_only=True … shutdown_bye=shutdown port_closed_after=True` |
| `20261018T045349Z-sidecar-ss` | `ss -ltnp`: `127.0.0.1:29170` only; no IPv6 listener; SIGTERM exit 0; no listener after |
| flood (scratch script) | 20 000 `ev.hit` + `state` lines pushed back to back: all 20 021 lines processed, 0 invalid; the first `pong` after the burst took 184 ms (backlog), then median 0.06 ms. Planned load is ≤ 50 msg/s. |
| `20261018T045701Z-…-x20`, `20261018T050255Z-…-x20` | full suite 20× each, 0 failures (TESTING §Layers flakiness rule) |
| `20261018T052004Z-sidecar-pytest-x20` | after the review fixes: 253 tests × 20 runs, 0 failures |
| `20261018T052227Z-sidecar-selftest`, `20261018T052227Z-sidecar-ss`, `20261018T052228Z-voice-smoke-netns` | final code: selftest ok on 29170; `127.0.0.1:29170` only, no IPv6, SIGTERM exit 0; offline voice smoke ok (stt_ms 121, tts_first_audio_ms 387, cuda/float16) |
| `20261018T045357Z-sidecar-mic-discovery` | `mic: resolved index=63 matches=1` (name in the local log only) |

### Open items for later packages

- W1-SIDECAR: verify `PULSE_SOURCE` + PortAudio `pulse` device actually selects the resolved source (capture.py comment); wire WhisperEngine/KokoroEngine into the live profile; the speech queue; the grammar.
- W2-REFLEX: ipc.md §11 is the DLL contract. Test against `tools/fakegame.py` inverted, or run the real sidecar with `--profile test`.
- Harness: run sidecar tests with `$FLMOD_SIDECAR_VENV/bin/pytest -q sidecar/tests`. Under the shared `$FLMOD_VENV` (no numpy/sounddevice/kokoro) the audio-library tests skip with a reason and the rest pass.

## RESUME POINT (review round 1, fix round 1, paused for the GPU-reset reboot, 2026-10-18)

Branch `wp/P0-SIDECAR`. The last commit holds the fix-round-1 work in progress. `pytest -q sidecar/tests`: 262 passed at the checkpoint. The review is `state/reports/P0-SIDECAR-r1.md`; the orchestrator's choices are in the fix-round message (summarised under each item below).

### Review r1 findings: status

| Finding | Status |
|---|---|
| **MAJOR: stopped-tick lifecycle** | **Spec done:** ipc.md §4.7 (worker owns handshake and heartbeat; `ev.pause{on}`; one `state` per edge with `rate:"paused"`; queued commands with deferred acks; late acks; ptt cancel) and §11 MUSTs. **Code done:** `server.py` per-process ids, `Pending` with `late`, `on_late`, `Session.reconciled`, `set_paused()` suspending ack timers; `protocol.py` `ev.pause.on`, `ptt.reason`, `rate:"paused"`, `ev.menu`; `pipeline.py` ptt reason → `mic.cancel()`. **Remaining:** dedicated tests (see next steps 1–3). |
| MINOR abort on send timeout | Code done (`send()` aborts and sets `send_timeout`; `close()` arms a 2 s flush timer and then aborts; `_cleanup` aborts if `wait_closed` times out). Test remaining (step 4). |
| MINOR command ids per process + DLL drops unapplied | Code done (`_COMMAND_IDS`); spec §3, §4.5. Test remaining (step 5). |
| MINOR play port 29170 | Code done: `profiles.check_port` (test profile refuses 29170 unless `--allow-play-port` or `FLCOPILOT_ALLOW_PLAY_PORT=1`); `--selftest` uses port 0 unless `--port`; fakegame needs `--port` or `FLCOPILOT_PORT` and refuses 29170 unless `--allow-play-port`; `FakeGame(port)` has no default. Remaining: README example (`--port 29170` → `29171`) and tests (step 6). |
| MINOR async brain + §13 sandbox | Code done: the pipeline calls `brain.respond` via `asyncio.to_thread`; `brain.py` `BRAIN_CWD`, `BRAIN_CLI_FLAGS` (flags checked against `claude --help`), `BRAIN_ENV_ALLOWLIST`, `brain_env()`, `brain_command()`, `check_init_message()`. Tests remaining (step 7). |
| MINOR capture reset | Done with tests: discard at the cap (deliver if the tail is already pending), `cancel()`, `reset()` (pipeline resets on session start and cancels on end); `tests/test_capture.py` new cap/cancel/reset tests pass. |
| MINOR `--require-cuda` | Code done (`voice_smoke.py`: no CPU fallback with `--require-cuda`; results `ok`, `ok-cpu-fallback`, `fail`). Remaining: mocked unit test (step 8); real run after the reboot (step 10). |
| MINOR critical_hull cap | Spec done (§5, §9: clamp to [floor, min(bots_hull_below, 0.95)], floor wins, re-clamped when either changes). Remaining: fakegame `apply_policy` clamp and a test (step 9). |
| MINOR ptt key source of truth | Spec done (deploy writes the DLL INI `ptt_vk` from `ptt_key`; default 110 per D-11.3); `welcome.ptt_vk` sent by the server. Test remaining (step 6). |
| MINOR spec gaps | Done: duplicate keys invalid (`decode` `object_pairs_hook`, test); `state.target.obj` (test); `ev.menu` and single-player-only rule (§4.8); `hello` once per connection (§4.1). |
| MINOR evidence hygiene | Done: the 12 hand-stamped run dirs were renamed to their real creation stamps (the tables above use the new names); new runs use `date -u +%Y%m%dT%H%M%SZ` or the tools' own stamps. |

### Exact next steps

1. `tests/test_review_r1.py`: pause suspends ack timeouts (ack_timeout 0.2 s, `ev.pause{on:true}`, wait 0.5 s, future still pending, `stats.ack_timeouts == 0`; resume, ack, future resolves). Also: pings still answered during the pause (heartbeat 0.05 s).
2. Late ack: no ack within the timeout → future is `None`, then the ack arrives → `session.reconciled`, `stats.late_acks == 1`, `on_late` called, no "unknown id". Session end resolves the pending ones to `None`.
3. PTT cancel: `ptt{down:false, reason:"focus_lost"}` → no `policy.set` (`expect_silence`), `pipeline.cancelled == 1`, and the next normal press works. Add `{"ptt": "cancel", "reason": …}` to the fakegame directives (`DIRECTIVES["ptt"]` gets `"reason"`; `FakeGame.ptt()` gets an optional reason).
4. Send timeout: a raw client with a small `SO_RCVBUF` that never reads; monkeypatch `server.SEND_TIMEOUT_S = 0.2`; loop `send_command("say", text=500 chars)` until `ConnectionError` → `close_reason == "send_timeout"`, `stats.send_timeouts == 1`, the session finishes, no ESTABLISHED socket left on the port (`/proc/net/tcp` state 01), and `server.stop()` returns quickly.
5. Ids: two sessions in a row never reuse an id; a stale ack id from session A does not resolve a command of session B.
6. Ports: `check_port` unit tests; `run.sh --profile test` with no port → exit 2; `--selftest` prints a port ≠ 29170; fakegame CLI without `--port` → exit 2, with `--port 29170` → exit 2. `welcome.ptt_vk == 110` in the handshake test. Fix the README fakegame example to 29171 and mention `--allow-play-port`.
7. Brain: a slow `FakeBrain` subclass (sleeping 0.6 s) does not delay a ping/pong (< 0.1 s); `brain_env` drops `CLAUDECODE`, keeps the allowlist, adds `CLAUDE_CODE_DISABLE_AUTO_MEMORY`; `brain_command` contains every §13 flag; `check_init_message` flags tools and MCP servers.
8. `voice_smoke` mocked: patch `kokoro_onnx.Kokoro`, `faster_whisper.WhisperModel` (raise on cuda) and `subprocess.run` (no nvidia-smi); `--require-cuda` → exit 1 with WhisperModel called once (no CPU attempt); without it → `ok-cpu-fallback`, exit 0.
9. fakegame `apply_policy`: re-clamp `critical_hull` to [0.25, min(bots_hull_below, 0.95)] with the floor winning, plus a test.
10. After the reboot (GPU healthy): rerun `sidecar/run.sh --tool voice_smoke --require-cuda` and the `unshare -rn` variant; run the suite 20×; `check_public --tree` and `--commits main..wp/P0-SIDECAR`; update this file and README; commit; send the fix report (per finding, tests, evidence paths, SHA).

### Outside the repo (all survive a reboot; nothing runs in the background)

- `$FLMOD_SIDECAR_VENV` = `/home/user/freelancer/carrier-mod/local/sidecar-venv` (on disk; rebuild with `sidecar/setup_venv.sh` if ever lost).
- `$FLMOD_MODELS/kokoro/{kokoro-v1.0.onnx,voices-v1.0.bin}` and `$FLMOD_MODELS/whisper/faster-whisper-large-v3-turbo/` (on disk; `setup_venv.sh --models` recreates them).
- Run dirs under `$FLMOD_TESTRUNS` (on disk).
- Scratch patch scripts under the session scratchpad in `/tmp` may vanish on reboot; nothing depends on them.
- No sidecar servers or background jobs are running at the checkpoint.
