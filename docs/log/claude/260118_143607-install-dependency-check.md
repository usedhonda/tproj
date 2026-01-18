# install.sh 依存関係チェック機能追加

## 日時
2026-01-18 14:36

## 作業内容
install.sh に依存関係チェックと自動バックアップ機能を追加

## 変更ファイル
- `install.sh:1-121` - 全面改修

## 追加機能

### 1. check_command() 関数 (11-21行)
- コマンド存在チェック
- ✅/❌ で視覚的に表示

### 2. backup_if_exists() 関数 (23-30行)
- 既存ファイルをタイムスタンプ付きでバックアップ
- シンボリックリンクは除外

### 3. 依存関係チェック (34-62行)
対象ツール:
- npm, git, tmux, yazi, bat, claude, codex

不足時の動作:
- インストール方法を表示
- exit 1 で停止

### 4. PATHチェック (102-107行)
- ~/bin がPATHに含まれていない場合に警告

## 動作確認
```
🔍 依存関係を確認中...
  ✅ npm
  ✅ git
  ✅ tmux
  ✅ yazi
  ✅ bat
  ✅ Claude Code
  ✅ Codex

🚀 tproj インストール開始
📦 tmux.conf → ~/.tmux.conf
  📋 バックアップ: /Users/usedhonda/.tmux.conf.bak.20260118_143556
```

バックアップファイルが正常に作成されることを確認。
