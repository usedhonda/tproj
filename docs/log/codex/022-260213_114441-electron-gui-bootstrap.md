# 022 electron gui bootstrap

## 指示内容
- `tproj` をCLIだけでなくMacアプリ（GUI）化し、プロジェクト列の追加/削除、保存を操作できるようにする。
- UIは縦長・ダーク・ターミナル系デザイン。

## 実施内容
- `apps/tproj-app` を新規作成し、Electron + React(Vite) 構成を追加。
  - `apps/tproj-app/package.json`
  - `apps/tproj-app/vite.config.js`
  - `apps/tproj-app/index.html`
  - `apps/tproj-app/electron/main.js`
  - `apps/tproj-app/electron/preload.js`
  - `apps/tproj-app/src/main.jsx`
  - `apps/tproj-app/src/App.jsx`
  - `apps/tproj-app/src/styles.css`
- Electron IPC API を実装:
  - `workspace:list` : tmux から列状態を取得
  - `workspace:add` : `tproj --add [alias]` 実行
  - `workspace:remove` : 指定 `@column` の pane を削除 + 再配分
  - `workspace:save` : 現在列から `~/.config/tproj/workspace.yaml` を再生成
- UI実装（縦長ダーク）:
  - 列カード一覧（local/remote バッジ、pane id、幅、agent数）
  - Add Column（alias選択 + 現在列複製）
  - Remove Project（確認ダイアログ）
  - Save Workspace（明示保存）
- 依存導入とビルド確認:
  - `npm install`
  - `npm run build` 成功
  - `npx electron --version` 確認

## 課題、検討事項
- Electron本体起動テスト（`npm run dev`）は対話GUI前提のため、この作業ログでは非実施。
- 今後の改善候補:
  - 列削除後の `@column` 再採番
  - 追加時の alias/path 入力UI（新規パス直接追加）
  - Rust/Tauri への移行（希望時）
