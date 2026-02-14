---
name: msg
description: |
  tproj-msg internal reference. AI-to-AI communication tool for
  inter-pane messaging in tproj workspace environments.
metadata:
  short-description: AI-to-AI inter-pane communication reference
---

# tproj-msg リファレンス（内部ツール）

Codex が他の AI ペイン（CC, Cdx, Agent）と通信するための内部ツール。

## コマンド

```bash
# 送信（応答待ち）
~/bin/tproj-msg <target> "message"

# 送りっぱなし（タスク委任向き）
~/bin/tproj-msg --fire <target> "message"

# アクティブなターゲット一覧
~/bin/tproj-msg --list

# ターゲットの最新出力を読取
~/bin/tproj-msg --read <target> [lines]
```

## ターゲット書式

| 書式 | 意味 | 例 |
|------|------|-----|
| `cc`, `cdx` | 同列 / 単一モード | `~/bin/tproj-msg cc "question"` |
| `<alias>.cc` | 特定列の Claude Code | `~/bin/tproj-msg tproj.cc "help"` |
| `<alias>.cdx` | 特定列の Codex | `~/bin/tproj-msg sl.cdx "review"` |
| `<alias>` | エイリアスのみ（cc にデフォルト） | `~/bin/tproj-msg sl "question"` |
| `agent-<name>` | Agent ペイン | `~/bin/tproj-msg agent-reviewer "check"` |

## 使用方針

- 通信前に `~/bin/tproj-msg --list` でターゲット一覧を確認
- メッセージは背景・文脈を含めて構築（生のユーザー入力を転送しない）
- 質問・相談: デフォルトモード（応答待ち）
- タスク委任: `--fire` モード
