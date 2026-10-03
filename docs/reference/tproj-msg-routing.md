# tproj-msg role and cross-host routing

For enrolled unified hosts, native conversation IDs and endpoint incarnations
are authoritative. Client YAML, pane labels, aliases, and unauthenticated
sender hints never grant identity or task authority.

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
Formal tasks are separate from ordinary message delivery and use the unified
task authority. `--new-task` is not a wake mechanism and message arrival never
grants task authority. A direct role binding is distinct from the GUI main
conversation.
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

Unsupported capabilities are rejected explicitly; no silent legacy or
unauthenticated fallback is allowed. Standalone legacy routing remains scoped
to explicitly configured standalone deployments.

The sendability gate blocks a live approval selection. A completed approval
menu still visible above Codex's current empty composer is history, not a live
selection; it must not indefinitely block subsequent chat delivery.
