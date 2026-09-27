# Unified messaging

This is the public contract for the unified host-agent transport. It is
**not globally active by default**. The transport is active
only when the local client configuration exists at
`$HOME/.config/tproj/msg-client.json` and contains an explicit
`"active": true` marker. Until that condition is met, the existing `tproj-msg`
legacy routes remain authoritative only on never-enrolled installations.
An enrolled installation never automatically returns to those routes.

## Directory and identity

Each execution host owns its project aliases, endpoints, and durable mailbox.
The operator sees a unified live view of these authoritative owner directories;
foreign endpoint evidence retained with a message is never a routing directory. A local
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


## Standalone-first topology

`tproj init` provisions one local host and local mailbox; it does not require
SSH, a GUI, OpenClaw, or the optional external role/persona implementation.
`tproj topology set standalone|multi` selects the connection mode. Saved remote
configuration survives standalone mode; neither mode switching nor host removal
terminates sessions. `tproj host list|add|remove|check` manages connections. `host remove` disconnects that host from this Mac only; it does not delete remote projects, revoke credentials on other Macs, or terminate sessions. Re-adding performs enrollment checks again.
The `check` operation never installs helpers; explicit `add` can provision them.

Every host dispatches local messages locally, including when all remote hosts
are unreachable. Multi-host enrollment validates unique project aliases and
stable host IDs, authenticates the directed SSH routes between admitted hosts,
and stages membership before committing it. Existing SSH host-key checking is
preserved. No unrelated host discovered in SSH configuration is enrolled.

Remote resolution asks the owning live directory; stored aliases are not a
fallback. A missing destination fails before acceptance. Once accepted, a
message and its exact-ID outbound record are committed atomically. Retry keeps
that same ID, content and recipient incarnation; presentation belongs to the
recipient mailbox. Unknown transport outcome is not presentation. A local
send is not blocked by a remote catalog refresh or retry worker.

Directory edits are serialized by the configured management host, with live
snapshots of every member, owner-specific revision checks, prepare records and
a durable commit decision. That host is a configuration coordinator only,
not a required broker for normal local or peer-to-peer messages. Unavailable
members block group-wide name changes, not local work or local delivery.
`cc` and `cdx` still resolve only within the authenticated sender project;
replies retain the original message and endpoint IDs.

The protocol version is checked at peer ingress. Unknown peers or incompatible
versions fail closed for that connection, without selecting legacy transport.
The optional OpenClaw participant obeys the same ownership rule; its absence
has no effect on ordinary project messaging.

Standalone tmux discovery retains each live candidate found in a distinct pane
for an otherwise-unregistered participant.  If more than one such endpoint is
live, binding and target resolution fail closed as ambiguous; discovery never
silently selects the first pane.

When a standalone tmux observation is followed by a registry observation for a
child agent, the host preserves the already-active endpoint ID only after both
recorded PID start values verify and the two processes are proven to share a
live ancestor/descendant chain with the same participant, host, session, pane,
and platform.  Alias, runtime labels, and pane tags alone never authorize this
continuity; a restart or ambiguous lineage remains a new or rejected identity.
