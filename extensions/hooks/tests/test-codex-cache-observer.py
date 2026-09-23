#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


OBSERVER = Path(__file__).resolve().parents[1] / "tproj-codex-cache-observer"


class CodexCacheObserverTest(unittest.TestCase):
    def test_records_only_bound_codex_sample_and_redacts_payload(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            tmux = bin_dir / "tmux"
            tmux.write_text("#!/bin/sh\nprintf '%s\\n' '%2|/dev/ttys999|0|700|codex-p1|demo|test-session'\n")
            tmux.chmod(0o700)
            env = {
                **os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "TMUX_PANE": "%2", "TPROJ_CODEX_CACHE_DIR": str(root / "state"),
                "TPROJ_CODEX_OBSERVER_PID": "900",
                "TPROJ_CODEX_OBSERVER_PROCESS_CHAIN": "900 901 hook-shell;901 902 codex --stdio;902 700 zsh",
            }
            payload = {"hook_event_name": "UserPromptSubmit", "session_id": "codex-session",
                       "prompt": "do not persist", "transcript_path": "/private/transcript",
                       "prompt_cache": {"warm": True, "expires_at": 2_000_000_001,
                                        "read_tokens": 42}}
            result = subprocess.run(["python3", str(OBSERVER), "prompt"], input=json.dumps(payload),
                                    text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0)
            files = list((root / "state").glob("*.json"))
            self.assertEqual(len(files), 1)
            state = json.loads(files[0].read_text())
            self.assertTrue(state["sample_available"])
            self.assertEqual(state["cache_sample"]["read_tokens"], 42)
            self.assertNotIn("session_id", state)
            self.assertNotIn("do not persist", files[0].read_text())
            self.assertNotIn("transcript", files[0].read_text())

    def test_ambiguous_or_remote_binding_writes_nothing(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            tmux = bin_dir / "tmux"
            tmux.write_text("#!/bin/sh\nprintf '%s\\n' '%2|/dev/ttys999|0|700|codex-p1|demo|test-session'\n")
            tmux.chmod(0o700)
            env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "TMUX_PANE": "%2",
                   "TPROJ_CODEX_CACHE_DIR": str(root / "state"), "TPROJ_CODEX_OBSERVER_PID": "900",
                   "TPROJ_CODEX_OBSERVER_PROCESS_CHAIN": "900 901 hook-shell;901 902 codex --stdio;902 700 zsh"}
            subprocess.run(["python3", str(OBSERVER), "stop"], input=json.dumps({
                "hook_event_name": "Stop", "session_id": "codex-session", "remote": True}),
                text=True, env=env, check=True)
            self.assertFalse((root / "state").exists())


if __name__ == "__main__":
    unittest.main()
