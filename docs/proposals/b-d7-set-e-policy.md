# B-D7 — bash/zsh スクリプトの set -e 方針統一（提案・実装禁止）

> Debt B-D7。承認前に実装しない。挙動変更を伴うため 1 スクリプト = 1 commit で慎重に。

## 背景

bin/ と extensions/ のシェル群で `set` の指定が不統一（`-euo` / `-uo` / なし が混在）。
方針が言語化されておらず、新規スクリプトがどれを選ぶべきか判断基準が無い。

現状サーベイ（`head -1` shebang + 最初の `set` 行、2026-07-07 Phase 4 後）:

| ファイル | shebang | set 行 |
|---|---|---|
| bin/rebalance-workspace-columns | /bin/bash | `set -euo pipefail` |
| bin/tproj | /bin/zsh | `set -euo pipefail` |
| bin/tproj-drop-column | env bash | `set -euo pipefail` |
| bin/tproj-kill-pane | /bin/bash | `set -euo pipefail` |
| bin/tproj-mru-tracker | /bin/bash | `set -euo pipefail` |
| bin/tproj-pane-autozoom | /bin/bash | `set -euo pipefail` |
| bin/tproj-pane-clear-rank | /bin/zsh | `set -euo pipefail` |
| bin/tproj-pane-focus-hook | /bin/zsh | `set -euo pipefail` |
| bin/tproj-respawn-guard | /bin/bash | `set -euo pipefail` |
| bin/tproj-tmux-state-notify | /bin/bash | `set -euo pipefail` |
| bin/tproj-toggle-yazi | /bin/bash | `set -euo pipefail` |
| **bin/sign-codex** | /bin/bash | **(no set)** ← 逸脱 |
| **bin/tproj-mem-trace** | /bin/bash | **`set -uo pipefail`（-e 無し）** ← 逸脱 |
| **bin/tproj-postmortem** | /bin/bash | **`set -uo pipefail`（-e 無し）** ← 逸脱 |
| **bin/wait-for-pane-text** | env bash | **`set -uo pipefail`（-e 無し）** ← 逸脱 |
| bin/lib/tproj-common.sh | (source lib) | (no set) ← 正（後述） |
| extensions/messaging/tproj-msg | /bin/bash | `set -euo pipefail` |
| extensions/hooks/tproj-inbox-check | /bin/bash | `set -euo pipefail` |
| extensions/hooks/tproj-inbox-record | /bin/bash | `set -euo pipefail` |

## 提案する設計（統一方針）

3 カテゴリで方針を固定する:

1. **通常の CLI/デーモン系（bin/ の大半, tproj-msg）** → `set -euo pipefail` を必須。
   早期失敗で不整合を防ぐ。既に大半が準拠。
2. **sourced ライブラリ（`bin/lib/tproj-common.sh`）** → `set -e` を**付けない**。
   ライブラリは呼び出し元のシェルに `set` を波及させるため、`-e` を付けると source した
   スクリプトの挙動を汚染する。現状（no set）が正。方針として明文化。
3. **hook 系（`extensions/hooks/*`）** → **best-effort / fail-open を最優先**。hook は
   Claude Code のプロンプト/ツール処理に割り込むため、途中の 1 コマンド失敗で `set -e` に
   より全体が非ゼロ終了すると、プロンプト処理をブロックしうる。方針は「`-e` を外し、
   各 fallible 行を個別に `|| true` 等で守る」か、`-e` を残すなら**全経路が fail-open で
   非ゼロ終了しないことをテストで保証**する。現状 hooks は `-euo pipefail`。これを
   best-effort へ寄せるか、fail-open をテストで固定するかは要判断（下記リスク参照）。

### 現状の逸脱一覧（統一方針に対して）

- `bin/sign-codex`: set 無し → **`set -euo pipefail` を追加**。
- `bin/tproj-mem-trace`: `-uo`（`-e` 欠）→ trace 系で途中失敗を握って続行したい意図の可能性。
  意図確認の上、CLI 方針に合わせるなら `-e` 追加、best-effort 意図なら理由をコメント明記。
- `bin/tproj-postmortem`: `-uo` → 同上（postmortem は途中失敗しても最大限情報を集めたい =
  best-effort 意図が濃厚）。best-effort として**明示コメント + 方針表に例外記載**が妥当。
- `bin/wait-for-pane-text`: `-uo` → poll ループで一時失敗を握る意図が濃厚。同上。
- hooks（inbox-check/record）: 現 `-euo` を best-effort 方針と照合し要判断。

→ 結論の型: 「CLI = -euo 必須」「lib = set なし」「best-effort が本質のもの（postmortem /
wait / mem-trace / hook）は -e を外し**理由コメント + 方針表の例外欄**で正当化」。
黙って混在ではなく、各逸脱に根拠を持たせるのが統一の実体。

## 段階的な commit 計画（1 スクリプト = 1 commit）

1. `docs(reference): add shell set -e policy (B-D7-doc)` — 方針を
   `docs/reference/` にコメント/表として明文化（このカテゴリ 3 分類）。
2. `fix(bin): add set -euo pipefail to sign-codex (B-D7a)` — 明確な欠落補完。動作確認必須。
3. `chore(bin): annotate best-effort rationale for postmortem/wait/mem-trace (B-D7b)`
   — `-e` を付けず、なぜ best-effort かをコメントで固定（挙動不変）。
4. （要判断）`refactor(hooks): make inbox hooks fail-open explicit (B-D7c)` — hook の
   `-e` 方針を確定。触るなら `test-inbox-check.sh` 緑を維持し、失敗注入でプロンプトを
   ブロックしないことを検証。
5. 各段: `bash -n`/`zsh -n`（`tests/smoke-bin.sh`）全緑 + 変更スクリプトの代表実行 +
   drift ゼロ（`cp` 反映）。

## リスクと検証方法

- リスク（最大）: `set -e` を後付けすると、これまで握られていた失敗で**早期 exit するように
  挙動が変わる**（特に postmortem/wait のような握り前提スクリプト）。→ best-effort が本質の
  ものには `-e` を付けない。付けるのは明確に「失敗即停止が正しい」CLI のみ。
- リスク: hook に `-e` を残したまま fallible 行があると、プロンプト処理をブロック。→ hook は
  失敗注入テストで「非ゼロ終了しない/プロンプトを止めない」を確認してから確定。
- 検証: `tests/smoke-bin.sh`（構文 + 無害実行）緑 + `test-inbox-check.sh` 緑 +
  各スクリプトの代表実行で早期 exit しないこと。

## やらない場合の影響

新規スクリプトが `set` 方針を都度カンで選び、混在が拡大。best-effort であるべき postmortem
系にうっかり `-e` が付いて情報収集が途中で止まる、逆に CLI で握りつぶしが増える、といった
判断ミスが起き続ける。方針が言語化されないため、逸脱がバグか意図か区別できない。
