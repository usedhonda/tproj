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

## Commits (filled as work proceeds)

(see git log; 1 commit = 1 subphase)
