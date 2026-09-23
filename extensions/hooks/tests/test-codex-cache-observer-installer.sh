#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"; mkdir -p "$HOME/.codex"
hooks="$HOME/.codex/hooks.json"; config="$HOME/.codex/config.toml"; installed="$HOME/bin/tproj-codex-cache-observer"; response="$TMP/hooks-list.json"
printf '%s\n' '{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"keep-me"}]}]}}' > "$hooks"
printf '%s\n' 'model = "test"' > "$config"
cat > "$response" <<EOF
{"result":{"data":[{"hooks":[{"key":"observer-prompt","sourcePath":"$hooks","command":"$installed prompt","currentHash":"sha256:prompt001"},{"key":"observer-stop","sourcePath":"$hooks","command":"$installed stop","currentHash":"sha256:stop002"}]}]}}
EOF
python3 "$REPO/extensions/hooks/install-tproj-codex-cache-observer" --installed "$installed" --codex-hooks "$hooks" --codex-config "$config" --trust-response "$response" >/dev/null
grep -Fq keep-me "$hooks"; grep -Fq "$installed prompt" "$hooks"; grep -Fq "$installed stop" "$hooks"
grep -Fq 'trusted_hash = "sha256:prompt001"' "$config"; grep -Fq 'trusted_hash = "sha256:stop002"' "$config"
test "$(grep -Fc "$installed prompt" "$hooks")" -eq 1; test "$(grep -Fc "$installed stop" "$hooks")" -eq 1
python3 "$REPO/extensions/hooks/install-tproj-codex-cache-observer" --installed "$installed" --codex-hooks "$hooks" --codex-config "$config" --trust-response "$response" --check >/dev/null
before="$(shasum -a 256 "$hooks" "$config")"
python3 "$REPO/extensions/hooks/install-tproj-codex-cache-observer" --installed "$installed" --codex-hooks "$hooks" --codex-config "$config" --trust-response "$response" --dry-run >/dev/null
test "$before" = "$(shasum -a 256 "$hooks" "$config")"
bad="$TMP/bad.json"; printf '%s\n' '{"result":{"data":[]}}' > "$bad"; before="$(shasum -a 256 "$hooks")"
if python3 "$REPO/extensions/hooks/install-tproj-codex-cache-observer" --installed "$installed" --codex-hooks "$hooks" --codex-config "$config" --trust-response "$bad" >/dev/null 2>&1; then exit 1; fi
test "$before" = "$(shasum -a 256 "$hooks")"
duplicate="$TMP/duplicate.json"
printf '%s\n' "{\"result\":{\"data\":[{\"hooks\":[{\"key\":\"one\",\"sourcePath\":\"$hooks\",\"command\":\"$installed prompt\",\"currentHash\":\"sha256:one\"},{\"key\":\"two\",\"sourcePath\":\"$hooks\",\"command\":\"$installed prompt\",\"currentHash\":\"sha256:two\"}]}]}}" > "$duplicate"
before="$(shasum -a 256 "$hooks")"
if python3 "$REPO/extensions/hooks/install-tproj-codex-cache-observer" --installed "$installed" --codex-hooks "$hooks" --codex-config "$config" --trust-response "$duplicate" >/dev/null 2>&1; then exit 1; fi
test "$before" = "$(shasum -a 256 "$hooks")"
printf '%s\n' '{broken' > "$hooks"; before="$(shasum -a 256 "$hooks")"
if python3 "$REPO/extensions/hooks/install-tproj-codex-cache-observer" --installed "$installed" --codex-hooks "$hooks" --codex-config "$config" --trust-response "$response" >/dev/null 2>&1; then exit 1; fi
test "$before" = "$(shasum -a 256 "$hooks")"
echo "ok: narrow Codex observer installer"
