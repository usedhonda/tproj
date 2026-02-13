# 指示内容
- つまんでも最小サイズ制約で小さくできない問題を修正する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` のウィンドウ制約を緩和。
  - `minHeight: 860 -> 520`
  - `idealHeight: 1100 -> 980`
  - `defaultSize.height: 1100 -> 980`
  - 幅固定300は維持
- 検証:
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 66791 で起動確認

# 課題、検討事項
- さらに小さくしたければ `minHeight` を 460 程度まで下げる余地あり。
