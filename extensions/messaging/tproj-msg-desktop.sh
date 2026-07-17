#!/bin/bash
# tproj-msg-desktop.sh — Codex Desktop <-> tmux session data-plane mailbox.
#
# Sourced by tproj-msg (function-only, no side effects at source time, fail-open).
#
# Design contract:
#   - Desktop is identity_class=desktop: a per-project data-plane mailbox peer
#     (desktop.<project>), NOT a pane alias and NOT an orchestrator/worker.
#   - Desktop-originated content is ALWAYS untrusted mailbox data. It is NEVER
#     injected into a pane (no tmux send-keys), never enters ACK/DONE/BLOCK task
#     tracking, role handoff, or control parsing. Each party reads its own
#     mailbox explicitly; reading triggers no execution / resend / task accept /
#     role-metadata change.
#   - Desktop identity is resolved by the caller's live PID ancestry + the
#     registry-recorded pid_start (pid-reuse defence), independent of any body,
#     title, --as claim, or role label.
#   - Hygiene: 0700 dirs, 0600 atomic files (temp+rename under umask 077),
#     sanitized identifiers, bounded envelope size / mailbox count / TTL,
#     stale/future/pid-reuse registry checks.
#
# This file DEPENDS on two functions defined by the sourcing tproj-msg process
# (reused, not re-implemented): find_registry_ancestor_match and
# pid_start_epoch_bash. It is only ever driven through tproj-msg, so those are
# always in scope when resolve_desktop_identity runs.

# --- tunables (all env-adjustable; defaults are the production values) --------
TPROJ_DESKTOP_MAILBOX_ROOT="${TPROJ_DESKTOP_MAILBOX_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/tproj-msg/desktop-mailbox}"
TPROJ_DESKTOP_MAILBOX_MAX_BYTES="${TPROJ_DESKTOP_MAILBOX_MAX_BYTES:-65536}"    # 64 KiB per envelope body
TPROJ_DESKTOP_MAILBOX_MAX_COUNT="${TPROJ_DESKTOP_MAILBOX_MAX_COUNT:-200}"      # envelopes per mailbox
TPROJ_DESKTOP_MAILBOX_TTL_SEC="${TPROJ_DESKTOP_MAILBOX_TTL_SEC:-604800}"       # 7 days
# Reuse the alias.role registry stale window when one is not already exported.
TPROJ_MSG_REGISTRY_STALE_SECONDS="${TPROJ_MSG_REGISTRY_STALE_SECONDS:-172800}" # 48h

# Sanitize an arbitrary string into a filesystem-safe identifier segment:
# keep [A-Za-z0-9_.-], collapse everything else to '_', strip leading dots
# (no dotfiles / no traversal), bound length. Empty -> "unknown".
sanitize_desktop_id() {
  local s="$1" out
  out=$(printf '%s' "$s" | tr -d '\n\r' | sed -E 's/[^A-Za-z0-9_.-]+/_/g; s/^\.+//; s/\.\.+/_/g')
  out="${out:0:96}"
  [[ -n "$out" ]] || out="unknown"
  printf '%s' "$out"
}

# ===========================================================================
# ISOLATED DESKTOP REGISTRY SCHEMA CONSUMER  (Phase 1)
# ===========================================================================
# This is the SINGLE integration point with general's standalone Desktop
# registry schema (general owner task tproj-29737970-01). When the canonical
# schema lands, only this function changes (surgical Phase-6 adjustment).
#
# CONSUMES these registry JSON fields (and nothing else) for authorization:
#   .identity_class : "desktop"          (canonical desktop marker — assumed)
#   .pid            : recorded owning pid (verification anchor)
#   .pid_start      : recorded process-start epoch (pid-reuse defence; REQUIRED)
#   .observed_at    : registry freshness (bounded on both sides)
#   .desktop_project / .alias / .project : source of the <project> segment
#   .session        : owning session (assumed "standalone" during assumed phase)
#
# NEVER consumes body, title, role labels, or any --as claim for authz.
#
# ASSUMED SCHEMA (until general defines identity_class=desktop):
#   general currently emits no identity_class field. A Desktop/standalone probe
#   entry is recognised heuristically as a registry file whose .identity_class
#   == "desktop" OR whose .session == "standalone" (and .column == "standalone").
#   The <project> segment is taken from .desktop_project, else the sub-part of a
#   "desktop.<x>" .alias, else basename(.project), else "unknown".
#   TODO(Phase 6): replace the heuristic predicate + project derivation with the
#   canonical identity_class=desktop fields once general publishes the schema.
#   TODO(Phase 6): per-app-server-instance record, collision-resistant project
#   key — pending general schema. Do NOT synthesize these here on speculation;
#   this isolated consumer is the only site that changes when general lands them.
# ---------------------------------------------------------------------------

# True (rc 0) if the registry JSON at $1 is a Desktop-class entry (assumed schema).
_desktop_registry_entry_is_desktop() {
  local f="$1" ic sess col
  ic=$(jq -r '.identity_class // empty' "$f" 2>/dev/null)
  if [[ "$ic" == "desktop" ]]; then return 0; fi
  # Assumed-phase heuristic: standalone session/column probe entries.
  sess=$(jq -r '.session // empty' "$f" 2>/dev/null)
  col=$(jq -r '.column // empty' "$f" 2>/dev/null)
  [[ "$sess" == "standalone" && "$col" == "standalone" ]]
}

# Derive the sanitized <project> segment for a Desktop registry entry.
_desktop_project_of_entry() {
  local f="$1" p alias base
  p=$(jq -r '.desktop_project // empty' "$f" 2>/dev/null)
  if [[ -z "$p" ]]; then
    alias=$(jq -r '.alias // empty' "$f" 2>/dev/null)
    case "$alias" in
      desktop.*) p="${alias#desktop.}" ;;
      ""|unknown.agent) p="" ;;
      *) p="$alias" ;;
    esac
  fi
  if [[ -z "$p" ]]; then
    base=$(jq -r '.project // empty' "$f" 2>/dev/null)
    p="${base##*/}"
  fi
  sanitize_desktop_id "$p"
}

# Resolve the UNIQUE live Desktop identity that owns the calling process.
#
# For every Desktop-class registry entry: require recorded pid>0 and pid_start>0,
# then require the recorded pid to be a genuine ancestor of THIS process whose
# live start epoch equals the recorded pid_start (pid-reuse defence), and require
# observed_at to be present, positive, not-future, and within the stale window.
# Exactly one genuine match -> success; zero or many -> fail-closed reject.
#
# On success sets: DESKTOP_PROJECT / DESKTOP_IDENTITY / DESKTOP_REGISTRY_FILE /
#   VERIFIED_ANCHOR_PID / VERIFIED_CALLER_PID / VERIFIED_PROCESS_START and rc 0.
# On failure sets CALLER_VERIFY_REASON (desktop_identity_unresolved |
#   desktop_identity_ambiguous) and rc 1. Fail-closed on any unexpected state.
resolve_desktop_identity() {
  local cache_dir now f
  local reg_pid reg_pid_start reg_observed_at ancestor_pair ancestor_pid ancestor_start
  local match_count=0 match_file="" match_anchor=0 match_caller=0 match_start=0
  CALLER_VERIFY_REASON=""
  DESKTOP_PROJECT=""
  DESKTOP_IDENTITY=""
  DESKTOP_REGISTRY_FILE=""
  VERIFIED_ANCHOR_PID=0
  VERIFIED_CALLER_PID=0
  VERIFIED_PROCESS_START=0

  cache_dir="${MODEL_ROLE_CACHE:-$HOME/.cache/tproj-model-role}"
  [[ -d "$cache_dir" ]] || { CALLER_VERIFY_REASON="desktop_identity_unresolved"; return 1; }
  now=$(date +%s)

  while IFS= read -r -d '' f; do
    _desktop_registry_entry_is_desktop "$f" || continue
    reg_pid=$(jq -r '.pid // 0' "$f" 2>/dev/null)
    reg_pid_start=$(jq -r '.pid_start // 0' "$f" 2>/dev/null)
    reg_observed_at=$(jq -r '.observed_at // 0' "$f" 2>/dev/null)
    [[ "$reg_pid" =~ ^[0-9]+$ && "$reg_pid" -gt 0 ]] || continue
    # pid_start MUST be recorded and positive — same fail-closed rule as the
    # alias.role verifier. An unrecorded pid_start cannot be authenticated.
    [[ "$reg_pid_start" =~ ^[0-9]+$ && "$reg_pid_start" -gt 0 ]] || continue
    # observed_at bounded on both sides (future == forged/skew == reject).
    [[ "$reg_observed_at" =~ ^[0-9]+$ && "$reg_observed_at" -gt 0 ]] || continue
    (( now - reg_observed_at < 0 )) && continue
    (( now - reg_observed_at > TPROJ_MSG_REGISTRY_STALE_SECONDS )) && continue
    # The recorded pid must be a genuine ancestor of THIS process.
    ancestor_pair=$(find_registry_ancestor_match "$reg_pid") || continue
    ancestor_pid="${ancestor_pair%% *}"
    ancestor_start="${ancestor_pair##* }"
    # pid-reuse defence: live ancestor start must equal recorded pid_start.
    [[ "$ancestor_start" == "$reg_pid_start" ]] || continue
    match_count=$((match_count + 1))
    match_file="$f"
    match_anchor="$reg_pid"
    match_caller="$ancestor_pid"
    match_start="$ancestor_start"
  done < <(find "$cache_dir" -type f -name '*.json' -print0 2>/dev/null)

  if (( match_count == 0 )); then
    CALLER_VERIFY_REASON="desktop_identity_unresolved"
    return 1
  fi
  if (( match_count > 1 )); then
    CALLER_VERIFY_REASON="desktop_identity_ambiguous"
    return 1
  fi

  DESKTOP_PROJECT=$(_desktop_project_of_entry "$match_file")
  DESKTOP_IDENTITY="desktop.${DESKTOP_PROJECT}"
  DESKTOP_REGISTRY_FILE="$match_file"
  VERIFIED_ANCHOR_PID="$match_anchor"
  VERIFIED_CALLER_PID="$match_caller"
  VERIFIED_PROCESS_START="$match_start"
  return 0
}

# ===========================================================================
# Mailbox storage (Phases 2-4)
# ===========================================================================
# Layout under $TPROJ_DESKTOP_MAILBOX_ROOT (0700):
#   to-session/<session>/<target_alias>/   Desktop -> session (session reads)
#   to-desktop/<project>/                  session -> desktop (desktop reads)
# Each mailbox holds 0600 envelope files named "<epoch>-<pid>-<rand>.json".

# Print the mailbox directory path for a (kind, key...) tuple. Does not create it.
#   desktop_mailbox_dir to-session <session> <target_alias>
#   desktop_mailbox_dir to-desktop <project>
desktop_mailbox_dir() {
  local kind="$1"; shift
  case "$kind" in
    to-session)
      printf '%s/to-session/%s/%s' "$TPROJ_DESKTOP_MAILBOX_ROOT" \
        "$(sanitize_desktop_id "${1:-}")" "$(sanitize_desktop_id "${2:-}")" ;;
    to-desktop)
      printf '%s/to-desktop/%s' "$TPROJ_DESKTOP_MAILBOX_ROOT" \
        "$(sanitize_desktop_id "${1:-}")" ;;
    *) return 1 ;;
  esac
}

# Remove envelopes older than the TTL from a mailbox dir (best-effort, fail-open).
desktop_mailbox_purge_expired() {
  local dir="$1" now cutoff f mtime
  [[ -d "$dir" ]] || return 0
  now=$(date +%s)
  cutoff=$((now - TPROJ_DESKTOP_MAILBOX_TTL_SEC))
  for f in "$dir"/*.json; do
    [[ -e "$f" ]] || continue
    mtime=$(stat -f %m "$f" 2>/dev/null || echo 0)
    [[ "$mtime" =~ ^[0-9]+$ ]] || mtime=0
    (( mtime < cutoff )) && rm -f "$f" 2>/dev/null
  done
  return 0
}

# Count current (post-purge) envelopes in a mailbox dir.
desktop_mailbox_count() {
  local dir="$1" n=0 f
  [[ -d "$dir" ]] || { printf '0'; return 0; }
  for f in "$dir"/*.json; do
    [[ -e "$f" ]] && n=$((n + 1))
  done
  printf '%s' "$n"
}

# --- per-mailbox critical-section lock (Fix 3) -------------------------------
# macOS has no flock(1); use an atomic mkdir lock (same idiom as tproj-msg's
# with_queue_lock). Serializes purge -> count -> write for one mailbox so
# concurrent writers cannot race past MAX_COUNT. Fail-open after a bounded wait
# so a stale lock never wedges delivery.
TPROJ_DESKTOP_LOCK_WAIT_MS="${TPROJ_DESKTOP_LOCK_WAIT_MS:-3000}"
TPROJ_DESKTOP_LOCK_POLL_MS="${TPROJ_DESKTOP_LOCK_POLL_MS:-25}"
with_desktop_mailbox_lock() {
  local dir="$1"; shift
  local lockdir="${dir}.lock" waited=0 rc
  ( umask 077; mkdir -p "$(dirname "$lockdir")" ) 2>/dev/null || true
  while (( waited < TPROJ_DESKTOP_LOCK_WAIT_MS )); do
    if mkdir "$lockdir" 2>/dev/null; then
      "$@"; rc=$?
      rmdir "$lockdir" 2>/dev/null || true
      return $rc
    fi
    sleep 0.025
    waited=$(( waited + TPROJ_DESKTOP_LOCK_POLL_MS ))
  done
  # fail-open: proceed unlocked rather than drop the message. mktemp naming
  # below stays collision-free even without the lock.
  "$@"
}

# Write one envelope into <dir> from <from> to <to> with body <body>.
# Enforces per-envelope byte bound and per-mailbox count bound (after TTL purge).
# 0700 dir, 0600 atomic file (temp+rename under umask 077). Body is stored as-is
# in a JSON string (jq-encoded) — it is NEVER shell-expanded or pane-injected.
# The purge -> count -> write critical section runs under a per-mailbox lock and
# the final name is a collision-free mktemp token + no-clobber rename, so
# concurrent writers can neither exceed the cap nor overwrite an envelope.
# rc: 0 ok | 1 body-too-large | 2 mailbox-full | 3 write-error.
desktop_mailbox_write() {
  local dir="$1" from="$2" to="$3" body="$4"
  local nbytes
  # Enforce the limit in BYTES, not characters. `${#body}` counts UTF-8 code
  # points under a multibyte locale (4 Japanese chars == 4, not 12), which would
  # let an oversized body slip past a byte-denominated cap. Count raw bytes.
  # (No shared state touched -> checked outside the lock.)
  nbytes=$(LC_ALL=C printf '%s' "$body" | wc -c | tr -d '[:space:]')
  [[ "$nbytes" =~ ^[0-9]+$ ]] || nbytes=0
  (( nbytes > TPROJ_DESKTOP_MAILBOX_MAX_BYTES )) && return 1
  with_desktop_mailbox_lock "$dir" _desktop_mailbox_write_locked "$dir" "$from" "$to" "$body"
}

# Locked body of desktop_mailbox_write (runs inside with_desktop_mailbox_lock).
_desktop_mailbox_write_locked() {
  local dir="$1" from="$2" to="$3" body="$4"
  local now count tmp final tok
  ( umask 077; mkdir -p "$dir" ) 2>/dev/null || return 3
  chmod 700 "$dir" 2>/dev/null || true
  desktop_mailbox_purge_expired "$dir"
  count=$(desktop_mailbox_count "$dir")
  (( count >= TPROJ_DESKTOP_MAILBOX_MAX_COUNT )) && return 2
  now=$(date +%s)
  # Collision-free unique temp inside the mailbox dir (BSD mktemp cannot append a
  # suffix after the X's, so name the temp then derive the .json final from its
  # unique token). mv -n never clobbers an existing envelope.
  tmp=$(mktemp "$dir/.wtmp.XXXXXXXX" 2>/dev/null) || return 3
  if ! ( umask 077; jq -n \
      --arg from "$from" --arg to "$to" --arg body "$body" \
      --arg sha "$(printf '%s' "$body" | shasum -a 256 2>/dev/null | awk '{print $1}')" \
      --argjson ts "$now" \
      '{from:$from,to:$to,body:$body,body_sha256:$sha,created_at:$ts,bridge:"desktop"}' \
      > "$tmp" 2>/dev/null ); then
    rm -f "$tmp" 2>/dev/null
    return 3
  fi
  chmod 600 "$tmp" 2>/dev/null || true
  tok="${tmp##*.wtmp.}"
  final="$dir/${now}-$$-${tok}.json"
  if mv -n "$tmp" "$final" 2>/dev/null && [[ -e "$final" && ! -e "$tmp" ]]; then
    return 0
  fi
  rm -f "$tmp" 2>/dev/null
  return 3
}

# Drain (explicit ack-all) a mailbox dir: delete every envelope and print the
# number removed to stdout. This is the ONLY delete path a recipient invokes to
# reclaim a full mailbox — normal read (below) stays pure/non-deleting. Runs
# under the per-mailbox lock so a concurrent write is serialized. Fail-open.
desktop_mailbox_drain() {
  local dir="$1"
  [[ -d "$dir" ]] || { printf '0'; return 0; }
  with_desktop_mailbox_lock "$dir" _desktop_mailbox_drain_locked "$dir"
}
_desktop_mailbox_drain_locked() {
  local dir="$1" f n=0
  for f in "$dir"/*.json; do
    [[ -e "$f" ]] || continue
    rm -f "$f" 2>/dev/null && n=$((n + 1))
  done
  printf '%s' "$n"
}

# Read (pure inspection) every current envelope in <dir>, oldest first, to stdout
# as human-readable blocks. TTL-purges first. NO execution, NO resend, NO task
# accept, NO role change, NO deletion of read messages. Prints a "(no messages)"
# note to stderr when empty. rc always 0.
desktop_mailbox_read() {
  local dir="$1" f from created body when n=0
  desktop_mailbox_purge_expired "$dir"
  if [[ ! -d "$dir" ]]; then
    echo "(no messages)" >&2
    return 0
  fi
  for f in $(ls -1 "$dir"/*.json 2>/dev/null | sort); do
    [[ -e "$f" ]] || continue
    from=$(jq -r '.from // "?"' "$f" 2>/dev/null)
    created=$(jq -r '.created_at // 0' "$f" 2>/dev/null)
    body=$(jq -r '.body // ""' "$f" 2>/dev/null)
    when=$(date -r "$created" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || printf '%s' "$created")
    n=$((n + 1))
    printf -- '--- from %s at %s ---\n' "$from" "$when"
    printf '%s\n' "$body"
  done
  (( n == 0 )) && echo "(no messages)" >&2
  return 0
}
