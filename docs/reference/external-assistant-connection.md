# External assistant connection proposal

**Status: proposed interface; no server, registration or subscription is
installed.** This is the next capability-check packet for [issue #14](https://github.com/usedhonda/tproj/issues/14), not an operational setup guide.

## Evidence and selected candidate

The [assistant's response](https://github.com/usedhonda/tproj/issues/14#issuecomment-5925714846)
confirms connected-computer task execution and Slack conversation delivery.
It does not confirm custom MCP registration, external event subscriptions,
trusted Dots conversation metadata, or return to the originating Dots
conversation. Issue comments are fetched explicitly, not automatically.

The candidate is a small authenticated MCP adapter exposing the
[proposed tool catalog](external-assistant-tools.json) and
[tool contract](external-assistant-tool-contract.md), backed by the existing
owner-local mailbox/federation. No new message master is introduced.
Slack is a proven alternative conversation surface, not proof of delivery to
the original Dots conversation. Choosing Slack instead changes the requested
conversation destination and must not be done silently.

## Three distinct identity boundaries

| Boundary | Proposed check | What it does not prove |
|---|---|---|
| Cloud client and account | Supported MCP transport plus validated OAuth credentials; validate the official OpenAI client certificate where that supported transport provides it | Which assistant or cloud conversation made the call |
| Cloud conversation | Provider-supported invocation context with demonstrated provenance, mapped to the enrolled assistant and originating conversation | A model-supplied ID, display name or arbitrary `_meta` string is not authority |
| Local service process | Independent service enrollment; configured credential plus verified local process incarnation | Local PID binding alone does not authenticate a cloud conversation |

Do not expose `service_token`, `--as`, `--session`, an endpoint selector or
conversation impersonation as tool arguments. The adapter derives these from
validated context. A shared user's OAuth grant is not proof of a specific
assistant's identity. If the provider cannot establish the required context,
conversation-scoped send/read/reply/ack remain unavailable; do not bridge the
gap using shared app-server ancestry, shell tasks or another agent's identity.

## Remote MCP authentication candidate

For a supported remote MCP route, the proposed account authentication is
OAuth authorization code with PKCE, using an established identity provider.
Publish protected-resource and authorization-server discovery metadata;
validate token signature, issuer, intended resource/audience, expiry and
scopes on every request. The proposed scopes are `tproj:read` for catalog and
message reads and `tproj:write` for send/reply/ack. They are application policy,
not existing tproj or provider-defined scopes. Both still require explicit
participant, project and conversation authorization.

OpenAI's [authentication documentation](https://developers.openai.com/plugins/build/auth)
describes these MCP authentication mechanisms. They do not establish that the
current Dots environment supports this route. Do not pass a local tproj
credential through the cloud tools or substitute a static secret in a prompt.
An OAuth provider, reachable MCP endpoint and client registration are not yet
selected or provisioned. A tunnel is not assumed to work for Dots.

The [client metadata reference](https://developers.openai.com/plugins/reference)
documents `openai/subject` and `openai/session` correlation fields. Their
presence alone is insufficient authorization; native context provenance and
assistant binding remain a discovery requirement.

## Connection lifecycle (future implementation)

1. **Review, without connecting.** The assistant checks whether this tool
   catalog and authentication candidate can be used in its actual environment.
   Record supported registration surface, native invocation context, event
   destination and reply route. No credentials or real conversation IDs in
   public responses.
2. **Prepare a reviewable installation.** Select the existing identity provider
   and supported endpoint transport; prepare the independent service registry,
   project allowlist, launchd process binding, credential storage and diagnostic
   output. Keep external delivery disabled. Existing OpenClaw enrollment and
   sessions remain untouched. Proposed commands are not advertised as installed.
3. **Authorize and enroll.** Before granting new persistent cloud access or
   publishing a reachable endpoint, obtain authorization for the concrete
   account, projects, scopes and transport. Enroll the adapter independently;
   do not replace the existing service or run a blanket installer over live
   workspaces. User consent must not be inferred from another agent's approval.
4. **Connect and validate read-only.** Verify tool discovery, validated principal
   and conversation binding in a bounded test context. Reject missing,
   ambiguous or cross-conversation binding. Do not send messages as part of
   catalog discovery.
5. **Validate one round trip.** With a separately authorized bounded probe,
   record send acceptance, endpoint presentation and ID-linked reply returning
   to the originating conversation as separate evidence. Then cover concurrent
   conversations/projects, drafts, duplicates, restart and revocation using
   the minimum tests in the integration assessment.
6. **Enable supported routes only.** Record whether the connection supports
   assistant-to-session request/reply and session-initiated conversations.
   The latter requires a proven event destination and activation method;
   synchronous MCP tool responses do not prove it.

## Events, revocation and recovery

The optional [MCP Events interface](https://developers.openai.com/plugins/build/mcp-events)
is a candidate only. The future adapter must validate subscriber authorization,
callback destination and signed delivery, persist subscription/cursor/binding
metadata, and deduplicate events against mailbox IDs. A webhook `2xx` is only
acceptance; it must not mark a message as read or replied. A native event that
creates a new task does not prove resumption of the original conversation.

Revocation disables new tool access and event delivery first, invalidates the
grant/local service credential, retires the affected endpoint and removes its
subscriptions. Other services and project sessions stay running. Preserve
mailbox IDs and terminal states for diagnostics rather than deleting messages.

Recovery reconciles existing IDs and subscriptions before resuming. An
uncertain outbound result must be queried/retried with the original submission
ID, not resubmitted as a new message. No model conversation is reopened by
guessing an alias or choosing the currently active chat. Endpoint-incarnation
changes require proven continuity; the OpenClaw-specific restart exception is
not automatically inherited by this adapter.

## Capability response needed

Return a supported/unsupported/unverified result for: custom MCP registration;
the proposed tools and OAuth route; native assistant/conversation provenance;
subscription delivery destination; return to the originating conversation;
and session-initiated activation. Cite actual environment observations
separately from documentation. This review requires no configuration changes,
new access grants, live test sends, service restarts or private identifiers.
