# tproj-msg role and cross-host routing

An unqualified `cc` or `cdx` target names the opposite-side role in the
**sender's project**, including when that project's panes occupy separate tmux
sessions on Mac mini. `tproj-msg --status cdx` reports the resolved
`<alias>.cdx` and destination session; a sender must not substitute a familiar
alias from another project when the local role is unavailable. For example,
`artist.cc` sending to `cdx` targets `artist.cdx`, not `tproj.cdx`.

Only an explicit `<alias>.cc` or `<alias>.cdx` selects another project. The
client's workspace YAML supplies those aliases to the peer ledger; a server
catalog alias does not override them. Cross-host delivery is plain chat with a
non-authoritative sender hint. A receiver must not treat that hint as verified
pane identity or task/role-handoff authority. A reply uses the intended exact
alias from the project ledger, not a guessed alias based on the receiving pane.
