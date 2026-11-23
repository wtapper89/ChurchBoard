# Audio consoles

Open Modules → Audio consoles and choose a console family, IP address, port,
and (for Allen & Heath) the MIDI channel configured on the desk. Existing
X32/M32 and WING settings and Console faders widgets remain compatible.

| Family | Transport / default port | Support |
| --- | --- | --- |
| X32 / M32 | OSC UDP 10023 | Existing faders, mutes, names and personal sends |
| WING | OSC UDP 2223 | Existing faders, mutes, names and personal sends |
| Avantis | MIDI TCP 51325 | Faders, mutes, names; values unknown until reported by the desk |
| dLive | MIDI TCP 51325 (MixRack), 51328 (Surface) | Faders, mutes, names |
| SQ-5 / SQ-6 / SQ-7 | MIDI TCP 51325 | Faders and mutes; the protocol supplies no names |
| Yamaha CL / QL / TF | RCP TCP 49280 | Read-only faders, mutes and names |

Avantis/dLive require a base MIDI channel from 1–12; SQ permits 1–16.
Set the same channel on the console and in ChurchBoard. Use Console faders
widgets for input channels, buses, aux masters, DCAs and main LR.
For Avantis/dLive, bus means mono aux and aux means stereo aux.
SQ bus/aux both refer to its Mix 1–12 masters.
Personal input-to-bus sends remain available only on X32/M32 and WING.
Unsupported strip types are disabled rather than sending a guessed command.
Yamaha controls are disabled in the dashboard and rejected by the server.

These new adapters are tested with protocol fixtures and simulated connections,
not physical consoles. Confirm behavior on your desk before service. Avantis
cannot supply an initial mute/fader snapshot over this protocol; unknown values
are shown as Unknown. Connections discard their readings after disconnect.

Protocol maps and SQ taper values were adapted from
[ProDeck](https://github.com/whiteoakmedia/prodeck), licensed under MIT.
See `licenses/PRODECK.txt`.
