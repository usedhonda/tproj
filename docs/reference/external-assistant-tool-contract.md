# Proposed external-assistant MCP tool contract

**Status: proposed / unimplemented.** This document defines a reviewable tool
surface for issue #14; it does not register an MCP server, add runtime routes,
or prove that an external provider can use the surface. The machine-readable
catalog is [external-assistant-tools.json](external-assistant-tools.json).

## Authority and identity

The existing mailbox remains the sole message authority. The proposed adapter
must authenticate a service participant and bind it to one live endpoint
incarnation. A local service identity is distinct from a provider cloud
conversation binding: the former uses trusted process/service credentials and
the latter requires an authenticated adapter mapping. Neither may be supplied
as caller text. In particular, callers cannot pass `role`, `as`, `session`, a
conversation selector, endpoint/PID/host data, or a receiver override.

Send/status inputs require full project-qualified addresses such as `alpha.cc`
and `alpha.cdx`; bare `cc` or `cdx` is rejected because it is projectless and
ambiguous. Message views may show a registry-validated service address as a
sender or target. `tproj_reply` is pinned to the supplied original `message_id`; the
adapter resolves the original thread and recipient and does not accept a
receiver or conversation argument.

The proposed `tproj_list` and `tproj_status` results are an authorized,
sanitized catalog. They must not expose raw PIDs, host names, credentials,
tokens, or private process paths. Catalog visibility is not enrollment,
reachability, delivery, or presentation evidence.

## Tool summary

| Tool | Inputs | Authority | Result meaning |
| --- | --- | --- | --- |
| `tproj_list` | none | authenticated context's catalog | sanitized participant addresses |
| `tproj_status` | full `target` | same catalog scope | target availability/status |
| `tproj_send` | `target`, `body`, stable `submission_id` | authenticated sender | unique `message_id`/`thread_id`, normally `queued` |
| `tproj_inbox` | bounded `cursor`, `limit` | authenticated recipient | page plus `next_cursor`; does not acknowledge |
| `tproj_message` | `message_id` | sender or recipient party | one authorized message view |
| `tproj_reply` | pinned `message_id`, `body`, stable `submission_id` | original recipient only | unique reply IDs, original `thread_id` |
| `tproj_ack` | consumed `message_id` | bound recipient only | `presented` receipt |

All seven schemas, including annotations and output schemas, are in the JSON
catalog. Read-only annotations apply only to list/status/inbox/message. Write
tools are explicitly not marked read-only; `destructiveHint: false` is not an
approval exemption. The calling host or operator still owns approval policy.
The connection proposal names `tproj:read` and `tproj:write` as application
policy scopes; they are not existing provider or tproj scopes and do not replace
participant or conversation authorization.

## States and idempotency

Tool responses identify unique `message_id` and `thread_id` values. A submit
projection must enrich the current host/hub response: `submit` currently returns
`message_id`, `state` and optionally `duplicate`, not `thread_id`. The proposed
adapter retrieves the authorized durable row to return its thread and reply
linkage. Message views project `target_address` to `target` and omit raw
endpoint/process fields; the JSON outputs are not unmodified host RPC results.
A submit
response with `queued` (or an existing state and `duplicate: true`) means the
mailbox accepted or recovered a durable row; it does **not** mean the message
was received by an adapter or shown to a user. `adapter_received` means the
bound adapter claimed it, while `presented` is reserved for an explicit
recipient acknowledgement after consumption. `uncertain` is recoverable by
reconciliation; `stale_session`, `rejected`, and `expired` are
diagnostic/terminal outcomes as defined by the hub.

Every send or reply requires a caller-persisted stable `submission_id`. The
current host uses that value as `message_id`; a new chat's `thread_id` starts
with the same value. The mailbox's saved submission record is the idempotency authority. Reusing that
ID with the same sender and payload recovers the existing result; reusing it
with a different payload or sender fails with `id_conflict`. A timeout or
unknown network result must therefore be reconciled by retrying the same ID,
never by inventing a second submission ID.
The adapter must not hide an unknown result in an automatic retry loop: a
bounded reconciliation may repeat the same submission ID, while retry policy
and operator-visible uncertainty remain explicit.

`tproj_inbox` uses a bounded cursor and limit. Reading or enumerating rows does
not mark them presented. `tproj_ack` is allowed only after the bound recipient
has explicitly consumed the message; the recipient check and durable receipt
are required. An acknowledgement from another endpoint, or a stale endpoint
incarnation, fails closed.

## Error contract

The local host RPC currently uses the structured error shape
`{"ok":false,"error":{"code":"...","message":"..."}}`; an MCP adapter
may project these codes into its provider error envelope but must preserve the
distinction. At minimum,
the following cases are required:

* missing or invalid trusted identity: `identity_rejected` (fail closed);
* bare or unknown target, or ambiguous catalog entry: `unknown_target`;
* malformed body/submission/message ID: `invalid_message` (including the
  server's 64 KiB UTF-8 byte limit and forbidden terminal-control check;
  JSON Schema's character-count bound alone is insufficient);
* duplicate ID with a different payload or sender: `id_conflict`;
* reply from a non-recipient, receiver override, or cross-conversation use:
  `identity_rejected`;
* retired endpoint or stale process/conversation binding: `stale_session` or
  `identity_rejected`;
* message not found or caller is not a party: `not_found`/`unauthorized`;
* provider/host delivery pause: `maintenance`;
* expired original message or unavailable original sender: `expired` or
  `no_recipient`.

An implementation may use a more specific code, but must not turn any of
these failures into an alias fallback, a new conversation, or an unbound
successful-looking result.

## Schematic exchange (not a live example)

The first call is from the external sender context. The following inbox and
ack calls illustrate the separate, authenticated recipient context; the sender
does not receive its own outgoing message in its inbox.

```json
{"name":"tproj_send","arguments":{"target":"voyager.cc","body":"ping","submission_id":"msg-01"}}
{"message_id":"msg-01","thread_id":"msg-01","state":"queued"}
{"name":"tproj_inbox","arguments":{"cursor":0,"limit":10}}
{"messages":[{"message_id":"msg-01","thread_id":"msg-01","target":"voyager.cc","body":"ping","state":"adapter_received"}],"next_cursor":1}
{"name":"tproj_ack","arguments":{"message_id":"msg-01"}}
{"message_id":"msg-01","state":"presented"}
```

The exchange is schematic: it does not demonstrate an installed MCP server,
provider event delivery, user presentation, or reply capability. A reply would
use the pinned `msg-01` and a new stable submission ID; it would not include a
receiver or cloud conversation selector.

## Explicit non-goals and evidence boundary

This proposal does not implement service-specific `service_inbox`,
`service_message`, or `service_ack` extensions. The seven reviewed shapes are
only a proposed adapter contract. The existing local
`service_claim`/`service_receipt` and normal `inbox`/`message` operations are
source evidence, not a provider-neutral external API.

The connection/authentication lifecycle is owned by
[external-assistant-connection.md](external-assistant-connection.md), which is
being specified separately. This document does not claim that transport,
custom MCP registration, trusted metadata, provider events, or an original
cloud-conversation return path has been proven. KAI's confirmed connected-
computer tasks and Slack capability do not establish any of those missing
surfaces. No claim is made for Dots original-thread return, shared `codex
app-server` conversations, tasks, role handoff, shell execution, or a new
authority channel.

## Review checklist

Before implementation, a bounded proof must show independent enrollment,
trusted service-process and cloud-conversation binding, duplicate-safe send and
reply, cursor bounds, recipient-only acknowledgement, restart/stale-binding
rejection, and cross-project/cross-conversation isolation. Until then the
catalog remains a proposal and the integration status remains unimplemented.

## Catalog version and acknowledgement guidance

`tools/list` includes `_meta.catalog_version`, a short digest of the tool set and its
descriptions, so a consumer can tell whether its copy is current without diffing it.
The `tproj_inbox` and `tproj_message` descriptions ask a recipient that has actually
read a message to call `tproj_ack`; otherwise the sender keeps seeing the message as
not presented. Reading or enumerating still never acknowledges on the reader's behalf.
