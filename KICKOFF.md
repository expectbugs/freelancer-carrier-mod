# Starting the autonomous build

## Before you leave (about 2 minutes)

1. **Close Freelancer** if it's running. The build clones your play prefix and needs no wine process using it.
2. **Start the build:**

   ```bash
   ~/freelancer/carrier-mod/tools/start-build.sh
   ```

   This opens two tmux sessions:

   | Session | What runs there |
   |---|---|
   | `flbuild` | The orchestrator: Claude Code, Opus, xhigh effort, bypass permissions, Remote Control on |
   | `flwatch` | The watchdog. It relaunches or nudges the orchestrator if it dies or stalls. |

   Add `--no-remote-control` if you don't want phone access.
3. **Check that it took off:** `tmux attach -t flbuild`.
   - You should see Claude reading `CLAUDE.md` and the plan.
   - If Claude asks you to confirm bypass-permissions or Remote Control, answer it once.
   - Detach with `Ctrl-b d`. Closing the terminal is fine; tmux keeps running.

## While you're away

- **Phone:** push notifications arrive at the start, at each gate, on a degrade or blocker, and at completion. Remote Control shows the live session.
- **Progress:** `state/BUILD_STATE.md` (the ledger) and `state/gates/*.md`, locally or on GitHub (`expectbugs/freelancer-carrier-mod`) once P0-REPO has pushed.
- **Your desktop:** game windows will appear on `:0`. The screensaver is paused for the duration, and your settings are restored at the end.

## Stopping it

```bash
touch ~/freelancer/carrier-mod/STOP
```

The orchestrator stops its agents and game lanes, restores the display settings, marks the ledger `STOPPED` and exits. The watchdog exits too.

To resume later: `~/freelancer/carrier-mod/tools/start-build.sh`. It removes `STOP`, resets the ledger status line, replaces the idle orchestrator session and restarts the watchdog, then picks up from the ledger.

## When it's done

- Play with `~/freelancer/play-carrier.sh`. Your original `~/freelancer/play.sh` and its install are untouched.
- Read `docs/BUILD_REPORT.md` for:
  - what was built and what was degraded;
  - the test evidence;
  - the tunables;
  - how to uninstall.
- Read `docs/design/ESCALATION.md` for the faction-influence endgame design; edit it or comment on it and ask a session to apply your changes.

## Safety rails

- Wine commands from the build are wrapped by guards that refuse anything except the build's own prefixes. Your play prefix and `~/.wine` are off-limits.
- `sudo` is used only for package installs, and every use is logged in `state/DECISIONS.md`.
- The public repo carries no game files: a check runs on every commit.
