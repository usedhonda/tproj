---
name: role
description: |
  tproj の役割設定スキル。プロジェクトの Mode と Main conversation を変更する時に使う。

  **Mode と Main は別のレバー。混同してはならない。**
  - Mode = 二人の働き方（Collab / Assist / Solo）
  - Main conversation = ユーザーが会話する主の側（cc / cdx）。GUI の表示とペイン背景の主従もこれで決まる

  以下のような状況・表現で発動:
  - 「主を Cdx に」「Cdx を主にして」「主役 Cdx」「Main を cc に」
  - 「主を渡して」「主を交代して」（= 言われた側から見た反対側へ渡す）
  - 「主を戻して」「主の指定を消して」
  - 「Collab にして」「Assist にして」「Solo で」「一人でやって」
  - 「役割を変えて」「モードを変えて」「役割どうなってる？」
  - `/role` コマンド

  ※ 「主を渡して」は相対指定。cc ペインで言われたら cdx へ、cdx ペインで言われたら cc へ
  ※ 何も言われなければ現在のプロジェクトだけ。「全プロジェクト」「全部の列」なら --all
  ※ Crew（subagent を tmux ペインに並べる運用機能）は Mode ではない。「crew を立てて」は別物
  ※ auto / advisor は撤去された旧名。使わない。言われたら Collab / Assist と読み替える
argument-hint: <collab|assist|solo> | main <cc|cdx>
allowed-tools: [Bash, Read]
compression-anchors:
  - "tproj-role で Mode と Main conversation を変更"
  - "Mode(Collab/Assist/Solo) と Main(cc/cdx) は別のレバー"
  - "変更後は --json で before/after を確認してから報告"
---

# role — tproj の役割設定

Mode と Main conversation は `<project>/.local/role-mode.json` に保存され、
`model-role-router` だけがこれを書く。`tproj-role` はその front end。

## 二つのレバー

| | 値 | 何が変わるか |
|---|---|---|
| **Mode** | `collab` / `assist` / `solo` | 二人の働き方。PreToolUse ゲートの権限もここで決まる |
| **Main conversation** | `cc` / `cdx` | ユーザーが会話する主の側。GUI の表示とペイン背景の主従 |

**片方を変えても、もう片方は動かない。** 「主を渡して」と言われて Mode だけ変えると、
状態ファイルは書き換わるのに GUI も背景も何も変わらず、依頼が無視されたように見える。

Mode の意味:

- **Collab** — 両方が作業する。tier で指揮側が決まる（既定。ファイルが無い状態）
- **Assist** — 話しかけた側が作業し、反対側は助言のみ。実装・commit はしない
- **Solo** — 話しかけた側が単独で完遂し、反対側は関与しない

## 使用手順

1. 対象プロジェクトを決める（指定が無ければ現在のプロジェクト）
2. **変更前の状態を読む**: `tproj-role --json [--project <path>]`
3. 変更を実行する
4. **もう一度読んで、実際に変わったことを確認する**
5. before → after を示して報告する

```bash
tproj-role --json                          # いまの状態
tproj-role main cdx                        # 主を Cdx へ
tproj-role main cc                         # 主を CC へ
tproj-role main derived                    # 主の指定を消して自動判定に戻す
tproj-role assist                          # Mode だけ変える
tproj-role assist --main cdx               # Mode と主を同時に
tproj-role collab --project <path>         # 別プロジェクト
tproj-role assist --all                    # workspace の全プロジェクト
```

## 「主を渡して」の解き方

**相対指定として解く。** 言われたペインから見た反対側へ渡す。

- `cc` ペインで「主を渡して」→ `tproj-role main cdx`
- `cdx` ペインで「主を渡して」→ `tproj-role main cc`

自分がどちら側かは、毎ターン注入される `[Model Role Runtime]` の `self=` で分かる。

## 報告の形

**「やった」だけで終えない。** 実際に変わったことを確認してから、こう返す。

```
mb: mode assist（変更なし） / main cc -> cdx
背景も切り替わりました
```

GUI と背景は3秒以内に自動で追いつく（GUI が role-mode.json を監視し、
変化を見つけたら `tproj-pane-bg sync --fast` を蹴る）。**手で sync を叩く必要はない。**
追いつかない場合はそれ自体が不具合なので、握りつぶさず報告する。

## 混同しやすいもの

- **Crew** — subagent を tmux ペインとして並べる別機能（`extensions/crew/`、`crew-watcher`）。
  Mode ではない。「crew を立てて」「crew ペイン」はこのスキルの担当外
- **role の値** — `orchestrator` / `worker` / `solo-fallback` / `assist` は
  「このペインが今何者か」を表す派生値で、router が毎ターン計算する。直接は設定できない
- **`auto` / `advisor`** — 撤去された旧名。CLI は受け付けない。
  古い state file を読む時だけ内部で読み替えられる

## やってはいけないこと

- Mode を変えて「主を変えた」と報告する（今回の改名の発端になった事故）
- ユーザーの指示なしに自分から主を自分側へ移す。`set_by` に実行者が記録され、
  注入行に毎ターン表示される。指示がある時だけ動かす
- 確認せずに完了を報告する
