# Codex Desktop <-> tmux session mailbox

`tproj-msg` lets the Codex Desktop app exchange messages with the CC/Cdx panes
running inside a tmux workspace. Because the Desktop app has no tmux pane and no
per-turn provenance for its content, this channel is a **data-plane mailbox**: it
moves envelope files between private mailboxes and never injects anything into a
pane. Each side reads its own mailbox explicitly.

## Security model

- **Desktop is `identity_class=desktop`** — a per-project mailbox peer named
  `desktop.<project>`. It is not a pane alias and not an orchestrator/worker.
- **Desktop-originated content is always untrusted.** It is never delivered to a
  pane (no `tmux send-keys`), never enters ACK/DONE/BLOCK task tracking, role
  handoff, or control parsing. It is only ever written to a mailbox file that the
  recipient reads on demand.
- **Desktop identity is proven by process ancestry**, not by a claimed name. The
  caller's live process tree must contain the pid that the model-role registry
  recorded for the Desktop entry, and that pid's live start time must match the
  registry-recorded value (pid-reuse defence). Body, title, and any `--as` claim
  are ignored for authorization.
- **Control-plane use is rejected** from the Desktop identity: `--new-task`,
  `--role-handoff`, `--force`, `--fire`, `--as`, `--allow-relay`, `--allow-fanout`.
- **Reading is pure.** Reading a mailbox never triggers execution, resend, task
  acceptance, or any role-metadata change, and does not delete messages.

## Storage

Mailboxes live under a user-private root (`0700`), one `0600` JSON envelope per
message (written atomically via a temp file + rename):

```
<root>/to-session/<session>/<target_alias>/    Desktop -> session (session reads)
<root>/to-desktop/<project>/                   session -> desktop (desktop reads)
```

The default root is `${XDG_CACHE_HOME:-$HOME/.cache}/tproj-msg/desktop-mailbox`.
Each envelope carries `from`, `to`, `body`, `body_sha256`, `created_at`, and
`bridge:"desktop"`. Bounds (all env-adjustable) protect the store:

| limit | default | env var |
|---|---|---|
| max bytes per envelope | 65536 | `TPROJ_DESKTOP_MAILBOX_MAX_BYTES` |
| max envelopes per mailbox | 200 | `TPROJ_DESKTOP_MAILBOX_MAX_COUNT` |
| envelope TTL | 7 days | `TPROJ_DESKTOP_MAILBOX_TTL_SEC` |
| mailbox root | see above | `TPROJ_DESKTOP_MAILBOX_ROOT` |

## Usage

Desktop -> a session pane (rings the pane's body-free arrival bell):

```
tproj-msg --desktop --session <session> <alias.role> "message"
tproj-msg --desktop --session tproj-workspace tproj.cc "please look at the PR"
```

Desktop reads its own mailbox (what sessions sent back):

```
tproj-msg --desktop --mailbox
```

A session pane sends to the Desktop and reads what the Desktop sent it:

```
tproj-msg desktop.<project> "reply to the desktop"
tproj-msg --read desktop
```

## Arrival notification

A Desktop -> session write also records a body-free inbound row in the shared
`messages.db` (`bridge=desktop`, empty body). The existing inbox monitor turns
that into a count-only "arrival bell"; message content is never shown in the
notification — read it with `tproj-msg --read desktop`.

## Notes

- The channel fails closed: an unresolved or ambiguous Desktop identity is
  rejected, and every reject is recorded in the caller-audit trail
  (`auth_path = desktop-rejected`; accepts use `desktop-mailbox`).
- The Desktop registry schema this consumes is owned by the model-role router
  (the standalone/Desktop registry entry). `tproj-msg` isolates the schema
  consumption in a single function so the field mapping can be aligned when the
  canonical schema is published.
