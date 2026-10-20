import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'unified'))
import native_publication as pub
spec = importlib.util.spec_from_file_location('consumer_fixture', Path(__file__).with_name('test-native-consumer.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class PublicationTest(unittest.TestCase):
    setUp = fixtures.ConsumerTest.setUp

    def fixture(self):
        self.host.config.update(native_queue_enabled=True, native_queue_socket='fixture-private-socket')
        clock = [1000.0]
        self.patch_time = patch.object(pub.time, 'time', side_effect=lambda: clock[0])
        self.patch_time.start()
        self.addCleanup(self.patch_time.stop)
        created = []
        host = self.host
        class FakeJob:
            def __init__(self, packet, directory):
                self.packet = packet
                self.result = None
                # A different connection sees the attempt *before* I/O begins.
                db = sqlite3.connect(host.config['journal'])
                envelope = json.loads(db.execute('SELECT envelope FROM deliveries').fetchone()[0])
                db.close()
                assert envelope[pub.KEY]['attempt']
                created.append(self)
            def poll(self): return self.result
        patch_job = patch.object(pub, 'Job', FakeJob)
        patch_job.start()
        self.addCleanup(patch_job.stop)
        return clock, created

    def row(self):
        return self.host.db.execute("SELECT * FROM deliveries WHERE message_id='original'").fetchone()

    def success(self, job):
        n = job.packet['notice']
        return {'ok': True, 'result': {'queuedSubmission': {'id': 'queue-id',
            'clientUserMessageId': n['client_id'], 'input': [{'type': 'text', 'text': n['prompt']}]}}}

    def test_commit_before_io_and_ack_does_not_present_body_or_publish_twice(self):
        clock, jobs = self.fixture()
        publisher = pub.Publisher()
        publisher.tick(self.host, self.ep, 'original')
        self.assertEqual(pub.metadata(self.row())['state'], 'publishing')
        jobs[0].result = self.success(jobs[0])
        publisher.tick(self.host, self.ep, 'original')
        self.assertEqual(pub.metadata(self.row())['state'], 'queued')
        self.assertEqual(self.row()['state'], 'received')
        clock[0] += 60
        pub.Publisher().tick(self.host, self.ep, 'original')
        self.assertEqual(len(jobs), 1)
        self.assertEqual(json.loads(self.row()['envelope'])['body'], self.original['body'])

    def test_unknown_result_reconciles_pages_without_republication(self):
        clock, jobs = self.fixture()
        publisher = pub.Publisher()
        publisher.tick(self.host, self.ep, 'original')
        jobs[0].result = {'ok': False, 'code': 'publication_unknown'}
        publisher.tick(self.host, self.ep, 'original')
        clock[0] += 31
        publisher.tick(self.host, self.ep, 'original')
        self.assertEqual(jobs[1].packet['op'], 'pending')
        jobs[1].result = {'ok': True, 'result': {'data': [], 'nextCursor': 'opaque-next'}}
        publisher.tick(self.host, self.ep, 'original')
        clock[0] += 31
        publisher.tick(self.host, self.ep, 'original')
        self.assertEqual(jobs[2].packet['cursor'], 'opaque-next')
        item = self.success(jobs[0])['result']['queuedSubmission']
        jobs[2].result = {'ok': True, 'result': {'data': [item], 'nextCursor': None}}
        publisher.tick(self.host, self.ep, 'original')
        self.assertEqual(pub.metadata(self.row())['state'], 'queued')
        self.assertEqual(sum(j.packet['op'] == 'publish' for j in jobs), 1)

    def test_restart_fences_old_result_and_preserves_unknown(self):
        clock, jobs = self.fixture()
        old = pub.Publisher()
        old.tick(self.host, self.ep, 'original')
        new = pub.Publisher()
        new.tick(self.host, self.ep, 'original')
        jobs[0].result = self.success(jobs[0])
        old.maintain(self.host)
        saved = pub.metadata(self.row())
        self.assertEqual(saved['generation'], new.generation)
        self.assertEqual(saved['state'], 'unknown')
        self.assertNotIn('queue_id', saved)

    def test_body_reservation_does_not_get_overwritten_by_late_queue_ack(self):
        _, jobs = self.fixture()
        publisher = pub.Publisher()
        publisher.tick(self.host, self.ep, 'original')
        self.host.db.execute("UPDATE deliveries SET state='dispatching'")
        self.host.db.commit()
        publisher.tick(self.host, self.ep, 'original')
        jobs[0].result = self.success(jobs[0])
        publisher.maintain(self.host)
        self.assertEqual(pub.metadata(self.row())['state'], 'body_reserved')
        self.assertEqual(self.row()['state'], 'dispatching')

    def test_bad_worker_result_is_unknown_not_a_delivery_thread_crash(self):
        _, jobs = self.fixture()
        publisher = pub.Publisher()
        publisher.tick(self.host, self.ep, 'original')
        jobs[0].result = {'ok': True, 'result': {}}
        publisher.maintain(self.host)
        self.assertEqual(pub.metadata(self.row())['reason'], 'invalid_worker_result')

    def test_transport_poll_failure_cannot_kill_or_wedge_scheduler(self):
        _, jobs = self.fixture()
        publisher = pub.Publisher()
        publisher.tick(self.host, self.ep, 'original')
        with patch.object(jobs[0], 'poll', side_effect=OSError('fixture pipe error')):
            publisher.maintain(self.host)
        self.assertFalse(publisher.jobs)
        self.assertEqual(pub.metadata(self.row())['state'], 'unknown')

    def test_only_known_prepublication_failure_is_eligible_for_later_attempt(self):
        clock, jobs = self.fixture()
        publisher = pub.Publisher()
        publisher.tick(self.host, self.ep, 'original')
        jobs[0].result = {'ok': False, 'code': 'dependency_unavailable'}
        publisher.tick(self.host, self.ep, 'original')
        self.assertEqual(pub.metadata(self.row())['state'], 'ready')
        self.assertEqual(len(jobs), 1)
        clock[0] += 31
        publisher.tick(self.host, self.ep, 'original')
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].packet['notice']['token'], jobs[1].packet['notice']['token'])

    def test_historical_unknown_is_not_converted_or_replayed(self):
        _, jobs = self.fixture()
        self.host.db.execute('DELETE FROM native_notice_metadata')
        self.host.db.execute("UPDATE deliveries SET state='uncertain'")
        self.host.db.commit()
        self.assertFalse(pub.Publisher().tick(self.host, self.ep, 'original'))
        self.assertEqual(len(jobs), 0)
        self.assertEqual(self.host.db.execute('SELECT count(*) FROM native_notice_metadata').fetchone()[0], 0)

    def test_transport_child_timeout_is_bounded_and_cleans_private_packet(self):
        original_popen = subprocess.Popen
        def hung(*args, **kwargs):
            return original_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
        with patch.object(pub.subprocess, 'Popen', side_effect=hung):
            job = pub.Job({'op': 'publish'}, self.home)
        job.started -= 16
        self.assertEqual(job.poll(), {'ok': False, 'code': 'publication_unknown'})
        self.assertIsNotNone(job.process.poll())
        self.assertFalse(job.path.exists())


if __name__ == '__main__': unittest.main()
