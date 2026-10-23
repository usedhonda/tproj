# Test audit remediation — 2026-10-23

The [2026-10-22 audit](test-audit.md) and its hash/position ledgers are historical
snapshots, not a claim that the modified files still have those hashes/counts.
This checkpoint implements the accepted F01–F17 recommendations. It does not
turn source, lint, mock, or isolated runtime evidence into production acceptance.

| Finding | Implemented correction | Remaining guarantee boundary |
| --- | --- | --- |
| F01 | Consolidate seven obsolete RPC-failure/forward/close cases into an event/input matrix that explicitly asserts no RPC; name pretool marker behavior accurately | Exact retired callbacks, journal corruption and native hook wire checks retained |
| F02 | Replace constant-set tautology with actual target/submission request assertions | Other service binding assertions retained; `target` remains a valid send field |
| F03 | Execute the exact expression consumed by GUI save, extracted from its production literal; verify its use in the yq call | Not the entire GUI save lifecycle; real workspace lock checks retained |
| F04 | Execute the production `generate_task_id` function with the four collision-prone inputs, only GC stubbed | Existing resolution/owner/DB migration checks retained |
| F05 | Label MSG wording checks as document lint | Not authentication, delivery or receipt coverage |
| F06 | Run real reload with isolated HOME and inert service/SSH tools; inspect actual tar entry set independent of order | Not remote extraction, service activation or loaded generation |
| F07 | Assert saved reply recipient equals original sender and linkage equals original ID | Not just `queued` state |
| F08 | Name the existing sequential full/fast test accurately | No claim of simultaneous-writer coverage; no unnecessary concurrency gate added |
| F09 | Require hook exit success separately from non-block decision; isolate the legacy CLI rejection fixture HOME | Crashes cannot count as successful non-block replies |
| F10 | Isolate HOME/enrollment from the first cross-Mac test invocation | Deliberately legacy transport boundary, not unified native E2E |
| F11 | Rename pre-call tracked-path replacement to match the actual symlink rejection scenario | Not a TOCTOU reproduction |
| F12 | Rename list adapter test as Host-projection preservation | Host owns filtering/authorization |
| F13 | Separate non-gating P3 from assertions; remove stale RED claims; update P1 to current registered/live PID-start contract and isolate legacy consumer HOME | Sibling router is a local dependency; no invented deterministic P3 assertion |
| F14 | Bound timeout-tool fallback with Python process-group cleanup; report zsh timeout as degraded, never bash-parser PASS | Degraded output is explicitly not zsh syntax proof |
| F15 | Label image-detail literal checks as regression lint | Not generated API request coverage |
| F16 | Preserve attach exit status under `set -e`; assert SSH for the non-opted-in host | Existing direct shell exit checks retained |
| F17 | Label wrapper match as a partial diagnostic and require the intentional independent drift failure | Not whole-host no-drift success |

No test suite or useful contract was wholesale deleted. Focused checks and the
required workflow gates are recorded separately in the local execution report.
