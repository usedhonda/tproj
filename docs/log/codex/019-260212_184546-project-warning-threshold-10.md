# 019 project warning threshold 10

## 指示内容
- ワークスペースのプロジェクト数警告閾値を 5 ではなく 10 まで許容するよう変更。

## 実施内容
- `bin/tproj` のプロジェクト数警告条件を変更:
  - `if [[ ${#PROJECT_PATHS[@]} -gt 5 ]]; then`
  - -> `if [[ ${#PROJECT_PATHS[@]} -gt 10 ]]; then`
- コメントも整合:
  - `# プロジェクト数警告（10超）`
- 構文チェック:
  - `zsh -n bin/tproj`
  - `bash -n bin/tproj`
- 実行実体へ反映:
  - `/Users/usedhonda/bin/tproj` にコピーし同一性確認。

## 課題、検討事項
- 10 を超える構成では横幅がかなり狭くなるため、将来は自動レイアウト最適化やページングの検討余地あり。
