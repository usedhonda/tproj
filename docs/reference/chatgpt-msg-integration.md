# ChatGPT conversation messaging integration

Status: agreed Phase 1 design; implementation and desktop acceptance pending.
This specifies conversation messaging, not task delegation or execution authority.

## Scope

Reuse the existing mailbox, federation, MCP tools and tunnel transport. Enroll
ChatGPT independently from an existing external assistant. Do not borrow that
assistant's identity, credentials or inbox. Repository tools are unnecessary
for the minimum messaging scope.

Phase 1 is explicit messaging from two independently bound ChatGPT conversations.
Automatic resumption of an idle conversation is a separate acceptance milestone.
An existing assistant's successful tool calls do not prove support on ordinary
ChatGPT desktop chats.

## Identity and conversation isolation

The server verifies the authenticated principal, participant binding and
conversation mapping. Provider session metadata is correlation data, not an
independent source of authorization. Caller-supplied conversation IDs cannot
grant access or choose a sender.

Even under one user account, knowledge of another conversation's message ID
must not allow inbox, message, reply or acknowledgement access. Reconnection or
conversation duplication must not silently move an old binding to another chat.
Replies resolve their recipient and originating conversation server-side from
the original message ID. Messages never confer Role, task approval or execution
authority.

## Tool workflow

Use the existing messaging tool names:

- Discover new destinations with `tproj_list`; use `tproj_status` when needed.
- Persist a stable submission ID before `tproj_send`; preserve it on unknown
  outcomes rather than creating a new submission.
- Receive through `tproj_inbox`, then read the exact ID with `tproj_message`.
- Call `tproj_ack` only after the agent consumes the body.
- Reply with `tproj_reply` against the original ID.

Acknowledgement means agent consumption, not human read receipt, business
acceptance, task approval or completion. Queue persistence alone is not failure.
Preserve complete bodies without silent summarization; report actual transport
limits. Do not duplicate requests through Issues, Slack, alternate identities or
new IDs to work around an uncertain outcome.

## Capability discovery and skill behavior

Skill visibility is not evidence that callable tools or an authenticated
connection exist. Skills select actual MCP tools for cloud conversations and
CLI only for enrolled native environments. Missing tools must not provoke an
attempt to execute a nonexistent shell or ask the user to relay the message.

Machine-readable diagnostics must distinguish:

| Layer | Required distinction |
| --- | --- |
| Skill | Instructions visible versus absent |
| Catalog | Required tools present, missing, or stale |
| Connection | Available, disconnected, or unknown |
| Authority | Binding valid, expired, mismatched, or authentication required |
| Operation | Actual call success, explicit failure, or unknown outcome |
| Notification | Delivery evidence versus body consumption |
| Resumption | Supported and demonstrated, unavailable, or unverified |

Errors describe only observed deficiencies: missing MSG tools, authentication
required, or binding mismatch. Unknown remains unknown. Do not equate an
uninvestigated surface with an unsupported surface.

Shared plugin descriptions must agree with individual tool schemas. An
external assistant reported a connection-only/no-mailbox description despite
working mailbox tools. This is a reported catalog-description inconsistency,
not a proven cause of any particular abandonment. Its deployed metadata source
must be located before correction; no matching literal was found in the local
tracked source during specification work.

## Notifications and recovery

Notifications are hints to retrieve the exact message through the authenticated
path. Reconcile stale or duplicate events against durable processing records.
Distinguish missed-notification inbox recovery, expired bindings and inability
to resume the original conversation. Never redirect to another chat or another
assistant and claim successful delivery to the original recipient.

A notification HTTP success is not proof of read or answer. Supported provider
events do not by themselves prove arbitrary original-chat resumption.

## Acceptance

1. Two independent ChatGPT conversations each complete send -> peer body read
   -> peer reply -> originating conversation body read.
2. Exercise an external assistant and a native AI session as destinations.
3. Cross-conversation inbox/message/reply/ack access is rejected, including
   intentional use of a known foreign message ID.
4. Reconnect/duplicate does not transfer another conversation's binding.
5. Missing tools or invalid binding yields the correct diagnostic and no send,
   alternate-route duplicate, or identity fallback.
6. Deployed shared descriptions and callable catalogs agree.

This acceptance excludes automatic resumption, business approval, execution
exactly-once guarantees and A2A compliance.

## Implementation prerequisites

Verify tool availability on the actual desktop chat surface and determine the
supported authenticated conversation-binding mechanism. If trustworthy
multi-chat isolation cannot be established, that mode remains unsupported;
do not replace it with a shared inbox. Existing service-principal authorization
alone is insufficient proof of conversation isolation.

## Primary references

- [Custom MCP connections](https://developers.openai.com/api/docs/guides/custom-mcp-server)
- [MCP Events](https://developers.openai.com/plugins/build/mcp-events)
- [Conversation correlation metadata](https://developers.openai.com/plugins/reference)
