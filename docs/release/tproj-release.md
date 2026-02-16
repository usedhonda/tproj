# tproj Release Guide

This guide describes how to generate a notarized DMG that includes:
- `tproj.app` (GUI)
- `Install tproj.command` (CLI + config installer)
- `tproj-cli-payload.tar.gz` (install assets)

Installer payload also includes:
- `cc-mem`
- `memory-guard` + launchd plist (`com.tproj.memory-guard`)
- `tproj-mem-json` (merged monitor collector)

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

## GitHub Release (same flow as ccsb)

`workflow_dispatch` from `.github/workflows/release.yml` builds/signs/notarizes DMG and publishes GitHub Release.

Required repository secrets:
- `SIGNING_ID` (e.g. `Developer ID Application: ... (TEAMID)`)
- `DEVELOPER_ID_CERT` (base64 encoded `.p12`)
- `DEVELOPER_ID_CERT_PASSWORD`
- `APPLE_ID`
- `APPLE_TEAM_ID`
- `APPLE_ID_PASSWORD` (app-specific password)

Workflow inputs:
- `bump_type`: `patch` / `minor` / `major`
- `skip_notarize`: `true` to skip notarization for test runs

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
- While GUI is running, monitor snapshot is published to `/tmp/tproj-monitor-status.json`.
