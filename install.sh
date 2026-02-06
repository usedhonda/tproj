#!/bin/bash
set -euo pipefail

# tproj インストーラ
# 使い方: ./install.sh [-h] [-n] [-y]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ========== オプション ==========

DRY_RUN=false
AUTO_YES=false

usage() {
  cat << 'EOF'
tproj インストーラ

使い方: ./install.sh [OPTIONS]

オプション:
  -h, --help     このヘルプを表示
  -n, --dry-run  実際の変更を行わずに表示
  -y, --yes      確認なしで自動インストール

例:
  ./install.sh           # 通常インストール
  ./install.sh -n        # ドライラン（変更なし）
  ./install.sh -y        # 確認なしで自動インストール
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
    *)
      echo "❌ 不明なオプション: $1"
      echo "   ヘルプ: ./install.sh -h"
      exit 1
      ;;
  esac
done

# ========== ヘルパー関数 ==========

# ドライラン対応のコマンド実行
run_cmd() {
  if $DRY_RUN; then
    echo "[DRY-RUN] $*"
  else
    "$@"
  fi
}

# Y/n 確認（-y で自動Yes）
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

backup_if_exists() {
  local file=$1
  if [[ -f "$file" && ! -L "$file" ]]; then
    local backup="${file}.bak.$(date +%Y%m%d_%H%M%S)"
    if $DRY_RUN; then
      echo "[DRY-RUN] 📋 バックアップ: $file -> $backup"
    else
      cp "$file" "$backup"
      echo "  📋 バックアップ: $backup"
    fi
  fi
}

# ========== 1. 依存関係チェック ==========

echo "🔍 依存関係を確認中..."

# brew でインストール可能なツール
BREW_DEPS=(npm:node git tmux yazi bat)
# npm でインストールするツール
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

# ========== 2. 不足ツールのインストール ==========

if [[ ${#MISSING_BREW[@]} -gt 0 ]]; then
  echo ""
  echo "❌ 以下のツールがありません: ${MISSING_BREW[*]}"

  if command -v brew &> /dev/null; then
    if confirm "🍺 brewでインストールしますか？"; then
      for pkg in "${MISSING_BREW[@]}"; do
        echo "📦 brew install $pkg"
        if ! $DRY_RUN; then
          brew install "$pkg"
        else
          echo "[DRY-RUN] brew install $pkg"
        fi
      done
    else
      echo ""
      echo "手動でインストールしてください:"
      for pkg in "${MISSING_BREW[@]}"; do
        echo "  brew install $pkg"
      done
      exit 1
    fi
  else
    echo ""
    echo "⚠️  Homebrewがインストールされていません"
    echo "   https://brew.sh を参照してインストール後、再実行してください"
    echo ""
    echo "   または手動でインストール:"
    for pkg in "${MISSING_BREW[@]}"; do
      echo "   • $pkg"
    done
    exit 1
  fi
fi

if [[ ${#MISSING_NPM[@]} -gt 0 ]]; then
  echo ""
  echo "❌ 以下のnpmパッケージがありません:"
  for pkg in "${MISSING_NPM[@]}"; do
    echo "   • $pkg"
  done

  if command -v npm &> /dev/null; then
    if confirm "📦 npmでグローバルインストールしますか？"; then
      for pkg in "${MISSING_NPM[@]}"; do
        echo "📦 npm install -g $pkg"
        if ! $DRY_RUN; then
          npm install -g "$pkg"
        else
          echo "[DRY-RUN] npm install -g $pkg"
        fi
      done
    else
      echo ""
      echo "手動でインストールしてください:"
      for pkg in "${MISSING_NPM[@]}"; do
        echo "  npm install -g $pkg"
      done
      exit 1
    fi
  else
    echo ""
    echo "⚠️  npmがありません。先にnpmをインストールしてください"
    exit 1
  fi
fi

echo ""
if $DRY_RUN; then
  echo "🔍 tproj インストール (ドライラン)"
else
  echo "🚀 tproj インストール開始"
fi

# ========== 3. Terminfo セットアップ ==========

if ! infocmp xterm-ghostty &>/dev/null; then
  if $DRY_RUN; then
    echo "[DRY-RUN] 📦 xterm-ghostty terminfo -> ~/.terminfo/"
  else
    echo "📦 xterm-ghostty terminfo -> ~/.terminfo/"
    tic -x "$SCRIPT_DIR/config/terminfo/xterm-ghostty.terminfo"
  fi
else
  echo "✅ xterm-ghostty terminfo (already installed)"
fi

# ========== 4. バックアップ & コピー ==========

# 4.1 tproj スクリプト
if $DRY_RUN; then
  echo "[DRY-RUN] 📦 tproj -> ~/bin/"
else
  echo "📦 tproj -> ~/bin/"
  mkdir -p ~/bin
  cp "$SCRIPT_DIR/bin/tproj" ~/bin/tproj
  chmod +x ~/bin/tproj
fi

# 4.2 tmux 設定
backup_if_exists ~/.tmux.conf
if $DRY_RUN; then
  echo "[DRY-RUN] 📦 tmux.conf -> ~/.tmux.conf"
else
  echo "📦 tmux.conf -> ~/.tmux.conf"
  cp "$SCRIPT_DIR/config/tmux/tmux.conf" ~/.tmux.conf
fi

# 4.3 yazi 設定
if $DRY_RUN; then
  echo "[DRY-RUN] 📦 yazi設定 -> ~/.config/yazi/"
else
  echo "📦 yazi設定 -> ~/.config/yazi/"
  mkdir -p ~/.config/yazi/plugins
fi
backup_if_exists ~/.config/yazi/yazi.toml
backup_if_exists ~/.config/yazi/keymap.toml
if ! $DRY_RUN; then
  cp "$SCRIPT_DIR/config/yazi/yazi.toml" ~/.config/yazi/
  cp "$SCRIPT_DIR/config/yazi/keymap.toml" ~/.config/yazi/
  cp -r "$SCRIPT_DIR/config/yazi/plugins/"* ~/.config/yazi/plugins/
fi

# 4.4 yaziパッケージ（piperプラグイン）
if command -v ya &> /dev/null; then
  if $DRY_RUN; then
    echo "[DRY-RUN] 📦 yazi plugins (ya pack)"
  else
    echo "📦 yazi plugins (ya pack)"
    (cd ~/.config/yazi && ya pack -i 2>/dev/null || true)
  fi
fi

# 4.5 Claude Code カスタムコマンド
if $DRY_RUN; then
  echo "[DRY-RUN] 📦 Claude Code commands -> ~/.claude/commands/"
else
  echo "📦 Claude Code commands -> ~/.claude/commands/"
  mkdir -p ~/.claude/commands
  if ls "$SCRIPT_DIR/config/claude/commands/"*.md &>/dev/null; then
    cp "$SCRIPT_DIR/config/claude/commands/"*.md ~/.claude/commands/
  fi
fi

# 4.6 Claude Code スキル
if $DRY_RUN; then
  echo "[DRY-RUN] 📦 Claude Code skills -> ~/.claude/skills/"
else
  echo "📦 Claude Code skills -> ~/.claude/skills/"
  mkdir -p ~/.claude/skills
  cp -r "$SCRIPT_DIR/config/claude/skills/"* ~/.claude/skills/
fi

# ========== 5. PATH自動設定 ==========

if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
  echo ""
  echo "⚠️  ~/bin がPATHに含まれていません"

  SHELL_RC=""
  if [[ -f ~/.zshrc ]]; then
    SHELL_RC=~/.zshrc
  elif [[ -f ~/.bashrc ]]; then
    SHELL_RC=~/.bashrc
  fi

  if [[ -n "$SHELL_RC" ]]; then
    if confirm "📝 $SHELL_RC に PATH設定を追加しますか？"; then
      PATH_LINE='export PATH="$HOME/bin:$PATH"'
      if $DRY_RUN; then
        echo "[DRY-RUN] 以下を $SHELL_RC に追加:"
        echo "   $PATH_LINE"
      else
        echo "" >> "$SHELL_RC"
        echo "# Added by tproj installer" >> "$SHELL_RC"
        echo "$PATH_LINE" >> "$SHELL_RC"
        echo "✅ $SHELL_RC にPATH設定を追加しました"
        echo "   反映するには: source $SHELL_RC"
      fi
    else
      echo "   以下を手動で追加してください:"
      echo '   export PATH="$HOME/bin:$PATH"'
    fi
  else
    echo "   以下を ~/.zshrc または ~/.bashrc に追加してください:"
    echo '   export PATH="$HOME/bin:$PATH"'
  fi
fi

# ========== 6. 完了メッセージ ==========

echo ""
if $DRY_RUN; then
  echo "✅ ドライラン完了（実際の変更はありません）"
  echo ""
  echo "実行するには: ./install.sh"
else
  echo "✅ インストール完了!"
fi

echo ""
echo "📍 インストール先:"
echo "   ~/bin/tproj"
echo "   ~/.tmux.conf"
echo "   ~/.config/yazi/"
echo "   ~/.claude/commands/"
echo "   ~/.claude/skills/"
echo ""
echo "💡 使い方: cd <project> && tproj"
