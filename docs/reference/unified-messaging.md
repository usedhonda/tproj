# Unified messaging checkpoint

This is the public guide for the proposed unified host-agent branch. It is a
migration checkpoint, **not globally active by default**. The branch is active
only when the local client configuration exists at
`$HOME/.config/tproj/msg-client.json` and contains an explicit
`"active": true` marker. Until that condition is met, the existing `tproj-msg`
legacy routes remain authoritative.

## Directory and identity

The central directory owns project aliases and endpoint registrations. A local
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
When a submission result is uncertain, `--retry` may retry **the same message
ID and content only**; it must never create a second request automatically.
Replies remain pinned to the original sender endpoint and message ID.

Ordinary chat cannot change roles, grant implementation authority, or create a
task. `--force` cannot bypass identity, generation, approval, draft, or
sendability guards. Receipt/status events do not generate ACK loops; a reply is
sent only when the application has an actual response.

## Rollout boundary

Before enabling the marker, verify the directory import, endpoint registration,
and one exact-ID presentation/reply proof for each platform. Do not restart
tmux, agents, or the GUI as part of this documentation checkpoint. Keep the
legacy section in the messaging skill until the cutover checkpoint is complete.
