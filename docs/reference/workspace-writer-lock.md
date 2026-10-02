# workspace.yaml writer contract

All local writers of `workspace.yaml` coordinate through the sibling advisory
directory `<workspace>.lock`.

- Acquire with atomic `mkdir`; write the owner PID to `<lock>/pid`.
- Wait at most five seconds. A PID that no longer exists may be reclaimed.
- Hold the lock through the read, conflict/location validation, and atomic
  replacement. Release by removing `pid` and the lock directory.
- Project saves merge requested fields onto the current row by `project_id`,
  falling back to `(host, path)`, preserving unknown/manual keys. MRU updates
  remain field-level updates.
- A location snapshot mismatch is a conflict; writers must report it and never
  silently overwrite the changed location.

The shell implementation is `bin/lib/tproj-workspace-lock.sh`; the Swift GUI
uses the same path and mkdir/PID semantics.
