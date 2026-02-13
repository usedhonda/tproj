# 指示内容
- 横幅をさらに約40px縮める。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` のウィンドウサイズ設定を調整。
  - `defaultSize.width: 320 -> 280`（約40px縮小）
  - `minWidth: 220 -> 200`（縮小しやすくするため）
- 検証:
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 41595 で起動確認

# 課題、検討事項
- さらに詰める場合は 260 も可能だが、picker表示が窮屈になるため実画面確認が必要。
