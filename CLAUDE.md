# tproj - tmux開発環境

tmuxベースの開発環境セットアップを管理するプロジェクト。

## 構成

```
tproj/
├── install.sh                    # インストーラ
├── bin/tproj                     # tmuxセッション起動スクリプト
├── config/
│   ├── tmux/tmux.conf           # tmux設定
│   ├── yazi/                    # yaziファイルマネージャー設定
│   │   ├── yazi.toml
│   │   ├── keymap.toml
│   │   └── plugins/open-finder.yazi/
│   └── claude/commands/         # Claude Codeカスタムコマンド
│       └── ask-codex.md
└── docs/
```

## tproj コマンド

```bash
tproj      # プロジェクトディレクトリでtmuxセッション起動（自動アップデート）
tproj -n   # アップデートなしで起動（オフライン用）
```

### レイアウト

```
┌─────────────────┬─────────────┐
│                 │   codex 30% │
│     claude      ├─────────────┤
│                 │   yazi  70% │
└─────────────────┴─────────────┘
         dev window

┌─────────────────────────────────┐
│            git                  │
└─────────────────────────────────┘
         git window
```

## ask-codex コマンド

Claude Code内で `/ask-codex` を実行すると、Codexペインに質問を送信。

- tprojレイアウト固定でペイン検出（dev.2=Codex）
- Codex未起動時は自動起動
- 引数なしなら直近の作業から自動で質問を構築

## インストール

```bash
./install.sh
```

## 設定ファイルの変更

1. このリポジトリ内のファイルを編集
2. `./install.sh` で再インストール

## 主な設定

### tmux (`config/tmux/tmux.conf`)
- Prefix: `C-a`
- 分割: `|`（左右）、`-`（上下）
- マウス操作有効
- Ghosttyタブ連携（🔔通知）

### yazi (`config/yazi/`)
- j/k: 上下移動（反転）
- Enter: ディレクトリ→Finder、ファイル→オープン
- batによるシンタックスハイライトプレビュー
- 隠しファイル表示デフォルトON
