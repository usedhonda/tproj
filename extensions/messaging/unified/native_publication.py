"""Durable reference publication on the existing delivery scheduler; no mailbox."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from native_notice import prepare, verify, content_digest
from native_consumer import _hook_binding, owns
from native_queue import LIMIT, QueueError, _queued
from protocol import HubError

KEY = '_native_publication'


class Job:
    """One owned non-AI transport child. poll never waits for socket I/O."""
    def __init__(self, packet, directory):
        raw = json.dumps(packet, ensure_ascii=False).encode()
        if len(raw) > LIMIT: raise QueueError('request_too_large')
        self.packet = packet
        self.data = bytearray()
        self.started = time.monotonic()
        self.done = False
        self.process = None
        fd, filename = tempfile.mkstemp(prefix='.native-io-', dir=directory)
        self.path = Path(filename)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
            env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TMPDIR', 'HOME') if k in os.environ}
            self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('native_queue.py')),
                '--worker', str(self.path)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, env=env, cwd=Path(__file__).parent)
            os.set_blocking(self.process.stdout.fileno(), False)
        except Exception:
            if self.process is not None:
                try:
                    self.process.kill()
                    self.process.wait(timeout=.2)
                except (OSError, subprocess.TimeoutExpired): pass
                if self.process.stdout: self.process.stdout.close()
            self.path.unlink(missing_ok=True)
            raise

    def poll(self):
        if self.done: return self.result
        try:
            while len(self.data) <= LIMIT:
                try: chunk = os.read(self.process.stdout.fileno(), min(65536, LIMIT + 1 - len(self.data)))
                except BlockingIOError: break
                if not chunk: break
                self.data.extend(chunk)
            timeout = time.monotonic() - self.started >= 15
            if len(self.data) > LIMIT or timeout:
                self.process.kill()
                try: self.process.wait(timeout=.2)
                except subprocess.TimeoutExpired: pass
                return self._finish({'ok': False, 'code': 'publication_unknown' if self.packet['op'] == 'publish' else 'transport_unavailable'})
            if self.process.poll() is None: return None
            # Exit can race the first EAGAIN. Drain the final pipe bytes before
            # interpreting the child result; never turn that race into loss.
            while len(self.data) <= LIMIT:
                try: chunk = os.read(self.process.stdout.fileno(), min(65536, LIMIT + 1 - len(self.data)))
                except BlockingIOError: break
                if not chunk: break
                self.data.extend(chunk)
            if len(self.data) > LIMIT:
                return self._finish({'ok': False, 'code': 'publication_unknown'})
            try:
                result = json.loads(self.data)
                if (not isinstance(result, dict) or type(result.get('ok')) is not bool
                        or (result['ok'] and not isinstance(result.get('result'), dict))
                        or (not result['ok'] and not isinstance(result.get('code'), str))):
                    raise ValueError('invalid worker result')
            except (ValueError, UnicodeError):
                result = {'ok': False, 'code': 'publication_unknown' if self.packet['op'] == 'publish' else 'transport_unavailable'}
            return self._finish(result)
        except Exception:
            self.process.kill()
            try: self.process.wait(timeout=.2)
            except subprocess.TimeoutExpired: pass
            return self._finish({'ok': False, 'code': 'publication_unknown' if self.packet['op'] == 'publish' else 'transport_unavailable'})

    def _finish(self, result):
        self.done = True
        self.result = result
        self.process.stdout.close()
        self.path.unlink(missing_ok=True)
        return result


def metadata(row):
    value = json.loads(row['envelope'])
    saved = value.get(KEY)
    return saved if isinstance(saved, dict) else {}


def store(host, row, value):
    """CAS metadata only: never overwrite body-state/receipt or another attempt."""
    envelope = json.loads(row['envelope'])
    envelope[KEY] = value
    count = host.db.execute('UPDATE deliveries SET envelope=? WHERE message_id=? AND endpoint_id=? AND envelope=?',
        (json.dumps(envelope, ensure_ascii=False), row['message_id'], row['endpoint_id'], row['envelope'])).rowcount
    host.db.commit()
    return count == 1


def report_wait(host, row, value, notice, operation):
    """Optional observed notification status, never a body/model receipt."""
    reason = {'queued': 'native_queue_accepted' if operation == 'publish' else 'native_queue_pending', 'unknown': 'native_publication_unknown',
              'reference_absent': 'native_retry_pending', 'ready': 'native_retry_pending'}.get(value.get('state'))
    if reason and row['state'] == 'received':
        observed = {k: notice[k] for k in ('incarnation', 'native_kind', 'native_id')}
        observed.update(attempt=value['attempt'], generation=value['generation'])
        try: host.delivery_status(row['endpoint_id'], row['message_id'], reason, native_observation=observed)
        except (HubError, OSError, ValueError): pass


class Publisher:
    def __init__(self):
        self.generation = str(uuid.uuid4())
        self.jobs = {}

    def maintain(self, host):
        """Drain every owned child on each existing scheduler tick, even off-path."""
        for mid, (job, attempt, notice) in list(self.jobs.items()):
            try: result = job.poll()
            except Exception:
                result = {'ok': False, 'code': 'publication_unknown' if job.packet['op'] == 'publish' else 'transport_unavailable'}
            if result is None: continue
            del self.jobs[mid]
            latest = host.db.execute('SELECT * FROM deliveries WHERE message_id=?', (mid,)).fetchone()
            if latest is None: continue
            saved = metadata(latest)
            if (saved.get('attempt') != attempt or saved.get('generation') != self.generation
                    or saved.get('state') == 'body_reserved'):
                continue
            value = dict(saved, checked_at=time.time())
            if not result['ok']:
                safe = result['code'] in ('socket_unavailable', 'dependency_unavailable', 'transport_unavailable',
                    'request_too_large', 'invalid_native_id', 'invalid_notice', 'operation_rejected')
                value.update(state='ready' if job.packet['op'] == 'publish' and safe else 'unknown', reason=result['code'])
                if job.packet['op'] == 'publish' and not safe:
                    value['last_unknown_publication'] = dict(attempt=attempt, generation=self.generation, reason=result['code'])
            elif job.packet['op'] == 'publish':
                item = result['result'].get('queuedSubmission')
                if (_queued(item) and item['clientUserMessageId'] == notice['client_id']
                        and len(item['input']) == 1 and item['input'][0].get('type') == 'text'
                        and item['input'][0].get('text') == notice['prompt']):
                    value.update(state='queued', queue_id=item['id'], reason=None)
                else:
                    value.update(state='unknown', reason='invalid_worker_result',
                        last_unknown_publication=dict(attempt=attempt, generation=self.generation, reason='invalid_worker_result'))
            else:
                page = result['result']
                if (not isinstance(page.get('data'), list) or len(page['data']) > 32
                        or any(not _queued(x) for x in page['data'])
                        or 'nextCursor' not in page
                        or (page['nextCursor'] is not None and not isinstance(page['nextCursor'], str))):
                    value.update(state='unknown', reason='invalid_worker_result')
                    if store(host, latest, value): report_wait(host, latest, value, notice, job.packet['op'])
                    continue
                matches = [x for x in page['data'] if x.get('clientUserMessageId') == notice['client_id']
                    and len(x.get('input', [])) == 1 and x['input'][0].get('type') == 'text'
                    and x['input'][0].get('text') == notice['prompt']]
                if matches:
                    value.update(state='queued', queue_id=matches[0]['id'], cursor=None, reason=None)
                else:
                    # Queue absence is not proof of non-consumption. It permits
                    # only another immutable reference wake, whose body resolve
                    # is fenced by the independent one-shot reservation CAS.
                    absent = page['nextCursor'] is None and latest['state'] == 'received'
                    value.update(state='reference_absent' if absent else 'unknown', cursor=page['nextCursor'],
                                 reason='reference_not_pending' if absent else
                                     ('queue_page_incomplete' if page['nextCursor'] is not None else 'publication_unconfirmed'))
            if store(host, latest, value): report_wait(host, latest, value, notice, job.packet['op'])

    def tick(self, host, ep, message_id):
        """One pinned claimed row; scheduler integration remains a separate step."""
        self.maintain(host)
        if (host.config.get('native_queue_enabled') is not True
                or host.config.get('native_consumer_enabled') is not True or ep.get('platform') != 'cdx'):
            return False
        native, _ = _hook_binding(host, ep)
        row = host.db.execute('SELECT * FROM deliveries WHERE message_id=?', (message_id,)).fetchone()
        if not row or row['endpoint_id'] != ep['endpoint_id']: raise QueueError('invalid_notice')
        if not owns(host.db, message_id):
            # Never convert historical/uncertain terminal injection into a new
            # native reference, or steal its existing receipt recovery path.
            if row['state'] != 'received': return False
            current = host.hub('query', endpoint_id=ep['endpoint_id'], message_id=message_id)
            if (current.get('recipient_endpoint') != ep['endpoint_id']
                    or content_digest(current) != content_digest(json.loads(row['envelope']))):
                raise QueueError('invalid_notice')
            if not current.get('delivery_summary', {}).get('new_presentation_eligible'):
                return True
        message = json.loads(row['envelope'])
        notice = prepare(host.db, ep, native, message)
        host.db.commit()
        verify(host.db, ep, native, message_id, notice['token'])
        value = metadata(row)
        # A native body reservation/receipt is independent of queue ACK. Do not
        # keep another notification outstanding after that reference was handled.
        if row['state'] in ('dispatching', 'uncertain', 'presented'):
            if value.get('state') != 'body_reserved':
                store(host, row, dict(value, state='body_reserved', checked_at=time.time()))
            return True
        if message_id in self.jobs: return True
        if value.get('state') == 'publishing':
            store(host, row, dict(value, state='unknown', generation=self.generation, reason='publisher_interrupted', checked_at=time.time(),
                last_unknown_publication=dict(attempt=value.get('attempt'), generation=value.get('generation'), reason='publisher_interrupted')))
            return True
        if value.get('state') == 'not_eligible': return True
        if time.time() - float(value.get('checked_at', 0)) < 30: return True
        # Serialize new notices within this native endpoint. New arrivals remain
        # durable Hub rows and are found by the next normal scheduler scan.
        if any(job.packet['native_id'] == native['native_id'] for job, _, _ in self.jobs.values()): return True
        operation = 'pending' if value.get('state') in ('unknown', 'queued') else 'publish'
        for other in host.db.execute("SELECT envelope,message_id FROM deliveries WHERE endpoint_id=? AND state='received'", (ep['endpoint_id'],)):
            if (operation == 'publish' and other['message_id'] != message_id
                    and metadata(other).get('state') in ('publishing', 'queued')):
                # A cancelled/expired leader may no longer be claimed at all.
                # Its stale local queue label must not starve later originals.
                current_other = host.hub('query', endpoint_id=ep['endpoint_id'], message_id=other['message_id'])
                if (current_other.get('recipient_endpoint') != ep['endpoint_id']
                        or content_digest(current_other) != content_digest(json.loads(other['envelope']))):
                    raise QueueError('invalid_notice')
                if current_other.get('delivery_summary', {}).get('new_presentation_eligible'):
                    return True
        attempt = str(uuid.uuid4())
        if operation == 'publish':
            # Includes known-unsubmitted retries: ownership of a prepared token
            # never carries yesterday's cancellation/expiry decision forward.
            current = host.hub('query', endpoint_id=ep['endpoint_id'], message_id=message_id)
            if (current.get('recipient_endpoint') != ep['endpoint_id']
                    or content_digest(current) != content_digest(message)):
                raise QueueError('invalid_notice')
            if not current.get('delivery_summary', {}).get('new_presentation_eligible'):
                store(host, row, dict(value, state='not_eligible', reason='latest_hub_ineligible', checked_at=time.time()))
                return True
        packet = dict(op=operation, socket=host.config.get('native_queue_socket'), native_id=native['native_id'])
        if operation == 'publish': packet['notice'] = notice
        else: packet['cursor'] = value.get('cursor')
        value = dict(value, state='publishing' if operation == 'publish' else 'unknown',
                     attempt=attempt, generation=self.generation, checked_at=time.time())
        if not store(host, row, value): return True
        try:
            self.jobs[message_id] = (Job(packet, Path(host.config['journal']).parent), attempt, notice)
        except Exception:
            latest = host.db.execute('SELECT * FROM deliveries WHERE message_id=?', (message_id,)).fetchone()
            store(host, latest, dict(value, state='unknown', reason='publisher_start_unknown'))
        return True
