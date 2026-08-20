#!/usr/bin/env bash
#
# smoke-bin.sh — minimal safety net for bin/* (refactor-instructions.md Phase 1).
#
# Two checks, both side-effect free:
#   1. Shebang-aware syntax check of every bin/* script. Using the matching
#      parser matters: bin/tproj et al. use zsh-only syntax (e.g. `&!`) that
#      `bash -n` rejects, while pure-bash scripts should be checked with bash.
#      Caveat: zsh's no-exec (`-n`) mode still runs `$(...)` command
#      substitutions at parse time, and a substitution whose no-exec subshell
#      blocks can hang (observed on tproj-pane-focus-hook: `$(date +%H:%M:%S)`).
#      So each zsh check is time-bounded; on timeout we fall back to `bash -n`,
#      which parses those files cleanly enough to catch gross syntax errors.
#   2. A couple of harmless, state-reading executions only
#      (`tproj-pane-autozoom --status` / `--help`). No tmux state-changing
#      command (select-pane / resize-pane / kill-pane / send-keys) is run.
#
# Usage: bash tests/smoke-bin.sh   (run from anywhere; paths resolve to repo).

set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
BIN_DIR="$REPO_ROOT/bin"

PASS=0
FAIL=0

pass() { printf 'PASS  %s\n' "$1"; PASS=$((PASS+1)); }
fail() { printf 'FAIL  %s\n      %s\n' "$1" "$2"; FAIL=$((FAIL+1)); }

# Bound every parser invocation so a zsh -n no-exec hang can never wedge the run.
timeout_bin=""
if command -v timeout >/dev/null 2>&1; then
  timeout_bin="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  timeout_bin="gtimeout"
fi
run_bounded() { # <seconds> <cmd...>
  local secs="$1"; shift
  if [[ -n "$timeout_bin" ]]; then
    "$timeout_bin" "$secs" "$@"
  else
    "$@"
  fi
}

# --- 1. shebang-aware syntax check ------------------------------------------
for f in "$BIN_DIR"/*; do
  [[ -f "$f" ]] || continue
  base=$(basename "$f")
  shebang=$(head -1 "$f")
  case "$shebang" in
    *zsh*)
      if err=$(run_bounded 6 zsh -n "$f" 2>&1); then
        pass "syntax:${base} (zsh -n)"
      else
        rc=$?
        if [[ "$rc" -eq 124 ]]; then
          # zsh -n hung on a parse-time command substitution; bash -n as fallback.
          if err=$(bash -n "$f" 2>&1); then
            pass "syntax:${base} (zsh -n timed out; bash -n fallback ok)"
          else
            fail "syntax:${base}" "zsh -n timeout AND bash -n failed: $(printf '%s' "$err" | tr '\n' '|')"
          fi
        else
          fail "syntax:${base} (zsh -n)" "$(printf '%s' "$err" | tr '\n' '|')"
        fi
      fi
      ;;
    *)
      if err=$(run_bounded 6 bash -n "$f" 2>&1); then
        pass "syntax:${base} (bash -n)"
      else
        fail "syntax:${base} (bash -n)" "$(printf '%s' "$err" | tr '\n' '|')"
      fi
      ;;
  esac
done

# --- 2. harmless representative executions ----------------------------------
# tproj-pane-autozoom --status only reads a flag file and prints on/off.
AUTOZOOM="$BIN_DIR/tproj-pane-autozoom"
if [[ -x "$AUTOZOOM" ]]; then
  if out=$(run_bounded 6 "$AUTOZOOM" --status 2>&1) && [[ "$out" == "on" || "$out" == "off" ]]; then
    pass "exec:tproj-pane-autozoom --status (=> $out)"
  else
    fail "exec:tproj-pane-autozoom --status" "unexpected output: $(printf '%s' "$out" | tr '\n' '|')"
  fi
  # --help just seds its own header; no side effects.
  if run_bounded 6 "$AUTOZOOM" --help >/dev/null 2>&1; then
    pass "exec:tproj-pane-autozoom --help"
  else
    fail "exec:tproj-pane-autozoom --help" "non-zero exit"
  fi
else
  fail "exec:tproj-pane-autozoom" "not executable"
fi

# tproj-role reads the declared mode. Both invocations below are read-only: the
# status segment is what the tmux status line calls many times an hour, so it has to
# stay quiet and quick, and --help must not touch the state either.
ROLE="$BIN_DIR/tproj-role"
if [[ -x "$ROLE" ]]; then
  if run_bounded 6 "$ROLE" --status-segment >/dev/null 2>&1; then
    pass "exec:tproj-role --status-segment"
  else
    fail "exec:tproj-role --status-segment" "non-zero exit"
  fi
  if run_bounded 6 "$ROLE" --help >/dev/null 2>&1; then
    pass "exec:tproj-role --help"
  else
    fail "exec:tproj-role --help" "non-zero exit"
  fi
  # An installation without model-role-router has no declared mode, and the read-only
  # entry points have to survive that: the status line calls the segment on every
  # refresh, so an error would be painted into the status bar permanently.
  # `env` narrows the PATH for the script alone; narrowing it for run_bounded would
  # hide the timeout binary it resolved at startup.
  if out=$(run_bounded 6 env PATH="/usr/bin:/bin" "$ROLE" --status-segment 2>&1) && [[ -z "$out" ]]; then
    pass "exec:tproj-role --status-segment without the router"
  else
    fail "exec:tproj-role --status-segment without the router" "output: $(printf '%s' "$out" | tr '\n' '|')"
  fi
  # The main side is what decides which pane the GUI treats as the one you talk to,
  # and it was only reachable from the GUI: an agent asked to hand it over could
  # declare a mode and leave `main` exactly where it was, which looks like nothing
  # happened. Both spellings are validated before the router is ever needed, so this
  # runs on an installation without one.
  # Needs the router on PATH: without one the script reports that first, by design,
  # so an installation that has no router simply does not exercise these.
  if command -v model-role-router >/dev/null 2>&1; then
    if out=$(run_bounded 6 "$ROLE" main bogus 2>&1); rc=$?; [[ "$rc" -eq 2 ]] \
       && printf '%s' "$out" | grep -q "cc, cdx, or derived"; then
      pass "exec:tproj-role rejects an unknown main side"
    else
      fail "exec:tproj-role rejects an unknown main side" "rc=$rc output: $(printf '%s' "$out" | tr '\n' '|')"
    fi
    if out=$(run_bounded 6 "$ROLE" --main bogus 2>&1); rc=$?; [[ "$rc" -eq 2 ]]; then
      pass "exec:tproj-role rejects an unknown --main side"
    else
      fail "exec:tproj-role rejects an unknown --main side" "rc=$rc output: $(printf '%s' "$out" | tr '\n' '|')"
    fi
  fi
  if printf '%s' "$($ROLE --help 2>&1)" | grep -q "main <side>"; then
    pass "exec:tproj-role --help documents the main side"
  else
    fail "exec:tproj-role --help documents the main side" "not in usage"
  fi
else
  fail "exec:tproj-role" "not executable"
fi

echo "----"
printf 'PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
