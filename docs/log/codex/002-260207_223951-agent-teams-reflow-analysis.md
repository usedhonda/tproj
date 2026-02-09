# Agent Teams reflow 調査ログ

- 指示内容:
  - 実装は行わず、tproj の Agent Teams ペイン reflow の現方式を評価する。
  - 質問への回答:
    1. `resize-pane -x` 方式の妥当性
    2. より良い方式の有無（Agent Teams 側 split 制御含む）
    3. `kill-pane` 後のスペース回収先制御の可否

- 実施内容:
  - `bin/reflow-agent-pane` を確認し、現行実装が以下であることを確認。
    - split+swap+kill 方式 (`bin/reflow-agent-pane:55-61`)
    - Claude 幅復元 `resize-pane -x` (`bin/reflow-agent-pane:65-67`)
  - `bin/team-watcher` を確認し、`after-split-window` フックで reflow を直列実行していることを確認 (`bin/team-watcher:19-20`)。
  - `docs/reference/agent-teams.md` を確認し、`teammateMode` が `auto/in-process/tmux` の3種のみで、tmux split の方向やターゲットペインを制御する設定が記載されていないことを確認 (`docs/reference/agent-teams.md:91-96`, `docs/reference/agent-teams.md:155-157`)。
  - 評価結果:
    - `resize-pane -x` は現象に対する実務的な対処として妥当。
    - ただし「kill 後の回収先」を直接制御しているのではなく、回収後に目標幅へ補正するアプローチ。
    - Agent Teams 側で split 方向/配置先を直接制御する手段は、現時点のプロジェクト資料上は見当たらない。

- 課題、検討事項:
  - `resize-pane -x` の注意点:
    - 端末幅が急変した直後など、指定幅を確保できない場合は補正しきれない可能性がある。
    - ただし失敗時も `|| true` で安全に継続するため、運用上は壊れにくい。
  - 代替候補（実装は未着手）:
    - `select-layout main-vertical` + `main-pane-width` を基準化して、再配置後にレイアウト規約へ戻す方式。
    - Agent Teams の表示モードを `in-process` に切り替えて tmux split 自体を回避（同時可視性とのトレードオフ）。
  - `kill-pane` 後の回収先制御:
    - tmux はレイアウトツリー上の sibling へ領域を返す挙動で、`kill-pane` 単体に「回収先指定」オプションはない。
    - 制御したい場合は、事前にレイアウト構造を作る（どの sibling に吸わせるかを構造で決める）か、事後に `resize-pane` / `select-layout` で補正する運用が現実的。
