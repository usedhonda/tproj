# tproj-msg role and cross-host routing

An unqualified `cc` or `cdx` target names the opposite-side role in the
**sender's project**, including when that project's panes occupy separate tmux
sessions on Mac mini. `tproj-msg --status cdx` reports the resolved
`<alias>.cdx` and destination session; a sender must not substitute a familiar
alias from another project when the local role is unavailable. For example,
`artist.cc` sending to `cdx` targets `artist.cdx`, not `tproj.cdx`.
On a persistent host, a verified sender's absolute project path is used to
find the other role's remote session. Its single-project pane tags are `*-p1`;
the role lookup retains column 1 even when `--session` already names that
destination session. This keeps `--status cc` and the matching send consistent
for Codex's explicit `--session ... --as artist.cdx cc` invocation.
Across two sessions on the same persistent host, a verified pane-origin bare
opposite-role `--new-task` keeps the sender session as task owner and binds the
task to the sender project path; the destination session is used only for
delivery. Cdx's explicit `--as` route also requires a matching live registry
session ID and project. A blocked destination is rejected without queueing.
The exact `<alias>.role` key is used in task rows and reply message evidence,
even when the sender typed the bare role.
Unverified external `--as`, other-project aliases, role handoffs, and
cross-host control remain outside this task route.

Only an explicit `<alias>.cc` or `<alias>.cdx` selects another project. The
client's workspace YAML is the live alias master queried over the reverse
socket; a server
catalog alias does not override them. Cross-host delivery is plain chat with a
non-authoritative sender hint. A receiver must not treat that hint as verified
pane identity or task/role-handoff authority. A reply uses the intended exact
alias from the project ledger, not a guessed alias based on the receiving pane.

The sendability gate blocks a live approval selection. A completed approval
menu still visible above Codex's current empty composer is history, not a live
selection; it must not indefinitely block subsequent chat delivery.
