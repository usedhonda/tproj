# 指示内容
- アプリを常に上に持っていく（Always On Top）対応。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を修正。
  - `import AppKit` を追加。
  - `ContentView` に `WindowAccessor` を追加し、取得した `NSWindow` に
    `window.level = .floating` を設定。
  - `WindowAccessor` (`NSViewRepresentable`) を新規追加し、SwiftUIからWindow参照を解決。
- 検証。
  - `apps/tproj/build-app.sh` でビルド成功。
  - 再起動後 PID 74642 で起動確認。

# 課題、検討事項
- 現状は「同一スペース内で常に手前」。
- 全スペース表示が必要な場合は `collectionBehavior` の追加設定を検討。
