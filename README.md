# claude-work

Run Claude Code on a **second Claude subscription, one process at a time**,
without touching your main login.

Got a work seat as well as your own plan? `claude-work` lets headless workers
(subagents, swarm members, overnight jobs) spend the second account's quota
while every session you already have open stays on yours.

```bash
claude-work login                     # mint a token for the second account; stored in the macOS Keychain
claude-work status                    # live usage for both accounts, side by side
claude-work -p "write tests for src/parse.py" --permission-mode auto   # any claude flags work
claude-work                           # or an interactive session on the second account
```

## Why not an account switcher?

Account switchers such as [claude-swap](https://github.com/realiti4/claude-swap)
change Claude Code's **global** login. That suits one person moving between
accounts, but on macOS a running session picks up the switch within about 30
seconds, so your own session moves too. `claude-work` hands the second
account's token to one `claude` process through `CLAUDE_CODE_OAUTH_TOKEN` and
changes nothing else.

Everything else is shared: the same `~/.claude` (settings, skills, MCP config,
CLAUDE.md, transcripts). That is what lets a worker on the second account fork
a session you started on the first:

```bash
claude-work -p "now implement what we agreed" --resume "$CLAUDE_CODE_SESSION_ID" --fork-session
```

## Install

macOS, with Claude Code and Python 3 on your PATH.

```bash
git clone https://github.com/jhammant/claude-work.git
ln -s "$PWD/claude-work/bin/claude-work" ~/.local/bin/claude-work
```

## Signing in without signing out

`claude-work login` runs `claude setup-token`, which mints a one-year token for
whichever claude.ai account approves it. To keep your main browser out of it:

- By default **no browser opens**. The sign-in URL is printed; open it in an
  incognito window or a browser profile where the second account is signed in,
  and check the consent page names that account before approving.
- Or send it straight there: `claude-work login --chrome-profile "Profile 2"`
  (the folder name from `chrome://version`), or `--browser Firefox`.

The login runs in a throwaway `CLAUDE_CONFIG_DIR`. Claude Code names its
Keychain item after the config directory (`Claude Code-credentials-<hash>`),
so the login cannot overwrite your main credentials. `claude-work` also checks
the main item before and after, and warns if it changed.

The token is captured from the session (recorded with `script` in an
owner-only temp directory, then deleted), because the terminal UI wraps it and
indents the wrap, which breaks copy-paste. If that fails, it asks you to paste
and copes with line breaks. Either way it reaches the Keychain through
`security -i` on stdin, never on a command line.

More than one extra account? Name a different Keychain item per account:
`CLAUDE_WORK_KEYCHAIN=claude-client-x claude-work login`.

## Seeing its quota

A `setup-token` token carries the `user:inference` scope only, so the
`/api/oauth/usage` endpoint behind `/usage` refuses it. What it can see is the
unified rate-limit state Claude Code reports in its stream-json output:

```json
{"type":"rate_limit_event","rate_limit_info":{"status":"allowed",
 "unifiedWindows":{"seven_day":{"utilization":0.27,"resetsAt":1794297600}}}}
```

`claude-work status` reads it from a one-turn Haiku probe (no tools, MCP
servers, settings or saved session; about 500 input tokens) for each account.
[quotamax](https://github.com/jhammant/quotamax) does the same in the
background and shows the second account as the `claude-work` pool, and
[route-skill](https://github.com/jhammant/route-skill) uses that to send
delegated work to whichever account has quota to spare.

## Things that differ on the second account

- **Claude in Chrome is off** in these sessions: it needs a token with the
  profile scope, and env-var and setup-token sessions are inference-only.
- **`--bare` won't work**: bare mode ignores OAuth entirely.
- Hooks, skills and MCP servers from your settings all run, because the config
  is shared. For lean headless workers, pass
  `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`. `--mcp-config` takes
  several values, so put another option after it, never the prompt.
- The prompt cache is per account and per model, so forking a long session
  onto the second account bills every token uncached on its first turn.

## Make it the default for a while

`shell/claude-default.zsh` (opt-in; source it from `~/.zshrc`) sends new
interactive `claude` sessions to the second account **with ultracode on**, so
standing multi-agent workflows spend its quota instead of yours:

```bash
ultra-default on                      # until the second account's weekly reset
ultra-default on "2026-11-09 15:00"   # or until a date
ultra-default status | off
claude-me                             # your own account, whatever the default
cu                                    # second account + ultracode, always
```

It stands down by itself when the date passes or the second account's week
passes `CLAUDE_ULTRA_MAX_PCT` (default 80%, from quotamax's last reading). Only
interactive starts are redirected: `claude -p`, subcommands and
`claude "a prompt"` run as usual, and scripts never see the function. Sessions
on the second account have no claude.ai connectors (Gmail, Calendar, Drive...)
and no Claude in Chrome; use `claude-me` for those.

## Commands

| Command | Does |
|---|---|
| `claude-work login [--browser APP \| --chrome-profile DIR]` | mint and store a token (needs a real terminal) |
| `claude-work status` | usage for both accounts |
| `claude-work logout` | delete the stored token |
| `claude-work <claude args>` | run `claude` on the second account |

## Tests

```bash
bash test/test.sh
zsh test/test-default.zsh
```

No network and no real token. The Keychain round-trip uses a throwaway item.

## License

MIT
