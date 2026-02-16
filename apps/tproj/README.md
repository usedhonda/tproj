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
