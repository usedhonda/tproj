#!/usr/bin/env python3
import json, os, socket, tempfile, threading, unittest, sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from extensions.messaging.unified import cli


class CliTest(unittest.TestCase):
    def test_inbox_forwards_cursor_and_limit_for_next_page(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); sock_path = root / "mailbox.sock"; cfg = root / "config.json"
            server = socket.socket(socket.AF_UNIX); server.bind(str(sock_path)); server.listen(1)
            def serve():
                conn, _ = server.accept()
                with conn, conn.makefile("rwb") as stream:
                    request = json.loads(stream.readline())
                    self.assertEqual(request["op"], "inbox")
                    self.assertEqual(request["cursor"], 100)
                    self.assertEqual(request["limit"], 100)
                    stream.write(b'{"ok":true,"result":{"messages":[],"next_cursor":200}}\n'); stream.flush()
                server.close()
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            cfg.write_text(json.dumps({"socket": str(sock_path)}))
            with patch.object(cli, "DEFAULT_CONFIG", cfg):
                self.assertEqual(cli.main(["inbox", "--cursor", "100", "--limit", "100"]), 0)
            thread.join(1)

    def test_relative_status_resolves_configured_project(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); sock_path = root / "mailbox.sock"; cfg = root / "config.json"
            server = socket.socket(socket.AF_UNIX); server.bind(str(sock_path)); server.listen(1)
            def serve():
                conn, _ = server.accept()
                with conn, conn.makefile("rwb") as stream:
                    request = json.loads(stream.readline())
                    self.assertEqual(request, {"op": "status", "target": "cdx", "session": None, "as": None})
                    stream.write(json.dumps({"ok": True, "result": {"address": "proj.cdx", "online": True}}).encode() + b"\n"); stream.flush()
                server.close()
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            cfg.write_text(json.dumps({"socket": str(sock_path)}))
            with patch.object(cli, "DEFAULT_CONFIG", cfg):
                self.assertEqual(cli.main(["--status", "cdx", "--json"]), 0)
            thread.join(1)

    def test_stdin_persists_submission_before_fake_uds_request_and_retry_reuses_id(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); sock_path = root / "mailbox.sock"; spool = root / "spool.json"; seen = []
            server = socket.socket(socket.AF_UNIX); server.bind(str(sock_path)); server.listen(4)
            def serve():
                for _ in range(2):
                    conn, _ = server.accept()
                    with conn, conn.makefile("rwb") as stream:
                        req = json.loads(stream.readline()); seen.append(req)
                        stream.write(b'{"ok":true,"result":{"message_id":"accepted"}}\n'); stream.flush()
                server.close()
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            cfg = root / "config.json"; cfg.write_text(json.dumps({"socket": str(sock_path)}))
            with patch.object(cli, "DEFAULT_SPOOL", spool), patch.object(cli, "DEFAULT_CONFIG", cfg), patch("sys.stdin", new=__import__("io").StringIO("hello `world`\n")):
                self.assertEqual(cli.main(["proj.cc", "--stdin"]), 0)
            first = seen[0]["submission_id"]
            self.assertEqual(json.loads(spool.read_text())[first]["body"], "hello `world`\n")
            with patch.object(cli, "DEFAULT_SPOOL", spool), patch.object(cli, "DEFAULT_CONFIG", cfg):
                self.assertEqual(cli.main(["--retry", first]), 0)
            self.assertEqual(seen[1]["submission_id"], first)
            thread.join(1)

    def test_missing_config_is_explicit(self):
        with patch.object(cli, "DEFAULT_CONFIG", Path("/definitely/missing/msg-client.json")):
            self.assertEqual(cli.main(["proj.cc", "hello"]), 2)


if __name__ == "__main__": unittest.main()
