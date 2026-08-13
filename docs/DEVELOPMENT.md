# Development and release builds

## Development environment

Requires Python 3.11 or newer:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Useful startup options:

```bash
python run.py --background
python run.py --page /display/main
```

Run the test suite:

```bash
python -m unittest discover -s tests
```

## Local release builds

Install build requirements in the active environment:

```bash
pip install -r build-requirements.txt
```

### macOS

Double-click `installers/macos/Build-macOS.command`, or run:

```bash
./installers/macos/build.sh
```

Output is written to `dist` as an architecture-specific drag-to-Applications `.dmg`.

### Windows

Install Python 3.11+ and Inno Setup 6, then run:

```powershell
.\installers\windows\Build-Windows.ps1
```

The versioned Setup executable is written to `dist\installers`.

### Linux

Run:

```bash
./installers/linux/build.sh
```

This produces a portable `.tar.gz` and a `.deb` for the current architecture.

## Automated releases

GitHub Actions runs tests on pushes and pull requests. The release workflow can be started manually for test artifacts. Pushing a release tag such as `v2.0.0` builds macOS Intel, macOS Apple-silicon, Windows x64, and Linux packages and attaches them to a GitHub Release.

Before creating a release:

1. Update `app/version.py`.
2. Run tests and platform builds where available.
3. Commit the version change.
4. Tag the exact commit:

   ```bash
   git tag v2.0.0
   git push origin v2.0.0
   ```

### macOS signing and notarization

Apple requires software distributed outside the Mac App Store to use a Developer ID certificate and notarization for the normal Gatekeeper experience. Add these GitHub Actions repository secrets to enable the release workflow's built-in signing path:

- `MACOS_CERTIFICATE_P12_BASE64`: the exported **Developer ID Application** `.p12`, base64 encoded;
- `MACOS_CERTIFICATE_PASSWORD`: the `.p12` export password;
- `MACOS_KEYCHAIN_PASSWORD`: a temporary CI keychain password;
- `APPLE_ID`: the Apple Account used for notarization;
- `APPLE_TEAM_ID`: the Apple Developer team identifier;
- `APPLE_APP_SPECIFIC_PASSWORD`: an app-specific password for that Apple Account.

When all values are present, the workflow imports the certificate into a temporary keychain, enables the hardened runtime, signs the app, submits the disk image with `notarytool`, and staples Apple's ticket. With no certificate configured, builds remain ad-hoc signed for private testing. Certificates and passwords must only be stored as GitHub secrets; never commit them.

Production Windows distribution should similarly add an Authenticode signing certificate.

## Repository safety

`data/churchboard.json` is intentionally ignored because it can contain live Planning Center credentials and local integration addresses. Never force-add that file, copied browser profiles, screenshots containing secrets, or private keys.
