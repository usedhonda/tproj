#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/tproj-remote-client" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$HOME/remote-calls"
printf '%s\n' '{"mode":"solo","main":"cc","lead":"cdx"}'
EOF
cat > "$tmp/bin/router" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$HOME/local-calls"
printf '%s\n' '{"mode":"collab","main":"cdx","lead":"cc"}'
EOF
chmod +x "$tmp/bin/tproj-remote-client" "$tmp/bin/router"

# Load only the two pure lookup functions, without starting background generation.
awk '/^load_conversation_main\(\)/{copy=1} /^translate_gender\(\)/{exit} copy{print}' \
  "$repo/extensions/persona/tproj-pane-bg" > "$tmp/functions.sh"
export HOME="$tmp"
MODEL_ROLE_ROUTER="$tmp/bin/router"
WORK_ROOT="$tmp/work"
safe_name() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }
CONVERSATION_MAIN_CACHE=$'\n'
CONVERSATION_MAIN_RESULT=""
source "$tmp/functions.sh"

load_conversation_main /same/path remote-host /same/path
[[ "$CONVERSATION_MAIN_RESULT" == cc ]]
load_conversation_main /same/path
[[ "$CONVERSATION_MAIN_RESULT" == cdx ]]
load_conversation_main "" remote-host /remote/only
[[ "$CONVERSATION_MAIN_RESULT" == cc ]]
[[ "$(wc -l < "$tmp/remote-calls")" -eq 2 ]]
[[ "$(wc -l < "$tmp/local-calls")" -eq 1 ]]
printf 'PASS  remote main uses the remote router independently of local path\n'

# A removed local checkout must not redirect remote artwork to the SSH client's cwd.
awk '/^resolve_pane_project\(\)/{copy=1} /^SYNC_FAST_HOOKS=/{exit} copy{print}' \
  "$repo/extensions/persona/tproj-pane-bg" > "$tmp/project-functions.sh"
source "$tmp/project-functions.sh"
hash_string() { printf '%s' "$1" | shasum -a 256 | awk '{print $1}'; }
normalize_dir() { [[ -d "$1" ]] && (cd "$1" && pwd -P); }
unset XDG_CACHE_HOME
identity='ssh://fixture-host//missing/remote-project'
cached="$HOME/.cache/tproj-pane-bg/remote/$(hash_string "$identity")"
mkdir -p "$cached/.local/tproj-pane-bg"
[[ "$(resolve_pane_project "$identity" "$tmp")" == "$cached" ]]
if resolve_pane_project 'ssh://other-host//missing/remote-project' "$tmp"; then
  printf 'FAIL  another host or cwd supplied remote artwork\n' >&2
  exit 1
fi
printf 'PASS  remote-only artwork survives local checkout removal and is host scoped\n'
