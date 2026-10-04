#!/usr/bin/env python3
"""Thin client for the unified tproj host-agent mailbox."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import uuid

try:
    from .identity import native_conversation_context
except ImportError:
    from identity import native_conversation_context

WIRE_LIMIT = 262144
DEFAULT_CONFIG = Path.home() / ".config/tproj/msg-client.json"
DEFAULT_SPOOL = Path.home() / ".local/state/tproj-msg-unified/submissions.json"


class ClientError(Exception):
    def __init__(self, message, code="unavailable"):
        super().__init__(message)
        self.code = code


def config(path: Path | None = None) -> dict:
    path = path or DEFAULT_CONFIG
    if not path.is_file():
        raise ClientError("unified messaging not configured")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClientError(f"invalid unified messaging config: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("socket"), str) or not value["socket"].strip():
        raise ClientError("invalid unified messaging config: socket is required")
    return value


def rpc(socket_path: str, request: dict) -> object:
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(15)
            sock.connect(socket_path)
            sock.sendall((json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            with sock.makefile("rb") as stream:
                raw = stream.readline(WIRE_LIMIT + 1)
    except OSError as exc:
        raise ClientError(f"unified messaging unavailable: {exc}") from exc
    if len(raw) > WIRE_LIMIT or not raw.endswith(b"\n"):
        raise ClientError("invalid host response")
    try:
        response = json.loads(raw)
    except ValueError as exc:
        raise ClientError("invalid host response") from exc
    if not response.get("ok"):
        error = response.get("error", {})
        raise ClientError(error.get("message", "host unavailable"), error.get("code", "unavailable"))
    return response.get("result")


def read_spool(path: Path | None = None) -> dict:
    path = path or DEFAULT_SPOOL
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClientError(f"submission spool unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ClientError("submission spool unreadable")
    return value


def write_spool(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw_path, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dir_fd)
        finally: os.close(dir_fd)
    finally:
        if os.path.exists(raw_path): os.unlink(raw_path)


def submission(request: dict, *, spool: Path | None = None, retry: str | None = None) -> object:
    spool = spool or DEFAULT_SPOOL
    spool.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(str(spool)+".lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = read_spool(spool)
        if retry:
            prior = saved.get(retry)
            if not isinstance(prior, dict):
                raise ClientError(f"unknown submission ID: {retry}")
            # Keep the durable message ID and body, but rebind the caller to
            # the currently active native conversation after a restart.
            request = dict(prior)
            context = native_conversation_context()
            if context:
                request["conversation"] = context
        else:
            mid = str(request.get("submission_id") or uuid.uuid4())
            request = dict(request, submission_id=mid)
            saved[mid] = request
            write_spool(spool, saved)
    finally:
        lock.close()
    return request, saved


_WHERE_NOTE = {
    "this_mac": "this Mac: waiting for the recipient to be idle with no draft",
    "other_mac": "another Mac: state re-checked on that Mac",
    "service": "service: state re-checked on its side; a service shows as read only after it acks",
}


def _age(seconds: int) -> str:
    if seconds < 90: return f"{seconds}s"
    if seconds < 5400: return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def format_pending(result: dict) -> str:
    groups = result.get("groups", [])
    if not groups:
        return "nothing pending: every message you sent in the last 7 days has reached a final state"
    lines = [f"{result.get('total', 0)} sent message(s) not presented yet (oldest first):"]
    for group in groups:
        states = ", ".join(f"{name}={count}" for name, count in sorted(group["states"].items()))
        extra = f"  ({group['unchecked']} not re-checked on the owning side)" if group.get('unchecked') else ""
        lines.append(f"  {group['target']:<18} {group['count']:>3} msg  oldest {_age(group['oldest_age_s']):>7}  [{states}]{extra}")
        lines.append(f"      {_WHERE_NOTE.get(group['where'], group['where'])}")
        lines.append(f"      oldest id {group['oldest_message_id']}")
    lines.append("Read-only. Nothing was resent; resending creates a duplicate.")
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tproj-msg-unified", epilog="diagnose MESSAGE_ID: read-only delivery metadata for a party or configured maintenance operator; never resends")
    p.add_argument("target", nargs="?")
    p.add_argument("body", nargs="?")
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--session")
    p.add_argument("--as", dest="claimed_alias")
    p.add_argument("--retry", metavar="SUBMISSION_ID")
    p.add_argument("--cursor", type=int, default=0)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--list", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def _caller_request(op: str, **kwargs) -> dict:
    request = dict(kwargs, op=op)
    context = native_conversation_context()
    if context:
        request["conversation"] = context
    return request


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        cfg = config()
        if args.retry:
            req, _ = submission({}, retry=args.retry)
            result = rpc(cfg["socket"], req)
        elif args.list or args.status:
            request = {"op": "list" if args.list else "status"}
            if args.status:
                request.update(target=args.target, session=args.session, **{"as": args.claimed_alias})
                context = native_conversation_context()
                if context:
                    request["conversation"] = context
            result = rpc(cfg["socket"], request)
        elif args.target in ("whoami", "doctor"):
            result = rpc(cfg["socket"], _caller_request(args.target, session=args.session, **{"as": args.claimed_alias}))
        elif args.target == "cancel":
            if not args.body: raise ClientError("cancel requires message ID")
            result = rpc(cfg["socket"], _caller_request("cancel", message_id=args.body, session=args.session, **{"as": args.claimed_alias}))
        elif args.target == "retry-event":
            if not args.body: raise ClientError("retry-event requires message ID")
            result = rpc(cfg["socket"], _caller_request("retry_event", message_id=args.body,
                                                        session=args.session, **{"as": args.claimed_alias}))
        elif args.target == "pending":
            result = rpc(cfg["socket"], _caller_request("pending", session=args.session, **{"as": args.claimed_alias}))
            if not args.json:
                print(format_pending(result))
                return 0
        elif args.target == "directory":
            result = rpc(cfg["socket"], {"op": "directory"})
        elif args.target == "directory-sync":
            if not args.stdin: raise ClientError("directory-sync requires --stdin")
            data = json.load(sys.stdin)
            result = rpc(cfg["socket"], dict(data, op="directory-sync"))
        elif args.target == "reply":
            if not args.body: raise ClientError("reply requires message ID")
            body = sys.stdin.read() if args.stdin else ""
            if not args.stdin: raise ClientError("reply requires --stdin")
            req = _caller_request("reply", message_id=args.body, body=body, session=args.session, **{"as": args.claimed_alias})
            req, _ = submission(req, retry=args.retry)
            result = rpc(cfg["socket"], req)
        elif args.target == "inbox":
            if args.cursor < 0 or args.limit <= 0:
                raise ClientError("inbox cursor must be non-negative and limit must be positive", "invalid_argument")
            result = rpc(cfg["socket"], _caller_request("inbox", session=args.session, **{"as": args.claimed_alias},
                                                        cursor=args.cursor, limit=args.limit))
        elif args.target in ("message", "ack", "diagnose"):
            if not args.body: raise ClientError("message requires message ID")
            result = rpc(cfg["socket"], _caller_request(args.target, message_id=args.body, session=args.session,
                                                        **{"as": args.claimed_alias}))
        else:
            if not args.target: raise ClientError("target is required")
            body = sys.stdin.read() if args.stdin else (args.body or "")
            if not body: raise ClientError("message body is required")
            req = _caller_request("send", target=args.target, body=body, session=args.session,
                                  **{"as": args.claimed_alias})
            req, _ = submission(req, retry=args.retry)
            result = rpc(cfg["socket"], req)
        if args.json or args.target in ("inbox", "message", "directory"):
            print(json.dumps(result, ensure_ascii=False))
        elif isinstance(result, dict) and "participants" in result:
            for participant in result["participants"]:
                print(participant["address"] + " " + ("online" if participant["online"] else "offline"))
        else:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except ClientError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}), file=sys.stderr)
        else:
            print(exc.code + ": " + str(exc), file=sys.stderr)
        if "req" in locals() and req.get("submission_id"):
            print("Submission ID: " + req["submission_id"] + "; query it or retry this ID only", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
