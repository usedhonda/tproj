#!/usr/bin/env python3
"""Focused trust metadata checks for the Codex hook installer."""

import runpy
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "install-tproj-hooks"
hook_metadata = runpy.run_path(str(INSTALLER))["hook_metadata"]


class HookMetadataTest(unittest.TestCase):
    def test_optional_hook_is_accepted_with_required_hooks(self):
        source = Path("/tmp/tproj-hooks.json")
        names = (
            "tproj-inbox-record",
            "tproj-inbox-check",
            "tproj-completion-guard",
            "tproj-mutation-guard",
            "tproj-codex-cache-observer",
        )
        hooks = [
            {
                "key": name,
                "sourcePath": str(source),
                "command": f"/tmp/bin/{name}",
                "currentHash": "sha256:abc",
            }
            for name in names
        ]
        found = hook_metadata({"result": {"data": [{"hooks": hooks}]}}, source)
        self.assertEqual({entry["key"] for entry in found}, set(names))


if __name__ == "__main__":
    unittest.main()
