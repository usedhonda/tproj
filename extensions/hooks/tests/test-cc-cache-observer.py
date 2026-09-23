#!/usr/bin/env python3
"""One focused fixture for Tproj-owned Claude cache observation."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


OBSERVER = Path(__file__).resolve().parents[1] / "tproj-cc-cache-observer"
TAP = Path(__file__).resolve().parents[1] / "tproj-cc-statusline-tap"


class CCCacheObserverTest(unittest.TestCase):
    def test_statusline_tap_preserves_renderer_output_and_observes_copy(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            home_bin = root / "bin"
            home_bin.mkdir()
            (home_bin / "tproj-cc-cache-observer").symlink_to(OBSERVER)
            fake_tmux = home_bin / "tmux"
            fake_tmux.write_text("#!/bin/sh\nprintf '%s\\n' '%2|/dev/ttys999|0|111|claude-p1|demo|test-session'\n")
            fake_tmux.chmod(0o700)
            renderer = home_bin / "renderer"
            renderer.write_text("#!/bin/sh\ncat\n")
            renderer.chmod(0o700)
            payload = json.dumps({"session_id": "tap-session", "prompt_cache": {
                "warm": True, "expires_at": 2_000_000_001}})
            env = {**os.environ, "HOME": str(root), "PATH": f"{home_bin}:{os.environ['PATH']}",
                   "TMUX_PANE": "%2", "TPROJ_CC_CACHE_DIR": str(root / "state")}
            result = subprocess.run(["python3", str(TAP), "--", str(renderer)],
                                    input=payload, text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, payload)
            state_files = list((root / "state").glob("*.json"))
            self.assertEqual(len(state_files), 1)
            self.assertEqual(json.loads(state_files[0].read_text())["cache_expires_at"], 2_000_000_001)

    def test_statusline_prompt_and_keepalive_are_scoped_and_private(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_tmux = bin_dir / "tmux"
            fake_tmux.write_text(
                "#!/bin/sh\nprintf '%s\\n' '%2|/dev/ttys999|0|111|claude-p1|demo|test-session'\n"
            )
            fake_tmux.chmod(0o700)
            state_dir = root / "state"
            env = {
                **os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "TMUX_PANE": "%2", "TPROJ_CC_CACHE_DIR": str(state_dir),
            }

            def observe(event, payload, override_env=None):
                result = subprocess.run(
                    ["python3", str(OBSERVER), event], input=json.dumps(payload),
                    text=True, capture_output=True, env=override_env or env, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            observe("statusline", {
                "session_id": "test-session-id",
                "prompt_cache": {"warm": True, "expires_at": 2_000_000_000,
                                 "recache_tokens_if_cold": 1234},
                "transcript_path": "/private/do-not-store",
            })
            observe("prompt", {"session_id": "test-session-id", "prompt": "private test text"})
            files = list(state_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            state = json.loads(files[0].read_text())
            self.assertEqual(state["cache_expires_at"], 2_000_000_000)
            self.assertEqual(state["last_user_prompt_at"] > 0, True)
            self.assertEqual(state["pane_id"], "%2")
            self.assertEqual(state["turn_state"], "running")
            self.assertEqual(state["owner_session"], "test-session")
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertNotIn("private test text", files[0].read_text())
            self.assertNotIn("do-not-store", files[0].read_text())

            previous_prompt_at = state["last_user_prompt_at"]
            observe("prompt", {"session_id": "test-session-id", "prompt": "[keep-alive] ok"})
            self.assertEqual(json.loads(files[0].read_text())["last_user_prompt_at"], previous_prompt_at)
            observe("stop", {"session_id": "test-session-id"})
            self.assertEqual(json.loads(files[0].read_text())["turn_state"], "stop_seen")
            observe("statusline", {"session_id": "test-session-id", "prompt_cache": {"warm": False}})
            self.assertIsNone(json.loads(files[0].read_text())["cache_expires_at"])

            observe("statusline", {"session_id": "new-session", "prompt_cache": {"warm": True,
                    "expires_at": 2_000_000_002}})
            newer = [file for file in state_dir.glob("*.json") if file != files[0]]
            self.assertEqual(len(newer), 1)
            self.assertNotIn("turn_state", json.loads(newer[0].read_text()))

            observe("prompt", {"session_id": "another-session", "prompt": "ignored"},
                    {**env, "TMUX_PANE": ""})
            self.assertEqual(len(list(state_dir.glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
