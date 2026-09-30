#!/usr/bin/env python3
"""Freshness boundary for unified terminal prompt-state hints."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1] / "unified"
GUARD = ROOT / "terminal-guard.sh"


class TerminalFreshness(unittest.TestCase):
    def run_guard(self, state, timestamp, capture):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tmux = root / "tmux"
            fixture = root / "capture"
            fixture.write_text(capture)
            tmux.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  display-message) printf '0\\n' ;;\n"
                "  show-options) case \"$6\" in\n"
                "    @prompt_state) printf '%s\\n' \"$STATE\" ;;\n"
                "    @prompt_state_ts) printf '%s\\n' \"$TS\" ;;\n"
                "  esac ;;\n"
                "  capture-pane) cat \"$FIXTURE\" ;;\n"
                "esac\n"
            )
            tmux.chmod(0o755)
            env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}",
                       STATE=state, TS=str(timestamp), FIXTURE=str(fixture))
            return subprocess.run(
                ["bash", str(GUARD), "%1"],
                env=env, capture_output=True, text=True,
            )

    def test_fresh_typing_still_denies(self):
        result = self.run_guard("typing", int(time.time()), "❯ \n")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"reason":"busy"', result.stdout)

    def test_stale_typing_empty_prompt_falls_through_to_safe(self):
        result = self.run_guard("typing", int(time.time()) - 30, "❯ \n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_typing_real_draft_still_denies(self):
        result = self.run_guard("typing", int(time.time()) - 30, "❯ draft\n")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"reason":"draft_or_unclassified"', result.stdout)

    def test_stale_running_approval_still_denies(self):
        capture = "Permission required\n❯ Allow command\n  Deny\n"
        result = self.run_guard("running", int(time.time()) - 30, capture)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"reason":"selection_screen"', result.stdout)

    def test_invalid_or_future_timestamp_does_not_block_clean_prompt(self):
        for timestamp in ("not-a-timestamp", str(int(time.time()) + 30)):
            result = self.run_guard("busy", timestamp, "❯ \n")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
