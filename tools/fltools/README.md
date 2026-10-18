# fltools

Python toolkit (stdlib only, Python >= 3.11) that reads and writes the Freelancer data formats
the mod touches, on Linux, without Windows tools. Owned by P0-DATATOOLS. Nothing here writes into
a game install unless a caller explicitly asks (`fltools.patch`, `gen/run.py deploy`).

## Running

- Library: put `tools/` on `sys.path` (the tests' `conftest.py` and `gen/run.py` do this).
- CLIs: `$FLMOD_VENV/bin/python -I tools/fltools/bin/<tool> ...`. The wrappers add `tools/`
  themselves because `-I` ignores `PYTHONPATH`. Without `-I`,
  `PYTHONPATH=tools python -m fltools.<module>` also works.
- Install root: `--install <HDE dir>`; the default is `$FLMOD_HDE`, else the play install's HDE
  directory, **read-only**.
- Tests: `$FLMOD_VENV/bin/python -I -m pytest -q -p no:cacheprovider tests/py/fltools`. Tests that
  need the install, `$FLMOD_RESEARCH` or the venv skip with a reason when those are absent.

| Tool | Module | Purpose |
|---|---|---|
| `flhash` | `hash` | `CreateID`, `--faction` (MakeId), `--room R` (MakeLocationID) |
| `flids` | `peres` | resolve IDS numbers; `--dll x.dll` dumps a DLL |
| `flresdll` | `resdll` | build a resource DLL from `{"strings": {...}, "infocards": {...}}` |
| `flutf` | `utf` | dump a UTF tree; `--hardpoints` lists a model's hardpoints |
| `flpatch` | `patch` | `apply` / `unpatch` / `status` of marker-block patches |
| `flvalidate` | `validate` | cross-reference validator (`--overlay`, `--json`, `--write-baseline`) |
| `flhashscan` | `hashscan` | CreateID and faction-hash collision scan |
| `flworldexport` | `worldexport` | write `world.json` (default `$FLMOD_LOCAL/gen/world.json`); `--route-exposure-golden DIR` |

## API summary

| Module | Main API |
|---|---|
| `ini` | `load(path)`, `loads(bytes)` -> `Document`; `Document.sections(name, **match)`, `.section(name, **match)`, `.add_section(name, items)`, `.dumps()`, `.to_bytes()`, `.dump(path)`; `Section.get(key)` (params string), `.get1(key)` (first field), `.getv(key)` (fields), `.getall(key)`, `.getallv(key)`, `.set(key, value, index=0)`, `.add(key, value)`, `.remove(key)`, `.nickname`; `CIResolver` / `ci_path(base, rel)`; `iter_ini_files(root)` |
| `bini` | `decode(bytes)`, `encode(sections)`, `to_document(bytes)` (`ini.loads` uses it for `BINI` input) |
| `hash` | `create_id(nick)`, `faction_id(nick)`, `location_id(base, room)` |
| `peres` | `read_pe(bytes)`, `ResourceDll(path)` (`.strings`, `.html`), `IdsResolver.from_install(install)` (`.name(ids)`, `.infocard(ids)`, `.lookup(ids)`, `.names`) |
| `resdll` | `build_dll(strings, infocards, backend="python"|"llvm")`, `write_dll(path, ...)`, `rdl_from_text(text)`, `check_infocard(xml)`, `detect_resource_index(install, dll_name=None, expected=8)` |
| `utf` | `load(path)` / `loads(bytes)` -> `UtfFile` (`.root` `Node` tree, `.dumps(layout="preserve"|"compact")`, `.dump(path)`); `list_hardpoints(utf)`, `add_hardpoint(utf, part, name, kind, position, orientation, axis, min, max)`, `parts(utf)` |
| `install` | `Install(root, overlay=None, pristine=False)`: `data_path(rel)`, `exe_path(rel)`, `data_ini(rel)`, `exe_ini(rel)`, `freelancer_ini()`, `data_entries()`, `data_files(key)`, `resource_dll_names()`, `iter_data_inis()`; `CONTENT_HARDCODED` |
| `patch` | `apply_units(text, units)`, `strip(text, ids=None)`, `patch_file(root, rel, units)`, `unpatch_file(root, rel, ids)`, `apply_overlay_patches(root, units)`, `PatchState` |
| `validate` | `validate(install, baseline=None, check_hardpoints=True)` -> `Report` (`.findings`, `.errors`, `.exit_code`, `.stats`) |
| `hashscan` | `scan(install)` -> `HashScan` (`.createid_collisions`, `.faction_collisions`, `.nicknames`, `.factions`) |
| `geometry` | `rot(rx, ry, rz)`, `contains(zone, p)`, `cylinder_endpoints(zone)`, `exposure(world, system, a, b, rep)` |
| `worldexport` | `export(install)` -> dict (schema in `gen/framework/WORLD_JSON.md`), `dumps`, `write`, `route_exposure_golden(world)` |

## Formats and facts (with evidence)

- **INI** (VERIFIED): every one of the 1,254 INIs under HDE `DATA/` round-trips byte-identically
  (`test_every_hde_data_ini_roundtrips`). Grammar follows the retail text reader (Freelancer-Decomp
  `docs/ini/parsers.md`): line ends `\r\n`, `\n\r`, `\r`, `\n`; only space/tab are blanks; `;`
  comments; key up to `=`/`;`; `[;Name]` sections are disabled.
- **CreateID** (VERIFIED): 5 goldens plus every `locked_gate = <hash> ;<name>` pair in
  `newplayer.fl`. **Faction id** (UNVERIFIED in game): matches Librelancer and the decompilation's
  `MakeId`; no game-produced value was found.
- **Resource DLLs** (VERIFIED read): the `[Resources]` order resolves R3's recorded names (systems,
  bases, factions). **Build** (VERIFIED structurally): the pure-Python DLL reads back, and
  `llvm-readobj` reports `IMAGE_FILE_MACHINE_I386` and `IMAGE_FILE_DLL`; its header shape copies
  HDE's `Controls.dll`. The llvm backend (`llvm-rc /C 65001` + `lld-link`) gives the same resources.
  In-game loading is UNVERIFIED until a lane test loads it.
- **UTF** (VERIFIED round trip): all 3,284 UTF files in HDE `DATA` (`.cmp .3db .mat .txm .sph .ale
  .dfm .anm .vms .utf`) round-trip byte-identically in preserve layout; adding a hardpoint re-reads
  on all 2,022 `.cmp`/`.3db` models. In-game effect of added hardpoints is S-LOADOUT's job
  (UNVERIFIED).
- **Hash scan** (VERIFIED): 24,900 unique nicknames, 0 CreateID collisions; 55 factions, 0
  faction-hash collisions. R4's 24,877 came from a regex that stopped at blanks (26 nicknames with
  spaces collapsed into 3); `legacy_regex_count` reproduces it.
- **Validator** (VERIFIED on stock HDE): 0 ERROR and 0 WARNING after the baseline; 79 baseline
  findings (below); 19,704 loadout hardpoint references checked against 104 parsed models, all
  present; 12,587 IDS references checked.
- **world.json** (VERIFIED against R3): 53 systems, 232 links (84/140/6/2 by kind), 124 lanes,
  3,801 zones, 6,608 zone x encounter x faction rows; exposures equal R3's reference script.

## Validator finding codes

| Code | Severity | Check |
|---|---|---|
| F001 / F002 | ERROR (F002 Universe path tables: WARNING) | `[Data]` file / Content.dll hard-coded file missing |
| D001 | ERROR | nickname defined twice in a namespace with different case |
| D002 | WARNING (ERROR on overlay content) | nickname defined twice in a namespace |
| L001 / L002 | ERROR | loadout `equip` / `cargo` references nothing |
| L003 | WARNING | loadout `archetype` is not a ship or solar |
| N001 / N003 | ERROR | NPCShipArch loadout / ship_archetype missing |
| N002 | ERROR | NPC loadout has no `[Engine]` equip (server.dll 0x2247f) |
| N004 | ERROR (missing pilot) / WARNING (no pilot key) | NPC pilot |
| N005 / N006 / N007 | ERROR | faction_prop `npc_ship` / `affiliation` / `formation` target missing |
| N010 | WARNING | faction_prop costume parts not in costumes/bodyparts |
| A001 / A003 | WARNING | sound key / mbases voice is not defined; A002 (ERROR): faction_prop voice |
| R001 / R002 | ERROR | `[Group] rep` target / `[GF_NPC] affiliation` is not a faction |
| M001 | ERROR | ship/solar `DA_archetype` file missing |
| H001 | WARNING (ERROR on overlay content) | loadout hardpoint not on the archetype's model |
| S001-S010, S013 | ERROR (S010, S013 WARNING) | system file, object archetype, goto target, object loadout/reputation, > 10 jump objects (server.dll 0x1b221), no solar (Freelancer.exe 0xd1744), undeclared/missing encounter, zone faction, density class, parent |
| B001-B007, B009 | ERROR | universe `[Base]` system/file/rooms/start room, no `[MBase]`, no dock solar (server.dll 0x14990/0xab670; INFO when mission- or runtime-spawned), object `base`/`dock_with` unknown, dock solar in another system, mbases factions |
| E001-E005, E007 | ERROR | > 17 ships per formation, permutation past the formations, missing formation mapping, empty formation, unknown ship class, patrol_path encounter in a zone without `path_label` |
| E006 | WARNING (ERROR on overlay content) | heuristic: path-zone faction has no `[BaseFaction]` on any base of the system; overlay when the zone, encounter or file is the overlay's |
| E008 | WARNING | formations.ini formation with > 17 positions |
| G001-G003 | ERROR | goods `equipment`/`ship`/`hull`/`addon`, market base, `marketgood` |
| I001 | ERROR | IDS points past the last loaded DLL |
| I002 | WARNING (ERROR in our own DLL's range) | IDS not found in its DLL |
| I003 | ERROR | `[Resources]` DLL file missing |
| I004 | INFO | `ids_info` points at a string (or `ids_name` at an infocard): vanilla does this often |
| C001 | ERROR | a nickname the overlay introduces does not start with `fcm_` (CONVENTIONS §2). Candidates: sections of overlay files and every section a patch unit adds (by marker region). "Introduces" = no pristine section of the same namespace (symbol table such as goods/equipment/ships, else the section type) has it. `[Room]`/`[MRoom]` names are exempt |
| C002 | ERROR | a patch unit adds, replaces or disables a `nickname` key inside a vanilla section (shipped nicknames are never renamed, CLAUDE.md guardrail 4) |

`baseline_findings.txt` lists stock HDE's findings (`CODE|file|subject`); they report as BASELINE.
Subjects hold nicknames and key names only, never values copied from game files (IDS findings use
`<nickname>:<key>`; the number is in the message). Findings on files or nicknames an overlay
introduces never match it. The 79 entries: 4 B004 + 7
B005 (intro-scene bases and three story bases without a static dock solar), 1 D002, 62 E006, 4
I002, 1 N004. `test_baseline_is_exact` fails when the baseline goes stale in either direction.

## Patch markers

```
; >>> carrier-mod <region-id> v<N>[ noeol]
; carrier-mod-disabled: <original line>
<new lines>
; <<< carrier-mod <region-id>
```

State lives in `<install>/carrier-mod.patchstate.json` (pristine sha256, patched sha256, applied
units, re-baseline log). A file whose pristine content changed is refused unless `--force`. When
the last recorded file is restored the state file is deleted, so a fully unpatched install is
byte-identical to the original. Patch targets are root-relative (absolute paths and `..` are
refused) and a target that resolves into the play prefix (e.g. a symlinked file) is refused while
planning, before anything is written.

Overlay provenance in the validator is by region: every section whose header lies inside a
carrier-mod region counts as overlay content (so a unit that re-adds a vanilla nickname is an
overlay D001/D002 finding, an ERROR). Exception: sections whose nickname references something
defined elsewhere (`[EncounterParameters]`, `[Room]`, `[MRoom]`, `[BaseInfo]`) do not make that
nickname overlay, and a zone row (E003/E006) is overlay only when its zone, system file or
encounter file is; so declaring a vanilla encounter for a new `fcm_` zone leaves vanilla zones
elsewhere alone.

## Reserved unit namespace `harness.*` (D107)

Unit ids starting with `harness.` (case-insensitive; `fltools.patch.PRESERVED_PREFIXES`) belong
to the test harness, which uses them for its own install edits (first user: the devbridge block
in `EXE/dacom.ini [Libraries]`, unit `harness.dacom`).

- **Who may use it:** only harness code (`harness/lib/deploy.py`, owned by P0-HARNESS, later
  W1-HARNESS). It applies and removes its units with `fltools.patch.patch_file(root, rel,
  [unit])` / `unpatch_file(root, rel, ["harness.<x>"])` on the install's shared patch state.
  Generators may not: `gen/run.py` refuses a `harness.*` unit (a generator named `harness`
  fails at build), and `plan_overlay_patches` refuses one with a PatchError.
- **What gen guarantees:** overlay reconciliation (`plan_overlay_patches` /
  `apply_overlay_patches`, so `gen/run.py deploy` and `undeploy`) carries already applied
  `harness.*` units over unchanged: never stripped, re-ordered or rewritten. Each stays right
  after the overlay unit it followed (or first), so an unchanged overlay redeploy is byte-exact.
  `undeploy` removes only gen's files and regions and keeps the patch state while it still
  records harness units. Only an explicit harness unpatch with the unit's id removes it, which
  leaves the file byte-identical to its state before the unit was added.
- The baseline check strips every carrier-mod region, harness ones included, so the harness
  rewriting its own unit never trips gen's baseline check.
- **Switch-over:** `harness/lib/deploy.py` still writes its own un-id'd `; >>> carrier-mod` block
  today. Moving it to the `harness.dacom` unit is P0-HARNESS/W1-HARNESS work, done after both
  packages have merged (not part of P0-DATATOOLS).
- Tests: `tests/py/fltools/test_harness_units.py` (gen then harness, harness then gen, harness
  unpatch keeps gen's regions, reserved-id refusals, merge order).
