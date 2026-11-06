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
  *dots-event-probe*) tar tf - > "$ARCHIVE_LIST.probe" ;;
  *dots-mcp*) tar tf - > "$ARCHIVE_LIST" ;;
  *'tar xf -'*) tar tf - >/dev/null ;;
  *) exit 0 ;;
esac
SSH
for tool in launchctl sleep; do printf '#!/bin/sh\nexit 0\n' > "$TMP/bin/$tool"; done
cat > "$TMP/bin/osascript" <<'OSA'
#!/bin/bash
case "$*" in
  *javascript*)
    printf 'click\n' >> "$UI_CLICKS"
    case "$*" in *refresh_requested*) echo refresh_requested ;; *) echo refreshed ;; esac ;;
  *) exit 0 ;;
esac
OSA
printf '#!/bin/sh\necho dots\n' > "$TMP/bin/tproj-msg"
printf '#!/bin/sh\nexit 0\n' > "$TMP/bin/tproj-repo"
chmod +x "$TMP/bin/"*
mkdir -p "$TMP/home/.config/tproj"
printf '%s\n' '{"remote":"fixture","app":"fixture-app"}' > "$TMP/home/.config/tproj/msg-reload.json"
HOME="$TMP/home" ARCHIVE_LIST="$TMP/archive.list" UI_CLICKS="$TMP/clicks" PATH="$TMP/bin:$PATH" \
  bash "$ROOT/bin/tproj-msg-reload" > "$TMP/out"
python3 - "$TMP/archive.list" "$ROOT" "$TMP/out" "$TMP/clicks" <<'PY'
from pathlib import Path
import sys
output = Path(sys.argv[3]).read_text()
assert 'dots: refresh_requested' in output and 'callable activation unverified' in output, output
assert 'dots: refreshed' not in output
assert Path(sys.argv[4]).read_text().splitlines() == ['click']
entries = Path(sys.argv[1]).read_text().splitlines()
assert Path(sys.argv[1] + ".probe").read_text().splitlines() == ["server.py"]
required = {'mailbox_tools.py', 'connection.py', 'conversation.py', 'events.py',
            'runtime.py', 'server.py', 'external-assistant-tools.json'}
assert len(entries) == len(set(entries))
assert set(entries) == required, entries
for name in entries:
    assert (Path(sys.argv[2]) / 'extensions/messaging/external/dots-mcp' / name).is_file()
PY
printf '%s\n' "Dots MSG actual reload archive entries: PASS (no service or remote activation)"
