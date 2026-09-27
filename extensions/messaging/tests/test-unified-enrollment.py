import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "unified" / "enrollment.py"
spec = importlib.util.spec_from_file_location("enrollment", SOURCE)
enrollment = importlib.util.module_from_spec(spec); spec.loader.exec_module(enrollment)


class EnrollmentTest(unittest.TestCase):
    def test_admission_rejects_duplicate_global_alias(self):
        hosts = [{"host_id": "a", "aliases": ["app"], "online": True},
                 {"host_id": "b", "aliases": ["app"], "online": True}]
        with self.assertRaisesRegex(enrollment.EnrollmentError, "duplicated"):
            enrollment.admit(hosts, "a")

    def test_prepare_commit_is_atomic_and_recoverable(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw); cfg = home / ".config/tproj"; cfg.mkdir(parents=True)
            (cfg / "msg-hub.json").write_text(json.dumps({"hosts": {"a": "old"}}))
            request = {"action": "prepare", "txn": "txn1", "topology": {"mode": "multi"}, "hosts": {"a": "new"}}
            self.assertTrue(enrollment._control(home, request)["prepared"])
            self.assertFalse((cfg / "topology.json").exists())
            enrollment._control(home, {"action": "recover", "txn": "txn1"})
            self.assertFalse((cfg / "enrollment.txn1.pending.json").exists())
            enrollment._control(home, request)
            self.assertTrue(enrollment._control(home, {"action": "commit", "txn": "txn1"})["committed"])
            self.assertTrue(enrollment._control(home, {"action": "commit", "txn": "txn1"})["retry"])
            self.assertEqual(json.loads((cfg / "msg-hub.json").read_text())["hosts"], {"a": "new"})

    def test_topology_keeps_different_directed_routes(self):
        hosts = [{"host_id": "a", "ssh_alias": "server-a", "aliases": ["one"], "online": True},
                 {"host_id": "b", "ssh_alias": "workstation-a", "aliases": ["two"], "online": True}]
        result = enrollment.topology(hosts, "a", {"one": "a", "two": "b"},
                                     {"a": {"b": "workstation-a"}, "b": {"a": "workstation-from-b"}})
        self.assertEqual(result["hosts"][0]["routes"]["b"], "workstation-a")
        self.assertEqual(result["hosts"][1]["routes"]["a"], "workstation-from-b")


    def test_three_host_control_uses_each_hosts_own_routes(self):
        hosts = [{"host_id": h, "aliases": ["project-" + h], "host_token": "test-" + h} for h in ("a", "b", "c")]
        routes = {h: {other: other + "-from-" + h for other in ("a", "b", "c") if other != h} for h in ("a", "b", "c")}
        top = enrollment.topology(hosts, "a", {}, routes)
        with tempfile.TemporaryDirectory() as raw:
            for h in ("a", "b", "c"):
                home = Path(raw) / h
                cfg = home / ".config/tproj"; cfg.mkdir(parents=True)
                (cfg / "msg-host.json").write_text(json.dumps({"host_id": h}))
                enrollment._control(home, {"action": "prepare", "txn": "three", "topology": top, "hosts": {x: "test-" + x for x in ("a", "b", "c")}})
                enrollment._control(home, {"action": "commit", "txn": "three"})
                saved = json.loads((cfg / "topology.json").read_text())
                self.assertEqual(saved["local"]["id"], h)
                self.assertEqual({x["id"]: x["ssh_alias"] for x in saved["hosts"]}, routes[h])

if __name__ == "__main__": unittest.main()
