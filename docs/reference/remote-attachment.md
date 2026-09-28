# Remote attachment terminal lifecycle

`tproj-remote-client attach HOST ABS_PATH cc|cdx` attaches SSH to an existing
persistent remote agent pane. The local client supervises SSH until it exits;
it does not reconnect, restart the remote agent, or replace its session.
Other client actions retain their noninteractive SSH behavior.

Before attachment, the supervisor snapshots the controlling terminal settings
through `/dev/tty`. After SSH exits, including disconnect and forwarded
`SIGHUP`, `SIGINT`, or `SIGTERM`, it disables mouse tracking and encodings,
focus reporting, bracketed paste, kitty keyboard reporting, xterm modified
keys, and application cursor/keypad modes. It then restores the saved terminal
settings and flushes queued input before returning to the local shell. Mouse
reports queued during a disconnect must not become shell commands.

SSH inherits the terminal input/output unchanged while attached. Its normal
exit status is preserved; signal termination is represented as `128 + signal`.
The supervisor forwards termination signals and waits for SSH before cleanup.
When there is no controlling terminal, attachment still works and produces no
terminal reset sequences on redirected output. Terminal cleanup is best-effort
if the terminal disappears; uncatchable `SIGKILL` cannot run cleanup.

Python 3 is already required by the preceding peer-ledger refresh. The cleanup
uses only its standard library. Verify locally without network changes using
`bash tests/test-remote-client-tty.sh`, which exercises a fake SSH process on a
PTY, typed input, queued mouse reports, exit status, and signal forwarding.
