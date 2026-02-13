# 指示内容
- 列入れ替え後、アプリ側の順番が新しいものに反映されない症状を修正する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` に列メタ同期処理を追加。
- 変更点:
  - `ColumnMeta` 構造体を追加。
  - `moveColumn` 開始時に source/target の列メタ（projectPath/hostLabel）を保持。
  - pane swap / role relabel 後に、列ごとの `@project`, `@remote_host`, `@remote_path` を
    source/target 入れ替えに合わせて再設定。
  - 補助関数を追加:
    - `columnMeta(for:)`
    - `applyColumnMetadataSwap(...)`
    - `projectTagValue(for:)`
    - `hostValue(from:)`
- 目的:
  - tmux表示は変わるがアプリ順序が旧表示のままになる不整合を解消。

# 検証
- `apps/tproj/build-app.sh` 成功。
- 再起動後 PID 15111 で起動確認。

# 課題、検討事項
- もし still 再現する場合は、具体的に「どの列→どの列」で発生するかを取得して追跡可能。
