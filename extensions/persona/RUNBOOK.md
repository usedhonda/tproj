# tproj-pane-bg Runbook

`extensions/persona/tproj-pane-bg` の運用手順書。persona 画像を image-only で override する方法、プロンプト構造、ハマりポイント、Cdx/CC 両方が読む前提。

## 何のためのツール

tmux pane 背景画像を Gemini で生成する。各ペインの persona（職業 / 性別 / 時代 / 口調 / キャラ属性 / 呼称 / 上下関係）から衣装・構図・背景を決めて、設定した house style（公開デフォルトは generic な手描きアニメ調、`~/.config/tproj/pane-bg.local` で変更可）の半身ポートレートを出す。

## 基本的な呼び出し

```
~/bin/tproj-pane-bg generate --project <repo> --role <cc|cdx> [--refresh]
```

- `--project`: 対象 persona を持つリポジトリ（例 `/Users/alice/projects/my-app`）
- `--role`: `cc` / `cdx` のどちらのペイン画像を作るか
- `--refresh`: 既存キャッシュ無視、強制再生成
- 出力: `<repo>/.local/tproj-pane-bg/<role>.vertical.png` と `.json` sidecar

## instruction 二層契約

`project-bootstrap` は shared instruction と local runtime artifact を別の
操作として扱う。

- shared 層: tracked `AGENTS.md` / `CLAUDE.md`。作成は
  `project-bootstrap --init-shared <repo>`、legacy block や instruction
  symlink の移行は `--migrate-shared <repo>`（dry-run）と `--apply` でのみ行う。
- local 層: `MEMORY.md` persona block、`.codex/config.toml` persona block、
  `.cc-status-bar.voice.json`。SessionStart、`tproj` startup の `--prime`、
  `voice-identity-sync --ensure` が扱うのはこの層だけ。
- runtime 経路は tracked `AGENTS.md` / `CLAUDE.md` / `.gitignore` を作成・
  変更しない。shared 層の初期化や移行を startup の副作用にしない。

実装の版は general の canonical 実体 ->
`extensions/persona/project-bootstrap` の tracked symlink ->
`~/bin/project-bootstrap` の install copy の順に流れる。
`./install.sh --check` で三段の同一性を確認できる。

## project-local prompt override

公開 repo の prompt は generic なまま保ち、個人環境だけ画風や構図を強めたい場合は、対象 project に以下を置く:

```
<repo>/.local/tproj-pane-bg/prompt.local.json
```

`.local/` は gitignore 済みなので公開 repo には入らない。ファイルは JSON として読むため、shell code は実行されない。

例:

```json
{
  "style_ref_en": "classic Japanese hand-drawn theatrical anime",
  "style_ref_jp": "日本の名作劇場アニメ",
  "style_author_jp": "名作劇場アニメ映画",
  "style_reference_fallback": "classic Japanese hand-drawn theatrical anime",
  "style_guard_jp": "手描きセル画の人物と柔らかな背景美術を保ち、汎用的な現代アニメ塗りや西洋ファンタジー調に寄せない。",
  "composition_extra_jp": "毎回同じ正面 bust にならないよう、手元、視線、肩の角度、小道具の置き方に自然な変化を入れる。",
  "negative_extra_jp": "強いネオン、フォトリアル、厚塗りコンセプトアート、汎用ソシャゲ風の顔立ちは避ける。"
}
```

この JSON の内容は prompt hash に含まれるため、変更すると既存 sidecar が stale になり、次回生成時に新 prompt として扱われる。sidecar には `prompt_override_path` と `prompt_override_fingerprint` が記録される。

## image-only override（`--prof`）

MEMORY.md を書き換えずに「画像だけ別職業に寄せたい」ケース用。

```
~/bin/tproj-pane-bg generate \
  --project <repo> \
  --role <role> \
  --prof <値> \
  --refresh
```

- `--prof` は persona_line の `prof:xxx` 部分だけを画像生成時に上書きする（`apply_prof_override` 関数で処理）
- MEMORY.md は触らない。生成後は `--prof` 無しで再生成すれば元に戻る
- sidecar JSON の `persona_line` に override 後の値が入る
- 永続化したい場合は MEMORY.md の `CC/Cdx Persona` テーブルの prof 行を手編集する（ただし外部同期で管理されているプロジェクトでは revert されるので注意、後述）

### prof の case 定義（重要）

`persona_prof_costume_prompt_jp` に case があると衣装プロンプトが強くなる。未定義の prof 値は default fallback（`*)`）に落ちて「その職業らしい衣装アイテム」程度の弱い指示しか出ない。鍛冶師など元の persona の case が強い場合でも、apply_prof_override が PERSONA_PROF を上書きするので干渉はしないが、**未定義 prof は default fallback 経由なので楽器や小道具 specific な描画が保証されない**。

定義済みの prof（一部）:

- 巫女 / 薬師 / ナース / メイド / 歌姫 / バーチャルアイドル / 占い師 / 花魁 / 女騎士 / 魔女 / 剣士 / 学者 / 航海士 / 鍛冶師 / 僧侶 / 諜報員 / 料理人 / 楽師 / 商人 / 錬金術師 / 踊り子

新規職業を使いたい場合は以下 2 択:

1. **既存 case から近いものを選ぶ**（例: バイオリン系なら `楽師`「楽器を携える衣装、音楽家らしい繊細さ」。ただし楽器不特定）
2. **新 case を追加する**（CC 側の `persona_prof_costume_prompt_jp` に分岐を足す）。以下テンプレ:

```bash
"ヴァイオリニスト") printf 'ヴァイオリンと弓を自然に携える佇まい、クラシカルな演奏家らしい端正な衣装、シャツやベストなど弦楽器奏者らしい上品さ。本来の手描きセル画タッチと落ち着いた色調はそのまま保つ' ;;
```

## プロンプト 3 層構造

画像プロンプトは `build_flash_named_prompt` / `build_flash_fallback_prompt` で組み立てる。手順 3 で衣装が決まる:

```
3. $(role_costume_prompt_jp "$role")。$(persona_prof_costume_prompt_jp)
```

`role_costume_prompt_jp` は内部で `era → master → chara → prof` の 4 要素を連結する:

```
$(persona_era_costume_prompt_jp)
。$(persona_master_costume_prompt_jp)
。$(persona_chara_costume_prompt_jp)
。$(persona_prof_costume_prompt_jp)
```

そのあと更に step 3 で `persona_prof_costume_prompt_jp` が独立して再呼び出しされるため、**prof 指示は 2 回入る**（強調）。このため強い prof case を書くと衣装が prof に寄る。

## ハマりポイント（全部 2026-04-17 のやらかしから）

### 1. sidecar だけで完了判定しない（visual verify 必須）

`--prof` 実行後、sidecar の `persona_line` に `prof:xxx` が反映されていても、**実際の画像がその職業になっているとは限らない**。理由:

- apply_prof_override は sidecar には反映されるが、build_flash_* への配線が抜けていると実プロンプト経路に届かない（2026-04-17 の tproj.cdx 実装で配線抜けがあり、CC が後追い修正）
- default fallback の弱い指示だと楽器や小道具 specific な描画が出ない（bust-up 構図で楽器がフレーム外になる等）

**運用ルール**: 生成後は Read tool で `<repo>/.local/tproj-pane-bg/<role>.vertical.png` を開いて目視確認してから「完了」と報告する。sidecar / MD5 変更だけでは不十分。

### 2. house style キーワードを衣装 case で打ち消さない

衣装 case に「サイバー / ネオン / ホログラム / ステージ」等の強スタイル要素を入れると、Gemini が衣装指示に引き寄せられて画像全体が強ネオンのアニメ調になり、設定した house style のやわらかさが消える。

style は変数で制御される（`STYLE_REF_EN` / `STYLE_REF_JP` / `STYLE_AUTHOR_JP`）。公開デフォルトは generic な手描き劇場アニメ調で、`~/.config/tproj/pane-bg.local` で特定の house style に override できる。プロンプト本文はこれらの変数を参照するので、衣装 case 側では style の固有名詞をハードコードしない。

**style を保つために衣装 case で守ること**:
- 手描きセル画タッチ
- やわらかな自然光
- 落ち着いた色調
- 主役級の顔立ち（劇場アニメ映画の主役級キャラクターに男女とも寄せる）

新 case 追加時は衣装文中に「本来の手描きセル画タッチと落ち着いた色調はそのまま保つ」相当の抑え文を必ず入れる。musician 系（アイドル / 歌姫 / シンガー）は `build_negative_prompt` にも「過度なネオン演出禁止」「サイバーパンク禁止」「メタリック CGI 光沢禁止」を条件追加する。

### 3. 外部同期プロジェクトではローカル書換が revert されることがある

リモートマシン、社内同期、launchd/cron などで workspace が自動同期されている場合、ローカルの `~/.claude/projects/.../memory/MEMORY.md` の `<!-- CC-PERSONA-START -->` sentinel 内を手動書換しても revert されることがある。その場合、persona 変更依頼にはまず `--prof` による image-only override で応える。

永続変更が必要なら、そのプロジェクトの source of truth 側を編集するか、該当プロジェクトの担当 AI に依頼する。

### 4. 他プロジェクトで MEMORY.md 書換はしない

一時的な職業変更依頼では、persona 変更ではなく **画像だけ override** を優先する。MEMORY.md に手を入れると sync 機構や persona データとの齟齬が出ることがある。画像 override が足りなければ tracked AGENTS.md の public-safe な user-owned section に override instruction を追加する、あるいは `--prof` 用の case を tproj-pane-bg 側で拡張する、のどちらかで対応する。

## 完了判定チェックリスト

生成タスクを「完了」と言う前に以下 4 点すべて satisfy:

1. コマンド実行が exit 0 で終わった
2. `<repo>/.local/tproj-pane-bg/<role>.vertical.png` のタイムスタンプが更新されている
3. sidecar JSON の `persona_line` が意図した値になっている
4. **Read tool で実画像を視覚確認**して、衣装・職業・構図が要件を満たしている

4 のスキップが最大のやらかしパターン。楽器持ち職業なら楽器が写っているか、和装要件なら和装か、を必ず目視する。

## 関連ファイル

- 本体スクリプト: `extensions/persona/tproj-pane-bg`
- `apply_prof_override`（prof override の本体）
- `persona_prof_costume_prompt_jp`（職業ごとの衣装 case）
- `role_costume_prompt_jp`（era/master/chara/prof を連結）
- `build_flash_named_prompt` / `build_flash_fallback_prompt`（プロンプト本文）
- `build_negative_prompt`（ネガティブプロンプト）
- 他 persona helper: `extensions/persona/project-bootstrap`

> 関数の行番号は実装変更で動くため、本書では関数名のみで参照する（grep で位置を引く）。

## Cdx が最初に読む節

Cdx が pane 背景の依頼を受けたら、以下の順で読む:

1. **基本的な呼び出し** — どのコマンドで動くか
2. **image-only override** — `--prof` で MEMORY.md に触らず画像だけ変える定石
3. **prof の case 定義** — 使いたい prof が case 済か確認、未定義なら CC に追加依頼
4. **ハマりポイント 1（visual verify）** — sidecar だけで完了判定しない
5. **完了判定チェックリスト** — 4 点すべてクリアしてから完了報告
