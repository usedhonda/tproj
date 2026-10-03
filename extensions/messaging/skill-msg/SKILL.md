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
| `kai` | 設定済み KAI 接続（AIペインとは別） |

「CCに」「Cdxに」だけなら同じプロジェクトの相方。別名へ勝手に置き換えない。
`chi.cc` / `chi.cdx` も AI ペインであり、OpenClaw main ではない。
別ホストでも送り方は同じ。SSH や `--remote` を足さない。
パスを伝えるときは、そのファイルがあるホストも本文に書く。

送信元は実行中の会話から自動識別する。通常は `--session` / `--as` は不要。
必要なら `tproj-msg whoami` で確認し、識別できないときは `tproj-msg doctor`。
明示する場合も本人の正しい値だけを使う。別名指定で認証や権限は作れない。

## 2. 送る

```bash
tproj-msg --stdin cc <<'EOF'
相談したい内容
EOF
```

- 送信前の `--status` は必須ではない。
- 宛先不明なら `tproj-msg --list`。
- 本文は `--stdin` + 引用符付き `<<'EOF'`。バッククォートや `$` をシェルに展開させない。
- 通常送信は受信 endpoint が利用可能なら自動提示される。wake や `--new-task` は送信経路に存在しない。
- 入力中・作業中・下書き保護で提示が保留されても、上書き・force・旧方式で回避しない。
- 送信結果の `message_id` を保持する。送ったら返信の自動配信を待ち、依存しない作業は続ける。
  `--read` / `sleep` のポーリングや再送はしない。

## 3. 読む・返信する

自動提示には `[from:<送信元>] [tproj-message:<ID>]` と返信用 ID が付く。
質問・相談・依頼は、無関係な作業より先に **その ID へ1回だけ**返信する。
`FYI` / `返信不要` は返信しない。ID に固定した `reply` を使い、宛先を推測し直さない。

```bash
tproj-msg reply <message-id> --stdin <<'EOF'
質問への回答
EOF
```

自分の inbox を読む必要があるときは次を使う。
**`ack` は受信者本人が本文を実際に読んだ後だけ**実行する。

```bash
tproj-msg inbox --cursor 0 --limit 100 --json
# 本文を読んだ後だけ:
tproj-msg ack <message-id>
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
| `uncertain` | 提示結果を確定できない。未配達や入力保護待ちと断定せず、自動再送しない |
| 返信本文 | 実際に読んで、依頼した質問への回答か確認する |

必要なら当事者が、その ID の状態を一度確認する:

```bash
tproj-msg message <message-id>
```

配送調査は `tproj-msg diagnose <ID>` で本文を含まない状態・保留理由を確認できる。
当事者または設定済みの保守担当のみ利用可能。権限拒否を別名やDB直読で回避しない。
`receipt_timeout` は提示確認の時間切れ、`dispatch_error` は配送操作失敗、
`adapter_interrupted` は配送途中のプロセス中断。古い記録の理由は不明のまま扱う。

`online` は最近の生存信号であり、暇・読了・返信の証拠ではない。
`online: false` は未起動とは限らない。送信時の配送結果と具体的なエラーで判断する。
`delivery_pending` は転送待ち。自動再試行に任せ、再送しない。
返答に依存する判断は、受付・提示・受信確認だけで相談済みにしない。

## 5. 困ったときの最小対応

| 症状 | 対応 |
|---|---|
| `command not found` | `export PATH="$HOME/bin:$PATH"` 後、同じコマンドを実行 |
| `unknown_target` | `--list` で名前を確認。似た別名へ置き換えない |
| `queued` のまま／返答なし | `message <ID>` を一度確認。未提示なら配達ログ・生存状態・ペインから保留／接続断／endpoint失効／配達故障を切り分け、許可範囲で安全に修復。提示済みなら返信待ち。受付だけで完了扱いにしない |
| 結果不明で `Submission ID: <id>` が出た | 下記 `--retry` のみ。同じ ID・本文の再試行であり、新規送信を作らない |
| `identity_rejected` | `whoami` / `doctor` で会話登録の不一致を確認。別名・他ペイン・旧方式で回避しない |
| `endpoint_unavailable` | 宛先ホストの生存確認待ち。古い宛先に送り直さない |
| `rejected` / `expired` / `stale_session` / `host_unavailable` | 具体的な状態を報告。成功扱い・自律再送をしない |
| `maintenance` / 終了コード75 | 保守中として報告 |
| CC の `auto mode classifier gave no verdict (error)` | CC 側の一時障害。少し後に同じコマンドを1回だけ再実行し、続けば報告 |
| `Permission ... denied` | 権限拒否を回避せず報告して止める |

```bash
tproj-msg --retry <submission-id>
```

未提示の送信を取り消す場合は `tproj-msg cancel <message-id>`。
`cancelled` は配送取消、`cancellation_pending` は相手ホストの確認待ち。
`too_late` は提示開始済み等で取消できないことを示す。作業終了・Role変更は意味しない。

## 6. 通常会話では使わないもの

- 通常メッセージは task 登録・役割変更・ユーザー承認を作らない。正式な task／handoff は
  unified task authority の専用 API を使い、メッセージ送信へフォールバックしない。
- unified では `--fire` / `--force` / `--remote` などの旧配送フラグや `gate:direct` は廃止。
  全リストは `tproj-msg --help` で確認する。
- `--read` は旧来のローカル画面読取り。返信待ちに使わない。
  `--help` が legacy 表示でも unified の宛先を旧フラグで迂回しない。
- 一斉送信・`all` 宛先、受信した `[from:...]` / `[Control:...]` の他ペインへの転送は禁止。
  正当な提示保留をユーザーの起動代行で回避しない。

詳細は **tproj checkout 内**の参照資料（インストール済み skill からの相対リンクは解決しない場合がある）:
[配送・認証・receipt](../../../docs/reference/unified-messaging.md)、
[宛先・legacy task の経路](../../../docs/reference/tproj-msg-routing.md)、
[役割と権限](../../../docs/reference/role-mode.md)。
