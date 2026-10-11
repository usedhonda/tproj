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

    def test_master_cancelled_release_preserves_open_operations_as_unresolved_history(self):
        task, db = authority('cancelled')
        with self.assertRaises(TaskAuthorityError):
            task.dispatch({'op':'cancelled_release_check','task_id':'task','expected_epoch':0}, CURRENT)
        db.execute("UPDATE tasks SET executor_endpoint='new', executor_incarnation='new-inc'")
        result = task.dispatch({'op':'cancelled_release_check','task_id':'task','expected_epoch':1}, CURRENT)
        self.assertTrue(result['allowed'])
        db.execute("INSERT INTO task_operations VALUES('tok','task','new','new-inc',1,'tool','open',1.0)")
        result = task.dispatch({'op':'cancelled_release_check','task_id':'task','expected_epoch':1}, CURRENT)
        self.assertEqual(result['unresolved_operations'], 1)
        self.assertEqual(result['unresolved_operation_details'], [{'tool_use_id':'tool','epoch':1}])

    def test_master_cancelled_release_accepts_authenticated_former_incarnation(self):
        task, db = authority('cancelled')
        db.execute("UPDATE tasks SET executor_endpoint='old', executor_incarnation='old-inc', executor_host_id='host', epoch=0")
        result = task.dispatch({
            'op': 'cancelled_release_check', 'task_id': 'task', 'expected_epoch': 0,
            'native_id': 'native-1', 'previous': self.proof(),
        }, CURRENT)
        self.assertTrue(result['allowed'])

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
            self.assertEqual(task_host.dispatch(host, ep, {'op':'task_detach','task_id':'task','expected_epoch':0}), {'detached':True})

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
            Path(raw, task_host.digest('other-native')).touch()
            ep = {'endpoint_id':'new','incarnation':'new-inc','host_id':'host','project_id':'project',
                  'participant_id':'project:cdx','platform':'cdx','session_id':'other-native','project_path':'/project'}
            with patch.dict(os.environ, {'TPROJ_TASK_BINDING_DIR':raw}):
                with self.assertRaises(task_host.HubError):
                    task_host.dispatch(host, ep, {'op':'task_detach','task_id':'task','expected_epoch':0})
                with self.assertRaises(task_host.HubError):
                    task_host.dispatch(host, ep, {'op':'task_binding_release_check','task_id':'task','expected_epoch':0})
            self.assertIsNotNone(host.db.execute("SELECT 1 FROM formal_task_binding WHERE endpoint_id='old'").fetchone())
            self.assertTrue(marker.exists())

    def test_host_rejects_wrong_task_epoch_and_ambiguous_old_row(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
        import task_host

        class Host:
            def __init__(self, ambiguous=False):
                self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
                self.ambiguous = ambiguous
            def hub(self, op, **kwargs):
                if op == 'endpoints_list':
                    old = {'endpoint_id':'old','participant_id':'project:cdx','host_id':'host',
                           'incarnation':'old-inc','platform':'cdx','retired':1}
                    return {'endpoints':[old, dict(old)] if self.ambiguous else [old]}
                return {'allowed':True}

        ep = {'endpoint_id':'new','incarnation':'new-inc','host_id':'host','project_id':'project',
              'participant_id':'project:cdx','platform':'cdx','session_id':'native-1','project_path':'/project'}
        for mode, task_id, epoch in (('wrong_task','other',0), ('wrong_epoch','task',1), ('ambiguous','task',0)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as raw:
                host = Host(mode == 'ambiguous')
                host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
                host.db.execute("INSERT INTO formal_task_binding VALUES('old','old-inc','task',0,'native-1')"); host.db.commit()
                if mode == 'ambiguous':
                    host.db.execute("INSERT INTO formal_task_binding VALUES('old2','old2-inc','task',0,'native-1')"); host.db.commit()
                marker = Path(raw) / task_host.digest('native-1'); marker.touch()
                with patch.dict(os.environ, {'TPROJ_TASK_BINDING_DIR':raw}), self.assertRaises(task_host.HubError):
                    task_host.dispatch(host, ep, {'op':'task_detach','task_id':task_id,'expected_epoch':epoch})
                self.assertIsNotNone(host.db.execute("SELECT 1 FROM formal_task_binding WHERE endpoint_id='old'").fetchone())
                self.assertTrue(marker.exists())

    def test_cancelled_release_clears_exact_bound_marker_only_after_master_check(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
        import task_host

        class Host:
            def __init__(self):
                self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
                self.calls = []
            def hub(self, op, **kwargs):
                self.calls.append((op, kwargs))
                if op == 'task_cancelled_release_check':
                    return {'allowed': True, 'status': 'cancelled', 'unresolved_operations': 2}
                raise AssertionError(op)

        with tempfile.TemporaryDirectory() as raw:
            host = Host(); host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
            host.db.execute("INSERT INTO formal_task_binding VALUES('executor','inc','cancelled-task',0,'native-cancelled')"); host.db.commit()
            marker = Path(raw) / task_host.digest('native-cancelled'); marker.touch()
            ep = {'endpoint_id':'executor','incarnation':'inc','host_id':'host','project_id':'project',
                  'platform':'cdx','session_id':'native-cancelled','project_path':'/project'}
            with patch.dict(os.environ, {'TPROJ_TASK_BINDING_DIR':raw}):
                result = task_host.dispatch(host, ep, {'op':'task_release_cancelled','task_id':'cancelled-task','expected_epoch':0})
            self.assertEqual(result['unresolved_operations'], 2)
            self.assertIsNone(host.db.execute("SELECT 1 FROM formal_task_binding WHERE endpoint_id='executor'").fetchone())
            self.assertFalse(marker.exists())
            self.assertEqual(host.calls[0][0], 'task_cancelled_release_check')

    def test_cancelled_release_keeps_binding_when_master_rejects_open_operation(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
        import task_host

        class Host:
            def __init__(self):
                self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
            def hub(self, op, **kwargs):
                raise task_host.HubError('operations_open', 'cancelled assignment still has open operations')

        with tempfile.TemporaryDirectory() as raw:
            host = Host(); host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
            host.db.execute("INSERT INTO formal_task_binding VALUES('executor','inc','cancelled-task',0,'native-cancelled')"); host.db.commit()
            marker = Path(raw) / task_host.digest('native-cancelled'); marker.touch()
            ep = {'endpoint_id':'executor','incarnation':'inc','host_id':'host','project_id':'project',
                  'platform':'cdx','session_id':'native-cancelled','project_path':'/project'}
            with patch.dict(os.environ, {'TPROJ_TASK_BINDING_DIR':raw}), self.assertRaises(task_host.HubError):
                task_host.dispatch(host, ep, {'op':'task_release_cancelled','task_id':'cancelled-task','expected_epoch':0})
            self.assertIsNotNone(host.db.execute("SELECT 1 FROM formal_task_binding WHERE endpoint_id='executor'").fetchone())
            self.assertTrue(marker.exists())

    def test_retired_operation_is_fenced_after_new_binding(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
        import task_host
        class Host:
            def __init__(self):
                self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
            def hub(self, op, **kwargs):
                raise AssertionError('late retired operation reached hub')
        host = Host()
        ep = {'endpoint_id':'executor','incarnation':'inc','host_id':'host','project_id':'project',
              'platform':'cdx','session_id':'native-cancelled','project_path':'/project'}
        host.db.execute('CREATE TABLE formal_task_retired(task_id TEXT, epoch INTEGER, native_id TEXT, tool_use_id TEXT)')
        host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
        host.db.execute('INSERT INTO formal_task_retired VALUES(?,?,?,?)', ('old-task', 0, 'native-cancelled', 'old-op'))
        host.db.execute('INSERT INTO formal_task_binding VALUES(?,?,?,?,?)', ('executor','inc','new-task',1,'native-cancelled'))
        with self.assertRaisesRegex(task_host.HubError, 'retired'):
            task_host.dispatch(host, ep, {'op':'task_guard_begin','tool_use_id':'old-op'})

    def test_cancelled_release_accepts_same_native_after_incarnation_restart(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
        import task_host

        class Host:
            def __init__(self):
                self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
                self.calls = []
            def hub(self, op, **kwargs):
                self.calls.append((op, kwargs))
                if op == 'task_cancelled_release_check':
                    self.assert_previous = kwargs.get('previous')
                    return {'allowed': True, 'status': 'cancelled', 'unresolved_operations': 0}
                raise AssertionError(op)

        with tempfile.TemporaryDirectory() as raw:
            host = Host()
            host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
            host.db.execute("INSERT INTO formal_task_binding VALUES('executor','old-inc','cancelled-task',0,'native-restart')")
            host.db.commit()
            marker = Path(raw) / task_host.digest('native-restart'); marker.touch()
            ep = {'endpoint_id':'executor','incarnation':'new-inc','host_id':'host','project_id':'project',
                  'platform':'cdx','session_id':'native-restart','project_path':'/project'}
            with patch.dict(os.environ, {'TPROJ_TASK_BINDING_DIR':raw}):
                result = task_host.dispatch(host, ep, {'op':'task_release_cancelled','task_id':'cancelled-task','expected_epoch':0})
            self.assertTrue(result['released'])
            self.assertEqual(host.calls[0][1]['previous']['incarnation'], 'old-inc')
            self.assertFalse(marker.exists())

    def test_detach_receipt_replays_after_marker_cleanup_failure_without_clearing_new_binding(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
        import task_host

        class Host:
            def __init__(self):
                self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
            def hub(self, op, **kwargs):
                if op == 'task_status':
                    return {'task': {'task_id':'task','epoch':0,'status':'cancelled',
                                     'executor_endpoint':'executor','executor_incarnation':'inc','executor_host_id':'host'},
                            'handoff': None, 'actor_open_operations': 0}
                raise AssertionError(op)

        with tempfile.TemporaryDirectory() as raw:
            host = Host()
            host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
            host.db.execute("INSERT INTO formal_task_binding VALUES('executor','inc','task',0,'native-detach')"); host.db.commit()
            marker = Path(raw) / task_host.digest('native-detach'); marker.touch()
            ep = {'endpoint_id':'executor','incarnation':'inc','host_id':'host','project_id':'project',
                  'platform':'cdx','session_id':'native-detach','project_path':'/project'}
            original_unlink = Path.unlink
            calls = {'n': 0}
            def fail_once(path, *args, **kwargs):
                if path == marker and calls['n'] == 0:
                    calls['n'] += 1
                    raise OSError('simulated crash before marker cleanup')
                return original_unlink(path, *args, **kwargs)
            with patch.dict(os.environ, {'TPROJ_TASK_BINDING_DIR':raw}), patch.object(Path, 'unlink', fail_once):
                with self.assertRaises(OSError):
                    task_host.dispatch(host, ep, {'op':'task_detach','task_id':'task','expected_epoch':0})
                self.assertIsNone(host.db.execute('SELECT 1 FROM formal_task_binding').fetchone())
                host.db.execute("INSERT INTO formal_task_binding VALUES('executor','inc2','new-task',1,'native-detach')")
                host.db.commit()
                with self.assertRaises(task_host.HubError):
                    task_host.dispatch(host, {**ep, 'incarnation':'inc'}, {'op':'task_detach','task_id':'task','expected_epoch':0})


if __name__ == '__main__':
    unittest.main()
