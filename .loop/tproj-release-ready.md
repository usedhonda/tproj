# LOOP: tproj release-ready

## GOAL

現在の tproj `main` を、不要な作業や反復テストを増やさず、検証済みの publish-ready 状態にする。

このループは closed loop である。1回の起動では1 iterationだけ実行し、必ず `FINAL` または `ITERATING` で終了する。ループ実行そのもの、継続起動、push はこの文書の生成タスクには含まれない。

## SUCCESS CRITERIA

次をすべて満たした時だけ成功とする。

1. 現在の対象不具合、失敗、または未統合変更が明示され、根拠のない仕事を新設していない。
2. 必要な変更がある場合、変更行は対象に直結し、無関係な差分がない。
3. 反復中は変更面を偽証できる最小の既存チェックだけが通っている。
4. 実バグまたは protected contract の未捕捉がある場合だけ、挙動安定後に最小回帰テストを1つ追加または修正している。
5. publish 直前に必要な最終ゲートを同一 HEAD・同一環境で1回だけ通している。既に同条件の成功記録が state にあれば再実行しない。
6. 配布対象を変更した場合だけ installed copy を更新し、`install.sh --check` が通っている。
7. `git diff --check` が通り、関連変更だけが conventional commit になり、worktree が clean である。
8. push はその実行に対するユーザーの明示指示がある場合だけ行い、行った場合は local HEAD と remote default branch の一致を確認している。

対象不具合も未統合変更もなく、必要な gate の有効な成功記録がある場合は、変更を作らず成功とする。

## STATE FILE

`.loop/tproj-release-ready-state.md` を唯一の進捗正本とする。iteration開始時に読み、終了前に必ず更新する。

記録する項目:

- iteration番号、開始時刻、HEAD SHA
- 今回変える意思決定と、その根拠
- 変更したファイルと intent との対応
- 実行したチェック、終了コード、結果、実行環境
- 同一 HEAD・同一環境で再利用できる green evidence
- 未解決 blocker、次の最小1手
- budget 使用量と no-progress 回数

## BUDGET AND STOP POLICY

- iteration cap: 6
- wall-clock cap: 60分
- no-progress cap: 2 iteration
- 1 iteration: 1つの意思決定、1つの最小変更単位、必要最小限の確認まで

次のいずれかで即停止する。

- SUCCESS CRITERIA を満たした: `FINAL: success`
- 対象が存在せず、現状が既に条件を満たす: `FINAL: already-ready`
- 安全、機密、破壊的変更、根拠不足の境界に達した: `FINAL: blocked`
- cap 到達または no-progress: `FINAL: budget-exhausted` または `FINAL: no-progress`
- まだ安全に進められる: `ITERATING`

cap 到達を成功扱いしない。未確認を推測で埋めない。

## ITERATION PROCEDURE

### 1. ORIENT

state、`git status --short`、現在の HEAD、対象となるユーザー指示・CI失敗・未統合差分を読む。読む対象ごとに「結果が何の意思決定を変えるか」を1行で言えない read/tool call は省く。

対象が曖昧な場合、勝手に改善点を作らない。repo内の一次証拠から現在の失敗を1つに絞れなければ `FINAL: blocked` とし、必要な判断だけを報告する。

### 2. SELECT ONE DELTA

最も上流で、最小変更で、ユーザーに観測可能な失敗を1つだけ選ぶ。Fact と Hypothesis を分離し、再現または一次ソースで原因を確定してから編集する。

同時に複数の改善、drive-by refactor、将来用抽象化、無関係な整形を行わない。

### 3. IMPLEMENT SURGICALLY

既存挙動を保ち、対象に直結する行だけ変更する。protected contract を変更する場合は対応する contract doc と最小 focused test を同一 commit に含める。

中間パッチごとに新しいテストを作らない。重い suite を走らせない。挙動または契約が安定するまで回帰テストを増やさない。

### 4. VERIFY CHEAPLY

変更がある iteration では、次の順で必要なものだけ実行する。

1. 変更ファイルの syntax/static check
2. 変更を偽証できる最小の既存 focused testを1つ
3. `git diff --check`

同一 HEAD・同一環境ですでに green のチェックは再実行しない。workerやCIの全suite証拠を、同じ条件で丸ごと複製しない。

回帰テストの追加・修正は、実バグ、外部観測可能な挙動、または未捕捉の protected contract に限る。1つの安定した最終挙動に対して最小1件とし、中間実装ごとのテストを禁止する。

### 5. FINAL GATE ONCE

publish直前、または acceptance criteria が要求する時だけ実行する。`extensions/messaging` または `extensions/hooks` を変更した場合の最終ゲートは `.github/workflows/test.yml` のsuite集合を正本とし、同一 HEAD・同一環境で1回だけ通す。

それ以外の変更では、repo契約が要求する relevant gate だけを使い、理由なくfull gateへ拡張しない。関連コード・test・環境が変わった時だけ再実行できる。

配布対象を変更した場合だけ、安全な反映経路を使ってinstalled copyを更新し、`install.sh --check` を実行する。live workspace中に `install.sh` を直接実行しない。

### 6. COMMIT AND PUBLISH BOUNDARY

変更が完成して最小確認が通ったら、関連差分だけを英語の conventional commit にする。push は現在のユーザー指示が明示している場合だけ行う。push後はremoteをfetchし、local HEADとremote default branchのSHA一致を確認する。

### 7. UPDATE STATE

新しい証拠だけをstateへ書く。同じ結果の再掲、長いtest transcript、推測の履歴は残さない。次のiterationがある場合は「次の最小1手」を1つだけ指定する。

## VERIFY

判定の正本は、変更面に対応するfocused check、`git diff --check`、必要時だけのfinal gate、配布変更時だけの`install.sh --check`、およびGitのSHAである。文章上の自己申告だけで完了にしない。

checkerはmakerと同じ主張を読み替えるだけでなく、diffまたは一次出力を確認する。利用可能な独立peerがいない場合は、決定的コマンドとfresh diff reviewをcheckerとし、存在しないpeerを理由に停止しない。

## OUTPUT CONTRACT

各iterationの最終出力は短く、次のどちらかだけで始める。

- `ITERATING` — 今回のdelta、得た新証拠、次の最小1手
- `FINAL` — 終了理由、反映、最小確認、commit/push SHA、未実施またはblocker

テスト名の羅列や既出証拠の再掲より、今回変わった判断を優先する。
