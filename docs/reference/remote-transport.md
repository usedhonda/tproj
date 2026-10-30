# Remote interactive transport

`tproj-remote-client shell HOST REMOTE_PATH` opens a login shell in an absolute
remote project directory without registering, starting, or attaching an agent.
The GUI terminal dock and legacy remote workspace shells use this same client.
Existing attach/reattach behavior is unchanged.

The client defaults to SSH. A `HOST mosh` entry in
`~/.config/tproj/remote-transport` opts that host into mosh when the local binary
is available. A quick unsuccessful mosh startup falls back to SSH; a running
mosh session handles roaming itself. If that process later fails, agent attachments
recover over SSH with `reattach`, never repeat agent startup. Normal detach and
signals remain final. Shell and agent attachments share transport
selection, terminal cleanup, and fallback rather than maintaining separate paths.
Mosh is optional and never required for workspace startup.

Interactive SSH uses ServerAliveInterval=15, ServerAliveCountMax=3 and
ConnectTimeout=10. Interactive SSH and mosh bootstrap use `ControlMaster=no`
and `ControlPath=none` so stale shared masters and unrelated tunnel lifecycles
cannot determine this connection. Global SSH configuration is not changed.
These tolerate transient latency without the previous
approximately four-second keepalive failure threshold. They are not a maximum
wall-clock outage guarantee: OS networking and the existing network/wake
supervisor also affect reconnection. Noninteractive management commands retain
their existing timeout. Changes apply to new client processes; active connections
are not disconnected or reconfigured.
