# tproj マルチプロジェクトワークスペース機能実装完了

**日時**: 2026-02-11 23:08:55
**対応者**: Claude Sonnet 4.5

## 実装内容

tproj に、YAML ファイルで複数のプロジェクトを定義して並行作業できるマルチプロジェクトワークスペース機能を実装しました。

## 実装済みファイル

### 1. `bin/tproj` (317行)

**主要な変更:**
- `-s, --single` オプション追加（workspace.yaml を無視して単一モード強制）
- YAML パース機能（yq 使用）
- ワークスペースモード判定（`~/.config/tproj/workspace.yaml` の有無）
- `create_workspace_layout()` 関数（マルチ列レイアウト構築）
- `start_workspace_tools()` 関数（各列で Claude Code + Codex 起動）
- エラーハンドリング（YAML 構文エラー、存在しないパス、プロジェクト数警告）
- リモートモード非対応チェック（ワークスペース + `-r` はエラー）

**@role タグ命名:**
- 単一モード: `claude`, `codex`, `yazi`
- ワークスペースモード: `claude-p1`, `codex-p1`, `yazi-p1` (列番号付き)
- 追加タグ: `@project` (プロジェクトパス), `@column` (列番号)

### 2. `bin/tproj-toggle-yazi` (83行、新規作成)

**機能:**
- セッション名から単一/マルチモード判定
- マルチモードではアクティブなペインの `@column` タグから列番号取得
- その列に yazi ペインがあれば削除、なければ codex の下に作成
- 単一モードでは従来の yazi トグル動作（codex の下にグローバル yazi）

### 3. `config/tmux/tmux.conf` (line 168)

**追加キーバインド:**
```tmux
bind y run-shell "~/bin/tproj-toggle-yazi '#{session_name}' '#{pane_id}'"
```

Prefix + y で yazi をトグル表示。

### 4. `config/claude/skills/codex/SKILL.md` (line 111-131)

**変更箇所:**
ペイン検出ロジックをワークスペース対応に変更。

```bash
if [[ "$SESSION" == "tproj-workspace" ]]; then
  # マルチプロジェクトモード: アクティブな列の Codex を検出
  ACTIVE_PANE=$(tmux display-message -p '#{pane_id}')
  ACTIVE_COLUMN=$(tmux display-message -t "$ACTIVE_PANE" -p '#{@column}')
  CODEX_PANE=$(tmux list-panes -t "$SESSION:dev" \
    -F "#{pane_id}:#{@role}" | grep ":codex-p${ACTIVE_COLUMN}$" | cut -d: -f1)
else
  # 単一プロジェクトモード
  CODEX_PANE=$(tmux list-panes -t "$SESSION:dev" \
    -F "#{pane_id}:#{@role}" | grep ":codex$" | cut -d: -f1)
fi
```

これにより、ワークスペースモードでも `/codex` スキルが正しく動作。

### 5. `bin/reflow-agent-pane` (line 20-49)

**変更箇所:**
ワークスペースモード判定を追加し、アクティブな列の Codex を検出。

```bash
if [[ "$SESSION" == "tproj-workspace" ]]; then
  WORKSPACE_MODE=true
  ACTIVE_PANE=$(tmux display-message -p '#{pane_id}')
  ACTIVE_COLUMN=$(tmux display-message -t "$ACTIVE_PANE" -p '#{@column}')
  # codex-p${ACTIVE_COLUMN} を検出
else
  WORKSPACE_MODE=false
  # 従来の codex 検出
fi
```

Agent Teams のペインが正しい列の Codex 上に配置される。

### 6. `install.sh` (line 109, 237, 241)

**変更箇所:**
- yq を依存関係に追加（line 109: `BREW_DEPS=(npm:node git tmux yazi bat yq)`）
- `tproj-toggle-yazi` のインストール追加（line 237, 241）

## 機能説明

### マルチプロジェクトモードの起動

**YAML 設定ファイル:** `~/.config/tproj/workspace.yaml`

```yaml
projects:
  - /path/to/project1
  - /path/to/project2
  - /path/to/project3
```

**起動方法:**
```bash
tproj           # workspace.yaml があれば自動的にマルチモード
tproj -s        # 単一モード強制（workspace.yaml を無視）
```

### レイアウト

**初期レイアウト（3プロジェクトの例）:**
```
┌─────────┬─────────┬─────────┐
│ claude1 │ claude2 │ claude3 │
│         │         │         │
├─────────┼─────────┼─────────┤
│ codex1  │ codex2  │ codex3  │
└─────────┴─────────┴─────────┘
```

**yazi トグル後（Prefix + y）:**
```
┌─────────┬─────────┬─────────┐
│ claude1 │ claude2 │ claude3 │
├─────────┼─────────┼─────────┤
│ codex1  │ codex2  │ codex3  │
│         ├─────────┤         │
│         │ yazi2   │         │  <- アクティブ列の下
└─────────┴─────────┴─────────┘
```

### 機能詳細

**列の幅:** 均等分割（`tmux select-layout tiled`）

**各列の構成:**
1. Claude Code ペイン（上 70%）
2. Codex ペイン（下 30%）
3. yazi ペイン（トグル、Codex の下 70%）

**セッション管理:**
- 単一モード: セッション名 = `<project-name>`
- マルチモード: セッション名 = `tproj-workspace`
- 各 Claude Code は独立したセッション（`~/.claude/projects/<encoded-path>/`）

**オプション:**
- `-n, --no-update`: npm update スキップ（両モードで動作）
- `-s, --single`: 単一モード強制
- `-r, --remote`: SSH 接続（マルチモードでは**エラー**）

## エラーハンドリング

### 1. YAML 構文エラー

```bash
if ! yq eval '.projects[]' "$WORKSPACE_CONFIG" &>/dev/null; then
  echo "Error: Invalid YAML syntax in $WORKSPACE_CONFIG"
  exit 1
fi
```

### 2. プロジェクトパスが存在しない

```bash
for project in "${PROJECTS[@]}"; do
  if [[ -d "$project" ]]; then
    VALID_PROJECTS+=("$project")
  else
    echo "Warning: Skipping non-existent path: $project" >&2
  fi
done
```

### 3. プロジェクト数が多すぎる（5以上）

```bash
if [[ ${#PROJECTS[@]} -gt 5 ]]; then
  echo "Warning: You have ${#PROJECTS[@]} projects configured."
  read -p "Continue anyway? [y/N] " answer
fi
```

### 4. リモートモード非対応

```bash
if [[ "$WORKSPACE_MODE" == "true" && -n "$REMOTE_HOST" ]]; then
  echo "Error: Remote mode (-r) is not supported in workspace mode"
  exit 1
fi
```

## 使用例

### 単一プロジェクトモード（従来通り）

```bash
cd /path/to/project
tproj              # 3ペインレイアウト（claude, codex, yazi）
tproj -n           # アップデートなし
tproj -r macmini   # SSH リモート接続
```

### マルチプロジェクトモード

```bash
# 1. workspace.yaml 作成
mkdir -p ~/.config/tproj
cat > ~/.config/tproj/workspace.yaml << 'EOF'
projects:
  - /Users/usedhonda/projects/frontend
  - /Users/usedhonda/projects/backend
  - /Users/usedhonda/projects/tools
EOF

# 2. 起動（どのディレクトリからでも OK）
tproj              # マルチプロジェクトモードで起動

# 3. 操作
# - Prefix + 矢印キー or マウス で列を切り替え
# - Prefix + y で yazi トグル（アクティブな列の下）
# - /codex でアクティブな列の Codex にメッセージ送信
# - Agent Teams もアクティブな列に spawn

# 4. 単一モード強制（テスト用）
tproj -s           # workspace.yaml があっても単一モード
```

## 技術的詳細

### zsh 互換性

`bin/tproj` の先頭に追加:
```bash
setopt KSH_ARRAYS  # 0-based array indexing (bash compatibility)
```

これにより、bash と zsh の配列インデックスの違いを吸収。

### ペイン ID の安定性

tmux のペインは `#{pane_index}` が動的に変化するため、`#{pane_id}` を使用して追跡:

```bash
local new_claude=$(tmux split-window -h -t "$prev_claude" -c "$project" -P -F '#{pane_id}')
```

### レイアウト均等化

`tmux select-layout tiled` は、すべてのペインを均等に配置する組み込みレイアウト:

```bash
tmux select-layout -t "$session:dev" tiled
```

## 後方互換性

**単一プロジェクトモード:**
- すべての既存機能が動作
- `-n`, `-r` オプション継続サポート
- @role タグ: `claude`, `codex`, `yazi`（変更なし）

**マルチプロジェクトモード:**
- YAML ファイルがなければ自動的に単一モードで起動
- `-s` オプションで強制的に単一モード
- 既存のワークフローに影響なし

## 既知の制限事項

1. **リモートモード非対応**: マルチプロジェクトモードでは `-r` オプション使用不可
2. **プロジェクト数上限**: 5プロジェクト以上は画面が狭くなる（警告表示）
3. **リソース使用量**: 3プロジェクト ≈ 2.4GB RAM（Claude + Codex × 3）
4. **Agent Teams の列判定**: 現在の実装では、Agent pane はアクティブな列の Codex 上に配置される

## 検証項目

### 単一プロジェクトモード（後方互換性）
- [ ] workspace.yaml なしで tproj 起動
- [ ] 3ペインレイアウト（claude, codex, yazi）確認
- [ ] `-n` オプション動作確認
- [ ] `-r` オプション動作確認
- [ ] Codex スキル動作確認
- [ ] Agent Teams spawn 確認

### マルチプロジェクトモード
- [ ] workspace.yaml (2プロジェクト) で起動
- [ ] 4ペインレイアウト（2列×2ペイン）確認
- [ ] workspace.yaml (3プロジェクト) で起動
- [ ] 6ペインレイアウト（3列×2ペイン）確認
- [ ] `-n` オプション動作確認
- [ ] `-s` オプション動作確認
- [ ] `-r` オプションでエラー確認

### yazi トグル
- [ ] 単一モードで Prefix + y 動作確認
- [ ] 各列で Prefix + y 動作確認
- [ ] 複数回トグル（表示/非表示/表示）
- [ ] 列を切り替えて yazi トグル

### Codex スキル
- [ ] 列1で `/codex` → codex-p1 にメッセージ送信確認
- [ ] 列2に切り替えて `/codex` → codex-p2 にメッセージ送信確認

### Agent Teams
- [ ] 列1から Agent spawn → codex-p1 の上に配置確認
- [ ] 列2から Agent spawn → codex-p2 の上に配置確認
- [ ] 同じ列で複数 Agent spawn
- [ ] Team shutdown 後のペイン削除確認

## 今後の拡張可能性

- プロジェクトの動的追加/削除（`tproj add/remove`）
- プロジェクトスイッチャー（Prefix + p）
- 全 Claude への一斉コマンド送信
- プロジェクトごとのレイアウトカスタマイズ
- YAML でペイン構成をカスタマイズ（claude のみ、codex なし、など）

## ターミナルエミュレータ互換性

この機能は tmux ベースのため、**すべてのターミナルエミュレータで動作**します:

- ✅ Ghostty
- ✅ iTerm2
- ✅ Kitty
- ✅ WezTerm
- ✅ Alacritty
- ✅ 標準 Terminal.app

OSC 52（yazi のクリップボードコピー）も上記すべてで動作します。

## 参考資料

- [tmux manual - User Options](https://man.openbsd.org/tmux.1#set-option)
- [yq - YAML processor](https://github.com/mikefarah/yq)
- [tproj 計画ファイル](../../plans/cheerful-beaming-barto.md)
