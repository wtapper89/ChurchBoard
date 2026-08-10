# Build from the project root with:
#   pyinstaller packaging/ChurchBoard.spec --noconfirm --clean
from pathlib import Path
import os
import shutil
import sys


project = Path.cwd()
if not (project / "run.py").is_file():
    project = Path(SPECPATH).resolve().parent

version_scope = {}
exec((project / "app" / "version.py").read_text(), version_scope)
app_version = version_scope["__version__"]
mac_icon = str(project / "packaging" / "assets" / "ChurchBoard.icns")
windows_icon = str(project / "packaging" / "assets" / "ChurchBoard.ico")
datas = [
    (str(project / "app" / "static"), "app/static"),
    (str(project / "LICENSE"), "."),
    (str(project / "LEGAL.md"), "."),
    (str(project / "THIRD_PARTY_NOTICES.md"), "."),
]
collected_licenses = project / "build" / "legal" / "third-party"
if collected_licenses.is_dir():
    datas.append((str(collected_licenses), "legal/third-party"))
tray_hidden_imports = []
binaries = []
livekit_server = Path(os.getenv("CHURCHBOARD_LIVEKIT_SERVER_PATH") or shutil.which("livekit-server") or "").expanduser()
if livekit_server.is_file():
    binaries.append((str(livekit_server), "livekit-server"))
if os.getenv("CHURCHBOARD_BUNDLE_NDI_RUNTIME", "").casefold() in {"1", "true", "yes", "on"}:
    ndi_directory = Path(os.environ.get("CHURCHBOARD_NDI_RUNTIME_DIR") or os.environ.get("NDI_RUNTIME_DIR_V6") or os.environ.get("NDI_RUNTIME_DIR_V5") or "").expanduser()
    ndi_names = {
        "darwin": ["libndi.dylib", "libndi.6.dylib"],
        "win32": ["Processing.NDI.Lib.x64.dll"],
        "linux": ["libndi.so.6", "libndi.so"],
    }.get(sys.platform, [])
    ndi_search_directories = [
        ndi_directory,
        ndi_directory / "lib" / "macOS",
        ndi_directory / "lib" / "x86_64-linux-gnu",
        ndi_directory / "Bin" / "x64",
        ndi_directory / "Lib" / "x64",
        ndi_directory / "Runtime",
    ]
    ndi_binary = next(
        (directory / name for directory in ndi_search_directories for name in ndi_names if (directory / name).is_file()),
        None,
    )
    ndi_license_names = ["Processing.NDI.Lib.Licenses.txt", "libndi_licenses.txt"]
    ndi_license_directories = [
        *(directory for directory in ndi_search_directories if directory),
        ndi_directory / "licenses",
        ndi_directory.parent,
    ]
    ndi_license = next(
        (directory / name for directory in ndi_license_directories for name in ndi_license_names if (directory / name).is_file()),
        None,
    )
    if not ndi_binary or not ndi_license:
        raise SystemExit("NDI bundling requires an NDI runtime binary and its supplied license notice")
    binaries.append((str(ndi_binary), "ndi-runtime"))
    datas.append((str(ndi_license), "ndi-runtime"))
if sys.platform == "darwin":
    tray_hidden_imports.extend(["app.tray", "PIL.Image", "pystray", "pystray._darwin"])
elif sys.platform == "win32":
    tray_hidden_imports.extend(["app.tray", "PIL.Image", "pystray", "pystray._win32"])

a = Analysis(
    [str(project / "run.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        *tray_hidden_imports,
    ],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ChurchBoard",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon=mac_icon,
    )
    collected = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        name="ChurchBoard",
    )
    app = BUNDLE(
        collected,
        name="ChurchBoard.app",
        bundle_identifier="org.churchboard.app",
        icon=mac_icon,
        info_plist={
            "CFBundleDisplayName": "ChurchBoard",
            "CFBundleName": "ChurchBoard",
            "CFBundleShortVersionString": app_version,
            "CFBundleVersion": app_version,
            "NSHighResolutionCapable": True,
            "NSLocalNetworkUsageDescription": "ChurchBoard discovers NDI sources and connects production devices and its hosted intercom on your local network.",
            "LSUIElement": False,
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="ChurchBoard",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=sys.platform != "win32",
        icon=windows_icon if sys.platform == "win32" else None,
    )
