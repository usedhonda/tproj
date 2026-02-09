# reflow-agent-pane v3: split+swap+kill 方式

## 変更内容

`bin/reflow-agent-pane` の未タグペイン再配置ロジックを変更:

### Before (move-pane)
```bash
tmux move-pane -d -v -b -s "$pane_id" -t "$CODEX_PANE" -l 20%
```
問題: `move-pane` はペインツリーを再構築 -> 左右の横幅比率が崩壊

### After (split+swap+kill)
```bash
# 1. 右カラム内で codex の上に空ペインを作成
NEW_PANE=$(tmux split-window -v -b -t "$CODEX_PANE" -l 20% -d -P -F '#{pane_id}')
# 2. エージェントプロセスを正しい位置にswap
tmux swap-pane -s "$pane_id" -t "$NEW_PANE"
# 3. 元位置の空ペインを削除（siblingが領域回収）
tmux kill-pane -t "$pane_id"
# 4. タグ設定
tmux set-option -pt "$NEW_PANE" @role "agent-pending"
```

横幅が崩れない理由:
- `split-window -v` は右カラム内部の縦分割のみ
- `swap-pane` はプロセス内容の入替のみ
- `kill-pane` で元位置削除 -> claude が元の幅に自然復帰

追加改善: 未タグペインを先に配列に収集してからループ（ループ中のペインリスト変動を防止）

## 変更ファイル

| ファイル | 行 | 変更 |
|----------|-----|------|
| `bin/reflow-agent-pane:34-51` | 34-51 | `move-pane` -> `split+swap+kill` |

## テスト手順

### 前提条件

残存チームがあると TeamCreate が失敗する。テスト前に必ずクリーンアップ:

```bash
# 残存チームの確認
ls ~/.claude/teams/

# 残存チームの削除（あれば）
rm -rf ~/.claude/teams/*

# TeamDelete も実行（セッション内状態のクリア）
# Claude Code 内で: TeamDelete ツールを使用
```

### テスト実行

1. `./install.sh` で再デプロイ
2. `tmux kill-session -t tproj && tproj` で新規起動
3. TeamCreate + 2人の teammate spawn
4. 確認:
   - エージェントペインが codex の上に配置される
   - claude ペインの横幅が reflow 前後で変わっていない
   - 全ペインに `@role` タグがある (`tmux list-panes -t tproj:dev -F '#{pane_id}:#{@role}:#{pane_width}x#{pane_height}'`)
   - claude ペインにフォーカスが戻っている

### テスト後クリーンアップ

```bash
# teammate をシャットダウン（Claude Code 内）
SendMessage type: "shutdown_request" to each teammate

# チーム削除（Claude Code 内）
TeamDelete

# 残骸確認
ls ~/.claude/teams/
```

## 課題

- TeamCreate ツールが同一セッション内で繰り返し内部エラーになる問題あり
- config.json がファイルシステムに書き込まれない場合がある
- テストは新規セッションから実行するのが確実
