#!/bin/bash
set -u

REPO="$(cd "$(dirname "$0")/../../.." && pwd -P)"
INSTALLER="$REPO/extensions/messaging/install-tproj-messaging-runtime"
TMP="$(mktemp -d)"
trap 'find "$TMP" -depth -delete 2>/dev/null || true' EXIT

PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$1"; }
check() {
  local label="$1"
  shift
  if "$@"; then pass "$label"; else fail "$label"; fi
}

runtime_targets=(
  tproj-msg
  tproj-task
  tproj-task-cache.sh
  tproj-msg-db.sh
  tproj-msg-desktop.sh
  tproj-inbox-monitor
  tproj-inbox-record
  tproj-inbox-check
  tproj-completion-guard
  tproj-mutation-guard
)

make_trust_response() {
  local home_root="$1"
  local codex_hooks="$home_root/.codex/hooks.json"
  cat > "$TMP/hooks-list.json" <<EOF
{"result":{"data":[{"hooks":[
  {"key":"task-mutation","sourcePath":"$codex_hooks","command":"$home_root/bin/tproj-mutation-guard --platform codex","currentHash":"sha256:abc000"},
  {"key":"task-record","sourcePath":"$codex_hooks","command":"$home_root/bin/tproj-inbox-record","currentHash":"sha256:abc001"},
  {"key":"task-check","sourcePath":"$codex_hooks","command":"$home_root/bin/tproj-inbox-check --platform codex","currentHash":"sha256:abc002"},
  {"key":"task-stop","sourcePath":"$codex_hooks","command":"$home_root/bin/tproj-completion-guard --platform codex","currentHash":"sha256:abc003"}
]}]}}
EOF
}

state_digest() {
  local home_root="$1"
  shasum -a 256 \
    "$home_root/.claude/settings.json" \
    "$home_root/.codex/hooks.json" \
    "$home_root/.codex/config.toml" \
    "$home_root/.claude/skills/msg/SKILL.md" \
    "$home_root/.codex/skills/msg/SKILL.md" \
    "$home_root/bin/"* \
    | shasum -a 256
}

# Case A: dry-run remains side-effect free.
dry_home="$TMP/dry-home"
dry_out="$("$INSTALLER" --home "$dry_home" --dry-run --skip-codex-trust 2>/dev/null || true)"
check "dry-run prints planned installs" grep -q "WOULD INSTALL" <<<"$dry_out"
check "dry-run does not create runtime files" test ! -e "$dry_home/bin/tproj-msg"

# Case B: install into isolated home and verify bytes, hooks, unrelated config, check mode, and idempotency.
home_root="$TMP/home"
mkdir -p "$home_root/.claude" "$home_root/.codex"
cat > "$home_root/.claude/settings.json" <<'EOF'
{"preserve":"claude","hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"keep-claude-hook"}]}]}}
EOF
cat > "$home_root/.codex/hooks.json" <<'EOF'
{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"keep-codex-hook"}]}]}}
EOF
cat > "$home_root/.codex/config.toml" <<'EOF'
model = "test"
keep = true
EOF
make_trust_response "$home_root"
install_rc=0
"$INSTALLER" --home "$home_root" --trust-response "$TMP/hooks-list.json" >/dev/null 2>&1 || install_rc=$?
check "installer succeeds in isolated home" test "$install_rc" -eq 0

runtime_ok=0
for target in "${runtime_targets[@]}"; do
  repo_source="$REPO/extensions/messaging/$target"
  [[ -f "$repo_source" ]] || repo_source="$REPO/extensions/hooks/$target"
  if [[ ! -x "$home_root/bin/$target" ]] || ! cmp -s "$repo_source" "$home_root/bin/$target"; then
    runtime_ok=1
    break
  fi
done
check "required runtime files are installed executable and byte-equal" test "$runtime_ok" -eq 0
check "msg skill is refreshed for Claude and Codex" sh -c "cmp -s '$REPO/extensions/messaging/skill-msg/SKILL.md' '$home_root/.claude/skills/msg/SKILL.md' && cmp -s '$REPO/extensions/messaging/skill-msg/SKILL.md' '$home_root/.codex/skills/msg/SKILL.md'"
check "unrelated config remains in Claude/Codex settings" sh -c "grep -q keep-claude-hook '$home_root/.claude/settings.json' && grep -q keep-codex-hook '$home_root/.codex/hooks.json' && grep -q '^keep = true$' '$home_root/.codex/config.toml'"
check "Claude and Codex hook configs register lifecycle and mutation guards" sh -c "grep -Fq '\$HOME/bin/tproj-mutation-guard' '$home_root/.claude/settings.json' && grep -Fq '\$HOME/bin/tproj-completion-guard' '$home_root/.claude/settings.json' && grep -Fq '$home_root/bin/tproj-mutation-guard --platform codex' '$home_root/.codex/hooks.json' && grep -Fq '$home_root/bin/tproj-completion-guard --platform codex' '$home_root/.codex/hooks.json' && grep -Fq 'trusted_hash = \"sha256:abc003\"' '$home_root/.codex/config.toml'"
check "installer check mode passes after install" sh -c "'$INSTALLER' --home '$home_root' --check >/dev/null 2>&1"

before_digest="$(state_digest "$home_root")"
second_rc=0
"$INSTALLER" --home "$home_root" --trust-response "$TMP/hooks-list.json" >/dev/null 2>&1 || second_rc=$?
after_digest="$(state_digest "$home_root")"
check "second installer run is idempotent" test "$second_rc" -eq 0 -a "$before_digest" = "$after_digest"

printf '%s\n' "----" "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
