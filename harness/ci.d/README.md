# `harness/ci.d/`: CI drop-in stages

`harness/ci.sh` is the single CI entry point (CONVENTIONS §5, TESTING §CI). It has exactly one built-in stage, `public`. Every other stage is a drop-in script in this directory. This file is the protocol every drop-in must follow. P0-REPO owns `ci.sh` and this README; each stage file belongs to the package listed below.

## CLI

```
harness/ci.sh [--quick|--full] [--lanes N] [--only <stage>[,<stage>...]]
```

| Invocation | Runs | Used by |
|---|---|---|
| `ci.sh --quick` | `public` + drop-ins numbered **below 60** (no game) | authors during development |
| `ci.sh` | `public` + drop-ins numbered **up to and including 60** | the orchestrator, after each merge |
| `ci.sh --full` | `public` + **every** drop-in | every gate |
| `ci.sh --only a,b` | only the named stages (repeatable), ignoring the number cutoff | targeted reruns, e.g. `--only data-validate` |

- `--lanes N` (default 1) is passed to stages as `CI_LANES`.
- `--only` takes stage names: `public`, or the `<name>` part of a drop-in file name.
  - Naming a canonical stage whose drop-in doesn't exist yet reports `SKIP`.
  - Any other unknown name is a usage error (exit 2).
- Stages run in order: `public` first, then the drop-ins in lexical file-name order. **The run stops at the first FAIL**; the remaining stages are listed as `NOT RUN`.
- Exit codes: `0` when no stage failed (PASS and SKIP only), `1` when a stage failed, `2` for a usage or setup error.

## Stage numbers and owners (fixed by CONVENTIONS §5)

| File | Stage | Owner | Mode |
|---|---|---|---|
| (built in) | `public` | P0-REPO | always, first |
| `10-build.sh` | build | P0-TOOLCHAIN | quick, default, full |
| `20-host-tests.sh` | host-tests | P0-TOOLCHAIN | quick, default, full |
| `30-pytest.sh` | pytest | P0-DATATOOLS | quick, default, full |
| `40-data-validate.sh` | data-validate | W1-DATA | quick, default, full |
| `50-import-check.sh` | import-check | P0-TOOLCHAIN | quick, default, full |
| `60-scenarios-quick.sh` | scenarios-quick | ARCH-0 stub, then W1-HARNESS | default, full |
| `70-scenarios-full.sh` | scenarios-full | W1-HARNESS | full |
| `80-soak-smoke.sh` | soak-smoke | W1-HARNESS | full |

Only the owner creates or edits a stage file. Don't add new numbers without an orchestrator decision.

## The drop-in protocol

1. **Name and mode.**
   - The file name is `NN-<name>.sh`: two digits, a dash, then lowercase letters, digits and dashes. Other files here are ignored, with a warning for stray `*.sh` files.
   - The file must be **executable** (`git update-index --chmod=+x`). A non-executable drop-in is reported as FAIL.
   - It is run directly, so start it with a shebang (`#!/usr/bin/env bash`).
2. **Environment.** `ci.sh` sources `tools/env.sh` first, so the `FLMOD_*` paths and the wine guards are already set. On top of that, each stage receives:

   | Variable | Value |
   |---|---|
   | `CI_MODE` | `quick`, `default` or `full` |
   | `CI_LANES` | the `--lanes` value (a positive integer) |
   | `CI_RUNDIR` | the run directory, `$FLMOD_TESTRUNS/<UTC stamp>-ci/`. Put the stage's artifacts in `$CI_RUNDIR/<NN>-<name>/`. |
   | `CI_QUARANTINE` | path of `state/QUARANTINE.md` (it may not exist) |
   | `CI_REPO_ROOT` | the work tree under test (your worktree, or the main checkout) |
   | `CI_STAGE` | the stage name |

   - The working directory is `CI_REPO_ROOT`, and stdin is `/dev/null`.
   - `FLMOD_REPO` always points at the main checkout. Build and test the code in `CI_REPO_ROOT`.
3. **Output.**
   - Everything the stage prints goes to `$CI_RUNDIR/<NN>-<name>.log`.
   - The stage must print exactly one verdict line, ideally last:

     ```
     CI <name>: PASS|FAIL|SKIP (<reason>)
     ```

     `ci.sh` copies the reason into `summary.md`.
4. **Exit code.** It sets the verdict, and wins if it disagrees with the printed line (the mismatch is noted).

   | Exit code | Verdict |
   |---|---|
   | `0` | PASS |
   | `77` | SKIP |
   | anything else | FAIL |

5. **Missing prerequisites mean SKIP, never FAIL.** If what the stage needs doesn't exist yet, it prints `CI <name>: SKIP (<what is missing>)` and exits 77. Examples: no `CMakeLists.txt`, no built DLL, no lane prefix, no `harness/scenario.sh`. A stage FAILs only when something that exists is broken.
6. **Quarantine** (CONVENTIONS §10). Scenario stages (60, 70, 80) read `CI_QUARANTINE`.
   - A listed scenario still runs, but is reported as `SKIP(quarantined)` and doesn't fail the stage.
   - Mention the count in the reason, e.g. `CI scenarios-quick: PASS (14 pass, 2 SKIP(quarantined))`.
7. **Hygiene.**
   - Write only under `CI_RUNDIR` (and your own build dirs), never under `harness/out/`.
   - Game stages acquire and release lanes through `harness/lane.sh`.
   - Never trigger real outbound side effects.

### Minimal drop-in

```bash
#!/usr/bin/env bash
set -uo pipefail
name=pytest
if [ ! -d "$CI_REPO_ROOT/tests/py" ]; then
    echo "CI $name: SKIP (no tests/py yet)"; exit 77
fi
if "$FLMOD_VENV/bin/python" -I -m pytest -q "$CI_REPO_ROOT/tests/py"; then
    echo "CI $name: PASS (pytest green)"; exit 0
fi
echo "CI $name: FAIL (pytest failures, see log)"; exit 1
```

## Output: `summary.md`

Each run writes `$FLMOD_TESTRUNS/<UTC stamp>-ci/summary.md`, the only file the orchestrator reads. It contains:

- a header: mode, lanes, `--only`, the repo and HEAD sha, the number of uncommitted paths, and start and finish times;
- one line per stage: `CI <name>: PASS|FAIL|SKIP|NOT RUN <reason> [<secs>s] log: <path>`;
- a final line: `VERDICT: PASS|FAIL (<n> pass, <n> skip, <n> fail, <n> not run)`.

While the run is going, the verdict reads `RUNNING`. If the run is interrupted, it reads `ABORTED`.

## Overrides (tests only)

`ci.sh` reads these variables for tests and special runs. Normal runs leave them unset.

| Variable | Default |
|---|---|
| `CI_REPO_ROOT` | the repo containing `ci.sh` |
| `CI_D_DIR` | `$CI_REPO_ROOT/harness/ci.d` |
| `CI_RUNS_DIR` | `$FLMOD_TESTRUNS` |
| `CI_QUARANTINE` | `$CI_REPO_ROOT/state/QUARANTINE.md` |
| `CI_PYTHON` | `python3`, used for the `public` stage |

`tests/py/test_check_public.py` uses them to run `ci.sh` against a temporary `ci.d` and a temporary run directory.

## The `public` stage and the git hooks

- `public` runs `python3 -I tools/check_public.py --tree <CI_REPO_ROOT>`.
  - The file list comes only from `git ls-files -co --exclude-standard`, and only `.claude/worktrees/` is skipped (CONVENTIONS §5).
  - Run `python3 -I tools/check_public.py --explain` to see the rules.
- Two gitignored local inputs make the check stricter on the build machine. Without them (a fresh clone, GitHub Actions) the checker warns and applies the generic rules:
  - the personal-literal blocklist `$FLMOD_LOCAL/public_blocklist.txt`;
  - the reference fingerprint index `$FLMOD_LOCAL/public_index/` (rule R7: copies of other mods, the decomp or HDE data). Rebuild it with `python3 -I tools/check_public.py --build-index` after the reference repos change; it takes about 20 s.
- The same checker backs the git hooks in `.githooks/`. The shared repo config holds the absolute path `core.hooksPath=/home/user/freelancer/carrier-mod/.githooks` (DECISIONS D101), so every worktree runs the main checkout's hooks and checker, even one branched before the hooks existed. A fresh clone uses `git config core.hooksPath .githooks`.

  | Hook | Runs |
  |---|---|
  | `pre-commit` | `--staged` |
  | `pre-merge-commit` | `--staged` (merge commits) |
  | `pre-push` | `--commits` over every commit being pushed: trees, author identity, commit and annotated-tag messages |

- Before merging a branch, vet its whole history too: `python3 -I tools/check_public.py --commits=main..wp/<ID>`. The first push vets everything reachable from `main`.
