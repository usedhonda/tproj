# Agent Teams reflow 修正レビュー

- 指示内容:
  - 実装せず、`team-watcher` / `reflow-agent-pane` の今回修正をレビューする。
  - 主な懸念点:
    1. TeamCreate hook 時点で split 前に幅保存できているか
    2. 複数エージェントで再崩れしないか
    3. 見落としの有無

- 実施内容:
  - `bin/team-watcher` の Phase 1 を確認 (`bin/team-watcher:13-25`)。
    - `TPROJ_AGENTS_ACTIVE=1` 設定後に `claude` 幅を取得し、`TPROJ_CLAUDE_WIDTH` に保存 (`bin/team-watcher:17-19`)。
    - その後 `after-split-window` hook を設定 (`bin/team-watcher:24-25`)。
  - `bin/reflow-agent-pane` を確認 (`bin/reflow-agent-pane:34-66`)。
    - `CLAUDE_PANE` は `@role=claude` で特定。
    - `TPROJ_CLAUDE_WIDTH` を読み出して `resize-pane -x` で復元。
  - レビュー判定:
    - 方向性は正しい。旧方式より「崩壊後の幅を保存してしまう」問題を解消している。
    - ただし、環境変数の未設定/削除時の扱いに不備がある。

- 課題、検討事項:
  - 重大度: Medium
    - `TPROJ_CLAUDE_WIDTH` が未設定または削除済みの場合、`tmux show-environment` は `-TPROJ_CLAUDE_WIDTH` を返し得る。
      現行実装は `cut -d= -f2` だけなので、その文字列が `CLAUDE_WIDTH` に入りうる (`bin/reflow-agent-pane:42`)。
      その結果 `resize-pane -x` は失敗し、`|| true` で握りつぶされるため、幅復元が silently skip される。
      対応案: `show-environment` の戻り値が数値かどうかを検証してから `resize-pane`。
  - 重大度: Medium
    - 幅スナップショットが TeamCreate 時点で 1 回固定のため、チーム実行中にユーザーが手動で `claude` 幅を変更すると、次の reflow で古い幅へ戻される。
      対応案: 「チーム実行中は固定幅ポリシー」と明記するか、手動変更を新しい基準幅として更新する運用を設ける。
  - 重大度: Low
    - `CLAUDE_W` 取得が `grep '^claude:' | cut -d: -f2` 依存 (`bin/team-watcher:17-18`)。
      role 不整合や複数一致時に想定外値を拾う可能性があるため、1件に限定するガードがあるとより堅牢。

- 懸念点への回答:
  - TeamCreate 時点が split 前か:
    - 現在の 2 フェーズ構成（Phase 1 同期完了後に制御返却）と整合しており、設計意図としては split 前保存になっている。
    - ただしこれは `TeamCreate` フックが本当に同期実行であることが前提。設定が `async` に戻ると再発。
  - 複数エージェントで再崩れするか:
    - 毎回同じ `TPROJ_CLAUDE_WIDTH` に戻すため、理論上は2人目以降の split でも復元可能。
    - ただし前述の「手動リサイズ上書き」仕様は残る。
  - その他の見落とし:
    - `show-environment` 未設定時の値検証不足が最重要の残課題。
