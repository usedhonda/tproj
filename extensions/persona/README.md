# persona

Local persona bootstrap, explicit shared instruction setup, and pane background images.

## What's included

- **project-bootstrap** -- local persona/voice bootstrap plus explicit shared instruction initialization and migration
- **tproj-pane-bg** -- Generates AI artwork for tmux pane backgrounds using Gemini

## How it works

Each project gets a deterministic persona derived from an MD5 hash of its path. Traits include MBTI type, gender, age, historical era, speaking tone, character archetype, and relationship style.

`project-bootstrap` runs automatically on Claude Code SessionStart and through
`tproj` startup's `--prime` call. Both runtime paths are local-only and generate:

- `MEMORY.md` managed persona/bootstrap section (for Claude Code)
- `.codex/config.toml` managed bootstrap contract (for Codex)
- `.cc-status-bar.voice.json` (for VOICEVOX TTS, optional)

Runtime bootstrap never creates or modifies tracked `AGENTS.md`, `CLAUDE.md`,
or `.gitignore`. Shared repository instructions use explicit maintenance modes:

```bash
project-bootstrap --init-shared <project_path>
project-bootstrap --migrate-shared <project_path>          # dry-run
project-bootstrap --migrate-shared <project_path> --apply  # apply migration
```

`--init-shared` creates a public-safe tracked `AGENTS.md` / `CLAUDE.md` pair
when missing and records local artifact ignores. `--migrate-shared` removes
legacy generated blocks or instruction symlinks while preserving user-owned
content; it is dry-run unless `--apply` is supplied.

## Source and install contract

The executable follows one version chain:

1. canonical implementation: `../general/system/project-bootstrap/project-bootstrap`
2. tracked tproj symlink: `extensions/persona/project-bootstrap`
3. installed executable copy: `~/bin/project-bootstrap`

`install.sh` preserves the tracked symlink, dereferences it only for the
installed copy, and `./install.sh --check` verifies the full chain.

Run the focused regression test with:

```bash
bash extensions/persona/test-project-bootstrap-contract.sh
```

## Pane backgrounds

tproj-pane-bg generates character artwork using Google's Gemini image models, driven by the persona traits. Images are cached per-project in `.local/tproj-pane-bg/`.

## Requirements

- `jq` (required by project-bootstrap)
- `python3` + `google-genai` (optional, for image generation)
- `GEMINI_API_KEY` exported in your shell profile (optional, for image generation; see the root README)
- VOICEVOX (optional, for TTS voice synthesis via cc-status-bar)


`cc-persona` is kept as a compatibility alias that forwards to `project-bootstrap`.
