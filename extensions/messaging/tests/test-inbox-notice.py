import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "unified"))
spec = importlib.util.spec_from_file_location("inbox_notice", ROOT / "unified/inbox_notice.py")
notice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notice)


class InboxNoticeTest(unittest.TestCase):
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
            self.assertEqual(json.loads(state.read_text())[json.dumps(payload, sort_keys=True, separators=(",", ":"))], ["m1"])


if __name__ == "__main__":
    unittest.main()
