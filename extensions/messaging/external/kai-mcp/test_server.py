import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("kai_mcp_server", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class MCPServerTest(unittest.TestCase):
    def test_initialize_and_tools_list_expose_contract_catalog(self):
        instance = server.MCPServer()
        initialized = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(initialized["result"]["protocolVersion"], server.PROTOCOL_VERSION)
        listed = instance.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual({tool["name"] for tool in listed["result"]["tools"]}, server.TOOL_NAMES)
        self.assertTrue(all("inputSchema" in tool and "annotations" in tool for tool in listed["result"]["tools"]))

    def test_default_call_fails_closed_without_host_access(self):
        response = server.MCPServer().handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                               "params": {"name": "tproj_inbox", "arguments": {}}})
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["error"]["code"], "identity_rejected")

    def test_injected_tools_are_called_and_structured_result_returned(self):
        class FakeTools:
            def dispatch(self, name, arguments):
                self.seen = (name, arguments)
                return {"participants": []}

        fake = FakeTools()
        response = server.MCPServer(fake).handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                                  "params": {"name": "tproj_list", "arguments": {}}})
        self.assertEqual(response["result"]["structuredContent"], {"participants": []})
        self.assertEqual(fake.seen, ("tproj_list", {}))

    def test_stdio_reports_parse_error_and_suppresses_notifications(self):
        output = StringIO()
        server.run_stdio(server.MCPServer(), StringIO("not-json\n{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n"), output)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
