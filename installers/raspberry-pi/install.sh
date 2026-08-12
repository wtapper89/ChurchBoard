#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${CHURCHBOARD_REPOSITORY:-wtapper89/ChurchBoard}"
REF="${CHURCHBOARD_REF:-main}"
LIVEKIT_VERSION="1.13.5"
PRODMESH_RTA_REF="ffd8ee2adfa0fcedc9bb846aa1e6a142eda04c06"
ENABLE_KIOSK=false

usage() {
  cat <<'EOF'
Install ChurchBoard on Raspberry Pi OS.

Usage:
  install.sh [--kiosk] [--ref BRANCH_OR_TAG]

Options:
  --kiosk       Open the Main dashboard fullscreen after desktop login.
  --ref VALUE   Install a specific Git branch or tag (default: main).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kiosk) ENABLE_KIOSK=true; shift ;;
    --ref) REF="${2:?--ref requires a branch or tag}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run this installer as your normal Raspberry Pi desktop user, not root." >&2
  exit 1
fi

for command in sudo curl tar python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "$command is required." >&2
    exit 1
  fi
done

echo "Installing Raspberry Pi prerequisites…"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip curl ca-certificates git cmake ninja-build qt6-base-dev qt6-multimedia-dev libgl1-mesa-dev libpulse-dev

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
LOCAL_PROJECT="$(cd "$SCRIPT_DIR/../.." 2>/dev/null && pwd || true)"
TEMP_DIR=""
if [[ -n "$LOCAL_PROJECT" && -f "$LOCAL_PROJECT/app/main.py" ]]; then
  SOURCE_DIR="$LOCAL_PROJECT"
else
  TEMP_DIR="$(mktemp -d)"
  trap '[[ -n "${TEMP_DIR:-}" ]] && /bin/rm -rf "$TEMP_DIR"' EXIT
  SOURCE_DIR="$TEMP_DIR/source"
  mkdir -p "$SOURCE_DIR"
  echo "Downloading ChurchBoard $REF from GitHub…"
  if ! curl -fsSL "https://github.com/$REPOSITORY/archive/refs/heads/$REF.tar.gz" | tar -xz -C "$SOURCE_DIR" --strip-components=1; then
    curl -fsSL "https://github.com/$REPOSITORY/archive/refs/tags/$REF.tar.gz" | tar -xz -C "$SOURCE_DIR" --strip-components=1
  fi
fi

BASE_DIR="$HOME/.local/share/churchboard"
INSTALL_DIR="$BASE_DIR/app"
DATA_DIR="$BASE_DIR/data"
BACKUP_DIR="$BASE_DIR/app.previous"
mkdir -p "$BASE_DIR" "$DATA_DIR"
if [[ -d "$INSTALL_DIR" ]]; then
  /bin/rm -rf "$BACKUP_DIR"
  /bin/mv "$INSTALL_DIR" "$BACKUP_DIR"
fi

restore_previous_install() {
  if [[ -d "$BACKUP_DIR" ]]; then
    /bin/rm -rf "$INSTALL_DIR"
    /bin/mv "$BACKUP_DIR" "$INSTALL_DIR"
    echo "The previous ChurchBoard installation was restored." >&2
  fi
}

mkdir -p "$INSTALL_DIR"
/bin/cp -R "$SOURCE_DIR/app" "$SOURCE_DIR/run.py" "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/"

echo "Building ChurchBoard's embedded ProdMesh RTA engine…"
PRODMESH_SOURCE="$(mktemp -d)"
git clone https://github.com/jbeale/prodmesh-rta.git "$PRODMESH_SOURCE"
git -C "$PRODMESH_SOURCE" checkout "$PRODMESH_RTA_REF"
cmake -S "$PRODMESH_SOURCE" -B "$PRODMESH_SOURCE/build" -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build "$PRODMESH_SOURCE/build"
mkdir -p "$INSTALL_DIR/prodmesh-rta/Qt-LICENSES"
install -m 0755 "$PRODMESH_SOURCE/build/ProdMeshRemoteRTA" "$INSTALL_DIR/prodmesh-rta/ProdMeshRemoteRTA"
cp /usr/share/doc/qt6-base-dev/copyright "$INSTALL_DIR/prodmesh-rta/Qt-LICENSES/qt6-base-copyright"
cp /usr/share/doc/qt6-multimedia-dev/copyright "$INSTALL_DIR/prodmesh-rta/Qt-LICENSES/qt6-multimedia-copyright"
install -m 0644 "$SOURCE_DIR/packaging/licenses/prodmesh-rta.LICENSE" "$INSTALL_DIR/prodmesh-rta/LICENSE"
/bin/rm -rf "$PRODMESH_SOURCE"

case "$(uname -m)" in
  aarch64|arm64) LIVEKIT_ARCH="arm64"; LIVEKIT_SHA256="332015305518765fe05bad74fc3a9d9583e635e7dd130de3c4fc563d69c550f3" ;;
  armv7l|armv7) LIVEKIT_ARCH="armv7"; LIVEKIT_SHA256="6dceb15fec3b2b90a67615acff7f92a48a901408f31c74f3d290a7d4277f76bd" ;;
  x86_64|amd64) LIVEKIT_ARCH="amd64"; LIVEKIT_SHA256="c020fac437b7cc9b776eef1ad5ea8af77be9acfa07602eca20a3a44930dfbc70" ;;
  *) LIVEKIT_ARCH=""; LIVEKIT_SHA256="" ;;
esac
if [[ -n "$LIVEKIT_ARCH" ]]; then
  echo "Installing ChurchBoard's hosted intercom engine…"
  LIVEKIT_ARCHIVE="$(mktemp)"
  curl -fsSL "https://github.com/livekit/livekit/releases/download/v${LIVEKIT_VERSION}/livekit_${LIVEKIT_VERSION}_linux_${LIVEKIT_ARCH}.tar.gz" -o "$LIVEKIT_ARCHIVE"
  echo "$LIVEKIT_SHA256  $LIVEKIT_ARCHIVE" | sha256sum --check --status
  mkdir -p "$INSTALL_DIR/livekit-server"
  tar -xzf "$LIVEKIT_ARCHIVE" -C "$INSTALL_DIR/livekit-server"
  /bin/rm -f "$LIVEKIT_ARCHIVE"
  chmod 0755 "$INSTALL_DIR/livekit-server/livekit-server"
else
  echo "Warning: no hosted intercom engine is published for $(uname -m). The rest of ChurchBoard will still work." >&2
fi

if ! python3 -m venv "$INSTALL_DIR/.venv"; then
  restore_previous_install
  exit 1
fi
if ! "$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip; then
  restore_previous_install
  exit 1
fi
if ! "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"; then
  restore_previous_install
  exit 1
fi
/bin/rm -rf "$BACKUP_DIR"

SERVICE_TEMP="$(mktemp)"
sed \
  -e "s|__USER__|$USER|g" \
  -e "s|__GROUP__|$(id -gn)|g" \
  -e "s|__HOME__|$HOME|g" \
  -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
  -e "s|__DATA_DIR__|$DATA_DIR|g" \
  "$SOURCE_DIR/installers/raspberry-pi/churchboard.service.in" > "$SERVICE_TEMP"
sudo install -m 0644 "$SERVICE_TEMP" /etc/systemd/system/churchboard.service
/bin/rm -f "$SERVICE_TEMP"
sudo systemctl daemon-reload
sudo systemctl enable --now churchboard.service

if [[ "$ENABLE_KIOSK" == "true" ]]; then
  echo "Installing Chromium kiosk startup…"
  if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
    sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser
  fi
  mkdir -p "$HOME/.local/bin" "$HOME/.config/autostart"
  install -m 0755 "$SOURCE_DIR/installers/raspberry-pi/churchboard-kiosk.sh" "$HOME/.local/bin/churchboard-kiosk"
  install -m 0644 "$SOURCE_DIR/installers/raspberry-pi/churchboard-kiosk.desktop" "$HOME/.config/autostart/churchboard-kiosk.desktop"
fi

PI_ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "ChurchBoard is installed and starts automatically at boot."
echo "Setup on this Pi: http://127.0.0.1:8040/admin"
if [[ -n "$PI_ADDRESS" ]]; then
  echo "Setup from another computer: http://$PI_ADDRESS:8040/admin"
fi
if [[ "$ENABLE_KIOSK" == "true" ]]; then
  echo "Kiosk mode will open after the next desktop login."
fi
