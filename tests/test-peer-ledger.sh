#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
ledger="$repo/bin/tproj-peer-ledger"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/workspace.yaml" <<'YAML'
projects:
  - path: /local/one
    alias: one
  - path: /remote/two
    type: remote
    host: other-host
    alias: two
    remote_path: /srv/two
  - path: /local/disabled
    alias: two
    enabled: false
YAML
python3 "$ledger" refresh --workspace "$tmp/workspace.yaml" --ledger "$tmp/peers.json" --host this-host > "$tmp/export.json"
python3 - "$tmp/export.json" <<'PY'
import hashlib, json, sys
s=json.load(open(sys.argv[1]))
assert s['revision'] == 1 and len(s['projects']) == 2
assert s['projects'][1]['remote_path'] == '/srv/two'
expected=hashlib.sha256(json.dumps(['other-host','/srv/two'],separators=(',',':')).encode()).hexdigest()[:24]
assert s['projects'][1]['project_id'] == 'p-' + expected
PY
python3 "$ledger" resolve two --ledger "$tmp/peers.json" > "$tmp/resolved.json"
python3 - "$tmp/resolved.json" <<'PY'
import json, sys
p=json.load(open(sys.argv[1]))
assert p['host'] == 'other-host' and p['alias'] == 'two'
PY
id=$(python3 - "$tmp/resolved.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))['project_id'])
PY
)
python3 "$ledger" resolve "$id" --ledger "$tmp/peers.json" > /dev/null
python3 "$ledger" refresh --workspace "$tmp/workspace.yaml" --ledger "$tmp/peers.json" --host this-host > "$tmp/same.json"
cmp "$tmp/export.json" "$tmp/same.json"
python3 "$ledger" export --ledger "$tmp/peers.json" | python3 "$ledger" import --stdin --ledger "$tmp/imported.json"
cmp "$tmp/peers.json" "$tmp/imported.json"
cat >> "$tmp/workspace.yaml" <<'YAML'
  - path: /local/three
    alias: three
YAML
python3 "$ledger" refresh --workspace "$tmp/workspace.yaml" --ledger "$tmp/peers.json" --host this-host > "$tmp/new.json"
python3 - "$tmp/new.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))['revision'] == 2
PY
if python3 "$ledger" import --stdin --ledger "$tmp/peers.json" < "$tmp/export.json" 2>/dev/null; then
  echo 'FAIL: stale import accepted' >&2; exit 1
fi
cat >> "$tmp/workspace.yaml" <<'YAML'
  - path: /local/four
    alias: two
YAML
if python3 "$ledger" refresh --workspace "$tmp/workspace.yaml" --ledger "$tmp/peers.json" --host this-host >/dev/null 2>&1; then
  echo 'FAIL: duplicate alias accepted' >&2; exit 1
fi
cmp "$tmp/peers.json" "$tmp/new.json"
mkdir -p "$tmp/bin"
cat > "$tmp/bin/tmux" <<'TMUX'
#!/bin/sh
printf '/local/disabled\n'
TMUX
chmod +x "$tmp/bin/tmux"
cat > "$tmp/live.yaml" <<'YAML'
projects:
  - path: /local/disabled
    alias: disabled
    enabled: false
YAML
PATH="$tmp/bin:$PATH" python3 "$ledger" refresh --workspace "$tmp/live.yaml" --ledger "$tmp/live.json" --host this-host > "$tmp/live.out"
python3 - "$tmp/live.out" <<'PY'
import json, sys
assert [p['alias'] for p in json.load(open(sys.argv[1]))['projects']] == ['disabled']
PY
echo 'PASS: peer ledger projection, resolve, revision, import, duplicate rejection'
