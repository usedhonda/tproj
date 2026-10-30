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
  "$repo/bin/tproj-remote-client" attach "$1" /p/x cc </dev/null >/dev/null 2>&1; }
fail() { echo "FAIL: $1"; cat "$tmp/log"; exit 1; }

run hostA
grep -q '^SSH ' "$tmp/log" && ! grep -q '^MOSH' "$tmp/log" || fail "no opt-in must use ssh"

echo "hostA mosh" > "$tmp/home/.config/tproj/remote-transport"
run hostA
grep -q '^MOSH .*hostA -- /bin/sh -c .*tproj-remote-host attach' "$tmp/log" || fail "opt-in host must use mosh"
grep -q '^MOSH .*--ssh=ssh -o ControlMaster=no -o ControlPath=none ' "$tmp/log" || fail "mosh bootstrap must not reuse a shared SSH master"
! grep -q '^SSH ' "$tmp/log" || fail "successful mosh must not also run ssh"

run hostB
grep -q '^SSH .*hostB' "$tmp/log" && ! grep -q '^MOSH' "$tmp/log" || fail "opt-in is per host and other hosts use ssh"

MOSH_STATUS=1 run hostA
grep -q '^MOSH' "$tmp/log" && grep -q '^SSH .*hostA' "$tmp/log" || fail "quick mosh failure must fall back to ssh"
: > "$tmp/log"
HOME="$tmp/home" LOG="$tmp/log" PATH="$tmp/bin:$PATH" \
  "$repo/bin/tproj-remote-client" shell hostA "/p/with space" </dev/null >/dev/null 2>&1
grep -q '^MOSH .*hostA -- /bin/sh -c cd ' "$tmp/log" || fail "shell must share mosh transport"
! grep -q 'tproj-remote-host' "$tmp/log" || fail "shell must not start an agent attachment"
: > "$tmp/log"
HOME="$tmp/home" LOG="$tmp/log" PATH="$tmp/bin:$PATH" MOSH_STATUS=1 \
  "$repo/bin/tproj-remote-client" shell hostA /p/x </dev/null >/dev/null 2>&1
grep -q '^SSH .*ServerAliveInterval=15.*ServerAliveCountMax=3.*ConnectTimeout=10.*cd /p/x' "$tmp/log" || fail "shell fallback must share relaxed ssh options"
# Model an already-running mosh dying, without a 30-second test sleep.
python3 - "$repo/bin/tproj-remote-client" "$tmp/long-client" <<'PYLONG'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
assert source.count('started = time.monotonic()') == 1
Path(sys.argv[2]).write_text(source.replace('started = time.monotonic()', 'started = time.monotonic() - 31'))
PYLONG
chmod +x "$tmp/long-client"
: > "$tmp/log"
HOME="$tmp/home" LOG="$tmp/log" PATH="$tmp/bin:$PATH" MOSH_STATUS=1 \
  "$tmp/long-client" attach hostA /p/x cdx </dev/null >/dev/null 2>&1
grep -q '^SSH .*ControlMaster=no.*ControlPath=none.*tproj-remote-host reattach' "$tmp/log" || fail "late mosh failure must recover only the existing session on independent SSH"
! grep -q '^SSH .*tproj-remote-host attach' "$tmp/log" || fail "late recovery must not repeat agent startup"
echo "remote client mosh transport: PASS (default ssh, per-host opt-in, fallback)"
