"""Small, dependency-free wire protocol helpers for the unified hub."""
from __future__ import annotations

import json
import errno
import os
import sqlite3
import socket
import sys
from typing import Any, BinaryIO

MAX_TTL = 24 * 60 * 60
MAX_REQUEST = 256 * 1024
# Native context JSON nests already wire-bounded originals. Response-only limit;
# normal requests, Hub queries and all other client responses stay unchanged.
NATIVE_CONTEXT_LIMIT = 4 * MAX_REQUEST
NATIVE_RUNTIME_CONTRACT = {"host_version": 10, "consumer_version": 4,
                           "context_response_limit": NATIVE_CONTEXT_LIMIT}


RESOURCE_STAGES = frozenset({'local_persistence', 'authority_persistence', 'authority_rpc', 'outcome_query', 'unknown'})


class HubError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        clean = None
        if isinstance(details, dict):
            stage = details.get('failure_stage')
            acceptance = details.get('acceptance')
            if stage in RESOURCE_STAGES and acceptance == 'unknown':
                clean = {'failure_stage': stage, 'acceptance': 'unknown'}
        self.code, self.message, self.details = code, message, clean


def resource_error(exc: BaseException, stage: str = 'unknown') -> HubError | None:
    """Classify only durable-storage exhaustion; never inspect error text."""
    if stage not in RESOURCE_STAGES:
        stage = 'unknown'
    full = isinstance(exc, OSError) and getattr(exc, 'errno', None) in (errno.ENOSPC, errno.EDQUOT)
    if isinstance(exc, sqlite3.Error):
        code = getattr(exc, 'sqlite_errorcode', None)
        full = full or (isinstance(code, int) and (code & 0xff) == sqlite3.SQLITE_FULL)
    if not full:
        return None
    return HubError('resource_exhausted', 'local messaging storage is exhausted',
                    {'failure_stage': stage, 'acceptance': 'unknown'})


def success(result: Any = None) -> dict:
    return {"ok": True, "result": result}


def failure(exc: HubError) -> dict:
    error = {"code": exc.code, "message": exc.message}
    if exc.details:
        error['details'] = dict(exc.details)
    return {"ok": False, "error": error}


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


def _report_internal_error(exc: Exception) -> None:
    """Report locations only; never format exception values or source lines."""
    frames = []
    trace = exc.__traceback__
    while trace is not None:
        frames.append({"file": os.path.basename(trace.tb_frame.f_code.co_filename),
                       "line": trace.tb_lineno})
        trace = trace.tb_next
    try:
        print(json.dumps({"error": "hub_internal_error", "type": type(exc).__name__,
                          "frames": frames}), file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def serve_socket(sock: socket.socket, handler, idle=None, concurrent=False) -> None:
    """One bounded request per connection; idle clients cannot hold the broker."""
    import threading
    slots = threading.BoundedSemaphore(16)
    def handle(conn):
        with conn:
            conn.settimeout(50)
            stream = conn.makefile("rwb")
            try:
                for request in read_json_lines(stream):
                    try: write_json_line(stream, success(handler(request)))
                    except HubError as exc: write_json_line(stream, failure(exc))
                    except Exception as exc:
                        _report_internal_error(exc)
                        classified = resource_error(exc, 'unknown')
                        write_json_line(stream, failure(classified or HubError("internal", "hub internal error")))
                    break
            except (OSError, HubError, ValueError): pass
            finally:
                try:
                    stream.close()
                except OSError:
                    # A disconnected peer can fail the final buffered flush.
                    pass
                finally:
                    if concurrent: slots.release()
    if idle: sock.settimeout(1)
    while True:
        try: conn, _ = sock.accept()
        except socket.timeout:
            try: idle()
            except (OSError, HubError): pass
            continue
        if concurrent:
            if not slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=handle,args=(conn,),daemon=True).start()
        else: handle(conn)
