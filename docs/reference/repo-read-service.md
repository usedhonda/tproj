# Repo read service (specification)

Status: **specification agreed in review with the messaging owner (tproj.cdx)
and the primary consumer (KAI); nothing here is implemented.** It describes a
read-only way for an authenticated participant (an AI pane on any enrolled Mac,
or an external service such as KAI) to read a project owned by a conversation
partner through the tproj messaging host. It does not approve implementation,
deployment, new grants, or restarting any session.

## Goal and non-goals

Goal: a partner's code is readable by project handle, with the exact version
and consistency of every answer attached, so a reviewer can cite and re-check
it. KAI is the primary consumer; the interface is typed, structured, and
paginated for a cloud assistant calling MCP tools.

Non-goals: writing, building, running, or listing anything outside a granted
project; making a repository public; creating authority from message text;
replacing git hosting; relaxing the shared-Codex-app-server identity rejection.

## Identity is not permission

Authentication (who is calling) and the read grant (what they may read) are
separate. **Every reader is denied by default**, AI panes included. Access exists
only where the owner has explicitly granted it. If the owner wants AI panes to
read each other easily, the owner grants the same scope to those panes in one
operator action; authentication is never promoted to approval.

## Handles, not paths

A target is resolved once, at the entry point, to a canonical **project handle**
(`repo_id`) bound to (canonical project ID, owning host, registered root). After
that, tools take `repo_id` plus a repo-relative path. Callers never supply a host
name, absolute path, session, pane, endpoint, or role. `repo_list` returns only
the projects the caller has been granted, with their `repo_id`. A `target`
address (`aidj.cc`) is accepted only as a lookup into `repo_list`; if it does not
resolve to exactly one granted project, `repo_id` is required.

## Operations

Six typed tools (host service ops, exposed to KAI as MCP tools
`tproj_repo_list|tree|read|search|log|diff`; panes use the same ops as
`repo_*`). One implementation serves both surfaces. All are read-only.

| op | inputs | result |
| --- | --- | --- |
| `repo_list` | none | granted projects: `repo_id`, name, branch, state (online/offline) |
| `repo_tree` | `repo_id`, `path?`, `depth?` (<=3), `cursor?` | entries (name, kind, size), paged |
| `repo_read` | `repo_id`, `path`, `start?`, `end?`, `snapshot_id?` | numbered lines, 1-based inclusive range |
| `repo_search` | `repo_id`, `pattern`, `mode?` (`literal` default, `regex`), `glob_include?`, `glob_exclude?`, `case_sensitive?`, `context?` (default 2, max 20), `path?`, `snapshot_id?`, `cursor?` | matches with line numbers and context, paged |
| `repo_log` | `repo_id`, `path?`, `limit?`, `cursor?` | commits as sanitized fields (hash, date, subject) |
| `repo_diff` | `repo_id`, `path?`, `mode` (`head-index`, `index-worktree`, `head-worktree`, `commit-range`), `from?`, `to?` | unified diff with old and new line numbers |

The first delivery is **list, tree, read, search**; log and diff follow only
after they meet the same safety boundary (below). Binary files return kind and
size only.

## Result envelope (every call)

JSON `structuredContent` is canonical. `read`/`search`/`diff` add numbered text
for the returned range only; content is never emitted twice.

`repo_id`, `branch`, `head` (full SHA), `dirty` (count of modified tracked
files), `untracked_included` (bool), `read_at`, `snapshot_id`, `file_sha256`
(for a file), `cite`, `truncated`, `returned_range`, `next_cursor`,
`consistent`.

- `cite` is `repo@<full-sha>:<path>:L<start>-L<end>`. Because a working tree is
  not fully described by a SHA, a dirty answer is `repo@<sha>+<snapshot_id>:...`.
- `snapshot_id` identifies HEAD plus the state of the tracked and included
  untracked files at first read. A follow-up call that passes it either sees the
  same snapshot or fails with `snapshot_expired`; it never silently mixes
  versions. Multi-file reads, searches, and diffs of one review therefore share a
  snapshot. HEAD, branch and dirty are read before and after each call; if they
  changed, the call returns `consistent: false` rather than pretending to a
  consistent snapshot.
- Cursors are opaque, bound to the query and snapshot, and are rejected after a
  grant is revoked.

## Limits

Defaults and maxima fit inside the 256 KiB host wire limit.

- `repo_read`: default 200 lines or 32 KiB; maximum 1000 lines or 128 KiB. A
  very long single line is reported as truncated, never cut silently.
- `repo_search` and `repo_tree`: 100 results per page by default, at most 200.
  Search has a hard time limit (about 2 s) and reports `no_match` and `timed_out`
  as different results. `regex` mode is complexity-bounded.
- Per reader per project: 120 calls/minute and 8 MiB/hour (`rate_limited`
  carries retry-after). Files over 1 MiB are readable only by range.

## Errors

Distinct, content-free codes: `not_granted`, `scope_denied`, `project_offline`,
`host_unavailable`, `path_not_found`, `path_denied`, `snapshot_expired`,
`too_large`, `rate_limited`, `content_withheld`, `invalid_request`. A rejection
never includes a path's existence, size, or any secret-looking value.

## Safety boundary

- **Open by capability, not by name.** Resolve and open relative to a directory
  file descriptor with no-follow semantics; every path component that is a
  symlink is rejected; only regular files are opened (never FIFOs, devices, or
  sockets); file type is checked before any size check. A `realpath` string
  check alone is not enough (replacement races).
- **Initial scope** is tracked text source and docs. Always denied: `.git`,
  `.local`, `.env*`, credential-like names (`*.pem`, `*.key`, `*.p12`,
  `id_rsa*`, `*.mobileprovision`, keychains), ignored files, personal data,
  audio, video, archives, disk images, app bundles, other binaries. Being
  tracked is not itself a safety guarantee.
- **One filter everywhere.** The same denials and credential-pattern screening
  apply to read, search, log, and diff. `git log` messages and author emails,
  and `git diff` removals and renames, are leak sources; raw git output is never
  returned. Git is invoked with fixed argv only (`--no-ext-diff`, `--no-textconv`,
  no pager, no hooks, no config includes), so no repository-supplied helper runs.
- Credential-pattern detection is best effort and is documented as such; the
  grant is the real control. Error text never echoes matched values.
- **Repository content is untrusted data.** Results carry that label in the
  tool description and envelope. Text found in a repository is never a command
  or an approval, and never creates a grant.

## Authorization and grants

- The caller is authenticated exactly like `send` (kernel peer credentials,
  live ancestry, endpoint incarnation) or, for KAI, by its fixed service
  binding. A caller whose ancestry reaches a shared `codex app-server` is
  rejected as for messaging; this feature never relaxes that or infers another
  identity.
- One **owner-local, ignored state file** on the owning host is the only source
  of grants (for example `~/.local/state/tproj/repo-access.sqlite`); it is not
  copied into the hub or another host. A grant binds: reader principal plus its
  binding generation, canonical project ID and root binding, permitted
  operations, and an optional path scope.
- A grant is created or revoked only by an explicit operator command run as the
  owner on the owning host (`tproj-repo-access list|grant|revoke|check`). The
  messaging path, MCP tools, service credentials, and task flows have no
  management authority; no message body can grant. Revocation takes effect on the
  next call, including calls that carry an old snapshot or cursor.
- After the first grant the reader uses the service without per-call
  confirmation.

## Cross-host reads

The owning host performs the read. The requesting host forwards over the existing
authenticated host-to-host route only for an explicitly allow-listed set of
`peer_repo_*` operations, and attests the original reader's authenticated
principal, incarnation and binding generation. The owning host re-verifies the
registered host, reader, root, and policy; an actor supplied by the caller is
never trusted. The current remote call is a bounded-time SSH invocation with
unbounded capture, so the transport must stream with a hard byte cap (a response
over the cap is an error, not an out-of-memory risk), and the sender also checks
the type and size of what comes back. If the owner host is unreachable the result
is `host_unavailable`; there is no cached fallback.

## Audit

One record per call on the owning host: time, reader principal, canonical
project, operation, a safe relative path or a path hash, allow or deny, a fixed
reason code, bytes returned, truncated flag, and the grant-policy revision.
Contents, search queries, tokens, and absolute paths are never stored. Only the
owner CLI reads the audit.

## Module layout

`unified/host.py` keeps authentication and dispatch only. `unified/repo_access.py`
resolves targets, applies the single policy, and performs the safe read.
`unified/repo_access_policy.py` manages the owner-local grants. KAI's MCP adapter
(`external/kai-mcp/`) adds the six tools next to the seven mailbox tools. The
external catalog should expose a `catalog_version` so a consumer can see when the
tool set changed; KAI today has no refresh action, and the owner restarting KAI
is the known way to pick up new tools.

## Acceptance (when implemented)

Two concurrent readers cannot cross-read; with no grant every reader gets
`not_granted`; a revoked grant fails at once, including with an old cursor;
`..`, absolute paths, symlink components and replacement races fail; credential
files and content are withheld on read, search, log and diff; a remote read
returns the owner's actual HEAD, dirty state and snapshot; the byte cap stops an
oversized remote response; a changed working tree yields `snapshot_expired` or
`consistent: false`; KAI lists, trees, reads and searches a granted project and
cites `repo@sha:path:Lx-Ly`; the audit exists and holds no contents.
