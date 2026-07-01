# LOOP: chi-roundtrip — CC↔ちー姉様 往復の pane 着弾を実証

GOAL: gate 経由で nonce 付き probe を投げ、ちー姉様の返信 `PONG <nonce>` が
この tproj.cc pane に着弾する（＋ macmini gateway.log の reverse reply path が
発火する ＋ LINE/owner 漏れが無い）ことを実証する。1 回でも clean に実証できたら完了。

SUCCESS CRITERIA（strict / soft pass 禁止）:
- [1 着弾] 送った `PONG <nonce>` と同一の nonce 文字列が、この pane（会話）に
  ちー姉様からの返信として届く。
- [2 経路] macmini gateway.log に、その nonce に対応する reverse reply path
  （`sendTprojReturnUrlRedirect` / `tproj-msg-deliver` / `tprojOriginForSessionKey`
  のいずれか）が記録される（従来ずっと 0 → 今回 ≥1）。
- [3 非漏洩] その nonce が LINE/owner 側に出ていない（gateway.log に
  `[line] ... PONG` / `to:Yuzuru` が無い）。
- [4 規律] probe は 1 deploy につき 1 発だけ。お頭に作業をさせない。
  ちー姉様への無断再投入をしない（§3.4 / §6.6）。

VERIFY — ゲート（毎 iteration 実行・自己採点しない・fastest→slowest で最初の赤で止める）:
1. 新 deploy 判定（安い）: `tproj-msg --read oc-general.cc 40` を読み、前回 probe 以降に
   「deploy 完了」通知があるか、または macmini の gateway restart が新しく入ったかを確認。
   → 新 deploy が無ければ probe を撃たない（criterion 4）。heartbeat だけ出して次 tick へ。
2. probe（新 deploy がある時だけ）: NONCE を新規生成し
   `tproj-msg gate "ちー姉様、tproj.cc です。次の一行だけプレーンテキストで返信ください: PONG <NONCE>"`
   を 1 発。NONCE と送信時刻を state に記録。
3. 着弾待ち＋検証（遅い）: 送信から ~150 秒待ち、macmini gateway.log を NONCE で scan
   （reverse path / dispatch / LINE 漏れ）＋ この pane に `PONG <NONCE>` が来ているか確認。
PASS = criterion 1 かつ 2 かつ 3 が全て true。

観測妥当性（結果を信じる前に）:
- probe の送信が実際に成功したか（`Sent via gate...` を確認）。失敗なら着弾判定へ進まない。
- gateway.log の scan が freshness を持つか（送信時刻より後のログ行を見る）。
  blank / stale なら「未着」と断定せず、次 tick で再確認（stop_reason=unrecoverable-harness は
  ssh 自体が落ちている時だけ）。

STATE FILE: .loop/chi-roundtrip-state.md
- 開始前に必ず読む。これは resume であって restart ではない。
- 毎 iteration 追記: tested deploy ref / 撃った NONCE / 判定結果（PASS or 失敗種別）/ 次の一歩。

BUDGET（state に書く）: iteration cap 12 / wall-clock 2h / no-progress 4 tick。

EACH ITERATION:
1. contract（GOAL + SUCCESS CRITERIA + RULES）と state を RE-READ。VERIFY step 1 で現況確認。
2. PLAN: 次の最小の一歩を1つだけ決める（新 deploy 待ち / probe / 失敗種別の報告 のどれか）。
3. EXECUTE: その一歩だけ実行。
4. VERIFY: ゲートを回し、結果を state に記録。
5. DECIDE: SUCCESS CRITERIA が全て満たされたか？
   - Yes → "FINAL" を出力して停止。
   - No → 失敗なら種別（silence / Unknown-target / LINE漏れ）を分類して oc-general.cc に
     報告（1 deploy = 1 報告）。"ITERATING" を出力して次 tick へ。

No-progress サーキットブレーカー:
- 新 deploy も新しい返信も無いまま 4 tick 連続なら、probe を撃たず heartbeat のみ。
  同じ {行動+引数} を 3 回繰り返したら stop_reason=no-progress で止める（spin にお金を払わない）。

STOP WHEN（各停止に stop_reason ラベルを付ける）:
- success        : 1 回 clean に実証（criterion 1+2+3）。→ FINAL
- no-progress    : 4 tick 新規なし、または同一行動の反復。
- failure        : deploy を跨いでも壊れたまま（例: 3 deploy 連続で criterion 未達）。
- budget         : cap 12 / wall-clock 2h 到達。
- scope-boundary : お頭の介入 or ちー姉様への無断再投入が必要になった。→ 止めて報告。

ON DEAD-END（failure / budget / scope-boundary）: 黙って死なない。
何を試したか・最後の失敗種別・関係する event/nonce・次にやるべきことを、
お頭（この pane）と oc-general.cc の両方に context 付きで残す。escalate も success path。

RULES:
- ゲートが本当に通るまで「完了」と言わない。自己採点しない。
- 初回 VERIFY を尊重: 最初のチェックで既に往復が成立していたら、それは本物の success。
  作業を捏造せず FINAL を正直に出す。
- maker != checker: 着弾判定は log（外部一次証拠）と pane の両方で確認する。片方だけで断定しない。
- Surgical: probe の文面はいじらない（原因は target 解決であって文面ではないと確定済み）。
  失敗しても「ついでに」他を触らない。
- Chi 規律: probe は 1 deploy 1 発。無断再投入禁止。お頭に「LINE 見て」等の作業を振らない。
- Empty is not failure: 新 deploy が無い tick は正常。静けさを「もっと頑張れ」と読まない。
- ループ中に質問しない。妥当な仮定を state に記して続行。

# 完了トークン: FINAL
