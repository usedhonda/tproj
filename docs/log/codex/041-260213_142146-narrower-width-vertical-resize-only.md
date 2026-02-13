# 指示内容
- ウィンドウ横幅をさらに狭くする。
- 縦方向のみリサイズ可能にして、超縦長レイアウトにする。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` のウィンドウ制約を変更。
  - 幅: 固定 `320`（`min/ideal/max` 同値）
  - 高さ: `min 860 / ideal 1100 / max 2200`
  - `defaultSize(width: 320, height: 1100)`
  - `windowResizability(.contentMinSize)` に変更
- 検証。
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 62291 で起動確認

# 課題、検討事項
- macOSのウィンドウ復元によって前回サイズが残る場合があるため、再起動で反映を確認。
