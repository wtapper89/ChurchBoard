from __future__ import annotations

import ctypes
import io
import os
import platform
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image


class _Source(ctypes.Structure):
    _fields_ = [("p_ndi_name", ctypes.c_char_p), ("p_url_address", ctypes.c_char_p)]


class _FindCreate(ctypes.Structure):
    _fields_ = [("show_local_sources", ctypes.c_bool), ("p_groups", ctypes.c_char_p), ("p_extra_ips", ctypes.c_char_p)]


class _RecvCreate(ctypes.Structure):
    _fields_ = [
        ("source_to_connect", _Source),
        ("color_format", ctypes.c_int),
        ("bandwidth", ctypes.c_int),
        ("allow_video_fields", ctypes.c_bool),
        ("p_ndi_recv_name", ctypes.c_char_p),
    ]


class _VideoFrame(ctypes.Structure):
    _fields_ = [
        ("xres", ctypes.c_int), ("yres", ctypes.c_int), ("FourCC", ctypes.c_uint32),
        ("frame_rate_N", ctypes.c_int), ("frame_rate_D", ctypes.c_int),
        ("picture_aspect_ratio", ctypes.c_float), ("frame_format_type", ctypes.c_int),
        ("timecode", ctypes.c_int64), ("p_data", ctypes.POINTER(ctypes.c_uint8)),
        ("line_stride_in_bytes", ctypes.c_int), ("p_metadata", ctypes.c_char_p),
        ("timestamp", ctypes.c_int64),
    ]


def _fourcc(value: str) -> int:
    return int.from_bytes(value.encode("ascii"), "little")


class NDIRuntime:
    """Optional dynamic loader for the NDI® runtime; no NDI Tools dependency."""

    def __init__(self):
        self.library: Any = None
        self.error = "NDI runtime is not configured"
        self._path = ""
        self.runtime_path = ""
        self.searched_paths: list[str] = []
        self._receivers: dict[str, Any] = {}
        self._source_cache: dict[str, dict[str, str]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _candidates(directory: str = "") -> list[Path]:
        names = {
            "Windows": ["Processing.NDI.Lib.x64.dll", "Processing.NDI.Lib.x86.dll"],
            "Darwin": ["libndi.dylib", "libndi.6.dylib"],
            "Linux": ["libndi.so.6", "libndi.so.5", "libndi.so"],
        }.get(platform.system(), ["libndi.so"])
        configured_roots = [
            directory,
            os.getenv("CHURCHBOARD_NDI_RUNTIME_DIR", ""),
            os.getenv("NDI_RUNTIME_DIR_V6", ""),
            os.getenv("NDI_RUNTIME_DIR_V5", ""),
        ]
        system = platform.system()
        if system == "Darwin":
            configured_roots.extend([
                "/Library/NDI SDK for Apple",
                "/Library/NDI",
                "/Applications/NDI",
            ])
        elif system == "Windows":
            program_files = [os.getenv("PROGRAMFILES", ""), os.getenv("PROGRAMFILES(X86)", "")]
            for root in program_files:
                if root:
                    configured_roots.extend([
                        str(Path(root) / "NDI" / "NDI 6 SDK"),
                        str(Path(root) / "NDI" / "NDI 6 Runtime" / "v6"),
                        str(Path(root) / "NewTek" / "NDI 5 Runtime" / "v5"),
                    ])
        else:
            configured_roots.extend(["/opt/ndi", "/usr/local/lib", "/usr/lib"])
        configured_roots.append(str(Path(__file__).resolve().parents[2] / "ndi-runtime"))

        suffixes = {
            "Darwin": ["", "lib/macOS", "lib", "bin/macOS", "redist"],
            "Windows": ["", "Bin/x64", "bin/x64", "Lib/x64", "lib/x64", "Redist", "redist"],
            "Linux": ["", "lib/x86_64-linux-gnu", "lib/aarch64-rpi4-linux-gnueabi", "lib", "bin/x86_64-linux-gnu"],
        }.get(system, [""])
        candidates: list[Path] = []
        seen: set[str] = set()
        for raw_root in configured_roots:
            if not raw_root:
                continue
            root = Path(raw_root).expanduser()
            possible = [root] if root.suffix.lower() in {".dll", ".dylib", ".so"} else [root / suffix / name for suffix in suffixes for name in names]
            for path in possible:
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    candidates.append(path)
        return candidates

    def configure(self, settings: dict[str, Any]) -> None:
        directory = str(settings.get("runtime_directory") or "")
        if self.library is not None and directory == self._path:
            return
        with self._lock:
            self._destroy_receivers()
            self.library = None
            self._path = directory
            candidates = self._candidates(directory)
            self.searched_paths = [str(path) for path in candidates]
            self.runtime_path = ""
            chosen = next((path for path in candidates if path.is_file()), None)
            if chosen is None:
                self.error = "NDI runtime not found. Install the NDI SDK, then use Auto-detect in Setup."
                return
            try:
                lib = ctypes.CDLL(str(chosen))
                lib.NDIlib_initialize.restype = ctypes.c_bool
                if not lib.NDIlib_initialize():
                    raise RuntimeError("NDIlib_initialize returned false")
                lib.NDIlib_find_create_v2.argtypes = [ctypes.POINTER(_FindCreate)]
                lib.NDIlib_find_create_v2.restype = ctypes.c_void_p
                lib.NDIlib_find_wait_for_sources.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                lib.NDIlib_find_wait_for_sources.restype = ctypes.c_bool
                lib.NDIlib_find_get_current_sources.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
                lib.NDIlib_find_get_current_sources.restype = ctypes.POINTER(_Source)
                lib.NDIlib_find_destroy.argtypes = [ctypes.c_void_p]
                lib.NDIlib_recv_create_v3.argtypes = [ctypes.POINTER(_RecvCreate)]
                lib.NDIlib_recv_create_v3.restype = ctypes.c_void_p
                lib.NDIlib_recv_connect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Source)]
                lib.NDIlib_recv_capture_v2.argtypes = [ctypes.c_void_p, ctypes.POINTER(_VideoFrame), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
                lib.NDIlib_recv_capture_v2.restype = ctypes.c_int
                lib.NDIlib_recv_free_video_v2.argtypes = [ctypes.c_void_p, ctypes.POINTER(_VideoFrame)]
                lib.NDIlib_recv_destroy.argtypes = [ctypes.c_void_p]
                self.library = lib
                self.runtime_path = str(chosen)
                self.error = ""
            except Exception as exc:
                self.error = f"Could not load NDI runtime: {exc}"

    def _destroy_receivers(self) -> None:
        if self.library is not None:
            for receiver in self._receivers.values():
                try:
                    self.library.NDIlib_recv_destroy(receiver)
                except Exception:
                    pass
        self._receivers.clear()
        self._source_cache.clear()

    def status(self) -> dict[str, Any]:
        return {
            "available": self.library is not None,
            "runtime_path": self.runtime_path,
            "error": self.error,
            "searched_paths": self.searched_paths,
        }

    def close(self) -> None:
        with self._lock:
            self._destroy_receivers()

    def sources(self, wait_ms: int = 500) -> list[dict[str, str]]:
        if self.library is None:
            return []
        with self._lock:
            finder = self.library.NDIlib_find_create_v2(ctypes.byref(_FindCreate(True, None, None)))
            if not finder:
                return []
            try:
                self.library.NDIlib_find_wait_for_sources(finder, max(0, int(wait_ms)))
                count = ctypes.c_uint32(0)
                rows = self.library.NDIlib_find_get_current_sources(finder, ctypes.byref(count))
                result = [
                    {
                        "name": (rows[index].p_ndi_name or b"").decode("utf-8", "replace"),
                        "url": (rows[index].p_url_address or b"").decode("utf-8", "replace"),
                    }
                    for index in range(count.value)
                ]
                self._source_cache.update({row["name"]: row for row in result if row["name"]})
                return result
            finally:
                self.library.NDIlib_find_destroy(finder)

    def _receiver(self, source_name: str) -> Any:
        existing = self._receivers.get(source_name)
        if existing:
            return existing
        source = self._source_cache.get(source_name)
        if source is None:
            source = next((row for row in self.sources(900) if row["name"] == source_name), None)
        if not source:
            raise RuntimeError("The selected NDI source is not currently available")
        native_source = _Source(source["name"].encode(), source["url"].encode() or None)
        # RGBX/RGBA gives Pillow a predictable four-byte pixel layout while
        # still allowing the NDI runtime to decode High Bandwidth and HX.
        receiver = self.library.NDIlib_recv_create_v3(ctypes.byref(_RecvCreate(native_source, 2, 100, False, b"ChurchBoard Preview")))
        if not receiver:
            raise RuntimeError("Could not create the NDI preview receiver")
        self._receivers[source_name] = receiver
        return receiver

    def snapshot(self, source_name: str, timeout_ms: int = 3500) -> bytes:
        if self.library is None:
            raise RuntimeError(self.error)
        with self._lock:
            receiver = self._receiver(source_name)
            deadline = time.monotonic() + max(0.5, int(timeout_ms) / 1000)
            last_frame_type = 0
            while time.monotonic() < deadline:
                frame = _VideoFrame()
                wait_ms = max(1, min(500, int((deadline - time.monotonic()) * 1000)))
                frame_type = int(self.library.NDIlib_recv_capture_v2(receiver, ctypes.byref(frame), None, None, wait_ms))
                last_frame_type = frame_type
                if frame_type == 4:
                    break
                if frame_type != 1:
                    # NDI can report status/source changes before the first
                    # video frame. Keep waiting rather than displaying a
                    # broken image after that normal receiver handshake.
                    continue
                try:
                    if not frame.p_data or frame.xres <= 0 or frame.yres <= 0:
                        raise RuntimeError("NDI returned an empty video frame")
                    stride = frame.line_stride_in_bytes or frame.xres * 4
                    raw = ctypes.string_at(frame.p_data, stride * frame.yres)
                    modes = {
                        _fourcc("BGRA"): ("RGBA", "BGRA"), _fourcc("BGRX"): ("RGB", "BGRX"),
                        _fourcc("RGBA"): ("RGBA", "RGBA"), _fourcc("RGBX"): ("RGB", "RGBX"),
                    }
                    if frame.FourCC not in modes:
                        label = int(frame.FourCC).to_bytes(4, "little").decode("ascii", "replace")
                        raise RuntimeError(f"Unsupported NDI pixel format {label}")
                    mode, decoder = modes[frame.FourCC]
                    image = Image.frombuffer(mode, (frame.xres, frame.yres), raw, "raw", decoder, stride, 1).convert("RGB")
                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=84, optimize=True)
                    return output.getvalue()
                finally:
                    self.library.NDIlib_recv_free_video_v2(receiver, ctypes.byref(frame))
            self.library.NDIlib_recv_destroy(receiver)
            self._receivers.pop(source_name, None)
            if last_frame_type == 4:
                raise RuntimeError("The NDI receiver reported an error while opening this source")
            raise RuntimeError("The NDI source was found, but no video frame arrived before the timeout")
