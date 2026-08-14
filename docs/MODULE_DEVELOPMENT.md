# ChurchBoard module development

This guide is written to be pasted into Codex, Claude, or another coding assistant when building a ChurchBoard module.

## Copy/paste brief

> Build a ChurchBoard module in `modules/<module-id>/`. Add a `manifest.json` with a stable kebab-case `id`, `name`, `vendor`, semantic `version`, `dependencies`, `settings_keys`, `widgets`, and `files`. Keep integration code inside the module directory, expose a small adapter class, and do not edit the ChurchBoard shell unless the module API requires a backwards-compatible change. Include tests, a README, and SHA-256 checksums for every distributable file. The module must work when installed from the local `modules/` folder and when downloaded from the module catalog. Never include credentials in the manifest or source.

## Folder and manifest

Place a module at either:

```text
modules/my-module/
  manifest.json
  my_module.py
  README.md
  tests/
```

The application scans both the bundled `modules/` folder and the user data `modules/` folder at startup. A valid manifest is immediately shown in Setup and can be installed without rebuilding the core application.

Example:

```json
{
  "schema": 1,
  "id": "my-module",
  "name": "My integration",
  "vendor": "Example vendor",
  "version": "1.0.0",
  "dependencies": [],
  "settings_keys": ["my_integration"],
  "widgets": [{"type": "my_widget", "name": "My widget", "category": "Production"}],
  "files": [{"path": "my_module.py", "sha256": "..."}]
}
```

Use semantic versions. Increment the module version whenever its files change. Keep widget types stable so existing dashboards continue to work.

## Updating without a full release

The module catalog is `modules/catalog.json`. Each entry points to versioned files and includes a SHA-256 checksum. Admins can use **Setup → Modules → Check for module updates**, then update an individual module. ChurchBoard downloads the files to a staging directory, verifies every checksum, and atomically activates the new version. The core app keeps running and reloads the affected adapter.

For a private GitHub catalog, set `CHURCHBOARD_MODULE_UPDATE_TOKEN` to a fine-grained token with read-only Contents access. Public catalogs need no token. Do not commit the token.

## Adapter rules

- Keep network calls asynchronous or short-lived; never block the UI thread.
- Return plain JSON-compatible dictionaries from status methods.
- Treat missing or unavailable hardware as an explicit disconnected state.
- Reuse the module's settings namespace and preserve unknown settings.
- Never log API keys, access tokens, or personal data.
- Provide a bundled fallback so an unavailable update cannot prevent ChurchBoard from starting.
- Add unit tests for parsing, connection failures, and version upgrades.

## Checklist before publishing

1. Run the full test suite.
2. Verify the manifest parses and every file exists.
3. Calculate SHA-256 checksums after the final edit.
4. Add release notes and vendor/license attribution.
5. Publish the module files and update `modules/catalog.json` with the new version.
6. Test **Check for module updates** and **Update** on a copy of ChurchBoard data.

Modules are third-party code. Review permissions, licenses, and update sources before enabling automatic updates.
