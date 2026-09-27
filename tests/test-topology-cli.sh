#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/tproj-topology.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home" TPROJ_TOPOLOGY_CONFIG="$TMP/home/.config/tproj/topology.json"
mkdir -p "$HOME/bin" "$HOME/.config/tproj"
out=$("$ROOT/bin/tproj" topology status --json)
python3 -c 'import json,sys; x=json.loads(sys.argv[1]); assert x["effective_mode"]=="standalone"; assert x["local"]["id"]==x["host_id"]' "$out"
id1=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["host_id"])' "$out")
"$ROOT/bin/tproj" topology set multi >/dev/null
"$ROOT/bin/tproj" host remove no-such >/dev/null
id2=$("$ROOT/bin/tproj" topology status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["host_id"])')
[[ "$id1" == "$id2" ]]
cat > "$TMP/fake-ssh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '{"local":{"id":"remote-stable","display_name":"remote","ssh_alias":null},"host_id":"remote-stable","effective_mode":"standalone","hosts":[],"capabilities":["topology","host-check"]}'
EOF
chmod +x "$TMP/fake-ssh"
mkdir -p "$TMP/bin"
ln -s "$TMP/fake-ssh" "$TMP/bin/ssh"
PATH="$TMP/bin:$PATH" "$ROOT/bin/tproj" host add captain --name "Remote Captain" >/dev/null
python3 -c 'import json,sys; x=json.load(open(sys.argv[1])); assert x["hosts"][0]["id"]=="remote-stable"; assert x["hosts"][0]["ssh_alias"]=="captain"' "$TPROJ_TOPOLOGY_CONFIG"
echo 'PASS topology CLI lifecycle'
