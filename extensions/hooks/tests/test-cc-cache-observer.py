#!/usr/bin/env python3
"""One focused fixture for Tproj-owned Claude cache observation."""

import json
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


OBSERVER = Path(__file__).resolve().parents[1] / "tproj-cc-cache-observer"
TAP = Path(__file__).resolve().parents[1] / "tproj-cc-statusline-tap"
loader = importlib.machinery.SourceFileLoader("tproj_cc_observer_tested", str(OBSERVER))
spec = importlib.util.spec_from_loader(loader.name, loader)
observer = importlib.util.module_from_spec(spec)
loader.exec_module(observer)
IDENTITY = {"pane_id": "%2", "tty": "/dev/ttys999", "pane_pid": 111,
            "role": "claude-p1", "alias": "demo", "owner_session": "test-session"}
BINDING = {"agent_pid": 222, "agent_pid_start": 1234567890}


class CCCacheObserverTest(unittest.TestCase):
    def test_statusline_tap_preserves_renderer_output_and_observes_copy(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            home_bin = root / "bin"
            home_bin.mkdir()
            fake_observer = home_bin / "tproj-cc-cache-observer"
            fake_observer.write_text("#!/usr/bin/env python3\nimport os, pathlib, sys\npathlib.Path(os.environ['TPROJ_CC_CACHE_DIR']).write_bytes(sys.stdin.buffer.read())\n")
            fake_observer.chmod(0o700)
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
            self.assertEqual((root / "state").read_text(), payload)

    def test_statusline_prompt_and_keepalive_are_scoped_and_private(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            state_dir = root / "state"

            def observe(event, payload):
                with mock.patch.dict(os.environ, {"TPROJ_CC_CACHE_DIR": str(state_dir)}), \
                     mock.patch.object(observer, "agent_binding", return_value=BINDING):
                    observer.record(event, payload, IDENTITY)

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
            self.assertEqual(state["agent_pid"], 222)
            self.assertEqual(state["agent_pid_start"], 1234567890)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertNotIn("private test text", files[0].read_text())
            self.assertNotIn("do-not-store", files[0].read_text())

            previous_prompt_at = state["last_user_prompt_at"]
            observe("prompt", {"session_id": "test-session-id", "prompt": "[keep-alive] ok"})
            self.assertEqual(json.loads(files[0].read_text())["last_user_prompt_at"], previous_prompt_at)
            observe("stop", {"session_id": "test-session-id"})
            self.assertEqual(json.loads(files[0].read_text())["turn_state"], "stop_seen")
            observe("notification", {"session_id": "test-session-id",
                                     "notification_type": "permission_prompt"})
            self.assertEqual(json.loads(files[0].read_text())["turn_state"], "stop_seen")
            observe("notification", {"session_id": "test-session-id",
                                     "notification_type": "idle_prompt"})
            idle_state = json.loads(files[0].read_text())
            self.assertEqual(idle_state["turn_state"], "idle_notified")
            self.assertGreater(idle_state["idle_prompt_at"], 0)
            observe("prompt", {"session_id": "test-session-id", "prompt": "next turn"})
            next_state = json.loads(files[0].read_text())
            self.assertEqual(next_state["turn_state"], "running")
            self.assertNotIn("idle_prompt_at", next_state)
            observe("statusline", {"session_id": "test-session-id", "prompt_cache": {"warm": False}})
            self.assertIsNone(json.loads(files[0].read_text())["cache_expires_at"])

            observe("statusline", {"session_id": "new-session", "prompt_cache": {"warm": True,
                    "expires_at": 2_000_000_002}})
            newer = [file for file in state_dir.glob("*.json") if file != files[0]]
            self.assertEqual(len(newer), 1)
            self.assertNotIn("turn_state", json.loads(newer[0].read_text()))

            # A resumed Claude under the same pane and session must not inherit
            # the previous agent incarnation's idle notification or prompt.
            with mock.patch.dict(os.environ, {"TPROJ_CC_CACHE_DIR": str(state_dir)}), \
                 mock.patch.object(observer, "agent_binding", return_value={"agent_pid": 333,
                                                                            "agent_pid_start": 1234567900}):
                observer.record("statusline", {"session_id": "test-session-id",
                                               "prompt_cache": {"warm": True,
                                                                "expires_at": 2_000_000_003}}, IDENTITY)
            restarted = json.loads(files[0].read_text())
            self.assertEqual(restarted["agent_pid"], 333)
            self.assertNotIn("turn_state", restarted)
            self.assertNotIn("last_user_prompt_at", restarted)

            with mock.patch.dict(os.environ, {"TPROJ_CC_CACHE_DIR": str(state_dir)}), \
                 mock.patch.object(observer, "agent_binding", return_value=None):
                observer.record("prompt", {"session_id": "another-session", "prompt": "ignored"}, IDENTITY)
            self.assertEqual(len(list(state_dir.glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
