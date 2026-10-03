#!/usr/bin/env python3
"""Public client for the authenticated unified task authority.

This module deliberately contains no local task state.  Every operation is an
authenticated request to the unified host, bound to the native conversation
by :mod:`cli`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
from typing import Any

try:
    from . import cli
except ImportError:  # installed launcher executes this file directly
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cli  # type: ignore


TASK_OPS = {"approval", "submit", "status", "list", "ack", "progress", "done",
            "block", "verify", "report", "cancel", "freeze"}
HANDOFF_OPS = {"prepare_handoff", "release_handoff", "accept_handoff", "commit_handoff"}


def _hash(value: Any) -> str:
    if isinstance(value, str) and len(value) == 64:
        return value
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def request(op: str, **fields: Any) -> Any:
    """Send one caller-bound request through the existing unified CLI client."""
    req = cli._caller_request("task_" + op, **fields)
    cfg = cli.config()
    # ``request`` is intentionally the only transport seam; tests and future
    # callers can replace it without introducing an alternate authentication
    # path.
    return cli.rpc(cfg["socket"], req)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tproj-task", description="unified authenticated task authority")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("approval", help="record host-attested direct-user approval")
    a.add_argument("--approval-id", default=None)
    a.add_argument("--intent", required=True)
    a.add_argument("--scope-file", required=True, help="file containing the exact approved scope text")
    a.add_argument("--evidence-hash", required=True)
    s = sub.add_parser("submit", help="submit a task packet")
    s.add_argument("target", nargs="?")
    s.add_argument("--intent", required=True)
    s.add_argument("--scope-file", required=True, help="file containing the approved scope text")
    s.add_argument("--approval", required=True, dest="approval_id")
    s.add_argument("--idempotency-key", default=None)
    s.add_argument("--stdin", action="store_true", help="read packet JSON from stdin")
    for name in ("status", "ack", "progress", "done", "block", "verify", "report", "cancel", "freeze", "detach"):
        q = sub.add_parser(name)
        q.add_argument("task_id")
        q.add_argument("--epoch", type=int, dest="expected_epoch")
        q.add_argument("--data", help="JSON event data")
    sub.add_parser("list")
    h = sub.add_parser("handoff", help="prepare, release, accept, or commit a handoff")
    h.add_argument("action", choices=("prepare", "release", "accept", "commit"))
    h.add_argument("task_id")
    h.add_argument("--epoch", type=int, dest="expected_epoch")
    h.add_argument("--target", help="target project endpoint address")
    h.add_argument("--token")
    return p


def _json_data(raw: str | None) -> Any:
    if raw is None:
        return {}
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise cli.ClientError("data must be valid JSON", "invalid_argument") from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "approval":
            try:
                scope = Path(args.scope_file).read_text(encoding="utf-8")
            except OSError as exc:
                raise cli.ClientError(f"cannot read scope file: {exc}", "invalid_argument") from exc
            result = request("approval", approval_id=args.approval_id or str(uuid.uuid4()),
                             intent=args.intent, scope=scope, evidence_hash=args.evidence_hash)
        elif args.command == "submit":
            if not args.target:
                raise cli.ClientError("submit requires target", "invalid_argument")
            try:
                scope = Path(args.scope_file).read_text(encoding="utf-8")
            except OSError as exc:
                raise cli.ClientError(f"cannot read scope file: {exc}", "invalid_argument") from exc
            packet = json.load(sys.stdin) if args.stdin else {"target": args.target}
            if not isinstance(packet, dict):
                raise cli.ClientError("submit packet must be a JSON object", "invalid_argument")
            packet.setdefault("target", args.target)
            result = request("submit", idempotency_key=args.idempotency_key or str(uuid.uuid4()),
                             intent=args.intent, scope=scope, approval_id=args.approval_id,
                             executor=args.target, payload=packet)
        elif args.command == "list":
            result = request("list")
        elif args.command == "handoff":
            op = {"prepare": "prepare_handoff", "release": "release_handoff",
                  "accept": "accept_handoff", "commit": "commit_handoff"}[args.action]
            fields: dict[str, Any] = {"task_id": args.task_id}
            if args.expected_epoch is not None: fields["expected_epoch"] = args.expected_epoch
            if args.target: fields["target"] = args.target
            if args.token: fields["token"] = args.token
            result = request(op, **fields)
        else:
            fields = {"task_id": args.task_id}
            if args.command != "status" and args.expected_epoch is None:
                raise cli.ClientError(f"{args.command} requires --epoch", "invalid_argument")
            if args.expected_epoch is not None: fields["expected_epoch"] = args.expected_epoch
            if args.data is not None: fields["data"] = _json_data(args.data)
            result = request(args.command, **fields)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (cli.ClientError, ValueError, OSError) as exc:
        code = getattr(exc, "code", "invalid_argument")
        print(f"{code}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
