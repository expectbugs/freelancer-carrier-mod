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
- W2-REFLEX: ipc.md §11 is the DLL contract, including the §4.7 stopped-tick MUSTs: the worker owns the heartbeat; `ev.pause{on}` plus one `state` per edge; commands queued while stopped (at most 64) and acked when applied; `ptt{down:false, reason}` whenever polling stops with the key held; unapplied commands dropped on disconnect. Test against `tools/fakegame.py` inverted, or run the real sidecar with `--profile test` on a lane port (it refuses 29170).
- W4-BRAIN: use `brain.brain_command()`, `brain_env()` and `BRAIN_CWD`, and assert `check_init_message()` is empty on the first run (CONVENTIONS §13). The init-message field names (`tools`, `mcp_servers`) are UNVERIFIED until that live run.
- Deploy: write the DLL INI `ptt_vk` from the sidecar's `ptt_key` (D24); `numpad_minus` also needs the keymap patch. **Owner (orchestrator, review r2):** W2-REFLEX reads `ptt_vk` from the DLL INI on the DLL side, and W1-DATA's deploy integration writes it from `ptt_key`.
- Harness: run sidecar tests with `$FLMOD_SIDECAR_VENV/bin/pytest -q sidecar/tests`. Under the shared `$FLMOD_VENV` (no numpy/sounddevice/kokoro) the audio-library tests skip with a reason and the rest pass. `lane.sh` should export `FLCOPILOT_FORCE_TEST_PROFILE=1` along with `FLCOPILOT_PORT` (D7).

## Review r1 fix round (2026-10-18)

The review (`state/reports/P0-SIDECAR-r1.md`) found 1 MAJOR and 10 MINOR issues. All are fixed, each with regression tests, mostly in `tests/test_review_r1.py`. Against the reviewed sources (cf21a75) plus the new fakegame, 33 of those tests fail and 8 pass. The 8 that pass exercise only the new fakegame/README or behaviour that did not change (run `20261018T064950Z-sidecar-r1-prefix-regressions`).

### Decisions (fix round)

- **D15 stopped tick: deferred acks, not `not_now`.** While the game tick is stopped, the DLL worker queues commands (in order, at most 64) and acks each one when it is applied after the resume. The sidecar suspends its ack timeouts between `ev.pause{on:true}` and `{on:false}` and restarts them in full. This was chosen over an immediate `err:"not_now"` because a player who pauses and gives an order expects it to stick, and a deferred ack still carries the clamped `applied` (ipc.md §4.7).
- **D16 late acks are reconciled.** An overdue command resolves its future to `None` but stays pending (marked late) until the session ends. If its ack comes, it goes to `Session.reconciled` and `on_late(ack)`. Commands are never re-sent automatically.
- **D17 the DLL worker owns the link.** Connect, `hello`, ping/pong and miss detection run on the IPC worker, independent of the tick. The DLL sends one `state` (`rate:"paused"`) per pause edge and no stream while stopped.
- **D18 PTT cancel.** The DLL sends `ptt{down:false, reason}` (`focus_lost`, `pause`, `menu`, `chat`, `disconnect`) whenever polling stops with the key held. The sidecar discards the clip (`Mic.cancel()`), and also cancels at session end.
- **D19 command ids per process.** Ids are `c-<n>` from one counter per process, and the DLL drops unapplied commands and their acks on disconnect, so a stale ack resolves nothing.
- **D20 abort, never half-close.** A send that cannot drain within 2 s aborts the transport (`close_reason = send_timeout`). `close()` arms a 2 s flush timer and aborts when it fires. `_cleanup` aborts if `wait_closed` takes longer than 1 s.
- **D21 the play port is guarded.**
  - The test profile refuses 29170 unless `--allow-play-port` or `FLCOPILOT_ALLOW_PLAY_PORT=1` is given.
  - `--selftest` binds an ephemeral port unless `--port` is given.
  - fakegame needs `--port` or `FLCOPILOT_PORT`, and refuses 29170 unless `--allow-play-port` is given.
- **D22 the brain runs in a thread.** The pipeline calls `brain.respond` through `asyncio.to_thread`. The CONVENTIONS §13 sandbox (cwd, flags, env allowlist, init-message check) is data in `brain.py` for W4-BRAIN. Nothing in P0 starts the CLI.
- **D23 `critical_hull` ≤ `bots_hull_below`.** The DLL clamps it to [floor, min(bots_hull_below, 0.95)], the floor wins, and the clamp is re-applied when either value changes. Raising the floor therefore cannot spend a reserve early (the D-11.1 intent).
- **D24 the PTT key's source of truth is the sidecar config `ptt_key`.** Deploy writes the DLL INI `ptt_vk` from it, and `welcome.ptt_vk` carries the sidecar's value. Both sides log a mismatch; the DLL keeps polling its INI value.
- **D25 `voice_smoke` results.** A run ends as `ok`, `ok-cpu-fallback` or `fail`. With `--require-cuda` no CPU fallback is attempted, and the run exits 1 if CUDA fails.
- **D26 smaller spec rules.** Duplicate JSON keys are malformed. The DLL sends `hello` once per connection; a repeated one is tolerated. `state.target.id` became `obj`. `ev.menu` was added. The protocol is single-player only: on entering multiplayer the DLL sends `bye{reason:"shutdown", detail:"multiplayer"}`.

### Findings, fixes and tests

| Finding | Fix | Tests |
|---|---|---|
| MAJOR stopped-tick lifecycle | ipc.md §4.7, §7.1–§7.3, §9, §11 MUSTs; `server.py` `set_paused`, `Pending.late`, `on_late`, `reconciled`; `protocol.py` `ev.pause.on`, `ptt.reason`, `rate:"paused"`; pipeline cancel | `test_pause_suspends_ack_timeouts_and_keeps_the_heartbeat`, `test_resume_rearms_the_ack_timer_in_full`, `test_late_ack_is_reconciled_and_session_end_resolves_the_rest`, `test_ptt_cancel_discards_the_utterance_for_every_reason`, `test_script_ptt_cancel` |
| send timeout leaves the socket ESTABLISHED | D20 | `test_send_timeout_aborts_a_peer_that_never_reads`, `test_close_aborts_when_the_flush_never_finishes[session.close, server.stop]` |
| ids restart per connection | D19 | `test_command_ids_never_repeat_and_stale_acks_resolve_nothing` |
| test tools default to the play port | D21; README examples use 29171 | `test_check_port[*]`, `test_run_sh_test_profile_refuses_play_port[*]`, `test_selftest_defaults_to_an_ephemeral_port`, `test_fakegame_cli_needs_a_non_play_port[*]`, `test_fakegame_has_no_default_port`, `test_readme_examples_avoid_the_play_port_for_tests` |
| sync brain on the loop; §13 not recorded | D22 | `test_slow_brain_does_not_block_pings_or_io`, `test_brain_env_is_an_allowlist`, `test_brain_command_carries_every_section_13_flag`, `test_brain_cwd_is_outside_the_repo`, `test_check_init_message[*]` |
| stale `_recording` after a lost release | discard at the cap, `cancel()`, `reset()` on session start | `test_capture.py`: `test_max_utterance_discards_and_next_press_starts_clean`, `test_cap_reached_during_tail_delivers_clip`, `test_cancel_and_reset`, `test_cancel_resolves_a_pending_tail`, `test_close_while_recording_discards`; the reset on session start is asserted in `test_ptt_cancel_discards_the_utterance_for_every_reason` |
| CPU fallback passes the CUDA gate | D25 | `test_voice_smoke_*` (mocked); real runs below |
| `critical_hull` up to 0.95 | D23 (spec and the fake DLL) | `test_fakegame_caps_critical_hull_at_bots_hull_below` |
| PTT key source of truth | D24, `welcome.ptt_vk` | `test_welcome_carries_the_configured_ptt_vk[*]` |
| spec gaps | D26 | `test_protocol.py`: `test_duplicate_keys_are_malformed`, `test_invalid_payloads[*]`, `test_rate_tiers_include_paused`, `test_spec_and_code_list_the_same_types` |
| evidence hygiene | hand-stamped run dirs renamed to their real creation stamps; new runs use `date -u +%Y%m%dT%H%M%SZ` | — |

### Evidence (VERIFIED, run dirs under `$FLMOD_TESTRUNS`)

GPU check before and after each GPU run: `nvidia-smi -q` showed "GPU Recovery Action: None".

| Run | Result |
|---|---|
| `20261018T064806Z-voice-smoke` | `--require-cuda`: ok, cuda/float16. STT: transcript "Save nanobots for the cruiser.", stt_ms 131.3 (warm median of 5, range 122–143), first 710.5, Whisper load 1.65 s. TTS: tts_first_audio_ms 374.0 (cold 412.1), Kokoro load 0.72 s. GPU: this PID held 2336 MiB, VRAM delta 2342 MiB, RTX 3090, driver 615.71.09. |
| `20261018T064822Z-voice-smoke-netns` | the same under `unshare -rn` (interfaces: `lo` only): ok, cuda, stt_ms 114.6, tts_first_audio_ms 358.7 |
| `20261018T064843Z-voice-smoke-nogpu-require-cuda` | `CUDA_VISIBLE_DEVICES=""` with `--require-cuda`: fail, exit 1, "no CUDA-capable device is detected", no CPU attempt |
| `20261018T064850Z-voice-smoke-nogpu-fallback` | the same without `--require-cuda`: ok-cpu-fallback, exit 0, cpu/int8, stt_ms 7843 |
| `20261018T064931Z-sidecar-selftest-ss` | selftest ok on ephemeral port 45659; `--profile test` without a port: exit 2, "refuses the play port"; serving on ephemeral port 39285, `ss -ltnp` shows only `127.0.0.1:39285` (no IPv6, no UDP); SIGTERM exit 0; no listener afterwards |
| `20261018T064950Z-sidecar-r1-prefix-regressions` | the new tests on the reviewed sources: 33 failed, 8 passed |
| `20261018T065455Z-sidecar-pytest-x20` | final code (8a23e7e): 306 tests × 20 runs, 0 failures (about 14.5 s per run). Under the shared `$FLMOD_VENV`: 281 passed, 15 skipped with reasons. |
| `20261018T064942Z-sidecar-pytest-x20` | an earlier run while the last test was being edited: 19 of 20 clean; run 6 failed in the new test itself (an assertion filter that also matched the expected "close did not flush" warning, fixed in 8a23e7e), not in the sidecar code |

## Review r2 polish (2026-10-18)

Review r2 (`state/reports/P0-SIDECAR-r2.md`) passed with 5 MINORs, all closed here before ARCH-0 freezes ipc.md. New tests are in `tests/test_review_r2.py` (40). On the r2-reviewed code (75da0e4) with the new fakegame, 30 of them fail and 10 pass; the 10 are in-range accept-cases and "resume does not cancel" (`20261018T074506Z-sidecar-r2-prefix-regressions`).

### Decisions (polish)

- **D27 the tick is reported after `welcome`.** The DLL's first messages after `welcome` report the tick (running: `state`; stopped: `ev.pause{on:true}` + `state{rate:"paused"}`; menu: `ev.pause{on:true}` + `ev.menu` + `state{rate:"paused", ship:null}`). `Session.tick` is `unknown` until the first `state`/`ev.pause`/`ev.menu`, with ack timers suspended; after 5 s without a report it assumes `running` (warning). A later `state` never changes the tick; only edges do.
- **D28 the game tick is the simulation step**, with one stopped flag (the OR of F1, unfocused, loading, menu), edges evaluated per frame from a hook that also runs while stopped, and a 1 s stall watchdog on a tick counter in the worker. The main menu is a stopped tick, and the worker answers commands there with `not_now` at once.
- **D29 load boundaries** (save load, new game, respawn, main menu): queued commands are tagged with a game generation and acked `not_now` (`detail:"load"`) instead of being applied in another save. Gate and hole transitions are not boundaries.
- **D30 ack order.** Acks of commands that reached the game thread are FIFO. Only the worker's immediate `ok:false` acks (rate_limited, queue full, not_now at the menu, validation errors) may overtake.
- **D31 the outbox** never drops acks, control messages, `ptt` or lifecycle events. When full it drops the oldest `state` first, then the oldest other event. A hard cap (about 1024 lines or 1 MiB) closes the connection.
- **D32 integer widths.** `seq`, `n` and `obj` are uint32, `gt` is int64 up to 2⁵³ − 1, and every other integer is int32. Any integer outside int64 makes the line malformed; an out-of-width known field makes the message invalid.
- **D33 push-to-talk per session.** Only the session that owns the mic counts. A press while down, and a release or cancel while not down, are ignored (`ignored_ptt`). `ev.pause{on:true}`, `ev.menu` and `ev.load` cancel a held press.
- **D34 unknown-type log cap.** The first 64 distinct unknown types per connection are logged at WARNING, then one cap notice, then DEBUG.
- **D35 port-safe tests.** Play-port tests run in-process with serving and binding patched out, or in a private network namespace (`unshare -rn`, its own loopback) and are killed on any ready line. Without `unshare` they skip with a reason; the in-process ones always run.

### Findings, fixes and tests

| Finding | Fix | Tests |
|---|---|---|
| ipc.md gaps (a)–(f) | §4.1 tick report, §4.7.1 definitions, §4.7.4–6, §4.8, §7.3 ack order, §11 outbox and MUSTs, §3 integer widths; `server.py` `Session.tick`; `protocol.py` widths and int64 guard | `test_reconnect_while_paused_keeps_ack_timers_suspended`, `test_reconnect_at_the_main_menu_gets_not_now`, `test_ev_menu_alone_stops_the_tick`, `test_first_state_sets_the_tick[*]`, `test_running_tick_times_commands_out`, `test_no_report_after_welcome_assumes_running`, `test_integer_widths[*]`, `test_integers_outside_int64_are_malformed[*]`, `test_server_drops_out_of_range_integers` |
| pipeline PTT state | D33 | `test_unmatched_release_and_cancel_are_ignored`, `test_repeated_press_is_ignored_and_one_utterance_follows`, `test_cancel_after_release_does_not_discard_the_utterance`, `test_tick_edges_cancel_a_held_press[*]`, `test_resume_does_not_cancel_a_press`, `test_ptt_from_a_session_that_does_not_own_the_mic_is_ignored` |
| unknown-type WARNING flood | D34 | `test_unknown_type_warnings_are_capped` |
| play-port test could hold 29170 | D35 | `test_cli_guard_refuses_before_anything_binds[*]`, `test_cli_selftest_picks_port_0_before_anything_binds`, `test_run_sh_test_profile_refuses_play_port[*]`, `test_selftest_defaults_to_an_ephemeral_port`, `test_fakegame_cli_needs_a_non_play_port[*]` |
| `critical_hull` doc | `protocol.py` doc names min(bots_hull_below, 0.95) | `test_critical_hull_doc_names_the_cap` |

The fakegame's `handshake()` now reports a running tick after `welcome`, like the DLL; `state=False` or a dict varies it. The scripts do the same. `test_handler_exception_is_contained` syncs with a ping first, so that state line cannot race the patch.

### Evidence (VERIFIED, run dirs under `$FLMOD_TESTRUNS`)

| Run | Result |
|---|---|
| `20261018T074534Z-sidecar-pytest-x5` | sidecar venv, dec1f45: 351 passed in each of 5 runs; shared `$FLMOD_VENV`: 326 passed, 15 skipped, each with a reason (`shared-venv.txt`) |
| `20261018T074739Z-sidecar-ci-like` | fresh `git archive` copy outside the repo, `env -i`, `CUDA_VISIBLE_DEVICES=""`: sidecar venv 349 passed, 2 skipped (no local overlay); shared venv 324 passed, 17 skipped; both exit 0 |
| `20261018T074824Z-sidecar-selftest-ss` | selftest ok on ephemeral port 37897; `--profile test` without a port: exit 2, no ready line; serving on 34613, only `127.0.0.1:34613` listens (no UDP, no IPv6); SIGTERM exit 0; no listener after |
| `20261018T074428Z-sidecar-r2-guard-off-proof` | copy with every play-port guard disabled: 13 guard tests fail; a host-side poller saw 0 sockets on 29170 in 1050 samples over 9.4 s |
| `20261018T074506Z-sidecar-r2-prefix-regressions` | r2 tests on 75da0e4: 30 failed, 10 passed (see above) |

check_public (snapshot): `--tree` OK (152 files); `--commits=main..HEAD` OK.

## RESUME POINT

The review r2 polish is complete and committed on `wp/P0-SIDECAR`: all 5 MINORs are closed, with tests and evidence. Nothing is pending in this package. Next: the merge after P0-REPO (ci.sh and the hooks); the ARCH-0 freeze of `docs/spec/ipc.md`.
