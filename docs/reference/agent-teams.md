# Claude Code Agent Teams 完全リファレンス

> 調査日: 2026-02-07 / Claude Code v2.1.33 / Opus 4.6 同時発表（2026/2/5）

---

## 1. Agent Teams 概要

### 1.1 何ができるか

Agent Teams は複数の Claude Code インスタンスを「チーム」として協調させる実験的機能。
1つの Claude Code セッション（リーダー）が複数の独立した Claude Code セッション（テメイト）を
spawn し、共有タスクリストとメッセージングで協調作業を行う。

**ユースケース例:**
- PR レビュー: セキュリティ担当、パフォーマンス担当、テスト担当を spawn
- 新機能実装: フロントエンド担当、バックエンド担当、DB担当を並列実行
- バグ調査: 複数の仮説を別々の teammate が同時に検証
- リファクタリング: 各モジュールを別 teammate が担当

### 1.2 アーキテクチャ

```
┌──────────────────────────────────────────┐
│              Team Lead                    │
│  (メインの Claude Code セッション)         │
│                                           │
│  ・チーム作成 (TeamCreate)                 │
│  ・タスク作成・割り当て (TaskCreate/Update) │
│  ・teammate spawn (Task tool + team_name) │
│  ・メッセージ送受信 (SendMessage)          │
│  ・シャットダウン指示                      │
└───────┬──────────┬──────────┬─────────────┘
        │          │          │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐
   │ mate-1 │ │ mate-2 │ │ mate-3 │
   │        │ │        │ │        │
   │独自の   │ │独自の   │ │独自の   │
   │コンテキスト│ │コンテキスト│ │コンテキスト│
   │ウィンドウ │ │ウィンドウ │ │ウィンドウ │
   └────────┘ └────────┘ └────────┘
        ↕          ↕          ↕
   ┌──────────────────────────────┐
   │    Shared Task List          │
   │  ~/.claude/tasks/{team}/     │
   └──────────────────────────────┘
```

### 1.3 subagent (Task tool) との違い

| 特性 | subagent | Teammate |
|------|----------|----------|
| **独立性** | 親セッション内で実行、結果を返して終了 | 完全に独立したプロセス |
| **コンテキスト** | 親の会話履歴にアクセス可能 | 独自のコンテキストウィンドウ（親の履歴なし） |
| **通信** | 結果を1回返すのみ（単方向） | 双方向メッセージング、peer-to-peer 可能 |
| **持続性** | タスク完了で終了 | チーム解散まで存続、複数タスクを処理 |
| **コスト** | 親のコンテキスト内で動作 | 各自フルコンテキスト消費（N人 ≒ N倍コスト） |
| **協調** | なし（独立実行） | 共有タスクリスト + メッセージで協調 |
| **ツール** | agent type に依存（Explore は read-only 等） | フル権限（リーダーと同じ permission mode） |

**使い分けの目安:**
- 単発の調査・検索 -> subagent（安い、速い）
- 並列実装・長時間タスク -> teammate（高い、協調可能）

---

## 2. 有効化と設定

### 2.1 有効化

実験的機能のため、明示的な有効化が必要。

```json
// ~/.claude/settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

または環境変数:
```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

### 2.2 表示モード（teammateMode）

teammate の表示方法を制御する最重要設定。

| モード | 動作 | 要件 |
|--------|------|------|
| `"auto"` | tmux 内なら split panes、それ以外は in-process | **デフォルト** |
| `"in-process"` | メインターミナル内で全 teammate を管理 | なし |
| `"tmux"` | 各 teammate に tmux ペインを割り当て | tmux または iTerm2 |

```json
// ~/.claude/settings.json
{
  "teammateMode": "tmux"
}
```

> **tproj での運用:** `tmux` モードを使用し、`reflow-agent-pane` フックで
> Agent Teams が作成したペインを Codex の上に即時再配置する。

CLI オーバーライド:
```bash
claude --teammate-mode in-process
```

### 2.3 auto モードの判定フロー

```
teammateMode: "auto"
├── TMUX 環境変数が存在？
│   └── Yes -> tmux split panes を使用
├── iTerm2 が検出された？
│   └── Yes -> iTerm2 split を使用
├── 外部 tmux が利用可能？
│   └── Yes -> tmux を起動して使用
└── すべて No -> in-process にフォールバック
```

---

## 3. 表示モード詳細

### 3.1 In-Process モード

全 teammate がメインの Claude Code ターミナル内で動作。

**操作方法:**
| キー | 動作 |
|------|------|
| `Shift+Up/Down` | teammate を選択 |
| `Enter` | 選択した teammate のセッションを表示 |
| `Escape` | teammate を中断 |
| `Ctrl+T` | タスクリストの表示/非表示 |

**メリット:**
- どのターミナルでも動作（VS Code, Ghostty, SSH 等）
- 既存のターミナルレイアウトに影響なし
- 設定不要

**デメリット:**
- 1つのペインで全 teammate を切り替えるため、同時表示不可
- UI が若干狭い

### 3.2 Split Panes モード（tmux）

各 teammate が独自の tmux ペインを取得。

**動作:**
1. Agent Teams が `tmux split-window` を実行
2. 新しいペインに teammate の Claude Code セッションを起動
3. 各ペインをクリックして直接操作可能

**メリット:**
- 複数 teammate の出力を同時に確認できる
- 各 teammate に直接入力可能

**デメリット:**
- **既存の tmux レイアウトを破壊する**
- tmux/iTerm2 が必須
- 既知バグあり（#23615, #23513）

**非対応ターミナル:**
- VS Code 統合ターミナル
- Windows Terminal
- Ghostty

### 3.3 Split Panes モード（iTerm2）

各 teammate が iTerm2 のウィンドウ/タブを取得。
iTerm2 の Python API を有効化する必要がある。

---

## 4. チームの作成と運用

### 4.1 チーム作成

自然言語で指示するだけ:
```
3人のチームを作って、このPRをレビューして:
- セキュリティ担当
- パフォーマンス担当
- テスト担当
```

内部的には `TeamCreate` ツールが呼ばれる:
```json
{
  "team_name": "pr-review",
  "description": "PR #142 のレビュー"
}
```

### 4.2 teammate の spawn

`Task` ツールに `team_name` と `name` を指定:
```json
{
  "team_name": "pr-review",
  "name": "security-reviewer",
  "subagent_type": "general-purpose",
  "prompt": "セキュリティの観点からコードレビューして...",
  "run_in_background": true
}
```

**利用可能な agent type:**
| タイプ | ツール | 用途 |
|--------|--------|------|
| `general-purpose` | 全ツール（Edit, Write, Bash 等） | 実装タスク |
| `Explore` | Read-only（Glob, Grep, Read 等） | 調査・検索 |
| `Plan` | Read-only + 計画設計 | アーキテクチャ設計 |
| `Bash` | Bash のみ | コマンド実行特化 |

### 4.3 タスク管理

共有タスクリストで作業を管理:

```
TaskCreate -> pending
TaskUpdate(status: "in_progress", owner: "mate-1") -> 作業中
TaskUpdate(status: "completed") -> 完了
```

**依存関係:**
```json
// タスク2はタスク1の完了を待つ
{ "taskId": "2", "addBlockedBy": ["1"] }
```

タスク1が completed になると、タスク2が自動的に unblock される。
ファイルロックでレースコンディションを防止。

### 4.4 メッセージング

| タイプ | 説明 | コスト |
|--------|------|--------|
| `message` | 特定の teammate に DM | 低 |
| `broadcast` | 全 teammate に送信 | N人 = N倍（非推奨） |
| `shutdown_request` | 終了を要求 | - |

**重要:** broadcast は N 人分のメッセージを送信するため高コスト。通常は `message` を使用。

### 4.5 チームのライフサイクル

```
1. TeamCreate          -> チームとタスクリスト作成
2. Task(team_name=...) -> teammate を spawn
3. TaskCreate          -> タスクを作成・割り当て
4. 作業中...            -> teammate が自律的にタスク処理
5. SendMessage(shutdown_request) -> 終了を要求
6. TeamDelete          -> チームリソース削除
```

### 4.6 Delegate モード

リーダーを「調整のみ」に制限するモード。`Shift+Tab` で有効化。
リーダーはファイル編集不可になり、teammate に作業を委託するのみ。

### 4.7 Plan Approval

teammate に計画承認を要求できる。
teammate が `ExitPlanMode` を呼ぶと、リーダーに承認リクエストが届く。
リーダーが承認すると teammate は実装を開始、拒否するとフィードバック付きで差し戻し。

---

## 5. ファイル構造

### 5.1 チーム設定

```
~/.claude/teams/{team-name}/
├── config.json          # チームメタデータ、メンバーリスト
└── inboxes/
    ├── lead.json        # リーダーのメッセージボックス
    ├── mate-1.json      # teammate-1 のメッセージボックス
    └── mate-2.json      # teammate-2 のメッセージボックス
```

**config.json の構造:**
```json
{
  "members": [
    {
      "name": "security-reviewer",
      "agentId": "abc123",
      "agentType": "general-purpose"
    }
  ]
}
```

### 5.2 タスクリスト

```
~/.claude/tasks/{team-name}/
├── 1.json     # タスク1
├── 2.json     # タスク2
└── 3.json     # タスク3
```

### 5.3 環境変数（teammate に自動注入）

| 変数 | 説明 |
|------|------|
| `CLAUDE_CODE_TEAM_NAME` | チーム名 |
| `CLAUDE_CODE_AGENT_ID` | エージェントID |
| `CLAUDE_CODE_AGENT_NAME` | エージェント名 |
| `CLAUDE_CODE_PLAN_MODE_REQUIRED` | 計画承認が必要か |

---

## 6. Hooks（v2.1.33 で追加）

### 6.1 TeammateIdle

teammate がアイドル状態になったとき発火。

```json
{
  "hooks": {
    "TeammateIdle": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/check-teammate-idle.sh"
          }
        ]
      }
    ]
  }
}
```

- exit code 2: teammate に stderr をフィードバックとして送り、作業継続させる
- matcher 非対応（全発火）
- 入力: `teammate_name`, `team_name`

### 6.2 TaskCompleted

タスクが完了マークされるとき発火。

```bash
#!/bin/bash
INPUT=$(cat)
TASK_SUBJECT=$(echo "$INPUT" | jq -r '.task_subject')

# テストが通らなければ完了を拒否
if ! npm test 2>&1; then
  echo "テスト未通過。修正してから完了にしてください: $TASK_SUBJECT" >&2
  exit 2  # 完了を阻止
fi
exit 0
```

- exit code 2: 完了を阻止し、stderr をフィードバック
- 入力: `task_id`, `task_subject`, `task_description`, `teammate_name`, `team_name`

---

## 7. コストと制限

### 7.1 トークンコスト

**重要:** 各 teammate は独立した Claude Code セッション = 独自のコンテキストウィンドウを消費。

```
teammate 数 x フルコンテキスト = 総コスト
例: 5 teammate = 約5倍のトークン消費
```

**最適化:**
- 3-5 teammate が実用的な上限
- 共通コンテキストは CLAUDE.md に入れる（spawn prompt より効率的）
- 調査だけなら subagent の方が安い
- `/cost` コマンドでモニタリング

### 7.2 既知の制限事項

| 制限 | 影響 |
|------|------|
| セッション復元不可 | `/resume`, `/rewind` で in-process teammate は復元されない |
| タスクステータスの遅延 | teammate が完了マークを忘れることがある -> 依存タスクがブロック |
| シャットダウンが遅い | 現在のリクエスト完了を待つ |
| 1チーム/セッション | リーダーは同時に1チームのみ管理可能 |
| ネストチーム不可 | teammate は自分のチームを作れない |
| リーダー固定 | リーダーの交代・昇格不可 |
| 権限は spawn 時に決定 | リーダーの permission mode を全 teammate が継承 |
| Split Panes 制限 | tmux/iTerm2 のみ。Ghostty, VS Code, Windows Terminal 不可 |

### 7.3 既知のバグ（2026/2/7 時点）

| Issue | 内容 |
|-------|------|
| **#23615** | tmux split panes が既存レイアウトを破壊。4+ agent でコマンド文字化け |
| **#23572** | `teammateMode: "tmux"` が iTerm2 検出失敗時に無言で in-process にフォールバック |
| **#23513** | tmux send-keys のレースコンディションで teammate が起動しない |
| **#23456** | tmux ベースの teammate が初期プロンプトを受け取らない |
| **#23437** | in-process の CLI フラグが tmux team members に無視される |

---

## 8. 実践的な使い方

### 8.1 コードレビュー（推奨の入門ユースケース）

```
3人のチームを作って、src/ のコードレビューをして:
- セキュリティの観点
- パフォーマンスの観点
- テストカバレッジの観点
それぞれの結果をまとめて報告して。
```

### 8.2 並列実装

```
フロントエンドとバックエンドを並列で実装して:
- frontend: src/components/UserProfile.tsx を実装
- backend: src/api/users.ts を実装
ファイルの競合がないように注意して。
```

### 8.3 バグ調査（Anthropic 推奨パターン）

```
このバグについて5つの仮説を持つチームを作って:
- 仮説A: 認証トークンの期限切れ
- 仮説B: データベース接続プール枯渇
- 仮説C: ...
各自が自分の仮説を検証し、お互いの発見を議論すること。
```

### 8.4 ベストプラクティス

1. **十分なコンテキストを prompt に含める** - teammate は親の会話履歴を持たない
2. **ファイル競合を避ける** - 各 teammate が別ファイルを担当するよう設計
3. **5-6 タスク/teammate** - 生産性が高い粒度
4. **調査->実装の順** - まず Explore agent で調査、結果を元に実装 teammate を spawn
5. **放置しすぎない** - 定期的にタスクリストと進捗を確認
6. **CLAUDE.md を活用** - 共通コンテキストは spawn prompt より CLAUDE.md に

---

## 9. Anthropic の事例: C コンパイラ構築

16 個の並列 Claude インスタンスが Docker コンテナで C コンパイラを構築:
- git リポジトリ経由で協調（inbox メッセージングではなく）
- `current_tasks/` ディレクトリにファイルを書いてタスクを claim
- 20億入力トークン、1.4億出力トークン、約$20,000（2週間）
- 10万行の Rust コードベースを生成
- オーケストレーションエージェントなし（git 操作のみで協調）
