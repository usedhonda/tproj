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
from conversation import ConversationBindingRegistry, ConversationToolResolver, provider_digest


class MCPServerTest(unittest.TestCase):
    def test_capability_diagnosis_never_claims_cloud_isolation_or_reads_mailbox(self):
        request = {"jsonrpc": "2.0", "id": 101, "method": "tools/call",
                   "params": {"name": "tproj_capabilities", "arguments": {}}}
        absent = server.MCPServer().handle(request)["result"]["structuredContent"]
        self.assertEqual(absent["binding"], "authentication_required")
        self.assertEqual(absent["conversation_isolation"], "not_configured")
        calls = []
        tools = server.MailboxTools(service_id="external", service_address="external",
            service_token="private", authorizer=lambda name, args: {"allowed_addresses": ["peer.cc"],
                "principal": "kai-service", "conversation_id": "self-reported"},
            host_call=lambda request: calls.append(request))
        bound = server.MCPServer(tools).handle(request)["result"]["structuredContent"]
        self.assertEqual(bound["binding"], "service_principal_valid")
        self.assertEqual(bound["conversation_isolation"], "not_configured")
        self.assertEqual(bound["operation"], "not_attempted")
        self.assertEqual(calls, [])
        tools.authorizer = lambda *_: (_ for _ in ()).throw(RuntimeError("private detail"))
        failed = server.MCPServer(tools).handle(request)["result"]["structuredContent"]
        self.assertEqual(failed["binding"], "authorization_unavailable")
        self.assertEqual(failed["connection"], "unknown")
        self.assertNotIn("private detail", str(failed))

    def test_initialize_and_tools_list_expose_contract_catalog(self):
        instance = server.MCPServer()
        initialized = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(initialized["result"]["protocolVersion"], server.PROTOCOL_VERSION)
        listed = instance.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual({tool["name"] for tool in listed["result"]["tools"]}, server.TOOL_NAMES)
        self.assertTrue(all("inputSchema" in tool and "annotations" in tool for tool in listed["result"]["tools"]))
        self.assertNotIn("events", initialized["result"]["capabilities"])

    def test_optional_event_dispatcher_adds_capability_only_when_injected(self):
        class Events:
            def definition(self):
                return {"name": "kai.mailbox.message"}

            def subscribe(self, url, secret, ttl_ms=None):
                return {"id": "sub-1"}

        instance = server.MCPServer(events=Events())
        initialized = instance.handle({"jsonrpc": "2.0", "id": 5, "method": "initialize", "params": {}})
        self.assertIn("events", initialized["result"]["capabilities"])
        response = instance.handle({"jsonrpc": "2.0", "id": 6, "method": "events/subscribe", "params": {
            "name": "kai.mailbox.message", "arguments": {},
            "delivery": {"mode": "webhook", "url": "https://example.test/hook", "secret": "hidden"},
        }})
        self.assertEqual(response["result"], {"id": "sub-1"})
        listed = instance.handle({"jsonrpc": "2.0", "id": 7, "method": "events/list", "params": {}})
        self.assertEqual(listed["result"]["events"][0]["name"], "kai.mailbox.message")

    def test_event_subscribe_rejects_resume_cursor_without_adapter_side_effect(self):
        class Events:
            def __init__(self):
                self.calls = 0

            def definition(self):
                return {"name": "kai.mailbox.message"}

            def subscribe(self, url, secret, ttl_ms=None):
                self.calls += 1
                return {"id": "sub-1"}

        events = Events()
        instance = server.MCPServer(events=events)
        base = {
            "jsonrpc": "2.0", "method": "events/subscribe",
            "params": {
                "name": "kai.mailbox.message", "arguments": {},
                "delivery": {"mode": "webhook", "url": "https://example.test/hook", "secret": "hidden"},
            },
        }
        for request_id, cursor in ((10, ""), (11, 7)):
            request = dict(base, id=request_id, params=dict(base["params"], cursor=cursor))
            response = instance.handle(request)
            self.assertEqual(response["error"], {
                "code": -32014,
                "message": "Unsupported data",
                "data": {"feature": "cursor", "reason": "replay_not_supported"},
            })
        self.assertEqual(events.calls, 0)

        null_cursor = dict(base, id=12, params=dict(base["params"], cursor=None))
        response = instance.handle(null_cursor)
        self.assertEqual(response["result"], {"id": "sub-1"})
        self.assertEqual(events.calls, 1)

    def test_event_protocol_negotiates_2026_and_rejects_old_clients(self):
        instance = server.MCPServer(events=object())
        ok = instance.handle({"jsonrpc": "2.0", "id": 8, "method": "initialize",
                              "params": {"protocolVersion": "2026-07-28"}})
        self.assertEqual(ok["result"]["protocolVersion"], "2026-07-28")
        bad = instance.handle({"jsonrpc": "2.0", "id": 9, "method": "initialize",
                               "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(bad["error"]["code"], -32602)

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

    def test_request_resolver_selects_enrolled_tools_and_denial_never_falls_back(self):
        config = {"bindings": [
            {"principal_id": "owner-a", "provider_subject_digest": provider_digest("sub-a"),
             "provider_session_digest": provider_digest("sess-a"), "binding_id": "bind-a",
             "service_id": "svc-a", "address": "a@example", "participant_id": "p-a"},
            {"principal_id": "owner-b", "provider_subject_digest": provider_digest("sub-b"),
             "provider_session_digest": provider_digest("sess-b"), "binding_id": "bind-b",
             "service_id": "svc-b", "address": "b@example", "participant_id": "p-b"},
        ]}
        registry = ConversationBindingRegistry(config)
        attestations = {
            "a": {"principal_id": "owner-a", "provider_subject_digest": provider_digest("sub-a"),
                  "provider_session_digest": provider_digest("sess-a")},
            "b": {"principal_id": "owner-b", "provider_subject_digest": provider_digest("sub-b"),
                  "provider_session_digest": provider_digest("sess-b")},
            "wrong": {"principal_id": "owner-a", "provider_subject_digest": provider_digest("foreign"),
                       "provider_session_digest": provider_digest("sess-a")},
        }
        selected = []
        fixed_calls = []

        class BoundTools:
            def __init__(self, binding):
                self.binding = binding

            def dispatch(self, name, arguments):
                selected.append((self.binding.binding_id, name, dict(arguments)))
                return {"binding": self.binding.binding_id}

        class FixedTools:
            def dispatch(self, name, arguments):
                fixed_calls.append((name, arguments))
                return {"fixed": True}

        def attestor(request):
            value = attestations.get(request.get("id"))
            if value is None:
                raise RuntimeError("no independent attestation")
            return value

        resolver = ConversationToolResolver(registry, attestor, BoundTools)
        instance = server.MCPServer(FixedTools(), conversation_resolver=resolver)
        base = {"jsonrpc": "2.0", "method": "tools/call",
                "params": {"name": "tproj_list", "arguments": {}}}
        for request_id, expected in (("a", "bind-a"), ("b", "bind-b")):
            request = dict(base, id=request_id,
                           params=dict(base["params"], _meta={"principal_id": "spoofed"}))
            response = instance.handle(request)
            self.assertEqual(response["result"]["structuredContent"]["binding"], expected)
        for request_id in ("missing", "wrong", "spoof"):
            request = dict(base, id=request_id,
                           params=dict(base["params"], arguments={"principal_id": "owner-a"},
                                       _meta={"principal_id": "owner-a", "provider_subject_digest": provider_digest("sub-a")}))
            response = instance.handle(request)
            self.assertTrue(response["result"]["isError"])
            self.assertEqual(response["result"]["structuredContent"]["error"]["code"], "identity_rejected")
        self.assertEqual([item[0] for item in selected], ["bind-a", "bind-b"])
        self.assertEqual(fixed_calls, [])

    def test_stdio_reports_parse_error_and_suppresses_notifications(self):
        output = StringIO()
        server.run_stdio(server.MCPServer(), StringIO("not-json\n{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n"), output)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
