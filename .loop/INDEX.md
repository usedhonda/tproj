# Loops (tproj)

| slug | goal | kind | gate | cap | runtime | launch |
| --- | --- | --- | --- | --- | --- | --- |
| chi-roundtrip | CC↔ちー姉様 往復の pane 着弾を実証（✅ 2026-07-01 達成: PONG RT-020653-8697 着弾） | closed | tproj-msg gate probe → macmini gateway.log reverse-path scan ＋ pane 確認 ＋ LINE 漏れ無し | 12 | /loop self-paced | `/loop .loop/chi-roundtrip.md の手順に従って CC↔ちー姉様の往復 pane 着弾を実証して。state は .loop/chi-roundtrip-state.md。` |
| sendability-gate-green | tproj-msg 送信ゲート試験を完全緑に（pending case 7 実装＋維持） | closed | `bash extensions/messaging/tests/test-sendability-gate.sh` (PASS=13 FAIL=0 PENDING=0) | 8 | /loop self-paced | `/loop .loop/sendability-gate-green.md の手順に従って sendability-gate 試験を完全緑にして。state は .loop/sendability-gate-green-state.md。` |
| proposals-green | docs/proposals の機械検証可能な 4 本（m-d6/m-d5/m-d3/s-d2）をゲート緑のまま実装しきる | closed | smoke-bin + sendability-gate (>=22) + swift test (>=13) + dev-app.sh の二段ゲート | 12 | /loop self-paced | `/loop .loop/proposals-green.md の手順に従って proposals 4 本を実装しきって。state は .loop/proposals-green-state.md。` |
| tproj-release-ready | 現在の tproj main を不要な反復テストなしで検証済み publish-ready 状態にする | closed | 反復中は最小 focused check、publish 直前に必要な final gate を同一 HEAD で1回 | 6 | Codex manual tick | `.loop/tproj-release-ready.md の手順に従って1 iterationだけ進めて。state は .loop/tproj-release-ready-state.md を読んで更新して。完了なら FINAL、続行なら ITERATING で終えて。` |
| pane-bg-style-layers | gpt-image-2 のセル画技術 baseline を tracked script へ移し、~/.config と project-local を house/persona override 専用に降格 | closed | 反復は `bash -n` + `bash tests/test-pane-bg-style-layers.sh`、最後に1回 smoke-bin + install.sh --check | 6 | /loop self-paced | `/loop .loop/pane-bg-style-layers.md の手順に従って pane-bg の画風レシピを二層に分離して。state は .loop/pane-bg-style-layers-state.md。` |
