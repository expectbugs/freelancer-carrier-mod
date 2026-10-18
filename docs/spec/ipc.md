# IPC protocol v1: game DLL ↔ copilot sidecar

- **Status:** v1, written by P0-SIDECAR (2026-10-17; review round 1 fixes 2026-10-18). ARCH-0 freezes it after review. After that, a change either adds optional fields (no version bump) or bumps `v`.
- **Source:** adapted from research R6 §2–§3 (gitignored `local/research/R6-copilot-sidecar.md`). The machine-readable twin of this file is `sidecar/flcopilot/protocol.py`; `sidecar/tests/test_protocol.py` checks that the two list the same message types.
- **Implementations:** sidecar server `sidecar/flcopilot/server.py`; reference client `sidecar/tools/fakegame.py` (stdlib only, independent of the server code); in-game client W2-REFLEX (`src/game/ipc/`).

Design rule (DESIGN §11): fast code handles split-second actions; the LLM sets strategy. **No reflex ever waits on this link.** The game must play identically with the sidecar absent, except that voice is missing (D-11.3).

## 1. Transport

| Item | Rule |
|---|---|
| Socket | **TCP over IPv4 loopback.** Wine maps Winsock `AF_INET` sockets to host sockets (`server/sock.c`, VERIFIED from source, R6 §2.1). Windows named pipes stay inside wineserver, and Wine 11 has no `AF_UNIX` for Windows programs, so neither crosses to Linux. |
| Roles | The **sidecar listens**; the **DLL connects** (client). |
| Address | `127.0.0.1` only, never `0.0.0.0` (the host has LAN, VPN and tailnet interfaces). The DLL connects to the literal `127.0.0.1`, never `localhost` (it can resolve to `::1`). |
| Port | Default **29170** (the play install). Set by env `FLCOPILOT_PORT` on both sides, falling back to config. Test lane N uses **29170 + N** (CONVENTIONS §7; `harness/lane.sh` exports it), so concurrent lanes never cross-connect. 29170 is below the ephemeral range 32768–60999 (VERIFIED R6 §2.2). |
| Connections | **One active session.** The newest connection that completes the handshake becomes active; the previous active one gets `bye{reason:"replaced"}` and is closed (game restart). A connection that never sends `hello` does not displace the active one. At most 4 connections may be waiting for their `hello`. |
| Options | The DLL sets `TCP_NODELAY` (supported by Wine, `ntdll/unix/socket.c`). |

## 2. Framing

- **NDJSON:** one UTF-8 JSON **object** per line, terminated by `\n`. A trailing `\r` before the `\n` is tolerated and ignored. Empty and whitespace-only lines are ignored.
- **Size:** a line, including its `\n`, is at most **65 536 bytes** (64 KiB). Senders never produce a longer line.
- **Objects:** duplicate keys are invalid (parsers disagree on which value wins). Senders never produce them; receivers drop such a line as malformed.
- **Encoding:** compact JSON (`ensure_ascii` off). `NaN`, `Infinity` and numbers that overflow a double (for example `1e400`) are invalid, and so are `\uD800`–`\uDFFF` escapes that do not form a surrogate pair. JSON string escaping means a message can never contain a raw newline.
- **Receiver behaviour on a bad line** (both sides). The line is logged and dropped; the connection stays up:
  - not UTF-8, not JSON (including nesting too deep to parse and duplicate keys), not an object, or an envelope error → dropped (`malformed`);
  - longer than 64 KiB → skipped **up to and including its newline**, even if it arrives in many reads, so that the tail of an oversize line is never parsed as a new message (`oversize`);
  - a valid envelope with an invalid payload for a known type → dropped (`invalid`);
  - unknown `t` → ignored (§10).

## 3. Envelope

Every message is a JSON object with these fields:

| Field | Type | Who | Rule |
|---|---|---|---|
| `v` | int | both | Protocol version, `1`. |
| `t` | string | both | Message type, 1–64 chars (§6–§8). |
| `seq` | uint32 | both | Per direction, per connection: starts at 1 and increases by 1 per message. Receivers log gaps and regressions but never reject on them. A connection never sends more than 2³² − 1 messages (2.7 years at 50 per second). |
| `gt` | int64, 0 to 2⁵³ − 1 | DLL only | Game time in ms on the DLL side. The DLL always sends it (0 when no game is loaded); it may restart after a load. The sidecar omits it. Receivers tolerate its absence. |
| `id` | string | commands, acks | `[A-Za-z0-9_.:-]{1,32}` (whole string; patterns in this spec always match the whole value). The sidecar uses `c-<n>` from a **per-process** counter, so an id never repeats across reconnects to the same sidecar process. A top-level `id` means a command id and nothing else: payloads name object ids differently (`obj`, `wing`, `carrier`). |

Payload fields sit next to the envelope fields (flat, no nesting under a `payload` key).

**Integer widths.** Every JSON integer anywhere in a line, known field or not, fits in int64; a line with a larger integer is malformed. Known fields are narrower (C++ types for W2-REFLEX):

| Width | Fields | Range |
|---|---|---|
| uint32 | `seq`, `n` (ping/pong), `obj` (space object id) | 0 to 4 294 967 295 |
| int64 | `gt` | 0 to 2⁵³ − 1 (exact in a double) |
| int32 | every other integer: counts, reserves, `left`, `hostiles`, `incoming_missiles`, `band`, `prio`, `ptt_vk`, `heartbeat_ms`, `supported` | its stated range, always within −2³¹ to 2³¹ − 1 |

A known field outside its width or range makes the message invalid: an event is dropped, a command is answered `err:"bad_value"`.

## 4. Session lifecycle

```
DLL (worker thread)                         sidecar
connect 127.0.0.1:$FLCOPILOT_PORT ──────────▶ accept
hello{v:1, dll, game, char, save, policy}  ──▶
                                          ◀── welcome{v:1, sidecar, features, heartbeat_ms, profile}
state / ev.* / ptt / ack  ─────────────────▶
                                          ◀── policy.set / act / wing.* / say  (each with an id)
ping{n} ◀──────────────────────────────────▶ pong{n}   (each side pings every 2 s)
bye{reason} ◀─────────────────────────────▶ (either side, then close)
```

1. **Handshake.** The DLL's first message is `hello`. The sidecar answers `welcome`.
   - If `hello.v` is not a supported version, the sidecar sends `bye{reason:"version", supported:[1]}` and closes. The DLL then stays offline and retries only after **30 s** (no retry storm).
   - An invalid `hello` (a required field missing or of the wrong type) gets `bye{reason:"protocol"}`.
   - No `hello` within **5 s** of connecting gets `bye{reason:"protocol"}`.
   - Before `hello`, the sidecar answers `ping` and ignores everything else.
   - The DLL sends `hello` **exactly once per connection**. A character or save change during a connection is reported with `ev.load` (or `ev.menu`), never with a second `hello`. A sidecar that does receive a second `hello` answers with a fresh `welcome` and replaces the stored hello fields (tolerated, not relied on).
   - **Right after `welcome`** the DLL reports the game tick (§4.7), also after a reconnect: if the tick runs, one fresh `state`; if it is stopped in a loaded game, `ev.pause{on:true}` then `state{rate:"paused"}`; at the main menu, `ev.pause{on:true}`, `ev.menu`, then `state{rate:"paused", ship:null}`. Until the first of these arrives the sidecar treats the tick as **unknown** and keeps its ack timers suspended; if none arrives within 5 s it logs a warning and assumes the tick runs.
2. **Heartbeat.** The DLL's IPC worker thread owns the socket, the handshake and the heartbeat, independent of the game tick (§11). After the handshake each side sends `ping{n}` every **2 s** (`welcome.heartbeat_ms`) and answers every received `ping` at once with `pong{n}` echoing `n`. Only `pong` resets the miss counter. After **3 consecutive pings without a pong**, a side closes the connection at its next tick, so a dead peer is detected within 6–8 s. The sidecar sends `bye{reason:"timeout"}` first; the DLL just closes and reconnects.
3. **Reconnect (DLL).** On EOF, error or timeout: close, then reconnect with backoff **1 s, 2 s, 5 s, 5 s…** (capped at 5 s). After `bye{reason:"version"}` or `bye{reason:"replaced"}`, wait **30 s** (two game instances on one port must not keep replacing each other). The connect itself is non-blocking `connect` plus `select` (≤ 250 ms) on the worker thread.
4. **Shutdown.** The sidecar sends `bye{reason:"shutdown"}` and closes on SIGTERM/SIGINT; the DLL backs off normally. The DLL may send `bye{reason:"shutdown"}` on game exit.
5. **Disconnect.** On disconnect the DLL **drops every command it has received but not yet applied**, and their acks. Nothing from an old connection is applied or acked after a reconnect. The sidecar resolves its unacked commands of that session as lost when the session ends.
6. **State after reconnect.** The DLL keeps its **last applied policy** across disconnects and reports it in the next `hello.policy`. The sidecar must not assume its earlier commands survived a game restart; it re-sends what it wants (W1-SIDECAR: policy persistence).
7. **Game tick stopped** (F1 pause, the unfocused-window pause, loading screens, the main menu). Normative for both sides:
   1. **Definitions.**
      - The **game tick** is the simulation step: the game-thread hook that advances the space simulation, where W2-REFLEX runs its reflexes and applies commands. It runs only while a game is loaded, unpaused and not loading. A per-frame hook that also runs in menus (render or UI frame) is **not** the tick.
      - The tick is **stopped** while any reason holds: F1 pause, the unfocused-window pause, a loading screen (a save load or a system transition), the main menu. The DLL keeps **one** stopped flag, the OR of all reasons, and sends `ev.pause` only when that flag changes. Overlapping reasons (F1, then alt-tab; alt-tab during a load) give one `on:true` edge and one `on:false` edge, sent when the last reason clears.
      - **Edge detection.** The game thread evaluates the reasons every frame from a hook that also runs while the simulation is stopped (for example the main-loop or UI frame hook) and posts changes to the worker. Backstop: the tick hook increments a counter, and if it has not advanced for 1 s while the flag says running, the worker counts the tick as stopped until it advances again (this covers a game thread blocked in a modal dialog). The worker is the only sender: it sends an edge when "flag OR stalled" changes.
   2. The DLL worker keeps answering `ping` and keeps sending its own pings while the tick is stopped, so a pause of any length never causes a timeout or a reconnect.
   3. When the tick stops, the DLL sends `ev.pause{on:true}` and then one `state` with `rate:"paused"`. When it resumes, it sends `ev.pause{on:false}` and then one fresh `state`. **No `state` is sent in between** (no producer runs).
   4. Commands that arrive while the tick is stopped in a loaded game are **queued by the worker** (in order; at most 64; beyond that the worker answers `err:"rate_limited"` at once) and **applied on the first tick after resume**. Each is acked only when applied, with `applied` as usual (a *deferred ack*). The DLL never acks before applying. At the main menu nothing is queued: the worker answers every command at once with `ok:false, err:"not_now"`.
   5. **Load boundaries.** Loading a save, starting a new game, respawning after death and returning to the main menu are load boundaries. A queued command never crosses one, so it can never be applied in a different save: the worker tags each command with the game generation (a counter the game thread increments at every load boundary), and at apply time a command from an older generation is not applied but acked `ok:false, err:"not_now", detail:"load"`. A system transition through a gate or hole is a stopped tick inside the same game, not a load boundary: its queue is applied after it.
   6. The sidecar starts every session with the tick unknown (§4.1) and suspends its 5 s ack timeout while the tick is unknown or stopped (`ev.pause{on:true}` or `ev.menu` until `ev.pause{on:false}`). It restarts the timeout in full when the tick runs. An ack that still arrives after the timeout is a *late ack* (§7.3): the sidecar reconciles its world model from it.
   7. **Push-to-talk:** whenever the DLL stops polling the key while it is held (focus lost, pause, menu, chat opened, or a deliberate disconnect), it sends `ptt{down:false, reason:…}` (§7.2). That cancels the utterance; the sidecar does not transcribe it. As a backstop for a lost cancel, the sidecar also cancels a held press on `ev.pause{on:true}`, `ev.menu` and `ev.load`. If the connection drops with the key held, the sidecar cancels the utterance when the session ends, and the DLL sends no release for the old press after reconnecting.
8. **Main menu and multiplayer.** The main menu is a stopped tick. Returning to it, the DLL sends `ev.pause{on:true}` (unless the tick is already stopped), then `ev.menu`, then one `state` with `rate:"paused"` and `ship: null`. The connection stays up. Loading a game from the menu keeps the tick stopped through the loading screen; then `ev.load`, and `ev.pause{on:false}` plus a fresh `state` once the simulation runs. The protocol is **single-player only**: on entering multiplayer the DLL sends `bye{reason:"shutdown", detail:"multiplayer"}`, closes, and stays offline until it is back in single player.

## 5. Common types

| Name | JSON | Range / rule |
|---|---|---|
| frac | number | 0.0 to 1.0 inclusive (hull, shield and damage are fractions, never percent) |
| count | int32 | ≥ 0 |
| name | string | ≤ 128 chars; a game nickname (for example `fcm_…`) or a display name |
| actor | string | `player`, `wing:<id>`, `carrier:<id>` or `other` (`<id>` is `[A-Za-z0-9_-]{1,32}`) |
| ship class `cls` | string | `fighter`, `freighter`, `gunboat`, `cruiser`, `battleship`, `carrier`, `transport`, `station`, `other` |
| carrier state | string | exactly the CONVENTIONS §9 names: `Stopped`, `DockedTravel`, `EscortTravel`, `Away`, `AmbushWaiting`, `UnderAttack`, `Destroyed` |

"opt" in the tables below means optional; "null ok" means the field may be JSON `null`.

### Policy object

Used in `hello.policy.<scope>`, in `policy.set` and in its ack's `applied`. Every field is optional in `policy.set` (a partial update); `applied` always carries the full resulting policy for that scope.

| Field | Type | DLL clamp (W2-REFLEX) | Suggested DLL default (INI) |
|---|---|---|---|
| `auto_bots` | bool | — | `true` |
| `bots_hull_below` | number | clamped to [0.05, 0.95] | 0.50 |
| `bots_reserve` | int | clamped to [0, nanobot max stock] | 0 |
| `critical_hull` | number | clamped to [`critical_hull_floor`, min(`bots_hull_below`, 0.95)]; `critical_hull_floor` is an INI value (default 0.25). A command may raise it, never lower it below the INI floor and never above `bots_hull_below`. If `bots_hull_below` is below the floor, `critical_hull` equals the floor (the floor wins). The clamp is re-applied whenever either field changes. | 0.25 |
| `release_reserve_when` | string | `never`, `capital_hostile_present`, `target_is_capital` | `never` |
| `auto_batts` | bool | — | `true` |
| `batts_shield_below` | number | clamped to [0.05, 0.95] | 0.25 |
| `batts_reserve` | int | clamped to [0, battery max stock] | 0 |

**Hard floor (D-11.1).** Below `critical_hull` the reflex fires nanobots whenever any are in stock, regardless of `auto_bots`, `bots_reserve` and `release_reserve_when`. No command can disable this. Because `critical_hull` never exceeds `bots_hull_below`, raising it cannot turn the floor into a way of spending a reserve early: "save bots for the cruiser" holds until hull is genuinely critical.

## 6. Control messages

#### `hello`

DLL → sidecar. The first message of every connection.

| Field | Type | Req | Rule |
|---|---|---|---|
| `dll` | name | yes | DLL version, e.g. `0.1.0` |
| `game` | name | yes | game build string |
| `char` | name, null ok | opt | character name; `null` at the main menu |
| `save` | name, null ok | opt | save id; `null` if none loaded |
| `policy` | object | opt | `{"player": Policy, "carrier": Policy}`: the policies currently applied |
| `features` | list of name (≤ 32) | opt | DLL capabilities, e.g. `reflex`, `carrier`, `wing`. Lets a newer sidecar avoid commands an older DLL lacks. |
| `ptt_vk` | int 1–255 | opt | the virtual-key code the DLL polls for push-to-talk, read from the DLL INI. **Source of truth:** at deploy, the installer writes the DLL INI `ptt_vk` from the sidecar config `ptt_key` (`numpad_period` = 110 = VK_DECIMAL, the default per DESIGN D-11.3; `numpad_minus` = 109, which also turns on the keymap patch that removes vanilla `USER_ZOOM_IN`). At runtime the DLL polls its INI value; both sides log a mismatch (see `welcome.ptt_vk`). |

#### `welcome`

Sidecar → DLL. The reply to a supported `hello`.

| Field | Type | Req | Rule |
|---|---|---|---|
| `sidecar` | name | yes | sidecar version |
| `features` | list of string | yes | subset of `stt`, `tts`, `llm`, `grammar`: what this sidecar can do right now. If `tts` is present the DLL may leave dynamic lines to the sidecar (reflex callouts stay local). |
| `heartbeat_ms` | int 10–60000 | opt | the ping interval the sidecar uses (2000; tests use less) |
| `profile` | string | opt | `live` or `test` (informational, for logs) |
| `ptt_vk` | int 1–255 | opt | the VK the sidecar's `ptt_key` maps to. The DLL logs a mismatch with its INI value and keeps polling its own. |

#### `bye`

Either direction. The sender closes the connection right after it.

| Field | Type | Req | Rule |
|---|---|---|---|
| `reason` | string | yes | `version`, `replaced`, `shutdown`, `timeout`, `protocol` |
| `detail` | string ≤ 256 | opt | human-readable |
| `supported` | list of int | opt | with `reason:"version"`: the versions the sender speaks |

#### `ping`

Either direction, every 2 s after the handshake. `n` (uint32, opt): a counter the peer echoes.

#### `pong`

Either direction, immediately on a `ping`. `n` (uint32, opt): the `n` of that ping.

## 7. Game → sidecar

### 7.1 State snapshot

#### `state`

A **coalesced full snapshot**: the DLL keeps only the latest unsent one. It is sent at **2 Hz** in space with hostiles present, **0.5 Hz** in space and calm, and **0.1 Hz** when docked. While the game tick is stopped none is sent, apart from the single `rate:"paused"` snapshot at the start of the pause (§4.7). A group that a DLL build cannot provide is absent; a group that applies but is empty is `null` (for example `target: null`).

| Field | Type | Req | Rule |
|---|---|---|---|
| `rate` | string | yes | `combat` (2 Hz), `calm` (0.5 Hz), `docked` (0.1 Hz), `paused` (the one snapshot sent when the tick stops; the next one follows the resume) |
| `ship` | object, null ok | opt | player ship, below; `null` while dead or at the main menu |
| `target` | object, null ok | opt | current target, below |
| `threat` | object | opt | below |
| `wing` | list (≤ 64) | opt | wingmen, below. Reserved for W4-WINGMEN |
| `carriers` | list (≤ 64) | opt | owned carriers, below. Reserved for W2-CARRIER-GAME |
| `ui` | object | opt | below. The sidecar uses it to mute voice and banter |

`ship`: `hull` frac (req), `shield` frac (req), `shield_up` bool, `bots` count, `batts` count, `bots_max` count, `batts_max` count, `speed` number ≥ 0 (m/s), `mode` (req) one of `free`, `cruise`, `lane`, `docked`, `dead`, `menu`, `system` name (null ok), `base` name (null ok; set when docked), `near` name (null ok; nearest base or zone).

`target`: `obj` uint32 (req; the space object id, the same name as in `ev.target`), `name` name, `faction` name (null ok), `cls`, `hull` frac, `shield` frac, `dist` number ≥ 0 (m), `hostile` bool.

`threat`: `hostiles` count (req; hostiles within the DLL's threat radius), `capital_hostile` bool, `incoming_missiles` int32 ≥ 0 (null ok, if obtainable).

`wing[]`: `id` name (req), `name`, `hull` frac, `shield` frac, `state` one of `follow`, `engage`, `retreat`, `guard`, `docked`, `dist` number ≥ 0.

`carriers[]`: `id` name (req), `name`, `state` carrier state (req), `hull` frac, `bots` count, `eta_s` number ≥ 0 (null ok), `system` name (null ok).

`ui`: `paused` bool, `menu_open` bool, `focused` bool (FL window in the foreground), `chat_typing` bool.

### 7.2 Events

Edge-triggered: sent at once when the edge happens, debounced in the DLL as noted. Each is one message type.

#### `ev.hull`

Player hull crossed a band. `band` (req) one of 75, 50, 25, 10 (percent band, the only percent value in the protocol); `dir` (req) `down` or `up`; `hull` frac (opt, the current value). Hysteresis ±5 percentage points.

#### `ev.shield`

`state` (req): `down` or `up`.

#### `ev.reflex`

Every reflex use (the sidecar plays a canned callout). `what` (req) `bots` or `batts`; `by` (req) `player` or `carrier`; `carrier` name (opt; the carrier id when `by` is `carrier`); `left` count (req; stock after use); `hull` frac (opt).

#### `ev.low_stock`

Stock fell below the DLL's warning threshold; once per crossing. `what` (req) `bots` or `batts`; `by` (opt) `player` (default) or `carrier`; `carrier` name (opt); `left` count (req).

#### `ev.target`

Target changed; at most 2 per second. `obj` uint32 or `null` (req; the space object id, `null` = target cleared, other fields then absent); `name`; `cls`; `faction` (null ok); `hostile` bool.

#### `ev.kill`

`victim` name (req); `cls`; `faction` (null ok); `by` actor (req).

#### `ev.hostiles`

Sent when the hostile count crosses 0 ↔ > 0, or a capital hostile appears. `count` count (req); `capital` bool (req); `faction` name (null ok; the dominant hostile faction).

#### `ev.hit`

Banter fuel only; at most 1 per 5 s. `attacker` name (null ok); `dmg` frac (req; hull fraction lost since the last `ev.hit`).

#### `ev.dock`

`base` name (req).

#### `ev.undock`

`base` name (req).

#### `ev.system`

Entered a system. `system` name (req); `from` name (null ok); `via` (req) `gate`, `hole`, `load` or `other`.

#### `ev.lane`

Trade lane. `state` (req): `enter`, `exit` or `disrupted`.

#### `ev.cruise`

Cruise engines. `state` (req): `enter`, `exit` or `disrupted`.

#### `ev.wing`

Reserved for W4-WINGMEN. `wing` name (req; the wingman id); `what` (req) `down`, `damaged`, `retreating` or `rejoined`.

#### `ev.carrier`

Reserved for W2-CARRIER-GAME. A carrier state-machine edge (CONVENTIONS §9), including ambush alerts and distress. `carrier` name (req; the carrier id); `state_from` (req) and `state_to` (req) carrier states; `detail` string ≤ 256 (opt).

#### `ev.death`

Player death. `save` name (null ok). Memory bookkeeping (R6 §6.3): events after the last save may become "unlived" when the player reloads.

#### `ev.load`

A save was loaded. `save` name (req); `char` name (null ok; lets the sidecar key memory when `hello.char` was `null`).

#### `ev.save`

The game was saved. `save` name (req).

#### `ev.menu`

Returned to the main menu: no ship, no game loaded (§4.8). No fields. A `state` with `ship: null` follows.

#### `ev.pause`

The game tick stopped or resumed (§4.7). `on` bool (req): `true` = stopped (F1 pause, unfocused pause, loading screen), `false` = running again. The sidecar suspends its ack timeouts while `on` is true.

#### `ptt`

Push-to-talk edge from the DLL's key polling: `down` bool (req); `reason` (opt, only with `down:false`) one of `focus_lost`, `pause`, `menu`, `chat`, `disconnect`. The DLL polls `GetAsyncKeyState(ptt_vk)` each tick only while the Freelancer window is in the foreground and chat is closed, and sends `ptt{down:true}` on press and `ptt{down:false}` on release. **Whenever polling stops while the key is held**, it sends `ptt{down:false, reason:…}` at once: that is a *cancel*, and the sidecar discards the utterance (§4.7). A `down:true` while already down, or a `down:false` (release or cancel) while not down, is ignored. The sidecar tracks the pressed state per session: only the session that owns the mic (the active one) counts, and a held press is cancelled on `ev.pause{on:true}`, `ev.menu` and `ev.load` (§4.7). Default key: numpad period, **VK_DECIMAL = 110** (DESIGN D-11.3). `ptt_key = numpad_minus` (VK 109) requires the keymap patch that removes vanilla `USER_ZOOM_IN`. The sidecar never reads keys itself. On `down` it starts keeping mic audio (with a 300 ms pre-roll); on `up` it adds a 150 ms tail and hands the clip to speech-to-text.

### 7.3 Acks

#### `ack`

The DLL's answer to every command, by `id`, at most once per command.

| Field | Type | Req | Rule |
|---|---|---|---|
| `id` | string | yes | the command's `id` |
| `ok` | bool | yes | `true` = applied |
| `applied` | object | opt | with `ok:true`: what took effect, **after clamping**. For `policy.set`: the full resulting policy of that scope, so the sidecar's world model stays truthful. |
| `err` | string | if `ok` is false | `unknown_type`, `unknown_field`, `bad_value`, `rate_limited`, `unsupported`, `not_now`, `internal` |
| `detail` | string ≤ 256 | opt | human-readable |

**Ack order.** Commands that reach the game thread are acked in the order they were received: the queue is first in, first out, and the game thread acks each command as it applies it (or refuses it at apply time, for example `not_now` after a load boundary). The worker's immediate acks are sent at once and may overtake acks of earlier commands still waiting for the tick. These are `rate_limited`, a full queue, `not_now` at the main menu, and validation errors (`unknown_type`, `unknown_field`, `bad_value`). They are always `ok:false` and change nothing, so a sidecar that reconciles from `applied` still sees every change in order: the last `ok:true` `policy.set` ack of a scope carries that scope's current policy.

**Deferred and late acks.** A command received while the tick is stopped is acked when it is applied after the resume (§4.7). The sidecar's ack timeout is **5 s**, suspended while paused. When it expires, the sidecar reports the command as overdue to whoever sent it, but **keeps it pending (marked late) until the session ends**. If its ack still arrives, the sidecar reconciles its world model from that ack's `applied` instead of dropping it. Commands are never re-sent automatically. At session end every unacked command counts as lost (the DLL drops unapplied commands on disconnect, §4.5).

## 8. Sidecar → game commands

Every command carries an `id` and gets exactly one `ack`. A rejected command changes nothing (atomic). Reserved commands may be answered `err:"unsupported"` until their wave lands. A command that arrives while the game tick is stopped is queued and acked when applied (§4.7).

#### `policy.set`

Strict: an unknown field fails the whole command with `err:"unknown_field"`, so a policy is never half-applied silently.

| Field | Type | Req | Rule |
|---|---|---|---|
| `scope` | string | yes | `player` or `carrier` |
| `carrier` | name | opt | only with `scope:"carrier"` (otherwise `bad_value`): one carrier's id. Absent = the default policy shared by all carriers |
| policy fields | | ≥ 1 | any subset of the Policy object (§5) |

Example: "save nanobots for the cruiser" → `{"t":"policy.set","id":"c-4","scope":"player","bots_reserve":7,"release_reserve_when":"capital_hostile_present"}`.

#### `act`

One-shot action, executed like the native key; refused (`not_now`) when impossible (docked, no stock, dead). `do` (req) `use_bots` or `use_batts`; `scope` (opt) `player` (default) or `carrier`; `carrier` name (opt; only with `scope:"carrier"`).

#### `wing.formation`

Reserved for W4-WINGMEN. `form` (req): `tight`, `loose`, `line` or `escort_carrier`.

#### `wing.focus`

Reserved for W4-WINGMEN. `target` (req): `player_target`, `nearest_hostile`, `capital` or `id:<n>`; resolved in the DLL.

#### `wing.order`

Reserved for W4-WINGMEN. `order` (req): `follow`, `engage`, `hold`, `retreat`, `guard_carrier` or `regroup`; `wing` name (opt): a wing id, or `all` (default).

#### `wing.policy`

Reserved for W4-WINGMEN. Strict like `policy.set`. `retreat_hull_below` number (req; clamped by the DLL to [0.05, 0.95]).

#### `say`

Presentation only: the DLL shows a subtitle or comm line. The sidecar plays the audio itself on the host. `speaker` (req) `copilot` or `wing:<id>`; `text` (req) string ≤ 500 chars; `prio` (opt) int 0–3 (0 = banter, 1 = conversation, 2 = ack, 3 = alert); `subtitle` bool (opt; `true` = show it). With TTS unavailable the sidecar still sends `say{subtitle:true}`.

## 9. DLL-side validation, clamps and rate limits

Enforced by the DLL (W2-REFLEX); the sidecar also validates its own commands before sending (a bug there raises in the sidecar and is never sent).

- **Types:** a wrong JSON type or an enum value outside the whitelist → `err:"bad_value"`.
- **Ranges:** numeric policy values outside their range are **clamped**, not rejected; the ack's `applied` shows the clamped value.
  - `0.05 ≤ *_below ≤ 0.95` (`bots_hull_below`, `batts_shield_below`, `retreat_hull_below`);
  - reserves in `[0, max stock]`;
  - `critical_hull` in `[critical_hull_floor, min(bots_hull_below, 0.95)]`, re-clamped whenever either changes; it is a hard floor the LLM cannot lower or disable, and it never exceeds the normal nanobot threshold.
- **Rate limits** (guards against an LLM loop): at most **10 commands per second** and at most **2 policy changes per second** (`policy.set` + `wing.policy`), sliding 1 s windows, counted when a command arrives. Excess commands are answered `err:"rate_limited"` and dropped. (Only the stopped-tick queue of §4.7 holds commands, and only those within the limits.)
- **Timing:** accepted commands apply on the next game tick, on the game's main thread; while the tick is stopped they wait in the §4.7 queue.

## 10. Extension rules

1. **Unknown `t`:** the receiver ignores the message with one log line (the sidecar logs the first occurrence of each type per connection at WARNING, later ones at DEBUG; after 64 distinct unknown types on one connection it logs one cap notice and then only DEBUG, so a flood of new types cannot flood the log). The connection stays up. On the sidecar, a later-wave handler registered for a new type receives it even before this spec lists it.
2. **Unknown fields:** ignored by the receiver, **except** in the strict commands `policy.set` and `wing.policy`, where they fail the command with `unknown_field`.
3. **New fields are optional.** A required field is never added to an existing type without bumping `v`.
4. **New types** for later waves (carrier, wingmen, hiring, escalation) use a dotted namespace: game events `ev.<area>[.<what>]`, commands `<area>.<verb>` (for example `carrier.order`, `hire.offer`). Add them to this file and to `protocol.py` in the same change.
5. **New enum values** for an existing field need care: an older peer rejects them (`bad_value`) or ignores the message. Add them only together with a `features` entry in `hello` or `welcome` that announces support.
6. **Version bump:** an incompatible change sets `v` to 2. A v1 sidecar answers a v2 `hello` with `bye{reason:"version", supported:[1]}`.

## 11. Notes for the DLL implementation (W2-REFLEX)

From R6 §2.3; these are requirements on the DLL side.

- **MUST: the IPC worker thread owns the connection.** Connect, `hello`, receiving `welcome`/`bye`, answering `ping` with `pong`, sending its own pings and detecting missed pongs all happen on the worker, never on the game tick. The worker keeps doing this while the tick is stopped (§4.7), so a pause never looks like a dead peer to either side.
- **MUST: release push-to-talk when polling stops.** The game thread tracks whether the PTT key is down. On focus loss, pause, menu, chat or a deliberate disconnect it posts `ptt{down:false, reason:…}` before it stops polling.
- **MUST: the stopped-tick protocol** of §4.7: one stopped flag (the OR of all reasons) with a stall watchdog on the tick counter; `ev.pause{on}` plus one `state` on each edge; queue incoming commands (at most 64) and ack them when applied; `not_now` at once at the main menu; no `state` stream while stopped.
- **MUST: report the tick right after `welcome`** (§4.1), on every connection, including a reconnect while stopped or at the menu.
- **MUST: never apply a command across a load boundary** (§4.7.5): tag queued commands with the game generation and ack stale ones `not_now`.
- **MUST: ack in command order** (§7.3); only the worker's immediate `ok:false` acks may overtake.
- **MUST: drop unapplied commands on disconnect** (§4.5) and never ack a command from an earlier connection.
- **MUST: integer widths** of §3: parse `seq`, `n` and `obj` as uint32, `gt` as int64, the rest as int32; a line with an integer outside int64 is malformed.
- **Never touch a socket on the game thread.** Every Winsock `recv`/`send` under Wine is a wineserver round trip (`dlls/ntdll/unix/socket.c`: `sock_recv` issues `SERVER_START_REQ(recv_socket)` before reading; `sock_send` likewise; VERIFIED from source, R6 §2.1). Run a dedicated IPC worker thread that `select()`s with a ≈ 50 ms timeout; never spin on `recv`.
- **Game thread ↔ worker:** the game thread only locks a mutex and pushes to or swaps a deque. No Winsock calls, no waits, no condition-variable blocking on the game thread. Commands are parsed and validated into POD structs on the worker and applied by the game thread on its next tick.
- **Outbox:** bounded (for example 256 lines). Snapshots are coalesced (`PostLatest`: only the newest unsent one is kept). While disconnected, posting is a no-op (keep at most the last snapshot), so nothing piles up while the sidecar is absent.
  - **Never dropped:** `hello`, `bye`, `ping`, `pong`, `ack`, `ptt`, `ev.pause`, `ev.menu`, `ev.load`, `ev.save`, `ev.death`.
  - **When full:** drop the oldest `state` first; if none is queued, drop the oldest other event (`ev.hit`, `ev.target`, `ev.hull` and the rest). Count the drops and log them once per second at most.
  - **Only never-dropped lines left:** the outbox may grow past its bound up to a hard cap (for example 1024 lines or 1 MiB). Reaching the hard cap means the sidecar is not reading: the worker closes the connection, discards the outbox and the unapplied commands (§4.5), and reconnects with the §4 backoff.
- **Startup:** call `WSAStartup` and start the worker from the module init hook, **not from `DllMain`** (loader lock). On shutdown set the stop flag and `closesocket` to break `select`; do not `join` inside `DLL_PROCESS_DETACH`.
- **Partial I/O:** handle partial sends; split received bytes on `\n`; enforce the 64 KiB line cap and skip an oversize line up to its newline (§2).
- **Absence:** with the sidecar absent there is at most one "copilot link offline" log line, quiet retries with the §4 backoff, and no frame-time impact.
- **Port:** env `FLCOPILOT_PORT` (Wine passes the Unix environment through; UNVERIFIED until S-UI), else the INI next to the DLL, else 29170.
- **UNVERIFIED until S-UI:** loopback TCP from inside the running Freelancer process (E9), and `GetAsyncKeyState` delivery of VK 110 and the X mouse buttons under Wine (E10).

## 12. Notes for the sidecar implementation

- `asyncio.start_server(host="127.0.0.1", family=AF_INET, limit=65535)`; lines are read with `StreamReader.readuntil(b"\n")`. `readline()` is not used because on overrun it silently clears its buffer, so the rest of an oversize line would then be parsed as a new message; `readuntil` leaves the data in place and the server discards the whole line explicitly.
- Handlers are registered with `HandlerRegistry.register_handler(t, fn)` (exact type, `prefix.*`, or `*`) and `on_session_start` / `on_session_end`. Later waves add features this way without editing the server.
- Profiles (CONVENTIONS §13): `--profile live` for play; `--profile test` for every harness, lane, soak and CI use (null audio sink, fake transcriber/TTS/brain, `--mic-file`). The test profile refuses the play port 29170 unless explicitly forced.
- `Session.send_command(t, on_late=None, **fields)` returns a future: the ack, or `None` when it is overdue or the session ends. A late ack goes to `on_late(ack)` and to `Session.reconciled`. `Session.tick` is `unknown` from `welcome` until the first `state`, `ev.pause` or `ev.menu` (or 5 s), then `running` or `stopped`; ack timers run only while it is `running` (`Session.paused` is true otherwise).
- The voice pipeline tracks the push-to-talk state of the session that owns the mic and ignores unmatched edges (§7.2). Unknown message types are logged at WARNING for the first 64 distinct types per connection, then one cap notice, then at DEBUG (§10).

## 13. Example session

```
DLL → {"v":1,"t":"hello","seq":1,"gt":0,"dll":"0.1.0","game":"FLHD","char":"Test Pilot","save":"slot1","policy":{"player":{"auto_bots":true,"bots_hull_below":0.5,"bots_reserve":0,"critical_hull":0.25,"release_reserve_when":"never","auto_batts":true,"batts_shield_below":0.25,"batts_reserve":0}},"features":["reflex"],"ptt_vk":110}
SC  → {"v":1,"t":"welcome","seq":1,"sidecar":"0.1.0","features":["stt","tts"],"heartbeat_ms":2000,"profile":"live","ptt_vk":110}
DLL → {"v":1,"t":"state","seq":2,"gt":81234,"rate":"combat","ship":{"hull":0.82,"shield":0.1,"shield_up":true,"bots":7,"batts":4,"mode":"free","system":"test_system"},"target":{"obj":40213,"name":"Bandit","faction":"test_faction","cls":"fighter","hull":0.6,"shield":0.0,"dist":850,"hostile":true},"threat":{"hostiles":3,"capital_hostile":false},"ui":{"paused":false,"menu_open":false,"focused":true,"chat_typing":false}}   (tick report after welcome, §4.1)
DLL → {"v":1,"t":"ptt","seq":3,"gt":82000,"down":true}
DLL → {"v":1,"t":"ptt","seq":4,"gt":83400,"down":false}
SC  → {"v":1,"t":"policy.set","seq":2,"id":"c-1","scope":"player","bots_reserve":7,"release_reserve_when":"capital_hostile_present"}
DLL → {"v":1,"t":"ack","seq":5,"gt":83950,"id":"c-1","ok":true,"applied":{"auto_bots":true,"bots_hull_below":0.5,"bots_reserve":7,"critical_hull":0.25,"release_reserve_when":"capital_hostile_present","auto_batts":true,"batts_shield_below":0.25,"batts_reserve":0}}
SC  → {"v":1,"t":"say","seq":3,"id":"c-2","speaker":"copilot","text":"Copy. Holding 7 nanobots for the capital ship.","prio":2,"subtitle":true}
DLL → {"v":1,"t":"ack","seq":6,"gt":84000,"id":"c-2","ok":true,"applied":{"shown":true}}
SC  → {"v":1,"t":"ping","seq":4,"n":1}
DLL → {"v":1,"t":"pong","seq":7,"gt":84100,"n":1}
DLL → {"v":1,"t":"ev.pause","seq":8,"gt":90000,"on":true}                       (F1 pressed)
DLL → {"v":1,"t":"state","seq":9,"gt":90000,"rate":"paused","ship":{"hull":0.82,"shield":0.4,"mode":"free"}}
SC  → {"v":1,"t":"act","seq":5,"id":"c-3","do":"use_bots"}                     (queued by the DLL)
SC  → {"v":1,"t":"ping","seq":6,"n":2}
DLL → {"v":1,"t":"pong","seq":10,"gt":90000,"n":2}                              (worker answers while paused)
DLL → {"v":1,"t":"ev.pause","seq":11,"gt":90000,"on":false}                     (40 s later: resumed)
DLL → {"v":1,"t":"ack","seq":12,"gt":90016,"id":"c-3","ok":true,"applied":{"do":"use_bots","left":6}}
DLL → {"v":1,"t":"state","seq":13,"gt":90016,"rate":"combat","ship":{"hull":0.97,"shield":0.4,"bots":6,"mode":"free"}}
```

## 14. Change log

- **v1 (P0-SIDECAR, 2026-10-17).** First version, adapted from R6 §3, with these deliberate changes:
  - `ev.hit.dmg_pct` became `dmg` as a fraction, like every other ratio;
  - the `release_reserve_when` value `hull_critical` was dropped, because the hard floor already spends the reserve below `critical_hull`;
  - `state.carrier` became the list `state.carriers` (several carriers can be owned);
  - top-level `id` is reserved for command ids, so `ev.target.id` became `obj`, `ev.wing.id` became `wing` and `ev.carrier.id` became `carrier`;
  - added: `bye.supported`, `hello.features`, `hello.ptt_vk`, `ev.load.char`, `ev.system.from`, `welcome.profile`, `welcome.heartbeat_ms`, and the optional `scope`/`carrier` on `act`;
  - `say` is a command with an `id` and an ack, like every other sidecar → game message.
- **v1, review round 1 (2026-10-18), before freeze:** the stopped-tick lifecycle (§4.7: worker owns the heartbeat; `ev.pause{on}` replaces `ev.pause{paused}`; one `state` per pause edge with the new `rate:"paused"`; queued commands with deferred acks; late-ack reconciliation; ack timeouts suspended while paused); `ptt.reason` cancels; `ev.menu`; single-player only; `hello` once per connection; DLL drops unapplied commands on disconnect; per-process command ids; `critical_hull` capped at `bots_hull_below`; `welcome.ptt_vk` and the deploy-time source of truth for the key; duplicate keys invalid; `state.target.id` became `obj`.
- **v1, review round 2 polish (2026-10-18), before freeze:** the tick is reported right after `welcome` and is unknown until then (§4.1); the game tick, the single stopped flag, edge detection and its watchdog are defined (§4.7.1); the main menu is a stopped tick with immediate `not_now`; load boundaries drop queued commands (§4.7.5); ack order (§7.3); outbox rules when full (§11); integer widths (§3); the sidecar tracks push-to-talk per session and cancels a held press on pause, menu and load (§7.2).
