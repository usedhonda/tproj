# M-D3 — tproj-msg トップレベル dispatch の関数抽出（提案・実装禁止）

> Debt M-D3。承認前に実装しない。各段で sendability gate 22 緑を維持する。

## 背景

`extensions/messaging/tproj-msg`（全 2822 行）の末尾がトップレベル直書きの逐次 dispatch。
mode 判定・target 解決・send/queue 分岐がスクリプト本体にベタ書きで、関数化されていない
ため単体テスト不能。極めつけに `raw_send` は**使用直前に inline 定義**される
（`extensions/messaging/tproj-msg:2673`、`raw_send` 呼び出しはその数十行下）。

根拠 file:line（現行、Phase 4 後）:

- `raw_send()` の inline 定義: `tproj-msg:2673`（`send-keys` exit code 検査は M-D1 で改修済み）。
- `generate_task_id()`: `2631`（同じく末尾近くで定義）。
- トップレベル dispatch の主分岐:
  - target 解決: `TARGET_PANE=$(resolve_target "$TARGET")` `2565` + 空チェック `2566`
  - `--read` mode: `if [[ "$READ_MODE" == "true" ]]` `2575`（`2613` で `fi`）
  - online guard: `if ! is_target_online` `2616`
  - HEADER 組み立て: `2625-2629`
  - `--force` mode: `2727-2750`
  - `--fire` mode: `2753-2781`（`enqueue`/`flush_queue`/`raw_send` 呼び分け）
  - normal mode: `2785-2820`（block→queue / それ以外→send）
- gate 経路（`send_via_gate`）は既に関数化済みで、この非対称が M-D3 の主眼。

## 提案する設計

トップレベルの逐次コードを、**副作用を明示した関数**へ抽出し、最後に薄い `dispatch_mode()`
から呼ぶ。1 関数 = 1 mode。関数化しても**分岐条件・順序・出力文言・exit code は一切変えない**。

- `do_send_tmux()` — normal/`--fire`/`--force` の tmux 送信経路（現 `2727-2820` の本体）。
  内部で `raw_send` / `enqueue` / `flush_queue` を呼ぶ。`raw_send` はファイル冒頭側の
  関数定義ブロックへ移動（inline 定義を廃し、定義の前方集約）。
- `do_send_gate()` — 既存 `send_via_gate` 経路のトップレベル配線を関数へ（gate 分岐が
  トップレベルに残っている分のみ）。
- `do_read()` — `--read` mode（現 `2575-2613`）。
- `dispatch_mode()` — mode フラグを見て上記のどれかへ振り分ける薄い関数。スクリプト末尾は
  `dispatch_mode "$@"` 相当の 1 行に縮む。
- `raw_send` / `generate_task_id` は定義位置を「使用直前」から「関数定義群」へ移すだけ
  （定義内容は不変。M-D1 の exit code 検査を保持）。

この形にすると各 `do_*` を hermetic harness（`tests/test-sendability-gate.sh` 流儀の
fake tmux/websocat/curl shim）から直接呼べ、mode ごとの回帰テストが書ける。

## 段階的な commit 計画（1 関数 = 1 commit、各段で gate 22 緑）

1. `refactor(messaging): hoist raw_send/generate_task_id to function block (M-D3a)`
   — 定義位置の移動のみ。呼び出し到達順は不変。gate 22 緑を確認。
2. `refactor(messaging): extract do_read() (M-D3b)`
   — 最も副作用の少ない `--read` から。
3. `refactor(messaging): extract do_send_tmux() (M-D3c)`
   — normal/fire/force 本体をそのまま関数へ。dedup/fanout mark の「送信/queue 成功後に
   立てる」不変条件（§3-3）を 1 行も動かさない。
4. `refactor(messaging): extract do_send_gate() (M-D3d)`
5. `refactor(messaging): add dispatch_mode() thin router (M-D3e)`
6. 各段: `bash extensions/messaging/tests/test-sendability-gate.sh`（PASS=22 維持）+
   `test-inbox-check.sh` 緑 + repo↔~/bin drift ゼロ（`cp` で反映）。以降 mode 別テストを追加。

## リスクと検証方法

- リスク: 関数化で変数スコープが変わる（トップレベルはグローバル、関数内は `local` 化しないと
  グローバル汚染 / `local` 化すると外へ出ない）。→ **最初は `local` を付けず**、既存の
  グローバル変数（`TARGET`, `HEADER`, `MESSAGE`, `SEND_BLOCK_REASON`, `TARGET_PANE` 等）を
  そのまま参照/代入する形で移送し、挙動同一を最優先。整理は別 Debt。
- リスク: `set -euo pipefail`（`tproj-msg:2`）下で関数の戻り値伝播が変わり早期 exit。→ 各段で
  gate 22 全ケースを回し、exit code 差分を検出。
- リスク: dedup/fanout mark の位置ずれ（§3 不変条件）。→ diff で mark 行が send/queue の
  成功後に留まることを目視 + fanout guard テスト（Phase 1 追加分）で担保。
- 検証: 各段 gate 22 緑 + `git diff` の全行が M-D3 に trace 可能かを自問。

## やらない場合の影響

送信ロジックがトップレベル直書きのままで、mode ごとの回帰テストが永久に書けない。
`raw_send` の inline 定義という可読性・保守性の罠が残り、M-D1 のような送達バグ修正が
毎回 2822 行の文脈読解を要する。gate/tmux の非対称（gate は関数、tmux はベタ書き）も温存。
