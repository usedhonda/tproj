import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "unified" / "identity.py"
spec = importlib.util.spec_from_file_location("unified_identity", SOURCE)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class UnifiedIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.registry = root / "registry"
        self.registry.mkdir()
        self.projects = [{"project_id": "demo", "alias": "demo", "host_id": "host-a",
                          "path": str(self.project)}]
        self.record = {"alias": "demo.cc", "project": str(self.project), "pid": 101,
                       "pid_start": 77, "observed_at": 100, "session_id": "sess",
                       "runtime_id": "runtime-1", "pane": "%1"}
        (self.registry / "demo.cc.json").write_text(json.dumps(self.record))

    def live(self, pid):
        return {101: {"ppid": 1, "pid_start": 77, "uid": 501,
                      "command": "claude --session sess"}}[pid]

    def test_discovery_and_stable_incarnation(self):
        one = identity.discover_endpoints(self.registry, "host-a", self.projects,
                                          now=100, inspect_process=self.live)
        two = identity.discover_endpoints(self.registry, "host-a", self.projects,
                                          now=100, inspect_process=self.live)
        self.assertEqual(one, two)
        self.assertEqual(one[0]["participant_id"], "demo:cc")
        self.assertEqual(one[0]["address"], "demo.cc")
        self.assertEqual(one[0]["endpoint_id"], identity.discover_endpoints(
            self.registry, "host-a", self.projects, now=100, inspect_process=self.live)[0]["endpoint_id"])

    def test_stale_and_pid_reuse_and_proxy_are_rejected(self):
        self.assertEqual(identity.discover_endpoints(self.registry, "host-a", self.projects,
                                                     now=100 + 172801, inspect_process=self.live), [])
        self.record["observed_at"] = 100
        self.record["pid_start"] = 78
        (self.registry / "demo.cc.json").write_text(json.dumps(self.record))
        self.assertEqual(identity.discover_endpoints(self.registry, "host-a", self.projects,
                                                     now=100, inspect_process=self.live), [])
        self.record["pid_start"] = 77
        (self.registry / "demo.cc.json").write_text(json.dumps(self.record))
        self.assertEqual(identity.discover_endpoints(self.registry, "host-a", self.projects,
                                                     now=100, inspect_process=lambda _: {
                                                         "ppid": 1, "pid_start": 77, "uid": 501,
                                                         "command": "ssh proxy"}), [])

    def test_binding_requires_ancestry_and_rejects_ambiguity(self):
        endpoint = identity.discover_endpoints(self.registry, "host-a", self.projects,
                                               now=100, inspect_process=self.live)[0]
        def child(pid):
            if pid == 9:
                return {"ppid": 101, "pid_start": 66, "uid": 501, "command": "host-agent"}
            return self.live(pid)
        self.assertEqual(identity.bind_caller(9, 501, [endpoint], inspect_process=child), endpoint)
        with self.assertRaises(identity.IdentityError):
            identity.bind_caller(9, 501, [endpoint], claimed_alias="other.cc", inspect_process=child)
        other = dict(endpoint, endpoint_id="other", address="demo.cc", pid=101, pid_start=77)
        with self.assertRaisesRegex(identity.IdentityError, "ambiguous"):
            identity.bind_caller(9, 501, [endpoint, other], inspect_process=child)

    def test_shared_app_server_cannot_bind_itself_children_or_launcher(self):
        launcher = {"endpoint_id": "launcher", "address": "demo.cdx", "platform": "cdx",
                    "pid": 101, "pid_start": 77, "session": "sess"}
        daemon = dict(launcher, endpoint_id="daemon", pid=102, pid_start=88)
        child = dict(launcher, endpoint_id="child", pid=103, pid_start=99)
        processes = {
            101: {"ppid": 1, "pid_start": 77, "uid": 501, "command": "codex resume --last"},
            102: {"ppid": 101, "pid_start": 88, "uid": 501, "command": ""},
            103: {"ppid": 102, "pid_start": 99, "uid": 501, "command": "codex tool-child"},
        }
        for command in ("codex app-server --listen unix:// --managed-daemon",
                        "/opt/bin/codex app-server",
                        "/opt/bin/node /opt/lib/codex.js app-server"):
            processes[102]["command"] = command
            for caller in (102, 103):
                for endpoint in (launcher, daemon, child):
                    for alias in (None, "demo.cdx"):
                        with self.subTest(command=command, caller=caller,
                                          endpoint=endpoint["endpoint_id"], alias=alias):
                            with self.assertRaisesRegex(identity.IdentityError, "app-server ancestry"):
                                identity.bind_caller(caller, 501, [endpoint], session="sess",
                                                     claimed_alias=alias,
                                                     inspect_process=processes.__getitem__)

    def test_standalone_codex_cli_child_still_binds(self):
        endpoint = {"endpoint_id": "cli", "address": "demo.cdx", "platform": "cdx",
                    "pid": 101, "pid_start": 77, "session": "sess"}
        processes = {
            101: {"ppid": 1, "pid_start": 77, "uid": 501, "command": "codex resume --last"},
            102: {"ppid": 101, "pid_start": 88, "uid": 501, "command": "tproj-msg"},
        }
        for command in ("tproj-msg", 'tproj-msg peer "codex app-server"',
                        "zsh -c 'tproj-msg peer \"codex app-server\"'"):
            processes[102]["command"] = command
            with self.subTest(command=command):
                self.assertEqual(identity.bind_caller(102, 501, [endpoint], session="sess",
                                                      claimed_alias="demo.cdx",
                                                      inspect_process=processes.__getitem__), endpoint)

    def test_shared_app_server_binds_native_conversation_and_rejects_cross_project(self):
        base = {"address": "demo.cdx", "platform": "cdx", "session": "shared",
                "pid": 101, "pid_start": 77}
        first = dict(base, endpoint_id="one", participant_id="demo:cdx", project_id="demo",
                     thread_id="thread-one", session_id="session-one")
        second = dict(base, endpoint_id="two", participant_id="other:cdx", project_id="other",
                      address="other.cdx", thread_id="thread-two", session_id="session-two")
        processes = {
            101: {"ppid": 1, "pid_start": 77, "uid": 501, "command": "codex app-server --stdio"},
            102: {"ppid": 101, "pid_start": 88, "uid": 501, "command": "tproj-msg"},
        }
        context = {"thread_id": "thread-one", "session_id": "session-one", "project_id": "demo", "platform": "cdx"}
        self.assertEqual(identity.bind_caller(102, 501, [first, second], session="shared",
                                              claimed_alias="demo.cdx", conversation=context,
                                              inspect_process=processes.__getitem__), first)
        with self.assertRaises(identity.IdentityError):
            identity.bind_caller(102, 501, [first, second], session="shared",
                                 claimed_alias="other.cdx", conversation=context,
                                 inspect_process=processes.__getitem__)

    def test_native_context_accepts_one_id_but_rejects_empty(self):
        self.assertEqual(identity.native_conversation_context({"CODEX_THREAD_ID": "t"}), {"thread_id": "t"})
        self.assertEqual(identity.native_conversation_context({"CODEX_SESSION_ID": "s"}), {"session_id": "s"})
        self.assertEqual(identity.native_conversation_context({}), {})

    def test_tmux_fallback_requires_live_agent_descendant_and_deduplicates_registry(self):
        panes = lambda: [
            {"session": "sess", "pane": "%1", "pane_pid": "10", "project": str(self.project),
             "alias": "demo", "role": "claude-p1"},
            {"session": "sess", "pane": "%2", "pane_pid": "20", "project": str(self.project),
             "alias": "demo", "role": "codex-p1"},
            {"session": "sess", "pane": "%3", "pane_pid": "30", "project": str(self.project),
             "alias": "demo", "role": "claude-p2"},
        ]
        descendants = lambda pid: {10: [11], 20: [21], 30: [31]}[pid]
        processes = {
            11: {"ppid": 10, "pid_start": 111, "uid": os.getuid(), "command": "claude --session sess"},
            21: {"ppid": 20, "pid_start": 222, "uid": os.getuid(), "command": "ssh host codex"},
            31: {"ppid": 30, "pid_start": 333, "uid": os.getuid(), "command": "tmux helper"},
        }
        found = identity.discover_tmux_endpoints("host-a", self.projects, panes=panes,
                                                  descendants=descendants,
                                                  inspect_process=processes.__getitem__)
        self.assertEqual([item["participant_id"] for item in found], ["demo:cc"])
        again = identity.discover_tmux_endpoints("host-a", self.projects, found, panes=panes,
                                                  descendants=descendants,
                                                  inspect_process=processes.__getitem__)
        self.assertEqual(again, [])

    def test_tmux_fallback_preserves_distinct_live_panes_for_ambiguity_rejection(self):
        panes = lambda: [
            {"session": "sess", "pane": "%1", "pane_pid": "10", "project": str(self.project),
             "alias": "demo", "role": "claude-p1"},
            {"session": "sess", "pane": "%2", "pane_pid": "20", "project": str(self.project),
             "alias": "demo", "role": "claude-p2"},
        ]
        descendants = lambda pid: {10: [11], 20: [21]}[pid]
        processes = {
            11: {"ppid": 10, "pid_start": 111, "uid": os.getuid(), "command": "claude --session sess"},
            21: {"ppid": 20, "pid_start": 222, "uid": os.getuid(), "command": "claude --session sess"},
        }
        found = identity.discover_tmux_endpoints("host-a", self.projects, panes=panes,
                                                  descendants=descendants,
                                                  inspect_process=processes.__getitem__)
        self.assertEqual(len(found), 2)
        self.assertEqual({item["pane"] for item in found}, {"%1", "%2"})

    def test_fallback_to_registry_preserves_identity_only_for_verified_live_family(self):
        fallback = {"endpoint_id": "fallback", "participant_id": "demo:cdx", "host_id": "host-a",
                    "session": "sess", "pane": "%1", "pid": 101, "pid_start": 77,
                    "runtime_id": "tmux:sess:%1:77", "platform": "cdx"}
        registry = dict(fallback, endpoint_id="registry", pid=102, pid_start=88,
                        runtime_id="conversation-uuid")
        processes = {
            101: {"ppid": 1, "pid_start": 77, "uid": 501, "command": "node codex"},
            102: {"ppid": 101, "pid_start": 88, "uid": 501, "command": "codex"},
        }
        inspect = processes.__getitem__
        self.assertTrue(identity.same_live_process_family(fallback, registry, inspect_process=inspect))
        # A reused PID/start or changed process tree must never inherit identity.
        restarted = dict(registry, pid_start=99)
        self.assertFalse(identity.same_live_process_family(fallback, restarted, inspect_process=inspect))
        unrelated = dict(registry, pid=103, pid_start=90)
        processes[103] = {"ppid": 1, "pid_start": 90, "uid": 501, "command": "codex"}
        self.assertFalse(identity.same_live_process_family(fallback, unrelated, inspect_process=inspect))


if __name__ == "__main__":
    unittest.main()
