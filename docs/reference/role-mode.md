# Role mode contract

Roles between the Claude and Codex panes of a column are normally decided by model
tier. A **role mode** lets the user override that: under a declared mode the side
that receives the user's direct prompt does the work, and the other side only
advises. This document is the contract for how that mode is stored, read, and
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

- One file for the whole workspace: `~/.config/tproj/role-mode.json`
  (override with `MODEL_ROLE_MODE_FILE`).
- **Absent means `auto`.** So does an unreadable file and an unrecognized mode value.
  A corrupt file can therefore never invent a restriction.
- Declaring `auto` deletes the file, so the default and the escape hatch below reach
  one state rather than two that have to behave identically.
- The file is **not** keyed by session or column, and is **not** cached into pane
  options. Every hook reads it on every turn, which is what makes a mode apply to
  columns and panes created after it was declared, with no registration step, and
  what makes a change reach a pane that started before it.

Shape:

```json
{"mode": "advisor", "set_at": 1786400000, "set_by": "user", "source": "tproj-role"}
```

`set_at` and `set_by` are echoed in every injected `[Model Role Runtime]` block as
`mode=advisor (set 2026-08-16 12:34 by user)`. An agent runs the user's shell and can
always clear its own gate, so the provenance line is the mitigation: widening its own
permissions leaves a trace the user can see.

## Reading the mode

`model-role-router mode --json` is the **only** supported reader. Nothing else parses
the file. A second parser is a second thing to keep in step, and the place a
disagreement would surface is a turn that cannot be ended.

Callers must treat a missing router, a non-zero exit, or unparseable output as `auto`
and keep their existing behaviour, never as "no mode, so no enforcement".

## Enforcement

| Surface | `auto` | `advisor` / `solo` |
|---|---|---|
| Injected context | unchanged, no `mode=` line | `mode=` line plus a mode-specific directive |
| Role resolution | tier and message markers | the mode alone, resolved **before** any marker |
| PreToolUse deny | orchestrator may not edit or run mutating git | the advising side may not; the leading side may |
| Automatic role handoff | as before | suppressed |
| Delegated-task lifecycle (`tproj-completion-guard`) | as before | suppressed |

Role resolution happens before `[Role-Handoff:]`, `[Task:]`, and an `Orchestrator:`
line in a message body are considered. Resolving it afterwards would let one stale
handoff sitting in a queue pull a pane back under the arrangement the user had just
replaced. A mode change also advances the role epoch, so handoffs already in flight
are dropped as stale by the existing epoch check.

The advising side's edit deny is a hard deny, which is safe because a pane only holds
that role while handling a message from the other side. A direct prompt from the user
makes it the leading side on that turn, so the gate never blocks the user's own
request.

## Escape hatch

```sh
rm ~/.config/tproj/role-mode.json
```

The state is a single file, so this returns the workspace to `auto` even if the
router itself is broken. `model-role-router mode auto` does the same thing.

## Tests

- `general/system/model-role-router/test-model-role-router.sh` — state file defaults
  and fallbacks, role resolution per mode, marker precedence, the advisor deny, and
  the return to `auto`.
- `extensions/hooks/tests/test-task-lifecycle.sh` — lifecycle enforcement is
  suspended under a declared mode and preserved under `auto`, including the fallback
  when the router cannot be read.
