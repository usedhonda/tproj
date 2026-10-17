#!/usr/bin/env bash
# Remote attach transport: per-host mosh opt-in, ssh default, quick-failure fallback.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/home/.config/tproj"
printf '#!/bin/sh\nexit 0\n' > "$tmp/bin/tproj-peer-ledger"
printf '#!/bin/sh\necho "SSH $*" >> "$LOG"\n' > "$tmp/bin/ssh"
printf '#!/bin/sh\necho "MOSH $*" >> "$LOG"\nexit "${MOSH_STATUS:-0}"\n' > "$tmp/bin/mosh"
chmod 755 "$tmp/bin/"*
mkdir -p "$tmp/home/bin"; cp "$tmp/bin/tproj-peer-ledger" "$tmp/home/bin/"
run() { : > "$tmp/log"; HOME="$tmp/home" LOG="$tmp/log" PATH="$tmp/bin:$PATH" \
  "$repo/bin/tproj-remote-client" attach "$1" /p/x cc </dev/null >/dev/null 2>&1 || true; }
fail() { echo "FAIL: $1"; cat "$tmp/log"; exit 1; }

run hostA
grep -q '^SSH ' "$tmp/log" && ! grep -q '^MOSH' "$tmp/log" || fail "no opt-in must use ssh"

echo "hostA mosh" > "$tmp/home/.config/tproj/remote-transport"
run hostA
grep -q '^MOSH .*hostA -- /bin/sh -c .*tproj-remote-host attach' "$tmp/log" || fail "opt-in host must use mosh"
! grep -q '^SSH ' "$tmp/log" || fail "successful mosh must not also run ssh"

run hostB
! grep -q '^MOSH' "$tmp/log" || fail "opt-in is per host"

MOSH_STATUS=1 run hostA
grep -q '^MOSH' "$tmp/log" && grep -q '^SSH .*hostA' "$tmp/log" || fail "quick mosh failure must fall back to ssh"
echo "remote client mosh transport: PASS (default ssh, per-host opt-in, fallback)"
