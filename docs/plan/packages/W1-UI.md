# W1-UI: UI kit, NavBar buttons, notifications, text service, waypoints

- **Type:** impl
- **Wave:** 1
- **Depends on:** W1-PLATFORM, W1-HARNESS (sub-wave 1b, CONVENTIONS §8; contracts `ui_kit.hpp`, `text.hpp`, `platform.hpp` from ARCH-0) → **Unblocks:** W2-YARD, W2-CARRIER-UI, W3-AMBUSH (distress UX), W3-NOMAD, W4-HIRING, W4-WINGMEN (roster), W4-ESCALATION

## Goal

One FL-styled UI toolkit that every panel uses: the Carrier Yard, the travel menu, the hold, the quartermaster, the roster, hiring and the influence map. Panels look and behave like Freelancer and stay readable from 1280×720 to 4K.

The package also provides:

- notification primitives: Neural Net messages, popups, toasts, chat lines and comms;
- a text service, so all player-facing text comes from our resource DLL or runtime overrides (FL's `FmtStr` APIs take IDS, not raw strings — R5 §5);
- a waypoint helper for distress calls and destinations.

## Requirements

- **REQ-W1-UI-1: Window kit** (D-15.2, D-15.3), built on the platform overlay.
  - **Widgets:** window (title, close, optional tabs), list or table with selection, buttons, toggles, sliders, number spinners, text input, progress bar, tooltips, confirm dialog, and a two-pane layout (catalog + details).
  - **Style:** FL-like. Dark translucent panels, the FL palette (cyan/teal highlights, amber warnings), and FL fonts if loadable. Otherwise Saira Condensed, which FLUF ships in `DATA/FONTS`, or the closest available face.
  - **Scaling:** by screen height (reference 1080p), clamped so the minimum text height is ≥ 14 px at 720p.
  - **Input:** full keyboard navigation (arrows, Enter, Esc closes) and mouse.
  - Windows remember position per resolution (stored in config).
  - Every widget has a stable ID `<window>/<widget>`. Devbridge verbs per CONVENTIONS §4: `ui.find <id>` (emits `ev=ui id= rect=x,y,w,h visible=0|1`), `ui.click <id>`, `ui.open <panel> [--test]`, `ui.list`. Additive `ui.type <id> <text>`, `ui.select <id> <row>` and `ui.perf` go to ARCH-1 for `docs/spec/devbridge.md`.
- **REQ-W1-UI-2: Native-only fallback.** If `Platform::HasOverlay()` is false, the same panel definitions render as a sequence of native popups/lists with hotkeys. This is degraded but functional: BUILD_PLAN §8 row 1.
- **REQ-W1-UI-3: NavBar button helper.**
  - `AddBaseButton(id, label, icon, predicate(baseId), onClick)` adds a button to the base NavBar when the predicate holds (e.g. "this base is a yard", "this base is a carrier").
  - Icon: reuse a vanilla `interface\baseside\*.3db` mesh chosen by S-UI.
  - Survives room switches; no duplicates.
  - Fallback: hotkey F7 plus a toast "Carrier menu: F7".
- **REQ-W1-UI-4: Notifications.**
  - `NeuralNet(msgId or text)`: `pub::Player::SendNNMessage` for vanilla voice IDs; text via the IDS override.
  - `Popup(title, body, buttons) → callback`: `pub::Player::PopUpDialog` (buttons bitmask: LeftYes=1, CenterNo=2, RightLater=4, CenterOk=8; the reply arrives through `IServerImpl::PopUpDialog` vtable +0x128), or a kit dialog.
  - `Toast(text, seconds, severity)`: an overlay toast stack.
  - `Mission message`: `pub::Player::DisplayMissionMessage`.
  - `ChatLine(text)`: if S-UI proves the SP chat path (HDE Console enables it; `WriteChatMessage` 0x46A150).
  - `Comm(speakerCostume, voice, lines…)`: `pub::SpaceObj::SendComm` if S-UI proves it (comm portrait).
- **REQ-W1-UI-5: Text service** (D-15.1).
  - All player-facing strings live in `data/**/strings*.yaml`: per-area files owned by their packages, merged by W1-DATA. W1-DATA builds `CarrierText.dll` at IDS `dll_index × 65536 + local_id` (HDE: index 8 → 524288+), allocated per `docs/spec/text_ids.md`. The index is detected at deploy time, and the key → IDS map is the deployed copy of `$FLMOD_LOCAL/gen/text_ids.json`.
  - `Text::Ids(key)` maps a string key to its IDS.
  - `Text::Format(key, args…)` produces a UTF-8 string for the kit.
  - `Text::OverrideIds(ids, wstring, isName)` makes a runtime change to a name or infocard (FLUF `InfocardManager::OverrideInfocard` on Track A; an own hook of the IDS lookup on Track B, e.g. `GetIdsName` 0x4347E0 / infocard 0x57DA40, per S-UI).
  - Used for carrier base names, base infocards (live travel progress in the base info text) and spawned-ship names.
  - Missing keys show `⟦key⟧` and log a warning; they never crash.
- **REQ-W1-UI-6: Waypoints.** `SetWaypoint(system, pos | objectId, label)`, `ClearWaypoint()`, and an optional best-path request across systems: `pub::Player::ReturnBestPath` with `RequestPath{repId, waypointCount, …, PathEntry{pos, objId, systemId}}` (R5 §5).
- **REQ-W1-UI-7: Screenshot-ability.** Each window has a deterministic test layout (devbridge `ui.open <window> --test`) so the playbot can screenshot it and vision-check it. Panels carry a visible title matching their ID's display name.
- **REQ-W1-UI-8: No game-thread stalls.** Rendering cost under 1 ms per frame with 3 windows open; measured.

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§3 specs, §4 devbridge, §7 XTEST input, §8 sub-waves)
- `docs/plan/DESIGN.md` §5.1 (Yard panel), §7.1–7.2 (travel menu and progress), §9.6 (distress UX), §11.6–11.7 (roster, orders), §15
- `docs/plan/TESTING.md` §Vision, §Playbot, §Scenarios
- `state/ENGINE_FACTS.md`: overlay, NavBar, popup, NN, chat, comm, IDS override, waypoint entries (S-UI)
- `src/contracts/{ui_kit,text,platform,events}.hpp`, `docs/spec/ui.md`, `docs/spec/text_ids.md`
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R1-fluf.md` §3 (ImGui overlay, `AbstractVanillaInterface`, `FlButtonControl`, `CreateButtonControl` 0x5A0C90, NavBar coordinates unknown, icon meshes `interface\baseside\*.3db`, `OpenDialogue`), §4 (`InfocardManager`, `SoundApi`)
  - `/home/user/freelancer/carrier-mod/local/research/R5-sp-architecture.md` §4.1 (NavBar comes from rooms and hotspots; no INI-only way to add buttons), §5 (messaging APIs and the FmtStr constraint)
  - `/home/user/freelancer/carrier-mod/local/research/R4-lore-and-testloop.md` §A2.3 (infocard RDL format: `<RDL><PUSH/><TEXT>…</TEXT><PARA/><POP/></RDL>`, BOM UTF-16)
- Reference:
  - `/home/user/freelancer/refs/FLUF/modules/ship_dealer_enhancements/` (NavBar button)
  - `/home/user/freelancer/refs/FLUF/modules/patch_notes/` (FlWindow)
  - `/home/user/freelancer/refs/FLUF/modules/ui_overhaul/`
  - `/home/user/freelancer/refs/adoxa-plugins/externalmsg/` (chat lines)

## Ownership

- **Owns:** `src/game/ui/kit/`, `src/game/text/` (with `tests/`, `scenarios/`), and `harness/scenarios/ui/`, plus `harness/rubrics/ui_*`.
- **Reads:** contracts, platform API, core API, `data/**/strings*.yaml` (read-only).
- **Must not touch:** feature panels (`src/game/ui/yard/`, `src/game/ui/carrier/`, `src/game/ui/hiring/`; Wave 2+), contracts.

## Contract

- **Provides:** `ui_kit.hpp` (widgets, windows, notifications, NavBar helper, waypoint helper) and `text.hpp`.
- **Consumes:** `platform.hpp` (overlay, native controls, keys), core config and devbridge.

## Tasks

1. Theme, scaling and fonts. Produce a style sheet document with screenshots: `src/game/ui/kit/STYLE.md`.
2. Widget set, with a stable-ID scheme and devbridge `ui click/type/select`.
3. Native-only fallback renderer.
4. NavBar button helper, using the S-UI method.
5. Notification APIs.
6. Text service: key → IDS map loader (generated by W1-DATA as `text_ids.json`), runtime override, missing-key handling.
7. Waypoint helper.
8. A demo window (`ui.open kit_demo --test`) with every widget, used by tests.
9. Scenarios and vision rubrics.

## Acceptance

- **Host tests:**
  - `text_missing_key_placeholder`
  - `text_format_args`
  - `widget_id_stability`
  - `scale_by_height` (720p/1080p/1440p/2160p)
- **In-game scenarios:**
  1. `ui_kit_demo`: from `HARNESS_endgame_eagle`, docked and in space, `ui.open kit_demo --test` → screenshot at 1280×720 and 3744×2106 (Adam's desktop) or 2560×1440.
     - **Vision rubric:** "A dark translucent window titled 'Kit Demo' with readable labels, a list with 5 rows, buttons, a progress bar at ~60 %, nothing clipped or overlapping, styled like Freelancer's UI (no default grey ImGui theme)".
  2. `ui_navbar_button`: docked at Manhattan (`Li01_01_Base`) with a predicate that is true → screenshot (vision: "an additional button sits in the base menu bar alongside Bar/Commodity/Equipment/Ship Dealer icons"). Click it (input lock, real XTEST input at the `ui.find` rect) → `ev=ui.click id=…`. Change rooms (Bar → Deck → Bar) → still exactly one button.
  3. `ui_notifications`: fire an NN message, a popup with Yes/No (answer Yes via input → callback `ev=popup answer=yes`), a toast, a mission message, a chat line (if supported), and a waypoint to the Li01→Li04 gate → screenshots. The waypoint is visible on the HUD or nav map (vision).
  4. `ui_ids_override`: override the name of the base you are docked at → the base info panel or the target name shows the new text (screenshot plus vision).
  5. `ui_native_fallback`: force `HasOverlay=false` (config) → `kit_demo` renders through the native fallback and is still operable by the keyboard.
- **Performance:** `ui.perf` → `HARNESS metric=ui_frame_ms value=<avg>` < 1.0 with 3 windows open.

## Engine facts to rely on / verify

- NavBar buttons come from rooms and hotspots, with hardcoded behaviours, so custom buttons need control creation (R5 §4.1). NavBar layout and coordinates are UNVERIFIED (R1 §3.2); use the S-UI result.
- `FmtStr` takes IDS plus mad-lib substitutions, not raw strings (R5 §5, VERIFIED header). Use the text service.

## Pitfalls

- FLUF draws its own cursor (NOPs FL's cursor code) on Track A. Make sure kit windows don't double-draw or hide the cursor.
- ReShade's overlay hotkey (Home) and ImGui input routing: don't let FL also receive clicks consumed by a kit window.
- Very high resolutions (3744×2106 is Adam's actual desktop): verify the scaling.

## Fallbacks and degrade path

1. No NavBar button → hotkey F7 plus a toast hint.
2. No overlay → native fallback (REQ-2).
3. No runtime IDS override → static strings only. Dynamic progress shows in kit windows instead of the base infocard.

## Report

Use the standard report. Include the style screenshots, the widget ID convention, and the capability matrix (chat, comm, override, waypoint).

## Gate-time addendum

The orchestrator fills:

- the track;
- S-UI ENGINE_FACTS IDs (NavBar method, icon mesh, IDS override method, chat or comm availability);
- the CarrierText DLL index detected on lanes;
- lanes;
- attempt notes;
- the commit trailer.
