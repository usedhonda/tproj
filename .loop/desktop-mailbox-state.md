# Desktop <-> tmux session mailbox — implementation state

Plan: `~/.claude/plans/fizzy-floating-bee.md`
Upper contract: `refactor-instructions.md` §3/§4/§5
Role: worker = tproj.cc (tproj-owned mailbox CLI + tests + docs)

## Phase 0 — baseline (recorded before any edit)

Date: 2026-07-17. Branch: main. Working tree: clean.
HEAD: b951325 test(messaging): add R2 Stage 2 caller-verification hardening fixtures

Baseline gates (all green):

| gate | count |
|---|---|
| test-sendability-gate.sh | PASS=40 FAIL=0 PENDING=0 |
| test-registry-contract.sh | PASS=4 FAIL=0 |
| test-role-handoff.sh | PASS=22 FAIL=0 |
| test-inbox-check.sh | 8 passed, 0 failed |
| tests/smoke-bin.sh | PASS=17 FAIL=0 |
| test-caller-verify-hardening.sh | PASS=13 FAIL=0 SKIP=1 |

intent-guard: started (Task Intent locked).

## General schema status (read-only inspection)

`~/.cache/tproj-model-role/` has two session dirs: `standalone/` and `tproj-workspace/`.
The only standalone entry is `standalone/standalone/unknown.agent.json`:
- alias="unknown.agent", column="standalone", session="standalone",
  platform="claude", project="<CodexBar/ClaudeProbe path>", role="solo-fallback".
- NO `identity_class` field. NO `desktop` concept anywhere in the registry or the
  general router (grep of extensions/messaging = 0 hits for desktop/standalone/identity_class).

Conclusion: general's canonical `identity_class=desktop` Desktop registry schema
(task tproj-29737970-01) is NOT yet defined. This implementation isolates the
schema consumer in ONE function (`resolve_desktop_identity` in
`extensions/messaging/tproj-msg-desktop.sh`) documented with an ASSUMED SCHEMA +
Phase-6 integration TODO. Phase 6 (final field integration) and push are deferred.

## Design summary

- New helper: `extensions/messaging/tproj-msg-desktop.sh` (function-only, sourced by tproj-msg).
- Mailbox root: `${XDG_CACHE_HOME:-$HOME/.cache}/tproj-msg/desktop-mailbox/` (0700).
  - to-session/<session>/<target_alias>/  <- Desktop writes here (session reads)
  - to-desktop/<project>/                 <- session writes here (desktop reads)
- 0600 atomic envelopes (temp+rename, umask 077). Bounds: 64KB/env, 200/mailbox, 7d TTL.
- Desktop identity resolved by PID ancestry + recorded pid_start (reuse
  find_registry_ancestor_match / pid_start_epoch_bash). Body/role-label independent.
- Desktop side never touches panes: no send-keys, no queue, no task tracking.
- Desktop->session also logs a body-free inbound DB row (bridge=desktop, empty body)
  so the existing inbox-monitor rings a count-only bell.
- auth_path enum += desktop-mailbox / desktop-rejected.
- Control use from Desktop rejected: --new-task/--role-handoff/--force/--as/relay/fanout.

## Commits

- b312ccc chore(messaging): record desktop-mailbox baseline + assumed-schema note (Phase 0)
- f4bad69 feat(tproj-msg): Desktop data-plane mailbox — identity + send + read + reject
  (Phase 1 identity resolver, Phase 2 Desktop->session write + body-free bell,
   Phase 4 desktop-side read, Phase 5 control reject; helper + 22-case test)
- 678914d feat(tproj-msg): session side (send to desktop.<project>, --read desktop)
  (Phase 3 session->desktop write, Phase 4 session-side read; test -> 26 cases)
- (docs + install.sh + help + state) — this commit

Phase-to-commit note: Phase 1 (identity) and Phase 2 (Desktop->session write) landed
together in one coherent, fully-working commit rather than a non-functional
identity-only intermediate (per §5.3A "no half-working commit"). Each commit is
independently working with all gates green.

## Final gate status

sendability 40 / registry-contract 4 / role-handoff 22 / caller-verify-hardening 13(+1 skip) /
inbox-check 8 / smoke-bin 17 — all unchanged & green. New gate test-desktop-mailbox.sh: 26/26.

## Deferred (Phase 6 + push)

- General canonical `identity_class=desktop` schema is NOT yet published. The consumer
  is isolated in `resolve_desktop_identity` / `_desktop_registry_entry_is_desktop` /
  `_desktop_project_of_entry` with an ASSUMED SCHEMA + Phase-6 TODO. Only those functions
  change when general lands the schema.
- push is NOT done (orchestrator tproj.cdx does cross-repo verification first).
