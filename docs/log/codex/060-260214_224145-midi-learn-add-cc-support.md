# 指示内容
- Learnが効かない件について、CCも対応すべきとの指摘。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の `MIDIPaneActivator.handleMessage` を修正。
- これまで `Note On (0x90)` のみだった学習/トリガー判定を、`Control Change (0xB0)` も受けるよう拡張。
- `data2 > 0` 条件は維持し、リリース/オフ相当の0値は無視。
- ビルド実施: `apps/tproj/build-app.sh`（成功）。
- 既存 `tproj` プロセスを停止し、`dist/tproj.app` を再起動。`dist` 単独起動を確認（PID 65343）。

# 課題、検討事項
- どのボタンが Note/CC のどちらを送るかは機器側モード依存。
- 追加で必要なら statusText に「受信種別(Note/CC)」を表示して学習デバッグ性を上げられる。
