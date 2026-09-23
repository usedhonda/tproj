#!/usr/bin/env python3
"""Focused safety tests for the initially unactivated Claude poke sender."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


SENDER = Path(__file__).resolve().parents[1] / "tproj-cc-poke"


class CCPokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bin = root / "bin"
        self.bin.mkdir()
        self.state = root / "state"
        self.state.mkdir()
        self.log = root / "tmux.log"
        tmux = self.bin / "tmux"
        tmux.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            " display-message) printf '%%2|/dev/ttys999|0|111|claude-p1|demo|test-session\\n' ;;\n"
            " capture-pane) printf 'old output\\n❯\\n' ;;\n"
            " send-keys) printf '%s\\n' \"$*\" >> \"$TMUX_LOG\" ;;\n"
            " *) exit 1 ;;\n"
            "esac\n"
        )
        tmux.chmod(0o700)
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "TMUX_LOG": str(self.log), "TPROJ_CC_CACHE_DIR": str(self.state),
                    "TMUX_PANE": "%2"}

    def tearDown(self):
        self.tmp.cleanup()

    def write_state(self, **changes):
        now = int(time.time())
        state = {
            "session_id": "session-1", "pane_id": "%2", "tty": "/dev/ttys999",
            "pane_pid": 111, "role": "claude-p1", "alias": "demo",
            "owner_session": "test-session", "turn_state": "idle_notified",
            "cache_expires_at": now + 300, "idle_prompt_at": now - 10,
            "last_user_prompt_at": now - 70,
        }
        state.update(changes)
        path = self.state / (hashlib.sha256(b"session-1").hexdigest() + ".json")
        path.write_text(json.dumps(state))

    def run_sender(self):
        return subprocess.run(["python3", str(SENDER), "session-1"], env=self.env,
                              text=True, capture_output=True)

    def test_sends_once_and_atomic_expiry_lock_deduplicates(self):
        self.write_state()
        first = self.run_sender()
        second = self.run_sender()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("already claimed", second.stderr)
        self.assertEqual(self.log.read_text().count("send-keys"), 2)

    def test_stop_or_question_or_stale_prompt_refuses_without_send(self):
        for changes in ({"turn_state": "stop_seen"}, {"last_user_prompt_at": int(time.time()) - 901}):
            with self.subTest(changes=changes):
                self.write_state(**changes)
                result = self.run_sender()
                self.assertNotEqual(result.returncode, 0)
        fake = self.bin / "tmux"
        fake.write_text(fake.read_text().replace("old output\\n❯", "permission required\\n❯"))
        self.write_state()
        result = self.run_sender()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
