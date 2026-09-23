# Claude cache observation for Tproj

`tproj-cc-cache-observer` is a fail-open, Tproj-owned recorder for Claude Code's
`statusLine` input and `UserPromptSubmit`/`Stop`/`Notification:idle_prompt`
hook input. It does not call
CCStatusBar. Invoke it as `statusline`, `prompt`, or `stop` with the respective
JSON on stdin. This recorder is an observation primitive, not a Poke sender.

It accepts only a non-dead tagged tmux Claude pane resolved with explicit
`-t "$TMUX_PANE"` and stores one mode-0600 JSON file per hashed Claude
`session_id` under `~/.local/state/tproj/cc-cache/` (directory mode 0700).
The file contains the session and pane binding, cache expiry, recache-token
estimate, and latest real user prompt time. Prompt text, transcript paths,
and raw status-line payloads are never persisted. A `[keep-alive]` prompt
does not extend the user window, but does mark the turn running. `Stop` records
`stop_seen`, not `idle`: another Stop hook can block and resume the turn after
this observer ran. Claude's `idle_prompt` notification, emitted roughly 60
seconds after an answer with no user typing, records `idle_notified` and its
timestamp; any new prompt clears that evidence. Other notification types are
ignored. A new session does not inherit an old turn state.
Missing identity, malformed input, or I/O
failure must not block a Claude turn.

This state never authorizes a Poke. `idle_notified` is stronger positive
evidence than `stop_seen`, but its freshness, exact session/pane binding,
empty composer, and race with a new turn still require live validation before
any sender can rely on it. Neither `stop_seen` nor an empty prompt glyph
suffices.
`tproj-cc-statusline-tap -- <renderer> [args...]` forwards the exact status-line
input and renderer output while observing a copy. The hook installer registers
the `prompt` event on Claude only. The machine's `statusLine.command` must
explicitly wrap its existing renderer with this tap; the installer does not
replace it silently. The GUI consumer is a separate integration step; until
that is installed and validated, existing
CCStatusBar-backed keep-warm remains unchanged.
