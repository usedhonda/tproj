# Loop state — pane-bg 画風レシピの二層分離

## Budget
iteration cap 6 / no-progress streak 2

## Done
(まだ無し)

## Failed / blocked
(まだ無し)

## Next step
tproj/.local/tproj-pane-bg/prompt.local.json を読み、provider 非依存の技術 baseline
（style_guard_jp と写実回避の否定語群）と、tproj 固有の persona/composition 記述を
仕分ける。前者だけを tracked script の組み込み既定値の候補として書き出す。

## Iteration 1 (2026-08-20)
実施:
- tracked script に provider 技術 baseline を追加（PANE_BG_GPT_IMAGE_STYLE_GUARD_JP /
  PANE_BG_GPT_IMAGE_NEGATIVE_JP）。apply_provider_style_defaults が「空のスロットだけ」を埋める。
- 二層の優先順位を tracked baseline < ~/.config house < project prompt.local.json に確定。
- build_negative_prompt の呼び出しを model 決定後へ移動（前だと技術 negative が落ちる）。
- style_baseline スタンプを sidecar に追加し、cache_is_fresh は「スタンプのある sidecar だけ」
  baseline を再適用する。これが無いと既存 4 プロジェクトの hash が変わり、全部再生成された。
- 観測点として style-layers サブコマンドを追加（画像生成なしで層を検査できる）。
- tests/test-pane-bg-style-layers.sh を追加（7件）。AGENTS.md のテスト一覧にも追記。

結果:
- 反復ゲート緑。最終ゲートも1回だけ実行し緑（smoke-bin 21 / style-layers 7 /
  install-check-persona 9 / install.sh --check = no drift）。
- 既存 7 プロジェクト 28 ファイルの shasum が実装前後で完全一致（再生成ゼロ）。
- 実装を revert すると style-layers テスト 3 件が落ちることを確認。

仮定（ループ規約に従い質問せず記録）:
- ~/.config の style_ref_en="Studio Ghibli" は house 層なので gpt-image でも残る。
  技術 baseline がセル画技法を明示することで写実化を打ち消す設計。
  実際の絵で確かめるには画像生成が要り、それは Explicitly Out。次に誰かが --refresh した
  ときに目視確認すること。

## Next step
（SUCCESS CRITERIA は全て達成。commit 済み。残るは御大の判断で push のみ）
