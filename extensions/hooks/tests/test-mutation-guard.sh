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
  find "$HOME/.cache/tproj-expect-reply" -depth -delete 2>/dev/null || true
  tt_db_ensure_init >/dev/null 2>&1 || true
  tt_cache_add unit/worker worker.cdx worker-freeze-01 1000 1800 hash delegated >/dev/null 2>&1 || true
  tt_cache_tombstone_task unit/worker worker.cdx worker-freeze-01 frozen 1122aabbccddeeff >/dev/null 2>&1 || true
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

unfreeze_cmd="$HOME/bin/tproj-task unfreeze worker-freeze-01 worker.cdx aabbccddeeff0011"
unfreeze_guard_out="$(invoke_guard Bash "$unfreeze_cmd")"
check "exact installed unfreeze command is allowed through frozen guard" test -z "$unfreeze_guard_out"
TT_CACHE_OWNER="$TT_CACHE_OWNER" "$REPO/extensions/messaging/tproj-task" unfreeze worker-freeze-01 worker.cdx aabbccddeeff0011 >/dev/null
post_override_edit_out="$(invoke_guard Edit '')"
check "direct user override releases mutation guard without reopening frozen cache task" sh -c "test -z '$post_override_edit_out' && test \"\$(jq -r '.[\"worker-freeze-01\"].state' '$HOME/.cache/tproj-expect-reply/unit/worker/worker.cdx.json')\" = frozen && test \"\$(jq -r '.[\"worker-freeze-01\"].user_override_hash' '$HOME/.cache/tproj-expect-reply/unit/worker/worker.cdx.json')\" = aabbccddeeff0011"

seed_frozen_task
wrong_path_out="$(invoke_guard Bash "/tmp/tproj-task unfreeze worker-freeze-01 worker.cdx aabbccddeeff0011")"
check "lookalike unfreeze command remains blocked" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$wrong_path_out
EOF"

seed_frozen_task
allow_cat="$(invoke_guard Bash 'cat docs/reference/handoff.md')"
allow_ls="$(invoke_guard Bash 'ls -la extensions/hooks')"
allow_head="$(invoke_guard Bash 'head -n 40 AGENTS.md')"
allow_grep="$(invoke_guard Bash 'grep -rn frozen extensions/hooks')"
allow_sed_n="$(invoke_guard Bash 'sed -n 1,40p AGENTS.md')"
check "read-only evidence commands are allowed for a frozen task" sh -c "test -z '$allow_cat' && test -z '$allow_ls' && test -z '$allow_head' && test -z '$allow_grep' && test -z '$allow_sed_n'"

sed_inplace_out="$(invoke_guard Bash 'sed -i "" s/a/b/ AGENTS.md')"
check "sed -i stays blocked for a frozen task" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$sed_inplace_out
EOF"

sqlite_rw_out="$(invoke_guard Bash 'sqlite3 messages.db "delete from tasks"')"
check "sqlite3 without -readonly stays blocked" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$sqlite_rw_out
EOF"

skill_out="$(invoke_guard Skill '')"
check "Skill is allowed so a frozen receiver can reach the messaging skill" test -z "$skill_out"

report_out="$(invoke_guard Bash 'tproj-msg worker.cc "[BLOCK: worker-freeze-01] frozen"')"
check "tproj-msg report to the owner is allowed for a frozen task" test -z "$report_out"

delegate_out="$(invoke_guard Bash 'tproj-msg --new-task worker.cc "please do the frozen work"')"
check "tproj-msg --new-task stays blocked so a frozen pane cannot delegate onward" sh -c "grep -q 'read-only incident shell commands' <<'EOF'
$delegate_out
EOF"

escape_out="$(invoke_guard Edit '')"
check "a frozen refusal names the unfreeze command that releases it" sh -c "grep -q 'tproj-task unfreeze worker-freeze-01 worker.cdx' <<'EOF'
$escape_out
EOF"

# The quarantine must not outlive the assignment: reading only the tombstone row
# kept the newest freeze enforcing itself against unrelated work forever, which is
# the reported incident.
find "$TMP" -maxdepth 1 -name 'messages.db*' -delete 2>/dev/null || true
find "$HOME/.cache/tproj-expect-reply" -depth -delete 2>/dev/null || true
tt_db_ensure_init >/dev/null 2>&1 || true
tt_cache_add unit/worker worker.cdx worker-freeze-01 1000 1800 hash delegated >/dev/null 2>&1 || true
tt_cache_tombstone_task unit/worker worker.cdx worker-freeze-01 frozen 1122aabbccddeeff 2000 >/dev/null 2>&1 || true
still_frozen_out="$(invoke_guard Edit '')"
check "the tombstone still gates the pane while it holds no newer task" sh -c "grep -q 'edits are blocked' <<'EOF'
$still_frozen_out
EOF"
tt_cache_add unit/worker worker.cdx worker-next-02 3000 3800 hash delegated >/dev/null 2>&1 || true
reassigned_out="$(invoke_guard Edit '')"
check "a newer task for the same pane ends the quarantine" test -z "$reassigned_out"

printf '%s\n' "----" "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
