# tproj Release Guide

This guide describes how to generate a notarized DMG that includes:
- `tproj.app` (GUI)
- `Install tproj.command` (CLI + config installer)
- `tproj-cli-payload.tar.gz` (install assets)

## 1. Prepare credentials

Create a local file:

```bash
cp apps/tproj/.local/release.example.md apps/tproj/.local/release.md
```

Fill at least:
- `SIGNING_ID`
- `NOTARY_PROFILE` (recommended)

If you do not use `NOTARY_PROFILE`, set:
- `APPLE_ID`
- `TEAM_ID`
- `APP_PASSWORD`

## 2. Build release DMG

```bash
cd apps/tproj
./scripts/release.sh
```

Artifact:
- `apps/tproj/dist/release/tproj.dmg`

## 3. Verify locally

```bash
xcrun stapler validate apps/tproj/dist/release/tproj.dmg
spctl --assess --type open --context context:primary-signature --verbose apps/tproj/dist/release/tproj.dmg
```

## 4. Install test

Open the DMG and run:
- `Install tproj.command`

Then check:

```bash
tproj --check
```

## Notes

- Installer keeps strict dependency checks.
- yazi plugin install is best-effort and does not fail installation.
- `workspace.yaml.example` uses generic placeholders and contains no personal paths.
