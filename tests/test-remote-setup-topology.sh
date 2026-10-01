#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/tproj-remote-setup.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/remote"
cat > "$TMP/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
host="${@: -2:1}"
if [[ "$*" == *"python3 -"* ]]; then
  script=$(cat)
  if [[ "$script" == *"'tproj_msg'"* ]]; then
    case "$host" in
      match) printf '%s\n' "{\"skills\": {}, \"allow\": [], \"tproj_msg\": \"$TPROJ_REMOTE_WRAPPER_DIGEST\", \"tproj_msg_executable\": true}" ;;
      missing) printf '%s\n' '{"skills": {}, "allow": [], "tproj_msg": null, "tproj_msg_executable": false}' ;;
      nonexec) printf '%s\n' "{\"skills\": {}, \"allow\": [], \"tproj_msg\": \"$TPROJ_REMOTE_WRAPPER_DIGEST\", \"tproj_msg_executable\": false}" ;;
      *) printf '%s\n' '{"skills": {}, "allow": [], "tproj_msg": "old-wrapper-digest", "tproj_msg_executable": true}' ;;
    esac
  fi
  exit 0
fi
if [[ "$*" == *"tar -xf -"* ]]; then
  tar -tf - >"$TPROJ_REMOTE_TAR_LIST"
  exit 0
fi
cat >/dev/null
EOF
chmod +x "$TMP/bin/ssh"
export TPROJ_REMOTE_TAR_LIST="$TMP/tar.list"
export TPROJ_REMOTE_WRAPPER_DIGEST="$(shasum -a 256 "$ROOT/extensions/messaging/tproj-msg" | awk '{print $1}')"
PATH="$TMP/bin:$PATH" "$ROOT/bin/tproj-remote-setup" add captain >"$TMP/out"
grep -q 'Remote helpers installed' "$TMP/out"
grep -qx 'bin/tproj-msg' "$TMP/tar.list"
if PATH="$TMP/bin:$PATH" "$ROOT/bin/tproj-remote-setup" check captain >"$TMP/check.out"; then
  echo 'expected wrapper drift check to fail' >&2
  exit 1
fi
grep -q '~/bin/tproj-msg: differs (CLI drift)' "$TMP/check.out"
PATH="$TMP/bin:$PATH" "$ROOT/bin/tproj-remote-setup" check match >"$TMP/match.out" || true
! grep -q '~/bin/tproj-msg:' "$TMP/match.out"
if PATH="$TMP/bin:$PATH" "$ROOT/bin/tproj-remote-setup" check missing >"$TMP/missing.out"; then exit 1; fi
grep -q '~/bin/tproj-msg: missing' "$TMP/missing.out"
if PATH="$TMP/bin:$PATH" "$ROOT/bin/tproj-remote-setup" check nonexec >"$TMP/nonexec.out"; then exit 1; fi
grep -q '~/bin/tproj-msg: not executable' "$TMP/nonexec.out"
echo 'PASS remote topology setup provisioning path'
