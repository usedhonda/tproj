# tproj `TPROJ_*` environment variables

Reference of `TPROJ_*` environment variables read by `bin/` and
`extensions/messaging/` (plus the `extensions/hooks/` gate). Generated for Debt
**B-D8**. Each row lists the variable, the primary read site (`file:line`), its
default when unset, and a one-line meaning.

Two kinds are listed: **inputs** (read with a `${VAR:-default}` fallback, meant
to be set by the user/environment) and **tmux inter-process vars** (set via
`tmux set-environment` by one process and read by another; not user-facing
tunables).

## Messaging (`extensions/messaging/`)

| Variable | Read at | Default | Meaning |
|---|---|---|---|
| `TPROJ_MSG_QUEUE_DIR` | `tproj-msg:511` | `/tmp/tproj-msg-queue` | Per-target send queue directory. |
| `TPROJ_MSG_CONTROL_DEDUP_DIR` | `tproj-msg:515` | `/tmp/tproj-msg-control-dedup` | Control-message dedup store (B-D M-D4 fallback). |
| `TPROJ_MSG_FANOUT_DEDUP_DIR` | `tproj-msg:518` | `/tmp/tproj-msg-fanout-dedup` | Fan-out dedup store (M-D4 fallback). |
| `TPROJ_MSG_GATE_DEDUP_DIR` | `tproj-msg:2240` | `/tmp/tproj-msg-gate-dedup` | Gate cross-adapter dedup store (M-D4 fallback). |
| `TPROJ_MSG_CHI_DISPATCH_LEDGER` | `tproj-msg:521` | `$HOME/.cache/tproj-msg/chi-dispatch.tsv` | Ledger of Chi/gate dispatches for rate control. |
| `TPROJ_MSG_CHI_DISPATCH_TTL_SEC` | `tproj-msg:522` | `86400` | TTL (seconds) for the Chi dispatch ledger entries. |
| `TPROJ_MSG_POLICY_DRY_RUN` | `tproj-msg:523` | `false` | When `true`, evaluate send policy without sending. |
| `TPROJ_TYPING_GUARD_STABLE_DRAFT_MIN_CHARS` | `tproj-msg:529` | `4` | Min draft chars before the typing guard treats a draft as stable. |
| `TPROJ_GATE_SESSION_TARGET` | `tproj-msg:2083` | (empty) | Override the resolved gate/session target. |
| `TPROJ_MSG_REEXECED` | `tproj-msg:146` | (unset) | Internal guard: set to `1` after re-exec to `~/bin` copy to prevent loops. |
| `TPROJ_MSG_DB_PATH` | `tproj-msg-db.sh:18`, `tproj-inbox-monitor:22` | `$HOME/.local/share/tproj-msg/messages.db` | SQLite shadow-write DB path. |
| `TPROJ_MSG_DB_ERROR_LOG` | `tproj-msg-db.sh:19` | `$HOME/.cache/tproj-msg/db-errors.log` | DB error log path. |
| `TPROJ_MSG_DB_INIT_FLAG` | `tproj-msg-db.sh:20` | `$HOME/.cache/tproj-msg/db-init.stamp` | DB init stamp file. |
| `TPROJ_MONITOR_ALIAS` | `tproj-inbox-monitor:24` | tmux `@alias` (else `unknown`) | This pane's alias for inbox monitoring. |
| `TPROJ_MONITOR_ROLE` | `tproj-inbox-monitor:25` | `cc` | This pane's role for inbox monitoring. |
| `TPROJ_MONITOR_POLL_SEC` | `tproj-inbox-monitor:28` | `5` | Inbox DB poll interval (seconds). |
| `TPROJ_MONITOR_RETRY_SEC` | `tproj-inbox-monitor:29` | `60` | Retry sleep when sqlite/DB is unavailable (seconds). |
| `TPROJ_MONITOR_DEBOUNCE_SEC` | `tproj-inbox-monitor:30` | `30` | Min interval between emitted digest notices (seconds). |
| `TPROJ_MONITOR_MAX_PARTS` | `tproj-inbox-monitor:31` | `5` | Max sender parts listed in a digest notice. |
| `TPROJ_HOOK_ENABLED` | `hooks/tproj-inbox-check:4`, `hooks/tproj-inbox-record:4` | (unset) | Hooks no-op unless set to `1`. |

## Layout / panes (`bin/`)

| Variable | Read at | Default | Meaning |
|---|---|---|---|
| `TPROJ_RUNTIME_ROOT` | `tproj:8,23` | resolved from script path | Root of the running tproj checkout (bin/ + config/). |
| `TPROJ_STATE_DIR` | `tproj-pane-autozoom:30`, `tproj-mru-tracker:7`, `tproj-tmux-state-notify:4` | `$HOME/.config/tproj` | Runtime state/flag directory. |
| `TPROJ_WORKSPACE_YAML` | `tproj-mru-tracker:6` | `$HOME/.config/tproj/workspace.yaml` | Workspace definition file. |
| `TPROJ_LOCK_TIMEOUT` | `tproj:506` | `10` | Layout lock acquire timeout (seconds). |
| `TPROJ_LAYOUT_LOCKFILE` | `tproj:502,507` | `/tmp/tproj-layout.lock` | Layout lock file path. |
| `TPROJ_LABEL_HOOK` | `tproj:398,739` | (empty) | Optional persona/label hook command. |
| `TPROJ_AFTER_LAYOUT_HOOK` | `tproj:657` | (empty) | Optional command run after layout changes. |
| `TPROJ_GUI_APP_PATH` | `tproj:584,1226` | (empty) | Override path to the GUI app binary. |
| `TPROJ_AUTOZOOM_ACTIVE_SHARES` | `tproj-pane-autozoom:32` | `2` | Width shares of the active column vs each other column. |
| `TPROJ_AUTOZOOM_W_MAX` (alias `_W_MIN`) | `tproj-pane-autozoom:33` | `120` | Upper bound (cols) on active pane width. |
| `TPROJ_AUTOZOOM_H_MIN` (alias `_H_MAX`) | `tproj-pane-autozoom:34` | `40` | Minimum active pane height (rows). |
| `TPROJ_AUTOZOOM_DEBUG` | `tproj-pane-autozoom:38,43` | `0` | When `1`, write `/tmp/tproj-pane-autozoom.log`. |

## tmux inter-process vars (set-environment; not user tunables)

| Variable | Set at | Read at | Meaning |
|---|---|---|---|
| `TPROJ_IDLE_PREV1/2/3` | `tproj-pane-clear-rank:35-37`, `tproj-pane-focus-hook:79-80` | focus/border logic | MRU focus stack of pane ids. |
| `TPROJ_PREV1/2/3_BORDER_FG` | `tproj:1360-1362` | tmux border formatting | Border colors for previously-focused panes. |
| `TPROJ_AUTOFOCUS_PENDING` | `tproj-pane-focus-hook:31` (unset) | `tproj-pane-focus-hook:28` | Marks a pending programmatic focus to suppress re-entrancy. |
| `TPROJ_STOPPING` | `tproj:863,901` | `tproj-pane-watchdog:23` | Signals session teardown so watchers stand down. |
| `TPROJ_LAYOUT_LOCK_HELD` | `tproj:503,512,534` | `tproj:532` | Internal shell flag: this process holds the layout lock. |
| `TPROJ_GUI_PIDFILE` | `tproj:573` | GUI launch logic | Pidfile path for the GUI process (derived from `TMPDIR`). |

Legacy note: `TPROJ_PANE_*` is a retired variable prefix (see comment at
`tproj-pane-focus-hook:77`); superseded by the `TPROJ_IDLE_*` vars above.
