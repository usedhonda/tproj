#!/bin/bash
# Execute the real reload with isolated destinations and inert service/SSH tools.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/home/lib/tproj-msg-unified" "$TMP/home/bin"
cat > "$TMP/bin/ssh" <<'SSH'
#!/bin/bash
case "${*: -1}" in
  true) exit 0 ;;
  *kai-mcp*) tar tf - > "$ARCHIVE_LIST" ;;
  *'tar xf -'*) tar tf - >/dev/null ;;
  *) exit 0 ;;
esac
SSH
for tool in launchctl sleep; do printf '#!/bin/sh\nexit 0\n' > "$TMP/bin/$tool"; done
printf '#!/bin/sh\nexit 1\n' > "$TMP/bin/osascript"
printf '#!/bin/sh\necho kai\n' > "$TMP/bin/tproj-msg"
printf '#!/bin/sh\nexit 0\n' > "$TMP/bin/tproj-repo"
chmod +x "$TMP/bin/"*
HOME="$TMP/home" ARCHIVE_LIST="$TMP/archive.list" PATH="$TMP/bin:$PATH" \
  bash "$ROOT/bin/tproj-msg-reload" > "$TMP/out"
python3 - "$TMP/archive.list" "$ROOT" <<'PY'
from pathlib import Path
import sys
entries = Path(sys.argv[1]).read_text().splitlines()
required = {'mailbox_tools.py', 'connection.py', 'conversation.py', 'events.py',
            'runtime.py', 'server.py', 'external-assistant-tools.json'}
assert len(entries) == len(set(entries))
assert set(entries) == required, entries
for name in entries:
    assert (Path(sys.argv[2]) / 'extensions/messaging/external/kai-mcp' / name).is_file()
PY
printf '%s\n' "kai-msg actual reload archive entries: PASS (no service or remote activation)"
