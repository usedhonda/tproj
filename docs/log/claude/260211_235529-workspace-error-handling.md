# tproj ワークスペースモード エラーハンドリング改善

**日時**: 2026-02-11 23:55:29
**対応者**: Claude Sonnet 4.5

## 問題

ワークスペースモードで起動したが、Claude Code も Codex も起動しなかった。

**報告された現象:**
- 両方のペインにシェルがあるだけ
- ツールが起動していない
- エラーメッセージがわかりづらい

## 原因

1. **ペイン ID 取得エラー**: `start_workspace_tools` 関数でペイン ID が取得できなかった場合のエラーハンドリングがなかった
2. **エラーメッセージ不足**: YAML パースエラーや依存関係エラーのメッセージがわかりづらかった

## 実装した修正

### 1. ペイン ID 取得エラーハンドリング

**ファイル**: `bin/tproj` (line 177-191)

```bash
# ペイン ID 取得（エラーチェック付き）
local claude_pane=$(tmux list-panes -t "$session:dev" -F '#{pane_id}:#{@role}' \
  | grep ":claude-p$i$" | cut -d: -f1)
local codex_pane=$(tmux list-panes -t "$session:dev" -F '#{pane_id}:#{@role}' \
  | grep ":codex-p$i$" | cut -d: -f1)

if [[ -z "$claude_pane" ]]; then
  echo "Error: Cannot find claude-p$i pane for project: $project" >&2
  echo "Available panes:" >&2
  tmux list-panes -t "$session:dev" -F '#{pane_id}:#{@role}' >&2
  continue
fi

if [[ -z "$codex_pane" ]]; then
  echo "Error: Cannot find codex-p$i pane for project: $project" >&2
  echo "Available panes:" >&2
  tmux list-panes -t "$session:dev" -F '#{pane_id}:#{@role}' >&2
  continue
fi
```

**効果:**
- ペイン ID が取得できない場合は、エラーメッセージを表示してスキップ
- 利用可能なペイン一覧を表示してデバッグを容易にする

### 2. 最初の Claude ペイン選択エラーハンドリング

**ファイル**: `bin/tproj` (line 221-225)

```bash
# 最初の Claude ペインを選択
local first_claude=$(tmux list-panes -t "$session:dev" -F '#{pane_id}:#{@role}' \
  | grep ':claude-p1$' | cut -d: -f1)

if [[ -n "$first_claude" ]]; then
  tmux select-pane -t "$first_claude"
fi
```

**効果:**
- ペイン選択失敗時もエラーで止まらない

### 3. YAML パースエラーメッセージ改善

#### yq がない場合

**変更前:**
```
Error: yq is required for workspace mode
Install with: brew install yq
```

**変更後:**
```
❌ Error: yq is not installed (required for workspace mode)

Options:
  1. Install yq:    brew install yq
  2. Use single mode: tproj -s
  3. Remove workspace.yaml to disable workspace mode
```

#### YAML 構文エラー

**変更前:**
```
Error: Invalid YAML syntax in ~/.config/tproj/workspace.yaml
Please fix the syntax or remove the file to use single-project mode
```

**変更後:**
```
❌ Error: Invalid YAML syntax in ~/.config/tproj/workspace.yaml

Options:
  1. Fix the YAML syntax
  2. Use single mode: tproj -s
  3. Remove workspace.yaml to disable workspace mode
```

### 4. プロジェクトパス検証メッセージ改善

**変更前:**
```
Warning: Skipping non-existent path: /path/to/project
```

**変更後:**
```
📋 Workspace mode: ~/.config/tproj/workspace.yaml
  ✅ /path/to/valid/project
  ⚠️  Skipping non-existent: /path/to/invalid/project
```

**効果:**
- どのプロジェクトが有効で、どれが無効かが一目でわかる
- ワークスペースモードが有効であることを明示

### 5. プロジェクトが1つもない場合

**変更前:**
```
Error: workspace.yaml exists but contains no projects
```

**変更後:**
```
❌ Error: workspace.yaml exists but contains no projects

Example workspace.yaml:
  projects:
    - /path/to/project1
    - /path/to/project2
```

**効果:**
- 正しい YAML の書き方を例示

### 6. 有効なプロジェクトが0の場合

**変更前:**
```
Error: No valid project directories found
```

**変更後:**
```
❌ Error: No valid project directories found

Options:
  1. Fix project paths in ~/.config/tproj/workspace.yaml
  2. Use single mode: tproj -s
```

### 7. プロジェクト数警告

**変更前:**
```
Warning: You have 6 projects configured.
This may make panes very narrow. Consider using fewer projects.
Continue anyway? [y/N]
```

**変更後:**
```
⚠️  Warning: 6 projects configured (panes may be narrow)
Continue anyway? [y/N]
Tip: Use 'tproj -s' for single-project mode
```

**効果:**
- より簡潔でわかりやすいメッセージ
- キャンセル時に `-s` オプションのヒントを表示

### 8. リモートモード非対応エラー

**変更前:**
```
Error: Remote mode (-r) is not supported in workspace mode
Please use single-project mode or remove -r option
```

**変更後:**
```
❌ Error: Remote mode (-r) is not supported in workspace mode

Options:
  1. Use single mode: tproj -s -r <host>
  2. Remove -r option for local workspace mode
```

**効果:**
- 具体的なコマンド例を提示

## 単一モード強制（`-s` オプション）

既に実装済みの `-s, --single` オプションで、workspace.yaml がある状態でも従来の単一モードで起動できます。

```bash
tproj -s           # 単一モード強制（workspace.yaml を無視）
tproj -s -n        # 単一モード + アップデートなし
tproj -s -r host   # 単一モード + SSH リモート接続
```

## 変更ファイル

- `bin/tproj` (line 40-112, 164-225)
  - エラーハンドリング追加
  - エラーメッセージ改善
  - 絵文字と構造化されたメッセージで視認性向上

## デプロイ

```bash
./install.sh
```

設定が `~/bin/tproj` に反映されました。

## 検証項目

### エラーメッセージ確認
- [ ] yq がない状態で起動 → わかりやすいエラーメッセージ
- [ ] YAML 構文エラー → わかりやすいエラーメッセージ
- [ ] 存在しないパス → 警告表示 + 有効なプロジェクトのみ起動
- [ ] プロジェクトが0 → わかりやすいエラーメッセージ + 例示
- [ ] 6プロジェクト以上 → 警告 + ヒント表示

### 単一モード強制
- [ ] `tproj -s` で workspace.yaml を無視して単一モード起動
- [ ] `tproj -s -n` でアップデートなし起動
- [ ] `tproj -s -r host` でリモート接続

### ワークスペースモード
- [ ] 1プロジェクトで起動 → Claude Code + Codex が起動
- [ ] 2プロジェクトで起動 → 各列で Claude Code + Codex が起動
- [ ] ペイン ID 取得失敗時 → エラーメッセージ + 利用可能なペイン一覧表示

## 次の改善案

1. **デバッグモード**: `-v, --verbose` オプションで詳細ログを表示
2. **ドライラン**: `-d, --dry-run` オプションでレイアウト確認のみ
3. **ログファイル**: `~/.cache/tproj/tproj.log` にエラーログを保存
4. **ヘルプメッセージ**: `tproj -h` で使い方を表示

## まとめ

エラーハンドリングとエラーメッセージを大幅に改善しました。これにより:

1. **問題の早期発見**: ペイン ID が取得できない場合に即座にエラー表示
2. **わかりやすい解決策**: エラーごとに具体的な対処法を提示
3. **視認性向上**: 絵文字と構造化されたメッセージで状況が一目でわかる
4. **単一モード強制**: `-s` オプションで従来の動作を維持

これで、ワークスペースモードでの起動が失敗した場合も、原因と解決策がすぐにわかるようになりました。
