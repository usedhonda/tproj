---
name: msg
description: |
  tproj-msg による peer AI 間通信スキル。host 内部 subagent の親報告には
  使わず、native collaboration と final response を使う。
  「送って」「伝えて」「聞いて」「相談して」「依頼して」「/msg」など、
  明示された peer 通信で発動する。
argument-hint: <target> <message>
allowed-tools: [Bash, Read]
compression-anchors:
  - "tproj-msg で peer メッセージ送受信"
  - "gate は設定済み OpenClaw main participant"
  - "自律発動: 他列影響・依頼完了・解決不能・Chi相談"
---

## Unified messaging (authoritative for enrolled clients)

Protocol reference: `docs/reference/unified-messaging.md` in the repository.
Enrollment requires `$HOME/.config/tproj/msg-client.json` with
`"active": true`; the client persists `$HOME/.config/tproj/msg-client.enrolled`.
After enrollment, missing, malformed, or deactivated configuration fails closed
through unified messaging and never restores ordinary legacy routing. A
never-enrolled standalone client may use `tproj-msg --help` and the repository
legacy implementation; this skill is not a second legacy rulebook.

### Channel and identity boundary

- Host-internal subagents report to their parent with native collaboration and
  final response. Do not use `tproj-msg` for that parent lifecycle report.
- Use `tproj-msg` only for an explicitly requested peer or configured service.
  Reply exactly once to an inbound message unless it is marked FYI or
  返信不要; never invent a second acknowledgement.
- `cc` and `cdx` resolve to the authenticated local project. Cross-project
  peers use the full `<project>.cc` or `<project>.cdx` address. Bare role names
  are not evidence for another project.
- `gate` is the configured OpenClaw **main** participant. `chi.cc` and
  `chi.cdx` are ordinary AI-project endpoints, not the main participant.
- Named external channels remain separate, explicit service targets. Ordinary
  agent messages never fall through to owner channels.

The central directory binds the caller from kernel peer credentials and live
process ancestry. `--as`, `--session`, pane labels, and role/model metadata are
selectors, not credentials. Force-like options cannot bypass identity,
generation, approval, draft, or sendability guards.

### Sending and delivery evidence

Use `tproj-msg <target> <message>` or `tproj-msg --stdin <target>`. Message
body text is never parsed as a target or routing verb. Treat these as separate
states: `queued`/`accepted` (durable hub commit), `presented` (bound-recipient
receipt), and an application reply. Transport receipts and status events never
start an ACK conversation loop.

If a submission is uncertain, retry only the same submission ID and content;
never create a second request. A reply uses the original message ID:
`tproj-msg reply <message-id> --stdin`, and remains pinned to the original
sender endpoint.

Inbox reads are paged: start with
`tproj-msg inbox --cursor 0 --limit 100 --json`, then request each returned
`next_cursor` until it is absent. Reading an inbox is not acknowledgement;
use `tproj-msg ack <message-id>` only after the authenticated recipient has
actually consumed that message.

### Tasks, roles, and drafts

Ordinary chat cannot grant implementation authority or change roles. Keep
`--new-task`, `--role-handoff`, and `--desktop` on their existing validators;
they do not create cross-host authority. Exact user-authorized tasks retain
their exact target and scope and must not be broadened by the receiver.

Never overwrite an active native draft. A typing or unknown target is handled
by the existing sendability guard; do not force delivery merely to avoid a
queue. Do not poll with `--read` or sleep loops for replies. Use native
collaboration for parent lifecycle messages and the unified mailbox for peer
messages only.
