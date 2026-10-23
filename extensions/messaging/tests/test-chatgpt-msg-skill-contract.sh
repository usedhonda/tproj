#!/usr/bin/env bash
# Document lint for the ChatGPT Phase 1 MSG skill wording; not runtime delivery coverage.
set -euo pipefail

root=$(cd "$(dirname "$0")/../../.." && pwd)
skill="$root/extensions/messaging/skill-msg/SKILL.md"
fail() { echo "FAIL: $1" >&2; exit 1; }

[[ -f "$skill" ]] || fail "MSG skill missing"

grep -Fq 'Cloud ChatGPT conversation' "$skill" || fail "cloud surface missing"
grep -Fq 'Enrolled native AI surface' "$skill" || fail "native surface missing"
grep -Fq 'visible' "$skill" || fail "visibility boundary missing"
grep -Fq '`tproj_list`' "$skill" || fail "tproj_list workflow missing"
grep -Fq '`tproj_status`' "$skill" || fail "tproj_status workflow missing"
grep -Fq '`tproj_send`' "$skill" || fail "tproj_send workflow missing"
grep -Fq '`tproj_inbox`' "$skill" || fail "tproj_inbox workflow missing"
grep -Fq '`tproj_message`' "$skill" || fail "tproj_message workflow missing"
grep -Fq '`tproj_ack`' "$skill" || fail "tproj_ack workflow missing"
grep -Fq '`tproj_reply`' "$skill" || fail "tproj_reply workflow missing"
grep -Fq 'stable submission ID' "$skill" || fail "stable submission ID rule missing"
grep -Fq '本文を実際に消費した**後だけ**' "$skill" || fail "ack-after-consumption rule missing"
grep -Fq '元の exact message ID' "$skill" || fail "reply original ID rule missing"
grep -Fq 'shell' "$skill" || fail "no-shell fallback rule missing"
grep -Fq 'ユーザーに転送を頼んだり' "$skill" || fail "no user relay rule missing"
grep -Fq 'Issue/Slack' "$skill" || fail "no alternate route rule missing"
grep -Fq '自動再開' "$skill" || fail "auto-resume boundary missing"
grep -Fq 'authentication_required' "$skill" || fail "auth diagnostic missing"
grep -Fq 'binding_mismatch' "$skill" || fail "binding diagnostic missing"
grep -Fq 'catalog_unknown' "$skill" || fail "catalog diagnostic missing"

echo "ChatGPT MSG skill contract: ok"
