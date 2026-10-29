#!/usr/bin/env python3
"""Mobile API contract on an isolated tmux server with fake agent executables."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='tproj-mobile-') as temporary:
    root = Path(temporary).resolve(); binary = root/'bin'; binary.mkdir(); home = root/'home'; (home/'bin').mkdir(parents=True)
    helper=binary/'tproj-remote-host';shutil.copy2(ROOT/'bin/tproj-remote-host',helper)
    socket='tproj-mobile-'+uuid.uuid4().hex
    env=dict(os.environ, HOME=str(home), PATH=str(binary)+':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin', TPROJ_TMUX_SOCKET=socket)
    def executable(path,source):path.write_text(source);path.chmod(0o755)
    for name in ['claude','codex']:
        executable(binary/name,'#!/bin/sh\nprintf "%s:%s\\n" "'+name+'" "$*" >> '+str(root/'args')+'\nwhile :; do sleep 1; done\n')
    executable(binary/'npm','#!/bin/sh\nprintf "%s\\n" "$*" >> '+str(root/'updates')+'\n')
    executable(binary/'tproj-cli-update','#!/bin/sh\nif [ "$1" = --launch ]; then exec sh -c "$2"; fi\nnpm update -g "$1"\n')
    executable(home/'bin/tproj-msg-runtime','#!/bin/sh\nsleep .1\nexit 0\n')
    def command(*args):
        p=subprocess.run([str(helper),*args],env=env,capture_output=True,text=True,timeout=40)
        assert p.returncode==0,(args,p.stderr)
        return p.stdout.strip()
    def tmux(*args):return subprocess.check_output(['tmux','-L',socket,*args],env=env,text=True).strip()
    def start(path,operation):return json.loads(command('mobile-ensure','--path',str(path),'--operation',operation,'--fresh','--no-update'))
    try:
        caps=json.loads(command('mobile-capabilities'));assert caps['apiVersion']==1
        assert not (home/'.config/tproj-remote').exists(), 'capability probe wrote state'
        path=root/'first';path.mkdir();operation=str(uuid.uuid4())
        first=start(path,operation);assert first['state']=='created',first
        assert first['messaging']=='bindings_pending', 'tags must not be reported as registered identities'
        time.sleep(.15)
        assert not (root/'updates').exists(),'mobile updated a CLI'
        args=(root/'args').read_text();assert 'claude:\n' in args and 'codex:\n' in args,args
        sessions={role:item['session'] for role,item in first['roles'].items()}
        assert all(name.startswith('tproj-remote-') for name in sessions.values())
        pids={role:tmux('display-message','-p','-t','='+name+':dev','#{pane_pid}') for role,name in sessions.items()}
        assert all(pid.isdigit() for pid in pids.values()),pids
        assert start(path,operation)['state']=='created'
        assert start(path,str(uuid.uuid4()))['state']=='existing'
        assert {r:tmux('display-message','-p','-t','='+s+':dev','#{pane_pid}') for r,s in sessions.items()}==pids
        assert json.loads(command('mobile-operation','--operation',operation))['state']=='created'
        # Normal Mac startup sees the same canonical roles, not a second namespace.
        for role in ['cc','cdx']:
            assert command('ensure','--path',str(path),'--role',role)==sessions[role]
            assert tmux('display-message','-p','-t','='+sessions[role]+':dev','#{pane_pid}')==pids[role]
        # Mobile must find a live alias namespace even when the catalog stores
        # the physical spelling. Ordinary status/ensure remain unchanged.
        physical=root/'physical';physical.mkdir();alias=root/'alias';alias.symlink_to(physical)
        command('register','--path',str(physical),'--alias','physical-project')
        alias_session=command('ensure','--path',str(alias),'--role','cc','--fresh','--no-update')
        alias_result=start(alias,str(uuid.uuid4()))
        assert alias_result['state']=='existing' and alias_result['roles']['cc']['session']==alias_session,alias_result
        assert command('status','--path',str(alias),'--role','cc').startswith('running|'+alias_session+'|')
        # A catalog alias remains the identity when mobile uses its physical path.
        canonical=root/'canonical';canonical.mkdir();link=root/'canonical-link';link.symlink_to(canonical)
        command('register','--path',str(link),'--alias','linked-project')
        linked=start(canonical,str(uuid.uuid4()))
        assert linked['state']=='created' and linked['path']==str(link),linked
        interrupted_id=str(uuid.uuid4());record=home/'.config/tproj-remote/mobile'/(interrupted_id+'.json')
        record.write_text(json.dumps({'operation':interrupted_id,'path':str(canonical),'state':'creating','roles':{}}))
        before=(root/'args').read_text()
        assert json.loads(command('mobile-operation','--operation',interrupted_id))['state']=='interrupted'
        assert start(canonical,interrupted_id)['state']=='interrupted'
        assert (root/'args').read_text()==before,'interrupted operation replayed launch'
        race=root/'race';race.mkdir()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda _:start(race,str(uuid.uuid4())),range(2)))
        assert sum(x['state']=='created' for x in outcomes)==1,outcomes
        assert all(x['state'] in ['created','busy','existing'] for x in outcomes),outcomes
        # Dead/occupied is explicit, never a misleading generic existing success.
        for role,name in sessions.items():
            pane=tmux('display-message','-p','-t','='+name+':dev','#{pane_id}')
            tmux('set-option','-pt',pane,'remain-on-exit','on');os.kill(int(pids[role]),signal.SIGTERM)
        time.sleep(.15)
        dead=start(path,str(uuid.uuid4()));assert dead['state']=='dead',dead
        assert all(tmux('has-session','-t','='+name)=='' for name in sessions.values())
        # Preserve the host's existing login/ensure-all restore policy, including
        # its normal resume/update defaults. Only the mobile request skips them.
        for name in sessions.values():tmux('kill-session','-t','='+name)
        command('ensure-all');time.sleep(.2)
        args=(root/'args').read_text();assert 'claude:--continue' in args and 'codex:resume --last' in args,args
        assert (root/'updates').exists()
        print('PASS: canonical fresh/no-update, operation reconciliation, no tag identity claim, cross-entry dedup, path lock, dead state, normal restore policy')
    finally:
        subprocess.run(['tmux','-L',socket,'kill-server'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
