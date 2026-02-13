# 指示内容
- アプリ名の `tproj-native` をやめて、`tproj` に統一する。
- 継続して `.app` として使える状態にする。

# 実施内容
- ディレクトリを `apps/tproj-native` から `apps/tproj` にリネーム。
- `apps/tproj/Package.swift` を更新し、パッケージ名/実行ファイル名/ターゲット名を `tproj`, `TprojApp` に変更。
- ソースディレクトリを `apps/tproj/Sources/TprojApp` に変更し、`@main` 構造体名を `TprojApp` に変更。
- `.app` 生成スクリプト `apps/tproj/build-app.sh` を更新し、生成物名を `dist/tproj.app` に変更。
- `apps/tproj/README.md` の実行手順をすべて `tproj` 名に更新。
- ビルド確認:
  - `cd apps/tproj && swift package clean && swift build` 成功
  - `cd apps/tproj && ./build-app.sh` 成功（`apps/tproj/dist/tproj.app` 生成）

# 課題、検討事項
- `apps/tproj-app` (Electron) は残存しているため、不要なら削除方針を決める必要がある。
- `.app` は ad-hoc 署名でローカル実行想定。配布用の署名/Notarization は未対応。
