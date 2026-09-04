# tproj-bridge — a box-hosted Codex as a `gate:<id>` peer

`tproj-bridge.py` runs **on the remote box** (a Tailscale host with the Codex
CLI logged in), not on the Mac. It gives that box's Codex an inbox in the
tproj-msg mesh so a CC/Cdx pane can say `tproj-msg gate:bot01 "..."` and get
the answer back in the pane as `[from:bot01.cdx]`.

The design mirrors the Chi Gate: an external HTTP bridge with a health probe
and a reply callback into ClawGate. Nothing is injected into a tmux pane from
the box side; ClawGate on the Mac does that, exactly as it does for Chi.

```
Mac pane ──tproj-msg gate:bot01──▶ POST http://<box>:8765/v1/inbox
                                        │  codex exec (headless, on the box repo)
Mac pane ◀──[from:bot01.cdx]── ClawGate ◀── POST {return_url}/v1/tproj-msg-deliver
```

## Contract

| Endpoint | Direction | Body |
|---|---|---|
| `GET /v1/health` | Mac -> box | `{"ok":true,"id":"bot01","busy":false,"queued":0}` |
| `POST /v1/inbox` | Mac -> box | `{"from","to","session","text","trace_id","return_url","reply_as"}` -> `202 {"ok":true,"queued":n}` |
| `POST {return_url}/v1/tproj-msg-deliver` | box -> Mac (ClawGate) | `{"session","target","text","senderAs"}` |

- `to` must equal `gate:<this id>`; anything else is refused with 409 so two
  boxes can never be confused, even if a message physically reaches the wrong host.
- `trace_id` is remembered for an hour; a retried POST is acknowledged but not
  run again.
- Source IPs are limited to loopback and the Tailscale CGNAT range
  (`100.64.0.0/10`), the same rule ClawGate applies to the callback on the Mac.
- The reply is Codex's last message (`codex exec -o`), truncated to
  `TPROJ_BRIDGE_MAX_REPLY_CHARS`. A failed run still replies, with a
  `[bridge:<id>]` prefix explaining why, so the asking pane is never left waiting.

## Setup on the box

```bash
# 1. Codex logged in, repo cloned
codex login            # ChatGPT login
ls /workspace/repos/management-brain

# 2. Copy the bridge (scp from the Mac checkout, or curl the raw file)
mkdir -p ~/.local/bin
cp tproj-bridge.py ~/.local/bin/tproj-bridge && chmod +x ~/.local/bin/tproj-bridge

# 3. Run once by hand to see it come up
TPROJ_BRIDGE_ID=bot01 TPROJ_BRIDGE_REPO=/workspace/repos/management-brain \
  ~/.local/bin/tproj-bridge
# -> tproj-bridge id=bot01 listening on 0.0.0.0:8765 ...

# 4. From the Mac
curl -s http://100.64.0.10:8765/v1/health
```

Then install `tproj-bridge.service` (see that file) so it survives reboots.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `TPROJ_BRIDGE_ID` | `bot01` | The id in `gui.bridges.<id>` on the Mac; replies default to `<id>.cdx` |
| `TPROJ_BRIDGE_PORT` | `8765` | Listen port |
| `TPROJ_BRIDGE_BIND` | `0.0.0.0` | Bind address (Tailscale reaches it; the IP filter does the gating) |
| `TPROJ_BRIDGE_REPO` | cwd | Directory passed to `codex exec -C` |
| `TPROJ_BRIDGE_CODEX` | `codex` | Codex binary (e.g. `~/.local/bin/codex`) |
| `TPROJ_BRIDGE_TIMEOUT_SEC` | `1800` | Per-job Codex timeout |
| `TPROJ_BRIDGE_MAX_REPLY_CHARS` | `6000` | Reply truncation |

## Mac side

In `~/.config/tproj/workspace.yaml`:

```yaml
gui:
  bridge:
    reply_callback_url: http://<mac-tailscale-name>:8765   # already set for Chi
  bridges:
    bot01:
      url: http://100.64.0.10:8765
      # reply_as: bot01.cdx   # default
```

Then `tproj-msg --status gate:bot01`, `tproj-msg gate:bot01 "..."`. The reply
identity `bot01.cdx` is accepted by the sender verifier only when the delivery
comes through the local ClawGate process (verifier class 3 in
`docs/reference/tproj-msg-sender-verification.md`).

This file is **not** distributed by `install-tproj-messaging-runtime`; it is a
box-side component and is copied there by hand.
