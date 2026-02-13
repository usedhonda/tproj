# 指示内容
- UI上の「Alias」表記を不要にする。
- remote はホスト名が分かるようにする。
- プロジェクト名と別名が同じ場合などの重複表示を減らす。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を調整。
  - `Picker("Alias")` を `Picker("Project")` に変更。
  - `No alias selected` を `No project selected` に変更。
  - プロジェクトカード上部の `Alias: ...` 表示を廃止。
  - `projectPrimaryName` / `projectDetail` を追加し、
    - alias と project 名が異なる時だけ alias を主表示
    - remote は `@host` を表示
    - 重複時は片方を省略
  - live列でも `Alias:` 文言を廃止し、`columnPrimaryName` / `columnMeta` を追加。
    - remote の host を `@host` 形式で表示
    - `w<width>` と併記
  - 入力ラベルを `Alias (used by tproj --add)` から `Name used by tproj --add` へ変更。
- ビルド・起動確認。
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 6645 で動作確認

# 課題、検討事項
- 内部プロパティ名（`effectiveAlias`, `selectedAlias`）は互換性維持のためそのまま。必要なら別途リファクタ可能。
