# Presenter and console integration review

Reviewed 15 October 2026:

- [Slide-Desk](https://github.com/gavinpep98/Slide-Desk): bounded HTTP concurrency,
  active playlist identity, status subscriptions with polling fallback, and
  broader remote-control coverage. ChurchBoard already handles arrangements,
  thumbnails and explicit cue triggers. The changes here limit concurrent
  presentation-detail reads to four, isolate optional request failures from
  live slide status, and prevent a focused playlist from supplying an unrelated
  on-air Planning Center index. Status streaming and Slide-Desk's broader UI
  are not included. No GPL source was copied.
- [ProDeck](https://github.com/whiteoakmedia/prodeck): A&H console maps and
  dialects, SQ taper table, and read-only Yamaha RCP mapping were adapted into
  Python, with the MIT notice retained. See CONSOLE_INTEGRATIONS.md for scope.
- Issue 43: LIVE navigation skips headers but ChurchBoard counted them when
  computing the number of navigation calls. Navigation now counts playable
  rows and stops early if LIVE reaches the target. Headers cannot be fuzzy
  title matches. A regression crosses headers forward and backward and keeps
  polling to check that the result stays stable.
- Issue 42: EW 300–500 G4 receiver monitoring uses the documented UDP text
  protocol on 53212 rather than EW-DX JSON SSC on 45. See MICS.md.

The new hardware adapters have protocol-fixture and loopback transport tests.
They have not been validated against physical consoles or G4 receivers.
