# Remote cache monitor

`tproj-remote-cache` runs on the remote macOS host, independently of the
client GUI. It reads only projects registered with `tproj-remote-host` and
their tagged live tmux panes. CC expiry and last real prompt come from the
local `tproj-cc-cache-observer`; Cdx turn and quiet time come from
`tproj-codex-cache-state`.

```sh
tproj-remote-cache set --path /absolute/project --role cc --hours 3
tproj-remote-cache set --path /absolute/project --role cdx --hours 0
tproj-remote-cache status
tproj-remote-cache tick
```

Hours are `0` (off), `1`, `3`, `6`, or `12`, separately for each project and
role. The host-local configuration is mode 0600
`~/.config/tproj-remote/cache-hours.json`. `status` emits JSON. `tick` emits
the same status plus a send/refusal result. Only a CC session with an expiry
0–90 seconds away and a real prompt within its chosen window is offered to
`tproj-cc-poke`; that sender independently rechecks live identity, idle
notification, cache expiry, empty composer and its deduplication lock.

Cdx is **diagnostic-only**, even with nonzero hours. The current Cdx log and
sendability helpers do not positively prove both current-turn completion and
an empty composer at send time. `tick` never calls its sender.

For autonomous operation, install the CLI and the observer/poke helpers on the
remote host, then create a user LaunchAgent (do not use a system daemon) with
this plist at `~/Library/LaunchAgents/local.tproj.remote-cache.plist`, replacing
`USER_HOME` with the actual home path:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.tproj.remote-cache</string>
  <key>ProgramArguments</key><array>
    <string>USER_HOME/bin/tproj-remote-cache</string><string>tick</string>
  </array>
  <key>StartInterval</key><integer>30</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>USER_HOME/.local/state/tproj/remote-cache.out.log</string>
  <key>StandardErrorPath</key><string>USER_HOME/.local/state/tproj/remote-cache.err.log</string>
</dict></plist>
```

Create the log directory mode 0700 first. Load with
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.tproj.remote-cache.plist`
while the user GUI domain is available; inspect `status` and
`launchctl print gui/$(id -u)/local.tproj.remote-cache`.
Do not install or enable the agent merely by registering a project. A missing
observer, missing tag, stopped session, or refused sender leaves the cache
unmodified.
