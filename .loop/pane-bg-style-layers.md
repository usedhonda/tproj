# LOOP: pane-bg 画風レシピの二層分離

GOAL: gpt-image-2 向けのセル画「技術 baseline」を tracked script の組み込み既定値へ移し、
`~/.config/tproj/pane-bg.local` と project-local `prompt.local.json` を house/persona の
override 専用に降格する。既存プロジェクトの画像は明示 regenerate まで 1 byte も変えない。

背景（この差分が必要な理由）:
- いま cel baseline（`style_guard_jp` と写実回避の否定語群）は
  `tproj/.local/tproj-pane-bg/prompt.local.json` にしか無く、gitignore されている。
- 他プロジェクトは override を持たないため `~/.config/tproj/pane-bg.local` の
  `TPROJ_PANE_BG_STYLE_REF_EN="Studio Ghibli"` だけを読む。gpt-image-2 はこれを
  写実寄りのツヤツヤした Ghiblify 調に解釈するので、狙った画風にならない。
- Cdx 推奨の切り分け: **provider 別の技術 default は tracked script が正本**、
  `~/.config` と project-local は **house/persona の好み** だけを持つ。
  こうすれば新 project・新 machine で再発せず、技術 baseline の変更が diff と test で追える。

## SUCCESS CRITERIA（甘い合格を作らない）

- 新規プロジェクト（override ファイルを一切持たない状態）で `--prof`/`--era` 等を付けずに
  prompt を組み立てたとき、gpt-image-2 経路の prompt に cel baseline が含まれる。
- `~/.config/tproj/pane-bg.local` の house override（`Studio Ghibli` 等）は
  **gemini 系（PRO_MODEL_NAME）で従来どおり効く**。降格によって既存の指定が無視されない。
- 優先順位が `tracked default < ~/.config (house) < project prompt.local.json (persona)` の
  順で上書きされることを検証する focused test が `tests/` に追加され、
  **実装を戻すと落ちる**ことを1回確認済み。
- 既存 6 プロジェクト（oc-general / aidj / tproj / mb / clawgate / vibeterm）の
  `.local/tproj-pane-bg/*.png` と `*.json` が **1 byte も変わらない**。
  この差分では画像を1枚も生成しない。
- `bash tests/smoke-bin.sh` と `bash install.sh --check` が緑、`~/bin/tproj-pane-bg` に反映済み。

## VERIFY — ゲート（自己採点しない）

反復中（速い順に走らせ、最初の赤で止める）:
- `bash -n extensions/persona/tproj-pane-bg`
- `bash tests/test-pane-bg-style-layers.sh`   ← このループで新規作成するもの
PASS = 上記が exit 0

**最後の1回だけ**（AGENTS.md の evidence budget に従い、publish 直前に同一 HEAD で1回）:
- `bash tests/smoke-bin.sh`
- `bash tests/test-pane-bg-style-layers.sh`
- `bash install.sh --check`   → `no drift`
PASS = 全て exit 0 かつ `install.sh --check` が `no drift`

反復のたびに broad suite を回さないこと。AGENTS.md の Quality Bar が明示的に禁じている。

## STATE FILE: .loop/pane-bg-style-layers-state.md

- 開始前に必ず読む。これは再開であって、やり直しではない。
- 毎 iteration、末尾に追記する: 何をしたか / 何が通り何が落ちたか / 次の一手（1つだけ）。

BUDGET（state に書く）: iteration cap 6 / no-progress streak 2

## EACH ITERATION

1. **契約を読み直す**（GOAL + SUCCESS CRITERIA + RULES）と state を読み、VERIFY を走らせて
   いまの赤を見る。長く回すと境界が薄れるので、毎回読み直すこと。
2. 影響のいちばん大きい次の一手を **1つだけ** 決める。
3. その一手に対する **最小の変更** を書く。
4. ゲートを走らせて VERIFY し、結果を state に記録する。
5. 判定: SUCCESS CRITERIA を **全て** 満たしたか。
   - Yes → 最後の broad gate を1回走らせ、緑なら `FINAL` と出力して停止。
   - No  → `ITERATING` と出力して継続。いちばん弱い criterion から潰す。

**同一アクション検知**: 各 iteration の {tool 名 + 引数} をハッシュして直近を保持する。
同じ呼び出しが3回目、または計画が前回と85%以上同じなら詰まっている →
stop_reason=no-progress で止める。空回りに金を払わない。

**回帰ガード**: 実装が固まったら、二層の優先順位を守る focused test を1本だけ追加する。
追加したら **実装を revert すると落ちる**ことを1回確認する。落ちないテストは書いた意味がない。

## STOP WHEN（停止時は必ず stop_reason を残す）

- success             : SUCCESS CRITERIA 全達成 + 最後の broad gate 緑
- no-progress         : 2 iteration 何も進まない、または同一アクション反復
- oscillation         : 同じ問題と修正の組を3回繰り返した
- failure             : 同じ問題が3回直せない
- budget              : 6 iteration に到達
- regression          : 既存画像・sidecar が変化した、または以前通っていた check が落ちた
                        → **FREEZE、commit しない**
- scope-boundary      : Explicitly Out に触れる必要が出た → 提案だけ書いて停止

## RULES

- ゲートが実際に通るまで完了と呼ばない。自己採点しない。
- **最初の VERIFY を尊重する**。何も変更しない時点で全 criterion を満たしているなら、
  それは本物の成功。`FINAL` と正直に報告し（「既に満たされていた」）、
  ループを正当化するための作業を捏造しない。
- maker != checker: 危ない変更は fresh eyes / subagent で見直す。
- **外科的変更のみ**。diff の各行が GOAL に trace できること。できないなら revert。
- **画像を生成しない**。この差分の検証に image API を呼ばない（費用と、人の目が要る判断のため）。
  画質の良し悪しはこのループの判定対象ではない。
- **`.local/` を commit しない**。生成物・ローカル runtime artifact をステージしない。
- **AGENTS.md の Protected Contracts を壊さない**: `AGENTS.md` / `CLAUDE.md` / `.gitignore` は
  runtime が触ってはならない。`project-bootstrap` / `model-role-router` の tracked symlink を
  実体化・付け替えしない。
- 探す前に決めつけない: 「無い」と言う前に grep する。
- **偽の完了を作らない**: placeholder・stub・TODO を完了として報告しない。
  ゲートを緑にするために check を削る・skip する・弱めることは絶対にしない。
- 報告は簡潔に: PASS は1行、FAIL は {期待 / 実際 / 直し方} を書く。
  変わっていない前回の失敗を再掲しない。context が汚れるだけ。
- 差分を検証する、世界ではなく: iteration 1 は全部見る。以降は変えた面だけ見直す。
- 空は失敗ではない: きれいに走って対象が無かった check（一致行ゼロ、空 diff）は本物の PASS。
  沈黙を「もっと頑張れ」と読まない。
- 同じ subtask が2回落ちたら、そのまま再試行しない。落ちている最小片（関数1つ、行1つ、
  test 1本）まで切り縮めて挑み直す。それも落ちたら初めて escalate する。
- commit は英語の conventional commit（`feat:`/`fix:`/`refactor:`/`test:`/`docs:`）。
  **Co-Authored-By を付けない**。1 commit = 1 論理サブステップ。
- ループ中に質問しない。妥当な仮定を置き、state に書いて進む。

## Explicitly Out（触らない）

- 画像の生成・再生成、画質の判定
- 既存 6 プロジェクトの `.local/tproj-pane-bg/` 配下のファイル
- GUI（`apps/tproj/`）、messaging、hooks、model-role-router
- push（御大の号令があるまで）

## 参考（実装の入口）

- `extensions/persona/tproj-pane-bg` 18-40行目: style 語彙の既定値と
  `~/.config/tproj/pane-bg.local` の source。
- 同 1240-1248行目: project-local `prompt.local.json` から
  `style_guard_jp` / `composition_extra_jp` / `negative_extra_jp` を読む箇所。
- `GPT_IMAGE_MODEL_NAME="gpt-image-2"` と `PRO_MODEL_NAME`（gemini）で provider を分岐できる。
- 現行の cel baseline の実物: `tproj/.local/tproj-pane-bg/prompt.local.json`
  （gitignore 済み。ここから技術部分だけを抜き、persona 固有の記述は混ぜない）。
