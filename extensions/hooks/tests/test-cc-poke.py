#!/usr/bin/env python3
"""Focused safety tests for the initially unactivated Claude poke sender."""

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import contextlib
from unittest import mock
import sys
import tempfile
import time
import unittest


SENDER = Path(__file__).resolve().parents[1] / "tproj-cc-poke"
loader = importlib.machinery.SourceFileLoader("tproj_cc_poke_tested", str(SENDER))
spec = importlib.util.spec_from_loader(loader.name, loader)
sender = importlib.util.module_from_spec(spec)
loader.exec_module(sender)


class CCPokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bin = root / "bin"
        self.bin.mkdir()
        self.state = root / "state"
        self.state.mkdir()
        self.locks = root / "shared-locks"
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
            "version": 1,
            "session_id": "session-1", "pane_id": "%2", "tty": "/dev/ttys999",
            "pane_pid": 111, "role": "claude-p1", "alias": "demo",
            "owner_session": "test-session", "turn_state": "idle_notified",
            "agent_pid": 222, "agent_pid_start": 1234567890,
            "cache_expires_at": now + 300, "idle_prompt_at": now - 10,
            "last_user_prompt_at": now - 70,
        }
        state.update(changes)
        self.expiry = state["cache_expires_at"]
        path = self.state / (hashlib.sha256(b"session-1").hexdigest() + ".json")
        path.write_text(json.dumps(state))

    def run_sender(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch.object(sys, "argv", [str(SENDER), "session-1"]), \
             mock.patch.object(sender, "agent_binding", return_value={"agent_pid": 222, "agent_pid_start": 1234567890}), \
             mock.patch.object(sender, "lock_dir", return_value=self.locks), \
             contextlib.redirect_stderr(stderr):
            code = sender.main()
        return code, stderr.getvalue()

    def test_sends_once_and_atomic_expiry_lock_deduplicates(self):
        self.write_state()
        first = self.run_sender()
        second = self.run_sender()
        self.assertEqual(first[0], 0, first[1])
        self.assertNotEqual(second[0], 0)
        self.assertIn("already claimed", second[1])
        self.assertTrue((self.locks / f"session-1-{self.expiry}").is_file())
        self.assertEqual(self.log.read_text().count("send-keys"), 2)

    def test_existing_ccstatusbar_claim_prevents_duplicate_send(self):
        self.write_state()
        self.locks.mkdir()
        (self.locks / f"session-1-{self.expiry}").touch()
        result = self.run_sender()
        self.assertNotEqual(result[0], 0)
        self.assertIn("already claimed", result[1])
        self.assertFalse(self.log.exists())

    def test_stop_or_question_or_stale_prompt_refuses_without_send(self):
        for changes in ({"turn_state": "stop_seen"}, {"last_user_prompt_at": int(time.time()) - 901}):
            with self.subTest(changes=changes):
                self.write_state(**changes)
                result = self.run_sender()
                self.assertNotEqual(result[0], 0)
        fake = self.bin / "tmux"
        fake.write_text(fake.read_text().replace("old output\\n❯", "permission required\\n❯"))
        self.write_state()
        result = self.run_sender()
        self.assertNotEqual(result[0], 0)
        self.assertFalse(self.log.exists())

    def test_draft_and_unknown_cache_version_refuse_without_send(self):
        self.write_state()
        fake = self.bin / "tmux"
        fake.write_text(fake.read_text().replace("old output\\n❯", "old output\\n❯ draft"))
        result = self.run_sender()
        self.assertNotEqual(result[0], 0)
        self.assertFalse(self.log.exists())

        fake.write_text(fake.read_text().replace("❯ draft", "❯"))
        self.write_state(version=2)
        result = self.run_sender()
        self.assertNotEqual(result[0], 0)
        self.assertIn("unknown cache version", result[1])
        self.assertFalse(self.log.exists())

    def test_old_agent_binding_cannot_send_to_new_or_missing_agent(self):
        self.write_state(agent_pid=333)
        result = self.run_sender()
        self.assertNotEqual(result[0], 0)
        self.assertIn("agent_pid incarnation mismatch", result[1])
        self.assertFalse(self.log.exists())
        self.write_state(agent_pid=222)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(sys, "argv", [str(SENDER), "session-1"]), \
             mock.patch.object(sender, "agent_binding", return_value=None), contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(sender.main(), 0)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
