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

`with_codex_update_prefix`, the remote-host launcher, and the GUI-generated
local launcher use the wrapper for the complete Codex lifetime, with a
command-availability fallback so an absent helper does not prevent startup.
The guarantee applies only to launches that use one of these wrappers.
Unmanaged `codex` processes still require adoption of the same protocol before
they can claim this race-free behavior.

## Codex's built-in startup updater

On a host where tproj centrally manages Codex updates, set the native user
configuration `check_for_update_on_startup = false` in `~/.codex/config.toml`.
Otherwise Codex can offer its own npm update after the managed launcher starts,
bypassing these locks and exiting with a request to restart. That independent
package replacement can also disrupt other sessions using the shared install.
The setting disables only Codex's startup update check; tproj's serialized update
path remains enabled. Do not disable model, authentication, or permission checks.
Existing running clients are not restarted by changing this setting.

Reference: [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference).
