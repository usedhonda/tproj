# Unified messaging conversation identity

The unified host binds a shared Codex app-server caller using same-owner Unix
UID, an enrolled host-owned endpoint registry record, and native conversation
context (`CODEX_THREAD_ID` and/or `CODEX_SESSION_ID`). Selectors (`--as` and
`--session`) narrow a match but never create identity. Missing, ambiguous, or
mismatched native context is rejected.

Native Codex context is platform-scoped to `cdx`. Catalog rows are evidence,
not liveness; an endpoint carrying a different native thread or session
binding is never overwritten; stale or conflicting records remain unusable
until a live, unique endpoint observation proves the same binding.

The host may adopt an already-running endpoint without restarting Codex, tmux,
or the shared daemon. Adoption preserves the existing endpoint ID so pending
message IDs and replies remain valid. `tproj-msg-unified whoami` and `doctor`
are read-only diagnostics; `--retry` retains the original submission ID/body
while refreshing native caller context.
