# tproj refactor — state record

Contract: `refactor-instructions.md` (§9). This file records the Phase 0 baseline
(§6 Baseline Commands) so later phases can compare against it and detect regression.

## Phase 0 baseline — 2026-07-07 15:25 JST

| Baseline command | Result |
|---|---|
| `git status -s` | clean except untracked `refactor-instructions.md` (the contract itself) — no pre-existing code changes |
| `bash extensions/messaging/tests/test-sendability-gate.sh` | **PASS=13 FAIL=0 PENDING=0** (green) |
| `bash extensions/hooks/tests/test-inbox-check.sh` | **3 passed, 0 failed** (green) |
| `cd apps/tproj && ./dev-app.sh` | **Build complete + launched** (debug, pid 83570, rc 0) |
| repo↔~/bin drift (`diff bin/* ~/bin/*`) | **zero DRIFT** — repo == ~/bin |

Verdict: **baseline clean (not poisoned)**. Phase 1 authorized to proceed.

## Phase 1 — safety net (tests only, no implementation change) — 2026-07-07

Added, all hermetic (fake tmux/websocat/curl shims on PATH), no `tproj-msg` body edits:

- `extensions/messaging/tests/test-sendability-gate.sh`: appended relay/fanout/broadcast
  guard cases 14-21 after existing case 7. Existing cases 1-13 untouched (byte-for-byte).
  - relay body (`[from:]` / `[Control:]` / `[ACK:]`) blocked on normal send (exit 13)
  - `--allow-relay <reason> --force` lets a relay body through (sendkeys logged)
  - broadcast target (`all` / `broadcast`) forbidden (exit 14)
  - same message to a second same-family target blocked as fan-out (exit 15)
  - `--allow-fanout <reason>` overrides the fan-out block (sendkeys logged)
- `tests/smoke-bin.sh` (new): shebang-aware syntax check (`zsh -n` for zsh scripts,
  `bash -n` for bash scripts) of every `bin/*` file + harmless representative execs
  (`tproj-pane-autozoom --status`, `--help`). No tmux-state-changing commands run.

### Note on fan-out test isolation

`FANOUT_DEDUP_DIR` is hardcoded to `/tmp/tproj-msg-fanout-dedup` (env override is Debt
M-D4, deferred to Phase 2). The fan-out cases therefore drive the real `/tmp` dedup
store. Each run uses a unique nonce message so it never collides with real traffic and
its two entries expire via the 600s TTL. This is an honest Phase 1 limitation, not a
harness defect; it tightens once M-D4 lands.

### Post-Phase-1 baseline re-run

| Baseline command | Result |
|---|---|
| `bash extensions/messaging/tests/test-sendability-gate.sh` | **PASS=21 FAIL=0 PENDING=0** (13 existing + 8 added) |
| `bash tests/smoke-bin.sh` | **green** (all bin/* syntax-clean) |
| `bash extensions/hooks/tests/test-inbox-check.sh` | **3 passed, 0 failed** |
| repo↔~/bin drift | zero (no bin/* or tproj-msg body changed) |

Test count monotonic increase (13 → 21); no regression.

## Phase 2 — obviously-safe cleanup (behavior-preserving, 1 commit = 1 item) — 2026-07-07

All 7 §9 Phase 2 items landed, one commit each. Deploys used `cp` (messaging/bin)
and `dev-app.sh` (Swift); `install.sh` main path never run (tmux live).

| # | Debt | Commit | What changed |
|---|---|---|---|
| 1 | M-D2 | `67bcc79` | Removed 4 dead `unknown_prompt` case branches (SEND_BLOCK_REASON never set to it) + slot comment. Behavior unchanged. |
| 2 | M-D4 | `6969732` | Added `TPROJ_MSG_{CONTROL,FANOUT,GATE}_DEDUP_DIR` env fallbacks (`${VAR:-default}`, /tmp defaults unchanged). |
| 3 | B-D6 | `1baa685` | Gated autozoom entry-log append behind `TPROJ_AUTOZOOM_DEBUG=1` (same gate as dlog). |
| 4 | B-D8 | `502d258` | New `docs/reference/env-vars.md` enumerating TPROJ_* vars (force-added; dir is gitignored). |
| 5 | B-D9 | `844dc4a` | `install.sh --check` drift detector (CORE_BINS hoisted as single source of truth; copy/launchctl path byte-identical). |
| 6 | S-D2 | `7465ffb` | `enum TmuxTargets` for `tproj-workspace` / `:dev`; replaced all 17 tmux-target literals (values unchanged; UI prose left as-is). |
| 7 | S-D7 | `225798d` | Moved Card/SectionHeader/ActionButtonTone/ActionButtonStyle/ActionButton verbatim to `CommonViews.swift` (all internal; no modifier change). |

### Post-Phase-2 baseline re-run (compare vs Phase 0 / Phase 1)

| Baseline command | Phase 0 | Post-Phase-2 |
|---|---|---|
| `git status -s` | clean | **clean** (all committed) |
| `test-sendability-gate.sh` | PASS=13 | **PASS=21 FAIL=0 PENDING=0** |
| `test-inbox-check.sh` | 3 passed | **3 passed, 0 failed** |
| `tests/smoke-bin.sh` | (Phase 1) green | **PASS=18 FAIL=0** |
| `dev-app.sh` | build+launch rc0 | **Build complete + launched** (S-D7 build) |
| repo↔~/bin drift | zero | **zero** (loop + `install.sh --check`: no drift, 16/16) |

Regression: **none**. Test counts unchanged (no tests added/removed in Phase 2);
all previously-green baselines remain green.

## Phase 3 — approved deletions + logic separation — 2026-07-07

All 4 §9 Phase 3 items landed. Swift deploys via `dev-app.sh`; bin/ via `cp` to
~/bin (install.sh main path never run — tmux live).

| # | Debt | Commit(s) | What changed |
|---|---|---|---|
| 1 | B-D1 | `bdda1e1` | `git rm bin/tproj-pane-watchdog` (inert dead code: never launched, needs bash4 declare -A on a bash3.2 host). Removed from install.sh CORE_BINS + added to the legacy-cleanup loop (deletes stale ~/bin copies). Removed the 2 orphaned pkill sites; reworded every watchdog-crediting comment to name tproj-respawn-guard + the pane-died hook. `grep -rn watchdog bin/ install.sh` now shows only the intended legacy-cleanup line. |
| 2 | S-D4 | `991be4a` | Deleted the retired MIDI pad-slot path: MIDIBinding / StoredMIDIBinding / MIDILearnStore, MIDIPaneActivator bindings lookup + onSlotTriggered, AppViewModel onSlotTriggered wiring + activatePaneForMIDISlot. MIDIBinding had no jog users so it went too. 76 deletions / 0 additions / **no jog lines in the diff**. Stale `tproj.midi.learn.bindings.v1` UserDefaults value left as harmless residue (no removeObject, per contract). |
| 3a | S-D3 | `329c846` | New `Sources/TprojLogic` library target (TprojApp depends on it). Moved GhosttyTheme (public) + GhosttyConfigParser (internal; parseHex relaxed private->internal for @testable) + Color.brighten verbatim. GhosttyWindowInfo + window tracker stay. TprojApp + CommonViews `import TprojLogic`. |
| 3b | S-D3 | `ec5a288` | Extracted `JogQuantizer.feed(data2:now:)` (pure) from handleJog; activator refreshes ticksPerStep/minStepInterval before each feed. Algorithm byte-identical; `now` injected for tests. |
| 3c | S-D3 | `4342601` | Extracted `jogCycleOrder(panes:)` (contract signature) + companion `nextPaneInCycle(order:active:direction:)` from focusPaneByJog; the func is now a thin tmux wrapper. Same role filter / left sort / modulo wrap / order[0] fallback. |
| 3d | S-D3 | `a14d38a` | Moved shellSingleQuote / shellDoubleQuote / yamlQuote to TprojLogic as pure public free funcs (call sites resolve unchanged). renderWorkspaceYAML stayed (coupled to WorkspaceProject model — out of scope per "無理はしない"). |
| 4 | tests | `9f07bb2` | New `Tests/TprojLogicTests` (13 tests, green): JogQuantizer, jogCycleOrder + nextPaneInCycle, GhosttyConfigParser.parseHex. `swift test` added to Baseline. |

### Post-Phase-3 baseline re-run (compare vs Phase 0 / Phase 2)

| Baseline command | Phase 0 | Post-Phase-3 |
|---|---|---|
| `git status -s` | clean | **clean** (all committed) |
| `test-sendability-gate.sh` | PASS=13 | **PASS=21 FAIL=0 PENDING=0** |
| `test-inbox-check.sh` | 3 passed | **3 passed, 0 failed** |
| `tests/smoke-bin.sh` | (P1) green | **PASS=17 FAIL=0** (16->15 bin files: watchdog removed) |
| `dev-app.sh` | build+launch rc0 | **Build complete + launched** rc0 |
| `swift test` | (new) | **13 passed, 0 failures** |
| repo↔~/bin drift | zero | **zero** (watchdog gone from repo AND ~/bin) |

Regression: **none**. Test counts monotonic up (gate 21 held; smoke 18->17 tracks
the intentional watchdog deletion, not a lost test; +13 new swift tests). Jog diff
across S-D4 + S-D3: zero jog-function lines removed/altered — extractions are
call-through only. **Physical jog hardware confirmation is pending user** (agent
verified code-level: build green + tests green + zero jog diff).

## Phase 4 — boundary clarification (B-D2 / B-D3/D4/D5 / M-D1) — 2026-07-07

All 3 §9 Phase 4 items landed. bin/ deployed via `cp` to ~/bin; tproj-msg via `cp`;
Swift untouched (no dev-app rebuild needed for correctness, but run for baseline).

| # | Debt | Commit(s) | What changed |
|---|---|---|---|
| 1 | B-D2 | `a7dad6b` | drop-column passes `TPROJ_LAYOUT_LOCK_INHERITED=1` to its rebalance call (reentrancy prep; no-op until rebalance reads it). |
| 1 | B-D2 | `80cf01c` | rebalance: 4-pass resize burst wrapped in `tproj-layout` tmux lock, trap-guaranteed `-U`, honors the inherited guard. |
| 1 | B-D2 | `4714602` | autozoom: resize group (width loop + vertical grow) wrapped in the same lock; idempotent per-column skips kept INSIDE (SIGWINCH discipline intact). |
| 1 | B-D2 | `178254a` | tproj add_workspace_column: **dual-lock** = existing PID lock (kept for GUI coord — see note) + tmux `tproj-layout` lock; rebalance sub-call env-guarded. |
| 2 | B-D3 | `6d5c16a` | Shared `collect_descendant_pids` (positional-param BFS, bash/zsh-safe, leak-free) replaces tproj / drop-column / kill-pane inline copies. |
| 2 | B-D3 | `944d466` | respawn-guard reaps FULL descendant tree (was 2-level) — behavior change, own commit. |
| 2 | B-D4 | `2ec2a67` | Shared `exit_cmd_for_role` (3 sites) + `graceful_signal_for_role` (drop-column). tproj graceful block left inline (terminal-p* divergence). |
| 2 | B-D5 | `c18ecee` | Shared `avail_mem_mb` / `phys_mem_mb` across respawn-guard / mem-trace / postmortem. |
| lib | scaffold | `fd4c98a` | New `bin/lib/tproj-common.sh` + install.sh distribution (`~/bin/lib/`) + `--check`/`--dry-run` coverage. |
| 3 | M-D1 | `6419272` | raw_send checks both send-keys exit codes; on failure no "Sent to", DB delivery_error (not delivered), non-zero return; callers mark+exit0 on success only. Regression test case 22 (fake tmux send-keys exit 1). |

### Deadlock self-review (B-D2)

Empirically verified in throwaway tmux servers (isolated socket):
- Non-background `run-shell` hooks BLOCK the triggering command (deadlock risk if a
  lock holder triggers a hook that takes the same lock).
- BUT: `split-window`, `select-window`, `select-pane -T` (title-only), and
  `select-pane` on the already-active pane do NOT fire `after-select-pane`; killing
  a pane (even the active one) does NOT fire it either. Tracing add_workspace_column
  and drop-column, **neither fires the autozoom hook** during its locked
  transaction, so there is no hook-reentry deadlock.
- Only real nesting: direct child `rebalance` calls from lock holders
  (drop-column:348, add:1117) — solved by `TPROJ_LAYOUT_LOCK_INHERITED=1` (inherited
  by the child process; rebalance skips re-acquiring the non-reentrant lock).
- Concurrent reproduction test (scratchpad): 3-column fixture, rebalance standalone
  (no hang), drop-column holding the lock + calling rebalance internally
  (`rebalance=1`, completes ~1.2s, no self-deadlock), a lock holder + concurrent
  rebalance (blocked ~1.5s then ran), structure intact — all < 5s.

### Note — GUI PID lock (B-D2 analysis gap)

The B-D2 debt map framed `/tmp/tproj-layout.lock` as tproj-only, but the Swift GUI
(`TprojApp.acquireLayoutLockAsync`) uses the same PID file and relies on its
timeout + stale-detection, which tmux `wait-for` cannot provide. So tproj's PID
lock was **kept** (removing it would drop GUI↔add-column mutual exclusion) and the
tmux lock **added alongside** (dual-lock), bridging the two lock domains that
previously could not coordinate. Deadlock-free: add-column is the only multi-lock
holder; no tmux holder wants the PID lock and the GUI never wants the tmux lock.

### Post-Phase-4 baseline re-run (compare vs Phase 0 / Phase 3)

| Baseline command | Phase 0 | Post-Phase-4 |
|---|---|---|
| `git status -s` | clean | **clean** (all committed) |
| `test-sendability-gate.sh` | PASS=13 | **PASS=22 FAIL=0 PENDING=0** (+1 M-D1 case) |
| `test-inbox-check.sh` | 3 passed | **3 passed, 0 failed** |
| `tests/smoke-bin.sh` | (P1) green | **PASS=17 FAIL=0** |
| `swift test` | (P3) 13 | **13 passed, 0 failures** |
| `dev-app.sh` | build+launch rc0 | **Build complete + launched** (pid 15335) |
| repo↔~/bin drift | zero | **zero** (bin + lib + tproj-msg, `install.sh --check` clean) |

Regression: **none**. Test counts monotonic up (gate 21→22). Behavior changes are
scoped to §7-approved (B-D2 dual-lock, M-D1) plus the explicitly-committed
respawn-guard full-tree change. **Physical layout/focus hardware confirmation is
pending user** (agent verified: no deadlock via reproduction tests, focus path
unchanged — autozoom lock held only during resize execution).
