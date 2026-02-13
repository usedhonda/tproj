# 指示内容
- 左右の無駄スペースと、ボタン間の隙間をさらに削減する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を追加で圧縮調整。
- 余白・間隔:
  - Card padding: `compact 4`, `normal 8`
  - Card spacing: `compact 6`, `normal 10`
  - 画面外側 padding: `2`
  - live row padding: `4`
  - live button row spacing: `2`
- ボタン:
  - denseボタンをさらに小型化
    - horizontal padding `5`
    - vertical padding `3`
    - minHeight `20`
    - cornerRadius `6`
  - live行の `Yazi/Term/Drop` 幅を `44` に固定
- 画面幅:
  - 固定幅 `300 -> 276`
  - default width `300 -> 276`
- 検証:
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 70943 で起動確認

# 課題、検討事項
- さらに詰める場合は `Project` picker のラベル領域を短縮する専用カスタムビュー化を検討可能。
