#!/usr/bin/env bash
#
# test-install-check-persona.sh -- install.sh --check must cover what install.sh copies.
#
# The persona scripts are plain `cp`s into ~/bin, but --check used to look only at
# CORE_BINS and the symlink chains, so a stale installed copy stayed invisible. The
# first run of this check found exactly that: ~/bin/cc-persona still pointed at a
# layout that no longer exists, and nothing was reporting it.

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

PASS=0
FAIL=0
pass() { printf 'PASS  %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf 'FAIL  %s\n      %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }

TMP=$(mktemp -d "${TMPDIR:-/tmp}/install-check-persona.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin/lib"

# A fake ~/bin that starts out matching the repo for everything --check inspects.
for f in "$REPO_ROOT"/bin/*; do
  [[ -f "$f" ]] && cp "$f" "$TMP/bin/"
done
cp "$REPO_ROOT"/bin/lib/*.sh "$TMP/bin/lib/" 2>/dev/null || true
for f in "$REPO_ROOT"/extensions/persona/*; do
  [[ -f "$f" && ! -L "$f" ]] && cp "$f" "$TMP/bin/"
done
cp -L "$REPO_ROOT/extensions/persona/project-bootstrap" "$TMP/bin/project-bootstrap" 2>/dev/null || true

run_check() { HOME="$TMP" bash "$REPO_ROOT/install.sh" --check 2>&1; }

PERSONA_LIST=$(bash -c 'source /dev/stdin <<< "$(grep -m1 "^PERSONA_BINS=" "$1")"; printf "%s\n" "${PERSONA_BINS[@]}"' _ "$REPO_ROOT/install.sh")
[[ -n "$PERSONA_LIST" ]] \
  && pass "install.sh declares the persona scripts it copies" \
  || fail "install.sh declares the persona scripts it copies" "PERSONA_BINS not found"

# Every declared persona script must actually be reported when its installed copy
# drifts. A list that --check silently skips is the bug this test exists for.
while IFS= read -r bin_name; do
  [[ -n "$bin_name" ]] || continue
  printf '\n# drift\n' >> "$TMP/bin/$bin_name"
  out=$(run_check)
  if printf '%s' "$out" | grep -q -- "$bin_name (differs)"; then
    pass "--check reports drift in $bin_name"
  else
    fail "--check reports drift in $bin_name" "$(printf '%s' "$out" | tr '\n' '|' | cut -c1-140)"
  fi
  cp "$REPO_ROOT/extensions/persona/$bin_name" "$TMP/bin/$bin_name"
done <<< "$PERSONA_LIST"

while IFS= read -r bin_name; do
  [[ -n "$bin_name" ]] || continue
  rm -f "$TMP/bin/$bin_name"
  out=$(run_check)
  printf '%s' "$out" | grep -q -- "$bin_name (missing in ~/bin)" \
    && pass "--check reports a missing $bin_name" \
    || fail "--check reports a missing $bin_name" "$(printf '%s' "$out" | tr '\n' '|' | cut -c1-140)"
  cp "$REPO_ROOT/extensions/persona/$bin_name" "$TMP/bin/$bin_name"
done <<< "$PERSONA_LIST"

printf -- '----\nPASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
