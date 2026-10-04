#!/usr/bin/env python3
"""Reader behaviour of the repo read service against a real temporary git repository."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unified"))
import repo_access as ra
from repo_access import RepoAccess, RepoError


class FakePolicy:
    """The same surface as RepoPolicy, in memory (the real ledger has its own tests)."""

    def __init__(self):
        self.grants, self.audits, self._rev = [], [], 0

    def grant(self, reader, project_id, root, ops=("list", "tree", "read", "search"), path_scope=None):
        self.grants.append(dict(reader=reader, project_id=project_id, root=root, ops=list(ops), path_scope=path_scope))
        self._rev += 1

    def revoke_all(self):
        self.grants, self._rev = [], self._rev + 1

    def revision(self):
        return self._rev

    def granted_projects(self, reader, generation=""):
        return [dict(g, revision=self._rev) for g in self.grants if g["reader"] == reader]

    def check(self, reader, project_id, root, op, rel_path=None, generation=""):
        for g in self.grants:
            if g["reader"] == reader and g["project_id"] == project_id:
                if g["root"] != root:
                    return {"allowed": False, "reason": "root_changed"}
                if op not in g["ops"]:
                    return {"allowed": False, "reason": "op_not_granted"}
                scope = g["path_scope"]
                if scope and rel_path and not (rel_path == scope.rstrip("/") or rel_path.startswith(scope.rstrip("/") + "/")):
                    return {"allowed": False, "reason": "path_out_of_scope"}
                return {"allowed": True, "reason": "ok", "revision": self._rev}
        return {"allowed": False, "reason": "not_granted"}

    def audit(self, record):
        self.audits.append(record)


def git(root, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-C", str(root)] + list(args),
                   check=True, capture_output=True, env=env)


class RepoAccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name)) / "proj"
        (self.root / "src").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / "src" / "a.swift").write_text("".join("line %d\n" % i for i in range(1, 401)))
        (self.root / "docs" / "b.md").write_text("alpha\nbeta needle gamma\ndelta\nneedle again\n")
        (self.root / "src" / "long.txt").write_text("x" * 50000 + "\nshort\n")
        (self.root / "src" / "key.txt").write_text("api_key = 'abcdefghijklmnopqrstuvwxyz0123456789'\nfine\n")
        (self.root / "src" / "blob.dat").write_bytes(b"\x00\x01\x02binary")
        (self.root / ".env").write_text("TOKEN=hunter2hunter2hunter2hunter2hunter2\n")
        (self.root / "tracked_link").symlink_to("/etc")
        (self.root / "src" / "link.swift").symlink_to("../docs/b.md")
        git(self.root, "init", "-q"); git(self.root, "add", "-A"); git(self.root, "commit", "-q", "-m", "init")
        (self.root / "untracked.txt").write_text("not tracked\n")
        self.policy = FakePolicy()
        self.policy.grant("reader-1", "proj-1", str(self.root))
        self.svc = RepoAccess(self.policy, lambda: [{"project_id": "proj-1", "alias": "proj", "path": str(self.root)}])
        self.reader = {"participant_id": "reader-1", "generation": ""}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, op, **req):
        req.setdefault("repo_id", "proj-1")
        return self.svc.handle(op, self.reader, req)

    def code(self, op, **req):
        with self.assertRaises(RepoError) as ctx:
            self.call(op, **req)
        return ctx.exception.code

    def test_list_shows_only_granted_projects_with_version_info(self):
        out = self.svc.handle("list", self.reader, {})
        self.assertEqual([r["repo_id"] for r in out["repos"]], ["proj-1"])
        self.assertEqual(out["repos"][0]["name"], "proj")
        self.assertEqual(self.svc.handle("list", {"participant_id": "stranger"}, {})["repos"], [])

    def test_tree_serves_tracked_text_only(self):
        out = self.call("tree", depth=2)
        paths = {e["path"] for e in out["entries"]}
        self.assertIn("src/a.swift", paths); self.assertIn("docs/b.md", paths)
        for hidden in (".env", "untracked.txt", "tracked_link", "src/link.swift"):
            self.assertNotIn(hidden, paths)
        self.assertFalse(out["untracked_included"]); self.assertTrue(out["untrusted_content"])
        self.assertEqual(len(out["head"]), 40)

    def test_read_numbers_lines_cites_and_pages(self):
        out = self.call("read", path="src/a.swift", start=10, end=12)
        self.assertEqual([l["n"] for l in out["lines"]], [10, 11, 12])
        self.assertEqual(out["lines"][0]["text"], "line 10")
        self.assertEqual(out["returned_range"], [10, 12])
        self.assertIn("src/a.swift:L10-L12", out["cite"]); self.assertIn(out["head"], out["cite"])
        self.assertTrue(out["consistent"])
        first = self.call("read", path="src/a.swift")
        self.assertEqual(len(first["lines"]), 200); self.assertTrue(first["truncated"])
        self.assertEqual(first["next_cursor"], {"start": 201})
        self.assertEqual(self.code("read", path="src/a.swift", start=1, end=1500), "too_large")

    def test_paths_that_leave_the_root_or_are_never_served_are_denied(self):
        for bad in ("../x", "/etc/passwd", "src/../../x", ".env", ".git/config", "src//a.swift", "src\\a"):
            self.assertIn(self.code("read", path=bad), ("path_denied",), bad)
        self.assertEqual(self.code("read", path="untracked.txt"), "path_not_found")
        self.assertIn(self.code("read", path="tracked_link/passwd"), ("path_not_found", "path_denied"))
        self.assertIn(self.code("read", path="src/link.swift"), ("path_not_found", "path_denied"))

    def test_symlink_swapped_in_after_the_tracked_check_is_not_followed(self):
        target = self.root / "docs" / "b.md"
        target.unlink(); target.symlink_to("/etc/hosts")
        self.assertIn(self.code("read", path="docs/b.md"), ("path_not_found", "path_denied"))

    def test_binary_credential_and_long_line_handling(self):
        blob = self.call("read", path="src/blob.dat")
        self.assertEqual(blob["kind"], "binary"); self.assertEqual(blob["lines"], [])
        self.assertEqual(self.code("read", path="src/key.txt"), "content_withheld")
        long = self.call("read", path="src/long.txt", start=1, end=2)
        self.assertTrue(long["lines"][0].get("line_truncated")); self.assertEqual(long["lines"][1]["text"], "short")

    def test_snapshot_must_still_match(self):
        snap = self.call("tree")["snapshot_id"]
        self.call("read", path="docs/b.md", snapshot_id=snap)
        (self.root / "docs" / "b.md").write_text("changed\n")
        self.assertEqual(self.code("read", path="docs/b.md", snapshot_id=snap), "snapshot_expired")
        fresh = self.call("read", path="docs/b.md")
        self.assertEqual(fresh["dirty"], 1)
        self.assertIn(fresh["snapshot_id"], fresh["cite"])  # a dirty read is cited with its snapshot

    def test_search_literal_regex_context_paging_and_credentials(self):
        out = self.call("search", pattern="NEEDLE", context=1)
        hits = [(m["path"], m["n"]) for m in out["matches"]]
        self.assertEqual(hits, [("docs/b.md", 2), ("docs/b.md", 4)])
        self.assertEqual(out["matches"][0]["context_before"][0]["text"], "alpha")
        self.assertEqual(out["matches"][0]["context_after"][0]["text"], "delta")
        self.assertEqual(self.call("search", pattern="NEEDLE", case_sensitive=True)["no_match"], True)
        rx = self.call("search", pattern=r"line 3[0-9]\b", mode="regex", glob_include="*.swift")
        self.assertEqual(rx["match_count"], 10)
        page = self.call("search", pattern="line", limit=3, glob_include="src/a.swift")
        self.assertEqual(page["match_count"], 3); self.assertTrue(page["truncated"])
        more = self.call("search", pattern="line", limit=3, glob_include="src/a.swift", cursor=page["next_cursor"])
        self.assertEqual(more["matches"][0]["n"], 4)
        self.assertEqual(self.code("search", pattern="line", limit=3, cursor=page["next_cursor"]), "invalid_request")
        key = self.call("search", pattern="api_key")
        self.assertEqual(key["match_count"], 0); self.assertEqual(key["withheld_matches"], 1)
        for catastrophic in ("(a+)+", "(a|aa)+b", r"(x)\1", "a*a*a*a*a*b"):
            self.assertEqual(self.code("search", pattern=catastrophic, mode="regex"), "invalid_request", catastrophic)
        self.assertEqual(self.code("search", pattern="x" * 300), "invalid_request")

    def test_revocation_applies_to_the_next_call_even_with_a_cursor_or_snapshot(self):
        page = self.call("search", pattern="line", limit=2, glob_include="src/a.swift")
        self.policy.revoke_all()
        self.assertEqual(self.code("search", pattern="line", limit=2, glob_include="src/a.swift", cursor=page["next_cursor"]), "not_granted")
        self.assertEqual(self.code("read", path="docs/b.md", snapshot_id=page["snapshot_id"]), "not_granted")
        self.assertEqual(self.svc.handle("list", self.reader, {})["repos"], [])

    def test_operation_and_path_scope_limits(self):
        self.policy.grants[0]["ops"] = ["list", "read"]
        self.assertEqual(self.code("tree"), "scope_denied")
        self.policy.grants[0].update(ops=["list", "tree", "read", "search"], path_scope="docs")
        self.assertEqual(self.code("read", path="src/a.swift", start=1, end=2), "scope_denied")
        self.assertEqual(self.call("read", path="docs/b.md")["lines"][0]["text"], "alpha")

    def test_audit_names_the_call_but_never_the_content(self):
        self.call("read", path="docs/b.md")
        self.call("search", pattern="beta needle gamma")
        self.code("read", path="../x")
        flat = repr(self.policy.audits)
        self.assertNotIn("beta needle", flat); self.assertNotIn("alpha", flat)
        self.assertTrue(any(a["allowed"] is False for a in self.policy.audits))
        self.assertTrue(all(set(a) <= {"reader", "project_id", "op", "path_or_hash", "allowed", "reason", "bytes", "truncated", "revision"} for a in self.policy.audits))

    def test_rate_limit_returns_retry_after(self):
        now = [1000.0]
        svc = RepoAccess(self.policy, self.svc.projects, clock=lambda: now[0])
        for _ in range(ra.RATE_CALLS_PER_MIN):
            svc.handle("tree", self.reader, {"repo_id": "proj-1"})
        with self.assertRaises(RepoError) as ctx:
            svc.handle("tree", self.reader, {"repo_id": "proj-1"})
        self.assertEqual(ctx.exception.code, "rate_limited"); self.assertGreaterEqual(ctx.exception.retry_after, 1)
        now[0] += 61
        svc.handle("tree", self.reader, {"repo_id": "proj-1"})


if __name__ == "__main__":
    unittest.main()
