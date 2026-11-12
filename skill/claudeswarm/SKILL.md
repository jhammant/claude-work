---
name: claudeswarm
description: >-
  Delegate coding or research tasks to your other Claude accounts (the Claude swarm) so they
  spend those accounts' quota instead of this one, then verify the result. Use for
  "/claudeswarm", "/cs", "send this to my other Claude account", "run it on the work account",
  "fan this out across my Claude accounts", or when this account's quota is tight. Runs one
  task or many in parallel, picks the account with the most room, and continues on Opus if
  Fable's own cap is hit.
---

# /claudeswarm: hand tasks to your other Claude accounts

`claude-swarm` runs each task as one headless `claude --print` on another Claude
subscription. The token reaches that one process only, so this session and every other
open one stay on your own account. Today the swarm is one account (`work`, the
`claude-work` login); adding more is one command plus a sign-in (section 7).

Workers share `~/.claude`, so they load the same CLAUDE.md, skills and settings. They
start with **no MCP servers**, no claude.ai connectors and no Claude in Chrome. Keep
anything that needs those, or needs this conversation, here.

## 0. Look at the swarm

```bash
claude-swarm accounts            # each account: weekly %, cap, agents running/allowed, models
claude-swarm accounts --probe    # fresh reading (one tiny Haiku turn per account)
```

Probe when the reading is over an hour old. If no account has room, say so and keep the
work here, or offer to wait.

## 1. Model and number of agents

| What | Where it's set | Default |
|---|---|---|
| Model for one task | `--model fable\|opus\|sonnet` or a full id (`claude-...`) | `fable` (Fable 5.2) |
| What an alias means | `claude-swarm model fable claude-fable-5-3` | fable 5.2, opus 5.5, sonnet 5.5 |
| If Fable's own cap is hit | `fallback_model` in the config | `opus`, same session continues |
| Tasks at once in a fan-out | `--agents N` | every free agent |
| Agents per account | `max_agents` per account | 3 |
| Stop using an account at | `max_pct` per account (weekly %) | 85 |
| Models an account may run | `models` per account | all aliases |
| Thinking effort | `--effort low\|medium\|high\|xhigh\|max` | the CLI default |

The config is `~/.config/claude-swarm/accounts.json`. Per-account values beat the top-level
defaults. Pick by the task, not by habit:

- **fable** for features, multi-file changes, debugging and anything hard. It costs about
  2.5× Opus per token and has its own weekly cap, so the runner moves to Opus when that
  cap is reached.
- **opus** for contained modules and refactors, or when Fable is cooling.
- **sonnet** for mechanical work: tests for existing code, renames, summaries.
- `--effort high` for real features; `xhigh` for hard debugging; leave it unset for small jobs.

## 2. Brief it: workers have none of this conversation

Write each brief to a file. Give more than feels necessary:

```markdown
# Goal         what should be true when you're done, and why
# Context      verified facts from this conversation (label them VERIFIED); what not to assume
# Build        numbered deliverables
# Constraints  repo rules that matter (read AGENTS.md / CLAUDE.md); no commits, merges or pushes;
#              no new dependencies unless named; no rm -rf or glob deletes
# Done when    exact test commands and expected results
# Final message  files changed, decisions, assumptions, test commands with counts,
#                anything you could NOT verify
Work end to end without asking questions; make reasonable assumptions and list them.
```

One task per brief. Split unrelated asks into separate briefs and fan them out.

## 3. Safety: a worktree for anything that changes files

Use `--worktree` for every file-changing task. The task gets its own checkout beside the
repo (`<repo>--cs-<slug>`) on branch `cs/<slug>`, so your working tree and main are never
touched and parallel tasks can't collide. A pure question runs without it.

## 4. Dispatch

Run it with the Bash tool's `run_in_background` and a long timeout. Don't poll; you are
told when it exits. The runner kills a task that hasn't started a turn in 5 minutes
(exit 3) or whose log stops growing for 30 minutes (exit 4).

```bash
# one task
claude-swarm run --dir <repo> --slug <slug> --prompt <brief.md> --worktree [--model fable] [--effort high]

# several at once: one brief per file, the file name is the slug
claude-swarm fan --dir <repo> --worktree --agents 3 [--model opus] briefs/*.md
```

Output for each task lands in `~/.local/state/claude-swarm/runs/`: `<slug>.txt` (the
final message), `<slug>.jsonl` (the full stream) and `<slug>.meta.json` (account, model,
session, exit code, seconds, API-equivalent cost). `claude-swarm status` shows what's
running and the last ten tasks.

| Exit | Meaning |
|---|---|
| 0 | Done |
| 1 | The agent finished with an error; read `<slug>.txt` |
| 2 | Bad input, or the account has no token |
| 3 / 4 | No turn started / log stopped growing; read `<slug>.jsonl` |
| 5 | No final message |
| 6 | No account has room for that model; the message says why for each |

## 5. Verify and fix: don't take its word for it

1. Read `<slug>.txt`, especially its assumptions and what it couldn't verify.
2. Run the project's full tests yourself in the worktree, plus anything it couldn't run.
3. If something fails, send a fix pass to the same session on the same account:
   ```bash
   printf 'These still fail:\n%s\nFix them and re-run the tests.\n' "<output>" > fix.md
   claude-swarm resume <slug> --prompt fix.md
   ```
   At most two fix passes; then stop and report the failures.
4. Green tests are necessary, not sufficient: check the real deliverable against the intent
   (words people see, defaults, privacy).
5. Record the outcome so the router learns:
   `route outcome --shape <shape> --tier <tier> --arm claude-work --fix-passes <N>`
   (or `--abandoned` if you had to rewrite it).

## 6. Report: never commit or merge on your own

Show `git -C <worktree> diff --stat` and the test result per task, with the branch name
(`cs/<slug>`). The user decides to merge, tweak or drop it. To clean up afterwards:
`git worktree remove <worktree>` (only once its branch is merged or the user drops it).

## 7. Adding accounts to the swarm

```bash
claude-swarm add client-x --max-agents 3 --models fable,opus   # registers it
CLAUDE_WORK_KEYCHAIN=claude-swarm-client-x claude-work login  # the user runs this in a normal terminal
claude-swarm accounts --probe                                   # check it answers
```

Sign-in needs a real terminal and the account's own browser login, so it is always the
user's step. Tasks then spread across every account with room, least loaded first.
`claude-swarm remove NAME` takes one out (its token stays in the Keychain).

Pinning work to one account: `--account NAME` on `run`, `fan` or `pick`.
