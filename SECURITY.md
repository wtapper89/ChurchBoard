# Security

ChurchBoard can run a restricted second listener for volunteers. It exposes the Producer/checklist workflow but rejects dashboard, editor, desktop-control, and Setup routes. This reduces accidental access; it is not a substitute for network isolation, role-based sign-in, or HTTPS.

Planning Center tagged media is mirrored under the ChurchBoard data directory so volunteers do not need Planning Center access. Those files may contain sensitive production material and should be protected and backed up with the same care as `churchboard.json`. Files are deleted from the mirror after a complete Planning Center refresh confirms that they are no longer tagged.

ChurchBoard generates a private API key and secret for its bundled LiveKit intercom engine, stores them locally, and redacts them from the settings API. ChurchBoard issues short-lived room tokens only to authenticated users. The intercom's signaling connection stays on the ChurchBoard HTTP/HTTPS origin; media uses TCP `7881` and UDP `7882` on the ChurchBoard host. Restrict those ports to the trusted production LAN, and use HTTPS for the Producer workspace so mobile browsers permit microphone access.

## Intended deployment

ChurchBoard is intended for a trusted church production LAN. The primary listener defaults to port `8040` for dashboards and configuration. The optional restricted Producer listener defaults to port `80`. ChurchBoard provides local role-based accounts and can terminate HTTPS when certificate and private-key paths are configured.

Public dashboards on the primary listener do not require sign-in. Do not expose either listener directly to the public internet. Use network segmentation and firewall rules to restrict access to authorized production devices, use HTTPS for credentials and browser microphone access, and prefer a maintained reverse proxy when ChurchBoard must cross a network trust boundary.

## Credentials

Planning Center Personal Access Token credentials are stored in ChurchBoard's local data file with owner-restricted permissions. The file is ignored by Git:

- source/development: `data/churchboard.json`
- Windows and macOS packaged app: `~/.churchboard/churchboard.json`
- Linux user installer and Raspberry Pi: the installer's `data` directory
- Debian package: `/var/lib/churchboard/churchboard.json`

Protect backups of those locations. Revoke the token in Planning Center if a ChurchBoard computer or backup is lost.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose credentials or control a production service. Contact the repository owner privately with a description, affected version, reproduction steps, and any proposed mitigation.
