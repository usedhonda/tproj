# yazi クリップボードコピー機能の修正

**日時**: 2026-02-11 16:05:48
**対応者**: Claude Sonnet 4.5
**関連コミット**: c685e69 (pbcopy → OSC 52 変更)

## 問題

yazi の `p` キー（ファイルパスをクリップボードにコピー）がローカル環境で動かなくなった。

**原因**:
- コミット c685e69 で pbcopy → OSC 52 に変更
- Lua 文字列 `'\\033]52;c;%s\\a'` がシェルに渡される際、シングルクォートで囲まれるため、エスケープシーケンスが解釈されず、リテラル文字列 `\033` (4文字) として出力される
- 正しくは ESC バイト (`0x1b`) を出力する必要がある

## 実装した修正

**アプローチ**: 環境検出方式
- ローカル: pbcopy を使用（高速・確実）
- SSH: OSC 52 を使用（ANSI-C quoting で修正）
- 環境判定: `SSH_CONNECTION` 環境変数の有無

### 変更ファイル

1. **config/yazi/plugins/copy-path.yazi/main.lua** (11-20行目)
   ```lua
   -- Check if we're in SSH session
   local ssh_connection = os.getenv("SSH_CONNECTION")

   if ssh_connection then
     -- SSH: Use OSC 52 with ANSI-C quoting for proper escape interpretation
     ya.emit("shell", { "printf $'\\033]52;c;%s\\007' $(echo -n " .. ya.quote(path) .. " | base64)" })
   else
     -- Local: Use pbcopy (reliable and fast)
     ya.emit("shell", { "printf %s " .. ya.quote(path) .. " | pbcopy" })
   end
   ```

2. **config/yazi/plugins/copy-file.yazi/main.lua** (16-26行目)
   ```lua
   -- Check if we're in SSH session
   local ssh_connection = os.getenv("SSH_CONNECTION")

   if ssh_connection then
     -- SSH: Use OSC 52 with ANSI-C quoting for proper escape interpretation
     ya.emit("shell", { "printf $'\\033]52;c;%s\\007' $(cat " .. ya.quote(path) .. " | base64)" })
   else
     -- Local: Use pbcopy (reliable and fast)
     ya.emit("shell", { "cat " .. ya.quote(path) .. " | pbcopy" })
   end
   ```

### 技術的詳細

**ANSI-C quoting (`$'...'`)**:
- bash/zsh で ANSI-C エスケープシーケンスを解釈
- Lua の `\\033` → シェルの `\033` → ESC バイト (`0x1b`)
- `\\007` → `\007` → BEL バイト (OSC 52 終端文字)
- シングルクォート `'...'` では解釈されない（今回の問題の原因）

**環境検出**:
- `SSH_CONNECTION`: SSH 接続時に自動設定される環境変数
- 値: `client_ip client_port server_ip server_port`
- ローカル実行時は未設定（`nil`）

## デプロイ

```bash
./install.sh
```

設定が `~/.config/yazi/` にデプロイされた。

## 検証手順

### ローカル環境
1. `tproj` で tmux セッション起動（SSH なし）
2. yazi ペインでファイルを選択
3. `p` を押す → パスがクリップボードにコピーされること
4. `c` を押す → ファイル内容がクリップボードにコピーされること
5. `pbpaste` または Cmd+V で確認

### SSH 環境
1. `tproj -r macmini` でリモート接続
2. yazi ペインでファイルを選択
3. `p` を押す → パスが**ローカルマシン**のクリップボードにコピーされること
4. `c` を押す → ファイル内容が**ローカルマシン**のクリップボードにコピーされること
5. ローカルマシンで Cmd+V で確認

### デバッグコマンド

```bash
# SSH 状態確認
echo $SSH_CONNECTION

# pbcopy テスト（ローカル）
echo "test local" | pbcopy && pbpaste

# OSC 52 テスト（SSH）
printf $'\033]52;c;%s\007' $(echo -n "test" | base64)
# ローカルマシンで Cmd+V → "test" がペーストされること
```

## 既知の制限事項

1. **OSC 52 サイズ制限**: 約75KB（デコード後）
   - ファイルコピー (`c`) は大きいファイルで失敗する可能性（SSH時のみ）
   - パスコピー (`p`) は問題なし（パスは短い）

2. **OSC 52 対応ターミナル**:
   - 動作: Ghostty, Kitty, WezTerm, Alacritty, iTerm2
   - 非対応: GNOME Terminal, 古い Terminal.app

## 今後の改善案

1. **大容量ファイル対応** (SSH時):
   - OSC 52 サイズ制限を超えた場合の警告表示
   - または、scp/rsync でのファイル転送を提案

2. **エラーハンドリング**:
   - OSC 52 非対応ターミナルの検出
   - コピー失敗時のフォールバック処理

## 参考資料

- [OSC 52 specification](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h3-Operating-System-Commands)
- [ANSI-C quoting (bash)](https://www.gnu.org/software/bash/manual/html_node/ANSI_002dC-Quoting.html)
- [Ghostty OSC 52 support](https://ghostty.org/docs/features/clipboard)
