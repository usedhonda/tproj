#!/bin/bash
set -euo pipefail

# tproj インストーラ
# 使い方: ./install.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ========== ヘルパー関数 ==========

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
    cp "$file" "$backup"
    echo "  📋 バックアップ: $backup"
  fi
}

# ========== 1. 依存関係チェック ==========

echo "🔍 依存関係を確認中..."
MISSING=()

check_command npm "npm" || MISSING+=("npm")
check_command git "git" || MISSING+=("git")
check_command tmux "tmux" || MISSING+=("tmux")
check_command yazi "yazi" || MISSING+=("yazi")
check_command bat "bat" || MISSING+=("bat")
check_command claude "Claude Code" || MISSING+=("claude")
check_command codex "Codex" || MISSING+=("codex")

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo ""
  echo "❌ 以下のツールがインストールされていません:"
  for dep in "${MISSING[@]}"; do
    case $dep in
      npm)    echo "   • npm: brew install node" ;;
      git)    echo "   • git: brew install git" ;;
      tmux)   echo "   • tmux: brew install tmux" ;;
      yazi)   echo "   • yazi: brew install yazi" ;;
      bat)    echo "   • bat: brew install bat" ;;
      claude) echo "   • Claude Code: npm install -g @anthropic-ai/claude-code" ;;
      codex)  echo "   • Codex: npm install -g @openai/codex" ;;
    esac
  done
  echo ""
  echo "上記をインストール後、再度 ./install.sh を実行してください"
  exit 1
fi

echo ""
echo "🚀 tproj インストール開始"

# ========== 2. バックアップ & コピー ==========

# 2.1 tproj スクリプト
echo "📦 tproj → ~/bin/"
mkdir -p ~/bin
cp "$SCRIPT_DIR/bin/tproj" ~/bin/tproj
chmod +x ~/bin/tproj

# 2.2 tmux 設定
echo "📦 tmux.conf → ~/.tmux.conf"
backup_if_exists ~/.tmux.conf
cp "$SCRIPT_DIR/config/tmux/tmux.conf" ~/.tmux.conf

# 2.3 yazi 設定
echo "📦 yazi設定 → ~/.config/yazi/"
mkdir -p ~/.config/yazi/plugins
backup_if_exists ~/.config/yazi/yazi.toml
backup_if_exists ~/.config/yazi/keymap.toml
cp "$SCRIPT_DIR/config/yazi/yazi.toml" ~/.config/yazi/
cp "$SCRIPT_DIR/config/yazi/keymap.toml" ~/.config/yazi/
cp -r "$SCRIPT_DIR/config/yazi/plugins/"* ~/.config/yazi/plugins/

# 2.4 yaziパッケージ（piperプラグイン）
if command -v ya &> /dev/null; then
    echo "📦 yazi plugins (ya pack)"
    (cd ~/.config/yazi && ya pack -i 2>/dev/null || true)
fi

# 2.5 Claude Code カスタムコマンド
echo "📦 Claude Code commands → ~/.claude/commands/"
mkdir -p ~/.claude/commands
if ls "$SCRIPT_DIR/config/claude/commands/"*.md &>/dev/null; then
  cp "$SCRIPT_DIR/config/claude/commands/"*.md ~/.claude/commands/
fi

# 2.6 Claude Code スキル
echo "📦 Claude Code skills → ~/.claude/skills/"
mkdir -p ~/.claude/skills
cp -r "$SCRIPT_DIR/config/claude/skills/"* ~/.claude/skills/

# ========== 3. PATH確認 ==========

if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
  echo ""
  echo "⚠️  ~/bin がPATHに含まれていません"
  echo "   以下を ~/.zshrc に追加してください:"
  echo '   export PATH="$HOME/bin:$PATH"'
fi

# ========== 4. 完了メッセージ ==========

echo ""
echo "✅ インストール完了!"
echo ""
echo "📍 インストール先:"
echo "   ~/bin/tproj"
echo "   ~/.tmux.conf"
echo "   ~/.config/yazi/"
echo "   ~/.claude/commands/"
echo "   ~/.claude/skills/"
echo ""
echo "💡 使い方: cd <project> && tproj"
