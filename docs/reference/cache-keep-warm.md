# Prompt Cache Keep-Warm (CC and Cdx)

The tproj GUI can keep each column's agent prompt cache warm so the next turn
reuses cached context instead of rebuilding it. Claude Code (CC) and Codex
(Cdx) work differently, so each has its own data source, rule and setting,
but both show the same row shape and menu.

## Why

- **CC**: the Anthropic prompt cache expires one hour after it was written.
  The next turn after expiry rewrites the whole context at full price, which
  is large for long sessions. One short turn just before expiry resets the
  hour for a small fraction of that price.
- **Cdx**: OpenAI caches prompts automatically but publishes no expiry. With
  a ChatGPT subscription, turns count against usage limits rather than being
  billed per token. Warming Cdx is therefore a best-effort guess at an
  interval, not a countdown.

## What the GUI shows

Each column shows one cache line: `CC <left> · <setting>` and
`Cdx <left> · <setting>`.

| Text | Meaning |
|---|---|
| `53m · 3h` | Cache is warm, 53 minutes left; keep-warm is on for 3h |
| `53m · 3h?` | CC only: expiry known, but the last prompt time is unknown, so the keep-warm window cannot be judged |
| `cold · Off` | Cache is gone or assumed gone; keep-warm is off |
| `Done · 3h` | More than 3h have passed since your last message, so warming stopped |
| `Awaiting · 3h` | CC only: no expiry is known for this session yet |
| `busy` / `stalled` | Cdx only: a turn is running, or a turn was cut off (no end event for 10+ minutes) |
| `--` | No session found for this pane |

Colors: green means warm, yellow means less than 10 minutes left or the last
poke failed, grey means off or not applicable.

Each menu has the same two controls:

- **Keep warm**: Off / 1h / 3h / 6h / 12h. This is the window after your
  last message during which automatic pokes are allowed.
- **Poke now**: send one keep-alive turn immediately. It is disabled when
  sending is not safe.

Hovering over the line shows details: expiry, last prompt, last poke and
result, or the reason Poke is off.

## Settings

The settings are per project in `~/.config/tproj/workspace.yaml`. The GUI
menus write them.

```yaml
projects:
  - path: ~/projects/example
    keep_warm_hours: 3        # CC:  0 (absent) = Off, or 1 / 3 / 6 / 12
    cdx_keep_warm_hours: 1    # Cdx: same values, independent of CC
```

## The keep-alive turn

Both agents receive the same fixed text:

```
[keep-alive] Reply with just "ok". Do nothing else.
```

Arbitrary text is never sent. A keep-alive turn does not count as your last
message, so pokes cannot extend the keep-warm window by themselves.

## CC (Claude Code)

**Data.** The GUI polls every 30 seconds. It combines two sources:

1. **CCStatusBar API** (`GET http://127.0.0.1:<port>/api/cache`; the port
   comes from CCStatusBar's `keepwarm.json`). Per session it reports
   `cache_expires_at`, `last_user_prompt_at`, `pokeable` and `tty`.
2. **tproj's own observer** (`tproj-cc-cache-observer`). It is fed by Claude
   hooks (prompt, stop, notification) and by the status line through
   `tproj-cc-statusline-tap`. It writes one JSON file per session under
   `~/.local/state/tproj/cc-cache/`.

CCStatusBar owns `tty` and `pokeable`. A time CCStatusBar lacks is filled
from the local observer. CCStatusBar can miss the last prompt of a session
it started watching late.

**Auto poke.** Sent when all of these hold:

- the column's `keep_warm_hours` is on
- the expiry is 0 to 90 seconds away
- your last prompt was within the chosen hours
- CCStatusBar says `pokeable`

The poke goes through `POST /api/poke {"tty"}`. CCStatusBar decides whether
it is safe (no permission prompt, question, running tool or non-empty
composer) and holds the dedup lock. A `skipped` answer is normal and is not
retried. The CCStatusBar menu-bar keep-warm must stay **Off**, so only
tproj's per-column setting acts.

**Poke now.** Runs `tproj-cc-poke` for the exact observed session and pane,
which fails closed if it cannot confirm the pane is idle.

## Cdx (Codex)

**Data.** `tproj-codex-cache-state list`, run by the GUI every 30 seconds,
reads each Codex pane's own session log under `~/.codex/sessions/`:

- **Binding.** The pane's `@project` is matched to the newest interactive
  root session log with the same `cwd`. Newest means by file modification
  time, because a resumed session keeps writing to the log of the day it
  was first created.
  - Interactive root means `source: cli`, originator `codex-tui` (older builds:
    `codex_cli_rs`), and a user thread.
  - Subagent and `codex exec` logs are excluded.
- **Turn state.** The last `task_started` / `task_complete` event gives
  `working` or `idle`.
- **Quiet time.** The log's age since its last write.
- **Last human message.** The last user message that is not injected
  context (text starting with `<`) and not a keep-alive turn.
- **Cache hit.** The last `token_count` sample (cached / input tokens). It
  appears in the menu as "Last turn cached".

**Time left.** Counted against a fixed 30-minute quiet interval, because
Codex publishes no expiry.

**Auto poke.** Sent when all of these hold:

- the column's `cdx_keep_warm_hours` is on
- the turn is `idle`
- the log has been quiet for 30 minutes or more
- your last message was within the chosen hours

**Poke now / send.** `tproj-codex-cache-state poke <pane>` re-checks at send
time and refuses with a reason unless all of these hold:

- the turn is `idle`
- the log has been quiet for 20 seconds or more
- `tproj-msg --status` resolves the pane to `idle` or `suggestion`

The raw `@prompt_state` pane option is not used, because it can stay
`typing` long after the composer is empty. The text is then typed into the
pane with tmux.

## Known limits

- The Cdx interval (30 minutes) is a guess. The "Last turn cached" value
  after a poke shows whether the cache survived. If it comes back low, the
  interval is too long.
- Warming runs only while the tproj GUI is running.
- A Codex turn cut off with Esc never logs `task_complete`. It stays
  `stalled` and is never poked until a new turn completes.
- Remote (non-local) columns are not warmed.

## Files

| File | Role |
|---|---|
| `apps/tproj/Sources/TprojLogic/KeepWarm.swift` | Decision rules (`KeepWarmDecision`, `CodexPaneCacheState.shouldAutoPoke`) |
| `apps/tproj/Sources/TprojApp/TprojApp.swift` | 30s loop, rows, menus, settings I/O |
| `extensions/hooks/tproj-codex-cache-state` | Codex state reader and guarded sender |
| `extensions/hooks/tproj-cc-cache-observer` | Local CC cache observer |
| `extensions/hooks/tproj-cc-statusline-tap` | Feeds status line input to the observer |
| `extensions/hooks/tproj-cc-poke` | Guarded manual CC sender |
| `apps/tproj/Tests/TprojLogicTests/KeepWarmTests.swift` | Rule tests |
