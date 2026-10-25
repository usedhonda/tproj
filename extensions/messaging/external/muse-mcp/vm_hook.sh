#!/usr/bin/env bash
# Bounded, single-flight detector. No listener daemon and no bodies in hook state.
set -euo pipefail
source "${HATCH_HOOK_RUNTIME:?native hook runtime required}"
CONNECTOR="$HOME/workspace/custom-connectors/custom.tproj"
STATE_DIR="${HATCH_HOOK_STATE_DIR:?native hook state required}"
# flock is available on the Linux Muse VM. It never owns the native state file.
exec 9>"$STATE_DIR/${HATCH_HOOK_ID}.poll.lock"
flock -n 9 || silent "tproj-poll-already-running" '{}'
STATE="$(hook_state_get)"
OUT="$(printf '%s' "$STATE" | "$CONNECTOR/.venv/bin/python" "$CONNECTOR/bin/vm_poll.py" --config "$CONNECTOR/client.json")"
hook_state_set "$(printf '%s' "$OUT" | jq -ce '.state')"
REASON="$(printf '%s' "$OUT" | jq -r '.reason')"
PAYLOAD="$(printf '%s' "$OUT" | jq -c '.payload // {}')"
if [[ "$(printf '%s' "$OUT" | jq -r '.decision')" == wake ]]; then
  wake "$REASON" "$PAYLOAD"
else
  silent "$REASON" "$PAYLOAD"
fi
