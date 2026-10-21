# Unified messaging

This is the public contract for the unified host-agent transport. It is
**not globally active by default**. The transport is active
only when the local client configuration exists at
`$HOME/.config/tproj/msg-client.json` and contains an explicit
`"active": true` marker. Until that condition is met, the existing `tproj-msg`
legacy routes remain authoritative only on never-enrolled installations.
An enrolled installation never automatically returns to those routes.

Unexpected socket-handler exceptions retain the generic client response
`internal: hub internal error`. Server stderr records only the exception class
and traceback file basenames and line numbers. It must not contain exception
messages, source lines, locals, request bodies, or authentication tokens. This
diagnostic does not retry or duplicate the request.

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

## Explicit recipients and submission identity

Each ordinary send resolves one registered recipient. Identical text sent to
separately named recipients is not evidence of an unauthorized broadcast and
is not rejected by a cross-recipient similarity or time-window heuristic.
No additional approval token or recipient grant is required by this transport.
Authentication does not expand the sender's existing user-authorized recipients
or sharing scope.
Explicit broadcast targets and forged sender/control/task markers remain
forbidden; ordinary messages do not create user authorization or task authority.
The hub's immutable submission ID, not body similarity, identifies a retry:
the same ID and payload returns its recorded result; changing that payload is
rejected. This does not promise deduplication of different IDs with identical text.
Recovery replay protection for the OpenClaw main participant is unchanged.

## Delivery and replies

An accepted message is durably queued, but that is not proof of presentation.
The states are distinct:

1. `queued`/`accepted`: the hub committed the message;
2. `presented`: the target host recorded presentation to the bound endpoint;
3. a reply: a new message linked by the original message ID (`in_reply_to`).

Transport health, a socket write, or a model run does not collapse these states.
Body-free `diagnose` metadata exposes `receipt_state` (recorded receipt state or
null), `reply_count`, and up to 20 `reply_message_ids` ordered by creation time
and ID. The list is bounded, while `reply_count` reports the total; absence
from the first 20 IDs is not evidence that a particular reply does not exist.
These linked replies were authenticated on submission. They let callers
inspect an exact response without interpreting absent ACK as non-consumption.
They do not change the original transport state, assert an explicit ACK, or
prove the requested work completed; callers must inspect the actual answer.
Message query and diagnosis also expose `response_state` (`recipient_replied`
or `unconfirmed`), `recipient_reply_count`, and up to 20
`recipient_reply_message_ids`. These require the exact original recipient as
sender, original sender as recipient, and the same thread and `in_reply_to`.
They conservatively leave endpoint-successor cases unconfirmed. Unlike the
broader linked-reply exploration fields, these identify pinned-recipient response
evidence. An uncertain transport with `recipient_replied` must be described as
"recipient replied; presentation receipt unconfirmed", not as undelivered.
Neither these fields nor a reply synthesize an explicit ACK or task completion.
Old consumers may omit these additive fields; missing fields mean unknown.
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
For Codex CLI, the host may likewise recover presentation from a unique native
rollout pinned to the endpoint thread and project. Only a top-level live user
message with the exact normalized delivery prompt hash counts; compaction
histories, event mirrors, replies, other threads/projects and partial matches do
not. The bounded tail may leave older evidence unknown. This records observed
presentation, not an explicit recipient ACK or requested-work completion.
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

### Workspace launch registration

`tproj` registers the local projects requested by a workspace launch (and by
`tproj --add ALIAS`) through the local host socket's `directory-sync` operation.
It reads the current revision first and sends one bounded update containing only
missing, existing-on-disk local paths. Automatic launches exclude disabled
entries; an explicit local `--add` registers its launched project even when it is
disabled in the automatic workspace selection. Remote and unrelated catalog
entries are not synchronized. Existing project IDs and aliases are preserved.
The host/federated directory performs conflict and stale-revision checks before
mutation, so a conflict or an unavailable optional messaging service leaves the
core tmux launch available and does not replace the catalog. An unknown transport
result is reported without an automatic retry.

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

The host-owned `services.kai.allowed_addresses` is the outbound policy authority.
Each host connection reads one validated, bounded, no-follow configuration file
snapshot. Service list/status and actual send admission use that snapshot; the
consumer cache never grants access. Empty scope is valid (empty list and
`scope_denied` outbound requests). Missing or invalid scope is
`configuration_error`. Inbound reads and exact-party replies do not acquire an
outbound scope requirement. Invalid whole host configuration does not fall back
to old credentials. `service_policy_migrate.py` copies only an already approved
consumer scope into the matching existing enrollment, once and idempotently;
identity, token and generation are preserved, and competing edits or differing
existing policies reject without replacement.

Every KAI request carries the current enrollment generation; omitted or revoked
generation evidence is rejected before endpoint registration. Enrollment
generation rotation is revocation, not native continuity. Old
unpresented pending work becomes `stale_session`; dispatching or externally
accepted work remains uncertain and is never replayed. Policy revocation at host
admission rejects an unissued send, but cannot retroactively cancel an issued
request whose outcome is unknown.

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

Native catalog adoption can annotate an existing endpoint with a `thread_id`
identical to its authenticated `session_id`. In that exact case the host reads
its existing endpoint-native attestation and retains the stored kind when its
ID matches both authenticated fields. The hub's immutable native record is not
rewritten, and different IDs still fail closed. This is not general equivalence
between session and thread namespaces or authority to rebind another endpoint.

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
The integer `sequence` is the message's local hub row sequence, matching the
`inbox` event cursor on that hub. For recipient cursor diagnosis, use the
recipient host's record; sender and recipient hub sequences are not interchangeable.

The native `diagnose` and service `service_diagnose` paths include authentication
and database opening in their read-only boundary. They do not initialize schema,
change pragmas, recover queues, register/retire identities or attest native IDs.
SQLite is opened with `mode=ro` (not `immutable=1`) so committed WAL records remain
visible. Missing/corrupt database or unreadable WAL evidence returns unavailable
or unknown; normal initialization is never a fallback. Current live native
process evidence must match saved endpoint/native evidence; aliases alone do not
grant historical access. Service diagnosis checks the current enrollment
generation and launchd process without registering it.

Only ENOSPC, EDQUOT and SQLite SQLITE_FULL classify as `resource_exhausted`.
SQLite classification requires the exception's numeric error code (available
in Python 3.11 and later). Older runtimes return a generic failure when that
code is unavailable; error text is not used to infer exhaustion. Neither
failure acknowledges an uncommitted message. Existing committed originals
remain intact, and capacity recovery preserves the original submission ID.
The `resource_exhausted` response's optional metadata contains a bounded
`failure_stage` and `acceptance=unknown`;
even a locally failed attempt cannot disprove acceptance of an earlier attempt
with the same submission ID. Diagnosis is metadata-only and may itself be
unavailable on a full disk. Preserve the stable ID and body; do not create a new
send or automatically replay an uncertain outcome.

Generation-enforcing host and generation-capable adapter updates belong to the
same maintenance window. A legacy adapter that omits generation cannot operate
between host enforcement and adapter activation; report that interval as service
unavailable, not preserved legacy availability. If the compatible adapter is
already active, verify its generation envelope before tightening the host.

Dependent activation requires capabilities from running owner/backend sockets,
then the running host, before installing the consumer. Imported source modules
are not proof of loaded capability. Unsupported activation leaves current tools
and diagnostic paths unchanged. Messaging compatibility is independent of task
master capability checks; neither a successful probe nor status proves recipient
consumption.

Inbox/claim pages retain the conservative 200000-byte message budget. An
individually larger first message is returned alone when its complete success
response fits the 262144-byte wire limit, including the response wrapper, default
JSON spacing, and newline. This preserves message order, body, ID, and inbox
cursor progress. Query uses the same full-frame bound, including receipt-derived
fields. An accepted message whose response cannot fit raises the sanitized
`response_too_large` error rather than an empty page or an indexing failure;
messages are never skipped or truncated to make a response fit.

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

### Already-replied automatic delivery

A persisted, authenticated exact-ID reply from the original recipient suppresses
automatic claim of its original message. The hub rechecks this evidence inside
the atomic `begin_present` transaction, covering a reply committed after claim
but before presentation begins. Reply destination endpoint rotation does not
invalidate this evidence: reply ingress already authenticates the original
recipient and thread. No receipt or `presented` state is fabricated; history
remains queryable. Reading an inbox list alone does not suppress delivery.
Once presentation has begun (`dispatching`), this gate cannot retract the paste
or stop work. Later explicit user stop instructions remain authoritative.


### Same-native endpoint continuity

The owner host persists an immutable endpoint/native association only after local
process binding and native registry/catalog adoption authenticate the caller.
This is a separate messaging record, not a formal task binding. Public request
selectors, alias equality, tmux session/pane, or a new endpoint alone never prove
historical continuity. Both endpoint incarnations must have retained owner-host
attestations for the same native ID and native ID kind, host, participant, and
platform. The historical endpoint must be retired and the successor must be the
unique current participant endpoint with a fresh heartbeat. Missing, conflicting,
ambiguous, different-thread, or stale evidence fails closed.

A proven successor may query historical party messages and reply by exact message
ID. Original sender/recipient IDs and message thread IDs remain unchanged; replies
are new messages addressed to the proven current incarnation. This does not resend,
redispatch, retarget arbitrary aliases, alter task ownership, or grant general
historical inbox/receipt/cancel access. Query returns `reader_is_recipient` so the
host's reply boundary retains recipient-only authorization across rotation.

Federated exact-ID resolution asks the historical endpoint's enrolled owner for
the current endpoint. The receiving owner checks its own continuity record; a
rotated replying recipient is attested by its enrolled sending owner with exact
historical/current endpoint and same host/participant/platform constraints.
Foreign cached endpoint rows are not native continuity authority.

Migration creates empty continuity storage. Existing endpoint/message records do
not contain historical native identity, so past rotations cannot be retroactively
recovered from them. An authenticated current caller does not backfill a retired
endpoint. Historical recovery requires independent owner-host historical native
evidence; no recovery command or inference-based fallback is provided.

Upgrade hubs (schema and `native_attest`) before dependent hosts. If a new host
encounters an older hub's `unknown_op` for attestation, ordinary current-endpoint
operations remain available, but no continuity evidence is created. Identity or
other attestation errors are not ignored. Same-native continuation is unavailable
in mixed-version deployments; complete both owner upgrades before relying on it.

## Accepted-result continuity across endpoint revocation

Federated ingress authenticates the enrolled sender owner and validates immutable
recorded payload/parties before resolving a current recipient. An already
accepted exact-ID envelope returns its recorded result without registration or
new delivery, even after recipient generation revocation. A changed immutable
payload conflicts; an unaccepted envelope still requires current destination
validation. Sender retry responses preserve the recipient's recorded state
rather than replacing it with a fresh queued result. A malformed or mismatched
acceptance response keeps the outbox pending with outcome unknown; it neither
marks delivery successful nor raises an untyped exception that stops retries.

Read-only cross-host diagnosis may carry an owner-verified historical-party
attestation after the local host has authenticated current same-native
continuity. The peer checks that the pinned party belongs to the authenticated
owner, appears in the exact recorded message, and matches the current native
participant/platform. This uses the existing enrolled host trust boundary, as
historical replies do; aliases or caller assertions are not proof. The verified
party is an internal argument, not a public operator flag, and does not register
new endpoint/native evidence or authorize delivery. A forged/mismatched party is
rejected.

The sender stores the validated acceptance state in the same atomic outbox update
as its delivered marker. Subsequent exact-ID retries return that saved authority
state without contacting the recipient, rather than resetting it to queued.
Pre-upgrade delivered rows lacking this evidence report host_unavailable; they do
not fabricate a queued result or initiate new delivery. Read-only diagnosis remains
available to inspect existing recipient evidence.

Writable schema migration serializes its column check and ALTER in a write
transaction; concurrent constructors recheck after obtaining that lock. Read-only
constructors do not enter the migration or acquire a write transaction.

### Explicit caller selectors on same-ID retry

`--retry SUBMISSION_ID` preserves the stored operation, destination, body and
submission ID. Explicit `--session` and `--as` options replace only the caller
selectors for that attempt; omitted options retain their saved values. The host
still authenticates the current caller and enforces sender/idempotency checks.
The saved submission is not rewritten. `--session` selects the workspace session,
not a native thread/session UUID returned by `whoami`.

### Live endpoint discovery versus retained history

Host discovery, service attestation and event retry lookup request the
authenticated host-local `endpoints_list` with `active_only: true`. Retired
endpoint history remains stored and available to the unfiltered diagnostic
query, but is not serialized into live discovery responses. Historical growth
must not prevent current KAI attestation by exceeding the wire frame limit.
The filter does not revive endpoints, extend liveness, change enrollment or
relax caller authentication.

Live tmux fallback inspects both the pane root process and its descendants. A
pane that directly execs the agent remains discoverable after an advisory model
registry entry expires. Each candidate must still pass the same live PID/start,
UID and agent executable checks; a shell or pane tag alone proves no identity.

A rejected retired endpoint registration is isolated to that candidate. Discovery
continues for independent live participants. Retired identities are never revived
and no replacement identity is invented to bypass retirement. Registering an
actually new agent process still follows normal authenticated discovery.

### Disconnected broker clients

Each concurrent socket request releases its processing slot even if closing the
buffered response stream fails after a client disconnect. Repeated disconnects
must not leave a live broker permanently rejecting all new connections. This
cleanup does not acknowledge delivery or retry an uncertain message.

Native caller binding requests `diagnostic_identity` with `active_only=true`,
filtering both endpoint and native-marker rows to current endpoints on the
authenticated host. Retired history remains stored and available through the
existing unfiltered diagnostic operation; it is not sent on every caller bind.

Pane fallback discovery skips shell executables even when their `-c` arguments
mention Claude or Codex. A launcher wrapper is not an agent endpoint; discovery
continues to its live same-UID agent descendants with their own PID incarnation.

Registry process ancestry does not prove a Codex thread belongs to a pane's
project: a shared daemon may retain the launching pane's environment. When
host-local native thread metadata contradicts a registry record's project,
discovery rejects that record rather than letting it suppress live tmux fallback.
The existing native catalog/rollout, unique-project adoption and live process
checks still apply. A conflicting thread in the same project is not replaced.

### Delivery summary without rewriting evidence

Exact message/query and metadata-only diagnose return the same optional
`delivery_summary` object; the KAI message projection preserves it. It is a
read-only projection, not a delivery action or a new authorization gate. Existing
`state`, receipt/ACK evidence and authenticated recipient reply evidence remain
unchanged. Older consumers may ignore this additive field.

`status` is waiting, presentation_confirmed, recipient_replied or action_required.
`lifecycle` independently retains active, ttl_elapsed or the recorded terminal
state. `reason` explains their combination. `ttl_elapsed` is a clock observation,
not proof that a prior presentation did not happen. `new_presentation_eligible`
means only lifecycle eligibility (active pinned endpoint, unused presentation
state, unelapsed TTL), never sender authorization or permission to retry.

A deadline-past dispatching/uncertain message without presentation evidence has
reason ttl_elapsed_outcome_unknown, action_required, and false new-presentation
eligibility; it is not rewritten to expired or replayed. A late valid receipt
can still confirm the presentation under the existing receipt contract. Exact
recipient replies remain separate from presentation/ACK and work completion.
Explicit cancelled/expired/rejected/stale_session states take summary priority,
including a _with_reply reason if a late reply exists. A reply does not hide
cancellation or expiry. A deadline-past confirmed presentation still reports
presentation_confirmed with lifecycle ttl_elapsed; the deadline does not erase
the existing evidence. The summary never extends TTL, changes pinned endpoints,
synthesizes receipts, or starts a delivery.

Message query and diagnose are read-only even after TTL or when a query is
rejected by party authorization. Query does not persist an `expired` state for
accepted/queued/adapter_received rows: both views project ttl_elapsed from the
same stored state. Delivery admission still checks TTL independently in claim
and begin_present, so a stale stored state is not permission to deliver.

Owner-host identity diagnostics accept optional `endpoint_ids` (1–32 nonempty IDs,
at most 128 characters each) alongside `active_only`. Both endpoint and native
evidence rows are filtered within the authenticated host, including retired rows
when requested. Cross-host IDs return no rows; selectors never grant message
access or change identity. Use this bounded view for historical continuity
instead of fetching an ever-growing retired-endpoint inventory.
This bounds selected endpoint count, not the entire response size: host-owned
project metadata and individual field sizes still contribute. Oversized responses
remain explicit failures; never silently truncate or retry without selectors.

The existing delivery worker refreshes endpoint/process evidence at message
boundaries, including during historical uncertain-receipt recovery, rather than
only after an entire backlog. A refresh that removes an endpoint stops further
processing for that immutable endpoint. This does not relax heartbeat freshness,
create a second scheduler, replay unknown deliveries, or guarantee progress during
a single blocked operation longer than the heartbeat TTL.

An authenticated native endpoint need not have a tmux pane. Terminal delivery
requires a nonempty pane string; otherwise the original remains pending with
`endpoint_unavailable`, without terminal access, presentation claim, input
mutation, endpoint retirement, or replay. Other endpoints continue through the
same worker. Existing historical receipt recovery remains available separately.
This is an unavailable terminal surface, not proof of an invalid native identity
or a completed native ingress implementation.

### Native peer reference provenance (preparation only)

The native-notice primitive is not an enabled ingress adapter. It prepares a
small reference, never a copy of the original body, from an existing pinned
`deliveries` row. The same host journal retains only its token, immutable content
digest, native ID/kind, endpoint/incarnation and stable client ID in
`native_notice_metadata`. This metadata has no message body, pending list, cursor
or scheduler and is not another mailbox or an approval source.

The host supplies independently authenticated endpoint/native attestations, not
selectors from a peer body. Same-original preparation must preserve content and
binding or fail with conflict. The exact generated prompt digest is retained.
Verification is read-only, checks the stored
original and current binding, and rejects a changed token, thread, incarnation or
endpoint. Its result establishes peer provenance only, never user approval,
presentation, execution permission, cancellation success or expiry eligibility.

Native queue records may otherwise look like ordinary `user.text`. The queued
reference keeps the peer marker and excludes the original's authority claims;
existing approval and role classifiers must still reject it as direct user input.
The consumer must read the actual live record from the pinned transcript, check
its header/project binding, and use entire-record reference verification. Token
verification alone does not attest the full received text; appended, mixed or
changed content fails without direct-user fallback. Local journal/transcript
correlation retains the existing same-OS-user trust level, not provider-signed
attestation.
Body retrieval must separately recheck the authoritative original's latest
cancellation, TTL and sharing scope; later effects require the existing execution
scope/cancellation check. The primitive alone does not implement that consumer,
queue idempotency, coalescing, generation fencing or native delivery. A stable
client ID is a correlation key, not provider deduplication. Normal historical
message queries and established authorized carry are unchanged.

### Native presentation reservation (consumer integration pending)

`native_begin_present` is the owner-host authenticated, one-shot presentation
reservation for the prepared native reference. In the same transaction as the
existing `dispatching` transition it checks the current non-retired recipient,
Codex platform, persisted native attestation, exact endpoint incarnation and
canonical immutable original content digest. It also checks maintenance, current
cancellation/terminal state, expiry and prior recipient reply. A mismatched or
missing binding fails without advancing the message. The returned binding is a
presentation permission for that exact original, not a user approval, task grant,
body-consumption receipt or execution permission. Current authenticated host and
service scope restrictions remain independent; this operation creates no sharing
grant. Legacy `begin_present` remains unchanged for existing consumers.

Duplicate requests after reservation fail rather than re-expose the body. An
unknown reservation result requires existing-state reconciliation, never blind
re-enqueue or presentation retry. Later cancellation retains existing too-late
semantics; the execution side must still validate its scope/cancellation before
external effects. This primitive does not prove automatic consumer integration,
crash recovery, queue generation fencing, lost-wake prevention or any receipt.

### Authenticated native body consumer (activation pending)

The Host `native_resolve` operation authenticates its calling native process
through the normal caller binding before resolving a reference. It remains
unavailable unless `native_consumer_enabled` is explicitly true in that Host's
configuration. `messaging_capabilities.native_consumer` reports the loaded backend
version and activation flag; it is not queue/provider acceptance. Installing the module does not register a hook, queue a notice,
activate this setting or change a user's running conversation.

The preprompt consumer independently reads the exact native transcript selected
by the persisted owner-host attestation, checks its native CLI header and project,
and requires the hook's native ID/path/project to match. The complete hook prompt
must match the immutable notice digest, not merely contain its token. The current
Hub original must match the pinned immutable content. After checking response size,
the consumer durably transitions the original local delivery from `received` to
`dispatching` before requesting `native_begin_present`. Only an exact successful
reservation binding permits returning the original body as JSON external-peer
additional context. Neither this context nor its storage as a provider developer
record is a direct user approval or new grant; existing authenticated KAI carries
keep their independent stated scope. No body is silently truncated.

A lost response or failure after local reservation leaves `uncertain`; subsequent
resolve attempts never return the body again. A persisted native reference excludes
that original from terminal paste and legacy user-prompt receipt matching. This is
one-shot body exposure, not crash-safe exactly-once execution or guaranteed recovery
from a pre-context crash. The hook blocks an unavailable/malformed reference rather
than letting it fall back to a direct user prompt; ordinary prompts are unaffected.

Recovery examines only a bounded tail of the pinned native transcript. A reference
record alone is insufficient. Both a valid complete reference and the exact prepared
peer additional context must be recorded in the same native turn, with the provider's
`hooks.additional_context` kind, before reporting `presented`. This proves native
context recording, not provider request acceptance, model consumption, explicit ACK,
reply or task completion. Missing/old/other-turn evidence stays unknown. Presentation
receipt does not cancel effects; the execution side still owns its scope/cancel check.

Production queue publication/reconciliation, notification generations/no-lost-wake,
consumer cutover fencing, Goal-operation isolation and provider-wide activation
remain required before enabling native delivery. No legacy paste fallback is a
substitute for those acceptance requirements.

The pinned Codex 0.163 hook engine defaults additional context to a 2,500-token
spill threshold. Before production hook activation, configure and prove an
`additionalContextLimit` sufficient for the accepted full-message wire bound;
a spilled file/reference requiring discretionary model fetching is not full-body
acceptance. The exact-context recovery rule will not promote a spilled or altered
context to `presented`. The small-body native fixture is not max-body acceptance.

Local reconciliation stays `dispatching`/`uncertain` until the authoritative Hub
confirms `presented`. After a receipt transport error, the next tick reads Hub
state first: an already matching receipt closes the local row without another
receipt call; otherwise valid native context evidence can synchronize the receipt.
Neither path returns the body again. Local context recording must not prematurely
remove a Hub-unconfirmed row from reconciliation.

### Existing-socket Codex queue transport (scheduler integration pending)

`native_queue` uses only one existing owner-private Unix control socket and the
provider's `initialize`, `thread/queue/add` and bounded `thread/queue/list` RPCs.
It never starts a daemon, resumes/starts a thread, invokes a model or retries an
operation. The caller must supply independently authenticated native binding and
an immutable prepared reference, and durably record its publication attempt first.
The normal control-socket symlink is allowed only when owned by the caller and
resolving to a same-owner socket with no group/other permissions.

The optional Python `websockets.sync.client` dependency must be available in the
actual runtime. Missing dependency/socket/transport is explicit unavailability,
not successful delivery; it does not affect core tmux startup. Version 16.0 is
covered by the isolated installed-runtime fixture, not an all-host assumption.

Stable client IDs are correlation only: Codex does not deduplicate them. After an
add may have been sent, missing/malformed results and generic provider errors are
`publication_unknown`; only explicit method-not-found/invalid-params errors are
known rejection. No exception triggers replay, a different socket, runtime spawn
or a new client ID. Oversized frames fail explicitly rather than truncating queue
history. This transport primitive alone does not implement durable publication,
queue/history reconciliation, cutover fencing, no-lost-wake or provider acceptance.

Response validation follows the pinned Codex App Server profile (`rpc.rs`):
`jsonrpc` is intentionally absent in native responses; if explicitly present it
must be `2.0`. Response IDs have the exact requested type/value, result/error are
exclusive, and an error requires integer code plus string message. Malformed
post-send envelopes never establish known rejection. Add success additionally
requires the returned queued ID, exact correlation ID and original text input;
list results retain the opaque `nextCursor`, so absence on one 32-item page is
never proof of absence from the whole queue. Incoming unrelated messages do not
reset the per-RPC response deadline. The caller must also isolate potentially
blocking transport I/O from heartbeat scheduling before production integration.

### Durable publication controller (scheduler cutover pending)

`native_publication.Publisher` records reference-publication metadata under the
reserved `_native_publication` member of the existing private delivery envelope.
It does not change original content-digest fields, delivery/receipt state, create
a mailbox, introduce a second scheduler, or store an original body elsewhere.
The attempt ID and controller generation are committed before any queue I/O;
metadata updates use an envelope compare-and-swap and cannot reset body state.

One bounded, non-AI Python child handles each queue add/list request on the
existing socket. Private request files contain reference metadata, not the peer
body. The controller drains bounded stdout without waiting for network I/O;
its 15-second child deadline kills only that owned child and retains publication
unknown. Children never resume a thread or start a provider. Existing scheduler
integration must call `maintain` each tick, including ticks not visiting that row.

A process restart fences interrupted publication into a new generation and
`unknown`, not `ready`. Late results cannot overwrite a new attempt/generation
or a body-reserved reference. The publication label `body_reserved` means only
that the original local body-reservation/receipt path has started; it does not
claim queue consumption or model consumption. Historical unknown terminal
injections are never converted to new native references. A new reference needs
the latest Hub presentation-eligible original. Known pre-add failures may be retried with the exact same
reference after backoff. Both unknown results and acknowledged references use bounded paginated queue
inspection: CID plus the entire reference text must match. An incomplete page
never authorizes another add. An exhausted scan without that reference records
`reference_absent`, which is **not** evidence of non-consumption or failed delivery.
Only a still-`received` native original may then generate the same immutable
reference wake after the existing backoff and a fresh Hub eligibility/content
check. Token, CID, original digest and endpoint/native binding stay unchanged.
The independent consumer CAS rejects every duplicate before returning a body;
`dispatching`, `uncertain` and `presented` bodies are never returned again.
This reference-only at-least-once recovery does not resubmit the original, repeat
work, or erase unknown publication history (`last_unknown_publication` retains
the last uncertain attempt/generation). A queue ACK is not a body receipt.
Read-only reconciliation is not blocked by another queued reference. A queued
leader which is no longer Hub-eligible cannot starve later eligible originals,
even when that old leader is no longer returned by claim.
The existing native consumer still owns the one-shot body reservation and context
recording evidence.

This controller is not yet the provider-wide scheduler cutover: fair claim
pagination, complete no-lost-wake acceptance, conversation-level pending-set drain,
crash/history convergence, hook/carry activation and CC ingress remain incomplete.
Neither queue nor consumer flags are enabled by installing these modules.

Every new add attempt, including a known-unsubmitted retry, rechecks the latest
Hub eligibility and immutable original immediately before committing its attempt.
A prepared reference is not a cached permission to notify after cancellation or
expiry. Ineligible originals stop new publication. Unknown attempts must first
complete queue reconciliation; reference-only recovery is permitted only under
the one-shot body fence described above. A child-job exception is isolated, removed and
recorded unknown under its matching attempt/generation, so it cannot remain a
phantom live job or stop collecting other jobs.

### Bounded fair claim scan

The existing authenticated recipient `claim` accepts optional nonnegative integer
`after_sequence` (signed 64-bit). This uses the existing messages row sequence,
not a new queue. It returns `next_sequence` for the last returned row, or zero
only at SQL end. A probe-filtered empty page advances to the raw scanned
sequence instead of wrapping; a size-bounded nonempty page advances only through
returned rows. The Host visits one row per endpoint per tick and wraps on
the tick after SQL end, so an old adapter-received message cannot
permanently hide later messages. Default callers retain created-at ordering.
The cursor is a volatile scheduling hint, not consumption, notification-drain
completion, cancellation permission, or a no-lost-wake guarantee. Restart may
scan old rows again, but existing durable presentation/unknown fences remain
authoritative; claiming never authorizes replay.

### Native publication scheduler connection (inactive by default)

Host uses its existing delivery tick, not a second scheduler. Every tick first
maintains all owned publication jobs, including when delivery is disabled or
the original endpoint/claim row is not visited. With `native_queue_enabled`
true, fresh received Codex rows select native routing before any terminal
operation. Missing consumer enablement, failed identity or transport leaves
the row pending with an adapter diagnostic; it never falls back to paste.
Route selection is pinned as `_native_route=native-v1` in the existing local
delivery envelope before prepare/identity/I/O. This pin survives restart and
flag disablement; neither makes terminal delivery eligible again.
Previously native-owned rows retain their receipt-recovery path even with flags
off. Historical legacy uncertain/dispatching rows are not re-published. This
connection alone does not prove conversation notification coalescing, durable
pending generations, no-lost-wake, Goal carry, or provider acceptance. Both
native flags remain false until those activation prerequisites are proved.

### Native pending generation and drain

`native_pending` and `native_drain` require the authenticated owner host, active
endpoint, immutable incarnation, and exact persisted native kind/ID. The
generation is MAX existing message insertion sequence for that endpoint: the
message insert itself advances it atomically, without another mailbox/table or
separate generation update. The methods return metadata only, never bodies.

`native_drain(generation)` uses the existing Hub BEGIN IMMEDIATE transaction.
It records a drained generation in existing metadata only when that generation
is still current and no unexpired, unanswered, new-presentation candidate
remains. Insert after an empty snapshot therefore prevents stale clearing.
Insert after clearing advances the sequence and restores wake_needed. Crash
before drain leaves the same pending generation discoverable on restart.

This is notification bookkeeping, not receipt, consumption, completion,
permission to replay, or a new execution grant. It does not reactivate expired,
retired, cancelled or uncertain effects. Consumer notification coalescing and
activation must still be connected and separately demonstrated; these Hub
primitives alone are not end-to-end no-lost-wake acceptance.

### Bounded native pending-set consumption

With native queue enabled, Host journals a bounded claim page (up to 32) before
starting its first transport child. An authenticated reference hook coalesces
up to 32 same-endpoint received originals into one context, under the existing
wire bound; no body is truncated. The reference remains pinned to its leader.
All member notice/binding preparations run before the first irreversible body
reservation; a later predictable notice rejection cannot strand a reserved
leader. Every member separately validates its immutable original and passes the latest
Hub native presentation reservation (maintenance/probe/cancel/TTL included).
Failed later reservations expose no body and retain uncertainty; leader failure
blocks the reference. Each successful member pins the shared reference ID and
whole-context hash in its existing delivery row. Recovery requires that member's
immutable original plus the exact shared reference and context in the same turn.

Consumer snapshots pending generation before reserving and attempts generation-
matched drain afterwards. New unclaimed arrivals remain Hub candidates and
prevent stale clearing. Drain errors do not revoke an already issued context.
A crash before final context-hash commit leaves unresolved reserved effects,
not permission to return bodies again. Native feature flags remain off pending
full provider/carry/cutover acceptance; this connection is not a blanket
end-to-end reliability claim.

### Native context size and hook spill boundary

Normal requests, Hub query frames and non-native client responses remain
256 KiB. Only the authenticated `native_resolve` response has a bounded 1 MiB
client/consumer envelope, to accommodate JSON escaping of wire-bounded original
bodies without truncation or a permanently blocked oversized leader. Batches
stop before that limit; unreturned originals remain pending. Exact-record
recovery reads a bounded 4 MiB tail, enough for the maximum context frame and
its shared reference at immediate recovery (not arbitrary historical proof).

Codex 0.163 native hook activation must set `additionalContextLimit: 0` only on
the native consumer command. In that version zero disables additional-context
spill; the product's 1 MiB response bound remains effective. This must be
confirmed in loaded hook configuration before activation, not inferred from a
wrapper or a source file. Do not change unrelated hook limits. The native
flags remain off until this and the remaining carry/provider gates pass.

### Runtime generation and concurrent consumers

Existing runtime setup records `_native_runtime_expected` in the existing Host
configuration. A contract-version change participates in the existing changed/
LaunchAgent reload decision; unchanged setup does not reload again. A nonzero/failed reload is
reported unavailable, never reloaded. Even a successful reload command still
requires a loaded-capability readback. It does not
turn on either native feature flag. Expected configuration is not loaded proof.

`messaging_capabilities.native_runtime` reports the loaded Host version, loaded
consumer version and native response limit independently of that expected field.
Version 2 identifies the Host's pinned/batched native routing and the consumer's
coalesced, preflighted, large-frame path. Compare these plus installed artifacts
and actual behavior before activation. Hook trust/no-spill and Goal carry still
require their own direct evidence; version numbers do not grant authority.

Two concurrent hook consumers share the existing per-original received-state
CAS and latest Hub reservation. Exactly one can return that original body; the
loser remains rejected rather than reopening effects. Publisher attempt and
generation fences remain separate from endpoint incarnation/native identity
and from this build-contract version. An adapter's existing exclusive startup
lock prevents simultaneous delivery schedulers on its socket. No new lease,
mailbox, scheduler or permission registry is introduced.

### Read-only native user-Goal evidence

The existing approval module provides `native_goal_evidence` and
`validate_native_goal_evidence` as read-only selectors, not new approval
admission or Goal-tool permission. Caller must validate the native rollout
header/project/identity and pass top-level live stream records. Only exact
host-typed `user.goal` user messages with a unique record ID, creation time,
single text item and version-matched JSON Goal format are accepted. Plain peer
text, automatic `goal.internal_context`, nested replacement histories and
omitted/malformed objectives cannot create evidence.

Evidence hashes bind native ID, setter record ID/time, latest lifecycle record
ID/time, objective hash and status. Clear/omitted/new objective invalidates the
old setter; clear then same-text set does not revive an old hash. Explicit
paused/blocked/complete/limited states reject validation. Absent status is
reported as unknown if no status is known; objective-only edits preserve a
previously known status, matching native GoalSet semantics. Neither case grants
new execution permission. This is the same
host/local-transcript correlation trust level as existing direct evidence, not
a provider signature.

Every result explicitly has `execution_authorized=false`. Operation-specific
scope, exact current Goal target and latest cancellation must still be checked
at use, including KAI carry and external effects. The public task approval
path is unchanged: it must not persist this reader output as a permanent grant
without current-setter revocation checks. Production native ingress remains
off until that integration is proved without blocking valid existing carry.

### Optional native queue dependency

The unified installer accepts `--native-queue-dependency` to provision only the
optional queue library in its private module directory, using the universal
websockets 15.0.1 wheel and the pinned PyPI SHA-256. This release supports
Python 3.9; no global pip installation, package setup script, native extension
or OS permission change is involved. Default core installation remains offline
and unchanged. `--check --native-queue-dependency` verifies that artifact.

The transport prefers this adjacent owner-controlled wheel via zip import,
verifying its hash and ownership before any socket I/O. Conflicting/tampered
artifacts or an already loaded different library are unavailable, not silent
fallback or permission to publish. Without an adjacent wheel, the existing
optional installed-library path remains compatible. Provisioning does not
enable native consumer/queue flags or prove remote Codex/provider acceptance.
Pinned package metadata: https://pypi.org/project/websockets/15.0.1/ .

### Loaded Hub native capability

Authenticated local and peer capability views share the same Hub implementation
and report `native_runtime.hub_version` plus the native reservation/pending/drain
operations. Federation preserves a valid peer Hub version instead of reporting
only disk placement or dropping that generation. An older peer with no version
remains unknown; ordinary core messaging is not disabled. These read-only
capabilities neither claim successful native presentation nor grant authority.

After distributing Hub/Federation changes, reload only the existing Hub service,
keeping Host native flags off. Match loaded capability readback to the installed
version; preserve all mailbox rows and unknown effects. No old-message replay,
TTL extension, identity reassignment or provider restart belongs to this step.

### Per-recipient scheduler fault boundary

Loaded Host generation 3 includes this boundary; consumer generation remains 2.
The existing expected/loaded runtime contract reports the difference without
enabling either native feature or changing any authority.

An expected claim, transport, malformed-response, or local SQLite failure for one
recipient ends only that recipient's current tick. The same scheduler continues
with the other recipients; it does not create a replacement worker or resend an
original. Only uncommitted local work is rolled back. Already committed body
reservations, uncertain effects, receipts, and publication attempts are retained.
Global refresh/authority failures remain global and are not treated as delivery
permission. Unexpected programming errors are not reclassified as normal delivery.

Host generation 4 also discards a connection whose rollback fails, then opens
the same existing journal without startup recovery or schema creation. Committed
reservations and unknown effects are not reset. A failed reopen stops that tick;
the next tick must reopen before job maintenance or recipient processing. Missing
or schema-damaged journals are not silently replaced by a blank ledger. This is
local SQLite recovery, not a new messaging connection or authority grant.

### Observed waiting reason and age

Query and diagnose compute the same `delivery_summary`, without updating rows.
For status `waiting`, `pending_age_seconds` is nonnegative elapsed time since
that original was accepted, not time spent busy or an answer deadline. Otherwise
it is null. `reason_observed_at` dates a recognized adapter observation only
when its receipt state still matches; stale-state, malformed or future observations
do not override the summary. Terminal, presentation, reply and TTL precedence is
unchanged. An observed `busy` is not a fresh proof of what a model is doing.

`native_queue_accepted` records the past add ACK; `native_queue_pending` records
a positive list match at the observation time. Neither is model receipt, proof of
current queue contents after that time, or a claim that a tool is busy. `native_publication_unknown` means notification
publication/reconciliation was not confirmed. `native_retry_pending` means only a
reference wake may be retried under the existing eligibility and one-shot fences.
These optional diagnostic writes cannot block publication on transport failure.

Only the authenticated recipient-native `native_pending` view returns
`oldest_pending_age_seconds` over its existing raw pending candidate set; empty
is null. It is not presentation permission and is not returned to an original's
sender as cross-message metadata. CLI and KAI preserve the same per-original
summary; schemas admit its additive age/observation fields. Hub generation 2
identifies this projection; existing native feature flags remain unchanged.

Wait observations are bound to the reporting endpoint incarnation. Native
observations also retain the immutable notice binding and publication attempt/
generation, checked against current native attestation. Old-incarnation or
old-native observations do not become current reasons merely because the message
state is unchanged. Older unbound evidence remains historical diagnostic data.
Host generation 5 includes this optional reporting path; it does not enable native
publication or consumer features.

Within the same summary, an authenticated reply takes precedence over a
presentation receipt, while `presentation_confirmed` remains true as independent
evidence. Cancellation/expiry/rejection lifecycle precedence is unchanged. A
reply still does not establish task completion.

### Live native owner preservation during discovery

Host generation 7 does not treat discovery of another process for the same
participant as proof that the old owner disappeared. Retirement requires
positive PID absence or PID-start mismatch. Unknown process evidence leaves
the persisted identity active, without granting new caller authority.
When the old same-UID native process incarnation is independently verified
alive, it remains a caller candidate alongside the new process. Its complete
persisted binding is retained: project ID/path/address also carry routing or
diagnostic authority and are never borrowed from the new candidate, just as
native IDs, PID/start, runtime and endpoint binding are never borrowed. Multiple live recipient candidates
remain ambiguous rather than silently choosing or retiring one. This guard is
not same-native delivery handoff and does not revive historical stale messages.

### Bounded live target catalog

Target directory participants expose only non-retired endpoints. Historical
endpoint rows remain intact and accessible through the authenticated endpoint
diagnostics; they are not repeated in every local/federated target listing.
Online still requires a recent heartbeat, and a non-retired offline endpoint is
not silently discarded. This projection does not alter recipient resolution,
authorization, immutable messages, or delivery eligibility. Wire limits remain
enforced; this is not an unlimited catalog-size guarantee.

### Receipt cancellation and owner fencing

Receipt endpoint ownership and current message state are validated inside the
same BEGIN IMMEDIATE transaction as receipt persistence. A cancellation or
endpoint retirement committed before this transaction cannot be overwritten by
a receipt validated against an earlier snapshot. A receipt committed first
retains its existing lifecycle semantics. This does not transfer delivery rights
or authorize replay of a retired original.
