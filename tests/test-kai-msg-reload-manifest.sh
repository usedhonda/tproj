#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/bin/tproj-msg-reload"
MANIFEST='mailbox_tools.py connection.py conversation.py events.py runtime.py server.py external-assistant-tools.json'

bash -n "$SCRIPT"
grep -Fq "tar cf - $MANIFEST" "$SCRIPT"
for file in $MANIFEST; do
  test -f "$ROOT/extensions/messaging/external/kai-mcp/$file"
done

printf '%s\n' "kai-msg reload manifest closure: ok"
