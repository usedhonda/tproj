import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "unified"
SPEC = importlib.util.spec_from_file_location("runtime", ROOT / "runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimeDirectoryRegistrationTests(unittest.TestCase):
    def test_adds_only_missing_requested_projects_once(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            (home / "existing").mkdir(); (home / "new").mkdir(); (home / "disabled").mkdir(); (home / ".config/tproj").mkdir(parents=True)
            (home / ".config/tproj/msg-host.json").write_text('{"host_id":"h","socket":"/tmp/host.sock"}')
            runtime._workspace_payload = lambda _home: {"projects": [
                {"alias": "existing", "path": str(home / "existing")},
                {"alias": "new", "path": str(home / "new")},
                {"alias": "disabled", "path": str(home / "disabled"), "enabled": False},
            ]}
            calls = []
            current = {"revision": 4, "projects": [{"project_id": "p-existing", "alias": "existing", "host_id": "h", "path": str(home / "existing")}, {"project_id": "p-foreign", "alias": "foreign", "host_id": "other", "path": str(home / "new")}]}
            def fake_rpc(_socket, request):
                calls.append(request)
                if request["op"] == "directory": return current
                return {"revision": 5}
            runtime._host_rpc = fake_rpc
            result = runtime.register_projects(home)
            self.assertEqual(result["added"], ["p-" + runtime.hashlib.sha256(f"h\0{home / 'new'}".encode()).hexdigest()[:24]])
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["expected_revision"], 4)
            self.assertEqual([p["alias"] for p in calls[1]["projects"]], ["new"])
            self.assertEqual(runtime.register_projects(home, aliases=["existing"])["added"], [])
            calls.clear()
            self.assertEqual(runtime.register_projects(home, aliases=["disabled"])["added"], ["p-" + runtime.hashlib.sha256(f"h\0{home / 'disabled'}".encode()).hexdigest()[:24]])

    def test_conflict_and_offline_leave_directory_untouched(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw); project = home / "project"; project.mkdir(); (home / ".config/tproj").mkdir(parents=True)
            (home / ".config/tproj/msg-host.json").write_text('{"host_id":"h","socket":"/tmp/host.sock"}')
            runtime._workspace_payload = lambda _home: {"projects": [{"alias": "taken", "path": str(project)}]}
            runtime._host_rpc = lambda _socket, request: {"revision": 1, "projects": [{"project_id": "other", "alias": "taken", "host_id": "h", "path": "/else"}]} if request["op"] == "directory" else self.fail("mutation after conflict")
            with self.assertRaises(RuntimeError): runtime.register_projects(home)

            runtime._workspace_payload = lambda _home: {"projects": [{"alias": "renamed", "path": str(project)}]}
            runtime._host_rpc = lambda _socket, request: {"revision": 1, "projects": [{"project_id": "owner", "alias": "taken", "host_id": "h", "path": str(project)}]} if request["op"] == "directory" else self.fail("alias reassignment must not mutate")
            with self.assertRaisesRegex(RuntimeError, "different alias"):
                runtime.register_projects(home)

            runtime._host_rpc = lambda _socket, request: (_ for _ in ()).throw(OSError("offline"))
            with self.assertRaises(OSError): runtime.register_projects(home, aliases=["renamed"])

            runtime._workspace_payload = lambda _home: {"projects": [{"alias": "fresh", "path": str(project)}]}
            def stale_rpc(_socket, request):
                if request["op"] == "directory":
                    return {"revision": 2, "projects": []}
                raise RuntimeError("revision_conflict")
            runtime._host_rpc = stale_rpc
            with self.assertRaisesRegex(RuntimeError, "revision_conflict"):
                runtime.register_projects(home)


if __name__ == "__main__":
    unittest.main()
