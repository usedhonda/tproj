# tproj-msg 改修 — Phase A 診断 state

Contract plan: `~/.claude/plans/fizzy-floating-bee.md`
Upper contract: `refactor-instructions.md` §3/§4/§5
Scope: Phase A = P0-1 診断のみ（実装コード無変更、テスト新設のみ）
Date: 2026-07-17

このファイルは Phase A の確定事実と、Phase B が使う再現・契約を記録する。
実装コード（tproj-msg / router / DB / 実キャッシュ）は一切変更していない。

---

## A-1. router 契約の実測 — pid_start 分布（読み取りのみ）

対象: `~/.cache/tproj-model-role/**/*.json`（全 83 ファイル）。

| 分類 | 件数 | 意味 |
|---|---|---|
| pid_start キー **欠落**（MISSING） | 74 | peer 経路 `pane_peer()` 由来。`role_reason:"paired-with-*"` を伴う |
| pid_start に正値（POSVAL） | 9 | self 経路 `state_from_payload()` 由来。`orchestrator_alias` も併記 |
| pid_start=null（明示 null） | 0 | 実在せず |
| pid_start=0 | 0 | 実在せず |

**重要な訂正（プランとの差分）**: プラン本文は「`"pid_start": null`」と記述するが、実ファイルは
**キー自体が存在しない**（欠落）状態。`tproj-msg:596` の `jq -r '.pid_start // 0'` は
「欠落」も「null」も等しく `0` に落とすため、下流の誤爆挙動は同一。以後 B2 の実装は
「欠落/0/null すべてを『未記録』として扱う」ことで漏れなく救える。

POSVAL 9 件（self 経路）:
`standalone/.../unknown.agent`, `6/tproj.cc`, `6/tproj.cdx`, `1/oc-general.cc`,
`1/oc-general.cdx`, `4/vibeterm.cc`, `4/vibeterm.cdx`, `3/clawgate.cdx`, `5/tproj.cc`。

同一 alias でも window により有無が割れる（例: `vibeterm.cc` は window 4=POSVAL /
window 6,9=MISSING）。self 経路が先に書けば pid_start あり、peer 経路が先に書くと
欠落のまま固定（cache branch がそれを無変更で返し続ける）→ 起動レースで恒久化。

peer-path json 例（window6 vibeterm.cc、欠落キー）と self-path json 例（window4、pid_start あり）
のキー差分:
- 欠落側に無い: `pid_start`, `orchestrator_alias`

### 根本原因の確定（router 側、B1 の対象）

`model-role-router` の書き込み経路は 2 本:
- **self 経路**: `state_from_payload()`（router:377-395）は `"pid_start": pid_start_epoch(resolved_pid)` を **書く**。
- **peer 経路**: `pane_peer()`（router:398-447）の構築ブロック（424-440）は `pid` は書くが
  `pid_start` を **書かない**。`resolve_role()`（549-560）がこの peer dict を
  `persist_role(peer_update)` でそのまま `write_json` するため、peer の registry json が
  pid_start 欠落で着地する。cache branch（419-422）は既存ファイルを無変更で返すので、
  一度欠落で書かれると恒久化する。

→ B1 は `pane_peer()` 構築 dict（424-440）に self 経路と同じ
`"pid_start": pid_start_epoch(int(pid) if pid.isdigit() else 0)` を 1 行追加すれば足りる。

---

## A-2. verify_as_caller_identity 誤爆機序の hermetic 確定

harness: `test-sendability-gate.sh` の fixture 流儀（`MODEL_ROLE_CACHE` 上書き +
"claude" にリネームした fork が自 pid/pid_start で registry を書く wrapper + fake tmux/websocat）。
実環境 `~/.cache/tproj-model-role` は不変（temp registry のみ使用）。

採取結果（`--session tproj-workspace --as tproj.cc` で running pane へ normal send）:

| ケース | 録音内容 | 実挙動 | reason | 発火行 |
|---|---|---|---|---|
| (a) null+ancestor | pid=live-ancestor, pid_start **欠落** | REJECT | `pid_start_mismatch` | **606-609** |
| (a2) null+NONancestor | pid=非ancestor live pid, pid_start 欠落 | REJECT | `pid_start_mismatch` | **606-609** |
| (b) match | pid=ancestor, pid_start=一致 | VERIFY (sent) | (none) | 619 通過 |
| (c) mismatch | pid=ancestor, pid_start=不一致 | REJECT | `pid_start_mismatch` | **619-622** |

### 分岐の切り分け（606-609 vs 619-622）

- (a) は実 vibeterm 再現: 生きた agent が ancestor なのに、録音 pid_start 欠落
  （→ `jq // 0` で 0）→ `tproj-msg:606-609` の `reg_pid_start -gt 0` 判定で
  ancestor walk 前に即 reject。**外部 `--as` 検証が構造的に 100% fail** する経路を確定。
- (a2) が決定打: pid を **非 ancestor** の生 pid にしても reason は `no_agent_ancestor`
  ではなく `pid_start_mismatch` のまま。これは 606-609 が ancestor 照合（611-612）**より前**に
  短絡することを証明する（もし 611 に到達していれば非 ancestor は `no_agent_ancestor` を返す）。
- (c) は正当な reject。pid_start が正値（>0）なので 606 は通過し、619-622 の
  実 mismatch（pid 再利用/なりすまし防御）で reject。**この fail-closed は維持必須**。

### 追加所見（B2 設計への申し送り）

(a)/(a2) の **null 由来誤爆** と (c) の **実 mismatch** は reason 文字列が
両方 `pid_start_mismatch` で **区別できない**。audit ログ上も同一に見えるため、
今回のインシデントは triage が難しかった。B2 は null 短絡側に **別 reason**
（例 `pid_start_unrecorded`）を与えると、将来の監査で「未記録」と「なりすまし疑い」を分離できる。

---

## A-3. test-registry-contract.sh 新設（RED 確認済み）

`extensions/messaging/tests/test-registry-contract.sh`。gate suite とは **独立ファイル**
（26 ケース全緑の不変条件を、意図的に RED な契約テストと結合させないため）。

Phase B 完了で緑になる契約:
- **P1**（RED, B1）: 実 router を in-process import（`SourceFileLoader`、`__main__` guard あり）+
  tmux shim で peer 1 行 + 空 cache → `pane_peer()` 構築 dict に `pid_start` キーが有ること。
  現状の出力キー一覧に `pid_start` **無し** を確認 → RED。
- **P2a**（RED, B2）: 録音 pid_start 欠落 + 生 agent ancestor → VERIFY であるべき。現状 REJECT。
- **P2b**（GREEN 維持）: 録音一致 → VERIFY。
- **P2c**（GREEN 維持, fail-closed）: 録音不一致 → REJECT。
- **P3**（OBSERVE, 非 fatal, B3）: 複数 window 同名 alias → find 採用先の記録。

現状の実行結果:
```
FAIL  P1_router_peer_writes_pid_start (RED until Phase B1: peer path omits pid_start)
FAIL  P2a_null_pidstart_self_recompute_verifies (RED until Phase B2: got REJECT pid_start_mismatch)
PASS  P2b_matching_pidstart_verifies
PASS  P2c_mismatched_pidstart_rejects
OBSERVE P3_find_multi_candidate: verdict=REJECT no_agent_ancestor (...)
PASS=2 FAIL=2   (exit 1 — Phase A は意図的に RED)
```

---

## A-4. find_registry_state_file 非決定性の再現

`find_registry_state_file`（tproj-msg:551-564）は
`find "$cache/$session" -type f -name '*.json' -print0` の **先頭 alias 一致**を採用し、
liveness / mtime の tiebreak が無い。

観測（temp cache に window 6,3,4,10,2 の順で同名 `tproj.cc.json` を作成）:
- `find -print0` の返り順 = `6,10,4,3,2`（作成順でもソート順でもない = FS traversal/inode 順）。
- `sort` と不一致 → **未ソート走査**。
- 採用されたのは先頭の window 6（pid=6000）。どの pid/pid_start を掴むかは
  **FS traversal 順まかせ**で環境非決定。

契約テスト P3 でも実挙動を捕捉: window 1（生 ancestor）+ window 9（dead pid 999999）の
2 候補で、現 resolver は **dead 側（window 9）を採用**し `no_agent_ancestor` で REJECT した。
→ B3 は「reg_pid 生存エントリ優先、複数生存なら mtime 最新」で決定化する。

---

## Phase B が使う確定事実（申し送り）

1. **B1（router 1 行）**: `pane_peer()` 構築 dict（router:424-440）へ
   `"pid_start": pid_start_epoch(int(pid) if pid.isdigit() else 0)` 追加。self 経路と同一算出。
   → P1 が緑化。実施後 general 列へ tproj-msg で事後報告。
2. **B2（tproj 自衛）**: `verify_as_caller_identity`（tproj-msg:606-609）—
   録音 pid_start が **欠落/0/null**（`jq // 0` で 0）のときは即 reject せず、
   `reg_pid` の live process start を `pid_start_epoch_bash "$reg_pid"` で自前再計算し、
   ancestor 照合結果と比較する（pid 再利用耐性は同等担保）。再計算不能なら従来どおり reject
   （fail-closed 維持）。null 短絡は別 reason 化を推奨。→ P2a 緑化、P2c 維持。
3. **B3**: `find_registry_state_file`（551-564）を決定化 — 候補中「reg_pid 生存」優先、
   複数生存なら mtime 最新。→ P3 が VERIFY 決定化。
4. **回帰**: Phase B 完了後、A-2 の (a)欠落→自衛VERIFY / (c)実mismatch→REJECT維持 を
   gate suite に組み込む（plan Phase B4）。

## Phase A 検証

- `bash extensions/messaging/tests/test-registry-contract.sh` → PASS=2 FAIL=2（意図的 RED、exit 1）
- `bash extensions/messaging/tests/test-sendability-gate.sh` → **PASS=26 FAIL=0 PENDING=0**（不変条件維持）
- 実装コード変更: なし。実キャッシュ / messages.db 書き込み: なし。

---

# Phase B — P0-1 修正（実装済み・2026-07-17）

Scope: 契約プラン fizzy-floating-bee.md Phase B（B1..B4）を完了。Phase A の診断どおり修正。

## B1 — router `pane_peer()` に pid_start 出力を追加（別リポ general）

- 対象: `general/system/model-role-router/model-role-router` の peer 構築 dict。
  `"pid": ...` の直下へ self 経路と同一算出の
  `"pid_start": pid_start_epoch(int(pid) if pid.isdigit() else 0),` を 1 行追加。
  他は無変更。
- general 側テスト `system/model-role-router/test-model-role-router.sh` → **55 passed, 0 failed**。
- general commit（push なし）: `6a1e7e4`。
- 反映: `cp ...model-role-router ~/bin/model-role-router`（launchctl 系 install は未実行）。
  installed == repo（byte 一致）を確認。
- 効果: 契約テスト P1 が RED → GREEN。

## B2 — `verify_as_caller_identity` 自衛（tproj）

- 録音 pid_start が正値なら現行の厳密比較を維持（fail-closed 不変）。
- 録音が欠落/0/null（`jq // 0` で 0）なら即 reject せず、`pid_start_epoch_bash "$reg_pid"`
  で reg_pid の live start を自前再計算して bind。再計算不能（dead pid 等で 0）なら reject。
- 未記録経路の reject には新 reason `pid_start_unrecorded` を付与（`pid_start_mismatch`
  = なりすまし疑い と監査上区別可能に）。final compare の mismatch も録音有無で
  reason を出し分け。
- tproj commit: `2814172`。効果: 契約 P2a RED → GREEN、P2b/P2c GREEN 維持。

## B3 — `find_registry_state_file` 決定化（tproj）

- find の FS 走査順先頭採用をやめ、全候補を走査。reg_pid 生存（`kill -0`）を優先、
  同一 liveness では mtime 最新を採用。単一候補時の挙動は不変。
- tproj commit: `531ff7e`。効果: 契約 P3 が REJECT(no_agent_ancestor) → VERIFY 決定化。

## B4 — gate suite に回帰テスト追加（tproj）

- REG_MODE 選択式 wrapper で 4 ケース追加（既存 26 は不変）:
  - B4a 録音欠落 + live ancestor → VERIFY
  - B4b 録音欠落 + dead reg_pid → REJECT `pid_start_unrecorded`（fail-closed 維持）
  - B4c 録音あり不一致 → REJECT `pid_start_mismatch`（不変ガード）
  - B4d live + dead 複数窓 → live 採用で VERIFY（B3）
- tproj commit: `fd264ab`。

## Phase B 検証

- `test-registry-contract.sh` → **PASS=4 FAIL=0**（P1/P2a/P2b/P2c GREEN、P3 observe=VERIFY）。
- `test-sendability-gate.sh` → **PASS=30 FAIL=0 PENDING=0**（26 + B4 4）。
- `tests/smoke-bin.sh` → **PASS=17 FAIL=0**。
- `extensions/hooks/tests/test-inbox-check.sh` → **4 passed, 0 failed**。
- 反映: `cp extensions/messaging/tproj-msg ~/bin/tproj-msg`（install.sh は tmux 稼働中のため未実行）。
  installed == repo（byte 一致）を確認。
- 実機: `~/bin/tproj-msg --session tproj-workspace --as tproj.cc tproj.cc "P0-1 fix verification ping (ignore)"`
  → rc=0 "Sent to tproj.cc"。messages.db row 14312 = `verified=1 delivery=send-keys
  rejection_reason=NULL`（rejected でない）。同クラスは修正前 06:38:19 まで
  `pid_start_mismatch` で reject されていた（id 14297 が最後）。

---

# Phase C — P0-2/P0-3 修正（実装済み・2026-07-17）

Scope: 契約プラン fizzy-floating-bee.md Phase C（C1..C5）を完了。1 commit = 1 サブステップ。
既存ガード群・文言・dedup mark タイミング不変（--status への行**追加**のみ）。

## C1 — monitor consumer key を role 非依存へ（tproj-inbox-monitor）

- consumer key `${SESSION}:${MY_ALIAS}.${MY_ROLE}` → `${SESSION}:${MY_ALIAS}`。
  TO_ALIAS（メッセージ突合の宛先）は `alias.role` のまま不変。
- bootstrap は既存の cold-start（`COALESCE(MAX(id),0)`）を維持。旧 role 込み行
  （凍結 `tproj-workspace:tproj.cc`=344）は**継承せず**、新 key を MAX(id) で cold-start
  = 過去 backlog の一括通知爆発を防止（プラン note の趣旨）。新 key は旧 key と別名のため
  344 の巨大 backlog を舐めない。
- テスト容易化のため `main` を source guard 化（sourced 時は poll ループを起動しない）。
- tproj commit: `1484a40`。
- hermetic test: test-inbox-check.sh Case D（旧 role 込み cursor=5 + messages 最大 100 →
  新 key が 100 に cold-start、旧行 5 は不変）。

## C2 — `do_read` が inbound を read 化（tproj-msg）

- do_read: 読んだ target pane の `@alias.@role`（= from_alias）→ 自分（to_alias）宛の
  `direction=inbound AND read_at IS NULL` を一括 `read_at=now` に UPDATE（best-effort、
  DB 無ければ何もしない、失敗握りつぶし）。scrollback 厳密突合はしない。
- tproj commit: `13ca28e`。
- hermetic test: gate suite C2（synthetic inbound tproj.cdx→tproj.cc を --read tproj.cdx で
  read 化）。

## C3 — `--status` に monitor 生存診断（tproj-msg）

- `print_monitor_diagnostic`: monitor_cursors の自 key（`${SESSION}:${MY_ALIAS}`）の
  updated_at で判定。行無し=`monitor: not running`、閾値超過（既定 300s、
  `TPROJ_MONITOR_STALE_SEC`）=`monitor: stale (last <dt>)`、それ以外=`monitor: ok (last <dt>)`。
  既存の status 行は不変で 1 行**追加**のみ。target 指定/無指定の両分岐に追加。
- tproj commit: `1459d5e`。
- hermetic test: gate suite C3（no row/fresh/stale の 3 状態 + 既存 `sendable_running` 併存）。

## C4 — bare alias（`cc`/`cdx`）曖昧解決の厳格化（tproj）

- `check_bare_target_unambiguous`: bare cc/cdx 送信で、workspace の候補が複数かつ
  列コンテキストで一意化できないとき exit 19 + `cdx is ambiguous: <list>` で reject。
  候補 0/1（単一列）、in-pane 同一列一致（same-column 意味論）は従来どおり許可。
  send path（dispatch_mode の READ_MODE!=true）でのみ発火、flush は非対象。
- exit code `AMBIGUOUS_BARE_EXIT=19` を新設（13-18 は既存）。
- tproj commit: `d1e9d47`。
- hermetic test: gate suite C4（cdx 候補 1 → C4 透過 / other.cdx 追加で候補 2 → exit19 +
  候補一覧 + no send-keys）。

## C5 — task expire 時の送信元通知（tproj-inbox-check）

- 既存の expire 検出ループ（`tt_cache_gc_expired` 消費）に
  `[inbox-notice] task <id> expired (no ACK from <target>)` を**追加**（既存の
  `timeout on ...` 通知は不変）。cache-expired = 未 read = 未 ACK（ACK/DONE/BLOCK read で
  cache 除去済）ゆえ "no ACK" 妥当。hook 無効環境（TPROJ_HOOK_ENABLED!=1）は全体が
  早期 exit = fail-open。
- tproj commit: `f731ea0`。
- hermetic test: test-inbox-check.sh Case E（expired task → no-ACK 通知 + 既存 timeout 併存）。

## Phase C 検証

- `test-sendability-gate.sh` → **PASS=33 FAIL=0 PENDING=0**（30 + C2/C3/C4）。
- `test-registry-contract.sh` → **PASS=4 FAIL=0**。
- `tests/smoke-bin.sh` → **PASS=17 FAIL=0**。
- `test-inbox-check.sh` → **8 passed, 0 failed**（4 + C1 Case D 2 + C5 Case E 2）。
- 反映: `cp` で `~/bin/{tproj-msg,tproj-inbox-monitor,tproj-inbox-check}`（変更分のみ、
  install.sh は tmux 稼働中のため未実行）。installed == repo（byte 一致）確認。
- 実機（live DB 非破壊、read/reject または copy DB 上で検証）:
  1. monitor 前進: real DB copy に installed monitor を 2s 稼働 → 新 key
     `tproj-workspace:tproj` が MAX(id)=14314 で cold-start、旧 `.cc`=344 不変、digest 爆発なし。
  2. `--status`: copy（fresh cursor）で `monitor: ok (last 2026-07-17 07:13:11)`、
     live（行無し）で `monitor: not running`。既存 status 行不変。
  3. bare `cdx`（live, 複数列）→ `cdx is ambiguous: oc-general.cdx, ble-bridge.cdx,
     clawgate.cdx, vibeterm.cdx, tproj.cdx` rc=19、messages 行 0 件（DB 非汚染）。
  4. 自己宛 `--read tproj.cdx`（copy DB）: synthetic inbound の read_at が
     NULL → 1784240037（2026-07-17 07:13:57）に前進。

## 逸脱・申し送り

- C1: プラン本文「旧 key の last_message_id を継承」と note「MAX(id) cold-start 適用」は、
  cold-start = MAX(id) が継承値を上書きするため net で cold-start に収束。過去分再生をしない
  プラン趣旨（「通知が動き出すこと」）を優先し、旧行は継承せず orphan（無害）として残す。
  実装は既存 INSERT OR IGNORE の cold-start をそのまま活かし、CONSUMER 変更が主。
- C5: 既存 `timeout on ...` 通知が既に expire を送信元へ可視化しているため、C5 の
  `task <id> expired (no ACK ...)` は同一 gc_expired 行から**2 行目**として併存する。
  文言不変制約（Case B が timeout 文言を固定）と exact-string 要求の両立のための設計。
  重複というより orchestrator-follow-up 系 / delegation-closure 系の別フレーミング。

---

# Phase D — P1 修正（実装済み・2026-07-17）

Scope: 契約プラン fizzy-floating-bee.md Phase D（D1..D5）。1 サブステップ = 1 commit。
既存ガード群・"Sent to X" 文言・dedup mark タイミング（send/queue 成功後）不変。

## D1 — relay 漏れ 76(現 85)件の根治 → **根治対象なし（tproj 側バイパス不在を実証）**

messages.db を SELECT 監査した結論：**tproj の send/flush 経路に relay ガードのバイパスは存在しない**。
- `direction=outbound` かつ body が `[from:` 始まりの行 = **85**（プラン記載の 76 から増加）。
  内訳: **40** = sendability-gate テスト case 17 の `[from:OpenClaw Agent - Auto] allowed relay body …`
  （`--allow-relay --force` の正規テスト注入。E4 の DB 隔離が入る前に実 DB を汚染したもの）。
  **45** = oc-general 列を中心とした実トラフィック（oc-general.cc→cdx の ACK/DONE/BLOCK 応答等）。
- 45 件はすべて **caller-audit 列が空**（`verified=0`, `claimed_alias` NULL, `caller_pid` NULL）=
  `--as` 検証経路を通っていない = in-pane 送信。かつ 46/46 が relay ガード導入 commit
  (`3c9d1da`, 2026-03-31) より**後**。つまり「ガード導入後に、ガードを持つ検証経路を通らずに」着地。
- 現行 binary で再現テスト: relay-like body を通常/`--fire`/`--force`/gate 経路へ流すと
  `enforce_send_policy`（dispatch precheck 3508）が **rc=13 で block**。queue へは
  `--allow-relay` でも「blocked target には enqueue 不可」(3261/3316) で入れられない。
  → **queue/flush 経路は構造的に relay body を運べない**。
- したがって 85 件は「ガードを抜けた漏れ」ではなく、(a) 正規 `--allow-relay`（reverse-channel /
  Chi relay）と (b) テストハーネスの実 DB 汚染。**tproj 側に塞ぐバグは無い**（塞ごうとすると
  `--allow-relay` 正規経路を壊す or §4.5 No-Impossible-Handling 違反の到達不能分岐を足すことになる）。
  「再現が取れた経路だけを塞ぐ」に従い、**production コード変更は行わず**、seal を hermetic テストで固定。
- D1 テスト（`test-sendability-gate.sh` に追加）: `D1_relay_never_enqueued` =
  `--allow-relay` + relay body + **blocked target** → rc=13 / queue 生成なし / send-keys なし。
  = queue/flush 漏れベクタが構造的に不可能であることを lock。
- tproj commit: `1202c48`（test only）。

## D2 — 空 body / 短時間重複の reject

- **空 body**: dispatch precheck で `[[ -z "${MESSAGE//[[:space:]]/}" ]]` → 空・空白のみ
  （`--stdin` 空入力含む）を **exit 20**（`EMPTY_BODY_EXIT`、既存 13-19 と非衝突）で reject。
- **60s dedup**: `send_dedup_check`（gate_dedup を汎用化、key = sha1(from|to|body)）。
  TTL = `TPROJ_MSG_SEND_DEDUP_SEC`（既定 60）、store = `TPROJ_MSG_SEND_DEDUP_DIR`。
  precheck で **check のみ**（新規送信コマンド時、flush 経路では非適用）、**mark は配達/enqueue
  成功時**（`raw_send` / `enqueue` の choke point）に `DEDUP_BODY`（precheck で捕捉した
  mutation 前 body）で実施。→ downstream で reject された送信（fan-out 等）が後続の正規送信を
  poison しない。重複は **exit 21**（`DUP_SEND_EXIT`）、`--force` は bypass、gate は gate_dedup 継続。
- tproj commit: `7fb4c46`。hermetic: `D2a_empty_body_rejected` / `D2c_dup_resend_rejected`
  （既存 case 20/21 fan-out を割らないため mark-on-success 設計が必須だった）。

## D3 — queue 行の終端遷移

- enqueue が queued 行を **先に** shadow-write し、その row id を queue TSV の**任意 4 列目**へ格納。
  legacy 3 列行は空 dbid で後方互換 parse（`_queue_append` 4 列化、`_flush_drain_queue` は
  `read -r epoch header stored_msg dbid`）。
- flush 成功 → 元行を `delivery='flushed', delivered_at=now` に **in-place UPDATE**
  （別 outbound INSERT を廃止、inbound mirror は維持）。dbid 無い legacy 行のみ旧 INSERT に fallback。
- drop 時 → `dropped-stale`（STALE 超）/ `dropped-policy`（policy/control-dedup）/ `dropped-gone`
  （gone target、qfile rm 前に dbid を走査してマーク）+ delivery_err を UPDATE。
- 既存 260 件の孤児 queued 行 → `tt_db_init` 内の**冪等 one-shot sweep**
  `tt_db_sweep_orphaned_queued`（`queued` かつ `delivered_at NULL` かつ `created_at < now-600`
  → `orphaned-legacy`。stale 窓より古い行のみ = in-flight を絶対に触らない、再実行安全。E1 の
  user_version 機構までの暫定）。
- 新 helper: `tt_db_set_flushed` / `tt_db_set_dropped` / `tt_db_sweep_orphaned_queued`。
- tproj commit: `35adc6b`。hermetic: `D3a`(in-place flush)/`D3b`(stale→dropped)/`D3c`(legacy 互換)/
  `D3d`(orphaned-legacy sweep: 古い→orphaned-legacy、新しい→queued 維持)。

## D4 — 背景 worker の可観測化

- `start_flush_worker` の `&>/dev/null` を廃止。worker の stderr（起動/終了マーカー + flush の
  delivered/stale/policy/gone 診断）を `~/.cache/tproj-msg/flush-worker.log`
  （`TPROJ_MSG_FLUSH_WORKER_LOG` 上書き可）へ append。**1MB 超で `.1` にローテ**（respawn-guard の
  `stat -f%z` 流儀）。内側 `--flush 2>/dev/null` の stderr 握り潰しも解除（診断が log へ届くように）。
- tproj commit: `5cab2c6`。テストは sandbox で log を隔離。実機: rotate（>1MB→.1）+ 起動/配達/終了
  行の書き込みを確認。

## D5 — gate 返信の inbound ミラー → **tproj 管轄に受信点なし。実装せず（別レーン提案）**

- 調査: tproj-msg は gate への **送信側のみ**（`do_send_gate`, `gate_reply_callback_url`,
  `return_url=`, `reply=session` header の構築）。`tt_db_mirror_inbound` 呼び出しは
  outbound 送信（raw_send / flush）由来のみ。**ClawGate 返信の受信点（reverse channel receiver /
  EventBus / clawgate bridge の inbound ingestion）は tproj のコードベースに存在しない**
  （`grep` で receiver/listener/ingestion 該当ゼロ）。memory `reference_chi_gate_reverse_channel.md` /
  `gate-reply-routing-fix-plan.md` の通り、reverse channel の受け口は clawgate / general 列側にある。
- 結論: 受信点が tproj 管轄外のため、**tt_db_mirror_inbound の追加は実装しない**（他列所有コードへの
  越境禁止 §6.1）。**gate outbound の `delivered_at` 更新 = 別レーン提案**（clawgate/general 側の
  reverse-channel receiver に、`return_url` の workspace/task を使って tproj DB の gate outbound 行へ
  callback で `delivered_at`/inbound mirror を書く経路を新設する提案。tproj 単独では閉じない）。

## Phase D 検証

- `test-sendability-gate.sh` → **PASS=40 FAIL=0 PENDING=0**（33 + D1 + D2a/D2c + D3a-d = 7 追加）。
- `test-registry-contract.sh` → **PASS=4 FAIL=0**。
- `tests/smoke-bin.sh` → **PASS=17 FAIL=0**。
- `test-inbox-check.sh` → **8 passed, 0 failed**。
- 反映: `cp` で `~/bin/{tproj-msg,tproj-msg-db.sh}`（変更分のみ、install.sh は tmux 稼働中のため未実行）。
  installed == repo（両者 byte 一致）。
- 実機:
  1. D2 空 body → rc=20 / 空白のみ → rc=20 / seed 済み dup → rc=21 / `--force` → rc=0
     （dry-run 経路、実配達ゼロ。real binary + real registry）。
  2. D3 temp DB: queued 行を flush → `flushed` + delivered_at set、outbound 重複 0、inbound mirror 1、
     queue file 消滅。実 DB の孤児 260 行を `tt_db_init` sweep で `orphaned-legacy` 化
     （before queued=260 → after still-queued-aged=0 / orphaned-legacy=260、2nd run も 260 = 冪等）。
  3. D4 flush-worker.log に起動/配達/終了診断が書かれ、>1MB で `.1` へ rotate することを確認。

## 逸脱・申し送り（Phase D）

- **D1 はプラン前提と実測が食い違う**: プランは「76 件のガード漏れ経路を特定して塞ぐ」を想定したが、
  監査の結果 tproj 側にバイパスは無く、行の実体は正規 `--allow-relay`（40 件テスト汚染 + 45 件
  reverse/Chi relay）だった。タスク指示「再現が取れた経路だけを塞ぐ／--allow-relay 正規経路は壊さない」
  に従い production 変更を見送り、seal を lock する回帰テストのみ追加。テスト汚染 40 件の恒久隔離は E4。
- **事故報告**: Phase D 着手時の探査で `POLICY_DRY_RUN=1`（正しくは `TPROJ_MSG_POLICY_DRY_RUN`）
  を誤用し short-circuit が効かず、live tproj.cdx pane へ検証メッセージ 2 通（`clean message` と
  `[from:tproj.cc] [from:x.cc] relay body`）を実送信した。実 DB は temp path に隔離されており非汚染。
  以後の送信検証は fake-tmux harness / dry-run（正しい env 名）に限定した。
- **D2 mark-on-success が必須だった**: precheck-mark 案は fan-out で reject された送信が dedup store を
  poison し既存 case 21 を割った。gate_dedup 同様「成功時に mark」へ変更し、mutation 前 body
  (`DEDUP_BODY`) で check/mark を一致させた。
- **D5 は tproj 単独で閉じない**: 受信点が他列所有のため、delivered_at 更新は別レーン提案止まり。

---

# Phase E — P2 衛生（実装済み・2026-07-17）

Scope: 契約プラン fizzy-floating-bee.md Phase E（E1..E4）。1 サブステップ = 1 commit。
既定挙動不変（E3 は off 既定、E4 はテストハーネス側のみ）。ガード群・文言・dedup mark
タイミング不変。

## E1 — migration を user_version ゲートに（tproj-msg-db.sh）

- `tt_db_ensure_init` は DB ファイル存在で short-circuit していたため、スキーマ変更が
  既存 DB に届かなかった（reinstall 必須。7/16 の 156 件 insert 失敗クラス）。
- 修正: DB 欠落時は `tt_db_init`。DB 存在時は `PRAGMA user_version` を読み、
  `recorded < TT_DB_SCHEMA_VERSION` のときだけ冪等な `tt_db_init` を再実行して
  user_version を再スタンプ。`TT_DB_SCHEMA_VERSION=2`（env 上書き可）を新設し、
  既存の caller-audit 列を「gated schema」に取り込んだ。version 読取エラーは
  recorded=0 にフォールバック → 安全な no-op 再 init（fail-open 維持）。
- user_version スタンプは全 migration 実行後に最後に打つ（`PRAGMA user_version = 1;`
  ハードコードを heredoc から除去し、`tt_db_init` 末尾で動的スタンプ）。
- tproj commit: `44b3cde`。
- 実機（一時 DB）: (a) 列欠落の v1 DB → migrate 後 verified 列追加 + version 2、
  (b) **実 DB コピー（全列・v1）→ version 1→2 / count 14303 不変 / errlog 0 行 /
  2 回目実行も version 2・count 不変（冪等）**、(c) 欠落 DB → 新規 v2。

## E2a — file-per-hash dedup ストアの TTL 掃除（tproj-msg）

- `gate_dedup` と（D2 の）`send_dedup` は hash ごとに 1 ファイルを書くだけで削除ループが
  無く単調累積（control/fanout の TSV は毎 check で掃除するのと非対称）。
- 共有ヘルパ `cleanup_hashfile_dedup_store <dir> <ttl>` を新設し、`gate_dedup_check` /
  `send_dedup_check` の冒頭から呼ぶ。mtime（= 書込時刻、`>` truncate で 1 回書き）で
  TTL 超のファイルを `find -mmin +ceil(ttl/60) -delete`。分単位切上げで age<TTL の
  live エントリは絶対に消さない（check の age gate と整合）。gate TTL を
  `TPROJ_MSG_GATE_DEDUP_SEC`（既定 60=不変）で env 化。
- tproj commit: `b28c16c`。
- 実機（一時 dir）: 10 分前 backdate ファイル → 削除、fresh → 保持、
  欠落 dir / bad ttl → 安全 no-op。

## E2b — task-seq バケット剪定（tproj-msg）

- `generate_task_id` の `/tmp/tproj-task-seq/<target>/<epoch_min>/<seq>` は古い epoch_min
  バケットを消さず 192 dir 累積。
- `prune_task_seq_buckets`（epoch_min < (now-STALE)/60 の bucket を rm）+ 低頻度ゲート
  `maybe_prune_task_seq`（stamp file、GC_INTERVAL に 1 回）を新設し `generate_task_id`
  冒頭から呼ぶ。root/STALE/INTERVAL を env 化（`TPROJ_MSG_TASK_SEQ_DIR` /
  `_STALE_SEC` 既定 3600 / `_GC_INTERVAL` 既定 3600）。既定 STALE=1h >> 1 分割当なので
  現在バケットは絶対に触らない。seq_root ハードコードを `TASK_SEQ_ROOT` 化。
- tproj commit: `00c41d1`。
- 実機（一時 dir）: 2h 前 bucket（複数 target）→ 削除 / fresh bucket → 保持、
  interval ゲート: 1 回目（stamp 無）で剪定 + stamp 書込、2 回目（interval 内）は skip。

## E2c — DB error ログのサイズローテ（tproj-msg-db.sh）

- `tt_db_log_error` は無制限 append だった。`tt_db_rotate_error_log`（`stat -f%z` >
  `TPROJ_MSG_DB_ERROR_LOG_MAX` 既定 1MB で `<log>.1` へ mv）を append 前に呼ぶ。
  D4 の flush-worker ログ rotate と同流儀。flush-worker.log は D4 で既にローテ済み。
  直接 `2>>` append も、全論理エラー経路が `tt_db_log_error` を通り total size を見るため
  実質キャップ内。
- tproj commit: `725605b`。
- 実機（一時ログ、cap=1000）: cap 未満 → rotate なし、2034B に膨らませ → `.1` へ退避 +
  新ログは新エントリのみ（39B）。

## E3 — TPROJ_MSG_DEBUG 診断タップ（tproj-msg）

- `dlog` ヘルパ 1 個（`TPROJ_MSG_DEBUG=1` のときだけ `~/.cache/tproj-msg/debug.log`
  = `TPROJ_MSG_DEBUG_LOG` 上書き可、へ timestamped 1 行 append）。既定 off は
  即 return で挙動・出力完全不変。pre-flight verify より前に早期定義（全下流経路から
  呼べるように）。
- タップ点（主要経路）: caller verification（`verify --as: ...`）、send precheck
  （`send precheck: ...`）、dedup block（`dedup: blocked ...`）、enqueue（`queue: enqueued ...`）、
  delivery（`deliver: send-keys ok ...`）、status（`status: ...`）。
- tproj commit: `2cbc53e`。
- 実機（installed binary + 一時 debug log）: 既定 off で `--status` → debug.log **生えない**、
  `TPROJ_MSG_DEBUG=1 --status` → debug.log **生成**（`status: target=<none> ...` 1 行）。

## E4 — テスト送信の隔離ハード化（テストハーネスのみ）

- 本体 `tproj-msg` は既に `TPROJ_MSG_DB_PATH`（tproj-msg-db.sh:18）で DB パス env
  差替可 → **本体変更ゼロ**。DB を触る全スイート（sendability-gate:52 /
  registry-contract:115 / role-handoff:102）は既に temp DB へ export 済み
  （前フェーズで逐次導入）。smoke-bin は tproj-msg 非依存、inbox-check は temp HOME +
  Case D 専用 temp DB で実 DB 非接触。
- E4 の恒久化: 上記 3 スイートの export 直後に **不変条件ガード**を追加
  （`TPROJ_MSG_DB_PATH` 未設定 or 実 production DB を指すなら FATAL + exit 2）。
  将来の編集で隔離が外れても実履歴を汚染しない。既存汚染行は削除せず（履歴は履歴）。
- tproj commit: `ccf03ff`。
- 実機: 全 battery（sendability 40 / registry 4 / role-handoff 22 / smoke 17 /
  inbox 8）実行前後で **実 DB のテスト署名行数 = 0 → 0（delta 0）**。max_id は +3
  （live pane traffic のみ）。ガード単体: 実 path → rc=2 / temp path → rc=0 / unset → rc=2。

## Phase E 検証（各 commit 後・全緑）

- `test-sendability-gate.sh` → **PASS=40 FAIL=0 PENDING=0**（E で新規ケース追加なし）。
- `test-registry-contract.sh` → **PASS=4 FAIL=0**。
- `tests/smoke-bin.sh` → **PASS=17 FAIL=0**。
- `test-inbox-check.sh` → **8 passed, 0 failed**。
- `test-role-handoff.sh`（E4 対象）→ **PASS=22 FAIL=0**。
- 反映: `cp` で `~/bin/{tproj-msg,tproj-msg-db.sh}`（変更分のみ、install.sh は tmux 稼働中のため未実行）。
  installed == repo（byte 一致）。テストハーネスは runtime 非配布のため cp 対象外。

## 逸脱・申し送り（Phase E）

- **E2a は send_dedup も同時に掃除**: タスク明記は gate-dedup だが、D2 で追加された
  send_dedup は構造的に同一（file-per-hash・無制限成長）。共有ヘルパ 1 個で両方を
  同時に締める方が「単調累積の解消」という E2 の趣旨に忠実なため、send_dedup にも
  同ヘルパ呼び出しを 1 行追加した（既定挙動・dedup 判定は不変、掃除は age>=TTL の死骸のみ）。
- **E4 は実質的に前フェーズで隔離済み**: 3 スイートの temp DB export は B/C/D で逐次
  導入されていた。E4 の新規実装はガードによる「恒久化」（回帰防止）と検証。本体変更ゼロ。
- **実 DB は live workspace で ambient に成長**: 他 pane（vibeterm 等）の実トラフィックで
  count が常時増える。E4 検証は「テスト署名行の delta=0」で隔離を証明（生 count 差分は
  ambient と分離）。

---

# 全 Phase 完了サマリ（A-E, msg-repair）

契約プラン `fizzy-floating-bee.md`（P0+P1+P2 全部盛り）を A-E で完了。

## Phase 別 commit（tproj repo）

| Phase | 主眼 | コード commit | state commit | 主要 SHA |
|---|---|---|---|---|
| A | P0-1 診断（RED 契約テスト） | 1 | (B と同時記録) | `4eaee4e` |
| B | P0-1 送信者検証誤爆修正 | 3 | 1 (`d7379b4`) | `2814172` `531ff7e` `fd264ab`（+ general `6a1e7e4`=B1） |
| C | P0-2/P0-3 monitor/read/bare-alias/expire | 5 | 1 (`c59027a`) | `1484a40` `13ca28e` `1459d5e` `d1e9d47` `f731ea0` |
| D | P1 relay/empty/dup/queue/worker | 4 | 1 (`507de79`) | `1202c48` `7fb4c46` `35adc6b` `5cab2c6`（D5 は no-code 提案） |
| E | P2 migration/GC/debug/test 隔離 | 6 | 1 (本 commit) | `44b3cde` `b28c16c` `00c41d1` `725605b` `2cbc53e` `ccf03ff` |

- tproj コード commit 合計: **19**（A1 + B3 + C5 + D4 + E6）。state 記録 commit 4 + 本 finalize 1。
- 別リポ general: B1 の pid_start writer 1 行（`6a1e7e4`、事後報告済み）。

## ゲート推移（PASS 数）

| ゲート | 起点 | B | C | D | E（最終） |
|---|---|---|---|---|---|
| sendability-gate | 26 | 30 | 33 | 40 | **40** |
| registry-contract | —（A で新設, RED 2/4） | 4 | 4 | 4 | **4** |
| smoke-bin | 17 | 17 | 17 | 17 | **17** |
| inbox-check | 3 | 4 | 8 | 8 | **8** |
| role-handoff（参考） | — | — | — | — | **22** |

- sendability-gate の起点 26 は旧「sendability gate 新設」プラン完了時（その前身は 13 ケース）。
  本プランで 26 → 40（B+4 / C+3 / D+7、E は runtime + test 隔離のため新規ケースなし）。
- registry-contract は Phase A の新設スイート（router peer 経路の pid_start 契約）。B で全緑化。

## 到達点

- P0（3 件）: 送信者検証誤爆の構造修正（B）、monitor cursor 前進 + read 化 + bare-alias
  曖昧解決 + expire 通知（C）を実装・回帰固定。
- P1（4 件）: empty/dup reject、queue 行の終端遷移、worker 可観測化を実装（D）。relay 漏れ・
  gate inbound ミラーは監査の結果 tproj 側にバグ無し/受信点が他列所有と判明し、seal 固定 +
  別レーン提案に整理。
- P2（4 件）: user_version migration ゲート、GC 3 種、TPROJ_MSG_DEBUG、テスト隔離ガードを
  実装（E）。再発防止の恒久化まで完了。
- 全フェーズで既存ガード群・出力文言・dedup mark タイミング・fail-closed 検証方針を不変に維持。
