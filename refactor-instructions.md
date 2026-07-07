# refactor-instructions.md — tproj リファクタリング指示書

> 実装担当モデルへ: この文書があなたの契約です。各フェーズの開始時に本文書の
> **Behaviors To Preserve / Non-Negotiables / Stop And Ask Conditions** を再読してから
> 作業してください。証拠なき大規模削除・全面書き換えは禁止です。
> §7 の全判断は 2026-07-07 にユーザー確認済み。追加の質問なしで Phase 0〜4 を完遂できます。

---

## 1. Objective

既存仕様を一切壊さずに、tproj の技術的負債を「小さく・戻しやすい単位」で減らし、
今後の変更容易性（特にテスト可能性と並行実行の安全性）を上げる。

- 見た目の綺麗さは目的ではない。古いコード＝悪ではない。
- 各 diff 行が本文書の Debt ID（例 `M-D2`）に trace できること。
- 「動いているが読みにくい」より「読みやすいが壊れた」のほうが遥かに悪い。

## 2. Project Understanding

tproj は tmux ベースの AI ワークスペース・オーケストレータ。Claude Code (CC) と
Codex (Cdx) を tmux ペインに並べ、ペルソナ・背景・AI 間メッセージング・macOS GUI を
単一コマンドで管理する。

| 領域 | 実体 | 規模 |
|---|---|---|
| CLI ランチャ | `bin/tproj` ほか bin/ 16 ファイル | tproj 本体 2312 行 |
| macOS GUI | `apps/tproj/Sources/TprojApp/TprojApp.swift` | **5691 行の単一ファイル**（AppViewModel 2344 行 / ContentView 946 行） |
| AI 間通信 | `extensions/messaging/tproj-msg` | 2798 行の単一 bash（87 関数 + 末尾 ~270 行のトップレベル dispatch） |
| フック | `extensions/hooks/`（inbox-check / inbox-record） | Claude Code hook 連携 |
| 配布 | `install.sh` が repo → `~/bin` 等へ cp | repo と `~/bin` の二重管理 |

データフロー要点:
- ペイン識別は tmux オプション `@role` / `@column`（`bin/tproj:1086-1089` で設定）。
- tproj-msg は送信時に `~/.local/share/tproj-msg/messages.db` (SQLite) へ shadow-write。
- CC の idle/typing 状態は cc-status-bar の `ws://localhost:8080` から websocat で取得
  （欠如時は capture-pane ヒューリスティックへ fail-open）。
- GUI は `~/bin/tproj` 等を `NSHomeDirectory()` 解決で Process 実行（77 呼び出し箇所）。
- ランタイム状態は `/tmp/tproj-*`、`~/.config/tproj/`、UserDefaults `tproj.midi.*`、
  `~/.cache/tproj-expect-reply/` に散在。

外部依存: tmux(必須) / jq / yq / sqlite3 / websocat / gtimeout / CoreMIDI /
ClawGate(localhost:8765) / VOICEVOX。オプション依存は欠如時 fail-open。

## 3. Behaviors To Preserve（絶対に壊してはいけない挙動）

1. **tproj-msg 送信ガード群**: broadcast ターゲット禁止（all/*/broadcast/everyone）、
   relay 様本文（`[from:]` `[Control:]` `[ACK:]` `[Persona *]`）のデフォルトブロックと
   `--allow-relay <reason>` 単発解除、fanout ブロックと `--allow-fanout`、
   typing 保護（typing 時 normal/--fire はキュー、`--force` のみ bypass）。
   正本: `tproj-msg:644-922` + `tests/test-sendability-gate.sh`（現在 PASS=13）。
2. **sendability gate の現挙動**: `send_block_reason`（block-list 方式）が
   normal / `--fire` / `flush_queue` に接続済み。running（生成中）は送信可、
   選択肢画面 (permission/AskUserQuestion) は block。テスト 13 ケースが仕様。
3. **dedup/fanout mark は send または queue の成功後**にのみ立てる（不変条件）。
4. **MIDI ジョグ機能一式**（直近 3 コミット ef05221 / bf50b1d / 8103e14、実機確認済み）:
   相対 CC 量子化（ch0/CC6 既定、30 tick/step、0.15s 間隔）、巡回順 =
   codex 左→右 → claude 左→右、Learn ボタン = ジョグ学習（同一 CC 連続 8 回で確定）。
   **S-D4（パッド slot 削除）の作業でこれらを 1 行も巻き込まないこと。**
5. **autozoom の SIGWINCH 規律**（cb0a10d / e951052 で確立）: 単一 dispatch
   （after-select-pane[30] のみ）、他列幅リサイズの冪等化、codex ロールペインへの
   縦 grow スキップ。resize-pane を無条件連打する変更は再インシデント直結。
6. **GUI ビルドは `apps/tproj/dev-app.sh` 経由のみ**（P0）。`open` / pkill+手動起動 /
   `swift build` 後の手動起動は禁止。
7. **`install.sh` は tmux セッション稼働中に無断実行しない**（launchctl 経由で
   memory-guard が再起動され kill-pane しうる）。稼働中の反映は対象ファイルの
   `cp` デプロイで行い、その旨を報告する。
8. **`@role` / `@column` タグ規約**: レイアウト制御・メッセージルーティング・
   `--repair` の基盤。フォーマット変更禁止。
9. **GUI から `zsh -lc` 禁止**（ハングする）。パスは `NSHomeDirectory()` で解決。
10. **永続データ互換**: `messages.db` スキーマ、UserDefaults キー
    （`tproj.midi.jog.*`）、`workspace.yaml` 形式、`/tmp/tproj-*` の他プロセスが読む
    ファイル形式を勝手に変えない。
    （例外: `tproj.midi.learn.bindings.v1` は S-D4 承認により廃止対象。§7）
11. commit に Co-Authored-By を含めない。英語 conventional commits。

## 4. Non-Negotiables（作業規律）

- **最初に `git status -s` を確認**。既存の未コミット変更があれば混ぜない
  （自分の変更は自分のコミットにだけ入れる）。
- **編集前に §6 Baseline Commands を全て実行し、結果を state ファイル
  （`.loop/refactor-state.md` を新設）に記録**してから触る。
- 変更は小さく戻しやすい単位。**1 commit = 1 Debt ID の 1 サブステップ**。
- 無関係な整形・quote style 変更・勝手な型注釈/コメント追加・import 並び替え禁止。
- 既存挙動を勝手に変えない。「改善のつもりの挙動変更」も禁止
  （§7 で承認済みの挙動変更 = M-D1 / S-D4 / B-D1 / B-D2 のみ例外。承認範囲を超えない）。
- 正しさが不明なら実装を止めて質問する（§5）。
- 各フェーズ末に §9 Verification を実施。緑でなければ次フェーズへ進まない。
- 最後に実行したコマンドと結果を報告する（§10）。

## 5. Stop And Ask Conditions（即停止して人間に確認）

以下に触れそうになったら、実装せず質問を返すこと:

- 公開挙動・CLI フラグ・出力文言の変更で **§7 の承認範囲外**のもの
  （`--status` の語彙、"Sent to X" 文言等はユーザー/他 AI がパースしている可能性がある。
  M-D1 は「exit code 検査 + 失敗時 return 1 + DB delivered 抑止」までが承認範囲で、
  成功時の "Sent to X" 文言自体は変えない）
- `messages.db` スキーマ、`tproj.midi.jog.*` キー、`/tmp` の状態ファイル形式の変更
- §3 のいずれかと衝突する変更
- テストと実装が矛盾していると気づいた場合（どちらが正か勝手に決めない）
- 削除候補で、本文書に削除承認が明記されていないもの（呼び出し元 grep がゼロでも、
  hook・GUI・install.sh・tmux.conf・skill からの間接参照を全て確認してから）
- ClawGate/Chi・cc-status-bar・LINE 連携など外部システムに影響しうる変更
- 同一の修正で 2 回失敗した場合（3 回目の前に停止して報告）

## 6. Baseline Commands（Phase 0 で記録し、以後の各フェーズ末で再実行）

```bash
git -C /Users/usedhonda/projects/claude/tproj status -s        # クリーンであること
bash extensions/messaging/tests/test-sendability-gate.sh      # PASS=13 FAIL=0 PENDING=0
bash extensions/hooks/tests/test-inbox-check.sh               # 緑
cd apps/tproj && ./dev-app.sh                                 # debug ビルド成功 + GUI 起動
for f in bin/*; do diff "$f" "$HOME/bin/$(basename "$f")" >/dev/null || echo "DRIFT: $f"; done
```

GUI 手動スモーク（dev-app.sh 後）: ジョグ回転でフォーカス巡回 / Learn→ジョグ学習 /
列操作が動くこと。実機のジョグ操作が必要な確認は、まとめて 1 回の依頼に集約する。

## 7. 確定済み判断（2026-07-07 ユーザー回答。再質問不要）

| # | 論点 | 決定 |
|---|---|---|
| Q1 | raw_send の偽 "Sent" | **軽量版で修正**: send-keys の exit code 検査 + 失敗時 return 1 + DB delivered 抑止。capture-pane による実配送確認はしない。成功時の出力文言は不変 |
| Q2 | `unknown_prompt` デッド分岐 | **削除**（4 箇所、挙動不変） |
| Q3 | `bin/tproj-pane-watchdog` | **削除**（ファイル削除 + install.sh 配布から除去 + pkill 2 箇所と誤誘導コメント整理。git 履歴で復活可能） |
| Q4 | レイアウトロック統一 | **GO**: tmux `wait-for -L tproj-layout` に統一。rebalance → autozoom → tproj の順に 1 つずつ |
| Q5 | Swift library ターゲット分離 | **GO**: `Sources/TprojLogic/` + XCTest。dev-app.sh のビルド経路は不変であること |
| Q6 | パッド→ペイン即ジャンプ | **廃止・削除**: ユーザーはジョグのみ使用。slot 発火経路（onSlotTriggered / activatePaneForMIDISlot / bindings ルックアップ / MIDILearnStore / StoredMIDIBinding / UserDefaults `tproj.midi.learn.bindings.v1`）を削除してよい。**ジョグ系（MIDIPaneActivator の jog 検出・量子化・onJogStep・focusPaneByJog・jog learn）は残す** |
| Q7 | bin/ 共有ライブラリ | **GO**: `bin/lib/` 新設。対象は「子孫 PID 収集 4 重複 / role→exit 表 3 重複 / vm_stat パース 3 重複」に限定。それ以外の共通化はしない |
| Q8 | テスト空白 | **relay guard / fanout guard のみ今回**（Phase 1）。Chi recovery / dedup / DB / flush worker のテストは別レーン（Out-of-scope） |

## 8. Debt Map（重要度順・出典は各分析レポート）

凡例: 【可】= 実装承認済み / 【提案】= 本リファクタでは実装せず `docs/proposals/` に提案書のみ。

### Messaging (`extensions/messaging/tproj-msg`)

| ID | 内容 | 根拠 | 判定 |
|---|---|---|---|
| M-D1 | `raw_send`(2666-2684) が送達検証なしで "Sent" を返し DB も無条件 delivered。gate 経路 (send_via_gate) は HTTP 判定+エラー記録があり非対称。既知インシデント要因 | 2666-2684 vs 2173-2245 | 【可】軽量版（§7 Q1 の範囲厳守）+ fake tmux で失敗注入する回帰テストを同一 commit に |
| M-D2 | `unknown_prompt` が一度も代入されないのに case 分岐が 4 箇所（1698/1781/1880/2780）に残存 | grep 実証 | 【可】削除 |
| M-D3 | 末尾 ~270 行(2367-2798)がトップレベル直書き dispatch。`raw_send`/`generate_task_id` が使用直前 inline 定義。テスト不能 | 2367-2798 | 【提案】 |
| M-D4 | dedup ストア 3 種が `/tmp` ハードコード（QUEUE_DIR のみ env 可）。テスト隔離不能 | 515/518/2248 | 【可】env フォールバック追加（既定値不変） |
| M-D5 | enqueue(追記) と flush(read+truncate) が無ロックで競合しうる（レアな silent ロスト） | 1804/1865/1936/1955 | 【提案】 |
| M-D6 | 1973 の握りつぶしが「ターゲット消滅」と「一時エラー」を区別せず queue 保持（STALE_SECONDS で最終破棄されるため致命ではない） | 1973 | 【提案】 |
| M-T | relay/fanout guard のテスト空白 | tests/ 対比 | 【可】Phase 1 で追加（テストのみ、実装無変更） |

### Swift GUI (`apps/tproj/Sources/TprojApp/TprojApp.swift`)

| ID | 内容 | 根拠 | 判定 |
|---|---|---|---|
| S-D1 | AppViewModel が God object（1777-4121、2344 行、80 メソッド） | 型マップ | 【提案】(段階分割案のみ) |
| S-D2 | tmux/Process 呼び出し 77 箇所、`"tproj-workspace"` リテラル 18 箇所が散在 | 2069,2360 他 | 【可】定数化のみ（static let、値不変）。Service/protocol 抽出は【提案】 |
| S-D3 | executable 単体で XCTest 不能。純ロジック（GhosttyConfigParser 85-459、jog 量子化 1743-1764、巡回順ソート、yaml/quote 系）が癒着 | Package.swift | 【可】library 分離 + テスト（§7 Q5） |
| S-D4 | パッド slot 機能一式が廃止決定（§7 Q6）。`MIDILearnStore`(save は既に孤児) / `StoredMIDIBinding` / bindings ルックアップ / `onSlotTriggered` / `activatePaneForMIDISlot` を削除 | 1512-1540, 1739-1740, 3216, 3230 | 【可】削除。**ジョグ系を 1 行も巻き込まない**（§3-4）。旧キー `tproj.midi.learn.bindings.v1` の removeObject は任意（残置しても害なし、消すなら単独 commit） |
| S-D5 | エラーが statusText 文字列代入 78 箇所への握りつぶし | 1912 他 | 【提案】 |
| S-D6 | CoreMIDI スレッド→MainActor 境界が慣習依存（現状実機で問題なし） | 1682-1764 | 【提案】(触らない) |
| S-D7 | 汎用 View 部品 (4122-4453) と 946 行 ContentView の同居 | 型マップ | 【可】部品の別ファイル物理分割のみ。ContentView 分解は【提案】 |

### bin/ シェル群

| ID | 内容 | 根拠 | 判定 |
|---|---|---|---|
| B-D1 | `tproj-pane-watchdog` は無効化済み死コード（bash3 非互換 declare -A、関数外 `local` の latent bug）。コメント 3 箇所（tproj:1093,1144,1952 付近）が「watchdog が respawn」と誤誘導（実体は respawn-guard） | tproj:2308-2309, watchdog:16,109 | 【可】ファイル削除 + install.sh 配布除去 + pkill 2 箇所整理 + コメント訂正（§7 Q3） |
| B-D2 | レイアウトロック 3 系統分裂: PID ファイル (tproj:505) / tmux wait-for (drop-column:9) / 無し (autozoom, rebalance)。相互排他せず並行破壊可能。SIGWINCH storm と同クラスの構造問題 | 各ファイル | 【可】tmux wait-for へ統一（§7 Q4。§9 Phase 4 の手順・検証厳守） |
| B-D3 | 子孫 PID 収集が 4 実装（respawn-guard は 2 階層止まりで非対称） | tproj:541, drop-column:32, kill-pane:44, respawn-guard:34 | 【可】共有 lib へ 1 本化（§7 Q7）。respawn-guard の full-tree 化は挙動変更として単独 commit + 明記 |
| B-D4 | role→exit コマンド表が 3 重複 | kill-pane:28 他 | 【可】共有 lib へ集約 |
| B-D5 | vm_stat メモリ可用量パースが 3 重複 | respawn-guard:88 他 | 【可】共有 lib へ集約 |
| B-D6 | autozoom のエントリログが DEBUG gate 外で無条件追記・ローテなし | autozoom:37-38 | 【可】DEBUG gate 化 or size ローテ付与 |
| B-D7 | set -e 方針が不統一（-euo / -uo / -eo / なし 混在） | 各冒頭 | 【提案】 |
| B-D8 | `TPROJ_*` 環境変数 ~24 個がドキュメント未集約 | grep | 【可】docs/reference/env-vars.md 新設 |
| B-D9 | repo↔~/bin の drift 検知機構なし | install.sh:277 | 【可】`install.sh --check` 追加（検知のみ、install 本体不変更） |

## 9. Implementation Phases（この順で。各フェーズ末に Verification）

### Phase 0 — 現状固定（必須・最初）
1. `git status -s` 確認。dirty なら停止して報告。
2. §6 Baseline Commands を全て実行し、結果（テスト数・ビルド成否・drift 有無）を
   `.loop/refactor-state.md` に記録。
3. ベースラインが赤なら**リファクタ開始前に停止して報告**（poisoned baseline）。

### Phase 1 — 安全網の増設（テスト追加のみ・実装コード無変更）
1. M-T: `tests/test-sendability-gate.sh` の hermetic harness（fake tmux/websocat shim）
   流儀で **relay guard / fanout guard** のテストを追加（`enforce_send_policy`、
   `fanout_guard_*` の代表ケース各 2-3 本）。既存 13 ケースは触らない。
2. bin/ 用の最小スモーク `tests/smoke-bin.sh` を新設: 各スクリプトの `bash -n`
   構文チェック + 無害な代表実行。
3. コミット単位: テストファイルごと。

### Phase 2 — 明らかに安全な整理（挙動不変、1 commit = 1 項目）
1. M-D2: `unknown_prompt` デッド分岐 4 箇所を削除。
2. M-D4: dedup 3 ディレクトリに `TPROJ_MSG_*_DIR` env フォールバック追加。
3. B-D6: autozoom エントリログを DEBUG gate 内へ（または size ローテ付与）。
4. B-D8: `docs/reference/env-vars.md` 新設。
5. B-D9: `install.sh --check` 追加。
6. S-D2: `"tproj-workspace"` / `"tproj-workspace:dev"` リテラルを `static let` へ集約。
7. S-D7: Card/SectionHeader/ActionButton 系を同 target 内の別ファイルへ物理移動。

### Phase 3 — 承認済みの削除と責務分離
1. B-D1: `tproj-pane-watchdog` 削除一式（ファイル / install.sh CORE_BINS /
   `~/bin` からの除去手順 / pkill 2 箇所 / 誤誘導コメント 3 箇所訂正）。
2. S-D4: パッド slot 経路の削除（§7 Q6 の列挙どおり）。削除後に dev-app.sh で
   ビルド + **ジョグ巡回と Learn（ジョグ学習）が無傷で動くことを実機確認**。
3. S-D3: `Sources/TprojLogic/` library ターゲット新設。純ロジックのみ移設:
   GhosttyTheme+GhosttyConfigParser → JogQuantizer（handleJog の純化）→
   巡回順ソート（focusPaneByJog のソート部）→ yaml/quote 系。1 移設 = 1 commit。
4. `Tests/TprojLogicTests/` 新設。最優先はジョグ量子化と巡回順の退行テスト
   （実機確認済み挙動の固定）。以後 `swift test` を Baseline に追加。

### Phase 4 — 境界の明確化（承認済み・慎重に）
1. B-D2: レイアウトロックを tmux `wait-for -L tproj-layout` に統一。順序:
   rebalance → autozoom → tproj(add_workspace_column) の順に 1 つずつ。
   各ステップで「列追加 + 列削除の同時実行」再現スクリプトによる破損なし確認、
   および focus 応答の体感劣化がないことを確認。
2. B-D3/D4/D5: `bin/lib/tproj-common.sh` 新設 → install.sh 配布対象に追加 →
   descendant 収集 1 本化（respawn-guard full-tree 化は単独 commit で明記）→
   exit 表 → vm_stat の順。
3. M-D1: raw_send の軽量修正（§7 Q1 の範囲）+ fake tmux で send-keys 失敗を
   注入する回帰テストを同一 commit で追加。

### Phase 5 — 大きな設計変更（実装禁止・提案書のみ）
以下は `docs/proposals/` に設計案を書いて提出し、承認なしに実装しない:
S-D1（AppViewModel 段階分割計画）、S-D2 残り（TmuxService/CommandRunner protocol 化）、
S-D5（statusText の Result 化）、M-D3（dispatch 関数抽出の commit 計画）、
M-D5（flush の flock 設計）、M-D6、B-D7（set -e 方針）。

## 10. Verification Requirements

- 各フェーズ末: §6 Baseline Commands 全実行。**Phase 0 の記録と比較して劣化ゼロ**
  （テスト数は増える一方、減ったら regression として停止）。
- messaging 変更時: `test-sendability-gate.sh` が既存 13 + 追加分すべて緑。
- Swift 変更時: `./dev-app.sh` 成功 + GUI 起動 + （Phase 3 以降）`swift test` 緑。
  MIDI/レイアウトに触れた変更は、ジョグ巡回・Learn・列操作の実機確認まで必須。
- bin/ 変更時: `bash -n` 全通過 + 変更スクリプトの代表実行 + repo↔~/bin drift ゼロ
  （反映は cp。install.sh は tmux セッション非稼働の確認が取れた時のみ）。
- 削除系（B-D1 / S-D4）: 削除後に全 Baseline + 該当実機確認。加えて
  `grep -rn <削除した識別子> .` が「意図した残置（docs/履歴）以外ゼロ」であること。
- コミット前に毎回: diff の全行が今のフェーズの Debt ID に trace できるか自問。
  できない行があれば revert。

## 11. Reporting Format（各フェーズ完了時）

```
Phase: <番号と名前>
Task Intent: <このフェーズで直した Debt ID 列挙>
反映操作: <cp / dev-app.sh 等>
確認コマンド: <実行したもの>
確認結果: <ベースライン比較つき>
Commit: <SHA 列挙（1 commit = 1 サブステップ）>
未実施: <スキップした項目と理由>
Out-of-scope candidates: <見つけたが触らなかった改善候補>
```

最終報告では「最後に実行したコマンドと結果」を必ず含める。

## 12. Out-of-scope Items（本リファクタでは触らない）

- `extensions/persona/`（tproj-pane-bg 129KB 含む）と背景画像生成まわり
- `extensions/memory/`（memory-guard は launchctl 常駐・事故面が別）
- cc-status-bar（別リポジトリ/別レーン）、ClawGate/Chi サーバ側、LINE 連携
- Chi recovery / control・gate dedup / DB shadow-write / flush worker のテスト追加
  （§7 Q8 により別レーン）
- `.local/` 配下、`docs/log/codex/` の過去ログ
- GUI の見た目・UX 変更、パフォーマンスチューニング
- workspace.yaml スキーマ変更
- 新機能の追加（本文書は負債返済専用）
