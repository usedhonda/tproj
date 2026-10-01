# External assistant integration: investigation assessment

**Status: investigation/specification only.** This note records what the
current unified transport proves in source and what an independently operated
external assistant would still need. It does not claim a live external
integration, a successful production exchange, or an implementation decision.

## Scope and evidence boundary

Issue #14 concerns an assistant that is already able to connect to a remote
execution host. The source establishes local mailbox and federation
mechanisms, but this assessment has not proved an official outbound API,
inbound event subscription, or native conversation-correlation API for that
assistant. Those are dependencies to verify with the provider and in a
bounded live test owned by the project maintainers.

Shared `codex app-server` conversation identity, tasks, and role handoff are
out of scope here. The existing design deliberately rejects app-server
ancestry until a trusted conversation adapter is proven
(`docs/reference/unified-messaging.md`; `docs/reference/conversation-identity-and-cross-host-tasks.md`).

## What the current code proves

### One service participant, bound to one live process

The directory can contain a projectless service participant, including the
optional OpenClaw participant. A host accepts service operations only when all
of the following match:

* the caller is the local UID and presents the configured service token;
* the requested address is the configured service address; and
* `launchctl` reports the configured launchd label with the caller's PID.

`extensions/messaging/unified/host.py` then reads the kernel process-start
value and derives an endpoint ID from host, participant, PID, and process
start. Any prior live endpoint for that participant is retired. This is a
singleton binding: one current service process/endpoint is authoritative, and
an alias or self-reported runtime ID cannot claim continuity.

### OpenClaw restart rebinding is intentionally narrow

Replies are normally pinned to the original sender endpoint and message ID.
The hub and federated hub have one explicit exception: if that original
endpoint was the projectless OpenClaw service and it retired after a Gateway
restart, a reply may resolve to the participant's sole current endpoint. This
keeps the conversation participant stable while binding the new process
incarnation. Ordinary Claude/Codex endpoints do not receive this fallback.

### Existing service operations are not a complete external API

The authenticated host dispatch currently exposes service-prefixed operations
for `service_send`, `service_reply`, `service_claim`, and `service_receipt`.
The general `inbox` and `message` operations authenticate a normal discovered
caller; they are not service-prefixed and therefore are not a documented
external-service query/inbox interface. There is no provider-neutral service
query, webhook/event subscription, or acknowledgement protocol beyond the
local host RPC and the existing claim/receipt primitives. Directory listing is
an operator/catalog operation, not proof that a service can consume a message.

The mailbox does distinguish accepted/queued, adapter-received, and presented
states, and replies must retain the original thread and endpoint linkage.
Federation carries immutable endpoint evidence between independently enrolled
hosts; it does not create an external provider integration.

## Route matrix

| Route or capability | Current source-backed state | External-assistant implication | Future proof required |
|---|---|---|---|
| Local service identity | Implemented: token + configured address + launchd label/PID + kernel process start | A provider must run an independently enrolled service process or adapter that can satisfy an equivalent binding | Show stable provider process identity and rejection of stale/replayed credentials |
| Service send/reply | Implemented as local authenticated host RPC (`service_send`/`service_reply`) | Connection to a host is not by itself an outbound provider API | Prove the provider's official outbound request API, request IDs, retries, and error semantics |
| Service receive | `service_claim` and `service_receipt` exist for a bound service endpoint | No generic external event stream is established | Prove inbound webhook/stream delivery, authenticity, replay handling, and mapping to a claimed message |
| Service inbox/query | No service-specific `service_inbox` or `service_message` query operation; ordinary `inbox`/`message` use normal caller binding | A provider cannot be assumed to poll the mailbox through the public contract | Specify and implement a service-scoped query/inbox API, cursor semantics, and authorization |
| Directory/discovery | Local and federated directory APIs list enrolled participants and endpoints | Directory visibility is not provider enrollment or message presentation | Independently enroll the service and prove owner-host routing and endpoint retirement |
| Reply correlation | Message IDs, thread IDs, original sender/recipient endpoints, and the OpenClaw restart exception are enforced in source | Provider conversation IDs cannot be treated as tproj thread identity without a trusted mapping | Prove authenticated conversation binding and durable mapping across reconnect/restart |
| Delivery evidence | Queued/accepted, adapter-received, presented, receipt, and reply are distinct | HTTP success or model execution cannot stand in for presentation | Produce an end-to-end receipt tied to message ID, endpoint incarnation, and provider event/request ID |
| Cross-host transport | SSH federation is transactional and restricted to enrolled hosts; foreign endpoint evidence is immutable | Remote reachability does not enroll a new assistant service | Complete directed enrollment and capability negotiation before accepting traffic |

## Required future contract

Before implementation, the external assistant integration needs:

1. **Independent enrollment.** The assistant service must be a named
   participant with its own credentials, owner host, endpoint incarnation, and
   revocation/restart behavior. A generic remote connection or host alias is
   insufficient.
2. **Authenticated conversation binding.** A provider conversation/thread must
   be bound by a trusted adapter to the tproj endpoint incarnation and
   message/thread ID. Self-reported conversation IDs, prompts, process names,
   or shared daemon ancestry are not evidence.
3. **Durable routing.** Outbound requests and inbound events need persisted
   IDs, idempotent retry, expiry, replay rejection, and explicit states for
   accepted, presented, and replied. Unknown outcomes must remain recoverable
   without creating a second message.
4. **Provider API evidence.** Document the official API surface, authentication
   model, webhook or stream signature, ordering/duplication rules, rate/error
   behavior, and data-retention limits. Do not infer these from a successful
   network connection.
5. **Restart semantics.** Reconnect must either preserve the authenticated
   conversation binding or intentionally create a new endpoint incarnation;
   only the documented OpenClaw participant exception may rebind a pinned
   reply, and only to its sole current endpoint.

## Minimal acceptance cases (future)

These are acceptance targets, not current results:

* An enrolled external service can send one message and receive one durable
  reply with matching message ID, thread ID, endpoint incarnation, and
  provider request/event IDs.
* Two external conversations cannot read, acknowledge, or reply to each
  other's messages; an expired, retired, or replayed credential is rejected.
* A duplicate webhook or retry is idempotent and does not create a second
  message or second presentation receipt.
* A service restart either resumes through a verified binding or is rejected as
  a new incarnation; no alias-only rebinding occurs.
* Loss of the provider API, webhook, or host leaves an explicit pending or
  unknown state that can be reconciled without claiming live success.

Until these cases are demonstrated with the provider's official interfaces,
the correct status remains **unimplemented; no live success proven**.

## Source pointers

* `extensions/messaging/unified/host.py` — service credential/PID binding,
  service operations, normal-caller inbox/query dispatch.
* `extensions/messaging/unified/hub.py` — endpoint incarnation, mailbox
  states, claim/receipt, reply validation, and OpenClaw restart fallback.
* `extensions/messaging/unified/federation.py` — enrolled-host transport and
  immutable foreign endpoint evidence.
* `extensions/messaging/unified/enrollment.py` — transactional independent
  host enrollment and directed SSH checks.
* `docs/reference/unified-messaging.md` — public delivery and identity
  contract, including the OpenClaw exception.
* `docs/reference/conversation-identity-and-cross-host-tasks.md` — explicit
  precondition for trusted conversation binding; tasks/role handoff are not
  covered by this assessment.
