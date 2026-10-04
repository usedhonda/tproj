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

from identity import (IdentityError, adopt_native_conversation, bind_caller, discover_endpoints, discover_tmux_endpoints,
                      peer_credentials, same_live_process_family)
from protocol import HubError, success, failure
from receipt import normalize_prompt

WIRE_LIMIT = 262144


def paste_parts(platform, header, body):
    # Codex paste coalescing replaces preceding literal keystrokes; Claude's
    # pasted_content wrapper instead hides the role marker if it is pasted.
    return ('', header + body) if platform == 'cdx' else (header, body)


def rpc(path, request):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(12)
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
    def __init__(self, config, recover=True):
        self.config = config
        self.endpoints = []
        self.refreshed = 0
        self.db = sqlite3.connect(config['journal'])
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS deliveries(message_id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL,
        envelope TEXT NOT NULL, state TEXT NOT NULL, prompt_hash TEXT, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS submissions(message_id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL,
        envelope TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS delivery_diagnostics(message_id TEXT PRIMARY KEY, reason TEXT NOT NULL);''')
        # A process exit in the injection window must never trigger another injection.
        if recover:
            self.db.execute("INSERT OR REPLACE INTO delivery_diagnostics SELECT message_id,'adapter_interrupted' FROM deliveries WHERE state='dispatching'")
            self.db.execute("UPDATE deliveries SET state='uncertain' WHERE state='dispatching'")
            self.db.commit()

    def mark_uncertain(self, message_id, reason):
        if reason not in ('receipt_timeout','dispatch_error'):
            raise ValueError('invalid uncertainty classification')
        self.db.execute("UPDATE deliveries SET state='uncertain' WHERE message_id=?", (message_id,))
        self.db.execute('INSERT OR REPLACE INTO delivery_diagnostics VALUES(?,?)',(message_id,reason))
        self.db.commit()

    def hub(self, op, **args):
        return rpc(self.config['hub_socket'], dict(args, op=op,
                   host_id=self.config['host_id'], host_token=self.config['host_token']))

    def refresh(self):
        """Refresh discovery under a per-journal lock to serialize retirement."""
        lock_path = str(self.config['journal']) + '.identity.lock'
        with open(lock_path, 'a+', encoding='utf-8') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                return self._refresh_unlocked()
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _refresh_unlocked(self):
        directory = self.hub('directory_list')
        # Snapshot active identities before discovery.  A standalone tmux
        # endpoint may be replaced by a registry record for a child process;
        # preserve the original immutable endpoint ID when live lineage proves
        # this is the same process family.
        previous = self.hub('endpoints_list')['endpoints']
        discovered = discover_endpoints(self.config.get('registry', str(Path.home()/'.cache/tproj-model-role')),
                                        self.config['host_id'], directory['projects'])
        # Public standalone installs may have no model-role registry. Keep
        # registered identities authoritative and fill only unmatched panes.
        discovered.extend(discover_tmux_endpoints(self.config['host_id'], directory['projects'], discovered))
        active_previous = [ep for ep in previous if not ep['retired']]
        reconciled = []
        ambiguous_participants = set()
        for ep in discovered:
            matches = [old for old in active_previous if same_live_process_family(old, ep)]
            if len(matches) > 1:
                ambiguous_participants.add(ep['participant_id'])
                continue
            if matches:
                old = matches[0]
                # Keep the old endpoint's immutable binding while retaining
                # descriptive fields from the fresh registry observation.
                merged = dict(ep)
                merged.update({key: old[key] for key in
                               ('endpoint_id', 'host_id', 'participant_id', 'session', 'pane',
                                'pid', 'pid_start', 'runtime_id', 'platform')})
                merged['pid_start'] = int(old['pid_start'])
                merged['observed_runtime_id'] = ep.get('runtime_id')
                reconciled.append(merged)
            else:
                reconciled.append(ep)
        discovered = reconciled
        for ep in discovered:
            registered = self.hub('endpoint_register', **ep)
            if (registered.get('endpoint_id') != ep['endpoint_id'] or
                    not isinstance(registered.get('incarnation'), str) or not registered['incarnation']):
                raise HubError('identity_rejected', 'hub did not confirm endpoint incarnation')
            # Registry/process evidence authenticates the caller; the hub alone
            # issues the durable incarnation used by formal task fences.
            ep['incarnation'] = registered['incarnation']
        # A disappeared process is not inferred from an alias. Retire only after
        # a matching participant has a proven different live incarnation.
        live_ids = {ep['endpoint_id'] for ep in discovered}
        live_participants = {ep['participant_id'] for ep in discovered}
        for ep in previous:
            if (ep['endpoint_id'] not in live_ids and ep['participant_id'] in live_participants
                    and ep['participant_id'] not in ambiguous_participants and not ep['retired']):
                self.hub('endpoint_retire', endpoint_id=ep['endpoint_id'])
            elif (ep['endpoint_id'] not in live_ids and ep['participant_id'] not in live_participants
                  and not ep['retired'] and ep.get('platform') in ('cc', 'cdx')):
                # A vanished participant is retired only with direct PID/start
                # evidence; an absent registry row alone is not enough.
                from identity import _process_info
                try:
                    current = _process_info(int(ep['pid']))
                except (IdentityError, OSError, ValueError, KeyError, TypeError):
                    current = None
                absent = False
                if current is None:
                    try: os.kill(int(ep['pid']), 0)
                    except ProcessLookupError: absent = True
                    except (OSError, ValueError, TypeError): pass
                if absent or (current and str(current.get('pid_start')) != str(ep.get('pid_start'))):
                    self.hub('endpoint_retire', endpoint_id=ep['endpoint_id'])
        self.endpoints = discovered
        self.refreshed = time.monotonic()

    def caller(self, pid, uid, req):
        if not self.endpoints or time.monotonic() - self.refreshed >= 10:
            self.refresh()
        try:
            endpoints = adopt_native_conversation(self.endpoints, req.get('conversation') or {})
            return bind_caller(pid, uid, endpoints, session=req.get('session'),
                               claimed_alias=req.get('as'), conversation=req.get('conversation'))
        except IdentityError as exc:
            raise HubError('identity_rejected', str(exc)) from exc

    def _service_binding(self, req):
        """Return (stable service identity, config) without alias inference.

        ``service`` is the legacy OpenClaw singleton.  New deployments use a
        mapping keyed by an explicit stable service identity; callers must
        name that identity rather than selecting a credential by address.
        """
        services = self.config.get('services') or {}
        if services and not isinstance(services, dict):
            raise HubError('identity_rejected', 'service registry must be keyed by identity')
        service_id = req.get('service_id')
        if service_id is not None:
            if not isinstance(service_id, str) or not service_id or service_id not in services:
                raise HubError('identity_rejected', 'unknown service identity')
            cfg = services[service_id]
            if not isinstance(cfg, dict):
                raise HubError('identity_rejected', 'invalid service binding')
            return service_id, cfg
        # Keep the existing OpenClaw configuration path working unchanged.
        cfg = self.config.get('service') or {}
        if cfg:
            return 'openclaw', cfg
        raise HubError('identity_rejected', 'service identity required')

    def _validate_service_registry(self):
        """Reject ambiguous service ownership before touching endpoint state."""
        services = self.config.get('services') or {}
        if services and not isinstance(services, dict):
            raise HubError('identity_rejected', 'service registry must be keyed by identity')
        bindings = []
        legacy = self.config.get('service') or {}
        if legacy:
            bindings.append(('openclaw', legacy))
        bindings.extend(services.items())
        seen = {}
        for service_id, cfg in bindings:
            if not isinstance(cfg, dict):
                raise HubError('identity_rejected', 'invalid service binding')
            for field in ('participant_id', 'address'):
                value = cfg.get(field)
                if value and (field, value) in seen:
                    raise HubError('identity_rejected', f'duplicate service {field}')
                if value:
                    seen[(field, value)] = service_id

    def service(self, pid, uid, req):
        self._validate_service_registry()
        service_id, cfg = self._service_binding(req)
        if not all(cfg.get(key) for key in ('token', 'address', 'participant_id')):
            raise HubError('identity_rejected', 'incomplete service binding')
        if uid != os.getuid() or not cfg.get('token') or not secrets.compare_digest(str(req.get('service_token', '')), cfg['token']):
            raise HubError('identity_rejected', 'invalid service credential')
        if req.get('address', cfg['address']) != cfg['address']:
            raise HubError('identity_rejected', 'service address mismatch')
        platform = cfg.get('platform', 'openclaw' if service_id == 'openclaw' else service_id)
        if service_id != 'openclaw' and platform == 'openclaw':
            raise HubError('identity_rejected', 'non-OpenClaw service cannot use openclaw platform')
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
        legacy_binding = req.get('service_id') is None and bool(self.config.get('service'))
        endpoint_seed = (f"{self.config['host_id']}:{cfg['participant_id']}:{pid}:{start}"
                         if legacy_binding else
                         f"{self.config['host_id']}:{service_id}:{cfg['participant_id']}:{pid}:{start}")
        ep = dict(endpoint_id=str(uuid.uuid5(uuid.NAMESPACE_URL, endpoint_seed)),
                  participant_id=cfg['participant_id'], host_id=self.config['host_id'],
                  session=cfg['address'], pane='', pid=pid, pid_start=start,
                  runtime_id=f'{pid}:{start}', platform=platform, address=cfg['address'],
                  service_id=service_id)
        # KAI is an enrolled service principal, not a process/conversation
        # persona. Authenticate the current launchd process above on every call,
        # then retain its mailbox across process restarts within one enrollment.
        # Rotating the operator-owned generation revokes this continuity.
        generation = cfg.get('binding_generation') if service_id == 'kai' else None
        if generation:
            ep.update(endpoint_id=str(uuid.uuid5(uuid.NAMESPACE_URL,
                      f"{self.config['host_id']}:{service_id}:{cfg['participant_id']}:{generation}")),
                      pid=0, pid_start=0, runtime_id=f'kai:{generation}')
        for old in self.hub('endpoints_list')['endpoints']:
            if old['participant_id'] == ep['participant_id'] and old['endpoint_id'] != ep['endpoint_id'] and not old['retired']:
                self.hub('endpoint_retire', endpoint_id=old['endpoint_id'])
        self.hub('endpoint_register', **ep)
        for row in self.hub('endpoints_list')['endpoints']:
            if row.get('endpoint_id') == ep['endpoint_id']:
                ep['incarnation'] = row.get('incarnation')
                break
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

    def delivery_status(self, endpoint_id, message_id, reason):
        """Record a nonterminal delivery diagnostic without changing state."""
        try:
            return self.hub('delivery_status', endpoint_id=endpoint_id, message_id=message_id, reason=reason)
        except HubError:
            return None

    def _retry_event(self, caller, message_id):
        """Retry one live KAI event through the enrolled local bridge only."""
        services = self.config.get('services') or {}
        cfg = services.get('kai') if isinstance(services, dict) else None
        if not isinstance(cfg, dict) or not cfg.get('event_bridge_socket'):
            raise HubError('unavailable', 'KAI event bridge unavailable')
        endpoints = self.hub('endpoints_list')['endpoints']
        directory = self.hub('directory_list')['participants']
        if not any(p.get('participant_id') == cfg.get('participant_id')
                   and p.get('address') == cfg.get('address')
                   and p.get('host_id') == self.config['host_id'] for p in directory):
            raise HubError('identity_rejected', 'KAI participant is not locally configured')
        matches = [ep for ep in endpoints
                   if not ep.get('retired') and ep.get('host_id') == self.config['host_id']
                   and ep.get('participant_id') == cfg.get('participant_id')]
        if len(matches) != 1:
            raise HubError('identity_rejected', 'KAI endpoint is not uniquely enrolled')
        message = self.hub('query', endpoint_id=caller['endpoint_id'], message_id=message_id)
        if message.get('recipient_endpoint') != matches[0].get('endpoint_id'):
            raise HubError('identity_rejected', 'message is not addressed to current KAI')
        if message.get('state') not in ('accepted', 'queued', 'adapter_received'):
            raise HubError('ineligible', 'message is not eligible for event retry')
        request = {'op': 'retry_event', 'message_id': message_id,
                   'actor_endpoint': caller['endpoint_id'],
                   'service_token': cfg.get('token')}
        try:
            result = rpc(cfg['event_bridge_socket'], request)
        except OSError:
            raise HubError('unknown', 'KAI event retry outcome unknown')
        except ValueError:
            raise HubError('unavailable', 'KAI event retry unavailable')
        except HubError as exc:
            if exc.code == 'unavailable':
                raise HubError('unknown', 'KAI event retry outcome unknown')
            raise HubError(exc.code, 'KAI event retry rejected')
        if not isinstance(result, dict):
            raise HubError('unavailable', 'KAI event retry unavailable')
        allowed = {'message_id', 'event_id', 'status', 'attempts', 'total_attempts', 'status_code', 'error_class'}
        return {key: result[key] for key in allowed if key in result}

    REPO_FIELDS = ('repo_id', 'path', 'depth', 'start', 'end', 'max_bytes', 'pattern', 'mode', 'case_sensitive',
                   'glob_include', 'glob_exclude', 'context', 'limit', 'cursor', 'snapshot_id')

    def _repo_local(self):
        from repo_access import RepoAccess
        from repo_access_policy import RepoPolicy
        if getattr(self, '_repo_svc', None) is None:
            self._repo_svc = RepoAccess(RepoPolicy(), lambda: [
                p for p in self.hub('directory_list')['projects'] if p.get('host_id') == self.config['host_id']])
        return self._repo_svc

    def _repo(self, ep, op, req):
        """Read-only repo ops for an authenticated reader (pane or service).

        Who the reader is comes only from the authenticated endpoint. Whether it may
        read is the owning host's grant ledger (`repo_access_policy`); this method only
        routes: local projects are read here, others are forwarded to their owner.
        """
        from repo_access import RepoError
        reader = {'participant_id': ep['participant_id'], 'address': ep.get('address'), 'generation': ''}
        payload = {key: req[key] for key in self.REPO_FIELDS if key in req}
        try:
            if op == 'list':
                result = self._repo_local().list_repos(reader)
                if self.config.get('federated'):
                    remote = self.hub('repo_peer', endpoint_id=ep['endpoint_id'], repo_op='list')
                    result['repos'] = result['repos'] + remote.get('repos', [])
                    result['hosts_unavailable'] = remote.get('unavailable', [])
                return result
            target = payload.get('repo_id')
            owner = None
            if self.config.get('federated') and isinstance(target, str):
                projects = self.hub('directory_all')['projects']
                owners = {p['host_id'] for p in projects if target in (p.get('project_id'), p.get('alias'))}
                if len(owners) > 1:
                    raise RepoError('invalid_request')
                owner = next(iter(owners), None)
            if owner is None or owner == self.config['host_id']:
                return self._repo_local().handle(op, reader, payload)
            return self.hub('repo_peer', endpoint_id=ep['endpoint_id'], repo_op=op, host=owner, req=payload)
        except RepoError as exc:
            raise HubError(exc.code, str(exc)) from None

    def _pending(self, ep):
        """What this participant has sent that has not been presented yet.

        Grouped by recipient so a stuck conversation stands out. Where the recipient
        lives decides how far this host's copy can be trusted: only a recipient on this
        Mac reports truthfully here; for another Mac or a service the owning side holds
        the real state, which `message <ID>` fetches.
        """
        out = self.hub('outbox', endpoint_id=ep['endpoint_id'])
        now = out.get('now') or time.time()
        local_host = self.config.get('host_id')
        groups = {}
        checked = 0
        deadline = time.monotonic() + 12
        for item in out.get('messages', []):
            kind = item.get('recipient_kind')
            if kind not in ('cc', 'cdx'):
                where = 'service'
            elif item.get('recipient_host_id') == local_host:
                where = 'this_mac'
            else:
                where = 'other_mac'
            item['verified'] = where == 'this_mac'
            if where != 'this_mac' and checked < 25 and time.monotonic() < deadline:
                # The owning side holds the real state; this hub only has the hand-off
                # record. Ask it (bounded: at most 25 messages and 12 s per call).
                try:
                    fresh = self.hub('query', endpoint_id=ep['endpoint_id'], message_id=item['message_id'])
                    checked += 1
                    if isinstance(fresh, dict) and fresh.get('remote_state') != 'unavailable' and fresh.get('state'):
                        item['state'] = fresh['state']; item['verified'] = True
                except HubError:
                    pass
            if item['state'] not in ('accepted', 'queued', 'adapter_received', 'dispatching', 'uncertain'):
                continue  # presented or terminal on the owning side: nothing is stuck
            key = (item['target_address'], where)
            group = groups.setdefault(key, {'target': key[0], 'where': where, 'count': 0, 'states': {},
                                            'oldest_age_s': 0, 'oldest_message_id': None, 'newest_message_id': None})
            age = max(0, int(now - item['created_at']))
            group['count'] += 1
            if not item['verified']: group['unchecked'] = group.get('unchecked', 0) + 1
            group['states'][item['state']] = group['states'].get(item['state'], 0) + 1
            if age >= group['oldest_age_s']:
                group['oldest_age_s'] = age
                group['oldest_message_id'] = group['oldest_message_id'] or item['message_id']
            group['newest_message_id'] = item['message_id']
        ordered = sorted(groups.values(), key=lambda g: -g['oldest_age_s'])
        return {'groups': ordered, 'total': sum(g['count'] for g in ordered)}

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
            directory = self.hub('directory_all' if self.config.get('federated') else 'directory_list')
            matches = [p for p in directory['participants']
                       if (p['participant_id'] == participant_id if participant_id else p['address'] == target)]
            if len(matches) != 1:
                raise HubError('unknown_target', 'unknown or ambiguous target')
            return matches[0]
        if op in ('list', 'status', 'directory'):
            # Read-only catalog for operator/GUI; no caller can mutate identity.
            return self.hub('directory_all' if self.config.get('federated') else 'directory_list')
        if op == 'directory-sync':
            return self.hub('directory_update', projects=req['projects'], expected_revision=req['expected_revision'])
        is_service = isinstance(op, str) and op.startswith('service_')
        ep = self.service(pid, uid, req) if is_service else self.caller(pid, uid, req)
        if isinstance(op, str) and op.startswith('task_'):
            from task_host import dispatch
            return dispatch(self, ep, req)
        if op == 'service_whoami':
            return {key: ep.get(key) for key in ('endpoint_id', 'participant_id', 'host_id', 'address',
                                                  'session', 'runtime_id', 'platform', 'incarnation')}
        if op == 'service_begin_present':
            if not isinstance(req.get('message_id'), str) or not req['message_id']:
                raise HubError('invalid_message', 'message ID required')
            return self.hub('begin_present', endpoint_id=ep['endpoint_id'], message_id=req['message_id'])
        repo_base = op[8:] if is_service else op
        if repo_base in ('repo_list', 'repo_tree', 'repo_read', 'repo_search'):
            return self._repo(ep, repo_base[5:], req)
        if op == 'pending':
            return self._pending(ep)
        if op == 'whoami':
            return {key: ep.get(key) for key in ('endpoint_id', 'participant_id', 'project_id', 'host_id',
                                                  'address', 'session', 'runtime_id', 'platform', 'thread_id', 'session_id')}
        if op == 'doctor':
            return {'ok': True, 'endpoint': ep, 'conversation': req.get('conversation') or {},
                    'selectors': {'session': req.get('session'), 'as': req.get('as')}}
        if op == 'diagnose':
            if not isinstance(req.get('message_id'),str) or not req['message_id']:
                raise HubError('invalid_message','message ID required')
            operator = ep.get('project_id') in self.config.get('diagnostic_projects',[])
            return self.hub('diagnose',endpoint_id=ep['endpoint_id'],message_id=req['message_id'],operator_diagnostic=operator)
        if op == 'cancel':
            if not isinstance(req.get('message_id'), str) or not req['message_id']:
                raise HubError('invalid_message', 'message ID required')
            return self.hub('cancel', endpoint_id=ep['endpoint_id'], message_id=req['message_id'])
        if op == 'retry_event':
            if not isinstance(req.get('message_id'), str) or not req['message_id']:
                raise HubError('invalid_message', 'message ID required')
            return self._retry_event(ep, req['message_id'])
        if op in ('send', 'reply', 'service_send', 'service_reply'):
            return self.submit(ep, req, reply=op.endswith('reply'))
        if op == 'service_claim':
            return self.hub('claim', endpoint_id=ep['endpoint_id'], limit=min(int(req.get('limit', 8)), 32))
        if op == 'service_receipt':
            return self.hub('receipt', endpoint_id=ep['endpoint_id'], message_id=req['message_id'],
                            state=req['state'], evidence=json.dumps(req.get('evidence', {})))
        if op in ('inbox', 'service_inbox'):
            return self.hub('inbox', endpoint_id=ep['endpoint_id'],
                            cursor=req.get('cursor', 0), limit=req.get('limit', 100))
        if op in ('message', 'service_message'):
            return self.hub('query', endpoint_id=ep['endpoint_id'], message_id=req['message_id'])
        if op in ('ack', 'service_ack'):
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
            observed_runtime = ep.get('observed_runtime_id') or ep['runtime_id']
            native_ids={observed_runtime}
            if ep.get('platform') == 'cdx':
                native_ids.update(ep.get(key) for key in ('thread_id','session_id') if ep.get(key))
            if req.get('runtime_id') not in native_ids:
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
            for pending in self.db.execute("SELECT envelope,message_id FROM deliveries WHERE endpoint_id=? AND state IN ('dispatching','uncertain')", (ep['endpoint_id'],)):
                if pending['message_id'] not in claimed_ids:
                    claims.append(json.loads(pending['envelope']))
            for msg in claims:
                mid = msg['message_id']
                self.db.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?)',
                                (mid, ep['endpoint_id'], json.dumps(msg), 'received', None, time.time()))
                self.db.commit()
                row = self.db.execute('SELECT * FROM deliveries WHERE message_id=?', (mid,)).fetchone()
                if row['state'] in ('dispatching', 'uncertain') and ep['platform'] == 'cc':
                    observed_runtime = ep.get('observed_runtime_id') or ep['runtime_id']
                    for transcript in (Path.home()/'.claude/projects').glob('*/'+observed_runtime+'.jsonl'):
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
                    diagnostic=self.db.execute('SELECT reason FROM delivery_diagnostics WHERE message_id=?',(mid,)).fetchone()
                    evidence=json.dumps({'delivery_reason':diagnostic['reason']}) if row['state']=='uncertain' and diagnostic else 'durable local journal'
                    self.hub('receipt', endpoint_id=ep['endpoint_id'], message_id=mid, state=row['state'], evidence=evidence)
                    continue
                if row['state'] == 'dispatching':
                    self.delivery_status(ep['endpoint_id'], mid, 'waiting_input')
                    if time.time() - row['updated'] > 30:
                        self.mark_uncertain(mid, 'receipt_timeout')
                    continue
                # Revalidate this exact process incarnation immediately before terminal access.
                from identity import _process_info
                try:
                    current = _process_info(ep['pid'])
                    if current['pid_start'] != ep['pid_start']:
                        self.delivery_status(ep['endpoint_id'], mid, 'endpoint_unavailable')
                        continue
                except (IdentityError, OSError):
                    self.delivery_status(ep['endpoint_id'], mid, 'endpoint_unavailable')
                    continue
                cache_kind = 'cc-cache' if ep['platform'] == 'cc' else 'codex-cache'
                observed_runtime = ep.get('observed_runtime_id') or ep['runtime_id']
                cache_path = Path.home()/'.local/state/tproj'/cache_kind/(hashlib.sha256(observed_runtime.encode()).hexdigest()+'.json')
                try:
                    observed = json.loads(cache_path.read_text())
                    if observed.get('pane_id') == ep['pane'] and (observed.get('turn_state') == 'running' or observed.get('event') == 'prompt'):
                        self.delivery_status(ep['endpoint_id'], mid, 'busy')
                        continue
                except (OSError, ValueError): pass
                guard = subprocess.run(['bash', str(Path(__file__).with_name('terminal-guard.sh')), ep['pane']], capture_output=True, timeout=5)
                if guard.returncode:
                    self.delivery_status(ep['endpoint_id'], mid, 'draft_protected')
                    continue
                # The hub owns the atomic cancellation gate.  Claiming here
                # immediately before terminal access prevents a cancel racing
                # with paste from being reported as successful.
                try:
                    gate = self.hub('begin_present', endpoint_id=ep['endpoint_id'], message_id=mid)
                except HubError:
                    self.delivery_status(ep['endpoint_id'], mid, 'adapter_error')
                    continue
                if isinstance(gate, dict) and gate.get('ok') is False:
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
                    self.mark_uncertain(mid, 'dispatch_error')


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
    # Separate SQLite connections keep an unreachable remote catalog request
    # from blocking local sends or local terminal delivery.
    import threading
    recovery = Host(config)
    recovery.db.close()
    slots = threading.BoundedSemaphore(16)
    def handle(conn):
        host = None
        try:
            host = Host(json.loads(Path(args.config).read_text()), recover=False)
            with conn:
                conn.settimeout(15)
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
        finally:
            if host: host.db.close()
            conn.close()
            slots.release()
    def delivery_loop():
        adapter = Host(config, recover=False)
        while True:
            try: adapter.delivery_tick()
            except (OSError, HubError, ValueError, subprocess.SubprocessError, sqlite3.Error): pass
            time.sleep(1)
    threading.Thread(target=delivery_loop,daemon=True).start()
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path)); os.chmod(path, 0o600); server.listen(16)
        while True:
            conn, _ = server.accept()
            if not slots.acquire(blocking=False):
                conn.close(); continue
            threading.Thread(target=handle,args=(conn,),daemon=True).start()

if __name__ == '__main__': main()
