---
name: msg
description: |
  tproj-msg によるAI間通信スキル。
  他の AI ペイン（CC, Cdx, Agent, Chi）にメッセージを送る時に使う。

  以下のような状況・表現で発動:
  - 「XXに送って」「XXに伝えて」「XXに届けて」「XXに連絡して」
  - 「XXに聞いて」「XXに頼んで」「XXに依頼して」「XXに任せて」
  - 「XXに報告して」「XXに知らせて」「XXに共有して」
  - 「XXに相談して」「XXに相談」「XXに確認して」「XXに確認とって」
  - 「Codexに投げて」「Cdxに任せて」「Cdxに相談」「CCに聞いて」「CCに相談」
  - 「slに聞いて」「ちー姉様に送って」「gateに送って」
  - `/msg` コマンド

  ※ 「Cdxに」「CCに」（列指定なし）→ 同列の cdx / cc に送信（tproj-msg のデフォルト）
  ※ 別列指定は「sl.cdx に」「tproj.cc に」のように alias 付きで明示
  ※ 「プラン|計画」AND「レビュー|見てもらう」の両方を含む場合のみ plan-review。それ以外は全てこのスキルが担当
  ※ 「レビューして」単体（コードレビュー等）もこのスキルが担当

  自律トリガー（ユーザー指示なしで自分から発動）:
  - 他列・他プロジェクトに影響する問題を発見した
  - 依頼されたタスクが完了した（報告）
  - 自力では解決できない問題に遭遇した
  - Chi（ちー姉様）への技術相談・報告が必要
  ※ tproj-msg を Bash で直接実行してはならない。必ず Skill ツールで発動すること。
argument-hint: <target> <message>
allowed-tools: [Bash, Read]
compression-anchors:
  - "tproj-msg でペイン間メッセージ送受信"
  - "gate 経由でちー姉様と通信"
  - "自律発動: 他列影響発見・タスク完了・解決不能・Chi相談"
---

# tproj-msg AI間通信スキル

tmux ワークスペース内の他 AI ペイン（CC, Cdx, Agent）と通信するための内部ツール。

## 使用手順

1. ターゲットを選定（ユーザー指定があればそれを、なければ文脈から最適な相手を選ぶ）
2. **送信前ヘルスチェック（必須）**を実施
3. 直近の作業コンテキストから**自分の言葉で**メッセージを構築
4. **Control Safety（必須）**を確認（下記）
5. `tproj-msg <target> "メッセージ"` で送信
6. 応答をユーザーに報告

## 送信前ヘルスチェック（必須）

未起動ターゲットへの誤送信を防ぐため、`--status` で存在確認と状態確認を**1回で**実施する:

1. `tproj-msg --status <target>` を実行する（ターゲット存在確認 + 状態確認を兼ねる）
2. 結果に応じて判定:
   - `online/idle` or `online/suggestion` → そのまま送信
   - `online/typing` → ユーザーに確認（許可が出た場合のみ `--force` で送信）
   - `offline/...` → **送信中止**、ユーザーへ報告
   - `Target not found` → **送信中止**、ユーザーへ報告
   - `online/unknown` → **送信中止**（fail-safe）

**`--list` について**: ターゲット名が不明な場合にのみ手動で使う。送信フローの必須ステップではない。

**禁止**:
- `--status` 未確認のまま送信
- 未起動（`Target not found`）ターゲットへの送信
- 未起動（`offline`）ターゲットへの送信
- ユーザー確認なしでの `online/typing` ターゲットへの送信
- 「とりあえず queue に積む」目的で未確認ターゲットへ送信

**メッセージ構築ルール:**
- ユーザーの発言をそのまま転送しない
- 背景・文脈・具体的なファイル名を含め、相手 AI が即座に理解できるよう書く

## Control Message Safety（必須）

`[Control:*]` / `[ACK:*]` を含むメッセージは、ループ防止のため通常メッセージと別扱いにする。

必須ルール:
1. **再配布禁止**: 受信した control/ack を他ペインへ横展開しない  
2. **単発ACKのみ**: 必要な返答は原則「送信元への1回のみ」  
3. **全体配信は明示指示がある場合のみ**: ユーザーが明確に「全体へ送って」と指定した時だけ許可  
4. **Persona Sync/Check は転送しない**: 再送・再配布を行わない  

禁止:
- control/ack メッセージの連鎖転送
- 複数ターゲットへの同文面再送（明示指示なし）

## Relay Safety（必須）

`tproj-msg` は以下を relay-like として既定拒否する:

- 先頭 `\[from:...\]`
- `\[Control:...\]` / `\[ACK:...\]`
- `\[Persona Sync\]` / `\[Persona Check\]`

必須ルール:
1. relay-like 文面は通常送信しない
2. 必要な例外は `--allow-relay <reason>` を付けた**単発**のみ
3. `--force` は relay 制限を解除しない
4. ターゲット `all`, `*`, `broadcast`, `everyone` への送信は禁止

## Fan-out Safety（必須）

同一文面を CC 系または Cdx 系へ横展開する送信は、誤配信防止のため既定で拒否する。

必須ルール:
1. 「CCに聞いて」「Cdxに聞いて」は同一プロジェクトの相手（`cc` / `cdx`）を既定にする
2. 同一文面を別列の `*.cc` / `*.cdx` へ連続送信しない
3. 意図的な複数配信が必要な場合のみ `--allow-fanout <reason>` を明示して単発で許可する

## Typing Safety（必須）

ユーザーの未送信ドラフトを上書きしないため、入力中ターゲットは確認付きで扱う。

**状態別の送信判定:**

| `--status` 結果 | 判定 | アクション |
|-----------------|------|-----------|
| `online/idle` | 即送信 OK | 通常送信 |
| `online/suggestion` | 即送信 OK | 通常送信（dim 検出による suggestion = idle 相当） |
| `online/typing` | 要確認 | ユーザーに「`--force` で送るか」を確認 |
| `online/unknown` | fail-safe | 即送信せず中止 |
| `offline/...` | 送信不可 | 送信中止 |

必須ルール:
1. `online/idle` または `online/suggestion` は迷わず通常送信する
2. `--status` が `online/typing` の場合、まずユーザーに「`--force` で送るか」を確認する
3. ユーザー許可あり: `tproj-msg --force <target> "msg"` を使う
4. ユーザー許可なし: 送信しない（中止を報告）
5. prompt 判定が不明な場合は fail-safe で即送信せず中止する

### Role-Handoff 例外（active-model router 専用）

- `--role-handoff --new-task` は入力中でもユーザー確認を求めず、通常の deferred queue に積む
- `--force` は使用禁止（CLI 自体も組み合わせを拒否する）
- `--role-epoch` / `--orchestrator` が省略された場合は現在ペインの role metadata から解決する
- この例外は router による対称な orchestration handoff だけに適用し、通常メッセージの Typing Safety は変更しない

## Plan Mode 互換ルール（Cdx/CC 共通）

- Plan mode 中でも `msg` スキルの実送信は許可する
- `/msg`・「XXに送って」「XXに聞いて」指示は Plan mode でも通常どおり処理する
- Plan mode 専用の追加ゲートは設けない
- 既存の安全制約（relay/fanout/broadcast/typing guard）はそのまま適用する

## 配信モデル（重要）

- 送信後は**即 exit**する。応答は `[from:<sender>]` プレフィックスで自動配信される
- 返信を待つためにポーリングする必要はない。**そのまま作業を続ける**
- `--new-task` 委任の往復は PostToolUse / UserPromptSubmit hook が自動追跡する（Task ID cache 登録 → `[DONE:]` / `[ACK:]` 検出 → cache 自動削除 → `[inbox-notice]` を次 prompt の context に inject）。詳細は CLAUDE.md §6.3.1 / §8.5.1
- hook 追跡が効くのは `--new-task` 送信のみ。ID なし送信 or `TPROJ_HOOK_ENABLED` 未設定では CLAUDE.md §8.5.1 の手動 `--read` 運用に従う
- `--read` はターミナル出力を目視確認するためのツール。受信待ち目的では使わない

**禁止:**
- 送信後の `--read` ポーリング
- `sleep` ループでの応答待ち

## モード使い分け

| 状況 | コマンド |
|------|---------|
| 通常送信（デフォルト） | `tproj-msg <target> "msg"` |
| busy でも今すぐ届けたい（要件が明確な緊急時のみ） | `tproj-msg --fire <target> "msg"` |
| flush もスキップして純粋に即送信（例外運用） | `tproj-msg --force <target> "msg"` |
| relay-like 文面を単発で許可（理由必須） | `tproj-msg --allow-relay <reason> --force <target> "msg"` |
| 同一文面の多重配信を単発で許可（理由必須） | `tproj-msg --allow-fanout <reason> <target> "msg"` |
| 別セッション/ペイン外からの送信（CC/Cdx 共通） | `tproj-msg --session <sess> [--as <alias.role>] <target> "msg"` |
| orchestration role handoff | `tproj-msg --role-handoff --new-task [--role-epoch <n>] [--orchestrator <id>] <target> "msg"` |
| queue 内メッセージを全配信 | `tproj-msg --flush` |

**運用ルール（更新）**:
- デフォルトは通常送信（`tproj-msg <target> ...`）
- `--fire` / `--force` は、対象が `--status` で確認済みの場合にのみ使う
- relay-like 文面は `--allow-relay <reason>` なしでは送らない
- relay-like 文面を送る場合は `--force` か `--fire` を使う（queue 依存を避ける）
- 「CC/Cdx に聞く」指示はまず同列の `cc` / `cdx` に送る（別列指定は `<alias>.cc` / `<alias>.cdx` を明示）
- 同一文面の横展開は `--allow-fanout <reason>` なしでは送らない
- 入力中（`online/typing`）のターゲットに送る場合は、毎回ユーザー確認を取り、許可時のみ `--force` を使う
- 相手が未起動の疑いがある場合は送信せず、先に起動確認をユーザーへ報告する

## コマンドリファレンス

```bash
tproj-msg <target> "message"        # 通常送信（推奨）
tproj-msg --stdin <target> <<'EOF'  # stdin送信（バッククォート等を含む場合に推奨）
message with `backticks` safely
EOF
tproj-msg --fire <target> "message" # 緊急送信（typing中はqueue化）
tproj-msg --force <target> "message"# 例外即送信（typing guardをバイパス）
tproj-msg --allow-relay <reason> --force <target> "message" # relay-like 単発例外
tproj-msg --allow-fanout <reason> <target> "message" # 同文面 fan-out の単発例外
tproj-msg --role-handoff --new-task --role-epoch 7 --orchestrator tproj.cdx tproj.cdx "message"
tproj-msg --session <session> [--as <alias.role>] <target> "message" # 別セッション（tmux内ならas省略可）
tproj-msg --list                    # アクティブなターゲット一覧
tproj-msg --read <target> [lines]   # ターミナル出力の読取（目視確認用）
tproj-msg --status [target]         # idle/busy 判定 + キュー件数
tproj-msg --flush                   # キュー内メッセージを idle ターゲットに配信
```

**別セッションからの送信（`--session`）:**
- 別 tmux セッションの CC は `--session` だけでOK（caller ペインの `@alias`/`@role` から送信者を自動検出）
- tmux 外の Cdx は `--session` + `--as <alias.role>` が必須（自動検出できないため）
- `--as` を明示すれば自動検出より優先される
- 例（CC）: `tproj-msg --session tproj-workspace tproj.cc "question"`
- 例（Cdx）: `tproj-msg --session tproj-workspace --as creator_radar.cdx creator_radar.cc "done"`

**シェル展開事故の防止:**
- メッセージにバッククォート（`` ` ``）、`$()`、`${}` 等のシェルメタ文字が含まれる場合は `--stdin` + シングルクォート heredoc を使うこと
- `--stdin` は `--fire` / `--force` と組み合わせ可能
- コマンド出力やコードスニペットを送る場合は常に `--stdin` を推奨

## ターゲット書式

| 書式 | 意味 | 例 |
|------|------|-----|
| `cc`, `cdx` | 同列 / 単一モード | `tproj-msg cc "question"` |
| `<alias>.cc` | 特定列の Claude Code | `tproj-msg tproj.cc "help"` |
| `<alias>.cdx` | 特定列の Codex | `tproj-msg sl.cdx "review"` |
| `<alias>` | エイリアスのみ（cc にデフォルト） | `tproj-msg sl "question"` |
| `agent-<name>` | Agent ペイン | `tproj-msg agent-reviewer "check"` |
| `gate` | Chi（デフォルトアダプター） | `tproj-msg gate "相談"` |
| `gate:<adapter>` | Chi（アダプター指定） | `tproj-msg gate:line "報告"` |

## 受信メッセージの処理

`[from:...]` プレフィックスで届くメッセージを識別:

| プレフィックス | 送信元 |
|-------------|--------|
| `[from:tproj.cc]` | tproj列の Claude Code |
| `[from:sl.cdx]` | sl列の Codex |
| `[from:cc]` | 同列の Claude Code（単一モード） |
| `[from:agent-<name>]` | Agent ペイン |

**処理フロー**: 送信元を特定 → 本文を処理 → `tproj-msg <sender> "返信"` で返信

**返信義務リマインダー:**
- `[from:...]` で届いたメッセージには、FYI/返信不要の明示がない限り必ず返信すること
- 相談・質問も返信対象（「完了報告」だけではない）
- 返信は次の無関係な作業に移る前に送ること
- 詳細は CLAUDE.md Section 6.3 参照

## 典型的なユースケース

```bash
# 事前確認（必須 — 1回で存在確認+状態確認）
tproj-msg --status sl.cdx

# Codex に実装タスクを依頼（通常送信）
tproj-msg sl.cdx "APIエンドポイントの実装をお願い。spec は docs/api.md を参照"

# 別列の CC に設計相談
tproj-msg sl.cc "認証フローの設計でアドバイスほしい。JWTかSessionかで迷ってる"

# Agent ペインにレビュー依頼
tproj-msg agent-reviewer "PR #42 のレビューをお願い。セキュリティ観点で見てほしい"

# Chi（ちー姉様）に報告
tproj-msg gate "tproj v2.1 リリース完了しました。変更内容は CHANGELOG を参照ください"

# busy 相手に急ぎ送信（対象確認後のみ）
tproj-msg --fire tproj.cdx "緊急: 本番でエラー発生。調査お願い"

# relay-like 文面の例外送信（理由付き・単発）
tproj-msg --allow-relay incident-psync-stop --force tproj.cc "[Control:PSYNC-STOP-20260219] ACK"
```

## Gate ターゲット（ClawGate bridge -> Chi）

Chi（ちー姉様）との通信は `gate` ターゲットを使用:

```bash
tproj-msg gate "message"            # デフォルトアダプター（direct inject -> EventBus -> Chi poll）
tproj-msg gate:line "message"       # LINE アダプター経由
tproj-msg gate:direct "message"     # direct アダプター明示指定
tproj-msg --status gate             # bridge 生死確認
```

**フォールバック無効**: `gate:tmux` 失敗時は自動フォールバックしない（即エラー終了）。`gate:direct` を使いたい場合は `tproj-msg gate:direct "msg"` と明示的に指定すること。

**Gate 横断 dedup**: 同一メッセージを60秒以内に異なる gate アダプターで送信するとブロックされる。パニックリトライによる多重送信を防止する仕組み。

## `--list` 出力例

```
Available targets (tproj-workspace):
  tproj.cc    Claude Code [col 1]
  tproj.cdx   Codex [col 1]
  sl.cc       Claude Code [col 2]
  sl.cdx      Codex [col 2]
```

## よくあるエラーと対処

| エラー | 原因 | 対処 |
|-------|------|------|
| `Target not found: <name>` | ペインが存在しない or タグ未設定 | `tproj-msg --list` で利用可能なターゲットを確認 |
| `Gate connection failed` | ClawGate bridge が未起動 | `tproj-msg --status gate` で状態確認 |
| メッセージが届かない（queue 積み） | 相手が busy | `--fire` フラグで強制送信、または `--flush` で queue 配信 |
| `Session not found` | tmux セッション外で実行 | tproj セッション内から実行すること |

**重要**: `Target not found` の場合は送信をリトライしない。起動確認できるまで中断する。
