# WiFi切替時のSSH経由tmux幽霊入力: 多層防御

## 指示

WiFi切替時にSSH経由のリモートtmuxでエスケープシーケンスが生テキストとして表示される問題への多層防御を実装。

## 作業

### 1. tmux.conf に `set-clipboard external` 追加

- `config/tmux/tmux.conf:12` に追加
- tmuxがOSC 52をパースせず外部ターミナルにそのまま通すことで、断片化の影響を軽減

### 2. ユーザーへの手動変更案内（tprojスコープ外）

以下はセキュリティ関連/リポジトリ外ファイルのため手動変更が必要:

#### SSH Config (`~/.ssh/config`)
```
Host dev01
  ServerAliveInterval 15
  ServerAliveCountMax 2
  TCPKeepAlive yes
```

#### Ghostty Config (`~/.config/ghostty/config`)
```
shell-integration-features = cursor,sudo,title,ssh-terminfo
```

#### リモート側確認
```bash
tmux show -s escape-time    # -> 10
tmux show -g focus-events   # -> off
```

## 変更ファイル

- `config/tmux/tmux.conf:12` - `set -s set-clipboard external` 追加

## 課題

- SSH Config, Ghostty Config はtprojスコープ外のためユーザー手動変更が必要
- リモート側のtmux設定が古い場合、tmux kill-server + 再起動が必要
- 根本対策(mosh/et)は今回のスコープ外
