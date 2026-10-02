#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT="$SCRIPT_DIR/tproj-pane-bg"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tproj-pane-bg-coalesce.XXXXXX")"
BIN="$WORK/bin"
ROOT="$WORK/state"
mkdir -p "$BIN" "$ROOT/lock.demo"
trap 'rm -rf "$WORK"' EXIT

cat > "$BIN/tmux" <<'TMUX'
#!/usr/bin/env bash
exit 0
TMUX
chmod +x "$BIN/tmux"

export PATH="$BIN:$PATH"
hash -r
export TPROJ_PANE_BG_NO_PATH_PREPEND=1
export TPROJ_PANE_BG_WORK_ROOT="$ROOT"

# Simulate a lock holder, then concurrent full and fast arrivals. Full priority
# must remain queued after the later fast request.
TPROJ_PANE_BG_WORK_ROOT="$ROOT" "$SCRIPT" sync --session demo >/dev/null
TPROJ_PANE_BG_WORK_ROOT="$ROOT" "$SCRIPT" sync --session demo --fast >/dev/null
test "$(cat "$ROOT/pending.demo")" = full

echo "PASS: full sync remains sticky over a queued fast sync"

# Exercise the holder's promotion seam without tmux or provider calls.
export TPROJ_PANE_BG_SOURCE_ONLY=1
source "$SCRIPT"
PENDING="$ROOT/pending.claim"
CLAIM="$ROOT/pending.claim.$$"
printf '%s\n' full > "$PENDING"
mode="$(claim_pending_sync_mode "$PENDING" "$CLAIM")"
test "$mode" = full
test ! -e "$PENDING"
PROMOTION_LOG="$WORK/promotion.log"
prime_session_api_env() { printf '%s\n' prime >> "$PROMOTION_LOG"; }
hydrate_api_env_from_session() { printf '%s\n' hydrate >> "$PROMOTION_LOG"; }
ensure_all_runtime_placeholders() { printf '%s\n' placeholders >> "$PROMOTION_LOG"; }
prepare_promoted_full_sync demo
test "$(paste -sd, "$PROMOTION_LOG")" = prime,hydrate,placeholders
echo "PASS: claimed full sync promotes with runtime preparation"
