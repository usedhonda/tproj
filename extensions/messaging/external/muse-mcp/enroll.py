#!/usr/bin/env python3
"""Prepare/apply/check a read-only Muse enrollment; never starts services."""
from __future__ import annotations
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import shlex
import socket
import tempfile

SHARED_FILES = ('mailbox_tools.py', 'connection.py', 'conversation.py', 'events.py',
                'runtime.py', 'server.py', 'external-assistant-tools.json')


class EnrollmentError(RuntimeError):
    pass


def read(path):
    if path.is_symlink():
        raise EnrollmentError('symlink rejected')
    with path.open('rb') as stream:
        stat = os.fstat(stream.fileno())
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise EnrollmentError('private owner-only file required')
        value = json.load(stream)
    if not isinstance(value, dict):
        raise EnrollmentError('configuration object required')
    return value


def atomic(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise EnrollmentError('symlink rejected')
    if path.exists() and path.read_bytes() == data and path.stat().st_mode & 0o777 == mode:
        return
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, mode); os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2)+'\n').encode()


def service(parent):
    return dict(participant_id=parent['participant_id'], address='muse', platform='muse',
        token=parent['service_token'], binding_generation=parent['binding_generation'],
        launchd_label='local.tproj.muse-mailbox', allowed_addresses=parent['allowed_addresses'],
        read_only=parent['read_only'])


def prepare(home, host_path, root, scope):
    cfg = read(host_path)
    if root.is_symlink():
        raise EnrollmentError('symlink rejected')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_mode & 0o077:
        raise EnrollmentError('private enrollment directory required')
    parent_path = root/'parent.json'
    if parent_path.exists():
        parent = read(parent_path)
        if parent.get('allowed_addresses') != scope or parent.get('read_only') is not True:
            raise EnrollmentError('existing candidate scope differs; nothing changed')
    else:
        if 'muse' in cfg.get('services', {}):
            raise EnrollmentError('existing Muse enrollment has no matching private candidate')
        parent = dict(service_id='muse', address='muse', participant_id='muse-service',
            service_token=secrets.token_urlsafe(32), binding_generation=secrets.token_urlsafe(32),
            allowed_addresses=scope, read_only=True, host_socket=cfg['socket'],
            bridge_socket=str(root/'mailbox.sock'))
    candidate = service(parent)
    for sid, prior in [*cfg.get('services', {}).items(), *([('openclaw',cfg['service'])] if cfg.get('service') else [])]:
        if sid != 'muse' and (prior.get('address') == candidate['address']
                             or prior.get('participant_id') == candidate['participant_id']):
            raise EnrollmentError('service identity collision; nothing changed')
    existing = cfg.get('services', {}).get('muse')
    if existing is not None and existing != candidate:
        raise EnrollmentError('existing Muse enrollment differs; nothing changed')
    source = Path(__file__).resolve().parent
    expected = {root/'lib/kai-mcp'/name:(source.parent/'kai-mcp'/name).read_bytes()
                for name in SHARED_FILES}
    expected[root/'lib/muse-mcp/muse.py'] = (source/'muse.py').read_bytes()
    child = {key:parent[key] for key in ('service_id','address','participant_id','bridge_socket','read_only')}
    expected[root/'parent.json'] = encoded(parent)
    expected[root/'client.json'] = encoded(child)
    label = dict(Label='local.tproj.muse-mailbox',
        ProgramArguments=['/usr/bin/python3','-I',str(root/'lib/muse-mcp/muse.py'),
                          '--config',str(parent_path),'--bridge'],
        RunAtLoad=True, KeepAlive=True, ThrottleInterval=10,
        StandardErrorPath=str(root/'mailbox.err'))
    expected[root/'muse-mailbox.plist'] = plistlib.dumps(label)
    manifest_path = root/'candidate.json'
    manifest = read(manifest_path) if manifest_path.exists() else dict(
        host_before=hashlib.sha256(host_path.read_bytes()).hexdigest(), phase='prepared')
    for path, data in expected.items():
        atomic(path, data)
    atomic(manifest_path, encoded(manifest))
    return {'prepared': True, 'read_only': True, 'scope_count':len(scope), 'host_changed':False}




def rpc(path, request):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5);client.connect(path)
        client.sendall((json.dumps(request,separators=(',',':'))+'\n').encode())
        with client.makefile('rb') as stream:raw=stream.readline(262145)
    if len(raw)>262144 or not raw.endswith(b'\n'):
        raise EnrollmentError('invalid local service response')
    response=json.loads(raw)
    if not response.get('ok'):
        raise EnrollmentError('local enrollment operation rejected')
    return response.get('result',{})


def host_ready(config):
    if 'service_generation_v1' not in rpc(config['socket'],{'op':'messaging_capabilities'}).get('host_capabilities',[]):
        raise EnrollmentError('load the generation-capable Host before enrollment')


def register_participant(config, hub_path, check=False):
    """Use the owning Hub API, never direct database writes or foreign aliases."""
    hub=read(hub_path)
    if hub.get('host_id') != config.get('host_id'):
        raise EnrollmentError('Host and Hub owner differ')
    catalog=rpc(config['socket'],{'op':'directory'})
    matching=[row for row in catalog.get('participants',[])
              if row.get('address')=='muse' or row.get('participant_id')=='muse-service']
    expected=dict(participant_id='muse-service',address='muse',host_id=config['host_id'],kind='muse')
    if matching:
        if len(matching)!=1 or any(matching[0].get(k)!=v for k,v in expected.items()) or matching[0].get('project_id') is not None:
            raise EnrollmentError('participant namespace collision; nothing changed')
        if matching[0].get('endpoints') and 'muse' not in config.get('services',{}):
            raise EnrollmentError('active participant has no matching enrollment; nothing changed')
        return True
    if check:return False
    rpc(hub['socket'],dict(op='directory_import',admin_token=hub['admin_token'],services=[expected]))
    return True


def apply(host_path, root, check=False, hub_path=None):
    parent = read(root/'parent.json'); expected = service(parent)
    if parent.get('read_only') is not True:
        raise EnrollmentError('P1 must remain read-only')
    manifest = read(root/'candidate.json')
    cfg = read(host_path)
    hub_path = hub_path or host_path.parent/'msg-hub.json'
    host_ready(cfg)
    current = cfg.get('services', {}).get('muse')
    if current == expected:
        if not register_participant(cfg,hub_path,check=check):
            raise EnrollmentError('matching directory participant is missing')
        return {'enrolled':True, 'changed':False, 'read_only':True}
    if current is not None:
        raise EnrollmentError('registered Muse differs; nothing changed')
    if check:
        return {'enrolled':False, 'changed':False, 'prepared':True}
    if hashlib.sha256(host_path.read_bytes()).hexdigest() != manifest['host_before']:
        raise EnrollmentError('Host configuration changed since preparation; nothing changed')
    fd = os.open(str(host_path)+'.muse-enroll.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if read(host_path) != cfg:
            raise EnrollmentError('Host configuration changed; nothing changed')
        # A directory-only partial registration has no endpoint or client
        # credential access. Reapplying resumes it idempotently.
        register_participant(cfg,hub_path)
        if read(host_path) != cfg:
            raise EnrollmentError('Host changed; directory registration may be prepared')
        # Preserve every existing service and configuration field verbatim in value.
        atomic(root/'host-before.json', host_path.read_bytes())
        cfg.setdefault('services',{})['muse'] = expected
        atomic(host_path,encoded(cfg))
    atomic(root/'candidate.json',encoded(dict(manifest,phase='enrolled')))
    return {'enrolled':True,'changed':True,'read_only':True}


def key_enrollment(host_path, root, hub_path=None):
    """Check an existing enrollment without reverting its approved write policy."""
    parent = read(root/'parent.json')
    if type(parent.get('read_only')) is not bool:
        raise EnrollmentError('explicit enrollment policy required')
    client = read(root/'client.json')
    expected = {k: parent[k] for k in ('service_id','address','participant_id','bridge_socket','read_only')}
    if client != expected or parent.get('service_id') != 'muse' or parent.get('address') != 'muse':
        raise EnrollmentError('tokenless client differs from parent')
    config = read(host_path)
    host_ready(config)
    if config.get('services', {}).get('muse') != service(parent):
        raise EnrollmentError('registered Muse differs; nothing changed')
    if not register_participant(config, hub_path or host_path.parent/'msg-hub.json', check=True):
        raise EnrollmentError('matching directory participant is missing')
    return True


def install_key(home, root, public_key_path):
    """Register only a dedicated public key; never creates/reads a private key."""
    client = read(root/'client.json')
    if type(client.get('read_only')) is not bool:
        raise EnrollmentError('explicit client policy required')
    lines = public_key_path.read_text().strip().splitlines()
    parts = lines[0].split() if len(lines)==1 else []
    if len(parts) < 2 or parts[0] != 'ssh-ed25519':
        raise EnrollmentError('one dedicated Ed25519 public key required')
    try: raw = base64.b64decode(parts[1],validate=True)
    except ValueError: raise EnrollmentError('invalid public key') from None
    if len(raw) != 51 or raw[:19] != bytes.fromhex('0000000b')+b'ssh-ed25519'+bytes.fromhex('00000020'):
        raise EnrollmentError('invalid Ed25519 public key')
    command = 'exec /usr/bin/python3 -I '+shlex.quote(str(root/'lib/muse-mcp/muse.py'))+' --config '+shlex.quote(str(root/'client.json'))
    quoted = command.replace('\\','\\\\').replace('"','\\"')
    entry='restrict,command="'+quoted+'" '+parts[0]+' '+parts[1]+' tproj-muse\n'
    ssh=home/'.ssh'
    if ssh.is_symlink():
        raise EnrollmentError('symlink rejected')
    ssh.mkdir(mode=0o700,exist_ok=True)
    target=ssh/'authorized_keys'
    if target.is_symlink():
        raise EnrollmentError('symlink rejected')
    original=target.read_text() if target.exists() else ''
    matches=[line for line in original.splitlines() if parts[1] in line.split()]
    if matches:
        if matches == [entry.rstrip('\n')]:
            return {'key_installed':True,'changed':False}
        raise EnrollmentError('key already has another grant; management keys cannot be reused')
    if ssh.stat().st_uid != os.getuid() or ssh.stat().st_mode & 0o077:
        raise EnrollmentError('owner-only SSH directory required')
    if target.exists() and (target.stat().st_uid != os.getuid() or target.stat().st_mode & 0o077):
        raise EnrollmentError('owner-only authorized keys required')
    fd=os.open(str(target)+'.tproj-muse.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (target.read_text() if target.exists() else '') != original:
            raise EnrollmentError('authorized keys changed; nothing changed')
        atomic(root/'authorized-keys-before',original.encode())
        atomic(target,(original+('' if not original or original.endswith('\n') else '\n')+entry).encode())
    return {'key_installed':True,'changed':True}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    for name in ('prepare','apply','check','install-key'):mode.add_argument('--'+name,action='store_true')
    p.add_argument('--home',type=Path,default=Path.home())
    p.add_argument('--host-config',type=Path)
    p.add_argument('--hub-config',type=Path)
    p.add_argument('--root',type=Path)
    scope=p.add_mutually_exclusive_group()
    scope.add_argument('--allow-address',action='append')
    scope.add_argument('--empty-scope',action='store_true')
    p.add_argument('--public-key-file',type=Path)
    args=p.parse_args(argv)
    root=args.root or args.home/'.local/share/tproj/muse-mailbox'
    host=args.host_config or args.home/'.config/tproj/msg-host.json'
    try:
        if args.prepare:
            if args.allow_address is None and not args.empty_scope:
                raise EnrollmentError('operator must choose an explicit initial scope')
            targets=args.allow_address or []
            if len(set(targets)) != len(targets) or any(not x or x in ('cc','cdx') or '/' in x or any(c.isspace() for c in x) for x in targets):
                raise EnrollmentError('qualified unique addresses required')
            result=prepare(args.home,host,root,targets)
        elif args.install_key:
            if not args.public_key_file:raise EnrollmentError('dedicated VM public key required')
            key_enrollment(host,root,hub_path=args.hub_config)
            result=install_key(args.home,root,args.public_key_file)
        else:result=apply(host,root,check=args.check,hub_path=args.hub_config)
        print(json.dumps(result));return 0
    except EnrollmentError as exc:
        print('Muse enrollment unavailable: '+str(exc),file=os.sys.stderr);return 2
    except (OSError,ValueError,KeyError) as exc:
        print('Muse enrollment unavailable: '+type(exc).__name__,file=os.sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
