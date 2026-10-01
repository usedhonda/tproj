# KAI MCP Events connection-only probe

This probe is an isolated stdio MCP 2.0 server for checking event delivery to
an existing KAI Dots conversation. It has no mailbox connector and never reads
or imports mailbox data.

## Surface

- `server/discover` advertises MCP `2026-07-28` and `events` capability.
- `tools/list` and `tools/call` expose only `connection_status`.
- `events/list` exposes `kai.connection.probe` with no filter arguments.
- `events/subscribe` verifies a public HTTPS callback with a signed one-use
  challenge, then stores an idempotent subscription in local state.
- `events/unsubscribe` is idempotent.
- `--send-event SUBSCRIPTION_ID` sends exactly one synthetic event. Add
  `--event-id evt_fixed` when a retry must reconcile the same event; the probe
  persists the exact payload and rejects reuse with different data. This is an
  explicit operator command; it is not wired to a mailbox or tproj runtime.

Subscriptions are stored at `~/.local/share/tproj/kai-event-probe/` (or
`$KAI_EVENT_PROBE_STATE`) with directory mode `0700` and file mode `0600`.
Secrets are never printed. Callback validation requires HTTPS and rejects
private, loopback, link-local, reserved, multicast, and unspecified addresses;
redirects are not followed. Delivery uses Standard Webhooks HMAC headers and
one event per request, with a 256 KiB body limit. DNS is resolved once per
connection and the validated public address is pinned while TLS still uses the
original hostname. State is locked across processes; malformed state fails
closed rather than being replaced.

The probe reports only presence and SHA-256 digests of supported client context
metadata (`_meta` subject/session/organization). These digests are diagnostics,
not authentication or proof of ownership of a cloud conversation; missing
metadata remains absent/unverified.

## Launch

```bash
python3 extensions/messaging/external/kai-event-probe/server.py
```

The stdio process is suitable for an existing Secure MCP Tunnel client. The
probe does not enroll, send, or push anything externally by itself.

## Isolated Secure MCP Tunnel preparation

`runtime.py` prepares local launch artifacts for the official tunnel client
without starting it. The runtime has its own base directory and profile, uses
only the explicit loopback health listener (`127.0.0.1:0`), and does not inherit
Observation or shared-tunnel environment settings. It never creates a tunnel
or cloud resource and never reads the credential contents.

```bash
python3 extensions/messaging/external/kai-event-probe/runtime.py \
  --binary /absolute/path/to/tunnel-client \
  --tunnel-id tnl_example \
  --base-dir /absolute/path/to/private/kai-probe-runtime \
  --credential-file /absolute/path/to/control-plane-key
```

Preparation is idempotent for the exact same manifest and refuses conflicting
artifacts or profiles. If the credential file is not present, preparation still
writes the runner and launchd plist but leaves the profile uninitialized; the
runner exits before starting until the key exists, is a regular owner-only file
(`0600` or `0400`), and `profiles/<profile>.yaml` exists. With a safe existing
key, the preparer invokes only the client's local `init` command. It never
invokes `doctor`, `run`, `bootstrap`, or launchctl.

The generated plist is inert (`RunAtLoad=false`, `KeepAlive=false`); loading or
starting it is an explicit operator action outside this preparation step.

## Verification

```bash
python3 -m py_compile extensions/messaging/external/kai-event-probe/server.py
python3 -m unittest extensions/messaging/external/kai-event-probe/test_server.py
python3 -m unittest extensions/messaging/external/kai-event-probe/test_runtime.py
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"server/discover"}' | python3 extensions/messaging/external/kai-event-probe/server.py
```

The discovery command is discovery-only and should report `supportedVersions` as
`["2026-07-28"]` plus `events` capability.
