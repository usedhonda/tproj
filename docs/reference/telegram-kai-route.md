# Dedicated Telegram route to existing KAI

Status: implementation candidate; not enrolled, installed or phone-accepted.
Protocol contract: [unified messaging](unified-messaging.md).

## Required operator-owned configuration

Create a dedicated bot using the official BotFather, not the existing Chi bot.
Never send its token to KAI, commit it, or include it in diagnostics. The owner
starts the dedicated bot on the phone. Derive the allowed numeric owner identity
from an already verified owner registration, not the first arbitrary person to
message the new bot. A display name, username, body claim or forwarded message
does not establish identity. A new owner tuple requires explicit operator
approval; it is not an automatic first-message registration.

Run `telegram_runtime.py --config <private-file>` as the main process of its
registered launchd service. The file must be a current-UID regular file, mode
0600, and its SQLite journal must be in a current-UID mode-0700 directory. The
runtime config has:

- `bot_token_keychain`: reference with `service: "openclaw.kai.telegram"` and
  `account` equal to the decimal bot ID. Store the actual credential in macOS
  Keychain through a no-echo input flow; plaintext token config is not accepted.
- `owner_binding`: approved object with `binding_id`, `owner_id`, `bot_id`,
  `user_id`, `chat_id`, `target` (existing KAI address), integer `generation`,
  epoch `expires_at`, and boolean `revoked`.
- `host_socket`, `service_id` (`telegram`), `service_token`, `address`, and
  `binding_generation` matching the enrolled host service.
- `journal`: private SQLite path; `kai_endpoint`: existing KAI service endpoint.

The host's `services.telegram` has the existing standard service fields:
`participant_id`, `address`, private `token`, `launchd_label`, `platform`
(`telegram`), persistent `binding_generation`, and `allowed_addresses` containing
only the intended existing KAI address. Its additional `telegram_ingress` object
contains `mode: "long_poll"` and the same approved `owner_binding`.

The hub config's `telegram_ingress_bindings` maps that `binding_id` to
`host_id`, `participant_id` (the dedicated Telegram participant), and the same
approved `owner_binding`. These values are operator enrollment, not RPC input.
Register the dedicated Telegram participant in the existing hub directory;
do not replace/re-enroll the existing KAI participant or change its event pump.

Host and hub reload their configurations per request. Revoke the owner binding
on both sides; rotating a transport credential is not a substitute for revoking
the owner binding. Historical origin is retained for auditing but inactive
origin is not current owner authority. Already-started effects cannot be undone.

## Installation and acceptance

The installer distributes the new inert modules but does not create private
configuration, register services, install a bot or restart anything. Inspect
installed-code drift before staging the reviewed files. Retain existing KAI
service identity, event subscription and state. Do not install an entire old
checkout over a newer live runtime.

The dedicated process authenticates `getMe`, validates its fixed bot identity,
then authenticates `service_whoami`. `getUpdates` text goes to the host's dedicated
ingress operation, not ordinary `service_send`. The host constructs origin;
the hub validates attestor and tuple. KAI reads the origin via its existing MCP
tools and replies against the exact original mailbox message ID. The adapter
requeries the reply and sends its body unchanged with Telegram reply correlation;
it never invokes the Chi model.

Live acceptance must separately show:

1. Owner phone text arrives at the existing KAI, with current active origin.
2. KAI response returns to that phone's original chat and message.
3. Distinct continuing outputs arrive without another owner prompt.
4. Other senders, forwarded messages and old bindings do not invoke owner work.
5. Restart does not change identity, duplicate a known send or invoke Chi.

MVP limitations: private plain text only, replies at most 4096 characters, no
media/voice handling, no automatic reconciliation after an uncertain submission
or Telegram send. The process stops on uncertainty; inspect receipts instead of
recreating a request ID or deleting the journal. Local regression checks are not
evidence of actual phone delivery or current KAI consumption.

### Operational deployment notes

- On messaging-only networks, do not require opening a `t.me` web link.
  Deliver the one-use `/start <challenge>` as copyable text in the verified
  private owner channel; the owner pastes it into the dedicated bot's existing
  Telegram app conversation. Match the same challenge and consume it once.
  Do not infer the Telegram operation time from a delayed report in another app.
- Use an exact direct credential copy, not OCR correction guesses. Official
  bot identity authentication and a Keychain read-back establish the saved
  credential; do not repeatedly ask for it after those checks succeed.
- The launchd service bridge and tunnel-spawned MCP stdio child are separate
  processes. Restarting the bridge alone does not reload a previously running
  child's `MailboxTools` projection. Identify both processes and narrowly reload
  the existing tunnel when necessary, retaining service identity and event state.
  Verify provenance in KAI's actual structured tool result, not only installed
  source bytes or hub storage. Never resend an existing reply for this check.
- Record host acceptance, KAI read/reply, Telegram API acceptance and owner phone
  receipt separately. A process being alive is not end-to-end acceptance.
