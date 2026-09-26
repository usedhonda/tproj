# Unified messaging

This is the public contract for the unified host-agent transport. It is
**not globally active by default**. The transport is active
only when the local client configuration exists at
`$HOME/.config/tproj/msg-client.json` and contains an explicit
`"active": true` marker. Until that condition is met, the existing `tproj-msg`
legacy routes remain authoritative only on never-enrolled installations.
An enrolled installation never automatically returns to those routes.

## Directory and identity

The central directory owns project aliases and endpoint registrations. A local
host agent authenticates its caller from kernel peer credentials and live
process ancestry, including the recorded process-start value. `--as`,
`--session`, pane labels, and model/role metadata are selectors or attributes;
they are not credentials. `cc` and `cdx` resolve within the authenticated local
project. Cross-project sends use the full `<project>.cc` or `<project>.cdx`
address. `gate` is the configured OpenClaw **main** participant; `chi.cc` and
`chi.cdx` are ordinary AI-project endpoints and are not the main participant.

## Delivery and replies

An accepted message is durably queued, but that is not proof of presentation.
The states are distinct:

1. `queued`/`accepted`: the hub committed the message;
2. `presented`: the target host recorded presentation to the bound endpoint;
3. a reply: a new message linked by the original message ID (`in_reply_to`).

Transport health, a socket write, or a model run does not collapse these states.
When a submission result is uncertain, `--retry` may retry **the same message
ID and content only**; it must never create a second request automatically.
Replies remain pinned to the original sender endpoint and message ID. If the
original sender was the projectless OpenClaw main service and its endpoint has
retired after a Gateway restart, the same ID-pinned reply may reach that
participant's sole current endpoint. Ordinary CC/Codex endpoints never use
this restart fallback; an absent or ambiguous service endpoint fails closed.

Ordinary chat cannot change roles, grant implementation authority, or create a
task. `--force` cannot bypass identity, generation, approval, draft, or
sendability guards. Receipt/status events do not generate ACK loops; a reply is
sent only when the application has an actual response.

## Rollout boundary

Before enabling the marker, verify the directory import, endpoint registration,
and one exact-ID presentation/reply proof for each platform and the main service.
Pause acceptance during cutover, classify old queues without replaying history,
and retire obsolete ordinary-message relays. Do not restart tmux, agents, or
the GUI. Build GUI changes for the next operator-initiated launch and explicitly
record their pending activation. Broader route-matrix results remain separate
from these minimum cutover proofs; queued probes are not passing evidence.

## Presentation recovery and active recipients

A bound recipient may consume its inbox during an active turn and explicitly
acknowledge an observed message with `tproj-msg ack <message-id>`. This records
presentation by the authenticated recipient; listing an inbox alone does not.
The CLI never acknowledges on behalf of an unrelated process or project.

Claude terminal delivery keeps the `[from:...]` marker outside bracketed paste
so ordinary chat cannot be mistaken for a direct user role handoff. Codex receives
the entire envelope in one paste, because paste coalescing can discard preceding
literal keystrokes. Exact prompt
receipts normalize only the known single native paste wrapper. A matching bound
Claude session transcript may resolve an uncertain write without reinjection.
Observer running state, selection screens and independent draft measurement
block injection; terminal write success is never a presentation receipt.

`--status cc` and `--status cdx` use the same authenticated project as send,
not a local GUI label. Once enrolled, the persistent `msg-client.enrolled`
marker prevents missing or malformed client configuration from restoring the
legacy ordinary transport. The messaging installer distributes the unified
modules but never enrolls hosts or restarts services.
