# ProdMesh Remote RTA

ChurchBoard can display the live level, signal state, program loudness metrics, and 31-band analyzer from [ProdMesh Remote RTA](https://github.com/jbeale/prodmesh-rta).

1. Install and open ProdMesh Remote RTA on the measurement computer.
2. In ProdMesh, choose **Settings → API & Streaming…** and enable the API. Its default port is `8517`.
3. In ChurchBoard, open **Setup & Modules**, add **ProdMesh Remote RTA**, and open its settings.
4. Enter the IP address shown by ProdMesh and its API port, save, then select **Save & test connection**.
5. Edit a ChurchBoard page, add **ProdMesh RTA**, and choose a meter, RTA, or combined display.

Both computers must be able to reach each other on the production network. ProdMesh’s API is read-only and ChurchBoard does not bundle or modify ProdMesh.

## Credit and license

ProdMesh Remote RTA was created by Justin Beale and is available under the MIT License. Copyright © 2026 Justin Beale. ChurchBoard’s integration uses its documented HTTP API; see the [ProdMesh source and license](https://github.com/jbeale/prodmesh-rta).
