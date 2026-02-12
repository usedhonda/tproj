# MCP 起動時エラー再調査

- 指示内容:
  - 「mcpがこけている。起動時にエラーが出ていた」という申告の再調査。

- 実施内容:
  - `~/.codex/history.jsonl` の起動時エラー履歴を確認。
  - `~/.codex/config.toml` の現行 MCP 設定を確認。
  - `~/.codex/log/codex-tui.log` の直近ログを確認。

- 課題、検討事項:
  - 申告どおり、過去に起動時エラーは発生していた。
    - 例: `MCP client for chrome-ai-bridge-chatgpt/gemini failed to start`
    - 内容: `handshaking with MCP server failed` / `initialize response` / `Send message error`（HTTP 127.0.0.1:8765/8766）
  - ただし現行の `~/.codex/config.toml` は、HTTP の2サーバー構成ではなく、`mcp_servers.chrome-ai-bridge` の stdio 構成（`command=node` + `scripts/cli.mjs`）に変わっている。
  - 直近の `codex-tui.log` では、MCP 側は `chrome-ai-bridge ... Available tools ...` まで起動しており、同系統のハンドシェイク失敗は確認できなかった。
  - 補足:
    - `list_mcp_resources` が空なのは「MCPが死んでいる」ことの直接証拠ではない（resources APIを提供していないMCPでも起こる）。
    - このセッションでは `list_mcp_resources` / `list_mcp_resource_templates` はエラーなく応答済み。
