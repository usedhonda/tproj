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

## Failed / blocked
（まだなし）

## Next step
docs/proposals/m-d3-dispatch-extraction.md を読み、その commit 計画の最初の 1 commit を実装する。
pre-gate（smoke-bin + sendability-gate）を先に回して緑を確認してから着手。

## ベースライン（2026-07-07 実測、リファクタ完遂直後）
- sendability-gate: PASS=22 FAIL=0 PENDING=0
- smoke-bin: PASS=17 FAIL=0
- inbox-check: 3 passed
- swift test: 13 passed, 0 failures
- install.sh --check: no drift（15 core scripts）
- 対象 4 提案: m-d6 / m-d5 / m-d3 / s-d2（この順を推奨、易→難）
- 対象外（人間判断が必要、ループで触らない）: s-d1 / s-d5 / b-d7
