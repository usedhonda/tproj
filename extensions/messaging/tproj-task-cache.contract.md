# tproj-task-cache.sh — Contract & Race Test Spec

Lane D3 deliverable. This document pins down the public contract of the Task ID cache helper used by `tproj-msg --new-task`, `tproj-task` CLI, `tproj-inbox-record` (D4 PostToolUse hook), and `tproj-inbox-check` (D5 UserPromptSubmit hook).

Scope: implementation guidance for cache consumers and the regression surface checked by the current orchestrator during independent verification.

---

## 1. File layout & storage

| Aspect | Value |
|---|---|
| Cache root | `${TT_CACHE_DIR:-${HOME}/.cache/tproj-expect-reply}` |
| Per-target file | `<cache_root>/<target>.json` (one JSON object per target) |
| Lock dir root | `${TT_CACHE_LOCK_DIR:-/tmp}` |
| Per-target lock | `<lock_root>/tproj-task-cache.<target>.lock` (mkdir advisory lock) |
| Sequence dir | `/tmp/tproj-task-seq/<target>/<epoch_min>/NN/` (mkdir-atomic counter, D1 responsibility) |
| Required tools | `jq` (must), `shasum` or `sha1sum` or `cksum` (any one) |
| Optional tools | `flock` is **NOT** used (macOS default lacks it) |

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
| `tt_cache_init_dir` | `()` | `mkdir -p "$TT_CACHE_DIR"` if missing. Safe to call repeatedly. |
| `tt_cache_path_for_target` | `(target)` | Prints `<cache_root>/<target>.json` on stdout. No side effects. |
| `tt_cache_lock_for_target` | `(target)` | Prints `<lock_root>/tproj-task-cache.<target>.lock`. No side effects. |
| `tt_cache_acquire_lock` | `(lock_dir, timeout=5)` | mkdir-based advisory lock. Returns 0 on acquire, 1 on timeout. Writes `$$` into `<lock_dir>/pid` (best effort). Detects stale locks by checking if `pid` process is alive. |
| `tt_cache_release_lock` | `(lock_dir)` | `rm -rf "$lock_dir"`. Idempotent. |
| `tt_cache_ttl_to_seconds` | `(spec)` | Parses `"30m"`, `"2h"`, `"45s"`, `"1d"`, or raw int seconds. Prints seconds on stdout. Returns 2 on invalid spec. |
| `tt_cache_msg_hash` | `(msg)` | Prints SHA1 hex via `shasum`/`sha1sum`, falls back to `cksum` decimal. Never fails. |

### 2.2 Cache mutation

| Function | Signature | Behavior |
|---|---|---|
| `tt_cache_add` | `(target, task_id, sent_at, ttl_sec, [msg_hash])` | **Single-writer role** — called only by D4 PostToolUse hook. Adds entry to `<target>.json`, computing `expect_until = sent_at + ttl_sec`. Overwrites if `task_id` already exists. Takes per-target lock. |
| `tt_cache_remove_task` | `(target, task_id)` | **Remover role** — called by tproj-msg `--read` (on `[ACK:]` / `[DONE:]` / `[BLOCK:]` detection), D5 UserPromptSubmit hook (on TTL expiry via `tt_cache_gc_expired`), and `tproj-task close`. Idempotent; missing entry is not an error. Takes per-target lock. If the resulting file is empty `{}`, the file is removed. |
| `tt_cache_gc_expired` | `([now_epoch])` | Used by D5 hook. Removes entries where `expect_until <= now`. Emits one TSV row per removed entry on stdout: `<target>\t<task_id>\t<expect_until>\ttimeout`. Defaults `now` to current epoch. Takes per-target locks. |

### 2.3 Cache inspection (read-only)

| Function | Signature | Behavior |
|---|---|---|
| `tt_cache_get_task` | `(target, task_id)` | Prints the entry JSON on stdout, empty if missing. No locking (atomic `jq` read of a possibly half-written file is considered acceptable; the writer uses tmp+mv so the file is never mid-write). |
| `tt_cache_list_targets` | `()` | Prints active targets on stdout (one per line). A target is "active" iff the file exists and is non-empty. |
| `tt_cache_list_tasks` | `(target)` | TSV on stdout: `<task_id>\t<sent_at>\t<expect_until>`. |
| `tt_cache_list_all` | `()` | TSV on stdout: `<target>\t<task_id>\t<sent_at>\t<expect_until>`. |

---

## 3. Single-writer rule (MUST)

This is the invariant that keeps the system race-free without a heavier lock manager:

- `tt_cache_add` has **exactly one caller**: the D4 PostToolUse hook (`tproj-inbox-record`).
- `tt_cache_remove_task` has **three callers**: `tproj-msg --read`, D5 hook (`tproj-inbox-check` via `tt_cache_gc_expired`), and `tproj-task close`.
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
for i in $(seq 1 16); do
  ( tt_cache_add par.cdx "par-$(printf "%02d" $i)" $((1734500000+i)) 1800 "h$i" ) &
done
wait
[[ $(jq "keys | length" /tmp/rt-cache/par.cdx.json) == 16 ]] && echo "PASS: 16/16" || echo "FAIL"
jq empty /tmp/rt-cache/par.cdx.json && echo "PASS: JSON valid"
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
t0=$(date +%s%N)
for i in $(seq 1 8); do
  ( tt_cache_add "tgt-$i.cdx" "t-$i-01" $((1734500000+i)) 1800 "h$i" ) &
done
wait
t1=$(date +%s%N)
echo "elapsed ms: $(( (t1 - t0) / 1000000 ))"
ls /tmp/rt-cache/
'
```

Expected: 8 cache files (one per target), elapsed wall time close to single-add cost (locks are per-target, no cross-contention).

### 5.3 Idempotent remove

```bash
bash -c '
rm -rf /tmp/rt-cache /tmp/rt-locks
mkdir -p /tmp/rt-cache /tmp/rt-locks
export TT_CACHE_DIR=/tmp/rt-cache TT_CACHE_LOCK_DIR=/tmp/rt-locks
source ./extensions/messaging/tproj-task-cache.sh
# Remove on empty cache -> return 0
tt_cache_remove_task nope.cdx nothing && echo "PASS: remove on empty"
# Add then remove same id twice
tt_cache_add a.cdx t-1 1734500000 600 h1
tt_cache_remove_task a.cdx t-1 && echo "PASS: first remove"
tt_cache_remove_task a.cdx t-1 && echo "PASS: idempotent remove"
[[ ! -f /tmp/rt-cache/a.cdx.json ]] && echo "PASS: empty file removed"
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
tt_cache_add x.cdx live-1 1734500000 3600 h1   # expect_until = 1734503600
tt_cache_add x.cdx stale-1 1734500000 60 h2    # expect_until = 1734500060
tt_cache_gc_expired 1734503500                 # stale-1 expired, live-1 survives
[[ -n $(tt_cache_get_task x.cdx live-1) ]] && echo "PASS: live survived"
[[ -z $(tt_cache_get_task x.cdx stale-1) ]] && echo "PASS: stale removed"
'
```

Expected: `PASS: live survived` + `PASS: stale removed`, plus the timeout TSV row emitted on stdout during gc.

### 5.5 Stale lock recovery

```bash
bash -c '
rm -rf /tmp/rt-cache /tmp/rt-locks
mkdir -p /tmp/rt-cache /tmp/rt-locks
export TT_CACHE_DIR=/tmp/rt-cache TT_CACHE_LOCK_DIR=/tmp/rt-locks
# Forge a stale lock dir with a non-existent pid
mkdir -p /tmp/rt-locks/tproj-task-cache.x.cdx.lock
echo 99999 > /tmp/rt-locks/tproj-task-cache.x.cdx.lock/pid
source ./extensions/messaging/tproj-task-cache.sh
# Next add should detect dead holder, recycle, succeed
tt_cache_add x.cdx recovered-1 1734500000 600 h && echo "PASS: stale lock recovered"
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

---

Authoritative references:

- `AGENTS.md` (public messaging and runtime contribution rules)
- `extensions/messaging/tproj-msg` (D1 consumer — §3 single-writer rule binds this file)
- `extensions/hooks/tproj-inbox-record` (D4 adder — exclusive `tt_cache_add` caller)
- `extensions/hooks/tproj-inbox-check` (D5 remover via `tt_cache_gc_expired`)
- `extensions/messaging/tproj-task` (D2 CLI)
