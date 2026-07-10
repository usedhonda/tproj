# Active-model role routing

tproj integrates the canonical active-model hierarchy router through a tracked symlink:

```text
general/system/model-role-router/model-role-router
  -> tproj/extensions/model-role-router/model-role-router
  -> ~/bin/model-role-router
```

`install.sh` copies the resolved canonical file into `~/bin`; `install.sh --check` fails when any tier of this chain differs.

## Runtime metadata

Each AI pane carries four tmux pane options:

| Option | Meaning |
|---|---|
| `@active_model` | currently observed model identifier |
| `@model_tier` | model tier resolved by the canonical registry |
| `@orchestration_role` | `orchestrator`, `worker`, or `solo-fallback` |
| `@role_epoch` | monotonically advancing role-resolution epoch |

Startup initializes missing values without replacing complete existing metadata. When `model-role-router` is available, startup invokes `observe` and `resolve` for newly initialized AI panes. Router absence or failure never prevents workspace startup.

`cc` and `cdx` remain platform address labels; they do not imply orchestration ownership.

## Role handoff

The canonical router can transfer a direct request with the symmetric tproj messaging contract:

```bash
tproj-msg --role-handoff --new-task \
  --role-epoch 7 --orchestrator project.cdx \
  project.cdx "Plan this request and delegate its execution"
```

The receiver sees a `[Role-Handoff: <task-id>]` tag followed by `Role-Epoch`, `Orchestrator`, and the backward-compatible `[Task: <task-id>]` tag. If the target is typing or otherwise blocked, the handoff is queued and its Task ID is registered without overwriting prompt input. `--role-handoff` cannot be combined with `--force`.

The canonical commands consumed by tproj are `observe`, `resolve`, `route`, `status`, `doctor`, and `hook <event>`.
