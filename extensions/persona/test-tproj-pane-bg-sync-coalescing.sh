#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT="$SCRIPT_DIR/tproj-pane-bg"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tproj-pane-bg-coalesce.XXXXXX")"
# Project resolution uses physical paths; macOS temporary roots can be symlinks.
WORK="$(cd "$WORK" && pwd -P)"
BIN="$WORK/bin"
ROOT="$WORK/state"
mkdir -p "$BIN" "$ROOT/lock.demo"
trap 'rm -rf "$WORK"' EXIT

cat > "$BIN/tmux" <<'TMUX'
#!/usr/bin/env bash
exit 0
TMUX
# Queued full requests may try to prepare placeholders before taking the lock.
# Keep this suite independent of a host ImageMagick installation.
cat > "$BIN/magick" <<'MAGICK'
#!/usr/bin/env bash
exit 1
MAGICK
chmod +x "$BIN/tmux" "$BIN/magick"

export PATH="$BIN:$PATH"
hash -r
export TPROJ_PANE_BG_NO_PATH_PREPEND=1
export TPROJ_PANE_BG_WORK_ROOT="$ROOT"

# Simulate a lock holder, then sequential full and fast arrivals. Full priority
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

# Exercise real sync/manifest output with empty and populated windows. The JSON
# process budget must remain constant as the pane count grows; external routing,
# hooks and providers are independent boundaries and are stubbed here.
PANE_ROWS="$WORK/pane-rows"
JQ_LOG="$WORK/jq.log"
PROJECT="$WORK/project with spaces"
mkdir -p "$PROJECT/.local/tproj-pane-bg"
for side in cc cdx; do
  printf 'cached-image-%s' "$side" > "$PROJECT/.local/tproj-pane-bg/$side.vertical.png"
  printf '{}\n' > "$PROJECT/.local/tproj-pane-bg/$side.vertical.json"
done
GHOSTTY_CONFIG="$WORK/ghostty-config"
printf 'window-padding-x = 4\nwindow-padding-y = 3\n' > "$GHOSTTY_CONFIG"
DEFAULT_OPACITY=0.94
ALIAS=$'review "quoted" \\ path\t日本語'
tmux() {
  case "$1" in
    display-message) printf '120\t30\tdev\tfixture-layout\t120\t30\n' ;;
    list-panes) cat "$PANE_ROWS" ;;
    *) return 0 ;;
  esac
}
sync_hooks_are_current() { return 0; }
install_sync_hooks() { :; }
load_conversation_main() { CONVERSATION_MAIN_RESULT=cc; }
jq() { printf 'jq\n' >> "$JQ_LOG"; command jq "$@"; }
: > "$PANE_ROWS"
: > "$JQ_LOG"
sync_session empty fast >/dev/null
empty_json_calls="$(wc -l < "$JQ_LOG" | tr -d ' ')"
command jq -e '.version == 1 and .panes == []' "$ROOT/empty.json" >/dev/null

for ((i = 0; i < 12; i++)); do
  side=cc
  alias=""
  column=""
  active=0
  if ((i % 2)); then side=cdx; fi
  if ((i == 0)); then alias="$ALIAS"; column=left; active=1; fi
  printf '%%%s|%s|1|10|29|%s|%s|%s|%s|%s|%s||\n' \
    "$i" "$((i * 10))" "$PROJECT" "$side" "$alias" "$column" "$PROJECT" "$active" >> "$PANE_ROWS"
done
printf '%%ignored|0|0|120|30|%s|shell|||%s|0||\n' "$PROJECT" "$PROJECT" >> "$PANE_ROWS"
: > "$JQ_LOG"
sync_session populated fast >/dev/null
populated_json_calls="$(wc -l < "$JQ_LOG" | tr -d ' ')"
command jq -e --arg project "$PROJECT" --arg alias "$ALIAS" '
  .version == 1 and .session == "populated" and .window == "dev" and
  .window_layout == "fixture-layout" and .window_cells == {width:120,height:30} and
  .client_cells == {width:120,height:30} and .window_padding_px == {x:4,y:3} and
  .default_opacity == 0.94 and (.panes | length) == 12 and
  .panes[0] == {
    pane_id:"%0",tmux_role:"cc",role:"cc",alias:$alias,column:"left",
    pane_cwd:$project,project:$project,conversation_main:true,
    left:0,top:1,width:10,height:29,
    image_path:($project + "/.local/tproj-pane-bg/cc.vertical.png"),
    image_meta_path:($project + "/.local/tproj-pane-bg/cc.vertical.json"),
    opacity:0.94,active:true
  } and .panes[1].alias == null and .panes[1].column == null and
  .panes[1].role == "cdx" and .panes[1].conversation_main == false and
  .panes[1].active == false and .panes[11].left == 110 and
  .panes[11].image_path == ($project + "/.local/tproj-pane-bg/cdx.vertical.png")
' "$ROOT/populated.json" >/dev/null
if [[ "$empty_json_calls" != 2 || "$populated_json_calls" != "$empty_json_calls" ]]; then
  printf 'FAIL: JSON process count grew from %s (empty) to %s (12 panes)\n' \
    "$empty_json_calls" "$populated_json_calls" >&2
  exit 1
fi
echo "PASS: empty and 12-pane manifests preserve fields with 2 JSON processes each"

# A cold fast sync is a layout-only operation. It must remain responsive even
# when optional artwork is absent; a later full sync can create the fallback.
MISSING_PROJECT="$WORK/missing-art"
PLACEHOLDER_LOG="$WORK/placeholders.log"
mkdir -p "$MISSING_PROJECT"
printf '%%cold|0|0|120|30|%s|cc|||%s|1||\n' \
  "$MISSING_PROJECT" "$MISSING_PROJECT" > "$PANE_ROWS"
rm -f "$ROOT/fallback-cc.png" "$ROOT/fallback-cdx.png"
ensure_runtime_placeholder() {
  local path
  path="$(runtime_placeholder_path "$1")"
  printf '%s\n' "$1" >> "$PLACEHOLDER_LOG"
  printf 'fallback-image' > "$path"
  printf '%s\n' "$path"
}
generate_background() { return 1; }
schedule_generation_retry() { :; }
sync_session cold-fast fast >/dev/null
test ! -e "$PLACEHOLDER_LOG"
command jq -e '.panes[0].image_path == null' "$ROOT/cold-fast.json" >/dev/null
test "$(paste -sd, "$PROMOTION_LOG")" = prime,hydrate,placeholders
sync_session cold-full full >/dev/null 2>"$WORK/generation-warning.log"
test "$(cat "$PLACEHOLDER_LOG")" = cc
command jq -e --arg path "$ROOT/fallback-cc.png" \
  '.panes[0].image_path == $path and .panes[0].image_meta_path == null' \
  "$ROOT/cold-full.json" >/dev/null
sync_session warm-fast fast >/dev/null
test "$(cat "$PLACEHOLDER_LOG")" = cc
command jq -e --arg path "$ROOT/fallback-cc.png" \
  '.panes[0].image_path == $path' "$ROOT/warm-fast.json" >/dev/null
echo "PASS: fast sync reuses artwork and leaves missing fallback creation to full sync"


# Finish B's real publication between A's copy and rename. This deterministic
# interleaving exposes a shared temporary path without process timing or FIFOs.
(
  printf '[]\n' > "$WORK/publication-panes.json"
  cp() {
    command cp "$@"
    case "$1" in
      "$ROOT/publish-a.json")
        write_manifest publish-b "$ROOT/publish-b.json" "$WORK/publication-panes.json" dev layout-b 100 20
        command jq -e '.session == "publish-b" and .window_cells == {width:100,height:20} and .panes == []' "$CURRENT_MANIFEST" >/dev/null
        ;;
    esac
  }
  write_manifest publish-a "$ROOT/publish-a.json" "$WORK/publication-panes.json" dev layout-a 120 30
  if ! command jq -e '.session == "publish-a" and .window_cells == {width:120,height:30} and .panes == []' "$CURRENT_MANIFEST" >/dev/null; then
    printf 'FAIL: session A did not publish its own snapshot after session B\n' >&2
    exit 1
  fi
)
echo "PASS: overlapping session publications retain separate complete snapshots"
