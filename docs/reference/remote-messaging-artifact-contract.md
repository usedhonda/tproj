# Remote messaging artifact contract

`bin/tproj-remote-setup` provisions the messaging wrapper and its unified
runtime as one revision. The canonical wrapper is
`extensions/messaging/tproj-msg` in a checkout; when the setup script is run
from an installed tree it uses that tree's `bin/tproj-msg` source.

## Provisioning

`add HOST` copies the wrapper to `~/bin/tproj-msg` alongside the runtime and
shared skills. It then runs the runtime setup path, but does not restart
existing agent panes, tmux sessions, or the remote mailbox service.

## Drift check

`check HOST` is read-only. It compares the SHA-256 digest and executable mode
of the remote `~/bin/tproj-msg` with the canonical wrapper in the invoking tree,
in addition to checking shared skills and Claude allow rules. A missing wrapper
is reported as `~/bin/tproj-msg: missing`; a different wrapper is reported as
`~/bin/tproj-msg: differs (CLI drift)`; and a non-executable wrapper is reported
as `~/bin/tproj-msg: not executable`. A non-zero result means the remote is not
at the same CLI revision and `add HOST` is the remediation.

The wrapper digest check is intentionally separate from enrollment and service
health. A live enrolled client may remain active while its CLI artifact drifts;
the check must report that drift without changing the live session.
