#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


OBSERVER = Path(__file__).resolve().parents[1] / "tproj-codex-cache-observer"


class CodexCacheObserverTest(unittest.TestCase):
    def test_records_bound_codex_event_without_inventing_cache_sample(self):
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
                "TPROJ_CODEX_OBSERVER_PROCESS_CHAIN": "900 901 hook-shell;901 902 /usr/bin/codex;902 700 /bin/zsh",
            }
            payload = {"hook_event_name": "UserPromptSubmit", "session_id": "codex-session",
                       "prompt": "do not persist", "transcript_path": "/private/transcript"}
            result = subprocess.run(["python3", str(OBSERVER), "prompt"], input=json.dumps(payload),
                                    text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0)
            files = list((root / "state").glob("*.json"))
            self.assertEqual(len(files), 1)
            state = json.loads(files[0].read_text())
            self.assertFalse(state["sample_available"])
            self.assertIsNone(state["cache_sample"])
            self.assertNotIn("session_id", state)
            self.assertNotIn("do not persist", files[0].read_text())
            self.assertNotIn("transcript", files[0].read_text())

    def test_exact_hook_transcript_yields_numeric_sample_only(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            sessions = root / ".codex" / "sessions"
            sessions.mkdir(parents=True)
            transcript = sessions / "rollout.jsonl"
            transcript.write_text("\n".join(json.dumps(row) for row in (
                {"type": "session_meta", "payload": {"id": "codex-session"}},
                {"type": "event_msg", "timestamp": "2026-09-24T00:00:00Z",
                 "payload": {"type": "token_count", "info": {"last_token_usage": {
                     "input_tokens": 100, "cached_input_tokens": 60}}}},
            )) + "\n")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            tmux = bin_dir / "tmux"
            tmux.write_text("#!/bin/sh\nprintf '%s\\n' '%2|/dev/ttys999|0|700|codex-p1|demo|test-session'\n")
            tmux.chmod(0o700)
            env = {**os.environ, "HOME": str(root), "PATH": f"{bin_dir}:{os.environ['PATH']}",
                   "TMUX_PANE": "%2", "TPROJ_CODEX_CACHE_DIR": str(root / "state"),
                   "TPROJ_CODEX_OBSERVER_PID": "900",
                   "TPROJ_CODEX_OBSERVER_PROCESS_CHAIN": "900 901 hook-shell;901 902 /usr/bin/codex;902 700 /bin/zsh"}
            for session_id in ("wrong-session", "codex-session"):
                payload = {"hook_event_name": "Stop", "session_id": session_id,
                           "transcript_path": str(transcript), "prompt": "secret text"}
                subprocess.run(["python3", str(OBSERVER), "stop"], input=json.dumps(payload),
                               text=True, env=env, check=True)
            states = [json.loads(path.read_text()) for path in (root / "state").glob("*.json")]
            self.assertEqual(len(states), 2)
            self.assertEqual(sum(state["last_token_sample"] is not None for state in states), 1)
            sample = next(state["last_token_sample"] for state in states if state["last_token_sample"])
            self.assertEqual(sample["cached_input_tokens"], 60)
            self.assertNotIn("secret text", json.dumps(states))
            self.assertNotIn(str(transcript), json.dumps(states))

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
                   "TPROJ_CODEX_OBSERVER_PROCESS_CHAIN": "900 901 hook-shell;901 902 /usr/bin/codex;902 700 /bin/zsh"}
            subprocess.run(["python3", str(OBSERVER), "stop"], input=json.dumps({
                "hook_event_name": "Stop", "session_id": "codex-session", "remote": True}),
                text=True, env=env, check=True)
            self.assertFalse((root / "state").exists())


if __name__ == "__main__":
    unittest.main()
