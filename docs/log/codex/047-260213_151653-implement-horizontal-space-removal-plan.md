# 指示内容
- 横の無駄スペースをなくす計画を実装する。
- ボタン配置は変更しない。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を修正。
- 横幅追従化:
  - `Card` の root に `.frame(maxWidth: .infinity, alignment: .leading)` を追加。
  - `ScrollView` 内 `VStack` に `.frame(maxWidth: .infinity, alignment: .leading)` を追加。
  - `ScrollView` 自体にも `.frame(maxWidth: .infinity)` を追加。
- ウィンドウ幅制約の緩和:
  - `ContentView` の固定幅 (`260`) を解除。
  - `minWidth: 220` のみ維持し、横可変を許可。
  - `defaultSize.width` を `320` に設定。
- ボタン配置:
  - `Yazi/Term/Drop` の配置・順序・右寄せは未変更。
- 検証:
  - `apps/tproj/build-app.sh` 成功。
  - 再起動後 PID 39790 で起動確認。

# 課題、検討事項
- ウィンドウを意図的に広げた場合は横可変のため余白が出る可能性がある。通常運用では内容が横いっぱいに追従する。
