#!/bin/bash
# Tests for bin/claude-work. No network, no real token, no Claude calls.
# The Keychain round-trip uses a throwaway item and is skipped off macOS or
# when CLAUDE_WORK_SKIP_KEYCHAIN=1 (CI runners have no unlocked login keychain).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../bin/claude-work
source "$ROOT/bin/claude-work"
set +e

pass=0 fail=0
ok() { echo "ok   $1"; pass=$((pass + 1)); }
no() { echo "FAIL $1${2:+: $2}"; fail=$((fail + 1)); }
check() { if [ "$2" = "$3" ]; then ok "$1"; else no "$1" "got [$2], want [$3]"; fi; }

FAKE="sk-ant-oat01-$(printf 'AbCdEfGhIj%.0s' 1 2 3 4 5 6 7 8)_-xyz"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# The terminal UI wraps the token at its width and indents the continuation.
printf '\033[2K\033[1G Welcome\r\n \033[32m+\033[0m Long-lived authentication token created successfully!\r\n\r\n Your OAuth token (valid for 1 year):\r\n\r\n \033[1m%s\r\n %s\033[0m\r\n\r\n Store this token securely.\r\n' \
  "${FAKE:0:60}" "${FAKE:60}" > "$tmp/session.log"
check "token is read back from a wrapped, coloured session log" "$(extract_token "$tmp/session.log")" "$FAKE"
check "a missing session log yields nothing" "$(extract_token "$tmp/none.log")" ""

check "a paste split over two lines with leading spaces is joined" \
  "$(printf ' %s\n   %s\n\n' "${FAKE:0:40}" "${FAKE:40}" | read_pasted_token)" "$FAKE"
check "a paste that is not a token is rejected" "$(printf 'hunter2\n\n' | read_pasted_token)" ""
check "a truncated token is rejected" "$(printf '%s\n\n' "${FAKE:0:30}" | read_pasted_token)" ""

write_opener "$tmp/print" "" ""
check "default opener only prints the URL" \
  "$("$tmp/print" 'https://claude.ai/oauth/authorize?x=1' | tr -d '\n' | sed 's/  */ /g')" \
  " Sign-in URL (open it where the work account is signed in): https://claude.ai/oauth/authorize?x=1"
write_opener "$tmp/app" "Firefox" ""
check "app opener opens that app" "$(tail -1 "$tmp/app")" 'open -a Firefox "$1"'
write_opener "$tmp/chrome" "" "Profile 2"
check "chrome-profile opener targets that profile" "$(tail -1 "$tmp/chrome")" \
  'open -na "Google Chrome" --args --profile-directory=Profile\ 2 "$1"'

out="$(CLAUDE_WORK_KEYCHAIN=claude-work-test-missing bash "$ROOT/bin/claude-work" -p hi 2>&1)"; rc=$?
check "running with no stored token exits 1" "$rc" "1"
case "$out" in *"claude-work login"*) ok "and says how to fix it" ;; *) no "and says how to fix it" "$out" ;; esac

if command -v security >/dev/null 2>&1; then
  bash "$ROOT/bin/claude-work" login </dev/null >/dev/null 2>&1; rc=$?
  check "login refuses to run without a terminal" "$rc" "2"
fi

if [ "$(uname)" = Darwin ] && [ "${CLAUDE_WORK_SKIP_KEYCHAIN:-0}" != 1 ]; then
  SERVICE="claude-work-test-$$"
  store_token "$FAKE"
  check "token round-trips through the Keychain intact" "$(stored_token)" "$FAKE"
  security delete-generic-password -s "$SERVICE" >/dev/null 2>&1
  check "throwaway Keychain item removed" "$(stored_token || true)" ""
else
  echo "skip Keychain round-trip"
fi

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
