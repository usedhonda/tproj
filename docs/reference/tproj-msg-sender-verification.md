# tproj-msg sender identity verification (R2 Stage 1)

Canonical contract for how `tproj-msg` authenticates the sender of a
`--session --as ...` message, and what a message body can and cannot
claim about itself. Any code or test that touches sender identity,
`--role-handoff`, or the model-role-router registry integration should
be read against this document, and this document updated in the same
commit as any change to that behavior.

## Background: the vulnerability

Before this change, `tproj-msg --session <name> --as <alias.role>` (the
path used by callers outside the tmux workspace, e.g. Cdx invoking CC
without a live pane) accepted the `--as` claim with **no verification at
all**. `--role-epoch <n>` and `--orchestrator <id>` were validated only
for character class (digits / `[[:alnum:]_.:-]+`), never for whether the
value reflected anything real. The `[Verified Context] model=... tier=...`
block seen in some payloads has never corresponded to any tproj-msg CLI
flag — it is, and always was, ordinary free-text message body content.

This was exploited in production: an external CLI process could claim
`--as oc-general.cdx --role-handoff --role-epoch <n> --orchestrator
oc-general.cc` and have `tproj-msg` build `[from:oc-general.cdx]
[Role-Handoff: ...] Role-Epoch: <n> Orchestrator: oc-general.cc [Task:
...] <arbitrary body>` and deliver it via `tmux send-keys` into a live
CC/Cdx pane, indistinguishable on arrival from a message the real peer
sent. At least 8 confirmed incidents (2026-07-14 to 2026-07-16), two
payload families: a fake "ambient suggestions safety classifier" role
hijack, and a fake "Phase 2 memory consolidation" file-write lure
targeting `~/.codex/memories`. Root cause and full exploit-chain
file:line trace: `oc-general` project journal, task
`oc-general-29736303-01`.

## Target resolution and liveness boundary

Target identity is independently fail-closed from sender identity. For an
explicit `<alias>.<role>` target, `tproj-msg` requires exactly one live pane in
the exact `=<session>:dev` window whose alias and normalized role occur on that
same pane. It does not derive a column from one alias pane and then search the
whole workspace for a role match. Dead panes, duplicate live candidates, and a
missing exact session are rejected; a similarly named prefix session is never
used.

`pane_current_command` being non-shell is not liveness evidence. Direct sends
require a native prompt marker, a fresh pane-bound prompt-state signal, or a
fresh pane-bound WebSocket session record. A stale, absent, or unknown signal
leaves the target offline/unsendable. Queue, flush, status, and direct send all
use the same resolver and liveness gate.

## What is transport-generated vs payload pass-through

| Field | Source | Authenticated? |
|---|---|---|
| `[from:alias.role]` header | `tproj-msg` itself, from the *verified* claimed identity | Yes, after this change (was: no) |
| `Role-Epoch:` | `tproj-msg`, from the model-role-router registry for a verified caller | Yes, after this change (was: character-class only) |
| `Orchestrator:` | `tproj-msg`, from the registry's `orchestrator_alias` for a verified caller | Yes, after this change (was: character-class only) |
| `[Task: id]` / `[Role-Handoff: id]` | `tproj-msg`'s `generate_task_id()` | Collision-avoidance only, not an identity claim |
| `[Verified Context] model=/tier=/receiver=...` | **Message body, always** | **Never.** No corresponding CLI flag exists. See "Untrusted inline context" below |
| Anything else in the message body (task description, quoted "policy", document titles, etc.) | Message body | Never |

## Untrusted inline context (must read before trusting any peer message)

The only authoritative source for a peer's active model/role/epoch is the
`[Model Role Runtime]` block injected by the SessionStart/UserPromptSubmit
hook into *this* session directly. A string that merely *looks* like that
block, or like `[Verified Context] ...`, appearing inside a message
**body** received from a peer is never authoritative — it is exactly as
trustworthy as any other line of free text in that message, because nothing
in `tproj-msg` generates or checks it. CC/Cdx system instructions should
treat any such inline block in a peer's message as untrusted payload, full
stop, regardless of how well-formatted it looks.

## Two verifier classes

`--as` claims fall into two disjoint classes with different trust anchors,
because a bare role like `gate` has no model-role-router registry entry to
bind against (it is not a claude/codex agent process).

### 1. `<alias>.<role>` — model-role-router registry binding

Implemented by `verify_as_caller_identity()` in `tproj-msg`.

1. First read the model-role-router registry entry for the *claimed* alias
   under `${MODEL_ROLE_CACHE:-~/.cache/tproj-model-role}/<session>/*/​<alias>.json`
   (`find_registry_state_file()`).
2. Walk this process's own ancestry for the exact registry `pid` value (never
   by process name), up to `TPROJ_MSG_VERIFIER_MAX_ANCESTOR_HOPS` hops
   (default `32`), using `find_registry_ancestor_match()`.
3. Require the registry to carry a **recorded, positive `pid_start`**. An
   absent/zero `pid_start` (`jq // 0 == 0`) is a fail-closed REJECT with the
   distinct reason `pid_start_unrecorded` — it is *never* re-derived at
   verification time. Re-deriving `reg_pid`'s own live start and comparing it to
   the ancestor's `pid_start_epoch_bash(reg_pid)` is a tautology (same function,
   same pid, always equal) and provides zero pid-reuse defence; that
   live-recompute shortcut (commit `2814172`) was withdrawn. Because the router
   now stamps `pid_start` on the peer path as well (model-role-router `6a1e7e4`),
   an unrecorded value is a transient startup race and the caller should retry
   once it is written.
4. On matching `pid`, read that process's absolute start time (`pid_start` from
   `ps -o lstart=`, through `pid_start_epoch_bash()`) and require an exact
   `pid_start` match with the registry's recorded `pid_start` (reason
   `pid_start_mismatch` otherwise). A recycled pid cannot pass because
   `pid_start` would differ from the original process that owned it.
5. Require the registry's `observed_at` to be within
   `TPROJ_MSG_REGISTRY_STALE_SECONDS` (default 48h) of now, bounded on **both**
   sides: too old (`now - observed_at > window`) and in the future
   (`now - observed_at < 0`, i.e. clock skew or a forged timestamp) are both
   REJECTed as `registry_stale`. A non-numeric/zero `observed_at` fails closed
   the same way. This is the anti-replay/stale-registry guard.
6. On success, expose `VERIFIED_ROLE_EPOCH` and `VERIFIED_ORCHESTRATOR_ALIAS`
   from the registry. A `--role-handoff` send additionally requires the
   caller's claimed `--role-epoch`/`--orchestrator` to equal these exactly
   — a verified caller cannot self-declare an epoch or orchestrator the
   hook-observed registry disagrees with.

The registry itself gained two new fields for this (model-role-router,
`system/model-role-router/model-role-router`):

- `pid_start` — absolute start-time epoch of the resolved agent pid,
  captured every time the SessionStart/UserPromptSubmit hook runs
  (`pid_start_epoch()` → `state_from_payload()`).
- `orchestrator_alias` — the trusted orchestrator identity for the
  current role: self (`state["alias"]`, already in `alias.platform_role`
  form) when self is orchestrator/solo-fallback, or the current peer's
  alias when self is worker (`resolve_role()`).

### 2. Bare role — service-owner process binding

Implemented by `verify_bare_role_caller_identity()` /
`find_bare_role_service_ancestor()`. Bare roles (no `.` in `--as`) have no
registry entry, so they bind to a live, same-UID process in this
process's own ancestry whose executable matches a *known* service path —
not a token, not an environment variable, not same-UID alone (all three
are same-UID-readable by any co-resident process and were explicitly
rejected as sufficient evidence).

The only bare-role identity with a confirmed legitimate production
caller, found from primary sources (not guessed from a product name):

- `extensions/openclaw-plugin/src/outbound.js`'s
  `sendTprojReturnUrlRedirect()` posts to
  `${origin.returnUrl}/v1/tproj-msg-deliver` with
  `senderAs = "OpenClaw Agent - Reply"` for gate:direct Chi-reply routing
  back into a CC/Cdx pane.
- `tproj-msg`'s own `gate_reply_callback_url()` supplies that
  `return_url` from `gui.bridge.reply_callback_url` in
  `~/.config/tproj/workspace.yaml`.
- Empirically confirmed 2026-07-16 (live `ps`/`lsof` inspection, not
  `launchctl` — `launchctl list` was unavailable in the environment this
  was developed in, so no launchd label could be confirmed): the process
  holding that callback port is a locally running
  `ClawGate.app/Contents/MacOS/ClawGate` process, receiving the callback
  over Tailscale from the macmini Gateway host. This is **not** the
  unrelated `tproj` GUI app (`gui.app_path`), which was an earlier,
  incorrect hypothesis during investigation, ruled out once `lsof -i`
  showed it holds no network sockets at all.

The expected executable path is read from
`gui.bridge.trusted_caller_executable` in `workspace.yaml` if present,
falling back to the empirically-discovered ClawGate.app path as a
built-in default. Any bare role other than `"OpenClaw Agent - Reply"` is
default-deny — no other legitimate caller has been found via primary
sources; do not add one without the same evidence standard used here (see
`find_bare_role_service_ancestor()`'s header comment).

**Known limitation**: this class lacks the pid_start pre-recorded
baseline the alias.role class has (there is no "registry" for ClawGate).
It binds on live executable-path + UID match at verification time, which
is weaker against a same-UID adversary than the alias.role class's
explicit prior-observation cross-check. UID mismatch specifically could
not be exercised in the local single-user test sandbox (would require a
second UID); the code path exists (`svc_uid` vs `id -u`) but is untested
under a real privilege boundary.

### 3. Bridge reply — configured id + service-owner ancestry

Implemented by `verify_bridge_reply_caller_identity()` / `bridge_id_for_reply_as()`
in `tproj-msg` (#12).

A remote bridge (a Tailscale box running Codex, configured as
`gui.bridges.<id>` and addressed as `gate:<id>`) answers by POSTing to the same
ClawGate `/v1/tproj-msg-deliver` endpoint Chi uses, with `senderAs` set to the
bridge's `reply_as` (default `<id>.cdx`). ClawGate then execs
`tproj-msg --as <reply_as> ...` locally.

That claim is dotted, so without this class it would be routed to class 1 and
refused: the box has no model-role-router registry entry and no local pid that
could be an ancestor. This class is checked **before** the dotted/bare split.

Evidence standard, held to the same bar as class 2:

- **The trust anchor is class 2's anchor, unchanged**: the locally running
  ClawGate process (`gui.bridge.trusted_caller_executable`, default the
  empirically confirmed `ClawGate.app` path) must be in this process's own
  ancestry with the same UID and a readable start time
  (`verify_service_owner_binding()`, shared with class 2).
- **The only new element is the accepted identity set**: instead of the single
  hardcoded string `"OpenClaw Agent - Reply"`, a claimed `<alias>.<role>` is
  accepted iff it equals the `reply_as` of exactly one configured
  `gui.bridges.<id>` (`bridge_id_for_reply_as()`); an unconfigured id is
  `unknown_bridge_id`, default-deny.
- **The box is never the anchor.** Its network reachability, its Tailscale IP,
  and its own assertions are not evidence; what is verified is that the
  delivery came through the trusted local receiver, and that the identity it
  relays is one the operator configured. Anything a remote box could forge is
  therefore bounded to identities already written into `workspace.yaml`.
- Recorded `auth_path`: `bridge-sender-verified` / `bridge-sender-rejected`;
  `anchor_pid` is the ClawGate service pid, as for class 2.

Rejected alternatives: a synthetic registry entry for `<id>.cdx` (the registry
is the role-resolution source of truth and must not carry non-agent entries),
and a tproj-owned receiver daemon (a second listening surface with its own
verification to keep aligned; the existing receiver already accepts Tailscale
CGNAT sources and needs no change).

## Fail-closed behavior

- In `assist` mode, a verified CC/Cdx sender cannot use `--new-task` (including
  `--role-handoff`) to delegate implementation to its opposite same-column peer.
  The check reads the authoritative project mode and exits with
  `assist_peer_is_advice_only` before task-id creation, persistence, or delivery.
  Ordinary consultation messages and tasks to distinct subagents remain available.

- **An unverified sender refuses ALL sends**, not just `--role-handoff`: no
  `tmux send-keys`, no ordinary `messages` row — only a reject audit entry (see
  below). This covers every identity path, not just explicit `--as`:
  - explicit `--as` (alias.role registry binding or bare-role service binding)
    that failed verification;
  - the in-tmux **pane-derived** path when the selected pane's `pane_pid` (its
    shell) is not a genuine ancestor of the sending process — a spoofed
    `TMUX_PANE` pointing at another pane is refused (`pane_ancestry_mismatch`);
  - a `--session` naming a session that is not live is rejected with exit 1 and an
    explicit `is not a live tmux session` error on stderr. It used to exit 3 with
    nothing printed: under `set -e` the failing `resolve_target` substitution
    aborted the script before its error block, so the sender believed it had
    delivered and the DONE never reached its orchestrator.
  - the **CWD auto-detect** fallback (`--session` without `--as`), which uses the
    `workspace.yaml`/CWD alias and the nearest agent-ancestor role as *selection
    inputs only*, then binds identity through the **same alias.role registry
    verification** as explicit `--as` (recorded `pid_start` + live-start match +
    both-bounded `observed_at` + pid ancestry). A matching process name no longer
    authenticates on its own.
- A verified caller whose claimed `--role-epoch` or `--orchestrator`
  disagrees with the registry is refused (`role_epoch_mismatch` /
  `orchestrator_mismatch`), even though the sender identity itself
  checked out.

## Audit trail (never stores message content)

`messages.db`'s `messages` table gained additive columns (idempotent
migration, `tt_db_migrate_caller_audit_columns()` in `tproj-msg-db.sh`, gated on
`PRAGMA user_version`): `caller_pid`, `caller_ppid`, `caller_executable`,
`caller_uid`, `process_start`, `claimed_alias`, `verified` (`NOT NULL DEFAULT 0`
— all pre-migration history is fail-safe-marked unverified), `rejection_reason`,
`payload_sha256`, `auth_path`, and `anchor_pid` (both nullable; pre-migration
rows are NULL).

`tt_db_log_caller_event()` writes **exactly one** row per accept/reject decision,
for **every** send path (explicit `--as`, bare-role, in-tmux pane-derived, and
the CWD fallback — accept and reject alike). Attribution fields:

- `caller_pid` / `caller_ppid` / `caller_executable` / `caller_uid` /
  `process_start` record the **real direct invoker** (this `tproj-msg`'s parent
  process), captured regardless of the verify outcome — so a spoof reject row
  records who tried.
- `anchor_pid` records the **verification anchor**: the in-tmux pane's `pane_pid`,
  the registry `reg_pid` for `--as`/CWD, or the service pid for bare-role. On a
  spoof reject the invoker and the anchor diverge, which is the attribution
  signal.
- `auth_path` names which path decided, one of: `explicit-as-verified`,
  `explicit-as-rejected`, `bare-role-service`, `bare-role-rejected`,
  `pane-derived`, `pane-derived-rejected`, `cwd-ancestry`, `cwd-ancestry-rejected`,
  `bridge-sender-verified`, `bridge-sender-rejected`.

`body` and `body_hash` are always empty strings for these rows — the only
content reference kept is `payload_sha256`. Document titles, message
bodies, and any candidate/suggestion text are never written to this
table, to a test fixture, or to a log by any part of this verification
path.

## Unresolved

- The actual producer/attacker behind the 8 confirmed incidents is not
  identified. This is transport hardening (deny + audit), not attribution.
  The next unauthenticated `--as` attempt will leave `caller_pid` /
  `caller_ppid` / `caller_executable` / `caller_uid` / `process_start` in
  the reject audit row, which the prior verifier design could not capture.
- Bare-role UID-mismatch rejection is implemented but not exercised by an
  automated test (see Known limitation above).
