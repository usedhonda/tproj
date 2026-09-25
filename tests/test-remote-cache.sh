#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/state" "$tmp/cc"
cat > "$tmp/bin/tproj-remote-host" <<'EOF'
#!/bin/sh
printf 'id|alias|path|cc|cdx\n0123456789abcdef|sample|/tmp/sample|running|running\n'
EOF
cat > "$tmp/bin/tmux" <<'EOF'
#!/bin/sh
printf '%%1|0|claude-p1|/tmp/sample|tproj-remote-cc-test\n%%2|0|codex-p1|/tmp/sample|tproj-remote-cdx-test\n'
EOF
cat > "$tmp/bin/tproj-codex-cache-state" <<'EOF'
#!/bin/sh
printf '{"%%2":{"turn":"idle","quiet_seconds":1800}}\n'
EOF
cat > "$tmp/bin/tproj-cc-poke" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >> "$tmp/pokes"
EOF
chmod +x "$tmp/bin/"*
now=$(date +%s)
printf '{"pane_id":"%%1","session_id":"session-1","cache_expires_at":%s,"last_user_prompt_at":%s}\n' "$((now + 50))" "$((now - 100))" > "$tmp/cc/record.json"
export PATH="$tmp/bin:$PATH" TPROJ_REMOTE_STATE_DIR="$tmp/state" TPROJ_CC_CACHE_DIR="$tmp/cc"
"$repo/bin/tproj-remote-cache" set --path /tmp/sample --role cc --hours 3 >/dev/null
"$repo/bin/tproj-remote-cache" set --path /tmp/sample --role cdx --hours 12 >/dev/null
"$repo/bin/tproj-remote-cache" tick > "$tmp/result.json"
python3 - "$tmp/result.json" <<'PY'
import json, sys
cc, cdx = json.load(open(sys.argv[1]))
assert cc["poke_result"] == "sent" and cc["hours"] == 3
assert cdx["auto_poke"] == "disabled-unproven-composer-and-turn" and cdx["hours"] == 12
assert "poke_result" not in cdx
PY
test "$(wc -l < "$tmp/pokes" | tr -d ' ')" = 1
"$repo/bin/tproj-remote-cache" set --path /tmp/sample --role cc --hours 0 >/dev/null
"$repo/bin/tproj-remote-cache" tick >/dev/null
test "$(wc -l < "$tmp/pokes" | tr -d ' ')" = 1
echo 'ok: remote cache bounded CC tick and Cdx diagnostic-only'
