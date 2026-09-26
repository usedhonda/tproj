#!/bin/bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/.config/tproj" "$tmp/bin"
cat >"$tmp/.config/tproj/msg-client.json" <<'JSON'
{"active":true,"host_id":"h1"}
JSON
cat >"$tmp/bin/tproj-msg-unified" <<'SH'
#!/bin/bash
printf 'unified:%s\n' "$*"
SH
chmod +x "$tmp/bin/tproj-msg-unified"
out=$(HOME="$tmp" "$root/tproj-msg" cdx hello)
[[ "$out" == "unified:cdx hello" ]]
touch "$tmp/.config/tproj/msg-maintenance"
if HOME="$tmp" "$root/tproj-msg" cdx hello >/dev/null 2>&1; then exit 1; fi
out=$(HOME="$tmp" "$root/tproj-msg" --read cdx)
[[ "$out" == "unified:--read cdx" ]]
if HOME="$tmp" "$root/tproj-msg" gate:direct x >/dev/null 2>&1; then exit 1; fi
if HOME="$tmp" "$root/tproj-msg" --flush >/dev/null 2>&1; then exit 1; fi
echo "unified CLI routing: ok"
