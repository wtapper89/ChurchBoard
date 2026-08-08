# ProPresenter setup

ChurchBoard can read ProPresenter's current and next slides, slide images, notes, item title, part labels, colors, and slide number. Its ProPresenter Playlist widget also displays the focused playlist, including placeholders, every presentation, section markers, and all available slide thumbnails. On a trusted production network, ChurchBoard can trigger a playlist presentation or any slide within it. It can also match the active ProPresenter item to the same Planning Center plan and optionally use that match to advance Planning Center Services LIVE.

The most reliable workflow is to connect ProPresenter to Planning Center and open the service as a linked **Planning Center Service** playlist instead of building an unrelated local playlist.

## 1. Connect ProPresenter to Planning Center

In ProPresenter:

1. Open **ProPresenter > Settings** on macOS or **Edit > Preferences** on Windows.
2. Open **Integrations**.
3. Under **Planning Center**, choose **Connect** or **Login**.
4. Sign in to Planning Center, choose the correct organization, and approve access.
5. Return to ProPresenter and confirm that the Planning Center account/organization appears connected.

Renewed Vision recommends a Planning Center user with Editor or Administrator access to the plan. Use **Editor** for the relevant service types unless the operator genuinely needs administrator-only actions. See Renewed Vision's [Connect ProPresenter to Planning Center](https://support.renewedvision.com/hc/en-us/articles/1500003824022) guide.

Recommended Planning Center integration settings in ProPresenter include:

- **Automatically Check for Plan Updates** so plan changes are offered in ProPresenter;
- song matching by **Title** and **CCLI number** where your library data supports it;
- **Make Arrangements From Sequences** if your team uses Planning Center song sequences;
- automatic presentation/media upload or download only if your team understands the storage and media-sync implications.

Review these options in Renewed Vision's [Planning Center preferences](https://support.renewedvision.com/hc/en-us/articles/1500003710301) guide.

## 2. Add the service as a linked Planning Center playlist

1. In ProPresenter's Library/Playlist area, select the **+** button.
2. Choose **Planning Center Service**.
3. Browse to the correct folder, service type, and dated plan.
4. Refresh the list if a recently created or changed plan is missing.
5. Select the plan to add it as a Planning Center-linked playlist.
6. Resolve every unmatched item:
   - matched songs link to an existing ProPresenter presentation;
   - for an unmatched song or non-song item, drag the correct presentation or media into its drop zone;
   - keep the Planning Center item title visible even when the linked ProPresenter presentation has a different internal name.
7. When ProPresenter displays **Update Available**, review and apply the Planning Center changes.

Do not choose **Convert to Standard Playlist** for the service playlist. That removes its Planning Center link, stops plan updates, and cannot simply be converted back. Renewed Vision's illustrated instructions are in [Adding a Planning Center Plan to ProPresenter](https://support.renewedvision.com/hc/en-us/articles/360062310714-Adding-a-Planning-Center-Plan-to-ProPresenter).

Why this matters: a linked playlist preserves the Planning Center item order and title separately from the actual presentation title. ChurchBoard uses that context first, then normalized title matching. This is what allows a Planning Center item called `Message` to match while the linked presentation is called something like `John 1:1–3 (ASB)`.

## 3. Enable ProPresenter's Network API

ChurchBoard reads ProPresenter over the local network.

1. Open ProPresenter **Settings/Preferences**.
2. Select **Network**.
3. Enable **Network**.
4. Record the ProPresenter computer's local **IP address** and **Port** shown in this panel.
5. In ChurchBoard Setup, enable **ProPresenter**, enter that IP address and port, and save settings.
6. Open a ChurchBoard display and confirm that slide/item data updates when slides change.

Renewed Vision documents the Network controls in [ProPresenter Preferences](https://learn.renewedvision.com/propresenter/preferences) and its API in [Other Features](https://learn.renewedvision.com/propresenter/other-features).

For a dependable production connection:

- put ChurchBoard and ProPresenter on the same trusted production LAN;
- give the ProPresenter computer a DHCP reservation or stable IP address;
- allow ProPresenter and its selected port through the computer's firewall on private/local networks;
- use wired networking when practical;
- do not expose the ProPresenter API port directly to the public internet.

The address entered in ChurchBoard must be the ProPresenter computer's LAN address, not `127.0.0.1`, unless ChurchBoard and ProPresenter run on the same computer.

## 4. Configure ChurchBoard ProPresenter widgets

In ChurchBoard's dashboard editor, select a **ProPresenter** widget and choose:

- **Text** for clean slide text or **Slide image** for ProPresenter's slide thumbnail;
- current slide, next slide, both, or neither;
- `Slide x of y` on or off;
- item/playlist title, slide notes, and current/next part labels.

Part labels use their ProPresenter colors. If parts do not change with the slide, confirm the cues/groups in the presentation are named and colored in ProPresenter.

For the **ProPresenter playlist** widget, select the focused playlist in ProPresenter. ChurchBoard renders its placeholders and presentations in playlist order and shows every slide in each presentation continuously with its section marker. Choose compact, comfortable, or large density in the widget settings. **Follow and auto-scroll** keeps the active slide in view. ChurchBoard updates the active marker in place and caches stable playlist details and thumbnails, avoiding full list rebuilds and image flashes on every poll.

On the live board itself, turn on **Slide controls** to make presentation headings and slide thumbnails clickable. Keep it off on public or read-only displays. ChurchBoard uses the live active presentation's current arrangement, rather than a stale library copy, when building the active slide sequence.

Turn on **Arrow keys** in the live Playlist widget when an operator should drive ProPresenter from that board. **Slide controls** must also be on. Left Arrow or Up Arrow moves back; Right Arrow, Down Arrow, or Space advances. This choice is remembered by that browser and board. The command uses ProPresenter's global next/previous trigger, so it continues into the adjacent playlist item. Keyboard commands are ignored while the operator is typing in a field, using a button or menu, or holding a keyboard modifier.

For a simpler operator surface, add the separate **ProPresenter controls** widget. It provides large Previous slide, Next slide, Previous item, and Next item buttons. Item navigation skips Planning Center headers and unresolved placeholders and triggers the neighboring playable playlist item.

The focused playlist is used for the playlist browser, while the active playlist item is used for Planning Center Services LIVE matching. This distinction lets an operator inspect another presentation without making ChurchBoard leave the item that is actually on air. For Planning Center-synced content, the active playlist position remains authoritative when the local presentation name differs from the Planning Center item title—for example, a scripture presentation named `John 1:1-3 (ASB)` linked to the plan item `Message`.

ChurchBoard also publishes the active presentation as a slide-grid feed. Every
cue includes its number, text, notes, ProPresenter part/color, active state,
and a proxied thumbnail URL. This lets a Service Producer view present a
section-aware grid beside the order of service without exposing the
ProPresenter computer directly to browsers.

## Remote slide triggering

Remote triggering is controlled independently for each ProPresenter Playlist
widget. On the live board, enable **Slide controls** only for displays used by
trusted operators on the production network. ChurchBoard validates the board
and widget for every trigger request; viewing another dashboard does not grant
it control.

When the active slide contains a ProPresenter timer element, ChurchBoard replaces its design-time placeholder with the currently running ProPresenter timer and composites that changing value over the otherwise static slide thumbnail. Video remaining time is kept separate and is never shown as a slide timer. For foreground video cues, ChurchBoard displays playing state, elapsed time, duration, and progress; looping motion backgrounds behind lyrics do not receive that overlay. ProPresenter's HTTP API exposes static cue/media thumbnails and transport information, but not live rendered audience-screen frames, so moving video cannot be reproduced from that API alone. A true moving preview would require a separate browser-compatible output stream from ProPresenter or a capture application such as OBS.

Add a **ProPresenter timers** widget from the dashboard editor to show every configured ProPresenter timer that the Network API returns. Each card shows its timer name, current value, and state; the widget is read-only and updates from ProPresenter without controlling timer playback.

## 5. Let ProPresenter drive Planning Center Services LIVE

ProPresenter's built-in Planning Center LIVE panel and its slide playback are separate controls; advancing a slide does not itself advance LIVE. Renewed Vision explains that behavior in [Planning Center Live and Stage Timers](https://support.renewedvision.com/hc/en-us/articles/1500006143281-Planning-Center-Live-and-Planning-Center-Live-Stage-Timers). ChurchBoard's optional LIVE automation provides the linkage.

Before enabling it:

1. Connect ChurchBoard and ProPresenter to the same Planning Center organization.
2. Select the same dated Planning Center plan in both applications.
3. Use the linked Planning Center Service playlist in ProPresenter.
4. Make sure the ChurchBoard PAT user has **Editor** access to control LIVE. Taking control from another controller can require **Administrator** access.
5. Resolve all ProPresenter playlist items to the correct Planning Center items.

Then in ChurchBoard Setup:

1. Enable **Let ProPresenter drive Planning Center Services LIVE**.
2. Enable **Automatically take control when needed** only if ChurchBoard should claim control.
3. Leave **Prefer Planning Center song items for title matching** enabled for normal services.
4. Select exact or smart fallback matching.
5. Set the stability delay: the presentation must remain active for this long before ChurchBoard advances LIVE.
6. Save settings and test with a rehearsal or test plan before using it in a live service.

ChurchBoard first follows the Planning Center-linked playlist order/title. If that context is unavailable, it uses normalized matching. The stability delay prevents brief selections or rapid operator navigation from moving LIVE unexpectedly.

Only one system or operator should be responsible for controlling Services LIVE during a service. Agree on that responsibility before enabling automatic take-control.

## 6. Recommended weekly workflow

1. Finalize the Planning Center plan, plan times, item durations, teams, positions, and item leaders.
2. In ProPresenter, open or add that exact plan as a Planning Center Service playlist.
3. Apply any available plan update.
4. Resolve every unmatched song, message, video, announcement, or other plan item.
5. Confirm that the Planning Center item title is still linked even if the presentation title differs.
6. Verify ChurchBoard has selected the same plan; use its hamburger menu to select it manually if needed.
7. Test current/next slides, part labels, slide notes, and `Slide x of y`.
8. If LIVE automation is enabled, test item transitions and the stability delay before the service.
9. Keep the linked Planning Center playlist selected while operating the service.

## Troubleshooting

**ChurchBoard cannot connect to ProPresenter**

- Confirm ProPresenter's Network option is enabled.
- Recheck the IP address and port shown in ProPresenter.
- Confirm both computers are on the same network and the firewall permits local access.
- If the ProPresenter computer's address changed, create a DHCP reservation and update ChurchBoard.

**Slides update but the wrong Planning Center item is active**

- Confirm ProPresenter is using the linked Planning Center Service playlist, not a copied standard playlist.
- Apply pending plan updates and resolve unmatched items.
- Confirm ChurchBoard and ProPresenter selected the same dated plan and service type.
- Keep meaningful Planning Center item titles such as `Message`; do not replace them with only a Scripture or file name.

**A different presentation title is shown**

- In a linked Planning Center playlist, ProPresenter may display both the Planning Center item title and the linked presentation title. That is expected.
- ChurchBoard prefers the Planning Center context when available and falls back to normalized matching.

**Services LIVE does not advance**

- Confirm LIVE automation is enabled and the presentation remains active longer than the configured stability delay.
- Verify the ChurchBoard PAT user has Editor access to that service type.
- Check whether another operator controls LIVE; automatic take-control may be disabled or the user may lack permission.
- Test with the exact same Planning Center plan in ChurchBoard and ProPresenter.
