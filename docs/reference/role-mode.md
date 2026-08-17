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

The GUI may also store `main: "cc" | "cdx"`: the pane the user intends to talk to.
This is deliberately separate from role `lead`. It controls display/navigation only;
moving the actual conversation still determines the working side under a declared
mode, and tier still decides role authority under `auto`.

## State

- **One file per project**: `<project>/.local/role-mode.json`
  (the relative location can be overridden with `MODEL_ROLE_MODE_FILE_NAME`).
- The file's location is its scope. Declaring a mode in one project never affects a
  neighbouring column, and two projects hold different modes at the same time.
- **Absent means `auto` with no main preference.** So does an unreadable file, an unrecognized mode value,
  and a project that cannot be resolved to a local absolute root (remote `ssh://`
  projects have no local state directory and always read as `auto`).
- Declaring plain `auto` deletes the file. `auto --main cc|cdx` keeps a file only to
  retain the conversation preference; role resolution remains ordinary `auto`.
- The file is **not** cached into pane options. Every hook reads it on every turn,
  which is what makes a mode apply to panes created after it was declared, with no
  registration step, and what makes a change reach a pane that started before it.
- The retired workspace-wide file (`~/.config/tproj/role-mode.json`) is **never read**.
  A leftover copy cannot re-impose a mode on anything.
- Living under `.local/` keeps the file out of version control and inside the Codex
  work root, so either agent can act on "switch to solo" said in conversation.

Shape:

```json
{"mode": "advisor", "main": "cdx", "set_at": 1786400000, "set_by": "gui", "source": "tproj-gui"}
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
model-role-router mode advisor --main cdx --project /path/to/project
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
| `tproj-msg --new-task` to the opposite same-column peer | allowed | rejected before task creation or delivery; ordinary consultation remains allowed |
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

The messaging gate is deliberately narrower than a general communication ban. Under
`advisor`, an ordinary message to the opposite peer is still a consultation. A
`--new-task` (including `--role-handoff --new-task`) to that same-column peer is
rejected with `advisor_peer_is_advice_only` before liveness checks, task-id creation,
database writes, or `send-keys`. `--user-authorized` does not bypass the mode: the user
can instead prompt the other pane directly or change the mode. Tasks to a distinct
subagent are unaffected.

## Who leads (`lead`)

`mode --json` also reports `"lead": "cc" | "cdx" | ""` — which side is main for the
project right now. It is derived, not stored: the registry records that the last
directly prompted side resolved to `solo-fallback` (declared modes) or that a side
is `orchestrator` (auto), and the newest such entry wins. The router is the only
interpreter of registry entries; the GUI and CLI ask it rather than parsing the
cache themselves. An empty lead means no pane of the project has resolved a role
yet.

## Who the user talks to (`main`)

`mode --json` reports an optional `"main": "cc" | "cdx" | ""`. Unlike `lead`, this
is stored user preference and is never consulted by role resolution. The GUI uses it
to mark the intended conversation pane; when empty it falls back to displaying the
derived lead. `--main derived` clears the preference.

## Visibility

- tmux status line: `tproj-role --status-segment` shows ` role:<mode>·<lead>` for
  the **focused pane's project**, and nothing under `auto`, so an undeclared
  workspace keeps its old status line.
- The tproj GUI shows a first-row menu per project. Its `Mode` section selects
  Team/advisor/solo and its `Main conversation` section always selects CC or Cdx.
  `Team` is the GUI name for the stored `auto` mode; CLI and file compatibility
  keep using `auto`.
  An unset stored preference displays the derived lead, or Cdx when no lead exists.
  The compact badge shows only the mode (`Team`, `Advisor`, or `Solo`); clicking
  it exposes the detailed checked choices. The chosen conversation side's button
  is the sole always-visible main indicator and is tinted with the mode colour.
  The GUI reads and writes only through
  `model-role-router mode`.
- In every mode, the GUI reads CodexBar's selected-account weekly history snapshots
  from Application Support every five minutes. It also reads the exact
  `claude-weekly-scoped-fable` window from CodexBar's local structured CLI output
  when available; it never reads provider credentials or stores the CLI's identity
  fields. A missing or malformed optional CLI response simply omits the Fable row.
  For each displayed window, it derives the
  window start from that provider's own next reset minus seven days, calculates the
  average burn since that start, and projects usage at that provider's next reset.
  User-facing GUI and conversation notices follow CodexBar's remaining-capacity
  vocabulary: current weekly percentage remaining, time until reset, and projected
  percentage remaining at reset. The projected-used percentage remains internal to
  alert evaluation and is not shown as an unexplained standalone number.
  This account-global comparison appears once in a collapsible `Weekly Capacity`
  section directly below `Current Workspace`, not in every project's role-mode
  menu. Cdx has one row; CC has a base `Weekly` row and an optional `Fable` row.
  Headroom compares Cdx with CC Weekly because Fable is a model-scoped constraint.
  Each row gets one thin centered pace bar: the fixed middle line is the
  burn rate that would use exactly 100% at that provider's own reset, while the
  coloured marker shows the current linear burn rate. The shared English axis is
  `Over / Target / Spare`; fixed-width `Left`, signed `Margin`, and compact `Reset`
  columns avoid overlap in the narrow sidebar. Row labels retain provider identity
  colours, while the pace number, segment, and marker use the alert thresholds:
  green below 90% projected use, yellow from 90% through 99%, and red at 100%
  or above. Margin is `100 - projected use`: negative values appear left in red,
  zero is the center target, and positive spare capacity appears right in green.
  The panel never switches `main`.
  Assessment starts only after one hour and 10% actual use, and requires both
  provider snapshots to be no more than 30 minutes old. Red means the main projects
  100% usage; yellow means either 90% projected usage or a meaningful allocation gap
  (main at least 75%, other at most 60%, and at least 20 points apart). Recovery uses
  a lower band (main below 80% and the relative condition substantially cleared) to
  avoid flapping.
- The GUI writes only fixed enums, timestamps, and aggregate percentages to
  `~/.local/state/tproj/weekly-pace.json`; no account key, email, or raw CodexBar
  object is copied. `tproj-inbox-check` may inject a completed Japanese notice into
  the next normal response. One machine-global ledger at
  `~/.local/state/tproj/usage-notice.json` deduplicates across projects and CC/Cdx:
  critical escalation is immediate, critical reminders are at most every four
  hours, advisory reminders every twelve hours, and recovery is emitted once.
  Missing, stale, malformed, or unwritable optional state is silent and fail-open.
- The chosen conversation-main pane receives one shared warm-violet additive wash
  and a two-pixel edge in the existing background underlay; CC and Cdx do not use
  different pane hues. The other pane keeps its image but receives a slight dark
  scrim. The wash compensates for Ghostty transparency, while the edge remains the
  primary cue. A mode/main
  change runs only the fast manifest sync and never regenerates persona images.
  Warning yellow/red and conversation-main violet/cyan come from separate palette
  entries. The GUI never fetches provider usage directly or switches main automatically.

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
