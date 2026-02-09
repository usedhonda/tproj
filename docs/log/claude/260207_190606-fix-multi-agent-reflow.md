# Agent Teams 複数エージェント spawn 時のレイアウト崩壊修正

## 指示
Agent Teams で2人以上のエージェントを spawn した際にレイアウトが崩壊する3つのバグを修正。

## 作業内容

### bin/reflow-agent-pane (全面書き換え)
- flock による排他制御を削除（呼び出し側の `wait-for -L/U` が担当）
- 単一ペイン処理 -> 未タグ全ペインループに変更（バースト spawn の一括処理）
- Codex ペイン検索にリトライ追加（最大2秒、0.5秒x4回）

### bin/team-watcher
- フック設定を `run-shell -d 0.3` + `wait-for -L/U tproj-reflow` に変更
  - `-d 0.3`: バースト spawn をコアレス
  - `wait-for -L/U`: tmux ネイティブロックで直列化
- `in_array()` 関数削除（行36-44）
- `KNOWN_AGENTS` 配列削除（行10, 79-80, 85, 95）
- cleanup から lock file 削除処理を除去（行32）

## 変更ファイル
- `bin/reflow-agent-pane` - 全面書き換え
- `bin/team-watcher` - フック設定変更 + KNOWN_AGENTS 関連削除

## 根本原因
1. `flock -n` で2つ目の reflow が即 exit -> ペイン移動されない
2. `in_array` + `KNOWN_AGENTS` が2サイクル目以降のタグ付けをブロック
3. Codex ペイン未検出時に即 exit -> 全ペイン未配置

## 検証手順
1. `./install.sh` で再デプロイ -> 完了
2. `tmux kill-session -t tproj && tproj` で新規起動
3. Claude Code 内で TeamCreate + 2人の teammate を spawn
4. 両エージェントが Codex の上に配置されることを確認
