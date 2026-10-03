# Formal task guard hook

`tproj-formal-task-guard` is an optional PreToolUse/PostToolUse admission hook.
It reuses `tproj-mutation-guard`'s shell classifier and never invents a local
mutation whitelist. Read-only tools, read-only shell commands, and exact
`tproj-msg`/`tproj-task` lifecycle commands pass without contacting the host.

For a formal assignment it sends the native conversation context and exact
`tool_use_id` to the authenticated host's `task_guard_begin` and
`task_guard_end` operations. Missing IDs, host failure, stale incarnation or
epoch, and unknown operation completion deny the operation; an unassigned
conversation remains fail-open because formal tasks are optional.

The installer registers the guard for all mutating tool matchers on both
Claude and Codex. It does not activate hooks or alter an existing process.

Failure completion is platform-specific. Claude registers `PostToolUseFailure`
with the same tool identity to close the admitted operation. Codex registers
`PostToolUse` only: its documented Bash path emits that event for nonzero exits
as well. Unsupported failure events must not be added to Codex hook settings.
The installer includes the formal guard in required Codex trust metadata; copying
an executable or writing hooks.json without trusting the returned native hash is
not successful activation. Abrupt process loss without a completion event leaves
an open operation fenced; timeout is not proof of operation completion.

Primary Codex contract: https://learn.chatgpt.com/docs/hooks#posttooluse
Unified exec can emit PostToolUse from a later write_stdin completion; the original
tool_use_id, not the polling call's identity, owns that operation.
