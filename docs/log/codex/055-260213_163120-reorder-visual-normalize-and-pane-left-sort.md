# 指示内容
- 「すすめて」: ドラッグ後に tmux 側は入れ替わるが、アプリ側の順番が新しいものに反映されない症状を継続修正。
- 途中で `tmux list-panes` の実行安全性確認があり、読み取り専用で非破壊であることを確認。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を修正。
- `loadLiveColumns()` の pane 取得フォーマットに `#{pane_left}` を追加。
- `LiveColumn` / Builder に `left` を追加し、UI表示順を `@column` 固定ではなく `pane_left` 優先でソートするよう変更。
- ドラッグ入れ替え後に `normalizeColumnsByVisualOrderAsync()` を実行するよう追加。
  - `tmux list-panes` で `pane_left` と `@column` を取得
  - 可視順（左から右）で列番号を 1..N に再割当
  - `@column` と `@role` の suffix (`-pN`) を再マップして整合
- ビルド実施: `apps/tproj/build-app.sh`（成功）
- 起動確認実施: 既存プロセス停止後、`apps/tproj/dist/tproj.app` を再起動し、プロセス起動を確認。

# 課題、検討事項
- 実機でのドラッグ操作後に、期待どおり「アプリ表示順と番号」が更新されるかはユーザー操作での最終確認が必要。
- 現在 `main.swift` は Git 上で untracked 扱いのため、必要に応じて追跡対象化（add）方針を確認する。
