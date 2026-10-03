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
