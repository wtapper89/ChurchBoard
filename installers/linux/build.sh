#!/usr/bin/env bash
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
.build-venv/bin/python packaging/collect_licenses.py
if [[ -z "${CHURCHBOARD_PRODMESH_RTA_BUNDLE:-}" && -x "$PROJECT_DIR/build/prodmesh-rta/ProdMeshRemoteRTA" ]]; then
  export CHURCHBOARD_PRODMESH_RTA_BUNDLE="$PROJECT_DIR/build/prodmesh-rta"
fi
.build-venv/bin/pyinstaller packaging/ChurchBoard.spec --noconfirm --clean

VERSION="$("$PYTHON_BIN" -c 'from app.version import __version__; print(__version__)')"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) DEB_ARCH="amd64" ;;
  aarch64|arm64) DEB_ARCH="arm64" ;;
  *) DEB_ARCH="$ARCH" ;;
esac

ARCHIVE_STAGE="$PROJECT_DIR/build/churchboard-linux"
/bin/rm -rf "$ARCHIVE_STAGE"
/bin/mkdir -p "$ARCHIVE_STAGE"
/bin/cp "$PROJECT_DIR/dist/ChurchBoard" "$ARCHIVE_STAGE/"
/bin/cp "$PROJECT_DIR/installers/linux/install.sh" "$ARCHIVE_STAGE/"
/bin/cp "$PROJECT_DIR/installers/linux/uninstall.sh" "$ARCHIVE_STAGE/"
/bin/cp "$PROJECT_DIR/app/static/churchboard-icon.png" "$ARCHIVE_STAGE/"
/bin/cp "$PROJECT_DIR/LICENSE" "$PROJECT_DIR/LEGAL.md" "$PROJECT_DIR/THIRD_PARTY_NOTICES.md" "$ARCHIVE_STAGE/"
/bin/cp -R "$PROJECT_DIR/build/legal" "$ARCHIVE_STAGE/legal"
/bin/chmod +x "$ARCHIVE_STAGE/ChurchBoard" "$ARCHIVE_STAGE/install.sh" "$ARCHIVE_STAGE/uninstall.sh"
/usr/bin/tar -C "$ARCHIVE_STAGE" -czf "$PROJECT_DIR/dist/ChurchBoard-${VERSION}-Linux-${ARCH}.tar.gz" .

DEB_ROOT="$PROJECT_DIR/build/churchboard-deb"
/bin/rm -rf "$DEB_ROOT"
/bin/mkdir -p "$DEB_ROOT/DEBIAN" "$DEB_ROOT/opt/churchboard" "$DEB_ROOT/lib/systemd/system" "$DEB_ROOT/usr/share/applications" "$DEB_ROOT/usr/share/icons/hicolor/512x512/apps" "$DEB_ROOT/usr/share/doc/churchboard"
/bin/cp "$PROJECT_DIR/dist/ChurchBoard" "$DEB_ROOT/opt/churchboard/ChurchBoard"
/bin/cp "$PROJECT_DIR/installers/linux/churchboard.service" "$DEB_ROOT/lib/systemd/system/churchboard.service"
/bin/cp "$PROJECT_DIR/installers/linux/churchboard.desktop" "$DEB_ROOT/usr/share/applications/churchboard.desktop"
/bin/cp "$PROJECT_DIR/app/static/churchboard-icon.png" "$DEB_ROOT/usr/share/icons/hicolor/512x512/apps/churchboard.png"
/bin/cp "$PROJECT_DIR/installers/linux/debian/postinst" "$DEB_ROOT/DEBIAN/postinst"
/bin/cp "$PROJECT_DIR/installers/linux/debian/prerm" "$DEB_ROOT/DEBIAN/prerm"
/bin/cp "$PROJECT_DIR/LICENSE" "$PROJECT_DIR/LEGAL.md" "$PROJECT_DIR/THIRD_PARTY_NOTICES.md" "$DEB_ROOT/usr/share/doc/churchboard/"
/bin/cp -R "$PROJECT_DIR/build/legal/third-party" "$DEB_ROOT/usr/share/doc/churchboard/third-party"
/bin/chmod 0755 "$DEB_ROOT/opt/churchboard/ChurchBoard" "$DEB_ROOT/DEBIAN/postinst" "$DEB_ROOT/DEBIAN/prerm"

/bin/cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: churchboard
Version: $VERSION
Section: sound
Priority: optional
Architecture: $DEB_ARCH
Maintainer: ChurchBoard
Depends: xdg-utils
Description: Church production dashboard
 Planning Center, ProPresenter, and Shure monitoring dashboards for churches.
EOF

/usr/bin/dpkg-deb --build --root-owner-group "$DEB_ROOT" "$PROJECT_DIR/dist/ChurchBoard-${VERSION}-Linux-${DEB_ARCH}.deb"
echo "Built Linux archive and Debian package in dist/."
