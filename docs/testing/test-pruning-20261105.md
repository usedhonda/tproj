# Test pruning — 2026-11-05

## Scope and method

Baseline: `001b1a7`. Inventory: **124 owned executable test files / 22,875 lines**
(Python, shell and Swift), plus the CI workflow. No production code, installed
runtime, service, shared charter, or unadopted GUI design is changed.

This is a repository-wide inventory and redundancy review, not a new exhaustive
mutation campaign. Reuse the [October audit](test-audit.md) for the 77 byte-identical
files; inspect additions/changes in the other 47 (32 modified, 15 new), the current
suite call graph, assertion candidates and production seams relevant to deletion.
The [per-file disposition](test-pruning-20261105.tsv) records every file and its
post-pruning hash. Historical ledgers remain historical; their hashes are not
silently replaced with current ones.

Python AST screening found no identical complete test-method bodies. Similar
bodies and repeated assertions were candidates, not deletion evidence: checks
before/after retry, cancellation, revocation or restart often deliberately use
identical assertions on different state. Property getter/setter names are not
shadowed test methods. Source-string lint is distinguished from runtime proof.

## Implemented pruning

| Finding | Removed work | Guarantee retained / rationale |
| --- | --- | --- |
| P01 | Nested invocation of `test-runtime-compatibility.py` from the runtime-installer suite | The workflow already invokes the identical four-test suite directly in Unified core lifecycle. Both calls use the same standalone temporary fixtures; the nested call does not inspect the installer suite's HOME. Keep the dedicated CI invocation and all compatibility cases. |
| P02 | Four duplicate formal-guard methods | Three bound ordinary-work / caller-boolean / no-retired-history checks are already exercised by `test_ordinary_native_work_never_enters_task_rpc` with the same binding fixture, events and flags. Fold the fourth, retired-callback/offline case into the existing retired/fresh journal test, preserving both verdicts and explicitly asserting zero RPC calls. Keep corrupt-journal, native wire, stdin and lifecycle-parser boundaries. |
| P03 | Non-gating P3 registry probe and its unused fixture branch | It printed any verdict without an expected outcome and could not fail the suite. Keep P1/P2 producer identity and missing/matching/mismatched PID-start assertions. This removal is not a claim that legacy multi-window selection is covered. |
| P04 | Five whole-document substring checks in MSG skill lint | `visible`, `shell` and three isolated phrases do not establish their purported visibility/fallback/relay/resumption semantics. Their presence could pass in unrelated or contradictory prose. Keep the skill itself unchanged, surface/tool-name checks, exact-ID/ACK instruction checks and diagnostic vocabulary. No runtime permission check is removed. |
| P05 | Second identical `tproj-role --help` process in smoke | Check successful exit and main-side usage together using the first bounded invocation. No loss of exit/output coverage; the formerly unbounded duplicate is gone. |

Net executable-test reduction: **57 lines** (22,875 -> 22,818), four unittest
methods, one redundant four-method suite invocation per shell CI run, one
non-gating probe, five weak lint assertions and one duplicate help process.
These categories overlap in cost and must not be summed as an independent test
count. No time-saving percentage or coverage percentage is claimed.

## Deliberately retained

- **Native identity/recovery:** current versus historical actor, selected route
  versus old reply pin, same-native versus different-native restart, stale or
  ambiguous candidates, unknown one-shot reservations and grant revocation.
- **Federation:** initial slow preflight and pending-outbox retry are separate
  write-lock failure paths. Keep both despite their nearly identical wrappers.
- **Transport:** mocked frame/deadline tests and actual socket/SDK subprocess
  tests guard different layers. Keep durable acceptance versus lost response,
  exactly-once attempts, schema decoding and later local reconciliation.
- **Telegram/Muse/Dots:** ingress, poller, Host authorization and integrated bridge
  checks are not interchangeable. Group/private origin and revoked binding
  cases retain separate expected effects.
- **Remote lifecycle:** local Stop/drop/pane-close must preserve remote PID and
  independent reattachment. Mobile start idempotency and CLI ensure/resume have
  distinct lifecycles; keep both, plus source/bundle/staged drift checks.
- **Other shell/Swift tests:** configuration parsing, geometry, selection,
  installed-file preservation, hooks and legacy entrypoints retain independent
  boundaries. Small tests, mocks, source lint and non-CI tests are not deleted
  solely because of their size, style or execution location.
- Before/after assertions around the same submission are retained: for example,
  the two `remote_calls == ['resolve']` checks in deferred reconciliation have a
  worker invocation between them and protect against a replay.

## Verification and limits

At this checkpoint:

- Changed non-CI checks: formal guard **13 tests**, registry **4 assertions**,
  and MSG skill lint passed.
- Workflow shell commands: **17/17 groups exited 0**, executed once. The
  compatibility suite ran only through its dedicated workflow entry.
- Smoke: **33 passed, 0 failed, 1 degraded**. The existing bounded `zsh -n`
  check of `tproj-pane-focus-hook` timed out; its syntax is **not verified** by
  this run. No alternate-parser success is substituted.
- Legacy caller-verifier nested-tmux live observation remains skipped (`cvh14`);
  the existing inner-pane spoof assertion (`cvh09`) still runs. No live nested
  tmux coverage is claimed.
- Dedicated pinned MCP SDK 2.3.0 subprocess fault suite: **2/2 passed**;
  dependency-free discovery skips those cases as designed.
- All 124 inventory entries and post-change hashes match; `git diff --check`
  and Intent Drift Check passed.

These are test/source results, not production acceptance. Swift sources/tests
are unchanged; the already-green PR #23 native gate was not repeated and the GUI
was not rebuilt or restarted for this test-only change.

Tests and documentation are not installed artifacts. No runtime installation,
restart, delivery probe, message replay or push is required or performed.
