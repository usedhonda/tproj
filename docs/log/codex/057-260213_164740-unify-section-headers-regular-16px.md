# 指示内容
- 「Implement the plan.」
- `Current` と2つ目タイトルのサイズ/位置ずれを解消し、Regular統一。
- 見出しは小さすぎるため大きくし、上は `Current Workspace` にする。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を更新。
- `Card` からタイトル描画を削除し、コンテンツラッパー専用に変更。
- 新規 `SectionHeader` を追加し、見出しスタイルを統一。
  - size: 16
  - weight: semibold
- セクション見出しを以下に変更。
  - `Current Workspace`
  - `Workspace YAML`
- `ContentView` で `SectionHeader + Card` 構成に置換。
- 上余白を `4` に調整（`.padding(.top, 4)`）。
- ビルド成功: `apps/tproj/build-app.sh`
- 起動確認: 再起動後プロセス確認（PID 64106）

# 課題、検討事項
- 既存 `SectionHeader` の `leading` は `1px` 微調整。必要なら `0`/`2` でさらに詰められる。
- YAML編集系の未使用メソッドは引き続き残存。必要時に整理可能。
