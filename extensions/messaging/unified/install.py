#!/usr/bin/env python3
"""Install/check only the unified mailbox client; never edits legacy messaging."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWLIST = ("task_role.py", "tasks.py", "task_transport.py", "task_host.py", "task_approval.py", "task_cli.py", "cli.py", "receipt.py", "host.py", "hub.py", "identity.py", "protocol.py", "policy.py", "federation.py", "runtime.py", "directory.py", "enrollment.py", "terminal-parser.sh", "terminal-guard.sh")
LAUNCHER = "#!/bin/sh\nexec python3 \"$HOME/lib/tproj-msg-unified/cli.py\" \"$@\"\n"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""): h.update(chunk)
    return h.hexdigest()


def atomic_copy(source: Path, target: Path, mode: int, dry_run: bool = False) -> bool:
    data = LAUNCHER.encode() if source.name == "<launcher>" else source.read_bytes()
    if target.is_file() and target.read_bytes() == data and (target.stat().st_mode & 0o777) == mode: return False
    if dry_run:
        print(f"WOULD INSTALL {source} -> {target}"); return True
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(raw, mode); os.replace(raw, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(raw): os.unlink(raw)
    return True


def expected(home: Path) -> list[tuple[Path, Path, int]]:
    lib = home / "lib/tproj-msg-unified"
    return [(REPO_ROOT / "extensions/messaging/unified" / name, lib / name, 0o755 if name.endswith(".sh") else 0o644) for name in ALLOWLIST] + [
        (Path("<launcher>"), home / "bin/tproj-msg-unified", 0o755)
    ]


def check(home: Path) -> int:
    errors = []
    for source, target, mode in expected(home):
        if source.name == "<launcher>":
            if not target.is_file() or target.read_text() != LAUNCHER: errors.append(f"{target} differs or missing")
        elif not target.is_file() or digest(source) != digest(target): errors.append(f"{target} differs or missing")
        if target.exists() and (target.stat().st_mode & 0o777) != mode: errors.append(f"{target} mode mismatch")
    if errors:
        print("\n".join(errors)); return 1
    print("ok: unified mailbox client matches repo source"); return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(); p.add_argument("--check", action="store_true"); p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv); home = Path.home()
    if args.check: return check(home)
    changed = False
    for source, target, mode in expected(home):
        changed |= atomic_copy(source, target, mode, args.dry_run)
    if not args.dry_run: print("installed unified mailbox client" if changed else "unified mailbox client already current")
    return 0


if __name__ == "__main__": raise SystemExit(main())
