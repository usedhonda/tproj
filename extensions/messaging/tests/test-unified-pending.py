#!/usr/bin/env python3
"""`pending` re-checks messages on the owning side and drops the ones already presented."""
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


class Stub:
    config = {"host_id": "dev"}

    def __init__(self, rows, remote):
        self.rows, self.remote, self.queried = rows, remote, []

    def hub(self, op, **kw):
        if op == "outbox":
            return {"messages": self.rows, "now": 1000.0}
        self.queried.append(kw["message_id"])
        if kw["message_id"] not in self.remote:
            raise HubError("unavailable", "owner side unreachable")
        return self.remote[kw["message_id"]]


def row(mid, target, kind, host, age, state="accepted"):
    return {"message_id": mid, "target_address": target, "state": state, "created_at": 1000.0 - age,
            "expires_at": 9999.0, "recipient_host_id": host, "recipient_kind": kind}


class PendingTest(unittest.TestCase):
    def test_owning_side_state_replaces_the_handoff_copy(self):
        stub = Stub(
            [row("m-local", "tproj.cdx", "cdx", "dev", 600),
             row("m-acked", "kai", "kai", "mini", 500),
             row("m-stuck", "kai", "kai", "mini", 400),
             row("m-away", "chi.cc", "cc", "mini", 300)],
            {"m-acked": {"state": "presented"},
             "m-stuck": {"state": "dispatching"},
             "m-away": {"state": "accepted", "remote_state": "unavailable"}})
        out = host_mod.Host._pending(stub, {"endpoint_id": "e"})
        by_target = {g["target"]: g for g in out["groups"]}
        self.assertEqual(out["total"], 3)
        self.assertEqual(by_target["kai"]["count"], 1)            # the acked one is gone
        self.assertEqual(by_target["kai"]["states"], {"dispatching": 1})
        self.assertEqual(by_target["kai"]["where"], "service")
        self.assertNotIn("m-local", stub.queried)                  # this Mac's own state is authoritative
        self.assertEqual(by_target["tproj.cdx"]["where"], "this_mac")
        self.assertEqual(by_target["chi.cc"]["where"], "other_mac")
        self.assertEqual(by_target["chi.cc"].get("unchecked"), 1)  # owner was unreachable: say so
        self.assertNotIn("unchecked", by_target["tproj.cdx"])

    def test_a_cap_bounds_how_many_remote_checks_one_call_makes(self):
        rows = [row(f"m{i}", "kai", "kai", "mini", 1000 - i) for i in range(40)]
        stub = Stub(rows, {r["message_id"]: {"state": "accepted"} for r in rows})
        out = host_mod.Host._pending(stub, {"endpoint_id": "e"})
        self.assertEqual(len(stub.queried), 25)
        self.assertEqual(out["total"], 40)
        self.assertEqual(out["groups"][0]["unchecked"], 15)


if __name__ == "__main__":
    unittest.main()
