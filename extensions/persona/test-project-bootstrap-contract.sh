#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BOOTSTRAP_LINK="$SCRIPT_DIR/project-bootstrap"
EXPECTED_TARGET="../../../general/system/project-bootstrap/project-bootstrap"
CANONICAL_BOOTSTRAP="$REPO_ROOT/../general/system/project-bootstrap/project-bootstrap"
VOICE_SYNC="$SCRIPT_DIR/voice-identity-sync"
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/tproj-persona-contract.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_shared_unchanged() {
  local repo="$1"
  local before="$2"
  local after
  after=$(shasum "$repo/AGENTS.md" "$repo/CLAUDE.md" "$repo/.gitignore")
  [[ "$before" == "$after" ]] || fail "runtime bootstrap changed shared files in $repo"
}

make_shared_fixture() {
  local repo="$1"
  mkdir -p "$repo"
  printf '# Shared Agent Rule\n\n- Preserve me.\n' > "$repo/AGENTS.md"
  printf '@AGENTS.md\n\n# Shared Claude Rule\n\n- Preserve me too.\n' > "$repo/CLAUDE.md"
  printf '# Shared ignore rule\ncustom.cache\n' > "$repo/.gitignore"
}

[[ -L "$BOOTSTRAP_LINK" ]] || fail "tracked project-bootstrap is not a symlink"
[[ "$(readlink "$BOOTSTRAP_LINK")" == "$EXPECTED_TARGET" ]] || \
  fail "tracked project-bootstrap target differs from $EXPECTED_TARGET"
[[ -f "$CANONICAL_BOOTSTRAP" ]] || fail "canonical general project-bootstrap is missing"
cmp -s "$BOOTSTRAP_LINK" "$CANONICAL_BOOTSTRAP" || \
  fail "tracked symlink does not resolve to the canonical general implementation"

grep -qF 'local -a prime_args=("$persona_bin" --prime "$project")' "$REPO_ROOT/bin/tproj" || \
  fail "tproj startup does not call the local-only --prime mode"

TEST_HOME="$TMP_ROOT/home"
mkdir -p "$TEST_HOME/bin/lib"
for source in "$REPO_ROOT"/bin/*; do
  [[ -f "$source" ]] || continue
  cp "$source" "$TEST_HOME/bin/"
done
cp "$REPO_ROOT/bin/lib/tproj-common.sh" "$TEST_HOME/bin/lib/tproj-common.sh"
cp -L "$BOOTSTRAP_LINK" "$TEST_HOME/bin/project-bootstrap"

check_output=$(HOME="$TEST_HOME" "$REPO_ROOT/install.sh" --check)
[[ "$check_output" == *"canonical project-bootstrap chain match"* ]] || \
  fail "install --check did not validate the canonical/symlink/copy chain"

printf '\n# test drift\n' >> "$TEST_HOME/bin/project-bootstrap"
if drift_output=$(HOME="$TEST_HOME" "$REPO_ROOT/install.sh" --check 2>&1); then
  fail "install --check accepted a stale project-bootstrap copy"
fi
[[ "$drift_output" == *"installed copy differs from canonical source"* ]] || \
  fail "install --check did not report project-bootstrap copy drift"
cp -L "$BOOTSTRAP_LINK" "$TEST_HOME/bin/project-bootstrap"

prime_repo="$TMP_ROOT/prime-repo"
make_shared_fixture "$prime_repo"
prime_before=$(shasum "$prime_repo/AGENTS.md" "$prime_repo/CLAUDE.md" "$prime_repo/.gitignore")
HOME="$TEST_HOME" "$BOOTSTRAP_LINK" --prime "$prime_repo" --alias prime-fixture >/dev/null
assert_shared_unchanged "$prime_repo" "$prime_before"
[[ -f "$prime_repo/.codex/config.toml" ]] || fail "--prime did not create local Codex config"
[[ -f "$prime_repo/.cc-status-bar.voice.json" ]] || fail "--prime did not create local voice artifact"

hook_repo="$TMP_ROOT/hook-repo"
make_shared_fixture "$hook_repo"
hook_before=$(shasum "$hook_repo/AGENTS.md" "$hook_repo/CLAUDE.md" "$hook_repo/.gitignore")
printf '{"cwd":"%s"}\n' "$hook_repo" | HOME="$TEST_HOME" "$BOOTSTRAP_LINK" >/dev/null
assert_shared_unchanged "$hook_repo" "$hook_before"

ensure_repo="$TMP_ROOT/ensure-repo"
make_shared_fixture "$ensure_repo"
ensure_before=$(shasum "$ensure_repo/AGENTS.md" "$ensure_repo/CLAUDE.md" "$ensure_repo/.gitignore")
HOME="$TEST_HOME" PATH="$TEST_HOME/bin:$PATH" \
  "$VOICE_SYNC" "$ensure_repo" --alias ensure-fixture --ensure --quiet
assert_shared_unchanged "$ensure_repo" "$ensure_before"
[[ -f "$ensure_repo/.codex/config.toml" ]] || fail "voice --ensure did not request local persona config"
[[ -f "$ensure_repo/.cc-status-bar.voice.json" ]] || fail "voice --ensure did not request local voice artifact"

echo "PASS: project-bootstrap two-layer and three-tier contract"
