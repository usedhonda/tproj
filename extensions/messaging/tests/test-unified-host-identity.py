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
    def test_retired_candidate_does_not_block_other_live_discovery(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            h = host_mod.Host({"journal":str(Path(tmp)/"journal.db"),"host_id":"host-a","host_token":"token"},recover=False)
            def hub(op, **args):
                if op=="directory_list":return {"projects":[]}
                if op=="endpoints_list":return {"endpoints":[]}
                if op=="endpoint_register":
                    if args["endpoint_id"]=="retired":raise host_mod.HubError("stale_session","retired endpoint cannot be revived")
                    return {"endpoint_id":"live","incarnation":"new"}
                return {}
            h.hub=hub
            entries=[dict(endpoint_id=n,participant_id=n,platform="cc") for n in ("retired","live")]
            with patch.object(host_mod,"discover_endpoints",return_value=entries),patch.object(host_mod,"discover_tmux_endpoints",return_value=[]):h.refresh()
            self.assertEqual([e["endpoint_id"] for e in h.endpoints],["live"])

    def test_historical_receipt_scan_keeps_heartbeats_fresh_and_stops_retired_endpoint(self):
        import json
        from unittest.mock import patch
        for retire in (False, True):
            with self.subTest(retire=retire), tempfile.TemporaryDirectory() as tmp:
                h = host_mod.Host({'journal': str(Path(tmp)/'journal.db'), 'delivery_enabled': True}, recover=False)
                ep = {'endpoint_id': 'current', 'platform': 'cdx', 'thread_id': 'native'}
                h.endpoints = [ep]
                clock = [100.0]
                h.refreshed = clock[0]
                ages = []
                def refresh():
                    h.refreshed = clock[0]
                    if retire:
                        h.endpoints = []
                h.refresh = refresh
                def hub(op, **args):
                    if op == 'claim':
                        return {'messages': [], 'next_sequence': 0}
                    if op == 'receipt':
                        ages.append(clock[0] - h.refreshed)
                    return {}
                h.hub = hub
                for i in range(4):
                    h.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                                 (str(i), 'current', json.dumps({'message_id': str(i)}), 'uncertain', 'hash', 0))
                h.db.commit()
                def inspect(*args):
                    clock[0] += 12
                    return False
                with patch.object(host_mod.time, 'monotonic', side_effect=lambda: clock[0]), \
                     patch.object(host_mod, 'codex_transcript_presented', side_effect=inspect):
                    h.delivery_tick()
                self.assertTrue(ages)
                self.assertLess(max(ages), 30, 'historical receipt scan starved heartbeat')
                self.assertEqual(len(ages), 1 if retire else 4)
                h.db.close()

    def test_missing_pane_preserves_message_and_does_not_crash_other_endpoint(self):
        import json
        import time
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            h = host_mod.Host({'journal': str(Path(tmp)/'journal.db'), 'delivery_enabled': True}, recover=False)
            h.endpoints = [dict(endpoint_id='no-pane', platform='cdx', pane=None,
                                pid=1, pid_start=1, runtime_id='native'),
                           dict(endpoint_id='other', platform='cdx', thread_id='other-native')]
            h.refreshed = time.monotonic()
            calls = []
            def hub(op, **args):
                calls.append((op, args))
                if op == 'claim':
                    return {'messages': [{'message_id': 'pending'}] if args['endpoint_id'] == 'no-pane' else [], 'next_sequence': 0}
                return {}
            h.hub = hub
            h.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',
                         ('old', 'other', json.dumps({'message_id': 'old'}), 'uncertain', 'hash', 0))
            h.db.commit()
            with patch.object(identity, '_process_info', return_value={'pid_start': 1}), \
                 patch.object(host_mod, 'codex_transcript_presented', return_value=False), \
                 patch.object(host_mod.subprocess, 'run') as terminal:
                h.delivery_tick()
                terminal.assert_not_called()
            self.assertEqual(h.db.execute("SELECT state FROM deliveries WHERE message_id='pending'").fetchone()[0], 'received')
            self.assertIn(('delivery_status', {'endpoint_id': 'no-pane', 'message_id': 'pending', 'reason': 'endpoint_unavailable', 'native_observation': None}), calls)
            self.assertTrue(any(op == 'receipt' and args['endpoint_id'] == 'other' for op, args in calls))
            self.assertFalse(any(op == 'begin_present' for op, args in calls))
            h.db.close()

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
                                         (state["registered"].append(dict(args)) or {"endpoint_id":args["endpoint_id"],"incarnation":"hub-issued"}) if op == "endpoint_register" else
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
            self.assertEqual(h.endpoints[0]["incarnation"], "hub-issued")
            self.assertEqual(state["registered"][0]["endpoint_id"], "fallback")
            self.assertEqual(state["registered"][0]["address"], "demo.cdx")
            self.assertEqual(state["registered"][0]["observed_runtime_id"], "conversation-uuid")
            self.assertEqual(identity.bind_caller(102, os.getuid(), [state["registered"][0]],
                                                  inspect_process=processes.__getitem__)["endpoint_id"], "fallback")

            state["registered"].clear()
            state["retired"].clear()
            restarted = dict(registry, pid=103, pid_start=99, thread_id="new-native-only",
                             project_id="other-project", project_path="/other-project", address="other.cdx")
            host_mod.discover_endpoints = lambda *args, **kwargs: [restarted]
            from unittest.mock import patch
            with patch.object(identity, '_process_info', side_effect=processes.get):
                h.refresh()
            self.assertEqual(state["registered"][0]["endpoint_id"], "registry")
            self.assertEqual(state["retired"], [])
            self.assertEqual({ep['endpoint_id'] for ep in h.endpoints}, {'fallback', 'registry'})
            preserved = next(ep for ep in h.endpoints if ep['endpoint_id'] == 'fallback')
            self.assertEqual(preserved['pid'], old['pid'])
            self.assertEqual(preserved['runtime_id'], old['runtime_id'])
            for key in ('project_id', 'project_path', 'address'):
                self.assertEqual(preserved.get(key), old.get(key))
            self.assertNotIn('thread_id', preserved)
            self.assertEqual(identity.bind_caller(101, os.getuid(), h.endpoints,
                              inspect_process=processes.__getitem__)['endpoint_id'], 'fallback')
            # Only actual disappearance of the old PID incarnation permits
            # retirement; a different observed process alone does not.
            from unittest.mock import patch
            processes.pop(101)
            with patch.object(identity, '_process_info', return_value=None), patch.object(
                    host_mod.os, 'kill', side_effect=ProcessLookupError):
                h.refresh()
            self.assertEqual(state["retired"], ["fallback"])


if __name__ == "__main__":
    unittest.main()
