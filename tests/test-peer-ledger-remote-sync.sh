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
if [[ "$*" == *'import --stdin'* ]]; then
  cat > "${TEST_LOG}.snapshot"
  [[ "${REJECT_IMPORT:-}" != 1 ]] || exit 1
fi
SSH
chmod +x "$HOME/bin/tproj-peer-ledger" "$tmp/fake-bin/ssh"

client="$repo/bin/tproj-remote-client"
"$client" sync mini
[[ "$(cat "${TEST_LOG}.snapshot")" == '{"revision":1}' ]]
[[ "$(sed -n '1p' "$TEST_LOG")" == refresh ]]
[[ "$(sed -n '2p' "$TEST_LOG")" == *'import --stdin'* ]]

: > "$TEST_LOG"
"$client" status mini /remote/project cc
[[ "$(wc -l < "$TEST_LOG")" -eq 1 ]]
[[ "$(cat "$TEST_LOG")" == *'tproj-remote-host status'* ]]

: > "$TEST_LOG"
"$client" register mini /remote/project --alias project
[[ "$(wc -l < "$TEST_LOG")" -eq 3 ]]
[[ "$(sed -n '3p' "$TEST_LOG")" == *'tproj-remote-host register'* ]]

: > "$TEST_LOG"
if REJECT_IMPORT=1 "$client" ensure mini /remote/project cc >/dev/null 2>&1; then
  echo 'ensure proceeded after rejected ledger import' >&2
  exit 1
fi
[[ "$(wc -l < "$TEST_LOG")" -eq 2 ]]
echo 'peer ledger remote sync: ok'
