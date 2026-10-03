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
            {'type':'response_item','payload':{'type':'item_completed','thread_id':thread,'item':item}},
        ]
        file.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')

    def test_exact_file_change_witness_only(self):
        with tempfile.TemporaryDirectory() as raw:
            self.write_transcript(raw, 'native-thread', {'type':'FileChange','id':'op-1','status':'completed','started_at_ms':2000,'completed_at_ms':3000})
            ep={'platform':'cdx','thread_id':'native-thread','project_path':'/project'}
            with patch.object(task_host.Path, 'home', return_value=Path(raw)), patch.object(task_host.Path, 'is_symlink', return_value=False):
                self.assertTrue(task_host._file_change_witness(ep, 'op-1', 1.5))
                self.assertFalse(task_host._file_change_witness(ep, 'op-2', 1.5))
                self.assertFalse(task_host._file_change_witness(ep, 'op-1', 2.5))

    def test_wrong_thread_and_text_mention_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            self.write_transcript(raw, 'native-thread', {'type':'message','text':'FileChange op-1 completed'})
            ep={'platform':'cdx','thread_id':'other-thread','project_path':'/project'}
            with patch.object(task_host.Path, 'home', return_value=Path(raw)), patch.object(task_host.Path, 'is_symlink', return_value=False):
                self.assertFalse(task_host._file_change_witness(ep, 'op-1', 1.5))


if __name__ == '__main__':
    unittest.main()
