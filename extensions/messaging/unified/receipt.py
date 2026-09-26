"""Best-effort UserPromptSubmit receipt hook for unified mailbox deliveries."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

try:
    from .cli import DEFAULT_CONFIG, ClientError, config, rpc
except ImportError:  # installed standalone module
    from cli import DEFAULT_CONFIG, ClientError, config, rpc

MESSAGE_RE = re.compile(r"\[tproj-message:([^\]\s]+)\]")


def submit_prompt_receipt(payload: dict, *, config_path: Path | None = None) -> bool:
    """Send an exact prompt receipt; return False silently for unrelated/unsafe input."""
    try:
        if not isinstance(payload, dict): return False
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            prompt = payload.get("message")
        if not isinstance(prompt, str): return False
        match = MESSAGE_RE.search(prompt)
        if not match: return False
        session_id = payload.get("session_id") or payload.get("session")
        if not isinstance(session_id, str) or not session_id: return False
        cfg = config(config_path or DEFAULT_CONFIG)
        rpc(cfg["socket"], {
            "op": "prompt_receipt",
            "message_id": match.group(1),
            "prompt": prompt,
            "runtime_id": session_id,
            "session": session_id,
            "as": payload.get("as"),
        })
        return True
    except Exception:
        return False


def main() -> int:
    # Hooks must never print or block unrelated prompt processing.
    import json
    try: payload = json.load(__import__("sys").stdin)
    except Exception: return 0
    submit_prompt_receipt(payload)
    return 0


if __name__ == "__main__": raise SystemExit(main())
