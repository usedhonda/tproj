# LOOP: sendability-gate-green — tproj-msg 送信ゲート試験を完全緑に

GOAL: sendability-gate のテストスイートを完全緑にする。現在 PENDING の
case 7 (flush_skips_selection) を実データで検証する real test として実装して PASS させ、
全ケースを PASS / 0 FAIL / 0 PENDING にする。以後もその状態を保つ。
（gate 本体 = extensions/messaging/tproj-msg、試験 = extensions/messaging/tests/test-sendability-gate.sh）

SUCCESS CRITERIA（strict / soft pass 禁止）:
- [1 緑] `bash extensions/messaging/tests/test-sendability-gate.sh` が
  PASS=13 / FAIL=0 / PENDING=0 / exit 0。
- [2 実装] case 7 (flush_skips_selection) が flush_queue の実挙動
  （selection 中の target には queue を flush しない ＝ Arc 1 の回帰穴）を検証する
  real test として実装され PASS（stub / skip / 常真アサートでない）。
- [3 非改竄] どのテストも weaken / skip / delete で緑にしていない。
  ケース総数が baseline（13）から減っていない。case 7 は「flush の selection-skip を
  外すと FAIL する」＝本物の回帰ガードであること。
- [4 surgical] 変更は case 7 実装 ＋ それを通すのに必要最小の tproj-msg 修正のみ。
  gate の contract（running→sendable / selection→block / typing→block /
  flush は selection queue を残す）を書き換えない。

VERIFY — ゲート（fastest→slowest・最初の赤で止める・自己採点しない）:
- `bash -n extensions/messaging/tproj-msg`                      # 構文（速い）
- `bash extensions/messaging/tests/test-sendability-gate.sh`    # スイート（本体）
PASS = 構文 OK かつ 出力が PASS=13 FAIL=0 PENDING=0 かつ exit 0。

STATE FILE: .loop/sendability-gate-green-state.md
- 開始前に必ず読む。resume であって restart ではない。
- 毎 iteration 追記: 試したこと / PASS・FAIL・PEND の内訳 / 次の一歩。

BUDGET（state に書く）: iteration cap 8 / wall-clock 45m / no-progress 3。

EACH ITERATION:
1. contract（GOAL + SUCCESS CRITERIA + RULES）と state を RE-READ。VERIFY を回して現況把握。
2. PLAN: 次の最小の一歩を1つ（多くは「case 7 を実装」→「通す最小の gate 修正」）。
3. EXECUTE: その一歩だけ。
4. VERIFY: ゲートを回し、結果を state に記録。
5. DECIDE: SUCCESS CRITERIA 全達成か？
   - Yes → "FINAL" を出力して停止。
   - No  → "ITERATING"。一番弱い criterion から潰す。

回帰ガード（fix したら）:
- 新しいバグを見つけて直したら、その根本原因を突く最小ケースを1本
  test-sendability-gate.sh に足す（1 fix = 1 ケース）。既存ケースは触らない。

No-progress サーキットブレーカー:
- 同じ {行動+引数} を3回、または同じ FAIL が3 iteration 続いたら stop_reason=no-progress。

STOP WHEN（stop_reason ラベルを付ける）:
- success        : PASS=13 FAIL=0 PENDING=0（K=1、決定的ゲートなので1回緑で確定）。→ FINAL
- no-progress    : 3 iteration 新規なし、または同一行動反復。
- oscillation    : 同じ problem-fix ペアを3回繰り返した。
- failure        : case 7 が3回試して緑にならない。
- budget         : cap 8 / wall-clock 45m 到達。
- scope-boundary : テスト weaken / gate contract 書き換えが必要になった → 止めて報告
                   （緑にするためにテストを弱めるのは禁止＝Goodhart 防御）。

ON DEAD-END（failure / budget / scope-boundary）: 黙って死なない。
試したこと・最後の FAIL 出力・どこで詰まったか・次の一歩を state と、必要なら
お頭 pane に context 付きで残す。escalate も success path。

RULES:
- ゲートが本当に緑になるまで「完了」と言わない。自己採点しない。
- 初回 VERIFY を尊重: 最初から PASS=13/0/0 なら本物の success。作業を捏造せず FINAL。
  （※ baseline は 12 PASS + 1 PEND なので、通常は case 7 の実装が要る）
- No fake done（最重要 / Goodhart）: テストを weaken / skip / delete / 常真化して緑にしない。
  case 7 は stub でなく実挙動を検証。ケース総数を減らさない。緑にするために gate contract を
  骨抜きにしない。
- maker != checker: case 7 を書いて自分で通すので、アサートは「flush の selection-skip を
  外すと FAIL する」ことを一度確認して本物であることを担保する。
- Surgical: diff の各行が GOAL に trace できること。tproj-msg の無関係箇所・整形・
  drive-by refactor 禁止。
- Search before assuming: flush_queue / send_block_reason の実装を grep してから直す。
- テストは repo 内の extensions/messaging/tproj-msg を直接叩く（ハーネスは hermetic な
  fake tmux/websocat shim で動く）。live deploy（cp で ~/bin/tproj-msg）は loop の scope 外——
  緑になったら報告し、deploy は別途お頭の判断で。
- 緑到達時: 関連変更（test + 最小 gate 修正）を conventional commit（§5.3A、Claude 署名なし）。
- Empty is not failure: PEND が消えて全 PASS の静かな結果は本物の緑。
- ループ中に質問しない。妥当な仮定を state に記して続行。

# 完了トークン: FINAL
