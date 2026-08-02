# Handoff Note Format

A handoff note lets any agent (Claude Code or Codex, any role) resume work
without the previous agent's conversation history or memory. Notes are
task-scoped and temporary: keep them out of version control (e.g.
`.local/handoff/<task-id>.md`) and delete them when the task closes.

## Template

```
# Handoff: <one-line task title>
Task-Id: <tproj-msg task id if any>
From / To: <alias.role> -> <alias.role or "anyone">
Date: <YYYY-MM-DD>

## Goal and scope
<objective, in/out of scope, completion criteria>

## Current state
<done work; changed files; branch/commit ids>

## Verified results
<commands run and their actual results>

## Decisions
<key choices made and rejected alternatives, with reasons>

## Open items and risks
<unresolved questions, known risks>

## Next steps
<ordered, concrete>
```

## Rules

- Record verifiable facts, decisions, and state - never internal reasoning
  or conversation excerpts.
- Reference identifiers (commits, task ids, file paths) rather than pasting
  large content.
- The receiving agent re-verifies "Verified results" before building on them.
