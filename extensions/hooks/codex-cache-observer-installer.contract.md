# Codex cache observer installer contract

`install-tproj-codex-cache-observer` is the narrow installation path for the
Tproj Codex cache observer. It copies only `tproj-codex-cache-observer` to
`~/bin`, adds only its `UserPromptSubmit` and `Stop` commands to
`~/.codex/hooks.json`, and records the exact `sha256:` values returned by the
Codex app-server `hooks/list` protocol in `~/.codex/config.toml`.

The installer never edits Claude settings, other hooks, messaging state, or
GUI files. It is repeatable and preserves unrelated JSON entries. A normal
install performs a hooks/list preflight before changing `hooks.json`, then
rolls that file back if the post-install listing does not return both observer
hooks with exact hashes. `--dry-run` reports planned changes without writes;
`--check` verifies the installed file, both registrations, and matching trust
records without modifying anything. `--trust-response` is a fixture input for
tests and offline verification.
