---
name: codex
description: |
  Codex連携スキル。2つのモードがある。
  モード1: ask（「Codexに聞いて」「/codex」）- 質問・相談・レビュー依頼
  モード2: impl（「Codexに任せて」「/codex impl」）- 実装タスク
argument-hint: <質問/タスク内容>
allowed-tools: [Bash, Read]
compression-anchors:
  - "tmuxセッション内でCodexペインに質問/タスクを送信"
  - "回答完了を自動検知して結果を取得"
  - "ask/impl 2モード対応"
---

# Codex連携スキル

## 概要

tprojセッション内で、Claude Code（@role=claude）からCodex（@role=codex）に質問またはタスクを送信する。

## モード

| モード | トリガー | 動作 | ログ先 |
|--------|----------|------|--------|
| ask | `/codex`, `/codex ask`, 「Codexに聞いて」「Codexに相談」「Codexにレビュー」 | 調査・分析・提案のみ（実装禁止） | docs/log/codex/ |
| impl | `/codex impl`, 「Codexに任せて」「Codexで実装」 | 指示されたタスクを実装 | docs/log/codex-impl/ |

**デフォルト**: ask モード（引数なし or モード指定なし）

## モード判定ロジック

```
1. $ARGUMENTS の先頭が "impl" → impl モード
2. トリガーワードに「任せて」「実装」含む → impl モード
3. それ以外 → ask モード（デフォルト）
```

## 使用条件

- tprojで起動したtmuxセッション内であること
- Codexペイン（@role=codex）が存在すること
- Codexが起動していること

## 自律使用の判断基準

CCは以下の場合に自律的にこのスキルを使用すべき：

1. **設計判断に迷った時** - 複数のアプローチがあり、どれが最適か不明
2. **セカンドオピニオンが欲しい時** - 自分の判断に自信がない
3. **プロジェクト固有の知識が必要な時** - Codexが詳しいはず
4. **リスクの高い変更を行う前** - 大きな影響がある変更
5. **ユーザーが「Codexに聞いて」「Codexに任せて」等と言った時**

## 質問/タスクの構築（必須）

$ARGUMENTS はユーザーからの問いかけ。これをそのままCodexに渡すのではなく、**あなた自身の言葉で**Codexに伝えよ。

### やるべきこと

1. ユーザーの意図を咀嚼
2. 必要なプロジェクト背景・直近の作業を選定
3. 自然な文章でCodexに話しかける質問/タスクを構築

### $ARGUMENTSが空の場合

直近の会話・作業から、Codexに相談すべき内容を自分で判断して構築せよ。

### 例

ユーザー: `/codex ロードマップを考えて`

構築する質問:
```
このプロジェクトはClaude Code用のstatuslineツール（Python）。
今後のロードマップについて意見がほしい。
私としてはパフォーマンス改善が必要だと思っている。どう思う？
```

## 実行

**重要**: 以下のスクリプト全体を**1回のBash呼び出し**で実行せよ。

### Step 1: モード判定

$ARGUMENTS を解析し、モードを決定:
- 先頭が "impl" → CODEX_MODE="impl"、ARGUMENTSから "impl" を除去
- それ以外 → CODEX_MODE="ask"

### Step 2: スクリプト実行

`YOUR_MESSAGE_HERE` を構築した質問/タスクに置き換えること。
`CODEX_MODE_HERE` を判定したモード（ask または impl）に置き換えること。

```bash
#!/bin/bash
set -euo pipefail

# === 設定 ===
MESSAGE_TO_CODEX="YOUR_MESSAGE_HERE"
CODEX_MODE="CODEX_MODE_HERE"  # ask または impl

# === trusted登録 ===
PROJECT_PATH=$(pwd)
CONFIG_FILE="$HOME/.codex/config.toml"
if [[ -f "$CONFIG_FILE" ]] && ! grep -q "\\[projects.\"$PROJECT_PATH\"\\]" "$CONFIG_FILE" 2>/dev/null; then
  echo "" >> "$CONFIG_FILE"
  echo "[projects.\"$PROJECT_PATH\"]" >> "$CONFIG_FILE"
  echo 'trust_level = "trusted"' >> "$CONFIG_FILE"
fi

# === ペイン検出（@roleタグベース、ワークスペース対応）===
SESSION=$(tmux display-message -p '#S')

if [[ "$SESSION" == "tproj-workspace" ]]; then
  # マルチプロジェクトモード: アクティブな列の Codex を検出
  # $TMUX_PANE は自ペインのID（フォーカス位置に非依存で確実）
  ACTIVE_PANE="${TMUX_PANE:-$(tmux display-message -p '#{pane_id}')}"
  ACTIVE_COLUMN=$(tmux display-message -t "$ACTIVE_PANE" -p '#{@column}')

  CODEX_PANE=$(tmux list-panes -t "$SESSION:dev" \
    -F "#{pane_id}:#{@role}" 2>/dev/null | grep ":codex-p${ACTIVE_COLUMN}$" | cut -d: -f1)
else
  # 単一プロジェクトモード
  CODEX_PANE=$(tmux list-panes -t "$SESSION:dev" \
    -F "#{pane_id}:#{@role}" 2>/dev/null | grep ":codex$" | cut -d: -f1)
fi

if [[ -z "$CODEX_PANE" ]]; then
  echo "エラー: Codexペイン(@role=codex)が見つかりません"
  echo "tprojで起動したセッション内で実行してください"
  exit 1
fi

# === Codex起動確認 ===
CURRENT_CMD=$(tmux display-message -t "$CODEX_PANE" -p '#{pane_current_command}')
PANE_CONTENT=$(tmux capture-pane -t "$CODEX_PANE" -p)

CODEX_RUNNING=false
[[ "$CURRENT_CMD" == "node" ]] && CODEX_RUNNING=true
RECENT_LINES=$(echo "$PANE_CONTENT" | tail -20)
echo "$RECENT_LINES" | grep -q "context left" && CODEX_RUNNING=true
echo "$RECENT_LINES" | grep -q "esc to interrupt" && CODEX_RUNNING=true

if [[ "$CODEX_RUNNING" == "false" ]]; then
  echo "エラー: Codexが起動していません"
  echo "Codexペイン(@role=codex)でcodexを起動してください"
  exit 1
fi

# === モード別ルール構築 ===
if [[ "$CODEX_MODE" == "impl" ]]; then
  LOG_DIR="docs/log/codex-impl"
  RULES="【実装ルール】
1. 指示されたタスクを実装せよ。
2. 変更前に影響範囲を説明すること。
3. 結果は $LOG_DIR にマークダウンで残すこと（連番: 001-xxxx.md）
4. 不明点があれば実装前に質問すること。"
else
  LOG_DIR="docs/log/codex"
  RULES="【重要ルール】
1. 実装は禁止。調査・分析・提案のみ行うこと。
2. 結果は $LOG_DIR にマークダウンで残すこと（連番: 001-xxxx.md）
3. 追加の質問があれば遠慮なく聞いてください。詳細を文章で回答します。"
fi

# === 質問/タスク送信 ===
QUESTION="$RULES

$MESSAGE_TO_CODEX"

# リテラルモード(-l)で送信し、改行をそのまま扱う
tmux send-keys -l -t "$CODEX_PANE" "$QUESTION"
sleep 0.5
tmux send-keys -t "$CODEX_PANE" Enter

# === 回答待機 ===
COMPLETED=false
PREV_OUTPUT=""
NO_CHANGE_COUNT=0
NO_CHANGE_THRESHOLD=30  # 0.3秒×30=9秒
START_TIME=$(date +%s)

for i in {1..1000}; do
  sleep 0.3
  OUTPUT=$(tmux capture-pane -t "$CODEX_PANE" -p | tr -cd '\11\12\15\40-\176')
  LAST_LINES=$(echo "$OUTPUT" | tail -15)

  # 承認待ち検出（impl モードでは自動承認）
  if echo "$LAST_LINES" | grep -qE "Would you like|Yes, proceed|Press enter to confirm"; then
    if [[ "$CODEX_MODE" == "impl" ]]; then
      tmux send-keys -t "$CODEX_PANE" "y" Enter
    fi
    NO_CHANGE_COUNT=0
    continue
  fi

  # 処理中確認
  if echo "$LAST_LINES" | grep -q "esc to interrupt"; then
    NO_CHANGE_COUNT=0
    continue
  fi

  # 完了確認
  if echo "$LAST_LINES" | grep -q "context left"; then
    COMPLETED=true
    break
  fi

  # ログファイル検知
  if [[ -d "$LOG_DIR" ]]; then
    LATEST_LOG=$(ls -t "$LOG_DIR"/*.md 2>/dev/null | head -1)
    if [[ -n "$LATEST_LOG" ]]; then
      LOG_TIME=$(stat -f %m "$LATEST_LOG" 2>/dev/null || stat -c %Y "$LATEST_LOG" 2>/dev/null)
      if [[ -n "$LOG_TIME" && "$LOG_TIME" -gt "$START_TIME" ]]; then
        COMPLETED=true
        break
      fi
    fi
  fi

  # 変化なし検知
  if echo "$LAST_LINES" | grep -q "esc to interrupt"; then
    NO_CHANGE_COUNT=0
  elif [[ "$OUTPUT" == "$PREV_OUTPUT" ]]; then
    ((NO_CHANGE_COUNT++)) || true
    if [[ $NO_CHANGE_COUNT -ge $NO_CHANGE_THRESHOLD ]]; then
      COMPLETED=true
      break
    fi
  else
    NO_CHANGE_COUNT=0
  fi
  PREV_OUTPUT="$OUTPUT"
done

# === 結果取得 ===
if [[ "$COMPLETED" == "true" ]]; then
  tmux capture-pane -t "$CODEX_PANE" -p -S -100
  exit 0
else
  echo "=== タイムアウト（5分経過）==="
  tmux capture-pane -t "$CODEX_PANE" -p -S -30
  exit 1
fi
```
