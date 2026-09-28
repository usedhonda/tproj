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
    ledger.write_text('#!/bin/sh\nexit "${LEDGER_FAIL:-0}"\n')
    ledger.chmod(0o755)
    ssh = root / "bin/ssh"
    ssh.write_text('''#!/usr/bin/env python3
import os, select, signal, sys, termios, time, tty
from pathlib import Path
state = Path(os.environ["SSH_STATE"])
count = int(state.read_text()) if state.exists() else 0
state.write_text(str(count + 1))
if count and os.isatty(0):
    print("CONNECTING", flush=True)
    time.sleep(0.3)
    if not os.environ.get("PERSIST"):
        tty.setraw(0, termios.TCSANOW)
    print("RETRY=" + " ".join(sys.argv[1:]), flush=True)
    print("REPLAY=" + str(bool(select.select([0], [], [], 0)[0])), flush=True)
    if os.environ.get("PERSIST"):
        print("REPEATED_DIAGNOSTIC", file=sys.stderr)
        sys.exit(255)
    if os.environ.get("TWO_OUTAGES") and count == 1:
        time.sleep(0.25)
        sys.exit(255)
    time.sleep(0.15)
    sys.exit(int(os.environ.get("RETRY_STATUS", "0")))
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
import json, os, select, signal, subprocess, sys, termios
signal.signal(signal.SIGINT, signal.SIG_IGN)
before = termios.tcgetattr(0)
child = subprocess.Popen(sys.argv[1:])
print("SUPERVISOR=" + str(child.pid), flush=True)
status = child.wait()
after = termios.tcgetattr(0)
queued = bool(select.select([0], [], [], 0)[0])
print("RESULT=" + json.dumps([status, before == after, queued]), flush=True)
'''

    def check_pty(exit_status, interrupt=None, role="cc", cancel_wait=False, refresh=None, second_outage=False, retry_status=0):
        master, slave = pty.openpty()
        def setup():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        state = root / "ssh-state"
        state.unlink(missing_ok=True)
        case_env = dict(env, SSH_STATUS=str(exit_status), SSH_STATE=str(state), RETRY_STATUS=str(retry_status))
        if second_outage:
            case_env["TWO_OUTAGES"] = "1"
        case_client = client
        marker = root / "refresh-input"
        marker.write_text("0")
        if refresh:
            source = Path(client).read_text()
            if refresh == "network":
                scutil = root / "scutil"
                scutil.write_text("#!/bin/sh\ncat " + str(marker) + "\n")
                scutil.chmod(0o755)
                source = source.replace("/usr/sbin/scutil", str(scutil))
            else:
                # Model a clock jump at the same clock-read sites used on wake.
                source = source.replace("time.time()", "(time.time() + float(open(\"" + str(marker) + "\").read()) * 10)")
            case_client = str(root / "client-under-test")
            Path(case_client).write_text(source)
            Path(case_client).chmod(0o755)
        if cancel_wait == "persistent":
            case_env["PERSIST"] = "1"
        if interrupt or refresh:
            case_env["HOLD"] = "1"
        process = subprocess.Popen([sys.executable, "-c", runner, case_client, "attach", "test-host", "/remote/project", role], stdin=slave, stdout=slave, stderr=slave, env=case_env, preexec_fn=setup)
        os.close(slave)
        output = b""
        sent = killed = connecting_input = False
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
                if b"CONNECTING" in output and not connecting_input and not cancel_wait:
                    os.write(master, b"offline-keystrokes\n")
                    connecting_input = True
                if refresh and b"GOT=x;" in output and not killed:
                    marker.write_text("1")
                    killed = True
                if cancel_wait and b"reconnecting" in output and not killed and (cancel_wait != "persistent" or int(state.read_text()) >= 3):
                    os.write(master, b"discarded\x1b[<0;12;34M\n\x03")
                    killed = True
                if interrupt and b"GOT=x;" in output and not killed:
                    supervisor = int(re.search(rb"SUPERVISOR=(\d+)", output)[1])
                    os.kill(supervisor, interrupt)
                    killed = True
                if b"RESULT=" in output and process.poll() is not None:
                    break
            assert process.wait(timeout=1) == 0, output
            assert b"GOT=x;" in output, output
            match = re.search(rb"RESULT=(\[[^\r\n]+\])", output)
            expected = 130 if cancel_wait else 128 + interrupt if interrupt else retry_status if exit_status == 255 else exit_status
            if (exit_status == 255 or refresh) and not cancel_wait:
                assert b"tproj-remote-host reattach" in output and b"--role " + role.encode() in output, output
                assert b"REPLAY=False" in output, output
                assert b"BatchMode=yes" in output, output
                assert b"ServerAliveInterval=2" in output and b"ServerAliveCountMax=2" in output and b"ConnectTimeout=3" in output, output
            if retry_status:
                assert b"remote attachment exited with status 17" in output, output
            if second_outage:
                assert state.read_text() == "3" and output.count(b"reconnecting") == 2, output
            if cancel_wait:
                assert state.read_text() == ("3" if cancel_wait == "persistent" else "1"), output
                assert output.count(b"reconnecting") == 1, output
                assert b"REPEATED_DIAGNOSTIC" not in output, output
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
    check_pty(255, role="cdx")
    check_pty(255, second_outage=True)
    check_pty(255, retry_status=17)
    check_pty(255, cancel_wait=True)
    check_pty(255, cancel_wait="persistent")
    check_pty(17)
    check_pty(0, refresh="network")
    check_pty(0, refresh="wake")
    check_pty(0)
    check_pty(0, signal.SIGTERM)
    check_pty(0, signal.SIGINT)
    check_pty(0, signal.SIGHUP)
    for action, status in (("attach", 255), ("attach", 0), ("reattach", 0), ("status", 255)):
        result = subprocess.run([client, action, "test-host", "/remote/project", "cc"], input=b"", capture_output=True, env=dict(env, SSH_STATUS=str(status), SSH_STATE=str(root / "no-tty-state"), LEDGER_FAIL="1" if action == "reattach" else "0"), start_new_session=True)
        assert result.returncode == status, result
        assert b"\x1b" not in result.stdout + result.stderr, result
        assert (b"-tt --" if action in ("attach", "reattach") else b"-T --") in result.stdout, result
print("remote client TTY cleanup: PASS (input, queue, modes, exit 0/17, reconnect 255 cc/cdx, wait cancel, network/wake refresh, TERM/INT, no-TTY, non-attach)")
PY
