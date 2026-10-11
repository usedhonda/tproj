# Formal task guard hook

`tproj-formal-task-guard` is an optional PreToolUse/PostToolUse admission hook.
It reuses `tproj-mutation-guard`'s shell classifier and never invents a local
mutation whitelist. Read-only tools, read-only shell commands, and exact
`tproj-msg`/`tproj-task` lifecycle commands pass without contacting the host.

The native conversation marker is progress-ledger/recovery state, not a
conversation-wide permission overlay. Ordinary later user work is never
silently attributed to the historical task and remains fail-open even when a
ledger host is unavailable. Caller-supplied flags, task text, pane tags, and
tool IDs are not admission provenance. New operation admission is therefore
not performed by this hook; only exact historical callbacks are checked.

Retired-operation lookup remains independent of current assignment: an exact
retired callback is fenced from the local authenticated journal even after its
marker is released. If that journal cannot be read while a local native marker
proves legacy history, only the affected callback is denied with a diagnostic;
unrelated local work remains available.

The installer registers the guard for all mutating tool matchers on both
Claude and Codex. It does not activate hooks or alter an existing process.

Failure completion is platform-specific. Claude registers `PostToolUseFailure`
with the same tool identity to inspect the exact historical callback. Codex registers
`PostToolUse` only: its documented Bash path emits that event for nonzero exits
as well. Unsupported failure events must not be added to Codex hook settings.
The installer includes the formal guard in required Codex trust metadata; copying
an executable or writing hooks.json without trusting the returned native hash is
not successful activation. Abrupt process loss without a completion event leaves
an open operation fenced; timeout is not proof of operation completion.

Primary Codex contract: https://learn.chatgpt.com/docs/hooks#posttooluse
Unified exec can emit PostToolUse from a later write_stdin completion; the original
tool_use_id, not the polling call's identity, owns that operation.

Native code-mode envelopes may report `exec`, not `functions.exec`; both names,
along with Bash and exec_command aliases, are matched. Lifecycle commands inside
code mode are exempt only for one `text(await tools.exec_command({...}));` call
whose argument is literal JSON with the documented benign execution fields.
Computed arguments, custom shells, appended JavaScript, and shell chains are not
lifecycle exemptions. This keeps diagnostic and recovery commands reachable without treating arbitrary
JavaScript containing a task command as read-only.
Installer migration removes only obsolete exact installer-owned single-command
matcher entries; grouped and customized hooks remain untouched.

The established mutation/pretool and completion/posttool entry points also invoke
the same formal evaluator. This covers tool paths whose hooks an already-running
session loaded before the dedicated formal hook registration was installed.
Dedicated and established callbacks share the original tool_use_id for retired
identity checks. They neither admit new operations nor close old ones implicitly.
Exact witnessed legacy completion remains available through reconcile-operation.
A legacy mutation denial remains independent of the task ledger.
This does not add matcher coverage to an old session: paths absent from its
loaded posttool matchers cannot be reported as having confirmed completion.
Never clear an open operation by timeout or by assuming a tool completed.
