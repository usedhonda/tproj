#!/bin/bash
set -euo pipefail

# tproj installer
# Usage: ./install.sh [-h] [-n] [-y]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ========== Options ==========

DRY_RUN=false
AUTO_YES=false
CORE_ONLY=false
WITH_MEMORY=false
ALL_EXTENSIONS=false
CHECK_ONLY=false

# Core scripts copied to ~/bin (single source of truth for install + --check).
CORE_BINS=(tproj tproj-drop-column tproj-kill-pane tproj-toggle-yazi tproj-pane-focus-hook tproj-pane-clear-rank tproj-pane-autozoom tproj-tmux-state-notify tproj-mru-tracker tproj-respawn-guard tproj-postmortem tproj-mem-trace rebalance-workspace-columns sign-codex wait-for-pane-text)
PERSONA_BOOTSTRAP_LINK="$SCRIPT_DIR/extensions/persona/project-bootstrap"
PERSONA_BOOTSTRAP_TARGET="../../../general/system/project-bootstrap/project-bootstrap"
PERSONA_BOOTSTRAP_ERROR=""
MODEL_ROLE_ROUTER_LINK="$SCRIPT_DIR/extensions/model-role-router/model-role-router"
MODEL_ROLE_ROUTER_TARGET="../../../general/system/model-role-router/model-role-router"
MODEL_ROLE_ROUTER_ERROR=""

validate_persona_bootstrap_source() {
  PERSONA_BOOTSTRAP_ERROR=""
  if [[ ! -L "$PERSONA_BOOTSTRAP_LINK" ]]; then
    PERSONA_BOOTSTRAP_ERROR="project-bootstrap (tracked source is not a symlink)"
    return 1
  fi
  if [[ "$(readlink "$PERSONA_BOOTSTRAP_LINK")" != "$PERSONA_BOOTSTRAP_TARGET" ]]; then
    PERSONA_BOOTSTRAP_ERROR="project-bootstrap (tracked symlink target differs)"
    return 1
  fi
  if [[ ! -f "$PERSONA_BOOTSTRAP_LINK" ]]; then
    PERSONA_BOOTSTRAP_ERROR="project-bootstrap (canonical general source is missing)"
    return 1
  fi
}

validate_model_role_router_source() {
  MODEL_ROLE_ROUTER_ERROR=""
  if [[ ! -L "$MODEL_ROLE_ROUTER_LINK" ]]; then
    MODEL_ROLE_ROUTER_ERROR="model-role-router (tracked source is not a symlink)"
    return 1
  fi
  if [[ "$(readlink "$MODEL_ROLE_ROUTER_LINK")" != "$MODEL_ROLE_ROUTER_TARGET" ]]; then
    MODEL_ROLE_ROUTER_ERROR="model-role-router (tracked symlink target differs)"
    return 1
  fi
  if [[ ! -f "$MODEL_ROLE_ROUTER_LINK" ]]; then
    MODEL_ROLE_ROUTER_ERROR="model-role-router (canonical general source is missing)"
    return 1
  fi
}

usage() {
  cat << 'EOF'
tproj installer

Usage: ./install.sh [OPTIONS]

Options:
  -h, --help          Show this help
  -n, --dry-run       Show what would be done without making changes
  -y, --yes           Auto-yes (skip confirmations)
  --core-only         Install core only (no extensions)
  --with-memory       Include memory extension (cc-mem, memory-guard)
  --all               Install all extensions including memory
  --check             Report repo bin/ and canonical extension drift (no install)

By default, messaging + persona + model-role-router + agent-teams extensions are installed.
Memory extension requires --with-memory or --all (runs a launchd daemon).

Examples:
  ./install.sh           # core + default extensions
  ./install.sh --all     # everything including memory
  ./install.sh --core-only  # minimal install
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case $1 in
    -h|--help)
      usage
      ;;
    -n|--dry-run)
      DRY_RUN=true
      shift
      ;;
    -y|--yes)
      AUTO_YES=true
      shift
      ;;
    --core-only)
      CORE_ONLY=true
      shift
      ;;
    --with-memory)
      WITH_MEMORY=true
      shift
      ;;
    --all)
      ALL_EXTENSIONS=true
      WITH_MEMORY=true
      shift
      ;;
    --check)
      CHECK_ONLY=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "   Help: ./install.sh -h"
      exit 1
      ;;
  esac
done

# ========== --check: repo<->~/bin drift detection (read-only) ==========
# Self-contained: diffs each CORE_BINS file and each canonical general source ->
# tracked tproj symlink -> ~/bin copy chain. Exits before any
# install processing runs. Never copies or touches launchctl.
if $CHECK_ONLY; then
  drift=()
  for bin_name in "${CORE_BINS[@]}"; do
    repo_file="$SCRIPT_DIR/bin/$bin_name"
    installed="$HOME/bin/$bin_name"
    if [[ ! -f "$installed" ]]; then
      drift+=("$bin_name (missing in ~/bin)")
    elif ! diff -q "$repo_file" "$installed" >/dev/null 2>&1; then
      drift+=("$bin_name (differs)")
    fi
  done
  # shared library sourced by the core scripts
  if [[ ! -f "$HOME/bin/lib/tproj-common.sh" ]]; then
    drift+=("lib/tproj-common.sh (missing in ~/bin)")
  elif ! diff -q "$SCRIPT_DIR/bin/lib/tproj-common.sh" "$HOME/bin/lib/tproj-common.sh" >/dev/null 2>&1; then
    drift+=("lib/tproj-common.sh (differs)")
  fi
  if [[ ! -f "$HOME/bin/lib/tproj-model-role.sh" ]]; then
    drift+=("lib/tproj-model-role.sh (missing in ~/bin)")
  elif ! diff -q "$SCRIPT_DIR/bin/lib/tproj-model-role.sh" "$HOME/bin/lib/tproj-model-role.sh" >/dev/null 2>&1; then
    drift+=("lib/tproj-model-role.sh (differs)")
  fi
  if ! $CORE_ONLY; then
    if ! validate_persona_bootstrap_source; then
      drift+=("$PERSONA_BOOTSTRAP_ERROR")
    elif [[ ! -f "$HOME/bin/project-bootstrap" ]]; then
      drift+=("project-bootstrap (missing installed copy in ~/bin)")
    elif ! cmp -s "$PERSONA_BOOTSTRAP_LINK" "$HOME/bin/project-bootstrap"; then
      drift+=("project-bootstrap (installed copy differs from canonical source)")
    fi
    if ! validate_model_role_router_source; then
      drift+=("$MODEL_ROLE_ROUTER_ERROR")
    elif [[ ! -f "$HOME/bin/model-role-router" ]]; then
      drift+=("model-role-router (missing installed copy in ~/bin)")
    elif ! cmp -s "$MODEL_ROLE_ROUTER_LINK" "$HOME/bin/model-role-router"; then
      drift+=("model-role-router (installed copy differs from canonical source)")
    fi
    # msg skill distributed to Claude Code and Codex (see install step below)
    skill_src="$SCRIPT_DIR/extensions/messaging/skill-msg/SKILL.md"
    for skill_rel in ".claude/skills/msg/SKILL.md" ".codex/skills/msg/SKILL.md"; do
      skill_copy="$HOME/$skill_rel"
      if [[ ! -f "$skill_copy" ]]; then
        drift+=("$skill_rel (missing installed copy)")
      elif ! diff -q "$skill_src" "$skill_copy" >/dev/null 2>&1; then
        drift+=("$skill_rel (installed copy differs from repo source)")
      fi
    done
  fi
  if [[ ${#drift[@]} -gt 0 ]]; then
    echo "drift detected in repo/install chain:"
    for d in "${drift[@]}"; do
      echo "  - $d"
    done
    exit 1
  fi
  if $CORE_ONLY; then
    echo "no drift: repo bin/ matches ~/bin for all ${#CORE_BINS[@]} core scripts"
  else
    echo "no drift: core scripts and canonical extension chains match ~/bin"
  fi
  exit 0
fi

# ========== Helper functions ==========

# Dry-run aware command execution
run_cmd() {
  if $DRY_RUN; then
    echo "[DRY-RUN] $*"
  else
    "$@"
  fi
}

# Y/n confirmation (-y to auto-accept)
confirm() {
  local prompt=$1
  if $AUTO_YES; then
    return 0
  fi
  echo -n "$prompt [Y/n] "
  read -r answer
  case "$answer" in
    [nN]|[nN][oO]) return 1 ;;
    *) return 0 ;;
  esac
}

check_command() {
  local cmd=$1
  local name=${2:-$cmd}
  if command -v "$cmd" &> /dev/null; then
    echo "  ✅ $name"
    return 0
  else
    echo "  ❌ $name"
    return 1
  fi
}

BACKUP_TS="$(date +%Y%m%d_%H%M%S)"

backup_if_exists() {
  local file=$1
  if [[ -f "$file" && ! -L "$file" ]]; then
    local backup="${file}.bak.${BACKUP_TS}"
    if $DRY_RUN; then
      echo "[DRY-RUN] Backup: $file -> $backup"
    else
      cp "$file" "$backup"
      echo "  Backup: $backup"
    fi
  fi
}

print_config_preflight() {
  echo "Configuration preflight:"
  echo "  Will write: $HOME/.tmux.conf"
  [[ -f "$HOME/.tmux.conf" && ! -L "$HOME/.tmux.conf" ]] && echo "    Existing file will be backed up: $HOME/.tmux.conf.bak.${BACKUP_TS}"
  echo "  Will write: $HOME/.config/yazi/yazi.toml"
  [[ -f "$HOME/.config/yazi/yazi.toml" && ! -L "$HOME/.config/yazi/yazi.toml" ]] && echo "    Existing file will be backed up: $HOME/.config/yazi/yazi.toml.bak.${BACKUP_TS}"
  echo "  Will write: $HOME/.config/yazi/keymap.toml"
  [[ -f "$HOME/.config/yazi/keymap.toml" && ! -L "$HOME/.config/yazi/keymap.toml" ]] && echo "    Existing file will be backed up: $HOME/.config/yazi/keymap.toml.bak.${BACKUP_TS}"
  echo "  Will write: $HOME/.config/yazi/package.toml"
  [[ -f "$HOME/.config/yazi/package.toml" && ! -L "$HOME/.config/yazi/package.toml" ]] && echo "    Existing file will be backed up: $HOME/.config/yazi/package.toml.bak.${BACKUP_TS}"
  echo "  Will write: $HOME/.config/yazi/plugins/"
}

# ========== 1. Dependency check ==========

echo "Checking dependencies..."

# Tools installable via brew. Keep the required runtime set aligned with
# `tproj init` and `tproj --check` (tmux jq yq bat yazi).
BREW_DEPS=(npm:node git tmux yazi bat yq jq)
# Tools installable via npm
NPM_DEPS=(claude:@anthropic-ai/claude-code codex:@openai/codex)

MISSING_BREW=()
MISSING_NPM=()

for dep in "${BREW_DEPS[@]}"; do
  cmd="${dep%%:*}"
  pkg="${dep##*:}"
  if ! check_command "$cmd"; then
    MISSING_BREW+=("$pkg")
  fi
done

for dep in "${NPM_DEPS[@]}"; do
  cmd="${dep%%:*}"
  pkg="${dep##*:}"
  name="$cmd"
  [[ "$cmd" == "claude" ]] && name="Claude Code"
  [[ "$cmd" == "codex" ]] && name="Codex"
  if ! check_command "$cmd" "$name"; then
    MISSING_NPM+=("$pkg")
  fi
done

# ========== 2. Install missing tools ==========

if [[ ${#MISSING_BREW[@]} -gt 0 ]]; then
  echo ""
  echo "Missing tools: ${MISSING_BREW[*]}"

  if command -v brew &> /dev/null; then
    if confirm "Install with brew?"; then
      for pkg in "${MISSING_BREW[@]}"; do
        echo "  brew install $pkg"
        if ! $DRY_RUN; then
          brew install "$pkg"
        else
          echo "[DRY-RUN] brew install $pkg"
        fi
      done
    else
      echo ""
      echo "Please install manually:"
      for pkg in "${MISSING_BREW[@]}"; do
        echo "  brew install $pkg"
      done
      exit 1
    fi
  else
    echo ""
    echo "Homebrew not found. See https://brew.sh then re-run this script."
    echo ""
    echo "Or install manually:"
    for pkg in "${MISSING_BREW[@]}"; do
      echo "  $pkg"
    done
    exit 1
  fi
fi

if [[ ${#MISSING_NPM[@]} -gt 0 ]]; then
  echo ""
  echo "Missing npm packages:"
  for pkg in "${MISSING_NPM[@]}"; do
    echo "  $pkg"
  done

  if command -v npm &> /dev/null; then
    if confirm "Install globally with npm?"; then
      for pkg in "${MISSING_NPM[@]}"; do
        echo "  npm install -g $pkg"
        if ! $DRY_RUN; then
          npm install -g "$pkg"
        else
          echo "[DRY-RUN] npm install -g $pkg"
        fi
      done
    else
      echo ""
      echo "Please install manually:"
      for pkg in "${MISSING_NPM[@]}"; do
        echo "  npm install -g $pkg"
      done
      exit 1
    fi
  else
    echo ""
    echo "npm not found. Install Node.js first, then re-run."
    exit 1
  fi
fi

echo ""
if $DRY_RUN; then
  echo "tproj install (dry run)"
else
  echo "Installing tproj..."
fi

# ========== 3. Terminfo setup ==========

if ! infocmp xterm-ghostty &>/dev/null; then
  if $DRY_RUN; then
    echo "[DRY-RUN] xterm-ghostty terminfo -> ~/.terminfo/"
  else
    echo "  xterm-ghostty terminfo -> ~/.terminfo/"
    tic -x "$SCRIPT_DIR/config/terminfo/xterm-ghostty.terminfo"
  fi
else
  echo "  xterm-ghostty terminfo (already installed)"
fi

# ========== 4. Backup & copy ==========

# 4.1 Core scripts (CORE_BINS defined near the top; shared with --check)

if $DRY_RUN; then
  for bin_name in "${CORE_BINS[@]}"; do
    echo "[DRY-RUN] $bin_name -> ~/bin/"
  done
  echo "[DRY-RUN] lib/tproj-common.sh, lib/tproj-model-role.sh -> ~/bin/lib/"
else
  echo "  Core scripts -> ~/bin/"
  mkdir -p ~/bin
  # Remove broken symlinks (e.g. from deleted tproj-ext)
  find ~/bin/ -maxdepth 1 -type l ! -exec test -e {} \; -delete 2>/dev/null || true
  for bin_name in "${CORE_BINS[@]}"; do
    rm -f ~/bin/"$bin_name"  # remove stale symlink before cp
    cp "$SCRIPT_DIR/bin/$bin_name" ~/bin/"$bin_name"
    chmod +x ~/bin/"$bin_name"
  done
  # Shared library sourced by the core scripts (bin/lib -> ~/bin/lib)
  mkdir -p ~/bin/lib
  cp "$SCRIPT_DIR/bin/lib/tproj-common.sh" ~/bin/lib/tproj-common.sh
  cp "$SCRIPT_DIR/bin/lib/tproj-model-role.sh" ~/bin/lib/tproj-model-role.sh

  # Legacy cleanup: remove old launchd plist
  OLD_PLIST="$HOME/Library/LaunchAgents/com.memory-guard.plist"
  # Always try bootout (plist may be loaded even if file was already deleted)
  launchctl bootout "gui/$(id -u)/com.memory-guard" 2>/dev/null || true
  if [[ -f "$OLD_PLIST" ]]; then
    rm -f "$OLD_PLIST"
    echo "  removed legacy $OLD_PLIST"
  fi

  # Legacy cleanup: remove stale binaries
  for legacy_bin in tproj-gui tproj-mcp-init tproj-pane-watchdog; do
    if [[ -f "$HOME/bin/$legacy_bin" ]]; then
      rm -f "$HOME/bin/$legacy_bin"
      echo "  Removed legacy ~/bin/$legacy_bin"
    fi
  done
fi

# 4.2 tmux config
print_config_preflight
backup_if_exists ~/.tmux.conf
if $DRY_RUN; then
  echo "[DRY-RUN] tmux.conf -> ~/.tmux.conf"
else
  echo "  tmux.conf -> ~/.tmux.conf"
  cp "$SCRIPT_DIR/config/tmux/tmux.conf" ~/.tmux.conf
fi

# 4.3 yazi config
if $DRY_RUN; then
  echo "[DRY-RUN] yazi config -> ~/.config/yazi/"
else
  echo "  yazi config -> ~/.config/yazi/"
  mkdir -p ~/.config/yazi/plugins
fi
backup_if_exists ~/.config/yazi/yazi.toml
backup_if_exists ~/.config/yazi/keymap.toml
backup_if_exists ~/.config/yazi/package.toml
if ! $DRY_RUN; then
  cp "$SCRIPT_DIR/config/yazi/yazi.toml" ~/.config/yazi/
  cp "$SCRIPT_DIR/config/yazi/keymap.toml" ~/.config/yazi/
  cp "$SCRIPT_DIR/config/yazi/package.toml" ~/.config/yazi/
  cp -r "$SCRIPT_DIR/config/yazi/plugins/"* ~/.config/yazi/plugins/
fi

# 4.4 yazi plugins
if command -v ya &> /dev/null; then
  if $DRY_RUN; then
    echo "[DRY-RUN] yazi plugins (ya pack)"
  else
    echo "  yazi plugins (ya pack)"
    if ! (cd ~/.config/yazi && ya pack -i 2>/dev/null); then
      echo "  Warning: yazi plugin install failed (best-effort)."
      echo "           Retry manually: cd ~/.config/yazi && ya pack -i"
    fi
  fi
fi

# ========== 5. PATH setup ==========

if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
  echo ""
  echo "~/bin is not in your PATH."

  SHELL_RC=""
  if [[ -f ~/.zshrc ]]; then
    SHELL_RC=~/.zshrc
  elif [[ -f ~/.bashrc ]]; then
    SHELL_RC=~/.bashrc
  fi

  if [[ -n "$SHELL_RC" ]]; then
    if confirm "Add PATH entry to $SHELL_RC?"; then
      PATH_LINE='export PATH="$HOME/bin:$PATH"'
      if $DRY_RUN; then
        echo "[DRY-RUN] Would add to $SHELL_RC:"
        echo "   $PATH_LINE"
      else
        echo "" >> "$SHELL_RC"
        echo "# Added by tproj installer" >> "$SHELL_RC"
        echo "$PATH_LINE" >> "$SHELL_RC"
        echo "  Added PATH to $SHELL_RC"
        echo "  Run: source $SHELL_RC"
      fi
    else
      echo "  Add this to your shell profile manually:"
      echo '  export PATH="$HOME/bin:$PATH"'
    fi
  else
    echo "  Add this to ~/.zshrc or ~/.bashrc:"
    echo '  export PATH="$HOME/bin:$PATH"'
  fi
fi

# ========== 6. Extensions ==========

if ! $CORE_ONLY; then
  echo ""
  echo "Installing extensions..."
  mkdir -p ~/bin

  # --- messaging ---
  if [[ -d "$SCRIPT_DIR/extensions/messaging" ]]; then
    echo "  messaging (tproj-msg, tproj-task, tproj-task-cache, tproj-msg-db, tproj-msg-desktop)"
    if ! $DRY_RUN; then
      cp "$SCRIPT_DIR/extensions/messaging/tproj-msg" ~/bin/
      cp "$SCRIPT_DIR/extensions/messaging/tproj-task" ~/bin/
      cp "$SCRIPT_DIR/extensions/messaging/tproj-task-cache.sh" ~/bin/
      cp "$SCRIPT_DIR/extensions/messaging/tproj-msg-db.sh" ~/bin/
      cp "$SCRIPT_DIR/extensions/messaging/tproj-msg-desktop.sh" ~/bin/
      cp "$SCRIPT_DIR/extensions/messaging/tproj-inbox-monitor" ~/bin/
      chmod +x ~/bin/tproj-msg
      chmod +x ~/bin/tproj-task
      chmod +x ~/bin/tproj-task-cache.sh
      chmod +x ~/bin/tproj-msg-db.sh
      chmod +x ~/bin/tproj-msg-desktop.sh
      chmod +x ~/bin/tproj-inbox-monitor
      # Install msg skill for Claude Code and Codex
      mkdir -p "$HOME/.claude/skills/msg" "$HOME/.codex/skills/msg"
      cp "$SCRIPT_DIR/extensions/messaging/skill-msg/SKILL.md" "$HOME/.claude/skills/msg/"
      cp "$SCRIPT_DIR/extensions/messaging/skill-msg/SKILL.md" "$HOME/.codex/skills/msg/"
    else
      echo "    [DRY-RUN] tproj-msg -> ~/bin/"
      echo "    [DRY-RUN] tproj-task, tproj-task-cache.sh, tproj-msg-db.sh, tproj-msg-desktop.sh, tproj-inbox-monitor -> ~/bin/"
      echo "    [DRY-RUN] msg skill -> ~/.claude/skills/ + ~/.codex/skills/"
    fi
  fi

  # --- hooks ---
  if [[ -d "$SCRIPT_DIR/extensions/hooks" ]]; then
    echo "  hooks (tproj-inbox-record, tproj-inbox-check, tproj-completion-guard)"
    if ! $DRY_RUN; then
      cp "$SCRIPT_DIR/extensions/hooks/tproj-inbox-record" ~/bin/
      cp "$SCRIPT_DIR/extensions/hooks/tproj-inbox-check" ~/bin/
      cp "$SCRIPT_DIR/extensions/hooks/tproj-completion-guard" ~/bin/
      chmod +x ~/bin/tproj-inbox-record ~/bin/tproj-inbox-check ~/bin/tproj-completion-guard
      "$SCRIPT_DIR/extensions/hooks/install-tproj-hooks"
    else
      echo "    [DRY-RUN] tproj-inbox-record, tproj-inbox-check, tproj-completion-guard -> ~/bin/"
      echo "    [DRY-RUN] merge lifecycle hooks into Claude/Codex settings"
    fi
  fi

  # --- tproj-msg DB init (R1' Stage 5) ---
  echo "  tproj-msg DB (SQLite WAL at ~/.local/share/tproj-msg/messages.db)"
  if ! $DRY_RUN; then
    mkdir -p ~/.local/share/tproj-msg
    if command -v sqlite3 >/dev/null 2>&1; then
      ~/bin/tproj-msg-db.sh init 2>/dev/null || echo "    [warn] DB init failed (fail-open, shadow writes disabled)"
    else
      echo "    [skip] sqlite3 not found, DB shadow writes disabled (fail-open)"
    fi
  else
    echo "    [DRY-RUN] mkdir -p ~/.local/share/tproj-msg + tproj-msg-db.sh init"
  fi

  # --- persona ---
  if [[ -d "$SCRIPT_DIR/extensions/persona" ]]; then
    echo "  persona (project-bootstrap, cc-persona compat, tproj-pane-bg, voicevox-alert, voice-identity-sync)"
    if ! validate_persona_bootstrap_source; then
      echo "    [error] $PERSONA_BOOTSTRAP_ERROR" >&2
      exit 1
    fi
    if ! $DRY_RUN; then
      rm -f ~/bin/project-bootstrap ~/bin/cc-persona ~/bin/tproj-pane-bg ~/bin/voicevox-alert ~/bin/voice-identity-sync  # remove stale symlinks
      cp -L "$PERSONA_BOOTSTRAP_LINK" ~/bin/project-bootstrap
      cp "$SCRIPT_DIR/extensions/persona/cc-persona" ~/bin/
      cp "$SCRIPT_DIR/extensions/persona/tproj-pane-bg" ~/bin/
      cp "$SCRIPT_DIR/extensions/persona/voicevox-alert" ~/bin/
      cp "$SCRIPT_DIR/extensions/persona/voice-identity-sync" ~/bin/
      chmod +x ~/bin/project-bootstrap ~/bin/cc-persona ~/bin/tproj-pane-bg ~/bin/voicevox-alert ~/bin/voice-identity-sync
    else
      echo "    [DRY-RUN] project-bootstrap, cc-persona, tproj-pane-bg, voicevox-alert, voice-identity-sync -> ~/bin/"
    fi
    # Check optional deps
    if ! command -v jq &>/dev/null; then
      echo "    ⚠️  jq not found (required by project-bootstrap and tproj): brew install jq"
    fi
    if ! command -v sqlite3 &>/dev/null; then
      echo "    ℹ️  sqlite3 not found (optional, for tproj-msg SQLite monitor): brew install sqlite3"
    fi
    if ! python3 -c "import genai" 2>/dev/null; then
      echo "    ℹ️  google-genai not found (optional, for AI image generation): pip3 install google-genai"
    fi
  fi

  # --- active-model role router ---
  if [[ -d "$SCRIPT_DIR/extensions/model-role-router" ]]; then
    echo "  model-role-router (canonical active-model hierarchy router)"
    if ! validate_model_role_router_source; then
      echo "    [error] $MODEL_ROLE_ROUTER_ERROR" >&2
      exit 1
    fi
    if ! $DRY_RUN; then
      rm -f ~/bin/model-role-router
      cp -L "$MODEL_ROLE_ROUTER_LINK" ~/bin/model-role-router
      chmod +x ~/bin/model-role-router
    else
      echo "    [DRY-RUN] model-role-router -> ~/bin/"
    fi
  fi

  # --- agent-teams ---
  if [[ -d "$SCRIPT_DIR/extensions/agent-teams" ]]; then
    echo "  agent-teams (team-watcher, reflow-agent-pane, agent-monitor)"
    if ! $DRY_RUN; then
      for ext_bin in team-watcher reflow-agent-pane agent-monitor; do
        cp "$SCRIPT_DIR/extensions/agent-teams/$ext_bin" ~/bin/
        chmod +x ~/bin/"$ext_bin"
      done
    else
      echo "    [DRY-RUN] team-watcher, reflow-agent-pane, agent-monitor -> ~/bin/"
    fi
  fi

  # --- memory (opt-in) ---
  if $WITH_MEMORY && [[ -d "$SCRIPT_DIR/extensions/memory" ]]; then
    echo "  memory (cc-mem, memory-guard, tproj-mem-json)"
    if ! $DRY_RUN; then
      cp "$SCRIPT_DIR/extensions/memory/cc-mem" ~/bin/
      cp "$SCRIPT_DIR/extensions/memory/memory-guard" ~/bin/
      cp "$SCRIPT_DIR/extensions/memory/tproj-mem-json" ~/bin/
      chmod +x ~/bin/cc-mem ~/bin/memory-guard ~/bin/tproj-mem-json

      # Install launchd plist for memory-guard
      if [[ -f "$SCRIPT_DIR/extensions/memory/launchd/com.tproj.memory-guard.plist.template" ]]; then
        PLIST_DIR="$HOME/Library/LaunchAgents"
        PLIST_FILE="$PLIST_DIR/com.tproj.memory-guard.plist"
        mkdir -p "$PLIST_DIR"
        sed "s|__HOME__|$HOME|g" "$SCRIPT_DIR/extensions/memory/launchd/com.tproj.memory-guard.plist.template" > "$PLIST_FILE"
        launchctl bootout "gui/$(id -u)/com.tproj.memory-guard" 2>/dev/null || true
        launchctl bootstrap "gui/$(id -u)" "$PLIST_FILE" 2>/dev/null || true
        echo "    memory-guard launchd daemon installed"
      fi
    else
      echo "    [DRY-RUN] cc-mem, memory-guard, tproj-mem-json -> ~/bin/"
      echo "    [DRY-RUN] memory-guard launchd plist -> ~/Library/LaunchAgents/"
    fi
  elif ! $WITH_MEMORY && [[ -d "$SCRIPT_DIR/extensions/memory" ]]; then
    echo "  memory (skipped -- use --with-memory or --all to install)"
  fi
fi

# ========== 7. Done ==========

echo ""
if $DRY_RUN; then
  echo "Dry run complete (no changes made)."
  echo ""
  echo "Run for real:  ./install.sh"
else
  echo "Installation complete!"
fi

echo ""
echo "What was installed:"
echo "   ~/bin/            core scripts"
echo "   ~/.tmux.conf      tmux config (previous backed up)"
echo "   ~/.config/yazi/   yazi config (previous backed up)"
if ! $CORE_ONLY; then
  echo "   ~/bin/            extensions (messaging, persona, model-role-router, agent-teams)"
  $WITH_MEMORY && echo "   ~/bin/            memory extension (cc-mem, memory-guard)"
fi
echo ""
echo "Next steps:"
echo "   tproj init                     interactive setup wizard"
echo "   tproj --check                  verify your environment"
echo "   tproj                          launch workspace"
if ! $CORE_ONLY; then
  echo ""
  echo "Optional environment variables (add to your shell profile):"
  echo '   export TPROJ_LABEL_HOOK=cc-persona          # persona labels on pane titles'
  echo '   export TPROJ_AFTER_LAYOUT_HOOK=tproj-pane-bg # AI-generated pane backgrounds'
fi
