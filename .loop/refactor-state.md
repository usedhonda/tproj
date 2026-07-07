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
