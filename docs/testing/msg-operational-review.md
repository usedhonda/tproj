# MSG operational review

This review traces operational scenarios, not a promise that every possible input or
external provider lifecycle is error-free. Isolated fault injection, real conversation
evidence and unverified live scenarios are explicitly separated. A green shell workflow
alone is not complete messaging coverage.

## Scenario ledger

| ID | Scenario | Isolated proof | Real use / remaining boundary |
| --- | --- | --- | --- |
| R01 | Same-project CC/Cdx conversation | `test-unified-integration.py` | Established. Exact linked reply and recipient read/ACK; not just queued. |
| R02 | Different project on same host | `test-unified-hub.py` | Established. Original recipient and thread remain pinned. |
| R03 | Native peer across physical owners | `test-unified-federation.py` | Not exercised in this review. SQLite/direct-remote fixture is not a real SSH outage. |
| R04 | External MCP and native peer, both directions | `test-unified-host-services.py` | Established. Read/ACK evidence and service-generation continuity are separate. |
| R05 | External MCP peers talking to each other | `test_runtime.py` | Established by both peer reports. Report identifies real conversation, not just transport acceptance. |
| R06 | Side-chat initiates to newly listed project | `test-send-targets.py` | In progress. Old address memory must not override authenticated workspace policy. |
| R07 | Shared list and new-send routing agree | `test-send-targets.py` | Established. Ready is a route snapshot, not end-to-end delivery. |
| R08 | Missing/stale model and descriptive metadata | `test-send-targets.py` | Established. Metadata is never a routing/approval prerequisite. |
| R09 | Duplicate live endpoints and explicit preference | `test-recipient-recovery.py` | Historical incident only. Never guess a receiver by heartbeat freshness. |
| R10 | Read-only connection and service separation | `test-unified-host-services.py` | No destructive live probe. Writable workspace does not bypass read-only enrollment. |
| R11 | Wrong native thread/UID/participant | `test-unified-identity.py` | No identity-switch live probe. Rejection leaves unrelated sessions usable. |
| R12 | Same ID/same payload duplicate | `test-unified-hub.py` | Historical real usage. Idempotent acceptance is not repeated delivery. |
| R13 | Same ID/changed payload conflict | `test-unified-deferred-submissions.py` | No conflicting live write. Preserve the existing original. |
| R14 | Submission accepted but response lost | `test_vm_stdio_faults.py` | Historical observed timeout. Exact-ID lookup; never a fresh-ID replay. |
| R15 | Host journaled then Hub committed | `test-unified-deferred-submissions.py` | Established in recent peer reports. Unconfirmed journal receipt is not rejection. |
| R16 | Peer absent, DNS/SSH/bridge timeout | `test_runtime.py` | Observed intermittent management SSH reset. Management SSH reset alone does not explain model-turn silence. |
| R17 | One slow or broken recipient | `test-unified-host-services.py` | No deliberate production outage. Other recipients and heartbeats continue. |
| R18 | Concurrent workers/DB write-lock isolation | `test-unified-federation.py` | No production lock stress. Preflight/network outside write transactions. |
| R19 | Growing history and linked reply lookup | `test-unified-hub.py` | Reviewer found real scan cost. Covering reply index; no data purge. |
| R20 | Valid large/Unicode/multibyte body | `test-unified-federation.py` | No large live probe. Preserve exact body; use encoded response size. |
| R21 | New body fits request but not response | `test-unified-hub.py` | No poisoned live write. Reject before commit, not by blanket 200 KB limit. |
| R22 | Historical unreadable row before a normal row | `test-unified-hub.py` | No live row rewriting. Metadata error, cursor advance, no fake empty body/ACK. |
| R23 | Inbox pagination and later arrivals | `test-unified-cli.py` | Routine inbox usage. No cursor skip or first-row starvation. |
| R24 | Native notification/consumption/publication/ACK lost | `test-native-publication.py` | Earlier real native receipts. Unknown publication is not safe to replay. |
| R25 | Subscriber opt-in, both feature flags and no fallback | `test-native-cc.py` | No flag manipulation live. Do not pin an unobserved subscriber. |
| R26 | Process restart, same generation | `test-unified-host-services.py` | Observed targeted process reloads. Keep mailbox identity; do not borrow another chat. |
| R27 | Different incarnation/native and old pinned recovery | `test-recipient-recovery.py` | Not exercised live this review. Isolated proof only; authenticated continuity required. |
| R28 | Token/generation revoked while work pending | `test-unified-deferred-submissions.py` | No revocation live probe. Revocation cannot retroactively turn unknown into nonacceptance. |
| R29 | Expired original and late reply/receipt | `test-unified-hub.py` | Historical incidents. Keep unknown/late evidence distinct from active delivery. |
| R30 | Cancel races claim/commit/reconnect | `test-unified-deferred-submissions.py` | No production cancellation race. Durable cancellation fence and too-late semantics. |
| R31 | Mixed backend and strict MCP schemas | `test-runtime-compatibility.py` | Earlier dispatching-schema incident. Unknown older backend behavior is not claimed current-ready. |
| R32 | Owner mirror versus recipient-owner state | `test-unified-hub.py` | Real mirror mismatch observed. Explicit local_copy/owner_verified display, no hidden RPC. |
| R33 | Existing writable workspace enrollment recheck | `test_muse.py` | Not applied to live credentials. Preserve mode, keys and read-only policy. |
| R34 | Legacy address memory and multi-step safety refusal | `test_connection.py` | Reproduced; single-step list succeeds. Normal communication is not business-task authorization. |
| R35 | External ingress and normal development peers | `test-unified-telegram-compatibility.py` | Transport acceptance only for recent ingress report. Do not generalize workspace scope to inbound external users. |
| R36 | Installed versus loaded/current source | `test-runtime-installer.sh` | Both owners match recorded feature stages. Seven pre-existing unrelated distribution differences retained. |

## Reviewed findings and disposition

- Reply-history scans: add the covering linkage index; verify its actual query plan.
- Unreadable response frames: validate new admission and isolate historical bad rows; preserve valid large bodies.
- Stale restricted-scope interpretation: current authenticated workspace policy replaces remembered addresses; clarify tool descriptions and enrollment-only phase documentation.
- Enrollment recheck: retain existing writable workspace mode without changing credentials or widening a new enrollment.
- Sender mirrors: label local-copy state instead of presenting it as owner-verified delivery.
- Session directory metadata: retain the requested session identification. It grants no identity or routing override; do not remove it merely to add restrictions.
- CI coverage: include the omitted core lifecycle suites and update the stale additive-capability expectation.

## Verification discipline

Use a stable checkpoint for the complete required workflow. Run additional focused
proofs only for a named unproved or failing scenario. Tests use isolated mailboxes;
do not restart production sessions or inject unreadable originals to simulate faults.
A receipt is not a model reply. A successful client list is not a conversation.
No per-session approval is added to ordinary workspace communication.

Review and activation evidence, full message IDs and environment-specific observations
belong in the ignored local execution record, not this shared document.

## Remaining boundaries

- A direct legacy service_claim caller that never passes a keyset can repeat an
  error-only page when many historical oversized originals precede normal rows.
  Current MCP connectors do not use service_claim; native delivery uses a keyset.
- Historical oversized originals retain their original lifecycle until expiry;
  collection errors do not invent rejection, consumption or an ACK. Exact-ID
  inspection is needed to distinguish this from a receiver that has not replied.
- Frame-isolation behavior requires the upgraded recipient owner as well as the
  upgraded sender. Both running owners were targeted in this checkpoint; an older
  third owner is not covered by that activation evidence.
- Restart/recovery, expiry/cancel races and physical network loss are validated
  with isolated real SQLite/socket/SDK boundaries, not forced on working sessions.
