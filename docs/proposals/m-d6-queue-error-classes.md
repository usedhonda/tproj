# M-D6 — queue flush の「ターゲット消滅 vs 一時エラー」区別（提案・実装禁止）

> Debt M-D6。承認前に実装しない。致命ではない（STALE_SECONDS で最終破棄される）ため優先度低。

## 背景

`flush_all_queues()` は target 解決に失敗すると理由を問わず queue を保持する。
「ターゲットが恒久的に消えた（もう来ない）」ケースと「tmux 一時エラー / 一過性の未検出」を
区別せず、前者でも `STALE_SECONDS`（600s, `tproj-msg:512`）経過まで queue が残る。

根拠 file:line（現行、Phase 4 後）:

- `flush_all_queues()`: `tproj-msg:1956`。各 queue につき
  ```
  pane=$(resolve_target "$target_name" 2>/dev/null) || {
    echo "Warning: target '$target_name' not found, keeping queue" >&2
    continue
  }
  ```
  （`tproj-msg:1965-1968`）。`resolve_target`（`2282`）は **target が本当に存在しない**場合も
  **tmux list-panes が一時的に空を返した**場合も一様に非ゼロ終了（`return 1`, 例: `2309`）。
- 結果、恒久消滅でも「keeping queue」となり、`STALE_SECONDS` の age 判定（`1889`）で
  flush 時に破棄されるまで滞留。致命ではないが、消えた宛先向けメッセージが 10 分残る。

## 提案する設計

`resolve_target` に**失敗理由の exit code 分類**を持たせ、`flush_all_queues` が
恒久消滅を早期に見切れるようにする。文言・成功時挙動は不変。

- `resolve_target` の return code を 2 値化:
  - `0` = 解決成功（pane_id を stdout）
  - `RT_NOT_FOUND`（例: `3`）= セッション/ペイン一覧は取れたが該当 target が**居ない**
    （恒久消滅の可能性が高い）
  - `RT_TRANSIENT`（例: `4`）= `tmux list-panes` 自体が失敗/空（tmux 未応答等、一過性）
  - 判定材料は既にある: `pane_list=$(tmux list-panes ... 2>/dev/null)`（`2300`）の
    成否 + 一覧が空か否か。一覧が取れて該当なし → NOT_FOUND、一覧取得自体が失敗 → TRANSIENT。
- `flush_all_queues`（`1965-1968`）で分岐:
  - `RT_TRANSIENT` → 現状どおり「keeping queue」で `continue`（次 poll で再試行）。
  - `RT_NOT_FOUND` → age を見て閾値（例: 別定数 `TARGET_GONE_GRACE`、既定 = STALE_SECONDS の
    据え置きで挙動不変も可）超なら破棄ログを出して queue 削除、未満なら保持。
    **保守的初期値では STALE_SECONDS と同値**にして現行と等価挙動から始め、後で短縮可能に。

初期リリースは「分類の導入 + ログの明確化」までとし、破棄タイミングは現行等価に保つのが安全。

## 段階的な commit 計画

1. `refactor(messaging): classify resolve_target failures (not_found vs transient) (M-D6a)`
   — return code を 2 値化。呼び出し側は当面どちらも従来どおり扱い（挙動不変）。gate 22 緑。
2. `refactor(messaging): distinguish gone-target log in flush_all_queues (M-D6b)`
   — NOT_FOUND 時のログ文言を明確化（keeping/discard 判定は現行等価のまま）。
3. `feat(messaging): opt-in early discard for permanently-gone targets (M-D6c)`
   — `TARGET_GONE_GRACE`（既定 = STALE_SECONDS）で早期破棄を**設定可能に**。既定値では
   現行と同一挙動。有効化はユーザー判断。
4. 各段: gate 22 緑 + inbox 緑 + drift ゼロ（`cp` 反映）+ resolve_target 分類テスト追加。

## リスクと検証方法

- リスク: NOT_FOUND と TRANSIENT の誤判定で、一過性 tmux エラーを恒久消滅と誤認 →
  まだ来る宛先の queue を早期破棄（メッセージロスト）。→ 破棄は**恒久消滅かつ grace 超過**の
  二重条件に限定。初期は grace = STALE_SECONDS で現行等価から出発し、実運用で観測後に短縮。
- リスク: `resolve_target` は send/read 経路（`2565` 等）でも使う。return code 変更が
  それらの `|| { ... }` 分岐（`2566`）へ波及。→ send/read 側は「0 以外は全て失敗」で扱えば
  従来どおり（分類は flush だけが読む）。全経路の exit 分岐を回帰確認。
- 検証: fake tmux shim で (a) 一覧取得成功+該当なし (b) list-panes 失敗 の 2 系統を注入し、
  それぞれ NOT_FOUND / TRANSIENT を返すテスト。gate 22 全緑。

## やらない場合の影響

恒久消滅した宛先向けのメッセージが最大 10 分 queue に滞留し、無駄な flush poll を生む。
障害切り分け時に「宛先はもう居ないのに queue が残っている」状態の説明がログから読めず、
M-D5 と合わせて queue の観測性が低いまま。致命ではないため後回し可だが、消滅検知の
遅延はユーザーの「送ったのに反応がない」体験に寄与しうる。
