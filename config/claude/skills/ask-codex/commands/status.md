---
description: Codexペインの状態を確認
allowed-tools: [Bash]
---

# Codexペインの状態確認

以下のスクリプトを実行してCodexペインの状態を確認せよ。

```bash
#!/bin/bash

# セッション名取得
SESSION=$(tmux display-message -p '#S' 2>/dev/null)

if [[ -z "$SESSION" ]]; then
  echo "状態: tmuxセッション外"
  echo "解決: プロジェクトディレクトリで 'tproj' を実行してください"
  exit 1
fi

echo "セッション: $SESSION"

# Codexペイン確認
CODEX_PANE="$SESSION:dev.2"
if ! tmux list-panes -t "$CODEX_PANE" &>/dev/null; then
  echo "状態: Codexペインなし"
  echo "解決: tprojで起動したセッションで実行してください"
  exit 1
fi

# Codex起動確認
CURRENT_CMD=$(tmux display-message -t "$CODEX_PANE" -p '#{pane_current_command}')
PANE_CONTENT=$(tmux capture-pane -t "$CODEX_PANE" -p)
RECENT_LINES=$(echo "$PANE_CONTENT" | tail -20)

CODEX_RUNNING=false
[[ "$CURRENT_CMD" == "node" ]] && CODEX_RUNNING=true
echo "$RECENT_LINES" | grep -q "context left" && CODEX_RUNNING=true
echo "$RECENT_LINES" | grep -q "esc to interrupt" && CODEX_RUNNING=true

if [[ "$CODEX_RUNNING" == "true" ]]; then
  echo "状態: Codex起動中"
  echo "ペイン: $CODEX_PANE"
  echo "プロセス: $CURRENT_CMD"

  # コンテキスト残量を表示
  CONTEXT_LINE=$(echo "$RECENT_LINES" | grep "context left" | tail -1)
  if [[ -n "$CONTEXT_LINE" ]]; then
    echo "コンテキスト: $CONTEXT_LINE"
  fi
else
  echo "状態: Codex停止中"
  echo "解決: dev.2ペインで 'codex' を実行してください"
  exit 1
fi
```
