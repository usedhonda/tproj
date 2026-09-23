# Codex cache sample observation for Tproj

`tproj-codex-cache-observer` is a fail-open, read-only Tproj recorder for the
Codex `UserPromptSubmit` and `Stop` hook payloads. It never sends a Poke,
changes Codex state, or marks a pane pokeable.

The observer writes mode-0600 JSON below
`~/.local/state/tproj/codex-cache/`, keyed by a SHA-256 hash of `session_id`.
It records only the hashed session binding, tmux pane role/id, pane process id,
event, a small allow-listed `prompt_cache` sample, and the latest numeric token
sample from the exact hook `transcript_path`. The transcript must be below
`~/.codex/sessions/` and its `session_meta.payload.id` must equal the hook
`session_id`. Its metadata must also identify the root `cli` / `codex-tui` /
`user` thread; subagent and other same-process sessions write no state.
Otherwise the token sample is unavailable. Prompt text,
transcript paths, raw payloads, aliases, owner session names, and the raw
session identifier are never persisted.

It requires positive evidence that `TMUX_PANE` is a live `codex-pN` pane and
that the observer's process ancestry reaches that pane's process while
containing a process whose basename is exactly `codex`; process arguments are
never read. Process ancestry alone is not a thread identity: one Codex process
can host multiple transcripts. Missing, ambiguous, dead, or remote identity fails closed and
writes nothing. A cache sample is reported as unavailable when the
payload has no allow-listed `prompt_cache` fields; absence is not evidence that
Codex lacks caching.

No observed Codex hook payload has proven those `prompt_cache` fields are
supplied, so `sample_available=false` remains possible. `last_token_sample`
means the latest observed token count, not the latest human turn or a cache
expiry. Transcript format is not a stable public contract; parsing failures
produce `null`, never a guessed session or cwd join.

This state is diagnostic only. It does not prove that a Poke would help and is
not an authorization or readiness signal for any sender.
