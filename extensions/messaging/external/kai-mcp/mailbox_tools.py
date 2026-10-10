"""Inert KAI MCP mailbox adapter.

The module is deliberately not an MCP server or a service launcher.  A caller
must inject a trusted host-side authorizer and a host RPC function.  Until the
authorizer can prove the cloud conversation binding, every operation therefore
fails closed before a host socket is touched.
"""
from __future__ import annotations

import json
import re
import socket
from typing import Any, Callable, Mapping

MAX_LIMIT = 100
WIRE_LIMIT = 262_144
CANCELLED_STATES = frozenset(("cancelled", "canceled", "expired", "terminal", "rejected", "stale_session"))
# Project aliases may contain Unicode and internal dots, matching the hub's
# qualified address contract. Enrolled service addresses use a conservative
# ASCII token.
# In both cases the trusted authorization result remains the source of truth.
PROJECT_ADDRESS_RE = re.compile(r"^[^/\s]+\.(?:cc|cdx)$")
SERVICE_ADDRESS_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]*)(?:\.[A-Za-z0-9](?:[A-Za-z0-9_-]*)*)*$")
SHORTCUT_TARGETS = frozenset(("cc", "cdx"))
ID_RE = re.compile(r"^[^\s]+$")
FORBIDDEN_SELECTORS = {"role", "as", "session", "conversation", "conversation_id", "endpoint_id", "pid", "host"}


class MailboxToolError(Exception):
    """Structured adapter error retaining the host contract's error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def disconnected_capabilities() -> dict[str, Any]:
    return {"catalog": "tools_present", "connection": "not_configured",
            "binding": "authentication_required", "messaging": "unavailable",
            "conversation_isolation": "not_configured",
            "automatic_resumption": "unverified", "operation": "not_attempted"}


def socket_rpc(socket_path: str, request: Mapping[str, Any]) -> Any:
    """Call one local host request; no credentials are read by this helper."""
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(12)
            sock.connect(socket_path)
            sock.sendall((json.dumps(dict(request), ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            with sock.makefile("rb") as stream:
                raw = stream.readline(WIRE_LIMIT + 1)
    except OSError as exc:
        raise MailboxToolError("unavailable", f"host unavailable: {exc}") from exc
    if len(raw) > WIRE_LIMIT or not raw.endswith(b"\n"):
        raise MailboxToolError("unavailable", "invalid host response")
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise MailboxToolError("unavailable", "invalid host response") from exc
    if not response.get("ok"):
        error = response.get("error") or {}
        raise MailboxToolError(error.get("code", "unavailable"), error.get("message", "host unavailable"))
    return response.get("result")


class MailboxTools:
    """Dispatcher for the seven reviewed tools.

    ``authorizer`` is mandatory and must return a mapping containing a
    trusted ``allowed_addresses`` sequence.  Its result is not caller input:
    it is produced by the host-side conversation binding.  ``host_call`` is
    normally a ``socket_rpc`` partial; tests inject a recorder.
    """

    TOOLS = ("tproj_capabilities", "tproj_list", "tproj_status", "tproj_send", "tproj_inbox", "tproj_message", "tproj_reply", "tproj_ack",
             "tproj_repo_list", "tproj_repo_tree", "tproj_repo_read", "tproj_repo_search",
             "tproj_repo_write", "tproj_repo_revert")

    # Read-only repository tools: tool -> (host op, required fields, optional fields).
    # Only these fields reach the host; the host's owner-local grants decide access.
    REPO_TOOLS = {
        "tproj_repo_list": ("service_repo_list", set(), set()),
        "tproj_repo_tree": ("service_repo_tree", {"repo_id"}, {"path", "depth", "limit", "cursor", "snapshot_id"}),
        "tproj_repo_read": ("service_repo_read", {"repo_id", "path"}, {"start", "end", "max_bytes", "snapshot_id"}),
        "tproj_repo_search": ("service_repo_search", {"repo_id", "pattern"},
                              {"path", "mode", "case_sensitive", "glob_include", "glob_exclude", "context", "limit",
                               "cursor", "snapshot_id"}),
        # Write class: the owner's host still needs an explicit write grant, so these return not_granted otherwise.
        "tproj_repo_write": ("service_repo_write", {"repo_id", "patch_id", "changes"}, {"dry_run"}),
        "tproj_repo_revert": ("service_repo_revert", {"repo_id", "patch_id"}, set()),
    }

    def __init__(self, *, service_id: str, service_address: str, service_token: str,
                 authorizer: Callable[[str, Mapping[str, Any]], Mapping[str, Any] | None] | None,
                 host_call: Callable[[Mapping[str, Any]], Any]):
        self.service_id = service_id
        self.service_address = service_address
        self.service_token = service_token
        self.authorizer = authorizer
        self.host_call = host_call

    def dispatch(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        if name not in self.TOOLS:
            raise MailboxToolError("unknown_tool", "unsupported mailbox tool")
        if FORBIDDEN_SELECTORS.intersection(args):
            raise MailboxToolError("identity_rejected", "identity selectors are not tool arguments")
        if name == "tproj_capabilities":
            if args:
                raise MailboxToolError("invalid_request", "capabilities takes no arguments")
            return self.capabilities()
        ctx = self._authorize(name, args)
        if name in self.REPO_TOOLS:
            return self._repo(name, args)
        if name == "tproj_list": return self._list(args, ctx)
        if name == "tproj_status": return self._status(args, ctx)
        if name == "tproj_send": return self._send(args, ctx)
        if name == "tproj_inbox": return self._inbox(args, ctx)
        if name == "tproj_message": return self._message(args, ctx)
        if name == "tproj_reply": return self._reply(args, ctx)
        return self._ack(args, ctx)

    def capabilities(self) -> dict[str, Any]:
        """Diagnose the attested connection without reading a mailbox or secrets.

        Fixed service enrollment must never be advertised as isolated cloud
        conversation authority. An authorization failure has an unknown cause
        unless the trusted boundary supplies more precise evidence.
        """
        result = disconnected_capabilities()
        if not callable(self.authorizer):
            return result
        try:
            ctx = self._authorize("tproj_capabilities", {})
        except MailboxToolError:
            result.update(binding="authorization_unavailable", connection="unknown")
            return result
        result.update(connection="available", binding="service_principal_valid",
                      messaging="available_for_enrolled_service")
        return result

    def _authorize(self, name: str, args: Mapping[str, Any]) -> Mapping[str, Any]:
        if not callable(self.authorizer):
            raise MailboxToolError("identity_rejected", "trusted conversation authorizer required")
        try:
            result = self.authorizer(name, args)
        except Exception as exc:
            raise MailboxToolError("identity_rejected", "trusted conversation authorization failed") from exc
        if not isinstance(result, Mapping):
            raise MailboxToolError("identity_rejected", "trusted conversation authorization rejected")
        addresses = result.get("allowed_addresses")
        if not isinstance(addresses, (list, tuple, set)) or not addresses or not all(isinstance(x, str) for x in addresses):
            raise MailboxToolError("identity_rejected", "authorized participant scope is required")
        return result

    @staticmethod
    def _keys(args: Mapping[str, Any], required: set[str], optional: set[str] = set()) -> None:
        if set(args) - required - optional:
            raise MailboxToolError("invalid_request", "unexpected tool arguments")
        if not required.issubset(args):
            raise MailboxToolError("invalid_request", "required tool argument missing")

    @staticmethod
    def _id(value: Any, label: str = "message ID", max_len: int = 128) -> str:
        if not isinstance(value, str) or not value or len(value) > max_len or not ID_RE.match(value):
            raise MailboxToolError("invalid_message", f"invalid {label}")
        return value

    @staticmethod
    def _body(value: Any) -> str:
        if not isinstance(value, str):
            raise MailboxToolError("invalid_message", "body must be text")
        if any(ord(c) < 32 and c not in "\n\t" for c in value) or "\x7f" in value:
            raise MailboxToolError("invalid_message", "terminal control characters are forbidden")
        return value

    @staticmethod
    def _target(args: Mapping[str, Any], ctx: Mapping[str, Any]) -> str:
        value = args.get("target")
        malformed = (not isinstance(value, str) or value in SHORTCUT_TARGETS
                     or any(ord(char) < 32 or ord(char) == 127 for char in value)
                     or not (PROJECT_ADDRESS_RE.fullmatch(value) or SERVICE_ADDRESS_RE.fullmatch(value)))
        if malformed:
            raise MailboxToolError("unknown_target", "valid authorized target required")
        if value not in set(ctx["allowed_addresses"]):
            raise MailboxToolError("unknown_target", "target is outside authorized catalog")
        return value

    def _host(self, op: str, **extra: Any) -> Any:
        request = {"op": op, "service_id": self.service_id, "service_token": self.service_token,
                   "address": self.service_address, **extra}
        try:
            return self.host_call(request)
        except MailboxToolError:
            raise
        except Exception as exc:
            # Preserve structured host reasons for embedders that expose a
            # typed RPC exception rather than going through socket_rpc.
            code = getattr(exc, "code", None)
            message = getattr(exc, "message", None) or str(exc)
            if code:
                raise MailboxToolError(str(code), message) from exc
            raise MailboxToolError("unavailable", "host request failed") from exc

    def _repo(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        op, required, optional = self.REPO_TOOLS[name]
        self._keys(args, required, optional)
        result = self._host(op, **dict(args))
        if not isinstance(result, dict):
            raise MailboxToolError("unavailable", "host returned an invalid repository result")
        out = dict(result)
        # One full copy only (structuredContent). The text channel carries a one-line summary.
        if name == "tproj_repo_list":
            out["_summary"] = "%d readable project(s)" % len(out.get("repos", []))
        elif name in ("tproj_repo_write", "tproj_repo_revert"):
            out["_summary"] = "%s patch %s: %d file(s)%s" % (name[len("tproj_repo_"):], out.get("patch_id", ""), len(out.get("files", [])),
                                                            " (dry run)" if out.get("dry_run") else "")
        else:
            out["_summary"] = "%s %s%s%s" % (name[len("tproj_repo_"):], out.get("cite") or out.get("path") or out.get("repo_id", ""),
                                             " (truncated; see next_cursor)" if out.get("truncated") else "",
                                             "" if out.get("consistent", True) else " (tree changed while reading)")
        return out

    def _list(self, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
        self._keys(args, set())
        allowed = set(ctx["allowed_addresses"])
        result = self._host("list") or {}
        participants = []
        for item in result.get("participants", []):
            if not isinstance(item, Mapping) or item.get("address") not in allowed:
                continue
            participants.append({"address": item["address"], "kind": item.get("kind", "participant"),
                                 "available": bool(item.get("online", item.get("available", False)))})
        return {"participants": participants}

    def _status(self, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
        self._keys(args, {"target"})
        target = self._target(args, ctx)
        result = self._host("status", target=target) or {}
        return {"target": target, "available": bool(result.get("online", result.get("available", False))),
                **({"state": result["state"]} if "state" in result else {})}

    def _send(self, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
        self._keys(args, {"target", "body", "submission_id"})
        target = self._target(args, ctx); body = self._body(args["body"]); sid = self._id(args["submission_id"], "submission ID")
        result = self._host("service_send", target=target, body=body, submission_id=sid) or {}
        return {"message_id": result.get("message_id", sid), "thread_id": result.get("thread_id", sid),
                "state": result.get("state", "queued"), **({"duplicate": bool(result["duplicate"])} if "duplicate" in result else {})}

    def _inbox(self, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
        self._keys(args, set(), {"cursor", "limit"})
        cursor = args.get("cursor", 0); limit = args.get("limit", 100)
        if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
            raise MailboxToolError("invalid_request", "cursor and limit are out of bounds")
        result = self._host("service_inbox", cursor=cursor, limit=limit) or {}
        messages = []
        for item in result.get("messages", []):
            if not isinstance(item, Mapping) or item.get("state") in CANCELLED_STATES:
                continue
            mid = item.get("message_id")
            if not isinstance(mid, str) or not self._begin_present(mid):
                continue
            messages.append(item)
        return {"messages": [self._view(item) for item in messages], "next_cursor": int(result.get("next_cursor", cursor))}

    def _message(self, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
        self._keys(args, {"message_id"}); mid = self._id(args["message_id"])
        item = self._host("service_message", message_id=mid) or {}
        # Query permits either party; inspecting our own outbound record must
        # not claim presentation on behalf of its recipient.
        if item.get("target_address") == self.service_address and not self._begin_present(mid):
            raise MailboxToolError("not_found", "message is no longer available")
        return self._view(item)

    def _begin_present(self, mid: str) -> bool:
        try:
            result = self._host("service_begin_present", message_id=mid) or {}
        except MailboxToolError as exc:
            if exc.code == "presentation_unavailable":
                item = self._host("service_message", message_id=mid) or {}
                return (item.get("target_address") == self.service_address
                        and item.get("state") in ("dispatching", "presented", "uncertain"))
            if exc.code in CANCELLED_STATES or exc.code == "not_found":
                return False
            raise
        return result.get("state", "dispatching") not in CANCELLED_STATES

    def _reply(self, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
        self._keys(args, {"message_id", "body", "submission_id"})
        original = self._id(args["message_id"]); body = self._body(args["body"]); sid = self._id(args["submission_id"], "submission ID")
        result = self._host("service_reply", message_id=original, body=body, submission_id=sid) or {}
        thread = result.get("thread_id")
        if not thread:
            view = self._host("service_message", message_id=original) or {}
            thread = view.get("thread_id", original)
        return {"message_id": result.get("message_id", sid), "thread_id": thread, "in_reply_to": result.get("in_reply_to", original),
                "state": result.get("state", "queued"), **({"duplicate": bool(result["duplicate"])} if "duplicate" in result else {})}

    def _ack(self, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
        self._keys(args, {"message_id"}); mid = self._id(args["message_id"])
        self._host("service_ack", message_id=mid)
        return {"message_id": mid, "state": "presented"}

    @staticmethod
    def _view(item: Mapping[str, Any]) -> dict[str, Any]:
        if item.get("state") in CANCELLED_STATES:
            raise MailboxToolError("not_found", "message is no longer available")
        required = ("message_id", "thread_id", "target_address", "body", "state")
        if any(key not in item for key in required):
            raise MailboxToolError("unavailable", "host returned incomplete message")
        out = {"message_id": item["message_id"], "thread_id": item["thread_id"], "target": item["target_address"],
               "body": item["body"], "state": item["state"]}
        for source, dest in (("in_reply_to", "in_reply_to"), ("sender_address", "sender_address")):
            if item.get(source) is not None: out[dest] = item[source]
        return out
