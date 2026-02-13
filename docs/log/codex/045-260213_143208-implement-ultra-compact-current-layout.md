# 指示内容
- 先に提示した「まだ余白があるのでさらに詰める」計画を実装する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を超圧縮レイアウトへ調整。
- Current セクション最適化:
  - `statusText` を時刻部分のみ表示する `compactStatus()` を追加。
  - `Refresh` を `R`、`Add` を `A` に短縮。
  - Picker を `.labelsHidden()` 化。
- 余白とサイズ圧縮:
  - Card spacing/padding/corner を縮小。
  - 外側 padding を `0` に変更。
  - live row の padding, spacing を縮小。
- ボタン圧縮:
  - dense button の padding/minHeight/corner をさらに縮小。
  - live 行の `Yazi/Term/Drop` を幅 `38` に固定。
- Pill圧縮:
  - フォント/パディングを縮小。
  - local ラベルを `lcl` に短縮。
- ウィンドウ幅:
  - 固定幅 `276 -> 260`。
  - `defaultSize.width` も `260`。
- 検証:
  - `apps/tproj/build-app.sh` 成功。
  - 再起動後 PID 76288 で起動確認。

# 課題、検討事項
- ここまで詰めると可読性は低下するため、必要なら `Workspace YAML` 側だけ少し余白を戻す運用も可能。
