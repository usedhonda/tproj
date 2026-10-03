import io
import json
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

    def test_unassigned_is_fail_open(self):
        with patch.object(guard.cli, "config", return_value={"socket": "x"}), patch.object(guard.cli, "rpc", return_value={"assigned": False}):
            rc, result = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual((rc, result["decision"]), (0, "allow"))

    def test_bound_host_unavailable_denies(self):
        with patch.object(guard.cli, "config", side_effect=guard.cli.ClientError("offline")):
            _, result = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual(result["decision"], "block")

    def test_old_epoch_rejection_denies_post(self):
        with patch.object(guard.cli, "config", return_value={"socket": "x"}), patch.object(guard.cli, "rpc", side_effect=guard.cli.ClientError("epoch", "epoch_conflict")):
            _, result = self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": "rm file"}})
        self.assertEqual(result["decision"], "block")

if __name__ == "__main__": unittest.main()
