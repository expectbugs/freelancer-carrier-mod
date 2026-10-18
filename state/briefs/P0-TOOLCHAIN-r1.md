# Review brief: P0-TOOLCHAIN MSVC-ABI cross toolchain, vendor pins, host test build, import checker (round 1)

You are an independent reviewer in an autonomous build. Be adversarial: your job is to find what is wrong, missing, untested or risky before it reaches `main`.

**You do not fix code.** You report findings; the author fixes them.

## Inputs

- **Package spec:** `docs/plan/packages/P0-TOOLCHAIN.md`
- **Brief:** `state/briefs/P0-TOOLCHAIN.md`
- **Author's report:** pasted below (also `state/reports/P0-TOOLCHAIN-a1.md`).
- **Branch:** `wp/P0-TOOLCHAIN` @ `9d320f3`. Review with `git -C /home/user/freelancer/carrier-mod diff main...wp/P0-TOOLCHAIN`. To build or run, check it out in your own worktree.
- **Standards:**
  - `CLAUDE.md` guardrails
  - `docs/plan/DESIGN.md`
  - `docs/plan/TESTING.md`
  - `state/ENGINE_FACTS.md`
  - research pitfalls: `local/research/R4-lore-and-testloop.md` §A1, and `R2` §0 item 15

## Do all of these

1. **Requirements.** For every `REQ-P0-TOOLCHAIN-n`, find the code and the test that cover it. Mark each one covered, partial or missing.
2. **Tests.** Re-run the host tests and at least the package's primary in-game scenario yourself, on your own lane. Compare with the author's evidence. Flag any claim you can't reproduce.
3. **Engine-safety audit:**
   - main-thread-only game calls;
   - deferral of spawn, destroy and relocate inside callbacks;
   - validated spawns;
   - `st6` at the Common.dll boundary;
   - no blocking I/O on the game thread;
   - save/load and SP⇄MP lifecycle resets;
   - null and dead-object checks after every engine lookup.
4. **Contract conformance.** It doesn't modify frozen contracts. Events are used as specified.
5. **Data hygiene and public safety.** Run `tools/check_public.py`. No game files or extracts are committed. Nicknames are unique (hash scan).
6. **Design fidelity.** Does the behavior match DESIGN.md's words, especially "never forced", "earned danger" and "no artificial restrictions"?
7. **Failure paths:**
   - sidecar absent;
   - corrupt or missing JSON;
   - pre-mod saves;
   - player dies mid-operation;
   - F1 pause;
   - alt-tab.

## Verdict (your last message)

```
REVIEW: P0-TOOLCHAIN ROUND 1   VERDICT: PASS | CHANGES_REQUIRED
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the primary scenario reproduced.

## Orchestrator notes for this review

- `source /home/user/freelancer/carrier-mod/tools/env.sh` first. Use `$FLMOD_VENV/bin/python -I` for Python.
- The branch is checked out in the author's worktree, so inspect it detached in yours: `git fetch` is not needed (same repo); run `git checkout --detach wp/P0-TOOLCHAIN` (or `git worktree add --detach <tmpdir> wp/P0-TOOLCHAIN`).
- Run the public-safety checker on the branch's commits: `python3 -I tools/check_public.py --commits=main..wp/P0-TOOLCHAIN` (from a checkout that has it) and `--tree` on the branch checkout.
- You never edit the branch, `main`, `state/` or the main checkout. Write any scratch output under `$FLMOD_TESTRUNS/<UTC stamp>-review-P0-TOOLCHAIN-r1/`.
- Game runs only through the harness on a locked lane, if the harness exists on the branch or main; otherwise state that in REPRODUCED.
- Package-specific: rebuild from an empty build dir in your own worktree (host preset, host-asan, win32-trackA, win32-trackB), re-run ctest and `toolchain/check_imports.py` yourself. Re-run the runtime load proof (`toolchain/load_proof.sh` or the spec's manual steps) with your **own** throwaway clone named `prefix-dev-review-toolchain`; kill only that prefix's wineserver and delete the clone after.
- Check the pinning claims: every vendored input has a URL + SHA-256 in `toolchain/PINS.md`, `fetch_vendor.sh --verify` and `setup_xwin.sh --verify` pass, and re-running fetch is idempotent (no network writes into `$FLMOD_VENDOR` if already present). `$FLMOD_VENDOR` is shared by every worktree: do not delete or rewrite it; verify only.
- Judge decision 1 (CRT 14.51 / SDK 10.0.28000 from VS 2026 manifest) for Wine-compat risk: does the newer STL import any msvcp140/vcruntime140 symbol that Wine-proton 11's builtins lack? check_imports must prove it for both hello DLLs.
- Check that the root CMake glob discovery (decision 8) works for future `src/game/**`, `src/logic/**`, `tests/host/<area>/` and `spikes/*/` without editing the root CMakeLists (CONVENTIONS §14, BUILD_PLAN §6 ownership conventions).
- Licensing: FLSDK, FLUF (AGPL), MinHook, ImGui, doctest, nlohmann, magic_enum, reflect-cpp — note any license that would block AGPL distribution of source or a future binary release (CONVENTIONS §11).

## Author's report

```
PACKAGE: P0-TOOLCHAIN   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-TOOLCHAIN @ 9d320f39785c245604b6190da8210601460be359
SUMMARY: The clang-cl 22 i686 MSVC-ABI cross build works for both tracks. The native host build and tests work. Vendor inputs are pinned and reproducible, and the import checker is in place. hello_b.dll loads under Wine and calls Common.dll's CreateID: 2745692751. hello_a.dll builds as a FLUF module, and all 189 of its FLUF.dll imports resolve against the shipped FLUF.dll. Everything was rebuilt from an empty build/ and re-verified.
FILES: CMakeLists.txt, CMakePresets.json, cmake/{FlmodVendor,FlmodFunctions,LogicIncludeLint}.cmake,
  toolchain/{clang-cl-i686.cmake, clang-cl-i686-overrides.cmake, host.cmake, fetch_vendor.sh, setup_xwin.sh,
  check_imports.py, load_proof.sh, README.md, PINS.md, ABI.md, NOTES.md, tests/test_check_imports.py},
  src/logic/core/flhash.{hpp,cpp}, src/module/{hello_a,hello_b,loadtest}/, tests/host/{main.cpp,
  LogicHeaderCheck.cmake, core/test_flhash.cpp, negative/}, harness/ci.d/{10-build,20-host-tests,50-import-check}.sh
TESTS (run dir R = $FLMOD_TESTRUNS/20261018T045010Z-toolchain-acceptance/):
  host configure/build/ctest — PASS (5/5: host_tests 4 cases/12 asserts including the 5 golden CreateIDs,
    logic_headers_standalone, 2 negative probes, lint) — R/03-host-ctest.log, R/16-host-tests-verbose.log
  host-asan (ASan+UBSan) — PASS — R/04-hostasan.log
  win32-trackB build: hello_b.dll and loadtest.exe are Machine IMAGE_FILE_MACHINE_I386, PE32 — PASS — R/07-trackB-fileheaders.log
  check_imports hello_b + loadtest --prefix play prefix — PASS — R/08-trackB-imports.{log,json}
  win32-trackA build: hello_a exports GetMajorVersion, GetMinorVersion, ModuleFactory — PASS — R/11-trackA-exports.log
  check_imports hello_a --allow-fluf — PASS (FLUF.dll 189/189, MSVCP140 15/15, VCRUNTIME140 10/10) — R/12-trackA-imports.log
  runtime load proof — PASS: "hello_b CreateID(li02)=2745692751"; clone deleted — $FLMOD_TESTRUNS/20261018T045050Z-toolchain-loadproof/
  negative test (windows.h in src/logic) — PASS: host and win32 builds fail, then pass after removal — $FLMOD_TESTRUNS/20261018T044315Z-toolchain-negative-windows-h/
  pytest toolchain/tests — PASS 13/13 — R/13-pytest.log
  CI drop-ins (full mode) — PASS, and the SKIP paths exit 77 — $FLMOD_TESTRUNS/20261018T0445Z-toolchain-ci/
  fetch_vendor --verify, setup_xwin --verify — PASS — R/14,15-*.log
  hello_a load outside the game — SKIP (not required). FLUF.dll's DllMain builds the framework and the process exits with code 5. The in-game load is P0-TRACK-A's job.
DECISIONS:
  1. CRT 14.51.36231 and SDK 10.0.28000 (xwin --manifest-version 18, VS 2026 18.11), not xwin's default 14.44. FLUF's prebuilt libs carry /FAILIFMISMATCH:"annotate_optional=0", which only the 14.5x STL emits (VERIFIED by grepping both header sets). The channel manifest is pinned in /home/user/opt/xwin-cache-18/pinned/.
  2. GitHub inputs are fetched as commit archive tarballs with sha256 pins, cached under vendor/.cache/dl. FLSDK comes from `git archive` of the refs clone (HEAD = ae8c857, VERIFIED).
  3. ImGui is v1.92.9b-docking. v1.93.0 came out 3 days ago and was skipped. doctest v2.5.3, MinHook v1.3.4, nlohmann 3.11.3, magic_enum v0.9.8, reflect-cpp 6bba1e2.
  4. Added LIBUUID_CPP20_OR_GREATER to FLUF's must-match defines. Without it, FLUF's Utils/Random.hpp pulls <uuid.h>, which wants <gsl/span>.
  5. Track B ImGui is built with IMGUI_DISABLE_WIN32_DEFAULT_IME_FUNCTIONS, which avoids an imm32.dll import (not on the allowlist).
  6. Both tracks share one Win32 define set.
  7. check_imports goes beyond the spec. It also checks delay imports and the i386 machine type, checks api-ms-win-crt-* symbols against ucrtbase.dll, Common.dll/Server.dll imports against the game's own DLLs, and FLUF imports against the pinned FLUF.dll.
  8. The root CMake finds src/module/*/, spikes/*/ and harness/devbridge/ by glob. Each directory guards itself with flmod_track_only/win32_only/host_only.
  9. hello_b builds in trackB only, hello_a in trackA only, loadtest in both. CI stage 10 builds both tracks while FLMOD_TRACK is unset.
  10. flmod::flsdk_static (FLSDK's own sources) is built for Track B. VERIFIED: a temporary MinHook + ImGui dx9/win32 + FLSDK DLL linked and passed check_imports, then was removed.
  11. Vendor trees are read-only after extraction. DLLs keep DWARF.
  sudo commands: none.
ENGINE FACTS LEARNED:
  - Common.dll CreateID("li02") = 2745692751 when called from our clang-cl DLL under wine-proton 11 (VERIFIED, load-proof run dir).
  - Wine-proton 11 drops a console app's stdout when it is redirected to a regular file. Pipes, ptys and cmd-side redirects work, and exit codes propagate (VERIFIED, $FLMOD_TESTRUNS/20261018T043847Z-toolchain-console-exp/). The harness should pipe wine console output, not redirect it.
  - Wine's apisetschema maps api-ms-win-crt-* to ucrtbase.dll (VERIFIED from the strings in apisetschema.dll).
  - clang-cl 22 with STL 14.51 mangles FLUF's API the same way FLUF.dll does: 189/189 imports resolve (VERIFIED, static check).
OPEN QUESTIONS / BLOCKERS: none blocking.
  - The CI drop-ins follow the P0-REPO spec protocol (CI_MODE/CI_LANES/CI_RUNDIR, exit 77 for SKIP). Reconcile with their README at merge.
  - Stage 50 reads syswow64 from the play prefix, read-only (FLMOD_IMPORT_CHECK_PREFIX overrides it). Change the default to a lane baseline if preferred.
  - P0-REPO's in-progress check_public.py (worktree agent-af7c7d7da0b0d74b7) passes on this tree: 134 files clean.
KNOWN ISSUES:
  - hello_a has not been tested at runtime. That needs the game (P0-TRACK-A).
  - DWARF makes DLLs larger (hello_a is 1.6 MB). No stripped variant yet.
  - System-DLL imports are checked against the allowlist only, not symbol by symbol.
  - Disk use: /home/user/opt/xwin is 629M, xwin-cache-18 is 1.6G, vendor/ is 1.8G.
```

