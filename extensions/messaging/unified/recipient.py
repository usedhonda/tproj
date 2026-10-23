"""Owner-local recipient preferences and explicitly scoped historical reads.

Only Host-authenticated observations enter this module. A candidate is not an
identity credential, and selecting a recipient never grants historical access.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid

try:
    from .protocol import HubError, MAX_TTL
    from .native_notice import content_digest
except ImportError:
    from protocol import HubError, MAX_TTL
    from native_notice import content_digest

CAPABILITY = 'recipient_recovery_v1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS recipient_candidates (
 candidate TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL, incarnation TEXT NOT NULL,
 participant_id TEXT NOT NULL, native_kind TEXT NOT NULL, native_id TEXT NOT NULL,
 observed REAL NOT NULL, UNIQUE(endpoint_id,incarnation,native_kind,native_id));
CREATE TABLE IF NOT EXISTS recipient_preferences (
 participant_id TEXT PRIMARY KEY, candidate TEXT, revision INTEGER NOT NULL,
 set_by TEXT NOT NULL, operation_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS message_recovery_grants (
 grant_id TEXT PRIMARY KEY, message_id TEXT NOT NULL, content_hash TEXT NOT NULL,
 original_recipient TEXT NOT NULL, host_id TEXT NOT NULL, participant_id TEXT NOT NULL,
 native_kind TEXT NOT NULL, native_id TEXT NOT NULL, allow_reply INTEGER NOT NULL,
 expires REAL NOT NULL, revoked INTEGER NOT NULL, revision INTEGER NOT NULL,
 set_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS message_recovery_audit (
 audit_id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, action TEXT NOT NULL,
 actor TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS message_recovery_replies (
 message_id TEXT PRIMARY KEY, original_id TEXT NOT NULL, grant_id TEXT NOT NULL,
 owner_host TEXT NOT NULL, actor_endpoint TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recipient_operations (
 operation_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, result TEXT NOT NULL);
'''


def _local(h, host, participant):
    if (not participant or participant['host_id'] != host
            or h.config.get('host_id', host) != host):
        raise HubError('unauthorized', 'operation requires the recipient owner host')


def _marker(h, ep):
    return h._row('SELECT * FROM endpoint_native WHERE endpoint_id=?', (ep['endpoint_id'],))


def _candidate(h, host, key, *, fresh=False):
    c = h._row('SELECT * FROM recipient_candidates WHERE candidate=?', (key,))
    if not c:
        raise HubError('identity_rejected', 'unknown recipient candidate')
    ep = h._host_endpoint(host, c['endpoint_id'])
    _local(h, host, h._row('SELECT * FROM participants WHERE participant_id=?', (ep['participant_id'],)))
    marker = _marker(h, ep)
    if (ep['incarnation'] != c['incarnation'] or ep['participant_id'] != c['participant_id']
            or ep['platform'] != 'cdx' or not ep['pane'] or not marker
            or any(marker[k] != c[k] for k in ('native_kind', 'native_id'))
            or h._now() - ep['last_heartbeat'] > 30
            or (fresh and h._now() - c['observed'] > 120)):
        raise HubError('endpoint_unavailable', 'selected TUI binding requires a fresh observation')
    return c, ep


def new_message_recipient(h, participant):
    pref = h._row('SELECT * FROM recipient_preferences WHERE participant_id=?', (participant['participant_id'],))
    if not pref or pref['candidate'] is None:
        return h._endpoint_for_send(participant)
    _, ep = _candidate(h, participant['host_id'], pref['candidate'])
    return ep


def presentation_allowed(h, ep):
    """Fence only MSG writers for the selected native; never change its origin."""
    pref = h._row('SELECT * FROM recipient_preferences WHERE participant_id=?', (ep['participant_id'],))
    if not pref or pref['candidate'] is None:
        return True
    c = h._row('SELECT * FROM recipient_candidates WHERE candidate=?', (pref['candidate'],))
    marker = _marker(h, ep)
    if not c or not marker or any(marker[k] != c[k] for k in ('native_kind', 'native_id')):
        return True  # A different native retains its own historical rights.
    return ep['endpoint_id'] == c['endpoint_id'] and ep['incarnation'] == c['incarnation']


def _actor(h, host, endpoint_id, operator=None):
    if operator is not None:
        if (not isinstance(operator, dict) or type(operator.get('uid')) is not int
                or type(operator.get('pid')) is not int or operator['pid'] <= 1
                or type(operator.get('pid_start')) is not int or operator['pid_start'] <= 0):
            raise HubError('identity_rejected', 'invalid owner Host operator observation')
        return json.dumps(dict(host_id=host, operator=operator), sort_keys=True)
    ep = h._host_endpoint(host, endpoint_id)
    marker = _marker(h, ep)
    return json.dumps(dict(host_id=host, participant_id=ep['participant_id'],
                           endpoint_id=ep['endpoint_id'], incarnation=ep['incarnation'],
                           native_kind=marker['native_kind'] if marker else None,
                           native_id=marker['native_id'] if marker else None), sort_keys=True)


def _revision(req, current):
    value = req.get('expected_revision')
    if type(value) is not int or value != current:
        raise HubError('revision_conflict', 'recipient/recovery revision changed')


def _grant(h, host, req):
    grant = h._row('SELECT * FROM message_recovery_grants WHERE grant_id=?', (req.get('grant_id'),))
    if not grant or grant['host_id'] != host or h.config.get('host_id', host) != host:
        raise HubError('unauthorized', 'recovery grant is not owned by this host')
    if grant['revoked'] or grant['expires'] <= h._now():
        raise HubError('unauthorized', 'recovery grant is revoked or expired')
    if grant['message_id'] != req.get('message_id'):
        raise HubError('unauthorized', 'recovery grant does not cover this message')
    ep = h._host_endpoint(host, req.get('actor_endpoint'))
    marker = _marker(h, ep)
    if (ep['participant_id'] != grant['participant_id'] or not marker
            or any(marker[k] != grant[k] for k in ('native_kind', 'native_id'))):
        raise HubError('unauthorized', 'recovery requires the exact authorized native conversation')
    msg = h._row('SELECT * FROM messages WHERE message_id=?', (grant['message_id'],))
    if (not msg or msg['recipient_endpoint'] != grant['original_recipient']
            or content_digest(dict(msg)) != grant['content_hash']):
        raise HubError('identity_rejected', 'recovery original changed')
    old = h._row('SELECT * FROM endpoints WHERE endpoint_id=?', (msg['recipient_endpoint'],))
    if not old or old['host_id'] != host or old['participant_id'] != ep['participant_id']:
        raise HubError('unauthorized', 'recovery is restricted to the original recipient participant')
    return grant, ep, msg


def reply_authorized(h, sender, original, message):
    """Only the owner's explicit recovery operation can add this provenance."""
    proof = h._row('SELECT * FROM message_recovery_replies WHERE message_id=?', (message.get('message_id'),))
    return bool(proof and proof['original_id'] == original['message_id']
                and proof['owner_host'] == sender['host_id']
                and proof['actor_endpoint'] == sender['endpoint_id'])


def dispatch(h, req):
    host = h._auth(req)
    op = req['op']
    if h.config.get('host_id', host) != host:
        raise HubError('unauthorized', 'management requires the local owner host')
    if op == 'recipient_observe':
        # Internal owner Host observation, not a public caller-selected binding.
        ep = h._host_endpoint(host, req.get('observed_endpoint'))
        marker = _marker(h, ep)
        if ep['platform'] != 'cdx' or not ep['pane'] or not marker:
            raise HubError('identity_rejected', 'authenticated TUI native observation required')
        key = secrets.token_urlsafe(24)
        h.db.execute('INSERT INTO recipient_candidates VALUES(?,?,?,?,?,?,?) '
                     'ON CONFLICT(endpoint_id,incarnation,native_kind,native_id) '
                     'DO UPDATE SET observed=excluded.observed',
                     (key, ep['endpoint_id'], ep['incarnation'], ep['participant_id'],
                      marker['native_kind'], marker['native_id'], h._now()))
        c = h._row('SELECT candidate FROM recipient_candidates WHERE endpoint_id=? AND incarnation=? '
                   'AND native_kind=? AND native_id=?',
                   (ep['endpoint_id'], ep['incarnation'], marker['native_kind'], marker['native_id']))
        return {'candidate': c['candidate']}
    if req.get('actor_operator') is not None and op in ('recovery_read', 'recovery_reply'):
        raise HubError('unauthorized', 'recovery consumption requires the authorized native caller')
    actor = _actor(h, host, req.get('actor_endpoint'), req.get('actor_operator'))
    if op == 'recipient_list':
        p = h._participant(req.get('target', ''))
        _local(h, host, p)
        pref = h._row('SELECT * FROM recipient_preferences WHERE participant_id=?', (p['participant_id'],))
        candidates = []
        for c in h.db.execute('SELECT * FROM recipient_candidates WHERE participant_id=? ORDER BY candidate', (p['participant_id'],)):
            try:
                _, ep = _candidate(h, host, c['candidate'], fresh=True)
            except HubError:
                continue
            candidates.append(dict(candidate=c['candidate'], native_kind=c['native_kind'], native_id=c['native_id'],
                                   endpoint_id=ep['endpoint_id'], incarnation=ep['incarnation'], surface='tui'))
        reason = None
        if pref and pref['candidate']:
            try: _candidate(h, host, pref['candidate'])
            except HubError as exc: reason = exc.code
        return dict(target=p['address'], revision=pref['revision'] if pref else 0,
                    selected=pref['candidate'] if pref else None, blocking_reason=reason, candidates=candidates)
    prepared = None
    if op == 'recovery_reply' and hasattr(h, 'prepare_recovery_reply'):
        saved = h._row('SELECT * FROM recipient_operations WHERE operation_id=?', (req.get('operation_id'),))
        if saved:
            fingerprint = hashlib.sha256(json.dumps({k:v for k,v in req.items()
                if k not in ('host_token','host_id')}, sort_keys=True).encode()).hexdigest()
            if fingerprint != saved['request_hash']:
                raise HubError('id_conflict', 'operation ID has different scope')
            return json.loads(saved['result'])
        # No authority is created by preflight; the transaction below checks
        # the grant again after all potentially slow remote RPCs finish.
        grant, _, _ = _grant(h, host, req)
        if not grant['allow_reply']:
            raise HubError('unauthorized', 'grant does not permit reply')
        prepared = h.prepare_recovery_reply(req)
    h._tx()
    try:
        operation_id = req.get('operation_id')
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
            raise HubError('invalid_request', 'stable operation ID required')
        fingerprint = hashlib.sha256(json.dumps({k: v for k, v in req.items()
             if k not in ('host_token', 'host_id')}, sort_keys=True).encode()).hexdigest()
        previous = h._row('SELECT * FROM recipient_operations WHERE operation_id=?', (operation_id,))
        if previous:
            if previous['request_hash'] != fingerprint:
                raise HubError('id_conflict', 'operation ID has different scope')
            if op != 'recovery_read':
                result = json.loads(previous['result'])
                h._commit()
                return result
        if op in ('recipient_select', 'recipient_clear'):
            p = h._participant(req.get('target', ''))
            _local(h, host, p)
            pref = h._row('SELECT * FROM recipient_preferences WHERE participant_id=?', (p['participant_id'],))
            revision = pref['revision'] if pref else 0
            _revision(req, revision)
            key = req.get('candidate') if op == 'recipient_select' else None
            if key is not None:
                c, _ = _candidate(h, host, key, fresh=True)
                if c['participant_id'] != p['participant_id']:
                    raise HubError('identity_rejected', 'candidate belongs to a different participant')
            elif op == 'recipient_select':
                raise HubError('invalid_request', 'candidate is required')
            h.db.execute('INSERT INTO recipient_preferences VALUES(?,?,?,?,?) ON CONFLICT(participant_id) '
                         'DO UPDATE SET candidate=excluded.candidate,revision=excluded.revision,'
                         'set_by=excluded.set_by,operation_id=excluded.operation_id',
                         (p['participant_id'], key, revision + 1, actor, operation_id))
            result = dict(target=p['address'], selected=key, revision=revision + 1)
        elif op == 'recovery_grant':
            _revision(req, 0)
            ttl = req.get('ttl_sec', 3600)
            if type(ttl) is not int or not 1 <= ttl <= MAX_TTL:
                raise HubError('invalid_request', 'recovery access TTL must be 1 to 86400 seconds')
            if req.get('allow_read') is not True or type(req.get('allow_reply', False)) is not bool:
                raise HubError('invalid_request', 'explicit read/reply permissions required')
            c, ep = _candidate(h, host, req.get('candidate'), fresh=True)
            msg = h._row('SELECT * FROM messages WHERE message_id=?', (req.get('message_id'),))
            old = h._row('SELECT * FROM endpoints WHERE endpoint_id=?', (msg['recipient_endpoint'],)) if msg else None
            if not old or old['host_id'] != host or old['participant_id'] != ep['participant_id']:
                raise HubError('unauthorized', 'grant requires this owner and the original recipient participant')
            grant_id = str(uuid.uuid4())
            expires = h._now() + ttl
            h.db.execute('INSERT INTO message_recovery_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (grant_id, msg['message_id'], content_digest(dict(msg)), msg['recipient_endpoint'],
                          host, ep['participant_id'], c['native_kind'], c['native_id'],
                          int(req.get('allow_reply', False)), expires, 0, 1, actor))
            result = dict(grant_id=grant_id, message_id=msg['message_id'], revision=1, expires_at=expires,
                          allow_read=True, allow_reply=req.get('allow_reply', False))
        elif op == 'recovery_revoke':
            grant = h._row('SELECT * FROM message_recovery_grants WHERE grant_id=?', (req.get('grant_id'),))
            if not grant or grant['host_id'] != host:
                raise HubError('unauthorized', 'grant is not owned here')
            _revision(req, grant['revision'])
            h.db.execute('UPDATE message_recovery_grants SET revoked=1,revision=revision+1 WHERE grant_id=?', (grant['grant_id'],))
            result = dict(grant_id=grant['grant_id'], revoked=True, revision=grant['revision'] + 1)
        elif op == 'recovery_read':
            grant, ep, msg = _grant(h, host, req)
            view = h.message_views([msg], response_kind='query')[0]
            result = dict(message=view, grant_id=grant['grant_id'], archive=True,
                          data_origin='external_peer_message; historical recovery, not owner approval',
                          original_state=msg['state'], original_ttl_elapsed=msg['expires_at'] <= h._now())
            h._check_message_response(result)
        elif op == 'recovery_reply':
            grant, ep, msg = _grant(h, host, req)
            if not grant['allow_reply']:
                raise HubError('unauthorized', 'grant does not permit reply')
            mid = req.get('submission_id')
            if not isinstance(mid, str) or not 1 <= len(mid) <= 128:
                raise HubError('invalid_message', 'stable reply submission ID required')
            h.db.execute('INSERT OR IGNORE INTO message_recovery_replies VALUES(?,?,?,?,?)',
                         (mid, msg['message_id'], grant['grant_id'], host, ep['endpoint_id']))
            result = h.submit(dict(req, message=dict(message_id=mid, sender_endpoint=ep['endpoint_id'],
                                  in_reply_to=msg['message_id'], body=req.get('body', ''),
                                  recovery_grant=grant['grant_id'])), prepared=prepared)
        else:
            raise HubError('unknown_op', 'unsupported recipient/recovery operation')
        if op.startswith('recovery_'):
            h.db.execute('INSERT OR IGNORE INTO message_recovery_audit VALUES(?,?,?,?,?)',
                         (operation_id, result.get('grant_id', req.get('grant_id')), op, actor, h._now()))
        # Never retain recovered body or outgoing reply body in the management cache.
        cached = result if op != 'recovery_read' else dict(grant_id=req['grant_id'], message_id=req['message_id'])
        h.db.execute('INSERT OR IGNORE INTO recipient_operations VALUES(?,?,?)',
                     (operation_id, fingerprint, json.dumps(cached, sort_keys=True)))
        h._commit()
        if op == 'recovery_reply' and hasattr(h, 'flush_one'):
            pending = h._row('SELECT * FROM federated_outbox WHERE message_id=?', (req['submission_id'],))
            if pending:
                return h.flush_one(pending)
        return result
    except Exception:
        h._rollback()
        raise
