# IPC protocol v1: game DLL ↔ copilot sidecar

- **Status:** v1, written by P0-SIDECAR (2026-10-17). ARCH-0 freezes it after review. After that, a change either adds optional fields (no version bump) or bumps `v`.
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

- **NDJSON:** one UTF-8 JSON **object** per line, terminated by `\n`. A trailing `\r` before the `\n` is tolerated and ignored. Empty lines are ignored.
- **Size:** a line, including its `\n`, is at most **65 536 bytes** (64 KiB). Senders never produce a longer line.
- **Encoding:** compact JSON (`ensure_ascii` off). `NaN` and `Infinity` are invalid. JSON string escaping means a message can never contain a raw newline.
- **Receiver behaviour on a bad line** (both sides). The line is logged and dropped; the connection stays up:
  - not UTF-8, not JSON, not an object, or an envelope error → dropped (`malformed`);
  - longer than 64 KiB → skipped **up to and including its newline**, even if it arrives in many reads, so that the tail of an oversize line is never parsed as a new message (`oversize`);
  - a valid envelope with an invalid payload for a known type → dropped (`invalid`);
  - unknown `t` → ignored (§9).

## 3. Envelope

Every message is a JSON object with these fields:

| Field | Type | Who | Rule |
|---|---|---|---|
| `v` | int | both | Protocol version, `1`. |
| `t` | string | both | Message type, 1–64 chars (§6–§8). |
| `seq` | int ≥ 0 | both | Per direction, per connection: starts at 1 and increases by 1 per message. Receivers log gaps and regressions but never reject on them. |
| `gt` | int ≥ 0 | DLL only | Game time in ms on the DLL side. The DLL always sends it (0 when no game is loaded); it may restart after a load. The sidecar omits it. Receivers tolerate its absence. |
| `id` | string | commands, acks | `^[A-Za-z0-9_.:-]{1,32}$`. The sidecar uses `c-<n>`, unique per connection. A top-level `id` means a command id and nothing else: payloads name object ids differently (`obj`, `wing`, `carrier`). |

Payload fields sit next to the envelope fields (flat, no nesting under a `payload` key).

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
   - A second `hello` on the same connection is answered with a fresh `welcome` (re-handshake; e.g. after loading a save).
2. **Heartbeat.** After the handshake each side sends `ping{n}` every **2 s** (`welcome.heartbeat_ms`) and answers every received `ping` at once with `pong{n}` echoing `n`. Only `pong` resets the miss counter. After **3 consecutive pings without a pong**, a side closes the connection at its next tick, so a dead peer is detected within 6–8 s. The sidecar sends `bye{reason:"timeout"}` first; the DLL just closes and reconnects.
3. **Reconnect (DLL).** On EOF, error or timeout: close, then reconnect with backoff **1 s, 2 s, 5 s, 5 s…** (capped at 5 s). After `bye{reason:"version"}` or `bye{reason:"replaced"}`, wait **30 s** (two game instances on one port must not keep replacing each other). The connect itself is non-blocking `connect` plus `select` (≤ 250 ms) on the worker thread.
4. **Shutdown.** The sidecar sends `bye{reason:"shutdown"}` and closes on SIGTERM/SIGINT; the DLL backs off normally. The DLL may send `bye{reason:"shutdown"}` on game exit.
5. **State after reconnect.** The DLL keeps its **last applied policy** across disconnects and reports it in the next `hello.policy`. The sidecar must not assume its earlier commands survived a game restart; it re-sends what it wants (W1-SIDECAR: policy persistence).

## 5. Common types

| Name | JSON | Range / rule |
|---|---|---|
| frac | number | 0.0 to 1.0 inclusive (hull, shield and damage are fractions, never percent) |
| count | int | ≥ 0 |
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
| `critical_hull` | number | clamped to [`critical_hull_floor`, 0.95]; `critical_hull_floor` is an INI value (default 0.25). A command may raise the floor's trigger, never lower it below the INI floor. | 0.25 |
| `release_reserve_when` | string | `never`, `capital_hostile_present`, `target_is_capital` | `never` |
| `auto_batts` | bool | — | `true` |
| `batts_shield_below` | number | clamped to [0.05, 0.95] | 0.25 |
| `batts_reserve` | int | clamped to [0, battery max stock] | 0 |

**Hard floor (D-11.1).** Below `critical_hull` the reflex fires nanobots whenever any are in stock, regardless of `auto_bots`, `bots_reserve` and `release_reserve_when`. No command can disable this.

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
| `ptt_vk` | int 1–255 | opt | the virtual-key code the DLL polls for push-to-talk (default 110, VK_DECIMAL). The sidecar logs a mismatch with its own `ptt_key`; the DLL's value wins. |

#### `welcome`

Sidecar → DLL. The reply to a supported `hello`.

| Field | Type | Req | Rule |
|---|---|---|---|
| `sidecar` | name | yes | sidecar version |
| `features` | list of string | yes | subset of `stt`, `tts`, `llm`, `grammar`: what this sidecar can do right now. If `tts` is present the DLL may leave dynamic lines to the sidecar (reflex callouts stay local). |
| `heartbeat_ms` | int 100–60000 | opt | the ping interval the sidecar uses (2000) |
| `profile` | string | opt | `live` or `test` (informational, for logs) |

#### `bye`

Either direction. The sender closes the connection right after it.

| Field | Type | Req | Rule |
|---|---|---|---|
| `reason` | string | yes | `version`, `replaced`, `shutdown`, `timeout`, `protocol` |
| `detail` | string ≤ 256 | opt | human-readable |
| `supported` | list of int | opt | with `reason:"version"`: the versions the sender speaks |

#### `ping`

Either direction, every 2 s after the handshake. `n` (int ≥ 0, opt): a counter the peer echoes.

#### `pong`

Either direction, immediately on a `ping`. `n` (int ≥ 0, opt): the `n` of that ping.

## 7. Game → sidecar

### 7.1 State snapshot

#### `state`

A **coalesced full snapshot**: the DLL keeps only the latest unsent one. It is sent at **2 Hz** in space with hostiles present, **0.5 Hz** in space and calm, and **0.1 Hz** when docked or paused. A group that a DLL build cannot provide is absent; a group that applies but is empty is `null` (for example `target: null`).

| Field | Type | Req | Rule |
|---|---|---|---|
| `rate` | string | yes | `combat` (2 Hz), `calm` (0.5 Hz), `docked` (0.1 Hz; also used while paused) |
| `ship` | object, null ok | opt | player ship, below; `null` while dead or at the main menu |
| `target` | object, null ok | opt | current target, below |
| `threat` | object | opt | below |
| `wing` | list (≤ 64) | opt | wingmen, below. Reserved for W4-WINGMEN |
| `carriers` | list (≤ 64) | opt | owned carriers, below. Reserved for W2-CARRIER-GAME |
| `ui` | object | opt | below. The sidecar uses it to mute voice and banter |

`ship`: `hull` frac (req), `shield` frac (req), `shield_up` bool, `bots` count, `batts` count, `bots_max` count, `batts_max` count, `speed` number ≥ 0 (m/s), `mode` (req) one of `free`, `cruise`, `lane`, `docked`, `dead`, `menu`, `system` name (null ok), `base` name (null ok; set when docked), `near` name (null ok; nearest base or zone).

`target`: `id` int ≥ 0 (req; the space object id), `name` name, `faction` name (null ok), `cls`, `hull` frac, `shield` frac, `dist` number ≥ 0 (m), `hostile` bool.

`threat`: `hostiles` count (req; hostiles within the DLL's threat radius), `capital_hostile` bool, `incoming_missiles` int ≥ 0 (null ok, if obtainable).

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

Target changed; at most 2 per second. `obj` int ≥ 0 or `null` (req; the space object id, `null` = target cleared, other fields then absent); `name`; `cls`; `faction` (null ok); `hostile` bool.

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

#### `ev.pause`

`paused` bool (req).

#### `ptt`

Push-to-talk edge from the DLL's key polling: `down` bool (req). The DLL polls `GetAsyncKeyState(ptt_vk)` each tick only while the Freelancer window is in the foreground and chat is closed, and sends `ptt{down:true}` on press and `ptt{down:false}` on release. Default key: numpad period, **VK_DECIMAL = 110** (DESIGN D-11.3). `ptt_key = numpad_minus` (VK 109) requires the keymap patch that removes vanilla `USER_ZOOM_IN`. The sidecar never reads keys itself. On `down` it starts keeping mic audio (with a 300 ms pre-roll); on `up` it adds a 150 ms tail and hands the clip to speech-to-text.

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

The sidecar treats a command with no ack within **5 s** as lost (logged; it is not re-sent automatically).

## 8. Sidecar → game commands

Every command carries an `id` and gets exactly one `ack`. A rejected command changes nothing (atomic). Reserved commands may be answered `err:"unsupported"` until their wave lands.

#### `policy.set`

Strict: an unknown field fails the whole command with `err:"unknown_field"`, so a policy is never half-applied silently.

| Field | Type | Req | Rule |
|---|---|---|---|
| `scope` | string | yes | `player` or `carrier` |
| `carrier` | name | opt | with `scope:"carrier"`: one carrier's id. Absent = the default policy shared by all carriers |
| policy fields | | ≥ 1 | any subset of the Policy object (§5) |

Example: "save nanobots for the cruiser" → `{"t":"policy.set","id":"c-4","scope":"player","bots_reserve":7,"release_reserve_when":"capital_hostile_present"}`.

#### `act`

One-shot action, executed like the native key; refused (`not_now`) when impossible (docked, no stock, dead). `do` (req) `use_bots` or `use_batts`; `scope` (opt) `player` (default) or `carrier`; `carrier` name (opt).

#### `wing.formation`

Reserved for W4-WINGMEN. `form` (req): `tight`, `loose`, `line` or `escort_carrier`.

#### `wing.focus`

Reserved for W4-WINGMEN. `target` (req): `player_target`, `nearest_hostile`, `capital` or `id:<n>`; resolved in the DLL.

#### `wing.order`

Reserved for W4-WINGMEN. `order` (req): `follow`, `engage`, `hold`, `retreat`, `guard_carrier` or `regroup`; `wing` name (opt): a wing id, or `all` (default).

#### `wing.policy`

Reserved for W4-WINGMEN. Strict like `policy.set`. `retreat_hull_below` number (clamped by the DLL to [0.05, 0.95]).

#### `say`

Presentation only: the DLL shows a subtitle or comm line. The sidecar plays the audio itself on the host. `speaker` (req) `copilot` or `wing:<id>`; `text` (req) string ≤ 500 chars; `prio` (opt) int 0–3 (0 = banter, 1 = conversation, 2 = ack, 3 = alert); `subtitle` bool (opt; `true` = show it). With TTS unavailable the sidecar still sends `say{subtitle:true}`.

## 9. DLL-side validation, clamps and rate limits

Enforced by the DLL (W2-REFLEX); the sidecar also validates its own commands before sending (a bug there raises in the sidecar and is never sent).

- **Types:** a wrong JSON type or an enum value outside the whitelist → `err:"bad_value"`.
- **Ranges:** numeric policy values outside their range are **clamped**, not rejected; the ack's `applied` shows the clamped value.
  - `0.05 ≤ *_below ≤ 0.95` (`bots_hull_below`, `batts_shield_below`, `retreat_hull_below`);
  - reserves in `[0, max stock]`;
  - `critical_hull` in `[critical_hull_floor, 0.95]`; it is a hard floor the LLM cannot lower or disable.
- **Rate limits** (guards against an LLM loop): at most **10 commands per second** and at most **2 policy changes per second** (`policy.set` + `wing.policy`), sliding 1 s windows. Excess commands are answered `err:"rate_limited"` and dropped, never queued.
- **Timing:** accepted commands apply on the next game tick, on the game's main thread.

## 10. Extension rules

1. **Unknown `t`:** the receiver ignores the message with one log line (the sidecar logs the first occurrence per connection at WARNING, later ones at DEBUG). The connection stays up. On the sidecar, a later-wave handler registered for a new type receives it even before this spec lists it.
2. **Unknown fields:** ignored by the receiver, **except** in the strict commands `policy.set` and `wing.policy`, where they fail the command with `unknown_field`.
3. **New fields are optional.** A required field is never added to an existing type without bumping `v`.
4. **New types** for later waves (carrier, wingmen, hiring, escalation) use a dotted namespace: game events `ev.<area>[.<what>]`, commands `<area>.<verb>` (for example `carrier.order`, `hire.offer`). Add them to this file and to `protocol.py` in the same change.
5. **New enum values** for an existing field need care: an older peer rejects them (`bad_value`) or ignores the message. Add them only together with a `features` entry in `hello` or `welcome` that announces support.
6. **Version bump:** an incompatible change sets `v` to 2. A v1 sidecar answers a v2 `hello` with `bye{reason:"version", supported:[1]}`.

## 11. Notes for the DLL implementation (W2-REFLEX)

From R6 §2.3; these are requirements on the DLL side.

- **Never touch a socket on the game thread.** Every Winsock `recv`/`send` under Wine is a wineserver round trip (`dlls/ntdll/unix/socket.c`: `sock_recv` issues `SERVER_START_REQ(recv_socket)` before reading; `sock_send` likewise; VERIFIED from source, R6 §2.1). Run a dedicated IPC worker thread that `select()`s with a ≈ 50 ms timeout; never spin on `recv`.
- **Game thread ↔ worker:** the game thread only locks a mutex and pushes to or swaps a deque. No Winsock calls, no waits, no condition-variable blocking on the game thread. Commands are parsed and validated into POD structs on the worker and applied by the game thread on its next tick.
- **Outbox:** bounded (for example 256 lines). When full, drop the oldest state snapshot first and never drop an ack. Snapshots are coalesced (`PostLatest`: only the newest unsent one is kept). While disconnected, posting is a no-op (keep at most the last snapshot), so nothing piles up while the sidecar is absent.
- **Startup:** call `WSAStartup` and start the worker from the module init hook, **not from `DllMain`** (loader lock). On shutdown set the stop flag and `closesocket` to break `select`; do not `join` inside `DLL_PROCESS_DETACH`.
- **Partial I/O:** handle partial sends; split received bytes on `\n`; enforce the 64 KiB line cap and skip an oversize line up to its newline (§2).
- **Absence:** with the sidecar absent there is at most one "copilot link offline" log line, quiet retries with the §4 backoff, and no frame-time impact.
- **Port:** env `FLCOPILOT_PORT` (Wine passes the Unix environment through; UNVERIFIED until S-UI), else the INI next to the DLL, else 29170.
- **UNVERIFIED until S-UI:** loopback TCP from inside the running Freelancer process (E9), and `GetAsyncKeyState` delivery of VK 110 and the X mouse buttons under Wine (E10).

## 12. Notes for the sidecar implementation

- `asyncio.start_server(host="127.0.0.1", family=AF_INET, limit=65535)`; lines are read with `StreamReader.readuntil(b"\n")`. `readline()` is not used because on overrun it silently clears its buffer, so the rest of an oversize line would then be parsed as a new message; `readuntil` leaves the data in place and the server discards the whole line explicitly.
- Handlers are registered with `HandlerRegistry.register_handler(t, fn)` (exact type, `prefix.*`, or `*`) and `on_session_start` / `on_session_end`. Later waves add features this way without editing the server.
- Profiles (CONVENTIONS §13): `--profile live` for play; `--profile test` for every harness, lane, soak and CI use (null audio sink, fake transcriber/TTS/brain, `--mic-file`).

## 13. Example session

```
DLL → {"v":1,"t":"hello","seq":1,"gt":0,"dll":"0.1.0","game":"FLHD","char":"Test Pilot","save":"slot1","policy":{"player":{"auto_bots":true,"bots_hull_below":0.5,"bots_reserve":0,"critical_hull":0.25,"release_reserve_when":"never","auto_batts":true,"batts_shield_below":0.25,"batts_reserve":0}},"features":["reflex"],"ptt_vk":110}
SC  → {"v":1,"t":"welcome","seq":1,"sidecar":"0.1.0","features":["stt","tts"],"heartbeat_ms":2000,"profile":"live"}
DLL → {"v":1,"t":"state","seq":2,"gt":81234,"rate":"combat","ship":{"hull":0.82,"shield":0.1,"shield_up":true,"bots":7,"batts":4,"mode":"free","system":"test_system"},"target":{"id":40213,"name":"Bandit","faction":"test_faction","cls":"fighter","hull":0.6,"shield":0.0,"dist":850,"hostile":true},"threat":{"hostiles":3,"capital_hostile":false},"ui":{"paused":false,"menu_open":false,"focused":true,"chat_typing":false}}
DLL → {"v":1,"t":"ptt","seq":3,"gt":82000,"down":true}
DLL → {"v":1,"t":"ptt","seq":4,"gt":83400,"down":false}
SC  → {"v":1,"t":"policy.set","seq":2,"id":"c-1","scope":"player","bots_reserve":7,"release_reserve_when":"capital_hostile_present"}
DLL → {"v":1,"t":"ack","seq":5,"gt":83950,"id":"c-1","ok":true,"applied":{"auto_bots":true,"bots_hull_below":0.5,"bots_reserve":7,"critical_hull":0.25,"release_reserve_when":"capital_hostile_present","auto_batts":true,"batts_shield_below":0.25,"batts_reserve":0}}
SC  → {"v":1,"t":"say","seq":3,"id":"c-2","speaker":"copilot","text":"Copy. Holding 7 nanobots for the capital ship.","prio":2,"subtitle":true}
DLL → {"v":1,"t":"ack","seq":6,"gt":84000,"id":"c-2","ok":true,"applied":{"shown":true}}
SC  → {"v":1,"t":"ping","seq":4,"n":1}
DLL → {"v":1,"t":"pong","seq":7,"gt":84100,"n":1}
```

## 14. Change log

- **v1 (P0-SIDECAR, 2026-10-17).** First version, adapted from R6 §3, with these deliberate changes:
  - `ev.hit.dmg_pct` became `dmg` as a fraction, like every other ratio;
  - the `release_reserve_when` value `hull_critical` was dropped, because the hard floor already spends the reserve below `critical_hull`;
  - `state.carrier` became the list `state.carriers` (several carriers can be owned);
  - top-level `id` is reserved for command ids, so `ev.target.id` became `obj`, `ev.wing.id` became `wing` and `ev.carrier.id` became `carrier`;
  - added: `bye.supported`, `hello.features`, `hello.ptt_vk`, `ev.load.char`, `ev.system.from`, `welcome.profile`, `welcome.heartbeat_ms`, and the optional `scope`/`carrier` on `act`;
  - `say` is a command with an `id` and an ack, like every other sidecar → game message.
