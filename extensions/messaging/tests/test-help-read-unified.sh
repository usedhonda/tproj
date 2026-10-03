#!/bin/bash
# Focused coverage for --help/-h and --read honesty once unified messaging is
# active: --help must describe the unified verbs (and not present retired
# flags like --fire as ordinary usage), a never-enrolled install must keep the
# legacy usage text unchanged, and --read of a known remote alias must say so
# instead of the generic "not found".
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
repo=$(cd "$root/../.." && pwd)
msg="$root/tproj-msg"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }

# --- 1. never-enrolled: legacy help is unchanged in key lines ---
legacy_home="$tmp/legacy"
mkdir -p "$legacy_home"
legacy_out=$(HOME="$legacy_home" "$msg" --help)
grep -Fq 'tproj-msg --fire <target> <message>  Send immediately (no idle check, auto-flush)' <<<"$legacy_out" \
  || fail "legacy help missing --fire usage line"
grep -Fq 'tproj-msg --flush                    Deliver all queued messages to idle targets' <<<"$legacy_out" \
  || fail "legacy help missing --flush usage line"
grep -Fq 'unified transport active' <<<"$legacy_out" \
  && fail "legacy help unexpectedly mentions unified transport"
echo "ok: never-enrolled --help is unchanged"

# --- 2. enrolled: --help shows unified sections, does not advertise --fire as usable ---
enrolled_home="$tmp/enrolled"
mkdir -p "$enrolled_home/.config/tproj"
cat >"$enrolled_home/.config/tproj/msg-client.json" <<'JSON'
{"active":true,"host_id":"h1"}
JSON
enrolled_out=$(HOME="$enrolled_home" "$msg" --help)
grep -Fq 'unified transport active' <<<"$enrolled_out" || fail "enrolled help missing unified banner"
grep -Fq 'tproj-msg --status [target]' <<<"$enrolled_out" || fail "enrolled help missing --status"
grep -Fq 'tproj-msg inbox --cursor <n> --limit <n> [--json]' <<<"$enrolled_out" || fail "enrolled help missing inbox"
grep -Fq 'tproj-msg ack <id>' <<<"$enrolled_out" || fail "enrolled help missing ack"
grep -Fq 'tproj-msg --retry <submission-id>' <<<"$enrolled_out" || fail "enrolled help missing --retry"
grep -Fq 'Legacy paths still available' <<<"$enrolled_out" || fail "enrolled help missing legacy section"
grep -Fq 'Retired under unified messaging' <<<"$enrolled_out" || fail "enrolled help missing retired section"
# --fire must appear only in the retired list, never as a "tproj-msg --fire ..." usage line.
grep -Fq 'tproj-msg --fire' <<<"$enrolled_out" && fail "enrolled help still advertises --fire as usable"
grep -Fq -- '--fire' <<<"$enrolled_out" || fail "enrolled help dropped --fire from the retired list"
echo "ok: enrolled --help shows unified usage and demotes --fire to retired"
grep -Fq 'tproj-msg --new-task' <<<"$enrolled_out" && fail "enrolled help advertises legacy task mutation"
grep -Fq 'Formal tasks and handoff: tproj-task --help' <<<"$enrolled_out" || fail "formal task command missing"

# -h is the same code path as --help.
HOME="$enrolled_home" "$msg" -h | grep -Fq 'unified transport active' || fail "-h did not use unified usage"
echo "ok: -h matches --help"

# --- 3. --read of a configured remote alias fails with a clear message ---
read_home="$tmp/read"
mkdir -p "$read_home/.config/tproj" "$read_home/bin"
cat >"$read_home/.config/tproj/workspace.yaml" <<'EOF'
projects:
  - path: /remote/chi
    type: remote
    host: some-other-mac
    alias: chi
EOF
cp "$repo/bin/tproj-peer-ledger" "$read_home/bin/tproj-peer-ledger"
chmod +x "$read_home/bin/tproj-peer-ledger"

set +e
read_out=$(HOME="$read_home" "$msg" --session tproj-help-read-test-nonexistent --read chi.cc 2>&1)
read_rc=$?
set -e
[[ $read_rc -ne 0 ]] || fail "--read of a remote alias unexpectedly succeeded"
grep -Fq "cannot read panes running on another Mac" <<<"$read_out" \
  || fail "--read of a remote alias did not explain the failure: $read_out"
grep -Fq "it only reads local panes" <<<"$read_out" \
  || fail "--read of a remote alias did not mention local-only scope: $read_out"
echo "ok: --read of a configured remote alias explains itself instead of 'not found'"

# --read of a genuinely unknown local target keeps the plain "not found" message.
set +e
unknown_out=$(HOME="$read_home" "$msg" --session tproj-help-read-test-nonexistent --read totally-unknown-alias.cc 2>&1)
unknown_rc=$?
set -e
[[ $unknown_rc -ne 0 ]] || fail "--read of an unknown target unexpectedly succeeded"
grep -Fq "cannot read panes running on another Mac" <<<"$unknown_out" \
  && fail "--read of a genuinely unknown target should not claim it is remote: $unknown_out"
echo "ok: --read of an unrelated unknown target keeps the plain not-found message"

echo "help/read unified honesty: ok"
