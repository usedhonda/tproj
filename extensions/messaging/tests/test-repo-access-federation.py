#!/usr/bin/env python3
"""Cross-host reads: the owner's grants decide, a host may attest only its own participants,
and the transport is byte-capped."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unified"))
import federation
from federation import FederatedHub
from protocol import HubError
from repo_access_policy import RepoPolicy


def git(root, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-C", str(root)] + list(args),
                   check=True, capture_output=True, env=env)


class RepoFederationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(os.path.realpath(self.tmp.name))
        self.repo = base / "repo"; self.repo.mkdir()
        (self.repo / "f.txt").write_text("one\ntwo\nthree\n")
        git(self.repo, "init", "-q"); git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "x")
        os.environ["TPROJ_REPO_ACCESS_DB"] = str(base / "grants.sqlite")
        self.addCleanup(os.environ.pop, "TPROJ_REPO_ACCESS_DB", None)
        self.policy = RepoPolicy()
        self.hubs = {}
        projects = [{"project_id": "pa", "alias": "pa", "host_id": "a", "path": str(base / "unused")},
                    {"project_id": "pb", "alias": "pb", "host_id": "b", "path": str(self.repo)}]
        for host in ("a", "b"):
            cfg = {"host_id": host, "hosts": {h: h + "-token" for h in ("a", "b")}, "admin_token": "admin"}
            hub = FederatedHub(base / (host + ".db"), cfg)
            hub.topology = lambda host=host: {"mode": "multi", "management_host_id": "a",
                                              "hosts": [{"id": h, "ssh_alias": h} for h in ("a", "b") if h != host]}
            hub.directory_import({"admin_token": "admin", "projects": projects})
            for role in ("cc", "cdx"):
                hub.register(dict(host_id=host, host_token=host + "-token", endpoint_id=host + role, participant_id=("p" + host) + ":" + role,
                                  session=host, pane="%1", pid=100, pid_start=10, runtime_id=host + role, platform=role))
            self.hubs[host] = hub; self.addCleanup(hub.close)
        self.calls = []

        def remote_bounded(owner, op, args, host="a", **kw):
            self.calls.append(owner)
            return self.hubs[owner].dispatch(dict(args, op="peer_" + op, host_id=host, host_token=host + "-token", protocol=1))
        self.hubs["a"].remote_bounded = remote_bounded
        self.reader_id = "pa:cc"
        self.root = os.path.realpath(self.repo)

    def read(self, path="f.txt", **kw):
        return self.hubs["a"].dispatch(dict(op="repo_peer", host_id="a", host_token="a-token", endpoint_id="acc",
                                            repo_op="read", host="b", req=dict(repo_id="pb", path=path, **kw)))

    def test_owner_grant_decides_and_revocation_is_immediate(self):
        with self.assertRaises(HubError) as ctx:
            self.read()
        self.assertEqual(ctx.exception.code, "not_granted")
        self.policy.grant(self.reader_id, "pb", self.root)
        out = self.read(start=2, end=3)
        self.assertEqual([l["text"] for l in out["lines"]], ["two", "three"])
        self.assertEqual(self.calls[-1], "b")
        self.policy.revoke(reader=self.reader_id, project_id="pb")
        with self.assertRaises(HubError) as ctx:
            self.read()
        self.assertEqual(ctx.exception.code, "not_granted")

    def test_a_host_cannot_attest_a_participant_it_does_not_own(self):
        self.policy.grant("pb:cc", "pb", self.root)   # a participant that lives on b itself
        with self.assertRaises(HubError) as ctx:
            self.hubs["b"].dispatch(dict(op="peer_repo", host_id="a", host_token="a-token", protocol=1, repo_op="read",
                                         reader={"participant_id": "pb:cc", "host_id": "a"}, req={"repo_id": "pb", "path": "f.txt"}))
        self.assertEqual(ctx.exception.code, "unauthorized")
        with self.assertRaises(HubError) as ctx:
            self.hubs["b"].dispatch(dict(op="peer_repo", host_id="a", host_token="a-token", protocol=1, repo_op="read",
                                         reader={"participant_id": "nobody", "host_id": "a"}, req={"repo_id": "pb", "path": "f.txt"}))
        self.assertEqual(ctx.exception.code, "unauthorized")

    def test_list_aggregates_peers_and_reports_unreachable_ones(self):
        self.policy.grant(self.reader_id, "pb", self.root)
        out = self.hubs["a"].dispatch(dict(op="repo_peer", host_id="a", host_token="a-token", endpoint_id="acc", repo_op="list"))
        self.assertEqual([r["repo_id"] for r in out["repos"]], ["pb"])
        self.assertEqual(out["unavailable"], [])

        def down(owner, op, args, **kw):
            raise HubError("host_unavailable", "offline")
        self.hubs["a"].remote_bounded = down
        out = self.hubs["a"].dispatch(dict(op="repo_peer", host_id="a", host_token="a-token", endpoint_id="acc", repo_op="list"))
        self.assertEqual(out, {"repos": [], "unavailable": ["b"]})

    def test_invalid_forwarding_requests_are_rejected_before_any_transport(self):
        for bad in (dict(repo_op="write", host="b", req={}), dict(repo_op="read", host="zzz", req={}), dict(repo_op="read", host="b", req="x")):
            with self.assertRaises(HubError) as ctx:
                self.hubs["a"].dispatch(dict(op="repo_peer", host_id="a", host_token="a-token", endpoint_id="acc", **bad))
            self.assertEqual(ctx.exception.code, "invalid_request")
        self.assertEqual(self.calls, [])


class Proc:
    def __init__(self, out, returncode=0):
        self.stdin, self.stdout, self.returncode, self.killed = io.BytesIO(), io.BytesIO(out), returncode, False

    def poll(self): return None if not self.killed else -9
    def kill(self): self.killed = True
    def wait(self, timeout=None): return self.returncode


class BoundedTransportTest(unittest.TestCase):
    def hub(self, tmp):
        cfg = {"host_id": "a", "hosts": {"a": "a-token", "b": "b-token"}, "admin_token": "admin"}
        hub = FederatedHub(Path(tmp) / "a.db", cfg)
        hub.topology = lambda: {"mode": "multi", "management_host_id": "a", "hosts": [{"id": "b", "ssh_alias": "b"}]}
        return hub

    def test_oversized_response_is_cut_off_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = self.hub(tmp); proc = Proc(b"x" * 5000)
            with patch.object(federation.subprocess, "Popen", return_value=proc):
                with self.assertRaises(HubError) as ctx:
                    hub.remote_bounded("b", "repo", {}, max_bytes=1000)
            self.assertEqual(ctx.exception.code, "too_large"); self.assertTrue(proc.killed)
            hub.close()

    def test_well_formed_response_is_returned_and_garbage_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = self.hub(tmp)
            with patch.object(federation.subprocess, "Popen", return_value=Proc(b'{"ok":true,"result":{"repos":[]}}')):
                self.assertEqual(hub.remote_bounded("b", "repo", {}), {"repos": []})
            with patch.object(federation.subprocess, "Popen", return_value=Proc(b"not json")):
                with self.assertRaises(HubError) as ctx:
                    hub.remote_bounded("b", "repo", {})
            self.assertEqual(ctx.exception.code, "host_unavailable")
            with patch.object(federation.subprocess, "Popen", return_value=Proc(b'{"ok":false,"error":{"code":"not_granted","message":"m"}}')):
                with self.assertRaises(HubError) as ctx:
                    hub.remote_bounded("b", "repo", {})
            self.assertEqual(ctx.exception.code, "not_granted")
            hub.close()


if __name__ == "__main__":
    unittest.main()
