# 012 remote path others confirmation

## 指示内容
- `openclaw_general` のリモートパスについて、`other` ではなく `others` が正しいか確認。

## 実施内容
- 実接続結果から、`/Users/usedhonda/projects/other/openclaw_general` は存在せず、`/Users/usedhonda/projects/others/openclaw_general` が実在することを再確認。
- リポジトリ内のサンプル設定 `config/workspace.yaml.example` の誤記を修正:
  - `.../projects/other/openclaw_general` -> `.../projects/others/openclaw_general`

## 課題、検討事項
- 実運用で参照される `~/.config/tproj/workspace.yaml` も同様に `others` へ修正が必要。
- `tproj` 起動時にリモートパスの存在チェック（`ssh host test -d path`）を追加すると、typo を早期検知できる。
