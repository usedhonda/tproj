# Loops (tproj)

| slug | goal | kind | gate | cap | runtime | launch |
| --- | --- | --- | --- | --- | --- | --- |
| chi-roundtrip | CC↔ちー姉様 往復の pane 着弾を実証（✅ 2026-07-01 達成: PONG RT-020653-8697 着弾） | closed | tproj-msg gate probe → macmini gateway.log reverse-path scan ＋ pane 確認 ＋ LINE 漏れ無し | 12 | /loop self-paced | `/loop .loop/chi-roundtrip.md の手順に従って CC↔ちー姉様の往復 pane 着弾を実証して。state は .loop/chi-roundtrip-state.md。` |
| sendability-gate-green | tproj-msg 送信ゲート試験を完全緑に（pending case 7 実装＋維持） | closed | `bash extensions/messaging/tests/test-sendability-gate.sh` (PASS=13 FAIL=0 PENDING=0) | 8 | /loop self-paced | `/loop .loop/sendability-gate-green.md の手順に従って sendability-gate 試験を完全緑にして。state は .loop/sendability-gate-green-state.md。` |
