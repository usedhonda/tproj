import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.messaging.unified.tasks import TaskAuthority, TaskAuthorityError


CURRENT = {'endpoint_id':'new', 'incarnation':'new-inc', 'host_id':'host', 'project_id':'project'}
OTHER = {'endpoint_id':'other', 'incarnation':'other-inc', 'host_id':'host', 'project_id':'project'}
OLD = {'endpoint_id':'old', 'incarnation':'old-inc', 'host_id':'host', 'project_id':'project',
       'platform':'cdx', 'native_id':'native-1'}


def authority(status='accepted'):
    db = sqlite3.connect(':memory:', isolation_level=None)
    task = TaskAuthority(db)
    db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               ('task', 'key', 'i', 's', 'approval', 'owner', 'owner-inc', 'host', 'project',
                OTHER['endpoint_id'], OTHER['incarnation'], 'host', status, 1, '{}', 1.0, 1.0))
    db.execute('INSERT INTO task_assignments VALUES(?,?,?,?,?)', ('task', OLD['endpoint_id'], OLD['incarnation'], OLD['host_id'], 0))
    return task, db


class BindingReleaseTest(unittest.TestCase):
    def proof(self):
        return dict(OLD)

    def test_master_allows_former_assignment_only_read(self):
        task, db = authority()
        for index in range(10):
            db.execute("INSERT INTO task_operations VALUES(?,?,?,?,?,?,?,?)",
                       (f'other-token-{index}', 'task', 'other', 'other-inc', 1, f'other-tool-{index}', 'open', 1.0 + index))
        result = task.dispatch({'op':'binding_release_check','task_id':'task','expected_epoch':0,'previous':self.proof()}, CURRENT)
        self.assertTrue(result['allowed'])
        self.assertEqual(db.execute('SELECT COUNT(*) FROM task_assignments').fetchone()[0], 1)

    def test_master_rejects_old_open_current_owner_pending_and_frozen(self):
        for mode in ('old_open', 'current_owner', 'pending', 'frozen'):
            with self.subTest(mode=mode):
                task, db = authority('frozen' if mode == 'frozen' else 'accepted')
                actor = dict(CURRENT)
                if mode == 'current_owner':
                    db.execute("UPDATE tasks SET executor_endpoint='old', executor_incarnation='old-inc'")
                if mode == 'old_open':
                    db.execute("INSERT INTO task_operations VALUES('tok','task','old','old-inc',0,'tool','open',1.0)")
                if mode == 'pending':
                    db.execute("INSERT INTO task_handoffs VALUES('task',1,'old','old-inc','host','prepared',1.0)")
                with self.assertRaises(TaskAuthorityError):
                    task.dispatch({'op':'binding_release_check','task_id':'task','expected_epoch':0,'previous':self.proof()}, actor)

    def test_host_resynchronizes_only_exact_same_native_old_row(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
        import task_host

        class Host:
            def __init__(self):
                self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
                self.calls = []
            def hub(self, op, **kwargs):
                self.calls.append((op, kwargs))
                if op == 'endpoints_list':
                    return {'endpoints':[{'endpoint_id':'old','participant_id':'project:cdx','host_id':'host',
                                          'incarnation':'old-inc','platform':'cdx','retired':1}]}
                return {'allowed':True}

        with tempfile.TemporaryDirectory() as raw:
            host = Host()
            ep = {'endpoint_id':'new','incarnation':'new-inc','host_id':'host','project_id':'project',
                  'participant_id':'project:cdx','platform':'cdx','session_id':'native-1','project_path':'/project'}
            host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
            host.db.execute("INSERT INTO formal_task_binding VALUES('old','old-inc','task',0,'native-1')")
            host.db.commit()
            marker = Path(raw) / task_host.digest('native-1')
            marker.touch()
            with patch.dict(os.environ, {'TPROJ_TASK_BINDING_DIR':raw}):
                result = task_host.dispatch(host, ep, {'op':'task_detach','task_id':'task','expected_epoch':0})
            self.assertTrue(result['resynchronized'])
            self.assertIsNone(host.db.execute("SELECT 1 FROM formal_task_binding WHERE endpoint_id='old'").fetchone())
            self.assertFalse(marker.exists())
            self.assertEqual(host.calls[0][0], 'endpoints_list')
            self.assertEqual(host.calls[1][0], 'task_binding_release_check')

    def test_host_rejects_direct_internal_check_and_cross_native_without_cleanup(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
        import task_host

        class Host:
            def __init__(self):
                self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
            def hub(self, op, **kwargs):
                if op == 'endpoints_list':
                    return {'endpoints':[{'endpoint_id':'old','participant_id':'project:cdx','host_id':'host',
                                          'incarnation':'old-inc','platform':'cdx','retired':1}]}
                return {'allowed':True}

        with tempfile.TemporaryDirectory() as raw:
            host = Host(); host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
            host.db.execute("INSERT INTO formal_task_binding VALUES('old','old-inc','task',0,'native-1')"); host.db.commit()
            marker = Path(raw) / task_host.digest('native-1'); marker.touch()
            ep = {'endpoint_id':'new','incarnation':'new-inc','host_id':'host','project_id':'project',
                  'participant_id':'project:cdx','platform':'cdx','session_id':'other-native','project_path':'/project'}
            with patch.dict(os.environ, {'TPROJ_TASK_BINDING_DIR':raw}):
                with self.assertRaises(task_host.HubError):
                    task_host.dispatch(host, ep, {'op':'task_detach','task_id':'task','expected_epoch':0})
                with self.assertRaises(task_host.HubError):
                    task_host.dispatch(host, ep, {'op':'task_binding_release_check','task_id':'task','expected_epoch':0})
            self.assertIsNotNone(host.db.execute("SELECT 1 FROM formal_task_binding WHERE endpoint_id='old'").fetchone())
            self.assertTrue(marker.exists())


if __name__ == '__main__':
    unittest.main()
