# tproj-task-cache.sh — Contract & Race Test Spec

Lane D3 deliverable. This document pins down the public contract of the Task ID cache helper used by `tproj-msg --new-task`, `tproj-task` CLI, `tproj-inbox-record` (D4 PostToolUse hook), and `tproj-inbox-check` (D5 UserPromptSubmit hook).

Scope: implementation guidance for cache consumers and the regression surface checked by the current orchestrator during independent verification.

---

## 1. File layout & storage

| Aspect | Value |
|---|---|
| Cache root | `${TT_CACHE_DIR:-${HOME}/.cache/tproj-expect-reply}` |
| Owner key | `<session>/<owner_alias>` — the tmux session name plus the issuing pane's `@alias` (the column that delegated the task) |
| Per-target file (v2) | `<cache_root>/<owner>/<target>.json` (one JSON object per target, under an owner subdir) |
| Lock dir root | `${TT_CACHE_LOCK_DIR:-/tmp}` |
| Per-owner-per-target lock | `<lock_root>/tproj-task-cache~<session>~<alias>~<target>.lock` (mkdir advisory lock; `~` is absent from the component charset so the join is injective) |
| Sequence dir | `/tmp/tproj-task-seq/<target>/<epoch_min>/NN/` (mkdir-atomic counter, D1 responsibility) |
| Required tools | `jq` (must), `shasum` or `sha1sum` or `cksum` (any one) |
| Optional tools | `flock` is **NOT** used (macOS default lacks it) |
| Legacy (pre-v2) | flat `<cache_root>/<target>.json` files are drained silently by `tt_cache_gc_legacy_flat` (TTL-GC, no notice, no owner guess) |

### Owner scoping (cross-column leak fix)

The cache is **owner-scoped**: every mutating and enumerating op takes the owner
key `<session>/<owner_alias>` as its first argument and touches ONLY that owner's
subdir. This prevents one column's UserPromptSubmit hook from reading, GC-ing,
notifying on, or `--read`-driving another column's tracked tasks.

Owner resolution is **fail-closed**. `tt_cache_valid_owner` requires exactly two
collision-safe components (`<session>/<alias>`) separated by a single slash,
neither being the `unknown`/`null` resolution sentinel. On an invalid owner,
mutations refuse (`tt_cache_add` returns 2; `tt_cache_remove_task` is a no-op)
and read/list ops return empty. A caller that cannot resolve its own
`<session>/@alias` (e.g. a hook running outside tmux) writes and emits nothing
rather than guessing.

**Path-component collision resistance.** Every component that reaches a cache
path (session, alias, and target) is validated by `tt_cache_valid_component`,
which **rejects** (never sanitizes/transforms) an empty string, `.`/`..`, or any
character outside `[A-Za-z0-9._-]`. This keeps the `<session>/<alias>/<target>`
mapping injective — no two distinct inputs collapse onto the same file — and
blocks traversal (`..`, embedded `/`). `tt_cache_add` and `tproj-inbox-record`
return fail-closed on an invalid target; remove/get/list ops treat it as a
no-op/empty. The canonical workspace aliases (`ble-bridge`, `creator_radar`,
`tproj`, `tproj-workspace`, `tproj.cdx`, ...) all pass.

### JSON shape (per target file)

```json
{
  "<task_id>": {
    "target":       "<target>",
    "sent_at":      <int-epoch-seconds>,
    "expect_until": <int-epoch-seconds>,
    "ttl_sec":      <int>,
    "msg_hash":     "<sha1-hex-or-cksum-decimal>",
    "state":        "pending|acked|done|blocked|received|verified|cancelled|frozen",
    "task_kind":    "delegated|role_handoff",
    "intent_hash":  "<sha256-hex-or-empty>",
    "user_authorized_exact": 0,
    "role_handoff_epoch": null,
    "orchestrator": "<alias.role-or-empty>",
    "tombstone_reason_hash": "<hash-or-empty>",
    "notices":      {"<event>": <int-epoch-seconds>}
  },
  ...
}
```

- Empty files are removed only after platform-observed `USER_REPORTED`; consumers treat missing files as "no open tasks for that target".
- Atomic writes use `tmp + mv` under lock.
- `msg_hash` is opaque to consumers; D4 may pass empty string if hashing is not feasible.

---

## 2. Public API (MUST)

Source the library (`source /path/to/tproj-task-cache.sh`). All functions return non-zero on hard failure (missing `jq`, broken JSON) and zero on idempotent no-op.

### 2.1 Utilities

| Function | Signature | Behavior |
|---|---|---|
| `tt_cache_require_jq` | `()` | Returns 0 if `jq` is on PATH, else 127 with stderr message. Called internally by mutation ops. |
| `tt_cache_valid_component` | `(component)` | Returns 0 iff `component` is non-empty, not `.`/`..`, and matches `[A-Za-z0-9._-]+`. Rejects (never sanitizes) so distinct inputs never collapse onto one path. Used for session, alias, and target. |
| `tt_cache_valid_owner` | `(owner)` | Returns 0 iff `owner` is a well-formed `<session>/<alias>`: exactly two `tt_cache_valid_component`s separated by one slash, neither an `unknown`/`null` sentinel. Fail-closed gate used by every owner-scoped op. |
| `tt_cache_owner_dir` | `(owner)` | Prints `<cache_root>/<owner>` on stdout. No side effects. |
| `tt_cache_init_dir` | `([owner])` | With `owner`, validates it (`tt_cache_valid_owner`) and `mkdir -p`s that owner's subdir; an invalid owner returns non-zero with **no mkdir** (fail-closed traversal guard). Without an owner, ensures the cache root. Safe to call repeatedly. |
| `tt_cache_path_for_target` | `(owner, target)` | Prints `<cache_root>/<owner>/<target>.json` on stdout. No side effects. |
| `tt_cache_lock_for_target` | `(owner, target)` | Prints `<lock_root>/tproj-task-cache~<session>~<alias>~<target>.lock` (injective `~`-join). No side effects. |
| `tt_cache_acquire_lock` | `(lock_dir, timeout=5)` | mkdir-based advisory lock. Returns 0 on acquire, 1 on timeout. Writes `$$` into `<lock_dir>/pid` (best effort). Detects stale locks by checking if `pid` process is alive. |
| `tt_cache_release_lock` | `(lock_dir)` | `rm -rf "$lock_dir"`. Idempotent. |
| `tt_cache_ttl_to_seconds` | `(spec)` | Parses `"30m"`, `"2h"`, `"45s"`, `"1d"`, or raw int seconds. Prints seconds on stdout. Returns 2 on invalid spec. |
| `tt_cache_msg_hash` | `(msg)` | Prints SHA1 hex via `shasum`/`sha1sum`, falls back to `cksum` decimal. Never fails. |

### 2.2 Cache mutation

| Function | Signature | Behavior |
|---|---|---|
| `tt_cache_add` | `(owner, target, task_id, sent_at, ttl_sec, [msg_hash], [task_kind], [intent_hash], [user_authorized_exact], [role_handoff_epoch], [orchestrator])` | **Single-writer role** — called only by D4 PostToolUse hook for cache insertion. Adds or refreshes `<owner>/<target>.json`, computing `expect_until = sent_at + ttl_sec`, and records only structural metadata / hashes (never delegated body text). Invalid owner returns 2 (fail-closed). Shadow-writes the durable DB task row with the same metadata. Takes per-owner-per-target lock. |
| `tt_cache_transition_state` | `(owner, target, task_id, state, [now_epoch])` | Monotonic in-place transition. ACK and ACK-PROGRESS become `acked`; valid terminal evidence advances through `done|blocked` to `received`; verification becomes `verified`; owner tombstones become `cancelled|frozen`. Tombstones are terminal except same-state idempotency. Never removes the entry. |
| `tt_cache_tombstone_task` | `(owner, target, task_id, cancelled\\|frozen, reason_hash, [now_epoch])` | Exact-owner durable tombstone. Writes only the structural `reason_hash`, never raw body/prompt text. Idempotent on repeated same-state requests; rejects cross-owner and cross-target mutation. Shadow-writes DB tombstone columns and resets the receiver one-shot notice marker. |
| `tt_cache_apply_reply` | `(owner, target, task_id, tag, [message_id], [body_hash], [owner_recipient], [now_epoch])` | Applies ACK/ACK-PROGRESS as non-terminal. DONE/BLOCK requires a matching inbound DB row for the exact sender, recipient, message id, body hash, and marker; malformed evidence leaves the task open. |
| `tt_cache_mark_notice` | `(owner, target, task_id, notice, [now_epoch])` | Atomically records one notice key. Returns 0 only on first emission. |
| `tt_cache_due_notices` | `(owner, [now_epoch])` | Emits newly due once-only rows `<target>\t<task_id>\t<state>\t<event>`. It never removes or expires open tasks. `tt_cache_gc_expired` is a compatibility alias. |
| `tt_cache_remove_task` | `(owner, target, task_id)` | Internal USER_REPORTED remover. Idempotent and exact-owner scoped. `tproj-msg --read`, TTL handling, and manual `tproj-task close` MUST NOT call it. |
| `tt_cache_gc_legacy_flat` | `([now_epoch])` | Silent drain of pre-v2 flat `<cache_root>/<target>.json` files. TTL-GCs expired entries and empty files. Emits NOTHING on stdout and writes no DB row (owner is unknowable). Owner subdirs are skipped (they are not `*.json` regular files). |

### 2.3 Cache inspection (read-only)

| Function | Signature | Behavior |
|---|---|---|
| `tt_cache_get_task` | `(owner, target, task_id)` | Prints the entry JSON on stdout, empty if missing or owner invalid. No locking (atomic `jq` read of a possibly half-written file is considered acceptable; the writer uses tmp+mv so the file is never mid-write). |
| `tt_cache_list_targets` | `(owner)` | Prints active targets under the owner subdir on stdout (one per line). A target is "active" iff the file exists and is non-empty. Invalid owner lists nothing. |
| `tt_cache_list_tasks` | `(owner, target)` | TSV on stdout: `<task_id>\t<sent_at>\t<expect_until>`. |
| `tt_cache_list_open_tasks` | `(owner, target)` | TSV on stdout for non-tombstoned rows only (`pending|acked|done|blocked|received|verified`). Used by `tproj-msg --read` and D5 so cancelled/frozen workers cannot reopen or re-notify the orchestrator. |
| `tt_cache_list_all` | `(owner)` | TSV on stdout: `<target>\t<task_id>\t<sent_at>\t<expect_until>` for that owner. |

---

## 3. Lifecycle and single-writer rule (MUST)

The machine lifecycle is:

`DELEGATED -> WORKER_ACK -> WORKER_DONE/BLOCKED -> ORCH_RECEIVED -> ORCH_VERIFIED -> USER_REPORTED`

Owner-side tombstones branch to durable terminal states:

`DELEGATED|WORKER_ACK|WORKER_DONE/BLOCKED|ORCH_RECEIVED|ORCH_VERIFIED -> CANCELLED|FROZEN`

- ACK and ACK-PROGRESS are non-terminal.
- DONE/BLOCK carries only durable message id + body hash into the task ledger; arbitrary response bodies are not copied into task evidence.
- CANCELLED/FROZEN retain the cache + DB tombstone instead of deleting the task. Only hashed structural reason metadata is stored.
- `tproj-task verify <id> <target> <summary> <done-body-hash>` is exact owner/target scoped and rejects a mismatched hash.
- `tproj-task cancel <id> <target> <reason-hash>` and `tproj-task freeze <id> <target> <reason-hash>` are exact owner/target scoped and idempotent.
- `[COMPLETION-REPORT: <id>]` in platform-observed final assistant text invokes `tproj-task report`; only that transition records `user_reported_at` and removes the cache entry. It means the platform observed the report marker, not that a human read it.
- `tproj-task close` is retired and fails closed.
- While an exact inbound task is active, the Claude/Codex Stop hook requires exactly one matching lifecycle tag that was already sent to the exact owner. Untagged local success is blocked with the required tag forms. The parser accepts Claude's top-level and Codex's nested `raw_event.last_assistant_message` Stop payloads.
- A cancelled/frozen inbound task installs a symmetric PreToolUse mutation guard: edits, staging/commit/reset/revert/stash/checkout, build/test/restart/deploy, and ambiguous shell commands are denied. Only the strict read-only incident whitelist is allowed.
- A queued `--role-handoff --new-task` revalidates the target pane's current `@role_epoch` at flush time. If the queued epoch is stale, the handoff is cancelled into a tombstone and never injected.
- Messages carrying `[Task:]` / `[ACK:]` / `[ACK-PROGRESS:]` / `[DONE:]` / `[BLOCK:]` for cancelled/frozen IDs are suppressed; they cannot advance or reopen the task and are not replayed to the orchestrator.
- `--user-authorized` exact tasks persist only `intent_hash` + `user_authorized_exact=1`. The worker contract is: do not re-ask the user for the same exact one-shot operation unless target or scope changes.
- A completion report selects its verified task by the explicit marker ID, so parallel verified tasks do not block one another. The Stop gate activation boundary defaults to the installed guard file's mtime; older historical task rows are never inferred as current work.

Escalation defaults are code-owned environment variables and notices are once-only: `TT_TASK_NO_ACK_SEC=30`, `TT_TASK_FOLLOWUP_SEC=900`, `TT_TASK_REROUTE_SEC=1800`, `TT_TASK_REPORT_DUE_SEC=900`, `TT_TASK_COMPLETION_STALLED_SEC=1800`. The final notice does not close the task.

This is the invariant that keeps the system race-free without a heavier lock manager:

- `tt_cache_add` has **exactly one caller**: the D4 PostToolUse hook (`tproj-inbox-record`), which resolves and passes its own owner key.
- Lifecycle updates have many readers but remain exact-owner scoped and monotonic. `tproj-msg --read` applies tags only to IDs present in its own cache and never removes them. The Stop hook validates exact sender/recipient DB evidence. `tproj-inbox-check` only marks notices. The sole removal occurs after `USER_REPORTED`.
- `tproj-msg --new-task` itself **MUST NOT** touch the cache. It only:
  1. generates a Task ID,
  2. prepends `[Task: <id>] `, or a role-handoff envelope containing that tag, to the outgoing message,
  3. emits `TASK_ID=<id> TASK_TARGET=<t> TASK_TTL_SEC=<n> TASK_SENT_AT=<epoch>` plus structural metadata (`TASK_KIND`, exact-user-auth flag, intent hash, role epoch, orchestrator) on stderr when the send is delivered or accepted into the deferred queue,
  4. may shadow-write the DB task row immediately, but cache insertion remains D4-hook only,
  5. invokes the normal send path.

Rationale: adds are rare (one per delegation) and pass through a single hook. State transitions serialize under the same per-target lock, while the sole remove follows durable USER_REPORTED. This avoids competing read-modify-write add paths without treating ACK as completion.

### 3.1 Backward compatibility (MUST)

- `TPROJ_HOOK_ENABLED != "1"` → D4/D5 hooks exit 0 immediately. In that mode, `tproj-msg --new-task` still generates IDs and sends, but no cache file is ever written.
- `tproj-msg` calls with no `--new-task` flag behave byte-identically to pre-Lane-D.
- `tproj-msg --role-handoff --new-task` uses the same cache record and lifecycle.
- `tproj-msg --new-task --user-authorized ...` records only structural metadata / hashes; no delegated body or prompt text is persisted in task storage.
- `tproj-msg --read` still returns capture output and exits 0 when any ACK/ACK-PROGRESS/DONE/BLOCK marker is detected. Its lifecycle side effect is state advancement, never close.

Consumers that depend on `--read` exit code being 0 unconditionally must be audited; none are known inside the tproj workspace at Lane D implementation time (regression floor).

---

## 4. Locking design

### 4.1 Why mkdir-based (not flock)

- macOS ships without `flock(1)` by default (it is not part of BSD `util-linux`); we refuse to introduce a Homebrew-install-only dependency into the hot path.
- `mkdir` is POSIX-atomic: two processes racing on `mkdir` will see exactly one success and one `EEXIST`.
- `rmdir` is likewise atomic; cleanup is safe.
- The only failure mode is a crashed holder leaving a stale `<lock>/pid`. `tt_cache_acquire_lock` detects this by sending `kill -0 <pid>`; if the pid is gone, the lock is recycled.

### 4.2 Granularity

Per-target lock, not global. Concurrent `--new-task` sends to **different** targets do not serialize. Adds to the **same** target serialize through one lock.

### 4.3 Timeout

Default 5 s. Exceeding it returns non-zero from cache mutation functions. Hooks fail open on cache lock contention, except the Stop gate keeps an already-known active task open when durable lifecycle recording fails.

---

## 5. Race test spec (regression surface)

These are the scenarios tproj.cc re-runs during §8.2 independent verification after tproj.cdx returns the D1/D2/D4/D5 bundle. All tests are reproducible from the command line with `TT_CACHE_DIR` / `TT_CACHE_LOCK_DIR` overrides.

### 5.1 Parallel add to same target (race floor)

```bash
bash -c '
rm -rf /tmp/rt-cache /tmp/rt-locks
mkdir -p /tmp/rt-cache /tmp/rt-locks
export TT_CACHE_DIR=/tmp/rt-cache TT_CACHE_LOCK_DIR=/tmp/rt-locks
source ./extensions/messaging/tproj-task-cache.sh
owner=rt/colA
for i in $(seq 1 16); do
  ( tt_cache_add "$owner" par.cdx "par-$(printf "%02d" $i)" $((1734500000+i)) 1800 "h$i" ) &
done
wait
[[ $(jq "keys | length" "/tmp/rt-cache/$owner/par.cdx.json") == 16 ]] && echo "PASS: 16/16" || echo "FAIL"
jq empty "/tmp/rt-cache/$owner/par.cdx.json" && echo "PASS: JSON valid"
'
```

Expected: `PASS: 16/16` + `PASS: JSON valid`. Verified green during D3 development (2026-04-17).

### 5.2 Parallel add to different targets (no serialization)

```bash
bash -c '
rm -rf /tmp/rt-cache /tmp/rt-locks
mkdir -p /tmp/rt-cache /tmp/rt-locks
export TT_CACHE_DIR=/tmp/rt-cache TT_CACHE_LOCK_DIR=/tmp/rt-locks
source ./extensions/messaging/tproj-task-cache.sh
owner=rt/colA
t0=$(date +%s%N)
for i in $(seq 1 8); do
  ( tt_cache_add "$owner" "tgt-$i.cdx" "t-$i-01" $((1734500000+i)) 1800 "h$i" ) &
done
wait
t1=$(date +%s%N)
echo "elapsed ms: $(( (t1 - t0) / 1000000 ))"
ls "/tmp/rt-cache/$owner/"
'
```

Expected: 8 cache files (one per target) under the owner subdir, elapsed wall time close to single-add cost (locks are per-owner-per-target, no cross-contention).

### 5.3 Idempotent remove

```bash
bash -c '
rm -rf /tmp/rt-cache /tmp/rt-locks
mkdir -p /tmp/rt-cache /tmp/rt-locks
export TT_CACHE_DIR=/tmp/rt-cache TT_CACHE_LOCK_DIR=/tmp/rt-locks
source ./extensions/messaging/tproj-task-cache.sh
owner=rt/colA
# Remove on empty cache -> return 0
tt_cache_remove_task "$owner" nope.cdx nothing && echo "PASS: remove on empty"
# Add then remove same id twice
tt_cache_add "$owner" a.cdx t-1 1734500000 600 h1
tt_cache_remove_task "$owner" a.cdx t-1 && echo "PASS: first remove"
tt_cache_remove_task "$owner" a.cdx t-1 && echo "PASS: idempotent remove"
[[ ! -f "/tmp/rt-cache/$owner/a.cdx.json" ]] && echo "PASS: empty file removed"
'
```

Expected: all four PASS lines.

### 5.4 Once-only escalation without expiry

```bash
bash -c '
rm -rf /tmp/rt-cache /tmp/rt-locks
mkdir -p /tmp/rt-cache /tmp/rt-locks
export TT_CACHE_DIR=/tmp/rt-cache TT_CACHE_LOCK_DIR=/tmp/rt-locks
source ./extensions/messaging/tproj-task-cache.sh
owner=rt/colA
tt_cache_add "$owner" x.cdx open-1 1734500000 1800 h1
TT_TASK_NO_ACK_SEC=30 tt_cache_due_notices "$owner" 1734500031
TT_TASK_NO_ACK_SEC=30 tt_cache_due_notices "$owner" 1734500031
[[ -n $(tt_cache_get_task "$owner" x.cdx open-1) ]] && echo "PASS: open task retained"
'
```

Expected: one `no_ack` TSV row total and `PASS: open task retained`.

### 5.5 Stale lock recovery

```bash
bash -c '
rm -rf /tmp/rt-cache /tmp/rt-locks
mkdir -p /tmp/rt-cache /tmp/rt-locks
export TT_CACHE_DIR=/tmp/rt-cache TT_CACHE_LOCK_DIR=/tmp/rt-locks
# Forge a stale lock dir with a non-existent pid (owner rt/colA, target x.cdx)
mkdir -p /tmp/rt-locks/tproj-task-cache~rt~colA~x.cdx.lock
echo 99999 > /tmp/rt-locks/tproj-task-cache~rt~colA~x.cdx.lock/pid
source ./extensions/messaging/tproj-task-cache.sh
# Next add should detect dead holder, recycle, succeed
tt_cache_add rt/colA x.cdx recovered-1 1734500000 600 h && echo "PASS: stale lock recovered"
'
```

Expected: `PASS: stale lock recovered` within ~50–100 ms (not full 5 s timeout).

---

## 6. Out of scope (D3)

- Network replication of the cache (future work; for now cache is always local).
- Cross-host lock coordination.
- Richer entry metadata (sender alias, message excerpt) — D4 hook may extend the shape later; the contract here locks only the fields listed in §1.

## 7. Revision log

- **2026-04-17 — v1.0**: initial contract. 8-parallel race test green. mkdir lock accepted in place of flock due to macOS default.
- **2026-07-10 — v1.1**: role-neutral orchestrator wording and queued role-handoff tracking contract.
- **2026-07-18 — v2.0**: owner-scoped layout (`<owner>/<target>.json`, owner = `<session>/<owner_alias>`) to fix cross-column notification leak. All owner-scoped ops take `owner` as their first argument and are fail-closed on an invalid owner. `--read` limits tag-driven transition/removal to own-cache ids. Added `tt_cache_valid_owner`, `tt_cache_owner_dir`, `tt_cache_gc_legacy_flat` (silent pre-v2 flat drain). DB `tasks.owner_alias` (schema v4) records the issuing column.
- **2026-07-18 — v2.1**: composite hardening. DB `tasks.owner_session` (schema v5) and full-composite (`owner_session + owner_alias + task_id`) task-row transitions, so no owner can mutate another owner's task and no task_id-only UPDATE path remains. Path components (session/alias/target) validated by `tt_cache_valid_component` (reject, not sanitize; `[A-Za-z0-9._-]`, no `.`/`..`) for an injective path mapping; lock name joins with `~` to stay collision-free.
- **2026-07-18 — v2.2**: independent-verification fixes. `tt_cache_init_dir` is fail-closed against a traversal owner (validates before any mkdir). DB task identity rebuilt to `UNIQUE(owner_session, owner_alias, target, task_id)` with a partial `UNIQUE(task_id) WHERE owner columns NULL` for legacy idempotency (schema v6); `tt_db_transition_task` also matches `target`. `generate_task_id` embeds a target-derived token (second collision-defense layer). `tproj-inbox-check` scopes its `notified_at` update to session + recipient + sender + task_id, not task_id alone.
- **2026-07-18 — v2.3**: second-round verification fixes. The v6 tasks rebuild runs in a single `BEGIN IMMEDIATE ... COMMIT` and recovers rows from a survivor temp table left by an interrupted pre-atomic run (no history loss). `tproj-inbox-check`'s `notified_at` update is fail-CLOSED when the pane role is unresolved (the recipient predicate is mandatory, never dropped). `generate_task_id`'s target token is an **injective** lowercase hex encoding of the target bytes (`od -An -v -tx1`), so collapse-prone targets (`a-b`/`ab`/`a_b`/`a.b`) yield distinct ids.
- **2026-08-06 — v3.0**: cache entries represent open delegations and close only at platform-observed USER_REPORTED. Added schema v7 lifecycle evidence, exact-owner verification/report commands, once-only staged escalation, ACK-PROGRESS, and symmetric Claude/Codex inbox + Stop hooks.
- **2026-08-09 — v3.1**: added durable `cancel` / `freeze` tombstones, queued role-handoff epoch revalidation at flush, exact-task user-authorization metadata (`intent_hash` + flag only), one-shot receiver cancellation/freeze notices, and the symmetric mutation guard for Claude/Codex.

---

Authoritative references:

- `AGENTS.md` (public messaging and runtime contribution rules)
- `extensions/messaging/tproj-msg` (D1 consumer — §3 single-writer rule binds this file)
- `extensions/hooks/tproj-inbox-record` (D4 adder — exclusive `tt_cache_add` caller)
- `extensions/hooks/tproj-inbox-check` (D5 once-only lifecycle notices)
- `extensions/hooks/tproj-mutation-guard` (cancel/freeze mutation blocker)
- `extensions/messaging/tproj-task` (D2 CLI)
