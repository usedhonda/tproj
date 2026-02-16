# 指示内容
- 「やれるところまでやっちゃいましょう。」
- 他プロジェクトを参考に Developer ID 情報を流用し、可能な範囲を進める。

# 実施内容
- 既存の配布実装に対し、`apps/tproj/scripts/release.sh` に `--skip-notarize` オプションを追加（資格情報未設定でも署名DMG生成可能化）。
- `cc-status-bar` 側の情報を参照し、`apps/tproj/.local/release.md` を作成（ローカルのみ、gitignore対象）。
- `apps/tproj/scripts/release.sh` を通常モードで実行し、フル工程を完了:
  1. app build
  2. app sign (Developer ID)
  3. CLI payload 同梱
  4. DMG create/sign
  5. notarytool submit (Accepted)
  6. stapler staple/validate
  7. spctl assess accepted
- 生成物:
  - `apps/tproj/dist/release/tproj.dmg`
- 検証結果:
  - `source=Notarized Developer ID`
- ビルドルールに従い、`dist/tproj.app` の起動確認を実施（プロセス確認済み）。

# 課題、検討事項
- 現在 `.local/release.md` はローカルに作成済み。共有は不要だが、認証情報管理ポリシー（定期ローテーションなど）は別途運用で管理する。
- 今回は公開（GitHub release作成）までは実施していない。
