#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/tproj-gui-reuse.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/project/apps/tproj/.build/debug/alias" "$TMP/project/apps/tproj/.build/debug/other"

real_bin="$TMP/project/apps/tproj/.build/debug/tproj-real"
other_bin="$TMP/project/apps/tproj/.build/debug/other/tproj"
touch "$real_bin" "$other_bin"
chmod +x "$real_bin" "$other_bin"
ln -s "$real_bin" "$TMP/project/apps/tproj/.build/debug/tproj"
ln -s "$real_bin" "$TMP/project/apps/tproj/.build/debug/alias/tproj"

expected=$(realpath "$TMP/project/apps/tproj/.build/debug/tproj")
same=$(realpath "$TMP/project/apps/tproj/.build/debug/alias/tproj")
[[ "$same" == "$expected" ]] || { echo "FAIL symlink did not resolve to canonical executable"; exit 1; }

# Extract and execute the production predicate itself.  Sourcing bin/tproj
# would attach tmux and launch the workspace, so isolate only this function.
eval "$(sed -n '/^_tproj_gui_command_matches() {/,/^}/p' "$REPO_ROOT/bin/tproj")"
_tproj_gui_command_matches "$expected" "$TMP/project/apps/tproj/.build/debug/tproj"
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
space_expected=$(realpath "$space_dir/tproj")
space_same=$(realpath "$space_dir/alias/tproj")
[[ "$space_same" == "$space_expected" ]] || { echo 'FAIL spaced path symlink mismatch'; exit 1; }
_tproj_gui_command_matches "$space_expected" "$space_dir/tproj"
_tproj_gui_command_matches "$space_expected" "$space_dir/alias/tproj"
echo 'PASS executable paths containing spaces compare without argument splitting'

echo 'PASS=3 FAIL=0'
