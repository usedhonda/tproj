#!/bin/bash
set -u

REPO="$(cd "$(dirname "$0")/../../.." && pwd -P)"
TMP="$(mktemp -d)"
trap 'find "$TMP" -depth -delete 2>/dev/null || true' EXIT

PASS=0
FAIL=0

export HOME="$TMP/home"
export TPROJ_MSG_DB_PATH="$TMP/messages.db"
export TPROJ_MSG_DB_ERROR_LOG="$TMP/db-errors.log"
export TPROJ_MSG_DB_INIT_FLAG="$TMP/db-init.stamp"
export TT_CACHE_OWNER="unit/worker"
export TT_OWNER_ROLE=cdx
mkdir -p "$HOME"

# shellcheck source=/dev/null
source "$REPO/extensions/messaging/tproj-task-cache.sh"

pass() { PASS=$((PASS + 1)); printf 'PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$1"; }
check() {
  local label="$1"
  shift
  if "$@"; then pass "$label"; else fail "$label"; fi
}

seed_frozen_task() {
  find "$TMP" -maxdepth 1 -name 'messages.db*' -delete 2>/dev/null || true
  tt_db_ensure_init >/dev/null 2>&1 || true
  tt_db_upsert_task worker-freeze-01 worker.cdx 1000 1800 hash worker unit >/dev/null 2>&1 || true
  tt_db_tombstone_task worker-freeze-01 frozen unit worker worker.cdx 1122aabbccddeeff >/dev/null 2>&1 || true
}

invoke_guard() {
  local tool_name="$1" command_text="$2"
  jq -nc --arg tool_name "$tool_name" --arg cmd "$command_text" '{tool_name:$tool_name,tool_input:{command:$cmd}}' \
    | TT_CACHE_OWNER="$TT_CACHE_OWNER" TT_OWNER_ROLE="$TT_OWNER_ROLE" "$REPO/extensions/hooks/tproj-mutation-guard" --platform codex 2>/dev/null
}

seed_frozen_task
edit_out="$(invoke_guard Edit '')"
check "Edit is blocked for frozen task" sh -c "grep -q 'edits are blocked' <<'EOF'
$edit_out
EOF"

shell_block_out="$(invoke_guard Bash 'git commit -m freeze')"
check "mutating git command is blocked for frozen task" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$shell_block_out
EOF"

ambiguous_out="$(invoke_guard Bash 'git status | cat')"
check "ambiguous shell pipeline is blocked" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$ambiguous_out
EOF"

find_delete_out="$(invoke_guard Bash 'find . -delete')"
check "find -delete is blocked" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$find_delete_out
EOF"

find_exec_out="$(invoke_guard Bash 'find . -exec rm {} ;')"
check "find -exec is blocked" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$find_exec_out
EOF"

git_diff_output_eq_out="$(invoke_guard Bash 'git diff --output=x')"
check "git diff --output=x is blocked" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$git_diff_output_eq_out
EOF"

git_diff_output_sep_out="$(invoke_guard Bash 'git diff --output x')"
check "git diff --output x is blocked" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$git_diff_output_sep_out
EOF"

git_config_diff_out="$(invoke_guard Bash 'git -c core.pager=cat diff')"
check "git -c core.pager=cat diff is blocked" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$git_config_diff_out
EOF"

allow_status="$(invoke_guard Bash 'git status --short --branch')"
allow_diff="$(invoke_guard Bash 'git diff --cached')"
allow_show="$(invoke_guard Bash 'git show HEAD')"
allow_find="$(invoke_guard Bash 'find . -maxdepth 2 -type f -name '\''*.sh'\''')"
allow_hash="$(invoke_guard Bash 'shasum -a 256 README.md')"
check "strict read-only incident commands are allowed" sh -c "test -z '$allow_status' && test -z '$allow_diff' && test -z '$allow_show' && test -z '$allow_find' && test -z '$allow_hash'"

printf '%s\n' "----" "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
