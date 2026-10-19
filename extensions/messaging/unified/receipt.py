"""Best-effort UserPromptSubmit receipt hook for unified mailbox deliveries."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

try:
    from .cli import DEFAULT_CONFIG, ClientError, config, rpc, _caller_request
except ImportError:  # installed standalone module
    from cli import DEFAULT_CONFIG, ClientError, config, rpc, _caller_request

MESSAGE_RE = re.compile(r"\[tproj-message:([^\]\s]+)\]")


def normalize_prompt(prompt: str) -> str:
    prefixed = re.fullmatch(r'(\[from:[^\]]+\] \[tproj-message:[^\]]+\])\s*<pasted_content id="([A-Za-z0-9_-]+)">\n(.*)\n</pasted_content id="\2">\s*', prompt, re.DOTALL)
    if prefixed: return prefixed.group(1) + " " + prefixed.group(3)
    # Claude wraps a bracketed-paste prompt in one transport-owned block.
    match = re.fullmatch(r'\s*<pasted_content id="([A-Za-z0-9_-]+)">\n(.*)\n</pasted_content id="\1">\s*', prompt, re.DOTALL)
    return match.group(2) if match else prompt


def submit_prompt_receipt(payload: dict, *, config_path: Path | None = None, platform: str | None = None) -> bool:
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
        request = _caller_request("prompt_receipt", message_id=match.group(1),
                                  prompt=prompt, runtime_id=session_id)
        if platform == "cdx" and not request.get("conversation"):
            request["conversation"] = {"platform":"cdx", "session_id":session_id,
                                       "thread_id":payload.get("thread_id") or session_id}
        rpc(cfg["socket"], request)
        return True
    except Exception:
        return False


def main() -> int:
    # Hooks must never print or block unrelated prompt processing.
    import json
    try: payload = json.load(__import__("sys").stdin)
    except Exception: return 0
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--platform',choices=('cc','cdx'))
    args=parser.parse_args()
    submit_prompt_receipt(payload,platform=args.platform)
    return 0




def codex_transcript_presented(endpoint: dict, prompt_hash: str, *, sessions_root: Path | None = None) -> bool:
    """Recover presentation from one pinned native CLI transcript, never a reply.

    Only top-level live user items count. Compaction/replacement histories and
    event mirrors cannot supply evidence. Read a bounded tail; older evidence
    outside it remains unknown rather than scanning unrelated conversations.
    """
    native = endpoint.get("thread_id") or endpoint.get("session_id")
    if not isinstance(native, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", native):
        return False
    root = sessions_root or Path.home() / ".codex/sessions"
    try:
        if root.is_symlink(): return False
        root = root.resolve()
        paths = list(root.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/rollout-*-" + native + ".jsonl"))
        if len(paths) != 1: return False
        path = paths[0]
        if any(p.is_symlink() for p in (path, *path.parents)):
            return False
        with path.open("rb") as stream:
            header = json.loads(stream.readline(65537))
            meta = header.get("payload", {})
            if (header.get("type") != "session_meta" or meta.get("id") != native
                    or meta.get("source") != "cli" or meta.get("originator") != "codex-tui"
                    or meta.get("thread_source") != "user"):
                return False
            project = endpoint.get("project_path") or endpoint.get("path")
            if not project or Path(meta.get("cwd", "")).resolve() != Path(project).resolve():
                return False
            size = stream.seek(0, os.SEEK_END)
            start = max(0, size - 262144)
            stream.seek(start)
            if start: stream.readline()  # discard partial leading record
            tail = stream.read(262144)
        for raw in tail.splitlines():
            try: row = json.loads(raw)
            except (ValueError, UnicodeError): continue
            item = row.get("payload", {})
            if (row.get("type") != "response_item" or item.get("type") != "message"
                    or item.get("role") != "user"):
                continue
            content = item.get("content")
            if not isinstance(content, list) or not content or any(
                    not isinstance(c, dict) or c.get("type") != "input_text"
                    or not isinstance(c.get("text"), str) for c in content):
                continue
            text = "".join(c["text"] for c in content)
            if hashlib.sha256(normalize_prompt(text).encode()).hexdigest() == prompt_hash:
                return True
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return False


if __name__ == "__main__":
    raise SystemExit(main())
