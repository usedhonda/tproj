# Owner-host session console redesign

Status: design proposal and offline interaction preview, not deployed application UI.

## Intent

Make tproj on an agent-owning Mac a usable session manager in the same visual
family as the existing client. The main job is to see, start, open, and stop each
project's CC/Cdx session. A viewing client does not own the agent lifecycle.

The current source already has a `ServerModeView` with lifecycle controls. This
proposal reorganizes those controls; it does not claim the installed owner-host
build already matches this design or that `--server` necessarily means no UI.

## Deliverables

- [Interactive, offline preview](../../apps/tproj/docs/server-console-preview.html)
- [Static layout drawing](../../apps/tproj/docs/server-console-preview.svg)

Both use synthetic projects and state. Buttons never contact a host, read
credentials, launch processes, or change real sessions. The drawing is a design
illustration, not a screenshot of a deployed native application.

## Layout and visual language

- Keep the native macOS window, client typography and `GhosttyTheme.current`.
  The preview illustrates the existing dark palette and white foreground; the
  native implementation must consume shared tokens, not introduce another theme.
- Suggested native window: 720 x 700, minimum width 520. Allow resizing and
  preserve scroll position across refreshes. At narrow widths put connection
  metadata under the status instead of truncating the project name or controls.
- Header: tproj, `This Mac`, Refresh, Add, and a quiet overflow menu. Show the
  actual owning host label when available; never imply this is a remote client.
- A short persistent boundary statement explains that closing this window does
  not stop sessions. It is informational, not a confirmation gate.
- Search and status filters come before the project cards. Count sessions, not
  projects, in filters; show both counts in the footer.
- Each card uses the catalog alias as its title, with the repository path as
  secondary, selectable information. Do not replace a configured alias with the
  last component of the path as the old view currently does.
- Each CC/Cdx row has a distinct harness label, textual lifecycle state,
  connection count and direct actions. Harness color is not lifecycle color or
  model authority. No redundant decorative dots or colored outlines.
- Use white primary text and sufficiently bright secondary text. Do not dim
  stopped sessions into illegibility. Disabled controls may dim, their state
  explanation must remain readable.
- Running uses green; attention uses amber. Stop is a neutral button until
  hovered/confirmed. Red is reserved for an actual destructive confirmation or
  an actionable failure, not a frame around green Cdx text.
- Move memory, messaging health and cache settings into a collapsed secondary
  area. Do not let resource charts push session actions below the fold.

## Required interactions

| Action | UI result | Owning behavior |
| --- | --- | --- |
| Start | Progress on the affected role row, then verified current state | Existing `ensure`; no fresh conversation flag, no duplicate live process |
| Open | Open the existing role session | Attach, never restart as a side effect |
| Stop with no attached clients | Direct targeted stop, then current-state readback | Owner-host helper validates the target; other roles stay untouched |
| Stop with attached clients | Show project, role, connection count and the disconnect effect once | Confirm only this explicit operation; never infer that all clients are remote devices |
| Stop all | Overflow action with enumerated scope and one confirmation | Stop known owned running sessions, never unknown/occupied processes |
| Start stopped sessions | Overflow action, no extra confirmation | Only known stopped registered roles; skip occupied/unknown states |
| Add | Select an existing folder and optional alias | Register only; new roles remain stopped until explicitly started |
| Unregister | Available after all roles are stopped | Remove catalog registration, not files or conversation history |
| Close window | Close the manager only | No stop, exit keystrokes, process kill, or restoration side effect |
| Refresh | Update the snapshot and its age | Read-only, independent from lifecycle operations |

Normal start/open/refresh has no approval dialog. A confirmation is not a session
permission system. Existing native/task authorization remains unchanged.

## Lifecycle presentation

| Owner result | Presentation | Actions |
| --- | --- | --- |
| running, zero clients | Running; no connected view, continuing | Open, Stop |
| running, clients present | Running; N connections | Open, targeted Stop with connection-impact confirmation |
| stopped | Stopped, not a faint offline placeholder | Start |
| occupied | Needs inspection; expected agent not proven | Inspect; no force replacement or generic kill |
| unavailable / incomplete read | State unknown with last-observed timestamp | Retry read; do not treat missing data as stopped |
| operation in flight | Starting/stopping/opening, only affected resource disabled | Other independent rows and search remain usable |
| operation result lost | Result needs reconciliation | Read the same owned resource; do not blindly repeat mutation |

Connection count is not proof of another physical device, a recipient reading a
message, agent activity or task completion. Display client origin only when
actually observed. No client count may be used as permission to terminate an
unknown process.

A memory read failure does not erase a successful lifecycle snapshot; a
lifecycle read failure does not claim the system memory monitor also failed.
Messaging must distinguish service/process existence from verified RPC health.
CC cache warming does not control process lifetime or imply idle-session expiry.

## Existing backend mapping and gaps

Available owner-host CLI operations are `list`, `status`, `ensure`, `attach`,
`stop`, `register`, `unregister`; cache controls and memory collection already
exist in `ServerModeView`. Keep them local to the owning host and preserve the
catalog's existing IDs, aliases and exact project paths.

Implementation work still required beyond this design:

1. Preserve alias and catalog ID in the UI model. The current parser drops both
   for row identity/display purposes and titles by path basename.
2. Add a bounded owner-readable structured snapshot for per-role connection
   count, actual session identity, current PID/incarnation and observed time.
   The current `list` text output only includes role lifecycle labels; do not
   fabricate the additional preview data from that output. A structured command
   is a proposed extension, not an existing callable.
3. Map unavailable, occupied, stopped and in-flight operation states explicitly;
   preserve last-good data as stale, not current. Use request generations so an
   older refresh cannot overwrite a newly completed action.
4. Serialize mutations by project/role while leaving independent rows usable;
   stop and unregister must reconcile current owner state before acting.
5. Implement the native folder picker and concise alias editing. Do not require
   a user to know absolute paths for routine project addition.
6. Integrate the new layout in `ServerModeView` using shared Card/ActionButton
   and theme tokens. Keep local ownership explicit; no management by an SSH
   alias that happens to resolve to the same-looking path.
7. Build/package through the canonical wrapper on the relevant Mac, deploy the
   owner-host application in its real GUI context, then verify actual controls.

Opening the manager reads state only. This redesign does not change login-time
restoration policy, start stopped conversations on appearance, enable new
connections, edit grants, change Roles, or add an automatic restart loop.

## Acceptance before native deployment

- Review the normal, stopped, connected, occupied and unavailable layouts.
- Start a stopped fixture; open/reopen it and prove the same session/PID remains.
- Stop exactly one owned role with a second client attached: show the effect,
  then prove only the confirmed target ended.
- Close a viewing window/app/tmux client: owned processes survive, and another
  independent client can still attach. Owner-host Stop remains available.
- Prove an unavailable/occupied snapshot cannot enable an unsafe Start or Stop.
- Refresh without collapsing expanded details, losing scroll/focus, or replacing
  an in-flight result with an older snapshot.
- Add/unregister affects the catalog only; no repository or history deletion.
- Native theme/font/contrast and narrow-window layout checked visually. Design
  illustrations, mocked state and a successful build do not count as live UI or
  real session acceptance.
