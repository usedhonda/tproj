# Extracted native prompt parser from tproj-msg; read-only, no routing.
TMUX_TYPING_GUARD_READ_LINES=120
TMUX_TYPING_GUARD_SCAN_TAIL_LINES=48
TMUX_TYPING_GUARD_MAX_PROMPT_DISTANCE_LINES=8
TMUX_TYPING_GUARD_MAX_CONTINUATION_LINES=2
TMUX_TYPING_GUARD_RECHECK_DELAY_SEC=0.12
TMUX_TYPING_GUARD_STABLE_DRAFT_MIN_CHARS="${TPROJ_TYPING_GUARD_STABLE_DRAFT_MIN_CHARS:-4}"

strip_ansi() {
  sed 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\x1b\][^\x07]*\x07//g'
}

trim_spaces() {
  printf '%s' "$1" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
}

is_tmux_footer_line() {
  local line="$1"
  local s lower
  s=$(trim_spaces "$line")
  [[ -z "$s" ]] && return 1
  lower=$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')

  [[ "$lower" == "? for shortcuts" ]] && return 0
  [[ "$lower" =~ ^[0-9]+%[[:space:]]+context[[:space:]]+left$ ]] && return 0
  [[ "$lower" =~ ^[0-9]+%[[:space:]]+context[[:space:]]+window$ ]] && return 0
  [[ "$lower" =~ ^autonomous:[[:space:]]+ ]] && return 0
  return 1
}

is_tmux_divider_line() {
  local line="$1" s
  s=$(trim_spaces "$line")
  [[ -z "$s" ]] && return 1
  printf '%s\n' "$s" | grep -Eq '^[-─━]{3,}$'
}

is_prompt_line() {
  local line="$1"
  printf '%s\n' "$line" | grep -Eq '^[[:space:]]*[›❯>][[:space:]]*'
}

has_cursor_glyph() {
  local line="$1"
  printf '%s\n' "$line" | grep -Eq '[▌█▋▍▎▏]'
}

strip_prompt_ui_tail() {
  local text cleaned
  if [[ $# -gt 0 ]]; then
    text="$1"
  else
    text=$(cat)
  fi
  cleaned=$(printf '%s' "$text" \
    | sed -E 's/[[:space:]]+\?[[:space:]]*for[[:space:]]+shortcuts.*$//')
  cleaned=$(printf '%s' "$cleaned" \
    | sed -E 's/[[:space:]]+[0-9]+%[[:space:]]+context[[:space:]]+(left|window)$//')
  printf '%s' "$cleaned" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
}

is_prompt_placeholder_text() {
  local text="$1"
  local lower
  lower=$(printf '%s' "$text" | tr '[:upper:]' '[:lower:]' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
  [[ -z "$lower" ]] && return 0
  [[ "$lower" == "? for shortcuts" ]] && return 0
  [[ "$lower" =~ ^(type|enter)[[:space:]]+(a[[:space:]]+)?(message|prompt) ]] && return 0
  [[ "$lower" =~ ^(esc|escape)[[:space:]]+to[[:space:]]+ ]] && return 0
  [[ "$lower" =~ ^(shift|ctrl|control|tab)[+[:space:]-] ]] && return 0
  return 1
}

raw_prompt_has_dim() {
  local raw_captured="$1" line prompt_raw plain
  [[ -z "$raw_captured" ]] && return 1

  prompt_raw=""
  while IFS= read -r line; do
    plain=$(printf '%s' "$line" | strip_ansi)
    if is_prompt_line "$plain"; then
      prompt_raw="$line"
    fi
  done <<< "$raw_captured"
  [[ -z "$prompt_raw" ]] && return 1

  local after_prompt after_plain
  after_prompt=$(printf '%s' "$prompt_raw" | sed -E 's/^.*[›❯>][[:space:]]*//')
  after_plain=$(printf '%s' "$after_prompt" | strip_ansi | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
  [[ -z "$after_plain" ]] && return 1

  local esc=$'\x1b'
  # SGR dim: ESC[2m or ESC[0;2m (not ESC[12m, ESC[22m)
  printf '%s' "$after_prompt" | grep -qE "${esc}\[(0;)?2m|${esc}\[;2m" && return 0
  # Bright black (SGR 90)
  printf '%s' "$after_prompt" | grep -qE "${esc}\[90m" && return 0
  return 1
}

parse_prompt_snapshot() {
  local captured="$1"
  local cleaned line

  PROMPT_PARSE_OK="false"
  PROMPT_PARSE_REASON="capture_failed"
  PROMPT_PARSE_TEXT=""
  PROMPT_PARSE_HAS_CURSOR="false"
  PROMPT_PARSE_DISTANCE=999
  PROMPT_PARSE_MARKER="none"

  if [[ -z "$captured" ]]; then
    PROMPT_PARSE_REASON="empty_capture"
    return 0
  fi

  cleaned=$(printf '%s\n' "$captured" | strip_ansi)
  local _draft_source=()
  while IFS= read -r line; do
    _draft_source+=("$line")
  done <<< "$cleaned"
  if [[ ${#_draft_source[@]} -eq 0 ]]; then
    PROMPT_PARSE_REASON="empty_capture"
    return 0
  fi

  local source_len start
  source_len=${#_draft_source[@]}
  if (( source_len > TMUX_TYPING_GUARD_SCAN_TAIL_LINES )); then
    start=$(( source_len - TMUX_TYPING_GUARD_SCAN_TAIL_LINES ))
  else
    start=0
  fi
  local _draft_tail=( "${_draft_source[@]:$start}" )
  local tail_len=${#_draft_tail[@]}
  if (( tail_len == 0 )); then
    PROMPT_PARSE_REASON="empty_capture"
    return 0
  fi

  local end=$(( tail_len - 1 ))
  local trimmed
  while (( end >= 0 )); do
    trimmed=$(trim_spaces "${_draft_tail[$end]}")
    [[ -n "$trimmed" ]] && break
    ((end--))
  done
  if (( end < 0 )); then
    PROMPT_PARSE_REASON="blank_capture"
    return 0
  fi

  while (( end >= 0 )); do
    if is_tmux_footer_line "${_draft_tail[$end]}" || is_tmux_divider_line "${_draft_tail[$end]}"; then
      ((end--))
      continue
    fi
    break
  done
  if (( end < 0 )); then
    PROMPT_PARSE_REASON="footer_only_capture"
    return 0
  fi

  local search_start=$(( end - 16 ))
  (( search_start < 0 )) && search_start=0
  local prompt_index=-1 i
  for (( i=end; i>=search_start; i-- )); do
    if is_prompt_line "${_draft_tail[$i]}"; then
      prompt_index=$i
      break
    fi
  done

  if (( prompt_index < 0 )); then
    PROMPT_PARSE_REASON="prompt_not_found"
    return 0
  fi

  if (( end - prompt_index > TMUX_TYPING_GUARD_MAX_PROMPT_DISTANCE_LINES )); then
    PROMPT_PARSE_REASON="prompt_too_far_from_bottom"
    return 0
  fi
  PROMPT_PARSE_DISTANCE=$(( end - prompt_index ))

  # Classify the prompt-line marker so callers can distinguish a native TUI
  # prompt (❯ U+276F / › U+203A) from a bare ASCII '>' -- the latter is also a
  # Markdown blockquote in generated output and must not be trusted as a live
  # input prompt by the signal-agnostic draft guard.
  local _prompt_lead
  _prompt_lead=$(printf '%s' "${_draft_tail[$prompt_index]}" | sed -E 's/^[[:space:]]*//')
  case "$_prompt_lead" in
    $'\xe2\x9d\xaf'*|$'\xe2\x80\xba'*) PROMPT_PARSE_MARKER="native" ;;
    '>'*)                             PROMPT_PARSE_MARKER="ascii" ;;
    *)                                PROMPT_PARSE_MARKER="none" ;;
  esac

  local draft_parts=()
  local prompt_body first_draft
  prompt_body=$(printf '%s' "${_draft_tail[$prompt_index]}" \
    | sed -E 's/^[[:space:]]*[›❯>][[:space:]]*//')
  if has_cursor_glyph "$prompt_body"; then
    PROMPT_PARSE_HAS_CURSOR="true"
  fi

  first_draft=$(printf '%s' "$prompt_body" \
    | sed -E 's/[▌█▋▍▎▏]+$//' \
    | strip_prompt_ui_tail)
  [[ -n "$first_draft" ]] && draft_parts+=("$first_draft")

  local continuation_end=$(( prompt_index + TMUX_TYPING_GUARD_MAX_CONTINUATION_LINES ))
  (( continuation_end > end )) && continuation_end=$end
  local raw normalized
  for (( i=prompt_index+1; i<=continuation_end; i++ )); do
    raw="${_draft_tail[$i]}"
    trimmed=$(trim_spaces "$raw")
    [[ -z "$trimmed" ]] && continue
    if is_tmux_footer_line "$raw" || is_tmux_divider_line "$raw" || is_prompt_line "$raw"; then
      break
    fi
    if has_cursor_glyph "$raw"; then
      PROMPT_PARSE_HAS_CURSOR="true"
    fi
    normalized=$(printf '%s' "$raw" \
      | sed -E 's/[▌█▋▍▎▏]+$//' \
      | strip_prompt_ui_tail)
    [[ -n "$normalized" ]] && draft_parts+=("$normalized")
  done

  local draft_text=""
  if (( ${#draft_parts[@]} > 0 )); then
    draft_text=$(printf '%s ' "${draft_parts[@]}" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')
  fi

  PROMPT_PARSE_OK="true"
  PROMPT_PARSE_REASON="ok"
  PROMPT_PARSE_TEXT="$draft_text"
  return 0
}

measure_input_line_draft() {
  local pane="$1"
  local raw_captured captured
  INPUT_DRAFT_RESULT="unknown"
  INPUT_DRAFT_SNIPPET=""

  raw_captured=$(tmux capture-pane -t "$pane" -e -p -S "-${TMUX_TYPING_GUARD_READ_LINES}" 2>/dev/null || true)
  if [[ -z "$raw_captured" ]]; then
    return 0  # capture failed -> unknown (fail-open)
  fi
  captured=$(printf '%s\n' "$raw_captured" | strip_ansi)
  parse_prompt_snapshot "$captured"
  if [[ "$PROMPT_PARSE_OK" != "true" ]]; then
    return 0  # no locatable prompt line -> unknown (fail-open)
  fi

  # Empty or placeholder-only input line -> clean prompt.
  if [[ -z "$PROMPT_PARSE_TEXT" ]] || is_prompt_placeholder_text "$PROMPT_PARSE_TEXT"; then
    INPUT_DRAFT_RESULT="clear"
    return 0
  fi

  # A dim ghost-suggestion is not an unsent draft; existing behavior treats it
  # as sendable, so do not block on it (keeps the #9 false-busy contract).
  if raw_prompt_has_dim "$raw_captured"; then
    INPUT_DRAFT_RESULT="clear"
    return 0
  fi

  # Require native-marker evidence (❯/›). A bare ASCII '>' line is a Markdown
  # blockquote in generated output, not a live input prompt -- treating it as a
  # draft would queue notices behind ordinary output (2026-07-20 false positive).
  # Without a native marker the measurement is inconclusive -> unknown (fail-open).
  if [[ "$PROMPT_PARSE_MARKER" != "native" ]]; then
    INPUT_DRAFT_RESULT="unknown"
    return 0
  fi

  # Real text on the active bottom native prompt (cursor present, or the prompt
  # line is at/adjacent to the active bottom) is an unsent draft. Text on a
  # prompt line further up the scrollback is historical, not a live draft.
  if [[ "$PROMPT_PARSE_HAS_CURSOR" == "true" ]] || (( PROMPT_PARSE_DISTANCE <= 1 )); then
    INPUT_DRAFT_RESULT="draft"
    INPUT_DRAFT_SNIPPET=$(printf '%s' "$PROMPT_PARSE_TEXT" | cut -c1-120)
    return 0
  fi

  INPUT_DRAFT_RESULT="unknown"
  return 0
}
