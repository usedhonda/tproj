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


if __name__ == "__main__": unittest.main()
