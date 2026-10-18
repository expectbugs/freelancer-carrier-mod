# S-UI: Spike: base-menu UI, text, notifications, sounds, waypoints, loopback TCP, push-to-talk, resource DLL

- **Type:** spike
- **Wave:** Phase 0 (after G0a)
- **Depends on:** G0a, P0-DATATOOLS, P0-SIDECAR → **Unblocks:** G0b, W1-UI, W1-DATA (strings), W2-CARRIER-UI, W2-YARD, W2-REFLEX (IPC + PTT), W4-HIRING.

## Goal

Prove which UI and I/O channels work in single player on the chosen track, and what they look like. That covers:

- native base-menu buttons and panels;
- dynamic base text;
- popups;
- Neural Net messages and mission text;
- comm windows;
- custom sound playback;
- waypoints;
- our own text resource DLL;
- a TCP connection from inside the game to the Linux sidecar;
- reliable push-to-talk key detection under Wine.

Later UI packages build only on what this spike proves.

## Requirements

- **REQ-S-UI-1:** Build `s_ui.dll` on `spike_platform_<track>`. Test strings come from a spike resource DLL built with `fltools.resdll` and appended to `freelancer.ini [Resources]` in the lane. Detect its index; it is 8 on HDE, giving IDS 524288+ (R3 §1.2).
- **REQ-S-UI-2:** For each experiment, write a `FINDINGS.md` entry: hypothesis, method, observation, verdict, evidence (screenshots with vision-check verdicts), proposed `EF-UI-<n>` facts. Add a "UI capability matrix" table: channel × works? × looks right? × limitations.

## Experiments

### E1: Native NavBar button

- Using the track's `AddBaseNavButton`, add "Carrier" with a vanilla icon mesh from `DATA/INTERFACE/BASESIDE/` (listed via `navbar.ini`; `RoomControl1` = Launch = `take_off.3db`, R5 §4.1).
- Test at 4 base types: a planet (Manhattan `Li01_01_Base`), a station, a house battleship base (`Li01_03_Base` Missouri) and a liner base (`Br06_01_Base` Shetland).
- **Pass:**
  - the button is visible, aligned with the vanilla buttons, and has a tooltip (screenshots plus vision rubric: "an extra round navigation button sits in line with the base's room buttons and does not overlap them");
  - the click is received;
  - it survives room switches, dealer screens and re-docks;
  - no crash on undock.

### E2: Panel while docked

- An overlay panel ("Carrier") with:
  - a list of 10 destinations;
  - selection;
  - a progress bar with text ("two systems out, arriving in 4 minutes");
  - Stop and Travel buttons;
  - a text input (carrier rename);
  - a scrollable list of 50 items (the Yard catalog).
- Style it to resemble FL: dark panel, FL font if loadable, FL colours.
- Test at 1280×720 and 1920×1080 (lane `PerfOptions` size change). Screenshot at each.
- Vision rubric: "panel legible, no clipped text, looks consistent with the game's UI".
- Input: keyboard focus must not leak into flight controls, and Esc closes the panel.
- On Track A, compare the FLUF ImGui panel with a FLUF vanilla-controls panel (`FlTextControl` + buttons); record which looks closer to FL.

### E3: Dynamic base info text

- Override the base's information or infocard text at runtime.
  - Track A: `InfocardManager::OverrideInfocard(ids, wstring, isName)`.
  - Track B: hook `GetIdsName` 0x4347E0 / the infocard getter 0x57DA40 (R5 §1.2, VERIFIED addresses), or use FLSharp's `dynamic_solar_infocards` + `missioncreatedsolars.ini` (R3 §1.3).
- Update it every 5 s with a countdown.
- **Pass:** the text shown in the base screen changes live (two screenshots).

### E4: Popups

- `pub::Player::PopUpDialog(1, FmtStr title, FmtStr body, buttons)` with our resource-DLL IDS. Buttons: `LeftYes=1`, `CenterNo=2`, `RightLater=4`, `CenterOk=8`.
- The reply arrives at `IServerImpl::PopUpDialog(client, button)`, vtable +0x128 (R5 §5, VERIFIED signature).
- Hook or observe that reply. Popups don't pause SP (R5 §1.3).
- **Pass:** the dialog shows our text; each button's reply is received.

### E5: NN messages, mission text, NN log

- `pub::Player::SendNNMessage(1, CreateID("look_at_news"))` plays a Neural Net voice. Find 2–3 suitable stock IDs for "alert" and "distress" via `DATA/AUDIO` voice entries.
- `pub::Player::DisplayMissionMessage(1, FmtStr, MissionMessageType, bool)`.
- Mission objective text: `SetMissionObjectives` / `ReplaceMissionObjective` (R5 §5).
- Neural Net log entry: `PlayerData.neuralNetLog` st6::list of IDS (R5 §5; adding entries is UNVERIFIED).
- **Pass:** each shows on screen (screenshot) and doesn't break the save (`save`/`load` round trip).

### E6: Comms with portrait

`pub::SpaceObj::SendComm(sender, receiver, voiceId, const Costume*, infocardId, lines*, lineCount, infocardId2, radioSilenceAfter, global)`. Parameter names come from FLHook's `IEngineHook.cpp` (R5 §5). Send it from our carrier solar or ship to the player, with a costume and a stock voice.

**Pass:** the comm window shows a portrait and text, or record what does work.

### E7: Custom sound playback

1. Register our own WAV, a Kokoro-rendered "Nanobots deployed" from P0-SIDECAR's venv, generated into the lane's overlay. Add it as a sound entry in a new `DATA/AUDIO/carrier_sounds.ini`, added through `freelancer.ini [Data] sounds =` (append).
2. Play it with `pub::Audio::PlaySoundEffect(1, CreateID(name))` (R6 §4.5). On Track A, also try `SoundApi::Create2dSoundSource`.
3. Evidence for audibility: no error in FLSpew, and a PipeWire sink-input from the wine process active during playback (`pactl list sink-inputs` snapshot, or `pw-dump`).

Also record whether **comm-style voice lines** can use our WAVs, i.e. a voice entry used by SendComm.

### E8: Waypoints

Set a nav waypoint to a position or object from code: `pub::Player::ReturnBestPath(client, RequestPath*, size)`, or the client waypoint API. FLSharp touches waypoint code (R5 §5). Applies to distress calls (D-9.6).

**Pass:** the waypoint shows in HUD and nav map (screenshots); it is cleared on arrival.

### E9: Loopback TCP from inside the game

A worker thread in the DLL runs `WSAStartup` and connects a non-blocking socket to **`127.0.0.1:$FLCOPILOT_PORT`**: `29170 + N` on lane N, exported by `lane.sh` (CONVENTIONS §7). The DLL reads `FLCOPILOT_PORT` from its environment, which Wine passes through; verify that, and if it doesn't arrive, fall back to an INI next to the DLL that `deploy.sh` writes per lane.
- The scenario starts the P0-SIDECAR server with `sidecar/run.sh --profile test --port $FLCOPILOT_PORT`: null audio, no real speaker or mic.
- Never call `WSAStartup` in DllMain (R6 §2.3).
- Exchange `hello`/`welcome`, then 500 `ping`/`pong` round trips.

- **Measure:**
  - round-trip latency (p50/p99);
  - frame time with and without traffic (devbridge `perf`).
- **Robustness:** kill the sidecar mid-session → the game continues with no frame hitch over 50 ms → restart the sidecar → automatic reconnect within 5 s.
- Sidecar absent at startup → no stall.

The game thread must never block (R6 §2.3).

### E10: Push-to-talk detection

Poll `GetAsyncKeyState` each tick while FL is focused and no chat or text input is active, for:

- `VK_DECIMAL` (110, numpad period; default PTT, D-11.3);
- `VK_SUBTRACT` (109, numpad minus);
- `VK_XBUTTON1` (0x05).

Drive it with **real XTEST input** under the input lock (CONVENTIONS §7):

1. `xdotool windowactivate --sync <wid>`;
2. `xdotool keydown KP_Decimal; sleep 0.3; xdotool keyup KP_Decimal`, and the same for `KP_Subtract`;
3. for the mouse, `xdotool mousemove` into the window, then `xdotool mousedown 8; sleep 0.3; xdotool mouseup 8` (button 8 = XBUTTON1 under X11; verify the mapping).

**Never `xdotool key --window`.** It uses XSendEvent, which `GetAsyncKeyState` under Wine doesn't see, so the test would fail falsely.

- **Pass:** press and release are detected with timing under 50 ms; the keys don't trigger FL actions.
  - Note: numpad minus is bound to the hidden `USER_ZOOM_IN` (VERIFIED keymap.ini L868–873). Document what it visibly does; DESIGN keeps it as an option only.
- **Unfocused case:** while FL is unfocused, GetAsyncKeyState may not see keys (UNVERIFIED, R6 §4.3). Record the behaviour.

### E11: Rebindable custom key

Can a custom key command appear in FL's Options → Controls and be rebound?

- Track A: `FlufClient::GetKeyManager()->RegisterKey(name, Key::X_OVERRIDE, fn)` plus `keylist.ini`/`keymap.ini` entries (R1 §4, VERIFIED API).
- Track B: add `[KeyCmd]` entries via overlay patches and intercept the command. Study adoxa `dockkey`.

Record whether it works. Fallback: a config-file key for PTT.

### E12: Our resource DLL

Strings and infocards from our generated DLL resolve in game: a base name, an infocard HTML with formatting. The DLL is index 8 (R3 §1.2). Verify on the info screen (screenshot).

### E13: Chat line output (optional)

Write a line to the chat window in SP. Console enables chat in SP (R5 §5; `WriteChatMessage` 0x46A150). Useful for debug or subtitles. Record the result.

## Context pack

- `docs/plan/DESIGN.md` §5 (Yard panel), §7 (D-7.1, D-7.2 menu and progress), §9 (D-9.6 distress UX), §11.3 (voice/PTT), §15 (text and UI)
- `docs/plan/TESTING.md` §Vision, §Scenarios
- `$FLMOD_RESEARCH/R1-fluf.md` §3 (UI: both systems; addresses), §4 (InfocardManager, SoundApi, KeyManager)
- `$FLMOD_RESEARCH/R5-sp-architecture.md` §4.1 (base room UI), §5 (messaging, audio, objectives, text constraints), §7 (input and IPC under Wine)
- `$FLMOD_RESEARCH/R6-copilot-sidecar.md` §2 (IPC), §3.1 (handshake), §4.3 (PTT), §4.5 (playback)
- `docs/plan/CONVENTIONS.md` §4 (devbridge names), §7 (locks, XTEST input, per-lane ports), §13 (sidecar test profile): authoritative
- `refs/FLUF/modules/{ship_dealer_enhancements,ui_overhaul,patch_notes,load_limit}`, `refs/adoxa-plugins/{dockkey,externalmsg,console}`, `refs/FLSharp/src/{infocards,waypoint*}.cpp`
- `docs/spec/ipc.md` (from P0-SIDECAR)

## Ownership

- **Owns:** `spikes/s_ui/`.
- **Must not touch:** `spikes/track_*`, `harness/`, `sidecar/` (run it; don't modify it), `docs/plan/`, `state/`.

## Contract

- **Provides:**
  - the UI capability matrix;
  - the PTT key recipe;
  - socket worker-thread code in our own words: a reference for W2-REFLEX;
  - the sound-registration recipe;
  - the text-override recipe;
  - proposed `EF-UI-*` facts.

## Tasks

E12 first (strings are needed by E4–E6), then E1 → E2 → E3 → E4 → E5 → E6 → E7 → E8 → E9 → E10 → E11 → E13.

## Acceptance

Every experiment has a verdict and evidence; the screenshot-based experiments have vision-check verdicts. Reviewers re-run E1, E2, E9 and E10.

## Engine facts to rely on / verify

- **Verify:**
  - native button placement;
  - the overlay look and input capture;
  - live infocard override;
  - the PopUpDialog reply hook;
  - custom-sound playback;
  - loopback TCP from the FL process;
  - GetAsyncKeyState under Wine;
  - our DLL at index 8.
- **Rely on:** FmtStr uses IDS, not raw strings (R5 §5); text needs our DLL or overrides.

## Pitfalls

- Every Winsock call costs a wineserver round trip. Sockets stay on the worker thread only (R6 §2.1).
- Don't play speech through FL's streaming path. FL's streaming already logs `missing MP3 codec?` under Wine, so it's fragile there (R6 §4.5). Short WAV effects are a separate matter.
- Synthetic input steals Adam's desktop focus. Hold the input lock and keep it short.

## Fallbacks and degrade path

| Channel fails | Fallback |
|---|---|
| Native button | ImGui button |
| Infocard override | The overlay shows the dynamic text |
| PopUpDialog reply | Overlay modal |
| Custom FL sound | Host playback by the sidecar for all voice; the reflex voice lines then need the sidecar (record the degraded scope) |
| GetAsyncKeyState | X11 passive key listener in the sidecar (`python-xlib` RECORD; system python has Xlib 0.33, R6 §4.3), or a WndProc subclass in the DLL |

## Report

AGENT_BRIEF_TEMPLATE format plus the UI capability matrix.

## Gate-time addendum

(Orchestrator: track, lane(s), attempt, commit trailer.)
