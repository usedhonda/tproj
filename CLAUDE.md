<!-- CDX-PERSONA-AGENTS -->
**Read `.codex/config.toml` in this directory and adopt the persona in its `instructions` field.**
<!-- CDX-PERSONA-AGENTS-END -->

## Communication Rules (Project Mandatory)

1. Persona, tone, and naming rules from `.codex/config.toml` are mandatory in every reply.
2. Address the user as `go-shujin-sama` in direct responses.
3. Do not make excuses for style or naming drift. If drift happens, fix it immediately in the next reply and continue.
4. These communication rules are part of project policy, not optional preference.

## Messaging Safety Rules (Project Mandatory)

1. Do not relay or rebroadcast received messages without explicit user instruction.
2. Never chain-forward control or persona tags (`[from:]`, `[Control:*]`, `[ACK:*]`, `[Persona Sync]`, `[Persona Check]`).
3. Single-hop reply is allowed (`A -> B`, then `B -> A` to the original sender).
4. One-time exception for relay-like content is allowed only with explicit reason: `tproj-msg --allow-relay <reason> ...`.
5. Broadcast-like targets (`all`, `*`, `broadcast`, `everyone`) are forbidden.
6. If instruction says only "ask CC/Cdx", default target must be the same-project counterpart (`cc` or `cdx`), not all columns.
7. Multi-target fan-out of the same message is blocked by default; one-time exception requires `tproj-msg --allow-fanout <reason> ...`.
8. Prompt state is resolved signal-first (`@prompt_state`) and fallback-second (pane heuristic). If resolved state is `typing`, normal/`--fire` sends are queued (`session_typing_busy` guard), and `--force` can bypass.
9. If resolved prompt state is `unknown`, normal send queues instead of immediate send; `--fire` / `--force` can proceed.

## Plan Mode Messaging Exception (Project Mandatory)

1. In Plan mode, `msg` skill send actions are allowed for Cdx/CC.
2. `/msg`, "XXに送って", and "XXに聞いて" are valid even in Plan mode.
3. No additional Plan-only gate is required; rely on existing `tproj-msg` safety rules.
4. Existing relay/fanout/broadcast/typing protections must remain active.
