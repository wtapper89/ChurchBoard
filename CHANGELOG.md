# Changelog

## 2.0.11

- ProPresenter polling limits concurrent presentation requests and tolerates optional endpoint failures. The playlist widget displays the live presentation and its slides when playing directly from the Library.
- Planning Center Services LIVE navigation skips section headers when counting steps, preventing the target from being overshot (#43). Matching prefers normalized titles, accepts close matches, and can infer a single item between two matched playlist neighbors.
- Added read-only monitoring for Sennheiser EM 300–500 G4 receivers on firmware 1.7.0 and newer (#42). EM 100 G4 is outside the documented Ethernet protocol.
- Added fader and mute support for Allen & Heath Avantis, dLive and SQ, and read-only Yamaha CL/QL/TF support. See [Audio consoles](docs/CONSOLE_INTEGRATIONS.md) for model-specific capabilities. Physical verification of the new hardware integrations is pending.
- Both microphone card styles show battery percentage and a tall, thin trace of recent receiver audio levels by default. Demonstration mode provides animated examples and can be toggled without losing its sample microphones.
- Core Settings accepts PNG, JPEG and WebP uploads up to 1 MB as the default icon for unassigned photo cards. Widgets that select a Planning Center media item continue to prefer it.
- Order of Service can display the Planning Center Description beneath each item title. Deleting the Audio Board's SPL meter now persists across reloads.
- Bundled builds retain the certificate policy file required by the Python runtime when present, fixing HTTPS startup for the local beta.

Console protocol code is adapted from [ProDeck](https://github.com/whiteoakmedia/prodeck) by Zach Green and White Oak Media under the MIT License. [Slide-Desk](https://github.com/gavinpep98/Slide-Desk) informed behavior and [Micboard](https://micboard.io/) by Karl Swanson inspired the mic display. See [third-party notices](THIRD_PARTY_NOTICES.md) and the [ProDeck license](licenses/PRODECK.txt).
