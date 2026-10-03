import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.messaging.unified import task_cli


class UnifiedTaskCliTest(unittest.TestCase):
    def test_submit_uses_text_contract_and_native_request(self):
        seen = []
        with patch.object(task_cli, "request", side_effect=lambda op, **fields: seen.append((op, fields)) or {"ok": True}), \
             patch("sys.stdin", io.StringIO('{"body":"packet"}\n')):
            self.assertEqual(task_cli.main(["submit", "worker", "--intent", "Build X", "--scope", "Build X only", "--approval", "a1", "--stdin"]), 0)
        op, req = seen[0]
        self.assertEqual(op, "submit")
        self.assertEqual(req["intent"], "Build X")
        self.assertEqual(req["scope"], "Build X only")
        self.assertEqual(req["approval_id"], "a1")
        self.assertEqual(req["payload"], {"body": "packet"})

    def test_approval_reads_scope_file_and_never_accepts_selector(self):
        with tempfile.TemporaryDirectory() as raw:
            scope = Path(raw) / "scope.txt"
            scope.write_text("Implement the task", encoding="utf-8")
            seen = []
            with patch.object(task_cli, "request", side_effect=lambda op, **fields: seen.append((op, fields)) or {}):
                self.assertEqual(task_cli.main(["approval", "--intent", "Implement", "--scope-file", str(scope), "--evidence-hash", "e" * 64]), 0)
            op, req = seen[0]
            self.assertEqual(op, "approval")
            self.assertEqual(req["scope"], "Implement the task")
            self.assertNotIn("as", req)
            self.assertNotIn("intent_hash", req)

    def test_handoff_maps_to_authenticated_task_operation(self):
        seen = []
        with patch.object(task_cli, "request", side_effect=lambda op, **fields: seen.append((op, fields)) or {}):
            self.assertEqual(task_cli.main(["handoff", "prepare", "t1", "--epoch", "2", "--target", '{"endpoint_id":"e","incarnation":"i","host_id":"h"}']), 0)
        self.assertEqual(seen, [("prepare_handoff", {"task_id": "t1", "expected_epoch": 2, "target": {"endpoint_id": "e", "incarnation": "i", "host_id": "h"}})])


if __name__ == "__main__":
    unittest.main()
