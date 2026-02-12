# tproj - tmux開発環境

tmuxベースの開発環境セットアップを管理するプロジェクト。

## 構成

```
tproj/
├── install.sh                    # インストーラ
├── bin/
│   ├── tproj                    # tmuxセッション起動スクリプト
│   ├── agent-monitor            # Agent Teams 個別エージェント状態表示
│   ├── team-watcher             # Agent Teams フックベースペイン管理デーモン
│   └── reflow-agent-pane        # tmux after-split-window フックスクリプト
├── config/
│   ├── tmux/tmux.conf           # tmux設定
│   ├── yazi/                    # yaziファイルマネージャー設定
│   │   ├── yazi.toml
│   │   ├── keymap.toml
│   │   └── plugins/
│   │       ├── open-finder.yazi/
│   │       ├── open-terminal.yazi/
│   │       └── copy-path.yazi/
│   └── claude/skills/           # Claude Codeスキル
│       └── codex/               # Codex連携スキル
└── docs/
    └── reference/
        └── agent-teams.md       # Agent Teams 完全リファレンス
```

## tproj コマンド

```bash
# 単一プロジェクトモード
tproj      # プロジェクトディレクトリでtmuxセッション起動（自動アップデート）
tproj -n   # アップデートなしで起動（オフライン用）
tproj -s   # 単一モード強制（workspace.yaml を無視）
tproj -r macmini  # SSH リモート接続（単一モードのみ）

# マルチプロジェクトモード
tproj              # ~/.config/tproj/workspace.yaml があれば自動的にマルチモード
tproj --add        # 現在の列を複製して右に追加
tproj --add sl     # エイリアスで workspace.yaml のプロジェクトを追加
tproj --check      # workspace.yaml のプロジェクト一覧・エイリアス・有効状態を表示
```

### 動作モード

tproj は2つのモードで動作します:

**単一プロジェクトモード（デフォルト）:**
- 現在のディレクトリを1つのプロジェクトとして起動
- セッション名: `<project-name>`
- 3ペインレイアウト（claude, codex, yazi）

**マルチプロジェクトモード（ワークスペース）:**
- `~/.config/tproj/workspace.yaml` が存在すると自動有効化
- 複数プロジェクトを縦列に並べて同時作業
- セッション名: `tproj-workspace`
- 各列に独立した Claude Code + Codex

### レイアウト

**単一プロジェクトモード:**

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

**マルチプロジェクトモード（ワークスペース）:**
```
3プロジェクトの例:
┌─────────┬─────────┬─────────┐
│ codex1  │ codex2  │ codex3  │
├─────────┼─────────┼─────────┤
│ claude1 │ claude2 │ claude3 │
│         │         │         │
└─────────┴─────────┴─────────┘
         dev window

yazi トグル後（列2のみ）:
┌─────────┬─────────┬─────────┐
│ codex1  │ yazi2   │ codex3  │
│         ├─────────┤         │
│         │ codex2  │         │
├─────────┼─────────┼─────────┤
│ claude1 │ claude2 │ claude3 │
└─────────┴─────────┴─────────┘
```

### ワークスペース設定

**設定ファイル:** `~/.config/tproj/workspace.yaml`

**簡易形式（ローカルプロジェクトのみ）:**
```yaml
projects:
  - /Users/username/projects/frontend
  - /Users/username/projects/backend
  - /Users/username/projects/tools
```

**詳細形式（ローカル + リモート、alias/enabled 対応）:**
```yaml
projects:
  - path: /Users/username/projects/tproj
    type: local
    alias: tproj              # tproj --add tproj で追加可能

  - path: /Users/username/projects/statusline
    alias: sl
    enabled: false            # 起動時スキップ、--add sl で追加可能

  - path: ~/projects/statusline
    type: remote
    host: macmini
    alias: openclaw
```

**フィールド:**
- `alias`: プロジェクト短縮名（省略時 = path の basename）。`tproj --add <alias>` で使用
- `enabled`: 起動時の有効/無効（省略時 = true）。false だと起動時スキップだが `--add` で追加可能

**セットアップ:**
```bash
mkdir -p ~/.config/tproj
cp config/workspace.yaml.example ~/.config/tproj/workspace.yaml
# workspace.yaml を編集してプロジェクトパスを設定
tproj  # マルチプロジェクトモードで起動
```

**機能:**
- 各列で独立した Claude Code + Codex セッション
- `Prefix + y` でアクティブな列の yazi をトグル
- リモートプロジェクト対応（SSH 経由）
- プロジェクト数は5個以下推奨

**制限:**
- リモートモード (`-r`) はマルチモードでは使用不可
- リモートプロジェクトには claude, codex, yazi が必要
```

## codex スキル

Claude Code内で `/codex` を実行すると、Codexペインと連携。

**モード:**
- **ask**（デフォルト）: `/codex`, `Codexに聞いて` - 質問・相談・レビュー
- **impl**: `/codex impl`, `Codexに任せて` - 実装タスク（完全自動）

**機能:**
- @roleタグでペイン検出（Agent Teams対応、ペイン番号に非依存）
- ワークスペースモード対応（アクティブな列の Codex を自動検出）
- リモートプロジェクト対応（SSH 経由でも動作）
- 引数なしなら直近の作業から自動で質問を構築
- impl モードは承認を自動で行う

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

**基本操作:**
- `j`/`k`: 上下移動（反転）
- `←`/`→`: 親/子ディレクトリ移動
- `Enter`: ディレクトリ→Finder、ファイル→オープン
- `y`: ファイル/ディレクトリをコピー（yank）
- `x`: ファイル/ディレクトリをカット
- `v`: ペースト
- `c`: ファイル内容をクリップボードにコピー
- `p`: ファイルパス（フルパス）をクリップボードにコピー
- `T`: ターミナルペインをトグル（開く/閉じる）
- `h`: ヘルプ表示
- `q`: 終了

**コマンドモードから抜ける:**
- `Esc`: 入力モードをキャンセル
- `Ctrl+C`: 強制中断
- `Ctrl+[`: Escの代替

**再起動:** `q` で終了後、`yazi` で再起動

**その他:**
- batによるシンタックスハイライトプレビュー
- 隠しファイル表示デフォルトON

## Agent Teams 対応

tproj は Claude Code Agent Teams と統合。詳細は `docs/reference/agent-teams.md` を参照。

### ペイン管理

各ペインに `@role` タグを設定し、ペイン番号に依存しない動的管理を実現:

**単一プロジェクトモード:**
- `@role=claude` - Claude Code メインペイン
- `@role=codex` - Codex ペイン
- `@role=yazi` - yazi ペイン
- `@role=agent-*` - Agent Teams のエージェントペイン（動的に追加/削除）

**マルチプロジェクトモード:**
- `@role=claude-p1`, `@role=claude-p2`, ... - 各列の Claude Code
- `@role=codex-p1`, `@role=codex-p2`, ... - 各列の Codex
- `@role=yazi-p1`, `@role=yazi-p2`, ... - 各列の yazi
- `@role=agent-p1-*`, `@role=agent-p2-*`, ... - 各列の Agent Teams
- `@column=1`, `@column=2`, ... - 列番号
- `@project=<path>` または `@project=ssh://<host>/<path>` - プロジェクト識別

### 動的ペインレイアウト（フックベース）

`teammateMode: "tmux"` で Agent Teams のペイン作成を受け入れ、
tmux `after-split-window` フックで即座に Codex の上に再配置する仕組み。

**フロー:**
1. `TeamCreate` hook -> `team-watcher` 起動
2. `team-watcher` が `after-split-window` フック + `TPROJ_AGENTS_ACTIVE` 環境変数を設定
3. Agent Teams が `split-window` 実行 -> フック発火
4. `reflow-agent-pane` が新ペインを Codex の上に `move-pane` + `@role=agent-pending` タグ
5. `team-watcher` ポーリング（3秒）で `config.json` の新メンバー検知 -> `agent-$name` にリネーム
6. Agent 終了 -> ペインが自然に閉じる（Claude プロセス終了 -> tmux がスペース回収）
7. 全 agent 消失 + config 削除 -> team-watcher 自身も終了、フック解除

**単一プロジェクトモード:**
```
初期状態:              agent spawn後:
┌────────┬────────┐   ┌────────┬────────┐
│        │ codex  │   │        │agent-1 │
│ claude ├────────┤   │ claude ├────────┤
│        │ yazi   │   │        │ codex  │
└────────┴────────┘   │        ├────────┤
                      │        │ yazi   │
                      └────────┴────────┘
```

**マルチプロジェクトモード:**
```
3列環境で列2から agent spawn:
┌─────────┬─────────┬─────────┐
│ codex1  │ codex2  │ codex3  │
├─────────┼─────────┼─────────┤
│ claude1 │ claude2 │ claude3 │
└─────────┴─────────┴─────────┘

       ↓ TeamCreate in column 2

┌─────────┬─────────┬─────────┐
│ codex1  │ agent-1 │ codex3  │
├─────────┼─────────┼─────────┤
│         │ codex2  │         │
│ claude1 ├─────────┤ claude3 │
│         │ claude2 │         │
└─────────┴─────────┴─────────┘
```

### teammateMode

`tmux` モードを使用。Agent Teams のペイン作成を受け入れた上で、
`reflow-agent-pane` フックで tproj レイアウトに即時再配置。
設定: `~/.claude/settings.json` の `teammateMode: "tmux"`
