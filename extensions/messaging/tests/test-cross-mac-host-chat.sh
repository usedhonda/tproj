#!/bin/bash
set -euo pipefail

repo=$(cd "$(dirname "$0")/../../.." && pwd -P)
msg="$repo/extensions/messaging/tproj-msg"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/ssh" <<'EOF'
#!/bin/sh
echo invoked > "$SSH_CALLED_MARKER"
exit 0
EOF
chmod +x "$tmp/bin/ssh"
export SSH_CALLED_MARKER="$tmp/ssh-called"

reject() {
  local name="$1" expected="$2"
  shift 2
  if PATH="$tmp/bin:$PATH" "$msg" "$@" >"$tmp/out" 2>"$tmp/err"; then
    echo "FAIL: $name accepted" >&2
    exit 1
  fi
  if ! grep -Fq "$expected" "$tmp/err"; then
    echo "FAIL: $name: missing '$expected'" >&2
    cat "$tmp/err" >&2
    exit 1
  fi
  if [[ -e "$SSH_CALLED_MARKER" ]]; then
    echo "FAIL: $name invoked ssh" >&2
    exit 1
  fi
  echo "ok: $name"
}

reject 'remote rejects task control' 'only plain chat' --remote paired --new-task exact.cc hello
reject 'remote requires exact target' 'exact alias.role target' --remote paired cc hello
reject 'remote rejects unverified sender' 'verified local sender' --session tproj-workspace --as exact.cc --remote paired exact.cc hello
reject 'ingress rejects as claim' 'only plain --stdin chat' --remote-ingress --session tproj-workspace --as exact.cc --stdin exact.cc <<<hello
reject 'ingress rejects non-SSH ancestry' 'live SSH session ancestor' --remote-ingress --session tproj-workspace --stdin exact.cc <<<hello
