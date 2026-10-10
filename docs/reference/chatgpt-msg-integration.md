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
must not allow inbox, message, reply or acknowledgement access. Reconnection must revalidate the same trusted identity; changed identity must
not silently inherit an old binding. Distinct trusted identities are isolated.
Whether a provider fork always creates a distinct identity is unverified: if
the host duplicates the same identity, the backend cannot distinguish the copies.
Phase 1 does not claim isolation between such indistinguishable copies.
Replies resolve their recipient and originating conversation server-side from
the original message ID. Messages never confer Role, task approval or execution
authority.

## Tool workflow

Use the existing messaging tool names:

- Discover new destinations with `tproj_list`; use `tproj_status` when needed.
- Persist a stable submission ID before `tproj_send`; preserve it on unknown
  outcomes rather than creating a new submission.
- For enrolled conversation dispatch, valid `tproj_send` and `tproj_reply`
  submission IDs are deterministically namespaced by binding and operation
  before reaching the shared mailbox. The caller's arguments remain unchanged;
  invalid IDs are left untouched for the existing validator to reject. Thus
  the same input ID is stable for one binding and operation, while independent
  bindings or send/reply operations cannot collide; a changed payload retains
  the same ID and follows existing idempotency-conflict behavior.
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
4. Reconnect revalidates identity; a distinct fork identity does not inherit an
   old binding. Same-identity provider duplication remains explicitly unproven.
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

## Implementation checkpoint

`tproj_capabilities` now diagnoses catalog presence, connection, service
authorization, messaging availability, conversation isolation, resumption and
operation status without reading or sending a message. A valid fixed service
principal reports `service_principal_valid` and `conversation_isolation:
not_configured`; arbitrary conversation fields cannot upgrade that result.
An absent authorizer reports authentication required. Failed attestation has
unknown cause and does not expose exception text. The shared MSG skill now
selects actual cloud MCP tools versus enrolled native CLI.

This checkpoint does not implement isolated cloud conversation routing. The
existing stdio tunnel/runtime supplies only a fixed service identity; no verified
per-conversation authority ingress exists. Provider session correlation and
user OAuth authentication are not proof of that missing binding. Production
chat enrollment and the two-chat acceptance remain blocked on establishing
that ingress, not on a new user approval. Existing participants are unchanged.

The MCP dispatcher now has an optional runtime-injected conversation resolver.
When configured, each `tools/call` must resolve one owner-enrolled binding from
the trusted ingress attestor and receives tools built for that exact binding;
denial never falls back to fixed KAI tools. Request `_meta` and arguments are
correlation context only and cannot grant identity. This is a unit-tested
dispatch boundary, not live ChatGPT acceptance: production still needs a real
provider attestor and runtime wiring.

Before dispatch, the resolver revalidates the exact binding ID, immutable
attested identity, generation, revocation state and expiry from the current
registry. The canonical owner lock is held across that validation and the
dispatch call (including persisted-registry file locking), so a revoke that
acquires the lock before dispatch wins and returns fixed `identity_rejected`
with no mailbox call. A revoke that begins after dispatch has started is not
claimed to roll back an already-started host operation. Attestation is captured
once per request; revalidation never trusts request metadata or re-attests model
arguments.

Resolver-enabled MCP dispatch does not advertise or route the fixed KAI event
and subscription handlers. Event delivery remains a fixed-service capability;
ordinary conversation binding is limited to explicitly dispatched mailbox
operations and does not grant access to fixed subscription state.

## Reviewed implementation requirements

Authentication requirements describe guarantees, not a mandatory deployment
recipe: verified client origin appropriate to the actual transport, an
authenticated principal with required authority, and host-controlled conversation
correlation bound to that request through the final hop. Direct HTTPS mTLS and
user OAuth serve different purposes. OAuth entrances validate issuer, audience,
expiry and scope. A verified tunnel boundary may provide the necessary guarantees
without a second public endpoint, extra credentials or duplicate mTLS. The
current stdio boundary has not yet proved those guarantees; tunnel identity or
workspace permission alone is not per-chat principal proof.

Enrollment is an explicit connect action under an owner-approved policy, never
an implicit side effect of read/reply. Labels are not authority; users do not
copy internal IDs or tokens. Persistent participant identity is separate from a
transient transport session. Reconnect, revoke, expiry, binding generation and
restart revalidation must be defined. Identity changes must not be repaired by
matching chat titles or history.

For a persisted binding registry, disappearance of an embedded `owner_policy`
after it has been observed is a configuration rejection, not a request to
resurrect the cached policy; the rejected operation performs no write. Enrollment
expiry is checked after acquiring the file lock and reloading current state, and
again immediately before writing a new binding, so a request that expires while
waiting cannot create a binding.

Owner policies are compared after normalization, so the canonical
`principal_ids`/`provider_subject_digests` keys and their `principals`/
`provider_subjects` aliases are equivalent regardless of list order. A reload
publishes policy, its persisted-provenance flag, and bindings only after all
three have validated; malformed bindings therefore cannot partially update the
registry or grant enrollment.

Acceptance additionally covers alternating and concurrent calls from two chats
within one runtime, principal/session/participant argument spoofing, stale
generations and identity changes, foreign cursors and batch acknowledgements
where supported. Rejection causes zero mailbox mutations, including send,
acknowledgement, read state and enrollment. Idempotency is scoped by binding and
operation: the same key with a different payload is rejected; an interrupted
response is resolved using the original ID. Single acceptance is not a
guarantee of single delivery.

See [the reviewed execution plan](chatgpt-msg-execution-plan.md) for sequencing,
production evidence and the remaining two blockers.
