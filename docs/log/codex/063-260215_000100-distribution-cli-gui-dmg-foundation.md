# 指示内容
- cc-status-bar を参考に、tproj も配布可能にするための実装。
- tproj CLI も含めたセット配布前提。
- install.sh では yazi プラグインの個別確認はやらない。
- workspace YAML テンプレートから usedhonda 固有値を削除する。

# 実施内容
- 配布基盤を追加。
  - `apps/tproj/scripts/release.sh` 追加
    - GUIビルド
    - app署名
    - CLI payload 同梱
    - DMG生成/署名
    - notarize/staple/verify
  - `scripts/package-cli-payload.sh` 追加
    - `install.sh`, `bin/`, `config/`, `README.md` を tar.gz 化
  - `apps/tproj/scripts/README-QuickStart.txt` 追加
  - `docs/release/tproj-release.md` 追加
  - `apps/tproj/.local/release.example.md` 追加（秘密情報テンプレ）
- `apps/tproj/.gitignore` 更新
  - `.local/release.md` を除外
- `install.sh` 更新
  - `ya pack -i` 失敗時は警告表示して継続（best-effort）
  - プラグイン個別確認ロジックは追加せず
- `config/workspace.yaml.example` 更新
  - `/Users/usedhonda/...` を `/Users/<username>/...` に置換
- `apps/tproj/README.md` 更新
  - DMG生成セクションを追加

# 課題、検討事項
- release.sh 実行には実際の Apple 署名情報（SIGNING_ID/NOTARY_PROFILE 等）が必要。
- 現時点では配布スクリプト追加まで。実際の notarize 成功確認は認証情報投入後に行う。
