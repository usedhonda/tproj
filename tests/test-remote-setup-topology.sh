#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/tproj-remote-setup.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/remote"
cat > "$TMP/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
host="${@: -1}"
if [[ "$*" == *"launchctl"* ]]; then exit 0; fi
cat >/dev/null
exit 0
EOF
chmod +x "$TMP/bin/ssh"
PATH="$TMP/bin:$PATH" "$ROOT/bin/tproj-remote-setup" add captain >"$TMP/out"
grep -q 'Remote helper installed' "$TMP/out"
echo 'PASS remote topology setup provisioning path'
