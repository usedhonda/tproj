# persona

SessionStart bootstrap for AI contract generation and pane background images.

## What's included

- **project-bootstrap** -- SessionStart bootstrap for persona, message rules, managed AGENTS/config blocks, and minimal repo defaults
- **tproj-pane-bg** -- Generates AI artwork for tmux pane backgrounds using Gemini

## How it works

Each project gets a deterministic persona derived from an MD5 hash of its path. Traits include MBTI type, gender, age, historical era, speaking tone, character archetype, and relationship style.

project-bootstrap runs automatically on Claude Code session start (via SessionStart hook) and generates:

- `MEMORY.md` managed persona/bootstrap section (for Claude Code)
- `.codex/config.toml` managed bootstrap contract (for Codex)
- `AGENTS.md` managed guidance block
- `.gitignore` managed block for local generated artifacts
- `.cc-status-bar.voice.json` (for VOICEVOX TTS, optional)

## Pane backgrounds

tproj-pane-bg generates character artwork using Google's Gemini image models, driven by the persona traits. Images are cached per-project in `.local/tproj-pane-bg/`.

## Requirements

- `jq` (required by project-bootstrap)
- `python3` + `google-genai` (optional, for image generation)
- `GEMINI_API_KEY` exported in your shell profile (optional, for image generation; see the root README)
- VOICEVOX (optional, for TTS voice synthesis via cc-status-bar)


`cc-persona` is kept as a compatibility alias that forwards to `project-bootstrap`.
