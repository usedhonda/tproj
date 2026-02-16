<!-- CDX-PERSONA-AGENTS -->
**Read `.codex/config.toml` in this directory and adopt the persona in its `instructions` field.**
<!-- CDX-PERSONA-AGENTS-END -->

## GUI アプリ (TprojApp) ビルド・起動ルール

- **開発中は常に開発版のみ使用する。配布版 (`tproj-gui`, `~/bin/tproj-gui`) は起動しない**
- `swift build` 後の再起動手順:
  1. `pkill -f 'tproj-gui'` — 配布版が動いていたら止める
  2. `pkill -f '.build/arm64-apple-macosx/debug/tproj'` — 旧開発版を止める
  3. `./apps/tproj/.build/arm64-apple-macosx/debug/tproj &` — 開発版のみ起動
- **2重起動厳禁**: 必ず全プロセスを kill してから1つだけ起動すること
