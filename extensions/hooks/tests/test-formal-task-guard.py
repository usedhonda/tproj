import io
import json
import sqlite3
import os
from importlib.machinery import SourceFileLoader
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
guard = SourceFileLoader("formal_guard", str(ROOT / "hooks/tproj-formal-task-guard")).load_module()

class FormalGuardTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        cfg = Path(self.home.name)/'host.json'
        cfg.write_text('{}')
        env = patch.dict(os.environ, {'TPROJ_MSG_HOST_CONFIG':str(cfg), 'TPROJ_TASK_BINDING_DIR':str(Path(self.home.name)/'markers'), 'CODEX_THREAD_ID':'n1'})
        env.start(); self.addCleanup(env.stop)

    def run_hook(self, value):
        with patch("sys.stdin", io.StringIO(json.dumps(value))), patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = guard.main()
        return rc, json.loads(out.getvalue())

    def _bound(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(); db = Path(self.tmp.name) / "host.db"
        con = sqlite3.connect(db); con.execute("CREATE TABLE formal_task_binding(endpoint_id TEXT, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)"); con.execute("INSERT INTO formal_task_binding VALUES('e','i','t',0,'n1')"); con.commit(); con.close()
        cfg = Path(self.tmp.name) / "msg-host.json"; cfg.write_text(json.dumps({"journal": str(db)})); self.env = patch.dict(os.environ, {"TPROJ_MSG_HOST_CONFIG": str(cfg), "CODEX_THREAD_ID": "n1"}); self.env.start(); self.addCleanup(self.env.stop); self.addCleanup(self.tmp.cleanup)

    def test_unassigned_is_fail_open(self):
        with patch.object(guard.cli, "config", return_value={"socket": "x"}), patch.object(guard.cli, "rpc", return_value={"assigned": False}):
            rc, result = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual((rc, result["decision"]), (0, "allow"))

    def test_bound_host_unavailable_denies(self):
        self._bound()
        with patch.object(guard.cli, "config", side_effect=guard.cli.ClientError("offline")):
            _, result = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual(result["decision"], "block")

    def test_durable_marker_blocks_when_journal_cannot_be_read(self):
        marker=guard.binding_marker('n1')
        marker.parent.mkdir(parents=True)
        marker.touch()
        with patch.object(guard.cli, "config", side_effect=guard.cli.ClientError("offline")):
            _, result=self.run_hook({"tool_name":"Bash", "tool_use_id":"u1", "tool_input":{"command":"touch file"}})
        self.assertEqual(result['decision'],'block')

    def test_corrupt_journal_never_means_unassigned(self):
        self._bound()
        cfg=json.loads(Path(os.environ['TPROJ_MSG_HOST_CONFIG']).read_text())
        Path(cfg['journal']).write_bytes(b'not a database')
        _, result=self.run_hook({"tool_name":"Bash", "tool_use_id":"u1", "tool_input":{"command":"touch file"}})
        self.assertEqual(result['decision'],'block')

    def test_old_epoch_rejection_denies_post(self):
        self._bound()
        with patch.object(guard.cli, "config", return_value={"socket": "x"}), patch.object(guard.cli, "rpc", side_effect=guard.cli.ClientError("epoch", "epoch_conflict")):
            _, result = self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual(result["decision"], "block")

    def test_failed_tool_completion_closes_the_same_operation(self):
        self._bound()
        seen=[]
        with patch.object(guard.cli,'config',return_value={'socket':'x'}), patch.object(guard.cli,'_caller_request',side_effect=lambda op,**kw:dict(kw,op=op)), patch.object(guard.cli,'rpc',side_effect=lambda socket,req:seen.append(req) or {'closed':True}):
            for event in ('PostToolUseFailure','PostToolUse'):
                _,result=self.run_hook({'hook_event_name':event,'tool_name':'Bash','tool_use_id':'original','tool_input':{'command':'touch file'},'tool_response':{'exit_code':17}})
                self.assertEqual(result['decision'],'allow')
        self.assertEqual([(r['op'],r['tool_use_id']) for r in seen],[('task_guard_end','original')]*2)

    def test_bound_semicolon_and_unknown_exec_are_guarded(self):
        self._bound()
        with patch.object(guard.cli, "config", return_value={"socket": "x"}), patch.object(guard.cli, "rpc", side_effect=guard.cli.ClientError("epoch", "epoch_conflict")):
            _, semicolon = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u2", "tool_input": {"command": "tproj-task status x; rm -rf ."}})
            _, unknown = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "functions.exec", "tool_use_id": "u3", "tool_input": {"code": "os.unlink('x')"}})
        self.assertEqual(semicolon["decision"], "block")
        self.assertEqual(unknown["decision"], "block")

if __name__ == "__main__": unittest.main()
