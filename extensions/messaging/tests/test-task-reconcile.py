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
