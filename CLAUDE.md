# tproj - tmux開発環境

tmuxベースの開発環境セットアップを管理するプロジェクト。

## 構成

```
tproj/
├── install.sh                    # インストーラ
├── bin/tproj                     # tmuxセッション起動スクリプト
├── config/
│   ├── tmux/tmux.conf           # tmux設定
│   └── yazi/                    # yaziファイルマネージャー設定
│       ├── yazi.toml
│       ├── keymap.toml
│       └── plugins/open-finder.yazi/
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
│                 │   codex     │
│     claude      ├─────────────┤
│                 │    yazi     │
└─────────────────┴─────────────┘
         dev window

┌─────────────────────────────────┐
│            git                  │
└─────────────────────────────────┘
         git window
```

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
