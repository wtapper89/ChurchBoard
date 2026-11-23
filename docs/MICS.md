# Microphones and IEM packs

Open **Setup & modules → Mics → Configure**. Choose **Add mic or IEM pack**.

For a networked receiver, choose its brand and enter the receiver IP address and channel. Enable monitoring for that brand.

For equipment without network monitoring, choose **Manual mic / IEM pack (no monitoring)**. Enter a name such as **IEM 3**, select its Planning Center position, and optionally upload a photo. No IP address, channel, or brand monitoring is needed. Click **Save module settings**.

Add or edit a **Scheduled Positions & Mics** widget on your board and select the relevant positions. Manual equipment appears alongside networked gear assigned to the same person, with its device name. Manual-only cards have a neutral border and an **Unmonitored** label; battery, RF, and audio readings are omitted. You can assign both a vocal microphone and an IEM pack to the same position.

If you do not use Planning Center, turn off **Use Planning Center for positions** in the Mics configuration. Configured devices appear directly on the board.

Manual assignments do not control audio or report whether a pack is powered on. For personal mix controls, see the [Producer guide](PRODUCER.md).

## Sennheiser EW G4

Choose **Sennheiser EW 300–500 G4** in the microphone device selector and
enter the EM receiver's IP address. Each receiver has one channel; ChurchBoard
uses channel 1 and UDP port 53212. Enable the Sennheiser integration toggle.
The dashboard receives battery steps (0/30/70/100), RF, audio, mute and warning
status using Sennheiser's Media Control Protocol, separately from EW-DX SSC.
A `?` battery response means the receiver has no battery telemetry.

Supported: EM 300–500 G4 with firmware 1.7.0 or newer. EM 100 G4 is not supported
by this Ethernet protocol. SR IEM G4 transmitter monitoring is not included in
this microphone receiver integration.

Reference: [Sennheiser TI 1254 v1.0](https://www.sennheiser.com/globalassets/digizuite/41944-en-ti_1254_metromediensteuerung_ewg4_en.pdf).
