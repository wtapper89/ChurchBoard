# Third-party notices

ChurchBoard depends on open-source software. Each dependency remains governed by its own license. Release builds run `packaging/collect_licenses.py` after installing dependencies and include the exact available license and notice files for the versions shipped in that build.

Core runtime components include:

| Component | License | Project |
| --- | --- | --- |
| FastAPI | MIT | https://github.com/fastapi/fastapi |
| Starlette | BSD-3-Clause | https://github.com/Kludex/starlette |
| Pydantic and pydantic-core | MIT | https://github.com/pydantic/pydantic |
| HTTPX and HTTPCore | BSD-3-Clause | https://github.com/encode/httpx |
| Uvicorn | BSD-3-Clause | https://github.com/Kludex/uvicorn |
| Pillow | MIT-CMU | https://python-pillow.github.io/ |
| OpenCV Python | Apache-2.0 | https://github.com/opencv/opencv-python |
| NumPy | BSD-3-Clause | https://numpy.org/ |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| AnyIO | MIT | https://github.com/agronholm/anyio |
| Click | BSD-3-Clause | https://github.com/pallets/click |
| h11 | MIT | https://github.com/python-hyper/h11 |
| httptools | MIT and bundled upstream licenses | https://github.com/MagicStack/httptools |
| watchfiles | MIT | https://github.com/samuelcolvin/watchfiles |
| websockets | BSD-3-Clause | https://github.com/python-websockets/websockets |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| PyYAML | MIT | https://pyyaml.org/ |
| LiveKit JavaScript client 2.21.0 | Apache-2.0 | https://github.com/livekit/client-sdk-js |
| LiveKit server 1.13.5 | Apache-2.0 | https://github.com/livekit/livekit |
| ProdMesh Remote RTA | MIT | https://github.com/jbeale/prodmesh-rta |
| Qt 6 runtime used by ProdMesh Remote RTA | Applicable Qt open-source licenses, including LGPL-3.0 | https://www.qt.io/licensing/open-source-lgpl-obligations |

Build and packaging tools include PyInstaller (GPL-2.0-or-later with its exception for distributing bundled applications), dmgbuild (MIT), and Inno Setup under its own license. These tools do not change ChurchBoard's MIT license. Exact notices collected from the Python build environment are placed in `legal/third-party` inside packaged builds; Windows and Linux installers also install them as readable files beside the application or under the platform documentation directory.

Micboard and NewsTalentMonitorPlus are credited inspirations, not bundled dependencies. The Behringer integration's OSC paths and fader behavior were implemented with reference to Bitfocus Companion's MIT-licensed X32 and WING modules; no Companion code is bundled. OBS Studio, Open Sound Meter, and Restream remain separately installed or hosted services accessed through their documented network interfaces. Release installers bundle the Apache-2.0-licensed LiveKit server as ChurchBoard's locally managed intercom engine. The vendored LiveKit browser client and server retain the Apache License text at `app/static/vendor/livekit-client.LICENSE`; LiveKit's upstream NOTICE identifies Copyright 2023 LiveKit, Inc.

Packaged ChurchBoard installers include the reviewed ProdMesh Remote RTA engine and its dynamically linked Qt runtime so embedded mode requires no separate product installation. ProdMesh Remote RTA is Copyright © 2026 Justin Beale and licensed under the MIT License. Its exact license and the applicable Qt license text are included in the packaged legal notices. Remote mode accesses a separately running copy through its documented read-only network API. The ShowXpress/TheLightingController integration was contributed by Caleb Hines of WorshipWarehouse and uses the controller's External Application protocol; ShowXpress and TheLightingController remain separately installed products.

The NDI runtime is not stored in this repository and is not part of a normal source build. Authorized release builders may optionally package an app-local runtime under the NDI SDK agreement. Those builds must include `Processing.NDI.Lib.Licenses.txt` beside the runtime and remain subject to NDI's SDK terms and third-party rights. See [ChurchBoard legal information](LEGAL.md).
