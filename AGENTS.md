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
bash extensions/messaging/tests/test-role-handoff.sh
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

Use `./dev-app.sh --release` only when a release build is required. Never
launch the GUI any other way (no direct `.app` open, no manual `.build`
binary): other launch paths run stale variants and invalidate verification.

## Protected Contracts

- `AGENTS.md`, `CLAUDE.md`, `.gitignore`: tracked contract files. Runtime
  startup must never create or modify them (enforced by
  `extensions/persona/test-project-bootstrap-contract.sh`).
- `project-bootstrap`, `model-role-router`: tracked symlinks into the sibling
  `general` checkout. Do not materialize or retarget them
  (`install.sh --check` verifies canonical/symlink/installed copies match).
- Generated or ignored runtime artifacts (`.local/`, `apps/tproj/AGENTS.md`,
  `apps/tproj/CLAUDE.md`, `CLAUDE.local.md`): never commit them; their
  generators refresh them.
- Messaging identity and safety gates in `extensions/messaging/` (sender
  verification, relay/fanout/typing/draft guards, role-handoff validation):
  behavior changes require updating the matching contract doc under
  `docs/reference/` and the focused tests in the same commit.

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

Durable project rules belong in this file. Do not introduce important shared
rules only in `CLAUDE.local.md`, `.codex/config.toml`, or agent memory: those
layers are tool- or machine-local and do not reach the other agent.

## Quality Bar and Completion

A change is complete when all of the following hold:

1. The relevant focused tests above pass (run the smallest covering set; run
   the full suite set defined in `.github/workflows/test.yml` for any
   `extensions/messaging` or `extensions/hooks` change).
2. The installed copy is refreshed for scripts that `install.sh` distributes
   (verify with `install.sh --check`; avoid running `install.sh` while a tmux
   workspace is live). GUI changes are verified through `dev-app.sh` only.
3. The change is committed with an English conventional commit
   (`feat:`/`fix:`/`docs:`/`test:`/`chore:`), one logical substep per commit.
4. Contract-sensitive changes (startup, installer, messaging, runtime
   contracts) include their focused test updates in the same commit.

## Handoff

Work must be resumable from the local worktree state plus the handoff note,
without conversation history or agent memory. When handing off between agents
(either direction), record scope, current state, verified results, open risks,
and next steps in a handoff note (template:
`docs/reference/handoff.md`; instances live outside version control, e.g.
`.local/handoff/`). Do not rely on conversation history or agent-local memory
for anything the next agent needs.

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
