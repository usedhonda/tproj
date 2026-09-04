# Bridge targets: `gate:<id>` (#12)

A **bridge** is a remote inbox for a Codex that has no tmux pane -- typically a
Tailscale box that carries a project's server-side workspace. It is addressed
from any pane as `gate:<id>` and replies into the asking pane as
`[from:<id>.cdx]`. The shape follows the Chi Gate deliberately: an external
HTTP bridge, a health probe, and the reply routed through ClawGate's existing
callback receiver rather than a second listener.

Box-side component: `extensions/messaging/bridge/tproj-bridge.py` (see its
README). Mac-side: `extensions/messaging/tproj-msg`.

## Configuration

```yaml
gui:
  bridge:                      # the Chi/ClawGate singleton, unchanged
    url: http://localhost:8765
    reply_callback_url: http://<mac>.<tailnet>.ts.net:8765
  bridges:                     # one entry per remote box
    bot01:
      url: http://100.64.0.10:8765
      # reply_as: bot01.cdx    # default <id>.cdx
```

- Ids are plain identifiers (`[A-Za-z0-9][A-Za-z0-9_-]*`). An id equal to a
  reserved ClawGate adapter name (`direct`, `line`, `tmux`, `session`,
  `default`) is refused by `bridge_config_check()` before any mode runs, so
  `gate:direct` can never mean two different things.
- `gui.bridge` and `gui.bridges` are independent; the singleton's readers are
  untouched.

## Target resolution

`is_bridge_target` matches `gate:<id>` only when `<id>` is a configured key.
`is_gate_target` now returns false for such targets, so every gate-only policy
stays off bridges: the Chi 24h recovery block, the `[line-private]` lane
rewrite, and the ClawGate `send_dedup` exemption. `target_family_from_target`
reports `bridge`, which keeps fan-out accounting separate from `gate`.

## Send

`send_via_bridge <id> <message>` POSTs a jq-built envelope to `<url>/v1/inbox`:

```json
{"from":"tproj.cc","to":"gate:bot01","session":"tproj-workspace",
 "text":"...","trace_id":"tproj-msg-bot01-<epoch>-<pid>",
 "return_url":"<gui.bridge.reply_callback_url>","reply_as":"bot01.cdx"}
```

No `[tproj-msg:...]` text header is prepended; the envelope carries the
sender. Newlines survive (the ClawGate path collapses them). Timeouts match
`send_via_gate` (`--connect-timeout 3 --max-time 10`). A 2xx is recorded in
`messages.db` as `delivery=gate`, `bridge=bridge`, `to_alias=gate:<id>`,
`external_id=<trace_id>`; failures as `delivery=error` with the reason.

## Dedup

The gate dedup store (`TPROJ_MSG_GATE_DEDUP_DIR`) now records `family:adapter`
(`gate:direct`, `bridge:bot01`) and blocks only a same-body send to **another
adapter of the same family** within `TPROJ_MSG_GATE_DEDUP_SEC`. The same body
to Chi and then to a box is two recipients, not a duplicate. The record is
split on its last colon because the label itself contains one.

## Status and list

- `tproj-msg --status gate:<id>` -> `online/idle`, `online/busy`, or `offline`,
  from `GET <url>/v1/health` -> `{"ok":true,"busy":<bool>}`. Unlike
  `gate_health`, the HTTP status is inspected: a non-2xx is `offline`.
- Bare `--status` and `--list` append one row per configured bridge.

## Reply

The box POSTs `{session, target: <from>, text, senderAs: <reply_as>}` to
`<return_url>/v1/tproj-msg-deliver`. ClawGate accepts loopback and Tailscale
CGNAT sources and execs `tproj-msg --as <reply_as> --session <session>
<target> <text>` locally. That `--as` is accepted by **verifier class 3**
(`docs/reference/tproj-msg-sender-verification.md`): the claimed identity must
be the `reply_as` of exactly one configured bridge **and** the caller's
ancestry must contain the trusted ClawGate executable. Audit rows carry
`auth_path = bridge-sender-verified | bridge-sender-rejected`.

## Acceptance (issue #12)

1. `--status gate:bot01` reports bridge liveness -- `bridge_health`.
2. A Mac pane can send and the box receives -- `send_via_bridge` +
   `tproj-bridge.py /v1/inbox`.
3. The reply returns as `[from:bot01.cdx]` -- class-3 verifier via ClawGate.
4. Two bots are never confused -- separate `gui.bridges` entries, `to` checked
   by the box (409 on mismatch), `test-sendability-gate.sh` BR2.
5. Existing pane messaging and the Chi gate are unchanged -- gate readers and
   policies untouched; suites green.

Tests: `test-sendability-gate.sh` (BR1-BR5), `test-role-handoff.sh`
(`bridge_reply_*`), `test-bridge-server.sh` (box side, hermetic).
