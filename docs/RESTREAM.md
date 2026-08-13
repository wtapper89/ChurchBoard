# Restream setup

ChurchBoard uses Restream's OAuth 2.0 API to provide read-only broadcast monitoring. It can show a live or upcoming event, elapsed live time, an available viewer count, and the status of the Restream destinations connected to that event.

## 1. Create a Restream API application

1. Sign in to Restream and open the [Restream API Applications page](https://developers.restream.io/guide/getting-started).
2. Create an application with a recognizable name such as `ChurchBoard`.
3. Copy the application's **Client ID** and **Client Secret**. Treat the secret like a password.
4. Add this exact Redirect URI:

   ```text
   http://127.0.0.1:8040/api/integrations/restream/callback
   ```

5. Select only the read scopes required to list channels, read live/upcoming events, and read viewer analytics.

If ChurchBoard runs on a non-default port, replace `8040` in the Redirect URI with that port. The URI registered in Restream and the one used by ChurchBoard must match exactly.

## 2. Authorize ChurchBoard

1. Open **Setup & modules** at `http://127.0.0.1:8040/modules` on the ChurchBoard computer, then choose **Restream**.
2. Enable **Restream monitoring**.
3. Paste the Client ID and Client Secret.
4. Choose **Save & connect Restream**.
5. Sign in to the Restream account that owns the desired channels and approve the requested read access.
6. After Restream returns to ChurchBoard, choose **Test connection**.

ChurchBoard stores the OAuth access token, refresh token, and client secret in its local settings. They are removed from public settings API responses. Protect the ChurchBoard computer and do not commit its data directory to Git.

## 3. Add the dashboard widget

1. Edit a dashboard.
2. Add **Restream livestream**.
3. Resize and position the widget, then save the board.

The widget distinguishes live, upcoming/preparing, and offline states. During a live event it shows elapsed time and the most recent viewer value when Restream provides it. Destinations attached to the event are shown separately from inactive configured channels.

## Limitations and troubleshooting

- Restream's public API does not provide encoder bitrate or encoder-health measurements to this integration. ChurchBoard displays those fields as unavailable rather than inferring them.
- If authorization fails, confirm that the Redirect URI matches exactly, including `http`, host, port, and path.
- If channels appear but viewer data does not, confirm that the application has the required analytics scope and that the Restream plan/event exposes viewer analytics.
- Changing scopes can require reconnecting the Restream account.
- Regenerate the Restream Client Secret and reconnect ChurchBoard if the secret is exposed.
