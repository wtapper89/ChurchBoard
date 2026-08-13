# ProdMesh Remote RTA

ChurchBoard can self-host the [ProdMesh Remote RTA](https://github.com/jbeale/prodmesh-rta) engine and display its live level, signal state, program loudness metrics, and 31-band analyzer. The engine and its required runtime are included inside packaged ChurchBoard installers; users do not install ProdMesh separately.

1. In ChurchBoard, open **Setup & Modules**, add **ProdMesh Remote RTA**, and open its settings.
2. Keep **Inside ChurchBoard — no other installation** selected and enable the module.
3. Select **Open audio & calibration settings**. On first use, allow microphone access, select the measurement microphone or audio-interface channel, and calibrate it against a trusted reference.
4. Select **Save & test**. ChurchBoard starts and supervises the analyzer automatically whenever it runs.
5. Edit a ChurchBoard page, add **ProdMesh RTA**, and choose a meter, RTA, or combined display.

The widget uses ProdMesh's own live calibration ceiling and 80 dB RTA window, so its bands match the scale in the full ProdMesh program instead of appearing maxed out early.

Keep **Store per-service audio history in Producer** enabled to record one sample per second. ChurchBoard associates each sample with the selected Planning Center plan, the specific service time, and the active item or song. Administrators and editors can open **Producer → Audio history** to compare the minimum, average, maximum, and level graph for every item. These recordings remain on the ChurchBoard computer and can also be downloaded as a graph or CSV.

To use an analyzer running on another machine instead, choose **Another ProdMesh computer**, enable **Settings → API & Streaming…** in ProdMesh on that computer, and enter its address. The default API port is `8517`.

Remote mode requires both computers to reach each other on the production network. ProdMesh’s API is read-only. In embedded mode, ChurchBoard bundles the reviewed upstream engine and restarts it if it stops.

## Credit and license

ProdMesh Remote RTA was created by Justin Beale and is available under the MIT License. Copyright © 2026 Justin Beale. ChurchBoard retains the upstream license notice in every installer and uses the engine’s documented HTTP API; see the [ProdMesh source and license](https://github.com/jbeale/prodmesh-rta).
