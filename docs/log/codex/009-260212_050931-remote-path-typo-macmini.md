# remote path エラー調査（macmini）

- 指示内容:
  - `ssh macmini` で接続確認し、`cd ... openclaw_general` 失敗の原因を調査。

- 実施内容:
  - `ssh macmini 'ls -ld /Users/usedhonda/projects/other/openclaw_general'` を実行。
    - 結果: `No such file or directory`
  - `ssh macmini` 側で `find /Users/usedhonda/projects -maxdepth 3 -type d -name 'openclaw*'` を実行。
    - 結果: 実在は `/Users/usedhonda/projects/others/openclaw_general`

- 課題、検討事項:
  - `~/.config/tproj/workspace.yaml` の remote path が `.../projects/other/openclaw_general` になっており typo。
  - 正しくは `.../projects/others/openclaw_general`。
