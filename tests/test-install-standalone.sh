#!/usr/bin/env bash
# Public standalone install must not require the private ../general checkout.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/tproj-standalone-install.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/tproj" "$TMP/home"

# Copy the checkout without local runtime state. The tracked persona/router
# symlinks then resolve nowhere, matching a public clone without ../general.
python3 - "$REPO_ROOT" "$TMP/tproj" <<'PYCLONE'
import os, pathlib, shutil, subprocess, sys
root, dest = map(pathlib.Path, sys.argv[1:])
for raw in subprocess.check_output(['git','ls-files','-z'],cwd=root).split(b'\0'):
    if not raw: continue
    relative=os.fsdecode(raw); source=root/relative; target=dest/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    if source.is_symlink(): target.symlink_to(os.readlink(source))
    elif source.is_file(): shutil.copy2(source,target)
PYCLONE

set +e
output=$(HOME="$TMP/home" bash "$TMP/tproj/install.sh" --dry-run --yes 2>&1)
status=$?
set -e

if [[ "$status" -ne 0 ]]; then
  printf 'FAIL standalone dry-run exited %s\n%s\n' "$status" "$output"
  exit 1
fi
grep -q 'optional persona unavailable: project-bootstrap (canonical general source is missing)' <<<"$output" \
  || { printf 'FAIL persona was not reported as optional\n%s\n' "$output"; exit 1; }
grep -q 'optional model-role-router unavailable: model-role-router (canonical general source is missing)' <<<"$output" \
  || { printf 'FAIL model-role-router was not reported as optional\n%s\n' "$output"; exit 1; }
grep -q 'Dry run complete (no changes made).' <<<"$output" \
  || { printf 'FAIL standalone dry-run did not complete\n%s\n' "$output"; exit 1; }

echo 'PASS public standalone install skips unavailable optional general integrations'
