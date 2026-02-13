# 指示内容
- Electron 風の見た目をやめ、Swift でネイティブアプリ化する。
- UI は縦長を前提にする。
- 既存の tproj workspace 状態を読み込み、現在状態を反映する。
- プロジェクトの追加/削除、workspace.yaml の上書き保存を行えるようにする。

# 実施内容
- `apps/tproj-native` を新規作成し、Swift Package ベースの macOS SwiftUI アプリを実装。
- 1カラム縦長UIに変更し、以下の3セクション構成にした。
  - Live Workspace: `tmux list-panes -t tproj-workspace:dev` から列情報を表示
  - Column Actions: `tproj --add <alias>` 実行
  - Workspace YAML: `workspace.yaml` 編集 + `Save (overwrite)`
- YAML 読み込みは `yq` を利用し、`path/type/host/alias/enabled` を反映。
- 列削除は `claude/codex` 両 pane を `tmux kill-pane` で落とし、`rebalance-workspace-columns` を再実行。
- ビルド確認: `cd apps/tproj-native && swift build` 成功。

# 課題、検討事項
- 現在は Swift Package 実行形式（`swift run` / `.build/debug/tproj-native`）で、`.app` バンドル配布は未整備。
- `yq` / `tmux` / `tproj` コマンドに依存するため、未インストール環境では機能しない。
- workspace.yaml の保存は整形上書きのため、既存コメントや独自フォーマットは保持されない。
