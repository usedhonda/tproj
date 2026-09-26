# Peer ledger remote sync

`~/.config/tproj/workspace.yaml` on the initiating Mac is the alias source.
`tproj-peer-ledger refresh` projects it atomically to the initiating host's
`~/.config/tproj/peers.json`. Persistent remote panes query that master live
through the private reverse socket. `tproj-remote-client sync HOST` validates
the local master but does not copy it to HOST. No tmux restart is involved.

`ensure`, `attach`, and `register` require a valid master before their
remote action. `status` and `list` stay read-only. The legacy remote-host
catalog still handles these actions and is not an independent source of alias
truth; callers must not copy its aliases over local workspace aliases.
GUI-disabled projects are omitted unless their tagged tmux pane is already
running. Disabling a GUI row must not remove an active pane from cross-host
message addressing; destination sendability remains a separate live check.

`tproj-remote-client identity HOST ABS_PATH cc|cdx` is a read-only, fail-closed
target observation. It returns one JSON object with `session`, `pane`, `alias`,
`project`, `platform`, `pid`, `pid_start`, `role`, and `role_epoch`. `alias` is
the registry identity (`<pane @alias>.cc` or `<pane @alias>.cdx`). It requires a
live exact-path role pane and a matching model-role registry entry, including
the process start and pane ancestry. A missing or mismatched entry is an error,
not a guessed epoch; the catalog is not identity authority.
