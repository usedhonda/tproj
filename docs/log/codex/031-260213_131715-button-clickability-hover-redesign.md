# 指示内容
- 押せるボタンが分かりにくいため、クリック可能と分かるデザインに見直す。
- マウスオーバー時に反応するようにする。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` に共通ボタンを追加。
  - `ActionButtonTone`（neutral / primary / danger）
  - `ActionButtonStyle`（通常・hover・pressed・disabledの見た目差）
  - `ActionButton`（`onHover` でホバー反応、再利用可能）
- 既存ボタンを置換。
  - `Add Column`, `Remove`, `+ Project`, `Save`, `Refresh`, `Drop`
- 余計な旧ボタン残骸を削除。
- 検証。
  - `apps/tproj/build-app.sh` でビルド成功。
  - アプリ再起動して新プロセス PID 98745 で起動確認。

# 課題、検討事項
- 現状は色＋スケールで反応を示す実装。必要ならカーソル変更やアイコン追加も検討可能。
