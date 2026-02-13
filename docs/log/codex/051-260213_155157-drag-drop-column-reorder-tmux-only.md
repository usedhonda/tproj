# 指示内容
- `#1` などの列をドラッグで入れ替え、番号表示とtmux列を入れ替えたい。
- 反映範囲は tmux 実行中のみ（YAMLは変更しない）。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を更新。

## UI側
- `LiveColumn` の `Identifiable` を安定ID化（`id = column`）。
- `ContentView` の `ForEach(vm.liveColumns)` 各行に以下を追加。
  - `.onDrag` で `column` をドラッグデータ化
  - `.onDrop` + `ColumnDropDelegate` で target 行へドロップ受付
  - ドラッグ中の行を `opacity 0.7` 表示
- `ColumnDropDelegate` を追加し、ドロップ時に `moveColumn(from:to:)` を呼び出し。

## ViewModel側
- `moveColumn(from:to:)` を追加。
  - agent panes 有効時は reorder をブロック
  - claude/codex の必須paneを `tmux swap-pane` で入れ替え
  - yazi/terminal は
    - 両列に存在: `swap-pane`
    - 片側のみ: `relocatePaneAboveCodex` で対象列へ追従移動
  - `@column` と `@role` の `-pN` サフィックスを source/target で再ラベル
  - `rebalance-workspace-columns` 実行後に `loadLiveColumns()`
- 補助関数を追加。
  - `listWorkspacePanes`
  - `paneID(forRole:panes:)`
  - `relocatePaneAboveCodex`
  - `swapColumnTagsAndRoles`
  - `swappedRoleColumnSuffix`

# 課題、検討事項
- agent が有効な状態では安全のため reorder を無効化。
- 並び替えは tmux 実行状態にのみ反映（workspace.yaml 非更新）。

# 検証
- `apps/tproj/build-app.sh` 成功
- 再起動後 PID 84654 で起動確認
