# 指示内容
- 「それぞれのセッションで、yazi / terminal のボタンが有るべき」に対応する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を修正。
- 仕様変更:
  - 上部の全体トグル（選択プロジェクト依存）を削除。
  - 各 `Live Column` 行ごとに `Yazi On/Off`, `Term On/Off`, `Drop` を配置。
- ViewModel変更:
  - `toggleYazi(for column: LiveColumn)`
  - `toggleTerminal(for column: LiveColumn)`
  - 列指定で直接トグル操作する実装へ変更。
- 画面連動:
  - `column.yaziPaneID`, `column.terminalPaneID` で On/Off ラベルとトーンを切替。
- 既存コード整理:
  - 使わなくなった selected-column 系状態・関数を削除。
- 検証:
  - `apps/tproj/build-app.sh` でビルド成功。
  - 再起動後 PID 12060 で起動確認。

# 課題、検討事項
- 列ごとにボタンが増えたため、さらに詰める場合は `Y` / `T` の短縮ラベル化も可能。
