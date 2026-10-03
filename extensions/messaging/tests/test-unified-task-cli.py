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
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as scope:
                scope.write("Build X only"); scope.flush()
                self.assertEqual(task_cli.main(["submit", "worker", "--intent", "Build X", "--scope-file", scope.name, "--approval", "a1", "--stdin"]), 0)
        op, req = seen[0]
        self.assertEqual(op, "submit")
        self.assertEqual(req["intent"], "Build X")
        self.assertEqual(req["scope"], "Build X only")
        self.assertEqual(req["approval_id"], "a1")
        self.assertEqual(req["executor"], "worker")
        self.assertEqual(req["payload"], {"body": "packet", "target": "worker"})

    def test_same_packet_retry_reuses_key_and_target_conflict_rejects(self):
        seen=[]
        with tempfile.TemporaryDirectory() as raw:
            scope=Path(raw)/'scope'; scope.write_text('Repair selected module')
            args=['submit','worker.cdx','--intent','Repair','--scope-file',str(scope),'--approval','a1']
            with patch.object(task_cli,'request',side_effect=lambda op,**fields: seen.append(fields) or {}):
                self.assertEqual(task_cli.main(args),0)
                self.assertEqual(task_cli.main(args),0)
                self.assertEqual(seen[0]['idempotency_key'],seen[1]['idempotency_key'])
                with patch('sys.stdin',io.StringIO('{"target":"other.cdx"}')):
                    self.assertEqual(task_cli.main(args+['--stdin']),2)
                self.assertEqual(len(seen),2)

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

    def test_enrolled_wrapper_does_not_fall_back_on_broken_config(self):
        import os, subprocess
        wrapper=Path(__file__).resolve().parents[1]/'tproj-task'
        with tempfile.TemporaryDirectory() as raw:
            cfg=Path(raw)/'client.json'; latch=Path(raw)/'enrolled'; latch.touch()
            env=dict(os.environ,TPROJ_UNIFIED_CONFIG=str(cfg),TPROJ_UNIFIED_LATCH=str(latch))
            for content in (None,'{broken','{"active":false}'):
                if content is not None: cfg.write_text(content)
                result=subprocess.run(['bash',str(wrapper),'status','old-id'],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,2)
                self.assertIn('configuration_error:',result.stderr)

    def test_handoff_maps_to_authenticated_task_operation(self):
        seen = []
        with patch.object(task_cli, "request", side_effect=lambda op, **fields: seen.append((op, fields)) or {}):
            self.assertEqual(task_cli.main(["handoff", "prepare", "t1", "--epoch", "2", "--target", "proj.cdx"]), 0)
        self.assertEqual(seen, [("prepare_handoff", {"task_id": "t1", "expected_epoch": 2, "target": "proj.cdx"})])


if __name__ == "__main__":
    unittest.main()
