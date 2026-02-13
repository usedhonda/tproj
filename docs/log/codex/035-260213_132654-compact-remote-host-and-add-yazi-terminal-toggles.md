# 指示内容
- remote 表示は `@macmini` のように最小表現にしたい。
- そのぶん画面を小さくしたい。
- ボタンを増やし、yazi と terminal の on/off を切り替えたい。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を更新。
- 表示圧縮:
  - remote 詳細を `@host` 形式へ統一（余分な語を削除）。
  - local のときはメタ行を非表示にして行高さを削減。
  - プロジェクトカードも remote 詳細を `@host` ベースで短縮。
- ボタン追加:
  - Current セクションに `Yazi On/Off` と `Term On/Off` を追加。
  - 選択中プロジェクトの live 列に紐づいてトグル状態を表示。
- 機能追加（ViewModel）:
  - `toggleYazi()`
    - `~/bin/tproj-toggle-yazi tproj-workspace <pane>` を実行。
  - `toggleTerminal()`
    - `terminal-p<column>` pane を検出して存在時は kill（Off）。
    - 未存在時は codex pane 上に新規 split して role 設定（On）。
    - remote は `ssh -t <host> "cd <path> && exec $SHELL -l"` で接続。
    - local は `cd <path> && exec $SHELL -l` で起動。
  - `selectedYaziIsOn` / `selectedTerminalIsOn` / `canToggleTools` などの状態追加。
- 検証:
  - `apps/tproj/build-app.sh` 成功
  - 再起動後 PID 9973 で起動確認

# 課題、検討事項
- 切替対象は「選択中プロジェクト列」。将来的に列ごとの個別ボタン表示にも拡張可能。
- terminal pane の高さは現在 25%。必要なら UI からプリセット化できる。
