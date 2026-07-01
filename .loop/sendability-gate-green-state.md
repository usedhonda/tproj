# Loop state — sendability-gate-green

## Budget
iteration cap 8 / wall-clock 45m / no-progress 3

## Baseline (2026-07-01 実測)
`bash extensions/messaging/tests/test-sendability-gate.sh` = PASS=12 / FAIL=0 / PENDING=1 / exit 0。
PEND = case 7 `flush_skips_selection`（Step 3 wiring 後に追加された live flush check、未実装の stub）。

## Done
- 2026-07-01 iter1: case 7 (flush_skips_selection) を real test として実装
  （--flush 経路を hermetic な TPROJ_MSG_QUEUE_DIR で駆動、send-keys shim で検証。
  7a=selection→非flush・queue保持 / 7b=sendable→flush・queue削除）。
  QUEUE_DIR を `${TPROJ_MSG_QUEUE_DIR:-/tmp/tproj-msg-queue}` に env 化（本番挙動不変）。
  suite = PASS=13 FAIL=0 PENDING=0 / exit 0。
  mutation check（detect_selection_screen を無効化）で case 7 が FAIL することを確認
  ＝ tautology でない本物の回帰ガード。commit d4baf11（main, local, push未）。→ FINAL

## Failed / blocked
(なし)

## Next step
完了（FINAL）。tproj-msg を触ったので live deploy（cp で ~/bin/tproj-msg）は
お頭の判断で別途（本番は TPROJ_MSG_QUEUE_DIR 未設定＝従来どおりで挙動不変）。
