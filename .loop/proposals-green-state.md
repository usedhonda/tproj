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

## Failed / blocked
（まだなし）

## Next step
docs/proposals/m-d5-flush-flock.md を読み、その commit 計画の最初の 1 commit を実装する。
pre-gate（smoke-bin + sendability-gate）を先に回して緑を確認してから着手。

## ベースライン（2026-07-07 実測、リファクタ完遂直後）
- sendability-gate: PASS=22 FAIL=0 PENDING=0
- smoke-bin: PASS=17 FAIL=0
- inbox-check: 3 passed
- swift test: 13 passed, 0 failures
- install.sh --check: no drift（15 core scripts）
- 対象 4 提案: m-d6 / m-d5 / m-d3 / s-d2（この順を推奨、易→難）
- 対象外（人間判断が必要、ループで触らない）: s-d1 / s-d5 / b-d7
