# 指示内容
- 列入れ替えは成功するが、アプリ表示が反映されない問題を修正する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の `loadLiveColumns()` を修正。
- 変更点:
  - `isPrimaryPane` (`claude-p*` or `codex-p*`) を判定。
  - `projectPath` / `hostLabel` は primary pane を優先して採用。
  - yazi/terminal の古いメタ情報で列表示が上書きされないようにした。
- 目的:
  - tmuxで入れ替え後、UIの列表示（プロジェクト/ホスト）が追従しない不整合を防止。

# 検証
- `apps/tproj/build-app.sh` 成功。
- 再起動後 PID 1169 で起動確認。

# 課題、検討事項
- なお再現する場合は、実際の操作手順（例: #1→#3）を指定してもらえればログ追加して追跡可能。
