# 指示内容
- 全体的に無駄が多いので、上部（現在の状態）と下部（YAML編集）を明確に分離し、特に上部のスペースを削減する。
- 追加で「ウィンドウサイズが合っていない」問題を修正する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` を再構成。
  - 上部を `Current` カード1枚に統合（`Refresh` / `Alias Picker` / `Add` / `Live列`）。
  - 下部を `Workspace YAML` カードに分離。
  - 旧ヘッダ（タイトル・パス表示）を削除して上部の無駄を削減。
  - `Card` に `compact` モードを追加して余白・フォントを圧縮。
  - `ActionButton` に `dense` モードを追加してボタン密度を上げた。
  - Live行を2行構成から実質1行半へ圧縮（path詳細表示を省略）。
- サイズ挙動の不一致対策。
  - ウィンドウサイズを固定寄りに変更。
  - `frame(min/ideal/max)` を同値化（幅360・高さ920）。
  - `.windowResizability(.contentSize)` へ変更。
  - `.defaultSize(width: 360, height: 920)` に統一。
- 検証。
  - `apps/tproj/build-app.sh` でビルド成功。
  - 既存プロセス停止後に再起動し、PID 1465 で起動確認。

# 課題、検討事項
- 上部情報をさらに削る場合は、`statusText` を短文化または非表示にする選択肢がある。
- 固定サイズは運用上の自由度が低いため、必要なら後で `contentMinSize` に戻せる。
