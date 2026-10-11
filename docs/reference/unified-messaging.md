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
For a service recipient, mailbox acceptance, notification acceptance, presentation,
recipient consumption, and a substantive answer are separate observations. The
absence of an ACK does not establish that a screen is absent, that the recipient is
busy, or that delivery failed. Preserve the original message ID while awaiting an
asynchronous answer; an authorized party may use `message` or `diagnose` metadata,
but must not duplicate the request through an Issue, Slack, or a new message ID, or
ask the user to relay it when the owner can investigate.
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

## Native CLI visible follow-through

After a substantive peer message reaches an existing enrolled native CLI
conversation, the receiver concisely explains the sender, request type, current
status, and next action on that conversation's current user-facing surface.
Include one nonsecret sentence identifying the request's target and key question
or requested change.
Do not echo the full peer body, secrets, or raw diagnostic output. This is local
conversation progress, not forwarding or an additional notification route.
FYI/no-reply messages do not require a peer reply; information affecting an active
objective still belongs in the relevant visible status explanation.

An exact-ID peer reply, user-visible progress, and completion of the original
already-user-authorized objective are separate obligations. A successful reply
does not finish that objective: continue its authorized scope through the required
implementation, minimal verification, and result report. Ordinary messages and
diagnostics grant no new implementation authorization. Existing task lifecycle
authority alone controls formal task scope, executor, epoch, cancellation, and
freeze; ignored notes are supplemental, not a new ledger or authority.

Keep bound exact-prompt acceptance, TUI rendering, direct human observation, and
the receiver's progress explanation separate in evidence and reports. A receipt
alone proves neither that the human saw the message nor that progress was explained.
This contract changes only existing native CLI receiver behavior. Existing KAI
normal MSG delivery and existing ChatGPT failure notifications remain unchanged;
it adds no all-MSG ChatGPT fanout, notification expansion, enrollment, role change,
or ledger.

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
`tproj-msg --help`/`-h` reflects unified mode once enrolled, and `--read` stays
local-only: it reads a pane on this Mac and reports a configured remote alias
as unreadable rather than "not found".

Claude terminal delivery keeps the `[from:...]` marker outside bracketed paste
so ordinary chat cannot be mistaken for a direct user role handoff. Codex receives
the entire envelope in one paste, because paste coalescing can discard preceding
literal keystrokes. Exact prompt
receipts normalize only the known single native paste wrapper. A matching bound
Claude session transcript may resolve an uncertain write without reinjection.
Observer running state, selection screens and independent draft measurement
block injection; terminal write success is never a presentation receipt.

The terminal guard treats the optional tmux `@prompt_state` value as a hint
only when its numeric `@prompt_state_ts` is no more than 5 seconds old and no
more than 2 seconds in the future. Missing, malformed, stale, or far-future
timestamps fall through to the independent current-screen, approval, and
draft checks; they never clear a real guard and never authorize injection by
themselves. A fresh `typing`, `busy`, or `running` value still blocks delivery.
Independent draft detection is coordinate-aware: it binds the native composer
to the live cursor/pane position and keeps trailing status/footer rows in the
snapshot for alignment, rather than assuming the prompt is the last captured
line. Footer trimming requires a native prompt at the actual cursor row and
an immediately following divider; historical prompts do not gain trust from
footer trimming. Real text in that composer remains protected.

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

## Project names (aliases)

A project's alias is its address (`<alias>.cc`, `<alias>.cdx`). Rules:

- The alias comes from the `alias` field of the owning host's `workspace.yaml`
  entry (the directory name only when `alias` is absent). The owning host is the
  only authority for it; a project has exactly one owner and one live name.
- A name is never reused for a different project, including after retirement.
- When a project that used to be local becomes a `remote` entry (it now lives on
  another Mac) or is renamed, the old local entry is **retired**:
  `tproj-msg-runtime reconcile` lists local entries whose path the
  workspace now declares as remote, and `reconcile --apply` retires them.
  `retire-alias OLD --successor NEW` retires one explicitly. Retirement needs
  the admin credential and is refused while the entry has a live endpoint.
- A retired alias leaves the directory and `--list`, stays reserved, and
  **redirects one hop** to its successor. A send to `OLD.cc` is delivered to
  `NEW.cc` and the result carries `renamed_from` / `renamed_to` so the sender
  learns the new name. A retry of the same message ID with the old name is the
  same message.
- Retirement never terminates sessions or deletes messages and endpoints.
- Pane labels (`@alias`, titles) follow the workspace; a session that predates
  an alias change is re-tagged with `tproj --repair`.

Host-to-host calls travel over SSH with one reused connection per peer
(`ControlMaster=auto`, kept 15 minutes) and generous timeouts (30 s per call, 40 s
for byte-capped repo calls, with the local sockets above them waiting longer), because
two Macs can be far apart: over a relayed Tailscale path one handshake took about
10 s, which a short timeout turned into intermittent `host_unavailable` failures.

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

## Independent local services

The host adapter may retain the legacy `service` object for the projectless
OpenClaw main participant and may additionally configure a `services` mapping
keyed by stable service identity (for example, `kai`). Each entry has its own
participant ID, address, token, launchd label, process incarnation, and
`platform`. A non-OpenClaw identity cannot claim `platform: "openclaw"`.
Service requests select the identity with `service_id`; an address or token
alone never selects another service. The host verifies the local UID, token,
exact configured address, launchd PID, and kernel process-start value before
registering that service endpoint. This authenticates only the local service
process; it does not establish a cloud-provider adapter or conversation
binding.

In addition to `service_send`, `service_reply`, `service_claim`, and
`service_receipt`, an authenticated service may use `service_inbox`,
`service_message`, and `service_ack`. These are endpoint-scoped equivalents
of `inbox`, `message`, and `ack`: query and acknowledgement remain bound to
the authenticated recipient and preserve the original-recipient check for
replies and receipts. Independent service configuration does not replace or
restart the OpenClaw participant.

Standalone tmux discovery retains each live candidate found in a distinct pane
for an otherwise-unregistered participant.  If more than one such endpoint is
live, binding and target resolution fail closed as ambiguous; discovery never
silently selects the first pane.

Shared Codex app-server callers use the approved same-owner native conversation
binding. Native thread/session context is matched against the host-owned live
registry; the launcher pane is never substituted for another conversation.
Missing/ambiguous context and mismatching explicit selectors are rejected.
This correlates trusted local conversations; it is not provider-signed identity
or an isolation boundary against malicious same-UID code. See
[conversation identity](unified-conversation-identity.md) for the current contract.

KAI uses a separate enrolled service principal. Every service call still checks
the private credential and current launchd main PID/start. Its mailbox endpoint
is stable for the operator-owned enrollment generation, so an MSG bridge restart
does not lose replies. Changing that generation creates a different endpoint;
old KAI endpoints are not forwarded to the new enrollment. This continuity does
not borrow OpenClaw identity or attest a cloud persona.

The private KAI bridge admits only a bounded number of connections and handles
each admitted connection independently. A slow host RPC therefore cannot hold
the serial accept loop hostage; once capacity is full, a new caller receives a
structured `unavailable` response and is not dispatched. Frame receive and
response send each have their own bounded transport deadline. A timeout or
disconnect never redispatches the request, and a timed-out mutation must not be
reported as having a known result or as a publication success.

When a standalone tmux observation is followed by a registry observation for a
child agent, the host preserves the already-active endpoint ID only after both
recorded PID start values verify and the two processes are proven to share a
live ancestor/descendant chain with the same participant, host, session, pane,
and platform.  Alias, runtime labels, and pane tags alone never authorize this
continuity; a restart or ambiguous lineage remains a new or rejected identity.

## Bounded delivery diagnostics

`tproj-msg diagnose MESSAGE_ID` is a read-only metadata query. Message parties
can use it. Nonparty maintenance access additionally requires the native caller's
project in the local host's `diagnostic_projects` and the origin host in the
receiving hub's `diagnostic_hosts`. Both lists default empty; a CLI flag cannot
grant this permission. Ordinary `message` authorization remains unchanged.
The response excludes body, payload hash, raw receipt evidence, process commands,
paths, headers, and credentials. It distinguishes delivery state and presentation
confirmation from recipient liveness; neither establishes a substantive answer.
Cross-host diagnosis prefers the recipient host's record and labels unavailable
remote evidence without claiming the sender-side copy is current.

Authorized sender-side diagnosis also includes `federated_outbox` when a saved
outbox exists, even when the destination has no record. It exposes only `state`,
`operation`, `destination_host_id`, `legacy_request_bytes`, `current_request_bytes`,
`request_limit_bytes`, and the unchanged `expires_at`. Legacy bytes reproduce the
old duplicate-body, ASCII-escaped SSH request; current bytes include authentication,
metadata and the newline used by hub forwarding, using the actual UTF-8 serializer.
These sizes are derived from saved evidence, not captured historical transport traces.
Neither size field exposes body or credentials. When remote evidence is unavailable,
local `recipient_online` is cached evidence, not destination health.

Accept/cancel transport omits only the unused `payload.message` duplicate; the
saved submit payload, IDs, body, expiry, ownership and receiver checks stay intact.
Older receivers already consume `record`, `sender` and `recipient`. Peer requests
are bounded before SSH at 262144 bytes. Deterministic `request_too_large` marks
accept delivery rejected rather than transient pending; cancellation records a
rejected outbox and raises the error, never claiming cancellation succeeded.

New uncertain deliveries retain a fixed cause: `receipt_timeout`,
`dispatch_error`, or `adapter_interrupted`. Historical uncertain rows with no
such evidence remain unclassified. Diagnosis never retries, acknowledges,
rewrites, or cancels the message and never synthesizes a cause for old records.

Codex prompt receipts carry native conversation context, including when the
app-server is shared. The host still verifies the caller and exact pinned prompt
hash; a bound native thread/session ID may identify the prompt even when the
immutable endpoint retains its earlier bootstrap runtime label. No alias-based
identity adoption or synthetic acknowledgement is introduced.

Remote resolution preserves the sole authoritative failure (`endpoint_unavailable`,
`no_recipient`, or another protocol rejection) rather than labeling every failure
as a host outage. Multiple failing authorities report only fixed error classes.
Transport timeout, command failure, and invalid protocol response have distinct
fixed diagnostics; no SSH output or credentials are included. This does not
change destination selection, authorize retry, or prove the original cause of a
historical generic `host_unavailable` result.

## Seeing what is stuck: `tproj-msg pending`

`tproj-msg pending` is a read-only list of the messages the caller sent that have
not reached a final state (not presented, not cancelled, not expired), grouped by
recipient with the count, the states and the age of the oldest. It carries no
message bodies and never resends. The group says where the recipient lives, because
that decides how far the sender-side state can be trusted: for a recipient on this
Mac the state is authoritative; for another Mac or a service the sender's hub holds
only the hand-off record, and `tproj-msg message <ID>` asks the owning side. A
service recipient (such as KAI) shows as presented only after the service
acknowledges, which the external tool descriptions now ask it to do once it has read
a message. Until then, the sender-side view cannot distinguish delayed consumption
from an absent, busy, or failed screen. Keep the original ID, use authorized
diagnostic metadata when needed, and await the async answer without creating a
duplicate route. The hub operation is `outbox` (sender-authenticated, current participant
only, last 7 days, at most 500 rows).
