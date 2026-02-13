# 指示内容
- Swiftアプリで「何がリモートで何がエイリアスか分かりにくい」を改善する。
- もっと縦長で細いウィンドウ向けに、無駄を省いたデザインへ調整する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` のUIを再設計。
- ラベルの明確化:
  - `Live Columns` で `LOCAL/REMOTE` バッジ表示。
  - 各行で `Alias: ...` を明示。
  - Workspace編集で `Project Path`, `Connection`, `Alias (tproj --add で使う名前)`, `Remote Host` を明示。
- レイアウト最適化:
  - 横並び要素を減らして1カラム中心へ整理。
  - ヘッダ情報を簡素化。
  - ウィンドウサイズを細幅向けに変更（min 420 / ideal 460 / max 560）。
- 検証:
  - `apps/tproj/build-app.sh` で再ビルド成功。
  - `open .../dist/tproj.app` で起動。
  - 既存プロセスを再起動し、新プロセス PID 93619 で起動確認。

# 課題、検討事項
- エイリアス推定は `workspace.path` との一致を優先し、未一致時は `projectName` をフォールバックとして表示。
- 視覚面の最終判断は実機UI確認（配色・余白・可読性）で微調整可能。
