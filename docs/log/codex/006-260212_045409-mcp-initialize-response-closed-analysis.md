# MCP initialize response closed 調査

- 指示内容:
  - 起動時エラー `MCP client for chrome-ai-bridge failed to start ... connection closed: initialize response` の原因調査

- 実施内容:
  - ユーザー提示エラー文言を確認。
  - `~/.codex/config.toml` を確認し、現行は `mcp_servers.chrome-ai-bridge` (stdio) 構成であることを確認。
  - `~/.codex/log/codex-tui.log` を確認し、通常時は `chrome-ai-bridge ... Available tools ...` まで起動しているログが多数あることを確認。
  - `chrome-ai-bridge` 実装を確認:
    - `scripts/cli.mjs` は `stdio: 'inherit'` で `build/src/main.js` を起動。
    - `src/main.ts` は `await server.connect(new StdioServerTransport())` 前に `killSiblings()` と `acquireLock()` を実行。
    - `src/process-lock.ts` は sibling を SIGTERM/SIGKILL する実装、および lock 取得失敗時に throw で終了する実装。
  - `--help` 実行で `browser-globals-mock` のメッセージは stderr 側に出ており、stdout 汚染ではないことを確認。

- 課題、検討事項:
  - 最有力原因（高）:
    - **起動レースでサーバープロセスが initialize 応答前に終了している**。
    - 特に `killSiblings()` が他の `chrome-ai-bridge` を積極的に kill するため、複数 Codex セッション/ペイン同時起動で相互に落とし合う可能性がある。
    - その結果としてクライアント側では `connection closed: initialize response` になる説明と整合。
  - 補助原因（中）:
    - `acquireLock()` 失敗 throw（lock競合）でも initialize 前終了が起こり得る。
  - 可能性が低いもの:
    - stdout 汚染（今回の確認では stderr出力）。
  - 観測事実:
    - 同じ環境でも成功ログが多数あるため、恒常的破損ではなく **間欠的レース** の性質。
