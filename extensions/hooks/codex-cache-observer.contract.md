# Codex cache sample observation for Tproj

`tproj-codex-cache-observer` is a fail-open, read-only Tproj recorder for the
Codex `UserPromptSubmit` and `Stop` hook payloads. It never sends a Poke,
changes Codex state, or marks a pane pokeable.

The observer writes mode-0600 JSON below
`~/.local/state/tproj/codex-cache/`, keyed by a SHA-256 hash of `session_id`.
It records only the hashed session binding, tmux pane role/id, pane process id,
event, and a small allow-listed `prompt_cache` sample. Prompt text, transcript
paths, raw payloads, aliases, owner session names, and the raw session
identifier are never persisted.

It requires positive evidence that `TMUX_PANE` is a live `codex-pN` pane and
that the observer's process ancestry reaches that pane's process while
containing a Codex process. Missing, ambiguous, dead, or remote identity fails
closed and writes nothing. A cache sample is reported as unavailable when the
payload has no allow-listed `prompt_cache` fields; absence is not evidence that
Codex lacks caching.

This state is diagnostic only. It does not prove that a Poke would help and is
not an authorization or readiness signal for any sender.
