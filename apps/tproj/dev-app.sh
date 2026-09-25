#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_BUNDLE="$SCRIPT_DIR/dist/tproj.app"
DEBUG_BIN=""
MODE="debug"
PREBUILT=false
TPROJ_GUI_PIDFILE="${TMPDIR:-/tmp}/tproj-gui.pid"
TPROJ_GUI_LOG="${TMPDIR:-/tmp}/tproj-gui.log"

if [[ "${1:-}" == "--release" ]]; then
  MODE="release"
fi
APP_ARGUMENTS=()
for arg in "$@"; do
  if [[ "$arg" == "--server" ]]; then APP_ARGUMENTS+=("--server"); fi
  if [[ "$arg" == "--prebuilt" ]]; then PREBUILT=true; fi
done

# --- Build ---
if [[ "$PREBUILT" == true ]]; then
  [[ "$MODE" == "debug" ]] || { echo "--prebuilt cannot be combined with --release" >&2; exit 2; }
  DEBUG_BIN="$SCRIPT_DIR/.build/debug/tproj"
  [[ -x "$DEBUG_BIN" ]] || { echo "prebuilt app missing: $DEBUG_BIN" >&2; exit 1; }
elif [[ "$MODE" == "debug" ]]; then
  echo "==> Build app (debug)"
  pushd "$SCRIPT_DIR" >/dev/null
  swift build
  DEBUG_BIN="$(swift build --show-bin-path)/tproj"
  popd >/dev/null
else
  echo "==> Build app (release)"
  "$SCRIPT_DIR/build-app.sh"
fi

previous_pid=""
if [[ -f "$TPROJ_GUI_PIDFILE" ]]; then
  previous_pid="$(<"$TPROJ_GUI_PIDFILE")"
fi

retire_previous_gui() {
  local new_pid="$1" previous_command=""
  echo "$new_pid" > "$TPROJ_GUI_PIDFILE"
  [[ "$previous_pid" =~ ^[0-9]+$ && "$previous_pid" != "$new_pid" ]] || return 0
  previous_command="$(ps -p "$previous_pid" -o command= 2>/dev/null || true)"
  case "$previous_command" in
    "$SCRIPT_DIR"/.build/*/tproj|"$SCRIPT_DIR"/.build/*/tproj\ --server|"$SCRIPT_DIR"/dist/tproj.app/Contents/MacOS/tproj)
      kill "$previous_pid" 2>/dev/null || true ;;
  esac
}

launch_gui() {
  local executable="$1"

  : > "$TPROJ_GUI_LOG"
  if (( ${#APP_ARGUMENTS[@]} )); then
    /usr/bin/python3 -c \
      'import subprocess, sys; log = open(sys.argv[3], "ab", buffering=0); process = subprocess.Popen([sys.argv[2], *sys.argv[4:]], cwd=sys.argv[1], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True); print(process.pid)' \
      "$SCRIPT_DIR" "$executable" "$TPROJ_GUI_LOG" "${APP_ARGUMENTS[@]}"
  else
    /usr/bin/python3 -c \
      'import subprocess, sys; log = open(sys.argv[3], "ab", buffering=0); process = subprocess.Popen([sys.argv[2], *sys.argv[4:]], cwd=sys.argv[1], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True); print(process.pid)' \
      "$SCRIPT_DIR" "$executable" "$TPROJ_GUI_LOG"
  fi
}

# --- Launch ---
if [[ "$MODE" == "debug" ]]; then
  echo "==> Launch app (debug)"
  local_pid="$(launch_gui "$DEBUG_BIN")"
  sleep 1
  if ! kill -0 "$local_pid" 2>/dev/null; then
    echo "debug process (pid $local_pid) not detected; check $TPROJ_GUI_LOG" >&2
    exit 1
  fi
  retire_previous_gui "$local_pid"
  echo "Done: $DEBUG_BIN (pid $local_pid)"
else
  echo "==> Launch app (release)"
  local_pid="$(launch_gui "$APP_BUNDLE/Contents/MacOS/tproj")"
  sleep 1
  if ! kill -0 "$local_pid" 2>/dev/null; then
    echo "app process (pid $local_pid) not detected; check $TPROJ_GUI_LOG" >&2
    exit 1
  fi
  retire_previous_gui "$local_pid"
  echo "Done: $APP_BUNDLE (pid $local_pid)"
fi
