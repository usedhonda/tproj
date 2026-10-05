#!/usr/bin/env python3
"""Writer behaviour of the repo write service against a real temporary git repository."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unified"))
from repo_access import RepoAccess, RepoError


class FakePolicy:
    def __init__(self): self.grants, self.audits, self._rev = [], [], 0
    def grant(self, reader, project_id, root, ops=("write",), path_scope=None):
        self.grants.append(dict(reader=reader, project_id=project_id, root=root, ops=list(ops), path_scope=path_scope)); self._rev += 1
    def revoke_all(self): self.grants, self._rev = [], self._rev + 1
    def revision(self): return self._rev
    def granted_projects(self, reader, generation=""):
        return [dict(g, revision=self._rev) for g in self.grants if g["reader"] == reader]
    def check(self, reader, project_id, root, op, rel_path=None, generation=""):
        for g in self.grants:
            if g["reader"] == reader and g["project_id"] == project_id:
                if op not in g["ops"]: return {"allowed": False, "reason": "op_not_granted"}
                scope = g["path_scope"]
                if scope and rel_path and not rel_path.startswith(scope.rstrip("/") + "/"):
                    return {"allowed": False, "reason": "path_out_of_scope"}
                return {"allowed": True, "reason": "ok"}
        return {"allowed": False, "reason": "not_granted"}
    def audit(self, record): self.audits.append(record)


def git(root, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-C", str(root)] + list(args),
                   check=True, capture_output=True, env=env)


def sha(text): return hashlib.sha256(text.encode()).hexdigest()


class RepoWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(os.path.realpath(self.tmp.name))
        os.environ["TPROJ_REPO_PATCH_DIR"] = str(base / "patches"); self.addCleanup(os.environ.pop, "TPROJ_REPO_PATCH_DIR", None)
        self.root = base / "proj"; (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "a.md").write_text("one\n")
        (self.root / "docs" / "b.md").write_text("two\n")
        (self.root / "run.sh").write_text("echo\n"); os.chmod(self.root / "run.sh", 0o755)
        git(self.root, "init", "-q"); git(self.root, "add", "-A"); git(self.root, "commit", "-q", "-m", "init")
        self.policy = FakePolicy(); self.policy.grant("w1", "p1", str(self.root))
        self.svc = RepoAccess(self.policy, lambda: [{"project_id": "p1", "alias": "proj", "path": str(self.root)}])
        self.writer = {"participant_id": "w1", "generation": ""}; self.n = 0

    def call(self, op="write", **req):
        self.n += 1
        if op == "write": req.setdefault("patch_id", "00000000-0000-4000-8000-%012d" % self.n)
        req.setdefault("repo_id", "p1")
        return self.svc.handle(op, self.writer, req)

    def code(self, op="write", **req):
        with self.assertRaises(RepoError) as ctx: self.call(op, **req)
        return ctx.exception.code

    def mod(self, path, content, base): return {"path": path, "action": "modify", "content": content, "base_sha256": sha(base)}
    def new(self, path, content): return {"path": path, "action": "create", "content": content}

    def test_modify_and_create_write_files_without_touching_git(self):
        head = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        out = self.call(changes=[self.mod("docs/a.md", "ONE\n", "one\n"), self.new("docs/c.md", "new\n")])
        self.assertTrue(out["applied"]); self.assertEqual(out["dirty"], 1)       # untracked c.md is not counted
        self.assertEqual((self.root / "docs" / "a.md").read_text(), "ONE\n"); self.assertEqual((self.root / "docs" / "c.md").read_text(), "new\n")
        self.assertEqual(subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout, head)
        self.assertEqual(subprocess.run(["git", "-C", str(self.root), "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout, "")
        self.assertEqual([p for p in os.listdir(self.root / "docs") if p.startswith(".tproj-write")], [])

    def test_no_grant_read_only_grant_scope_and_revocation(self):
        self.writer = {"participant_id": "stranger", "generation": ""}
        self.assertEqual(self.code(changes=[self.new("docs/x.md", "x")]), "not_granted")
        self.writer = {"participant_id": "w1", "generation": ""}
        self.policy.grants[0]["ops"] = ["read"]
        self.assertEqual(self.code(changes=[self.new("docs/x.md", "x")]), "not_granted")
        self.policy.grants[0].update(ops=["write"], path_scope="docs")
        self.assertEqual(self.code(changes=[self.new("src/x.md", "x")]), "scope_denied")
        self.call(changes=[self.new("docs/x.md", "x")])
        self.policy.revoke_all()
        self.assertEqual(self.code(changes=[self.new("docs/y.md", "y")]), "not_granted")

    def test_stale_base_existing_path_and_owner_work_in_progress_are_refused(self):
        self.assertEqual(self.code(changes=[self.mod("docs/a.md", "x", "stale\n")]), "conflict")
        self.assertEqual(self.code(changes=[self.new("docs/a.md", "x")]), "exists")
        (self.root / "docs" / "b.md").write_text("owner edit\n")
        self.assertEqual(self.code(changes=[self.mod("docs/b.md", "x", "owner edit\n")]), "dirty_path")
        self.assertEqual((self.root / "docs" / "b.md").read_text(), "owner edit\n")

    def test_a_batch_with_one_bad_file_writes_nothing_and_dry_run_writes_nothing(self):
        before = (self.root / "docs" / "a.md").read_text()
        self.assertEqual(self.code(changes=[self.mod("docs/a.md", "ONE\n", "one\n"), self.mod("docs/b.md", "x", "wrong\n")]), "conflict")
        self.assertEqual((self.root / "docs" / "a.md").read_text(), before)
        out = self.call(changes=[self.mod("docs/a.md", "ONE\n", "one\n")], dry_run=True)
        self.assertFalse(out["applied"]); self.assertEqual((self.root / "docs" / "a.md").read_text(), before)

    def test_forbidden_paths_content_and_modes(self):
        for bad in ("../x", "/etc/x", ".env", ".git/config", "docs/../../x", "a\\b", ".local/x", "id_rsa", "k.pem"):
            self.assertEqual(self.code(changes=[self.new(bad, "x")]), "path_denied", bad)
        self.assertEqual(self.code(changes=[self.new("docs/k.md", "api_key = 'abcdefghijklmnopqrstuvwxyz0123456789'\n")]), "content_withheld")
        self.assertEqual(self.code(changes=[self.mod("run.sh", "echo 2\n", "echo\n")]), "path_denied")      # executable
        self.assertEqual(self.code(changes=[self.new("docs/n.md", "a\0b")]), "invalid_request")
        self.assertEqual(self.code(changes=[self.new("docs/big.md", "x" * (128 * 1024 + 1))]), "too_large")
        self.assertEqual(self.code(changes=[self.new("docs/d1.md", "1"), self.new("docs/d1.md", "2")]), "invalid_request")

    def test_symlinks_are_not_followed(self):
        outside = Path(self.tmp.name) / "outside"; outside.mkdir()
        (self.root / "docs" / "link").symlink_to(outside)
        self.assertIn(self.code(changes=[self.new("docs/link/x.md", "x")]), ("path_denied", "path_not_found"))
        self.assertFalse((outside / "x.md").exists())
        (self.root / "docs" / "a.md").unlink(); (self.root / "docs" / "a.md").symlink_to(outside)
        self.assertIn(self.code(changes=[self.mod("docs/a.md", "x", "one\n")]), ("path_denied", "path_not_found"))

    def test_new_directories_are_limited_in_depth(self):
        self.call(changes=[self.new("docs/x/y/z/f.md", "ok")])
        self.assertEqual(self.code(changes=[self.new("p/q/r/s/f.md", "no")]), "scope_denied")

    def test_replayed_patch_id_does_not_write_twice_and_a_different_body_is_refused(self):
        change = [self.mod("docs/a.md", "ONE\n", "one\n")]
        first = self.call(patch_id="11111111-1111-4111-8111-111111111111", changes=change)
        again = self.call(patch_id="11111111-1111-4111-8111-111111111111", changes=change)
        self.assertTrue(again["duplicate"]); self.assertEqual(again["files"], first["files"])
        self.assertEqual(self.code(patch_id="11111111-1111-4111-8111-111111111111", changes=[self.new("docs/z.md", "z")]), "conflict")

    def test_the_same_writer_can_keep_editing_its_own_change_but_not_the_owners(self):
        self.call(changes=[self.mod("docs/a.md", "v2\n", "one\n")])
        self.call(changes=[self.mod("docs/a.md", "v3\n", "v2\n")])
        (self.root / "docs" / "a.md").write_text("owner\n")
        self.assertEqual(self.code(changes=[self.mod("docs/a.md", "v4\n", "owner\n")]), "dirty_path")

    def test_revert_restores_exactly_and_refuses_when_the_file_moved_on(self):
        out = self.call(changes=[self.mod("docs/a.md", "ONE\n", "one\n"), self.new("docs/c.md", "new\n")])
        res = self.call("revert", patch_id=out["patch_id"])
        self.assertTrue(res["reverted"]); self.assertEqual((self.root / "docs" / "a.md").read_text(), "one\n"); self.assertFalse((self.root / "docs" / "c.md").exists())
        self.assertEqual(self.code("revert", patch_id=out["patch_id"]), "conflict")                  # already reverted
        out2 = self.call(changes=[self.mod("docs/a.md", "TWO\n", "one\n")])
        (self.root / "docs" / "a.md").write_text("owner\n")
        self.assertEqual(self.code("revert", patch_id=out2["patch_id"]), "conflict")
        self.assertEqual((self.root / "docs" / "a.md").read_text(), "owner\n")
        self.writer = {"participant_id": "w1", "generation": ""}
        self.assertEqual(self.code("revert", patch_id="22222222-2222-4222-8222-222222222222"), "path_not_found")

    def test_a_created_file_can_be_read_back_until_it_changes_and_read_gives_the_base_sha(self):
        self.policy.grants[0]["ops"] = ["read", "write"]
        tracked = self.call("read", path="docs/a.md")
        self.assertEqual(tracked["file_sha256"], sha("one\n"))                      # the base for a later modify
        out = self.call(changes=[self.mod("docs/a.md", "ONE\n", "one\n"), self.new("docs/c.md", "new\n")])
        back = self.call("read", path="docs/c.md")
        self.assertEqual([l["text"] for l in back["lines"]], ["new"]); self.assertEqual(back["file_sha256"], sha("new\n"))
        self.assertEqual(self.call("read", path="docs/a.md")["file_sha256"], sha("ONE\n"))
        self.assertEqual(self.code("read", path="docs/untouched-new.md"), "path_not_found")      # never an arbitrary untracked path
        (self.root / "docs" / "other.md").write_text("owner file\n")
        self.assertEqual(self.code("read", path="docs/other.md"), "path_not_found")
        (self.root / "docs" / "c.md").write_text("owner changed it\n")
        self.assertEqual(self.code("read", path="docs/c.md"), "path_not_found")                  # no longer what the service wrote
        (self.root / "docs" / "c.md").write_text("new\n")
        self.call("revert", patch_id=out["patch_id"])
        self.assertEqual(self.code("read", path="docs/c.md"), "path_not_found")

    def test_a_file_the_service_created_can_be_modified_until_the_owner_changes_it(self):
        self.call(changes=[self.new("docs/c.md", "v1\n")])
        self.call(changes=[self.mod("docs/c.md", "v2\n", "v1\n")])
        self.assertEqual((self.root / "docs" / "c.md").read_text(), "v2\n")
        (self.root / "docs" / "c.md").write_text("owner\n")
        self.assertEqual(self.code(changes=[self.mod("docs/c.md", "v3\n", "owner\n")]), "path_not_found")
        (self.root / "docs" / "other.md").write_text("not ours\n")                        # an untracked file nobody here wrote
        self.assertEqual(self.code(changes=[self.mod("docs/other.md", "x", "not ours\n")]), "path_not_found")

    def test_audit_names_the_call_but_never_the_content(self):
        self.call(changes=[self.mod("docs/a.md", "SECRET-BODY-TEXT\n", "one\n")])
        self.code(changes=[self.new("../x", "x")])
        flat = repr(self.policy.audits)
        self.assertNotIn("SECRET-BODY-TEXT", flat)
        self.assertTrue(any(a["allowed"] is False for a in self.policy.audits))


if __name__ == "__main__":
    unittest.main()
