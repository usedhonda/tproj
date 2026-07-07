# S-D5 — statusText 握りつぶしの Result/throws 境界化（提案・実装禁止）

> Debt S-D5。承認前に実装しない。文言互換の維持が前提。

## 背景

`apps/tproj/Sources/TprojApp/TprojApp.swift` でエラーが `statusText` への文字列代入へ
握りつぶされる。`grep -c 'statusText = \|self.statusText = '` = **72 箇所**（初期分析
「78」から Phase 2-4 の周辺整理で微減、依然大量）。失敗が UI 文字列に落ち、呼び出し元は
成功/失敗を型で判別できないため、連鎖する非同期処理（列操作→normalize→保存）の途中失敗が
握られたまま次工程へ進みうる。

根拠 file:line:

- 代表: `applyLiveColumnsResult:3412`（失敗系で `statusText = ...` 分岐）/
  `trimmedError:3844`（`CommandResult` から人間可読文字列を作る唯一の集約点）/
  列操作 `addColumn:2304` / `removeColumn:2688` / `moveColumn:2761` 各所で
  `statusText = "..."` により失敗を吸収。
- 失敗の実体は主に `CommandResult`（`runCommandAsync:3776` の戻り）。exit code は
  持っているが、呼び出し側は文字列化してから捨てている。

## 提案する設計

「握りつぶし」を無くすのではなく、**成功/失敗を型で運び、UI 文言への変換を 1 箇所へ集約**する。
文言は現行を temネート化して**バイト互換**を保つ。

1. 失敗表現を `enum TprojError: Error`（case ごとに現行文言テンプレを保持）へ。
   `trimmedError(_:)` (`3844`) を `TprojError` → 表示文字列の**唯一の変換器**にする
   （現行の文言生成ロジックをそのまま移す）。
2. Process 実行境界を `throws`/`Result` 化。
   `runCommandAsync` はそのまま `CommandResult` を返し、その直上の各操作メソッドが
   `func addColumn() async throws` のように失敗を投げる/返す形へ。
3. UI 最外周（`Task { @MainActor in ... }` の catch）で 1 回だけ
   `statusText = trimmedError(error)` を実行。中間層は代入しない。
4. **文言互換の守り方**: 移行の各 commit で「旧経路が出していた statusText 文字列」と
   「新経路が出す文字列」を突き合わせるゴールデンテストを `Tests/` に置く。文字列定数は
   `TprojError` の case に literal で保持し、既存文と 1 文字も変えない。

## 段階的な commit 計画（1 操作系 = 1 commit）

1. `refactor(gui): define TprojError with verbatim message templates (S-D5a)`
   — 型追加のみ。`trimmedError` を変換器として明示。呼び出し差し替えなし・挙動不変。
2. `refactor(gui): thread Result through addColumn path (S-D5b)`
   — 列追加系の中間握りつぶしを除去、最外周で 1 回代入。ゴールデンテスト同梱。
3. `refactor(gui): thread Result through removeColumn/moveColumn (S-D5c)`
4. `refactor(gui): thread Result through save/workspace paths (S-D5d)`
5. 残りの散発代入を最外周へ寄せる段（必要なら分割）。
6. 各段: `dev-app.sh` 緑 + 文言ゴールデンテスト + `swift test` 緑。

移行は**全 72 箇所を一度に触らない**。1 操作系ずつ、旧文言を固定したまま内部配線だけ変える。

## リスクと検証方法

- リスク: 文言が 1 文字でも変わると、ユーザー/他 AI が UI をパースしていた場合に破断
  （§5 Stop 条件「出力文言」）。→ ゴールデンテストで旧文言を pin。差分が出たら stop。
- リスク: `throws` 化で SwiftUI の `Task` 境界に伝播漏れ→無音失敗。→ 最外周 catch を
  必須にし、握りつぶし禁止のパスは `try` 経路のみ通す。
- リスク: MainActor 越境（S-D6）。→ 代入は最外周 `@MainActor` の 1 点に限定。
- 検証: 各段で失敗注入（fake runner が exit≠0 を返す）→ 期待 statusText が旧文言と一致。

## やらない場合の影響

失敗が UI 文字列へ落ちたまま呼び出し元へ伝わらず、連鎖非同期処理の途中失敗が握られて
次工程へ進む構造が残る（列操作の部分失敗が silent に）。失敗経路のテストが書けず、
回帰は「たまたま UI 文言が出た/出ない」の目視依存のまま。
