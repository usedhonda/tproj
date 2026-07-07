# S-D2 残り — TmuxService / CommandRunner protocol 化（提案・実装禁止）

> Debt S-D2 の残り部分。Phase 2 で `"tproj-workspace"` リテラルの `static let` 集約
> （`enum TmuxTargets`, commit `7465ffb`）は完了済み。本書はその上に載る Service 抽出案。
> 承認前に実装しない。

## 背景

`apps/tproj/Sources/TprojApp/TprojApp.swift` に tmux/Process 呼び出しが **77 箇所**散在
（`grep -c 'runCommand\|Process()\|runTproj\|runTmux'` = 77）。ほぼ全てが
`runCommand(_:_:environment:)` (`3763`) / `runCommandAsync(...)` (`3776`) を直接叩き、
`~/bin/tproj` 等の launch path を各所で `NSHomeDirectory()` 解決して組み立てている。

根拠 file:line:

- 同期実行: `TprojApp.swift:3763 runCommand(_ launchPath:_ arguments:environment:)`
- 非同期実行: `TprojApp.swift:3776 runCommandAsync(...)`
- 代表 tmux 直呼び: `listWorkspacePanesAsync:3631` / `relocatePaneAboveCodexAsync:3649` /
  `swapProjectTagsAsync:3659` / `applyLiveColumnsResult:3412` ほか。
- session リテラルは Phase 2 で `TmuxTargets`（`7465ffb`）へ集約済み（値: `tproj-workspace`,
  `tproj-workspace:dev`）。tmux **動詞**（list-panes / set-option / select-pane 等）は未抽象。

Phase 2 完了分（定数化）の上に、呼び出しの**振る舞い**を protocol 越しへ移すのが本提案。

## 提案する設計

2 層に分ける。

1. **`protocol CommandRunning`**（S-D1a と共有の土台）
   ```
   protocol CommandRunning {
     func run(_ launchPath: String, _ args: [String], env: [String:String]) -> CommandResult
     func runAsync(_ launchPath: String, _ args: [String], env: [String:String]) async -> CommandResult
   }
   struct ProcessCommandRunner: CommandRunning { /* 現 runCommand 本体を移設 */ }
   ```
   `NSHomeDirectory()` 解決・環境変数マージ・`CommandResult` 生成をここへ集約。GUI からの
   `zsh -lc` 禁止（§3-9）は ProcessCommandRunner のドキュメントコメントで固定。

2. **`struct TmuxService`**（CommandRunner の上の薄い動詞ラッパ）
   ```
   struct TmuxService {
     let runner: CommandRunning
     let session = TmuxTargets.session   // 既存 enum を再利用
     func listPanes(window: String) async -> [PaneInfo]
     func setOption(_ key: String, _ value: String, target: String) async
     func selectPane(_ paneID: String) async
     func swapRoleTags(...) async -> String?
     // 現在 AppViewModel に散る tmux 動詞を 1:1 で移送
   }
   ```
   AppViewModel は `let tmux: TmuxService` を保持し、`tmux list-panes ...` の文字列組み立てを
   Service 内へ隠蔽。呼び出し側は動詞名で読める。

テスト可能性: `CommandRunning` を fake 実装（記録・固定応答）にすれば、TmuxService の
コマンド組み立てとパースを `Tests/` で単体検証できる（現状 executable 癒着で不能）。

## 段階的な commit 計画

1. `refactor(gui): add CommandRunning protocol + ProcessCommandRunner (S-D2a)`
   — 現 `runCommand`/`runCommandAsync` 本体を移設、AppViewModel は委譲。挙動不変。
2. `refactor(gui): add TmuxService over CommandRunning (S-D2b)`
   — 空の Service を追加、`TmuxTargets` を束ねるだけ（呼び出し差し替えなし）。
3. `refactor(gui): route pane-list/read paths through TmuxService (S-D2c)`
   — `listWorkspacePanesAsync` など**読み取り系**から順に差し替え（低リスク先行）。
4. `refactor(gui): route mutation tmux calls through TmuxService (S-D2d)`
   — set-option / select-pane / swap tag 系。**レイアウトロック配下の呼びは
   最後、かつ B-D2 の lock 順を 1 行も変えない**。
5. 各段: `dev-app.sh` 緑 + TmuxService/runner の単体テスト追加 + `swift test` 緑。

## リスクと検証方法

- リスク: コマンド文字列の組み立てを移送する際、引数のクォート/順序がずれると tmux 動作が
  変わる。→ fake runner で「投げたコマンド列」をスナップショット比較するテストを先に置き、
  移送前後で同一を保証。
- リスク: mutation 系を Service 化する過程でレイアウトロック（`acquireLayoutLockAsync:2172`,
  B-D2 dual-lock）の内外関係を崩す。→ ロック取得/解放は AppViewModel 側に残し、Service は
  ロックを知らない純粋な動詞に留める。
- リスク: `zsh -lc` ハング（§3-9）を Service 化のついでに混入。→ ProcessCommandRunner は
  launchPath 直実行のみ許可、`zsh -lc` 経路を作らない。
- 検証: 各段で列追加/削除・yazi/terminal トグル・focus の実機スモーク + `swift test`。

## やらない場合の影響

77 箇所の tmux 直呼びが型で守られず、session 名以外の tmux 動詞は文字列散在のまま。
コマンド組み立ての回帰（引数順・window 指定漏れ）を机上で検出できず、常に実機依存。
S-D1 の CommandRunner 差し替えテストも土台が無いまま進められない。
