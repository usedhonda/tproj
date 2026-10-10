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
- The current Computer Use attachment rejects process ancestry before obtaining
  app state, so that observation route is unavailable. Another authorized,
  supported route has not been confirmed; real two-chat acceptance remains open.
- Fork behavior is not guaranteed: distinct trusted identities are isolated;
  indistinguishable provider identity copies cannot be separated by the backend.

## A. Establish the actual ingress contract

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
ordinary app chats. Recovery of the current Computer Use attachment is one
possible route, not an exclusive prerequisite; alternatives remain unconfirmed:

1. A sends to the external assistant; peer reads and replies; A reads that reply.
2. B sends to a native session; peer reads and replies; B reads that reply.
3. A/B attempts to read each other's known message IDs are rejected.
4. Record the resolved actor/binding, original reply ID and body consumption;
   verify reconnect and distinct-identity fork behavior without overstating
   same-identity duplication guarantees.

Tool discovery, HTTP success, fixtures and existing assistant success do not
substitute for this acceptance. Automatic idle-chat resumption is excluded.

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
2. Real two-chat app acceptance has no confirmed authorized, supported
   observation/operation route; the current Computer Use attachment is unavailable.

Neither blocks independent Phase 1/source work, requires declaring all source
work impossible, or justifies introducing a new conversation-signing infrastructure.

## Review disposition

All six substantive review sections were adopted: guarantee-based authentication,
request provenance, explicit lifecycle and conditional fork guarantees, expanded
minimal acceptance, narrow ingress reuse, and separation of the two blockers.
No configuration, test execution, credential issuance or deployment was requested
from the reviewer.

## Primary references

- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Client authentication and mTLS](https://developers.openai.com/plugins/build/auth#mutual-tls-mtls)
- [Host-provided correlation metadata](https://developers.openai.com/plugins/reference#_meta-fields-the-client-provides)

- [Pinned forwarding implementation](https://github.com/openai/tunnel-client/blob/b91e6c992dfd33e5c5ea94b00449c527c110851e/pkg/mcpclient/forwarding_transport_impl.go)
- [Pinned stdio implementation](https://github.com/openai/tunnel-client/blob/b91e6c992dfd33e5c5ea94b00449c527c110851e/pkg/mcpclient/stdio_command.go)
