import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unified"))
spec = importlib.util.spec_from_file_location("unified_host", ROOT / "unified" / "host.py")
host_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_mod)
import identity


class UnifiedHostIdentityTest(unittest.TestCase):
    def test_refresh_keeps_fallback_id_and_rejects_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {"endpoint_id": "fallback", "participant_id": "demo:cdx", "project_id": "demo",
                   "host_id": "host-a", "address": "demo.cdx", "session": "sess", "pane": "%34",
                   "pid": 101, "pid_start": 77, "runtime_id": "tmux:sess:%34:77", "platform": "cdx",
                   "retired": 0}
            registry = dict(old, endpoint_id="registry", pid=102, pid_start=88,
                            runtime_id="conversation-uuid")
            state = {"registered": [], "retired": []}
            processes = {101: {"ppid": 1, "pid_start": 77, "uid": os.getuid(), "command": "node codex"},
                         102: {"ppid": 101, "pid_start": 88, "uid": os.getuid(), "command": "codex"}}
            h = host_mod.Host({"journal": str(Path(tmp) / "journal.db"), "host_id": "host-a",
                               "host_token": "token", "registry": str(Path(tmp) / "registry")}, recover=False)
            h.hub = lambda op, **args: ({"projects": [{"project_id": "demo", "alias": "demo",
                                                           "host_id": "host-a", "path": tmp}]}
                                         if op == "directory_list" else
                                         {"endpoints": [old]} if op == "endpoints_list" else
                                         (state["registered"].append(dict(args)) or {}) if op == "endpoint_register" else
                                         (state["retired"].append(args["endpoint_id"]) or {}) if op == "endpoint_retire" else {})
            original_registry = host_mod.discover_endpoints
            original_tmux = host_mod.discover_tmux_endpoints
            original_family = host_mod.same_live_process_family
            host_mod.discover_endpoints = lambda *args, **kwargs: [registry]
            host_mod.discover_tmux_endpoints = lambda *args, **kwargs: []
            host_mod.same_live_process_family = lambda a, b: identity.same_live_process_family(
                a, b, inspect_process=processes.__getitem__)
            self.addCleanup(setattr, host_mod, "discover_endpoints", original_registry)
            self.addCleanup(setattr, host_mod, "discover_tmux_endpoints", original_tmux)
            self.addCleanup(setattr, host_mod, "same_live_process_family", original_family)
            h.refresh()
            self.assertEqual(state["registered"][0]["endpoint_id"], "fallback")
            self.assertEqual(state["registered"][0]["address"], "demo.cdx")
            self.assertEqual(state["registered"][0]["observed_runtime_id"], "conversation-uuid")
            self.assertEqual(identity.bind_caller(102, os.getuid(), [state["registered"][0]],
                                                  inspect_process=processes.__getitem__)["endpoint_id"], "fallback")

            state["registered"].clear()
            state["retired"].clear()
            restarted = dict(registry, pid=103, pid_start=99)
            host_mod.discover_endpoints = lambda *args, **kwargs: [restarted]
            h.refresh()
            self.assertEqual(state["registered"][0]["endpoint_id"], "registry")
            self.assertEqual(state["retired"], ["fallback"])


if __name__ == "__main__":
    unittest.main()
