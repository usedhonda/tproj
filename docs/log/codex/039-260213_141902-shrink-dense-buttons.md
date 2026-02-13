# 指示内容
- 「ボタンはおおきすぎる」ため、サイズを小さくする。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の `ActionButtonStyle` (dense) を縮小。
  - font: `12 -> 11`
  - horizontal padding: `9 -> 7`
  - vertical padding: `6 -> 4`
  - minHeight: `28 -> 24`
  - cornerRadius: `9 -> 7`
- ビルド・起動確認。
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 59306 を確認

# 課題、検討事項
- さらに小さくする場合は、live行ボタンだけ専用スタイル（extra-dense）に分離可能。
