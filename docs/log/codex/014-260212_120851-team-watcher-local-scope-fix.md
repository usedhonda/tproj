# 指示内容
コードが汚くなってそう

# 実施内容
- リポジトリを走査し、主要スクリプト (`bin/tproj`, `bin/team-watcher`) を確認。
- `bin/team-watcher` の実行時エラー要因を特定。
  - Bash 関数外で `local` が使われていたため、該当分岐到達時に `local: can only be used in a function` で停止する状態。
- `bin/team-watcher` を最小修正。
  - `col` と `agent_found` の宣言を関数外 `local` から通常変数へ変更。
- `bash -n bin/team-watcher` で構文確認を実施し、OK を確認。

# 課題、検討事項
- 現在ワークツリーには未コミット変更が複数存在するため、今回の修正は最小差分に限定した。
- `shellcheck` が未導入のため、静的解析を網羅実行できていない。必要なら導入して追加クリーンアップを実施可能。
