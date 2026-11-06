# persona

Local persona bootstrap, explicit shared instruction setup, and pane background images.

## What's included

- **project-bootstrap** -- local persona/voice bootstrap plus explicit shared instruction initialization and migration
- **tproj-pane-bg** -- Generates AI artwork for tmux pane backgrounds using GPT Image or Gemini

## How it works

Each project gets a deterministic persona derived from an MD5 hash of its path. Traits include MBTI type, gender, age, historical era, speaking tone, character archetype, and relationship style.

`project-bootstrap` runs automatically on Claude Code SessionStart and through
`tproj` startup's `--prime` call. Both runtime paths are local-only and generate:

- `MEMORY.md` managed persona/bootstrap section (for Claude Code)
- `.codex/config.toml` managed bootstrap contract (for Codex)
- `.cc-status-bar.voice.json` (for VOICEVOX TTS, optional)

Runtime bootstrap never creates or modifies tracked `AGENTS.md` or
`.gitignore`, and never creates a `CLAUDE.md`. Shared repository instructions use explicit maintenance modes:

```bash
project-bootstrap --init-shared <project_path>
project-bootstrap --migrate-shared <project_path>          # dry-run
project-bootstrap --migrate-shared <project_path> --apply  # apply migration
```

`--init-shared` creates a public-safe tracked `AGENTS.md` when missing (Claude
Code and Codex both read it directly, so no `CLAUDE.md` is created) and records
local artifact ignores. `--migrate-shared` removes
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

`tproj-pane-bg` generates character artwork from the persona traits. Images are
cached per project in `.local/tproj-pane-bg/`.

The default route prefers `gpt-image-2` when the local Codex auth file contains an
access token. Otherwise it uses Gemini. Set
`TPROJ_PANE_BG_IMAGE_PROVIDER=gemini` to select Gemini explicitly. Token presence
selects the GPT Image route; it does not guarantee that the provider will accept
the request.

The Gemini route uses `gemini-3-pro-image` for new images and explicit
`--refresh` requests. It tries Vertex with Application Default Credentials when
`GOOGLE_CLOUD_PROJECT` is configured, then a Gemini API key when one is available.
The default Vertex location is `global`. The fallback to
`gemini-3.1-flash-image` handles an unavailable Pro model and supported transient
image failures; permanent authentication failures stop retries.

An otherwise-valid wallpaper generated with `gemini-3-pro-image-preview` or
`gemini-2.5-flash-image` remains cached. Its original model, prompt, schema, and
hash are used to validate it; upgrading the model alone does not overwrite the
image or sidecar. An explicit `--refresh` or a genuine cache miss uses the current
generation model.

The provider and cache migration contracts can be checked without live image
generation:

```bash
bash extensions/persona/test-tproj-pane-bg-provider-contract.sh
bash tests/test-pane-bg-style-layers.sh
```

## Requirements

- `jq` (required by project-bootstrap)
- `python3` (optional, for image generation)
- A local Codex login for GPT Image, or Google credentials for Gemini (optional;
  image generation is independent of core tmux startup)
- `google-genai` (Gemini only), with either Vertex Application Default Credentials
  and `GOOGLE_CLOUD_PROJECT`, or a `GEMINI_API_KEY` / `GOOGLE_API_KEY` (see the root
  README)
- VOICEVOX (optional, for TTS voice synthesis via cc-status-bar)


`cc-persona` is kept as a compatibility alias that forwards to `project-bootstrap`.
