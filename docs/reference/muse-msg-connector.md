# Muse MSG connector and receive hook

Muse uses the existing service mailbox, not a separate messaging database.
The fixed service/connection principal is not provider-attested chat identity.
The native hook's delivery destination belongs to its originating Muse chat.
It must not be copied from another connector's hook or supplied by peer text.

## Transport and interfaces

The VM owns a dedicated Ed25519 key. The Mac enrollment helper accepts its
public key only after private parent, tokenless child, current Host policy and
owner directory match. Initial prepare/apply remain read-only. Key installation
also supports a previously approved writable enrollment; it never changes that
policy. Another grant for the same public key is rejected.

The grant is `restrict` plus the fixed Muse stdio command. No management-key
reuse, shell, forwarding, public listener, alternate identity or API token on
the VM. Pin the owner's SSH host key through an existing authenticated route.

`vm_client.py --config CLIENT list-tools [--cursor CURSOR]` and
`vm_client.py --config CLIENT call-tool --name TOOL --arguments-file JSON`
manage one SSH/stdio MCP session on Python 3.11+ using the pinned official SDK. The configuration
contains only the fixed SSH profile and alias; SSH manages the VM-private key.
Exactly the original eight mailbox tools are allowed. A call is never replayed.
The SDK child inherits only the caller's current native HTTPS_PROXY context in
ephemeral process environment; it is never saved or logged. If that context is
absent, fail closed instead of using another invocation's saved authorization.
An ambiguous write reports unknown and retains its original submission ID.
Read back that ID before deciding on any subsequent operation.

## Detection without presentation

`tproj_inbox` accepts optional boolean `metadata_only` (default false). True
returns `messages: []`, `pending` metadata and `next_cursor`. Metadata contains
IDs, sender, sequence, lifecycle state and expiry, never bodies or provenance
payloads. This mode does not call `service_begin_present` or ACK. Default inbox
behavior is unchanged. The existing tool count and service authorization remain
unchanged. An old server without this mode must not be silently used by a hook.

`vm_poll.py` performs one metadata request. `vm_hook.sh` uses the native hook
runtime and its state helpers, with a nonblocking single-flight lock. Create
through native hooks APIs, initially disabled; inspect dry-run before enabling.
Use 15-second polling and a 30-second script timeout. Each check terminates;
never launch a listener daemon inside the hook. Empty inbox stays silent.

Notification state contains only cursor, active ID/sequence and notification
timestamps, not mailbox content. The native state helper skips writes in a dry
run. A restart retains active notification state instead of replaying a message.
The active message is cleared only after authoritative state is terminal,
expired or absent from its current page. After 180 seconds awaiting consumption,
a single stalled-work wake asks for inspection, never a resend. A connection
outage similarly emits one diagnostic wake per outage, retaining active state.

On a message wake, Muse reads the exact ID, consumes the body, then ACKs.
A question receives an ID-linked reply using a pre-persisted stable submission
ID and immutable arguments. FYI/reply-not-required traffic does not create an
answer loop. Uncertain replies are diagnosed, not resubmitted under new IDs.

## Deployment and acceptance

Keep canonical VM helpers and requirements in the Muse adapter source. Deploy
only the isolated Muse package and VM connector; preserve Host/Hub and every
other service's files, policy and processes. A compatible Muse-only restart
retains the enrollment generation. Do not use a blanket installer during live
workspaces. Pin all installed dependency versions in the VM requirements file.

Prove read-only catalog/list/status first. Then create fresh, explicitly labeled
acceptance probes in both directions, one original ID each; expired historical
probes are never replayed. With the Mac app closed, verify actual body consumption
and exact in_reply_to/thread metadata, not merely queued/adapter status. Verify
empty polling, a dry-run preserving state, one consumer restart and a simulated
SSH failure without duplicate work. This does not prove full VM-replacement
recovery or permanent availability.

### Reliability evidence

A roundtrip that needed an intervening human instruction proves that particular
exchange, not unattended reliability. Keep these results separate. Unattended
acceptance sends distinct short and long-body questions while the app stays
closed, checks the actual answers and exact thread links, and includes a new
recipient-originated question. Persist IDs before each call, record latency and
any intervention, and do not replay a failed or uncertain probe. A safety hold
is a failed unattended case, not permission to change identity or weaken checks.

`test_vm.py` covers queued pages across notification-state reload, repeated
outages, expiry/cancellation and clearing an active message without skipping the
next one. `test_vm_stdio_faults.py` uses the pinned official SDK and real child
processes against an isolated protocol fixture, not a mocked `invoke()`. The
fixture saves acceptance but withholds the response. It verifies a bounded
unknown result, original submission-ID retention, child cleanup, a subsequent
successful exact-ID read and exactly one acceptance. It does not claim a live
SSH-server outage or native Muse authorization proof.

Run the latter with Python 3.11+ and the pinned SDK installed:

```bash
python extensions/messaging/external/muse-mcp/test_vm_stdio_faults.py -v
```

The dedicated Linux CI job installs the pinned requirements and runs it on
Python 3.12. Dependency-free test discovery may skip it; a skip is not transport
evidence. Actual native-message safety decisions remain a separate live gate.

Rollback disables only the new native hook and restores only the isolated Muse
package if necessary. Preserve notification state, immutable submission records,
unknown outcomes and dedicated-key evidence. Do not roll back a mailbox DB or
revert another service's async work/tombstone implementation.
