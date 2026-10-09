# Managed Codex launch/update lock

`bin/tproj-cli-update` coordinates two host-local locks for Codex:

- The existing update lock serializes npm updates and signing commands.
- A separate per-user launch lock is held shared for the complete lifetime of
  a managed Codex command. The launch wrapper is `tproj-cli-update --launch
  '<shell command>'`.

The Codex updater takes the launch lock exclusively while it checks process
state and performs the update. If a participating launch already holds the
shared lock, the updater exits successfully without touching the installed
package. A launch started while an update is active waits for the exclusive
lock, then runs with the same shell command, terminal, arguments, and exit
status semantics.

`with_codex_update_prefix` uses the wrapper for both updating and
`--no-update` launches, with a command-availability fallback so an absent
helper does not prevent startup. The guarantee applies only to launches that
use this wrapper. Unmanaged `codex` processes, and the separately implemented
remote-host launcher, still require adoption of the same protocol before they
can claim this race-free behavior.
