# Remote attachment terminal lifecycle

`tproj-remote-client attach HOST ABS_PATH cc|cdx` attaches SSH to an existing
persistent remote agent pane. The local client supervises SSH until it exits;
it reconnects after transport loss, but never restarts the remote agent or
replaces its session.
`reattach` starts the same supervisor using only an already-existing role
session. Other client actions retain their noninteractive SSH behavior.

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

## Shared recovery policy

CC and Codex use the same transport policy. Interactive attachments request SSH
server-alive probes every 15 seconds with 3 missed replies, a 10-second connect
timeout, and retry after approximately 1 second (no long backoff). An available
macOS network signature is sampled about once per second with a bounded query;
a changed signature refreshes only the locally owned SSH process. A wall-clock
loop gap over 4 seconds likewise refreshes a potentially stale transport after
wake. These are polling-based detection, not a guarantee of instantaneous OS
notification or reachability. Once the server is reachable, recovery should take
seconds; DNS, authentication and remote availability can still delay or prevent it.

Only transport failure (SSH status 255) or detected transport refresh retries.
A normal detach, explicit HUP/INT/TERM, or remote non-transport failure stops.
Noninteractive attachment remains one-shot. Retry uses batch authentication;
it must not wait on repeated password prompts. Offline typing is discarded,
never queued for later execution. Terminal input modes are reset between attempts.

Recovery calls the host helper `reattach`, never `ensure` or `attach`. It checks
the existing role session, project/role pane tags and live pane before attachment.
A missing session returns an error without catalog registration, CLI update,
agent launch or session creation. Legacy shared-pair sessions are not silently
migrated. Explicit startup remains separate from recovery.

Focused proof: `bash tests/test-remote-client-tty.sh` and
`bash tests/test-remote-reattach.sh`. No real network outage is needed.

## Optional mosh transport

A line `HOST mosh` in `~/.config/tproj/remote-transport` on the attaching Mac
selects mosh for that host when `mosh` is on the local PATH. Without the line,
or without local mosh, attachment uses the SSH supervisor above unchanged.
mosh echoes typing locally and keeps the session across latency spikes, address
changes and sleep, so the supervisor neither reaps nor retries it. The remote
command runs as `/bin/sh -c` with `mosh-server` resolved from the Homebrew
paths and a UTF-8 locale. A nonzero mosh exit within 30 seconds (for example a
missing `mosh-server` or blocked UDP) falls back once to the SSH supervisor
with the same command. A later nonzero exit of an agent attachment falls back
once to SSH using `reattach` only; it cannot create a session or restart an agent.
A successful exit (including explicit mosh detach) and a forwarded signal remain
final. A later project-shell exit remains final rather than opening another shell.
Interactive SSH and mosh SSH bootstrap disable control connection multiplexing
(`ControlMaster=no`, `ControlPath=none`), leaving management/tunnel SSH config
unchanged. Existing connected clients are not forcibly replaced. Terminal
mode reset and termios restore on exit are the same as for SSH.

Focused proof: `bash tests/test-remote-client-mosh.sh`.
