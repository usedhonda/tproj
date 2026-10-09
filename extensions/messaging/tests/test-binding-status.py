import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unified"))
import task_cli
import task_host


class BindingStatusTest(unittest.TestCase):
    def test_parser_uses_only_authenticated_native_request(self):
        seen = []
        with patch.object(task_cli, "request", side_effect=lambda op, **fields: seen.append((op, fields)) or {}):
            self.assertEqual(task_cli.main(["binding-status"]), 0)
        self.assertEqual(seen, [("binding_status", {})])
        with self.assertRaises(SystemExit):
            task_cli.parser().parse_args(["binding-status", "caller-selected-native"])

    def test_stale_marker_and_old_endpoint_are_distinguished_without_writes(self):
        class Host:
            def __init__(self):
                self.db = sqlite3.connect(":memory:")
                self.db.row_factory = sqlite3.Row
                self.db.execute("CREATE TABLE formal_task_binding(endpoint_id TEXT PRIMARY KEY, incarnation TEXT NOT NULL, task_id TEXT NOT NULL, epoch INTEGER NOT NULL, native_id TEXT NOT NULL)")
                self.db.execute("INSERT INTO formal_task_binding VALUES('old-endpoint','old-inc','old-task',4,'native-thread')")
                self.db.commit()

            def hub(self, *args, **kwargs):
                raise AssertionError("old endpoint must not query task status")

        host = Host()
        ep = {"endpoint_id": "current-endpoint", "incarnation": "current-inc", "thread_id": "native-thread"}
        with tempfile.TemporaryDirectory() as raw, patch.dict("os.environ", {"TPROJ_TASK_BINDING_DIR": raw}):
            marker = task_host.binding_marker("native-thread")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
            before = host.db.total_changes
            result = task_host.dispatch(host, ep, {"op": "task_binding_status", "native_id": "redirect-me"})
            self.assertEqual(host.db.total_changes, before)
        self.assertTrue(result["marker_present"])
        self.assertEqual(result["current_binding"]["status"], "not_bound")
        self.assertEqual(result["matching_native_bindings_count"], 1)
        self.assertEqual(result["matching_native_bindings"], [{
            "task_id": "old-task", "epoch": 4,
            "current_endpoint": False, "current_incarnation": False,
        }])


if __name__ == "__main__":
    unittest.main()
