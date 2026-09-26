"""Small, dependency-free wire protocol helpers for the unified hub."""
from __future__ import annotations

import json
import socket
from typing import Any, BinaryIO

MAX_BODY = 64 * 1024
MAX_TTL = 24 * 60 * 60
MAX_REQUEST = 256 * 1024


class HubError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def success(result: Any = None) -> dict:
    return {"ok": True, "result": result}


def failure(exc: HubError) -> dict:
    return {"ok": False, "error": {"code": exc.code, "message": exc.message}}


def read_json_lines(stream: BinaryIO):
    while True:
        line = stream.readline(MAX_REQUEST + 1)
        if not line: return
        if not line.strip():
            continue
        if len(line) > MAX_REQUEST:
            raise HubError("invalid_request", "request exceeds limit")
        try:
            value = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HubError("invalid_json", str(exc)) from exc
        if not isinstance(value, dict):
            raise HubError("invalid_request", "request must be a JSON object")
        yield value


def write_json_line(stream: BinaryIO, value: dict) -> None:
    stream.write((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    stream.flush()


def serve_socket(sock: socket.socket, handler) -> None:
    """One bounded request per connection; idle clients cannot hold the broker."""
    while True:
        conn, _ = sock.accept()
        with conn:
            conn.settimeout(2)
            stream = conn.makefile("rwb")
            try:
                for request in read_json_lines(stream):
                    try:
                        write_json_line(stream, success(handler(request)))
                    except HubError as exc:
                        write_json_line(stream, failure(exc))
                    except Exception:  # never leak internals over RPC
                        write_json_line(stream, failure(HubError("internal", "hub internal error")))
                    break
            except (OSError, HubError, ValueError):
                pass  # malformed or disconnected clients cannot stop the broker
            finally:
                stream.close()
