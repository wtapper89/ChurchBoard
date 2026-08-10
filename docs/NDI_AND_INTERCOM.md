# NDI video and Producer intercom

These beta features are optional. ChurchBoard continues to run normally when neither is configured.

## NDI® video

ChurchBoard dynamically loads the NDI runtime and discovers sources on the production network. It does not require NDI Tools. In **Setup → NDI video**, enable NDI, select **Save & find NDI sources**, then add an **NDI video** widget and choose the advertised source name.

### Install the NDI SDK

1. Open the **[official NDI SDK download page](https://ndi.video/for-developers/ndi-sdk/download/)**. Complete NDI's download form, choose Windows, macOS, or Linux, and use the link NDI sends you.
2. Run the downloaded installer and accept NDI's SDK license. On macOS, keep the default `/Library/NDI SDK for Apple` location. On Windows, the standard SDK location is `C:\Program Files\NDI\NDI 6 SDK`. On Linux, follow the README/install script included with the SDK archive.
3. Restart ChurchBoard after installation. Leave **NDI SDK or runtime location** blank and use **Save & find NDI sources**; ChurchBoard now checks the standard SDK and runtime locations automatically.
4. If you used a custom install location, paste either the SDK's top-level folder, its `lib` folder, or the runtime file itself. For example, `/Library/NDI SDK for Apple` is sufficient—there is no need to locate `lib/macOS/libndi.dylib` manually.

The setup status deliberately reports two separate results:

- **Runtime found** means the SDK/runtime installed correctly and ChurchBoard loaded it.
- **No sources advertised yet** means installation is working, but no sender is visible. Enable NDI output in ProPresenter or another sender, place both devices on the same LAN/VLAN, and check multicast or Discovery Server configuration.

See NDI's [SDK documentation](https://docs.ndi.video/all/developing-with-ndi/sdk) for installation and platform details. Open-source builds can use dynamic loading without committing NDI binaries to this repository. A release builder who is authorized to redistribute the runtime can set `CHURCHBOARD_BUNDLE_NDI_RUNTIME=1` and `CHURCHBOARD_NDI_RUNTIME_DIR=/path/to/runtime` before packaging. The build refuses to bundle it unless the required NDI license notice is present, and keeps both files inside ChurchBoard's private `ndi-runtime` folder.

Source discovery depends on multicast visibility between the ChurchBoard computer and the NDI sender. VLANs commonly require an NDI Discovery Server or network configuration beyond ChurchBoard.

NDI® is a registered trademark of Vizrt NDI AB. See the [NDI licensing documentation](https://docs.ndi.video/all/developing-with-ndi/sdk/licensing) before distributing a build with the runtime.

## ChurchBoard-hosted Producer intercom

ChurchBoard includes and manages its own open-source LiveKit server for WebRTC audio. A church does not need a LiveKit Cloud account, another computer, Docker, a WebSocket URL, an API key, or a manually configured secret.

1. In **Setup → Producer intercom**, enable the ChurchBoard-hosted intercom.
2. List one party-line name per line. A new installation starts with **Production**.
3. Save. ChurchBoard generates private credentials, starts the audio engine, and reports when it is ready.
4. Open the Producer workspace, choose a channel, and select **Join**.
5. Hold **Push to talk**, or turn on **Lock mic open**. Administrators can select **Close all mics** to mute every connected ChurchBoard client.

The signaling connection is proxied through the same ChurchBoard HTTP/HTTPS address used by the Producer workspace. The private LiveKit signaling listener stays on the ChurchBoard computer. Browsers receive a short-lived, room-scoped token; the generated API secret never leaves ChurchBoard. Administrator mute-all commands are accepted only when the sender's signed participant metadata identifies an administrator.

Mobile Safari and Chrome allow microphone access only in a secure context. Use ChurchBoard's HTTPS settings or an HTTPS reverse proxy; plain HTTP on another computer or phone cannot use the intercom microphone.

On the production LAN, allow ChurchBoard through the operating-system firewall. The hosted engine uses TCP `7881` as a WebRTC fallback and UDP `7882` for encrypted media. The HTTP/WebSocket signaling connection uses ChurchBoard's normal dashboard or Producer-workspace port. Remote use across the public internet still requires professional TLS, TURN, firewall, and network design; the automatic hosted mode is designed first for devices on the same church production network.

ChurchBoard vendors the Apache-2.0-licensed [LiveKit](https://github.com/livekit/livekit) server and JavaScript client so the Producer workspace does not depend on a cloud media service during a service.
