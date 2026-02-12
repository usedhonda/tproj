# Codex MCP 自動起動無効化

- 指示内容:
  - インストール済みのMCPは保持したまま、Codex起動時に初期自動起動しないように全体設定したい。

- 実施内容:
  - `codex mcp get chrome-ai-bridge` で現在値を確認（enabled=true）。
  - `~/.codex/config.toml` の `[mcp_servers.chrome-ai-bridge]` に `enabled = false` を追加。
  - 反映確認:
    - `codex mcp get chrome-ai-bridge` -> `chrome-ai-bridge (disabled)`
    - `codex mcp list` -> Status が `disabled`

- 課題、検討事項:
  - 使うときは `enabled=true` に戻す必要がある。
  - MCP本体（chrome-ai-bridge）はアンインストールしていないため、設定だけで再有効化可能。
