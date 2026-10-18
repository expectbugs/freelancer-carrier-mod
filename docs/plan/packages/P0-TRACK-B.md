# P0-TRACK-B: Platform bake-off, Track B (own hook DLL, HDE fully intact)

- **Type:** spike
- **Wave:** Phase 0 bake-off
- **Depends on:** P0-TOOLCHAIN, P0-HARNESS → **Unblocks:** G0a. If B is chosen: S-* spikes, W1-PLATFORM.

## Goal

Prove or disprove, with automated in-game evidence, that our own plain dacom DLL can deliver every platform capability the mod needs while leaving HD Edition completely intact: JFLP, FLSharp, Console, flplusplus, DelayDisplay, MP3codec, storyfactions, callsign and the Hud* plugins all stay loaded. Run the same 13-item checklist as Track A (BUILD_PLAN §4). Leave behind `spike_platform_b`, which implements the common spike API. G0a prefers B if both pass (BUILD_PLAN §4 decision rule).

## Requirements

- **REQ-P0-TRACK-B-1: the DLL.** Build `spike_b.dll` with P0-TOOLCHAIN's `win32-trackB` preset (`/MD`, FLSDK import libs, static MinHook, static Dear ImGui with the dx9 and win32 backends). Deploy it with `harness/deploy.sh --dacom-lib spike_b.dll`, which appends it to `dacom.ini [Libraries]` inside a marker block **after all HDE entries**.
  - Link `FLCoreServer.lib` so `server.dll` is a static import, mapped before our `DllMain`. HDE's `console.dll` also imports server.dll statically (VERIFIED, R5 §1.1).
- **REQ-P0-TRACK-B-2: common spike API.** Same as Track A. `spikes/track_b/include/spike_platform.hpp` must be byte-identical to this:

```cpp
#pragma once
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>
namespace sp {
struct Vec3 { float x, y, z; };
struct Mat3 { float m[3][3]; };                 // same layout as FL Matrix
struct Transform { Vec3 pos; Mat3 rot; };
struct Cmd { std::string id, verb; std::vector<std::string> args; };
struct CmdResult { bool ok = true; std::string kv; std::string err; };

// devbridge / logging (main thread)
void Harness(const std::string& kv);                                   // emits "HARNESS t=.. wall=.. <kv>"
void RegisterCommand(const std::string& verb, std::function<CmdResult(const Cmd&)> fn);
double GameSeconds();                                                  // server game time (pub::GetRwTime)
bool Paused();                                                         // F1/Esc pause (Freelancer.exe IsPaused 0x42D740)
void Defer(std::function<void()> fn);                                  // run on next tick, main thread

// per-frame tick, main thread; dtGame = delta of GameSeconds (0 while paused)
void OnTick(std::function<void(double dtGame, bool paused)> fn);

// server events (single player: client id is always 1)
void OnBaseEnter(std::function<void(uint32_t baseId)> fn);
void OnBaseExit(std::function<void(uint32_t baseId)> fn);
void OnLaunchComplete(std::function<void(uint32_t baseId, uint32_t shipId)> fn);
void OnJumpInComplete(std::function<void(uint32_t systemId, uint32_t shipId)> fn);
void OnSystemSwitchOut(std::function<void(uint32_t shipId)> fn);
void OnDockRequest(std::function<bool(uint32_t requesterShip, uint32_t targetObj)> fn); // return false = deny
void OnObjectDestroyed(std::function<void(uint32_t objId, uint32_t killerId)> fn);      // ships and solars
void OnSaveWritten(std::function<void(const std::string& saveFileAbsPath)> fn);         // after FL wrote the .fl
void OnSaveLoaded(std::function<void(const std::string& saveFileAbsPath)> fn);          // after a save was loaded

// control
void SetLaunchBlocked(bool blocked);                                   // client refusal + server backstop
void SetUndockOverride(std::function<std::optional<Transform>(uint32_t shipId, uint32_t baseId)> fn);

// UI
void OnOverlay(std::function<void()> fn);                              // Dear ImGui calls valid only inside
bool AddBaseNavButton(const std::string& nick, const std::string& iconMesh,
                      const std::string& tooltip, std::function<void()> onClick);

// queries
uint32_t PlayerShip();   // 0 if docked/none
uint32_t PlayerSystem();
uint32_t PlayerBase();   // 0 if in space
}
```

- **REQ-P0-TRACK-B-3: hook implementation.** This is the first time these hooks are built without FLUF. **Study FLUF, FLHook, Discovery and adoxa code, but do not copy AGPL/GPL code verbatim.** Write our own implementation from the documented addresses and signatures. Addresses are facts; R1, R2 and R5 cite their sources. Absolute VAs assume Freelancer.exe's base 0x400000. Server.dll addresses are **RVAs**, applied to the runtime `GetModuleHandleA("server.dll")` base (preferred base 0x6CE0000, R5 header).
  - **Detours:** MinHook. Create hooks from `DllMain(DLL_PROCESS_ATTACH)` only for the frame function; do everything else on the first tick, outside the loader lock (R6 §2.3 rationale).
  - **Frame tick:** detour `Freelancer.exe` **0x5B2890**, `void __cdecl Frame(double dt)`. Same function FLUF detours as `fl+0x1B2890`. Main thread, once per rendered frame, runs while paused (R5 §1.3, VERIFIED disassembly).
    - `Paused()`: read the pause counter at **0x667D54** (> 0 in SP), or call `IsPaused` 0x42D740.
    - `GameSeconds()`: `pub::GetRwTime(double&)` from Server.dll.
  - **Server vtable hooks.** `GetProcAddress(GetModuleHandleA("server.dll"), "Server")` returns the exported `IServerImpl` object. Read its vtable pointer, `VirtualProtect` the slot, and swap the function pointers, keeping the originals. Patch only these slots (byte offsets into the vtable; R1 §2.2, R5 §1.2/§3.4, VERIFIED):

    | Offset | Slot |
    |---|---|
    | 0x050 | CharacterSelect (load game in SP) |
    | 0x08C | BaseEnter |
    | 0x090 | BaseExit |
    | 0x0BC | SystemSwitchOutComplete |
    | 0x0C0 | PlayerLaunch |
    | 0x0C4 | LaunchComplete |
    | 0x0C8 | JumpInComplete |
    | 0x0F0 | RequestEvent (eventType 0 = dock) |

    - Signatures are in `refs/FLHookSDK-v4/include/FLCore/FLCoreServer.h:355-455` (VERIFIED; `__thiscall` on the object), cross-checked with `refs/FLUF/FLUF/Include/Server/Internal/IServerHook.hpp:205-288`.
    - **Before patching, check that each slot's current pointer lies inside server.dll's image range.** If another plugin already hooked it, chain to it and log `HARNESS warn=slot_prehooked off=0x..`.
    - SP routing: the exe calls rpclocal's `IServerImpl`, which forwards to server.dll's `Server` virtuals. That is why FLUF's identical patching works in SP (R5 §1.2, R1 §2.1).
    - Intro bases (`Intro1_Base`…`Intro99_Base`) fire BaseEnter at the main menu: filter them (R1 §2.3).
  - **Dock requests:** `RequestEvent(int eventType, uint shipId, uint dockTarget, uint, ulong, uint client)` with eventType 0 = dock. To deny, don't call the original, and tell the client: `pub::Player::SendNNMessage(1, CreateID("info_access_denied"))` or equivalent. Discovery denies with `ACCESS_DENIED` via its Dock_Call hook (R2 §2.1/§13); study the cancel flow. Verify the player isn't left stuck in "docking" state.
  - **Destroy detection (spike-level):** poll `pub::SpaceObj::ExistsAndAlive(id)` (0 = alive) for watched objects every tick. Real engine hooks are W1-PLATFORM's job: FLHook 4.0's `ShipDestroyed`/`AddDamageEntry` sites, R2 §6, §9 list.
  - **Launch block:**
    - Client: detour the launch-permission check **0x4422B0**, FLUF's `ClientExeLaunchMountedEquipmentCheckFunc` (R5 §4.3, VERIFIED). When blocked, return "cannot launch" and show a message (e.g. `pub::Player::SendNNMessage`, or adoxa TractorRequired's `0x489E80(nnv_id, 0)` + resource string; see `refs/adoxa-plugins/tractorrequired/`).
    - Server backstop: in the `PlayerLaunch` slot, if blocked, don't call the original. Observe what happens and pick the cleanest re-dock. R5 §4.3 notes FLUF's suppression force-redocks; Discovery re-docks via `ForceLand`/beam.
  - **Undock position:** patch the call at **server.dll RVA 0x8420C**, the call to `CEqObj::launch_pos(pos, rot, dock)` on the docking solar. Route it to our function: call the original, then apply the override. References: FLUF `FlufServer.cpp` DynPatch +0x8420C, Discovery `base_plugin/Main.cpp` `LaunchPosHook`, '88 Flak `HkCbOther.cpp:6-20` (R2 §2.1/§2.3, R5 §4.2).
  - **Save hook:** detour the **entry** of `PlayerData::save` at **server.dll RVA 0x6C800** (thiscall `(const CHARACTER_ID&, const wchar_t* desc, uint ids)`). Call the original, then emit `OnSaveWritten(<GetUserDataPath>\Accts\SinglePlayer\<CHARACTER_ID.charFilename>)`.
    - Console (loaded in HDE) patches +0xA75 inside it (0x6D275), the delete at 0x6A177, and exe 0x5AB231. Don't touch those (R5 §3.4, §8.2).
    - `GetUserDataPath` is the common.dll export `?GetUserDataPath@@YA_NQAD@Z`; flplusplus detours it, so call it and use its answer.
  - **Load hook:** `CharacterSelect` slot (0x050). After the original returns, emit `OnSaveLoaded(path)`, built from `CHARACTER_ID` the same way.
  - **Overlay (D3D9 route preferred):** HDE's chain is `EXE/d3d8.dll` (dxwrapper stub) → `dxwrapper.dll` d3d8to9 → `EXE/d3d9.dll` (**ReShade**) → DXVK `syswow64/d3d9.dll` (R1 §3.4, R4 §B6, VERIFIED).
    1. On the first tick, create a hidden dummy window and dummy `IDirect3DDevice9` via `Direct3DCreate9` from the **already loaded** `d3d9.dll` module (`GetModuleHandleA("d3d9.dll")`, i.e. ReShade's).
    2. Read `EndScene` (vtable index 42), `Reset` (index 16) and `Present` (index 17) from the dummy's vtable, release the dummy, and MinHook those functions.
    3. In `EndScene`, on the device whose `GetCreationParameters().hFocusWindow` is FL's window, initialize Dear ImGui (`imgui_impl_dx9` + `imgui_impl_win32`, MIT) once and draw `OnOverlay` callbacks.
    4. Handle `Reset`: `ImGui_ImplDX9_InvalidateDeviceObjects` / `CreateDeviceObjects`.
    5. Subclass FL's WndProc for ImGui input. Swallow input only when `ImGui::GetIO().WantCaptureMouse/Keyboard`.
    - UNVERIFIED that the dummy-device vtable equals the device dxwrapper creates through ReShade. Verify by logging the device pointer seen in the hooks against the one `GetCreationParameters` reports.
    - **Fallback:** hook D3D8 like FLUF (detour `Direct3DCreate8` of `EXE/d3d8.dll` → `IDirect3D8::CreateDevice` vtable[15] → device `EndScene`) with a small custom D3D8 ImGui renderer. That needs DX8 headers, which are not in the Windows SDK; FLUF downloads the DX8 SDK. Only go here if D3D9 fails, and record it.
  - **Native NavBar button.** Reimplement FL control creation using the documented addresses (R1 §3.1–3.2, VERIFIED in FLUF source):

    | Address | Purpose |
    |---|---|
    | 0x59DB20 | control factory |
    | 0x5A0C90 | `CreateButtonControl(parent, nickname, mesh, mesh2, clickSound, event, pos, hardpoint, mouseSize, noMeshRender, actionButton, noColourChange, noZEnable, tip, tip2, keyId)` |
    | 0x5A0DB0 | `CreateStaticControl` |
    | 0x5664A0 | button click / Perform dispatch |
    | 0x59DA10 | `FindUiControl(name)` (R5 §1.2) |
    | 0x5e15f4 | button vtable |

    - The navbar control is named `"NavBar"`; icons are `interface\baseside\*.3db`. `navbar.ini` is hard-coded in the exe (R1 §3.2, R5 §4.1).
    - Study `refs/FLUF/FLUF/Include/Client/UI/Vanilla/*`, `refs/FLUF/FLUF/Source/Client/Ui/*` and `refs/FLUF/modules/ship_dealer_enhancements/Source/ShipDealerInterface.cpp`, then reimplement.
    - Note: FLSharp patches base-menu hotspot code (0x43FFB6, 0x43E9CA; R5 §8.2). Make sure our button survives alongside it.
    - **Fallback:** an ImGui button anchored to the base screen while docked.
  - **Queries:** client mirrors (R5 §1.2, VERIFIED): base id `[0x673358]`, system `[0x673354]`, ship id `[0x673378]`, client id `[0x673344]`. Or use `pub::Player::GetBase/GetSystem/GetShip(1, …)` on the main thread.
- **REQ-P0-TRACK-B-4: devbridge verbs.** Same names and semantics as Track A REQ-4:
  - `state`, `load`, `save`, `quit`, `shot`, `vmstat`, `perf`;
  - helpers: `forceland`, `launch`, `instantdock`, `block_launch`, `undock_offset`, `deny_dock`, `nav_button`, `overlay`.
  - **`load` is critical for B.** No FLUF debugger exists here, so P0-HARNESS's `run.sh` sends `load <file>` once `state=menu`. Implement it by calling **Freelancer.exe `LoadGame` 0x5b2c70** with a `CHARACTER_ID` filled with the save filename (adoxa console `cmdLoad`, VERIFIED source `refs/adoxa-plugins/console/console.cpp:465-480`; `fl_name` builds `"%x.fl"` from CreateID(description)). Whether this works from the main menu is UNVERIFIED.
    - **Fallback:** reimplement FLUF debugger's menu-button presses. Main menu: `PressMenuButton2` 0x5743A0 with presser 0x67A598 and codes 0x3, 0x2, 0x12. Then wait about 55 frames; then select the save (0xF001, index) and load (0x3004/0x3003) via `PressMenuButton` 0x56C360 with presser 0x67AE10 (`refs/FLUF/modules/debugger/Source/Debugger.cpp:94-240`, VERIFIED source).
  - `save <desc>`: `Players.playerdata->save(cid, desc, 0)`, as adoxa `cmdSave`. `PlayerData::save` is the function we hook, so item 9 also exercises it.
  - `launch`: adoxa `cmdLaunch` jumps into exe 0x440f94 (`console.cpp:1633`, VERIFIED source). Reimplement the equivalent, or invoke the NavBar Launch control.
- **REQ-P0-TRACK-B-5: the checklist** (BUILD_PLAN §4). Identical items, scenarios and evidence to P0-TRACK-A REQ-5, except:
  - Item 1 also verifies that **all HDE plugins still load**: `+loaddll` in `wine.log` shows `jflp`, `FLSharp`, `console`, `flplusplus`, `DelayDisplay`, `MP3codec`, `storyfactions`, `HudShift` and the other Hud* DLLs, plus `spike_b`.
  - Item 13 becomes "no HDE feature lost". Confirm the `dacom.ini` diff is only our marker block and that `freelancer.ini` is unchanged, and write that diff into `spikes/track_b/LOST_FEATURES.md` ("none"). It's scored like A's: PASS when complete.
  - Item 12 uses the **same shared scenario** `harness/scenarios/bakeoff_vmstat.yaml` as Track A: same route, same PASS threshold `va_largest_free_mb ≥ 300`, numbers in `verdict.json`. Expect far more headroom, since FLUF's 404 MiB image is absent.
  - Item 4's F1 press uses real XTEST input under the input lock: `xdotool windowactivate --sync`, then `xdotool key F1`, never `--window` (CONVENTIONS §7).
- **REQ-P0-TRACK-B-6: results file.** `spikes/track_b/RESULTS.md`, with the same table format as A: evidence paths are absolute run dirs under `$FLMOD_TESTRUNS`. G0a reads it together with your saved report (`state/reports/P0-TRACK-B-a<n>.md`).

## Context pack

- `docs/plan/CONVENTIONS.md` (authoritative: §1 paths, §4 devbridge names, §5 run output, §6 fixtures, §7 locks/input, §15 wine)
- `docs/plan/BUILD_PLAN.md` §4; `docs/plan/TESTING.md` §Lanes, §Devbridge, §Scenarios, §Vision, §Soak, §CrashTriage
- `$FLMOD_RESEARCH/R5-sp-architecture.md`: **all** (the core reference for Track B: frame function, pause, server vtable, save and load chokepoints, launch block, launch position, HDE hook map §8.2)
- `$FLMOD_RESEARCH/R1-fluf.md` §2.1–2.2 (how FLUF hooks the vtable in SP), §3.1–3.4 (UI internals and the HDE graphics chain)
- `$FLMOD_RESEARCH/R2-engine-api.md` §2 (dock denial, launch-position precedents), §9 (hook catalogue)
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md` §B6–B10
- Reference source to **study** (licenses: FLUF AGPL, FLHook GPL-3, Discovery DBAD; reimplement, don't paste):
  - `refs/FLUF/FLUF/Source/Server/FlufServer.cpp`
  - `refs/FLUF/FLUF/Include/Server/Internal/IServerHook.hpp`
  - `refs/FLUF/FLUF/Source/Client/Ui/UiManager.cpp`
  - `refs/FLUF/FLUF/Source/Client/Hooks/BaseHooks.cpp`
  - `refs/FLUF/modules/debugger/Source/Debugger.cpp`
  - `refs/FLHook-4.0-locked/source/HkInit.cpp`
  - `refs/DiscoveryFLHook/Plugins/Public/base_plugin/Main.cpp`
  - `refs/adoxa-plugins/{console,tractorrequired,externalmsg}/` (adoxa: check the readme's terms; reimplement)
  - `refs/FLSharp/src/*` (MIT, so reuse is allowed with attribution; it shows the HDE-compatible patching style)
- Dear ImGui `backends/imgui_impl_dx9.cpp`, `imgui_impl_win32.cpp` (vendored by P0-TOOLCHAIN); MinHook docs

## Ownership

- **Owns:** `spikes/track_b/`, plus `harness/scenarios/bakeoff_vmstat.yaml`, which is shared with P0-TRACK-A (whoever commits first; the content must be identical).
- **Reads:** everything.
- **Must not touch:** `harness/` (propose fixes), `toolchain/`, baselines, `docs/plan/`, `state/`.

## Contract

- **Provides:** `spike_platform_b` (static lib + the header); `RESULTS.md`; a list of every address patched, with original bytes, in `spikes/track_b/PATCHES.md`.
- **Consumes:** P0-HARNESS, P0-TOOLCHAIN.

## Tasks

1. Frame tick, devbridge, `state`, `quit` → item 1.
2. `load`/`save` verbs → item 2. This unblocks automated runs on B.
3. Vtable hooks plus the helpers → item 3. Then items 4, 7, 8, 9.
4. Overlay (item 5), then the native button (item 6).
5. `vmstat` (item 12) and the spew diff (item 11).
6. The 60-minute soak (item 10). Write `RESULTS.md` and `PATCHES.md`.

## Acceptance

`RESULTS.md` is complete with evidence per item. Reviewers re-run items 2, 3, 7, 8 and 9. `PATCHES.md` lists every patched address with the original bytes verified before writing.

## Engine facts to rely on / verify

- **VERIFIED:**
  - frame 0x5B2890 and pause 0x667D54;
  - `Server` export and vtable layout;
  - save entry 0x6C800 and Console's patch sites;
  - launch check 0x4422B0;
  - launch-pos call site server+0x8420C;
  - `LoadGame` 0x5b2c70;
  - client mirrors;
  - the HDE D3D chain.
- **UNVERIFIED, settled here:**
  - D3D9 dummy-device vtable hooking through ReShade;
  - `LoadGame` from the main menu;
  - the native button with FLSharp present;
  - the server-side launch-suppression behaviour;
  - the dock-deny client state.

## Pitfalls

- Never patch the same slot or bytes as an HDE plugin without chaining. HDE patch sites are listed in R5 §8.2: Console, flplusplus, FLSharp.
- Any wrong thiscall/stdcall signature corrupts the stack silently. Copy signatures from the FLHookSDK-v4 header, and test each hook with a pass-through first.
- `DllMain` runs under the loader lock: no `LoadLibrary`, no D3D, no threads.
- With ReShade present, two overlays exist. Make sure ours draws after ReShade's or doesn't conflict, and note it.
- FL's own cursor vs the ImGui cursor: verify clicks land where the screenshot shows.

## Fallbacks and degrade path

| Item fails | Fallback |
|---|---|
| Overlay | D3D8 route; else native-controls-only UI |
| Native button | ImGui anchored button |
| `load` via LoadGame | Menu-press route |
| Server launch suppression is messy | Rely on client-side blocking plus re-dock via ForceLand |

Report PARTIAL items honestly.

## Report

AGENT_BRIEF_TEMPLATE format. Include the `RESULTS.md` table inline and the `PATCHES.md` summary.

## Gate-time addendum

(Orchestrator: lane assignment, attempt number, commit trailer.)
