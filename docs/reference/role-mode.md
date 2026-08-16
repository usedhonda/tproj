# Role mode contract

Roles between the Claude and Codex panes of a column are normally decided by model
tier. A **role mode** lets the user override that per project: under a declared mode
the side that receives the user's direct prompt does the work, and the other side
only advises. This document is the contract for how that mode is stored, read, and
enforced.

## Modes

| Mode | Who leads | The other side |
|---|---|---|
| `auto` (default) | tier decides, as before | tier decides, as before |
| `advisor` | whichever side the user prompted directly | advises: read, search, review, answer when asked |
| `solo` | whichever side the user prompted directly | stays out unless asked something directly |

No side is ever named in a declaration. Moving the conversation to the other pane
moves the lead with it, so `advisor` needs no re-declaration and cannot get between
the user and a pane they are talking to.

## State

- **One file per project**: `<project>/.local/role-mode.json`
  (the relative location can be overridden with `MODEL_ROLE_MODE_FILE_NAME`).
- The file's location is its scope. Declaring a mode in one project never affects a
  neighbouring column, and two projects hold different modes at the same time.
- **Absent means `auto`.** So does an unreadable file, an unrecognized mode value,
  and a project that cannot be resolved to a local absolute root (remote `ssh://`
  projects have no local state directory and always read as `auto`).
- Declaring `auto` deletes the file, so the default and the escape hatch below reach
  one state rather than two that have to behave identically.
- The file is **not** cached into pane options. Every hook reads it on every turn,
  which is what makes a mode apply to panes created after it was declared, with no
  registration step, and what makes a change reach a pane that started before it.
- The retired workspace-wide file (`~/.config/tproj/role-mode.json`) is **never read**.
  A leftover copy cannot re-impose a mode on anything.
- Living under `.local/` keeps the file out of version control and inside the Codex
  work root, so either agent can act on "switch to solo" said in conversation.

Shape:

```json
{"mode": "advisor", "set_at": 1786400000, "set_by": "tproj.cc", "source": "tproj-role"}
```

`set_by` records the **actual declarer**: an agent pane records its own alias
(`tproj.cc`), a plain terminal records `user`. It is echoed in every injected
`[Model Role Runtime]` block as `mode=advisor (set 2026-08-16 12:34 by tproj.cc)`.
An agent runs the user's shell and can always clear its own gate, so this provenance
line is the mitigation: widening its own permissions leaves a trace the user sees on
every turn.

## Reading and declaring

`model-role-router mode [--project DIR] [--json]` is the **only** supported reader.
Nothing else parses the file. The project defaults to `TPROJ_PROJECT`, then the
pane's `@project` tag, then the caller's cwd.

`tproj-role` is the front end:

```sh
tproj-role                # this project's mode
tproj-role advisor        # declare for this project
tproj-role solo --project /path/to/other
tproj-role auto --all     # every local project in workspace.yaml
```

Callers must treat a missing router, a non-zero exit, or unparseable output as
`auto` and keep their existing behaviour, never as "no mode, so no enforcement".

## Enforcement

| Surface | `auto` | `advisor` / `solo` |
|---|---|---|
| Injected context | unchanged, no `mode=` line | `mode=` line plus a mode-specific directive |
| Role resolution | tier and message markers | the mode alone, resolved **before** any marker |
| PreToolUse deny | orchestrator may not edit or run mutating git | the advising side may not; the leading side may |
| Automatic role handoff | as before | suppressed |
| Delegated-task lifecycle (`tproj-completion-guard`) | as before | suspended, **scoped to the guard's own project** |

Role resolution happens before `[Role-Handoff:]`, `[Task:]`, and an `Orchestrator:`
line in a message body are considered. Resolving it afterwards would let one stale
handoff sitting in a queue pull a pane back under the arrangement the user had just
replaced. A mode change also advances the role epoch, so handoffs already in flight
are dropped as stale by the existing epoch check.

The advising side's edit deny is a hard deny, which is safe because a pane only holds
that role while handling a message from the other side. A direct prompt from the user
makes it the leading side on that turn, so the gate never blocks the user's own
request.

## Who leads (`lead`)

`mode --json` also reports `"lead": "cc" | "cdx" | ""` — which side is main for the
project right now. It is derived, not stored: the registry records that the last
directly prompted side resolved to `solo-fallback` (declared modes) or that a side
is `orchestrator` (auto), and the newest such entry wins. The router is the only
interpreter of registry entries; the GUI and CLI ask it rather than parsing the
cache themselves. An empty lead means no pane of the project has resolved a role
yet.

## Visibility

- tmux status line: `tproj-role --status-segment` shows ` role:<mode>·<lead>` for
  the **focused pane's project**, and nothing under `auto`, so an undeclared
  workspace keeps its old status line.
- The tproj GUI shows a badge per project row (`auto·CC` green / `advisor·Cdx`
  cyan / `solo·CC` red), click to cycle; the lead side's CC/Cdx button is tinted
  with the mode colour. The badge reads via `mode --json` and writes the same
  per-project file.

## Escape hatch

```sh
rm <project>/.local/role-mode.json
```

The state is one file per project, so this returns that project to `auto` even if
the router itself is broken. `tproj-role auto` does the same thing.

## Tests

- `general/system/model-role-router/test-model-role-router.sh` — state file defaults
  and fallbacks, per-project isolation, the legacy-file ban, remote-project refusal,
  role resolution per mode, marker precedence, the advisor deny, and the return to
  `auto`.
- `extensions/hooks/tests/test-task-lifecycle.sh` — lifecycle enforcement suspended
  under a declared mode, preserved under `auto`, the router-unreadable fallback, and
  the project scoping of the guard's mode query.
- `tests/smoke-bin.sh` — `tproj-role` read paths survive a checkout with no
  installed router.
