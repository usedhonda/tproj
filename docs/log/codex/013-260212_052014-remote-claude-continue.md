# 013 remote claude continue

## 指示内容
- リモート起動時に Claude Code が `--continue` を使っていないため、まずは付ける。

## 実施内容
- `bin/tproj` のリモート起動分岐を修正し、Claude コマンドを以下へ変更。
  - `claude` -> `claude --continue || claude`
  - `npm update ...; claude` -> `npm update ...; claude --continue || claude`
- 変更箇所:
  - ワークスペースモードの remote project 起動 (`claude_pane`)
  - 単一モードの remote 起動 (`$session:dev.1`)
- `bash -n bin/tproj` で構文チェックを実施（OK）。
- 実行実体 `/Users/usedhonda/bin/tproj` へ再配置し、リポジトリ版と同期。

## 課題、検討事項
- `--continue` が失敗するケース（初回等）を考慮し、`|| claude` でフォールバックする実装にした。
- 将来的にはリモート側セッション有無を事前判定して分岐すると、不要な失敗ログを減らせる。
