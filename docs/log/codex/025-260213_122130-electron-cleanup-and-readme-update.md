# 指示内容
- `tproj-native` 改名後の流れで、次作業を進める。
- 旧GUI資産を整理し、`tproj` 名での利用導線を揃える。

# 実施内容
- 不要になった Electron GUI ディレクトリ `apps/tproj-app` を削除。
- `README.md` に SwiftUI GUI の利用手順を追加。
  - `swift run tproj`
  - `./build-app.sh` + `open dist/tproj.app`

# 課題、検討事項
- `apps/tproj` は Swift Package ベースのため、Xcode プロジェクト形式の管理は未導入。
- GUIからの操作対象は `tproj-workspace` 前提のため、単一セッションとの統合UIは今後の検討余地あり。
