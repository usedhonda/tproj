#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/tproj-pane-bg-face-stock.XXXXXX")"
PROJECT="$WORK/project"
STOCK="$WORK/stock"
HOME="$WORK/home"
mkdir -p "$PROJECT/.local/tproj-pane-bg" "$STOCK" "$HOME"
trap 'rm -rf "$WORK"' EXIT

export HOME
export TPROJ_PANE_BG_SOURCE_ONLY=1
export TPROJ_PANE_BG_FACE_STOCK_DIR="$STOCK"
source "$SCRIPT_DIR/tproj-pane-bg"

printf 'png-a' > "$STOCK/face-a.png"
printf 'png-b' > "$STOCK/face-b.png"
PERSONA_GENDER_RAW="女"
select_face_stock_reference "$PROJECT" cdx
case "$FACE_STOCK_REFERENCE_ID" in face-a|face-b) ;; *) exit 1 ;; esac
selected="$FACE_STOCK_REFERENCE_ID"
write_face_stock_pin "$PROJECT" cdx "$FACE_STOCK_REFERENCE_PATH" "$FACE_STOCK_REFERENCE_ID"
printf 'png-c' > "$STOCK/face-c.png"
select_face_stock_reference "$PROJECT" cdx
test "$FACE_STOCK_REFERENCE_ID" = "$selected"

PERSONA_GENDER_RAW="男"
select_face_stock_reference "$PROJECT" cc
test -z "$FACE_STOCK_REFERENCE_PATH"

cat > "$PROJECT/.local/tproj-pane-bg/prompt.local.json" <<'JSON'
{"face_reference_cc":"face-a"}
JSON
PERSONA_GENDER_RAW="女"
select_face_stock_reference "$PROJECT" cc
test "$FACE_STOCK_REFERENCE_ID" = face-a

rm -f "$PROJECT/.local/tproj-pane-bg/cc.face-reference.json" "$PROJECT/.local/tproj-pane-bg/prompt.local.json"
if face_stock_selection_needed "$PROJECT" cc true; then
  exit 1
fi

echo "PASS: female stock selection pins deterministically and male remains unchanged"
