# Peer ledger remote sync

`~/.config/tproj/workspace.yaml` on the initiating Mac is the alias source.
`tproj-peer-ledger refresh` projects it atomically to the host-local
`~/.config/tproj/peers.json`; `tproj-remote-client sync HOST` sends that snapshot
through the existing batch SSH connection to `tproj-peer-ledger import --stdin`
on HOST. Import rejects stale or conflicting revisions without replacing its
prior snapshot. No service or tmux restart is part of this operation.

`ensure`, `attach`, and `register` require a successful sync before their
remote action. `status` and `list` stay read-only. The legacy remote-host
catalog still handles these actions and is not an independent source of alias
truth; callers must not copy its aliases over local workspace aliases.
