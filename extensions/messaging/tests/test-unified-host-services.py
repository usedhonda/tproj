import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unified"))
spec = importlib.util.spec_from_file_location("unified_host", ROOT / "unified" / "host.py")
host_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_mod)
from protocol import HubError


class UnifiedHostServicesTest(unittest.TestCase):
    def host(self, tmp, **extra):
        config = {
            "journal": str(Path(tmp) / "journal.db"),
            "host_id": "host-a",
            "services": {
                "openclaw": {
                    "participant_id": "gate",
                    "address": "gate",
                    "token": "open-token",
                    "launchd_label": "com.example.openclaw",
                    "platform": "openclaw",
                },
                "kai": {
                    "participant_id": "kai-service",
                    "address": "kai",
                    "token": "kai-token",
                    "launchd_label": "com.example.kai",
                    "platform": "kai",
                },
            },
        }
        config.update(extra)
        return host_mod.Host(config, recover=False)

    @staticmethod
    def launchd(pid):
        return subprocess.CompletedProcess([], 0, stdout='"PID" = %d;\n' % pid, stderr='')

    def test_service_registry_binds_identity_platform_and_incarnation(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            host.hub = lambda op, **args: {"endpoints": []} if op == "endpoints_list" else {}
            with patch.object(host_mod.subprocess, "run", return_value=self.launchd(os.getpid())), \
                 patch("identity._process_info", return_value={"pid_start": 42}):
                ep = host.service(os.getpid(), os.getuid(), {
                    "service_id": "kai", "service_token": "kai-token", "address": "kai"})
            self.assertEqual(ep["participant_id"], "kai-service")
            self.assertEqual(ep["platform"], "kai")
            self.assertEqual(ep["service_id"], "kai")
            host.db.close()

    def test_service_id_prevents_cross_service_token_or_address_confusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            for req in (
                {"service_id": "kai", "service_token": "open-token", "address": "kai"},
                {"service_id": "kai", "service_token": "kai-token", "address": "gate"},
                {"service_id": "missing", "service_token": "kai-token", "address": "kai"},
            ):
                with self.assertRaises(HubError):
                    host.service(os.getpid(), os.getuid(), req)
            host.db.close()

    def test_kai_cannot_be_declared_as_openclaw_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            host.config["services"]["kai"]["platform"] = "openclaw"
            with self.assertRaisesRegex(HubError, "cannot use openclaw"):
                host.service(os.getpid(), os.getuid(), {
                    "service_id": "kai", "service_token": "kai-token", "address": "kai"})
            host.db.close()

    def test_legacy_service_config_remains_openclaw(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = host_mod.Host({
                "journal": str(Path(tmp) / "journal.db"), "host_id": "host-a",
                "service": {"participant_id": "gate", "address": "gate", "token": "token",
                             "launchd_label": "com.example.openclaw"},
            }, recover=False)
            self.assertEqual(host._service_binding({})[0], "openclaw")
            self.assertEqual(host._service_binding({})[1]["address"], "gate")
            host.hub = lambda op, **args: {"endpoints": []} if op == "endpoints_list" else {}
            with patch.object(host_mod.subprocess, "run", return_value=self.launchd(os.getpid())), \
                 patch("identity._process_info", return_value={"pid_start": 42}):
                ep = host.service(os.getpid(), os.getuid(), {"service_token": "token", "address": "gate"})
            expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "host-a:gate:%d:42" % os.getpid()))
            self.assertEqual(ep["endpoint_id"], expected)
            host.db.close()

    def test_duplicate_service_participant_or_address_rejected_before_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            host.config["services"]["kai"]["participant_id"] = "gate"
            calls = []
            host.hub = lambda op, **args: calls.append((op, args)) or {"endpoints": []}
            with self.assertRaisesRegex(HubError, "duplicate service participant_id"):
                host.service(os.getpid(), os.getuid(), {
                    "service_id": "kai", "service_token": "kai-token", "address": "kai"})
            self.assertEqual(calls, [])

    def test_scoped_inbox_message_and_ack_use_authenticated_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self.host(tmp)
            ep = {"endpoint_id": "kai-endpoint", "runtime_id": "kai-runtime"}
            host.service = lambda pid, uid, req: ep
            calls = []

            def hub(op, **args):
                calls.append((op, args))
                if op == "query":
                    return {"message_id": args["message_id"], "recipient_endpoint": ep["endpoint_id"]}
                return {"messages": [], "next_cursor": 0} if op == "inbox" else {"state": "presented"}

            host.hub = hub
            self.assertEqual(host.dispatch({"op": "service_inbox", "service_id": "kai"}, os.getpid(), os.getuid())["next_cursor"], 0)
            self.assertEqual(host.dispatch({"op": "service_message", "service_id": "kai", "message_id": "m1"}, os.getpid(), os.getuid())["message_id"], "m1")
            host.dispatch({"op": "service_ack", "service_id": "kai", "message_id": "m1"}, os.getpid(), os.getuid())
            self.assertEqual([item[0] for item in calls], ["inbox", "query", "query", "receipt"])
            host.db.close()


if __name__ == "__main__":
    unittest.main()
