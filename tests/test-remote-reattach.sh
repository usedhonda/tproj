#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
python3 - "$repo" <<'TEST'
import os, pathlib, subprocess, sys, tempfile
with tempfile.TemporaryDirectory() as root:
    root=pathlib.Path(root); (root/'bin').mkdir(); (root/'project').mkdir()
    fake=root/'bin/tmux'
    fake.write_text("""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$TEST_CALLS"
case "$1" in
 has-session) [[ "$TEST_EXISTS" == yes ]] ;;
 list-panes) printf '%%7|%s|%s\n' "$TEST_ROLE" "$TEST_PROJECT" ;;
 display-message) printf '0\n' ;;
 attach-session) exit 0 ;;
 *) echo 'unexpected mutation' >&2; exit 99 ;;
esac
""")
    fake.chmod(0o755)
    for role,tag in [('cc','claude-p1'),('cdx','codex-p1')]:
        for exists in ['yes','no']:
            log=root/'calls'; log.write_text('')
            env=dict(os.environ,HOME=str(root),PATH=str(root/'bin')+':'+os.environ['PATH'],TEST_CALLS=str(log),TEST_EXISTS=exists,TEST_ROLE=tag,TEST_PROJECT=str(root/'project'))
            env.pop('TPROJ_TMUX_SOCKET',None)
            result=subprocess.run([str(pathlib.Path(sys.argv[1])/'bin/tproj-remote-host'),'reattach','--path',str(root/'project'),'--role',role],env=env,capture_output=True,text=True)
            calls=log.read_text().splitlines()
            assert (result.returncode==0)==(exists=='yes'),result.stderr
            assert any(x.startswith('attach-session ') for x in calls)==(exists=='yes'),calls
            assert all(x.split()[0] in ['has-session','list-panes','display-message','attach-session'] for x in calls),calls
            assert not (root/'.config/tproj-remote').exists()
print('PASS: CC/Cdx reattach existing only; missing session never starts or registers')
TEST
