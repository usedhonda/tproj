#!/usr/bin/env python3
"""Tests for the repo read service grant ledger and operator CLI (temp dirs only)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "unified"))
import repo_access_policy as rap  # noqa: E402

CLI = ROOT / "repo-access-cli"


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "state", "repo.sqlite")
        self.p = rap.RepoPolicy(self.db)
        self.now = 1000.0
        self._orig = rap.time.time
        rap.time.time = lambda: self.now
        self.addCleanup(lambda: setattr(rap.time, "time", self._orig))

    def test_default_deny_and_perms(self):
        r = self.p.check("r1", "p1", "/x", "read")
        self.assertEqual((r["allowed"], r["reason"]), (False, "not_granted"))
        self.assertEqual(oct(os.stat(self.db).st_mode & 0o777), "0o600")
        self.assertEqual(oct(os.stat(os.path.dirname(self.db)).st_mode & 0o777), "0o700")

    def test_grant_ok_and_op(self):
        self.p.grant("r1", "p1", "/x")
        self.assertTrue(self.p.check("r1", "p1", "/x", "read")["allowed"])
        self.assertEqual(self.p.check("r1", "p1", "/x", "diff")["reason"], "op_not_granted")
        self.assertEqual(self.p.check("r2", "p1", "/x", "read")["reason"], "not_granted")

    def test_path_scope_segment_aware(self):
        self.p.grant("r1", "p1", "/x", path_scope="Sources/")
        c = lambda rel: self.p.check("r1", "p1", "/x", "read", rel)
        self.assertTrue(c("Sources/a.swift")["allowed"])
        self.assertTrue(c("Sources")["allowed"])
        self.assertEqual(c("SourcesEvil/x")["reason"], "path_out_of_scope")
        self.assertEqual(c("Sources/../secret")["reason"], "path_out_of_scope")
        self.assertEqual(c("/etc/passwd")["reason"], "path_out_of_scope")
        self.assertTrue(self.p.check("r1", "p1", "/x", "read")["allowed"])

    def test_expiry(self):
        self.p.grant("r1", "p1", "/x", expires_at=1500)
        self.assertTrue(self.p.check("r1", "p1", "/x", "read")["allowed"])
        self.assertEqual(len(self.p.granted_projects("r1")), 1)
        self.now = 1500.0
        self.assertEqual(self.p.check("r1", "p1", "/x", "read")["reason"], "expired")
        self.assertEqual(self.p.granted_projects("r1"), [])

    def test_root_changed(self):
        self.p.grant("r1", "p1", "/x")
        self.assertEqual(self.p.check("r1", "p1", "/y", "read")["reason"], "root_changed")

    def test_regrant_replaces_and_revoke(self):
        self.p.grant("r1", "p1", "/x", ops=["read"])
        self.p.grant("r1", "p1", "/x", ops=["list"])
        rows = self.p.list("r1", "p1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ops"], ["list"])
        self.assertEqual(self.p.check("r1", "p1", "/x", "read")["reason"], "op_not_granted")
        rev = self.p.revision()
        self.assertEqual(self.p.revoke(reader="r1", project_id="p1"), 1)
        self.assertEqual(self.p.check("r1", "p1", "/x", "list")["reason"], "not_granted")
        self.assertGreater(self.p.revision(), rev)
        rev = self.p.revision()
        self.assertEqual(self.p.revoke(reader="nobody"), 0)
        self.assertEqual(self.p.revision(), rev)
        with self.assertRaises(ValueError):
            self.p.revoke()

    def test_revoke_by_id(self):
        gid = self.p.grant("r1", "p1", "/x")
        self.assertEqual(self.p.revoke(grant_id=gid), 1)

    def test_revision_monotonic(self):
        seen = [self.p.revision()]
        self.p.grant("r1", "p1", "/x")
        seen.append(self.p.revision())
        self.p.grant("r1", "p2", "/y")
        seen.append(self.p.revision())
        self.p.revoke(reader="r1")
        seen.append(self.p.revision())
        self.assertEqual(seen[0], 0)
        self.assertEqual(seen, sorted(set(seen)))
        self.assertEqual(self.p.check("r1", "p1", "/x", "read")["revision"], seen[-1])

    def test_generation(self):
        self.p.grant("r1", "p1", "/x", generation="g1")
        self.p.grant("r1", "p2", "/y")
        self.assertEqual([g["project_id"] for g in self.p.granted_projects("r1", "g1")], ["p1", "p2"])
        self.assertEqual([g["project_id"] for g in self.p.granted_projects("r1", "g2")], ["p2"])
        self.assertEqual(self.p.check("r1", "p1", "/x", "read", generation="g2")["reason"], "generation_mismatch")
        self.assertTrue(self.p.check("r1", "p1", "/x", "read", generation="g1")["allowed"])
        self.assertTrue(self.p.check("r1", "p2", "/y", "read", generation="anything")["allowed"])

    def test_ops_validation(self):
        with self.assertRaises(ValueError):
            self.p.grant("r1", "p1", "/x", ops=["read", "write"])
        with self.assertRaises(ValueError):
            self.p.grant("r1", "p1", "/x", ops=[])
        self.p.grant("r1", "p1", "/x", ops=["search", "read", "read"])
        self.assertEqual(self.p.list()[0]["ops"], ["read", "search"])

    def test_sql_injection_is_inert(self):
        self.p.grant("r1", "p1", "/x")
        self.assertEqual(self.p.check("r1' OR '1'='1", "p1", "/x", "read")["reason"], "not_granted")

    def test_audit_only_allowed_keys(self):
        secret = "SECRET-FILE-CONTENT-12345"
        abs_path = "/Users/someone/private-dir-xyz/file.txt"
        self.p.audit({"reader": "r1", "project_id": "p1", "op": "read", "path_or_hash": abs_path,
                      "allowed": True, "reason": "ok", "bytes": 12, "truncated": False, "revision": 3,
                      "content": secret, "query": secret, "token": secret, "abs": abs_path})
        self.p.audit({"reader": "r1", "project_id": "p1", "op": "read", "path_or_hash": "a/../b",
                      "allowed": False, "reason": "path_out_of_scope"})
        self.p.audit({"reader": "r2", "project_id": "p1", "op": "list", "path_or_hash": "Sources/a.swift",
                      "allowed": True, "reason": "ok", "ts": 5.0})
        rows = self.p.audit_list()
        self.assertEqual(rows[0]["path_or_hash"], "Sources/a.swift")
        self.assertEqual(set(rows[0]), set(rap.AUDIT_KEYS))
        hashed = [r["path_or_hash"] for r in rows[1:]]
        self.assertTrue(all(len(h) == 16 and "/" not in h for h in hashed))
        self.assertEqual(len(self.p.audit_list(limit=1)), 1)
        self.assertEqual(len(self.p.audit_list(reader="r2")), 1)
        blob = b""
        for suffix in ("", "-wal", "-shm"):
            f = self.db + suffix
            if os.path.exists(f):
                blob += Path(f).read_bytes()
        self.assertNotIn(secret.encode(), blob)
        self.assertNotIn(b"private-dir-xyz", blob)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.proj = t / "proj"
        self.proj.mkdir()
        self.remote = t / "remote"
        self.remote.mkdir()
        directory = {
            "host_id": "H1",
            "participants": [
                {"address": "alpha.cc", "participant_id": "pid-alpha", "host_id": "H1"},
                {"address": "dup.cc", "participant_id": "pid-d1", "host_id": "H1"},
                {"address": "dup.cc", "participant_id": "pid-d2", "host_id": "H1"},
            ],
            "projects": [
                {"project_id": "proj-1", "alias": "demo", "host_id": "H1", "path": str(self.proj)},
                {"project_id": "proj-2", "alias": "elsewhere", "host_id": "H2", "path": str(self.remote)},
            ],
        }
        self.dir_json = t / "dir.json"
        self.dir_json.write_text(json.dumps(directory))
        self.env = dict(os.environ, TPROJ_REPO_ACCESS_DB=str(t / "s" / "db.sqlite"),
                        TPROJ_REPO_ACCESS_DIRECTORY_JSON=str(self.dir_json), HOME=str(t))

    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, str(CLI)] + list(args), env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        lines = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
        return proc.returncode, lines, proc.stderr

    def test_end_to_end(self):
        rc, out, _ = self.run_cli("grant", "--reader", "alpha.cc", "--project", "demo",
                                  "--ops", "list,read", "--path-prefix", "Sources/", "--expires-in-hours", "1")
        self.assertEqual(rc, 0)
        self.assertEqual(out[0]["reader"], "pid-alpha")
        self.assertEqual(out[0]["project_id"], "proj-1")
        self.assertEqual(out[0]["root"], os.path.realpath(str(self.proj)))
        self.assertEqual(out[0]["ops"], ["list", "read"])
        self.assertIsNotNone(out[0]["expires_at"])
        rc, out, _ = self.run_cli("list")
        self.assertEqual((rc, len(out)), (0, 1))
        rc, out, _ = self.run_cli("check", "--reader", "alpha.cc", "--project", "demo", "--op", "read", "--path", "Sources/a")
        self.assertEqual((rc, out[0]["allowed"]), (0, True))
        rc, out, _ = self.run_cli("check", "--reader", "alpha.cc", "--project", "demo", "--op", "search")
        self.assertEqual(out[0]["reason"], "op_not_granted")
        rc, out, _ = self.run_cli("revoke", "--reader", "alpha.cc", "--project", "demo")
        self.assertEqual((rc, out[0]["removed"]), (0, 1))
        rc, out, _ = self.run_cli("revoke", "--reader", "alpha.cc", "--project", "demo")
        self.assertEqual(rc, 3)
        rc, out, _ = self.run_cli("check", "--reader", "alpha.cc", "--project", "demo", "--op", "read")
        self.assertEqual(out[0]["reason"], "not_granted")
        rc, out, _ = self.run_cli("audit")
        self.assertEqual(rc, 0)

    def test_validation_errors(self):
        for args in (
            ("grant", "--reader", "dup.cc", "--project", "demo"),
            ("grant", "--reader", "nobody.cc", "--project", "demo"),
            ("grant", "--reader", "alpha.cc", "--project", "elsewhere"),
            ("grant", "--reader", "alpha.cc", "--project", "ghost"),
            ("grant", "--reader", "alpha.cc", "--project", "demo", "--ops", "write"),
            ("revoke",),
            ("bogus",),
        ):
            rc, _, err = self.run_cli(*args)
            self.assertEqual(rc, 2, args)
            self.assertTrue(err.strip() or args == ("bogus",), args)

    def test_stale_grant_revocable_by_raw_id(self):
        rc, _, _ = self.run_cli("grant", "--reader", "alpha.cc", "--project", "demo")
        self.assertEqual(rc, 0)
        self.env["TPROJ_REPO_ACCESS_DIRECTORY_JSON"] = str(Path(self.tmp.name) / "missing.json")
        rc, out, _ = self.run_cli("revoke", "--reader", "pid-alpha", "--project", "proj-1")
        self.assertEqual((rc, out[0]["removed"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
