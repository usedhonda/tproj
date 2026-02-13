# 指示内容
- 横幅に無駄な空間が多いので詰める。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の余白と幅を縮小。
  - Card padding: `compact 10->6`, `normal 16->12`
  - Card corner radius: `compact 10->8`, `normal 14->12`
  - 外側 padding: `10->6`
  - live row padding: `8->6`
  - window width: `320 -> 300`（固定）
  - default width: `320 -> 300`
- 検証:
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 65481 で起動確認

# 課題、検討事項
- さらに詰める場合は、`Workspace YAML` 側の各プロジェクトカード内 `padding(12)` も縮小可能。
