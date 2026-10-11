"""Bounded, metadata-only native PostToolUse inbox notice helper."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import socket
import tempfile
import time

from identity import native_conversation_context
import task_role

WIRE_LIMIT = 262144
TIMEOUT = 0.75
DEFAULT_CONFIG = Path.home() / ".config/tproj/msg-client.json"
DEFAULT_STATE = Path.home() / ".local/state/tproj/inbox-notice.json"


def _config() -> dict:
    try:
        value = json.loads((Path(os.environ.get("TPROJ_MSG_CONFIG", str(DEFAULT_CONFIG)))).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _rpc(path: str, request: dict) -> object:
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(TIMEOUT)
        sock.connect(path)
        sock.sendall((json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        with sock.makefile("rb") as stream:
            raw = stream.readline(WIRE_LIMIT + 1)
    if len(raw) > WIRE_LIMIT or not raw.endswith(b"\n"):
        raise RuntimeError("invalid host response")
    response = json.loads(raw)
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error", {}).get("message", "host unavailable")))
    return response.get("result")


def _native(payload: dict) -> dict:
    value = task_role.native_context(payload)
    env = native_conversation_context()
    for key in ("thread_id", "session_id"):
        if value.get(key) and env.get(key) and value[key] != env[key]:
            raise ValueError("native conversation context conflict")
    merged = dict(env)
    merged.update(value)
    return merged


def _state_path() -> Path:
    return Path(os.environ.get("TPROJ_INBOX_NOTICE_STATE", str(DEFAULT_STATE)))


def _dedup(path: Path, native_key: str, messages: list[dict], next_cursor: object = 0) -> list[dict]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(str(path) + ".lock", "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError):
            state = {}
        entry = state.get(native_key, []) if isinstance(state, dict) else []
        if isinstance(entry, dict):
            seen = entry.get("seen", [])
            try:
                stored_cursor = max(int(entry.get("cursor", 0)), 0)
            except (TypeError, ValueError):
                stored_cursor = 0
        else:
            # Migrate the old native-key -> [message IDs] shape in place.
            seen = entry
            stored_cursor = 0
        seen = [str(item) for item in seen if isinstance(item, str)]
        fresh = [item for item in messages if str(item.get("message_id", "")) not in seen]
        try:
            observed_cursor = max(int(next_cursor or 0), 0)
        except (TypeError, ValueError):
            observed_cursor = 0
        cursor = max(stored_cursor, observed_cursor)
        if fresh or cursor != stored_cursor or not isinstance(entry, dict):
            seen.extend(str(item["message_id"]) for item in fresh if item.get("message_id"))
            state = state if isinstance(state, dict) else {}
            state[native_key] = {"cursor": cursor, "seen": seen[-256:]}
            fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(state, stream, ensure_ascii=False, sort_keys=True)
                    stream.write("\n")
                    stream.flush(); os.fsync(stream.fileno())
                os.chmod(temp, 0o600); os.replace(temp, path)
            finally:
                if os.path.exists(temp): os.unlink(temp)
        return fresh[:3]
    finally:
        lock.close()


def notice(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    native = _native(payload)
    # A cursor is safe only when scoped to native conversation identity.  A
    # missing context could belong to another authenticated endpoint, so fail
    # open instead of sharing a global cursor/dedup bucket.
    if not native:
        return ""
    cfg = _config()
    socket_path = str(cfg.get("socket") or "")
    if not socket_path:
        return ""
    native_key = json.dumps(native, sort_keys=True, separators=(",", ":"))
    state_path = _state_path()
    cursor = 0
    try:
        with open(str(state_path) + ".lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
            entry = state.get(native_key, []) if isinstance(state, dict) else []
            if isinstance(entry, dict):
                cursor = max(int(entry.get("cursor", 0)), 0)
    except (OSError, ValueError, TypeError):
        cursor = 0
    request = {"op": "inbox_notice", "conversation": native, "cursor": cursor}
    result = _rpc(socket_path, request)
    if not isinstance(result, dict):
        return ""
    rows = result.get("messages")
    if not isinstance(rows, list):
        return ""
    fresh = _dedup(state_path, native_key, [row for row in rows if isinstance(row, dict)], result.get("next_cursor", cursor))
    if not fresh:
        return ""
    lines = ["Pending message metadata (read each exact ID with tproj-msg message <ID>):"]
    for row in fresh[:3]:
        sender = str(row.get("sender_address") or "unknown sender")
        lines.append(f"- {sender}: {row.get('message_id')} (state={row.get('state', 'unknown')})")
    return "\n".join(lines)


def main() -> int:
    try:
        payload = json.load(os.fdopen(0))
        text = notice(payload)
        if text:
            print(json.dumps({"additionalContext": text}, ensure_ascii=False))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
