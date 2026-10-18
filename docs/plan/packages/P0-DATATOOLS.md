# P0-DATATOOLS: fltools (INI, hashes, resource DLLs, UTF/CMP, validation, patches, world export)

- **Type:** impl
- **Wave:** Phase 0
- **Depends on:** — → **Unblocks:** S-LOADOUT, W1-DATA, W1-WORLD, every generator.

## Goal

A tested Python toolkit that reads and writes every Freelancer data format the mod touches, entirely on Linux and without Windows tools. Generators can then produce the mod's data from YAML and the *local* game install at deploy time. A validator guarantees we never ship a broken reference, which is a known silent-crash class. Nothing derived from game files is ever committed.

## Requirements

- **REQ-P0-DATATOOLS-1: package layout.** `tools/fltools/`: an importable Python package, **stdlib only at runtime** (Python ≥ 3.11; the host has 3.13).
  - CLIs: `$FLMOD_VENV/bin/python -I -m fltools.<tool>` (with `tools/` on `PYTHONPATH`), or the `tools/fltools/bin/*` wrapper scripts.
  - Tests live in `tests/py/fltools/` and run with **pytest from the shared venv `$FLMOD_VENV`** (CONVENTIONS §1). The orchestrator creates the venv with pytest, pyyaml and jsonschema. Add anything else with `$FLMOD_VENV/bin/pip install` and append it to `requirements-dev.txt`.
  - Test data is **synthetic or generated at test time from the local install into `tmp_path`**; never committed (check_public blocks `.ini`, `.cmp` and `.dll` files).
  - **No game-derived values hardcoded in committed test code** (CONVENTIONS §12). Expected counts and spot values come at test time from `$FLMOD_RESEARCH/R3-data/*.json` or `$FLMOD_GOLDEN`; if those are absent, skip with a reason. Hash goldens are algorithm outputs and may be inline.
- **REQ-P0-DATATOOLS-2: `fltools.ini`.** Read and write FL INI text, round-trip exact.
  - Duplicate sections and duplicate keys are normal.
  - `;` comments.
  - CRLF line endings preserved.
  - Encoding: the files are plain text, cp1252-ish. Read as latin-1 and write latin-1 so bytes round-trip.
  - Case-insensitive section and key lookup, plus a case-insensitive path resolver. FL paths are case-insensitive while the Linux filesystem is not; HDE files mix case, e.g. `DATA/UNIVERSE/universe.ini` vs `Universe\Systems\...`.
  - API: `load(path) -> Document`; `Document.sections(name)`; `Section.get(key)`, `getall(key)`, `set(key, value, index=0)`, `add(key, value)`; `dump(path)`.
  - Port and extend `$FLMOD_RESEARCH/R3-data/tools/flini.py` (VERIFIED working on all HDE DATA INIs, per R3).
  - The DATA INIs are plain text, not BINI (VERIFIED, R3 §0, R4 §0.5).
  - A BINI decoder is optional (R4 §A3.4 has the format), only needed for other mods.
- **REQ-P0-DATATOOLS-3: `fltools.hash`.**
  - `create_id(nickname) -> int`. The algorithm is in R3 §10 and R4 §A3.3:

    ```
    table[i] built from x=i, 8 iterations of x=(x&1)?(x>>1)^(0xA001<<14):x>>1
    h=0; for c in lower(s): h=(h>>8)^table[(h&0xFF)^c]
    h=byteswap32(h); h=(h>>2)|0x80000000
    ```

    Golden values (VERIFIED against `newplayer.fl`): `Li01_to_Li02`→2830511361, `Ew06_01_Base`→3094908802, `Li02`→2745692751, `ew0601_monkey_003_m`→2318074572, `Br05`→2945937410.
  - `faction_id(nickname) -> int`: the 16-bit CRC-16/CCITT-style hash (poly 0x1021, init 0xFFFF, lower-cased; R3 §10). UNVERIFIED against a game value: find one, e.g. a faction id visible in a save or FLHook code, and add it as a golden test, or mark the test UNVERIFIED.
  - `location_id(base_id, room) = create_id("%X_%s" % (create_id(base), room))`, per Librelancer `CreateLocationID` (R3 §10).
  - Port from `$FLMOD_RESEARCH/R3-data/tools/flhash.py` and `$FLMOD_RESEARCH/scratch/tools-r4a/flhash_scan.py`.
- **REQ-P0-DATATOOLS-4: `fltools.peres`.** Read RT_STRING (type 6, blocks of 16) and RT_HTML (type 23, UTF-16 `<RDL>` XML infocards) from PE resource DLLs.
  - Resolve a global IDS (`dll_index*65536 + local_id`) using the `[Resources]` order in `EXE/freelancer.ini`. `resources.dll` is the implicit index 0; HDE has indexes 1–7 (`InfoCards`, `MiscText`, `NameResources`, `EquipResources`, `OfferBribeResources`, `MiscTextInfo2`, `Controls`), VERIFIED R3 §1.2.
  - Port `$FLMOD_RESEARCH/R3-data/tools/flres.py`.
- **REQ-P0-DATATOOLS-5: `fltools.resdll`.** Build a resource-only x86 DLL from `{local_id: string}` and `{local_id: infocard_xml}`.
  - Recipe (VERIFIED by R4 §A2.4, built and inspected):
    - write a `.rc` with `#pragma code_page(65001)`, `LANGUAGE 0x09, 0x01`, a `STRINGTABLE`, and `<id> HTML "<file>.xml"`;
    - each XML file is `b"\xff\xfe"` + UTF-16LE `<RDL><PUSH/><TEXT>…</TEXT><PARA/><POP/></RDL>`;
    - compile with `/usr/lib/llvm/22/bin/llvm-rc`;
    - link with `/usr/lib/llvm/22/bin/lld-link /dll /noentry /machine:x86`.
  - Verify by reading back with `fltools.peres`.
  - Also provide `detect_resource_index(install) -> int`: the index our DLL will get = the number of `DLL =` lines in `[Resources]` + 1. HDE gives 8, so IDS = 524288 + local id (R3 §1.2, R4 §0.1 #9). Fail loudly if something else was appended.
- **REQ-P0-DATATOOLS-6: `fltools.utf`.** Read and write the UTF container format: the `.cmp`/`.3db`/`.mat`/`.txm` tree of nodes with data leaves. Round-trip exact for unmodified trees.
  - Higher-level helpers:
    - `list_hardpoints(cmp)`: walks every part, then `Hardpoints/Fixed` and `Hardpoints/Revolute`. Each hardpoint has `Position` (3 floats) and `Orientation` (3×3 floats), and revolute ones also have `Axis` (3 floats), `Min` and `Max` (float, radians).
    - `add_hardpoint(cmp, part, name, kind, position, orientation, axis=None, min=None, max=None)`.
  - The format reference is Librelancer: `/home/user/freelancer/refs/Librelancer/src/LibreLancer.Data` (UTF parser) and LancerEdit hardpoint editing code. Study the structure; reimplement in Python (don't copy C# verbatim). Mark every format claim VERIFIED by round-trip tests on real files.
  - Test with a **copy** of `rh_battleship.cmp` and `li_dreadnought.cmp` from the play install's `DATA/SHIPS/...`, read-only, copied into `tmp_path` at test time. Round-trip byte-exact; add 2 hardpoints; re-read and confirm.
  - In-game proof is S-LOADOUT's job.
- **REQ-P0-DATATOOLS-7: `fltools.validate`.** A cross-reference validator over the **combined** data: HDE install plus a candidate overlay dir.
  - It loads every file listed in `freelancer.ini [Data]`, plus the files Content.dll hard-codes:
    - `missions\npcships.ini`, `faction_prop.ini`, `mBases.ini`, `lootprops.ini`, `pilots_population.ini`, `shipclasses.ini`, `formations.ini`, `voice_properties.ini`, `empathy.ini`, `specific_npc.ini`, `news.ini`, `RankDiff.ini`, `PTough.ini`
    - `equipment\commodities_per_faction.ini`
    - `Universe\*shortest*path.ini`

    The list is VERIFIED by string scan, R3 §1.1.
  - It checks that every reference resolves:
    - ship and solar archetypes, loadouts, equipment and goods;
    - bases, with a universe `[Base]`, an mbases `[MBase]`, a base ini with rooms, and a dock solar;
    - systems;
    - factions (in `initialworld.ini` groups);
    - pilots and NPCShipArchs;
    - sounds and voices;
    - IDS (via `fltools.peres` + our resource DLL);
    - loadout hardpoints exist on the model (via `fltools.utf`);
    - every NPC loadout has an engine. A missing engine crashes server.dll at 0x2247f (R4 §0.1 #4).
  - It also checks the encounter rules (R4 §0.1 #3):
    - every patrol faction is in the base's `[BaseFaction]`;
    - no more than 17 ships per formation;
    - permutations do not exceed formations;
    - formations exist.
  - Output: a findings list with severity, plus exit code.
- **REQ-P0-DATATOOLS-8: `fltools.hashscan`.** Collision scan over all nicknames in HDE + overlay, for CreateID and for the faction hash (16-bit; about a 1/1200 collision chance per new faction).
  - Baseline: HDE has 24,877 nicknames with 0 CreateID collisions, and 55 factions with 0 faction collisions (VERIFIED R4 §A1.3).
  - Case-only nickname differences count as the same object.
- **REQ-P0-DATATOOLS-9: `fltools.patch`.** An idempotent INI patch framework.
  - It edits **existing** HDE files inside marker blocks (`; >>> carrier-mod <block-id> v<N>` … `; <<< carrier-mod <block-id>`). Operations: append to a section; add a section; set a key in a section matched by nickname; comment out a key line (prefix `; carrier-mod-disabled: `).
  - Every operation is reversible (`unpatch`). Never replace a whole HDE file (R4 §0.1 #10).
  - It records the pre-patch sha256 and refuses to apply if the file changed unexpectedly. `--force` re-baselines and logs it.
  - Covers `freelancer.ini [Data]` / `[Resources]` / `[Initial SP DLLs]`, `dacom.ini [Libraries]`, `universe.ini`, `market_*.ini`, `mbases.ini`, `npcships.ini`, `solararch.ini`, `shiparch.ini` and `loadouts*.ini`.
  - For new standalone files we add a new `[Data]` entry instead (append after existing ones of the same key, so MP-style archetype ordering is preserved: R3 §1.1 SNICHOLS note).
- **REQ-P0-DATATOOLS-10: `fltools.worldexport`.** Produces `world.json` from an install. It is built at deploy time into the overlay (under `$FLMOD_LOCAL/gen/`) and never committed. Port and extend the R3 extract scripts (`$FLMOD_RESEARCH/R3-data/tools/extract_*.py`, `route_exposure.py`, `euler_test.py`). Contents:
  - `systems`: nickname, name (resolved IDS), navmap pos, region (from `Territory.ini`), file.
  - `links`: from every system `[Object]` with `goto = <system>, <dest_object>, <tunnel>`. Fields: from/to system, from/to object, kind (jumpgate | jumphole | airlock | nomad_gate), positions, `locked_player` (initialworld `[locked_gates] locked_gate` + newplayer story locks), `locked_npc` (`npc_locked_gate`). There are 232 directed links, all symmetric (VERIFIED R3 §2.2).
  - `objects` per system: nickname, archetype, type, pos, rotate, base, dock_with, reputation, radius (from solararch or planet archetype), death-zone radius and exclusion radius where present.
  - `hazards`: suns, planets (death zones), asteroid and nebula fields, exclusion zones and their geometry.
  - `trade_lanes`: ring chains with positions. There are 124 chains (VERIFIED R3 §2.3).
  - `zones` with encounters: shape, size, pos, rotate, density, repop, `max_battle_size`, `path_label`, usage, encounters `[(name, level, chance)]`, factions `[(faction, weight)]`. There are 3,801 zones and 6,608 zone×encounter×faction rows (VERIFIED R3 §3.3).
  - Per-faction **CD-capable fraction** by level, from the npcships→loadouts join on `cruise_disruptor01_mark01/02` / `nomad_cruise_disruptor01` (R3 §8).
  - Zone geometry convention (VERIFIED empirically, R3 §3.4): `world = Rz(rz)·Ry(ry)·Rx(rx)·local`, in degrees. CYLINDER axis is local Y, `size = (radius, length)`.
  - Document the schema in `gen/framework/WORLD_JSON.md`. ARCH-0 promotes it to `docs/spec/world_json.md`.
- **REQ-P0-DATATOOLS-11: generator framework.** `gen/framework/`, plus the **single entry point `gen/run.py`**. Every other spec and TESTING §CI call this script; there is no `gen/build.py`.
  - **`gen/run.py build --install <HDE dir> [--out <dir>] [--only <gen>]`** builds an overlay. The default out is `$FLMOD_LOCAL/gen/overlay/`, never inside the repo.
  - **`gen/run.py deploy --install <HDE dir>`** builds into a temp overlay, copies it onto the install, and applies the patch blocks. `harness/deploy.sh` calls this on lanes.
  - **`gen/run.py validate --install <HDE dir> [--overlay <dir>]`** runs the validator and the hashscan (used by CI stage 40).
  - **Discovery and plugins.**
    - Generators live in `gen/<name>/generator.py` and in **`gen/plugins/<area>/generator.py`**, the plugin interface later packages use (W1-DATA owns `gen/` outside `framework/` and `models/`).
    - Each exposes `generate(ctx)` and an optional `ORDER` int.
    - `ctx` holds:
      - the install path and the out dir;
      - the loaded INI documents (cached under `$FLMOD_LOCAL/gen/cache/`);
      - the patch framework and the resdll builder;
      - a **strings registry**, which loads `data/**/strings*.yaml`, allocates local ids deterministically from stable keys (rules in `docs/spec/text_ids.md`, written by ARCH-0), and persists the mapping to **`$FLMOD_LOCAL/gen/text_ids.json`** (CONVENTIONS §2).
  - It writes `<out>/MANIFEST.json`: new files, patched files with block ids, and sha256s.
  - **Deterministic:** the same inputs produce byte-identical outputs.
  - Ship one example generator, `gen/example_strings/`, that adds a test string and infocard and a resource DLL. Any nickname it creates uses the **`fcm_` prefix** (CONVENTIONS §2).

## Context pack

- `CLAUDE.md` guardrails 4 and 5; `docs/plan/CONVENTIONS.md` §1, §2, §5, §12 (authoritative)
- `docs/plan/DESIGN.md` §2 (D-2.1 level-gating patch will use `fltools.patch`) and §15 (text)
- `$FLMOD_RESEARCH/R3-game-data.md`: **all** (formats, `[Data]` list, `[Resources]`, hard-coded Content paths, zone keys and geometry, hashes)
- `$FLMOD_RESEARCH/R3-data/tools/*.py` (port these: `flini`, `flres`, `flhash`, `extract_*`, `route_exposure`, `euler_test`)
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md` §A1.3 (limits, hash stats), §A1.4 (crash causes), §A2 (INI practice, resource DLL recipe), §A3 (tooling, BINI, hashes)
- `$FLMOD_RESEARCH/scratch/tools-r4a/` (flhash_scan.py, resdll-test)
- `/home/user/freelancer/refs/Librelancer/src/LibreLancer.Data/` (UTF, FLHash, INI parsing, Zone.cs), `/home/user/freelancer/refs/flint/`, `/home/user/freelancer/refs/flair/` (Python FL libraries: study only; check licenses before reusing any code)
- `/home/user/freelancer/refs/Freelancer-Decomp/docs/ini/` (authoritative INI key docs)

## Ownership

- **Owns:** `tools/fltools/`, `gen/framework/`, `gen/run.py`, `gen/example_strings/`, `tests/py/fltools/`, `harness/ci.d/30-pytest.sh` (CONVENTIONS §5: runs pytest over `tests/py`, `sidecar/tests`, `gen/tests`; SKIPs absent dirs).
- **Reads:** the play install (read-only), refs, research.
- **Must not touch:** any install files (tests copy into `tmp_path`), `docs/plan/`, `state/`.

## Contract

- **Provides:** the Python API above; `gen/run.py` (`build`/`deploy`/`validate`); the plugin interface (`gen/plugins/<area>/`); the overlay `MANIFEST.json`; the `world.json` schema; the strings registry writing `$FLMOD_LOCAL/gen/text_ids.json`.
- **Consumers:** W1-DATA, W1-WORLD, S-LOADOUT, the harness deploy step.

## Tasks

1. Port `flini`, `flhash` and `flres` with tests: round-trip every HDE DATA INI in a temp copy; the hash goldens; IDS lookups of known strings (universe `strid_name = 196609` → "New York", VERIFIED R3 §1.2).
2. Write `resdll`, then verify it by reading back.
3. Write `utf` with round-trip and hardpoint-add tests.
4. Write the validator and hashscan. Run them on stock HDE: expect no ERROR findings, and record any pre-existing vanilla warnings as a baseline allow-list in `tools/fltools/baseline_findings.txt` (our own text, not game data).
5. Write the patch framework with apply/unapply tests on temp copies (byte-identical after unpatch).
6. Write `worldexport`, golden-tested against the R3 extracts in `$FLMOD_RESEARCH/R3-data/*.json`: counts of systems, links and zones, plus selected values (`Hi02_to_Ew06_hole` position `24336,0,-44216`; Li01 trade lane "Fort Bush"→"Colorado Jump Gate" 30,000 m; R3 §2.3–2.4).
7. Build the generator framework and the example generator.
8. Write `tools/fltools/README.md`.

## Acceptance (automated)

- `pytest -q tests/py/fltools` all pass. The INI round-trip test covers **every** INI under the install's `DATA/`, copied to tmp: 100% byte-identical.
- Hash goldens pass (5 CreateID values).
- The resdll test builds a DLL, reads back 2 strings and 1 infocard, and `llvm-readobj --file-headers` shows `IMAGE_FILE_MACHINE_I386` and DLL characteristics.
- UTF round-trip is byte-identical for `rh_battleship.cmp`, `li_dreadnought.cmp` and `or_osiris.cmp` (find the paths via shiparch `DA_archetype`). Adding a hardpoint round-trips and lists it.
- Validator on stock HDE: zero ERROR. Validator on a synthetic broken overlay reports each deliberate break:
  - a loadout referencing a missing equipment;
  - an NPC loadout without an engine;
  - a base without a dock solar;
  - an IDS outside any DLL;
  - a duplicate nickname differing only in case.
- Hashscan on stock HDE: 0 collisions, 24,877 nicknames (±0; if different, explain).
- `worldexport`: 53 systems, 232 links, 124 lane chains, 3,801 zones, matching the counts in `$FLMOD_RESEARCH/R3-data/*.json` at test time. Golden spot checks pass.
  - Route-exposure parity data (a few precomputed exposures from the Python reference) is written to **`$FLMOD_GOLDEN/route_exposure/`** for W1-WORLD's golden tests, never committed. R3 §3.4 has one example leg in Li01.
- `gen/run.py` on the example generator is deterministic: two runs produce identical MANIFEST sha256s.
- `python3 -I tools/check_public.py --tree .` passes, so no game data is committed.

## Engine facts to rely on / verify

- VERIFIED: plain-text INIs; the `[Resources]` order and the index-8 prediction; CreateID goldens; zone rotation convention; the Content.dll hard-coded file list.
- UNVERIFIED: the faction-hash golden; UTF write correctness in game (S-LOADOUT proves it).

## Pitfalls

- Never write into an install from tests. Copy to `tmp_path`.
- Don't "normalize" whitespace or case when rewriting HDE files. Patch blocks only.
- The HDE installer swaps resource DLLs (`*_vanilla.dll`); always read the ones `[Resources]` names (R3 §1.2).
- Nicknames are case-insensitive (R4 §A1.3).
- R3 tools expect `strings.pkl` beside them. The ports must rebuild that cache in a temp or overlay dir, never in the repo.

## Fallbacks and degrade path

- UTF writing proves hard: deliver read-only UTF plus a "copy model and append hardpoint node" writer. Mark `add_hardpoint` DEGRADED; S-LOADOUT then tests the alternative (loadouts only on existing hardpoints).
- The validator is too slow: cache parsed docs in `$FLMOD_LOCAL/gen/cache/`.

## Report

AGENT_BRIEF_TEMPLATE format. Include the API summary, test counts, the `world.json` schema path, and baseline validator findings.

## Gate-time addendum

(Orchestrator: attempt number, commit trailer.)
