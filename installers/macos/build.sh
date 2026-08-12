#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR"

find_python() {
  if [[ -n "${PYTHON:-}" ]] && "$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    echo "$PYTHON"
    return
  fi
  for candidate in "$PROJECT_DIR/.venv/bin/python" python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
      command -v "$candidate"
      return
    fi
  done
  echo "Python 3.11 or newer is required to build ChurchBoard." >&2
  exit 1
}

PYTHON_BIN="$(find_python)"
"$PYTHON_BIN" -m venv .build-venv
.build-venv/bin/python -m pip install --upgrade pip
.build-venv/bin/pip install -r requirements.txt -r build-requirements.txt
.build-venv/bin/python packaging/generate_brand_assets.py
.build-venv/bin/python packaging/collect_licenses.py
if [[ -z "${CHURCHBOARD_PRODMESH_RTA_BUNDLE:-}" ]]; then
  for candidate in "$PROJECT_DIR/build/prodmesh-rta/ProdMeshRemoteRTA.app" "$PROJECT_DIR/vendor/prodmesh-rta/ProdMeshRemoteRTA.app"; do
    if [[ -d "$candidate" ]]; then export CHURCHBOARD_PRODMESH_RTA_BUNDLE="$candidate"; break; fi
  done
fi
.build-venv/bin/pyinstaller packaging/ChurchBoard.spec --noconfirm --clean

VERSION="$("$PYTHON_BIN" -c 'from app.version import __version__; print(__version__)')"
ARCH="$(uname -m)"
APP_PATH="$PROJECT_DIR/dist/ChurchBoard.app"
DMG_PATH="$PROJECT_DIR/dist/ChurchBoard-${VERSION}-macOS-${ARCH}.dmg"

PACKAGE_STAGE="$(/usr/bin/mktemp -d /private/tmp/churchboard-package.XXXXXX)"
TEMP_KEYCHAIN=""
cleanup_package_stage() {
  if [[ -n "$TEMP_KEYCHAIN" ]]; then
    /usr/bin/security delete-keychain "$TEMP_KEYCHAIN" >/dev/null 2>&1 || true
  fi
  /bin/rm -rf "$PACKAGE_STAGE"
}
trap cleanup_package_stage EXIT

SIGNING_IDENTITY="${MACOS_SIGNING_IDENTITY:-}"
if [[ -n "${MACOS_CERTIFICATE_P12_BASE64:-}" ]]; then
  CERTIFICATE_PATH="$PACKAGE_STAGE/developer-id.p12"
  TEMP_KEYCHAIN="$PACKAGE_STAGE/churchboard-build.keychain-db"
  KEYCHAIN_PASSWORD="${MACOS_KEYCHAIN_PASSWORD:-churchboard-ci-keychain}"
  /usr/bin/printf '%s' "$MACOS_CERTIFICATE_P12_BASE64" | /usr/bin/base64 -D > "$CERTIFICATE_PATH"
  /usr/bin/security create-keychain -p "$KEYCHAIN_PASSWORD" "$TEMP_KEYCHAIN"
  /usr/bin/security set-keychain-settings -lut 21600 "$TEMP_KEYCHAIN"
  /usr/bin/security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$TEMP_KEYCHAIN"
  /usr/bin/security import "$CERTIFICATE_PATH" -P "${MACOS_CERTIFICATE_PASSWORD:-}" -A -t cert -f pkcs12 -k "$TEMP_KEYCHAIN"
  /usr/bin/security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$TEMP_KEYCHAIN"
  /usr/bin/security list-keychains -d user -s "$TEMP_KEYCHAIN"
  SIGNING_IDENTITY="$(/usr/bin/security find-identity -v -p codesigning "$TEMP_KEYCHAIN" | /usr/bin/awk -F'"' '/Developer ID Application/{print $2; exit}')"
  if [[ -z "$SIGNING_IDENTITY" ]]; then
    echo "No Developer ID Application identity was found in the supplied certificate." >&2
    exit 1
  fi
fi

STAGED_APP="$PACKAGE_STAGE/ChurchBoard.app"
/usr/bin/ditto --norsrc --noextattr --noacl "$APP_PATH" "$STAGED_APP"
/usr/bin/xattr -cr "$STAGED_APP"
/usr/bin/find "$STAGED_APP" -name '._*' -delete
if [[ -n "$SIGNING_IDENTITY" ]]; then
  /usr/bin/codesign --force --deep --options runtime --timestamp --sign "$SIGNING_IDENTITY" "$STAGED_APP"
else
  /usr/bin/codesign --force --deep --sign - "$STAGED_APP"
fi
/usr/bin/codesign --verify --deep --strict "$STAGED_APP"
/usr/bin/xattr -cr "$STAGED_APP"
/usr/bin/find "$STAGED_APP" -name '._*' -delete

HTTPS_INSTALLER="$PACKAGE_STAGE/Enable HTTPS.command"
/usr/bin/ditto "$PROJECT_DIR/installers/macos/Enable HTTPS.command" "$HTTPS_INSTALLER"
/bin/chmod +x "$HTTPS_INSTALLER"

.build-venv/bin/dmgbuild \
  -s "$PROJECT_DIR/packaging/dmg-settings.py" \
  -D "app=$STAGED_APP" \
  -D "background=$PROJECT_DIR/packaging/assets/dmg-background.png" \
  -D "icon=$PROJECT_DIR/packaging/assets/ChurchBoard.icns" \
  -D "https_installer=$HTTPS_INSTALLER" \
  "ChurchBoard ${VERSION}" "$PACKAGE_STAGE/ChurchBoard.dmg"
COPYFILE_DISABLE=1 /bin/cp "$PACKAGE_STAGE/ChurchBoard.dmg" "$DMG_PATH"

if [[ -n "${MACOS_NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
  /usr/bin/xcrun notarytool submit "$DMG_PATH" --keychain-profile "$MACOS_NOTARY_KEYCHAIN_PROFILE" --wait
  /usr/bin/xcrun stapler staple "$DMG_PATH"
  /usr/bin/xcrun stapler validate "$DMG_PATH"
elif [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
  /usr/bin/xcrun notarytool submit "$DMG_PATH" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD" --wait
  /usr/bin/xcrun stapler staple "$DMG_PATH"
  /usr/bin/xcrun stapler validate "$DMG_PATH"
elif [[ -n "$SIGNING_IDENTITY" ]]; then
  echo "Developer ID signing completed, but notarization credentials were not supplied." >&2
fi

echo "Built:"
echo "  $DMG_PATH"
