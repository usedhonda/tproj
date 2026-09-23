#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"; mkdir -p "$HOME/.claude" "$HOME/bin"
settings="$HOME/.claude/settings.json"
printf '%s\n' '{"keep":true,"statusLine":{"type":"command","command":"STATUSLINE_DISPLAY_MODE=full ~/.claude/statusline.py --show all"},"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"keep-hook"}]}]}}' > "$settings"
PYTHONDONTWRITEBYTECODE=1 python3 "$REPO/extensions/hooks/install-tproj-claude-cache-observer" --claude-settings "$settings" --wrap-statusline
grep -Fq keep-hook "$settings"; grep -Fq 'tproj-cc-cache-observer prompt' "$settings"; grep -Fq 'tproj-cc-cache-observer notification' "$settings"; grep -Fq 'tproj-cc-cache-observer stop' "$settings"
grep -Fq '$HOME/bin/tproj-cc-statusline-tap -- /bin/sh -c' "$settings"; grep -Fq 'STATUSLINE_DISPLAY_MODE=full ~/.claude/statusline.py --show all' "$settings"
before="$(shasum -a 256 "$settings")"; PYTHONDONTWRITEBYTECODE=1 python3 "$REPO/extensions/hooks/install-tproj-claude-cache-observer" --claude-settings "$settings" --wrap-statusline; test "$before" = "$(shasum -a 256 "$settings")"
PYTHONDONTWRITEBYTECODE=1 python3 "$REPO/extensions/hooks/install-tproj-claude-cache-observer" --claude-settings "$settings" --check --wrap-statusline
echo "ok: narrow Claude observer installer"
