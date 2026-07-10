#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
LINK="$ROOT/extensions/model-role-router/model-role-router"
EXPECTED_TARGET="../../../general/system/model-role-router/model-role-router"
CANONICAL="$ROOT/../general/system/model-role-router/model-role-router"
HELPER="$ROOT/bin/lib/tproj-model-role.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tproj-model-role-contract.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -L "$LINK" ]] || fail "tracked model-role-router is not a symlink"
[[ "$(readlink "$LINK")" == "$EXPECTED_TARGET" ]] || fail "tracked symlink target differs"
[[ -x "$CANONICAL" ]] || fail "canonical general router is missing or not executable"
cmp -s "$LINK" "$CANONICAL" || fail "tracked symlink does not resolve to canonical bytes"

help_output="$($LINK --help)"
for command in observe resolve route status doctor hook; do
  [[ "$help_output" == *"$command"* ]] || fail "canonical router is missing command: $command"
done

mkdir -p "$WORK/bin"
cat > "$WORK/bin/tmux" <<'TMUX'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  list-panes)
    printf '%%1\n%%2\n'
    ;;
  display-message)
    target=""; fmt=""; shift
    while [[ $# -gt 0 ]]; do
      case "$1" in -t) target="$2"; shift 2 ;; -p) fmt="$2"; shift 2 ;; *) shift ;; esac
    done
    case "${target}:${fmt}" in
      '%1:#{@role}') printf '%s' 'claude-p1' ;;
      '%2:#{@role}') printf '%s' 'codex-p1' ;;
      *':#{@alias}') printf '%s' 'tproj' ;;
      *':#{@column}') printf '%s' '1' ;;
      *':#{@project}') printf '%s' '/repo' ;;
    esac
    ;;
  show-options)
    target=""; option=""; shift
    while [[ $# -gt 0 ]]; do
      case "$1" in -t) target="$2"; shift 2 ;; @*) option="$1"; shift ;; *) shift ;; esac
    done
    case "${target}:${option}" in
      '%2:@active_model') printf '%s' 'gpt-existing' ;;
      '%2:@model_tier') printf '%s' 'tier-existing' ;;
      '%2:@orchestration_role') printf '%s' 'orchestrator' ;;
      '%2:@role_epoch') printf '%s' '9' ;;
    esac
    ;;
  set-option)
    printf '%s\n' "$*" >> "$MODEL_ROLE_TEST_DIR/tmux-set.log"
    ;;
esac
TMUX
chmod +x "$WORK/bin/tmux"

cat > "$WORK/bin/router" <<'ROUTER'
#!/usr/bin/env bash
printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
  "$1" "$TPROJ_SESSION" "$TPROJ_PANE" "$TPROJ_ALIAS" "$TPROJ_ROLE" "$TPROJ_COLUMN" \
  >> "$MODEL_ROLE_TEST_DIR/router.log"
ROUTER
chmod +x "$WORK/bin/router"

export MODEL_ROLE_TEST_DIR="$WORK"
export PATH="$WORK/bin:$PATH"
# shellcheck source=/dev/null
source "$HELPER"
tproj_model_role_initialize test-session "$WORK/bin/router" dev

set_log="$(cat "$WORK/tmux-set.log")"
router_log="$(cat "$WORK/router.log")"
for expected in '@active_model unknown' '@model_tier unknown' '@orchestration_role solo-fallback' '@role_epoch 0'; do
  [[ "$set_log" == *"-pt %1 $expected"* ]] || fail "missing initialization: $expected"
done
[[ "$set_log" != *'-pt %2'* ]] || fail "existing metadata was overwritten"
[[ "$router_log" == *$'observe\ttest-session\t%1\ttproj.cc\tcc\t1'* ]] || fail "observe invocation metadata differs"
[[ "$router_log" == *$'resolve\ttest-session\t%1\ttproj.cc\tcc\t1'* ]] || fail "resolve invocation metadata differs"
[[ "$router_log" != *$'\t%2\t'* ]] || fail "router ran for a pane whose metadata was already complete"

rm -f "$WORK/router.log" "$WORK/tmux-set.log"
tproj_model_role_initialize test-session "$WORK/bin/missing-router" dev
[[ -s "$WORK/tmux-set.log" ]] || fail "metadata defaults were not initialized without the router"
[[ ! -e "$WORK/router.log" ]] || fail "missing router was invoked"

echo "PASS: model-role-router symlink and startup metadata contract"
