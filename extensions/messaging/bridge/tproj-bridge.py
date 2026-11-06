#!/usr/bin/env python3
"""tproj-bridge: a remote inbox that lets a box-hosted Codex join the tproj-msg mesh.

Runs on a Tailscale box (not the Mac). The Mac's ``tproj-msg gate:<id>`` POSTs an
envelope to ``/v1/inbox``; this process runs ``codex exec`` on the box's repo and
POSTs the last message back to ClawGate's ``/v1/tproj-msg-deliver``, which injects
it into the asking pane as ``[from:<reply_as>]`` (default ``<id>.cdx``).

Contract (see docs/reference/bridge-targets.md):

  GET  /v1/health -> {"ok": true, "id": "<id>", "busy": <bool>}
  POST /v1/inbox  <- {"from","to","session","text","trace_id","return_url","reply_as"}
                  -> 202 {"ok": true, "queued": <n>}   (or 4xx/5xx with {"ok": false})
  reply           -> POST {return_url}/v1/tproj-msg-deliver
                     {"session","target"(=from),"text","senderAs"(=reply_as)}

Standard library only, so the box needs nothing but python3 and the codex CLI.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import queue
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple
from urllib.parse import urlsplit

BRIDGE_ID = os.environ.get("TPROJ_BRIDGE_ID", "bot01")
PORT = int(os.environ.get("TPROJ_BRIDGE_PORT", "8765"))
BIND = os.environ.get("TPROJ_BRIDGE_BIND", "0.0.0.0")
REPO = os.environ.get("TPROJ_BRIDGE_REPO", os.getcwd())
CODEX = os.environ.get("TPROJ_BRIDGE_CODEX", "codex")
TIMEOUT_SEC = int(os.environ.get("TPROJ_BRIDGE_TIMEOUT_SEC", "1800"))
# Sandbox policy for the Codex run. The defaults are Codex's own conservative
# ones: writes only inside REPO (its .git/.agents/.codex stay read-only), no
# network. Anything wider is an explicit operator choice on the box, and the
# effective policy is reported on /v1/health so the Mac side can see what a
# live bridge actually runs with rather than guess from a service file.
SANDBOX = os.environ.get("TPROJ_BRIDGE_SANDBOX", "workspace-write")
# Extra writable roots. Both "," and ":" separate entries: a box-local variant of
# this bridge already used commas, and a drop-in replacement that read only
# colons would have turned its two repos into one wrong path without a word.
ADD_DIRS = [d for d in re.split(r"[,:]", os.environ.get("TPROJ_BRIDGE_ADD_DIRS", "")) if d]
# Generic `codex -c key=value` passthrough (comma-separated), honoured for the
# same reason: the box variant set network access through it. Network access is
# true if either the simple switch or a passthrough entry says so, and health
# reports the resolved value, not the spelling.
CODEX_CONFIG = [c for c in os.environ.get("TPROJ_BRIDGE_CODEX_CONFIG", "").split(",") if c.strip()]
NETWORK = os.environ.get("TPROJ_BRIDGE_NETWORK", "0") in ("1", "true", "yes") or any(
    c.replace(" ", "") == "sandbox_workspace_write.network_access=true" for c in CODEX_CONFIG)
if SANDBOX not in ("read-only", "workspace-write", "danger-full-access"):
    raise SystemExit(f"TPROJ_BRIDGE_SANDBOX must be read-only|workspace-write|danger-full-access, got {SANDBOX!r}")
MAX_REPLY_CHARS = int(os.environ.get("TPROJ_BRIDGE_MAX_REPLY_CHARS", "6000"))
MAX_BODY_BYTES = int(os.environ.get("TPROJ_BRIDGE_MAX_BODY_BYTES", str(256 * 1024)))
# Only loopback and the Tailscale CGNAT range may talk to this inbox. That is
# the same rule ClawGate applies on the Mac side, so the two ends of the bridge
# trust exactly the same network.
ALLOW_NETS = [ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128"),
              ipaddress.ip_network("100.64.0.0/10")]

_jobs: "queue.Queue[dict]" = queue.Queue()
_busy = threading.Event()
_seen_trace: dict[str, float] = {}
_seen_lock = threading.Lock()


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%dT%H:%M:%S ") + msg, file=sys.stderr, flush=True)


def ip_allowed(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    return any(ip in net for net in ALLOW_NETS)


class CallbackTarget(NamedTuple):
    scheme: str
    host: str
    port: int
    authority: str
    addresses: tuple


def resolve_callback(url: str) -> CallbackTarget:
    """Validate a callback base and pin all resolved addresses before queuing."""
    if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise ValueError("return_url must be an HTTP(S) base URL")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
        if (parts.scheme not in ("http", "https") or not host
                or parts.username is not None or parts.password is not None
                or parts.path not in ("", "/") or "?" in url or "#" in url
                or "%" in host or parts.netloc.endswith(":")):
            raise ValueError
        host = host.encode("idna").decode("ascii")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("return_url must be an HTTP(S) base URL without credentials, path, query or fragment") from None
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    port = port if port is not None else (443 if parts.scheme == "https" else 80)
    try:
        addresses = tuple(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
    except OSError:
        raise ValueError("return_url host could not be resolved") from None
    if not addresses or any(family not in (socket.AF_INET, socket.AF_INET6) or not ip_allowed(address[0])
                            for family, _, _, _, address in addresses):
        raise ValueError("return_url must resolve only to loopback or Tailscale addresses")
    return CallbackTarget(parts.scheme, host, port, authority, addresses)


class CallbackConnection(http.client.HTTPConnection):
    """Direct HTTP(S) connection to an accepted address, with no proxy or redirect."""
    def __init__(self, target: CallbackTarget, timeout: int):
        super().__init__(target.host, target.port, timeout=timeout)
        self.target = target

    def connect(self) -> None:
        last_error = OSError("no callback address available")
        for family, socktype, proto, _, address in self.target.addresses:
            sock = socket.socket(family, socktype, proto)
            try:
                sock.settimeout(self.timeout)
                sock.connect(address)
                if self.target.scheme == "https":
                    sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.target.host)
                self.sock = sock
                return
            except OSError as exc:
                sock.close()
                last_error = exc
        raise last_error


def seen_before(trace_id: str) -> bool:
    # A retried POST must not run the job twice. Keyed on the sender's
    # trace_id, remembered for an hour.
    now = time.time()
    with _seen_lock:
        for k, t in list(_seen_trace.items()):
            if now - t > 3600:
                del _seen_trace[k]
        if trace_id in _seen_trace:
            return True
        _seen_trace[trace_id] = now
        return False


def run_codex(prompt: str) -> tuple[bool, str]:
    """Run one headless Codex turn on the box repo; return (ok, last_message)."""
    with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as out:
        out_path = out.name
    cmd = [CODEX, "exec", "-C", REPO, "--skip-git-repo-check", "-s", SANDBOX]
    for c in CODEX_CONFIG:
        cmd += ["-c", c.strip()]
    if NETWORK and SANDBOX == "workspace-write" and not any(
            c.replace(" ", "") == "sandbox_workspace_write.network_access=true" for c in CODEX_CONFIG):
        cmd += ["-c", "sandbox_workspace_write.network_access=true"]
    for d in ADD_DIRS:
        cmd += ["--add-dir", d]
    cmd += ["-o", out_path, "-"]
    try:
        proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True,
                              timeout=TIMEOUT_SEC, check=False)
    except FileNotFoundError:
        return False, f"codex not found at {CODEX!r}"
    except subprocess.TimeoutExpired:
        return False, f"codex exec timed out after {TIMEOUT_SEC}s"
    try:
        with open(out_path, encoding="utf-8") as fh:
            last = fh.read().strip()
    except OSError:
        last = ""
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-800:]
        return False, f"codex exec exited {proc.returncode}: {tail}"
    if not last:
        # -o is the contract; fall back to stdout so a box with an older codex
        # still answers something instead of silently replying nothing.
        last = (proc.stdout or "").strip()
    return True, last


def post_json(target: CallbackTarget, payload: dict, timeout: int = 20) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    conn = CallbackConnection(target, timeout)
    try:
        conn.request("POST", "/v1/tproj-msg-deliver", body=data,
                     headers={"Content-Type": "application/json", "Host": target.authority})
        with conn.getresponse() as resp:
            return resp.status, resp.read(500).decode("utf-8", "replace")
    except (http.client.HTTPException, OSError) as exc:
        return 0, str(exc)
    finally:
        conn.close()


def deliver_reply(job: dict, text: str) -> None:
    url = job["return_url"].rstrip("/") + "/v1/tproj-msg-deliver"
    payload = {"session": job["session"], "target": job["from"],
               "text": text[:MAX_REPLY_CHARS], "senderAs": job["reply_as"]}
    for attempt in (1, 2):
        code, body = post_json(job["_callback"], payload)
        if 200 <= code < 300:
            log(f"reply delivered trace={job['trace_id']} -> {job['from']} via {url}")
            return
        log(f"reply delivery attempt {attempt} failed trace={job['trace_id']} code={code} body={body[:200]}")
        time.sleep(2)
    log(f"reply NOT delivered trace={job['trace_id']}; giving up")


def worker() -> None:
    while True:
        job = _jobs.get()
        _busy.set()
        try:
            prompt = f"[from:{job['from']}] {job['text']}"
            log(f"job start trace={job['trace_id']} from={job['from']}")
            ok, text = run_codex(prompt)
            if not ok:
                deliver_reply(job, f"[bridge:{BRIDGE_ID}] Codex could not complete this request: {text}")
            elif not text.strip():
                # A clean run with nothing to say (an FYI, a 返信不要) is a normal
                # outcome, not a fault. Delivering a stub for it made every quiet
                # completion look like a failure in the asking pane.
                log(f"job done with no reply trace={job['trace_id']} (exit 0, empty last message; nothing delivered)")
            else:
                deliver_reply(job, text)
        except Exception as exc:  # never let one job kill the worker
            log(f"job crashed trace={job.get('trace_id')}: {exc!r}")
        finally:
            _busy.clear()
            _jobs.task_done()


class Handler(BaseHTTPRequestHandler):
    server_version = "tproj-bridge/1"

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # quieter default access log
        log("http " + (fmt % args))

    def _client_ok(self) -> bool:
        if ip_allowed(self.client_address[0]):
            return True
        self._send(403, {"ok": False, "error": "source address not allowed (loopback or Tailscale only)"})
        return False

    def do_GET(self) -> None:
        if not self._client_ok():
            return
        if self.path == "/v1/health":
            self._send(200, {"ok": True, "id": BRIDGE_ID, "busy": _busy.is_set(), "queued": _jobs.qsize(),
                             "repo": REPO, "sandbox": SANDBOX, "network": NETWORK, "add_dirs": ADD_DIRS,
                             "codex_config_count": len(CODEX_CONFIG)})
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._client_ok():
            return
        if self.path != "/v1/inbox":
            self._send(404, {"ok": False, "error": "not found"})
            return
        # IP trust must not let a web page turn the user's browser into a CLI.
        if self.headers.get("Origin") is not None:
            self._send(403, {"ok": False, "error": "browser-origin requests are not allowed"})
            return
        if (len(self.headers.get_all("Content-Type", [])) != 1
                or self.headers.get_content_type() != "application/json"):
            self._send(415, {"ok": False, "error": "Content-Type must be application/json"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1
                or not re.fullmatch(r"[0-9]+", lengths[0].strip())):
            self._send(400, {"ok": False, "error": "bad body length"})
            return
        try:
            length = int(lengths[0])
        except ValueError:
            self._send(400, {"ok": False, "error": "bad body length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send(413 if length > MAX_BODY_BYTES else 400, {"ok": False, "error": "bad body length"})
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._send(400, {"ok": False, "error": "incomplete body"})
            return
        try:
            job = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            self._send(400, {"ok": False, "error": "invalid JSON"})
            return
        if not isinstance(job, dict):
            self._send(400, {"ok": False, "error": "JSON object required"})
            return
        required = ("from", "session", "text", "trace_id", "return_url", "reply_as")
        missing = [k for k in required if not isinstance(job.get(k), str) or not job[k].strip()]
        if missing:
            self._send(400, {"ok": False, "error": f"missing fields: {', '.join(missing)}"})
            return
        if job.get("to") not in (None, f"gate:{BRIDGE_ID}"):
            # Two boxes must never be confused: a message addressed to another
            # id is refused here even if it reached this host.
            self._send(409, {"ok": False, "error": f"addressed to {job.get('to')!r}, this bridge is gate:{BRIDGE_ID}"})
            return
        try:
            job["_callback"] = resolve_callback(job["return_url"])
        except ValueError as exc:
            self._send(400, {"ok": False, "error": str(exc)})
            return
        if seen_before(job["trace_id"]):
            self._send(202, {"ok": True, "queued": _jobs.qsize(), "duplicate": True})
            return
        _jobs.put(job)
        self._send(202, {"ok": True, "queued": _jobs.qsize()})


def main() -> int:
    threading.Thread(target=worker, name="codex-worker", daemon=True).start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    log(f"tproj-bridge id={BRIDGE_ID} listening on {BIND}:{PORT} repo={REPO} codex={CODEX} "
        f"sandbox={SANDBOX} network={NETWORK} add_dirs={ADD_DIRS} codex_config_count={len(CODEX_CONFIG)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
