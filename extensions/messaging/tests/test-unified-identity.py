import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "unified" / "identity.py"
spec = importlib.util.spec_from_file_location("unified_identity", SOURCE)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class UnifiedIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.registry = root / "registry"
        self.registry.mkdir()
        self.projects = [{"project_id": "demo", "alias": "demo", "host_id": "host-a",
                          "path": str(self.project)}]
        self.record = {"alias": "demo.cc", "project": str(self.project), "pid": 101,
                       "pid_start": 77, "observed_at": 100, "session_id": "sess",
                       "runtime_id": "runtime-1", "pane": "%1"}
        (self.registry / "demo.cc.json").write_text(json.dumps(self.record))

    def live(self, pid):
        return {101: {"ppid": 1, "pid_start": 77, "uid": 501,
                      "command": "claude --session sess"}}[pid]

    def test_discovery_and_stable_incarnation(self):
        one = identity.discover_endpoints(self.registry, "host-a", self.projects,
                                          now=100, inspect_process=self.live)
        two = identity.discover_endpoints(self.registry, "host-a", self.projects,
                                          now=100, inspect_process=self.live)
        self.assertEqual(one, two)
        self.assertEqual(one[0]["participant_id"], "demo:cc")
        self.assertEqual(one[0]["address"], "demo.cc")
        self.assertEqual(one[0]["endpoint_id"], identity.discover_endpoints(
            self.registry, "host-a", self.projects, now=100, inspect_process=self.live)[0]["endpoint_id"])

    def test_stale_and_pid_reuse_and_proxy_are_rejected(self):
        self.assertEqual(identity.discover_endpoints(self.registry, "host-a", self.projects,
                                                     now=100 + 172801, inspect_process=self.live), [])
        self.record["observed_at"] = 100
        self.record["pid_start"] = 78
        (self.registry / "demo.cc.json").write_text(json.dumps(self.record))
        self.assertEqual(identity.discover_endpoints(self.registry, "host-a", self.projects,
                                                     now=100, inspect_process=self.live), [])
        self.record["pid_start"] = 77
        (self.registry / "demo.cc.json").write_text(json.dumps(self.record))
        self.assertEqual(identity.discover_endpoints(self.registry, "host-a", self.projects,
                                                     now=100, inspect_process=lambda _: {
                                                         "ppid": 1, "pid_start": 77, "uid": 501,
                                                         "command": "ssh proxy"}), [])

    def test_binding_requires_ancestry_and_rejects_ambiguity(self):
        endpoint = identity.discover_endpoints(self.registry, "host-a", self.projects,
                                               now=100, inspect_process=self.live)[0]
        def child(pid):
            if pid == 9:
                return {"ppid": 101, "pid_start": 66, "uid": 501, "command": "host-agent"}
            return self.live(pid)
        self.assertEqual(identity.bind_caller(9, 501, [endpoint], inspect_process=child), endpoint)
        with self.assertRaises(identity.IdentityError):
            identity.bind_caller(9, 501, [endpoint], claimed_alias="other.cc", inspect_process=child)
        other = dict(endpoint, endpoint_id="other", address="demo.cc", pid=101, pid_start=77)
        with self.assertRaisesRegex(identity.IdentityError, "ambiguous"):
            identity.bind_caller(9, 501, [endpoint, other], inspect_process=child)


if __name__ == "__main__":
    unittest.main()
