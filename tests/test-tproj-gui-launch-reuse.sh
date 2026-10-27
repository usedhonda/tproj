#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
TMP=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/tproj-gui-reuse.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/project/apps/tproj/.build/debug/alias" "$TMP/project/apps/tproj/.build/debug/other"

real_bin="$TMP/project/apps/tproj/.build/debug/tproj-real"
other_bin="$TMP/project/apps/tproj/.build/debug/other/tproj"
touch "$real_bin" "$other_bin"
chmod +x "$real_bin" "$other_bin"
ln -s "$real_bin" "$TMP/project/apps/tproj/.build/debug/tproj"
ln -s "$real_bin" "$TMP/project/apps/tproj/.build/debug/alias/tproj"

canonical_command="$TMP/project/apps/tproj/.build/debug/tproj"
same_command="$TMP/project/apps/tproj/.build/debug/alias/tproj"
expected="${canonical_command:A}"
same="${same_command:A}"
[[ "$same" == "$expected" ]] || { echo "FAIL symlink did not resolve to canonical executable"; exit 1; }

# Extract and execute the production predicate itself.  Sourcing bin/tproj
# would attach tmux and launch the workspace, so isolate only this function.
sed -n '/^_tproj_gui_command_matches() {/,/^}/p' "$REPO_ROOT/bin/tproj" > "$TMP/helper.zsh"
source "$TMP/helper.zsh"
_tproj_gui_command_matches "$expected" "$canonical_command"
_tproj_gui_command_matches "$expected" "$TMP/project/apps/tproj/.build/debug/alias/tproj"
echo 'PASS canonical and symlink GUI spellings reuse'

[[ "$other_bin" != "$expected" ]] || { echo 'FAIL fixture different executable unexpectedly matched'; exit 1; }
if _tproj_gui_command_matches "$expected" "$other_bin"; then
  echo 'FAIL genuinely different executable matched'; exit 1
fi
if _tproj_gui_command_matches "$expected" "$TMP/project/apps/tproj/.build/debug/tproj --server"; then
  echo 'FAIL --server command line matched as reusable GUI'; exit 1
fi
if _tproj_gui_command_matches "$expected" "/tmp/unrelated"; then
  echo 'FAIL unrelated command matched as reusable GUI'; exit 1
fi
echo 'PASS different, --server, and unrelated variants are replaceable'

space_dir="$TMP/project with spaces/apps/tproj/.build/debug"
mkdir -p "$space_dir/alias"
touch "$space_dir/tproj-real"
chmod +x "$space_dir/tproj-real"
ln -s "$space_dir/tproj-real" "$space_dir/tproj"
ln -s "$space_dir/tproj-real" "$space_dir/alias/tproj"
space_command="$space_dir/tproj"
space_same_command="$space_dir/alias/tproj"
space_expected="${space_command:A}"
space_same="${space_same_command:A}"
[[ "$space_same" == "$space_expected" ]] || { echo 'FAIL spaced path symlink mismatch'; exit 1; }
_tproj_gui_command_matches "$space_expected" "$space_dir/tproj"
_tproj_gui_command_matches "$space_expected" "$space_dir/alias/tproj"
echo 'PASS executable paths containing spaces compare without argument splitting'


# Match bin/tproj's zero-based catalog arrays for the extracted resolver.
setopt KSH_ARRAYS

# Workspace startup and the developer wrapper must select the same bundle,
# even when a stale raw debug executable is also present.
sed -n '/^_find_gui_target() {/,/^}/p' "$REPO_ROOT/bin/tproj" > "$TMP/target.zsh"
source "$TMP/target.zsh"
CATALOG_ALIASES=(tproj)
CATALOG_TYPES=(local)
CATALOG_PATHS=("$TMP/project")
bundle_bin="$TMP/project/apps/tproj/dist/release-app/tproj.app/Contents/MacOS/tproj"
mkdir -p "${bundle_bin:h}"
touch "$bundle_bin"; chmod +x "$bundle_bin"
[[ "$(_find_gui_target)" == "${bundle_bin:A}" ]] || { echo 'FAIL workspace did not choose canonical bundle'; exit 1; }
rm "$bundle_bin"
if _find_gui_target >/dev/null 2>&1; then
  echo 'FAIL missing bundle silently fell back to old raw debug GUI'; exit 1
fi
echo 'PASS workspace canonical bundle selection, no stale raw fallback'

# Never launch an unchecked prebuilt executable just because it exists.
if "$REPO_ROOT/apps/tproj/dev-app.sh" --prebuilt >"$TMP/prebuilt.log" 2>&1; then
  echo 'FAIL stale prebuilt launch still accepted'; exit 1
fi
grep -q -- '--prebuilt is retired' "$TMP/prebuilt.log"
echo 'PASS unchecked prebuilt launch rejected before packaging or launch'

# Exercise production cleanup with only the process inventory/signals stubbed.
# comm (not argv) lets --server variants match without touching unrelated apps.
sed -n '/^retire_stale_gui_variants() {/,/^}/p' "$REPO_ROOT/apps/tproj/dev-app.sh" > "$TMP/retire.bash"
cat > "$TMP/check-retire.bash" <<'BASH'
set -euo pipefail
source "$HELPER"
SCRIPT_DIR=/fixture/apps/tproj
APP_BUNDLE=$SCRIPT_DIR/dist/release-app/tproj.app
ps() {
  [[ "$*" == '-axo pid=,comm=' ]] || exit 5
  printf '%s\n' '10 /fixture/apps/tproj/.build/out/Products/Debug/tproj' \
    '11 /fixture/apps/tproj/dist/release-app/tproj.app/Contents/MacOS/tproj' \
    '12 /fixture/apps/tproj/.build/debug/tproj' '13 /unrelated/tproj'
}
kill() { echo "$1" >> "$SIGNALS"; }
retire_stale_gui_variants 11
[[ "$(cat "$SIGNALS")" == $'10\n12' ]]
BASH
HELPER="$TMP/retire.bash" SIGNALS="$TMP/signals" bash "$TMP/check-retire.bash"
echo 'PASS cleanup retires owned raw variants, preserves selected bundle and unrelated app'

echo 'PASS=6 FAIL=0'
