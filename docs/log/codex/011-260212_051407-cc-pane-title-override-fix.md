# 011 CC pane title override fix

## 指示内容
- ペインタイトルで Codex は正しく表示されるが、CC だけうまくいかない問題を調査・修正する。
- 実行中に表示されるタイトル上書きの原因を特定し、反映漏れ（インストール先との不一致）があれば解消する。

## 実施内容
- 現在の tmux 状態を確認し、`claude-p*` の `pane_title` が `✳ Claude Code` に戻されることを確認。
- `bin/tproj` のタイトル設定箇所を確認し、`tmux select-pane -T` のみで固定していたことを確認。
- 原因を `Claude 側の OSC タイトル送信による上書き` と特定。
- `bin/tproj` を修正:
  - ワークスペースモードの `claude-p*` 作成時に `tmux set-option -pt "$claude_pane" allow-set-title off` を追加。
  - 単一モードの `dev.1 (claude)` にも同様の `allow-set-title off` を追加。
- 構文チェック (`bash -n bin/tproj`) を実施し問題なしを確認。
- 実行中コマンドが `/Users/usedhonda/bin/tproj` で、リポジトリ版と差分があることを確認。
- `/Users/usedhonda/bin/tproj` へ最新 `bin/tproj` を再配置し、実行バイナリを同期。
- 実 tmux セッションで `allow-set-title off` を適用後、`claude-p1..p3` のタイトルが `...[...] | CC` で保持されることを確認。

## 課題、検討事項
- 既存セッションには設定が自動反映されないため、完全反映には `tproj` 再起動（新規セッション作成）が必要。
- 将来的には `install.sh` 実行有無に依存しないよう、`tproj` 実体の参照先（`~/bin` とリポジトリ内）を一本化すると運用事故が減る。
