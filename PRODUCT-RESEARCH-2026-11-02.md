# Product research: less coordination work across agents and Macs

Research date: 2026-11-02 (America/New_York; retrieval continued into 2026-11-03 UTC).
Repository baseline: `85c78830bea3303370f32503ce2816ab560fa654`.
Status: research and proposed implementation plan, not shipped functionality.

## 1. Recommendation

Position tproj as a way to keep existing, heterogeneous coding sessions working together across machines without making the person act as their message courier. Do not position it simply as multiple agents in terminal panes: competing products already address parallel work, review, notifications, and remote operation.

The first improvement should be a small, trustworthy **attention view** over the existing task authority: what needs a decision, what is ready to review, what has stopped, and where to return. Follow it with a readable continuation/result packet. Both should reduce repeated explanations and navigation, not introduce another workflow engine or more mandatory approvals.

This recommendation is a product hypothesis grounded in the source and official competitor documentation below. No user interviews, comparative usability sessions, live host inspection, or performance benchmark were conducted. Source capability is not proof that a particular installation is running it.

## 2. Current baseline: reuse, do not rebuild

| Observed evidence | Already present | Implication |
| --- | --- | --- |
| [README at baseline](https://github.com/usedhonda/tproj/blob/85c78830bea3303370f32503ce2816ab560fa654/README.md) | Claude Code/Codex workspaces, GUI, messaging, local/remote topology, persistent remote sessions and restoration; optional features must not block the core CLI. | Remote sessions and multi-agent messaging are not missing features. Preserve terminal-first operation. |
| [Task CLI](https://github.com/usedhonda/tproj/blob/85c78830bea3303370f32503ce2816ab560fa654/extensions/messaging/unified/task_cli.py) | Authenticated task submission, status/list, progress, done, verification/reporting, handoff, binding inspection and `resume --check`. | Build a presentation layer over these operations, not a second task database. |
| [Task authority, especially its schema and dispatch](https://github.com/usedhonda/tproj/blob/85c78830bea3303370f32503ce2816ab560fa654/extensions/messaging/unified/tasks.py) | Durable tasks/events, owner and executor identities, incarnation/epoch checks, idempotency, explicit visibility checks; `done`, `verified` and `reported` are separate states. | The display must not turn a completed agent turn into verified delivery. Do not bypass visibility to aggregate tasks. |
| [Messaging source/test inventory](https://github.com/usedhonda/tproj/tree/85c78830bea3303370f32503ce2816ab560fa654/extensions/messaging) | Native notices, queues, publication, external adapters, reconciliation and resumption tests already exist. | Discover the relevant current adapter before adding a watcher or retry mechanism. File presence alone does not establish end-to-end reliability. |
| [Repository operating instructions](https://github.com/usedhonda/tproj/blob/85c78830bea3303370f32503ce2816ab560fa654/AGENTS.md) | Optional fail-open behavior, protected shared contracts and focused verification practices. | Improve usability without modifying deployment ownership, shared symlinks or canonical contracts as a side effect. |

This was a targeted source read, not a complete GUI audit. A proposal described below as a gap is an end-to-end experience to validate, not a claim that no related view or helper exists anywhere in the repository.

Open issues [#14](https://github.com/usedhonda/tproj/issues/14) and [#18](https://github.com/usedhonda/tproj/issues/18) were also inspected. They track external-session connectivity and model maintenance respectively. This report neither closes them nor claims their runtime acceptance has been completed. The cross-repository open-PR search returned no open PRs at inspection time; recheck before implementing.

## 3. Competitive comparison

Official documentation was retrieved during this research. Feature availability can vary by version; these are documented capabilities, not independent product tests.

| Reference | Documented capability | Consequence for tproj |
| --- | --- | --- |
| [Conductor workflow](https://www.conductor.build/docs/concepts/workflow) | Workspaces organize shippable changes; branches/PRs organize integration. Its workflow includes multiple agent harnesses, diff review, checks, PR creation and archive/restore. | A session list alone is not enough. Link a unit of work to its reviewable result. Do not claim mixed harnesses alone are unique. |
| [cmux notifications](https://cmux.com/docs/notifications) | An unread notification can navigate directly to a workspace. Agent notification context distinguishes turn completion, permission needs and pending work. | Learn the short path from interruption to the exact place requiring attention. Avoid broadcasting every state transition. |
| [Claude Code agent teams](https://code.claude.com/docs/en/agent-teams) | Shared tasks and direct teammate messaging exist. The documentation labels teams experimental and describes coordination/resumption limitations and overhead. | Do not rebuild same-provider teamwork. Focus on the existing heterogeneous, cross-host boundary; do not add agents where sequential work is simpler. |
| [OpenAI's remote engineering guide](https://developers.openai.com/blog/mastering-codex-remote-for-engineering) | Remote host/workspace selection, worktrees, goals, queued versus steering prompts, and inline review are documented. | Remote control is not an uncontested differentiator. tproj should make its existing CLI ecosystem coherent rather than imitate an entire remote IDE. |

**Inference:** the most defensible near-term opportunity is reducing coordination cost in an existing mixed-agent, multi-machine setup. This research does not establish a unique market position or justify replacing the underlying harnesses.

## 4. Jobs to validate

1. **Return after an interruption.** A developer has several sessions across two Macs. They need to identify the one requiring a decision and return to the correct conversation without reading every terminal.
2. **Review a finished change.** An executor says it is done. The owner needs the actual branch/commit, tests and remaining limitations, not another generic status message.
3. **Continue existing work.** A session restarts or an executor changes. The approved scope and decisions should survive without duplicating the task or requiring the person to carry context manually.

Use fictional tasks for the first usability pass. Compare the current journey with the proposed one using the same tasks. Record navigation steps, repeated explanations and incorrect state interpretations. Five representative walkthroughs can guide prioritization but cannot establish population-level success rates.

## 5. Prioritized implementation slices

### P1-A: read-only attention view — first implementation

**Outcome:** answer “What needs me now?” without changing task state.

Render a compact projection of authorized existing tasks. Candidate fields are task ID, project/host, current executor, source status, observation time, attention reason, result reference and a link to the existing conversation. These are a proposed presentation model, not a new wire contract.

Suggested groups are decision required, ready for review, stopped/blocked, and unavailable/stale. Keep the actual lifecycle status visible. Silence alone is not evidence of a block. A fresh heartbeat is not proof of progress. A `done` task can be awaiting review rather than complete from the owner's perspective.

Start with a bounded CLI presentation; add a compact GUI surface only after the same read model works. Candidate seams are `extensions/messaging/unified/task_cli.py`, the authorized list/status paths in `tasks.py`, and the existing app/logic boundary under `apps/tproj/Sources/`. Exact UI placement must be checked against the current GUI before coding.

The hard dependency is identity: an existing conversation's task visibility must not silently become a machine-wide administrator view. Use an already authorized caller/host path. Where the GUI cannot obtain one, show that limitation instead of opening the mailbox database directly or manufacturing an identity.

**Acceptance:** opening/refreshing the view sends no messages, ACKs no inbox items, resumes nothing and writes no task transitions; unrelated tasks remain invisible; stale observations are labelled; the destination resolves by stable identity rather than pane focus; unavailable optional components do not prevent normal CLI work.

### P1-B: continuation and result packet

**Outcome:** preserve the useful working context without copying an entire transcript.

Present the existing task's objective, approved scope, current owner/executor, branch/commit where evidenced, accepted and rejected decisions, verification evidence, unresolved blockers and next action. Keep submitted evidence attributable to its producer. Missing fields remain unknown; do not infer passing tests or merge status from prose.

Use `resume --check` and existing handoff/reconciliation paths. Preview is read-only. An actual continuation still uses the current caller identity, epoch and authority. The packet itself grants no permissions. Preserve the existing distinction between source changes, installed runtime and observed execution.

Do not require a new approval for every message or test. Existing approved scope remains the boundary; only a genuinely new authorization requirement should interrupt the person. Do not automatically resend old work to make a dashboard appear active.

**Acceptance:** retrying the same submission does not create a second task; an old epoch cannot change the current task; execution completion without verification remains distinct; a restart preserves available evidence and does not invent lost in-flight input; handoff does not reset accepted decisions.

### P2: branch/PR-linked work units, then optional isolation

**Outcome:** make completed work easy to integrate.

First attach existing branch/commit/PR references to the work item and expose the review destination. A PR check result must be tied to the relevant head SHA; unavailable GitHub data stays unavailable rather than green.

Only then evaluate opt-in worktree creation for independently mergeable changes. Agents collaborating on one change may deliberately share a checkout. Do not force one worktree per agent, delete unknown worktrees, or replace the existing terminal workflow. Inventory current worktree support before proposing new machinery.

This is lower priority because it spans Git lifecycle, process ownership, remote paths and cleanup. It should not delay the small attention view.

## 6. Focused validation plan

The following are proposed acceptance cases, not test results from this research.

| Case | Required observation |
| --- | --- |
| Task is `done`, not `verified` | Review remains pending; no success claim based on an agent turn alone. |
| Remote host stops reporting | Last observation remains visible as stale/unknown; no synthetic progress or automatic restart. |
| Caller has no task visibility | Neither task content nor a direct database fallback is exposed. |
| Handoff advances the epoch | Old controls cannot act on the new owner/executor incarnation. |
| Identical submission follows a lost response | Existing task/idempotency behavior is preserved; no second task appears. |
| GUI/optional messaging component is unavailable | Core terminal startup and current documented fallbacks remain usable. |

Reuse relevant existing tests such as `test-unified-task-cli.py`, `test-task-resume.py`, `test-task-reconcile.py` and `test-task-binding-release.py` after reading their fixtures. Add only a test covering a newly introduced failure. Run focused checks for the slice; run broader integration checks once when the changed boundary requires them, not repeatedly to fill time.

## 7. Handoff for the first implementation PR

Implement **P1-A only** initially. Before editing, inventory current CLI/GUI status views and identify the authenticated read seam. Reuse an existing equivalent view when present instead of duplicating it. Limit the patch to the read projection, its presentation, focused tests and usage documentation. Do not add a daemon, new task authority, forced migration, model change or deployment step.

Evaluate whether a returning user can identify the required action and open the correct conversation within two navigation actions from the attention view. This is a proposed usability target, not a measured result. Also count false completion labels and unintended state-changing calls; the acceptance target is zero in the defined fixtures.

Stop this slice when the read-only journey is demonstrated. Do not extend it into worktree automation or approval redesign. This research PR changes documentation only; it does not claim a build, test-suite run, live message delivery or deployment verification.
