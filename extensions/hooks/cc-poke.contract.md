# Standalone Claude Poke sender

`tproj-cc-poke` is a standalone, initially unactivated Tproj primitive. It is
not registered in Claude hooks and no GUI invokes it. A later integration may
invoke it with one exact Claude `session_id`; it has no broadcast or implicit
target mode.

The sender fails closed unless the hashed cache record is a regular file in a
non-symlink cache directory and all of these hold: session id, pane id, tty,
pane PID, role, alias, and owner tmux session match a fresh live tagged Claude
pane; one live `claude` process remains below the pane and its PID plus start
epoch match the observer's recorded binding; the prompt cache expiry is in the
future; a bounded recent non-`[keep-alive]`
user prompt exists; and a fresh `Notification:idle_prompt` follows that prompt.
`Stop` and an empty prompt glyph alone are never sufficient.
The observer resets prior turn evidence when the agent binding changes, even
when a resumed session keeps the same tmux pane and Claude session ID.

It captures the pane immediately before and again immediately before sending.
The current capture must end at an empty `›`/`❯` composer and contain no
permission, question, or running-turn evidence. The second identity/state/
capture check includes a fresh agent binding; any change refuses the send. The only
literal body is `[keep-alive]`, sent with tmux literal text followed by Enter.

Deduplication uses CCStatusBar's existing `~/.claude/.cache-poke/` claim name,
`<session_id>-<integer cache expiry>`, with atomic mode-0600 `O_CREAT|O_EXCL`.
The session ID is restricted to safe filename characters. An existing claim
from either application refuses the send. The sender never removes a lock
(including after a failed attempt), so it cannot delete another process's
claim; the cache expiry bounds the resulting fail-closed dedup window. This
shared claim is a safety protocol, not a runtime dependency on CCSB.

The runtime installer copies the executable artifact but does not add a hook,
enable a setting, or perform a live send. This contract intentionally does not
claim that the sender is safe for GUI activation without a separate live
integration review.
