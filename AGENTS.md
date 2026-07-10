# tproj Repository Instructions

## Project Overview

tproj is a tmux-based workspace orchestrator for running Claude Code and Codex
side by side. The repository contains a shell CLI, optional extensions, shared
tmux/yazi configuration, and a native macOS SwiftUI application.

Optional features must fail open: a missing GUI, image provider, voice service,
database helper, or bridge must not prevent the core tmux workspace from
starting unless that component is explicitly required by the invoked command.

## Architecture

- `bin/`: core CLI and tmux lifecycle scripts. `bin/tproj` is the main entrypoint.
- `bin/lib/`: shell helpers shared by the core scripts.
- `config/`: public tmux, yazi, and workspace example configuration.
- `extensions/`: optional messaging, hooks, bootstrap, agent-team, and memory tooling.
- `apps/tproj/`: macOS SwiftUI GUI, split into `TprojApp` and `TprojLogic` targets.
- `tests/`: repository-level smoke coverage for the CLI scripts.
- `docs/`: public project and release documentation.

Keep core behavior independent from optional extensions. Shared shell helpers
belong in `bin/lib/`; GUI-independent Swift logic belongs in `TprojLogic`.

## Build and Test

Run the smallest relevant checks for every change. Common commands from the
repository root are:

```bash
bash tests/smoke-bin.sh
bash extensions/messaging/tests/test-sendability-gate.sh
bash extensions/hooks/tests/test-inbox-check.sh
```

For Swift changes:

```bash
cd apps/tproj
swift test
```

For a source build plus GUI restart, use the repository wrapper so stale app
variants are stopped consistently:

```bash
cd apps/tproj
./dev-app.sh
```

Use `./dev-app.sh --release` only when a release build is required. Do not use a
direct `.app` open or launch a `.build` executable manually as a substitute for
the wrapper when validating GUI changes.

## Runtime Instruction Contract

`AGENTS.md`, `CLAUDE.md`, and `.gitignore` are public, tracked repository files.
Runtime startup must not create or modify them.

The ignored local layer is limited to machine- or session-specific artifacts:

- `CLAUDE.local.md`
- `.codex/config.toml`
- `.local/`
- `.cc-status-bar.voice.json`

SessionStart and `project-bootstrap --prime` may update only the local layer.
Shared instruction initialization or migration requires an explicit
`project-bootstrap --init-shared` or `project-bootstrap --migrate-shared`
command. Any bootstrap change must preserve the focused contract test's
before/after hash guarantee for the three tracked files.

The repository's `project-bootstrap` entrypoint is a tracked symlink to the
canonical implementation in the sibling `general` checkout. Do not materialize
or retarget that symlink in tproj changes. `install.sh --check` verifies the
canonical source, tracked symlink, and installed copy remain byte-identical.

## Contribution Rules

- Keep changes scoped to the requested behavior; avoid unrelated formatting or refactors.
- Preserve existing CLI and GUI behavior unless the task explicitly changes it.
- Add or update focused tests when changing startup, installer, messaging, or runtime contracts.
- Keep tracked documentation and examples free of credentials, user-specific paths, and machine-specific instructions.
- Use ASCII shell operators and arrows in shell scripts (`!=`, `<=`, `>=`, `->`).
- Use English conventional commit messages such as `feat:`, `fix:`, `docs:`, `test:`, and `chore:`.
- Do not add generated build output, local logs, or ignored runtime artifacts to commits.

Before committing, inspect `git diff --check`, run the relevant tests, and confirm
that only task-related files are staged.
