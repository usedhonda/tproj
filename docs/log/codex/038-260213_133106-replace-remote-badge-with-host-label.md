# 指示内容
- `#7` のようなLive列表示で、`REMOTE` ではなく `@macmini` 形式で表示したい。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の `liveColumnRow` を更新。
  - `REMOTE/LOCAL` バッジを `liveHostLabel(column)` に変更。
  - remote は `@host`、local は `local` 表示。
- 重複を避けるため、同じ remote 情報の下段表示を削除。
- `liveHostLabel(_:)` を追加してラベル生成を集約。
- ビルド・起動確認。
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 15620 を確認

# 課題、検討事項
- local 表示も不要なら `local` を空表示に変更可能。
