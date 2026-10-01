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
| Mailbox MCP tools/events | Seven tool dispatcher, durable outbox and bounded retries implemented; `03a0c9d`; Python 15/15 and required shell 11/11 passed | Trusted cloud binding, activation and six live acceptance cases |

Do not repeat the initial KAI capability question or rebuild these completed
slices. Native background-terminal logical process IDs are not OS PIDs. The supported
isolated launch flag does not authenticate an existing caller, and restoring the
same thread concurrently is not a proven safe migration. Context metadata hashes are diagnostics,
not authenticated conversation identity.

## Ordered tasks

### P1 — Prove the cloud route and conversation identity

1. Finish the prepared, connection-only dedicated tunnel registration. Keep
   the existing Observation tunnel/profile untouched. Record the outstanding
   action-time access confirmation; do not ask again if it has been answered.
2. Provision a separate restricted runtime credential using the supported flow;
   never display it, put it in a prompt, or borrow another service's key.
3. Prepare a dedicated profile and launchd runner on the remote host, using the
   already verified tunnel binary and deployed stdio probe. Limit exposure to
   connection status and synthetic events. Start only this new component.
4. Connect that probe in the existing KAI conversation. Have KAI subscribe there,
   send one signed synthetic event with a stable ID, and observe receipt in the
   **same** conversation. Record subscription expiry and unsubscribe behavior.
5. Establish the supported provenance of cloud invocation context, account,
   assistant, and conversation. Do not promote self-reported IDs or best-effort
   metadata into authority. Record the exact supported mechanism before writes
   or real mailbox data are enabled.

Acceptance: original-chat event receipt plus authenticated invocation binding.
If either is unsupported, isolate that route, retain evidence, investigate the
provider-supported alternative, and continue P2/P4 preparation. Do not silently
replace Dots with Slack or declare the integration finished.

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

Dependencies: P1 binding proof and P2 live enrollment.

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

### P4 — Repair remote Codex conversation authentication

Run independently alongside P1/P2; required before remote-Codex acceptance.

1. Ask the affected Codex session to run the prepared metadata-only native
   identity probe during its own actual tool execution. Capture native thread,
   tool item, OS PID, and registered endpoint association; no histories/secrets.
2. Prove two root conversations and subagents cannot borrow each other's
   identity. Daemon ancestry, cwd, aliases, and client-supplied thread IDs remain
   insufficient. Keep the existing fail-closed rejection until proof exists.
3. Implement a trusted host conversation adapter if native provenance is proven;
   bind to endpoint incarnation and operation. If unavailable, investigate a
   provider-supported isolated-runtime route without terminating existing
   sessions. Do not promise unverified launch flags or an identity bypass.
4. Coordinate the sibling router change with its owner. MSG and role routing
   must consume the same authenticated identity; role/epoch remain separate.

Acceptance: the affected remote Codex session authenticates itself and gets the
correct runtime role; another conversation cannot send as it. Fixing only the
wrapper or allowing a daemon launcher to stand in for the caller is not repair.

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
