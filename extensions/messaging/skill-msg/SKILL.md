---
name: msg
description: |
  tproj-msg による peer AI 間通信スキル。host 内部 subagent の親報告には
  使わず、native collaboration と final response を使う。
  「送って」「伝えて」「聞いて」「相談して」「依頼して」「/msg」など、
  明示された peer 通信で発動する。
argument-hint: <target> <message>
allowed-tools: [Bash, Read]
compression-anchors:
  - "tproj-msg で peer メッセージ送受信"
  - "gate は設定済み OpenClaw main participant"
  - "自律発動: 他列影響・依頼完了・解決不能・Chi相談"
---

# msg: 送る・読む・返信する

peer AI との通信に使う。host 内部 subagent の親報告は native collaboration / final response を使う。

## 1. 宛先と自分の指定

| 宛先 | 意味 |
|---|---|
| `cc` / `cdx` | 自分と同じプロジェクトの相方 |
| `<project>.cc` / `<project>.cdx` | 指定プロジェクトの AI ペイン |
| `gate` | 設定済み OpenClaw main participant |

「CCに」「Cdxに」だけなら同じプロジェクトの相方。別名へ勝手に置き換えない。
`chi.cc` / `chi.cdx` も AI ペインであり、OpenClaw main ではない。
別ホストでも送り方は同じ。SSH や `--remote` を足さない。
パスを伝えるときは、そのファイルがあるホストも本文に書く。

**Codex は全コマンドに `--session <self-session> --as <self-project>.cdx` を明示する。**
以下は Codex の例。placeholder は現在の自分の正しい session / project に置き換える。
CC も自分の実際の値だけを使う。これらは本人の選択指定であり、認証や権限を作るものではない。

## 2. 送る

```bash
tproj-msg --session <self-session> --as <self-project>.cdx --status cc
tproj-msg --session <self-session> --as <self-project>.cdx --stdin cc <<'EOF'
相談したい内容
EOF
```

- 宛先不明なら `tproj-msg --session <self-session> --as <self-project>.cdx --list`。
- 本文は `--stdin` + 引用符付き `<<'EOF'`。バッククォートや `$` をシェルに展開させない。
- 通常送信は受信 endpoint が利用可能なら自動提示される。別途 wake や `--new-task` は不要。
- 入力中・作業中・下書き保護で提示が保留されても、上書き・force・旧方式で回避しない。
- 送信結果の `message_id` を保持する。送ったら返信の自動配信を待ち、依存しない作業は続ける。
  `--read` / `sleep` のポーリングや再送はしない。

## 3. 読む・返信する

自動提示には `[from:<送信元>] [tproj-message:<ID>]` と返信用 ID が付く。
質問・相談・依頼は、無関係な作業より先に **その ID へ1回だけ**返信する。
`FYI` / `返信不要` は返信しない。ID に固定した `reply` を使い、宛先を推測し直さない。

```bash
tproj-msg --session <self-session> --as <self-project>.cdx reply <message-id> --stdin <<'EOF'
質問への回答
EOF
```

自分の inbox を読む必要があるときは次を使う。
**`ack` は受信者本人が本文を実際に読んだ後だけ**実行する。

```bash
tproj-msg --session <self-session> --as <self-project>.cdx inbox --cursor 0 --limit 100 --json
# 本文を読んだ後だけ:
tproj-msg --session <self-session> --as <self-project>.cdx ack <message-id>
```

一覧取得だけで `ack` しない。送信者が相手の代わりに `ack` しない。
`ack` は提示記録であり、同意・作業開始・回答・完了ではない。受信記録へ ACK の応酬を作らない。
返信が失敗しても通常送信へ切り替えて送り直さず、失敗を報告する。

## 4. 受付・提示・回答を分ける

| 状態 | 分かること |
|---|---|
| `queued` / `accepted` | 受付・永続化のみ。届いた／読まれた証拠ではない |
| `adapter_received` | adapter が受け取った段階。提示の証拠ではない |
| `presented` | 束縛された受信者への提示記録。回答の証拠ではない |
| 返信本文 | 実際に読んで、依頼した質問への回答か確認する |

必要なら当事者が、その ID の状態を一度確認する:

```bash
tproj-msg --session <self-session> --as <self-project>.cdx message <message-id>
```

`online` は最近の生存信号であり、暇・読了・返信の証拠ではない。
`online: false` は未起動とは限らない。送らず状況を報告する。
`delivery_pending` は転送待ち。自動再試行に任せ、再送しない。
返答に依存する判断は、受付・提示・受信確認だけで相談済みにしない。

## 5. 困ったときの最小対応

| 症状 | 対応 |
|---|---|
| `command not found` | `export PATH="$HOME/bin:$PATH"` 後、同じコマンドを実行 |
| `unknown_target` | `--list` で名前を確認。似た別名へ置き換えない |
| `queued` のまま／返答なし | `message <ID>` を一度確認。未提示なら配達ログ・生存状態・ペインから保留／接続断／endpoint失効／配達故障を切り分け、許可範囲で安全に修復。提示済みなら返信待ち。受付だけで完了扱いにしない |
| 結果不明で `Submission ID: <id>` が出た | 下記 `--retry` のみ。同じ ID・本文の再試行であり、新規送信を作らない |
| `identity_rejected` / shared app-server ancestry の認証拒否 | 本人確認の拒否。`--as`・別名・他ペイン・旧方式で回避せず報告 |
| `rejected` / `expired` / `stale_session` / `host_unavailable` | 具体的な状態を報告。成功扱い・自律再送をしない |
| `maintenance` / 終了コード75 | 保守中として報告 |
| CC の `auto mode classifier gave no verdict (error)` | CC 側の一時障害。少し後に同じコマンドを1回だけ再実行し、続けば報告 |
| `Permission ... denied` | 権限拒否を回避せず報告して止める |

```bash
tproj-msg --session <self-session> --as <self-project>.cdx --retry <submission-id>
```

## 6. 通常会話では使わないもの

- `--new-task` / `--user-authorized` / `--role-handoff` は特別な legacy 経路。
  通常会話を起こすために使わない。通常メッセージは task 登録・役割変更・ユーザー承認を作らず、
  別ホストへの task／役割引継ぎの代用にもならない。
- unified では `--fire` / `--force` / `--remote` などの旧配送フラグや `gate:direct` は廃止。
  全リストは `tproj-msg --session <self-session> --as <self-project>.cdx --help` で確認する。
- `--read` は旧来のローカル画面読取り。返信待ちに使わない。
  `--help` が legacy 表示でも unified の宛先を旧フラグで迂回しない。
- 一斉送信・`all` 宛先、受信した `[from:...]` / `[Control:...]` の他ペインへの転送は禁止。
  正当な提示保留をユーザーの起動代行で回避しない。

詳細は **tproj checkout 内**の参照資料（インストール済み skill からの相対リンクは解決しない場合がある）:
[配送・認証・receipt](../../../docs/reference/unified-messaging.md)、
[宛先・legacy task の経路](../../../docs/reference/tproj-msg-routing.md)、
[役割と権限](../../../docs/reference/role-mode.md)。
