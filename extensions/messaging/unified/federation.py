"""Owner-local mailbox federation over enrolled SSH hosts.

Foreign endpoint rows are immutable message evidence, never directory authority.
Local dispatch never requires a remote request. No alias cache is a routing source.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from hub import Hub
from protocol import HubError, MAX_REQUEST
from policy import check_policy

PROTOCOL = 1


class FederatedHub(Hub):
    def __init__(self, db_path, config):
        super().__init__(db_path, config)
        self.local_id = self.config['host_id']
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS federated_outbox (
          message_id TEXT PRIMARY KEY, host_id TEXT NOT NULL, payload TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending');
        ''')

    def topology(self):
        path = self.config.get('topology_path')
        if path:
            try:
                return json.loads(Path(path).read_text())
            except (OSError, ValueError):
                raise HubError('configuration_error', 'topology configuration is unavailable')
        return {'mode': 'standalone', 'hosts': []}

    def peers(self):
        top = self.topology()
        if top.get('mode') != 'multi':
            return {}
        return {h['id']: h for h in top.get('hosts', [])
                if h.get('id') != self.local_id and h.get('ssh_alias')}

    def remote(self, host_id, op, **args):
        peer = self.peers().get(host_id)
        token = self.host_tokens.get(self.local_id)
        if not peer or not token:
            raise HubError('host_unavailable', 'destination host is not connected in this mode')
        alias = peer['ssh_alias']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', alias):
            raise HubError('configuration_error', 'invalid SSH alias')
        request = dict(args, op='peer_' + op, host_id=self.local_id,
                       host_token=token, protocol=PROTOCOL)
        try:
            proc = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3',
                                   '-T', '--', alias,
                                   'PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" '
                                   'python3 "$HOME/lib/tproj-msg-unified/federation.py" --rpc'],
                                  input=json.dumps(request), capture_output=True, text=True, timeout=8)
            if proc.returncode:
                raise HubError('host_unavailable', 'remote transport command failed')
            response = json.loads(proc.stdout)
            if not isinstance(response, dict):
                raise ValueError('invalid response envelope')
            if not response.get('ok'):
                e = response.get('error', {})
                raise HubError(e.get('code', 'host_unavailable'), e.get('message', 'remote request failed'))
            return response['result']
        except subprocess.TimeoutExpired:
            raise HubError('host_unavailable', 'remote messaging request timed out') from None
        except (OSError, subprocess.SubprocessError):
            raise HubError('host_unavailable', 'remote transport could not run') from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HubError('host_unavailable', 'remote messaging response is invalid') from None

    def remote_bounded(self, host_id, op, args, max_bytes=300_000, timeout=15):
        """Like `remote`, but the response is read with a hard byte cap.

        `remote` captures all of stdout, so a peer could make this host buffer without
        limit. File reads travel this way, so the cap is enforced while reading and the
        transport is killed when it is exceeded.
        """
        peer = self.peers().get(host_id)
        token = self.host_tokens.get(self.local_id)
        if not peer or not token:
            raise HubError('host_unavailable', 'destination host is not connected in this mode')
        alias = peer['ssh_alias']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', alias):
            raise HubError('configuration_error', 'invalid SSH alias')
        request = dict(args, op='peer_' + op, host_id=self.local_id, host_token=token, protocol=PROTOCOL)
        try:
            proc = subprocess.Popen(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3', '-T', '--', alias,
                                     'PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" '
                                     'python3 "$HOME/lib/tproj-msg-unified/federation.py" --rpc'],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            raise HubError('host_unavailable', 'remote transport could not run') from None
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            try:
                proc.stdin.write(json.dumps(request).encode()); proc.stdin.close()
            except OSError:
                raise HubError('host_unavailable', 'remote transport command failed') from None
            data = proc.stdout.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise HubError('too_large', 'remote response exceeds the size limit')
            proc.wait(timeout=2)
            if proc.returncode:
                raise HubError('host_unavailable', 'remote transport command failed')
            response = json.loads(data.decode('utf-8'))
            if not isinstance(response, dict):
                raise ValueError('invalid response envelope')
            if not response.get('ok'):
                e = response.get('error', {})
                raise HubError(e.get('code', 'host_unavailable'), e.get('message', 'remote request failed'))
            return response['result']
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
            raise HubError('host_unavailable', 'remote messaging response is invalid') from None
        except subprocess.TimeoutExpired:
            raise HubError('host_unavailable', 'remote messaging request timed out') from None
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
            try: proc.stdout.close()
            except OSError: pass

    def repo_service(self):
        from repo_access import RepoAccess
        from repo_access_policy import RepoPolicy
        if getattr(self, '_repo_svc', None) is None:
            self._repo_svc = RepoAccess(RepoPolicy(), lambda: self.local_directory()['projects'])
        return self._repo_svc

    def repo_peer(self, req):
        """Host-facing: forward one read to the host that owns the project.

        The reader is taken from this hub's own record of the authenticated endpoint,
        never from the caller's request, and is attested to the owner by this host.
        """
        from repo_access import RepoError
        host = self._auth(req)
        ep = self._host_endpoint(host, req.get('endpoint_id'))
        reader = {'participant_id': ep['participant_id'], 'host_id': self.local_id}
        op = req.get('repo_op')
        if op == 'list':
            repos, unavailable = [], []
            for ident in self.peers():
                try:
                    part = self.remote_bounded(ident, 'repo', {'repo_op': 'list', 'reader': reader, 'req': {}})
                except HubError:
                    unavailable.append(ident); continue
                if isinstance(part, dict) and isinstance(part.get('repos'), list):
                    repos.extend(r for r in part['repos'] if isinstance(r, dict))
            return {'repos': repos, 'unavailable': unavailable}
        ident = req.get('host')
        if op not in ('tree', 'read', 'search', 'write', 'revert') or ident not in self.peers() or not isinstance(req.get('req'), dict):
            raise HubError('invalid_request', 'invalid repo request')
        result = self.remote_bounded(ident, 'repo', {'repo_op': op, 'reader': reader, 'req': req['req']})
        if not isinstance(result, dict):
            raise HubError('host_unavailable', 'remote messaging response is invalid')
        return result

    def peer_repo(self, req, owner):
        """Owner-facing: a trusted peer attests its own participant; the policy decides."""
        from repo_access import RepoError
        reader = req.get('reader') if isinstance(req.get('reader'), dict) else {}
        pid = reader.get('participant_id')
        row = self._row('SELECT host_id FROM participants WHERE participant_id=?', (pid,)) if isinstance(pid, str) else None
        if not row or row['host_id'] != owner or reader.get('host_id') != owner:
            raise HubError('unauthorized', 'reader is not a participant of the calling host')
        op = req.get('repo_op')
        if op not in ('list', 'tree', 'read', 'search', 'write', 'revert') or not isinstance(req.get('req', {}), dict):
            raise HubError('invalid_request', 'invalid repo request')
        try:
            return self.repo_service().handle(op, {'participant_id': pid, 'generation': ''}, dict(req.get('req') or {}))
        except RepoError as exc:
            raise HubError(exc.code, str(exc)) from None

    def local_directory(self):
        d = super().directory_list()
        d['projects'] = [p for p in d['projects'] if p['host_id'] == self.local_id]
        d['participants'] = [p for p in d['participants'] if p['host_id'] == self.local_id]
        d['services'] = [p for p in d['participants'] if p['project_id'] is None]
        d['host_id'] = self.local_id
        d['alias_history'] = [r[0] for r in self.db.execute('SELECT alias FROM alias_history')]
        return d

    def directory_list(self):
        # Internal discovery must be strictly local, even if every peer is down.
        return self.local_directory()

    def combined_directory(self):
        result = self.local_directory()
        result['hosts'] = [{'host_id': self.local_id, 'state': 'online'}]
        def fetch(ident):
            try:
                return ident, self.remote(ident, 'directory'), None
            except HubError as exc:
                return ident, None, exc.code
        with ThreadPoolExecutor(max_workers=max(1, min(8, len(self.peers())))) as pool:
            for ident, remote, error in pool.map(fetch, self.peers()):
                result['hosts'].append({'host_id': ident, 'state': 'unavailable' if error else 'online', 'error': error})
                if remote:
                    for key in ('projects', 'participants', 'services'):
                        result[key].extend(remote[key])
        return result

    def evidence(self, endpoint_id):
        ep = self._row('SELECT * FROM endpoints WHERE endpoint_id=?', (endpoint_id,))
        if not ep:
            raise HubError('no_recipient', 'endpoint is unavailable')
        p = self._row('SELECT * FROM participants WHERE participant_id=?', (ep['participant_id'],))
        return {'endpoint': dict(ep), 'participant': dict(p)}

    def remember_evidence(self, evidence, owner):
        ep, p = evidence['endpoint'], evidence['participant']
        if ep['host_id'] != owner or p['host_id'] != owner or ep['participant_id'] != p['participant_id']:
            raise HubError('identity_rejected', 'foreign endpoint owner mismatch')
        if owner == self.local_id:
            local = self.evidence(ep['endpoint_id'])
            if local['endpoint']['incarnation'] != ep['incarnation']:
                raise HubError('stale_session', 'recipient incarnation changed')
            return
        old = self._row('SELECT * FROM endpoints WHERE endpoint_id=?', (ep['endpoint_id'],))
        if old and any(str(old[k]) != str(ep[k]) for k in ('host_id', 'participant_id', 'pid', 'pid_start', 'runtime_id', 'incarnation')):
            raise HubError('identity_rejected', 'endpoint evidence is immutable')
        existing = self._row('SELECT * FROM participants WHERE participant_id=?', (p['participant_id'],))
        if existing and existing['host_id'] != owner:
            raise HubError('identity_rejected', 'participant ownership conflict')
        # Foreign records support reply authentication only. Never add projects.
        cols = ('participant_id', 'project_id', 'address', 'host_id', 'kind')
        self.db.execute('INSERT INTO participants('+','.join(cols)+') VALUES(?,?,?,?,?) '
                        'ON CONFLICT(participant_id) DO UPDATE SET address=excluded.address', tuple(p[k] for k in cols))
        cols = ('endpoint_id','participant_id','host_id','session','pane','pid','pid_start','runtime_id','platform','incarnation','last_heartbeat','retired')
        self.db.execute('INSERT OR IGNORE INTO endpoints('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')', tuple(ep[k] for k in cols))

    def local_resolve(self, address=None, endpoint_id=None):
        if endpoint_id:
            ep = self._row('SELECT * FROM endpoints WHERE endpoint_id=? AND host_id=?', (endpoint_id, self.local_id))
            if ep and ep['retired']:
                participant = self._row('SELECT * FROM participants WHERE participant_id=?', (ep['participant_id'],))
                if participant and participant['project_id'] is None and participant['kind'] == 'openclaw':
                    ep = self._endpoint_for_send(participant)
                else: ep = None
            if not ep:
                raise HubError('no_recipient', 'original endpoint is unavailable')
        else:
            p = self._participant(address)
            if p['host_id'] != self.local_id:
                raise HubError('unknown_target', 'not owned by this host')
            ep = self._endpoint_for_send(p)
        return self.evidence(ep['endpoint_id'])

    def resolve_destination(self, address):
        try:
            return self.local_resolve(address)
        except HubError as exc:
            if exc.code != 'unknown_target':
                raise
        matches, unavailable = [], []
        # Query authoritative owners, never foreign evidence rows.
        def fetch(host_id):
            try: return self.remote(host_id, 'resolve', address=address), None
            except HubError as exc: return None, exc
        with ThreadPoolExecutor(max_workers=max(1, min(8, len(self.peers())))) as pool:
            for evidence, error in pool.map(fetch, self.peers()):
                if evidence: matches.append(evidence)
                elif error.code != 'unknown_target': unavailable.append(error)
        if len(matches) > 1:
            raise HubError('ambiguous_target', 'address has multiple owners')
        if unavailable and not matches:
            # With one failing authority, preserve its specific rejection. A
            # stale heartbeat or ambiguous endpoint is not a host outage.
            if len(unavailable) == 1:
                raise unavailable[0]
            # Fixed code allowlist only: never surface transport output or
            # arbitrary peer text when summarizing multiple authorities.
            known = {'host_unavailable', 'endpoint_unavailable', 'no_recipient',
                     'ambiguous_target', 'identity_rejected', 'unauthorized',
                     'configuration_error', 'maintenance', 'unavailable'}
            causes = sorted({e.code if e.code in known else 'remote_error' for e in unavailable})
            raise HubError('host_unavailable', 'remote destination unresolved: ' + ', '.join(causes))
        if not matches:
            raise HubError('unknown_target', 'unknown target')
        return matches[0]

    def submit(self, req):
        host = self._auth(req)
        if host != self.local_id:
            raise HubError('unauthorized', 'use authenticated peer ingress')
        msg = dict(req.get('message') or {})
        sender = self._host_endpoint(host, msg.get('sender_endpoint'))
        mid = msg.get('message_id')
        queued = self._row('SELECT * FROM federated_outbox WHERE message_id=?', (mid,))
        if queued:
            saved = json.loads(queued['payload'])
            if saved['message'] != msg:
                raise HubError('id_conflict', 'message ID has different payload')
            return self.flush_one(queued)
        if msg.get('in_reply_to'):
            original = self._row('SELECT * FROM messages WHERE message_id=?', (msg['in_reply_to'],))
            if not original or original['recipient_endpoint'] != sender['endpoint_id']:
                raise HubError('identity_rejected', 'not original recipient')
            evidence = self.evidence(original['sender_endpoint'])
            owner = evidence['endpoint']['host_id']
            if owner == self.local_id:
                return super().submit(req)
            evidence = self.remote(owner, 'resolve', endpoint_id=original['sender_endpoint'])
            target = evidence['participant']['address']
        else:
            target = self._address(msg.get('target', ''), sender['endpoint_id'])
            evidence = self.resolve_destination(target)
            owner = evidence['endpoint']['host_id']
            if owner == self.local_id:
                return super().submit(req)
        # Commit the accepted message and its outbound retry record atomically.
        self._tx()
        if msg.get('in_reply_to') and original['sender_endpoint'] != evidence['endpoint']['endpoint_id']:
            self.db.execute('UPDATE endpoints SET retired=1 WHERE endpoint_id=?', (original['sender_endpoint'],))
        original_resolver, original_endpoint = self._participant, self._endpoint_for_send
        try:
            self.remember_evidence(evidence, owner)
            self._participant = lambda address: evidence['participant'] if address == target else original_resolver(address)
            self._endpoint_for_send = lambda participant: evidence['endpoint'] if participant['participant_id'] == evidence['participant']['participant_id'] else original_endpoint(participant)
            accepted = super().submit(req)
            if accepted.get('duplicate'):
                self._commit()
                return accepted
            stored = dict(self._row('SELECT * FROM messages WHERE message_id=?', (mid,)))
            payload = {'message': msg, 'record': stored, 'sender': self.evidence(sender['endpoint_id']), 'recipient': evidence}
            self.db.execute('INSERT INTO federated_outbox(message_id,host_id,payload) VALUES(?,?,?)',
                            (mid, owner, json.dumps(payload, ensure_ascii=False)))
            self._commit()
        except Exception:
            self._rollback()
            raise
        finally:
            self._participant, self._endpoint_for_send = original_resolver, original_endpoint
        return self.flush_one(self._row('SELECT * FROM federated_outbox WHERE message_id=?', (mid,)))

    def flush_one(self, row):
        if row['state'] == 'cancel_pending':
            return self._cancel_remote(row)
        if row['state'] in ('cancelled', 'expired', 'rejected'):
            return {'message_id': row['message_id'], 'state': row['state'], 'duplicate': True}
        if row['state'] == 'delivered':
            return {'message_id': row['message_id'], 'state': 'queued', 'duplicate': True}
        record = self._row('SELECT * FROM messages WHERE message_id=?', (row['message_id'],))
        if record['expires_at'] <= self._now():
            self.db.execute("UPDATE federated_outbox SET state='expired' WHERE message_id=?", (row['message_id'],))
            return {'message_id': row['message_id'], 'state': 'expired'}
        try:
            self.remote(row['host_id'], 'accept', payload=json.loads(row['payload']))
        except HubError as exc:
            if exc.code in ('stale_session', 'no_recipient', 'identity_rejected', 'policy_blocked', 'id_conflict', 'invalid_message'):
                self.db.execute("UPDATE federated_outbox SET state='rejected' WHERE message_id=?", (row['message_id'],))
                self.db.execute("UPDATE messages SET state='rejected' WHERE message_id=?", (row['message_id'],))
                return {'message_id': row['message_id'], 'state': 'rejected', 'reason': exc.code}
            return {'message_id': row['message_id'], 'state': 'queued', 'delivery_pending': True}
        self.db.execute("UPDATE federated_outbox SET state='delivered' WHERE message_id=?", (row['message_id'],))
        return {'message_id': row['message_id'], 'state': 'queued'}

    def tick(self):
        for row in self.db.execute("SELECT * FROM federated_outbox WHERE state IN ('pending','cancel_pending') LIMIT 8").fetchall():
            self.flush_one(row)

    def cancel(self, req):
        host = self._auth(req)
        ep = self._host_endpoint(host, req.get('endpoint_id'))
        msg = self._row('SELECT * FROM messages WHERE message_id=?', (req.get('message_id'),))
        if not msg: raise HubError('not_found', 'message not found')
        if msg['sender_endpoint'] != ep['endpoint_id']:
            raise HubError('unauthorized', 'only original sender may cancel')
        row = self._row('SELECT * FROM federated_outbox WHERE message_id=?', (msg['message_id'],))
        if not row: return super().cancel(req)
        if msg['state'] == 'cancelled': return {'message_id': msg['message_id'], 'state': 'cancelled'}
        # Until the destination confirms cancellation, never claim success or
        # send again. A lost response is retried using the same immutable ID.
        self.db.execute("UPDATE federated_outbox SET state='cancel_pending' WHERE message_id=?", (msg['message_id'],))
        return self._cancel_remote(row)

    def _cancel_remote(self, row):
        try:
            result = self.remote(row['host_id'], 'cancel', payload=json.loads(row['payload']))
        except HubError as exc:
            if exc.code == 'too_late':
                self.db.execute("UPDATE federated_outbox SET state='delivered' WHERE message_id=?", (row['message_id'],))
                raise
            if exc.code in ('identity_rejected', 'unauthorized', 'id_conflict', 'invalid_message', 'expired'):
                self.db.execute("UPDATE federated_outbox SET state='rejected' WHERE message_id=?", (row['message_id'],))
                raise
            return {'message_id': row['message_id'], 'state': 'cancellation_pending', 'delivery_pending': True}
        self.db.execute("UPDATE federated_outbox SET state='cancelled' WHERE message_id=?", (row['message_id'],))
        self.db.execute("UPDATE messages SET state='cancelled' WHERE message_id=?", (row['message_id'],))
        return result

    def accept(self, req):
        owner = self._auth(req)
        payload = req['payload']; record = payload['record']
        sender, recipient = payload['sender'], payload['recipient']
        if owner not in self.peers():
            raise HubError('unauthorized', 'peer is not enrolled')
        if sender['endpoint']['host_id'] != owner or recipient['endpoint']['host_id'] != self.local_id:
            raise HubError('identity_rejected', 'message ownership mismatch')
        if record['sender_endpoint'] != sender['endpoint']['endpoint_id'] or record['recipient_endpoint'] != recipient['endpoint']['endpoint_id']:
            raise HubError('identity_rejected', 'message endpoint mismatch')
        self.local_resolve(endpoint_id=record['recipient_endpoint'])
        self.remember_evidence(sender, owner)
        old = self._row('SELECT * FROM messages WHERE message_id=?', (record['message_id'],))
        if old:
            if old['payload_hash'] != record['payload_hash']:
                raise HubError('id_conflict', 'message ID has different payload')
            return {'message_id': old['message_id'], 'state': old['state'], 'duplicate': True}
        if self._maintenance() == 'stopped':
            raise HubError('maintenance', 'mailbox paused')
        body = record['body']
        if not isinstance(body, str) or len(body.encode()) > 65536 or any(ord(c)<32 and c not in '\n\t' for c in body) or '\x7f' in body:
            raise HubError('invalid_message', 'invalid body')
        if record['expires_at'] <= self._now() or record['expires_at'] - record['created_at'] > 86400:
            raise HubError('invalid_message', 'expired or invalid TTL')
        if record['in_reply_to']:
            original = self._row('SELECT * FROM messages WHERE message_id=?', (record['in_reply_to'],))
            recipient_matches = bool(original and original['sender_endpoint'] == record['recipient_endpoint'])
            if original and not recipient_matches:
                old_sender = self.evidence(original['sender_endpoint'])
                service = old_sender['participant']
                recipient_matches = (service['project_id'] is None and service['kind'] == 'openclaw'
                    and service['participant_id'] == recipient['participant']['participant_id']
                    and self._endpoint_for_send(service)['endpoint_id'] == record['recipient_endpoint'])
            if not original or original['recipient_endpoint'] != record['sender_endpoint'] or not recipient_matches or original['thread_id'] != record['thread_id']:
                raise HubError('identity_rejected', 'reply does not match original endpoints')
        check_policy(self.db, record['sender_endpoint'], record['target_address'], body, self._now(), record['in_reply_to'])
        cols = ('message_id','thread_id','in_reply_to','sender_endpoint','target_address','recipient_endpoint','body','kind','created_at','expires_at','payload_hash')
        self.db.execute('INSERT INTO messages('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')', tuple(record[k] for k in cols))
        return {'message_id': record['message_id'], 'state': 'queued'}

    def manage_update(self, req, origin):
        from directory import manager_update
        manager = self.topology().get('management_host_id', self.local_id)
        if self.peers() and manager != self.local_id:
            return self.remote(manager, 'manage_update', request={k:v for k,v in req.items() if k not in ('host_token','admin_token')})
        projects = req.get('projects', [])
        # Operator edits may include a global GUI view. Partition by authoritative owner.
        payload = {'projects': projects, 'expected_revision': req.get('expected_revision'), 'origin_host_id': origin}
        change_id = req.get('change_id') or hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return manager_update(self, {'change_id':change_id, 'payload':payload},
                              lambda host, op, args: self.remote(host, op, **args), list(self.peers()))

    def dispatch(self, req):
        op = req.get('op', '')
        if op.startswith('peer_'):
            owner = self._auth(req)
            if req.get('protocol') != PROTOCOL or owner not in self.peers():
                raise HubError('incompatible_peer', 'peer is not enrolled with this protocol')
            if op.startswith('peer_directory_') or op == 'peer_manage_update':
                from directory import prepare, commit, status, abort
                manager = self.topology().get('management_host_id', self.local_id)
                if op != 'peer_manage_update' and owner != manager:
                    raise HubError('unauthorized', 'only the topology manager may change directory names')
                if op == 'peer_manage_update': return self.manage_update(req['request'], origin=owner)
                return {'peer_directory_prepare': prepare, 'peer_directory_commit': commit,
                        'peer_directory_status': status, 'peer_directory_abort': abort}[op](self, req)
            if op == 'peer_diagnose': return super().diagnose(req)
            if op == 'peer_task':
                from task_transport import dispatch
                return dispatch(self, req, peer=True)
            if op == 'peer_directory': return self.local_directory()
            if op == 'peer_repo': return self.peer_repo(req, owner)
            if op == 'peer_resolve': return self.local_resolve(req.get('address'), req.get('endpoint_id'))
            if op == 'peer_accept': return self.accept(req)
            if op == 'peer_cancel':
                # Accept the original immutable envelope if ingress raced the
                # cancellation. The serialized hub dispatch makes the resulting
                # tombstone visible before any adapter can claim this message.
                self.accept(req)
                return super().cancel(dict(req, endpoint_id=req['payload']['record']['sender_endpoint'],
                                            message_id=req['payload']['record']['message_id']))
            if op == 'peer_query':
                message = self._row('SELECT * FROM messages WHERE message_id=?', (req['message_id'],))
                if not message: raise HubError('not_found', 'message not found')
                ep = self._host_endpoint(owner, req['endpoint_id'])
                if ep['endpoint_id'] not in (message['sender_endpoint'], message['recipient_endpoint']):
                    raise HubError('unauthorized', 'not party to message')
                return super().dispatch(dict(req, op='query'))
            raise HubError('unknown_op', 'unsupported peer operation')
        if op == 'diagnose':
            origin=self._auth(req)
            if origin != self.local_id:raise HubError('unauthorized','diagnosis requires local native host ingress')
            fields={key:req.get(key) for key in ('endpoint_id','message_id','operator_diagnostic')}
            try:
                local=super().diagnose(req)
            except HubError as exc:
                if exc.code != 'not_found':raise
                matches=[]
                failures=[]
                for peer_id in self.peers():
                    try:matches.append(self.remote(peer_id,'diagnose',**fields))
                    except HubError as error:
                        if error.code != 'not_found':failures.append(error.code)
                if not matches:
                    raise HubError(failures[0] if failures else 'not_found','delivery metadata unavailable')
                authoritative=[m for m in matches if m.get('recipient_host_id') == m.get('diagnostic_host_id')]
                if len(authoritative)==1:return authoritative[0]
                if len(matches)==1:return dict(matches[0],remote_state='unavailable')
                raise HubError('ambiguous_diagnostic','multiple delivery owners responded')
            destination=local.get('recipient_host_id')
            if destination and destination != self.local_id:
                try:return self.remote(destination,'diagnose',**fields)
                except HubError as exc:return dict(local,remote_state='unavailable',remote_error=exc.code)
            return local
        if op.startswith('task_'):
            from task_transport import dispatch
            return dispatch(self, req)
        if op == 'directory_all':
            self._auth(req); return self.combined_directory()
        if op == 'directory_update':
            owner = self._auth(req)
            if owner != self.local_id: raise HubError('unauthorized', 'directory update requires local operator')
            return self.manage_update(req, origin=owner)
        if op == 'query':
            host = self._auth(req)
            result = super().dispatch(req)
            endpoint = self.evidence(result['recipient_endpoint'])['endpoint']
            if endpoint['host_id'] != self.local_id:
                try:
                    return self.remote(endpoint['host_id'], 'query', endpoint_id=req['endpoint_id'], message_id=req['message_id'])
                except HubError:
                    return dict(result, remote_state='unavailable')
            return result
        if op == 'repo_peer': return self.repo_peer(req)
        return super().dispatch(req)


def main():
    p = argparse.ArgumentParser(); p.add_argument('--rpc', action='store_true'); args=p.parse_args()
    if args.rpc:
        from host import rpc
        from protocol import success, failure
        try:
            raw = sys.stdin.buffer.readline(MAX_REQUEST+1)
            if len(raw)>MAX_REQUEST: raise HubError('invalid_request', 'request too large')
            req=json.loads(raw)
            if not str(req.get('op','')).startswith('peer_'): raise HubError('unauthorized','peer operation required')
            config=json.loads((Path.home()/'.config/tproj/msg-host.json').read_text())
            out=success(rpc(config['hub_socket'],req))
        except HubError as exc: out=failure(exc)
        except Exception: out={'ok':False,'error':{'code':'unavailable','message':'local messaging unavailable'}}
        print(json.dumps(out,ensure_ascii=False))

if __name__ == '__main__': main()
