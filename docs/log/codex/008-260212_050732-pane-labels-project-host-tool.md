# tproj ペインラベル表示 実装ログ

- 指示内容:
  - tproj 起動時に、各ペインラベルへ「プロジェクト名（ディレクトリ名）」「ホスト名」「CC/Codex」を表示する実装を行う。
  - 仕様は計画どおり: Claude/Codexのみ、形式は `[host] project | CC/Codex`。

- 実施内容:
  - `bin/tproj` に `build_pane_label()` を追加。
    - 引数: `project_type`, `project_host`, `project_path`, `tool_kind`
    - 出力: `[host] project | tool_kind`
    - local時は host=`local`、remote時は host=`project_host`。
  - ワークスペースモード (`create_workspace_layout`) で、各列の `claude-p*` / `codex-p*` に `tmux select-pane -T` を設定。
  - 単一モードで、`dev.1`(Claude) / `dev.2`(Codex) に `tmux select-pane -T` を設定。
    - `-r` 使用時は remote host、未指定時は local を表示。
  - yazi/git ペインにはタイトル設定しない（対象外）。
  - 構文検証: `zsh -n bin/tproj` を実行し、エラーなしを確認。

- 課題、検討事項:
  - `bin/tproj` は既存で大きな差分を含むため、今回変更のレビュー時は `build_pane_label` 追加箇所と `select-pane -T` 追加箇所に絞って確認するのが安全。
  - 実機確認（tmux表示）として、単一/ワークスペース/remote の3パターンで `#{pane_title}` を目視確認するのが次の妥当な検証。
