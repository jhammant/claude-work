#!/bin/zsh
# Tests for shell/claude-default.zsh: only the routing decision, no claude calls.
ROOT="${0:A:h:h}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export XDG_CONFIG_HOME="$T" XDG_STATE_HOME="$T"
mkdir -p "$T/quotamax"
source "$ROOT/shell/claude-default.zsh"
pass=0 fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; ((pass++)); else echo "FAIL $1: got [$2], want [$3]"; ((fail++)); fi; }
reading() { printf '{"at":0,"source":"probe","info":{"unifiedWindows":{"seven_day":{"utilization":%s,"resetsAt":%s}}}}' "$1" "$2" > "$T/quotamax/claude-work-ratelimit.json"; }
command -v claude-work >/dev/null 2>&1 || claude-work() { :; }   # the decision needs the wrapper on PATH or defined
future=$(( $(date +%s) + 86400 ))

check "off by default" "$(_claude_ultra_route)" own
reading 0.10 $future
ultra-default on >/dev/null
check "on: a bare claude goes to the second account" "$(_claude_ultra_route)" work
check "on: --resume goes too" "$(_claude_ultra_route --resume abc)" work
check "print mode stays on your own account" "$(_claude_ultra_route -p hi)" own
check "--version stays" "$(_claude_ultra_route --version)" own
check "subcommands stay" "$(_claude_ultra_route mcp list)" own
check "a prompt argument stays" "$(_claude_ultra_route 'fix the bug')" own
check "default end is the second account's weekly reset" "$(<"$T/claude-work/ultra-default")" "$future"
reading 0.85 $future
check "stands down once its week passes 80%" "$(_claude_ultra_route)" own
reading 0.10 $future
ultra-default on "2020-01-01 00:00" >/dev/null
check "an end date in the past stands down" "$(_claude_ultra_route)" own
ultra-default on >/dev/null; ultra-default off >/dev/null
check "off turns it off" "$(_claude_ultra_route)" own

echo; echo "$pass passed, $fail failed"; [ $fail -eq 0 ]
