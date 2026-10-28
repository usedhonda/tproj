import importlib.util
import tempfile
import json
import sys
from unittest.mock import patch
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "unified"
sys.path.insert(0,str(ROOT))
SPEC = importlib.util.spec_from_file_location("runtime", ROOT / "runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimeDirectoryRegistrationTests(unittest.TestCase):
    def test_native_expected_generation_triggers_existing_reload_decision_only_once(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            with patch.object(runtime,'_projects',return_value=[]), patch.object(runtime,'_activate',return_value=['skipped']) as activate:
                runtime.setup(home=home,no_start=True)
                cfgpath = home/'.config/tproj/msg-host.json'
                cfg = json.loads(cfgpath.read_text())
                cfg.update(native_queue_enabled=False,native_consumer_enabled=False)
                cfg['_native_runtime_expected'] = {'host_version':1}
                cfgpath.write_text(json.dumps(cfg))
                runtime.setup(home=home,no_start=True)
                self.assertTrue(activate.call_args.args[2])
                cfg = json.loads(cfgpath.read_text())
                self.assertEqual(cfg['_native_runtime_expected'],runtime.NATIVE_RUNTIME_CONTRACT)
                self.assertFalse(cfg['native_queue_enabled'])
                self.assertFalse(cfg['native_consumer_enabled'])
                runtime.setup(home=home,no_start=True)
                self.assertFalse(activate.call_args.args[2])

    def test_failed_existing_reload_is_not_reported_as_reloaded(self):
        import subprocess
        def run(args,**kwargs):
            return subprocess.CompletedProcess(args, 1 if args[1]=='kickstart' or (args[1]=='print' and args[2].startswith('gui/')) else 0)
        with patch.object(runtime.subprocess,'run',side_effect=run):
            result = runtime._activate(Path('/fixture'),[Path('/fixture/hub'),Path('/fixture/host')],True,False,False)
        self.assertEqual(result,['unavailable:local.tproj.msg-unified-hub','unavailable:local.tproj.msg-unified-host'])

    def test_headless_activation_uses_one_domain_and_requires_listener_response(self):
        import subprocess
        calls = []
        labels = ["local.tproj.msg-unified-hub", "local.tproj.msg-unified-host"]
        manifests = [Path("/fixture/hub"), Path("/fixture/host")]
        loaded = set()
        def run(args, **kwargs):
            calls.append(args)
            if args[1] == "print":
                return subprocess.CompletedProcess(args, 0 if args[2] in loaded else 113)
            if args[1] == "bootstrap":
                # Fail like launchd when an Aqua-only manifest is used headless.
                self.assertTrue(args[2].startswith("user/"))
                label = labels[manifests.index(Path(args[3]))]
                loaded.add(args[2] + "/" + label)
            return subprocess.CompletedProcess(args, 0)
        with patch.object(runtime.subprocess, "run", side_effect=run), \
             patch.object(runtime, "_activation_health", return_value=True):
            result = runtime._activate(Path("/fixture"), manifests, False, False, False)
            self.assertEqual(result, ["started:" + label for label in labels])
            calls.clear()
            self.assertEqual(runtime._activate(Path("/fixture"), manifests, False, False, False),
                             ["running:" + label for label in labels])
            self.assertFalse(any(c[1] in ("bootstrap", "kickstart") for c in calls))
        # A registered job and even a socket file do not prove a working listener.
        with patch.object(runtime.subprocess, "run", side_effect=run), \
             patch.object(runtime, "_activation_health", return_value=False):
            result = runtime._activate(Path("/fixture"), manifests, False, False, False)
        self.assertTrue(all("listener_unavailable" in item for item in result))
        # Existing GUI owner migrates even without config changes, never in parallel.
        loaded = {"gui/" + str(runtime.os.getuid()) + "/" + label for label in labels}
        calls.clear()
        with patch.object(runtime.subprocess, "run", side_effect=run), \
             patch.object(runtime, "_activation_health", return_value=True):
            runtime._activate(Path("/fixture"), manifests, False, False, False)
        for label in labels:
            stopped = calls.index(["/bin/launchctl", "bootout", "gui/" + str(runtime.os.getuid()) + "/" + label])
            started = next(i for i, c in enumerate(calls) if c[1] == "bootstrap" and c[3] == str(manifests[labels.index(label)]))
            self.assertLess(stopped, started)

    def test_gui_handover_waits_for_launchd_unregister_without_message_replay(self):
        import subprocess
        label = runtime.CORE_LABELS[0]
        calls = []
        gui_loaded = True
        attempts = 0
        def run(args, **kwargs):
            nonlocal gui_loaded, attempts
            calls.append(args)
            if args[1] == "print":
                rc = 0 if args[2].startswith("gui/") and gui_loaded else 113
            elif args[1] == "bootout":
                gui_loaded = False; rc = 0
            else:
                self.assertEqual(args[1], "bootstrap")
                attempts += 1; rc = 5 if attempts == 1 else 0
            return subprocess.CompletedProcess(args, rc)
        with patch.object(runtime.subprocess, "run", side_effect=run), \
             patch.object(runtime, "_activation_health", return_value=True), \
             patch.object(runtime.time, "sleep"):
            result = runtime._activate(Path("/fixture"), [Path("/fixture/hub")],
                                       False, False, False, labels=(label,))
        self.assertEqual(result, ["reloaded:" + label])
        self.assertEqual(attempts, 2)
        self.assertEqual(sum(c[1] == "bootout" for c in calls), 1)
        self.assertTrue(all(c[2].startswith("user/") for c in calls if c[1] == "bootstrap"))

    def test_recovery_activation_preserves_config_and_supports_background(self):
        import plistlib
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            runtime.setup(home, no_start=True)
            config = home / ".config/tproj/msg-host.json"
            before = config.read_bytes()
            with patch.object(runtime, "_activate", return_value=["running"]) as activate:
                runtime.activate(home)
            self.assertEqual(config.read_bytes(), before)
            self.assertFalse(activate.call_args.args[2])
            for manifest in activate.call_args.args[1]:
                self.assertEqual(plistlib.loads(manifest.read_bytes())["LimitLoadToSessionType"],
                                 "Background")

    def test_optional_bridge_recovery_is_separate_and_never_invented(self):
        import plistlib
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            runtime.setup(home, no_start=True)
            bridge = home / "Library/LaunchAgents/local.tproj.kai-mailbox.plist"
            bridge.write_bytes(plistlib.dumps({"Label": "local.tproj.kai-mailbox",
                                               "ProgramArguments": ["/fixture/mailbox"]}))
            with patch.object(runtime, "_activate", side_effect=[
                    ["running:" + label for label in runtime.CORE_LABELS],
                    ["unavailable:local.tproj.kai-mailbox:listener_unavailable"]]) as activate:
                results = runtime.activate(home)
            self.assertEqual(activate.call_count, 2)
            self.assertEqual(activate.call_args.kwargs["labels"], ("local.tproj.kai-mailbox",))
            self.assertTrue(results[-1].startswith("bridge_process_unavailable:"))
            self.assertFalse(any(item.startswith("unavailable:") for item in results))
            self.assertEqual(plistlib.loads(bridge.read_bytes())["ProgramArguments"], ["/fixture/mailbox"])
            self.assertFalse((bridge.parent / "local.tproj.muse-mailbox.plist").exists())
            # The actual Muse installer uses a private package path. It must
            # recover too, without a Library/LaunchAgents copy or new grant.
            muse = home / ".local/share/tproj/muse-mailbox/muse-mailbox.plist"
            muse.parent.mkdir(parents=True)
            muse.write_bytes(plistlib.dumps({"Label": "local.tproj.muse-mailbox",
                                             "ProgramArguments": ["/fixture/muse", "--bridge"]}))
            with patch.object(runtime, "_activate", side_effect=lambda *a, **kw: ["running"]) as activate:
                runtime.activate(home)
            self.assertEqual(activate.call_args.args[1], [muse])
            self.assertEqual(activate.call_args.kwargs["labels"], ("local.tproj.muse-mailbox",))
            self.assertEqual(plistlib.loads(muse.read_bytes())["LimitLoadToSessionType"], "Background")

    def test_adds_only_missing_requested_projects_once(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            (home / "existing").mkdir(); (home / "new").mkdir(); (home / "disabled").mkdir(); (home / ".config/tproj").mkdir(parents=True)
            (home / ".config/tproj/msg-host.json").write_text('{"host_id":"h","socket":"/tmp/host.sock"}')
            runtime._workspace_payload = lambda _home: {"projects": [
                {"alias": "existing", "path": str(home / "existing")},
                {"alias": "new", "path": str(home / "new")},
                {"alias": "disabled", "path": str(home / "disabled"), "enabled": False},
            ]}
            calls = []
            current = {"revision": 4, "projects": [{"project_id": "p-existing", "alias": "existing", "host_id": "h", "path": str(home / "existing")}, {"project_id": "p-foreign", "alias": "foreign", "host_id": "other", "path": str(home / "new")}]}
            def fake_rpc(_socket, request):
                calls.append(request)
                if request["op"] == "directory": return current
                return {"revision": 5}
            runtime._host_rpc = fake_rpc
            result = runtime.register_projects(home)
            self.assertEqual(result["added"], ["p-" + runtime.hashlib.sha256(f"h\0{home / 'new'}".encode()).hexdigest()[:24]])
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["expected_revision"], 4)
            self.assertEqual([p["alias"] for p in calls[1]["projects"]], ["new"])
            self.assertEqual(runtime.register_projects(home, aliases=["existing"])["added"], [])
            calls.clear()
            self.assertEqual(runtime.register_projects(home, aliases=["disabled"])["added"], ["p-" + runtime.hashlib.sha256(f"h\0{home / 'disabled'}".encode()).hexdigest()[:24]])

    def test_conflict_and_offline_leave_directory_untouched(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw); project = home / "project"; project.mkdir(); (home / ".config/tproj").mkdir(parents=True)
            (home / ".config/tproj/msg-host.json").write_text('{"host_id":"h","socket":"/tmp/host.sock"}')
            runtime._workspace_payload = lambda _home: {"projects": [{"alias": "taken", "path": str(project)}]}
            runtime._host_rpc = lambda _socket, request: {"revision": 1, "projects": [{"project_id": "other", "alias": "taken", "host_id": "h", "path": "/else"}]} if request["op"] == "directory" else self.fail("mutation after conflict")
            with self.assertRaises(RuntimeError): runtime.register_projects(home)

            runtime._workspace_payload = lambda _home: {"projects": [{"alias": "renamed", "path": str(project)}]}
            runtime._host_rpc = lambda _socket, request: {"revision": 1, "projects": [{"project_id": "owner", "alias": "taken", "host_id": "h", "path": str(project)}]} if request["op"] == "directory" else self.fail("alias reassignment must not mutate")
            with self.assertRaisesRegex(RuntimeError, "different alias"):
                runtime.register_projects(home)

            runtime._host_rpc = lambda _socket, request: (_ for _ in ()).throw(OSError("offline"))
            with self.assertRaises(OSError): runtime.register_projects(home, aliases=["renamed"])

            runtime._workspace_payload = lambda _home: {"projects": [{"alias": "fresh", "path": str(project)}]}
            def stale_rpc(_socket, request):
                if request["op"] == "directory":
                    return {"revision": 2, "projects": []}
                raise RuntimeError("revision_conflict")
            runtime._host_rpc = stale_rpc
            with self.assertRaisesRegex(RuntimeError, "revision_conflict"):
                runtime.register_projects(home)


if __name__ == "__main__":
    unittest.main()
