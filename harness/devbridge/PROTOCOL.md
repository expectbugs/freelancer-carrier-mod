# Devbridge wire protocol, version 1

Canonical spec for the file-based test channel between the harness and the game module (P0-HARNESS REQ-12). ARCH-0 copies this file verbatim to `docs/spec/devbridge.md`. W1-CORE may replace the implementation, but **not the wire format**. Reference implementation: `devbridge_core.{hpp,cpp}` (game side) and `harness/devbridge.py` (client).

## 1. Enable and directory

- **Directory:** `<exe dir>\..\SAVE\devbridge\` (for HDE: `<HDE>/SAVE/devbridge/`). It is fixed and independent of `GetUserDataPath`. The game creates it if it is missing.
- **Enable:** the bridge is active only if `<exe dir>\devbridge.enabled` exists when `DevbridgeInit` runs. Without the marker, nothing is created, read or deleted, and every API call is a no-op.

## 2. Commands (harness → game)

- **File name:** `cmd-<seq>.txt`, where `<seq>` is a decimal integer zero-padded to 10 digits (`cmd-0000000042.txt`). The game also accepts 1–19 unpadded digits and orders by numeric value. Any other `cmd-*.txt` is reported as malformed (§4) and deleted.
- **Atomic write:** write to `.tmp-cmd-<seq>`, a name that never matches `cmd-*.txt`, then rename it to `cmd-<seq>.txt`. The game ignores every file that doesn't match `cmd-*.txt`.
- **Seq allocation (client rule):** take an exclusive `flock` on `<dir>/.seq.lock`. Set `seq = max(<dir>/.seq counter, highest seq among existing cmd-* and .tmp-cmd-* files) + 1`. Store the counter, then write and rename the file, all **under the lock**, so that files from concurrent clients appear in seq order. Never reset `.seq` while the game runs.
- **Content:** exactly one line, `<id> <verb> [args...]`, UTF-8. A trailing LF or CRLF, a UTF-8 BOM and surrounding blank lines are tolerated. The file must be at most 64 KiB.
  - `id` must match `[A-Za-z0-9_.:-]{1,64}`. The client's default id is `h<seq>`.
  - `verb` is the second whitespace-delimited token, verbatim and case-sensitive.
  - `args` are the tokens after the verb, split on whitespace. A `"..."` section may appear anywhere in a token (`tag="x y"` → `tag=x y`). Inside quotes, `\"` → `"` and `\\` → `\`; any other backslash is literal. Outside quotes, backslashes are literal (`C:\dir` works unquoted). An unterminated quote is malformed.
  - `raw` is the rest of the line after the verb: verbatim (quotes kept) and trimmed.

## 3. Processing (game side)

- **Main thread only.** `DevbridgeInit`, `DevbridgeShutdown`, `DevbridgeTick`, `Harness`, `DevbridgeData` and the `Register` calls belong on the game's main thread. `DevbridgeTick(gameSeconds)` is called every frame from the platform tick; handlers run inside it. Until the first tick the thread that called `Init` owns the core; the first tick fixes the owner (`ev=devbridge_thread_mismatch` if it differs from the `Init` thread). Calls from other threads are dropped and counted (`ev=devbridge_wrong_thread`); debug builds also assert that `Shutdown` runs on the owner.
- **Polling:** the directory is listed on frames 1, 11, 21, … (every 10 frames). Files are read in ascending seq order, at most 64 per poll. Each file is deleted right after it is read.
- **Dedupe:** the game remembers `last_seq`, the highest seq read. A file with `seq <= last_seq` is never executed: it is deleted and reported once per file name as `ev=cmd_dup`. This covers Wine delete lag, where a deleted file can be listed again.
- **Stale files:** at init, every pre-existing `cmd-*.txt` is deleted unexecuted. `last_seq` is set to the highest stale seq, and the count is reported on the ready event. A client must therefore raise its counter to the ready line's `last_seq` (`wait_ready()` does this), and `send` resubmits once if it sees `ev=cmd_dup` for its own file.
- **Unreadable file:** it is retried on the next polls without letting later files overtake it. After 5 failed polls it is dropped as `ev=bad_cmd reason=unreadable`.
- **FIFO:** commands execute strictly in seq order. A sync command completes within the tick. An **async** command is polled once when it starts and then once per frame. While it is pending, every later command waits. Commands queued behind it run in the same tick it completes.
- **Timeout:** an async command's budget is 60 s of wall clock from its start. The handler may set its own budget by returning `pending` with `timeout_s` (W1 `wait_*` verbs take it from their arguments). On expiry the game sends `ack id=<id> ok=0 err="timeout" verb=<verb> timeout_s=<s>` and the next command runs.
- **Keep-alive (D111):** while an async command has been pending for more than 5 s, the game writes `ev=pending id=<id> verb=<verb> elapsed_s=<n>` every 5 s (n = whole seconds since the command started). The harness counts log growth as liveness, so a legitimate long command (`perf 75`, a 3-minute soak sample) is never mistaken for a hang. A sync command blocks the frame, so it cannot emit keep-alives; keep sync handlers short.
- **Shutdown:** a pending command and every queued command with an id get `ok=0 err="shutdown"`, then `ev=devbridge_shutdown` is written.
- **Exceptions:** no exception escapes. A throwing handler gives `ok=0 err="exception: <what>"`.

## 4. Output (game → harness)

- **File:** `log.txt` in the same directory. It is append-only, opened once at init, and gets one line per record (LF), flushed per line. The log continues across game runs; never delete or truncate it while the game runs, because the game would keep writing to the unlinked file. To start fresh, delete it before launch, or remember its size (`devbridge.py offset`) and read from that offset.
- **Line:** `HARNESS t=<game seconds, 3 decimals> wall=<unix ms> <payload>`. `t` is formatted independently of the locale. Payload tokens are bare words or `key=value`.
- **Values:** a value that is empty or contains a space, `"` or `=` is written double-quoted, with `\"` and `\\` escapes. An empty value is written `""`. Control characters (0x00–0x1F, 0x7F) are replaced by a space, so a record is always one line. Readers split `key=value` at the first unquoted `=`.
- **Response to a command:** zero or more data lines, then exactly one ack line, which ends the response:
  ```
  HARNESS t=.. wall=.. data id=<id> k=v ...
  HARNESS t=.. wall=.. ack id=<id> ok=1|0 [err="<text>"] verb=<verb> [k=v ...]
  ```
  Key order (D111, CONVENTIONS §4): `id`, `ok`, then `err` (only when `ok=0`, immediately after `ok`), then `verb`, then the command's result `k=v`. `err` is **always** double-quoted, with `\"` and `\\` escaped (`err="timeout"`, `err="unknown verb frob"`); other values are quoted only when needed (below). `verb=` is on every ack; the ack line is the log's record of every executed command. The keys `id`, `ok`, `verb` and `err` are reserved in results. Example: `ack id=h3 ok=0 err="unknown verb launch" verb=launch`.
- **Matching:** `t=` and `wall=` come first, so matchers must not anchor `ack` directly after `HARNESS`. Use regexes like `ack id=\S+ ok=0`, `ack id=h12 ` or `ack id=\S+ ok=0 err="timeout"`. Short forms such as `HARNESS ack id=... ok=1` in other docs mean the same line.
- **Events:** `HARNESS t=.. wall=.. ev=<name> k=v ...`. The key is always `ev=`, never `evt=`.

## 5. Core verbs and events

| Verb | Kind | Ack (ok=1 unless noted) |
|---|---|---|
| `ping` | sync | `pong=1` |
| `echo <text...>` | sync | `text=<raw>` (`raw` keeps any quotes from the command line) |
| `sleep_frames <n>` | async | after n further frames: `frames=<n>`; bad n → `ok=0 err="usage: sleep_frames <n>"` (before `verb=`, §4) |
| `seq` | sync | `last_seq=<n>` |
| *(unknown)* | | `ok=0 err="unknown verb <verb>"` |

| Event | When |
|---|---|
| `ev=devbridge_ready version=1 stale_cmds=<n> last_seq=<n> poll_frames=10 dir=<dir>` | init (marker present) |
| `ev=devbridge_shutdown` | `DevbridgeShutdown()` |
| `ev=bad_cmd file=<name> reason=<r> [id=<id>]` | malformed file. Reasons: `empty`, `"bad id"`, `"missing verb"`, `"multiple lines"`, `"unterminated quote"`, `"too large"`, `unreadable`, `"bad file name"`. If an id was parsed, an `ack id=<id> ok=0 err="bad_cmd: <reason>"` follows. |
| `ev=cmd_dup file=<name> last_seq=<n>` | file with `seq <= last_seq` deleted unexecuted |
| `ev=fs_error op=remove file=<name>` | a cmd file could not be deleted (reported once per name) |
| `ev=devbridge_wrong_thread dropped=<n>` | API calls from a non-main thread were dropped |
| `ev=devbridge_thread_mismatch init_thread_differs=1` | the first `DevbridgeTick` ran on a thread other than `DevbridgeInit`'s |
| `ev=pending id=<id> verb=<verb> elapsed_s=<n>` | every 5 s while an async command has been pending > 5 s (D111) |

Track and W1+ verbs (`state`, `load`, `save`, `quit`, `shot`, `vmstat`, `perf`, …) and their outputs are frozen in CONVENTIONS §4 and TESTING §Devbridge. The vmstat keys are `va_free_mb` and `va_largest_free_mb`.

## 6. C++ API (`devbridge_core.hpp`)

```cpp
void DevbridgeInit(const char* exeDir);            // UTF-8 exe dir; real filesystem
void DevbridgeInitWithFs(const char* exeDir, std::unique_ptr<devbridge::Fs>, std::function<int64_t()> wallMs = {});
void DevbridgeShutdown();
bool DevbridgeActive();
void DevbridgeTick(double gameSeconds);            // every frame, main thread
void DevbridgeRegister(const char* verb, std::function<devbridge::CmdResult(const devbridge::Cmd&)>);
void DevbridgeRegisterAsync(const char* verb,
    std::function<std::optional<devbridge::CmdResult>(const devbridge::Cmd&, int framesWaited)>);
void Harness(std::string_view kv);                 // event/info line
void DevbridgeData(std::string_view id, std::string_view kv);  // data line for a command
void DevbridgeSetMirror(std::function<void(const std::string&)>);  // e.g. module logger
std::string DevbridgeQuote(std::string_view v);
```

- **Handler results:** `CmdResult{ok, kv, err, pending, timeout_s}`. An async poll returns `std::nullopt` while still pending, `CmdResult::Pending(s)` to set its budget, or a final result. A sync handler that returns `pending` is answered `ok=0`.
- **Registration:** re-registering a verb replaces it. Sync and async verbs share one namespace, and user verbs override the built-ins. Handlers registered before `Init` are kept; `Shutdown` clears them.
- **Threading:** all of these are main-thread only (§3). Before the first `DevbridgeTick` the `Init` thread is the owner; the first tick fixes it. Later `Tick`, `Harness`, `Data` and `Register` calls from other threads are dropped and counted; debug builds `assert()` that `Shutdown` runs on the owner.

## 7. Client (`harness/devbridge.py`)

`Devbridge(dir).send(verb, *args, timeout=30, id=None, alive=None) -> Response(ok, id, kv, err, data, line, seq, end)`. It also provides `send_line`, `submit` and `wait_ack`, as well as `wait_for(regex | predicate, timeout, since)`, `wait_ready`, `offset()` and `lines(since)`. The CLI, `devbridge.py (--dir D | --lane N) send|wait-ready|wait|run-file|tail|offset`, exits with 0 for ok, 1 for ok=0, 2 for a timeout, 3 when the game is gone and 64 for usage errors. On an ack timeout the client deletes its command file if the game never took it, so it can't run later.
