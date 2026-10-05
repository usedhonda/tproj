# Repo write service (specification)

Status: **first slice implemented** (`repo_write`, `repo_revert`; panes use `tproj-repo put|write|revert`, KAI uses `tproj_repo_write|revert`). It extends the repo read service
(`repo-read-service.md`) so an authenticated participant (an AI pane on any
enrolled Mac, or KAI) can change files in a project it has been granted write
access to, through the messaging host. It creates no grant.

## Model

The writer submits **changes** (whole-file content, never a free-form command).
The **owning host** validates them against the owner's grants and the current
state of the tree, and applies them in the same call. The writer never touches the
owner's filesystem and never chooses where a file lands beyond a repo-relative
path. No shell, no git command, no hook, and no build ever runs on behalf of a
writer; the host only writes files.

Writes never commit, push, stage, or alter git state. The owner sees ordinary
uncommitted working-tree changes and decides what to do with them.

## Grants

Same owner-local ledger as reads, with one new op: `write`. A write grant is
a separate row from a read grant (granting read never grants write, granting
either never replaces the other, and each has its own path prefix), should be scoped
with a path prefix, and may expire. Only the owner CLI creates or revokes it
(`tproj-repo-access grant --ops write --path-prefix docs/ ...`). Identity, the
shared-Codex-app-server rejection, and revocation timing are exactly as for reads.
A call that arrives after revocation fails at once.

## Operations

| op | inputs | result |
| --- | --- | --- |
| `repo_write` | `repo_id`, `patch_id` (writer-chosen UUID), `changes[]`, `dry_run?` | per file: `status`, new `file_sha256`; overall `applied`, `patch_id`, `head`, `dirty` |
| `repo_revert` | `repo_id`, `patch_id` | files restored; refuses a file that no longer matches what the patch wrote |

Each change: `path`, `action` (`create` or `modify`; delete and rename are out of
scope), `content` (UTF-8 text), and for `modify` the `base_sha256` of the file the
writer read. A modify whose base does not match the current file is `conflict`.
`dry_run` validates everything and writes nothing.

## Rules the owner host enforces

- **All or nothing.** If any change fails validation, no file is written.
- **Precondition.** `modify` needs a matching `base_sha256`; `create` needs the
  path to be absent. A path with uncommitted changes the writer did not make
  (working tree differs from HEAD) is refused (`dirty_path`), so a writer never
  overwrites the owner's work in progress.
- **Same path filter as reads**, plus write-only limits: never `.git`, `.local`,
  `.env*`, credential-like names, binary or executable files, files that are not
  tracked-or-new text, or anything outside the grant's path prefix. A symlink in
  any component is refused. Open by capability: a directory file descriptor with
  no-follow, write to a temporary file in the same directory, then rename into
  place; file mode is preserved and never made executable.
- **Content screening.** Content that matches the credential patterns is refused
  (`content_withheld`); a writer cannot plant a secret.
- **Limits.** At most 20 files, 128 KiB per file, 192 KiB per call (one host frame); parent
  directories are created only below the granted prefix and only 3 levels deep.
- **Idempotency.** `patch_id` is the idempotency key: the same id with the same
  content returns the original result; the same id with different content is
  refused. The host keeps a per-project lock for the duration of a call.
- **Repository content and patches are untrusted data.** Nothing a writer sends is
  executed or interpreted as an instruction, and nothing in a result is an
  approval.

## Errors

Reads' codes plus: `conflict`, `dirty_path`, `exists`, `too_large`,
`content_withheld`, `scope_denied`, `invalid_request`. A refusal never echoes
content or reveals whether a forbidden path exists.

## Audit

One record per call on the owning host: time, writer principal, project, op,
`patch_id`, the safe relative paths (or hashes), allow/deny with a fixed reason,
bytes written, and the grant revision. Contents and absolute paths are never
stored. The previous contents needed for `repo_revert` are kept in an owner-local
ignored state file for a limited time and are never returned to a caller.

## Cross-host and KAI

The call forwards to the owning host exactly as reads do (`repo_peer` ->
`peer_repo`, with the writer's attested principal); a response over the byte cap
is an error. KAI gets two MCP tools, `tproj_repo_write` and `tproj_repo_revert`,
flagged as **write** class in the external catalog; without a write grant they
return `not_granted` and change nothing.

## Acceptance

No write grant: `not_granted`. A read-only grant cannot write. A modify with a
stale base is `conflict`; a path the owner has uncommitted changes in is
`dirty_path`; a batch with one bad file writes nothing. `..`, absolute paths,
symlinks, `.env`, credential content, executables and out-of-prefix paths fail.
A replayed `patch_id` does not write twice. A revoked grant fails the next call.
A revert restores exactly what the patch wrote and refuses otherwise. The audit
holds no contents. A remote write changes only the owner's working tree, and the
owner's `git status` shows it as uncommitted.
