# W2-REFLEX: Reflex layer, in-game IPC client, push-to-talk, voice lines

- **Type:** impl
- **Wave:** 2 (sub-wave 2a, CONVENTIONS §8)
- **Depends on:** ARCH-1 (uses S-NPC/S-UI facts; W1-SIDECAR protocol)
- **Unblocks:** M1-PLAYTEST, W3-AMBUSH / W3-LOSS (carrier auto-nanobots in fights), W4-WINGMEN (wing policy hooks), W4-BRAIN

## Goal

Split-second survival is handled by fast code, never by the LLM:

- **The player's ship** fires nanobots and shield batteries on thresholds.
- **Carriers** auto-use their nanobot stock with the same code.
- Short **voice callouts** play ("Hull at fifty, deploying bots").
- **The game streams state and events** to the copilot sidecar over a non-blocking TCP link and accepts clamped policy commands back.
- **Push-to-talk** is read in game and forwarded.

With the sidecar absent, gameplay is identical except for voice.

## Requirements

- **REQ-W2-REFLEX-1** (D-11.1): **policy-driven reflex.**
  - Per actor (`player`, `carrier:<id>`) a policy holds:
    - `auto_bots`, `bots_hull_below` (default 0.50), `bots_reserve` (0), `critical_hull` (0.25);
    - `release_reserve_when` ∈ {never, capital_hostile_present, target_is_capital, hull_critical};
    - `auto_batts`, `batts_shield_below` (0.0 = when shields are down), `batts_reserve`.
  - Defaults come from an INI/YAML. **Clamps:** `0.05 ≤ *_below ≤ 0.95`, reserves within `0..stock`, enums whitelisted, unknown fields rejected.
  - **Hard floor:** below `critical_hull` the reflex always fires, regardless of reserve or policy. No command can override this.
- **REQ-…-2** (D-11.1): **player actuation.** Use the S-NPC-proven method to consume one nanobot or battery and apply the vanilla effect:
  - `IObjAffect::use_item` on the player ship;
  - or emulating `SPRequestUseItem`;
  - or the native `USER_REPAIR_HEALTH` / `USER_REPAIR_SHIELD` command path.

  Respect vanilla cooldowns and stack limits. Never double-fire inside the cooldown. Evaluate every tick (≥ 30 Hz), on the main thread.
- **REQ-…-3** (D-8.1, D-11.1): **carrier actuation, "same reflex code".**
  - **Whenever a carrier exists in space and its hull is below the policy threshold** (CONVENTIONS §9: state ∈ {Stopped, EscortTravel, UnderAttack}, via the carrier model's `IsInSpace`), the same policy engine decides. This applies not only in combat. Actuation consumes `n` nanobots from the carrier stock (W2-LOADOUT/W1-INVENTORY) and heals by the per-nanobot value via `pub::SpaceObj::SetRelativeHealth`, or `use_item` if proven for NPCs and solars.
  - Respect a per-carrier cooldown from data.
  - Emit devbridge `ev=reflex.use actor=carrier:<id> by=carrier what=bots left=… hull=…`, plus the NDJSON `ev.reflex` message to the sidecar.
  - **Generic actor (test path):** the policy engine also accepts `tag:<t>` actors (any W1-SPAWN-tagged object with a test stock). That lets this sub-wave-2a package prove NPC actuation in game before W2-CARRIER-GAME (2b) exists.
- **REQ-…-4** (R6 §2): **IPC client.**
  - TCP to `127.0.0.1:<port>`: always the literal IP, never `localhost`. The port is env `FLCOPILOT_PORT` or config. The default is 29170 for the play install; **lane N uses 29170 + N** (CONVENTIONS §7, set by the harness), so concurrent lanes never cross-connect.
  - A **dedicated worker thread** with non-blocking connect + `select` (≤ 250 ms), reconnect backoff 1/2/5 s (30 s after a version mismatch), `TCP_NODELAY`.
  - The game thread only pushes to and swaps a bounded mutex-guarded queue (outbox 256 lines; coalesce snapshots; never drop acks).
  - `WSAStartup` and the thread start from the module init hook, **not `DllMain`**. On shutdown set the stop flag and `closesocket`; never join in `DLL_PROCESS_DETACH`.
- **REQ-…-5** (R6 §3; protocol per `docs/spec/ipc.md` from P0/W1-SIDECAR): **messages.**
  - NDJSON envelope `{"v":1,"t":…,"seq":…,"gt":…}`; hello/welcome handshake; 2 s ping/pong; 3 missed → reconnect.
  - **State snapshots** at 2 Hz (hostiles present), 0.5 Hz (calm in space), 0.1 Hz (docked or paused): ship, target, threat, carrier summary, ui flags.
  - **Edge events** (these are NDJSON message types of the sidecar protocol, distinct from devbridge `ev=` lines): `ev.hull`, `ev.shield`, `ev.reflex`, `ev.low_stock`, `ev.target`, `ev.kill`, `ev.hostiles`, `ev.dock`/`ev.undock`, `ev.system`, `ev.cruise`/`ev.lane`, `ev.carrier`, `ev.death`/`ev.load`/`ev.save`, `ev.pause`, `ptt`.
  - **Commands accepted:** `policy.set`, `act use_bots|use_batts`, `say` (subtitle display only). Wing commands are reserved for W4.
  - Every command is acked with the **applied** (post-clamp) values.
  - **Rate limits:** 10 commands/s, policy changes 2/s.
- **REQ-…-6** (D-11.3): **push-to-talk.**
  - Poll `GetAsyncKeyState(VK_DECIMAL = 110)` each tick when the Freelancer window is foreground and chat is not open. Send `ptt {"down":true|false}` on edges.
  - Config `ptt_key` accepts a VK name or code; `numpad_minus` (109) requires the keymap patch removing vanilla `USER_ZOOM_IN` (`key = 109` in `DATA/INTERFACE/keymap.ini`). That patch is a W1-DATA generator option, enabled by the same config. Coordinate via the gate addendum; if not available, refuse `numpad_minus` with a log line.
- **REQ-…-7** (D-11.3; DESIGN §11, phase-1 voice lines): **pre-rendered callouts.**
  - A manifest `src/game/reflex/voicelines.yaml` with ids and texts per speaker (copilot default).
  - A generator script in owned code renders WAVs with Kokoro, using the sidecar venv, offline, at deploy time. It registers them as Freelancer sound entries in an overlay audio INI through the W1-DATA generator plugin interface. **Never commit the generated WAVs.**
  - Callouts play via `pub::Audio::PlaySoundEffect(client, CreateID(<id>))` or the platform sound API. Use the S-UI-proven method.
  - If the sidecar is connected **and** advertises TTS, prefer sidecar playback for dynamic lines, but keep reflex callouts local (latency).
- **REQ-…-8:** **graceful absence.** Sidecar down means no frame-time impact (verify), one log line "copilot link offline", and no retry storms.
- **REQ-…-9:** devbridge (CONVENTIONS §4; `reflex.*` and `ipc.*` namespaces, owned here):
  - `reflex.policy <actor> [k=v…]`, `reflex.status <actor>`, where actor = `player`, `carrier:<id>` or `tag:<t>`;
  - `reflex.stock <actor> bots=<n> batts=<n>` (test);
  - `reflex.damage <actor> hull=<f>` (test helper: sets relative hull);
  - `ipc.status`, `ipc.inject <ndjson>` (test).

  Events: `ev=reflex.use actor=… by=player|carrier what=bots|batts left=… hull=…`, `ev=ipc.state connected=0|1`.

## Context pack (read before writing code)

- `CLAUDE.md`
- `CONVENTIONS.md` (all; §4 devbridge, §7 locks and ports, §8 sub-waves and DEFERRED, §9 reflex eligibility, §13 sidecar test profile)
- `DESIGN.md` §8.1, §11.1–11.3
- `TESTING.md` §Scenarios, §Metrics (frame time), §Soak
- `state/ENGINE_FACTS.md`: S-NPC (scripted nanobot/battery use for player and NPC), S-UI (TCP loopback from the game, key polling, custom sound playback)
- `local/research/R6-copilot-sidecar.md` §0, §2 (IPC design), §3 (protocol), §4.3 (PTT), §4.5 (playback), §7 (degradation)
- `local/research/R2-engine-api.md` §6 (health read/write, `use_item`), §0 fact 10 (NPC RepairUse)
- `local/research/R3-game-data.md` §5 (`ge_s_repair_01`, `ge_s_battery_01`)
- `docs/spec/ipc.md` (protocol v1)
- Contracts: platform (tick, foreground and chat-state queries, sound), events (damage, target, dock, system, cruise, pause, save/load), inventory (stocks), carrier object registry, notifications/subtitles, generator plugin interface

## Ownership

- **Owns:** `src/logic/reflex/`, `src/game/reflex/`, `src/game/ipc/`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/logic/reflex/tests/`, `src/game/reflex/scenarios/`, and the fake-sidecar test server in `src/game/ipc/tests/`.
- **Reads:** `src/contracts/`, `src/game/core/`, `src/game/spawn/`, `src/logic/economy/`, `src/game/loadout/`, `sidecar/` (protocol tests only), `docs/spec/ipc.md`
- **Must not touch:** `sidecar/` (W1-SIDECAR / W4-BRAIN own it), everything else

## Contract

- **Consumes:** the contracts above.
- **Provides:**
  - the policy engine API (used by W4-WINGMEN for wing retreat policy and by the carrier during fights);
  - the IPC client service (send event, register command handler), so W4 adds wing commands without touching this code;
  - the voice-line generator plugin;
  - devbridge commands.

## Tasks

1. Engine-free policy engine plus clamps plus the hard floor; host tests.
2. Player actuation; carrier actuation.
3. IPC client (worker thread, queues, framing, handshake, ping, rate limits) plus a fake-server test.
4. Snapshot builder and the edge-event detectors with hysteresis (±5 % hull bands).
5. PTT polling.
6. Voice-line manifest, generator and playback.
7. Scenarios.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:**
  - every policy field clamp;
  - the hard floor always fires;
  - reserve release rules;
  - cooldown;
  - NDJSON framing (partial reads, 64 KiB max, garbage lines);
  - rate limiter.
- **IPC tests:** the in-game client against a Python fake server (`sidecar` fake client inverted; a 30-line script in owned tests) covering handshake, ping, reconnect after the server restarts, version mismatch, a flood of 1000 commands/s (rate limited, game unaffected).
- **In-game scenarios:**

  | Scenario | Steps and expected result |
  |---|---|
  | `reflex_player_bots` | Fixture `HARNESS_endgame_eagle` (63 bots), `launch`, `reflex.damage player hull=0.45`. **Expect** `ev=reflex.use actor=player what=bots` within 0.5 s game time; hull increases; the stock decrements by 1. |
  | `reflex_critical_floor` | `reflex.policy player bots_reserve=63` (all reserved), `reflex.damage player hull=0.20`. **Expect** it fires anyway. |
  | `reflex_batts` | Shields down. **Expect** a battery used. |
  | `reflex_npc_actor_bots` | `spawn li_n_dreadnought_d25 1 near=player tag=c`, `reflex.stock tag:c bots=500`, `reflex.damage tag:c hull=0.40`, with **no fight**. **Expect** `ev=reflex.use actor=tag:c what=bots`; stock decrements; hull increases. |
  | `reflex_carrier_bots_stopped` | `DEFERRED(W2-CARRIER-GAME)`. A **Stopped** carrier (`carrier.buy …`) damaged below threshold by spawned attackers, and once by `reflex.damage` with no attackers. **Expect** `ev=reflex.use actor=carrier:<id> by=carrier`; carrier stock decrements; hull increases. This proves healing outside formal fights (CONVENTIONS §9). |
  | `reflex_voiceline` | Trigger the callout. **Expect** `ev=reflex.voiceline id=… played=1`. The audio itself can't be verified by vision; additionally check PipeWire sink activity via `pactl list sink-inputs` showing a wine stream during playback, if feasible, else mark SKIP with the reason. |
  | `ipc_sidecar_absent` | No sidecar. **Expect** one offline log line, no error spam; frame time unchanged vs baseline within 1 ms (mean over 60 s). |
  | `ipc_roundtrip` | Real `sidecar` (W1-SIDECAR) running in its **test profile** (`--profile test`: fake LLM, null audio sink, offline models; CONVENTIONS §13) on port 29170 + lane. **Expect** hello/welcome, snapshots at the specified rates (±20 %), `policy.set` acked with the clamped values, and reflex behavior changed accordingly. |
  | `ptt_key` | Lane acquired with `--input`. `xdotool windowactivate --sync $WID`, then `xdotool keydown KP_Decimal`, wait 1 s, then `xdotool keyup KP_Decimal`. This is XTEST input to the focused window; **never `--window`**, because XSendEvent is invisible to `GetAsyncKeyState` (CONVENTIONS §7). **Expect** `ptt down` then `ptt up` events at the sidecar fake. |

- **Metrics:** reflex decision latency ≤ 1 tick; IPC adds ≤ 0.2 ms to the game thread per frame, measured under `lane.sh acquire --perf`. The copilot latency target (≤ 0.6 s PTT-release-to-applied) is TESTING §Metrics / `harness/metrics_targets.yaml`.
- **Negative tests:** sidecar sends a malformed command (rejected, acked `ok:false`); sidecar killed mid-session; F1 pause (no reflex fires while paused); alt-tab with the keep-running patch.

## Engine facts to rely on / verify

- S-NPC: the player nanobot path and the NPC heal path.
- S-UI: Wine TCP loopback works from inside the game; `GetAsyncKeyState` reports numpad period under Wine; sound playback of a custom entry.

## Pitfalls

- Every Winsock call under Wine costs a wineserver round-trip (R6 §2.1). Never call it on the game thread or in tight loops.
- Don't fire nanobots while docked, in cutscenes, or while the ship is dead.
- The vanilla native repair key also exists. Avoid double consumption if the player presses G at the same time (cooldown check).

## Fallbacks and degrade path

- If programmatic player nanobot use is impossible, synthesize the native `USER_REPAIR_HEALTH` command through the platform key-command API. If that's impossible too, degrade player auto-use (carrier auto-nanobots still work via `SetRelativeHealth`) and log it.
- **Without custom sound playback:** callouts go through the sidecar only (with the sidecar absent there are no callouts), with a degrade note.

## Report (the agent's final message)

Per the template, including measured latencies and frame-time deltas.

## Gate-time addendum

Track, S-NPC/S-UI facts, IPC spec version, keymap-patch availability, lanes, attempt and prior notes.
