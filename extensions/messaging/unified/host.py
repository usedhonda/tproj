"""Local caller-bound mailbox adapter. No GUI or agent lifecycle ownership."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import sys
import socket
import sqlite3
import subprocess
import time
import uuid

from identity import IdentityError, bind_caller, discover_endpoints, peer_credentials
from protocol import HubError, success, failure
from receipt import normalize_prompt

WIRE_LIMIT = 262144


def paste_parts(platform, header, body):
    # Codex paste coalescing replaces preceding literal keystrokes; Claude's
    # pasted_content wrapper instead hides the role marker if it is pasted.
    return ('', header + body) if platform == 'cdx' else (header, body)


def rpc(path, request):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5)
        sock.connect(str(path))
        sock.sendall((json.dumps(request, ensure_ascii=False) + '\n').encode())
        with sock.makefile('rb') as stream:
            raw = stream.readline(WIRE_LIMIT + 1)
        if len(raw) > WIRE_LIMIT or not raw.endswith(b'\n'):
            raise HubError('unavailable', 'invalid hub response')
        response = json.loads(raw)
        if not response.get('ok'):
            error = response.get('error', {})
            raise HubError(error.get('code', 'unavailable'), error.get('message', 'hub unavailable'))
        return response.get('result')


class Host:
    def __init__(self, config):
        self.config = config
        self.endpoints = []
        self.refreshed = 0
        self.db = sqlite3.connect(config['journal'])
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS deliveries(message_id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL,
        envelope TEXT NOT NULL, state TEXT NOT NULL, prompt_hash TEXT, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS submissions(message_id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL,
        envelope TEXT NOT NULL);''')
        # A process exit in the injection window must never trigger another injection.
        self.db.execute("UPDATE deliveries SET state='uncertain' WHERE state='dispatching'")
        self.db.commit()

    def hub(self, op, **args):
        return rpc(self.config['hub_socket'], dict(args, op=op,
                   host_id=self.config['host_id'], host_token=self.config['host_token']))

    def refresh(self):
        directory = self.hub('directory_list')
        discovered = discover_endpoints(self.config.get('registry', str(Path.home()/'.cache/tproj-model-role')),
                                        self.config['host_id'], directory['projects'])
        for ep in discovered:
            self.hub('endpoint_register', **ep)
        # A disappeared process is not inferred from an alias. Retire only after
        # a matching participant has a proven different live incarnation.
        previous = self.hub('endpoints_list')['endpoints']
        live_ids = {ep['endpoint_id'] for ep in discovered}
        live_participants = {ep['participant_id'] for ep in discovered}
        for ep in previous:
            if ep['endpoint_id'] not in live_ids and ep['participant_id'] in live_participants and not ep['retired']:
                self.hub('endpoint_retire', endpoint_id=ep['endpoint_id'])
        self.endpoints = discovered
        self.refreshed = time.monotonic()

    def caller(self, pid, uid, req):
        if not self.endpoints or time.monotonic() - self.refreshed >= 10:
            self.refresh()
        try:
            return bind_caller(pid, uid, self.endpoints, session=req.get('session'), claimed_alias=req.get('as'))
        except IdentityError as exc:
            raise HubError('identity_rejected', str(exc)) from exc

    def service(self, pid, uid, req):
        cfg = self.config.get('service') or {}
        if uid != os.getuid() or not cfg.get('token') or not secrets.compare_digest(str(req.get('service_token', '')), cfg['token']):
            raise HubError('identity_rejected', 'invalid service credential')
        if req.get('address', cfg['address']) != cfg['address']:
            raise HubError('identity_rejected', 'service address mismatch')
        label = cfg.get('launchd_label')
        if not label:
            raise HubError('identity_rejected', 'service launchd binding required')
        listing = subprocess.run(['/bin/launchctl', 'list', label], capture_output=True, text=True, timeout=2)
        match = re.search(r'"PID"\s*=\s*(\d+)', listing.stdout)
        if listing.returncode or not match or int(match.group(1)) != pid:
            raise HubError('identity_rejected', 'caller is not the registered main service process')
        # Credentials are scoped to this participant only. Bind incarnation to
        # kernel peer process start, never to caller-supplied identity fields.
        from identity import _process_info
        info = _process_info(pid)
        start = info['pid_start']
        ep = dict(endpoint_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.config['host_id']}:{cfg['participant_id']}:{pid}:{start}")),
                  participant_id=cfg['participant_id'], host_id=self.config['host_id'],
                  session=cfg['address'], pane='', pid=pid, pid_start=start,
                  runtime_id=f'{pid}:{start}', platform='openclaw', address=cfg['address'])
        for old in self.hub('endpoints_list')['endpoints']:
            if old['participant_id'] == ep['participant_id'] and old['endpoint_id'] != ep['endpoint_id'] and not old['retired']:
                self.hub('endpoint_retire', endpoint_id=old['endpoint_id'])
        self.hub('endpoint_register', **ep)
        return ep

    def submit(self, ep, req, reply=False):
        mid = req.get('submission_id')
        if not isinstance(mid, str) or not mid or len(mid) > 128:
            raise HubError('invalid_message', 'persisted submission_id required')
        envelope = dict(message_id=mid, sender_endpoint=ep['endpoint_id'], body=req.get('body', ''), kind='chat')
        if reply:
            original = self.hub('query', endpoint_id=ep['endpoint_id'], message_id=req['message_id'])
            if original['recipient_endpoint'] != ep['endpoint_id']:
                raise HubError('identity_rejected', 'not original recipient')
            envelope.update(in_reply_to=original['message_id'], thread_id=original['thread_id'])
        else:
            envelope['target'] = req.get('target')
        serialized = json.dumps(envelope, sort_keys=True, ensure_ascii=False)
        old = self.db.execute('SELECT * FROM submissions WHERE message_id=?', (mid,)).fetchone()
        if old and (old['envelope'] != serialized or old['endpoint_id'] != ep['endpoint_id']):
            raise HubError('id_conflict', 'submission ID has different payload or sender')
        self.db.execute('INSERT OR IGNORE INTO submissions VALUES(?,?,?)', (mid, ep['endpoint_id'], serialized))
        self.db.commit()
        return self.hub('submit', message=envelope)

    def dispatch(self, req, pid, uid):
        op = req.get('op')
        if uid != os.getuid():
            raise HubError('identity_rejected', 'local UID mismatch')
        if op == 'status' and req.get('target'):
            target = req['target']
            participant_id = None
            if target in ('cc', 'cdx'):
                sender = self.caller(pid, uid, req)
                participant_id = sender['project_id'] + ':' + target
            directory = self.hub('directory_list')
            matches = [p for p in directory['participants']
                       if (p['participant_id'] == participant_id if participant_id else p['address'] == target)]
            if len(matches) != 1:
                raise HubError('unknown_target', 'unknown or ambiguous target')
            return matches[0]
        if op in ('list', 'status', 'directory'):
            # Read-only catalog for operator/GUI; no caller can mutate identity.
            return self.hub('directory_list')
        if op == 'directory-sync':
            return self.hub('directory_update', projects=req['projects'], expected_revision=req['expected_revision'])
        is_service = isinstance(op, str) and op.startswith('service_')
        ep = self.service(pid, uid, req) if is_service else self.caller(pid, uid, req)
        if op in ('send', 'reply', 'service_send', 'service_reply'):
            return self.submit(ep, req, reply=op.endswith('reply'))
        if op == 'service_claim':
            return self.hub('claim', endpoint_id=ep['endpoint_id'], limit=min(int(req.get('limit', 8)), 32))
        if op == 'service_receipt':
            return self.hub('receipt', endpoint_id=ep['endpoint_id'], message_id=req['message_id'],
                            state=req['state'], evidence=json.dumps(req.get('evidence', {})))
        if op == 'inbox':
            return self.hub('inbox', endpoint_id=ep['endpoint_id'],
                            cursor=req.get('cursor', 0), limit=req.get('limit', 100))
        if op == 'message':
            return self.hub('query', endpoint_id=ep['endpoint_id'], message_id=req['message_id'])
        if op == 'ack':
            message = self.hub('query', endpoint_id=ep['endpoint_id'], message_id=req['message_id'])
            if message['recipient_endpoint'] != ep['endpoint_id']:
                raise HubError('identity_rejected', 'only recipient may acknowledge')
            self.db.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?)',
                            (message['message_id'], ep['endpoint_id'], json.dumps(message), 'presented', None, time.time()))
            self.db.execute("UPDATE deliveries SET state='presented' WHERE message_id=?", (message['message_id'],))
            self.db.commit()
            return self.hub('receipt', endpoint_id=ep['endpoint_id'], message_id=message['message_id'],
                            state='presented', evidence='bound recipient explicit acknowledgement after inbox consumption')
        if op == 'prompt_receipt':
            row = self.db.execute('SELECT * FROM deliveries WHERE message_id=?', (req.get('message_id'),)).fetchone()
            digest = hashlib.sha256(normalize_prompt(str(req.get('prompt', ''))).encode()).hexdigest()
            if not row or row['endpoint_id'] != ep['endpoint_id'] or row['prompt_hash'] != digest:
                raise HubError('identity_rejected', 'prompt does not match pinned delivery')
            if req.get('runtime_id') != ep['runtime_id']:
                raise HubError('identity_rejected', 'prompt runtime mismatch')
            self.db.execute("UPDATE deliveries SET state='presented',updated=? WHERE message_id=?", (time.time(), row['message_id']))
            self.db.commit()
            return self.hub('receipt', endpoint_id=ep['endpoint_id'], message_id=row['message_id'], state='presented', evidence='bound UserPromptSubmit exact prompt hash')
        raise HubError('unknown_op', 'unsupported host operation')

    def delivery_tick(self):
        if time.monotonic() - self.refreshed >= 10:
            self.refresh()
        if not self.config.get('delivery_enabled', False):
            return
        for ep in self.endpoints:
            claims = self.hub('claim', endpoint_id=ep['endpoint_id'], limit=1)['messages']
            claimed_ids = {m['message_id'] for m in claims}
            for pending in self.db.execute("SELECT envelope,message_id FROM deliveries WHERE endpoint_id=? AND state='uncertain'", (ep['endpoint_id'],)):
                if pending['message_id'] not in claimed_ids:
                    claims.append(json.loads(pending['envelope']))
            for msg in claims:
                mid = msg['message_id']
                self.db.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?)',
                                (mid, ep['endpoint_id'], json.dumps(msg), 'received', None, time.time()))
                self.db.commit()
                row = self.db.execute('SELECT * FROM deliveries WHERE message_id=?', (mid,)).fetchone()
                if row['state'] in ('dispatching', 'uncertain') and ep['platform'] == 'cc':
                    for transcript in (Path.home()/'.claude/projects').glob('*/'+ep['runtime_id']+'.jsonl'):
                        try:
                            with transcript.open('rb') as handle:
                                handle.seek(max(0, transcript.stat().st_size - 262144))
                                tail = handle.read().decode(errors='replace')
                            for line in tail.splitlines():
                                try: event = json.loads(line)
                                except ValueError: continue
                                content = event.get('message', {}).get('content')
                                if event.get('type') == 'user' and isinstance(content, str):
                                    digest = hashlib.sha256(normalize_prompt(content).encode()).hexdigest()
                                    if digest == row['prompt_hash']:
                                        self.db.execute("UPDATE deliveries SET state='presented' WHERE message_id=?", (mid,)); self.db.commit()
                                        self.hub('receipt', endpoint_id=ep['endpoint_id'], message_id=mid, state='presented', evidence='bound Claude transcript exact prompt hash')
                                        break
                        except OSError: pass
                    row = self.db.execute('SELECT * FROM deliveries WHERE message_id=?', (mid,)).fetchone()
                if row['state'] in ('uncertain', 'presented'):
                    self.hub('receipt', endpoint_id=ep['endpoint_id'], message_id=mid, state=row['state'], evidence='durable local journal')
                    continue
                if row['state'] == 'dispatching':
                    if time.time() - row['updated'] > 30:
                        self.db.execute("UPDATE deliveries SET state='uncertain' WHERE message_id=?", (mid,)); self.db.commit()
                    continue
                # Revalidate this exact process incarnation immediately before terminal access.
                from identity import _process_info
                try:
                    current = _process_info(ep['pid'])
                    if current['pid_start'] != ep['pid_start']:
                        continue
                except (IdentityError, OSError):
                    continue
                cache_kind = 'cc-cache' if ep['platform'] == 'cc' else 'codex-cache'
                cache_path = Path.home()/'.local/state/tproj'/cache_kind/(hashlib.sha256(ep['runtime_id'].encode()).hexdigest()+'.json')
                try:
                    observed = json.loads(cache_path.read_text())
                    if observed.get('pane_id') == ep['pane'] and (observed.get('turn_state') == 'running' or observed.get('event') == 'prompt'):
                        continue
                except (OSError, ValueError): pass
                guard = subprocess.run(['bash', str(Path(__file__).with_name('terminal-guard.sh')), ep['pane']], capture_output=True, timeout=5)
                if guard.returncode:
                    continue
                # Resolve displayed sender from the hub, never from a stale local alias copy.
                sender = msg.get('sender_address') or msg['sender_endpoint']
                if sender == 'gate':
                    sender = 'OpenClaw Agent - Main'
                header = f"[from:{sender}] [tproj-message:{mid}] "
                body = f"{msg['body']}\n\nReply to this message with: tproj-msg reply {mid} --stdin"
                prompt = header + body
                self.db.execute("UPDATE deliveries SET state='dispatching',prompt_hash=?,updated=? WHERE message_id=?",
                                (hashlib.sha256(prompt.encode()).hexdigest(), time.time(), mid)); self.db.commit()
                try:
                    buffer = 'tproj-msg-' + hashlib.sha256(mid.encode()).hexdigest()[:24]
                    # Codex paste coalescing can replace immediately preceding
                    # literal keystrokes. Keep its complete envelope in one paste.
                    # Claude needs the sender outside its pasted_content wrapper.
                    literal, pasted = paste_parts(ep['platform'], header, body)
                    if literal:
                        subprocess.run(['tmux', 'send-keys', '-t', ep['pane'], '-l', '--', literal], check=True, timeout=5, capture_output=True)
                    subprocess.run(['tmux', 'load-buffer', '-b', buffer, '-'], input=pasted.encode(), check=True, timeout=5, capture_output=True)
                    subprocess.run(['tmux', 'paste-buffer', '-p', '-d', '-b', buffer, '-t', ep['pane']], check=True, timeout=5, capture_output=True)
                    time.sleep(0.5)
                    subprocess.run(['tmux', 'send-keys', '-t', ep['pane'], 'Enter'], check=True, timeout=5, capture_output=True)
                except (subprocess.SubprocessError, OSError):
                    self.db.execute("UPDATE deliveries SET state='uncertain' WHERE message_id=?", (mid,)); self.db.commit()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--config', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    config = json.loads(Path(args.config).read_text())
    path = Path(config['socket']); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Lock prevents replacing a live adapter's socket during a mistaken launch.
    lock = open(str(path)+'.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path.unlink(missing_ok=True)
    host = Host(config)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path)); os.chmod(path, 0o600); server.listen(16); server.settimeout(1)
        while True:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                try: host.delivery_tick()
                except (OSError, HubError, ValueError, subprocess.SubprocessError): pass
                continue
            with conn:
                conn.settimeout(5)
                try:
                    pid, uid = peer_credentials(conn)
                    with conn.makefile('rwb') as stream:
                        raw = stream.readline(WIRE_LIMIT+1)
                        if len(raw) > WIRE_LIMIT or not raw.endswith(b'\n'):
                            raise HubError('invalid_request', 'request too large')
                        request = json.loads(raw)
                        try: result = success(host.dispatch(request, pid, uid))
                        except (HubError, IdentityError) as exc:
                            result = failure(exc if isinstance(exc, HubError) else HubError('identity_rejected', str(exc)))
                        except Exception as exc:
                            print("host dispatch failure: " + type(exc).__name__, file=sys.stderr, flush=True)
                            result = failure(HubError('unavailable', 'host operation failed'))
                        stream.write((json.dumps(result, ensure_ascii=False)+'\n').encode()); stream.flush()
                except (OSError, ValueError, HubError, IdentityError) as exc:
                    print("host connection failure: " + type(exc).__name__, file=sys.stderr, flush=True)
            try: host.delivery_tick()
            except (OSError, HubError, ValueError, subprocess.SubprocessError): pass

if __name__ == '__main__': main()
