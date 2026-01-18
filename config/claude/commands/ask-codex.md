---
description: Codexに意見を求める（引数なしなら直近の作業から自動で相談内容を生成）
argument-hint: <質問内容（省略可）>
allowed-tools: [Bash]
---

# Codexに質問を送信

## 注意事項
- 引数なしで実行 → Claude Codeが直近の作業から自動で相談内容を生成
- 初回実行時、プロジェクトを自動でconfig.tomlにtrusted登録
- trustedプロジェクトでは承認プロンプトは出ない
- 万が一出ても自動承認される（フォールバック）
- タイムアウト（5分）後は状況を報告し、追加待機も可能

## 🚨 Codexへの質問を構築せよ（Claude Code用・必須）

$ARGUMENTS はユーザーからあなた（Claude Code）への問いかけである。
これをそのままCodexに渡すのではなく、**あなた自身の言葉で**Codexに伝えよ。

### やるべきこと

1. **ユーザーの意図を咀嚼**: 何を聞きたいのか、なぜ聞いているのかを理解
2. **必要な経緯を判断**: Codexが回答するために必要なプロジェクト背景・直近の作業を選定
3. **自分の言葉で質問を構築**: テンプレートではなく、自然な文章でCodexに話しかける

### $ARGUMENTSが空の場合

直近の会話・作業内容を分析し、Codexに相談すべき内容を自分で判断して構築せよ:
- 現在取り組んでいるタスクの設計判断
- 実装で迷っている点や不確実な部分
- エラーや問題の解決方針
- より良いアプローチがないかの確認

### 構築例

ユーザー: `/ask-codex ロードマップを考えて`

Claude Code → Codex への質問（$MESSAGE_TO_CODEX）:
```
このプロジェクトはClaude Code用のstatuslineツール（Python）。
4行表示（モデル/Git、Compact、Session、Burn）を実装済み。
最近はtprojコマンドの改善やtmux設定調整をした。

今後のロードマップについて意見がほしい。
私としてはパフォーマンス改善（transcript解析が重い）と
エラーハンドリング強化が必要だと思っている。どう思う？
```

### 構築した質問の使用

構築した質問を `$MESSAGE_TO_CODEX` として、手順3のbashで使用せよ。

## 手順

0. プロジェクトをconfig.tomlにtrustedとして自動登録:
   ```bash
   PROJECT_PATH=$(pwd)
   CONFIG_FILE="$HOME/.codex/config.toml"

   if ! grep -q "\\[projects.\"$PROJECT_PATH\"\\]" "$CONFIG_FILE" 2>/dev/null; then
     echo "" >> "$CONFIG_FILE"
     echo "[projects.\"$PROJECT_PATH\"]" >> "$CONFIG_FILE"
     echo "trust_level = \"trusted\"" >> "$CONFIG_FILE"
     echo "プロジェクト $PROJECT_PATH を trusted として登録しました"
   fi
   ```

1. Codexペインを検出（tprojレイアウト固定）:

   tprojレイアウト: dev.1=Claude, dev.2=Codex, dev.3=yazi
   ```bash
   SESSION=$(tmux display-message -p '#S')
   CODEX_PANE="$SESSION:dev.2"
   ```

2. Codexが起動していなければ起動:
   ```bash
   # ペイン内容とプロセスから判定
   PANE_CONTENT=$(tmux capture-pane -t $CODEX_PANE -p | tail -5)
   CURRENT_CMD=$(tmux display-message -t $CODEX_PANE -p '#{pane_current_command}')

   # nodeプロセスでなく、かつCodexのUI表示もない場合のみ起動
   if [[ "$CURRENT_CMD" != "node" ]] && ! echo "$PANE_CONTENT" | grep -q "context left"; then
     tmux send-keys -t $CODEX_PANE 'codex' Enter
     sleep 5
   fi
   ```

3. 質問を送信:
   - **前提**: 上記「Codexへの質問を構築せよ」で $MESSAGE_TO_CODEX を構築済み
   - 複数行テキストは send-keys で送信後、別途 Enter を送信
   ```bash
   # $MESSAGE_TO_CODEX は Claude Code が上記セクションで構築済み
   QUESTION="まずこのプロジェクトを理解してください。すでに理解しているならスキップして構いません。

【重要】調査結果は必ずログに残してください：
- 保存場所: docs/log/codex/ に連番で (001-xxxx.md など)
- 内容: 指示内容、実施内容、課題や検討事項

$MESSAGE_TO_CODEX"

   tmux send-keys -t $CODEX_PANE "$QUESTION"
   sleep 0.5
   tmux send-keys -t $CODEX_PANE Enter
   ```

4. 回答を待機（高速ポーリング + 自動承認 + 4段階完了検知）:
   - 0.3秒間隔で最大5分待機
   - 承認プロンプト検出時は自動で「y」を送信
   - **重要**: tmux出力から制御文字を除去してからgrep（ANSIエスケープ対策）
   - **完了検知**: 「esc to interrupt」なし + (「context left」あり or ログ作成 or 3秒間変化なし)
   ```bash
   COMPLETED=false
   PREV_OUTPUT=""
   NO_CHANGE_COUNT=0
   NO_CHANGE_THRESHOLD=10  # 3秒間変化なし（0.3秒×10）
   LOG_DIR="docs/log/codex"
   START_TIME=$(date +%s)

   for i in {1..1000}; do  # 最大300秒（5分）
     sleep 0.3
     # 制御文字を除去してから検出（ANSIエスケープ対策）
     OUTPUT=$(tmux capture-pane -t $CODEX_PANE -p | tr -cd '\11\12\15\40-\176')
     LAST_LINES=$(echo "$OUTPUT" | tail -15)

     # 承認待ち検出 → 自動承認（複数パターン）
     if echo "$LAST_LINES" | grep -qE "Would you like|Yes, proceed|Press enter to confirm"; then
       tmux send-keys -t $CODEX_PANE "y" Enter
       NO_CHANGE_COUNT=0
       continue
     fi

     # 処理中確認: 「esc to interrupt」があれば確実に処理中
     if echo "$LAST_LINES" | grep -q "esc to interrupt"; then
       NO_CHANGE_COUNT=0
       continue
     fi

     # 完了確認: 「context left」があれば完了
     if echo "$LAST_LINES" | grep -q "context left"; then
       COMPLETED=true
       break
     fi

     # ログファイル検知: 開始後に新しいログが作成されたか確認
     if [[ -d "$LOG_DIR" ]]; then
       LATEST_LOG=$(ls -t "$LOG_DIR"/*.md 2>/dev/null | head -1)
       if [[ -n "$LATEST_LOG" ]]; then
         LOG_TIME=$(stat -f %m "$LATEST_LOG" 2>/dev/null || stat -c %Y "$LATEST_LOG" 2>/dev/null)
         if [[ -n "$LOG_TIME" && "$LOG_TIME" -gt "$START_TIME" ]]; then
           # 開始後にログが作成された → 完了の強いシグナル
           COMPLETED=true
           break
         fi
       fi
     fi

     # 変化なし検知: 出力が変わらなければカウント
     if [[ "$OUTPUT" == "$PREV_OUTPUT" ]]; then
       ((NO_CHANGE_COUNT++))
       if [[ $NO_CHANGE_COUNT -ge $NO_CHANGE_THRESHOLD ]]; then
         # 処理中でなく、変化もない → おそらく完了
         COMPLETED=true
         break
       fi
     else
       NO_CHANGE_COUNT=0
     fi
     PREV_OUTPUT="$OUTPUT"
   done
   ```

5. 結果を取得・タイムアウト処理:
   ```bash
   if [ "$COMPLETED" = true ]; then
     tmux capture-pane -t $CODEX_PANE -p -S -100
   else
     echo "=== タイムアウト（5分経過）==="
     echo "Codexはまだ処理中の可能性があります。現在の状態:"
     tmux capture-pane -t $CODEX_PANE -p -S -30
     echo ""
     echo "対応方法:"
     echo "  - 「もう少し待って」→ 追加で待機を継続"
     echo "  - 「状況を見せて」→ 現在のCodex出力を再取得"
     echo "  - 手動でCodexペインを確認"
   fi
   ```
