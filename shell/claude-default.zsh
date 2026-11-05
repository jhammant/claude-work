# claude-work, opt-in: for a while, make new interactive `claude` sessions run on
# the second account with ultracode on, so standing multi-agent workflows spend
# its quota instead of yours. Source this from ~/.zshrc.
#
#   ultra-default on [YYYY-MM-DD HH:MM]   default: until the second account's weekly reset
#   ultra-default off | status
#   claude-me ...                         your own account, plain, whatever the default
#   cu ...                                second account + ultracode, always
#
# It stands down by itself once the second account's week passes CLAUDE_ULTRA_MAX_PCT
# (default 80), read from quotamax's last reading, and when the date passes.
# Only interactive starts are redirected: `claude -p`, `claude --version`,
# subcommands (`claude mcp ...`) and `claude "a prompt"` run as usual, and scripts
# never see this function.

CLAUDE_ULTRA_STATE="${XDG_CONFIG_HOME:-$HOME/.config}/claude-work/ultra-default"
CLAUDE_ULTRA_READING="${XDG_STATE_HOME:-$HOME/.local/state}/quotamax/claude-work-ratelimit.json"
: "${CLAUDE_ULTRA_MAX_PCT:=80}"

# "<weekly %> <weekly reset epoch>" from quotamax's last reading, or nothing.
_claude_ultra_reading() {
  [ -f "$CLAUDE_ULTRA_READING" ] || return 1
  python3 -I -c '
import json, sys
w = (json.load(open(sys.argv[1])).get("info") or {}).get("unifiedWindows", {}).get("seven_day") or {}
print(round(w.get("utilization", 0) * 100), int(w.get("resetsAt") or 0))
' "$CLAUDE_ULTRA_READING" 2>/dev/null
}

# Prints "work" or "own" for the given claude arguments.
_claude_ultra_route() {
  local a
  for a in "$@"; do
    case "$a" in -p|--print|-v|--version|-h|--help) echo own; return ;; esac
  done
  if [ $# -gt 0 ] && [[ "$1" != -* ]]; then echo own; return; fi
  [ -f "$CLAUDE_ULTRA_STATE" ] || { echo own; return; }
  local until; until="$(<"$CLAUDE_ULTRA_STATE")"
  if [ -z "$until" ] || [ "$(date +%s)" -ge "$until" ]; then echo own; return; fi
  local reading pct
  reading="$(_claude_ultra_reading)"; pct="${reading%% *}"
  if [ -n "$pct" ] && [ "$pct" -ge "$CLAUDE_ULTRA_MAX_PCT" ]; then echo own; return; fi
  command -v claude-work >/dev/null 2>&1 && echo work || echo own
}

claude() {
  if [ "$(_claude_ultra_route "$@")" = work ]; then
    print -P "%F{magenta}claude: second account, ultracode on%f  (claude-me for your own; ultra-default off to stop)"
    claude-work --settings '{"ultracode": true}' "$@"
  else
    command claude "$@"
  fi
}

claude-me() { command claude "$@"; }
cu() { claude-work --settings '{"ultracode": true}' "$@"; }

ultra-default() {
  case "${1:-status}" in
    on)
      local until reading
      if [ -n "${2:-}" ]; then
        until="$(date -j -f '%Y-%m-%d %H:%M' "$2" +%s 2>/dev/null)" || { echo "ultra-default: date must look like 2026-11-09 15:00" >&2; return 2; }
      else
        reading="$(_claude_ultra_reading)"; until="${reading##* }"
        if [ -z "$until" ] || [ "$until" -le "$(date +%s)" ]; then
          echo "ultra-default: no reading of the second account yet; give a date: ultra-default on 'YYYY-MM-DD HH:MM'" >&2; return 2
        fi
      fi
      mkdir -p "${CLAUDE_ULTRA_STATE:h}" && print -r -- "$until" > "$CLAUDE_ULTRA_STATE"
      ultra-default status ;;
    off) rm -f "$CLAUDE_ULTRA_STATE"; echo "ultra-default: off. New sessions use your own account." ;;
    status)
      if [ -f "$CLAUDE_ULTRA_STATE" ] && [ "$(date +%s)" -lt "$(<"$CLAUDE_ULTRA_STATE")" ]; then
        local reading; reading="$(_claude_ultra_reading)"
        echo "ultra-default: on until $(date -r "$(<"$CLAUDE_ULTRA_STATE")" '+%a %d %b %H:%M'); second account week ${reading%% *}% used (stands down at ${CLAUDE_ULTRA_MAX_PCT}%); new sessions -> $(_claude_ultra_route)"
      else
        echo "ultra-default: off"
      fi ;;
    *) echo "usage: ultra-default on [YYYY-MM-DD HH:MM] | off | status" >&2; return 2 ;;
  esac
}
