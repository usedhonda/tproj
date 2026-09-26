#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home" PATH="$tmp/fake-bin:$PATH" TEST_LOG="$tmp/calls"
mkdir -p "$HOME/bin" "$tmp/fake-bin"

cat > "$HOME/bin/tproj-peer-ledger" <<'LEDGER'
#!/usr/bin/env bash
printf 'refresh\n' >> "$TEST_LOG"
printf '{"revision":1}\n'
LEDGER
cat > "$tmp/fake-bin/ssh" <<'SSH'
#!/usr/bin/env bash
printf 'ssh %s\n' "$*" >> "$TEST_LOG"
SSH
chmod +x "$HOME/bin/tproj-peer-ledger" "$tmp/fake-bin/ssh"

client="$repo/bin/tproj-remote-client"
"$client" sync mini
[[ "$(cat "$TEST_LOG")" == refresh ]]

: > "$TEST_LOG"
"$client" status mini /remote/project cc
[[ "$(wc -l < "$TEST_LOG")" -eq 1 ]]
[[ "$(cat "$TEST_LOG")" == *'tproj-remote-host status'* ]]

: > "$TEST_LOG"
"$client" identity mini /remote/project cc
[[ "$(wc -l < "$TEST_LOG")" -eq 1 ]]
[[ "$(cat "$TEST_LOG")" == *'tproj-remote-host identity --path /remote/project --role cc'* ]]

: > "$TEST_LOG"
"$client" register mini /remote/project --alias project
[[ "$(wc -l < "$TEST_LOG")" -eq 2 ]]
[[ "$(sed -n '2p' "$TEST_LOG")" == *'tproj-remote-host register'* ]]

: > "$TEST_LOG"
"$client" ensure mini /remote/project cc >/dev/null
[[ "$(wc -l < "$TEST_LOG")" -eq 2 ]]
[[ "$(sed -n '2p' "$TEST_LOG")" == *'tproj-remote-host ensure'* ]]
echo 'peer ledger master check: ok'
