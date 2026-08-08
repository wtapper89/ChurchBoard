# Configuring ChurchBoard

For a guided walkthrough, watch the **[ChurchBoard setup and demo video](https://youtu.be/pE_uWD24G2c)**.

Open `http://127.0.0.1:8040/admin`. Keep **Use demonstration data** enabled while learning the editor, then disable it before connecting production systems.

![ChurchBoard setup page](screenshots/setup.jpg)

## 1. Connect Planning Center

ChurchBoard currently uses a Planning Center Personal Access Token.

For a complete walkthrough—including a dedicated integration user, least-privilege roles, creating and protecting the token, profile photos, scheduled positions, and song/item leaders—see **[Planning Center setup](PLANNING_CENTER.md)**.

1. In Planning Center, open the developer Personal Access Token page for the account ChurchBoard should use.
2. Create a personal token and copy its **Application ID** and **Secret**.
3. In ChurchBoard Setup, enable **Planning Center** and paste both values.
4. Choose **Save & test connection**.
5. Check each service type ChurchBoard should consider.
6. Set the automatic plan window:
   - **Open days before** and **Open hours before** determine how early a plan becomes eligible.
   - **Close hours after** determines how long a plan stays eligible.
7. Choose **Save settings**.

The token user needs access to the selected Services plans. Viewer access is a reasonable starting point for a read-only board; Services LIVE control requires Editor access, while taking control from another controller can require Administrator access. Do not grant organization-administrator access just for ChurchBoard.

The service-type name and ID are saved together. If Planning Center temporarily cannot be reached, ChurchBoard retains the last saved display name instead of replacing it with a blank label.

## 2. Choose positions for a widget

1. From Setup, choose **Edit** for a dashboard.
2. Click the gear on a **Scheduled Positions & Mics** widget.
3. In the settings dialog, check the teams/categories to include, such as Band or Production.
4. Check the individual Planning Center positions to display.
5. Under **Cards represent**, choose **One card per person** or **One card per position**.
6. Drag positions into the desired display order.
7. Save the dashboard.

Every selected position appears even when no person or microphone is assigned. **One card per person** consolidates a person who holds several selected roles—such as vocals and guitar—into one card and lists all of that person's mapped microphone/equipment channels. **One card per position** keeps every selected role in its own card, so the same person can appear more than once. This choice is saved independently for each dashboard widget, allowing the green room and audio booth to use different views. An open Planning Center position displays **Unassigned**.

### Planning Center tagged documentation

Producer resources can come directly from Planning Center Services Media:

1. In Planning Center Services, create a Media tag group such as **Documentation**.
2. Add tags for roles or departments, such as **Audio**, **Lights**, and **Producer**.
3. Add or upload the desired media and apply the appropriate tags.
4. In ChurchBoard, open **Producer → Checklists & resources**.
5. Under **Planning Center tagged media**, choose a scheduled position and its corresponding media tag, then save.

ChurchBoard shows all media carrying that tag to the person scheduled in the mapped position. The Planning Center PAT account must have access to those Services Media items.

## 3. Add Shure microphones

ChurchBoard monitors networked Shure QLX-D, ULX-D, and SLX-D receivers through the Shure TCP control protocol.

1. Give each receiver a stable IP address or DHCP reservation.
2. In Setup, enable **Receiver monitoring**.
3. Choose **+ Add microphone**.
4. Choose the receiver family, then enter a friendly mic name such as `Red`, the receiver IP, and channel.
5. Choose the Planning Center position that uses that mic.
6. Repeat for up to ten displayed microphones, then save.

For an **SLX-D** receiver, open `Advanced Settings → Controller Access` on the receiver and select **Allow** before adding it to ChurchBoard. SLX-D blocks third-party command strings by default. It connects over TCP port **2202**, the same port used by QLX-D and ULX-D. ChurchBoard reads the channel name, battery bars, RF and audio meters, transmitter type, and frequency; it does not change receiver settings.

The photo card and compact audio card use status borders:

- green: transmitter on with battery above 10%;
- yellow: transmitter on with 5–10% battery;
- red: transmitter off, receiver unreachable, or battery below 5%.

Deleting a microphone removes its receiver mapping only. It does not change Planning Center schedules.

## 4. Add Sennheiser microphones

ChurchBoard also monitors Sennheiser EW-DX receivers through the legacy Sennheiser Sound Control Protocol (SSC). In **Settings**, add a microphone, choose **Sennheiser**, enter the receiver IP address and channel, then save. The default SSC UDP port is **45**.

Enable **3rd Party Access → Legacy** on the receiver before connecting it. Current support polls EW-DX SSCv1 telemetry: battery percentage and runtime, transmitter mute, RF quality/RSSI, AF level, carrier frequency, device model, firmware, and device warnings. EW-DX firmware 4.0 and later can use Sennheiser’s secured SSCv2 REST API, which is not yet supported by ChurchBoard; select Legacy mode for this integration.

## 5. Connect ProPresenter

For the complete linked-playlist workflow, recommended Planning Center integration settings, Network API setup, production checklist, and troubleshooting, see **[ProPresenter setup](PROPRESENTER.md)**.

1. In ProPresenter, enable the Network API.
2. Note the ProPresenter computer's local IP address and API port.
3. In ChurchBoard Setup, enable ProPresenter and enter both values.
4. Save settings.

In a ProPresenter widget, choose:

- **Text** or **Slide image** presentation;
- current slide, next slide, both, or neither;
- whether to show `Slide x of y`;
- item/playlist title and current/next part labels.

Part labels use their ProPresenter colors. Slide notes appear when enabled, and widget typography scales to keep long content visible.

## 6. Let ProPresenter drive Services LIVE

When ProPresenter is synced from a Planning Center plan, ChurchBoard can use the active presentation to control the corresponding Services LIVE item and timing.

1. Enable **Let ProPresenter drive Planning Center Services LIVE**.
2. Leave **Automatically take control when needed** enabled if ChurchBoard should claim LIVE control.
3. Leave **Prefer Planning Center song items for title matching** enabled.
4. Choose exact or smart fallback matching.
5. Set how long a presentation must remain active before ChurchBoard advances LIVE.

ChurchBoard first uses ProPresenter's Planning Center playlist/item ordering when available. It then uses normalized title matching, including non-song items such as `Message`, even when the presentation itself has a title like a Scripture reference.

## 7. Configure order of service

Select an **Order of service** widget in the editor to enable:

- compact current-item, complete scrollable, or complete fit-to-widget display;
- scheduled item duration;
- estimated wall-clock start time;
- song/item leader;
- the leader's mapped microphone.

For multiple service times, ChurchBoard uses the active service instance. Before the day's first service or during an early rehearsal, estimates start from the earliest scheduled service time.

## 8. Configure team members

Add a **Team members** widget, select Planning Center teams/categories, then choose the positions to include. Each row can show a circular photo, name, and position. Names and positions scale together so longer entries remain visible.

## 9. Use a custom unassigned icon

A Scheduled Positions & Mics widget uses a one-color ChurchBoard mark for an unassigned position by default. It can replace that mark with media stored in the active Planning Center plan.

1. Add a PNG or JPEG as a Planning Center plan media item.
2. Give the media item a recognizable title, such as `Icon`.
3. Select the assignment widget in ChurchBoard's editor.
4. Enable the custom unassigned icon and enter that media title.
5. Save.

The title is configurable per widget, so different dashboards can use different plan-media icons. ChurchBoard matches the title without regard to capitalization.

## 10. Connect Open Sound Meter

ChurchBoard can receive calibrated level data directly from [Open Sound Meter](https://opensoundmeter.com/) instead of measuring through the dashboard browser.

1. In Open Sound Meter, configure the audio interface, measurement microphone, and calibration.
2. Choose the Wi-Fi icon and enable **Remote API Server**.
3. Keep the Open Sound Meter and ChurchBoard computers on the same multicast-enabled network segment.
4. In ChurchBoard Setup, enable **Open Sound Meter monitoring**.
5. Select the measurement source, report weighting, and Fast or Slow response.
6. Optionally enable downloadable SPL graphs and Planning Center item averages.
7. Choose **Test OSM connection**, then add an **Open Sound Meter** widget to the desired board.

ChurchBoard displays Open Sound Meter's selected level after applying the same SPL reference used by Open Sound Meter. It does not calibrate, smooth, or synthesize the measurement. See the complete [Open Sound Meter setup and data notes](OPEN_SOUND_METER.md) and [legal and operational limitations](../LEGAL.md).

## 11. Connect Restream

Restream monitoring shows whether a broadcast is live or upcoming, its elapsed time and available viewer count, and the state of each configured destination.

1. Create a Restream API application and copy its **Client ID** and **Client Secret**.
2. Add the Redirect URI displayed in ChurchBoard Setup. It follows the current HTTP/HTTPS origin and configured port.
3. Grant only the read scopes needed for channels, streams/events, and viewer analytics.
4. In ChurchBoard Setup, enable **Restream monitoring** and enter both credentials.
5. Choose **Save & connect Restream**, authorize the account, and then test the connection.
6. Add a **Restream livestream** widget to any dashboard that needs broadcast visibility.

ChurchBoard stores the client secret and OAuth tokens only in its local settings. Encoder bitrate and health are not exposed by the Restream public API, so ChurchBoard labels those values unavailable instead of estimating them. See [Restream setup](RESTREAM.md).

For a compact multi-destination view, add **Livestream status** from the Audio & streaming palette and open its gear menu. Each provider is configured independently:

- **Facebook:** enter the church Page/channel URL. A public-page check is available; an API status endpoint and token are optional for more reliable monitoring.
- **YouTube:** enter the channel URL or handle URL. Optionally add a YouTube Data API key so ChurchBoard can use the official live-search API.
- **BoxCast:** enter the broadcast API URL, such as `https://api.boxcast.com/broadcasts/BROADCAST_ID`. Public broadcast endpoints need no token; authenticated account endpoints can use a bearer token.
- **Resi:** enter the API/status endpoint and bearer credential supplied for your Resi account or integration.
- **Restream:** ChurchBoard uses its connected Restream account for the Restream indicator, or you can provide a custom Restream status endpoint.

Use **Live status value** when an endpoint returns a vendor-specific word such as `broadcasting`. API credentials are protected only by the operating-system access controls on the ChurchBoard data directory, so use read-only, least-privilege keys. They are stored separately from dashboard layouts and are never sent through the public dashboard API. Public Facebook and YouTube pages can change or require sign-in; provider APIs are the preferred reliable source.

## 12. Connect OBS Studio

ChurchBoard can monitor OBS Studio through its built-in WebSocket server without requiring Studio Mode.

1. In OBS, open **Tools → WebSocket Server Settings**.
2. Enable the WebSocket server, set a strong password, and note the port (normally `4455`).
3. In ChurchBoard Setup, enable **OBS Studio monitoring** and enter the OBS computer's LAN address, port, and password.
4. Set the dropped-frame warning threshold. Optionally provide a browser-readable preview-image URL if another tool publishes one; OBS WebSocket itself does not provide a live preview image.
5. Save, then add an **OBS Studio** widget to an operator dashboard.

The widget reports connection, streaming and recording state, elapsed time, output bitrate/statistics, dropped frames, and the configured preview. Keep OBS and ChurchBoard on the same trusted production network and do not expose the WebSocket port to the internet.

## 13. Configure the web server

Open **Setup → Web server** to change the listening port or enable direct HTTPS. Supply both the certificate and private-key paths. Restart ChurchBoard after saving. The page will then load using the configured `http://` or `https://` address; desktop and tray launch actions follow the same scheme and port.

Ports range from 1–65535. Port 80 is accepted, but macOS and Linux normally restrict ports below 1024. A reverse proxy on 80/443 is preferable to running ChurchBoard with elevated privileges. Keep the service on a trusted network and never commit the TLS private key.

## 14. Open displays

Each dashboard has its own **Background color** picker at the top of the editor. The dashboard background, translucent liquid-glass widget surfaces, reflections, borders, and interface accents follow that color. Operational mic and SPL states remain green, yellow, or red so warnings are still immediately recognizable.

Use these default URLs locally:

```text
http://127.0.0.1:8040/display/main
http://127.0.0.1:8040/display/green-room
http://127.0.0.1:8040/display/audio
```

Substitute the ChurchBoard computer's IP address on other production-network devices. Use the fullscreen button in the top-right corner or the Raspberry Pi kiosk installer for a dedicated screen. The hamburger menu provides an **Edit** action beside each board. In the editor, **Open display** returns to that board in the same browser tab.

![WYSIWYG dashboard editor](screenshots/dashboard-editor.jpg)
