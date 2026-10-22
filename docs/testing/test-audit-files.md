# Test file ledger

Baseline: `7fd654a02b49bd7657db4c7516c141d234c11176`. Static review; no new test execution.

[Audit and findings](test-audit.md) · [Per-case/check TSV](test-audit-cases.tsv) · [Structured evidence](test-audit-ledger.json)

`keep` = retain the stated contract, not proof of exhaustive coverage. Findings apply to the named subcase, not automatic whole-file deletion. Shell check sites are not test counts. Case IDs inherit the file-level production boundary; F01/F07/F11/F12 override misleading names.

## T001 — BoundedCommandRunnerTests.swift

[Test source](../../apps/tproj/Tests/TprojLogicTests/BoundedCommandRunnerTests.swift) · 26 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 子processの出力上限・timeout・TERM無視・継承pipeでUIを塞がない

**本番接点:** [BoundedCommandRunner.swift](../../apps/tproj/Sources/TprojLogic/BoundedCommandRunner.swift)

**証拠と限界:** 実shell子を使用。終了時間/exit/outputを検査。test名のreapを独立したzombie検査とは扱わない

**重なり:** `process`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T001-C001](../../apps/tproj/Tests/TprojLogicTests/BoundedCommandRunnerTests.swift#L5) | Drains Concurrent Large Output |
| [T001-C002](../../apps/tproj/Tests/TprojLogicTests/BoundedCommandRunnerTests.swift#L9) | Hung Helper Times Out |
| [T001-C003](../../apps/tproj/Tests/TprojLogicTests/BoundedCommandRunnerTests.swift#L14) | Sigkill Fallback Reaps Through Process Lifecycle |
| [T001-C004](../../apps/tproj/Tests/TprojLogicTests/BoundedCommandRunnerTests.swift#L21) | Ignores Term And Does Not Wait For Inherited Pipe |

## T002 — GhosttyConfigParserTests.swift

[Test source](../../apps/tproj/Tests/TprojLogicTests/GhosttyConfigParserTests.swift) · 30 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 背景色hexの妥当性とRGB変換

**本番接点:** [GhosttyTheme.swift](../../apps/tproj/Sources/TprojLogic/GhosttyTheme.swift)

**証拠と限界:** 純関数の正負入力。実Ghostty設定反映/描画は対象外

**重なり:** `gui-logic`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T002-C001](../../apps/tproj/Tests/TprojLogicTests/GhosttyConfigParserTests.swift#L8) | Parse Hex Valid |
| [T002-C002](../../apps/tproj/Tests/TprojLogicTests/GhosttyConfigParserTests.swift#L14) | Parse Hex Invalid |
| [T002-C003](../../apps/tproj/Tests/TprojLogicTests/GhosttyConfigParserTests.swift#L21) | Parse Hex Channel Mapping |

## T003 — JogCycleTests.swift

[Test source](../../apps/tproj/Tests/TprojLogicTests/JogCycleTests.swift) · 45 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** roleを除外したpane順序・wrap・空集合

**本番接点:** [JogCycle.swift](../../apps/tproj/Sources/TprojLogic/JogCycle.swift)

**証拠と限界:** 純粋な配列判定。MIDI入力や実focus変更なし

**重なり:** `gui-logic`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T003-C001](../../apps/tproj/Tests/TprojLogicTests/JogCycleTests.swift#L6) | Role Major Left To Right |
| [T003-C002](../../apps/tproj/Tests/TprojLogicTests/JogCycleTests.swift#L17) | Non Codex Claude Excluded |
| [T003-C003](../../apps/tproj/Tests/TprojLogicTests/JogCycleTests.swift#L27) | Step Wraps At Ends |
| [T003-C004](../../apps/tproj/Tests/TprojLogicTests/JogCycleTests.swift#L35) | Active Outside List Starts At First |
| [T003-C005](../../apps/tproj/Tests/TprojLogicTests/JogCycleTests.swift#L42) | Empty Order Returns Nil |

## T004 — JogQuantizerTests.swift

[Test source](../../apps/tproj/Tests/TprojLogicTests/JogQuantizerTests.swift) · 44 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** MIDI相対値decode・蓄積・反転・rate limit

**本番接点:** [JogQuantizer.swift](../../apps/tproj/Sources/TprojLogic/JogQuantizer.swift)

**証拠と限界:** 明示時刻の純関数。実デバイスなし。大きな1入力と蓄積は別境界

**重なり:** `gui-logic`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T004-C001](../../apps/tproj/Tests/TprojLogicTests/JogQuantizerTests.swift#L6) | Accumulates To One Step |
| [T004-C002](../../apps/tproj/Tests/TprojLogicTests/JogQuantizerTests.swift#L14) | Single Delta At Threshold Fires |
| [T004-C003](../../apps/tproj/Tests/TprojLogicTests/JogQuantizerTests.swift#L20) | Direction Reversal Resets Accumulator |
| [T004-C004](../../apps/tproj/Tests/TprojLogicTests/JogQuantizerTests.swift#L30) | Min Interval Suppresses Rapid Step |
| [T004-C005](../../apps/tproj/Tests/TprojLogicTests/JogQuantizerTests.swift#L39) | Relative C C Decode |

## T005 — KeepWarmTests.swift

[Test source](../../apps/tproj/Tests/TprojLogicTests/KeepWarmTests.swift) · 92 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** fresh/boundなsessionだけpoke候補とする

**本番接点:** [KeepWarm.swift](../../apps/tproj/Sources/TprojLogic/KeepWarm.swift)

**証拠と限界:** fixtureの状態/時刻判断。送信側の再検証はcc-pokeの別責務

**重なり:** `cache`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T005-C001](../../apps/tproj/Tests/TprojLogicTests/KeepWarmTests.swift#L5) | Local Observation Requires Exact Fresh Pane Binding And Cannot Poke |
| [T005-C002](../../apps/tproj/Tests/TprojLogicTests/KeepWarmTests.swift#L28) | Poke Eligibility Boundaries |
| [T005-C003](../../apps/tproj/Tests/TprojLogicTests/KeepWarmTests.swift#L61) | Codex Pane State Blocks Poke Unless Idle Quiet And Not Typing |
| [T005-C004](../../apps/tproj/Tests/TprojLogicTests/KeepWarmTests.swift#L77) | Codex Auto Poke Needs Quiet Idle And Recent Human Message |

## T006 — RoleModeTests.swift

[Test source](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift) · 207 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** mode parse/roundtripとusageの選択・期限・通知情報最小化

**本番接点:** [RoleMode.swift](../../apps/tproj/Sources/TprojLogic/RoleMode.swift) / [CodexBarPace.swift](../../apps/tproj/Sources/TprojLogic/CodexBarPace.swift)

**証拠と限界:** 純関数。RoleMode名のファイルにusageも同居。実account取得/通知到達とは別

**重なり:** `gui-logic`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T006-C001](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L6) | Parse Absent Is Auto |
| [T006-C002](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L11) | Parse Corrupt Is Auto |
| [T006-C003](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L17) | Parse Unknown Mode Is Auto |
| [T006-C004](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L23) | Parse Valid Modes |
| [T006-C005](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L31) | Cycle Order |
| [T006-C006](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L38) | Auto Has No File Contents |
| [T006-C007](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L44) | File Contents Shape |
| [T006-C008](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L60) | Parse Status |
| [T006-C009](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L70) | Badge Label Composition |
| [T006-C010](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L81) | Conversation Main Is Independent And Builds Canonical Command |
| [T006-C011](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L92) | Weekly Pace Alert Uses Fresh Preferred Snapshots Only |
| [T006-C012](../../apps/tproj/Tests/TprojLogicTests/RoleModeTests.swift#L180) | Session Snapshot Uses Selected Account And Latest Valid Entry |

## T007 — TmuxServiceTests.swift

[Test source](../../apps/tproj/Tests/TprojLogicTests/TmuxServiceTests.swift) · 91 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** argv組立・pane解析・非zero結果の扱い

**本番接点:** [TmuxService.swift](../../apps/tproj/Sources/TprojLogic/TmuxService.swift)

**証拠と限界:** RecordingRunner。実tmuxなし。BoundedCommandRunnerとは層が異なる

**重なり:** `gui-logic`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T007-C001](../../apps/tproj/Tests/TprojLogicTests/TmuxServiceTests.swift#L35) | List Panes Sends Expected Argv |
| [T007-C002](../../apps/tproj/Tests/TprojLogicTests/TmuxServiceTests.swift#L45) | List Panes Parses Output |
| [T007-C003](../../apps/tproj/Tests/TprojLogicTests/TmuxServiceTests.swift#L57) | List Panes Returns Empty On Non Zero Exit |
| [T007-C004](../../apps/tproj/Tests/TprojLogicTests/TmuxServiceTests.swift#L64) | Set Option Sends Expected Argv |
| [T007-C005](../../apps/tproj/Tests/TprojLogicTests/TmuxServiceTests.swift#L74) | Get Option Sends Expected Argv And Trims Value |
| [T007-C006](../../apps/tproj/Tests/TprojLogicTests/TmuxServiceTests.swift#L85) | Get Option Returns Nil For Missing Value |

## T008 — WorkspaceLocationGuardTests.swift

[Test source](../../apps/tproj/Tests/TprojLogicTests/WorkspaceLocationGuardTests.swift) · 50 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** project IDのhost/path拘束・並び順非依存

**本番接点:** [WorkspaceLocationGuard.swift](../../apps/tproj/Sources/TprojLogic/WorkspaceLocationGuard.swift)

**証拠と限界:** 純関数。実保存のlock/mergeとは別。UIクリック保存は未証明

**重なり:** `workspace`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T008-C001](../../apps/tproj/Tests/TprojLogicTests/WorkspaceLocationGuardTests.swift#L5) | Project I D Cannot Cross Host At Same Path |
| [T008-C002](../../apps/tproj/Tests/TprojLogicTests/WorkspaceLocationGuardTests.swift#L13) | Project I D At Exact Location Remains Valid |
| [T008-C003](../../apps/tproj/Tests/TprojLogicTests/WorkspaceLocationGuardTests.swift#L20) | Unknown Project I D Can Reuse Unambiguous Location |
| [T008-C004](../../apps/tproj/Tests/TprojLogicTests/WorkspaceLocationGuardTests.swift#L27) | Stale Local Model Does Not Match Remote Disk Location |
| [T008-C005](../../apps/tproj/Tests/TprojLogicTests/WorkspaceLocationGuardTests.swift#L33) | Unchanged Location Matches Regardless Of Ordering |
| [T008-C006](../../apps/tproj/Tests/TprojLogicTests/WorkspaceLocationGuardTests.swift#L39) | Legacy Location Fields Default From Active Path |

## T009 — test-cc-cache-observer.py

[Test source](../../extensions/hooks/tests/test-cc-cache-observer.py) · 126 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** statusline出力保持・binding/epoch・秘密非保存・権限

**本番接点:** [tproj-cc-cache-observer](../../extensions/hooks/tproj-cc-cache-observer) / [tproj-cc-statusline-tap](../../extensions/hooks/tproj-cc-statusline-tap)

**証拠と限界:** 実tapとobserver、agent_binding差替え。service API/実CC eventは未証明

**重なり:** `cache`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T009-C001](../../extensions/hooks/tests/test-cc-cache-observer.py#L27) | statusline tap preserves renderer output and observes copy |
| [T009-C002](../../extensions/hooks/tests/test-cc-cache-observer.py#L48) | statusline prompt and keepalive are scoped and private |

## T010 — test-cc-poke.py

[Test source](../../extensions/hooks/tests/test-cc-poke.py) · 140 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 期限claimで送信重複防止・draft/古いPID拒否

**本番接点:** [tproj-cc-poke](../../extensions/hooks/tproj-cc-poke)

**証拠と限界:** 実sender、fake tmux/状態。send-keys回数で副作用検査。実composer未確認

**重なり:** `cache`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T010-C001](../../extensions/hooks/tests/test-cc-poke.py#L79) | sends once and atomic expiry lock deduplicates |
| [T010-C002](../../extensions/hooks/tests/test-cc-poke.py#L89) | existing ccstatusbar claim prevents duplicate send |
| [T010-C003](../../extensions/hooks/tests/test-cc-poke.py#L98) | stop or question or stale prompt refuses without send |
| [T010-C004](../../extensions/hooks/tests/test-cc-poke.py#L111) | draft and unknown cache version refuse without send |
| [T010-C005](../../extensions/hooks/tests/test-cc-poke.py#L126) | old agent binding cannot send to new or missing agent |

## T011 — test-claude-cache-observer-installer.sh

[Test source](../../extensions/hooks/tests/test-claude-cache-observer-installer.sh) · 12 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 既存hook/statusline保全・再install不変

**本番接点:** [install-tproj-claude-cache-observer](../../extensions/hooks/install-tproj-claude-cache-observer)

**証拠と限界:** 隔離HOMEの実installer。文字列/内容hash。loaded hookは未証明

**重なり:** `install`.

Shellの検査位置 2 件はcase台帳の `T011` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T012 — test-codex-cache-observer-installer.sh

[Test source](../../extensions/hooks/tests/test-codex-cache-observer-installer.sh) · 31 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 既存設定保持・dry-run・不正trust応答で不変

**本番接点:** [install-tproj-codex-cache-observer](../../extensions/hooks/install-tproj-codex-cache-observer)

**証拠と限界:** 隔離HOME。trust応答は人工fixture、実承認成功ではない

**重なり:** `install`.

Shellの検査位置 7 件はcase台帳の `T012` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T013 — test-codex-cache-observer.py

[Test source](../../extensions/hooks/tests/test-codex-cache-observer.py) · 109 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** exact transcriptの数値だけ保存・曖昧/remote binding拒否

**本番接点:** [tproj-codex-cache-observer](../../extensions/hooks/tproj-codex-cache-observer)

**証拠と限界:** 実CLIと人工JSONL/registry。providerのevent schema更新は別検証

**重なり:** `cache`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T013-C001](../../extensions/hooks/tests/test-codex-cache-observer.py#L14) | records bound codex event without inventing cache sample |
| [T013-C002](../../extensions/hooks/tests/test-codex-cache-observer.py#L48) | exact hook transcript yields numeric sample only |
| [T013-C003](../../extensions/hooks/tests/test-codex-cache-observer.py#L91) | ambiguous or remote binding writes nothing |

## T014 — test-completion-guard-consult.sh

[Test source](../../extensions/hooks/tests/test-completion-guard-consult.sh) · 258 lines · CI: `not-in-test-workflow` · `strengthen`

**守るもの:** consult/reflectionを実行/Stopの許可gateにしない

**本番接点:** [tproj-completion-guard](../../extensions/hooks/tproj-completion-guard) / [tproj-msg](../../extensions/messaging/tproj-msg)

**証拠と限界:** 実guard、fake routerと状態。negative-only expectはhook crashでも非block扱いになり得る

**重なり:** `legacy-task` · **指摘:** F09.

Shellの検査位置 39 件はcase台帳の `T014` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T015 — test-formal-task-guard.py

[Test source](../../extensions/hooks/tests/test-formal-task-guard.py) · 265 lines · CI: `not-in-test-workflow` · `consolidate`

**守るもの:** 通常作業非占有・exact retired callbackのfence・native hook wire

**本番接点:** [tproj-formal-task-guard](../../extensions/hooks/tproj-formal-task-guard) / [tproj-mutation-guard](../../extensions/hooks/tproj-mutation-guard) / [tproj-completion-guard](../../extensions/hooks/tproj-completion-guard)

**証拠と限界:** 実evaluateとjournal、RPC差替え。一部名前/unused RPC故障注入が旧仕様のまま

**重なり:** `formal-task` · **指摘:** F01.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T015-C001](../../extensions/hooks/tests/test-formal-task-guard.py#L16) | existing hook entrypoints call formal evaluator |
| [T015-C002](../../extensions/hooks/tests/test-formal-task-guard.py#L44) | native wire has no internal allow decision |
| [T015-C003](../../extensions/hooks/tests/test-formal-task-guard.py#L63) | unassigned is fail open |
| [T015-C004](../../extensions/hooks/tests/test-formal-task-guard.py#L68) | retired operation is fenced without marker but fresh is unassigned |
| [T015-C005](../../extensions/hooks/tests/test-formal-task-guard.py#L79) | bound conversation does not capture later native work |
| [T015-C006](../../extensions/hooks/tests/test-formal-task-guard.py#L87) | caller boolean does not create task admission |
| [T015-C007](../../extensions/hooks/tests/test-formal-task-guard.py#L95) | retired callback is fenced from local journal when rpc offline |
| [T015-C008](../../extensions/hooks/tests/test-formal-task-guard.py#L105) | journal present without native history does not rpc |
| [T015-C009](../../extensions/hooks/tests/test-formal-task-guard.py#L111) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C010](../../extensions/hooks/tests/test-formal-task-guard.py#L120) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C011](../../extensions/hooks/tests/test-formal-task-guard.py#L126) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C012](../../extensions/hooks/tests/test-formal-task-guard.py#L134) | corrupt journal never means unassigned |
| [T015-C013](../../extensions/hooks/tests/test-formal-task-guard.py#L147) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C014](../../extensions/hooks/tests/test-formal-task-guard.py#L153) | empty write stdin poll does not complete formal operation |
| [T015-C015](../../extensions/hooks/tests/test-formal-task-guard.py#L160) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C016](../../extensions/hooks/tests/test-formal-task-guard.py#L176) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C017](../../extensions/hooks/tests/test-formal-task-guard.py#L188) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C018](../../extensions/hooks/tests/test-formal-task-guard.py#L200) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C019](../../extensions/hooks/tests/test-formal-task-guard.py#L213) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C020](../../extensions/hooks/tests/test-formal-task-guard.py#L223) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |
| [T015-C021](../../extensions/hooks/tests/test-formal-task-guard.py#L232) | native exec lifecycle literal does not open an operation |
| [T015-C022](../../extensions/hooks/tests/test-formal-task-guard.py#L242) | quoted heredoc msg is lifecycle but other heredocs are not |
| [T015-C023](../../extensions/hooks/tests/test-formal-task-guard.py#L257) | Actual oracle: ordinary operation remains allow (and some cases assert zero RPC); historical name does not establish denial/forward/close. See F01. |

## T016 — test-inbox-check.sh

[Test source](../../extensions/hooks/tests/test-inbox-check.sh) · 752 lines · CI: `direct` · `strengthen`

**守るもの:** owner別notice・DB移行・一度きりの通知・usage通知

**本番接点:** [tproj-inbox-check](../../extensions/hooks/tproj-inbox-check) / [tproj-inbox-record](../../extensions/hooks/tproj-inbox-record) / [tproj-task-cache.sh](../../extensions/messaging/tproj-task-cache.sh) / [tproj-msg-db.sh](../../extensions/messaging/tproj-msg-db.sh)

**証拠と限界:** 実hook/DB/cacheとfake tmux/msg。task-ID生成部分のみテスト側コピー＋grep

**重なり:** `legacy-task` · **指摘:** F04.

Shellの検査位置 116 件はcase台帳の `T016` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T017 — test-inbox-record-peer-outbox.sh

[Test source](../../extensions/hooks/tests/test-inbox-record-peer-outbox.sh) · 64 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 記録hookからprepared outboxをexact条件でcommit

**本番接点:** [tproj-inbox-record](../../extensions/hooks/tproj-inbox-record) / [tproj-peer-outbox](../../extensions/messaging/tproj-peer-outbox)

**証拠と限界:** 実helper/SQLite、fake tmux。authority/SSH配送は別

**重なり:** `peer-legacy`.

Shellの検査位置 5 件はcase台帳の `T017` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T018 — test-install-tproj-hooks-metadata.py

[Test source](../../extensions/hooks/tests/test-install-tproj-hooks-metadata.py) · 94 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** hook matcher移行・custom保持・platform別failure・metadata検証

**本番接点:** [install-tproj-hooks](../../extensions/hooks/install-tproj-hooks)

**証拠と限界:** installer mergeの直接呼出し。runtime-installerとは関数/配置の層違い

**重なり:** `install`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T018-C001](../../extensions/hooks/tests/test-install-tproj-hooks-metadata.py#L16) | native matcher migration preserves custom hooks |
| [T018-C002](../../extensions/hooks/tests/test-install-tproj-hooks-metadata.py#L33) | completion migration covers edits without clobbering custom entries |
| [T018-C003](../../extensions/hooks/tests/test-install-tproj-hooks-metadata.py#L55) | failure hook is platform specific |
| [T018-C004](../../extensions/hooks/tests/test-install-tproj-hooks-metadata.py#L65) | optional hook is accepted with required hooks |

## T019 — test-mutation-guard.sh

[Test source](../../extensions/hooks/tests/test-mutation-guard.sh) · 168 lines · CI: `direct` · `keep`

**守るもの:** frozen legacy taskの書込抑止・read-only/報告/解除の範囲

**本番接点:** [tproj-mutation-guard](../../extensions/hooks/tproj-mutation-guard) / [tproj-task-cache.sh](../../extensions/messaging/tproj-task-cache.sh)

**証拠と限界:** 実guard+isolated cache。文字列refusal/empty allow。formal ledgerへの適用は別

**重なり:** `legacy-task`.

Shellの検査位置 28 件はcase台帳の `T019` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T020 — test-task-lifecycle.sh

[Test source](../../extensions/hooks/tests/test-task-lifecycle.sh) · 434 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** ACK/DONE/verify/report/cancel/freezeのlegacy履歴保全

**本番接点:** [tproj-completion-guard](../../extensions/hooks/tproj-completion-guard) / [tproj-task](../../extensions/messaging/tproj-task) / [tproj-task-cache.sh](../../extensions/messaging/tproj-task-cache.sh)

**証拠と限界:** 実CLI/hook/SQLite、fake router。installer部分は重なりありだが信頼hash拒否の独自境界

**重なり:** `legacy-task`.

Shellの検査位置 47 件はcase台帳の `T020` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T021 — test_runtime.py

[Test source](../../extensions/messaging/external/kai-event-probe/test_runtime.py) · 91 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** probeのoffline準備・秘密ファイル権限・設定衝突・冪等

**本番接点:** [runtime.py](../../extensions/messaging/external/kai-event-probe/runtime.py)

**証拠と限界:** fake executableと一時ファイル。外部event配送/本番launchdではない

**重なり:** `probe`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T021-C001](../../extensions/messaging/external/kai-event-probe/test_runtime.py#L32) | offline prepare is inert and isolated |
| [T021-C002](../../extensions/messaging/external/kai-event-probe/test_runtime.py#L41) | conflicting manifest refuses overwrite |
| [T021-C003](../../extensions/messaging/external/kai-event-probe/test_runtime.py#L50) | offline then unexpected profile is rejected |
| [T021-C004](../../extensions/messaging/external/kai-event-probe/test_runtime.py#L59) | runner rejects missing or insecure key |
| [T021-C005](../../extensions/messaging/external/kai-event-probe/test_runtime.py#L69) | safe key allows local init only |
| [T021-C006](../../extensions/messaging/external/kai-event-probe/test_runtime.py#L78) | offline then key init keeps runner idempotent |

## T022 — test_server.py

[Test source](../../extensions/messaging/external/kai-event-probe/test_server.py) · 72 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** probe subscription/expiry/id衝突・digestのみ返却

**本番接点:** [server.py](../../extensions/messaging/external/kai-event-probe/server.py)

**証拠と限界:** 実状態保存、HTTP sender差替え。製品KAI eventsの合格に転用不可

**重なり:** `probe`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T022-C001](../../extensions/messaging/external/kai-event-probe/test_server.py#L27) | corrupt state fails closed |
| [T022-C002](../../extensions/messaging/external/kai-event-probe/test_server.py#L33) | malformed unsubscribe is json rpc error |
| [T022-C003](../../extensions/messaging/external/kai-event-probe/test_server.py#L38) | stable event id reuses payload and rejects conflict |
| [T022-C004](../../extensions/messaging/external/kai-event-probe/test_server.py#L54) | expired subscription is not delivered |
| [T022-C005](../../extensions/messaging/external/kai-event-probe/test_server.py#L63) | context is digest only |

## T023 — test_connection.py

[Test source](../../extensions/messaging/external/kai-mcp/test_connection.py) · 73 lines · CI: `discovery` · `keep`

**守るもの:** principal/scope/incarnationの結合とエラー秘匿

**本番接点:** [connection.py](../../extensions/messaging/external/kai-mcp/connection.py)

**証拠と限界:** attestor差替え。runtime/serverから使われる純認証境界

**重なり:** `kai`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T023-C001](../../extensions/messaging/external/kai-mcp/test_connection.py#L25) | fixed scope and host incarnation are returned |
| [T023-C002](../../extensions/messaging/external/kai-mcp/test_connection.py#L31) | scope or enrollment mismatch fails closed |
| [T023-C003](../../extensions/messaging/external/kai-mcp/test_connection.py#L36) | attestation rejection is sanitized |
| [T023-C004](../../extensions/messaging/external/kai-mcp/test_connection.py#L54) | event view uses same binding |
| [T023-C005](../../extensions/messaging/external/kai-mcp/test_connection.py#L60) | restart keeps generation but rotation changes event owner |

## T024 — test_conversation.py

[Test source](../../extensions/messaging/external/kai-mcp/test_conversation.py) · 458 lines · CI: `discovery` · `keep`

**守るもの:** conversation分離・revocation/expiry・永続reload・同時enroll・ID namespace

**本番接点:** [conversation.py](../../extensions/messaging/external/kai-mcp/conversation.py)

**証拠と限界:** 実ファイル/lockとthread、attestor/factory差替え。provider native identity供給は未証明

**重なり:** `kai`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T024-C001](../../extensions/messaging/external/kai-mcp/test_conversation.py#L40) | two independent contexts resolve distinct entries |
| [T024-C002](../../extensions/messaging/external/kai-mcp/test_conversation.py#L48) | wrong absent and expired contexts are denied |
| [T024-C003](../../extensions/messaging/external/kai-mcp/test_conversation.py#L60) | duplicate mapping and aliases are rejected |
| [T024-C004](../../extensions/messaging/external/kai-mcp/test_conversation.py#L70) | raw request metadata alone cannot authorize |
| [T024-C005](../../extensions/messaging/external/kai-mcp/test_conversation.py#L80) | load from json config |
| [T024-C006](../../extensions/messaging/external/kai-mcp/test_conversation.py#L89) | owner policy aliases and order roundtrip as same policy |
| [T024-C007](../../extensions/messaging/external/kai-mcp/test_conversation.py#L123) | malformed reload does not publish policy or provenance |
| [T024-C008](../../extensions/messaging/external/kai-mcp/test_conversation.py#L156) | explicit enroll reconnects distinct identity and fences revoke |
| [T024-C009](../../extensions/messaging/external/kai-mcp/test_conversation.py#L179) | cross instance resolve reloads revocation and expired enroll is unchanged |
| [T024-C010](../../extensions/messaging/external/kai-mcp/test_conversation.py#L200) | removed persisted owner policy fails closed without resurrection |
| [T024-C011](../../extensions/messaging/external/kai-mcp/test_conversation.py#L218) | expiry rechecked after reload when clock advances while waiting |
| [T024-C012](../../extensions/messaging/external/kai-mcp/test_conversation.py#L245) | load rejects group readable or symlinked registry |
| [T024-C013](../../extensions/messaging/external/kai-mcp/test_conversation.py#L259) | malformed owner private registry returns fixed error |
| [T024-C014](../../extensions/messaging/external/kai-mcp/test_conversation.py#L268) | policy denial and nonfinite expiry do not mutate config |
| [T024-C015](../../extensions/messaging/external/kai-mcp/test_conversation.py#L289) | concurrent enrollment creates one binding |
| [T024-C016](../../extensions/messaging/external/kai-mcp/test_conversation.py#L314) | resolver revalidates persisted revoke after factory |
| [T024-C017](../../extensions/messaging/external/kai-mcp/test_conversation.py#L337) | resolver revalidates expiry after factory without reattesting |
| [T024-C018](../../extensions/messaging/external/kai-mcp/test_conversation.py#L364) | send and reply submission ids are binding and operation scoped |
| [T024-C019](../../extensions/messaging/external/kai-mcp/test_conversation.py#L393) | submission namespace encoding separates delimiter like values |
| [T024-C020](../../extensions/messaging/external/kai-mcp/test_conversation.py#L404) | invalid submission ids use existing validator without host call |
| [T024-C021](../../extensions/messaging/external/kai-mcp/test_conversation.py#L427) | changed payload keeps namespaced id for host conflict |

## T025 — test_events.py

[Test source](../../extensions/messaging/external/kai-mcp/test_events.py) · 337 lines · CI: `discovery` · `keep`

**守るもの:** event outbox crash回復・同ID再試行・期限/取消・body非送出

**本番接点:** [events.py](../../extensions/messaging/external/kai-mcp/events.py)

**証拠と限界:** 実durable state、HTTP/DNS/timeを差替え。webhook到達/購読providerは未証明

**重なり:** `kai`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T025-C001](../../extensions/messaging/external/kai-mcp/test_events.py#L41) | missing auth and invalid page fail before send |
| [T025-C002](../../extensions/messaging/external/kai-mcp/test_events.py#L54) | post crash recovers exact persisted id and payload |
| [T025-C003](../../extensions/messaging/external/kai-mcp/test_events.py#L83) | expiry incarnation and unsubscribe fence pending delivery |
| [T025-C004](../../extensions/messaging/external/kai-mcp/test_events.py#L110) | failed delivery has bounded attempts |
| [T025-C005](../../extensions/messaging/external/kai-mcp/test_events.py#L122) | one active callback per binding |
| [T025-C006](../../extensions/messaging/external/kai-mcp/test_events.py#L127) | cancelled mailbox entry never becomes event |
| [T025-C007](../../extensions/messaging/external/kai-mcp/test_events.py#L135) | http error status is persisted without response secrets |
| [T025-C008](../../extensions/messaging/external/kai-mcp/test_events.py#L168) | post exception is classified without exception text |
| [T025-C009](../../extensions/messaging/external/kai-mcp/test_events.py#L187) | successful http response keeps legacy body tolerance |
| [T025-C010](../../extensions/messaging/external/kai-mcp/test_events.py#L217) | historical terminal record is not annotated |
| [T025-C011](../../extensions/messaging/external/kai-mcp/test_events.py#L237) | wire cursor is null and internal cursor remains durable |
| [T025-C012](../../extensions/messaging/external/kai-mcp/test_events.py#L249) | permanent status is terminal without automatic retry |
| [T025-C013](../../extensions/messaging/external/kai-mcp/test_events.py#L272) | legacy integer cursor rejected without mutating history |
| [T025-C014](../../extensions/messaging/external/kai-mcp/test_events.py#L286) | retry once claims one terminal event and never requeues |
| [T025-C015](../../extensions/messaging/external/kai-mcp/test_events.py#L301) | retry once rejects binding expiry and hash without post |
| [T025-C016](../../extensions/messaging/external/kai-mcp/test_events.py#L320) | retry once crash after claim is unknown and not posted again |

## T026 — test_mailbox_tools.py

[Test source](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py) · 348 lines · CI: `discovery` · `strengthen`

**守るもの:** tool引数/認証・exact reply・query投影・cancel後本文非返却

**本番接点:** [mailbox_tools.py](../../extensions/messaging/external/kai-mcp/mailbox_tools.py)

**証拠と限界:** 主にhost stub、一件real Host/Hub。定数だけのassertあり。listはhost policyへ委譲

**重なり:** `kai` · **指摘:** F02, F12.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T026-C001](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L46) | message preserves response evidence without synthesizing ack |
| [T026-C002](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L59) | repo tools send only declared fields to the service ops |
| [T026-C003](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L85) | write tools send only declared fields and never a content copy in the text |
| [T026-C004](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L105) | rejected authorizer makes zero host calls |
| [T026-C005](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L112) | diagnose is metadata only and bypasses adapter whoami |
| [T026-C006](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L127) | nested transport unavailable is not identity rejection |
| [T026-C007](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L149) | invalid identity selector is rejected before host |
| [T026-C008](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L155) | send uses stable submission id and fixed service binding |
| [T026-C009](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L163) | authorized service target sends once and rejects out of scope forms |
| [T026-C010](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L176) | unicode project target remains compatible |
| [T026-C011](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L182) | internal dot unicode project target status and send are authorized |
| [T026-C012](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L193) | internal dot unicode project target is delegated to host scope policy |
| [T026-C013](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L200) | project address regex rejects long dotted nonmatching target |
| [T026-C014](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L203) | reply is pinned and ack is scoped |
| [T026-C015](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L214) | reply preloads thread and never reads after commit |
| [T026-C016](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L232) | reply thread lookup failure prevents mutation |
| [T026-C017](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L248) | long lived adapter uses fresh host scope and reply survives empty scope |
| [T026-C018](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L265) | Host service_list projection is returned; adapter does not independently filter authorizer addresses. See F12. |
| [T026-C019](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L270) | inbox hides cancelled envelopes |
| [T026-C020](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L282) | begin present race suppresses cancelled before body |
| [T026-C021](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L297) | begin present unrelated error is not hidden |
| [T026-C022](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L309) | real host cancellation race reread and sent query |

## T027 — test_retry_event_route.py

[Test source](../../extensions/messaging/external/kai-mcp/test_retry_event_route.py) · 81 lines · CI: `discovery` · `keep`

**守るもの:** 既存event再試行のactor/token/party境界

**本番接点:** [runtime.py](../../extensions/messaging/external/kai-mcp/runtime.py) / [host.py](../../extensions/messaging/unified/host.py)

**証拠と限界:** 実route関数、bridge/Host隣接境界stub。実再配送なし

**重なり:** `kai`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T027-C001](../../extensions/messaging/external/kai-mcp/test_retry_event_route.py#L27) | routes only current kai party without body |
| [T027-C002](../../extensions/messaging/external/kai-mcp/test_retry_event_route.py#L52) | rejects foreign recipient before bridge |
| [T027-C003](../../extensions/messaging/external/kai-mcp/test_retry_event_route.py#L63) | bridge rejects forged token and actor |

## T028 — test_runtime.py

[Test source](../../extensions/messaging/external/kai-mcp/test_runtime.py) · 584 lines · CI: `discovery` · `keep`

**守るもの:** bridge frame/byte/deadline/slot・失敗後socket保全・private binding

**本番接点:** [runtime.py](../../extensions/messaging/external/kai-mcp/runtime.py)

**証拠と限界:** 実Unix socket/threadとfake dispatch/時計。外部providerは使わない

**重なり:** `kai`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T028-C001](../../extensions/messaging/external/kai-mcp/test_runtime.py#L30) | whoami binds principal and incarnation |
| [T028-C002](../../extensions/messaging/external/kai-mcp/test_runtime.py#L45) | runtime server tool call uses mocked authenticated host |
| [T028-C003](../../extensions/messaging/external/kai-mcp/test_runtime.py#L63) | mismatched host service is rejected |
| [T028-C004](../../extensions/messaging/external/kai-mcp/test_runtime.py#L70) | bridge allowlist excludes admin operations |
| [T028-C005](../../extensions/messaging/external/kai-mcp/test_runtime.py#L76) | invalid config does not remove live bridge socket |
| [T028-C006](../../extensions/messaging/external/kai-mcp/test_runtime.py#L97) | idle client does not stop bridge |
| [T028-C007](../../extensions/messaging/external/kai-mcp/test_runtime.py#L136) | connection reset probe does not remove socket |
| [T028-C008](../../extensions/messaging/external/kai-mcp/test_runtime.py#L159) | bridge lock rejects symlink |
| [T028-C009](../../extensions/messaging/external/kai-mcp/test_runtime.py#L169) | bridge frame reader rejects incomplete and oversized frames |
| [T028-C010](../../extensions/messaging/external/kai-mcp/test_runtime.py#L186) | bridge frame reader uses total monotonic deadline for trickle |
| [T028-C011](../../extensions/messaging/external/kai-mcp/test_runtime.py#L196) | bridge real connections bound frames before dispatch |
| [T028-C012](../../extensions/messaging/external/kai-mcp/test_runtime.py#L295) | bridge unicode response roundtrips with utf8 frame limit |
| [T028-C013](../../extensions/messaging/external/kai-mcp/test_runtime.py#L350) | bridge response timeout does not redispatch |
| [T028-C014](../../extensions/messaging/external/kai-mcp/test_runtime.py#L413) | slow dispatch does not block next authorized request |
| [T028-C015](../../extensions/messaging/external/kai-mcp/test_runtime.py#L491) | bridge response uses fresh timeout after near deadline receive |

## T029 — test_server.py

[Test source](../../extensions/messaging/external/kai-mcp/test_server.py) · 287 lines · CI: `discovery` · `keep`

**守るもの:** MCP catalog/schema/stdio・identity選択・event capability非偽装

**本番接点:** [server.py](../../extensions/messaging/external/kai-mcp/server.py)

**証拠と限界:** 実handler/stream。tools/resolver/dispatcherは注入。initialize成功と実channel到達は別

**重なり:** `kai`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T029-C001](../../extensions/messaging/external/kai-mcp/test_server.py#L18) | capability diagnosis never claims cloud isolation or reads mailbox |
| [T029-C002](../../extensions/messaging/external/kai-mcp/test_server.py#L40) | initialize and tools list expose contract catalog |
| [T029-C003](../../extensions/messaging/external/kai-mcp/test_server.py#L49) | diagnose preserves sanitized resource details |
| [T029-C004](../../extensions/messaging/external/kai-mcp/test_server.py#L62) | catalog target patterns match runtime for status and send |
| [T029-C005](../../extensions/messaging/external/kai-mcp/test_server.py#L82) | optional event dispatcher adds capability only when injected |
| [T029-C006](../../extensions/messaging/external/kai-mcp/test_server.py#L101) | conversation resolver cannot reach fixed event state |
| [T029-C007](../../extensions/messaging/external/kai-mcp/test_server.py#L127) | event subscribe rejects resume cursor without adapter side effect |
| [T029-C008](../../extensions/messaging/external/kai-mcp/test_server.py#L163) | event protocol negotiates 2026 and rejects old clients |
| [T029-C009](../../extensions/messaging/external/kai-mcp/test_server.py#L172) | default call fails closed without host access |
| [T029-C010](../../extensions/messaging/external/kai-mcp/test_server.py#L178) | injected tools are called and structured result returned |
| [T029-C011](../../extensions/messaging/external/kai-mcp/test_server.py#L190) | request resolver selects enrolled tools and denial never falls back |
| [T029-C012](../../extensions/messaging/external/kai-mcp/test_server.py#L249) | malformed tool names preserve stdio and skip identity |
| [T029-C013](../../extensions/messaging/external/kai-mcp/test_server.py#L266) | stdio pump obeys same resolver boundary as events |
| [T029-C014](../../extensions/messaging/external/kai-mcp/test_server.py#L278) | stdio reports parse error and suppresses notifications |

## T030 — test-alias-retire.py

[Test source](../../extensions/messaging/tests/test-alias-retire.py) · 60 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** alias改名redirect・同ID保持・retire名再利用拒否

**本番接点:** [hub.py](../../extensions/messaging/unified/hub.py)

**証拠と限界:** real SQLite/Hub dispatch。endpoint/hostはfixture

**重なり:** `hub`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T030-C001](../../extensions/messaging/tests/test-alias-retire.py#L28) | old name is redirected with a notice and a retry is the same message |
| [T030-C002](../../extensions/messaging/tests/test-alias-retire.py#L38) | retired project leaves the directory and the name cannot be reused |
| [T030-C003](../../extensions/messaging/tests/test-alias-retire.py#L45) | refusals |

## T031 — test-approval-evidence.py

[Test source](../../extensions/messaging/tests/test-approval-evidence.py) · 114 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** native approvalのscope/順序・peer混入・Goal証拠失効

**本番接点:** [task_approval.py](../../extensions/messaging/unified/task_approval.py) / [task_role.py](../../extensions/messaging/unified/task_role.py)

**証拠と限界:** 人工native記録と実attest/validator。Goal builtinの実carry全操作証明ではない

**重なり:** `formal-task`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T031-C001](../../extensions/messaging/tests/test-approval-evidence.py#L9) | cc native metadata cannot create or bridge owner approval |
| [T031-C002](../../extensions/messaging/tests/test-approval-evidence.py#L24) | summarized intent and ordered native evidence |
| [T031-C003](../../extensions/messaging/tests/test-approval-evidence.py#L42) | setter exact scope native and record identity |
| [T031-C004](../../extensions/messaging/tests/test-approval-evidence.py#L48) | continuation spoof and nested compaction cannot create evidence |
| [T031-C005](../../extensions/messaging/tests/test-approval-evidence.py#L53) | clear and same text reset never reactivate old proof |
| [T031-C006](../../extensions/messaging/tests/test-approval-evidence.py#L60) | omitted malformed duplicate and inactive do not fall back |
| [T031-C007](../../extensions/messaging/tests/test-approval-evidence.py#L67) | status resume is new lifecycle evidence not old hash |
| [T031-C008](../../extensions/messaging/tests/test-approval-evidence.py#L74) | existing public approval does not accept goal wrapper |
| [T031-C009](../../extensions/messaging/tests/test-approval-evidence.py#L79) | same native project movement preserves approval isolation |

## T032 — test-bare-remote-role-route.sh

[Test source](../../extensions/messaging/tests/test-bare-remote-role-route.sh) · 78 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** bare remote roleのproject/session一致とtask route

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg)

**証拠と限界:** 実source断片をawk/sed抽出。入口parser/認証済み変数はfixtureで供給

**重なり:** `legacy-route`.

Shellの検査位置 11 件はcase台帳の `T032` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T033 — test-binding-status.py

[Test source](../../extensions/messaging/tests/test-binding-status.py) · 53 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** binding-statusの本人選択禁止・旧bindingと現binding区別・read-only

**本番接点:** [task_cli.py](../../extensions/messaging/unified/task_cli.py) / [task_host.py](../../extensions/messaging/unified/task_host.py)

**証拠と限界:** 実parse/dispatch、stub Host+SQLite。読み取り不変を直接検査

**重なり:** `formal-task`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T033-C001](../../extensions/messaging/tests/test-binding-status.py#L14) | parser uses only authenticated native request |
| [T033-C002](../../extensions/messaging/tests/test-binding-status.py#L22) | stale marker and old endpoint are distinguished without writes |

## T034 — test-bridge-server.sh

[Test source](../../extensions/messaging/tests/test-bridge-server.sh) · 174 lines · CI: `direct` · `keep`

**守るもの:** HTTP bridgeのbusy/dedupe/戻りpayload/失敗通知

**本番接点:** [tproj-bridge.py](../../extensions/messaging/bridge/tproj-bridge.py)

**証拠と限界:** real loopback HTTP+fake Codex/receiver。health/argvは実sandbox実効性を証明しない

**重なり:** `bridge`.

Shellの検査位置 30 件はcase台帳の `T034` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T035 — test-caller-verify-hardening.sh

[Test source](../../extensions/messaging/tests/test-caller-verify-hardening.sh) · 382 lines · CI: `direct` · `keep`

**守るもの:** legacy送信者ancestry/PID-start/時刻境界・audit body非保存

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg)

**証拠と限界:** 実CLIとreal process tree、tmux/websocket stub。unified identityと別入口

**重なり:** `legacy-route`.

Shellの検査位置 32 件はcase台帳の `T035` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T036 — test-chatgpt-msg-skill-contract.sh

[Test source](../../extensions/messaging/tests/test-chatgpt-msg-skill-contract.sh) · 32 lines · CI: `not-in-test-workflow` · `reclassify`

**守るもの:** skillに操作名・境界説明が含まれること

**本番接点:** [SKILL.md](../../extensions/messaging/skill-msg/SKILL.md)

**証拠と限界:** grepのみ。否定文/無関係段落でも通る。動作試験として数えない

**重なり:** `docs-lint` · **指摘:** F05.

Shellの検査位置 21 件はcase台帳の `T036` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T037 — test-cross-mac-host-chat.sh

[Test source](../../extensions/messaging/tests/test-cross-mac-host-chat.sh) · 228 lines · CI: `not-in-test-workflow` · `strengthen`

**守るもの:** remote selector・stdin継続・reverse socketと送信者認証

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg) / [tproj-remote-relay](../../extensions/messaging/tproj-remote-relay)

**証拠と限界:** 実relay UDS/fake SSH・切出しCLI。前半HOME未隔離、現enrollmentに左右される

**重なり:** `legacy-route` · **指摘:** F10.

Shellの検査位置 35 件はcase台帳の `T037` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T038 — test-delivery-diagnostics.py

[Test source](../../extensions/messaging/tests/test-delivery-diagnostics.py) · 91 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** exact native receipt復旧・理由の後付け防止・自己申告operator無効

**本番接点:** [host.py](../../extensions/messaging/unified/host.py) / [receipt.py](../../extensions/messaging/unified/receipt.py) / [identity.py](../../extensions/messaging/unified/identity.py)

**証拠と限界:** 人工JSONL+real Host journal、Hub RPC mock。native consumerではない旧receipt境界

**重なり:** `native`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T038-C001](../../extensions/messaging/tests/test-delivery-diagnostics.py#L7) | only new uncertainty gets evidenced reason |
| [T038-C002](../../extensions/messaging/tests/test-delivery-diagnostics.py#L19) | codex receipt carries native binding and accepts pinned thread |
| [T038-C003](../../extensions/messaging/tests/test-delivery-diagnostics.py#L41) | codex exact transcript recovery rejects wrong evidence |
| [T038-C004](../../extensions/messaging/tests/test-delivery-diagnostics.py#L82) | native host ignores self asserted operator flag |

## T039 — test-desktop-mailbox.sh

[Test source](../../extensions/messaging/tests/test-desktop-mailbox.sh) · 573 lines · CI: `direct` · `keep`

**守るもの:** desktop mailboxのidentity・権限・no paste・容量/同時書込・drain

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg) / [tproj-msg-desktop.sh](../../extensions/messaging/tproj-msg-desktop.sh)

**証拠と限界:** 実CLI/ファイル/複数writer、fake tmux。desktop appモデル到達は対象外

**重なり:** `legacy-route`.

Shellの検査位置 85 件はcase台帳の `T039` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T040 — test-directory-transaction.py

[Test source](../../extensions/messaging/tests/test-directory-transaction.py) · 47 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** directory prepare/commit冪等とhost/path所有不変

**本番接点:** [directory.py](../../extensions/messaging/unified/directory.py)

**証拠と限界:** real Hub/SQLite。begin/commit関数直呼び、wire authは別

**重なり:** `directory`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T040-C001](../../extensions/messaging/tests/test-directory-transaction.py#L13) | prepare commit is idempotent and owner scoped |
| [T040-C002](../../extensions/messaging/tests/test-directory-transaction.py#L25) | rejects project id repointing |
| [T040-C003](../../extensions/messaging/tests/test-directory-transaction.py#L35) | rejects duplicate owner location with new id |

## T041 — test-help-read-unified.sh

[Test source](../../extensions/messaging/tests/test-help-read-unified.sh) · 87 lines · CI: `direct` · `keep`

**守るもの:** enrolled/未登録help差・remote read拒否説明

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg)

**証拠と限界:** 実CLI出力/exit検査。文言検査だが利用者向け公開interfaceなので単なるsource grepとは別

**重なり:** `legacy-route`.

Shellの検査位置 26 件はcase台帳の `T041` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T042 — test-inbox-notice.py

[Test source](../../extensions/messaging/tests/test-inbox-notice.py) · 94 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** native別exact-ID dedupe/cursor移行・metadata-only hook output

**本番接点:** [inbox_notice.py](../../extensions/messaging/unified/inbox_notice.py) / [tproj-completion-guard](../../extensions/hooks/tproj-completion-guard)

**証拠と限界:** 実notice state、RPC helper mock。Hub側候補抽出とは別層

**重なり:** `native`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T042-C001](../../extensions/messaging/tests/test-inbox-notice.py#L21) | codex posttool notice uses hook specific output shape |
| [T042-C002](../../extensions/messaging/tests/test-inbox-notice.py#L33) | exact id dedup is native scoped and metadata only |
| [T042-C003](../../extensions/messaging/tests/test-inbox-notice.py#L50) | cursor advances past deduped rows and migrates legacy state |
| [T042-C004](../../extensions/messaging/tests/test-inbox-notice.py#L64) | pre version cursor rewinds once for backfill without repeating seen ids |

## T043 — test-native-consumer.py

[Test source](../../extensions/messaging/tests/test-native-consumer.py) · 560 lines · CI: `direct` · `keep`

**守るもの:** one-shot本文予約・same-turn receipt・handoff・取消・RPC応答不明回復

**本番接点:** [native_consumer.py](../../extensions/messaging/unified/native_consumer.py) / [host.py](../../extensions/messaging/unified/host.py) / [hub.py](../../extensions/messaging/unified/hub.py)

**証拠と限界:** real SQLite/Host/Hub、一部real OS子/同時thread。native記録は人工、provider到達なし

**重なり:** `native`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T043-C001](../../extensions/messaging/tests/test-native-consumer.py#L75) | initial discovery attests without recipient caller |
| [T043-C002](../../extensions/messaging/tests/test-native-consumer.py#L112) | host refresh uses os death and independent native header |
| [T043-C003](../../extensions/messaging/tests/test-native-consumer.py#L164) | explicit old reservation rejection reconciles only after handoff |
| [T043-C004](../../extensions/messaging/tests/test-native-consumer.py#L187) | rejected old attempt cannot reconcile a later global reservation |
| [T043-C005](../../extensions/messaging/tests/test-native-consumer.py#L205) | unknown old reservation never reconciles even if new actor is pending |
| [T043-C006](../../extensions/messaging/tests/test-native-consumer.py#L222) | new local claim keeps reserved transfer recoverable |
| [T043-C007](../../extensions/messaging/tests/test-native-consumer.py#L243) | current actor generation mismatch stops before body reservation |
| [T043-C008](../../extensions/messaging/tests/test-native-consumer.py#L256) | transferred original resolve recover and host receipt |
| [T043-C009](../../extensions/messaging/tests/test-native-consumer.py#L289) | authenticated dispatch and same turn context evidence not reference alone |
| [T043-C010](../../extensions/messaging/tests/test-native-consumer.py#L310) | pending set one reference individual reservations and receipts |
| [T043-C011](../../extensions/messaging/tests/test-native-consumer.py#L340) | pending set later prepare conflict preserves leader context |
| [T043-C012](../../extensions/messaging/tests/test-native-consumer.py#L355) | pending set later gate failure does not expose failed body |
| [T043-C013](../../extensions/messaging/tests/test-native-consumer.py#L374) | pending set new arrival before drain retains wake |
| [T043-C014](../../extensions/messaging/tests/test-native-consumer.py#L388) | wire bounded escaped body fits native context without truncation |
| [T043-C015](../../extensions/messaging/tests/test-native-consumer.py#L409) | only native resolve client accepts larger response |
| [T043-C016](../../extensions/messaging/tests/test-native-consumer.py#L423) | concurrent consumers reserve original only once |
| [T043-C017](../../extensions/messaging/tests/test-native-consumer.py#L459) | wrong prompt thread path and disabled consumer do not reserve |
| [T043-C018](../../extensions/messaging/tests/test-native-consumer.py#L470) | cancel between query and reservation never exposes body |
| [T043-C019](../../extensions/messaging/tests/test-native-consumer.py#L484) | lost permission response survives reopen without second reservation |
| [T043-C020](../../extensions/messaging/tests/test-native-consumer.py#L543) | receipt request lost stays reconcilable |
| [T043-C021](../../extensions/messaging/tests/test-native-consumer.py#L546) | receipt ack lost queries before closing without resend |
| [T043-C022](../../extensions/messaging/tests/test-native-consumer.py#L549) | owned native delivery never falls back to terminal |

## T044 — test-native-notice.py

[Test source](../../extensions/messaging/tests/test-native-notice.py) · 151 lines · CI: `direct` · `keep`

**守るもの:** immutable origin/token/digest・actor世代・peerを承認へ昇格しない

**本番接点:** [native_notice.py](../../extensions/messaging/unified/native_notice.py) / [task_approval.py](../../extensions/messaging/unified/task_approval.py)

**証拠と限界:** 実SQLiteと人工record。consumerのcontext追加成功とは別

**重なり:** `native`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T044-C001](../../extensions/messaging/tests/test-native-notice.py#L33) | actor binding preserves original notice and rejects old consumer |
| [T044-C002](../../extensions/messaging/tests/test-native-notice.py#L55) | actor binding never resets reserved unknown or notice native origin |
| [T044-C003](../../extensions/messaging/tests/test-native-notice.py#L72) | reference pins original and does not expose peer authority claim |
| [T044-C004](../../extensions/messaging/tests/test-native-notice.py#L86) | wrong thread incarnation endpoint and token fail without writes |
| [T044-C005](../../extensions/messaging/tests/test-native-notice.py#L98) | reused original with changed content or binding is conflict |
| [T044-C006](../../extensions/messaging/tests/test-native-notice.py#L107) | changed or missing journal original cannot validate a reference |
| [T044-C007](../../extensions/messaging/tests/test-native-notice.py#L116) | valid original ids do not become prompt syntax or new gates |
| [T044-C008](../../extensions/messaging/tests/test-native-notice.py#L125) | entire native record must match not just the token |
| [T044-C009](../../extensions/messaging/tests/test-native-notice.py#L137) | native user record cannot turn notice or peer claim into approval |

## T045 — test-native-publication.py

[Test source](../../extensions/messaging/tests/test-native-publication.py) · 369 lines · CI: `direct` · `keep`

**守るもの:** publish前commit・未知結果照合・世代/CAS・取消/expiry再確認

**本番接点:** [native_publication.py](../../extensions/messaging/unified/native_publication.py)

**証拠と限界:** ConsumerTest.setUpのみ共有、test継承なし。FakeJob主体でtransport子timeoutのみ実process

**重なり:** `native`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T045-C001](../../extensions/messaging/tests/test-native-publication.py#L55) | two handoffs do not reuse stale actor projection |
| [T045-C002](../../extensions/messaging/tests/test-native-publication.py#L86) | transferred reference publication uses current binding and original token |
| [T045-C003](../../extensions/messaging/tests/test-native-publication.py#L118) | commit before io and ack does not present body or publish twice |
| [T045-C004](../../extensions/messaging/tests/test-native-publication.py#L135) | wait diagnostic failure cannot wedge publication |
| [T045-C005](../../extensions/messaging/tests/test-native-publication.py#L146) | unknown result reconciles pages without republication |
| [T045-C006](../../extensions/messaging/tests/test-native-publication.py#L166) | reconciled reference recovery preserves body fences and latest permission |
| [T045-C007](../../extensions/messaging/tests/test-native-publication.py#L216) | reconciliation is not blocked by another queued reference |
| [T045-C008](../../extensions/messaging/tests/test-native-publication.py#L227) | recovery backoff and stale attempt cas survive restart |
| [T045-C009](../../extensions/messaging/tests/test-native-publication.py#L246) | cancelled queued leader cannot starve later original |
| [T045-C010](../../extensions/messaging/tests/test-native-publication.py#L260) | restart fences old result and preserves unknown |
| [T045-C011](../../extensions/messaging/tests/test-native-publication.py#L273) | body reservation does not get overwritten by late queue ack |
| [T045-C012](../../extensions/messaging/tests/test-native-publication.py#L285) | bad worker result is unknown not a delivery thread crash |
| [T045-C013](../../extensions/messaging/tests/test-native-publication.py#L293) | transport poll failure cannot kill or wedge scheduler |
| [T045-C014](../../extensions/messaging/tests/test-native-publication.py#L315) | only known prepublication failure is eligible for later attempt |
| [T045-C015](../../extensions/messaging/tests/test-native-publication.py#L342) | known unqueued failure then cancel prevents new publication |
| [T045-C016](../../extensions/messaging/tests/test-native-publication.py#L345) | known unqueued failure then expiry prevents new publication |
| [T045-C017](../../extensions/messaging/tests/test-native-publication.py#L348) | historical unknown is not converted or replayed |
| [T045-C018](../../extensions/messaging/tests/test-native-publication.py#L357) | transport child timeout is bounded and cleans private packet |

## T046 — test-native-queue.py

[Test source](../../extensions/messaging/tests/test-native-queue.py) · 144 lines · CI: `direct` · `keep`

**守るもの:** queue wire検証・固定deadline・add一回・dependency digest

**本番接点:** [native_queue.py](../../extensions/messaging/unified/native_queue.py) / [install-tproj-messaging-runtime](../../extensions/messaging/install-tproj-messaging-runtime)

**証拠と限界:** fake SDK/clientとreal private socket属性。実installed SDK/provider互換は別

**重なり:** `native`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T046-C001](../../extensions/messaging/tests/test-native-queue.py#L36) | conflicting private wheel cannot silently fall back to global |
| [T046-C002](../../extensions/messaging/tests/test-native-queue.py#L43) | dependency install digest failure preserves absence |
| [T046-C003](../../extensions/messaging/tests/test-native-queue.py#L63) | existing private socket and owner symlink only |
| [T046-C004](../../extensions/messaging/tests/test-native-queue.py#L73) | single publication preserves notice and correlation without retry |
| [T046-C005](../../extensions/messaging/tests/test-native-queue.py#L85) | lost or internal error add result is unknown not retried |
| [T046-C006](../../extensions/messaging/tests/test-native-queue.py#L95) | malformed error envelope is unknown not known rejection |
| [T046-C007](../../extensions/messaging/tests/test-native-queue.py#L111) | unrelated notifications cannot reset reply deadline |
| [T046-C008](../../extensions/messaging/tests/test-native-queue.py#L121) | invalid params rejection and invalid binding do not become success |
| [T046-C009](../../extensions/messaging/tests/test-native-queue.py#L131) | list is bounded and initialization failure never sends add |

## T047 — test-peer-authority.py

[Test source](../../extensions/messaging/tests/test-peer-authority.py) · 126 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** legacy peer nonce/receiver/ancestry・commit proof

**本番接点:** [tproj-peer-authority](../../extensions/messaging/tproj-peer-authority)

**証拠と限界:** real outbox+authority、process inspection mock。SSH転送の証拠ではない

**重なり:** `peer-legacy`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T047-C001](../../extensions/messaging/tests/test-peer-authority.py#L66) | registry binding and forgery |
| [T047-C002](../../extensions/messaging/tests/test-peer-authority.py#L80) | nonce exact once and receiver bound |
| [T047-C003](../../extensions/messaging/tests/test-peer-authority.py#L95) | route tombstone and reconnect fail closed |
| [T047-C004](../../extensions/messaging/tests/test-peer-authority.py#L111) | commit proof requires committed outbox |

## T048 — test-peer-forward.py

[Test source](../../extensions/messaging/tests/test-peer-forward.py) · 45 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** SSH argv固定・forward PID-start一致

**本番接点:** [tproj-peer-forward](../../extensions/messaging/tproj-peer-forward)

**証拠と限界:** 実command builder、fake process。remote connection成立は未証明

**重なり:** `peer-legacy`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T048-C001](../../extensions/messaging/tests/test-peer-forward.py#L17) | fixed command and rejected routes |
| [T048-C002](../../extensions/messaging/tests/test-peer-forward.py#L28) | pid start must remain registered |

## T049 — test-peer-outbox.py

[Test source](../../extensions/messaging/tests/test-peer-outbox.py) · 106 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** prepare/commit/tombstone/claimのdurabilityと再claim禁止

**本番接点:** [tproj-peer-outbox](../../extensions/messaging/tproj-peer-outbox)

**証拠と限界:** real SQLite close/reopen。receiver/transportは別

**重なり:** `peer-legacy`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T049-C001](../../extensions/messaging/tests/test-peer-outbox.py#L38) | source durable idempotent and conflicting |
| [T049-C002](../../extensions/messaging/tests/test-peer-outbox.py#L55) | quarantine release and validation |
| [T049-C003](../../extensions/messaging/tests/test-peer-outbox.py#L67) | exact prepared lookup is read only |
| [T049-C004](../../extensions/messaging/tests/test-peer-outbox.py#L89) | delivery claim is durable and never reclaims |

## T050 — test-peer-receiver.py

[Test source](../../extensions/messaging/tests/test-peer-receiver.py) · 127 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** quarantine→release→claim/finish・expiry・epoch拒否

**本番接点:** [tproj-peer-receiver](../../extensions/messaging/tproj-peer-receiver)

**証拠と限界:** real receiver/outbox、authorityとpeer process mock。実SSHなし

**重なり:** `peer-legacy`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T050-C001](../../extensions/messaging/tests/test-peer-receiver.py#L60) | quarantine returns no body then release |
| [T050-C002](../../extensions/messaging/tests/test-peer-receiver.py#L77) | route epoch expiry and unquarantined reject |
| [T050-C003](../../extensions/messaging/tests/test-peer-receiver.py#L92) | forward peer pid and start binding |
| [T050-C004](../../extensions/messaging/tests/test-peer-receiver.py#L102) | local tombstone prevents release |
| [T050-C005](../../extensions/messaging/tests/test-peer-receiver.py#L112) | timeout becomes unknown without reclaim |

## T051 — test-protocol-slot-release.py

[Test source](../../extensions/messaging/tests/test-protocol-slot-release.py) · 47 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 切断clientでもconcurrency slotを返す

**本番接点:** [protocol.py](../../extensions/messaging/unified/protocol.py)

**証拠と限界:** fake listener/socketと実serve_socket。17 request処理数でslot漏れ検出

**重なり:** `protocol`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T051-C001](../../extensions/messaging/tests/test-protocol-slot-release.py#L40) | seventeen disconnected clients do not exhaust sixteen slots |

## T052 — test-registry-contract.sh

[Test source](../../extensions/messaging/tests/test-registry-contract.sh) · 280 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** router産出pid_startとcaller検証の接続

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg) / [model-role-router](../../extensions/model-role-router/model-role-router)

**証拠と限界:** canonical sibling sourceをimport。P3は観測のみで非fatal、古いRED説明も現結果ではない

**重なり:** `legacy-route` · **指摘:** F13.

Shellの検査位置 24 件はcase台帳の `T052` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T053 — test-repo-access-federation.py

[Test source](../../extensions/messaging/tests/test-repo-access-federation.py) · 162 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** owner側repo grant・remote read/write・frame上限

**本番接点:** [repo_access.py](../../extensions/messaging/unified/repo_access.py) / [federation.py](../../extensions/messaging/unified/federation.py)

**証拠と限界:** 複数real Hub+temp git、remote dispatch/Popen差替え。実SSHなし

**重なり:** `repo-access`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T053-C001](../../extensions/messaging/tests/test-repo-access-federation.py#L63) | owner grant decides and revocation is immediate |
| [T053-C002](../../extensions/messaging/tests/test-repo-access-federation.py#L76) | a remote write changes only the owners tree and needs its own grant |
| [T053-C003](../../extensions/messaging/tests/test-repo-access-federation.py#L89) | a host cannot attest a participant it does not own |
| [T053-C004](../../extensions/messaging/tests/test-repo-access-federation.py#L100) | list aggregates peers and reports unreachable ones |
| [T053-C005](../../extensions/messaging/tests/test-repo-access-federation.py#L112) | invalid forwarding requests are rejected before any transport |
| [T053-C006](../../extensions/messaging/tests/test-repo-access-federation.py#L136) | oversized response is cut off and reported |
| [T053-C007](../../extensions/messaging/tests/test-repo-access-federation.py#L145) | well formed response is returned and garbage is not trusted |

## T054 — test-repo-access-policy.py

[Test source](../../extensions/messaging/tests/test-repo-access-policy.py) · 262 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** grant scope/期限/世代/監査秘匿・移行・operator CLI

**本番接点:** [repo_access_policy.py](../../extensions/messaging/unified/repo_access_policy.py) / [repo-access-cli](../../extensions/messaging/repo-access-cli)

**証拠と限界:** real ledger/CLI、一時directory fixture。service path検査とは別

**重なり:** `repo-access`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T054-C001](../../extensions/messaging/tests/test-repo-access-policy.py#L31) | default deny and perms |
| [T054-C002](../../extensions/messaging/tests/test-repo-access-policy.py#L37) | grant ok and op |
| [T054-C003](../../extensions/messaging/tests/test-repo-access-policy.py#L43) | path scope segment aware |
| [T054-C004](../../extensions/messaging/tests/test-repo-access-policy.py#L53) | expiry |
| [T054-C005](../../extensions/messaging/tests/test-repo-access-policy.py#L61) | root changed |
| [T054-C006](../../extensions/messaging/tests/test-repo-access-policy.py#L65) | regrant replaces and revoke |
| [T054-C007](../../extensions/messaging/tests/test-repo-access-policy.py#L82) | revoke by id |
| [T054-C008](../../extensions/messaging/tests/test-repo-access-policy.py#L86) | revision monotonic |
| [T054-C009](../../extensions/messaging/tests/test-repo-access-policy.py#L98) | generation |
| [T054-C010](../../extensions/messaging/tests/test-repo-access-policy.py#L107) | ops validation |
| [T054-C011](../../extensions/messaging/tests/test-repo-access-policy.py#L115) | sql injection is inert |
| [T054-C012](../../extensions/messaging/tests/test-repo-access-policy.py#L119) | audit only allowed keys |
| [T054-C013](../../extensions/messaging/tests/test-repo-access-policy.py#L150) | read and write grants coexist with their own scopes |
| [T054-C014](../../extensions/messaging/tests/test-repo-access-policy.py#L163) | a read only grant never allows a write and mixed ops are refused |
| [T054-C015](../../extensions/messaging/tests/test-repo-access-policy.py#L168) | an old ledger with one grant per project is migrated in place |
| [T054-C016](../../extensions/messaging/tests/test-repo-access-policy.py#L215) | end to end |
| [T054-C017](../../extensions/messaging/tests/test-repo-access-policy.py#L239) | validation errors |
| [T054-C018](../../extensions/messaging/tests/test-repo-access-policy.py#L253) | stale grant revocable by raw id |

## T055 — test-repo-access.py

[Test source](../../extensions/messaging/tests/test-repo-access.py) · 203 lines · CI: `not-in-test-workflow` · `strengthen`

**守るもの:** tracked text限定・path/symlink/秘密・cursor/revoke・audit

**本番接点:** [repo_access.py](../../extensions/messaging/unified/repo_access.py)

**証拠と限界:** real temp git、FakePolicy。symlinkテストは呼出し前交換でTOCTOU競合は再現していない

**重なり:** `repo-access` · **指摘:** F11.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T055-C001](../../extensions/messaging/tests/test-repo-access.py#L92) | list shows only granted projects with version info |
| [T055-C002](../../extensions/messaging/tests/test-repo-access.py#L98) | tree serves tracked text only |
| [T055-C003](../../extensions/messaging/tests/test-repo-access.py#L107) | read numbers lines cites and pages |
| [T055-C004](../../extensions/messaging/tests/test-repo-access.py#L119) | paths that leave the root or are never served are denied |
| [T055-C005](../../extensions/messaging/tests/test-repo-access.py#L126) | Symlink already exists before read call; rejection tested, not an in-call TOCTOU swap. See F11. |
| [T055-C006](../../extensions/messaging/tests/test-repo-access.py#L131) | binary credential and long line handling |
| [T055-C007](../../extensions/messaging/tests/test-repo-access.py#L138) | snapshot must still match |
| [T055-C008](../../extensions/messaging/tests/test-repo-access.py#L147) | search literal regex context paging and credentials |
| [T055-C009](../../extensions/messaging/tests/test-repo-access.py#L167) | revocation applies to the next call even with a cursor or snapshot |
| [T055-C010](../../extensions/messaging/tests/test-repo-access.py#L174) | operation and path scope limits |
| [T055-C011](../../extensions/messaging/tests/test-repo-access.py#L181) | audit names the call but never the content |
| [T055-C012](../../extensions/messaging/tests/test-repo-access.py#L190) | rate limit returns retry after |

## T056 — test-repo-host-routing.py

[Test source](../../extensions/messaging/tests/test-repo-host-routing.py) · 93 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** repo callerをendpoint由来に固定・local/remote判定・曖昧拒否

**本番接点:** [host.py](../../extensions/messaging/unified/host.py)

**証拠と限界:** Hostメソッド+Stub。owner grant実効性はfederation/policyで別検査

**重なり:** `repo-access`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T056-C001](../../extensions/messaging/tests/test-repo-host-routing.py#L54) | the reader comes from the endpoint not from the request |
| [T056-C002](../../extensions/messaging/tests/test-repo-host-routing.py#L61) | local project is read here and remote project is forwarded |
| [T056-C003](../../extensions/messaging/tests/test-repo-host-routing.py#L70) | an alias owned by two hosts is refused not guessed |
| [T056-C004](../../extensions/messaging/tests/test-repo-host-routing.py#L75) | list merges local and peer results and reports unreachable hosts |
| [T056-C005](../../extensions/messaging/tests/test-repo-host-routing.py#L80) | without federation nothing leaves this host |
| [T056-C006](../../extensions/messaging/tests/test-repo-host-routing.py#L86) | a refusal keeps its fixed code |

## T057 — test-repo-write.py

[Test source](../../extensions/messaging/tests/test-repo-write.py) · 189 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** write/revertのhash・scope・owner dirty保護・同ID・原git不変

**本番接点:** [repo_access.py](../../extensions/messaging/unified/repo_access.py)

**証拠と限界:** real temp git/FS、FakePolicy。OS crash/fsync/物理disk fullなし

**重なり:** `repo-access`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T057-C001](../../extensions/messaging/tests/test-repo-write.py#L73) | modify and create write files without touching git |
| [T057-C002](../../extensions/messaging/tests/test-repo-write.py#L82) | no grant read only grant scope and revocation |
| [T057-C003](../../extensions/messaging/tests/test-repo-write.py#L94) | stale base existing path and owner work in progress are refused |
| [T057-C004](../../extensions/messaging/tests/test-repo-write.py#L101) | a batch with one bad file writes nothing and dry run writes nothing |
| [T057-C005](../../extensions/messaging/tests/test-repo-write.py#L108) | forbidden paths content and modes |
| [T057-C006](../../extensions/messaging/tests/test-repo-write.py#L117) | symlinks are not followed |
| [T057-C007](../../extensions/messaging/tests/test-repo-write.py#L125) | new directories are limited in depth |
| [T057-C008](../../extensions/messaging/tests/test-repo-write.py#L129) | replayed patch id does not write twice and a different body is refused |
| [T057-C009](../../extensions/messaging/tests/test-repo-write.py#L136) | the same writer can keep editing its own change but not the owners |
| [T057-C010](../../extensions/messaging/tests/test-repo-write.py#L142) | revert restores exactly and refuses when the file moved on |
| [T057-C011](../../extensions/messaging/tests/test-repo-write.py#L154) | a created file can be read back until it changes and read gives the base sha |
| [T057-C012](../../extensions/messaging/tests/test-repo-write.py#L171) | a file the service created can be modified until the owner changes it |
| [T057-C013](../../extensions/messaging/tests/test-repo-write.py#L180) | audit names the call but never the content |

## T058 — test-role-handoff.sh

[Test source](../../extensions/messaging/tests/test-role-handoff.sh) · 1014 lines · CI: `direct` · `keep`

**守るもの:** legacy task/handoff・承認carry・exact sender/targetとaudit

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg) / [tproj-task-cache.sh](../../extensions/messaging/tproj-task-cache.sh)

**証拠と限界:** 実CLI/DB/cache、fake tmux/router/websocket。native formal taskとは別経路

**重なり:** `legacy-task`.

Shellの検査位置 177 件はcase台帳の `T058` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T059 — test-runtime-compatibility.py

[Test source](../../extensions/messaging/tests/test-runtime-compatibility.py) · 123 lines · CI: `transitive:runtime-installer` · `keep`

**守るもの:** mixed-version時の既存installed bytes保全・capability認証

**本番接点:** [install-tproj-messaging-runtime](../../extensions/messaging/install-tproj-messaging-runtime) / [host.py](../../extensions/messaging/unified/host.py)

**証拠と限界:** real installerとlocal socket responder、fake task module。CI installerから間接実行

**重なり:** `install`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T059-C001](../../extensions/messaging/tests/test-runtime-compatibility.py#L23) | enrolled rejection preserves tools and diagnostics |
| [T059-C002](../../extensions/messaging/tests/test-runtime-compatibility.py#L66) | supported live messaging owner passes preflight |
| [T059-C003](../../extensions/messaging/tests/test-runtime-compatibility.py#L93) | new host does not claim capabilities of old task module |
| [T059-C004](../../extensions/messaging/tests/test-runtime-compatibility.py#L102) | route authentication and master selection |

## T060 — test-runtime-directory-registration.py

[Test source](../../extensions/messaging/tests/test-runtime-directory-registration.py) · 97 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 既存runtime setup/reload判断・directory差分とrevision

**本番接点:** [runtime.py](../../extensions/messaging/unified/runtime.py)

**証拠と限界:** activate/RPC/launchctl結果差替え。保存/判断のみでreload成功を証明しない

**重なり:** `install`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T060-C001](../../extensions/messaging/tests/test-runtime-directory-registration.py#L17) | native expected generation triggers existing reload decision only once |
| [T060-C002](../../extensions/messaging/tests/test-runtime-directory-registration.py#L36) | failed existing reload is not reported as reloaded |
| [T060-C003](../../extensions/messaging/tests/test-runtime-directory-registration.py#L44) | adds only missing requested projects once |
| [T060-C004](../../extensions/messaging/tests/test-runtime-directory-registration.py#L70) | conflict and offline leave directory untouched |

## T061 — test-runtime-installer.sh

[Test source](../../extensions/messaging/tests/test-runtime-installer.sh) · 117 lines · CI: `direct` · `keep`

**守るもの:** 配布byte一致・hook/config保持・dry-run・冪等

**本番接点:** [install-tproj-messaging-runtime](../../extensions/messaging/install-tproj-messaging-runtime)

**証拠と限界:** isolated HOMEの実installer、人工trust応答。実loaded版は別

**重なり:** `install`.

Shellの検査位置 21 件はcase台帳の `T061` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T062 — test-sendability-gate.sh

[Test source](../../extensions/messaging/tests/test-sendability-gate.sh) · 1284 lines · CI: `direct` · `keep`

**守るもの:** legacy sendability/selection/draft/relay/fanout/queue/bridge

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg)

**証拠と限界:** real CLI+fake tmux/websocket/curl。statusだけのcasesとsendログ検査を区別、native queue合格ではない

**重なり:** `legacy-route`.

Shellの検査位置 210 件はcase台帳の `T062` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T063 — test-target-resolution-hardening.sh

[Test source](../../extensions/messaging/tests/test-target-resolution-hardening.sh) · 242 lines · CI: `direct` · `keep`

**守るもの:** exact target/session・stale liveness・曖昧拒否

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg)

**証拠と限界:** real CLI+process harness、tmux/websocket fixture。unified discoveryと別入口

**重なり:** `legacy-route`.

Shellの検査位置 30 件はcase台帳の `T063` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T064 — test-task-binding-release.py

[Test source](../../extensions/messaging/tests/test-task-binding-release.py) · 430 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** binding解除の旧epoch/native・tombstone・marker cleanup回復

**本番接点:** [tasks.py](../../extensions/messaging/unified/tasks.py) / [task_host.py](../../extensions/messaging/unified/task_host.py) / [task_transport.py](../../extensions/messaging/unified/task_transport.py)

**証拠と限界:** real SQLite/authorityとStub Host。外部効果の取消保証にはしない

**重なり:** `formal-task`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T064-C001](../../extensions/messaging/tests/test-task-binding-release.py#L31) | master allows former assignment only read |
| [T064-C002](../../extensions/messaging/tests/test-task-binding-release.py#L40) | master rejects old open current owner pending and frozen |
| [T064-C003](../../extensions/messaging/tests/test-task-binding-release.py#L54) | master cancelled release preserves open operations as unresolved history |
| [T064-C004](../../extensions/messaging/tests/test-task-binding-release.py#L66) | master cancelled release accepts authenticated former incarnation |
| [T064-C005](../../extensions/messaging/tests/test-task-binding-release.py#L79) | master cancelled release rejects forged binding tuple native or epoch |
| [T064-C006](../../extensions/messaging/tests/test-task-binding-release.py#L104) | host resynchronizes only exact same native old row |
| [T064-C007](../../extensions/messaging/tests/test-task-binding-release.py#L138) | host rejects direct internal check and cross native without cleanup |
| [T064-C008](../../extensions/messaging/tests/test-task-binding-release.py#L167) | host rejects wrong task epoch and ambiguous old row |
| [T064-C009](../../extensions/messaging/tests/test-task-binding-release.py#L198) | cancelled release clears exact bound marker only after master check |
| [T064-C010](../../extensions/messaging/tests/test-task-binding-release.py#L242) | cancelled release keeps binding when master rejects open operation |
| [T064-C011](../../extensions/messaging/tests/test-task-binding-release.py#L264) | retired operation is fenced after new binding |
| [T064-C012](../../extensions/messaging/tests/test-task-binding-release.py#L283) | cancelled release accepts same native after incarnation restart |
| [T064-C013](../../extensions/messaging/tests/test-task-binding-release.py#L313) | transport rejects forged historical native or project |
| [T064-C014](../../extensions/messaging/tests/test-task-binding-release.py#L335) | detach receipt replays after marker cleanup failure without clearing new binding |
| [T064-C015](../../extensions/messaging/tests/test-task-binding-release.py#L377) | legacy binding cannot capture new tool or callback |
| [T064-C016](../../extensions/messaging/tests/test-task-binding-release.py#L397) | ack records ledger transition without overwriting legacy binding |

## T065 — test-task-project-path-db.sh

[Test source](../../extensions/messaging/tests/test-task-project-path-db.sh) · 33 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** v10→11で旧taskのproject scopeを発明しない

**本番接点:** [tproj-msg-db.sh](../../extensions/messaging/tproj-msg-db.sh)

**証拠と限界:** real SQLite/helper。既存path保持とerrors空を検査

**重なり:** `legacy-task`.

Shellの検査位置 6 件はcase台帳の `T065` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T066 — test-task-reconcile.py

[Test source](../../extensions/messaging/tests/test-task-reconcile.py) · 208 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** exact tool/native/timeの完了witness・error/unknown分離

**本番接点:** [task_host.py](../../extensions/messaging/unified/task_host.py)

**証拠と限界:** 人工JSONLとStub Host。実platform transcript供給/実効果は未証明

**重なり:** `formal-task`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T066-C001](../../extensions/messaging/tests/test-task-reconcile.py#L25) | exact file change witness only |
| [T066-C002](../../extensions/messaging/tests/test-task-reconcile.py#L35) | exact command execution outcome requires one strict terminal |
| [T066-C003](../../extensions/messaging/tests/test-task-reconcile.py#L66) | completion rejects mixed file change and command execution |
| [T066-C004](../../extensions/messaging/tests/test-task-reconcile.py#L80) | command observation unavailable fails closed |
| [T066-C005](../../extensions/messaging/tests/test-task-reconcile.py#L108) | exact cc tool witness and denials |
| [T066-C006](../../extensions/messaging/tests/test-task-reconcile.py#L132) | cc terminal error is reconciled as separate outcome |
| [T066-C007](../../extensions/messaging/tests/test-task-reconcile.py#L141) | cc target pair ignores unrelated historical cwds |
| [T066-C008](../../extensions/messaging/tests/test-task-reconcile.py#L152) | cc dispatch selects cc witness |
| [T066-C009](../../extensions/messaging/tests/test-task-reconcile.py#L170) | wrong thread and text mention are rejected |
| [T066-C010](../../extensions/messaging/tests/test-task-reconcile.py#L178) | empty or nonobject transcript fails closed |
| [T066-C011](../../extensions/messaging/tests/test-task-reconcile.py#L188) | dispatch closes only matching active bound operation |

## T067 — test-task-role.py

[Test source](../../extensions/messaging/tests/test-task-role.py) · 101 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** native context矛盾拒否・markerとauthority error分類

**本番接点:** [task_role.py](../../extensions/messaging/unified/task_role.py)

**証拠と限界:** RPC/metadata mockだがrequest引数を検査。formal guardの不呼出しテストとは別

**重なり:** `formal-task`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T067-C001](../../extensions/messaging/tests/test-task-role.py#L17) | payload native context is forwarded |
| [T067-C002](../../extensions/messaging/tests/test-task-role.py#L24) | session only context uses exactly one proven thread |
| [T067-C003](../../extensions/messaging/tests/test-task-role.py#L30) | session only context keeps session only without proof |
| [T067-C004](../../extensions/messaging/tests/test-task-role.py#L38) | conflicting environment context is rejected |
| [T067-C005](../../extensions/messaging/tests/test-task-role.py#L44) | payload context reaches task context for bound marker |
| [T067-C006](../../extensions/messaging/tests/test-task-role.py#L60) | conflicting payload roots are rejected |
| [T067-C007](../../extensions/messaging/tests/test-task-role.py#L64) | context conflict is restrictive and skips rpc |
| [T067-C008](../../extensions/messaging/tests/test-task-role.py#L72) | authority failures are fixed categories |
| [T067-C009](../../extensions/messaging/tests/test-task-role.py#L86) | unknown protocol error is not transport and phase is fixed |

## T068 — test-unified-cli-routing.sh

[Test source](../../extensions/messaging/tests/test-unified-cli-routing.sh) · 43 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** enrolled wrapperがlegacy mutationへfallbackしない

**本番接点:** [tproj-msg](../../extensions/messaging/tproj-msg)

**証拠と限界:** 実wrapper+fake unified executable、config破損/maintenance。unifiedの中身は別

**重なり:** `route`.

Shellの検査位置 9 件はcase台帳の `T068` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T069 — test-unified-cli.py

[Test source](../../extensions/messaging/tests/test-unified-cli.py) · 107 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 送信前spool保存・同IDretry・selector/ページング

**本番接点:** [cli.py](../../extensions/messaging/unified/cli.py)

**証拠と限界:** real CLI+fake UDS responder。本文保存とwire引数を直接検査

**重なり:** `route`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T069-C001](../../extensions/messaging/tests/test-unified-cli.py#L11) | pending explains acceptance and no ack without reroute |
| [T069-C002](../../extensions/messaging/tests/test-unified-cli.py#L27) | inbox forwards cursor and limit for next page |
| [T069-C003](../../extensions/messaging/tests/test-unified-cli.py#L46) | relative status resolves configured project |
| [T069-C004](../../extensions/messaging/tests/test-unified-cli.py#L63) | stdin persists submission before fake uds request and retry reuses id |
| [T069-C005](../../extensions/messaging/tests/test-unified-cli.py#L85) | retry corrects explicit selectors without changing saved payload |
| [T069-C006](../../extensions/messaging/tests/test-unified-cli.py#L102) | missing config is explicit |

## T070 — test-unified-enrollment.py

[Test source](../../extensions/messaging/tests/test-unified-enrollment.py) · 57 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** directory admission・prepare/commit・host別有向route

**本番接点:** [enrollment.py](../../extensions/messaging/unified/enrollment.py)

**証拠と限界:** real temporary config操作。複数host commitの実ネットワーク故障は未証明

**重なり:** `directory`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T070-C001](../../extensions/messaging/tests/test-unified-enrollment.py#L13) | admission rejects duplicate global alias |
| [T070-C002](../../extensions/messaging/tests/test-unified-enrollment.py#L19) | prepare commit is atomic and recoverable |
| [T070-C003](../../extensions/messaging/tests/test-unified-enrollment.py#L33) | topology keeps different directed routes |
| [T070-C004](../../extensions/messaging/tests/test-unified-enrollment.py#L42) | three host control uses each hosts own routes |

## T071 — test-unified-federation.py

[Test source](../../extensions/messaging/tests/test-unified-federation.py) · 311 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** owner受入結果・offline/unknown・取消/返信・byte上限

**本番接点:** [federation.py](../../extensions/messaging/unified/federation.py)

**証拠と限界:** 複数real SQLite Hubとdirect remote dispatch、SSH subprocess mock。物理ネットワークなし

**重なり:** `hub`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T071-C001](../../extensions/messaging/tests/test-unified-federation.py#L32) | concurrent writable legacy migration is serialized |
| [T071-C002](../../extensions/messaging/tests/test-unified-federation.py#L55) | capability probe keeps peer without transport evidence |
| [T071-C003](../../extensions/messaging/tests/test-unified-federation.py#L67) | accepted retry preserves result after recipient revocation |
| [T071-C004](../../extensions/messaging/tests/test-unified-federation.py#L95) | delivered retries preserve authority state atomically |
| [T071-C005](../../extensions/messaging/tests/test-unified-federation.py#L114) | invalid acceptance result preserves pending outcome |
| [T071-C006](../../extensions/messaging/tests/test-unified-federation.py#L128) | rotated sender diagnosis preserves remote presented evidence |
| [T071-C007](../../extensions/messaging/tests/test-unified-federation.py#L160) | exact remote reply lands on same native rotated sender |
| [T071-C008](../../extensions/messaging/tests/test-unified-federation.py#L168) | proven stale session tombstones outbox without retry |
| [T071-C009](../../extensions/messaging/tests/test-unified-federation.py#L180) | rotated recipient remote reply owner attestation |
| [T071-C010](../../extensions/messaging/tests/test-unified-federation.py#L187) | local without any remote and same path isolated |
| [T071-C011](../../extensions/messaging/tests/test-unified-federation.py#L193) | remote reply receipt and no foreign directory |
| [T071-C012](../../extensions/messaging/tests/test-unified-federation.py#L204) | large multibyte send and reply are retained exactly |
| [T071-C013](../../extensions/messaging/tests/test-unified-federation.py#L216) | bounded wire recovers saved multilingual payload |
| [T071-C014](../../extensions/messaging/tests/test-unified-federation.py#L273) | offline no accept and stale reply never retargets |
| [T071-C015](../../extensions/messaging/tests/test-unified-federation.py#L280) | resolver preserves owner rejection without accepting or retargeting |
| [T071-C016](../../extensions/messaging/tests/test-unified-federation.py#L294) | unknown peer cannot inject |
| [T071-C017](../../extensions/messaging/tests/test-unified-federation.py#L297) | remote cancel reconnect keeps id and prevents delivery |

## T072 — test-unified-host-identity.py

[Test source](../../extensions/messaging/tests/test-unified-host-identity.py) · 169 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 旧owner保持・pane欠落でも他endpoint継続・heartbeat

**本番接点:** [host.py](../../extensions/messaging/unified/host.py) / [identity.py](../../extensions/messaging/unified/identity.py)

**証拠と限界:** 人工process/registryと実Host。actual TUI discoveryとは別

**重なり:** `identity`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T072-C001](../../extensions/messaging/tests/test-unified-host-identity.py#L17) | retired candidate does not block other live discovery |
| [T072-C002](../../extensions/messaging/tests/test-unified-host-identity.py#L33) | historical receipt scan keeps heartbeats fresh and stops retired endpoint |
| [T072-C003](../../extensions/messaging/tests/test-unified-host-identity.py#L71) | missing pane preserves message and does not crash other endpoint |
| [T072-C004](../../extensions/messaging/tests/test-unified-host-identity.py#L102) | refresh keeps fallback id and rejects restart |

## T073 — test-unified-host-services.py

[Test source](../../extensions/messaging/tests/test-unified-host-services.py) · 488 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** endpoint故障分離・journal reopen・runtime pin・service scope

**本番接点:** [host.py](../../extensions/messaging/unified/host.py)

**証拠と限界:** real journalと故障注入、hub/launchd/process mock。loaded service未証明

**重なり:** `identity`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T073-C001](../../extensions/messaging/tests/test-unified-host-services.py#L21) | endpoint failure cannot starve other recipients |
| [T073-C002](../../extensions/messaging/tests/test-unified-host-services.py#L46) | endpoint failure rolls back partial work not committed reservations |
| [T073-C003](../../extensions/messaging/tests/test-unified-host-services.py#L78) | failed journal reopen never recreates ledger or runs later work |
| [T073-C004](../../extensions/messaging/tests/test-unified-host-services.py#L124) | delivery scan advances and wraps pending without terminal replay |
| [T073-C005](../../extensions/messaging/tests/test-unified-host-services.py#L148) | native scheduler maintains off path and never falls back |
| [T073-C006](../../extensions/messaging/tests/test-unified-host-services.py#L180) | native route survives flag off and host restart before prepare |
| [T073-C007](../../extensions/messaging/tests/test-unified-host-services.py#L207) | current host policy controls legacy and new service calls |
| [T073-C008](../../extensions/messaging/tests/test-unified-host-services.py#L234) | read only diagnose uses persisted identity without registration |
| [T073-C009](../../extensions/messaging/tests/test-unified-host-services.py#L271) | identity diagnostic forwards only bounded selectors |
| [T073-C010](../../extensions/messaging/tests/test-unified-host-services.py#L281) | private snapshot and idempotent scope migration |
| [T073-C011](../../extensions/messaging/tests/test-unified-host-services.py#L327) | native attestation is authenticated and old hub fail open only |
| [T073-C012](../../extensions/messaging/tests/test-unified-host-services.py#L347) | equal native session thread preserves existing attestation |
| [T073-C013](../../extensions/messaging/tests/test-unified-host-services.py#L380) | service registry binds identity platform and incarnation |
| [T073-C014](../../extensions/messaging/tests/test-unified-host-services.py#L393) | service id prevents cross service token or address confusion |
| [T073-C015](../../extensions/messaging/tests/test-unified-host-services.py#L405) | kai enrollment retains mailbox across verified process restart |
| [T073-C016](../../extensions/messaging/tests/test-unified-host-services.py#L429) | kai cannot be declared as openclaw platform |
| [T073-C017](../../extensions/messaging/tests/test-unified-host-services.py#L438) | legacy service config remains openclaw |
| [T073-C018](../../extensions/messaging/tests/test-unified-host-services.py#L455) | duplicate service participant or address rejected before retirement |
| [T073-C019](../../extensions/messaging/tests/test-unified-host-services.py#L466) | scoped inbox message and ack use authenticated endpoint |

## T074 — test-unified-hub.py

[Test source](../../extensions/messaging/tests/test-unified-hub.py) · 952 lines · CI: `not-in-test-workflow` · `strengthen`

**守るもの:** MSG状態/receipt/取消/TTL/identity/handoff・公平claim・read-only投影

**本番接点:** [hub.py](../../extensions/messaging/unified/hub.py) / [protocol.py](../../extensions/messaging/unified/protocol.py)

**証拠と限界:** real SQLite/二接続/部分real socket、人工endpoint。reverse replyの1caseはqueuedのみ

**重なり:** `hub` · **指摘:** F07.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T074-C001](../../extensions/messaging/tests/test-unified-hub.py#L9) | resource error is errno classified and sanitized |
| [T074-C002](../../extensions/messaging/tests/test-unified-hub.py#L16) | internal error reports only type and locations |
| [T074-C003](../../extensions/messaging/tests/test-unified-hub.py#L58) | sqlite full never acknowledges uncommitted admission |
| [T074-C004](../../extensions/messaging/tests/test-unified-hub.py#L108) | active endpoint list excludes large retired history without deletion |
| [T074-C005](../../extensions/messaging/tests/test-unified-hub.py#L127) | read only hub does not initialize schema and reports capabilities |
| [T074-C006](../../extensions/messaging/tests/test-unified-hub.py#L141) | diagnostic identity is host scoped and excludes message bodies |
| [T074-C007](../../extensions/messaging/tests/test-unified-hub.py#L150) | active identity stays bounded without deleting history |
| [T074-C008](../../extensions/messaging/tests/test-unified-hub.py#L175) | same native rotation preserves exact query and reply |
| [T074-C009](../../extensions/messaging/tests/test-unified-hub.py#L192) | reply evidence survives both native rotations |
| [T074-C010](../../extensions/messaging/tests/test-unified-hub.py#L219) | native rotation unknown different ambiguous and stale reject |
| [T074-C011](../../extensions/messaging/tests/test-unified-hub.py#L244) | receipt transaction rechecks cancel and retired owner |
| [T074-C012](../../extensions/messaging/tests/test-unified-hub.py#L287) | native handoff core preserves originals and excludes irreversible states |
| [T074-C013](../../extensions/messaging/tests/test-unified-hub.py#L340) | native handoff core rejects unproved or ambiguous continuity |
| [T074-C014](../../extensions/messaging/tests/test-unified-hub.py#L357) | native handoff core does not transfer a different actor generation |
| [T074-C015](../../extensions/messaging/tests/test-unified-hub.py#L370) | transferred native actor claim pending reservation and receipt |
| [T074-C016](../../extensions/messaging/tests/test-unified-hub.py#L410) | transferred presented receipt requires native reservation |
| [T074-C017](../../extensions/messaging/tests/test-unified-hub.py#L425) | transferred actor reply and old sequence do not lose wake |
| [T074-C018](../../extensions/messaging/tests/test-unified-hub.py#L444) | native handoff core rolls back owner and retirement together |
| [T074-C019](../../extensions/messaging/tests/test-unified-hub.py#L459) | claim sequence passes old pending and wraps without replay |
| [T074-C020](../../extensions/messaging/tests/test-unified-hub.py#L479) | claim probe filtered page is not scan end |
| [T074-C021](../../extensions/messaging/tests/test-unified-hub.py#L492) | native pending insert between empty and drain and restart |
| [T074-C022](../../extensions/messaging/tests/test-unified-hub.py#L532) | native capabilities are authenticated and read only |
| [T074-C023](../../extensions/messaging/tests/test-unified-hub.py#L541) | diagnosis is metadata only and operator permission is explicit |
| [T074-C024](../../extensions/messaging/tests/test-unified-hub.py#L564) | waiting summary uses observed reason and own age without writes |
| [T074-C025](../../extensions/messaging/tests/test-unified-hub.py#L596) | native wait observation requires current binding |
| [T074-C026](../../extensions/messaging/tests/test-unified-hub.py#L615) | delivery summary preserves expired unknown and late evidence |
| [T074-C027](../../extensions/messaging/tests/test-unified-hub.py#L672) | expired query rejection is read only for nonparty |
| [T074-C028](../../extensions/messaging/tests/test-unified-hub.py#L692) | diagnosis keeps linked reply separate from receipt |
| [T074-C029](../../extensions/messaging/tests/test-unified-hub.py#L721) | durable idempotency and relative route |
| [T074-C030](../../extensions/messaging/tests/test-unified-hub.py#L727) | query by id carries the resolved sender address |
| [T074-C031](../../extensions/messaging/tests/test-unified-hub.py#L734) | inbox notice is bounded metadata only and does not present |
| [T074-C032](../../extensions/messaging/tests/test-unified-hub.py#L745) | inbox notice excludes reply to message already received |
| [T074-C033](../../extensions/messaging/tests/test-unified-hub.py#L754) | inbox notice excludes candidate already replied to by recipient |
| [T074-C034](../../extensions/messaging/tests/test-unified-hub.py#L764) | inbox notice cursor reaches fourth row on second safe point |
| [T074-C035](../../extensions/messaging/tests/test-unified-hub.py#L774) | inbox notice includes dispatching before cursor advances |
| [T074-C036](../../extensions/messaging/tests/test-unified-hub.py#L790) | large first message advances cursor without starving next |
| [T074-C037](../../extensions/messaging/tests/test-unified-hub.py#L807) | message exceeding response frame fails explicitly |
| [T074-C038](../../extensions/messaging/tests/test-unified-hub.py#L818) | outbox lists only my unfinished sends without bodies |
| [T074-C039](../../extensions/messaging/tests/test-unified-hub.py#L837) | committed reply suppresses claim and pending presentation |
| [T074-C040](../../extensions/messaging/tests/test-unified-hub.py#L851) | Reply submit returns queued only; endpoint pin is NOT asserted. See F07. |
| [T074-C041](../../extensions/messaging/tests/test-unified-hub.py#L855) | reply to restarted openclaw service uses sole current endpoint |
| [T074-C042](../../extensions/messaging/tests/test-unified-hub.py#L869) | auth maintenance alias revision and ttl |
| [T074-C043](../../extensions/messaging/tests/test-unified-hub.py#L875) | ambiguous endpoint rejected |
| [T074-C044](../../extensions/messaging/tests/test-unified-hub.py#L879) | native reservation binds original and generation and remains one shot |
| [T074-C045](../../extensions/messaging/tests/test-unified-hub.py#L915) | cancel rechecks sender retirement inside transaction |
| [T074-C046](../../extensions/messaging/tests/test-unified-hub.py#L933) | sender cancel fences presentation and is not task cancellation |
| [T074-C047](../../extensions/messaging/tests/test-unified-hub.py#L947) | missing heartbeat rejects send without retirement |

## T075 — test-unified-identity.py

[Test source](../../extensions/messaging/tests/test-unified-identity.py) · 474 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** PID/ancestry/native catalog/rolloutの所有binding

**本番接点:** [identity.py](../../extensions/messaging/unified/identity.py)

**証拠と限界:** real一時DB/JSONL、process/tmux注入。本番process discoveryは別

**重なり:** `identity`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T075-C001](../../extensions/messaging/tests/test-unified-identity.py#L36) | discovery and stable incarnation |
| [T075-C002](../../extensions/messaging/tests/test-unified-identity.py#L47) | cross project native registry does not poison fallback |
| [T075-C003](../../extensions/messaging/tests/test-unified-identity.py#L69) | stale and pid reuse and proxy are rejected |
| [T075-C004](../../extensions/messaging/tests/test-unified-identity.py#L84) | binding requires ancestry and rejects ambiguity |
| [T075-C005](../../extensions/messaging/tests/test-unified-identity.py#L98) | shared app server cannot bind itself children or launcher |
| [T075-C006](../../extensions/messaging/tests/test-unified-identity.py#L122) | standalone codex cli child still binds |
| [T075-C007](../../extensions/messaging/tests/test-unified-identity.py#L137) | shared app server binds native conversation and rejects cross project |
| [T075-C008](../../extensions/messaging/tests/test-unified-identity.py#L157) | shared daemon adopts unrelated tool process by native id |
| [T075-C009](../../extensions/messaging/tests/test-unified-identity.py#L169) | native context accepts one id but rejects empty |
| [T075-C010](../../extensions/messaging/tests/test-unified-identity.py#L174) | native catalog adopts unique tmux endpoint without replacing id |
| [T075-C011](../../extensions/messaging/tests/test-unified-identity.py#L184) | native adoption scopes codex and preserves conflicting binding |
| [T075-C012](../../extensions/messaging/tests/test-unified-identity.py#L200) | composed adoption binds shared daemon tmux endpoint |
| [T075-C013](../../extensions/messaging/tests/test-unified-identity.py#L217) | native catalog keeps long lived cli thread |
| [T075-C014](../../extensions/messaging/tests/test-unified-identity.py#L224) | native catalog closes readonly connection on success and error |
| [T075-C015](../../extensions/messaging/tests/test-unified-identity.py#L265) | native rollout adopts and binds when catalog is missing |
| [T075-C016](../../extensions/messaging/tests/test-unified-identity.py#L288) | native vscode catalog transition requires matching rollout and binds |
| [T075-C017](../../extensions/messaging/tests/test-unified-identity.py#L315) | native vscode catalog transition rejects conflicts |
| [T075-C018](../../extensions/messaging/tests/test-unified-identity.py#L351) | native rollout rejects wrong source and conflicting catalog |
| [T075-C019](../../extensions/messaging/tests/test-unified-identity.py#L367) | native catalog conflict blocks rollout fallback |
| [T075-C020](../../extensions/messaging/tests/test-unified-identity.py#L382) | tmux direct agent root survives expired registry |
| [T075-C021](../../extensions/messaging/tests/test-unified-identity.py#L396) | tmux shell command mentioning codex is not an agent |
| [T075-C022](../../extensions/messaging/tests/test-unified-identity.py#L409) | tmux fallback requires live agent descendant and deduplicates registry |
| [T075-C023](../../extensions/messaging/tests/test-unified-identity.py#L433) | tmux fallback preserves distinct live panes for ambiguity rejection |
| [T075-C024](../../extensions/messaging/tests/test-unified-identity.py#L451) | fallback to registry preserves identity only for verified live family |

## T076 — test-unified-integration.py

[Test source](../../extensions/messaging/tests/test-unified-integration.py) · 115 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 旧terminal receiptとHub replyの接続・draft/menu parser

**本番接点:** [host.py](../../extensions/messaging/unified/host.py) / [hub.py](../../extensions/messaging/unified/hub.py) / [receipt.py](../../extensions/messaging/unified/receipt.py) / [terminal-guard.sh](../../extensions/messaging/unified/terminal-guard.sh)

**証拠と限界:** 実component、人工capture/Hub応答。integrationという名でもprovider E2Eではない

**重なり:** `native`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T076-C001](../../extensions/messaging/tests/test-unified-integration.py#L21) | reply after alias rename probe claim and retirement |
| [T076-C002](../../extensions/messaging/tests/test-unified-integration.py#L43) | host submission and exact receipt |
| [T076-C003](../../extensions/messaging/tests/test-unified-integration.py#L61) | native paste receipt keeps sender marker |
| [T076-C004](../../extensions/messaging/tests/test-unified-integration.py#L73) | relative status uses authenticated project |
| [T076-C005](../../extensions/messaging/tests/test-unified-integration.py#L82) | guard never accepts fresh idle draft or approval |
| [T076-C006](../../extensions/messaging/tests/test-unified-integration.py#L92) | live composer above long footer |

## T077 — test-unified-pending.py

[Test source](../../extensions/messaging/tests/test-unified-pending.py) · 68 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** pending表示をowner側状態で再照合・remote上限

**本番接点:** [host.py](../../extensions/messaging/unified/host.py)

**証拠と限界:** Stub Host。summary文字列だけより強いrouting/count検査だが実remoteなし

**重なり:** `hub`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T077-C001](../../extensions/messaging/tests/test-unified-pending.py#L37) | owning side state replaces the handoff copy |
| [T077-C002](../../extensions/messaging/tests/test-unified-pending.py#L58) | a cap bounds how many remote checks one call makes |

## T078 — test-unified-policy.py

[Test source](../../extensions/messaging/tests/test-unified-policy.py) · 41 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** relay/broadcast/重複の受付policy

**本番接点:** [policy.py](../../extensions/messaging/unified/policy.py)

**証拠と限界:** real in-memory DB/check_policy。blocked helperでassertRaises、直接assertゼロでも無価値でない

**重なり:** `hub`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T078-C001](../../extensions/messaging/tests/test-unified-policy.py#L22) | forbidden markers |
| [T078-C002](../../extensions/messaging/tests/test-unified-policy.py#L28) | explicit recipients allow identical text |
| [T078-C003](../../extensions/messaging/tests/test-unified-policy.py#L34) | recovery duplicate and reply |

## T079 — test-unified-task-cli.py

[Test source](../../extensions/messaging/tests/test-unified-task-cli.py) · 102 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** formal task CLIのscope/approval/idempotencyと旧入口遮断

**本番接点:** [task_cli.py](../../extensions/messaging/unified/task_cli.py) / [tproj-task](../../extensions/messaging/tproj-task)

**証拠と限界:** mock _call/requestと一部実wrapper subprocess。authorityの実審査は別

**重なり:** `formal-task`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T079-C001](../../extensions/messaging/tests/test-unified-task-cli.py#L12) | submit uses text contract and native request |
| [T079-C002](../../extensions/messaging/tests/test-unified-task-cli.py#L27) | same packet retry reuses key and target conflict rejects |
| [T079-C003](../../extensions/messaging/tests/test-unified-task-cli.py#L40) | approval reads scope file and never accepts selector |
| [T079-C004](../../extensions/messaging/tests/test-unified-task-cli.py#L53) | enrolled wrapper does not fall back on broken config |
| [T079-C005](../../extensions/messaging/tests/test-unified-task-cli.py#L65) | handoff maps to authenticated task operation |
| [T079-C006](../../extensions/messaging/tests/test-unified-task-cli.py#L71) | cancelled release maps to authenticated task operation |
| [T079-C007](../../extensions/messaging/tests/test-unified-task-cli.py#L77) | enrolled legacy fallback is status only |

## T080 — test-unified-terminal-freshness.py

[Test source](../../extensions/messaging/tests/test-unified-terminal-freshness.py) · 68 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 古いtyping hint無効化と実draft/approval保護

**本番接点:** [terminal-guard.sh](../../extensions/messaging/unified/terminal-guard.sh)

**証拠と限界:** 実shell parser+fake capture/clock値。実TUI描画の変化には別証拠必要

**重なり:** `native`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T080-C001](../../extensions/messaging/tests/test-unified-terminal-freshness.py#L41) | fresh typing still denies |
| [T080-C002](../../extensions/messaging/tests/test-unified-terminal-freshness.py#L46) | stale typing empty prompt falls through to safe |
| [T080-C003](../../extensions/messaging/tests/test-unified-terminal-freshness.py#L50) | stale typing real draft still denies |
| [T080-C004](../../extensions/messaging/tests/test-unified-terminal-freshness.py#L55) | stale running approval still denies |
| [T080-C005](../../extensions/messaging/tests/test-unified-terminal-freshness.py#L61) | invalid or future timestamp does not block clean prompt |

## T081 — test-model-role-router-contract.sh

[Test source](../../extensions/model-role-router/test-model-role-router-contract.sh) · 93 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** canonical symlinkと既存pane metadata非上書き

**本番接点:** [tproj-model-role.sh](../../bin/lib/tproj-model-role.sh) / [model-role-router](../../extensions/model-role-router/model-role-router)

**証拠と限界:** real helper/canonical help、fake tmux/router。general checkout必須

**重なり:** `install`.

Shellの検査位置 15 件はcase台帳の `T081` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T082 — test-project-bootstrap-contract.sh

[Test source](../../extensions/persona/test-project-bootstrap-contract.sh) · 127 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** runtime起動でshared files不変・canonical/installed drift検出

**本番接点:** [project-bootstrap](../../extensions/persona/project-bootstrap) / [voice-identity-sync](../../extensions/persona/voice-identity-sync) / [install.sh](../../install.sh)

**証拠と限界:** real canonical tools/temp HOME。sibling checkout必須。重要なので単なるsymlink重複として削らない

**重なり:** `install`.

Shellの検査位置 34 件はcase台帳の `T082` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T083 — test-tproj-pane-bg-face-stock.sh

[Test source](../../extensions/persona/test-tproj-pane-bg-face-stock.sh) · 44 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** face stockのpin維持・override・選択

**本番接点:** [tproj-pane-bg](../../extensions/persona/tproj-pane-bg)

**証拠と限界:** source helper、PNG代用bytes。画像の品質/identityを検証しない

**重なり:** `image`.

Shellの検査位置 3 件はcase台帳の `T083` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T084 — test-tproj-pane-bg-provider-contract.sh

[Test source](../../extensions/persona/test-tproj-pane-bg-provider-contract.sh) · 202 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** provider error分類/秘匿・bounded retry・fallback停止

**本番接点:** [tproj-pane-bg](../../extensions/persona/tproj-pane-bg)

**証拠と限界:** fake SDK/tmux/sleep、tiny PNG。実provider availability/画像品質は未証明

**重なり:** `image`.

Shellの検査位置 21 件はcase台帳の `T084` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T085 — test-tproj-pane-bg-sync-coalescing.sh

[Test source](../../extensions/persona/test-tproj-pane-bg-sync-coalescing.sh) · 46 lines · CI: `not-in-test-workflow` · `clarify`

**守るもの:** full requestをfastで上書きしない・promotion準備

**本番接点:** [tproj-pane-bg](../../extensions/persona/tproj-pane-bg)

**証拠と限界:** precreated lock下に逐次2呼出し、helper直接。真の並行競合は未再現

**重なり:** `image` · **指摘:** F08.

Shellの検査位置 4 件はcase台帳の `T085` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T086 — smoke-bin.sh

[Test source](../../tests/smoke-bin.sh) · 182 lines · CI: `direct` · `strengthen`

**守るもの:** bin構文・代表help/status・column上限拒否

**本番接点:** [tproj](../../bin/tproj) / [tproj-role](../../bin/tproj-role) / [tproj-pane-autozoom](../../bin/tproj-pane-autozoom)

**証拠と限界:** source syntax+小CLI。timeout不在時は無制限、zsh timeout→bash fallbackは同等保証でない

**重なり:** `core` · **指摘:** F14.

Shellの検査位置 44 件はcase台帳の `T086` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T087 — test-install-check-persona.sh

[Test source](../../tests/test-install-check-persona.sh) · 66 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** installerが配布personaの欠落/差分を報告する

**本番接点:** [install.sh](../../install.sh)

**証拠と限界:** real --check、isolated HOME。PERSONA_BINS自体から期待集合を取得、manifest完全性は別

**重なり:** `install`.

Shellの検査位置 17 件はcase台帳の `T087` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T088 — test-install-standalone.sh

[Test source](../../tests/test-install-standalone.sh) · 40 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** sibling無しpublic checkoutのdry-run fail-open

**本番接点:** [install.sh](../../install.sh)

**証拠と限界:** tracked tree copy+real installer --dry-run。実install/起動までを証明しない

**重なり:** `install`.

Shellの検査位置 4 件はcase台帳の `T088` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T089 — test-kai-msg-reload-manifest.sh

[Test source](../../tests/test-kai-msg-reload-manifest.sh) · 14 lines · CI: `not-in-test-workflow` · `reclassify`

**守るもの:** 配布manifestに必要moduleが列挙される

**本番接点:** [tproj-msg-reload](../../bin/tproj-msg-reload)

**証拠と限界:** 固定順序source grep+存在確認のみ。archive/remote更新/loaded証明なし

**重なり:** `install` · **指摘:** F06.

Shellの検査位置 2 件はcase台帳の `T089` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T090 — test-local-codex-update.py

[Test source](../../tests/test-local-codex-update.py) · 369 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** agent updateとlaunchの排他・failure fail-open

**本番接点:** [tproj](../../bin/tproj) / [tproj-cli-update](../../bin/tproj-cli-update) / [tproj-remote-host](../../bin/tproj-remote-host) / [TprojApp.swift](../../apps/tproj/Sources/TprojApp/TprojApp.swift)

**証拠と限界:** real lock/process、一部関数/Swift shell文字列抽出・npm fake。実npm更新ではない

**重なり:** `process`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T090-C001](../../tests/test-local-codex-update.py#L24) | gui generated update uses helper and fails open |
| [T090-C002](../../tests/test-local-codex-update.py#L81) | default update failure and explicit skip |
| [T090-C003](../../tests/test-local-codex-update.py#L112) | sign codex compatibility shim never invokes codesign or mutates fixture |
| [T090-C004](../../tests/test-local-codex-update.py#L133) | codex update skips when active or unverifiable |
| [T090-C005](../../tests/test-local-codex-update.py#L156) | remote generated update failure still launches |
| [T090-C006](../../tests/test-local-codex-update.py#L184) | npm keeps lock after helper termination |
| [T090-C007](../../tests/test-local-codex-update.py#L236) | managed launch blocks codex update |
| [T090-C008](../../tests/test-local-codex-update.py#L278) | managed launch waits for active codex update |
| [T090-C009](../../tests/test-local-codex-update.py#L325) | concurrent packages hold lock through sign and failure |

## T091 — test-msg-reload-help.sh

[Test source](../../tests/test-msg-reload-help.sh) · 14 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** helpはdeploy依存無しで動作・unknown option拒否

**本番接点:** [tproj-msg-reload](../../bin/tproj-msg-reload)

**証拠と限界:** PATH無しで実CLIを起動しexit/output検査。manifest grepと独自価値

**重なり:** `install`.

Shellの検査位置 2 件はcase台帳の `T091` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T092 — test-msg-runtime.py

[Test source](../../tests/test-msg-runtime.py) · 63 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** setupのlocal性・dry-run・冪等・旧enrollment移行拒否

**本番接点:** [runtime.py](../../extensions/messaging/unified/runtime.py)

**証拠と限界:** temp HOME/DB、activate無し。live runtimeのloaded世代は未証明

**重なり:** `install`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T092-C001](../../tests/test-msg-runtime.py#L15) | dry run has no side effects |
| [T092-C002](../../tests/test-msg-runtime.py#L22) | setup is local and idempotent |
| [T092-C003](../../tests/test-msg-runtime.py#L42) | existing remote enrollment requires migrate |

## T093 — test-pane-autozoom.sh

[Test source](../../tests/test-pane-autozoom.sh) · 87 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** window高に比例したpane resizeと最小floor

**本番接点:** [tproj-pane-autozoom](../../bin/tproj-pane-autozoom)

**証拠と限界:** 実CLI、fake tmux argv検査。実画面のgeometryは未証明

**重なり:** `gui-logic`.

Shellの検査位置 10 件はcase台帳の `T093` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T094 — test-pane-bg-remote-main.sh

[Test source](../../tests/test-pane-bg-remote-main.sh) · 37 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** remote/local同pathのmain roleを混同しない

**本番接点:** [tproj-pane-bg](../../extensions/persona/tproj-pane-bg)

**証拠と限界:** 実関数抽出+fake router/client。入口や画像表示は未検査

**重なり:** `image`.

Shellの検査位置 5 件はcase台帳の `T094` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T095 — test-pane-bg-style-layers.sh

[Test source](../../tests/test-pane-bg-style-layers.sh) · 87 lines · CI: `not-in-test-workflow` · `strengthen`

**守るもの:** baseline/house/project/provider優先順

**本番接点:** [tproj-pane-bg](../../extensions/persona/tproj-pane-bg)

**証拠と限界:** 実style-layers JSON。末尾detail検査だけliteral grepでAPI request未検査

**重なり:** `image` · **指摘:** F15.

Shellの検査位置 28 件はcase台帳の `T095` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T096 — test-peer-ledger-remote-sync.sh

[Test source](../../tests/test-peer-ledger-remote-sync.sh) · 44 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** remote操作別ledger refreshの有無/順序

**本番接点:** [tproj-remote-client](../../bin/tproj-remote-client)

**証拠と限界:** real client+fake ledger/SSHログ。引数契約であり接続試験ではない

**重なり:** `remote`.

Shellの検査位置 10 件はcase台帳の `T096` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T097 — test-peer-ledger.sh

[Test source](../../tests/test-peer-ledger.sh) · 83 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** project projection/ID・revision・duplicate拒否・import/export

**本番接点:** [tproj-peer-ledger](../../bin/tproj-peer-ledger)

**証拠と限界:** real CLI/JSON/YAML、live tmux部分mock。master remote同期は別

**重なり:** `directory`.

Shellの検査位置 8 件はcase台帳の `T097` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T098 — test-remote-cache.sh

[Test source](../../tests/test-remote-cache.sh) · 42 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** bounded keep-warm tick・CCのみpoke・無効化

**本番接点:** [tproj-remote-cache](../../bin/tproj-remote-cache)

**証拠と限界:** real CLI+fake remote-host/cache/poke。実recipient未検査

**重なり:** `cache`.

Shellの検査位置 5 件はcase台帳の `T098` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T099 — test-remote-client-mosh.sh

[Test source](../../tests/test-remote-client-mosh.sh) · 38 lines · CI: `not-in-test-workflow` · `strengthen`

**守るもの:** SSH既定/mosh opt-inとfailure fallback

**本番接点:** [tproj-remote-client](../../bin/tproj-remote-client)

**証拠と限界:** fake SSH/mosh。run helperのexit握り潰しで成功caseの終了値未確認

**重なり:** `remote` · **指摘:** F16.

Shellの検査位置 8 件はcase台帳の `T099` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T100 — test-remote-client-tty.sh

[Test source](../../tests/test-remote-client-tty.sh) · 197 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** TTY復元・offline入力非replay・再接続・signal cleanup

**本番接点:** [tproj-remote-client](../../bin/tproj-remote-client)

**証拠と限界:** real PTY/childとfake SSH、network/wakeはsource置換。実remoteネットワークなし

**重なり:** `remote`.

Shellの検査位置 33 件はcase台帳の `T100` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T101 — test-remote-host.sh

[Test source](../../tests/test-remote-host.sh) · 125 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** runtime register/ensure/identity/rename/stop/migrate

**本番接点:** [tproj-remote-host](../../bin/tproj-remote-host)

**証拠と限界:** real isolated tmux、fake agents/npm/sign。PID保持検査は価値あり、実モデルは対象外

**重なり:** `remote`.

Shellの検査位置 36 件はcase台帳の `T101` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T102 — test-remote-reattach.sh

[Test source](../../tests/test-remote-reattach.sh) · 32 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** 既存role sessionだけreattach・起動/config生成なし

**本番接点:** [tproj-remote-host](../../bin/tproj-remote-host)

**証拠と限界:** fake tmuxのallowlist/argv検査。ensureとは別の無副作用入口

**重なり:** `remote`.

Shellの検査位置 5 件はcase台帳の `T102` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T103 — test-remote-setup-topology.sh

[Test source](../../tests/test-remote-setup-topology.sh) · 56 lines · CI: `not-in-test-workflow` · `clarify`

**守るもの:** remote配布集合とdrift分類

**本番接点:** [tproj-remote-setup](../../bin/tproj-remote-setup)

**証拠と限界:** fake SSH/tar。matchはwrapperだけ一致しskills/allowは空。exit無視は局所診断で、全体no-drift成功の証拠ではない

**重なり:** `remote` · **指摘:** F17.

Shellの検査位置 22 件はcase台帳の `T103` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T104 — test-stop-dispatch.py

[Test source](../../tests/test-stop-dispatch.py) · 33 lines · CI: `direct` · `keep`

**守るもの:** stop/killが共有shutdown dispatchへ進む

**本番接点:** [tproj](../../bin/tproj)

**証拠と限界:** 実CLI+fake tmux、exit/stderr/argv。smoke構文試験とは重複しない

**重なり:** `core`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T104-C001](../../tests/test-stop-dispatch.py#L13) | shutdown reads sessions before reporting no session |

## T105 — test-topology-cli.sh

[Test source](../../tests/test-topology-cli.sh) · 24 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** host ID永続・topology modeとhost登録

**本番接点:** [tproj-topology](../../bin/tproj-topology)

**証拠と限界:** real CLI/temp HOME、enrollment明示skip。実接続成立は別

**重なり:** `directory`.

Shellの検査位置 1 件はcase台帳の `T105` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T106 — test-tproj-gui-launch-reuse.sh

[Test source](../../tests/test-tproj-gui-launch-reuse.sh) · 58 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** GUI binary path/symlink/--serverの判定

**本番接点:** [tproj](../../bin/tproj)

**証拠と限界:** 実関数をsourceから抽出。actual app再利用/多重起動解消までは証明しない

**重なり:** `gui-logic`.

Shellの検査位置 5 件はcase台帳の `T106` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

## T107 — test-unified-task-integration.py

[Test source](../../tests/test-unified-task-integration.py) · 188 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** approval→master route→formal lifecycleの接続・通常tool非占有

**本番接点:** [task_approval.py](../../extensions/messaging/unified/task_approval.py) / [task_host.py](../../extensions/messaging/unified/task_host.py) / [task_transport.py](../../extensions/messaging/unified/task_transport.py) / [tasks.py](../../extensions/messaging/unified/tasks.py)

**証拠と限界:** real authority/Host methods、native record/remote stub。builtin Goal権限の証明ではない

**重なり:** `formal-task`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T107-C001](../../tests/test-unified-task-integration.py#L15) | repeated approval matches later plan without reusing consumed plan |
| [T107-C002](../../tests/test-unified-task-integration.py#L29) | exact proposal and direct user not peer |
| [T107-C003](../../tests/test-unified-task-integration.py#L35) | intervening user breaks plan approval |
| [T107-C004](../../tests/test-unified-task-integration.py#L38) | native header binding and natural user instruction |
| [T107-C005](../../tests/test-unified-task-integration.py#L55) | peer dispatch does not call waiting origin back |
| [T107-C006](../../tests/test-unified-task-integration.py#L65) | peer without task capability is rejected before dispatch |
| [T107-C007](../../tests/test-unified-task-integration.py#L74) | multi never falls back to local master |
| [T107-C008](../../tests/test-unified-task-integration.py#L83) | status and submit reach master once |
| [T107-C009](../../tests/test-unified-task-integration.py#L106) | old executor detaches without waiting for new executor operations |
| [T107-C010](../../tests/test-unified-task-integration.py#L137) | task lifecycle fences ledger not ordinary tools |

## T108 — test-unified-tasks.py

[Test source](../../tests/test-unified-tasks.py) · 106 lines · CI: `not-in-test-workflow` · `keep`

**守るもの:** authorityのepoch/handoff/cancel/freeze/quiescence/visibility

**本番接点:** [tasks.py](../../extensions/messaging/unified/tasks.py)

**証拠と限界:** real in-memory SQLite。Host/CLI入口とは別層。外部効果完了は未証明

**重なり:** `formal-task`.

| Case | 守る振舞い / 実際の検査 |
| --- | --- |
| [T108-C001](../../tests/test-unified-tasks.py#L15) | approval submit and idempotency |
| [T108-C002](../../tests/test-unified-tasks.py#L20) | incarnation fence and handoff |
| [T108-C003](../../tests/test-unified-tasks.py#L35) | operation quiescence and cancel |
| [T108-C004](../../tests/test-unified-tasks.py#L44) | status exposes only current actor operation details |
| [T108-C005](../../tests/test-unified-tasks.py#L58) | cancel tombstone survives freeze and late ack |
| [T108-C006](../../tests/test-unified-tasks.py#L65) | unfreeze is owner only and fences old epoch |
| [T108-C007](../../tests/test-unified-tasks.py#L78) | unfreeze aborts pending handoff without enabling target |
| [T108-C008](../../tests/test-unified-tasks.py#L90) | former executor keeps read access but not execution |
| [T108-C009](../../tests/test-unified-tasks.py#L101) | foreign approval and visibility |

## T109 — test-workspace-writer-lock.sh

[Test source](../../tests/test-workspace-writer-lock.sh) · 57 lines · CI: `not-in-test-workflow` · `strengthen`

**守るもの:** workspace writer排他・stale回復・手動/volatile field保持

**本番接点:** [tproj-workspace-lock.sh](../../bin/lib/tproj-workspace-lock.sh) / [TprojApp.swift](../../apps/tproj/Sources/TprojApp/TprojApp.swift)

**証拠と限界:** lockは実helper、mergeはテスト内コピー。workspace lockでありGit index.lockではない

**重なり:** `workspace` · **指摘:** F03.

Shellの検査位置 4 件はcase台帳の `T109` を参照。fixture setup/補助assertを含む位置一覧であり、独立シナリオ数ではない。

