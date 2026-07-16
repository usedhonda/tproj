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
