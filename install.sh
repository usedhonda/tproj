#!/bin/bash
set -euo pipefail

# tproj インストーラ
# 使い方: ./install.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 tproj インストール開始"

# 1. tproj スクリプト
echo "📦 tproj → ~/bin/"
mkdir -p ~/bin
cp "$SCRIPT_DIR/bin/tproj" ~/bin/tproj
chmod +x ~/bin/tproj

# 2. tmux 設定
echo "📦 tmux.conf → ~/.tmux.conf"
cp "$SCRIPT_DIR/config/tmux/tmux.conf" ~/.tmux.conf

# 3. yazi 設定
echo "📦 yazi設定 → ~/.config/yazi/"
mkdir -p ~/.config/yazi/plugins
cp "$SCRIPT_DIR/config/yazi/yazi.toml" ~/.config/yazi/
cp "$SCRIPT_DIR/config/yazi/keymap.toml" ~/.config/yazi/
cp -r "$SCRIPT_DIR/config/yazi/plugins/open-finder.yazi" ~/.config/yazi/plugins/

# 4. yaziパッケージ（piperプラグイン）
if command -v ya &> /dev/null; then
    echo "📦 yazi plugins (ya pack)"
    (cd ~/.config/yazi && ya pack -i 2>/dev/null || true)
fi

echo ""
echo "✅ インストール完了！"
echo ""
echo "📍 インストール先:"
echo "   ~/bin/tproj"
echo "   ~/.tmux.conf"
echo "   ~/.config/yazi/"
echo ""
echo "💡 使い方: cd <project> && tproj"
