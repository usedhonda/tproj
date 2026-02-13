# 指示内容
- 狭くなったため、各セッション行のボタンを2段目に3つ並べる。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の `liveColumnRow` を変更。
  - 1段目: 列情報（番号 / local-remote / 名称 / remoteメタ）
  - 2段目: `Yazi`, `Term`, `Drop` の3ボタン
- ボタンは `expand: true` を指定して均等幅で横並び化。
- 検証:
  - `apps/tproj/build-app.sh` でビルド成功
  - 再起動後 PID 13057 で起動確認

# 課題、検討事項
- さらに横幅を詰める場合は `Yazi` / `Term` / `Drop` を `Y` / `T` / `X` に短縮可能。
