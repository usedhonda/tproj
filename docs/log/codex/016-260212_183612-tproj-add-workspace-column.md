# 016 tproj add workspace column

## 指示内容
- `tproj --add` を実装し、起動済み `tproj-workspace` 内で右隣に1列（Claude + Codex）を追加できるようにする。
- 追加元は実行中ペインのプロジェクト情報を使う。

## 実施内容
- `bin/tproj` に `--add` オプションを追加。
- `show_help` の `Options` / `Examples` を更新。
- `ADD_MODE` フラグを追加し、`--add` を引数パーサで処理。
- `add_workspace_column()` 関数を新規追加し、以下を実装:
  - `tproj-workspace:dev` の存在確認
  - 実行中ペイン（`TMUX_PANE`）から `@project/@remote_host/@remote_path` を解決
  - 既存 `@column` 最大値から新しい列番号を算出
  - 右端 `claude-pN` の右に `split-window -h` で Claude ペイン作成
  - その下に `split-window -v` で Codex ペイン作成
  - `@role/@column/@project/@remote_*` のタグ付与
  - pane title 設定（`[host] project | CC/Codex`）
  - Claude は `allow-set-title off` を適用
  - ローカル/リモートに応じて Claude/Codex を既存ルールで自動起動
- `--add` は `-r` / `-s` との併用をエラーにした。
- `--add` 実行時は YAML 解析（workspace.yaml/yq依存）をスキップするよう条件を調整。
- 検証:
  - `zsh -n bin/tproj`, `bash -n bin/tproj` で構文チェック
  - `./bin/tproj --help` でヘルプ反映確認
  - `TMUX='' ./bin/tproj --add` で想定エラーメッセージ確認
- 実行実体へ反映:
  - `/Users/usedhonda/bin/tproj` にコピーし、実行権限設定・同一性確認

## 課題、検討事項
- 今回は `--add` を `tproj-workspace` セッション専用に固定。
- 追加列は初期状態で yazi を作らない（既存運用通り `Prefix + y` で生成）。
- 列追加後の Agent Teams reflow 連携はタグ互換前提で動作する設計（実セッションでの長時間運用確認は今後推奨）。
