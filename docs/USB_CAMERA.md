# USB camera module

The USB Camera module displays a live feed captured by the computer running ChurchBoard. It works with standard USB Video Class (UVC) devices, including webcams and capture outputs such as Blackmagic Web Presenter. NDI software is not required.

## Setup

1. Connect the camera or capture device to the computer running ChurchBoard.
2. In **Setup & modules**, install **USB Camera**.
3. Edit a board and add the **USB camera** widget.
4. Open the widget settings and select **Find USB cameras**.
5. Approve camera access for the ChurchBoard app if macOS prompts you, choose the camera, and select **Fit entire frame** or **Fill widget**.
6. Save the board and open its display.

The selected device is stored per widget, so different boards can use different cameras. ChurchBoard requests video only; it does not capture camera audio or record the feed. The app serves the preview to every device viewing the dashboard, including phones and tablets.

## Browser and network requirements

Remote phones and tablets do not need camera permission because capture happens on the ChurchBoard host. Use ChurchBoard’s trusted HTTPS option when viewing dashboards across the production network.

If the selected device is disconnected, ChurchBoard displays a clear unavailable message and retries when the browser reports a camera change. If another application has exclusive control of the device, close that application or disable its camera preview.

## Blackmagic Web Presenter

Connect Web Presenter’s USB webcam output to the ChurchBoard display computer. It should appear in the camera list using the name supplied by macOS, Windows, or Linux. Choose that source in the widget; no Blackmagic Desktop Video or NDI integration is required for standard webcam output.
