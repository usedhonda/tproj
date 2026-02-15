# 指示内容
- Learnが反応しない件の継続対応。
- ユーザー補足: 「何度も1番ボタンを押し続けていた」

# 実施内容
- MIDI診断を実施し、`Reloop Ready` から Note On/Off が継続受信されていることを確認。
  - 例: `st=0x94 d1=20 d2=127` / `st=0x84 d1=20 d2=0`
- 根本原因を修正:
  - `MIDIPaneActivator.handle(packetList:)` で `MIDIPacketList` ポインタを `queue.async` に渡していた（コールバック外で無効メモリ参照の可能性）。
  - 受信パケット解析をコールバック内で同期処理するよう変更。
- ビルド・再起動:
  - `apps/tproj/build-app.sh` 成功
  - `dist/tproj.app` 再起動、`dist` 単独起動確認（PID 69133）

# 課題、検討事項
- 受信自体は確認済みのため、今回の修正で Learn が正常に進むかを実機再確認する。
- まだ不安定なら次段で raw受信カウンタをUI表示して追跡する。
