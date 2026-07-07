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
