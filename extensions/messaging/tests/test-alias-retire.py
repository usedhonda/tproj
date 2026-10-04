#!/usr/bin/env python3
"""A local project alias that moved elsewhere is retired; messages to the old name reach the new one."""
import pathlib, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from extensions.messaging.unified import Hub, HubError


class AliasRetireTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Hub(pathlib.Path(self.tmp.name) / "hub.db", {"admin_token": "adm", "host_id": "a", "hosts": {"a": "ta", "b": "tb"}})
        self.h.dispatch({"op": "directory_import", "admin_token": "adm", "projects": [
            {"project_id": "p", "alias": "proj", "host_id": "a", "path": "/p"},
            {"project_id": "o", "alias": "old", "host_id": "a", "path": "/o"}]})
        self.h.db.execute("UPDATE participants SET host_id='b' WHERE participant_id='p:cdx'")
        for host, tok, ep, part, pid in (("a", "ta", "ea", "p:cc", 1), ("b", "tb", "eb", "p:cdx", 2)):
            self.h.dispatch({"op": "endpoint_register", "host_id": host, "host_token": tok, "endpoint_id": ep, "participant_id": part,
                             "session": "s", "pane": "0", "pid": pid, "pid_start": "x", "runtime_id": "r", "platform": "test"})
    def tearDown(self): self.h.close(); self.tmp.cleanup()

    def retire(self, alias="old", successor="proj", token="adm"):
        return self.h.dispatch({"op": "directory_retire", "admin_token": token, "alias": alias, "successor": successor})

    def send(self, target, mid="m1"):
        return self.h.dispatch({"op": "submit", "host_id": "a", "host_token": "ta", "message": {
            "message_id": mid, "thread_id": "t", "sender_endpoint": "ea", "target": target, "body": "hi", "kind": "chat"}})

    def test_old_name_is_redirected_with_a_notice_and_a_retry_is_the_same_message(self):
        with self.assertRaises(HubError) as ctx: self.send("old.cdx", "m0")
        self.assertEqual(ctx.exception.code, "no_recipient")        # before: a dead local entry
        self.retire()
        out = self.send("old.cdx")
        self.assertEqual((out["renamed_from"], out["renamed_to"], out["state"]), ("old.cdx", "proj.cdx", "queued"))
        self.assertTrue(self.send("old.cdx")["duplicate"])
        inbox = self.h.dispatch({"op": "inbox", "host_id": "b", "host_token": "tb", "endpoint_id": "eb"})
        self.assertEqual([m["target_address"] for m in inbox["messages"]], ["proj.cdx"])

    def test_retired_project_leaves_the_directory_and_the_name_cannot_be_reused(self):
        self.retire()
        listed = self.h.directory_list()
        self.assertNotIn("old", [p["alias"] for p in listed["projects"]])
        self.assertFalse([x for x in listed["participants"] if x["address"].startswith("old.")])
        with self.assertRaises(HubError): self.send("old.bogus", "m2")

    def test_refusals(self):
        with self.assertRaises(HubError) as ctx: self.retire(token="nope")
        self.assertEqual(ctx.exception.code, "unauthorized")
        with self.assertRaises(HubError) as ctx: self.retire(alias="proj", successor="elsewhere")   # has a live endpoint
        self.assertEqual(ctx.exception.code, "project_in_use")
        with self.assertRaises(HubError) as ctx: self.retire(alias="missing")
        self.assertEqual(ctx.exception.code, "unknown_target")
        with self.assertRaises(HubError) as ctx: self.retire(successor="old")
        self.assertEqual(ctx.exception.code, "invalid_request")
        self.retire()
        with self.assertRaises(HubError) as ctx: self.retire()
        self.assertEqual(ctx.exception.code, "directory_conflict")


if __name__ == "__main__":
    unittest.main()
