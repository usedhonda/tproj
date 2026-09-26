import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

src = Path(__file__).resolve().parents[1] / "unified" / "policy.py"
sys.path.insert(0, str(src.parent))
spec = importlib.util.spec_from_file_location("policy", src)
policy = importlib.util.module_from_spec(spec); spec.loader.exec_module(policy)


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE messages(sender_endpoint TEXT,target_address TEXT,body TEXT,created_at REAL)")

    def blocked(self, target, body):
        with self.assertRaises(policy.HubError):
            policy.check_policy(self.db, "ep", target, body, 1000)

    def test_forbidden_markers(self):
        for target, body in [("all", "hello"), ("proj.cc", "[from:x] hi"),
                             ("proj.cc", "[Control:x]"), ("proj.cc", "[ACK:x]"),
                             ("proj.cc", "[Persona Sync]"), ("proj.cc", "[Task:x] do")]:
            self.blocked(target, body)

    def test_normal_multiline_and_fanout(self):
        policy.check_policy(self.db, "ep", "proj.cc", "hello\nworld", 1000)
        self.db.execute("INSERT INTO messages VALUES(?,?,?,?)", ("ep", "other.cdx", "hello world", 999))
        with self.assertRaises(policy.HubError):
            policy.check_policy(self.db, "ep", "proj.cdx", "hello\nworld", 1000)

    def test_recovery_duplicate_and_reply(self):
        body = "未達 LINE の作業依頼 id 42 を復元"
        self.db.execute("INSERT INTO messages VALUES(?,?,?,?)", ("ep", "gate", body, 999))
        self.blocked("gate", body)
        policy.check_policy(self.db, "ep", "proj.cc", "acknowledged", 1000, in_reply_to="m1")


if __name__ == "__main__": unittest.main()
