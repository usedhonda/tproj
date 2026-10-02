import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "unified"))
from hub import Hub  # noqa: E402
from directory import prepare, commit  # noqa: E402


class DirectoryTransactionTests(unittest.TestCase):
    def test_prepare_commit_is_idempotent_and_owner_scoped(self):
        with tempfile.TemporaryDirectory() as d:
            hub = Hub(os.path.join(d, "hub.db"), {"host_id": "local", "hosts": {}})
            hub.local_id = "local"
            hub.db.execute("INSERT INTO projects(project_id,alias,host_id,path) VALUES(?,?,?,?)", ("p", "old", "local", "/p"))
            payload = {"expected_revision": 0, "projects": [{"project_id": "p", "alias": "new", "host_id": "local", "path": "/p"}]}
            self.assertEqual(prepare(hub, {"change_id": "c1", "payload": payload})["state"], "prepared")
            self.assertEqual(commit(hub, {"change_id": "c1"})["state"], "committed")
            self.assertEqual(commit(hub, {"change_id": "c1"})["state"], "committed")
            self.assertEqual(hub.db.execute("SELECT alias FROM projects WHERE project_id='p'").fetchone()[0], "new")
            hub.close()

    def test_rejects_project_id_repointing(self):
        with tempfile.TemporaryDirectory() as d:
            hub = Hub(os.path.join(d, "hub.db"), {"host_id": "local", "hosts": {}})
            hub.local_id = "local"
            hub.db.execute("INSERT INTO projects(project_id,alias,host_id,path) VALUES(?,?,?,?)", ("p", "old", "local", "/p"))
            payload = {"expected_revision": 0, "projects": [{"project_id": "p", "alias": "new", "host_id": "local", "path": "/other"}]}
            with self.assertRaisesRegex(Exception, "different host/path"):
                prepare(hub, {"change_id": "repoint", "payload": payload})
            hub.close()

    def test_rejects_duplicate_owner_location_with_new_id(self):
        with tempfile.TemporaryDirectory() as d:
            hub = Hub(os.path.join(d, "hub.db"), {"host_id": "local", "hosts": {}})
            hub.local_id = "local"
            hub.db.execute("INSERT INTO projects(project_id,alias,host_id,path) VALUES(?,?,?,?)", ("p", "old", "local", "/p"))
            payload = {"expected_revision": 0, "projects": [{"project_id": "new", "alias": "new", "host_id": "local", "path": "/p"}]}
            with self.assertRaisesRegex(Exception, "already belongs"):
                prepare(hub, {"change_id": "duplicate-location", "payload": payload})
            hub.close()


if __name__ == "__main__":
    unittest.main()
