#!/usr/bin/env python3
"""Host routing for repo ops: local projects are read here, others go to their owner."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unified"))
spec = importlib.util.spec_from_file_location("unified_host", ROOT / "unified" / "host.py")
host_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_mod)
from protocol import HubError
from repo_access import RepoError


class Local:
    def __init__(self): self.calls = []
    def list_repos(self, reader): self.calls.append(("list", reader)); return {"repos": [{"repo_id": "pa"}]}
    def handle(self, op, reader, req):
        self.calls.append((op, reader, req))
        if req.get("repo_id") == "boom": raise RepoError("not_granted")
        return {"repo_id": req["repo_id"], "from": "local"}


class Stub:
    REPO_FIELDS = host_mod.Host.REPO_FIELDS

    def __init__(self, federated=True, projects=None):
        self.config = {"host_id": "a", "federated": federated}
        self.local, self.hub_calls = Local(), []
        self.projects = projects if projects is not None else [
            {"project_id": "pa", "alias": "proja", "host_id": "a"}, {"project_id": "pb", "alias": "projb", "host_id": "b"},
            {"project_id": "pc1", "alias": "dup", "host_id": "a"}, {"project_id": "pc2", "alias": "dup", "host_id": "b"}]

    def _repo_local(self): return self.local

    def hub(self, op, **kw):
        self.hub_calls.append((op, kw))
        if op == "directory_all": return {"projects": self.projects}
        if op == "repo_peer":
            if kw["repo_op"] == "list": return {"repos": [{"repo_id": "pb"}], "unavailable": ["c"]}
            return {"repo_id": kw["req"]["repo_id"], "from": "peer:" + kw["host"]}
        raise AssertionError(op)


EP = {"participant_id": "kai-participant", "address": "kai", "endpoint_id": "e1"}


class RepoRoutingTest(unittest.TestCase):
    def run_op(self, stub, op, **req):
        return host_mod.Host._repo(stub, EP, op, req)

    def test_the_reader_comes_from_the_endpoint_not_from_the_request(self):
        stub = Stub()
        self.run_op(stub, "read", repo_id="pa", path="f", participant_id="someone-else", generation="forged", host="b")
        op, reader, req = stub.local.calls[0]
        self.assertEqual(reader, {"participant_id": "kai-participant", "address": "kai", "generation": ""})
        self.assertEqual(req, {"repo_id": "pa", "path": "f"})      # unknown fields are dropped

    def test_local_project_is_read_here_and_remote_project_is_forwarded(self):
        stub = Stub()
        self.assertEqual(self.run_op(stub, "read", repo_id="pa", path="f")["from"], "local")
        out = self.run_op(stub, "read", repo_id="projb", path="f")
        self.assertEqual(out["from"], "peer:b")
        forwarded = [c for c in stub.hub_calls if c[0] == "repo_peer"][0][1]
        self.assertEqual(forwarded["endpoint_id"], "e1"); self.assertEqual(forwarded["host"], "b")
        self.assertEqual(forwarded["req"], {"repo_id": "projb", "path": "f"})

    def test_an_alias_owned_by_two_hosts_is_refused_not_guessed(self):
        with self.assertRaises(HubError) as ctx:
            self.run_op(Stub(), "read", repo_id="dup", path="f")
        self.assertEqual(ctx.exception.code, "invalid_request")

    def test_list_merges_local_and_peer_results_and_reports_unreachable_hosts(self):
        out = self.run_op(Stub(), "list")
        self.assertEqual([r["repo_id"] for r in out["repos"]], ["pa", "pb"])
        self.assertEqual(out["hosts_unavailable"], ["c"])

    def test_without_federation_nothing_leaves_this_host(self):
        stub = Stub(federated=False)
        self.assertEqual(self.run_op(stub, "list"), {"repos": [{"repo_id": "pa"}]})
        self.run_op(stub, "read", repo_id="projb", path="f")
        self.assertEqual([c for c in stub.hub_calls if c[0] == "repo_peer"], [])

    def test_a_refusal_keeps_its_fixed_code(self):
        with self.assertRaises(HubError) as ctx:
            self.run_op(Stub(), "read", repo_id="boom", path="f")
        self.assertEqual(ctx.exception.code, "not_granted")


if __name__ == "__main__":
    unittest.main()
