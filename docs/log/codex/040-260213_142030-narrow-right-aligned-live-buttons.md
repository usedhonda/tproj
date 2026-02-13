# 指示内容
- On/Off文言をなくした状態で、ボタン横幅を小さくして右寄せにする。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の `liveColumnRow` を調整。
  - ボタン行の先頭に `Spacer()` を追加して右寄せ。
  - `Yazi` / `Term` / `Drop` を `expand: true` から通常表示へ変更。
  - 各ボタンに `.frame(width: 54)` を適用して小幅化。
- 検証:
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 61088 で起動確認

# 課題、検討事項
- さらに詰める場合は幅 `48` まで縮小可能。
