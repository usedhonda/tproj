# LOOP: proposals-green — 機械検証可能な設計提案 4 本をゲート緑のまま実装しきる

GOAL: `docs/proposals/` のうち機械的に検証可能な 4 本（m-d3-dispatch-extraction /
m-d5-flush-flock / m-d6-queue-error-classes / s-d2-tmux-service）を、各提案書の
commit 計画どおりに実装し、全ゲートを一度も落とさずに完了する。
上位契約: `refactor-instructions.md`（§3 Behaviors To Preserve / §4 / §5 は本ループでも有効）。

SUCCESS CRITERIA（厳格・ソフトパス禁止）:
- 4 提案すべてが STATE の Done に「実装 commit SHA + 検証結果」付きで記録されている
- `bash extensions/messaging/tests/test-sendability-gate.sh` が PASS>=22 FAIL=0 PENDING=0
  （M-D5/M-D6 は提案書どおり新テストを足すので PASS は増える一方）
- `cd apps/tproj && swift test` が 13 本以上・0 failures（S-D2 実装時はテスト追加）
- `bash tests/smoke-bin.sh` PASS>=17 FAIL=0、`./install.sh --check` が no drift
- refactor-instructions.md §3 の保存挙動（ジョグ巡回 / Learn / messaging ガード /
  autozoom SIGWINCH 規律 / dedup-mark 不変条件）を壊す diff 行がゼロ

VERIFY — 二段ゲート（自己採点禁止、速い順に実行し最初の赤で止める）:
- pre-gate（各 iteration 冒頭）: `bash tests/smoke-bin.sh`
  && `bash extensions/messaging/tests/test-sendability-gate.sh`
- post-gate（変更後）: 上記 2 本 + 変更領域に応じて
  `bash extensions/hooks/tests/test-inbox-check.sh`（messaging を触った時）
  / `cd apps/tproj && swift test && ./dev-app.sh`（Swift を触った時。dev-app.sh は
  GUI 再起動を伴う正規ビルド経路、`| tail` を付けない）
PASS = 全コマンド exit 0 かつ FAIL=0 / 0 failures / no drift
- pre-gate 赤 -> HALT（stop_reason=poisoned-baseline）
- post-gate で「以前通っていたチェック」が落ちた -> FREEZE、commit しない
  （stop_reason=regression）

STATE FILE: .loop/proposals-green-state.md
- 開始前に必ず読む。これは resume であって restart ではない。
- 毎 iteration 追記: やったこと / 通った・落ちた / 次の一手（1 つだけ）。
BUDGET（state に記録）: iteration 上限 12 / no-progress 3 連続で停止。

EACH ITERATION:
1. 本契約（GOAL + SUCCESS CRITERIA + RULES）と state を再読 → pre-gate 実行。
2. PLAN: 未完了の提案から 1 本（推奨順: m-d6 → m-d5 → m-d3 → s-d2、易→難）を選び、
   **その提案書を読み**、書かれた commit 計画の「次の 1 commit ぶん」だけを次の一手にする。
3. EXECUTE: その最小単位だけ実装。提案書の設計から逸れる必要が出たら、逸脱内容を
   state に記録して停止（stop_reason=scope-boundary）。
4. 変更が bash なら `cp` で `~/bin` に反映（install.sh 本体は実行禁止）。
   post-gate 実行 → 提案書にテスト計画があれば同一 commit でテストも追加。
   結果を state に記録し、緑なら conventional commit（英語、Co-Authored-By 禁止、
   1 commit = 1 サブステップ）。
5. DECIDE: SUCCESS CRITERIA 全達成か？
   - Yes -> 別 subagent（fresh eyes）に「4 提案の実装が提案書と一致し、ゲートが緑か」を
     独立確認させ、確認が取れたら "FINAL" を出力して停止。
   - No  -> "ITERATING" を出力して継続。

STOP WHEN（停止時は stop_reason をログに明記）:
- success            : SUCCESS CRITERIA 全達成 + 独立確認済み
- no-progress        : 3 iteration 新規進捗ゼロ、または同一アクション 3 連続
- oscillation        : 同じ問題と修正の往復が 3 回
- failure            : 1 つのサブステップが 3 回失敗（2 回失敗した時点で対象を
                       最小断片に縮めて再試行してから数える）
- budget             : 12 iterations 到達
- regression         : post-gate が既存チェックを落とした（FREEZE、commit なし）
- poisoned-baseline  : pre-gate が最初から赤
- scope-boundary     : 提案書の設計から逸れる必要が出た / §3 保存挙動に触れそうになった
ON STOP: 何が変わり何が未達か、commit 一覧、概算 accept 率を要約する。

RULES:
- ゲートが実際に通るまで done と言わない。自己採点禁止。
- 初回 VERIFY が既に全 SUCCESS CRITERIA を満たしていたら（= 誰かが先に実装済み）、
  それを正直に FINAL 報告する。仕事をでっち上げない。
- maker != checker: 最終判定は必ず別 subagent の独立確認を通す。
- Surgical: 全 diff 行が「いま実装中の提案書」に trace できること。ついで修正禁止。
  触ってよいのは extensions/messaging/tproj-msg・そのテスト・apps/tproj/Sources・
  そのテストのみ。§12 Out-of-scope（persona/memory/cc-status-bar/Chi）は不可侵。
- ゲートを弱めて緑にする行為（テスト削除・アサーション緩和・スキップ）は禁止。
  ゲート改変が必要に見えたら stop_reason=scope-boundary で停止。
- 検索してから無いと言う: grep で確認せずに「未実装」と断じない。
- 報告は簡潔に: PASS は 1 行、FAIL は {期待 / 実際 / 直すこと}。同じ失敗の再掲禁止。
- 差分だけ再検証: iteration 1 は全部、以降は触った面だけ post-gate を回す
  （Swift を触っていないのに dev-app.sh を回さない）。
- 同じサブステップが 2 回失敗したら、そのまま再試行せず最小の失敗断片
  （1 関数 / 1 テスト）に縮めて挑む。それでも駄目なら failure カウント。
- ループ中に質問しない。妥当な仮定を置き、state に記録して続行。
