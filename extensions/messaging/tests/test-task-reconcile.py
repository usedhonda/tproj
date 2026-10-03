import json
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


if __name__ == '__main__':
    unittest.main()
