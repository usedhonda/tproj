# 018 workspace condition restored

## 指示内容
- `workspace.yaml` が読まれなくなっている問題を調査・修正。

## 実施内容
- `bin/tproj` の YAML 判定条件を確認し、以下の破損を検出:
  - `if [[ "" == "false" && "" == "false" && -f "" ]]; then`
- 条件式を正しい変数参照へ復元:
  - `if [[ "$FORCE_SINGLE_MODE" == "false" && "$ADD_MODE" == "false" && -f "$WORKSPACE_CONFIG" ]]; then`
- 同種の空文字化パターンが他にないことを確認。
- 構文チェック実施:
  - `zsh -n bin/tproj`
  - `bash -n bin/tproj`
- `--add` 実行トレースで分岐を確認（tmux外で expected error）。
- 実行実体 `/Users/usedhonda/bin/tproj` に再反映し同一性確認。

## 課題、検討事項
- 原因はテキスト置換時のミスで条件式が破損したこと。
- 今後は条件式を書き換える変更時に `grep -n '"" ==\| -f ""'` のような簡易チェックを併用する。
