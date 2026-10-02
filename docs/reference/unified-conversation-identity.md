# Unified messaging conversation identity

The unified host binds a shared Codex app-server caller using same-owner Unix
UID, an enrolled host-owned endpoint registry record, and native conversation
context (`CODEX_THREAD_ID` and/or `CODEX_SESSION_ID`). Selectors (`--as` and
`--session`) narrow a match but never create identity. Missing, ambiguous, or
mismatched native context is rejected.

Native Codex context is platform-scoped to `cdx`. Catalog rows are evidence,
not liveness; an endpoint carrying a different native thread or session
binding is never overwritten; stale or conflicting records remain unusable
until a live, unique endpoint observation proves the same binding. A local
catalog row marked `source_kind=vscode` is not sufficient by itself: it is
adopted only when exactly one matching rollout header independently confirms
the same thread, project, and any indexed session ID.

When the local thread catalog has no row, or has one matching
`source_kind=vscode` row, adoption may read one exact native Codex TUI rollout
header from `~/.codex/sessions/YYYY/MM/DD`. The filename UUID and first
`session_meta` record must match the requested thread exactly, its `cwd` must
identify the project, and the record must declare `originator=codex-tui` with
`source=vscode`. This is read-only evidence; a catalog conflict, foreign host,
wrong source, conflicting cwd/session ID, symlink, malformed header, or
non-UUID selector does not fall back to rollout files.

The host may adopt an already-running endpoint without restarting Codex, tmux,
or the shared daemon. Adoption preserves the existing endpoint ID so pending
message IDs and replies remain valid. `tproj-msg-unified whoami` and `doctor`
are read-only diagnostics; `--retry` retains the original submission ID/body
while refreshing native caller context.
