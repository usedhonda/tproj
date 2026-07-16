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
