# LOOP: 手元専用の契約試験を緑にする

GOAL: CI に入っていない（sibling の `general` checkout が要る）手元専用の契約試験2本を、試験を弱めずに exit 0 にする。

開始時点の実測（2026-09-20）:
- `extensions/persona/test-project-bootstrap-contract.sh` = exit 1、何も出力しない。落ちる場所は、仮の HOME で動かす `install.sh --check` の段階（出力をコマンド置換で受けているため、`set -e` で黙って落ちる）。
- `extensions/messaging/tests/test-registry-contract.sh` = PASS=3 FAIL=1。落ちているのは `P1_router_peer_writes_pid_start (harness error rc=3)`。試験の末尾に「Phase A では FAIL が想定どおり」という古い NOTE がある。rc=3 が「試験の土台が壊れている」のか「router 側の実装が足りない」のかは、まだ切り分けていない。

SUCCESS CRITERIA（甘い合格は認めない）:
- `bash extensions/persona/test-project-bootstrap-contract.sh` が exit 0。
- `bash extensions/messaging/tests/test-registry-contract.sh` が exit 0（FAIL=0）。
- 仕上げのゲートが緑: `bash tests/smoke-bin.sh` と `./install.sh --check`。
- 契約を守っている: `project-bootstrap` と `model-role-router` は `../../../general/...` を指す tracked symlink のまま。runtime が CLAUDE.md を作らない。tracked な AGENTS.md と .gitignore は変わらない。
- 残った assert は、どれも直す前と同じ性質を確かめている（削除・skip・条件の緩和をしていない）。

VERIFY — ゲート（必ず実行する。自己採点しない）:
- 反復中: `bash -n <触ったスクリプト>`、そのあと直した方の試験1本だけ
- 最後に1回: 契約試験2本 -> `bash tests/smoke-bin.sh` -> `./install.sh --check`
- `bash extensions/messaging/tests/test-role-handoff.sh`: router を変えた場合だけ実行する
PASS = 試験2本とも exit 0、smoke-bin 緑、install --check が "canonical extension chains match"
- 速いものから順に回し、最初に赤が出たところで止める。

STATE FILE: .loop/local-contract-green-state.md
- 始める前に読む。これは再開であって、やり直しではない。
- 毎回追記する: やったこと / 通った・落ちたもの / 次の一手（1つだけ）。

EACH ITERATION:
1. この契約（GOAL + SUCCESS CRITERIA + RULES）と state を読み直す。落ちている試験を実行して、今の失敗を確かめる。
2. 次の一手を1つだけ決める。黙って落ちる失敗は、まず見えるようにする（落ちたコマンドを試験の外で直接実行し、stderr を見る）。
3. その一手を進める最小の変更をする。直す場所は根本の原因がある所にする:
   - 試験の中の仮の環境が古い場合（例: install.sh --check が今は見ているのに、試験が仮の HOME に置いていないファイル）-> 試験の準備部分を直す。
   - 本体が契約に反している場合 -> 本体を直す。router と project-bootstrap の本体は `../general/system/...` の canonical source で直し、`general` の側で commit する。
4. ゲートを回して、結果を state に書く。
5. 判定: SUCCESS CRITERIA をすべて満たしたか。
   - 満たした -> "FINAL" と出力して止まる。
   - まだ -> "ITERATING" と出力して続ける。

STOP WHEN（止まる理由を必ず state に書く）:
- success       : SUCCESS CRITERIA をすべて満たした
- budget        : 6回に達した
- no-progress   : 2回続けて、新しく通る assert が1つも増えない
- failure       : 同じ失敗に3回挑んでも直らない
- scope-boundary: 直すには試験を弱めるか、symlink を実体化するか、tracked な契約を変える必要がある -> 変更せずに止まり、報告する
ON STOP: 変えたこと、まだ落ちているもの（期待値 / 実際 / 直すべき点）、commit の SHA をまとめる。

RULES:
- 試験が通ったことをもって完了とする。自分の判断で合格にしない。
- 最初の実行で既に全部緑なら、それは本当の成功。何もしていないのに変更したように書かない。
- assert の削除・skip・緩和で緑にしない。古い NOTE（「Phase A では FAIL が想定どおり」）は、実際に緑になったあとで事実に合わせて直すだけにする。
- 触ってよい範囲: この2本の試験、試験が使う fixture、落ちている原因の本体。それ以外は整形も「ついで」の修正もしない。
- `install.sh`（`--check` を除く）は、tmux workspace が動いている間は実行しない。反映が必要なら cp で行う。
- tproj は PUBLIC。commit の前に diff を検査し、`/Users/`、`usedhonda`、メールアドレス、`sk-`、`ghp_`、`eyJ` が入っていないことを確かめる。
- commit は英語の conventional commit にし、1つの論理単位で1 commit。Co-Authored-By は付けない。push は人の指示があるまでしない。
- 同じ一手が2回失敗したら、そのまま繰り返さない。失敗している範囲を最小（1つの assert、1つのコマンド）まで絞って試す。
- ループの途中で質問しない。仮定を置いたら state に書き、先へ進む。
