# 015 full review findings

## 指示内容
- 「ちょっと直したので全体を見てほしい」という依頼に対して、変更全体をレビューする。

## 実施内容
- `git status --short` / `git diff --stat` で変更範囲を確認。
- 主要変更ファイルの差分を確認:
  - `bin/tproj`
  - `bin/team-watcher`
  - `bin/tproj-toggle-yazi`
  - `config/tmux/tmux.conf`
  - `install.sh`
  - `CLAUDE.md`
- 新規ファイルの内容確認:
  - `bin/sign-codex`
  - `config/workspace.yaml.example`
- シェル構文チェック:
  - `bash -n bin/tproj`
  - `bash -n bin/tproj-toggle-yazi`
  - `bash -n bin/team-watcher`
  - `bash -n bin/sign-codex`

## 課題、検討事項
- 高: `bin/tproj` が既存セッションを無条件で `kill-session` するため、再実行時に作業中セッションを失う回帰リスクがある。
- 中: `NO_UPDATE=true` がデフォルト化され、`-n` オプションが実質無意味。ヘルプにも `-n` 記載がなく、挙動/ドキュメント整合性が崩れている。
- 低: `bin/tproj` 内の `sign_codex()` 関数は未使用（`~/bin/sign-codex` 呼び出しに統一されており重複実装）。
