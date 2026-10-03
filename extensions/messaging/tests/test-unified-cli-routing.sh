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
out=$(HOME="$tmp" "$root/tproj-msg" --allow-relay why cdx hello)
[[ "$out" == "unified:--allow-relay why cdx hello" ]]
out=$(HOME="$tmp" "$root/tproj-msg" cdx gate:line)
[[ "$out" == "unified:cdx gate:line" ]]
out=$(HOME="$tmp" "$root/tproj-msg" cdx reply)
[[ "$out" == "unified:cdx reply" ]]
out=$(HOME="$tmp" "$root/tproj-msg" cdx --new-task)
[[ "$out" == "unified:cdx --new-task" ]]
for flag in --new-task --role-handoff; do
  rc=0
  out=$(HOME="$tmp" "$root/tproj-msg" "$flag" cdx x 2>&1) || rc=$?
  [[ $rc -eq 64 && "$out" == *'use tproj-task --help'* ]]
done
touch "$tmp/.config/tproj/msg-maintenance"
if HOME="$tmp" "$root/tproj-msg" cdx hello >/dev/null 2>&1; then exit 1; fi
out=$(HOME="$tmp" "$root/tproj-msg" --read cdx || true)
[[ "$out" != unified:* ]]
if HOME="$tmp" "$root/tproj-msg" gate:direct x >/dev/null 2>&1; then exit 1; fi
if HOME="$tmp" "$root/tproj-msg" --flush >/dev/null 2>&1; then exit 1; fi
if HOME="$tmp" "$root/tproj-msg" gate:tmux x >/dev/null 2>&1; then exit 1; fi
if HOME="$tmp" "$root/tproj-msg" --new-task cdx x >/dev/null 2>&1; then exit 1; fi
rm -f "$tmp/.config/tproj/msg-maintenance" "$tmp/.config/tproj/msg-client.json"
out=$(HOME="$tmp" "$root/tproj-msg" cdx after-enrollment)
[[ "$out" == "unified:cdx after-enrollment" ]]
printf '{malformed\n' >"$tmp/.config/tproj/msg-client.json"
out=$(HOME="$tmp" "$root/tproj-msg" cdx malformed-config)
[[ "$out" == "unified:cdx malformed-config" ]]
echo "unified CLI routing: ok"
