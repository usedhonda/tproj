import importlib.util
import json
import os
import sqlite3
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

    def test_shared_daemon_adopts_unrelated_tool_process_by_native_id(self):
        endpoint = {"endpoint_id": "adopt", "participant_id": "demo:cdx", "project_id": "demo",
                    "address": "demo.cdx", "platform": "cdx", "session": "shared",
                    "pid": 101, "pid_start": 77, "thread_id": "thread-adopt", "session_id": "session-adopt"}
        processes = {
            101: {"ppid": 1, "pid_start": 77, "uid": 501, "command": "codex app-server --stdio"},
            201: {"ppid": 1, "pid_start": 88, "uid": 501, "command": "codex app-server --stdio"},
            202: {"ppid": 201, "pid_start": 99, "uid": 501, "command": "tproj-msg"},
        }
        self.assertEqual(identity.bind_caller(202, 501, [endpoint], conversation={"thread_id": "thread-adopt"},
                                              inspect_process=processes.__getitem__), endpoint)

    def test_native_context_accepts_one_id_but_rejects_empty(self):
        self.assertEqual(identity.native_conversation_context({"CODEX_THREAD_ID": "t"}), {"thread_id": "t", "platform": "cdx"})
        self.assertEqual(identity.native_conversation_context({"CODEX_SESSION_ID": "s"}), {"session_id": "s", "platform": "cdx"})
        self.assertEqual(identity.native_conversation_context({}), {})

    def test_native_catalog_adopts_unique_tmux_endpoint_without_replacing_id(self):
        endpoint = {"endpoint_id": "stable", "platform": "cdx", "project_path": str(self.project),
                    "runtime_id": "tmux:sess:%1:77"}
        adopted = identity.adopt_native_conversation(
            [endpoint], {"thread_id": "thread-native", "session_id": "thread-native"},
            [{"host_id": "local", "thread_id": "thread-native", "cwd": str(self.project)}])
        self.assertEqual(adopted[0]["endpoint_id"], "stable")
        self.assertEqual(adopted[0]["thread_id"], "thread-native")
        self.assertEqual(adopted[0]["session_id"], "thread-native")

    def test_native_adoption_scopes_codex_and_preserves_conflicting_binding(self):
        cdx = {"endpoint_id": "cdx", "platform": "cdx", "project_path": str(self.project),
               "runtime_id": "tmux:cdx"}
        cc = {"endpoint_id": "cc", "platform": "cc", "project_path": str(self.project),
              "runtime_id": "tmux:cc"}
        adopted = identity.adopt_native_conversation(
            [cdx, cc], {"thread_id": "thread-native", "session_id": "thread-native"},
            [{"host_id": "local", "thread_id": "thread-native", "cwd": str(self.project)}])
        self.assertEqual(adopted[0]["thread_id"], "thread-native")
        self.assertNotIn("thread_id", adopted[1])
        bound = dict(cdx, thread_id="other-thread", session_id="other-session")
        preserved = identity.adopt_native_conversation(
            [bound], {"thread_id": "thread-native", "session_id": "session-native"},
            [{"host_id": "local", "thread_id": "thread-native", "cwd": str(self.project)}])
        self.assertEqual(preserved[0]["thread_id"], "other-thread")

    def test_composed_adoption_binds_shared_daemon_tmux_endpoint(self):
        cdx = {"endpoint_id": "tmux-cdx", "participant_id": "demo:cdx", "platform": "cdx",
               "project_path": str(self.project), "session": "tproj", "runtime_id": "tmux:tproj:%3:77",
               "pid": 101, "pid_start": 77}
        cc = dict(cdx, endpoint_id="tmux-cc", participant_id="demo:cc", platform="cc", pid=111, pid_start=88)
        context = {"thread_id": "native-equal", "session_id": "native-equal", "platform": "cdx"}
        adopted = identity.adopt_native_conversation([cdx, cc], context,
                    [{"host_id": "local", "thread_id": "native-equal", "cwd": str(self.project)}])
        processes = {
            101: {"ppid": 1, "pid_start": 77, "uid": 501, "command": "codex"},
            201: {"ppid": 1, "pid_start": 99, "uid": 501, "command": "codex app-server --stdio"},
            202: {"ppid": 201, "pid_start": 100, "uid": 501, "command": "tproj-msg"},
        }
        bound = identity.bind_caller(202, 501, adopted, conversation=context,
                                     inspect_process=processes.__getitem__)
        self.assertEqual(bound["endpoint_id"], "tmux-cdx")

    def test_native_catalog_keeps_long_lived_cli_thread(self):
        db = Path(self.tmp.name) / "codex.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE local_thread_catalog(host_id TEXT, thread_id TEXT, cwd TEXT, source_kind TEXT, source_updated_at REAL)")
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)", ("local", "old", str(self.project), "cli", 1.0))
        self.assertEqual(identity.native_thread_metadata("old", db)[0]["thread_id"], "old")

    def test_native_rollout_adopts_and_binds_when_catalog_is_missing(self):
        thread = "019e9e25-a537-75c3-821e-8d057e86d19e"
        sessions = Path(self.tmp.name) / "sessions" / "2026" / "10" / "02"
        sessions.mkdir(parents=True)
        rollout = sessions / f"rollout-2026-10-02T22-31-44-{thread}.jsonl"
        rollout.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": thread, "cwd": str(self.project),
            "originator": "codex-tui", "source": "vscode"}}) + "\n")
        metadata = identity.native_thread_metadata(thread, db_path=Path(self.tmp.name) / "missing.db",
                                                  sessions_root=Path(self.tmp.name) / "sessions")
        endpoint = {"endpoint_id": "tmux", "participant_id": "demo:cdx", "project_id": "demo",
                    "platform": "cdx", "project_path": str(self.project), "session": "shared",
                    "pid": 101, "pid_start": 77}
        context = {"thread_id": thread, "session_id": thread, "platform": "cdx"}
        adopted = identity.adopt_native_conversation([endpoint], context, metadata)
        self.assertEqual(adopted[0]["thread_id"], thread)
        processes = {
            101: {"ppid": 1, "pid_start": 77, "uid": 501, "command": "codex app-server --stdio"},
            102: {"ppid": 101, "pid_start": 88, "uid": 501, "command": "tproj-msg"},
        }
        self.assertEqual(identity.bind_caller(102, 501, adopted, conversation=context,
                                              inspect_process=processes.__getitem__), adopted[0])

    def test_native_vscode_catalog_transition_requires_matching_rollout_and_binds(self):
        thread = "019e9e25-a537-75c3-821e-8d057e86d19e"
        sessions = Path(self.tmp.name) / "sessions" / "2026" / "10" / "02"
        sessions.mkdir(parents=True)
        (sessions / f"rollout-2026-10-02T22-31-44-{thread}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {
                "id": thread, "session_id": thread, "cwd": str(self.project),
                "originator": "codex-tui", "source": "vscode"}}) + "\n")
        db = Path(self.tmp.name) / "codex.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE local_thread_catalog(host_id TEXT, thread_id TEXT, cwd TEXT, source_kind TEXT, source_updated_at REAL)")
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("local", thread, str(self.project), "vscode", 1.0))
        metadata = identity.native_thread_metadata(thread, db, Path(self.tmp.name) / "sessions")
        self.assertEqual(metadata[0]["source_kind"], "vscode-rollout")
        endpoint = {"endpoint_id": "tmux", "participant_id": "demo:cdx", "project_id": "demo",
                    "platform": "cdx", "project_path": str(self.project), "session": "shared",
                    "pid": 101, "pid_start": 77}
        context = {"thread_id": thread, "session_id": thread, "platform": "cdx"}
        adopted = identity.adopt_native_conversation([endpoint], context, metadata)
        processes = {
            101: {"ppid": 1, "pid_start": 77, "uid": 501, "command": "codex app-server --stdio"},
            102: {"ppid": 101, "pid_start": 88, "uid": 501, "command": "tproj-msg"},
        }
        self.assertEqual(identity.bind_caller(102, 501, adopted, conversation=context,
                                              inspect_process=processes.__getitem__), adopted[0])

    def test_native_vscode_catalog_transition_rejects_conflicts(self):
        thread = "019e9e25-a537-75c3-821e-8d057e86d19e"
        sessions = Path(self.tmp.name) / "sessions" / "2026" / "10" / "02"
        sessions.mkdir(parents=True)
        (sessions / f"rollout-2026-10-02T22-31-44-{thread}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {
                "id": thread, "session_id": thread, "cwd": str(self.project),
                "originator": "codex-tui", "source": "vscode"}}) + "\n")
        db = Path(self.tmp.name) / "codex.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE local_thread_catalog(host_id TEXT, thread_id TEXT, cwd TEXT, source_kind TEXT, source_updated_at REAL)")
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("local", thread, str(self.project / "elsewhere"), "vscode", 1.0))
        self.assertEqual(identity.native_thread_metadata(thread, db, Path(self.tmp.name) / "sessions"), [])
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM local_thread_catalog")
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("local", thread, str(self.project), "vscode", 1.0))
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("local", thread, str(self.project), "vscode", 2.0))
        self.assertEqual(identity.native_thread_metadata(thread, db, Path(self.tmp.name) / "sessions"), [])
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM local_thread_catalog")
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("local", thread, str(self.project), "vscode", 1.0))
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("local", thread, str(self.project), "other", 2.0))
        self.assertEqual(identity.native_thread_metadata(thread, db, Path(self.tmp.name) / "sessions"), [])
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM local_thread_catalog")
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("local", thread, str(self.project), "vscode", 1.0))
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("remote", thread, str(self.project), "vscode", 2.0))
        self.assertEqual(identity.native_thread_metadata(thread, db, Path(self.tmp.name) / "sessions"), [])

    def test_native_rollout_rejects_wrong_source_and_conflicting_catalog(self):
        thread = "019e9e25-a537-75c3-821e-8d057e86d19e"
        sessions = Path(self.tmp.name) / "sessions" / "2026" / "10" / "02"
        sessions.mkdir(parents=True)
        rollout = sessions / f"rollout-2026-10-02T22-31-44-{thread}.jsonl"
        rollout.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": thread, "session_id": thread, "cwd": str(self.project),
            "originator": "other-client", "source": "vscode"}}) + "\n")
        self.assertEqual(identity.native_thread_metadata(thread, db_path=Path(self.tmp.name) / "missing.db",
                                                         sessions_root=Path(self.tmp.name) / "sessions"), [])
        endpoint = {"endpoint_id": "tmux", "platform": "cdx", "project_path": str(self.project)}
        conflicting = [{"host_id": "local", "thread_id": thread, "session_id": "other-session",
                        "cwd": str(self.project), "source_kind": "cli"}]
        self.assertEqual(identity.adopt_native_conversation(
            [endpoint], {"thread_id": thread, "session_id": "requested-session"}, conflicting), [endpoint])

    def test_native_catalog_conflict_blocks_rollout_fallback(self):
        thread = "019e9e25-a537-75c3-821e-8d057e86d19e"
        sessions = Path(self.tmp.name) / "sessions" / "2026" / "10" / "02"
        sessions.mkdir(parents=True)
        (sessions / f"rollout-2026-10-02T22-31-44-{thread}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {
                "id": thread, "cwd": str(self.project), "originator": "codex-tui", "source": "vscode"}})
            + "\n")
        db = Path(self.tmp.name) / "codex.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE local_thread_catalog(host_id TEXT, thread_id TEXT, cwd TEXT, source_kind TEXT, source_updated_at REAL)")
            conn.execute("INSERT INTO local_thread_catalog VALUES(?,?,?,?,?)",
                         ("remote", thread, str(self.project), "cli", 1.0))
        self.assertEqual(identity.native_thread_metadata(thread, db, Path(self.tmp.name) / "sessions"), [])

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
