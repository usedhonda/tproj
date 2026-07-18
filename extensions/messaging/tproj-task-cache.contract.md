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
    "msg_hash":     "<sha1-hex-or-cksum-decimal>"
  },
  ...
}
```

- Empty files are removed (post-remove / post-gc); consumers treat missing files as "no active tasks for that target".
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
| `tt_cache_add` | `(owner, target, task_id, sent_at, ttl_sec, [msg_hash])` | **Single-writer role** — called only by D4 PostToolUse hook. Adds entry to `<owner>/<target>.json`, computing `expect_until = sent_at + ttl_sec`. Overwrites if `task_id` already exists. Invalid owner returns 2 (fail-closed). Shadow-writes the DB task row with `owner_alias = <alias>`. Takes per-owner-per-target lock. |
| `tt_cache_remove_task` | `(owner, target, task_id)` | **Remover role** — called by tproj-msg `--read` (on `[ACK:]` / `[DONE:]` / `[BLOCK:]` detection, limited to own-cache task ids), D5 UserPromptSubmit hook (on TTL expiry via `tt_cache_gc_expired`), and `tproj-task close`. Idempotent; missing entry or invalid owner is a no-op. Takes per-owner-per-target lock. If the resulting file is empty `{}`, the file is removed. |
| `tt_cache_gc_expired` | `(owner, [now_epoch])` | Used by D5 hook. Removes entries under the owner subdir where `expect_until <= now`. Emits one TSV row per removed entry on stdout: `<target>\t<task_id>\t<expect_until>\ttimeout`. Invalid owner is a no-op. Defaults `now` to current epoch. Takes per-owner-per-target locks. |
| `tt_cache_gc_legacy_flat` | `([now_epoch])` | Silent drain of pre-v2 flat `<cache_root>/<target>.json` files. TTL-GCs expired entries and empty files. Emits NOTHING on stdout and writes no DB row (owner is unknowable). Owner subdirs are skipped (they are not `*.json` regular files). |

### 2.3 Cache inspection (read-only)

| Function | Signature | Behavior |
|---|---|---|
| `tt_cache_get_task` | `(owner, target, task_id)` | Prints the entry JSON on stdout, empty if missing or owner invalid. No locking (atomic `jq` read of a possibly half-written file is considered acceptable; the writer uses tmp+mv so the file is never mid-write). |
| `tt_cache_list_targets` | `(owner)` | Prints active targets under the owner subdir on stdout (one per line). A target is "active" iff the file exists and is non-empty. Invalid owner lists nothing. |
| `tt_cache_list_tasks` | `(owner, target)` | TSV on stdout: `<task_id>\t<sent_at>\t<expect_until>`. |
| `tt_cache_list_all` | `(owner)` | TSV on stdout: `<target>\t<task_id>\t<sent_at>\t<expect_until>` for that owner. |

---

## 3. Single-writer rule (MUST)

This is the invariant that keeps the system race-free without a heavier lock manager:

- `tt_cache_add` has **exactly one caller**: the D4 PostToolUse hook (`tproj-inbox-record`), which resolves and passes its own owner key.
- `tt_cache_remove_task` has **three callers**: `tproj-msg --read`, D5 hook (`tproj-inbox-check` via `tt_cache_gc_expired`), and `tproj-task close`. Each passes its own owner key. In `--read` the destructive side effects (DB state transition + cache removal) fire **only** for task ids present in its own owner subdir, so a tag seen in another column's pane scrollback never transitions the shared DB row nor steals that column's cache entry. The informational `TASK_REPLIED=<id>` stderr line and `--read`'s exit code are still emitted for every detected tag (legacy `--read` compatibility; it is the invoking pane's own output, not a cross-column notice, since the D5 hook cross-references only its own pending ids).
- `tproj-msg --new-task` itself **MUST NOT** touch the cache. It only:
  1. generates a Task ID,
  2. prepends `[Task: <id>] `, or a role-handoff envelope containing that tag, to the outgoing message,
  3. emits `TASK_ID=<id> TASK_TARGET=<t> TASK_TTL_SEC=<n> TASK_SENT_AT=<epoch>` on stderr when the send is delivered or accepted into the deferred queue,
  4. invokes the normal send path.

Rationale: adds are rare (one per delegation, at the moment of send) and pass through a single hook; removes are many (per `--read`, per hook tick, per manual close) but idempotent. Funneling adds through one writer removes the "two tproj-msg processes both opening + rewriting the same file" race.

### 3.1 Backward compatibility (MUST)

- `TPROJ_HOOK_ENABLED != "1"` → D4/D5 hooks exit 0 immediately. In that mode, `tproj-msg --new-task` still generates IDs and sends, but no cache file is ever written.
- `tproj-msg` calls with no `--new-task` flag behave byte-identically to pre-Lane-D.
- `tproj-msg --role-handoff --new-task` uses the same cache record and accepts the same `[ACK:]` / `[DONE:]` / `[BLOCK:]` terminal compatibility as a normal tracked task.
- `tproj-msg --read` still returns the capture output on stdout; the only behavioural additions are (a) idempotent cache removal as a side effect, and (b) exit code `0` if any `[ACK:]` / `[DONE:]` / `[BLOCK:]` was detected, else `1` (pre-Lane-D always exited 0).

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

Default 5 s. Exceeding it returns non-zero from `tt_cache_add` / `tt_cache_remove_task` / `tt_cache_gc_expired`. Callers (D4/D5 hooks, `tproj-task`) MUST log-and-continue on non-zero — the cache is auxiliary, never block the user's command.

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

### 5.4 TTL gc

```bash
bash -c '
rm -rf /tmp/rt-cache /tmp/rt-locks
mkdir -p /tmp/rt-cache /tmp/rt-locks
export TT_CACHE_DIR=/tmp/rt-cache TT_CACHE_LOCK_DIR=/tmp/rt-locks
source ./extensions/messaging/tproj-task-cache.sh
owner=rt/colA
tt_cache_add "$owner" x.cdx live-1 1734500000 3600 h1   # expect_until = 1734503600
tt_cache_add "$owner" x.cdx stale-1 1734500000 60 h2    # expect_until = 1734500060
tt_cache_gc_expired "$owner" 1734503500                 # stale-1 expired, live-1 survives
[[ -n $(tt_cache_get_task "$owner" x.cdx live-1) ]] && echo "PASS: live survived"
[[ -z $(tt_cache_get_task "$owner" x.cdx stale-1) ]] && echo "PASS: stale removed"
'
```

Expected: `PASS: live survived` + `PASS: stale removed`, plus the timeout TSV row emitted on stdout during gc.

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

---

Authoritative references:

- `AGENTS.md` (public messaging and runtime contribution rules)
- `extensions/messaging/tproj-msg` (D1 consumer — §3 single-writer rule binds this file)
- `extensions/hooks/tproj-inbox-record` (D4 adder — exclusive `tt_cache_add` caller)
- `extensions/hooks/tproj-inbox-check` (D5 remover via `tt_cache_gc_expired`)
- `extensions/messaging/tproj-task` (D2 CLI)
