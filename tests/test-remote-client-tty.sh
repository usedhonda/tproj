#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$repo" <<'PY'
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time

client = str(Path(sys.argv[1]) / "bin/tproj-remote-client")
with tempfile.TemporaryDirectory() as root:
    root = Path(root)
    (root / "bin").mkdir()
    ledger = root / "bin/tproj-peer-ledger"
    ledger.write_text("#!/bin/sh\nexit 0\n")
    ledger.chmod(0o755)
    ssh = root / "bin/ssh"
    ssh.write_text('''#!/usr/bin/env python3
import os, signal, sys, termios, tty
if os.isatty(0):
    tty.setraw(0)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, signal.SIG_DFL)
    os.write(1, b"\\x1b[?1003h\\x1b[?1006h\\x1b[?1004h\\x1b[?2004hREADY\\n")
    received = os.read(0, 1)
    os.write(1, b"GOT=" + received + b";PID=" + str(os.getpid()).encode() + b"\\n")
    if os.environ.get("HOLD"):
        while True:
            signal.pause()
else:
    print("SSH_ARGS=" + " ".join(sys.argv[1:]))
sys.exit(int(os.environ["SSH_STATUS"]))
''')
    ssh.chmod(0o755)
    env = dict(os.environ, HOME=str(root), PATH=str(root / "bin") + ":" + os.environ["PATH"])
    runner = '''
import json, os, select, subprocess, sys, termios
before = termios.tcgetattr(0)
child = subprocess.Popen(sys.argv[1:])
print("SUPERVISOR=" + str(child.pid), flush=True)
status = child.wait()
after = termios.tcgetattr(0)
queued = bool(select.select([0], [], [], 0)[0])
print("RESULT=" + json.dumps([status, before == after, queued]), flush=True)
'''

    def check_pty(exit_status, interrupt=None):
        master, slave = pty.openpty()
        def setup():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        case_env = dict(env, SSH_STATUS=str(exit_status))
        if interrupt:
            case_env["HOLD"] = "1"
        process = subprocess.Popen([sys.executable, "-c", runner, client, "attach", "test-host", "/remote/project", "cc"], stdin=slave, stdout=slave, stderr=slave, env=case_env, preexec_fn=setup)
        os.close(slave)
        output = b""
        sent = killed = False
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    output += chunk
                if b"READY\n" in output and not sent:
                    # Only x is consumed by SSH; mouse fragments must be flushed.
                    os.write(master, b"x\x1b[<0;45;35M\n")
                    sent = True
                if interrupt and b"GOT=x;" in output and not killed:
                    supervisor = int(re.search(rb"SUPERVISOR=(\d+)", output)[1])
                    os.kill(supervisor, interrupt)
                    killed = True
                if b"RESULT=" in output and process.poll() is not None:
                    break
            assert process.wait(timeout=1) == 0, output
            assert b"GOT=x;" in output, output
            match = re.search(rb"RESULT=(\[[^\r\n]+\])", output)
            expected = 128 + interrupt if interrupt else exit_status
            assert match and json.loads(match[1]) == [expected, True, False], output
            for mode in (1000, 1001, 1002, 1003, 1005, 1006, 1015, 1016, 1004, 2004, 1):
                assert f"\x1b[?{mode}l".encode() in output, (mode, output)
            for reset in (b"\x1b[<u", b"\x1b[>4;0m", b"\x1b>"):
                assert reset in output, output
            ssh_pid = int(re.search(rb";PID=(\d+)", output)[1])
            try:
                os.kill(ssh_pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("SSH child survived supervisor")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            os.close(master)

    check_pty(255)
    check_pty(0)
    check_pty(0, signal.SIGTERM)
    check_pty(0, signal.SIGINT)
    for action, status in (("attach", 255), ("attach", 0), ("status", 255)):
        result = subprocess.run([client, action, "test-host", "/remote/project", "cc"], input=b"", capture_output=True, env=dict(env, SSH_STATUS=str(status)), start_new_session=True)
        assert result.returncode == status, result
        assert b"\x1b" not in result.stdout + result.stderr, result
        assert (b"-tt --" if action == "attach" else b"-T --") in result.stdout, result
print("remote client TTY cleanup: PASS (input, queue, modes, exit 0/255, TERM/INT, no-TTY, non-attach)")
PY
