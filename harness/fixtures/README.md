# Fixture saves (`harness/fixtures/`)

The one fixture generator (CONVENTIONS §6, TESTING §Fixtures). It renders committed YAML specs into plain-text CRLF
`.fl` saves in a **lane's** save dir. P0-HARNESS seeds it; W1-HARNESS owns it from Wave 1.

```
gen_fixture.py --install <HDE dir> --spec <yaml path | fixture name> --out <savedir>
               [--name-rule hash|plain|both] [--tstamp now|HI,LO]
gen_fixture.py --install <HDE dir> --all --out <savedir>       # every spec in specs/
gen_fixture.py --list
```

- Run it with `$FLMOD_VENV/bin/python -I` (stdlib + pyyaml). `harness/deploy.sh --fixture <name>` calls it with the
  lane's `$HDE` and `$FL_SAVEDIR` (`<HDE>/SAVE/Accts/SinglePlayer`, flplusplus `save_in_directory = true`).
- `--spec HARNESS_endgame_eagle` (or `endgame_eagle`) resolves `specs/HARNESS_endgame_eagle.yaml` next to the script.
- On success it prints one line per written file:
  `fixture=<name> file=<path> description=<HARNESS_name> system=<sys> base=<base>` (or `pos=x,y,z`).
- Exit codes: `0` ok, `2` spec/validation error (every problem is listed on stderr), `3` refused path.

## Rules

- **Public repo (CONVENTIONS §12).** Specs hold only nicknames and our own design numbers. The template,
  loadouts, hardpoints, positions, rep tables and limits are read from the given install at generation time.
  Never commit a generated `.fl` (`*.fl` is gitignored).
- **Explicit start.** Every spec sets `system` and either `base` (docked) or `pos` (in space). HDE's
  `newplayer.fl` starts in FP7, so never rely on its defaults.
- **Lane saves only.** The generator refuses an `--out` under any `My Games` folder, under the play prefix
  (`$FLMOD_PLAY_PREFIX`, default `/home/user/freelancer/prefix`) or `~/.wine`, and refuses an `--install` in the
  play prefix. It never writes `Restart.fl`, and it won't overwrite an existing file that isn't the same fixture.
- **Validation.** An invalid fixture is a generator error, never a game crash. The generator checks:
  - `ship_archetype` against the `ships =` INIs;
  - every equip and cargo item against the `equipment =` INIs (from `EXE/freelancer.ini [Data]`);
  - every hardpoint and the item's hp type against shiparch `hp_type` lines;
  - system and base nicknames against `universe.ini`, and that the base is in that system;
  - rooms against the base INI;
  - factions against `initialworld.ini [Group]`;
  - nanobot, battery and hold limits;
  - exactly one engine and one power plant;
  - that an in-space `pos` is not inside an atmosphere or a damage zone.

  INI keys are case-insensitive, `;` starts a comment, and nicknames are written in the case the data uses.

## What gets written (and why)

The output is what the game itself writes for a new game, `Restart.fl`: **`EXE/newplayer.fl` followed by
`DATA/initialworld.ini`** (Freelancer-Decomp `server_classes.cpp` `create_restart_file`). The baseline's
`Restart.fl` line count matches that concatenation. On top of that:

- **`[Player]`** is regenerated in the game writer's key order (`server_pub.cpp`):
  - `description`, `tstamp`, `name`, `rank`, `house`…, `money`, `num_*`;
  - the template's `voice`/`costume` lines, carried over;
  - `system`, then `base` + `location` when docked, or `pos` + `rotate` in space (never both: SP writes
    `pos`/`rotate` only without a base, and no `last_base`);
  - `ship_archetype`, `equip`, `cargo`, `visit`, then the template's `log`.
  - Any other template key is carried over unchanged.
- **`description` and `name`** are `WideToHex`: `"%04x"` per UTF-16 code unit, i.e. lower-case hex of UTF-16BE.
  `HexToWide` reads that back; a non-hex value falls back to plain text, which is why `newplayer.fl`'s
  `name = Trent` works. `description = HARNESS_<name>` is what FLUF `--save-file=HARNESS_<name>` matches (FLUF
  debugger matches description, then IDS, then file name). `name` defaults to `HARNESS`.
- **`tstamp = HI,LO`** is the FILETIME of local time (`GetLocalTime` + `SystemTimeToFileTime`, as the writer
  does). `--tstamp HI,LO` pins it for deterministic output.
- **`equip = item, hardpoint, 1`.** Internal items (engine, power, scanner, tractor, armor) have an empty
  hardpoint.
- **`cargo = item, count, , , 0`.** This is the game writer's full-health form (`ReadCargoLine`: value 2 is the
  hardpoint, value 3 the health, value 4 the mission flag).
- **`location`** = `MakeLocationID(CreateID(base), room)` = `CreateID("%X_<room>")`. The room is the base INI's
  `[BaseInfo] start_room` by default, `room: <Room nickname>` to pick one, or `room: none` to omit `location`.
- **`post_campaign: true`** does the following:
  - sets `[StoryInfo] Mission = Mission_13`, `MissionNum = 42` (override with `mission:` / `mission_num:`);
  - applies the `Act_SetRep = Player, …` lines of the `enter_bar` trigger in `DATA/MISSIONS/M13/m13.ini`, read at
    generation time;
  - drops mission-state sections;
  - removes every player `locked_gate` line, both the template's `[mPlayer]` story locks and the
    `initialworld.ini [locked_gates]` ones, and keeps every `npc_locked_gate`. Every initialworld player lock is
    unlocked by an `Act_LockDock … unlock` in the story missions and in HDE's `m13_opensp_normal.ini`. That was
    checked on baseline B.
- **`story_mode: true`** keeps the template's story state, `[mPlayer]` and gate locks.

In game (Track B, harness/NOTES.md N15): the post-campaign fixtures load, docked or in space, and no story script
starts (the story control drops into a cutscene at the same spot). Still open: the "last objective" display shows
an M12 objective text, and the locked-gate check needs a devbridge `target` verb (`selftest.sh --with-gate`).

## Save file name (`--name-rule`)

- `hash` (default) writes `<CreateID(description) as %x>.fl`. This is adoxa console's `fl_name()`:
  `sprintf(file, "%x.fl", CreateIDW(desc))`, where `CreateIDW` is `wcstombs` + `CreateID`, and `CreateID`
  lower-cases. Example: `HARNESS_endgame_eagle` becomes `84ea6243.fl`.
- `plain` writes `HARNESS_<name>.fl`.
- `both` writes both files, for the in-game load-list experiment.

The file name should not matter to the game. SP login loads every `*.fl` in the folder
(`PlayerData_LoginAccount`: `_findfirst("*.fl")`), and the load list hides only `Restart.fl`. The game's own
named saves are `Save%04x.fl` from `rand()` (`PlayerData_SaveGame`). That is VERIFIED from the decomp; it is
UNVERIFIED in game.

## Spec format (`specs/HARNESS_<name>.yaml`)

```yaml
name: HARNESS_endgame_eagle   # required; must equal the file stem; becomes the save description
extends: HARNESS_other        # optional; shallow merge: this spec's top-level keys replace the parent's
summary: one line, ours
post_campaign: true           # exactly one of post_campaign / story_mode must be true
# story_mode: true
mission: Mission_13           # optional overrides of the post-campaign story state
mission_num: 42
player_name: HARNESS          # optional, default HARNESS
rank: 38                      # default: the template's
money: 60000000               # default: the template's
system: Li01                  # required
base: Li01_01_Base            # docked (exclusive with pos)
room: start_room              # start_room (default) | <Room nickname> | none
pos:                          # in space (exclusive with base); positions are always relative to a named object
  near: Li01_01               # an [Object] in `system`
  standoff: 3000              # metres beyond the object's clearance radius (atmosphere_range, enclosing
  direction: [0, 0, 1]        #   damage spheres) along `direction`
  # offset: [x, y, z]         # ...or a raw offset from the object's centre
rotate: [0, 0, 0]             # in space only, Euler degrees
ship: template                # newplayer.fl's ship, equip and cargo; or a mapping:
# ship:
#   archetype: ge_fighter6
#   base_loadout: package     # package (the ship's [Good] package + hull addons) | template | none | loadout:<nick>
#   shield: {best_class: 10}  # or best_class_10, or an explicit nickname; best = highest max_capacity that fits
#   guns:                     # per hardpoint: the highest-class preferred guns that fit, round-robin between equals
#     prefer: [special_nomad_gun01, special_nomad_gun02, special_nomad_gun03]
#     fill: all_gun_hardpoints  # or [HpWeapon01, ...]
#   turrets: {prefer: [...], fill: all_turret_hardpoints}
#   equip: [{item: ge_s_cm_01, hp: HpCM01}]   # replaces what is on that hardpoint (or the internal of that class)
cargo:                        # merged by item; count: max = the ship's nanobot_limit / shield_battery_limit
  - {item: ge_s_repair_01, count: max}
reps_default_min: 0.65        # raise every faction below this to it ...
reps_default_except: [fc_n_grp]   # ... except these
reps_owner_min:               # at least this rep with the owner (`reputation` of the system object with base =)
  - {base: Ew04_01_Base, min: 0.65}
reps: {fc_n_grp: -0.9}        # explicit values, applied last
visit: [{nick: Li01, flags: 1}]   # optional `visit = CreateID(nick), flags` for systems / bases
```

Rep order: template `house` table, then the M13 `enter_bar` table (post-campaign only), then `reps_default_min`,
then `reps_owner_min`, then `reps`. The seed specs use 0.65 rather than the 0.6 threshold, so that float
comparisons in the game can't flip them.

### Seeded fixtures

| Fixture | Contents |
|---|---|
| `HARNESS_new_story` | Story state (Mission_01a), rank 1, template ship, docked at `Li01_01_Base` |
| `HARNESS_endgame_eagle` | Post-campaign, rank 38, 60,000,000 cr, `ge_fighter6` with `special_nomad_gun01/02` on the class-10 gun hardpoints and `special_nomad_gun03` where only lower classes fit, the best class-10 shield, max bots and batteries, broadly friendly (Nomads and possessed navies stay hostile), docked at `Li01_01_Base` |
| `HARNESS_endgame_eagle_space` | The same, in space 3 km beyond Manhattan's atmosphere |
| `HARNESS_endgame_crete` | The same, docked at `Hi02_01_Base` |
| `HARNESS_ew06_space` | The same, in Ew06 1.5 km from `Ew06_to_Hi02_hole`, Nomads at -0.9 |
| `HARNESS_lvl1_rich_fp9` | Post-campaign gates and story, rank 1, 5,000,000 cr, template ship, ≥ 0.65 with Freeport 9's owner, docked at `Ew04_01_Base` |

## Adding a fixture

1. Write `specs/HARNESS_<name>.yaml`. Packages may keep their own spec dirs (e.g. `harness/fixtures/compat/`)
   and pass the path to `--spec`.
2. Use `extends:` to reuse a base fixture. Use only nicknames and your own numbers: no coordinates, prices or
   tables copied from game files.
3. Run `gen_fixture.py --install <baseline HDE> --spec <name> --out <tmp dir>`, then
   `$FLMOD_VENV/bin/pytest harness/tests/test_gen_fixture.py`. The test renders every spec in `specs/`.

## Files

- `gen_fixture.py`: the generator (`generate()` is importable).
- `flhash.py`: `create_id` (CreateID), `make_id` (faction MakeId), `make_location_id`.
- `specs/`: the committed fixture specs.
- Tests: `harness/tests/test_gen_fixture.py`. It renders every spec from the dev baseline install
  (`$FLMOD_FIXTURE_INSTALL`, default `prefix-dev-base-B`) into `tmp_path`.
