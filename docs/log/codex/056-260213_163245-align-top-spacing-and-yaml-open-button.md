# 指示内容
- 左右ギリギリ配置の中で、上部3ボタンとのズレ感をなくし、少しだけスペースを作る。
- `WORKSPACE YAML` は編集UIを廃止し、設定ファイルをOS既定で開くボタンだけにする。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を修正。
- 全体コンテンツに最小限の余白を追加。
  - `.padding(.horizontal, 4)`
  - `.padding(.top, 2)`
- `Workspace YAML` カードを簡素化し、`Open workspace.yaml` ボタン1つに変更。
- `AppViewModel` に `openWorkspaceYAML()` を追加し、`NSWorkspace.shared.open(...)` でOS既定アプリに委譲。
- ビルド実施: `apps/tproj/build-app.sh`（成功）
- 起動確認実施: 既存プロセス停止後、`apps/tproj/dist/tproj.app` を再起動してプロセス起動を確認。

# 課題、検討事項
- 旧YAML編集系メソッド（`saveWorkspace` / `addWorkspaceRow` / `deleteWorkspaceRow` など）は現UIでは未使用。必要なら次回整理可能。
