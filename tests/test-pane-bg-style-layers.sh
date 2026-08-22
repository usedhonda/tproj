#!/usr/bin/env bash
#
# test-pane-bg-style-layers.sh -- which layer supplies each style slot.
#
# The cel-rendering technique gpt-image-2 needs used to live only in one project's
# ignored prompt.local.json, so every other project fell through to the house style
# name alone and rendered glossy and photo-real. The technique is a tracked default
# now; the house file and a project's prompt.local.json still own taste. This asserts
# the order: tracked baseline < ~/.config house < project prompt.local.json.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BG="$SCRIPT_DIR/../extensions/persona/tproj-pane-bg"

PASS=0
FAIL=0
pass() { printf 'PASS  %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf 'FAIL  %s\n      %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }

TMP=$(mktemp -d "${TMPDIR:-/tmp}/pane-bg-layers.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/home" "$TMP/proj/.local/tproj-pane-bg" "$TMP/bare"

# A clean HOME so the real ~/.config/tproj/pane-bg.local cannot colour the result.
layers() { HOME="$TMP/home" "$BG" style-layers "$@" 2>/dev/null; }
field() { printf '%s' "$1" | jq -r "$2"; }

out=$(layers)
[[ "$(field "$out" .style_guard)" == "baseline" && "$(field "$out" .negative_extra)" == "baseline" ]] \
  && pass "gpt-image with no override inherits the tracked baseline" \
  || fail "gpt-image with no override inherits the tracked baseline" "$out"

[[ "$(field "$out" .style_baseline)" != "null" ]] \
  && pass "an applied baseline is stamped so a later cache check can reproduce it" \
  || fail "an applied baseline is stamped" "$out"

# Provider-scoped: the gemini route was never broken and must not start carrying a
# cel guard it did not ask for.
out=$(layers --model gemini-3-pro-image-preview)
[[ "$(field "$out" .style_guard)" == "empty" && "$(field "$out" .style_baseline)" == "null" ]] \
  && pass "the baseline is scoped to its provider" \
  || fail "the baseline is scoped to its provider" "$out"

# House layer.
mkdir -p "$TMP/home/.config/tproj"
cat > "$TMP/home/.config/tproj/pane-bg.local" <<'HOUSE'
TPROJ_PANE_BG_STYLE_REF_EN="House Style"
TPROJ_PANE_BG_STYLE_GUARD_JP="house guard"
TPROJ_PANE_BG_NEGATIVE_EXTRA_JP="house negative"
HOUSE
out=$(layers)
[[ "$(field "$out" .style_guard)" == "override" && "$(field "$out" .style_baseline)" == "null" ]] \
  && pass "a house guard wins over the tracked baseline" \
  || fail "a house guard wins over the tracked baseline" "$out"
[[ "$(field "$out" .style_ref_en)" == "House Style" ]] \
  && pass "the house style name still reaches the prompt" \
  || fail "the house style name still reaches the prompt" "$out"

# Project layer, on top of the house layer.
cat > "$TMP/proj/.local/tproj-pane-bg/prompt.local.json" <<'PROJ'
{ "style_guard_jp": "project guard", "negative_extra_jp": "project negative",
  "style_ref_en": "Project Style" }
PROJ
out=$(layers --project "$TMP/proj")
[[ "$(field "$out" .style_guard)" == "override" && "$(field "$out" .style_ref_en)" == "Project Style" ]] \
  && pass "a project override wins over the house layer" \
  || fail "a project override wins over the house layer" "$out"

# A project with no override file falls back through house to the baseline.
rm -f "$TMP/home/.config/tproj/pane-bg.local"
out=$(layers --project "$TMP/bare")
[[ "$(field "$out" .style_guard)" == "baseline" ]] \
  && pass "a project with no override file still inherits the baseline" \
  || fail "a project with no override file still inherits the baseline" "$out"

# The OpenAI image-detail parameter is the string "auto". A whole-word vocabulary
# rename (auto -> collab) once rewrote it, the API rejected the probe, and the
# face-centred crop silently fell open -- every new pane came out too far away.
if [[ "$(grep -c '"detail": "auto"' "$BG")" -ge 2 ]] && ! grep -q '"detail": "collab"' "$BG"; then
  pass "the OpenAI image-detail literal survived the vocabulary rename"
else
  fail "the OpenAI image-detail literal survived the vocabulary rename" "$(grep -n '"detail":' "$BG" | tr '\n' '|')"
fi

printf -- '----\nPASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
