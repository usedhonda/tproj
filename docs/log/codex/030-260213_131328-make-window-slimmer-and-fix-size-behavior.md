# 指示内容
- 「もっと細長に。あとサイズがおかしい。」への対応。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` のウィンドウサイズ設定を再調整。
  - `frame` を細幅寄りに変更: `minWidth: 340, idealWidth: 360, maxWidth: 420`
  - 高さは縦長維持: `minHeight: 760, idealHeight: 980, maxHeight: 1200`
  - `.defaultSize(width: 360, height: 980)` を追加
  - `.windowResizability(.contentMinSize)` を追加してサイズ挙動を安定化
- 細幅時の崩れ対策として、ヘッダの `workspacePath` を1行省略表示に変更
  - `.lineLimit(1)`
  - `.truncationMode(.middle)`
- ビルドと起動確認
  - `apps/tproj/build-app.sh` で再ビルド成功
  - 既存プロセス停止後に `dist/tproj.app` を再起動
  - 新プロセス PID 95253 を確認

# 課題、検討事項
- macOSのウィンドウ復元状態により、前回サイズが保持される場合があるため、再起動で反映確認した。
- さらに固定サイズにしたい場合は `.windowResizability(.contentSize)` への変更を検討可能。
