from __future__ import annotations

import argparse
import csv
import json
import logging.handlers
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from app.config import load_config
import uvicorn

from app.main import app, producer_portal_app, run
from app.macos import install_and_start_launch_agent
from app.version import __version__


def desktop_log_config(data_file) -> dict:
    log_path = data_file.parent / "ChurchBoard.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_path),
                "maxBytes": 2_000_000,
                "backupCount": 2,
                "encoding": "utf-8",
                "formatter": "default",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["file"], "level": "INFO", "propagate": False},
        },
    }


def open_churchboard(page: str) -> None:
    config = load_config()
    path = "/" + str(page or "admin").lstrip("/")
    webbrowser.open(f"{config.scheme}://127.0.0.1:{config.port}{path}")


def _local_urlopen(url: str, timeout: float):
    context = ssl._create_unverified_context() if url.startswith("https://") else None
    return urllib.request.urlopen(url, timeout=timeout, context=context)


def running_churchboard_info() -> dict | None:
    config = load_config()
    try:
        with _local_urlopen(f"{config.scheme}://127.0.0.1:{config.port}/api/app-info", timeout=0.75) as response:
            if response.status != 200:
                return None
            result = json.loads(response.read().decode("utf-8"))
            return result if isinstance(result, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def compatible_desktop_is_running() -> bool:
    info = running_churchboard_info()
    return bool(
        info
        and str(info.get("version") or "") == __version__
        and info.get("desktop_tray") is True
        and (sys.platform != "darwin" or info.get("macos_launchservices") is True)
    )


def _run_hidden(command: list[str]) -> subprocess.CompletedProcess[str]:
    options: dict = {
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if sys.platform == "win32":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(command, **options)


def _listener_pids(port: int) -> set[int]:
    try:
        if sys.platform == "win32":
            result = _run_hidden(["netstat", "-ano", "-p", "tcp"])
            pids: set[int] = set()
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) < 4 or not fields[0].upper().startswith("TCP"):
                    continue
                local_address = fields[1].rsplit(":", 1)
                if len(local_address) == 2 and local_address[1] == str(port) and fields[-1].isdigit():
                    pids.add(int(fields[-1]))
            return pids
        if sys.platform == "darwin":
            result = _run_hidden([
                "/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t",
            ])
            return {int(value) for value in result.stdout.split() if value.isdigit()}
    except OSError:
        pass
    return set()


def _is_churchboard_process(pid: int) -> bool:
    try:
        if sys.platform == "win32":
            result = _run_hidden([
                "tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH",
            ])
            row = next(csv.reader(result.stdout.splitlines()), [])
            return bool(row and row[0].strip().lower() == "churchboard.exe")
        if sys.platform == "darwin":
            result = _run_hidden(["/bin/ps", "-p", str(pid), "-o", "command="])
            command = result.stdout.strip().lower()
            return "churchboard.app/contents/macos/churchboard" in command
    except OSError:
        pass
    return False


def stop_incompatible_churchboard() -> bool:
    """Stop an older packaged ChurchBoard that still owns the configured port."""
    config = load_config()
    stopped = False
    for pid in _listener_pids(config.port):
        if pid == os.getpid() or not _is_churchboard_process(pid):
            continue
        try:
            if sys.platform == "win32":
                _run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"])
            else:
                _run_hidden(["/bin/kill", "-TERM", str(pid)])
            stopped = True
        except OSError:
            continue
    if stopped:
        deadline = time.monotonic() + 5
        while running_churchboard_info() and time.monotonic() < deadline:
            time.sleep(0.1)
    return stopped


def open_churchboard_when_ready(page: str, timeout: float = 20.0) -> None:
    config = load_config()
    deadline = time.monotonic() + timeout
    health_url = f"{config.scheme}://127.0.0.1:{config.port}/api/app-info"
    while time.monotonic() < deadline:
        try:
            with _local_urlopen(health_url, timeout=0.75) as response:
                if response.status == 200:
                    open_churchboard(page)
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    open_churchboard(page)


def run_with_desktop_tray() -> None:
    from app.tray import DesktopTray

    config = load_config()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=config.host,
            port=config.port,
            reload=False,
            access_log=False,
            log_config=desktop_log_config(config.data_file),
            ssl_certfile=str(config.ssl_certfile) if config.ssl_certfile else None,
            ssl_keyfile=str(config.ssl_keyfile) if config.ssl_keyfile else None,
        )
    )
    tray = DesktopTray(config.port, config.data_file, lambda: setattr(server, "should_exit", True), config.scheme)
    app.state.desktop_quit = tray.quit
    app.state.desktop_tray = True
    server_thread = threading.Thread(target=server.run, name="ChurchBoard server", daemon=True)
    server_thread.start()
    portal_server = None
    portal_thread = None
    if config.producer_port_enabled and config.producer_port != config.port:
        portal_server = uvicorn.Server(
            uvicorn.Config(
                producer_portal_app,
                host=config.host,
                port=config.producer_port,
                reload=False,
                lifespan="off",
                access_log=False,
                log_config=desktop_log_config(config.data_file),
                ssl_certfile=str(config.ssl_certfile) if config.ssl_certfile else None,
                ssl_keyfile=str(config.ssl_keyfile) if config.ssl_keyfile else None,
            )
        )
        def start_portal_when_ready() -> None:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not hasattr(app.state, "runtime"):
                time.sleep(0.05)
            if hasattr(app.state, "runtime"):
                portal_server.run()
        portal_thread = threading.Thread(target=start_portal_when_ready, name="ChurchBoard producer portal", daemon=True)
        portal_thread.start()
    try:
        tray.run()
    finally:
        server.should_exit = True
        if portal_server is not None:
            portal_server.should_exit = True
        server_thread.join(timeout=10)
        if portal_thread is not None:
            portal_thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChurchBoard production dashboard")
    parser.add_argument(
        "--background",
        action="store_true",
        help="start the server without opening a browser (used by OS startup services)",
    )
    parser.add_argument(
        "--page",
        default="desktop",
        help="page to open when starting interactively (default: desktop)",
    )
    parser.add_argument("--no-tray", action="store_true", help="run without a menu-bar or system-tray icon")
    parser.add_argument(
        "--launchservices",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args()
    app.state.macos_launchservices = bool(arguments.launchservices)
    if compatible_desktop_is_running():
        if not arguments.background:
            open_churchboard(arguments.page)
        raise SystemExit(0)
    # A previous release may still own the port after an in-place update. Only
    # stop a listener after verifying that its executable is ChurchBoard.
    if running_churchboard_info():
        stop_incompatible_churchboard()
    # Launch installed Mac builds through LaunchServices. Starting the inner
    # executable directly from a LaunchAgent does not reliably create a Dock
    # application.
    if not arguments.background and install_and_start_launch_agent():
        open_churchboard_when_ready(arguments.page)
        raise SystemExit(0)
    if not arguments.background:
        threading.Timer(1.25, open_churchboard, args=(arguments.page,)).start()
    if sys.platform in {"darwin", "win32"} and not arguments.no_tray:
        run_with_desktop_tray()
    else:
        run()
