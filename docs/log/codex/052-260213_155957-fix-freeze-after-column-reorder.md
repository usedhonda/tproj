# 指示内容
- 列入れ替え成功後にアプリが固まるように見える症状を改善する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の列入れ替え処理を非同期化。
- 主な変更:
  - `runCommandAsync()` を追加（`DispatchQueue.global` でコマンド実行）。
  - `executeCommand()` を `static` 実行関数として分離。
  - `moveColumn` 内の tmux 操作を `await runCommandAsync(...)` に置換。
  - 列入れ替え補助関数を async 化。
    - `listWorkspacePanesAsync`
    - `relocatePaneAboveCodexAsync`
    - `swapColumnTagsAndRolesAsync`
- 目的:
  - メインスレッド（UI）での同期 `Process.waitUntilExit` 連打を避け、フリーズ感を軽減。

# 検証
- `apps/tproj/build-app.sh` 成功。
- 再起動後 PID 97730 で起動確認。

# 課題、検討事項
- tmuxコマンド自体が長時間ハングした場合は待機が続くため、将来的にタイムアウト導入を検討可能。
