# Muse mailbox service — Issue #14 P1

This adapter reuses the KAI mailbox implementation instead of forking it.
ServiceIdentity is credential-free; ServiceBinding adds the parent-only
credential. KaiServiceBinding remains an API alias. Existing KAI event-enabled
defaults and its full catalog are unchanged.

## P1 boundary

- Eight tools: list, status, send, inbox, message, reply, ack and diagnose.
  No repository tools or MCP Events are advertised.
- P1 enrolls Muse read-only. Send/reply/ack/body-reservation operations are
  denied by both adapter and Host policy. A listed tool is not authorization.
- The launchd parent owns credential/generation in owner-only parent.json.
  The SSH child reads separate client.json, containing neither.
- The parent stamps private Host identity fields after the bridge boundary.
  Metadata-only heartbeats maintain liveness; no event pump/state is created.
- Every call checks the current launchd main PID/start. The stable endpoint is
  derived from service ID, participant and operator-owned generation.
- This is service/connection identity, not provider-attested chat isolation.
  Muse conversation/job routing belongs to later phases.

## Prepare / enroll / check

First load a Host advertising service_generation_v1. The helper checks that
capability before enrollment changes. Do not use the blanket installer or
restart KAI, OpenClaw, tmux, native agents or the GUI.

From source, on the intended owner, after the operator selects empty scope:

    python3 extensions/messaging/external/muse-mcp/enroll.py --prepare --empty-scope
    python3 extensions/messaging/external/muse-mcp/enroll.py --check
    python3 extensions/messaging/external/muse-mcp/enroll.py --apply

For explicitly selected participant access instead, repeat --allow-address.
There is no inferred grant. Prepare creates a private package/candidate only.
Apply preserves other services and rejects observed configuration drift.
Check writes nothing and does not start/repair anything. Existing-enrollment
scope sync also uses generic unified/service_policy_migrate.py: differing
identity, credential, generation or policy is never overwritten.

Output contains only booleans/counts, not credentials or generation.
The helper prepares a new plist without starting services. After apply:

    tproj-msg-runtime activate

The plist uses python3 -I and the private parent config/bridge.
Test initialization/tools/list through the separate tokenless client config.
Do not send messages during a new read-only P1 enrollment. This is an enrollment
phase, not a permanent restriction on an already writable workspace connection. A body read requiring a presentation reservation
also remains unavailable while enrolled read-only.

## Dedicated SSH key

Generate the dedicated Ed25519 keypair on the Muse VM, not on the Mac.
Never reuse the management key. Transfer only its public key, then:

    python3 extensions/messaging/external/muse-mcp/enroll.py --install-key --public-key-file PUBLIC_KEY_FILE

The helper rejects a key carrying another grant, preserves unrelated entries,
and adds restrict plus one forced tokenless stdio command. No listener,
interactive shell, PTY or forwarding is added. The child has no parent token.

VM connector/discovery are P2. Initially enabling message operations is P3.
These phase labels do not add per-session or per-destination approvals to normal
conversation after activation. Current workspace communication follows the
[shared MSG contract](../../../../docs/reference/unified-messaging.md).
Preparing/checking an existing workspace enrollment preserves its mode and approved
read-only/writable policy rather than reverting it to P1.
Missing dedicated public key or operator-selected scope leaves P1 incomplete.

## Continuity / revocation

A Muse-only restart with the same generation must retain endpoint/incarnation
and mailbox references. A private atomic Muse generation change or removal
rejects old parent requests without changing KAI/OpenClaw. Never put generation
in argv/chat/issues. Verify rejection first; restoring/re-enrolling access is
a separate explicit operator operation. Preserve historical unknown outcomes.

Check proves matching configuration and loaded Host support, not actual SSH
access, cloud chat isolation or successful message delivery.

## VM connector and receive phase

The initial P1 prepare/apply contract above stays read-only. An already-approved
writable enrollment can register its dedicated public key after exact current
parent/client/Host/directory validation, without changing policy. The VM helpers,
metadata-only inbox detection and native receive hook are specified in
[the Muse MSG connector contract](../../../../docs/reference/muse-msg-connector.md).
Use the fixed SSH stdio CLI and native hook APIs; do not substitute Slack/Issue
relay, a public HTTPS endpoint, or copying parent credentials onto the VM.
