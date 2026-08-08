<p align="center">
  <img src="app/static/churchboard-logo.png" alt="ChurchBoard wooden church announcement board logo" width="190">
</p>

![Complete ChurchBoard main dashboard with color-matched glass widgets](docs/screenshots/main-dashboard-complete.jpg)

<h1 align="center">ChurchBoard</h1>

ChurchBoard is a cross-platform production dashboard for churches. It combines Planning Center schedules and people, ProPresenter slides and service flow, Shure QLX-D/ULX-D/SLX-D and Sennheiser EW-DX microphone telemetry, Open Sound Meter levels, OBS Studio health, and Restream broadcast status in configurable displays for the stage, green room, audio booth, and production team.

> **Producer-platform beta:** The `beta/producer-platform` branch adds organization accounts and roles, campuses, Planning Center position checklists and tagged-media resources, completion/activity tracking, portable dashboard layouts, a modal widget editor with direct resize handles, configurable HTTP/HTTPS, and mobile layouts. See the [Producer workspace beta guide](docs/PRODUCER.md).

## Watch the setup and demo video

See ChurchBoard in action and follow the setup walkthrough in the **[ChurchBoard setup and demo video](https://youtu.be/pE_uWD24G2c)**.

[![Watch the ChurchBoard setup and demo video on YouTube](https://img.youtube.com/vi/pE_uWD24G2c/maxresdefault.jpg)](https://youtu.be/pE_uWD24G2c)


## What ChurchBoard shows

- Photo-forward scheduled-position and microphone cards, including unassigned positions and a per-widget choice between one card per person or one card per position
- Shure QLX-D/ULX-D/SLX-D and Sennheiser EW-DX battery, RF/audio, transmitter, mute, warning, and online/offline status
- Current and next ProPresenter slides as text or slide images, with live countdown overlays and video playback progress
- A scrollable ProPresenter playlist that shows every playlist item, placeholder, presentation, section marker, and slide thumbnail; trusted operators can trigger a presentation or individual slide from ChurchBoard
- Optional live-board slide controls and keyboard control for ProPresenter, with corrected current-slide thumbnails and Planning Center-linked item matching
- A read-only ProPresenter timers widget showing each timer's current value and state
- ProPresenter item title, part labels and colors, slide number, and notes
- Compact, complete scrollable, or fit-to-board Planning Center orders of service—including pre-service and post-service sections—with durations, estimated clock times, leaders, and mapped microphones
- Current item and overall service timing
- Team-member lists with photos, filtered by team and position
- Direct Open Sound Meter monitoring with selectable weighting/response and downloadable service graphs and per-item averages
- Restream broadcast, viewer, and destination-status monitoring through OAuth
- OBS Studio streaming/recording state, connection health, output statistics, dropped-frame warnings, and an optional preview image
- Planning Center Services LIVE control buttons
- A WYSIWYG dashboard editor with independent layouts and color-matched liquid-glass widgets for each destination
- Exportable/importable dashboard layout files and a categorized widget palette with gear/right-click modal settings and direct edge/corner resizing
- A multi-provider livestream status widget with Facebook/YouTube channel URLs and independent BoxCast, Resi, and Restream API configuration
- A dedicated ProPresenter control pad for previous/next slide and previous/next playlist item
- A mobile-friendly producer workspace for position checklists, files, links, team access, campuses, and an activity trail *(producer-platform beta)*

![ChurchBoard audio-board dashboard](docs/screenshots/audio-board.jpg)


## Download ChurchBoard

Choose your computer and click its download link:

| Your computer | Download |
| --- | --- |
| **Windows 10 or 11** | **[Download the Windows installer (.exe)](https://github.com/wtapper89/ChurchBoard/releases/latest/download/ChurchBoard-1.3.3-Windows-x64-Setup.exe)** |
| **Mac with Apple silicon** — M1 or newer | **[Download the Apple silicon Mac disk image (.dmg)](https://github.com/wtapper89/ChurchBoard/releases/latest/download/ChurchBoard-1.3.3-macOS-arm64.dmg)** |
| **Mac with an Intel processor** | **[Download the Intel Mac disk image (.dmg)](https://github.com/wtapper89/ChurchBoard/releases/latest/download/ChurchBoard-1.3.3-macOS-x86_64.dmg)** |
| **Ubuntu or Debian Linux** | **[Download the Linux installer (.deb)](https://github.com/wtapper89/ChurchBoard/releases/latest/download/ChurchBoard-1.3.3-Linux-amd64.deb)** |
| **Other 64-bit desktop Linux** | **[Download the portable Linux package (.tar.gz)](https://github.com/wtapper89/ChurchBoard/releases/latest/download/ChurchBoard-1.3.3-Linux-x86_64.tar.gz)** |

Not sure which Mac you have? Choose **Apple menu → About This Mac**. If it says **Chip**, use Apple silicon. If it says **Processor**, use Intel.

**Raspberry Pi:** jump to the [one-command Raspberry Pi installer](#raspberry-pi).

[View all v1.3.3 downloads and release notes](https://github.com/wtapper89/ChurchBoard/releases/tag/v1.3.3)

### What's new in 1.3.3

- Deleting the optional ProPresenter Playlist widget now keeps it deleted on every dashboard.
- The live Playlist widget's **Slide controls** and **Arrow keys** settings use larger, clearer toggle switches.

## Install

Every desktop installer configures ChurchBoard to start automatically. Opening ChurchBoard from the Start menu, Applications folder, or desktop menu opens its desktop control page in the default browser.

On macOS, the supplied old-school wooden board icon stays in the menu bar. On Windows, it stays in the system tray. Its menu opens the desktop control page, Setup, or any configured board and can quit ChurchBoard. The desktop control page also checks GitHub for updates and opens the correct installer for the computer.

### Raspberry Pi

For Raspberry Pi OS:

```bash
curl -fsSL https://raw.githubusercontent.com/wtapper89/ChurchBoard/main/installers/raspberry-pi/install.sh | bash
```

Add `--kiosk` to open the Main dashboard fullscreen after desktop login:

```bash
curl -fsSL https://raw.githubusercontent.com/wtapper89/ChurchBoard/main/installers/raspberry-pi/install.sh | bash -s -- --kiosk
```

See [Installation](docs/INSTALLATION.md) for detailed steps, updates, automatic-start behavior, and uninstall instructions.

## First-time setup

Open `http://127.0.0.1:8040/admin`, turn off demonstration data, and configure Planning Center first. ChurchBoard stores settings only on the computer running it.

![ChurchBoard integrations setup](docs/screenshots/setup.jpg)

Start with [Configuration](docs/CONFIGURATION.md), then follow the detailed [Planning Center setup](docs/PLANNING_CENTER.md), [ProPresenter setup](docs/PROPRESENTER.md), [Open Sound Meter setup](docs/OPEN_SOUND_METER.md), and [Restream setup](docs/RESTREAM.md) guides. They cover secure credentials, permissions, photos, leaders, linked service playlists, the Network API, Services LIVE automation, dashboards, microphone mapping, level reporting, livestream monitoring, and troubleshooting.

## Dashboard editing

Each dashboard has a stable URL. Add widgets from the palette, drag them on the canvas, and resize from the blue right edge, bottom edge, or corner. A gear or right-click opens modal settings, leaving the full editor width for the board. Every widget title can be hidden. Scheduled-position widgets can consolidate multiple roles into one card per person or retain one card per position. The ProPresenter playlist widget shows the focused playlist as a continuous, automatically scrolling list, including placeholders and all presentation slides; choose compact, comfortable, or large density and an active-slide border color. An optional per-board keyboard mode sends Left/Up to the previous ProPresenter cue and Right/Down/Space to the next cue. A separate control widget provides previous/next slide and item buttons. Order-of-service widgets can show a compact current window, a scrollable complete plan, or the complete plan fitted to the widget. Text, cards, photos, and status displays scale with their widget and stack into readable cards on narrow mobile screens. Setup can cancel a new dashboard before it is named, and the editor includes a confirmation-protected **Delete display** action. The display hamburger includes an **Edit** action beside every board, and **Open display** in the editor reuses the current tab.

![ChurchBoard WYSIWYG dashboard editor](docs/screenshots/dashboard-editor.jpg)

## Credits, licenses, and legal

ChurchBoard's visual microphone-monitoring direction was inspired by [Micboard](https://micboard.io/) by Karl Swanson, an independent MIT-licensed project for network-enabled Shure devices. The initial cross-platform dashboard concept also drew inspiration from [NewsTalentMonitorPlus](https://github.com/wtapper89/NewsTalentMonitorPlus). ChurchBoard is a separate implementation and does not bundle either project's code or assets.

Special thanks to [Caleb Hines (@WorshipWarehouse)](https://github.com/WorshipWarehouse) for the ChurchBoard 1.3 integration and dashboard contributions, including Open Sound Meter, Restream, OBS Studio, scheduled-person consolidation, complete service-order display modes, Sennheiser EW-DX and Shure SLX-D monitoring, ProPresenter playlist control and timers, dashboard lifecycle controls, and responsive fullscreen improvements. The original commits and authorship are preserved in the project history. See [Contributors](CONTRIBUTORS.md).

The people shown in demonstration mode and documentation are AI-generated fictional samples, not real team members. ChurchBoard is independently developed and is not affiliated with or endorsed by Planning Center, Shure, Renewed Vision/ProPresenter, Micboard, Apple, Microsoft, or Raspberry Pi.

See the [MIT License](LICENSE), [legal and trademark notices](LEGAL.md), [third-party dependency notices](THIRD_PARTY_NOTICES.md), and [security guidance](SECURITY.md).

## Local development

ChurchBoard requires Python 3.11 or newer:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Manual startup opens Setup automatically. Use `python run.py --background` for a headless service.

Run tests with:

```bash
python -m unittest discover -s tests
```

See [Development and release builds](docs/DEVELOPMENT.md) for platform build commands and release automation.

## Security

Planning Center credentials remain in the local ChurchBoard data directory and are excluded from Git. The producer-platform beta provides local accounts, role-based access, secure session cookies, and direct HTTPS certificate support. Keep ChurchBoard on a trusted production network and read [SECURITY.md](SECURITY.md) before allowing remote access.
