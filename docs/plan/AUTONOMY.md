# Autonomy: authorization, decision policy, failure policy, resume protocol

Adam (repo owner, addressed as "Mr. Awesome") wrote these rules on 2026-10-17 for the unattended build. He will not be available during the build.

**This file is his standing go-ahead.** For this build, it overrides the global CLAUDE.md rules "Investigating ≠ permission", "When you ask me a question, WAIT", and "present findings and STOP". Every other global rule still applies: verify before executing, integrity, ten explanations, testing safety, and "Stop means stop" for a `STOP` file.

## 1. Pre-authorized actions (do them without asking)

- **Code and docs.** Create, modify and commit anything inside `/home/user/freelancer/carrier-mod` (except `local/research/`, which is read-only reference).
- **Prefixes.**
  - Create, modify and delete Wine prefixes named `/home/user/freelancer/prefix-dev*`, `prefix-lane*` and `prefix-carrier`.
  - They are made by `cp -a --reflink=always` from `/home/user/freelancer/prefix`, taken while no wine process is using that prefix.
- **Run the game** in those prefixes as often as needed, including several instances at once.
  - Use display `:0`, move and resize game windows, send synthetic input to game windows, and take screenshots.
- **Keep the display awake** for the duration of the build: disable the screensaver, screen lock and DPMS, using `tools/display-awake.sh start`. Save the previous settings and restore them at the end (`stop`) or when the STOP file appears.
- **Install software.**
  - User-space: `cargo install`, Python venvs and `pip` inside venvs, source builds under `~/opt`, `uv` if needed.
  - Accept the Microsoft license prompts these tools require for the MSVC CRT/STL and Windows SDK (`xwin --accept-license`, `vsdownload.py --accept-license`). Adam authorized building with them.
  - **`sudo` is granted.** Use it only for package installs (`emerge`) and for permissions on build paths. Log every sudo command in `state/DECISIONS.md`. Never use sudo to change services, users, networking, the bootloader or the kernel.
- **GitHub.**
  - Create the **public** repo `expectbugs/freelancer-carrier-mod`; set its description and topics.
  - Push `main` and tags, and create releases.
  - License: AGPL-3.0.
- **Notifications.** Send push notifications (`PushNotification` tool) at:
  - build start;
  - each gate pass;
  - each degrade or blocker;
  - completion.

  Keep them short. If the `PushNotification` tool is unavailable or fails, append the message to `state/NOTIFICATIONS.md` and continue. Never block on notifications.
- **Agents.** Spawn as many agents as useful: Opus 5.5 (`model: "opus"`), `effort: "xhigh"`.
- **Watchdog.** Start and keep running the tmux watchdog (`tools/watchdog.sh`).
- **Final install.** Create `/home/user/freelancer/play-carrier.sh` and the `prefix-carrier` install at the end.

## 2. Forbidden (no exceptions)

- **Protected paths.** Never modify `/home/user/freelancer/prefix` (Adam's play install), `/home/user/freelancer/play.sh`, `/home/user/freelancer/installers/`, or `~/.wine` (Battle.net).
  - Never run any wine binary without an explicit allowed `WINEPREFIX`: `source tools/env.sh` first, which installs guards that refuse otherwise.
- **Other projects.** Never touch Adam's other projects under `/home/user` (listed in `local/research/R6-copilot-sidecar.md` §1).
  - Reading them is allowed. Copying pure functions into `sidecar/` is allowed.
  - **Never import their modules**: some have side effects that reach Adam's devices.
  - Never write to their databases or crontabs.
- **Nothing private or copyrighted goes public.** Never commit or publish:
  - Freelancer or HDE game files, or extracts of them (INI copies, models, DLLs, textures, audio);
  - decompiled code;
  - other mods' content;
  - files from `local/`;
  - secrets or personal infrastructure details.

  `tools/check_public.py` and the pre-commit hook enforce this. Never bypass them.
- **Runtime network.**
  - The mod DLL talks only to `127.0.0.1`.
  - The sidecar talks only to `127.0.0.1`, except for the Claude Code CLI it launches. That CLI connects to Anthropic on Adam's subscription; this is the only outbound path, and it is allowed.
  - The brain runs with no tools, no MCP and no connectors (`--tools ""` `--strict-mcp-config`, empty cwd).
  - Build-time downloads (cargo, pip, git clone, Codeberg/GitHub releases) are allowed.
- **Git safety.** No force-push to `main`, no history rewriting on `main`, and no deleting the GitHub repo or releases.
- **Unrelated system changes.** No shell rc files, no global git config, no editing XFCE settings except through `display-awake.sh`, no cron.

## 3. Decision policy (when the plan doesn't answer something)

1. Look for the answer, in this order:
   1. `DESIGN.md`
   2. this plan and the package spec
   3. `state/ENGINE_FACTS.md`
   4. the research files
   5. the reference repos and the decompilation
2. If it's still open, choose by this priority:
   1. the design principles (DESIGN §1: vanilla-faithful, earned danger, never forced, no artificial restrictions);
   2. stability: never crash the game, never corrupt saves;
   3. Adam's experience: fun, readable, consistent with Freelancer;
   4. the simplest robust implementation;
   5. reversibility.
3. Record every non-trivial decision in `state/DECISIONS.md`: date, context, options, choice, why, and who decided (orchestrator or package).
4. **Never block waiting for Adam.** If a decision is genuinely his taste (e.g. a balance number), pick a sensible value, make it a config or YAML setting, and list it in `docs/BUILD_REPORT.md` under "Tunables for Adam".

## 4. Failure policy

Every package has an attempt budget:

- **Implement → review → fix loops:** up to 4 rounds with the same agent.
- **Fresh restart:** if the agent is stuck (no progress in 2 rounds, or repeated identical failures), restart the package with a fresh agent and a brief that includes the previous attempt's report and the reviewer's findings. Up to 2 fresh restarts.
- **Bugs:** apply the user's **ten-explanations rule**. List at least 10 distinct hypotheses before choosing an experiment, and record them in the package report.

When the budget is exhausted:

1. **Take the pre-decided fallback**, if one exists (BUILD_PLAN §8 or the package spec's "Fallbacks"), as a new attempt cycle.
2. **Otherwise degrade:**
   1. Ship the package behind a config flag that is off, or in its reduced form.
   2. Mark it `DEGRADED` in the ledger.
   3. Write `state/DEGRADED.md` (what's missing, why, evidence, what a future session needs).
   4. Send a push notification, and continue with dependents using the degraded contract.
3. **Halt the build only if** the game can't boot with the mod, or there is a risk to Adam's play install or saves. Then:
   1. Write `state/HALT.md`.
   2. Notify.
   3. Set the ledger to `BUILD_STATUS: HALTED`.
   4. Stop the watchdog.

**Test results are never faked or waived silently.** A skipped test is reported as skipped, with the reason.

## 5. Resume protocol (fresh session, compaction, or watchdog nudge)

0. **If `/home/user/freelancer/carrier-mod/STOP` exists, stop:**
   1. Message running agents to stop.
   2. Kill lane wine processes (scoped `wineserver -k` per lane).
   3. Run `tools/display-awake.sh stop`.
   4. Set the ledger's first line to `BUILD_STATUS: STOPPED`.
   5. Commit, notify, and end. Check for `STOP` at the start of every turn.
1. Re-read `CLAUDE.md`, `BUILD_PLAN.md`, `CONVENTIONS.md`, this file and `state/BUILD_STATE.md`.
   - Run `date -Is > /home/user/freelancer/carrier-mod/local/heartbeat`.
   - Run `tools/display-awake.sh start` (idempotent).
   - Check that `type -P wine` resolves to `tools/bin/wine`. If not, `source tools/env.sh` in every Bash call.
2. Reconcile running agents:
   - The ledger lists agent ids. If you can't reach them (new session), treat their packages as interrupted.
   - Check the package branch for commits. Re-brief a fresh agent with the branch as a starting point ("continue from branch `wp/<ID>` at `<sha>`; read its NOTES.md first").
3. Check the lanes: kill stale wine processes in lane prefixes (`WINEPREFIX=<lane> wineserver -k`), and release stale `flock` locks.
4. Continue with the "Next actions" in the ledger.
5. Keep the ledger accurate after every state change, and commit it at least once per merge or gate.

## 6. Usage limits and outages

- **If an agent fails because of a usage limit or API error:**
  1. Note it in the ledger.
  2. Wait (`sleep 900` in the background, then retry), with exponential backoff up to 60 minutes.
  3. Do not mark the package failed for that reason.
- **If the orchestrator itself is limited,** the turn ends. The watchdog nudges the tmux session after about 75 minutes of stale heartbeat, or relaunches it if it died.
- **Concurrency:** at most 6 implementation agents + 3 reviewers + the lane count of game instances. If limits are hit repeatedly, reduce parallelism to 3 and log a decision.

## 7. Communication

- Adam may check in through Remote Control or tmux (`tmux attach -t flbuild`).
  - If he sends a message, it overrides this file.
  - If he writes "stop", stop everything (agents, lanes, watchdog) and confirm.
- **Push notifications** (one or two lines each):
  - build started;
  - gate X passed (with one key number);
  - package X degraded (why);
  - HALTED (why);
  - COMPLETE (with the link to `docs/BUILD_REPORT.md` on GitHub).
