# 020 rebalance on add/remove

## 指示内容
- プロジェクト列を「増やす/消す」たびに、横幅を均等化すること。

## 実施内容
- `bin/rebalance-workspace-columns` を新規追加。
  - `tproj-workspace:dev` の `codex-p*` 列を対象に横幅を再配分。
  - tmuxの木構造で1回で収束しないケースに備えて複数回リサイズ。
  - Agentペインが存在する場合は再配分をスキップ（不安定状態回避）。
- `bin/tproj` の `add_workspace_column()` 終了時に再配分呼び出しを追加。
  - `"$HOME/bin/rebalance-workspace-columns" "$session"`
- `bin/tproj` の workspace セッション生成時に `after-kill-pane` フックを追加。
  - 列削除（pane kill）後に自動再配分。
- `install.sh` に `rebalance-workspace-columns` の配布を追加。
  - copy + chmod 対象へ追加。
- 実行実体へ反映。
  - `/Users/usedhonda/bin/tproj`
  - `/Users/usedhonda/bin/rebalance-workspace-columns`

## 課題、検討事項
- tmuxレイアウト木の状態により完全等幅に収束しづらいケースがあるため、現時点では非破壊リサイズを優先。
- Agentペイン存在時はレイアウト変化が大きく、再配分は意図的にスキップ。
