# 017 tproj not reflected diagnosis

## 指示内容
- `tproj` の変更が反映されない事象を調査。

## 実施内容
- ローカル環境で `command -v tproj` / `which -a tproj` / `type -a tproj` を確認。
  - 実行先は `/Users/usedhonda/bin/tproj`。
- ローカルの `bin/tproj` と `/Users/usedhonda/bin/tproj` のサイズ・ハッシュを確認。
  - サイズ一致: 27627 bytes
  - SHA1 一致
- `ssh macmini` 側の `~/bin/tproj` を確認。
  - 3135 bytes の旧版スクリプト（`--add` 未実装）を確認。

## 課題、検討事項
- 反映されない現象は、実行場所（ローカルかリモートか）で参照バイナリが異なる可能性が高い。
- 実行中ペインで `command -v tproj` と `tproj --help` を確認し、参照先を特定する必要がある。
