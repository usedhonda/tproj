import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("kai_runtime", ROOT / "runtime.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.binary = self.root / "tunnel-client"
        self.binary.write_text("#!/bin/sh\nmkdir -p \"$5\"\nprintf '{}' > \"$5/kai-event-probe.yaml\"\n")
        self.binary.chmod(0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, base, key):
        return type("Args", (), {"binary": str(self.binary), "tunnel_id": "tnl_test",
                                  "base_dir": str(base), "credential_file": str(key),
                                  "profile": "kai-event-probe", "label": MODULE.DEFAULT_LABEL,
                                  "mcp_command": "python3 server.py"})()

    def test_offline_prepare_is_inert_and_isolated(self):
        base = self.root / "runtime"
        key = self.root / "secret"  # intentionally absent; contents are never needed
        result = MODULE.prepare(self.args(base, key))
        self.assertFalse(result["profileInitialized"])
        self.assertTrue((base / "run.sh").exists())
        self.assertTrue((base / f"{MODULE.DEFAULT_LABEL}.plist").exists())
        self.assertNotIn("Observation", " ".join(str(p) for p in base.rglob("*")))

    def test_conflicting_manifest_refuses_overwrite(self):
        base = self.root / "runtime"
        key = self.root / "secret"
        MODULE.prepare(self.args(base, key))
        altered = self.args(base, key)
        altered.tunnel_id = "other"
        with self.assertRaises(MODULE.RuntimeError_):
            MODULE.prepare(altered)

    def test_runner_rejects_missing_or_insecure_key(self):
        base = self.root / "runtime"
        key = self.root / "secret"
        MODULE.prepare(self.args(base, key))
        self.assertNotEqual(os.system(str(base / "run.sh")), 0)
        key.write_text("placeholder")
        key.chmod(0o644)
        self.assertNotEqual(os.system(str(base / "run.sh")), 0)
        key.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_safe_key_allows_local_init_only(self):
        base = self.root / "runtime"
        key = self.root / "secret"
        key.write_text("opaque")
        key.chmod(0o600)
        result = MODULE.prepare(self.args(base, key))
        self.assertTrue(result["profileInitialized"])
        self.assertTrue((base / "profiles" / "kai-event-probe.yaml").exists())


if __name__ == "__main__":
    unittest.main()
