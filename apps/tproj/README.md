# tproj (SwiftUI)

`tproj` workspace を GUI で操作する macOS ネイティブアプリです。

## 開発実行

```bash
cd apps/tproj
swift run tproj
```

## .app 生成

```bash
cd apps/tproj
./build-app.sh
open dist/tproj.app
```

生成先: `apps/tproj/dist/tproj.app`

## 配布用 DMG 生成

```bash
cd apps/tproj
./scripts/release.sh
```

生成先: `apps/tproj/dist/release/tproj.dmg`

事前に `apps/tproj/.local/release.md` を作成し、署名と notarization 情報を設定してください。

## 依存

- `tmux`
- `tproj` コマンド
- `yq` (workspace.yaml 読み込み)
- `tproj-mem-json` (メモリ/ペイン監視の統合JSON)

## 監視データ共有

GUIアプリは定期的に監視情報を取得し、以下へ書き出します:

- `/tmp/tproj-monitor-status.json`

他の tmux ペインの CC / Codex はこの JSON を読むことで、同じ監視状態を参照できます。
