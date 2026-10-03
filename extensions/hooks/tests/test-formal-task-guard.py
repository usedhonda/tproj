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
    def run_hook(self, value):
        with patch("sys.stdin", io.StringIO(json.dumps(value))), patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = guard.main()
        return rc, json.loads(out.getvalue())

    def _bound(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(); db = Path(self.tmp.name) / "host.db"
        con = sqlite3.connect(db); con.execute("CREATE TABLE formal_task_binding(endpoint_id TEXT, incarnation TEXT, task_id TEXT, epoch INTEGER, native_id TEXT)"); con.execute("INSERT INTO formal_task_binding VALUES('e','i','t',0,'n1')"); con.commit(); con.close()
        cfg = Path(self.tmp.name) / "msg-host.json"; cfg.write_text(json.dumps({"journal": str(db)})); self.env = patch.dict(os.environ, {"TPROJ_MSG_HOST_CONFIG": str(cfg), "CODEX_THREAD_ID": "n1"}); self.env.start()

    def test_unassigned_is_fail_open(self):
        with patch.object(guard.cli, "config", return_value={"socket": "x"}), patch.object(guard.cli, "rpc", return_value={"assigned": False}):
            rc, result = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual((rc, result["decision"]), (0, "allow"))

    def test_bound_host_unavailable_denies(self):
        self._bound()
        with patch.object(guard.cli, "config", side_effect=guard.cli.ClientError("offline")):
            _, result = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual(result["decision"], "block")

    def test_old_epoch_rejection_denies_post(self):
        self._bound()
        with patch.object(guard.cli, "config", return_value={"socket": "x"}), patch.object(guard.cli, "rpc", side_effect=guard.cli.ClientError("epoch", "epoch_conflict")):
            _, result = self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual(result["decision"], "block")

    def test_bound_semicolon_and_unknown_exec_are_guarded(self):
        self._bound()
        with patch.object(guard.cli, "config", return_value={"socket": "x"}), patch.object(guard.cli, "rpc", side_effect=guard.cli.ClientError("epoch", "epoch_conflict")):
            _, semicolon = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u2", "tool_input": {"command": "tproj-task status x; rm -rf ."}})
            _, unknown = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "functions.exec", "tool_use_id": "u3", "tool_input": {"code": "os.unlink('x')"}})
        self.assertEqual(semicolon["decision"], "block")
        self.assertEqual(unknown["decision"], "block")

if __name__ == "__main__": unittest.main()
