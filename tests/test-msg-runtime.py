#!/usr/bin/env python3
import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "extensions/messaging/unified"))
import runtime


class RuntimeSetupTests(unittest.TestCase):
    def test_dry_run_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            result = runtime.setup(home, dry_run=True)
            self.assertTrue(result["dry_run"])
            self.assertFalse((home / ".config/tproj/msg-host.json").exists())

    def test_setup_is_local_and_idempotent(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            first = runtime.setup(home)
            host = json.loads((home / ".config/tproj/msg-host.json").read_text())
            hub = json.loads((home / ".config/tproj/msg-hub.json").read_text())
            self.assertEqual(host["host_id"], hub["host_id"])
            self.assertEqual(host["host_token"], hub["hosts"][host["host_id"]])
            self.assertGreater(first["changed"], 0)
            before = (home / ".config/tproj/msg-host.json").read_bytes()
            second = runtime.setup(home, refresh=True)
            self.assertEqual(second["changed"], 0)
            self.assertEqual(before, (home / ".config/tproj/msg-host.json").read_bytes())

    def test_existing_remote_enrollment_requires_migrate(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw); config = home / ".config/tproj"; config.mkdir(parents=True)
            (config / "msg-client.json").write_text('{"active": true}\n')
            with self.assertRaises(RuntimeError): runtime.setup(home)
            self.assertIsInstance(runtime.setup(home, migrate=True), dict)


if __name__ == "__main__": unittest.main()
