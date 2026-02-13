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

## 依存

- `tmux`
- `tproj` コマンド
- `yq` (workspace.yaml 読み込み)
