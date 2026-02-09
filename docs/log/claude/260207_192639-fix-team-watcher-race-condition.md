# team-watcher レースコンディション修正 (v2)

## 指示
複数エージェント spawn 時のレイアウト崩壊を修正

## 根本原因
`settings.json` の PostToolUse hook で `async: true` + `&` により、
team-watcher がバックグラウンドで起動。Claude Code は hook 完了を待たず
即座にエージェント spawn に進むため、`after-split-window` フック設定前に
`split-window` が実行され、reflow 未実行でレイアウト崩壊。

## 修正内容

### `~/.claude/settings.json`
- PostToolUse TeamCreate hook: `async: true` と `&` を削除
- team-watcher を同期実行に変更（内部で即座に制御を返す）

### `bin/team-watcher`
- 2フェーズ構造に変更:
  - Phase 1 (同期): env var + hook 設定。Claude Code が agent spawn する前に必ず完了
  - Phase 2 (非同期): `( ... ) & disown` でポーリングループをバックグラウンド化
- cleanup trap をバックグラウンドプロセス内に配置
- `trap cleanup EXIT INT TERM` でシグナルも明示的にハンドル

### `bin/reflow-agent-pane`
- 変更なし（前回の修正を維持）

## 変更ファイル
- `~/.claude/settings.json` - hook 設定変更
- `bin/team-watcher:1-87` - 2フェーズ構造に全面書き換え

## 検証手順
1. `tmux kill-session -t tproj && tproj` で新規起動
2. Claude Code 内で TeamCreate + 2人の teammate を spawn
3. 確認: 両エージェントが Codex の上に配置、@role タグあり、Claude にフォーカス
