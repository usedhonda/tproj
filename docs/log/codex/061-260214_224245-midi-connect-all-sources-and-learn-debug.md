# 指示内容
- 「押してもダメ」への対応。
- Learn反応がない問題を追加で修正。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を修正。
- MIDI source 接続ロジックを変更:
  - これまで: `reloop/ready` 優先で一部sourceのみ接続
  - 変更後: 取得できる全MIDI sourceへ接続（取りこぼし防止）
- Learn中の可視化強化:
  - 受信時に `Learned Note/CC data1=... ch=... -> slot ...` を statusText 出力
  - 受信イベントの種別確認が可能に
- 起動時に source 一覧を statusText へ表示
  - `MIDI sources: ...`
- ビルド実施: `apps/tproj/build-app.sh` 成功
- 再起動実施: `dist/tproj.app` 単独起動確認（PID 66603）

# 課題、検討事項
- まだ反応しない場合は、機器が Note/CC 以外のメッセージ種別を出している可能性がある。
- 次段として raw受信ログ（status/data1/data2）を常時表示する診断モードを追加可能。
