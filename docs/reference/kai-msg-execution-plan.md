# KAI MSG integration: execution plan

Status: implementation checkpoint, 2026-10-02. Integration is **not complete**.
This document owns execution order and acceptance; the linked reference
contracts own protocol semantics. Machine-specific routes and credentials
remain in ignored local state.

## Goal and non-goals

Finish authenticated, bidirectional `tproj-msg` with the **existing KAI Dots
conversation**, from both a development host and a remote host. KAI must also
be able to initiate a message to an authorized session. A web/Slack conversation,
tool listing, callback acceptance, or synthetic event alone is not completion.

- Keep all existing CC/Codex/tmux/OpenClaw sessions alive. Do not restart their
  shared daemon to repair identity or replace a running workspace.
- Use the existing authoritative mailbox, not a second KAI mailbox or copied
  recipient ledger. Keep message identity and reply routing in that mailbox.
- Keep KAI service enrollment, credentials, and scopes separate from Observation
  and OpenClaw. Do not expose observation data, shell access, or model APIs.
- The approved local boundary is a dedicated KAI **connection principal**:
  authenticate the enrolled service process and fixed participant scope. This
  does not claim cryptographic KAI-persona or conversation authentication;
  provider conversation provenance remains a separate acceptance item.
- Do not add cross-host task/role-handoff features in this scope.
- No public push is authorized by this plan.

## Verified starting point

| Area | Evidence already available | Still missing |
| --- | --- | --- |
| Existing KAI conversation | Development message read and answered through browser | Actual MSG delivery and return to that conversation |
| Connection-only event probe | Dedicated tunnel and plugin connected; original Dots invoked status; event recognized | Subscription, original-chat event receipt and stop proof |
| Independent service registry | `66cf80a`, corrected in `a7fab6d`; reflected on both hosts without session termination | Authenticated KAI enrollment |
| Remote wrapper | `c4f94b8` | Shared-app-server conversation authentication remains rejected |
| Native identity investigation | Installed version source hardcodes native background-terminal OS PID as absent; `--no-daemon` selects embedded runtime | Authentication of existing caller; endpoint and subagent isolation |
| Mailbox MCP tools/events | Seven tool dispatcher, durable outbox and bounded retries implemented; fixed KAI connection authorizer now enforces service enrollment, endpoint incarnation and scope | Host enrollment reflection, activation and six live acceptance cases |

Do not repeat the initial KAI capability question or rebuild these completed
slices. Native background-terminal logical process IDs are not OS PIDs. The supported
isolated launch flag does not authenticate an existing caller, and restoring the
same thread concurrently is not a proven safe migration. Context metadata hashes are diagnostics,
not authenticated conversation identity.

## Ordered tasks

### P1 — Activate the approved connection-principal route

1. Keep the existing Observation tunnel/profile untouched and use the prepared
   dedicated KAI profile and no-expiry control-plane key.
2. Run the launchd-owned KAI runtime. It authenticates `service_whoami` with
   the configured service ID/address/token, verifies the exact launchd PID and
   endpoint incarnation supplied by the unified host, and fixes the participant
   allowlist. Tunnel-spawned stdio children may use only the owner-only bridge.
3. Verify read-only discovery and one synthetic event subscription through the
   existing KAI connection. Record callback acceptance separately from any
   presentation or conversation receipt; callback `2xx` is not proof of either.
4. Keep provider conversation provenance as an explicitly unresolved evidence
   item unless KAI supplies a supported binding. Do not infer it from `_meta`,
   display names, or a model claim, and do not use it as a prerequisite for the
   approved local service-principal boundary.

Acceptance: an independently enrolled KAI service is authenticated by the
host, restricted to the fixed participant scope, and can be revoked or fenced
by endpoint incarnation without affecting OpenClaw or Observation. Original
Dots conversation receipt remains a separate live acceptance case.

### P2 — Reflect and enroll the independent service

1. Refresh only the changed service runtime artifact through the supported safe
   distribution path; do not run the blanket installer over live workspaces.
2. Define one KAI service ID/address, authorized project/participant scope,
   credential, and process-incarnation binding. No duplicated aliases.
3. Register the adapter without replacing the existing OpenClaw service. Keep
   mailbox access disabled until P1 identity evidence is available.
4. Verify one scoped operation and unchanged existing service endpoint identity.

Acceptance: a distinct live KAI service with enforced scope; existing services
and sessions remain intact. Code commits alone do not satisfy this task.

### P3 — Implement real MSG tools and event delivery

Dependencies: P1 host-bound service principal and P2 live enrollment.

1. Implement the seven already specified tools: `tproj_list`, `tproj_status`,
   `tproj_send`, `tproj_inbox`, `tproj_message`, `tproj_reply`, `tproj_ack`.
   Derive sender identity from the trusted adapter, never from tool arguments.
2. Connect tools directly to service-scoped operations of the authoritative
   mailbox. Preserve submission IDs, message/thread IDs, bounded cursors,
   recipient-only acknowledgements, and replies pinned to the original sender.
3. Drive signed event notifications from durable mailbox/subscription state.
   An event wakes the subscribed original conversation; authorized inbox access
   retrieves messages. Callback `2xx` is acceptance, not presentation or reply.
4. Implement bounded backoff, expiry, unsubscribe/revocation, and restart
   reconciliation. Retries reuse existing IDs; uncertain delivery is not a new
   message. Incarnation changes require demonstrated continuity.
5. Enable only the enrolled KAI route after read-only binding verification.

Acceptance: KAI reads an actual authorized message, acknowledges consumption,
and sends an ID-linked reply to the correct pane without identity substitution.

### P4 — Preserve remote Codex identity boundaries

Run independently alongside P1/P2; required only for the distinct remote-Codex
acceptance case, not for local KAI service activation.

1. Preserve the existing fail-closed rejection for unproven shared app-server
   conversation identity. Native metadata and daemon ancestry are diagnostics,
   not authority for the KAI service principal.
2. If the affected remote Codex case is exercised, capture only the prepared
   metadata-only native identity evidence and require an independently bound
   endpoint incarnation; never borrow another conversation's thread or alias.
3. Coordinate any sibling router change with its owner. MSG service identity
   and role/epoch remain separate contracts; activating KAI does not silently
   authenticate a remote Codex conversation.

Acceptance: remote-Codex usage is either independently authenticated and
isolated, or explicitly recorded as unverified while the approved KAI
connection route remains usable.

### P5 — Minimal live acceptance and completion

After P1–P4 are ready, execute each distinct case once, using developer-labelled
messages and recording message ID, actual recipient receipt, and reply receipt:

| Case | Required evidence |
| --- | --- |
| Development host → KAI → sender | Original KAI conversation receives; exact originating pane receives reply |
| Remote Codex → KAI → sender | Real affected Codex caller authenticates; same-pane reply received |
| KAI → named pane → KAI | KAI initiates with the tool; answer returns to the original Dots conversation |
| Two simultaneous senders | No cross-project, cross-thread, or reply-target mixing |
| Disconnect + adapter restart | Existing IDs reconcile and delivery resumes without duplicate presentation; restart only the new adapter |
| Unsubscribe/revocation | Subsequent event/access rejected; unrelated services unaffected |

Use focused regressions for authorization, isolation, duplicates, and stale
bindings. Reuse already-green worker evidence rather than repeat unchanged
suites. Run the broad gate defined in `.github/workflows/test.yml` once at the
stabilized messaging checkpoint, plus the affected sibling router's required
focused check. No build/test is needed merely to edit this plan.

Finish with safe installed-copy verification, contract/skill/runbook updates,
scope-only conventional commits, and actual usage notifications to KAI and the
affected Codex session. Public push remains a separate authorization.

## Continuity: do not stop at a status report

- Persist progress in `.local/kai-msg-plan/tasks.json` after each logical step:
  implementation SHA, reflection state, acceptance evidence, blocker, next action.
- Keep `.local/handoff/issue14-external-assistant.md` current so the next turn
  resumes the **first unfinished action**, not discovery or replanning.
- Waiting for access approval blocks that access action only. Continue independent
  implementation and native identity work. Never infer consent from waiting.
- On a failure, record observed result, hypothesis, and a changed next attempt.
  Do not repeat unchanged failing sends, poll for replies, or use legacy injection
  to bypass rejection. A receipt notification is not a new implementation task.
- For genuinely unavailable user-only consent, prepare the exact single action
  and its expected result. Keep all other reachable work progressing.
- Report overall completion only after every P5 condition is evidenced. Partial
  code, synthetic events, or communication over another UI must be labelled partial.

## Reference contracts

- [External tool contract](external-assistant-tool-contract.md)
- [External connection boundaries](external-assistant-connection.md)
- [Unified mailbox and service registry](unified-messaging.md)
- [Connection-only probe](kai-event-probe.md)
- [Native conversation identity and router agreement](conversation-identity-and-cross-host-tasks.md)
