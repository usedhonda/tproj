# Loop state — proposals-green

## Budget
iteration 上限 12 / no-progress 3

## Done
- m-d6 (queue error classes) — 提案書 commit 計画どおり 3 commit で実装完了（iteration 1, 2026-07-07）:
  - `0cb4f93` M-D6a: resolve_target の失敗 return を 2 値化（RT_NOT_FOUND=3 / RT_TRANSIENT=4）。
    pane_list 取得成否で分類、全「not found」return を `$rt_fail` 化。呼び出し側は non-zero 一括扱いで挙動不変。
  - `4d9c038` M-D6b: flush_all_queues が NOT_FOUND / TRANSIENT で別ログ（keep-queue 挙動は不変）。
    fake tmux に list_panes_fail 注入を追加し gate test 23（gone）/ 24（transient）を追加。
  - `a722fd3` M-D6c: TARGET_GONE_GRACE（既定 = STALE_SECONDS）で gone-target 早期破棄を opt-in 化。
    queue_newest_age ヘルパ追加、既定値では末端挙動等価。gate test 25（short grace で discard）追加。
  - 検証: sendability-gate PASS=25 FAIL=0 PENDING=0 / smoke-bin PASS=17 FAIL=0 / inbox 3 passed。
    各 commit 後に post-gate 全緑を確認、`cp` で ~/bin/tproj-msg へ反映済み。
  - 提案書との一致: 完全一致。逸脱なし（M-D6c の「既定で現行等価」は newest-message age での whole-queue
    discard により no deliverable loss で担保）。実装中に set -euo の command-substitution abort を 1 度踏み、
    `pane=$(...) || rc_resolve=$?` で回避（挙動不変）。

- m-d5 (flush/enqueue flock mutual-exclusion) — 提案書 commit 計画どおり 3 commit で実装完了（iteration 2, 2026-07-08）:
  - `86d7802` M-D5b: with_queue_lock ヘルパ + config（QUEUE_LOCK_WAIT_MS/POLL_MS）追加。未使用、挙動不変。
    macOS に flock(1) 無し（`command -v flock` MISSING）のため提案書の代替 = mkdir アトミック lock
    （generate_task_id の seq_dir 流儀）を採用。timeout 到達で fail-open（未ロックで従来動作）。
  - `58af65c` M-D5c: enqueue の `printf >>` を `_queue_append` 経由で with_queue_lock 配下へ直列化。
  - `bed3ecf` M-D5d: flush の read->truncate を `_flush_drain_queue`（既存 body を verbatim 抽出）に
    切出し with_queue_lock で包む + 回帰テスト 26 を同一 commit で追加。
  - 検証: sendability-gate PASS=26 FAIL=0 PENDING=0 / smoke-bin PASS=17 FAIL=0 / inbox 3 passed。
    各 commit 後 post-gate 全緑、`cp` で ~/bin/tproj-msg へ反映（diff -q IDENTICAL 確認）。
  - 提案書との一致: flock -> mkdir lock は提案書§macOS 前提の明記済み代替（環境調査の上で決定）。
    テスト戦略のみ意図的逸脱を報告済み: 提案の M-D5a「並行 enqueue 中 flush で 1 行消える再現」は
    真の loss 窓（read-EOF→truncate 間）がほぼゼロ + bash read が open fd 上の追記を拾うため
    決定的な race 再現が不安定。タスク承認の代替（「ロックが取られている/解放されている」の決定的
    検証）に落とし、test 26 を「外部保持中は locked flush が block（drain しない）→ 解放後に drain +
    lockdir 自己解放」の相互排他プロパティ検証に。M-D5c 状態（flush 未ロック）で test 26 が RED
    (blocked=0)、M-D5d で GREEN を確認済み。standalone red test の commit はループの
    gate-green-at-every-commit 不変条件に反するため M-D5d 内へ green で同梱（4 commit→3 commit）。
  - 挙動微変の承認範囲遵守: flock 導入は enqueue 追記と flush read+truncate の相互排他のみ。
    STALE_SECONDS 破棄 / max_count 保持 / policy・dedup ガード / kept_lines 書戻し は verbatim 抽出で不変
    （既存 flush テスト 7/23/24/25 全緑で担保）。

- m-d3 (top-level dispatch extraction) — 提案書 commit 計画どおり 5 commit で実装完了（iteration 3, 2026-07-08）:
  - `beee46d` M-D3a: raw_send / _raw_send_record_error / generate_task_id の inline 定義を
    resolve_target 直後の関数定義ブロックへ verbatim hoist（定義位置移動のみ、呼び出し到達順不変）。
  - `ed2b905` M-D3b: `--read` mode body を do_read() へ verbatim 抽出、`if READ_MODE; then do_read; fi` に。
  - `3585c50` M-D3c: tmux 送信経路（online guard→header→task id→fanout/dedup guards→force/fire/normal→exit 0、
    137 行）を do_send_tmux() へ verbatim 抽出。dedup/fanout mark の send/queue 成功後配置は 1 行も動かさず。
  - `8f6e3d4` M-D3d: gate early-exit body（88 行）を do_send_gate() へ verbatim 抽出、`if is_gate_target; then do_send_gate; fi` に。
  - `13f39f9` M-D3e: policy precheck→do_send_tmux の dispatch tail を dispatch_mode() で in-place wrap（再インデントなし）、
    スクリプト末尾を `dispatch_mode` 1 行に。LIST/FLUSH/STATUS の top-level early-exit は wrap 対象外で温存。
  - 検証: 各 commit 後 post-gate 全緑（sendability-gate PASS=26 FAIL=0 PENDING=0 / smoke-bin PASS=17 FAIL=0 /
    inbox 3 passed）。bash -n OK、shellcheck -S error clean、`cp` で ~/bin/tproj-msg 反映（NO_DRIFT）。
  - 挙動不変の証明: pre-M-D3 baseline (d8f5f65) との sorted 多重集合 diff で削除行ゼロ（原本の全ロジック行が
    verbatim 保存）、追加は do_read/do_send_gate/do_send_tmux/dispatch_mode の 4 定義 + 4 closing brace + 4 call のみ。
  - verbatim 移動で許可した変換規則: (1) 関数化に伴う `foo() { ... }` ラッパ行の追加、(2) 抽出元 body を
    `foo` 呼び出し 1 行へ置換。body 本文・indent・exit/return・出力文言は一切改変せず。exit の意味保存 =
    do_* / dispatch_mode を全て「plain 呼び出し（if/$()/||/&& の外）」にしたため set -euo pipefail の活性状態と
    exit のスクリプト全体終了セマンティクスが top-level と同一。command-substitution 化はしていない。
  - 提案書との一致: 完全一致。逸脱なし。提案書の「最初は local を付けず既存グローバル変数をそのまま参照」も遵守
    （do_* に local 追加なし）。dispatch_mode の定義位置のみ提案の「関数定義群」ではなく in-place wrap を採用したが、
    これは surgical（再インデント回避で verbatim 維持）のためで、定義は top-level・呼び出し前・非ネストを満たし
    testability（source して do_* 個別呼び出し可）を損なわない。

## Failed / blocked
（まだなし）

## Next step
docs/proposals/s-d2-tmux-service.md を読み、その commit 計画の最初の 1 commit を実装する。
Swift を触る提案の可能性が高いので post-gate に `cd apps/tproj && swift test && ./dev-app.sh` が加わる点に注意。
pre-gate（smoke-bin + sendability-gate）を先に回して緑を確認してから着手。

## ベースライン（2026-07-07 実測、リファクタ完遂直後）
- sendability-gate: PASS=22 FAIL=0 PENDING=0
- smoke-bin: PASS=17 FAIL=0
- inbox-check: 3 passed
- swift test: 13 passed, 0 failures
- install.sh --check: no drift（15 core scripts）
- 対象 4 提案: m-d6 / m-d5 / m-d3 / s-d2（この順を推奨、易→難）
- 対象外（人間判断が必要、ループで触らない）: s-d1 / s-d5 / b-d7
