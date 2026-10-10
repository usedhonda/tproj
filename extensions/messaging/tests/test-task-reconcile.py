import json
import sqlite3
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
import task_host


class TaskReconcileWitnessTest(unittest.TestCase):
    def write_transcript(self, root, thread, item):
        path = Path(root) / '.codex/sessions/2026/01/01'
        path.mkdir(parents=True)
        file = path / ('rollout-test-' + thread + '.jsonl')
        rows = [
            {'type':'session_meta','payload':{'id':thread,'cwd':'/project'}},
            {'type':'event_msg','payload':{'type':'item_completed','thread_id':thread,'item':item,
                                            'started_at_ms':2000,'completed_at_ms':3000}},
        ]
        file.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')

    def test_exact_file_change_witness_only(self):
        thread = '11111111-1111-4111-8111-111111111111'
        with tempfile.TemporaryDirectory() as raw:
            self.write_transcript(raw, thread, {'type':'FileChange','id':'op-1','status':'completed'})
            ep={'platform':'cdx','thread_id':thread,'project_path':'/project'}
            with patch.object(task_host.Path, 'home', return_value=Path(raw)), patch.object(task_host.Path, 'is_symlink', return_value=False):
                self.assertTrue(task_host._file_change_witness(ep, 'op-1', 1.5))
                self.assertFalse(task_host._file_change_witness(ep, 'op-2', 1.5))
                self.assertFalse(task_host._file_change_witness(ep, 'op-1', 2.5))

    def write_cc_transcript(self, root, thread, rows):
        path = Path(root) / '.claude/projects/project'
        path.mkdir(parents=True)
        (path / (thread + '.jsonl')).write_text(
            '\n'.join(json.dumps(row) for row in rows) + '\n')

    def cc_rows(self, thread, *, project='/project', call_id='cc-1', result_id='cc-1',
                call_time='2026-01-01T00:00:02Z', result_time='2026-01-01T00:00:03Z',
                error=False, duplicate=False, text_only=False):
        call = {'type':'assistant','sessionId':thread,'cwd':project,
                'timestamp':call_time,
                'message':{'role':'assistant','content':([{'type':'text','text':'cc-1'}]
                    if text_only else [{'type':'tool_use','id':call_id,'name':'Bash','input':{}}])}}
        result = {'type':'user','sessionId':thread,'cwd':project,
                  'timestamp':result_time,
                  'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':result_id, 'is_error':error}]}}
        rows = [call, result]
        if duplicate:
            rows.insert(1, dict(call))
        return rows

    def test_exact_cc_tool_witness_and_denials(self):
        thread = '55555555-5555-4555-8555-555555555555'
        ep={'platform':'cc','session_id':thread,'project_path':'/project'}
        cases = {
            'wrong_session': (self.cc_rows('other'), ep, False),
            'wrong_project': (self.cc_rows(thread, project='/other'), ep, False),
            'precreation': (self.cc_rows(thread, call_time='2025-12-31T23:59:59Z', result_time='2025-12-31T23:59:59Z'), ep, False),
            'error': (self.cc_rows(thread, error=True), ep, False),
            'duplicate': (self.cc_rows(thread, duplicate=True), ep, False),
            'text_mention': (self.cc_rows(thread, text_only=True), ep, False),
            'missing_result': ([self.cc_rows(thread)[0]], ep, False),
        }
        with tempfile.TemporaryDirectory() as raw:
            self.write_cc_transcript(raw, thread, [{'type':'progress','sessionId':thread}, *self.cc_rows(thread)])
            with patch.object(task_host.Path, 'home', return_value=Path(raw)), patch.object(task_host.Path, 'is_symlink', return_value=False):
                self.assertTrue(task_host._cc_tool_witness(ep, 'cc-1', 1_767_225_602.5))
            for name, (rows, case_ep, expected) in cases.items():
                with self.subTest(name=name):
                    with tempfile.TemporaryDirectory() as denied:
                        self.write_cc_transcript(denied, thread, rows)
                        with patch.object(task_host.Path, 'home', return_value=Path(denied)), patch.object(task_host.Path, 'is_symlink', return_value=False):
                            self.assertEqual(task_host._cc_tool_witness(case_ep, 'cc-1', 1_767_225_601.0), expected)

    def test_cc_dispatch_selects_cc_witness(self):
        class Host:
            def __init__(self):
                self.db=sqlite3.connect(':memory:'); self.db.row_factory=sqlite3.Row; self.calls=[]
            def hub(self, op, **kwargs):
                self.calls.append((op, kwargs))
                if op == 'task_status':
                    return {'task':{'task_id':'t','epoch':0,'executor_endpoint':'e','executor_incarnation':'i','status':'in_progress'},
                            'handoff':None, 'actor_open_operation_details':[{'tool_use_id':'op-1','epoch':0,'created_at':1.5}]}
                return {'closed':True}
        host=Host(); host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
        host.db.execute("INSERT INTO formal_task_binding VALUES('e','i','t',0,'native')")
        ep={'endpoint_id':'e','incarnation':'i','host_id':'h','project_id':'p','platform':'cc','session_id':'native','project_path':'/project'}
        with patch.object(task_host, '_cc_tool_witness', return_value=True) as witness:
            result=task_host.dispatch(host, ep, {'op':'task_reconcile_operation','task_id':'t','expected_epoch':0,'tool_use_id':'op-1'})
        self.assertTrue(result['reconciled'])
        witness.assert_called_once_with(ep, 'op-1', 1.5)

    def test_wrong_thread_and_text_mention_are_rejected(self):
        thread = '22222222-2222-4222-8222-222222222222'
        with tempfile.TemporaryDirectory() as raw:
            self.write_transcript(raw, thread, {'type':'message','text':'FileChange op-1 completed'})
            ep={'platform':'cdx','thread_id':'33333333-3333-4333-8333-333333333333','project_path':'/project'}
            with patch.object(task_host.Path, 'home', return_value=Path(raw)), patch.object(task_host.Path, 'is_symlink', return_value=False):
                self.assertFalse(task_host._file_change_witness(ep, 'op-1', 1.5))

    def test_empty_or_nonobject_transcript_fails_closed(self):
        thread = '44444444-4444-4444-8444-444444444444'
        with tempfile.TemporaryDirectory() as raw:
            self.write_transcript(raw, thread, {'type':'FileChange','id':'op-1','status':'completed'})
            path = next((Path(raw) / '.codex/sessions/2026/01/01').glob('*.jsonl'))
            path.write_text('[]\n')
            ep={'platform':'cdx','thread_id':thread,'project_path':'/project'}
            with patch.object(task_host.Path, 'home', return_value=Path(raw)), patch.object(task_host.Path, 'is_symlink', return_value=False):
                self.assertFalse(task_host._file_change_witness(ep, 'op-1', 1.5))

    def test_dispatch_closes_only_matching_active_bound_operation(self):
        class Host:
            def __init__(self):
                self.db=sqlite3.connect(':memory:'); self.db.row_factory=sqlite3.Row; self.calls=[]
            def hub(self, op, **kwargs):
                self.calls.append((op, kwargs))
                if op == 'task_status':
                    return {'task':{'task_id':'t','epoch':0,'executor_endpoint':'e','executor_incarnation':'i','status':'in_progress'},
                            'handoff':None, 'actor_open_operation_details':[{'tool_use_id':'op-1','epoch':0,'created_at':1.5}]}
                return {'closed':True}
        host=Host(); host.db.execute('CREATE TABLE formal_task_binding(endpoint_id TEXT, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)')
        host.db.execute("INSERT INTO formal_task_binding VALUES('e','i','t',0,'native')")
        ep={'endpoint_id':'e','incarnation':'i','host_id':'h','project_id':'p','platform':'cdx','thread_id':'native','project_path':'/project'}
        with patch.object(task_host, '_file_change_witness', return_value=True):
            result=task_host.dispatch(host, ep, {'op':'task_reconcile_operation','task_id':'t','expected_epoch':0,'tool_use_id':'op-1'})
        self.assertTrue(result['reconciled'])
        self.assertEqual([call[0] for call in host.calls], ['task_status','task_end_operation'])


if __name__ == '__main__':
    unittest.main()
