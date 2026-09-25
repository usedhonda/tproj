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
reject 'remote rejects invalid destination session' 'invalid remote tmux session' --remote paired --remote-session '../dev' --session tproj-workspace --as exact.cc exact.cc hello
reject 'ingress rejects as claim' 'only plain --stdin chat' --remote-ingress --session tproj-workspace --as exact.cc --stdin exact.cc <<<hello
reject 'ingress rejects non-SSH ancestry' 'live SSH session ancestor' --remote-ingress --session tproj-workspace --stdin exact.cc <<<hello
reject 'relay ingress rejects absent listener' 'live relay ancestor' --remote-relay-ingress "$tmp/absent.sock" --session tproj-workspace --stdin exact.cc <<<hello

# A plain alias in this Mac's YAML selects the remote host before local pane
# resolution; an unverified caller must still be refused before SSH sends.
mkdir -p "$tmp/home/.config/tproj" "$tmp/home/bin"
cat > "$tmp/home/.config/tproj/workspace.yaml" <<'EOF'
projects:
  - path: /remote/chi
    type: remote
    host: paired
    alias: chi
EOF
cat > "$tmp/home/bin/tproj-remote-client" <<'EOF'
#!/bin/sh
echo 'running|tproj-remote-cc-test|123'
EOF
chmod +x "$tmp/home/bin/tproj-remote-client"
if HOME="$tmp/home" PATH="$tmp/bin:$PATH" "$msg" --session tproj-workspace --as exact.cc chi.cc hello >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: YAML route accepted an unverified sender' >&2
  exit 1
fi
grep -Fq 'verified local sender' "$tmp/err"
[[ ! -e "$SSH_CALLED_MARKER" ]]
echo 'ok: YAML alias routes remotely but preserves sender verification'

# Exercise the reverse Unix transport with a fake destination program; actual
# target/liveness behavior remains owned by tproj-msg's focused sendability test.
cp "$repo/extensions/messaging/tproj-remote-relay" "$tmp/tproj-remote-relay"
cat > "$tmp/tproj-msg" <<'EOF'
#!/bin/sh
cat > "$CAPTURE_BODY"
printf '%s\n' "$*" > "$CAPTURE_ARGS"
echo 'delivered by destination' >&2
EOF
chmod +x "$tmp/tproj-msg"
export CAPTURE_BODY="$tmp/body" CAPTURE_ARGS="$tmp/args"
python3 "$tmp/tproj-remote-relay" serve --socket "$tmp/local.sock" >"$tmp/server.out" 2>"$tmp/server.err" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true; rm -rf "$tmp"' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [[ -S "$tmp/local.sock" ]] && break
  sleep 0.1
done
[[ -S "$tmp/local.sock" ]] || { cat "$tmp/server.err" >&2; exit 1; }
printf 'hello over live socket' | python3 "$tmp/tproj-remote-relay" send \
  --socket "$tmp/local.sock" --session tproj-workspace --target exact.cc >"$tmp/out" 2>"$tmp/err"
[[ "$(cat "$tmp/body")" == 'hello over live socket' ]]
[[ "$(cat "$tmp/args")" == '--remote-relay-ingress '*" --session tproj-workspace --stdin exact.cc" ]]
echo 'ok: live reverse socket transport'
if printf 'hello' | python3 "$tmp/tproj-remote-relay" send \
    --socket "$tmp/missing.sock" --session tproj-workspace --target exact.cc >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: missing reverse socket accepted' >&2
  exit 1
fi
echo 'ok: missing reverse socket fails closed'

# Replace the fake destination with the real CLI: a live relay ancestor must
# pass authentication and then fail at the exact-session target gate here.
kill "$server_pid"
wait "$server_pid" 2>/dev/null || true
rm -f "$tmp/local.sock" "$tmp/local.sock.pid"
cp "$msg" "$tmp/tproj-msg"
python3 "$tmp/tproj-remote-relay" serve --socket "$tmp/local.sock" >"$tmp/server.out" 2>"$tmp/server.err" &
server_pid=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [[ -S "$tmp/local.sock" ]] && break
  sleep 0.1
done
[[ -S "$tmp/local.sock" ]] || { cat "$tmp/server.err" >&2; exit 1; }
if printf 'hello' | python3 "$tmp/tproj-remote-relay" send \
    --socket "$tmp/local.sock" --session nonexistent-cross-mac-session \
    --target exact.cc >"$tmp/out" 2>"$tmp/err"; then
  echo 'FAIL: missing destination session accepted' >&2
  exit 1
fi
if grep -Fq 'live relay ancestor' "$tmp/err"; then
  echo 'FAIL: relay ancestry was rejected' >&2
  exit 1
fi
if ! grep -Fq 'not a live tmux session' "$tmp/err"; then
  cat "$tmp/err" >&2
  exit 1
fi
echo 'ok: relay ingress reaches exact-session gate'
