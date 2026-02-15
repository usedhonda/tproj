# 指示内容
- 「２つともおとして。元からあった方をちゃんとビルドし直して。」

# 実施内容
- 実行中の `tproj` を2系統とも停止。
  - `apps/tproj/dist/tproj.app/Contents/MacOS/tproj`
  - `apps/tproj/.build/arm64-apple-macosx/debug/tproj`
- 停止後、対象プロセス0件を確認。
- 元から存在していた `debug` 側を再ビルド。
  - 実行コマンド: `swift build` (`apps/tproj`)
  - 結果: Build complete (debug)

# 課題、検討事項
- いまは両方停止状態。必要なら `debug` のみ起動、または `dist` のみ起動に統一して運用する。
