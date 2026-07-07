# S-D1 — AppViewModel 段階分割計画（提案・実装禁止）

> Debt S-D1。本書は設計案のみ。承認前に 1 行も実装しない。

## 背景

`apps/tproj/Sources/TprojApp/TprojApp.swift:1566-3848` の `@MainActor final class
AppViewModel: ObservableObject` が God object。約 2280 行・60 超のメソッドが 1 型に同居し、
ランタイム配置・監視ポーリング・レイアウトロック・列操作・MIDI・コマンド実行が絡む。

根拠（現行 file:line、Phase 3 後）:

- 宣言: `TprojApp.swift:1566` (`@MainActor`) / `1567` (`final class AppViewModel`)。閉じ括弧は約 3848。
- 純ロジックは Phase 3 で既に `Sources/TprojLogic/` へ分離済み（`JogQuantizer` /
  `jogCycleOrder` / `GhosttyConfigParser` / quoting）。残るのは副作用を持つ責務。
- 責務クラスタ（代表メソッド）:
  - RuntimeStager: `bundledRuntimeSeedURL:1688` / `runtimeSeedDigest:1692` /
    `ensureBundledRuntimeStaged:1698` / `bundledRuntimeCommand:1772` /
    `resolveCommandPath:1780` / `runtimeLaunchCommand:1797` / `fallbackLaunchCommand:1802`
  - CommandRunner: `runCommand:3763` / `runCommandAsync:3776` / `trimmedError:3844`
  - MonitorPoller: `startMemoryPolling:2007` / `refreshMemoryStatus:2018` /
    `monitorCollectorCommand:2060` / `persistMonitorStatus:2104` /
    `persistMonitorErrorStatus:2118`
  - LayoutLock: `beginLayoutMutation:2132` / `endLayoutMutation:2143` /
    `acquireLayoutLockAsync:2172` / `releaseLayoutLock:2202`
  - MIDICoordinator: `toggleMIDILearn:2379` / `startMIDIIfNeeded:2993` / `focusPaneByJog:3015`
  - 列操作: `addColumn:2304` / `removeColumn:2688` / `moveColumn:2761`

## 提案する設計

AppViewModel を「UI 状態の保持と orchestration だけを持つ薄い @MainActor 型」に寄せ、
副作用の塊を協調型（collaborator）へ移す。UI が観測する `@Published` は AppViewModel に残し、
collaborator は値を返すだけ（`@Published` を持たない）。

推奨切り出し順（依存の少ない順・各段独立にビルド緑を保てる順）:

1. **CommandRunner を protocol 化**（土台）。`runCommand` / `runCommandAsync` を
   `protocol CommandRunning` + `struct ProcessCommandRunner` に。AppViewModel は
   `let runner: CommandRunning` を保持。これでテスト時に fake runner を注入でき、以降の
   段の検証が机上でなく単体テストで回せる。
2. **TmuxService**（S-D2 と一体、別提案 `s-d2-tmux-service.md`）。CommandRunner の上に
   tmux 動詞を薄く載せる。AppViewModel の tmux 直呼びを Service 経由へ差し替え。
3. **MonitorPoller** を `final class`（nonisolated 実行部 + MainActor への結果適用）へ。
   `refreshMemoryStatus` の Process 実行は runner 経由、結果適用のみ MainActor。
4. **RuntimeStager** を純寄りな `struct`/`final class` へ。`ensureBundledRuntimeStaged`
   はファイル I/O + digest で、UI 状態非依存。切り出し容易。
5. **MIDICoordinator** を最後に。CoreMIDI コールバック（別スレッド）→ MainActor 境界
   （S-D6）が絡むため、純化済み `JogQuantizer` を使う focus 経路の橋渡しに限定して移す。

## 段階的な commit 計画（1 commit = 1 collaborator）

- `refactor(gui): introduce CommandRunning protocol + ProcessCommandRunner (S-D1a)`
- `refactor(gui): route AppViewModel tmux calls through TmuxService (S-D1b)` ※s-d2 と協調
- `refactor(gui): extract MonitorPoller collaborator (S-D1c)`
- `refactor(gui): extract RuntimeStager collaborator (S-D1d)`
- `refactor(gui): extract MIDICoordinator collaborator (S-D1e)`
- 各段: `dev-app.sh` 緑 + `swift test` 緑 + 該当 collaborator の新規テスト。

## MainActor 境界の注意点（最重要）

- AppViewModel は `@MainActor`。`@Published` の変更は必ず MainActor で。collaborator を
  `nonisolated`/`actor`/バックグラウンド `Task` で走らせる場合、**結果適用だけを
  `await MainActor.run { ... }` か `Task { @MainActor in ... }` に閉じる**（既存
  `TprojApp.swift:1946`/`2997`/`3002` の hop パターンを踏襲）。
- `runCommand`（同期）は MainActor を**ブロックする**。UI スレッド上の長い Process 実行を
  増やさない。分割の過程で誤って sync 版をホットパスに残さないこと（`runCommandAsync`
  へ寄せる方向は S-D5 と整合）。
- CoreMIDI コールバックは MIDI 内部スレッドから来る（`MIDIPaneActivator`, `1352`）。
  MIDICoordinator 抽出時に isolation を素朴に `@MainActor` へ塗ると受信で hop が増え遅延。
  現状の「検出は非 MainActor、focus 適用のみ MainActor」を保つ（S-D6 は触らない前提）。
- collaborator へ `self`（AppViewModel）を強参照で渡すと retain cycle。コールバック系は
  `[weak self]` を維持（既存 `926` の作法）。

## リスクと検証方法

- リスク: レイアウトロック（B-D2 で dual-lock 化済み）に触れると focus/列操作が壊れる。
  → LayoutLock は**今回分割対象に含めない**（触らない）。分割は上記 5 collaborator のみ。
- リスク: `@Published` の更新箇所がスレッドを跨ぐと SwiftUI が warn/クラッシュ。
  → 各段で `dev-app.sh` 起動後に列追加/削除・監視表示・MIDI focus の実機スモーク。
- 検証: 段ごとに collaborator 単体テストを `Tests/TprojLogicTests` 相当へ追加（runner を
  fake 注入）。`swift test` 緑を Baseline 比較で維持（減ったら stop）。

## やらない場合の影響

God object が残り、tmux/監視/MIDI の変更が常に 2280 行の文脈読み込みを要求する。
テストは相変わらず executable 癒着で書けず、回帰は実機依存のまま。並行実行（レイアウト・
監視・MIDI）の境界が型で表現されず、将来の SIGWINCH 級インシデントの温床が残る。
