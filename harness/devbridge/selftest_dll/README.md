# devbridge selftest DLL (throwaway)

A Track-B-style dacom library that proves the devbridge core works inside Freelancer **before** the track spikes exist. It is test-only and throwaway: the P0-TRACK-A/B spike DLLs, and later W1-CORE, replace it. Never deploy it to `prefix-carrier`.

## What it does

- Dacom loads it from `EXE/dacom.ini` `[Libraries]`, and all of its work happens in `DllMain(DLL_PROCESS_ATTACH)`. If `EXE/devbridge.enabled` is absent it does nothing.
- It detours Freelancer.exe's per-frame function at `0x5B2890`, `void __cdecl (double dt)`. That function runs on the main thread every frame (menus, docked, space, F1 pause; R5 §1.3).
  - The first 5 bytes are `51 55 56 33 ED` (`push ecx; push ebp; push esi; xor ebp,ebp`): whole instructions with no relative operands. The trampoline copies them and jumps back to `0x5B2895`.
  - The DLL checks that the image base is `0x400000` and that those bytes match before patching. Otherwise it logs `ev=selftest_hook_failed bytes=<first 8 bytes hex>` (or `reason=...`), shuts the bridge down and stays inert.
- The detour calls the original first, then `DevbridgeTick(t)`, where `t` is the sum of `dt` since load.
- Successful hook: `ev=selftest_hooked fn=0x5B2890 stolen=5 trampoline=0x...` after `ev=devbridge_ready`.

## Verbs (in addition to the core `ping`, `echo`, `sleep_frames`, `seq`)

| Verb | Output |
|---|---|
| `state` | `state=menu\|space\|docked base=- system=- ship=- hull=-1 cash=<[0x673364]> paused=<IsPaused 0x42D740> base_id= system_id= ship_id= rank=<n> rank_rc=<rc>` (rank from Server.dll `pub::Player::GetRank(1, rank)` when in game, else -1) (from the client mirrors base `[0x673358]`, system `[0x673354]` and ship `[0x673378]`: base≠0 → docked; system≠0 → space; else menu). No nicknames, hull or dead/loading states: tracks add those. |
| *(event)* | `ev=hb` every 10 s of wall time from the frame detour (the harness uses it to tell a frozen game from an idle one) |
| `quit` | `exit_next_tick=1`. At the start of the next frame: `DevbridgeShutdown()` then `ExitProcess(0)`. Whether DLL detach can hang there is UNVERIFIED, so the harness should still `wineserver -k` the lane after a grace period. |
| `vmstat` | `va_free_mb va_largest_free_mb va_committed_mb va_reserved_mb va_max=0x...`. The `VirtualQuery` walk runs from 0x10000 to `GetSystemInfo().lpMaximumApplicationAddress`, not a hard-coded 0x7FFF0000. |
| `perf <seconds>` | async (0.1–600 s; budget = seconds + 30): `fps_avg fps_p1 frame_ms_max frames window_s`. Frame times come from QPC deltas between detour calls. `fps_p1` = 1000 / (99th-percentile frame ms). |
| `shot <name>` | `ok=0 err="unsupported"` (screenshots come from `harness/shot.sh`) |
| `load <save.fl>` | **EXPERIMENTAL.** Bare file name, `.fl` appended if missing. It checks that `GetUserDataPath()\Accts\SinglePlayer\<file>` exists, then on the next tick calls `LoadGame` at `0x5B2C70` (`void __cdecl(const CHARACTER_ID&, bool)`, `CHARACTER_ID = char[512]`), as adoxa's console `load` does. The flag (`CharacterSkipAutosave` via the `IServer` vtable +0x60) is passed only when `[0x67ECD0]` is non-null. Ack: `file= skip_autosave=0\|1 experimental=1`. Poll `state` afterwards. Whether it works from the main menu is UNVERIFIED. |

## Build

```bash
bash harness/devbridge/selftest_dll/build.sh   # -> build/selftest_dll/devbridge_selftest.dll (+ .pdb)
```

- Needs P0-TOOLCHAIN's xwin splat in `$XWIN_ROOT` (default `/home/user/opt/xwin`, `/winsysroot` layout). Without it the script prints `SKIP: xwin splat missing` and exits 3.
- Flags: `clang-cl --target=i686-pc-windows-msvc /MD /O2 /EHsc /std:c++20 /Zi /utf-8 /permissive- -D_ITERATOR_DEBUG_LEVEL=0`, then `lld-link /DLL /machine:x86 /SAFESEH:NO /DEBUG`. MSVC ABI only, never mingw.
- Imports: `KERNEL32`, `MSVCP140`, `VCRUNTIME140` and `api-ms-win-crt-*`. Under Wine these resolve to Proton's builtin runtime DLLs.

## Deploy and run (lane only)

```bash
harness/deploy.sh --lane N --artifacts build/selftest_dll --dacom-lib devbridge_selftest.dll
touch "$HDE/EXE/devbridge.enabled"     # if the lane does not already have it
# launch through harness/run.sh, then:
harness/devbridge.py --lane N wait-ready --timeout 120
harness/devbridge.py --lane N send ping
harness/devbridge.py --lane N send state
harness/devbridge.py --lane N send perf 5 --timeout 60
harness/devbridge.py --lane N send vmstat
harness/devbridge.py --lane N send quit
```

Expected log: `ev=devbridge_ready`, `ev=selftest_hooked`, then one `ack` per command. If `ev=selftest_hooked` is missing but `ev=selftest_hook_failed` is present, the exe differs from the HDE build these addresses come from.
