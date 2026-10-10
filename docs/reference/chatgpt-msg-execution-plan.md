# Ordinary ChatGPT chat messaging: reviewed execution plan

Status: substantive external-assistant review incorporated; implementation and
live acceptance remain incomplete. This plan refines the existing Phase 1
scope, not task authority or automatic conversation resumption.

## Outcome

Two independent ordinary ChatGPT app chats communicate with an external
assistant and a native AI session. Each original chat reads its peer's actual
reply. Knowing the other chat's message ID does not grant access. Existing
assistant and native identities, permissions and sessions remain unchanged.

## Current evidence and limits

- Capability diagnostics, shared skill boundaries, enrolled binding registry and
  optional request-local dispatch exist. Configured dispatch denial cannot fall
  back to a fixed service identity.
- Registry/dispatcher fixtures do not establish a production authenticated ingress.
- The deployed fixed-service stdio runtime is not ordinary-chat enrollment.
- Supported Chrome Computer Use now reaches an ordinary ChatGPT web chat and
  the existing plugin catalog. A capabilities-only UI response reports fixed
  service authorization and isolation not configured. Independent tool receipt
  and real two-chat acceptance remain open; the denied desktop branch is not
  bypassed.
- Fork behavior is not guaranteed: distinct trusted identities are isolated;
  indistinguishable provider identity copies cannot be separated by the backend.

## A. Establish the actual ingress contract

### Select ingress and return route together

The acceptance unit is the actual reply body returning to the original chat,
not the existence of a registry or a successful catalog update. Classify the
actual test chats before choosing an adapter; a cloud conversation URL alone
does not establish Work mode or Events support.

| Surface | Return route candidate | Limit |
| --- | --- | --- |
| Ordinary non-Work ChatGPT | Authenticated inbox/message tool result; active app UI can offer an explicit "pass reply to conversation" action | No verified arbitrary-chat backend posting API; UI availability is not idle-chat resumption |
| Work chat on web or desktop Cloud; dots | Authenticated MCP Events subscription notifies its owning chat, then that chat pulls the message body | Requires MCP 2.0, verified callback, persistent authorized subscription; webhook receipt is not body consumption |
| Local Codex/native CLI | Existing enrolled adapter; app-server thread operations only where the actual connection and ownership are verified | Local thread IDs are not consumer ChatGPT conversation IDs |
| Authorized Web UI delivery | Reconfirm the original target, submit a clearly attributed external reply and read back the matching post | Paste, submit, visible post, model consumption and generation completion are distinct |

MCP tool `content`/`structuredContent` carries the reply to the model; result
`_meta` alone does not. An active app UI may use `ui/message` or
`window.openai.sendFollowUpMessage` in its hosting conversation. This is not
an API for selecting arbitrary closed chats. Keep notification, UI display,
context update, follow-up submission and model activation separate.

Reuse existing participant/mailbox state. Separate durable `participant_id`,
unique `address`, authenticated conversation `binding`, transient
`endpoint/incarnation`, typed live `return route`, and mutable display `label`.
Labels never authorize access or restore a binding. Return replies through the
original message's sender binding, not a responder-supplied URL or destination.
Endpoint restart alone must not create a new participant.

The next decision packet must contain the actual A/B surface, independent
tool-invocation/context evidence, and a compatible return route. Missing ingress
provenance is not repaired by manual pull, OAuth alone, or a different transport.
Do not replace an ordinary ChatGPT conversation with an API Conversation.

Produce a source-backed table for the existing tunnel before selecting an
architecture:

| Guarantee | Evidence required | Current status |
| --- | --- | --- |
| Verified caller origin | Actual transport verifier and its trust boundary | Not established for per-chat stdio dispatch |
| Authorized principal | Validated identity and permitted operations | Fixed service only |
| Host-controlled subject/session | Field producer, overwrite rules and injection limits | Documented correlation, provenance unverified on this route |
| Request binding | Context reaches the exact dispatched request | Resolver plumbing exists; production context absent |
| Local stdio custody | Child stdin/stdout controlled by the tunnel process | Confirmed in public client source; not upstream user attestation |
| Final-hop protection | Channel access control and immutable context handling | Must be proved end to end |
| Other allowed caller surfaces | Whether they can inject another chat's correlation | Unverified |

Do not require a separately signed conversation claim without evidence. Do not
require HTTPS mTLS on a stdio hop that has no TLS peer. For direct HTTPS, validate
OpenAI client origin through the documented mTLS boundary and separately
authenticate/authorize the user. For OAuth entrances validate issuer, audience,
expiry, scope and applicable replay policy. If the existing tunnel proves
equivalent guarantees, reuse it without a public HTTP endpoint, new credentials
or duplicate mTLS. Unknown guarantees remain unknown; do not invent flags such
as caller-supplied `mtls_verified`.

Source audit of the public client at revision
`b91e6c992dfd33e5c5ea94b00449c527c110851e` confirms that
`forwardingConnection.Write` carries headers in Go context while the stdio child
uses `mcp.IOTransport` over its pipes. Those files do not establish an
authenticated per-user context envelope for the child or prove upstream
protection of host correlation fields. This is a concrete transfer-contract gap,
not proof that every tunnel-based solution is impossible.

The follow-up review distinguishes an owner-exclusive deployment from a shared
caller deployment. Before selecting owner-only activation, enumerate effective
Use access across the relevant Platform organization and ChatGPT workspace,
including API callers and service accounts. Exclusivity must be established by
access evidence, not by the tunnel ID/runtime key or a subject allowlist. An
allowlisted subject is auxiliary matching, never first-request self-enrollment.
Even proven owner exclusivity does not establish a particular ChatGPT UI origin
or independent-chat isolation when a caller can copy session correlation.

The pinned stdio route does not serialize Go-context HTTP headers into the child
JSON-RPC stream. Public source does not establish upstream reserved-metadata
overwrite protection either; this is unverified, not a demonstrated spoofing
exploit. Keep effective caller access and upstream metadata generation/protection
as separate open evidence requirements. Do not activate the conversation resolver
from raw caller metadata while either required guarantee is absent.

The deployed client revision `a390c168ff1b2d14e73a95991c186c6aba3ff5a0`
decodes the raw JSON-RPC payload, forwards that message to `IOTransport`, and
uses Go SDK v1.7.0 encoding. The SDK retains request `Params` as raw JSON,
including any `params._meta` already present. Header non-transfer therefore
does not imply metadata non-transfer. This establishes source preservation,
not the upstream producer, overwrite protection, or an observed chat identity.
Read-only access screens show an existing runtime credential with Tunnel Read
and Use; a single owner in a member list alone does not exclude other caller
surfaces using existing credentials or prove plugin sharing boundaries.

Deliverable: verified guarantees, exact gaps and one selected minimal ingress.
A missing guarantee blocks live activation, not all independent source work.

## B. Connect one request-local path

Use one ingress adapter -> immutable authenticated request context -> enrolled
binding resolver -> existing mailbox handlers. Reuse the registry and original
message-party checks. Add HTTP/Unix socket plumbing only when it carries missing
verified context; changing transport alone is not authentication. Do not create
parallel mailbox stores, a second role system, operation-specific identity
wrappers, nonce-echo authentication or fixed-assistant fallback.

Deliverable: runtime and host wiring selects the exact enrolled actor for each
operation. Denial leaves logical mailbox and registration state unchanged;
permitted audit recording is separate from that logical state.

## C. Define and implement explicit enrollment lifecycle

Under an owner-approved policy, a new chat explicitly selects connect; trusted
context creates its participant and empty inbox. Read/reply never auto-enroll.
Display labels carry no authority and do not require token/ID copy-paste. The
same validated binding reconnects without repeated approval. A changed session
identity is not restored by title/history matching.

Separate durable participant identity from transient transport sessions. Define
reconnect, revoke, expiry, generation fencing and restart revalidation. A distinct
fork identity stays unenrolled with an empty inbox. If the provider duplicates
the same trusted identity, document that Phase 1 cannot distinguish those copies;
do not claim an enrollment screen fixes that limitation.

Deliverable: explicit lifecycle operations and truthful user-facing diagnostics.

The source lifecycle now provides explicit `enroll`, `revoke`, and reconnect
operations over the existing owner-controlled JSON binding registry. Enrollment
requires a trusted attestor plus principal/subject policy allowlists; resolve
never auto-enrolls. Reconnect returns the same non-revoked, unexpired binding,
while revoke fences its generation and old or changed identities are denied.
Writes use an owner-permissioned, symlink-rejected path, an exclusive sidecar
lock, and same-directory atomic replacement. This is source-level lifecycle
proof only; no provider ingress, transport attestation, or live ChatGPT
acceptance is implied.

Request-local dispatch now revalidates the exact resolved binding, generation,
identity, participant, address and expiry under the registry/file lock before
invoking the mailbox operation. Revoke or expiry between resolution and dispatch
is denied. A revoke after dispatch begins does not roll back committed work.
This source fence is not production ingress activation.

## D. Minimal source acceptance

Use the smallest relevant fixtures after the behavior stabilizes. Reuse existing
coverage; add a scenario below only where its acceptance condition is unproved:

- Alternate and concurrently process chats A/B in the same runtime: no global
  actor/context leakage.
- Reject spoofed principal/session/participant arguments and foreign message IDs
  for message/reply/ack; isolate inboxes, cursors and batch ACK where supported.
- Reject expired/revoked/old-generation bindings and unintended identity changes.
- Exercise concurrent connect for the same validated binding: no duplicate
  binding or participant is created.
- Exercise registry/host partial failure and restart recovery without duplicate
  registration or orphaned authoritative state.
- Resolve a binding, then revoke or expire it before operation execution: deny
  the stale operation, not merely the next resolve.
- On rejection or a precommit exception, assert logical mailbox and registration
  state remain unchanged, except permitted audit recording. Roll back precommit
  changes; do not roll back a committed result merely because its response was
  interrupted. Query that outcome using the same stable submission ID.
- Scope idempotency by binding plus operation; reject key reuse with a different
  payload and preserve original IDs across uncertain response outcomes.
- If existing coverage does not already prove it, use the same stable submission
  ID under distinct bindings and verify their idempotency isolation.
- Distinguish single mailbox acceptance from delivery cardinality.

Synthetic acceptance is not authenticated production ingress or real chat proof.

## E. Production activation and real app acceptance

Activate only the established new ingress; retain the existing fixed assistant
entrypoint separately. Preserve existing sessions and grants. New credentials or
security-sensitive grants, if truly necessary, require a concrete target and
minimum scope before their separate authorization.

Use an authorized, supported observation/operation route to operate two actual
ordinary app chats. The supported Chrome web route is now confirmed for the
capabilities-only diagnostic. It does not replace the following acceptance:

1. A sends to the external assistant; peer reads and replies; A reads that reply.
2. B sends to a native session; peer reads and replies; B reads that reply.
3. A/B attempts to read, reply to, or ACK each other's known message IDs are
   rejected in both directions.
4. Record the resolved actor/binding, original reply ID and body consumption;
   verify explicit connect, same-identity reconnect, explicit revoke and rejection
   of the revoked binding's old generation. Verify distinct-identity fork behavior
   without overstating same-identity duplication guarantees.

Tool discovery, HTTP success, fixtures and existing assistant success do not
substitute for this acceptance. Automatic idle-chat resumption is excluded.

For the selected notification/UI return adapter, separately verify acceptance,
presentation in the original chat, reply-body consumption and any model
activation actually promised. A manual-pull milestone does not remove this
return-route work from the overall communication objective. Preserve stable
message/submission IDs on uncertain outcomes; do not resend to manufacture proof.

## F. Catalog, rollback and final report

Keep shared plugin descriptions, schemas and callable catalogs consistent.
Refresh through the supported connection management path and verify the actual
ordinary-chat catalog. Commit logical slices and apply only the new entrance.
Rollback removes/disables that entrance without changing existing participants,
message histories or sessions. Run required checkpoint gates once; do not repeat
unchanged green checks. Report deployed revision, focused proof, live acceptance,
explicitly unproven requirements and a resumable handoff.

## Remaining blockers

1. Existing stdio ingress has no verified per-request principal/conversation
   context transfer contract yet.
2. Real two-chat acceptance has not been executed. Supported web observation is
   available; activation still depends on the trusted ingress contract above.

Neither blocks independent Phase 1/source work, requires declaring all source
work impossible, or justifies introducing a new conversation-signing infrastructure.

## Review disposition

All six substantive review sections were adopted: guarantee-based authentication,
request provenance, explicit lifecycle and conditional fork guarantees, expanded
minimal acceptance, narrow ingress reuse, and separation of the two blockers.
No configuration, test execution, credential issuance or deployment was requested
from the reviewer.

## Primary references

- [MCP Events: supported surfaces and subscription delivery](https://developers.openai.com/plugins/build/mcp-events)
- [ChatGPT app UI bridge](https://developers.openai.com/plugins/build/chatgpt-ui)
- [Tool results and component follow-up messages](https://developers.openai.com/plugins/reference)
- [Codex app-server thread operations](https://learn.chatgpt.com/docs/app-server)

- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Client authentication and mTLS](https://developers.openai.com/plugins/build/auth#mutual-tls-mtls)
- [Host-provided correlation metadata](https://developers.openai.com/plugins/reference#_meta-fields-the-client-provides)

- [Pinned forwarding implementation](https://github.com/openai/tunnel-client/blob/b91e6c992dfd33e5c5ea94b00449c527c110851e/pkg/mcpclient/forwarding_transport_impl.go)
- [Pinned stdio implementation](https://github.com/openai/tunnel-client/blob/b91e6c992dfd33e5c5ea94b00449c527c110851e/pkg/mcpclient/stdio_command.go)
