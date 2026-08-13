#!/bin/zsh
set -euo pipefail

APP="/Applications/ChurchBoard.app"
if [[ ! -x "$APP/Contents/MacOS/ChurchBoard" ]]; then
  /usr/bin/osascript -e 'display alert "Install ChurchBoard first" message "Drag ChurchBoard into Applications, then run Enable HTTPS again." as critical'
  exit 1
fi

"$APP/Contents/MacOS/ChurchBoard" --install-https
/usr/bin/osascript -e 'tell application "ChurchBoard" to quit' >/dev/null 2>&1 || true
/bin/sleep 1
/bin/launchctl kickstart -k "gui/$(/usr/bin/id -u)/org.churchboard.app" >/dev/null 2>&1 || true
/usr/bin/osascript -e 'display dialog "HTTPS is enabled. ChurchBoard has been restarted and will now use https:// links. This Mac trusts the new certificate." buttons {"Open ChurchBoard"} default button 1 with title "ChurchBoard HTTPS"'
/usr/bin/open -a ChurchBoard
