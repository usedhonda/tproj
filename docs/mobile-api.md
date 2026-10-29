# Canonical mobile pair API

`mobile-capabilities` is read-only and reports API version 1. The mobile app may
call `mobile-ensure --path ABSOLUTE --operation UUID --fresh --no-update` only on
an explicit user start action. `mobile-operation --operation UUID` reads the
record and public registered PID/start-time bindings; it never starts a CLI.

The transaction uses a realpath-keyed Python fcntl lock and a durable operation
record. It invokes canonical ensure with fresh/no-update flags; it does not copy
session names, tag schemas, or registration into another application. Codex still
uses the existing launch guard without running an update. Normal ensure/attach
sees the same canonical sessions and cannot create an invisible second pair.

Existing running work returns `existing` without creating a missing partner.
Dead or occupied sessions return those explicit states. Mobile never kills,
respawns, moves or migrates those sessions. Partial results retain successful
roles and can be inspected without replaying the transaction. A different path
cannot reuse an operation ID. `bindings_pending` is not a pair-ready claim, and
`bindings_verified` is not proof that a real peer message was delivered.

Registration uses the normal remote catalog. Existing host login/ensure-all
restore behavior is deliberately unchanged: after a host restart, normal restore
uses its existing resume/update policy. Fresh/no-update applies only to the
explicit mobile transaction, not all later host activity.

For a narrowly scoped helper update, `bin/install-remote-mobile-api --host HOST
--expected-sha SHA` checks the current artifact without writing. Add `--apply`
to save the old helper and atomically replace only that file after bash syntax
and hash checks. It does not install skills, change launchd, restart agents or
update CLIs. An unexpected existing hash stops the update. The regular broad
remote setup command remains unchanged.

Focused evidence: existing `tests/test-remote-host.sh` and
`tests/test-remote-reattach.sh`, plus isolated fake-agent
`python3 tests/test-remote-mobile.py`. Never point that fixture at a live server.
