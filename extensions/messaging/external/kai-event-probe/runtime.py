#!/usr/bin/env python3
"""Prepare an isolated Secure MCP Tunnel runtime for the KAI probe.

Preparation is intentionally inert: it writes local launch artifacts and may
run the official client's ``init`` command when the referenced key file is
already present and safe.  It never starts a tunnel, creates a cloud resource,
or reads the key contents.  The generated runner repeats the safety checks at
startup.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import stat
import subprocess
import sys
from pathlib import Path


DEFAULT_LABEL = "local.tproj.kai-probe-tunnel"
DEFAULT_PROFILE = "kai-event-probe"
SERVER = Path(__file__).with_name("server.py").resolve()
MANIFEST = "runtime.json"


class RuntimeError_(RuntimeError):
    pass


def _regular(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _safe_key(path: Path) -> bool:
    """Check metadata only; never opens or reads the credential file."""
    if not _regular(path):
        return False
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        return path.stat().st_uid == os.getuid() and mode & 0o077 == 0
    except OSError:
        return False


def _safe_dir(path: Path, *, create: bool = False) -> None:
    if path.exists() and path.is_symlink():
        raise RuntimeError_(f"unsafe symlink path: {path}")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise RuntimeError_(f"not a safe directory: {path}")
    os.chmod(path, 0o700)


def _write_new(path: Path, data: bytes, mode: int) -> None:
    if path.exists() or path.is_symlink():
        if not path.is_file() or path.read_bytes() != data:
            raise RuntimeError_(f"refusing to overwrite conflicting artifact: {path}")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _binary(path: Path) -> Path:
    if not path.is_absolute():
        raise RuntimeError_("--binary must be an absolute path")
    if not _regular(path) or not os.access(path, os.X_OK):
        raise RuntimeError_(f"tunnel client is not executable: {path}")
    return path


def _init_profile(binary: Path, profile_dir: Path, profile: str, tunnel_id: str,
                  key_file: Path, mcp_command: str) -> None:
    """Run only the official local init; env is deliberately tunnel-neutral."""
    _safe_dir(profile_dir, create=True)
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL") if key in os.environ}
    env["PATH"] = str(binary.parent)
    cmd = [str(binary), "init", "--profile", profile, "--profile-dir", str(profile_dir),
           "--tunnel-id", tunnel_id, "--mcp-command", mcp_command,
           "--control-plane-api-key-ref", f"file:{key_file}",
           "--health-listen-addr", "127.0.0.1:0"]
    result = subprocess.run(cmd, env=env, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError_(f"tunnel client init failed ({result.returncode})")
    if not any(profile_dir.iterdir()):
        raise RuntimeError_("tunnel client init produced no profile artifacts")


def _runner(binary: Path, base: Path, profile_dir: Path, profile: str, key_file: Path) -> bytes:
    b, p, d, k = map(shlex.quote, map(str, (binary, profile, profile_dir, key_file)))
    return ("#!/bin/sh\nset -eu\n" +
            f"BASE={shlex.quote(str(base))}\nPROFILE_DIR={shlex.quote(str(profile_dir))}\n" +
            f"KEY_FILE={k}\n" +
            "[ -d \"$BASE\" ] && [ ! -L \"$BASE\" ] || { echo 'unsafe runtime base' >&2; exit 78; }\n" +
            "[ -f \"$KEY_FILE\" ] && [ ! -L \"$KEY_FILE\" ] || { echo 'missing or symlinked credential file' >&2; exit 78; }\n" +
            "MODE=$(stat -f '%Lp' \"$KEY_FILE\" 2>/dev/null || stat -c '%a' \"$KEY_FILE\")\n" +
            "[ \"$MODE\" = 600 ] || [ \"$MODE\" = 400 ] || { echo 'credential file must be owner-only' >&2; exit 78; }\n" +
            f"exec {b} run --profile {p} --profile-dir \"$PROFILE_DIR\" --config \"$PROFILE_DIR/config.json\"\n").encode()


def prepare(args: argparse.Namespace) -> dict:
    binary = _binary(Path(args.binary).expanduser())
    base = Path(args.base_dir).expanduser().resolve()
    key_file = Path(args.credential_file).expanduser().resolve()
    if base == Path("/") or base == Path.home():
        raise RuntimeError_("dedicated --base-dir is required")
    _safe_dir(base, create=True)
    if key_file == base or str(key_file).startswith(str(base) + os.sep):
        raise RuntimeError_("credential file must remain separate from runtime base")
    profile = args.profile
    profile_dir = base / "profile"
    runner_path = base / "run.sh"
    plist_path = base / f"{args.label}.plist"
    manifest_path = base / MANIFEST
    mcp = args.mcp_command or f"{sys.executable} {SERVER}"
    manifest = {"binary": str(binary), "baseDir": str(base), "credentialFile": str(key_file),
                "profile": profile, "tunnelId": args.tunnel_id, "label": args.label,
                "mcpCommand": mcp, "healthListenAddr": "127.0.0.1:0"}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as exc:
            raise RuntimeError_("invalid existing runtime manifest") from exc
        if old != manifest:
            raise RuntimeError_("conflicting runtime manifest; refusing overwrite")
    else:
        _write_new(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), 0o600)
    if profile_dir.exists() and not profile_dir.is_dir():
        raise RuntimeError_("conflicting profile path")
    if not profile_dir.exists():
        profile_dir.mkdir(mode=0o700)
    if not any(profile_dir.iterdir()) and _safe_key(key_file):
        _init_profile(binary, profile_dir, profile, args.tunnel_id, key_file, mcp)
    elif not any(profile_dir.iterdir()):
        # Offline preparation leaves profile creation for the operator's
        # later run; generated startup still fails closed until then.
        os.chmod(profile_dir, 0o700)
    _write_new(runner_path, _runner(binary, base, profile_dir, profile, key_file), 0o700)
    plist = {"Label": args.label, "ProgramArguments": [str(runner_path)],
             "RunAtLoad": False, "KeepAlive": False, "ProcessType": "Background"}
    _write_new(plist_path, plistlib.dumps(plist, fmt=plistlib.FMT_XML), 0o600)
    return {"baseDir": str(base), "runner": str(runner_path), "plist": str(plist_path),
            "profileInitialized": bool(any(profile_dir.iterdir())), "credentialPresent": _safe_key(key_file)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare an inert isolated KAI tunnel runtime")
    parser.add_argument("--binary", required=True)
    parser.add_argument("--tunnel-id", required=True)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--mcp-command")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args), sort_keys=True))
    except RuntimeError_ as exc:
        print(f"runtime preparation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
