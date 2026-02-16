tproj Quick Start
=================

This DMG includes:
- tproj.app (GUI)
- Install tproj.command (CLI + config installer)

Recommended steps:
1) Run "Install tproj.command"
2) Open a new terminal
3) Run: tproj --check
4) Configure ~/.config/tproj/workspace.yaml if needed
5) Launch GUI: open /Applications/tproj.app

Notes:
- The installer checks core dependencies.
- yazi plugin install is best-effort. If it fails:
  cd ~/.config/yazi && ya pack -i
- If you already have local settings, install.sh creates backups.
