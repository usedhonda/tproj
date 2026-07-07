# M-D5 — enqueue/flush の flock 相互排他設計（提案・実装禁止）

> Debt M-D5。承認前に実装しない。flock 導入は挙動微変リスクがあるため慎重に。

## 背景

`extensions/messaging/tproj-msg` の queue は append(enqueue) と read+truncate(flush) が
**無ロック**で、レアな競合下で silent なメッセージロストが起こりうる。

根拠 file:line（現行、Phase 4 後）:

- `enqueue()`: `tproj-msg:1800`。追記は `printf ... >> "${QUEUE_DIR}/${target_name}.queue"`
  (`1805`)。追記後に `start_flush_worker`（`1806`）でバックグラウンド worker を起動。
- flush worker: `start_flush_worker()` `1817` が `bash -c` で detach し、
  `"$script" --flush` を poll ループで叩く（`1828-1842`）。
- `flush_queue()`: `1861`。`while IFS=$'\t' read -r ... < "$qfile"`（`1881-1944`）で全読み、
  末尾で **`printf ... > "$qfile"`（残存を上書き）または `rm -f "$qfile"`（`1946-1950`）**。
- 競合窓: flush が `read` を開始してから `1947`/`1949` で truncate/rm するまでの間に、
  別プロセスの `enqueue` が同ファイルへ `>>` すると、その追記行は flush の読み込み対象外
  かつ truncate/rm で消える → **silent lost**。`--fire`/normal は自プロセスで
  `flush_queue` を呼び（`2772`/`2790`）、worker も別プロセスで叩くため多重化しうる。

## 提案する設計

queue ファイル 1 つにつき **flock による相互排他**を導入し、「enqueue の追記」と
「flush の read→truncate/rm」を同一ロック下で直列化する。ロック粒度は per-target queue。

```
# 概念（実装時は tproj-msg の style に合わせる）
QLOCK="${QUEUE_DIR}/${target_name}.queue.lock"
with_queue_lock() {         # $1=target_name, 残り=実行するコマンド
  exec {fd}>"$QLOCK"
  flock "$fd"               # ブロッキング。worker/前景の両経路が同じロックを取る
  "${@:2}"
  # fd クローズでロック解放（サブシェルなら自動）
}
```

- `enqueue` の `printf >>`（`1805`）を `with_queue_lock` 配下へ。
- `flush_queue` の `read ... done < "$qfile"` から `> "$qfile"` / `rm -f`（`1881-1950`）までの
  **read→truncate を 1 つのクリティカルセクション**に収める。ここが肝：read 開始と truncate を
  同一ロックで囲まないと窓が残る。
- 「残存行を kept_lines に貯めて末尾で書き戻す」現行方式（`1897`/`1946-1950`）はそのまま。
  flock はその全体を包む。
- **macOS 前提**: `flock(1)` は標準では入っていない環境がある。util-linux 版が無い場合の
  代替として、既存の `start_flush_worker` が使う `.flush-worker.pid`（`1818`）と同じ
  `mkdir` アトミック lock（`tproj-msg:2642` の `seq_dir` パターンと同流儀）を使う案も併記。
  どちらか一方に統一（環境調査の上で決定）。

## 段階的な commit 計画

1. `test(messaging): add enqueue/flush race repro (M-D5a)`
   — 先に**壊れることを示す**テスト（並行 enqueue 中の flush で 1 行消える再現）を
   hermetic harness に追加。これが赤いことを確認してから実装。
2. `refactor(messaging): add with_queue_lock helper (M-D5b)`
   — ロックヘルパ追加のみ（未使用）。gate 22 緑。
3. `fix(messaging): serialize enqueue append under queue lock (M-D5c)`
4. `fix(messaging): serialize flush read+truncate under queue lock (M-D5d)`
   — M-D5a の再現テストが緑化することを確認。
5. 各段: gate 22 緑 + inbox 緑 + drift ゼロ（`cp` 反映）。

## リスクと検証方法

- リスク（挙動微変）: flock はブロッキング。前景 `--fire`/normal 送信が worker の flush 中は
  待たされ、体感でわずかに遅くなりうる。→ ロック粒度を per-target に限定し保持時間を最小化
  （send-keys の sleep はロック外へ出せるか検討）。デッドロックは単一ロックのみで回避。
- リスク: flock 依存追加で環境非対応（macOS 素の環境）→ 送信不能。→ 導入前に対象ホストで
  `command -v flock` を確認。無ければ mkdir アトミック lock 案へ切替（§依存 fail-open 方針）。
- リスク: worker と前景の二重 flush（`2772`/`2790` + worker）でロック競合が常態化。→ 再現
  テストで並行度を上げても lost=0 かつ deadlock=0 を確認。
- 検証: M-D5a 再現テストが実装前=赤 / 実装後=緑。gate 22 全緑。STALE_SECONDS 破棄
  （`1889`）と max_count 保持（`1895`）の既存挙動が不変であること。

## やらない場合の影響

レアだが実在する silent メッセージロストが残る（高並行時の enqueue↔flush 競合）。
M-D6（ターゲット消滅時の queue 保持）と合わせ、queue の信頼性が「たまたま競合しない」
前提に依存し続ける。障害時に「送ったのに届いていない」の再現不能な報告を生む温床。
