import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
import sys
import io
import os
from contextlib import redirect_stdout
from importlib.machinery import SourceFileLoader
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unified"))
spec = importlib.util.spec_from_file_location("inbox_notice", ROOT / "unified/inbox_notice.py")
notice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notice)


class InboxNoticeTest(unittest.TestCase):
    def test_codex_posttool_notice_uses_hook_specific_output_shape(self):
        guard = SourceFileLoader("completion_guard", str(Path(__file__).resolve().parents[2] / "hooks/tproj-completion-guard")).load_module()
        with tempfile.TemporaryDirectory() as raw:
            helper = Path(raw) / "helper.py"
            helper.write_text("print('{\"additionalContext\":\"Pending message metadata\"}')\n")
            out = io.StringIO()
            with patch.dict(os.environ, {"TPROJ_INBOX_NOTICE_HELPER": str(helper)}), redirect_stdout(out):
                guard.emit_inbox_notice({}, "codex")
            rendered = json.loads(out.getvalue())
            self.assertEqual(rendered["hookSpecificOutput"]["hookEventName"], "PostToolUse")
            self.assertEqual(rendered["hookSpecificOutput"]["additionalContext"], "Pending message metadata")

    def test_exact_id_dedup_is_native_scoped_and_metadata_only(self):
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw) / "notice.json"
            payload = {"thread_id": "native-a"}
            result = {"messages": [{"message_id": "m1", "sender_address": "kai.cdx", "body": "secret"}]}
            with patch.object(notice, "_state_path", return_value=state), \
                 patch.object(notice, "_config", return_value={"socket": "/tmp/unused"}), \
                 patch.object(notice, "_rpc", return_value=result), \
                 patch.object(notice, "_native", return_value=payload):
                first = notice.notice(payload)
                second = notice.notice(payload)
            self.assertIn("m1", first)
            self.assertNotIn("secret", first)
            self.assertEqual(second, "")
            entry = json.loads(state.read_text())[json.dumps(payload, sort_keys=True, separators=(",", ":"))]
            self.assertEqual(entry["seen"], ["m1"])

    def test_cursor_advances_past_deduped_rows_and_migrates_legacy_state(self):
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw) / "notice.json"
            payload = {"thread_id": "native-a"}
            key = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            state.write_text(json.dumps({key: ["m1"]}))
            with patch.object(notice, "_state_path", return_value=state), \
                 patch.object(notice, "_config", return_value={"socket": "/tmp/unused"}), \
                 patch.object(notice, "_rpc", return_value={"messages": [{"message_id": "m1"}], "next_cursor": 9}), \
                 patch.object(notice, "_native", return_value=payload):
                self.assertEqual(notice.notice(payload), "")
            entry = json.loads(state.read_text())[key]
            self.assertEqual(entry, {"cursor": 9, "seen": ["m1"]})


if __name__ == "__main__":
    unittest.main()
