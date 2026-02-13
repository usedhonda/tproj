# 指示内容
- 画面が「ウィンドウの中にウィンドウ」に見える。外側の無駄な枠を減らしたい。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` の `Card` に `chrome` パラメータを追加。
  - `chrome: true`（既定）では従来の背景+枠線を表示。
  - `chrome: false` では背景/枠線/内側余白を無効化。
- `Current` セクションを `Card(title: "Current", compact: true, chrome: false)` に変更。
  - 外側カード枠を除去し、二重ウィンドウ感を解消。
- 検証:
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 78196 で起動確認

# 課題、検討事項
- さらにフラットにする場合は、Live row の角丸背景もライン区切りへ置換可能。
