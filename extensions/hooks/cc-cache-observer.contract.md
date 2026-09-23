# Claude cache observation for Tproj

`tproj-cc-cache-observer` is a fail-open, Tproj-owned recorder for Claude Code's
`statusLine` input and `UserPromptSubmit` hook input. It does not call CCStatusBar.
Invoke it as `statusline` with the status-line JSON or `prompt` with the hook
JSON on stdin. This recorder is an observation primitive, not a Poke sender.

It accepts only a non-dead tagged tmux Claude pane resolved with explicit
`-t "$TMUX_PANE"` and stores one mode-0600 JSON file per hashed Claude
`session_id` under `~/.local/state/tproj/cc-cache/` (directory mode 0700).
The file contains the session and pane binding, cache expiry, recache-token
estimate, and latest real user prompt time. Prompt text, transcript paths,
and raw status-line payloads are never persisted. A `[keep-alive]` prompt
does not extend the user window. Missing identity, malformed input, or I/O
failure must not block a Claude turn.

Before this state can authorize any Poke, the caller must independently recheck
the live session/pane binding, freshness, idle state, and empty composer at
send time. Cache observation alone is never proof that sending is safe.
`tproj-cc-statusline-tap -- <renderer> [args...]` forwards the exact status-line
input and renderer output while observing a copy. The hook installer registers
the `prompt` event on Claude only. The machine's `statusLine.command` must
explicitly wrap its existing renderer with this tap; the installer does not
replace it silently. The GUI consumer is a separate integration step; until
that is installed and validated, existing
CCStatusBar-backed keep-warm remains unchanged.
