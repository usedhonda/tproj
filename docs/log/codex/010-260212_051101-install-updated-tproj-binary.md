# tproj 反映漏れ対応

- 指示内容:
  - 「再起動しても変わらない。インストールしていないのか？」の確認と対応。

- 実施内容:
  - `which -a tproj` で実行実体が `~/bin/tproj` であることを確認。
  - `cmp -s ./bin/tproj ~/bin/tproj` で不一致（古いバイナリ）を確認。
  - `~/bin/tproj` には `build_pane_label` / `select-pane -T` が無いことを確認。
  - `cp ./bin/tproj ~/bin/tproj && chmod +x ~/bin/tproj` で `tproj` 単体を更新。
  - 更新後に `build_pane_label` / `select-pane -T` が `~/bin/tproj` に存在することを確認。

- 課題、検討事項:
  - 今後同様の反映漏れを防ぐには、`./install.sh` 実行または `bin/tproj` 更新時のデプロイ手順を明文化するのが有効。
