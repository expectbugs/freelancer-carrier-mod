# W1-SIDECAR: copilot sidecar voice pipeline, grammar fast path, personas, memory, latency instrumentation

- **Type:** impl
- **Wave:** 1
- **Depends on:** P0-SIDECAR (skeleton: NDJSON server on 127.0.0.1:29170, protocol v1 `docs/spec/ipc.md`, fake-game client, venv), S-UI (facts on Wine TCP loopback and push-to-talk polling); sub-wave 1a (CONVENTIONS §8) → **Unblocks:** W2-REFLEX (voice lines and the PTT path end to end), W4-BRAIN (LLM layer), W4-WINGMEN (spoken orders)

## Goal

Turn the skeleton into the working voice half of the copilot. It stays fully functional **without** any LLM (the brain is W4-BRAIN):

- push-to-talk speech → text (faster-whisper on the GPU);
- deterministic **grammar fast path** → validated commands sent to the game;
- **canned and templated voice lines** spoken in distinct crew voices (Kokoro), with a radio filter, on the host through PipeWire;
- **crew personas** from a config file;
- a **SQLite memory store** ready for the brain;
- end-to-end **latency instrumentation**.

The game must behave identically when the sidecar is absent (D-11.3).

## Requirements

- **REQ-W1-SIDECAR-1: Protocol conformance** (`docs/spec/ipc.md` v1, P0-SIDECAR).
  - NDJSON envelope `{"v":1,"t":…,"seq":…}`.
  - The hello/welcome handshake; a 2 s ping/pong; 64 KiB line cap; coalesced snapshots.
  - Command ids with acks.
  - Binds **127.0.0.1 only** (never 0.0.0.0), with a configurable port: 29170 for the play install; lane N uses `FLCOPILOT_PORT = 29170 + N`, set by the harness (CONVENTIONS §7).
  - A new connection replaces the old one. Version mismatch → `bye`.
- **REQ-W1-SIDECAR-2: Speech-to-text** (D-11.3).
  - faster-whisper `large-v3-turbo`, `device=cuda`, `compute_type=float16`, `language="en"`, `beam_size=1` (5 if accuracy suffers), `without_timestamps=True`, `condition_on_previous_text=False`.
  - Biased via `initial_prompt`/`hotwords` with game vocabulary (nanobots, shield batteries, cruiser, gunboat, battleship, carrier, formation, wingmen, house and faction names, trade lane, jump gate, jump hole) plus current system and base names from snapshots.
  - **Models are offline-only** (CONVENTIONS §13). Copy the cached model from `~/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo` into `$FLMOD_MODELS/whisper/` once. Load it with `local_files_only=True` and `HF_HUB_OFFLINE=1`. The sidecar must never download anything at runtime.
  - **CUDA libraries:** ctranslate2 4.7.1 needs **CUDA-12** `libcublas.so.12` + cuDNN 9, but the host's `/opt/cuda` and the aria venv carry CUDA 13 (R6 §4.1, VERIFIED). The sidecar venv installs `nvidia-cublas-cu12` and `nvidia-cudnn-cu12==9.*`, and the launcher exports `LD_LIBRARY_PATH` to their lib dirs **before** Python starts.
  - Fallbacks: CPU `int8` (slower), then the G2CC parakeet/canary daemon protocol (R6 §1.2), then voice input disabled with a log line.
- **REQ-W1-SIDECAR-3: Microphone and push-to-talk** (D-11.3).
  - **Mic = Adam's configured headset mic.** Read the substring `mic_match` (and `ptt_key`) from the gitignored local config `/home/user/freelancer/carrier-mod/local/sidecar.local.yaml`, which overrides the public default config. At startup, resolve the PipeWire/Pulse source whose name contains that substring.
    - **Never** write the device name or its serial into any committed file, test or log under the repo (CONVENTIONS §13).
    - The public default config has no device name and falls back to the system default source.
    - If no source matches, fall back to the default source and log loudly (without the name).
  - Capture 16 kHz mono (resample from the device's 48 kHz stereo).
  - Keep the stream open while the game is connected, with a 300 ms pre-roll ring buffer.
  - PTT: `ptt down` / `ptt up` events come from the game DLL. **Default key numpad period, VK 110** (D-11.3; numpad minus is optional via `ptt_key = numpad_minus`, which the game side handles). Add a 150 ms tail after release.
  - Half-duplex: duck or stop crew speech while PTT is held.
  - An optional X11 passive listener fallback (python-xlib RECORD) for when the game isn't sending PTT. Off by default.
- **REQ-W1-SIDECAR-4: Text-to-speech** (D-11.3).
  - Kokoro-onnx 0.5.0 on CPU; model files `kokoro-v1.0.onnx` + `voices-v1.0.bin`, copied once into `$FLMOD_MODELS/kokoro/` from the paths in R6 §1.3. Never committed: the `.gitignore` covers `*.onnx`.
  - **Vendor (copy) only pure functions:** `prepare_for_speech()` / `split_sentences()` from `/home/user/G2CC/audio/pipeline/tts_daemon.py`, and the 509-phoneme split guard from aria's `tts.py`. Reimplement the latter; **never import it**. aria modules import a secret config at module load and have outbound side effects (R6 §1.4).
  - Distinct voices per crew member from the 28 English voices (blends allowed via style-vector sums).
  - Sentence streaming for fast first audio (target ≤ 0.3 s warm).
  - **Canned lines** (reflex callouts, acks, alerts, distress) are pre-rendered at startup into a cache keyed by `(voice, text, speed)` hash.
- **REQ-W1-SIDECAR-5: Playback.**
  - Host playback via `sounddevice` on the PipeWire default sink.
  - An optional numpy "comm radio" filter: a hand-written 300–3400 Hz biquad band-pass, soft clip and squelch click (scipy is not assumed).
  - A priority speech queue: alert > ack > conversation > banter. Higher priority preempts. Drop stale banter older than 5 s or after a context change.
  - Mute when the game reports `ui.paused`, or `focused=false` (configurable), and during PTT.
- **REQ-W1-SIDECAR-6: Grammar fast path** (D-11.2, no LLM). A regex/keyword intent table maps transcripts to protocol commands. Minimum intents:

  | Utterance | Command |
  |---|---|
  | "nanobots at N (percent)" | `policy.set bots_hull_below=N/100` |
  | "save (the) bots (for the cruiser/capital/big one)" | `bots_reserve=<current>, release_reserve_when=capital_hostile_present` |
  | "use bots / heal up" | `act use_bots` |
  | "batteries at N" | the equivalent battery policy |
  | "use batteries" | `act use_batts` |
  | "form up / tight / loose / line / escort the carrier" | `wing.formation` |
  | "attack my target / focus fire" | `wing.focus player_target` |
  | "engage / weapons free" | `wing.order engage` |
  | "hold fire / hold" | `wing.order hold` |
  | "fall back / retreat" | `wing.order retreat` |
  | "guard the carrier" | `wing.order guard_carrier` |
  | "regroup" | `wing.order regroup` |
  | "status / report" | a templated status line from the last snapshot (hull, shield, bots, batteries, carrier state, ETA) |
  | "carrier status" | the carrier state and ETA |
  | "stop the carrier" | `carrier.order stop` (if the protocol defines it; otherwise a templated "use the carrier panel" reply) |

  Unmatched utterances are queued for the brain when present (W4), otherwise answered "Say again?". Each recognized command gets a cached voice ack.
- **REQ-W1-SIDECAR-7: Personas** (`sidecar/personas.yaml`): crew entries with name, role (copilot, wing1…), voice and blend, speed, persona text, line style, and radio-filter flag. Lore-friendly original names (not campaign NPCs). Speakers map to `copilot` and `wing:<id>` in the protocol.
- **REQ-W1-SIDECAR-8: Memory store.**
  - A new SQLite DB owned by the sidecar, in WAL mode, at `$FLMOD_LOCAL/sidecar/copilot.db` by default (configurable; the play install may use its own path). Test profile: a temp file.
  - Schema from R6 §6.2: `crew`, `campaign`, `turn`, `event`, `memory`, `affinity`, `policy_log`.
  - Write events from `ev.*` messages, keyed by character name and save id from `hello`, `ev.load` and `ev.save`.
  - The save-scum policy: tag events with the save id and game time, and mark those newer than a loaded save as "unlived" (kept, flagged).
  - **Never** write to aria/aria2 databases (Postgres, Qdrant, Redis).
- **REQ-W1-SIDECAR-9: Policy persistence.** Keep the last applied policy (from DLL acks) and re-send it on reconnect if the DLL reports defaults.
- **REQ-W1-SIDECAR-10: Latency instrumentation.** Timestamp each stage: PTT up → STT start → STT done → intent → command sent → ack received → TTS first audio. Write the stage timings to `$FLMOD_LOCAL/sidecar/logs/latency.jsonl` (in tests, the run dir) and summarize per session. **Target:** the "Copilot latency" row of TESTING §Metrics / `harness/metrics_targets.yaml`: PTT release → simple order applied ≤ 0.6 s. Report p50 and p95; the target applies to p50.
- **REQ-W1-SIDECAR-11: Lifecycle and safety.**
  - Launched by `play-carrier.sh` (W5-SHIP) and the harness. Runs as the user.
  - No network beyond 127.0.0.1. No outbound side effects beyond local audio. No cron, no services.
  - Graceful shutdown on SIGTERM.
  - The game must run fine with the sidecar absent or crashing, and the sidecar must survive game restarts.
- **REQ-W1-SIDECAR-13: Test profile** (CONVENTIONS §13). `python -m sidecar --profile test` gives:
  - **a fake LLM:** a deterministic responder, with no CLI or network;
  - **a null audio sink:** no device output; rendered audio goes to WAVs in the run dir;
  - **a file mic:** `--mic-file <wav>` feeds STT from a file instead of the microphone.

  Lanes, soaks and milestones always use it, except the single live-brain step that W4-BRAIN or M3 owns. Also `--port <n>` and `--state-dir <dir>`, so lanes are isolated.
- **REQ-W1-SIDECAR-14: Offline voice-line renderer.** `python -m sidecar.render_lines --in <data/audio/*.yaml> --out $FLMOD_LOCAL/gen/voice/` renders canned lines with the configured crew voices into WAVs. W1-DATA's audio registration (REQ-W1-DATA-15) picks them up; W2-REFLEX authors the line lists.
  - Output must be deterministic (same input, same bytes, or a documented tolerance).
  - Never committed.
- **REQ-W1-SIDECAR-12: Tests mock at the defining module.** Examples: `patch("sounddevice.OutputStream")`, `patch("sounddevice.InputStream")`, `patch("faster_whisper.WhisperModel")`, `patch("kokoro_onnx.Kokoro")`. Never hit a real audio device or GPU in unit tests; use a temporary SQLite file.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§1 paths, §7 per-lane ports, §13 sidecar safety)
- `docs/plan/DESIGN.md` §11 (D-11.1–D-11.9)
- `docs/plan/TESTING.md` §Layers, §Metrics (voice latency), §CI
- `docs/spec/ipc.md` (P0-SIDECAR), `sidecar/` skeleton plus its `NOTES.md`
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R6-copilot-sidecar.md`, the whole file: reusable components and paths §1, IPC §2, protocol §3, voice I/O §4 (CUDA-12 gotcha, audio stack, PTT, TTS choice, playback), LLM options §5 (for W4, not this package), memory §6, safety §7, risks §8, paths §9
- Reference code (read and copy pure functions only; never import):
  - `/home/user/aria/whisper_engine.py` (`WhisperEngine`, `EnergyVAD`, `resample`)
  - `/home/user/G2CC/audio/pipeline/tts_daemon.py` (`prepare_for_speech`, `split_sentences`)
  - `/home/user/G2CC/audio/pipeline/parakeet_daemon.py` (fallback protocol)
  - `/home/user/rt-zomboid/daemon/memory_store.py` (SQLite pattern)
  - `/home/user/aria/wake_word.py` (optional)

## Ownership

- **Owns:** `sidecar/`, except `sidecar/brain/` (W4-BRAIN), and except `docs/spec/ipc.md` (it may propose protocol additions in its report; ARCH packages own spec changes).
- **Reads:** the aria/aria2/G2CC/rt-zomboid source (read-only), the model caches.
- **Must not touch:** anything in those projects (no writes, no DB writes, no crontab), game code.

## Contract

- **Provides:**
  - the `sidecar` process (CLI `python -m sidecar --config sidecar/config.yaml`), venv setup script, launcher (`sidecar/run.sh`, which sets `LD_LIBRARY_PATH`);
  - the grammar intent table (`sidecar/grammar/intents.yaml`), personas, the memory DB API (for W4-BRAIN), and the latency logs.
- **Consumes:** protocol v1 messages from the game DLL (W2-REFLEX implements the DLL side); the fake-game client for tests.

## Tasks

1. The sidecar venv at `$FLMOD_SIDECAR_VENV`, with pinned versions (faster-whisper 1.2.1, ctranslate2 4.7.1, kokoro-onnx 0.5.0, onnxruntime, sounddevice, numpy, pyyaml) plus the CUDA-12 wheels; the `run.sh` launcher with `LD_LIBRARY_PATH`.
2. Device discovery: list sources and sinks via `pactl`/sounddevice, pick the source matching `mic_match` from the local config, and log the choice by index only.
3. The STT engine (vendored), with the vocab bias and the fallback ladder.
4. TTS engine, voices, canned-line cache, sentence streaming.
5. Playback queue, priorities, radio filter, ducking.
6. Grammar fast path plus tests over a 150-utterance corpus (written by you, with expected intents).
7. Personas file plus voice assignment.
8. Memory DB plus event ingestion plus save-scum flags.
9. Latency instrumentation plus summary.
10. Fake-game end-to-end tests: replay recorded NDJSON (`sidecar/tests/fixtures/*.ndjson`).
11. An on-host smoke test (real GPU and audio): synthesize a WAV of a spoken command with Kokoro, play it into the STT path **as a file** (not the mic), check the intent, render the ack, and write the output WAV to disk. **Do not** play audio out of the speakers in automated tests unless TESTING §Layers allows an "audible smoke" step. Default: write files only.

## Acceptance

- **Host tests (pytest, mocks):**
  - `test_protocol_handshake_version_mismatch`
  - `test_ping_timeout_reconnect`
  - `test_grammar_corpus_accuracy` (≥ 97% on the 150-utterance corpus, 100% on the critical intents: use_bots, retreat, status)
  - `test_policy_clamps_sent_as_partial`
  - `test_speech_queue_priority_preempt`
  - `test_stale_banter_dropped`
  - `test_memory_unlived_flagging`
  - `test_no_aria_imports` (a static scan: no `import aria`, `from aria`, or aria2 paths)
  - `test_bind_localhost_only`
- **Host integration (real models, no speakers):**
  - `smoke_stt_tts_roundtrip`: Kokoro renders "nanobots at fifty percent" in voice `am_michael` → a WAV file → STT transcribes → the grammar maps to `policy.set bots_hull_below=0.5`. Record the timings.
  - `smoke_cuda12_libs`: `WhisperModel(..., device='cuda')` loads; report the VRAM delta.
  - `smoke_device_discovery`: the source matching `mic_match` is found (report its index; never print its name into committed files or repo logs).
- **Latency report:** p50/p95 per stage over 50 synthetic commands (file-fed). End-to-end p50 from synthetic PTT up to command sent within the `metrics_targets.yaml` copilot target (≤ 0.6 s).
- **Test profile:** `test_profile_no_audio_no_llm` (patching `sounddevice` proves it is never opened; the fake LLM answers deterministically) and `test_mic_file_feeds_stt`.
- **End to end with the game** (needs W2-REFLEX; run by W2-REFLEX, not here): this package provides `sidecar/tests/e2e_game.md` describing the steps.

## Engine facts to rely on / verify

- Wine maps Winsock TCP to host sockets; named pipes and AF_UNIX don't cross (R6 §2.1, VERIFIED source). Loopback from inside the FL process is UNVERIFIED until S-UI.
- PTT key polling under Wine (`GetAsyncKeyState` with VK 110 and XBUTTON) is UNVERIFIED until S-UI. If it fails, enable the X11 listener fallback by default.

## Pitfalls

- **Never import aria or aria2 modules.** They load a secret config at import time and contain outbound side effects (R6 §1.4).
- The default PipeWire source may change. Always resolve by substring.
- GPU memory is shared with the game (DXVK) and other apps. Load Whisper once, keep it warm, and measure the VRAM delta.
- Don't log transcripts containing personal info into committed files. Logs live under `$FLMOD_LOCAL/sidecar/logs/`, outside every worktree.

## Fallbacks and degrade path

1. CUDA-12 libs unavailable → CPU int8 → G2CC daemon → voice input off (typed commands through a devbridge-like `$FLMOD_LOCAL/sidecar/cmd.txt` remain).
2. Kokoro unavailable → Piper voices (`~/.local/share/piper*`), then subtitles only.
3. Playback device missing → subtitles only (`say` with `subtitle:true`).

## Report

Use the standard report. Include the device choice (without the serial), the latency table, the grammar accuracy, the VRAM numbers, and the venv lockfile path.

## Gate-time addendum

The orchestrator fills:

- the S-UI facts (TCP loopback, PTT polling; already merged, since S-UI is a dependency);
- the protocol version;
- whether W2-REFLEX's DLL side exists yet (if not, test with the fake client only);
- attempt notes;
- the commit trailer.
