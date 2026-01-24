---
name: ask-codex
description: |
  Codexへの質問・相談スキル。tmux上でCodexペインが存在する場合に使用可能。
  「Codexに聞いて」「Codexに相談」「ask-codex」で発動。
  設計の相談、セカンドオピニオン、不確実な判断時に活用。
argument-hint: <質問内容（省略可）>
allowed-tools: [Bash]
compression-anchors:
  - "tmuxセッション内でCodexペインに質問を送信"
  - "回答完了を自動検知して結果を取得"
  - "事前にCodexの起動状態を確認"
---

# Codexに質問を送信

## 概要

tprojセッション内で、Claude Code（dev.1）からCodex（dev.2）に質問を送信する。

## 使用条件

- tprojで起動したtmuxセッション内であること
- Codexペイン（dev.2）が存在すること
- Codexが起動していること

## 自律使用の判断基準

CCは以下の場合に自律的にこのスキルを使用すべき：

1. **設計判断に迷った時** - 複数のアプローチがあり、どれが最適か不明
2. **セカンドオピニオンが欲しい時** - 自分の判断に自信がない
3. **プロジェクト固有の知識が必要な時** - Codexが詳しいはず
4. **リスクの高い変更を行う前** - 大きな影響がある変更
5. **ユーザーが「Codexに聞いて」と言った時**

## 質問の構築（必須）

$ARGUMENTS はユーザーからの問いかけ。これをそのままCodexに渡すのではなく、**あなた自身の言葉で**Codexに伝えよ。

### やるべきこと

1. ユーザーの意図を咀嚼
2. 必要なプロジェクト背景・直近の作業を選定
3. 自然な文章でCodexに話しかける質問を構築

### $ARGUMENTSが空の場合

直近の会話・作業から、Codexに相談すべき内容を自分で判断して構築せよ。

### 例

ユーザー: `/ask-codex ロードマップを考えて`

構築する質問:
```
このプロジェクトはClaude Code用のstatuslineツール（Python）。
今後のロードマップについて意見がほしい。
私としてはパフォーマンス改善が必要だと思っている。どう思う？
```

## 実行

**重要**: 以下のスクリプト全体を**1回のBash呼び出し**で実行せよ。
`YOUR_QUESTION_HERE` を構築した質問に置き換えること。

```bash
#!/bin/bash
set -euo pipefail

# === 設定 ===
MESSAGE_TO_CODEX="YOUR_QUESTION_HERE"

# === trusted登録 ===
PROJECT_PATH=$(pwd)
CONFIG_FILE="$HOME/.codex/config.toml"
if [[ -f "$CONFIG_FILE" ]] && ! grep -q "\\[projects.\"$PROJECT_PATH\"\\]" "$CONFIG_FILE" 2>/dev/null; then
  echo "" >> "$CONFIG_FILE"
  echo "[projects.\"$PROJECT_PATH\"]" >> "$CONFIG_FILE"
  echo 'trust_level = "trusted"' >> "$CONFIG_FILE"
fi

# === ペイン検出（tprojレイアウト固定）===
SESSION=$(tmux display-message -p '#S')
CODEX_PANE="$SESSION:dev.2"

# ペインが存在するか確認
if ! tmux list-panes -t "$CODEX_PANE" &>/dev/null; then
  echo "エラー: Codexペイン($CODEX_PANE)が見つかりません"
  echo "tprojで起動したセッション内で実行してください"
  exit 1
fi

# === Codex起動確認 ===
# tprojで起動していればCodexは常に起動している前提
# 起動していない場合（手動終了/クラッシュ）はエラー
CURRENT_CMD=$(tmux display-message -t "$CODEX_PANE" -p '#{pane_current_command}')
PANE_CONTENT=$(tmux capture-pane -t "$CODEX_PANE" -p)

CODEX_RUNNING=false
[[ "$CURRENT_CMD" == "node" ]] && CODEX_RUNNING=true
# 直近20行だけ検索（過去ログの誤検出防止）
RECENT_LINES=$(echo "$PANE_CONTENT" | tail -20)
echo "$RECENT_LINES" | grep -q "context left" && CODEX_RUNNING=true
echo "$RECENT_LINES" | grep -q "esc to interrupt" && CODEX_RUNNING=true

if [[ "$CODEX_RUNNING" == "false" ]]; then
  echo "エラー: Codexが起動していません"
  echo "dev.2ペインでcodexを起動してください"
  exit 1
fi

# === 質問送信 ===
QUESTION="まずこのプロジェクトを理解してください。すでに理解しているならスキップして構いません。

【重要】調査結果は必ずログに残してください：
- 保存場所: docs/log/codex/ に連番で (001-xxxx.md など)
- 内容: 指示内容、実施内容、課題や検討事項

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
LOG_DIR="docs/log/codex"
START_TIME=$(date +%s)

for i in {1..1000}; do
  sleep 0.3
  OUTPUT=$(tmux capture-pane -t "$CODEX_PANE" -p | tr -cd '\11\12\15\40-\176')
  LAST_LINES=$(echo "$OUTPUT" | tail -15)

  # 承認待ち検出
  if echo "$LAST_LINES" | grep -qE "Would you like|Yes, proceed|Press enter to confirm"; then
    tmux send-keys -t "$CODEX_PANE" "y" Enter
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

  # 変化なし検知（処理中でなければ）
  if echo "$LAST_LINES" | grep -q "esc to interrupt"; then
    # 処理中は変化なしカウントをリセット
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
